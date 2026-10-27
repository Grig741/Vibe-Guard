"""Fetch a public website the way a browser would and pull out what it ships.

VibeGuard's URL mode starts here: download the page, its JS bundles (and the
chunks they import), then hand the text to the detectors (Firebase / Supabase
config, leaked secrets) and the passive checks (headers, exposed files).

Every outbound request goes through `safe_get`, which refuses private,
loopback and link-local addresses on every redirect hop — the scanner runs on
a server, so it must never be usable to reach that server's own network.
"""
import asyncio
import ipaddress
import os
import re
import socket
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import httpx

MAX_HTML = 1_500_000          # bytes kept from the HTML page
MAX_JS = 4_000_000            # bytes kept per script
MAX_SCRIPTS = 40              # scripts fetched per scan (entry + chunks)
MAX_REDIRECTS = 5

# For local testing only: lets the scanner reach 127.0.0.1 / LAN targets.
ALLOW_PRIVATE = os.getenv("ALLOW_PRIVATE_TARGETS", "").lower() in ("1", "true", "yes")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36 VibeGuard/2.0")


class BlockedTarget(Exception):
    """The URL points somewhere the scanner is not allowed to go."""


def normalize_url(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        raise BlockedTarget("Empty URL")
    if "://" not in raw:
        raw = "https://" + raw
    p = urlparse(raw)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise BlockedTarget("Only http(s) URLs can be scanned")
    return raw


async def _assert_public(host: str) -> None:
    if ALLOW_PRIVATE:
        return
    host = host.strip("[]").lower()
    if host in ("localhost",) or host.endswith((".localhost", ".local", ".internal")):
        raise BlockedTarget("Private hosts can't be scanned")
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise BlockedTarget(f"Can't resolve {host}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not ip.is_global:
            raise BlockedTarget("Private / internal addresses can't be scanned")


@dataclass
class Fetched:
    url: str
    status: int
    headers: httpx.Headers
    text: str
    content_type: str


async def safe_get(client: httpx.AsyncClient, url: str, *, limit: int = MAX_JS,
                   headers: dict | None = None) -> Fetched:
    """GET with manual, re-validated redirects and a body size cap."""
    for _ in range(MAX_REDIRECTS + 1):
        host = urlparse(url).hostname or ""
        await _assert_public(host)
        async with client.stream("GET", url, headers=headers) as resp:
            if resp.status_code in (301, 302, 303, 307, 308) and "location" in resp.headers:
                url = urljoin(url, resp.headers["location"])
                continue
            buf = bytearray()
            async for chunk in resp.aiter_bytes():
                buf.extend(chunk)
                if len(buf) >= limit:
                    break
            text = bytes(buf[:limit]).decode(resp.encoding or "utf-8", errors="replace")
            return Fetched(url=str(resp.url), status=resp.status_code, headers=resp.headers,
                           text=text, content_type=resp.headers.get("content-type", "").lower())
    raise BlockedTarget("Too many redirects")


def make_client(timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"User-Agent": UA, "Accept": "*/*"},
        timeout=httpx.Timeout(timeout),
        limits=httpx.Limits(max_connections=12),
        follow_redirects=False,
    )


# ---- Crawl -------------------------------------------------------------------

_SCRIPT_SRC = re.compile(r"""<script\b[^>]*?\bsrc\s*=\s*["']([^"']+)["']""", re.I)
_PRELOAD = re.compile(
    r"""<link\b[^>]*?\brel\s*=\s*["'](?:modulepreload|preload)["'][^>]*?\bhref\s*=\s*["']([^"']+\.m?js[^"']*)["']""",
    re.I)
_PRELOAD2 = re.compile(
    r"""<link\b[^>]*?\bhref\s*=\s*["']([^"']+\.m?js[^"']*)["'][^>]*?\brel\s*=\s*["'](?:modulepreload|preload)["']""",
    re.I)
_INLINE = re.compile(r"<script\b(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.I | re.S)
# Chunks referenced from inside a bundle (Vite, Next.js, CRA, Nuxt, Astro…).
_CHUNK = re.compile(
    r"""["'`]((?:\.{0,2}/)?(?:assets|_next/static|static/js|_nuxt|_astro|js|build|dist|chunks)/[\w\-./@~]+?\.m?js)["'`]""")


@dataclass
class Site:
    url: str                         # final URL after redirects
    status: int
    headers: httpx.Headers
    html: str
    scripts: dict = field(default_factory=dict)   # url -> text
    inline: str = ""

    @property
    def origin(self) -> str:
        p = urlparse(self.url)
        return f"{p.scheme}://{p.netloc}"

    def all_text(self) -> list[tuple[str, str]]:
        """(where, text) pairs for the detectors."""
        out = [(self.url, self.html)]
        if self.inline:
            out.append((self.url + " (inline script)", self.inline))
        out.extend(self.scripts.items())
        return out


async def crawl(client: httpx.AsyncClient, url: str) -> Site:
    page = await safe_get(client, url, limit=MAX_HTML,
                          headers={"Accept": "text/html,application/xhtml+xml,*/*"})
    html = page.text
    site = Site(url=page.url, status=page.status, headers=page.headers, html=html)
    site.inline = "\n".join(m.group(1) for m in _INLINE.finditer(html))[:MAX_HTML]

    queue: list[str] = []
    for rx in (_SCRIPT_SRC, _PRELOAD, _PRELOAD2):
        for m in rx.finditer(html):
            queue.append(urljoin(page.url, m.group(1).strip()))

    seen: set[str] = set()

    async def grab(u: str) -> None:
        try:
            f = await safe_get(client, u)
        except Exception:  # noqa: BLE001
            return
        if f.status == 200 and "html" not in f.content_type:
            site.scripts[u] = f.text

    # Two rounds: entry scripts, then the chunks they reference.
    for _round in range(2):
        batch = []
        for u in queue:
            if u in seen or len(seen) >= MAX_SCRIPTS:
                continue
            if urlparse(u).scheme not in ("http", "https"):
                continue
            seen.add(u)
            batch.append(u)
        queue = []
        await asyncio.gather(*(grab(u) for u in batch))
        if _round == 0:
            origin = site.origin
            for src_url, text in list(site.scripts.items()):
                for m in _CHUNK.finditer(text):
                    ref = m.group(1)
                    # Vite chunk paths are relative to the bundle, others to the site root.
                    base = src_url if ref.startswith(".") else origin + "/"
                    cand = urljoin(base, ref)
                    if urlparse(cand).netloc == urlparse(origin).netloc:
                        queue.append(cand)
    return site


def detect_stack(site: Site) -> list[str]:
    blob = site.html[:200_000] + "\n" + "\n".join(t[:200_000] for t in site.scripts.values())
    h = {k.lower(): v.lower() for k, v in site.headers.items()}
    tags: list[str] = []

    def add(name: str, cond: bool) -> None:
        if cond and name not in tags:
            tags.append(name)

    add("Next.js", "/_next/" in blob or "__NEXT_DATA__" in blob)
    add("Nuxt", "/_nuxt/" in blob or "__NUXT__" in blob)
    add("Vite", "/assets/index-" in blob or "vite" in blob[:5000].lower())
    add("React", "react-dom" in blob or "__reactFiber" in blob or "createRoot" in blob)
    add("Vue", "__vue__" in blob or "createApp(" in blob)
    add("Lovable", "lovable" in blob.lower() or "gptengineer" in blob.lower())
    add("Bolt", "bolt.new" in blob.lower() or "stackblitz" in blob.lower())
    add("Firebase", "firebaseapp.com" in blob or "firestore.googleapis.com" in blob)
    add("Supabase", ".supabase.co" in blob)
    add("Vercel", "x-vercel-id" in h or "vercel" in h.get("server", ""))
    add("Netlify", "netlify" in h.get("server", "") or "x-nf-request-id" in h)
    add("Cloudflare", h.get("server", "") == "cloudflare")
    return tags
