"""Individual security probes against a developer's own Firebase project.

Every probe is read-only or self-cleaning: write probes create a document under
a dedicated `__vibeguard_probe__` path and delete it immediately; auth probes
that create a throwaway user delete that user before returning. Nothing here
touches real application data.

A check returns a list of result dicts shaped like:
    {"check_id": str, "status": "vulnerable|ok|skipped|error", "evidence": str}
Title/severity/description/remediation are filled from rules.CHECKS by the
engine, so checks only decide status + evidence.
"""
import secrets
import time
from typing import Optional

import httpx

from ..schemas import FirebaseConfig

DEFAULT_COLLECTIONS = ["users", "messages", "posts", "orders", "data", "profiles", "chats"]
PROBE_PATH = "__vibeguard_probe__"


def _r(check_id: str, status: str, evidence: str = "") -> dict:
    return {"check_id": check_id, "status": status, "evidence": evidence}


# --- Firestore ----------------------------------------------------------------

ACTIVE_SKIP = "Active test — tick “This is my project” to run write/sign-up probes."


async def check_firestore(client: httpx.AsyncClient, cfg: FirebaseConfig,
                          extra_collections: list[str], active: bool = True) -> list[dict]:
    pid = cfg.projectId
    key = cfg.apiKey
    base = f"https://firestore.googleapis.com/v1/projects/{pid}/databases/(default)/documents"
    keyq = f"?key={key}" if key else ""

    results: list[dict] = []

    # ---- public READ ----
    collections = DEFAULT_COLLECTIONS + [c for c in extra_collections if c]
    read_hit: Optional[str] = None
    denied = 0
    other = 0
    for col in collections:
        url = f"{base}/{col}{keyq}"
        sep = "&" if keyq else "?"
        url += f"{sep}pageSize=1"
        try:
            resp = await client.get(url)
        except Exception as exc:  # noqa: BLE001
            other += 1
            continue
        if resp.status_code == 200:
            read_hit = col
            break
        if resp.status_code in (401, 403):
            denied += 1
        else:
            other += 1

    if read_hit is not None:
        results.append(_r(
            "firestore_public_read", "vulnerable",
            f"GET on collection '{read_hit}' returned 200 without authentication.",
        ))
    elif denied > 0:
        results.append(_r(
            "firestore_public_read", "ok",
            "Firestore refused unauthenticated reads (permission denied).",
        ))
    else:
        results.append(_r(
            "firestore_public_read", "skipped",
            "Could not determine Firestore read state (no probed collection responded).",
        ))

    # ---- public WRITE ----
    if not active:
        results.append(_r("firestore_public_write", "skipped", ACTIVE_SKIP))
        return results
    write_url = f"{base}/{PROBE_PATH}{keyq}"
    payload = {"fields": {"vibeguard": {"stringValue": "probe"}}}
    try:
        resp = await client.post(write_url, json=payload)
        if resp.status_code == 200:
            doc_name = resp.json().get("name")
            # clean up the probe document
            cleaned = "left in place (delete failed)"
            if doc_name:
                try:
                    del_url = f"https://firestore.googleapis.com/v1/{doc_name}{keyq}"
                    d = await client.delete(del_url)
                    if d.status_code in (200, 204):
                        cleaned = "probe document deleted"
                except Exception:  # noqa: BLE001
                    pass
            results.append(_r(
                "firestore_public_write", "vulnerable",
                f"Unauthenticated POST created a document ({cleaned}).",
            ))
        elif resp.status_code in (401, 403):
            results.append(_r(
                "firestore_public_write", "ok",
                "Firestore refused the unauthenticated write.",
            ))
        else:
            results.append(_r(
                "firestore_public_write", "skipped",
                f"Unexpected status {resp.status_code} on write probe.",
            ))
    except Exception as exc:  # noqa: BLE001
        results.append(_r("firestore_public_write", "error", str(exc)[:200]))

    return results


# --- Realtime Database --------------------------------------------------------

def _rtdb_base(cfg: FirebaseConfig) -> Optional[str]:
    if cfg.databaseURL:
        return cfg.databaseURL.rstrip("/")
    if cfg.projectId:
        return f"https://{cfg.projectId}-default-rtdb.firebaseio.com"
    return None


