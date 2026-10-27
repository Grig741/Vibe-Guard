"""Scan orchestrator.

Three kinds of target, one result shape:
  * firebase — probe a pasted firebaseConfig (the original behaviour).
  * supabase — probe a Supabase project from its URL + anon key.
  * url      — fetch a live site, discover its Firebase/Supabase config and any
               leaked secrets in the bundle, then run every probe that applies
               plus passive website checks.

Every network call is read-only or self-cleaning, and URL scanning goes through
the SSRF-safe client in web.py.
"""
import time

import httpx

from ..config import SCAN_TIMEOUT
from ..schemas import FirebaseConfig
from . import checks, supabase as sb_checks, webchecks
from .detect import (
    FirebaseFound,
    SupabaseFound,
    find_firebase,
    find_secrets,
    find_supabase,
    merge_supabase,
)
from .rules import CHECKS, PASS_TITLES, SECRET_REMEDIATION, SEVERITY_ORDER, grade_for
from .web import BlockedTarget, crawl, detect_stack, make_client, normalize_url

_HEADERS = {
    "User-Agent": "VibeGuard/2.0 (+security-self-scan)",
    "Content-Type": "application/json",
}


# ---------------------------------------------------------------------------
# Public entrypoints
# ---------------------------------------------------------------------------

async def run_scan(cfg: FirebaseConfig, extra_collections: list[str]) -> dict:
    """Firebase scan (kept for the existing /api/scan config path)."""
    return await scan_firebase(cfg, extra_collections)


async def scan_firebase(cfg: FirebaseConfig, extra_collections: list[str]) -> dict:
    started = time.perf_counter()

    if (cfg.projectId or "").strip().lower() == "vibeguard-demo":
        return await _demo_result(started)

    raw: list[dict] = []
    error = None
    timeout = httpx.Timeout(SCAN_TIMEOUT)
    try:
        async with httpx.AsyncClient(headers=_HEADERS, timeout=timeout,
                                     limits=httpx.Limits(max_connections=10),
                                     follow_redirects=True) as client:
            fs = await checks.check_firestore(client, cfg, extra_collections)
            rtdb = await checks.check_rtdb(client, cfg)
            storage = await checks.check_storage(client, cfg)
            auth = await checks.check_auth(client, cfg)
            raw = fs + rtdb + storage + auth
    except Exception as exc:  # noqa: BLE001
        error = str(exc)[:500]

    return _assemble(cfg.projectId or "firebase", "firebase", raw, started,
                     error=error, stack=["Firebase"])


async def scan_supabase(sb: SupabaseFound) -> dict:
    started = time.perf_counter()
    raw: list[dict] = []
    error = None
    timeout = httpx.Timeout(SCAN_TIMEOUT)
    try:
        async with httpx.AsyncClient(timeout=timeout,
                                     limits=httpx.Limits(max_connections=10),
                                     follow_redirects=True) as client:
            raw = await sb_checks.check_supabase(client, sb)
    except Exception as exc:  # noqa: BLE001
        error = str(exc)[:500]
    return _assemble(sb.ref or "supabase", "supabase", raw, started,
                     error=error, stack=["Supabase"])


async def scan_url(raw_url: str) -> dict:
    """Fetch a live site and run every applicable check."""
    started = time.perf_counter()
    try:
        url = normalize_url(raw_url)
    except BlockedTarget as exc:
        return _assemble(raw_url, "url", [], started, error=str(exc), stack=[])

    raw: list[dict] = []
    secret_items: list[dict] = []
    stack: list[str] = []
    error = None

    client = make_client(SCAN_TIMEOUT)
    try:
        site = await crawl(client, url)
        stack = detect_stack(site)
        texts = site.all_text()

        # --- find secrets anywhere in the shipped code ---
        seen_secret = set()
        for where, text in texts:
            for hit in find_secrets(text, where):
                if hit.kind in seen_secret:
                    continue
                seen_secret.add(hit.kind)
                secret_items.append({
                    "check_id": f"secret_{hit.kind}",
                    "title": f"Exposed secret: {hit.name}",
                    "severity": hit.severity,
                    "status": "vulnerable",
                    "description": f"A {hit.name} is shipped in your public frontend "
                                   f"({hit.masked}). {hit.impact}",
                    "remediation": SECRET_REMEDIATION,
                    "evidence": f"Found {hit.masked} in {_short(hit.where or where)}.",
                    "weight": _secret_weight(hit.severity),
                })

        # --- discover backends ---
        fb = None
        sb_list = []
        for where, text in texts:
            if fb is None:
                fb = find_firebase(text, where)
            got = find_supabase(text, where)
            if got:
                sb_list.append(got)
        sb = merge_supabase(sb_list)

        # --- probe whatever we found, concurrently-ish ---
        async with httpx.AsyncClient(headers=_HEADERS, timeout=httpx.Timeout(SCAN_TIMEOUT),
                                     limits=httpx.Limits(max_connections=10),
                                     follow_redirects=True) as probe:
            if fb and fb.projectId:
                if "Firebase" not in stack:
                    stack.append("Firebase")
                cfg = FirebaseConfig(**fb.as_config())
                cols = _collections_from(site)
                raw += await checks.check_firestore(probe, cfg, cols)
                raw += await checks.check_rtdb(probe, cfg)
                raw += await checks.check_storage(probe, cfg)
                raw += await checks.check_auth(probe, cfg)
            if sb and (sb.anon_key or sb.service_key):
                if "Supabase" not in stack:
                    stack.append("Supabase")
                raw += await sb_checks.check_supabase(probe, sb)

        # --- passive website checks (always) ---
        raw += webchecks.check_headers(site)
        raw += webchecks.check_source_maps(site)
        raw += await webchecks.check_exposed_files(client, site)

        display = _host(site.url)
    except BlockedTarget as exc:
        error = str(exc)
        display = raw_url
    except Exception as exc:  # noqa: BLE001
        error = str(exc)[:500]
        display = raw_url
    finally:
        await client.aclose()

    result = _assemble(display, "url", raw, started, error=error, stack=stack,
                       extra_findings=secret_items)
    # If we fetched the site but found no backend and no secrets, say so clearly.
    if not error and not raw and not secret_items:
        result["error"] = ("Fetched the site but found no Firebase/Supabase config or "
                           "leaked secrets to check. Paste the config directly for a deep scan.")
    return result


