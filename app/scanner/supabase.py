"""Probes against a Supabase project, using only its public anon key.

Same philosophy as the Firebase probes: read-only or self-cleaning, and only
ever run against a project the user controls. The anon key is public by design
(it ships in the frontend); the point of the scan is that Row Level Security,
not the key, is what should protect the data — so we check whether RLS is
actually on.

All requests go through the SSRF-safe client the engine passes in.
"""
import secrets
from typing import Optional

import httpx

from .detect import SupabaseFound, jwt_payload

PROBE_TABLE_FALLBACKS = ["users", "profiles", "posts", "messages", "todos", "items", "orders"]
PROBE_BUCKET_FALLBACKS = ["avatars", "public", "uploads", "images", "files"]


def _r(check_id: str, status: str, evidence: str = "") -> dict:
    return {"check_id": check_id, "status": status, "evidence": evidence}


def _headers(anon: str) -> dict:
    return {"apikey": anon, "Authorization": f"Bearer {anon}"}


async def check_supabase(client: httpx.AsyncClient, sb: SupabaseFound) -> list[dict]:
    results: list[dict] = []
    base = (sb.url or "").rstrip("/")
    anon = sb.anon_key

    # A service_role key in the frontend is the single worst Supabase mistake.
    if sb.service_key:
        results.append(_r(
            "supabase_service_key_exposed", "vulnerable",
            "A service_role key (bypasses all Row Level Security) is shipped in the frontend bundle.",
        ))

    if not base:
        return results or [_r("supabase_rls_read", "skipped", "No Supabase URL found.")]
    if not anon:
        results.append(_r("supabase_rls_read", "skipped",
                          "No anon key found — can't test table access without it."))
        return results

    rest = f"{base}/rest/v1"
    tables = _uniq((sb.tables or []) + PROBE_TABLE_FALLBACKS)

    # ---- RLS on tables: can the anon key READ rows? ----
    read_hit: Optional[tuple[str, int]] = None
    protected = 0
    tested = 0
    for t in tables[:20]:
        try:
            resp = await client.get(f"{rest}/{t}?select=*&limit=1", headers=_headers(anon))
        except Exception:  # noqa: BLE001
            continue
        if resp.status_code == 200:
            tested += 1
            try:
                rows = resp.json()
            except Exception:  # noqa: BLE001
                rows = []
            if isinstance(rows, list) and rows:
                read_hit = (t, len(rows))
                break
            # 200 + [] → table exists but RLS returns nothing to anon (good)
            protected += 1
        elif resp.status_code in (401, 403):
            protected += 1
            tested += 1
        # 404 → table doesn't exist, keep trying

    if read_hit:
        results.append(_r(
            "supabase_rls_read", "vulnerable",
            f"Table '{read_hit[0]}' returned rows to the anon key — Row Level Security is off or allows public SELECT.",
        ))
    elif tested:
        results.append(_r("supabase_rls_read", "ok",
                          "Tables returned no data to the anon key (RLS appears to restrict reads)."))
    else:
        results.append(_r("supabase_rls_read", "skipped",
                          "Couldn't find a known table to test (none of the detected/common names responded)."))

    # ---- RLS on writes: can the anon key INSERT? (self-cleaning) ----
    write_target = read_hit[0] if read_hit else (sb.tables[0] if sb.tables else None)
    if write_target:
        marker = f"__vibeguard_{secrets.token_hex(6)}"
        try:
            resp = await client.post(
                f"{rest}/{write_target}",
                headers={**_headers(anon), "Content-Type": "application/json",
                         "Prefer": "return=representation"},
                json={"id": marker, "name": marker, "title": marker},
            )
            if resp.status_code in (200, 201):
                cleaned = "probe row left (delete failed)"
                try:
                    d = await client.delete(f"{rest}/{write_target}?name=eq.{marker}",
                                            headers=_headers(anon))
                    if d.status_code in (200, 204):
                        cleaned = "probe row deleted"
                except Exception:  # noqa: BLE001
                    pass
                results.append(_r(
                    "supabase_rls_write", "vulnerable",
                    f"The anon key inserted a row into '{write_target}' ({cleaned}) — writes are not protected by RLS.",
                ))
            elif resp.status_code in (401, 403):
                results.append(_r("supabase_rls_write", "ok",
                                  "Supabase rejected the anonymous insert (RLS on writes)."))
            else:
                # 400/409/422 usually = RLS allowed it but the row shape was wrong → treat as inconclusive-but-leaning-open
                body = (resp.text or "")[:200]
                if "row-level security" in body.lower() or "rls" in body.lower() or resp.status_code == 403:
                    results.append(_r("supabase_rls_write", "ok",
                                      "Supabase rejected the anonymous insert (RLS on writes)."))
                else:
                    results.append(_r("supabase_rls_write", "skipped",
                                      f"Insert returned {resp.status_code}; couldn't confirm (table shape mismatch)."))
        except Exception as exc:  # noqa: BLE001
            results.append(_r("supabase_rls_write", "error", str(exc)[:200]))

    # ---- Storage buckets public? ----
    buckets = _uniq((sb.buckets or []) + PROBE_BUCKET_FALLBACKS)
    public_bucket = None
    checked_bucket = False
    for b in buckets[:12]:
        try:
            resp = await client.post(
                f"{base}/storage/v1/object/list/{b}",
                headers={**_headers(anon), "Content-Type": "application/json"},
                json={"prefix": "", "limit": 1},
            )
        except Exception:  # noqa: BLE001
            continue
        if resp.status_code == 200:
            checked_bucket = True
            try:
                items = resp.json()
            except Exception:  # noqa: BLE001
                items = []
            if isinstance(items, list) and items:
                public_bucket = b
                break
        elif resp.status_code in (400, 404):
            continue  # bucket missing
        elif resp.status_code in (401, 403):
            checked_bucket = True
    if public_bucket:
        results.append(_r("supabase_storage_public", "vulnerable",
                          f"Storage bucket '{public_bucket}' lists its objects to the anon key."))
    elif checked_bucket:
        results.append(_r("supabase_storage_public", "ok",
                          "Storage buckets did not list objects to the anon key."))

    # ---- Does the project leak its schema (PostgREST OpenAPI)? ----
    try:
        resp = await client.get(f"{rest}/", headers=_headers(anon))
        if resp.status_code == 200 and "swagger" in (resp.text or "")[:2000].lower():
            try:
                spec = resp.json()
                paths = [p.lstrip("/") for p in (spec.get("paths") or {}) if p not in ("/",)]
            except Exception:  # noqa: BLE001
                paths = []
            if paths:
                sample = ", ".join(paths[:8])
                results.append(_r(
                    "supabase_schema_exposed", "vulnerable",
                    f"The anon key can read the full API schema ({len(paths)} tables/views: {sample}…). "
                    "This hands an attacker a map of your whole database.",
                ))
    except Exception:  # noqa: BLE001
        pass

    return results


def anon_key_note(sb: SupabaseFound) -> Optional[str]:
    """Human note about the anon JWT (exp etc.), or None."""
    if not sb.anon_key or not sb.anon_key.startswith("eyJ"):
        return None
    p = jwt_payload(sb.anon_key)
    return f"anon key role={p.get('role', '?')}" if p else None


def _uniq(it) -> list:
    out: list = []
    for x in it:
        if x and x not in out:
            out.append(x)
    return out