async def check_rtdb(client: httpx.AsyncClient, cfg: FirebaseConfig,
                     active: bool = True) -> list[dict]:
    base = _rtdb_base(cfg)
    results: list[dict] = []
    if not base:
        return [_r("rtdb_public_read", "skipped", "No database URL to probe.")]

    # ---- READ ----
    provisioned = True
    try:
        resp = await client.get(f"{base}/.json?shallow=true")
        if resp.status_code == 200:
            results.append(_r(
                "rtdb_public_read", "vulnerable",
                "GET /.json returned 200 without authentication.",
            ))
        elif resp.status_code in (401, 403):
            results.append(_r(
                "rtdb_public_read", "ok",
                "Realtime Database denied the unauthenticated read.",
            ))
        elif resp.status_code == 404:
            provisioned = False
            results.append(_r(
                "rtdb_public_read", "skipped",
                "No Realtime Database instance found at this URL.",
            ))
        else:
            results.append(_r(
                "rtdb_public_read", "skipped",
                f"Unexpected status {resp.status_code}.",
            ))
    except Exception as exc:  # noqa: BLE001
        results.append(_r("rtdb_public_read", "error", str(exc)[:200]))
        provisioned = False

    # ---- WRITE ----
    if not provisioned:
        results.append(_r("rtdb_public_write", "skipped", "No RTDB instance to probe."))
        return results
    if not active:
        results.append(_r("rtdb_public_write", "skipped", ACTIVE_SKIP))
        return results

    ts = int(time.time() * 1000)
    probe_url = f"{base}/{PROBE_PATH}/{ts}.json"
    try:
        resp = await client.put(probe_url, json="vibeguard-probe")
        if resp.status_code == 200:
            cleaned = "left in place (delete failed)"
            try:
                d = await client.delete(f"{base}/{PROBE_PATH}.json")
                if d.status_code in (200, 204):
                    cleaned = "probe node deleted"
            except Exception:  # noqa: BLE001
                pass
            results.append(_r(
                "rtdb_public_write", "vulnerable",
                f"Unauthenticated PUT succeeded ({cleaned}).",
            ))
        elif resp.status_code in (401, 403):
            results.append(_r(
                "rtdb_public_write", "ok",
                "Realtime Database denied the unauthenticated write.",
            ))
        else:
            results.append(_r(
                "rtdb_public_write", "skipped",
                f"Unexpected status {resp.status_code} on write probe.",
            ))
    except Exception as exc:  # noqa: BLE001
        results.append(_r("rtdb_public_write", "error", str(exc)[:200]))

    return results


# --- Storage ------------------------------------------------------------------

def _buckets(cfg: FirebaseConfig) -> list[str]:
    if cfg.storageBucket:
        return [cfg.storageBucket]
    if cfg.projectId:
        return [f"{cfg.projectId}.appspot.com", f"{cfg.projectId}.firebasestorage.app"]
    return []


async def check_storage(client: httpx.AsyncClient, cfg: FirebaseConfig) -> list[dict]:
    buckets = _buckets(cfg)
    if not buckets:
        return [_r("storage_public_list", "skipped", "No storage bucket to probe.")]

    found_bucket = False
    for bucket in buckets:
        url = f"https://firebasestorage.googleapis.com/v0/b/{bucket}/o?maxResults=1"
        try:
            resp = await client.get(url)
        except Exception as exc:  # noqa: BLE001
            continue
        if resp.status_code == 200:
            return [_r(
                "storage_public_list", "vulnerable",
                f"Objects in bucket '{bucket}' are listable without authentication.",
            )]
        if resp.status_code in (401, 403):
            found_bucket = True
            # keep scanning other candidate buckets, but remember it's protected
            continue
        # 404 => bucket not found, try next candidate

    if found_bucket:
        return [_r(
            "storage_public_list", "ok",
            "Storage denied unauthenticated object listing.",
        )]
    return [_r("storage_public_list", "skipped", "No reachable storage bucket found.")]


# --- Authentication -----------------------------------------------------------

IDENTITY = "https://identitytoolkit.googleapis.com/v1/accounts"


async def _delete_user(client: httpx.AsyncClient, key: str, id_token: str) -> bool:
    try:
        resp = await client.post(f"{IDENTITY}:delete?key={key}", json={"idToken": id_token})
        return resp.status_code == 200
    except Exception:  # noqa: BLE001
        return False