# ---------------------------------------------------------------------------
# Assembly / scoring
# ---------------------------------------------------------------------------

def _assemble(display: str, scan_type: str, raw: list[dict], started: float, *,
              error=None, stack=None, extra_findings=None) -> dict:
    findings = _build_findings(raw)
    if extra_findings:
        findings = extra_findings + findings
        findings.sort(key=lambda f: (SEVERITY_ORDER.get(f["severity"], 9), f["check_id"]))
    score, counts = _score(findings)
    return {
        "project_id": display,
        "scan_type": scan_type,
        "stack": stack or [],
        "status": "error" if error and not findings else "completed",
        "score": score,
        "grade": grade_for(score),
        "critical": counts["critical"],
        "high": counts["high"],
        "medium": counts["medium"],
        "low": counts["low"],
        "passed": counts["passed"],
        "duration_ms": int((time.perf_counter() - started) * 1000),
        "error": error,
        "findings": findings,
    }


def _build_findings(raw: list[dict]) -> list[dict]:
    out: list[dict] = []
    for item in raw:
        cid = item["check_id"]
        meta = CHECKS.get(cid)
        if meta is None:
            continue
        status = item["status"]
        if status == "vulnerable":
            severity = meta.severity
        elif status == "ok":
            severity = "pass"
        else:
            severity = "info"
        out.append({
            "check_id": cid,
            "title": PASS_TITLES.get(cid, meta.title) if status == "ok" else meta.title,
            "severity": severity,
            "status": status,
            "description": meta.description,
            "remediation": meta.remediation,
            "evidence": item.get("evidence", ""),
            "weight": meta.weight,
        })
    out.sort(key=lambda f: (SEVERITY_ORDER.get(f["severity"], 9), f["check_id"]))
    return out


def _score(findings: list[dict]) -> tuple[int, dict]:
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "passed": 0}
    penalty = 0.0
    for f in findings:
        if f["status"] == "vulnerable":
            sev = f["severity"]
            if sev in counts:
                counts[sev] += 1
            penalty += f.get("weight", 0)
        elif f["status"] == "ok":
            counts["passed"] += 1
    score = max(0, min(100, round(100 - penalty)))
    return score, counts


def _secret_weight(sev: str) -> float:
    return {"critical": 45, "high": 24, "medium": 10, "low": 5}.get(sev, 10)


def _collections_from(site) -> list[str]:
    from .detect import find_collections
    cols: list[str] = []
    for _where, text in site.all_text():
        for c in find_collections(text):
            if c not in cols:
                cols.append(c)
    return cols[:30]


def _short(where: str) -> str:
    where = where or ""
    if len(where) > 60:
        return "…" + where[-57:]
    return where


def _host(url: str) -> str:
    from urllib.parse import urlparse
    p = urlparse(url)
    return p.netloc or url


async def _demo_result(started: float) -> dict:
    import asyncio
    await asyncio.sleep(1.2)
    raw = [
        {"check_id": "firestore_public_read", "status": "vulnerable", "evidence": "GET on collection 'users' returned 200 without authentication."},
        {"check_id": "firestore_public_write", "status": "vulnerable", "evidence": "Unauthenticated POST created a document (probe document deleted)."},
        {"check_id": "rtdb_public_read", "status": "ok", "evidence": "Realtime Database denied the unauthenticated read."},
        {"check_id": "rtdb_public_write", "status": "ok", "evidence": "Realtime Database denied the unauthenticated write."},
        {"check_id": "storage_public_list", "status": "vulnerable", "evidence": "Objects in bucket 'vibeguard-demo.appspot.com' are listable without authentication."},
        {"check_id": "auth_open_signup", "status": "vulnerable", "evidence": "Email/password sign-up created an account without approval (test user removed)."},
        {"check_id": "auth_anonymous_open", "status": "ok", "evidence": "Anonymous authentication is disabled."},
        {"check_id": "apikey_unrestricted", "status": "vulnerable", "evidence": "API key accepted requests from a non-browser origin (no referrer restriction)."},
    ]
    secret = [{
        "check_id": "secret_openai", "title": "Exposed secret: OpenAI API key",
        "severity": "critical", "status": "vulnerable",
        "description": "A OpenAI API key is shipped in your public frontend (sk-proj-…a1B2). "
                       "Anyone can call OpenAI on your bill.",
        "remediation": SECRET_REMEDIATION,
        "evidence": "Found sk-proj-…a1B2 in /assets/index-4f1c.js.", "weight": 45,
    }]
    return _assemble("vibeguard-demo", "url", raw, started, stack=["Firebase", "Vite"],
                     extra_findings=secret)
