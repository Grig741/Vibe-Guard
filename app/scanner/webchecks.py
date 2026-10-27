"""Passive checks on a fetched website: security headers and files that should
never be public (.env, .git, source maps, backups).

Only GETs over the SSRF-safe client; never modifies anything.
"""
import httpx

from .web import Site, safe_get

# Files that, if served, leak secrets or source.
EXPOSED_PATHS = [
    (".env", "critical", "Environment file with secrets (API keys, DB passwords) is downloadable."),
    (".env.local", "critical", "Local environment file with secrets is downloadable."),
    (".env.production", "critical", "Production environment file with secrets is downloadable."),
    (".git/config", "high", "The .git directory is exposed — the entire source history can be downloaded."),
    ("config.json", "medium", "A config.json is publicly served — check it for secrets."),
    ("firebase-debug.log", "low", "Firebase debug log is public."),
    ("backup.sql", "critical", "A database dump is downloadable."),
    ("db.sqlite", "critical", "A SQLite database file is downloadable."),
]

SECURITY_HEADERS = {
    "content-security-policy": ("medium", "No Content-Security-Policy — the main defense against XSS is missing."),
    "strict-transport-security": ("low", "No HSTS header — browsers may connect over plain HTTP."),
    "x-content-type-options": ("low", "No X-Content-Type-Options: nosniff — browsers may MIME-sniff responses."),
    "x-frame-options": ("low", "No X-Frame-Options / frame-ancestors — the site can be framed for clickjacking."),
}


def _r(check_id: str, status: str, evidence: str = "") -> dict:
    return {"check_id": check_id, "status": status, "evidence": evidence}


def check_headers(site: Site) -> list[dict]:
    h = {k.lower(): v for k, v in site.headers.items()}
    missing = []
    for name, (sev, _msg) in SECURITY_HEADERS.items():
        if name == "x-frame-options":
            csp = h.get("content-security-policy", "")
            if "frame-ancestors" in csp:
                continue
        if name not in h:
            missing.append(name)
    if missing:
        pretty = ", ".join(n.replace("-", " ").title() for n in missing)
        return [_r("web_security_headers", "vulnerable",
                   f"Missing security headers: {pretty}.")]
    return [_r("web_security_headers", "ok", "Key security headers are present.")]


async def check_exposed_files(client: httpx.AsyncClient, site: Site) -> list[dict]:
    origin = site.origin
    found: list[str] = []
    checked = False
    for path, _sev, _msg in EXPOSED_PATHS:
        url = f"{origin}/{path}"
        try:
            f = await safe_get(client, url, limit=4096)
        except Exception:  # noqa: BLE001
            continue
        checked = True
        if f.status != 200:
            continue
        ct = f.content_type
        body = f.text[:2000]
        # A SPA returns its index.html for everything with 200 — don't flag that.
        if "html" in ct and ("<!doctype html" in body.lower() or "<html" in body.lower()):
            continue
        if path == ".git/config" and "[core]" not in body:
            continue
        if path == ".env" and "=" not in body:
            continue
        found.append(path)

    if found:
        return [_r("web_exposed_files", "vulnerable",
                   f"Publicly downloadable: {', '.join(found)}.")]
    if checked:
        return [_r("web_exposed_files", "ok", "No common secret files are publicly served.")]
    return [_r("web_exposed_files", "skipped", "Could not probe for exposed files.")]


def check_source_maps(site: Site) -> list[dict]:
    """A production bundle shipping //# sourceMappingURL hands out readable source."""
    for url, text in site.scripts.items():
        tail = text[-2000:]
        if "sourceMappingURL=" in tail and ".map" in tail:
            return [_r("web_source_maps", "vulnerable",
                       "JavaScript bundles ship source maps (.map) — your original, unminified "
                       "source code (and any secrets in it) can be reconstructed.")]
    return [_r("web_source_maps", "ok", "No source maps are referenced from the bundles.")]