async def check_auth(client: httpx.AsyncClient, cfg: FirebaseConfig,
                     active: bool = True) -> list[dict]:
    key = cfg.apiKey
    results: list[dict] = []
    if not key:
        return [
            _r("auth_open_signup", "skipped", "No API key provided."),
            _r("auth_anonymous_open", "skipped", "No API key provided."),
            _r("apikey_unrestricted", "skipped", "No API key provided."),
        ]

    referrer_blocked = False
    # True only once we've seen a real Identity Toolkit reply (success fields or a
    # Google-shaped error). Guards against network/proxy errors being mistaken for
    # an unrestricted key.
    got_google_response = False

    def _is_google_body(b: dict) -> bool:
        if not isinstance(b, dict):
            return False
        if any(k in b for k in ("idToken", "localId", "kind", "refreshToken")):
            return True
        return bool((b.get("error", {}) or {}).get("message"))

    def _parse(resp: httpx.Response) -> dict:
        try:
            b = resp.json() if resp.content else {}
            return b if isinstance(b, dict) else {}
        except Exception:  # noqa: BLE001
            return {}

    if not active:
        # Passive: no accounts are created. createAuthUri only asks which sign-in
        # methods exist for a made-up address — enough to see if the key is restricted.
        results.append(_r("auth_open_signup", "skipped", ACTIVE_SKIP))
        results.append(_r("auth_anonymous_open", "skipped", ACTIVE_SKIP))
        try:
            resp = await client.post(
                f"{IDENTITY}:createAuthUri?key={key}",
                json={"identifier": f"vibeguard_{secrets.token_hex(6)}@vibeguard-probe.invalid",
                      "continueUri": "https://vibeguard.invalid/"},
            )
            body = _parse(resp)
            msg = (body.get("error", {}) or {}).get("message", "")
            if "API_KEY_HTTP_REFERRER_BLOCKED" in msg or "requests-from-referer" in msg.lower():
                referrer_blocked = True
                got_google_response = True
            elif _is_google_body(body):
                got_google_response = True
        except Exception:  # noqa: BLE001
            pass
    else:
        referrer_blocked, got_google_response = await _auth_active(
            client, key, results, _parse, _is_google_body)

    # ---- API key referrer restriction ----
    if referrer_blocked:
        results.append(_r("apikey_unrestricted", "ok",
                          "API key rejected server-side requests (referrer-restricted)."))
    elif got_google_response:
        results.append(_r(
            "apikey_unrestricted", "vulnerable",
            "API key accepted requests from a non-browser origin (no referrer restriction).",
        ))
    else:
        results.append(_r(
            "apikey_unrestricted", "skipped",
            "Could not reach the auth endpoint to test the API key.",
        ))
    return results


async def _auth_active(client, key, results, _parse, _is_google_body) -> tuple[bool, bool]:
    """Sign-up probes: create a throwaway user (deleted right after).
    Returns (referrer_blocked, got_google_response)."""
    referrer_blocked = False
    got_google_response = False
    # ---- Email/password sign-up open? (creates + deletes a throwaway user) ----
    probe_email = f"vibeguard_{secrets.token_hex(8)}@vibeguard-probe.invalid"
    probe_pass = secrets.token_urlsafe(16)
    try:
        resp = await client.post(
            f"{IDENTITY}:signUp?key={key}",
            json={"email": probe_email, "password": probe_pass, "returnSecureToken": True},
        )
        body = _parse(resp)
        if _is_google_body(body):
            got_google_response = True
        if resp.status_code == 200 and body.get("idToken"):
            deleted = await _delete_user(client, key, body["idToken"])
            note = "test user removed" if deleted else "test user NOT removed — delete manually"
            results.append(_r(
                "auth_open_signup", "vulnerable",
                f"Email/password sign-up created an account without approval ({note}).",
            ))
        else:
            msg = (body.get("error", {}) or {}).get("message", "")
            if any(m in msg for m in ("OPERATION_NOT_ALLOWED", "ADMIN_ONLY_OPERATION",
                                      "PASSWORD_LOGIN_DISABLED")):
                results.append(_r("auth_open_signup", "ok",
                                  "Self-serve email/password sign-up is disabled."))
            elif "API_KEY_HTTP_REFERRER_BLOCKED" in msg or "requests-from-referer" in msg.lower():
                referrer_blocked = True
                got_google_response = True
                results.append(_r("auth_open_signup", "skipped",
                                  "API key is referrer-restricted; auth not probed server-side."))
            else:
                results.append(_r("auth_open_signup", "skipped",
                                  f"Inconclusive sign-up response: {msg or resp.status_code}"))
    except Exception as exc:  # noqa: BLE001
        results.append(_r("auth_open_signup", "error", str(exc)[:200]))

    # ---- Anonymous auth enabled? ----
    try:
        resp = await client.post(f"{IDENTITY}:signUp?key={key}",
                                  json={"returnSecureToken": True})
        body = _parse(resp)
        if _is_google_body(body):
            got_google_response = True
        if resp.status_code == 200 and body.get("idToken"):
            deleted = await _delete_user(client, key, body["idToken"])
            note = "test user removed" if deleted else "test user NOT removed — delete manually"
            results.append(_r(
                "auth_anonymous_open", "vulnerable",
                f"Anonymous sign-in issued a token with no credentials ({note}).",
            ))
        else:
            msg = (body.get("error", {}) or {}).get("message", "")
            if any(m in msg for m in ("ADMIN_ONLY_OPERATION", "OPERATION_NOT_ALLOWED")):
                results.append(_r("auth_anonymous_open", "ok",
                                  "Anonymous authentication is disabled."))
            elif "API_KEY_HTTP_REFERRER_BLOCKED" in msg or "requests-from-referer" in msg.lower():
                referrer_blocked = True
                got_google_response = True
                results.append(_r("auth_anonymous_open", "skipped",
                                  "API key is referrer-restricted; auth not probed server-side."))
            else:
                results.append(_r("auth_anonymous_open", "skipped",
                                  f"Inconclusive anonymous response: {msg or resp.status_code}"))
    except Exception as exc:  # noqa: BLE001
        results.append(_r("auth_anonymous_open", "error", str(exc)[:200]))

    return referrer_blocked, got_google_response
