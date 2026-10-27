"""VibeGuard API — scan a Firebase / vibe-coded app for security holes.

Freemium model:
  * Free:  score, grade and HOW MANY holes there are (per severity).
  * Paid:  a license key (web) or Telegram Stars (Mini App) unlocks the full
           report — every hole, evidence and step-by-step fix. Details are
           stripped server-side for locked scans, so nothing leaks via DevTools.

Routes:  /      landing page
         /app   web scanner
         /tg/   Telegram Mini App
"""
import asyncio
import hmac
import logging
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from . import payments as pay
from . import telegram as tg
from .config import (
    ADMIN_TOKEN,
    APP_NAME,
    APP_VERSION,
    MANUAL_DETAILS,
    PACK_SCANS,
    PAYMENT_URL,
    PRICE_LABEL,
    PRICE_USD,
    STARS_PRICE,
    SUPPORT_CONTACT,
    TG_WEBHOOK_SECRET,
)
from .database import SessionLocal, get_db, init_db
from .scanner import scan_firebase, scan_supabase, scan_url
from .scanner.detect import classify_input
from .schemas import (
    LicenseCreate,
    LicenseOut,
    ScanDetail,
    ScanRequest,
    ScanSummary,
    UnlockRequest,
)

logging.basicConfig(level=logging.INFO)

app = FastAPI(title=APP_NAME, version=APP_VERSION,
              description="Security scanner for Firebase / vibe-coded apps.")

STATIC_DIR = Path(__file__).parent / "static"


@app.on_event("startup")
async def _startup() -> None:
    init_db()
    if tg.ENABLED:
        asyncio.create_task(tg.setup_bot())
    if pay.CRYPTO_ENABLED:
        asyncio.create_task(pay.sweep_loop())


# ---- Helpers -----------------------------------------------------------------

def _serialize(scan: models.Scan) -> dict:
    """Build the API response; strip details unless the scan is unlocked."""
    issues = scan.critical + scan.high + scan.medium + scan.low
    data = ScanSummary.model_validate(scan).model_dump()
    data.update({
        "error": scan.error,
        "issues": issues,
        "locked": not scan.unlocked,
        "stack": [s for s in (scan.stack or "").split(",") if s],
        "findings": [],
    })
    if scan.unlocked:
        data["findings"] = [
            {
                "check_id": f.check_id, "title": f.title, "severity": f.severity,
                "status": f.status, "description": f.description,
                "remediation": f.remediation, "evidence": f.evidence,
            }
            for f in scan.findings
        ]
    return data


async def _dispatch_scan(req: ScanRequest) -> dict:
    """Route a scan request to the right scanner based on what was sent."""
    # Explicit firebaseConfig (API, or the classic Firebase path).
    if req.config is not None and req.config.projectId:
        return await scan_firebase(req.config, req.collections)

    raw = (req.target or "").strip()
    if not raw:
        raise HTTPException(status_code=422,
                            detail="Send a website URL, a firebaseConfig, or Supabase URL + anon key.")

    if raw.lower() in ("vibeguard-demo", "demo"):
        from .schemas import FirebaseConfig
        return await scan_firebase(FirebaseConfig(projectId="vibeguard-demo"), [])

    kind = classify_input(raw)
    t = kind["type"]
    if t == "url":
        return await scan_url(kind["url"])
    if t == "supabase":
        sb = kind["supabase"]
        if not (sb.anon_key or sb.service_key):
            # Only a bare supabase URL → nothing to probe without the key.
            raise HTTPException(status_code=422,
                                detail="Found a Supabase URL but no anon key. Paste the "
                                       "createClient(url, anonKey) line, or just give me your site URL.")
        return await scan_supabase(sb)
    if t == "firebase":
        fb = kind["firebase"]
        from .schemas import FirebaseConfig
        return await scan_firebase(FirebaseConfig(**fb.as_config()), req.collections)
    raise HTTPException(status_code=422,
                        detail="Couldn't tell what that is. Paste your site URL, your "
                               "firebaseConfig object, or your Supabase URL + anon key.")


def _normalize_key(key: str | None) -> str:
    return (key or "").strip().upper()


def _check_license(db: Session, key: str | None) -> models.License:
    """Return a usable license or raise 402/403. Does not spend a use."""
    lic = db.get(models.License, _normalize_key(key))
    if lic is None or not lic.active:
        raise HTTPException(status_code=403, detail="Invalid license key")
    if lic.used >= lic.max_scans:
        raise HTTPException(status_code=402, detail="License key has no scans left")
    return lic


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=404, detail="Not found")
    if not x_admin_token or not hmac.compare_digest(x_admin_token, ADMIN_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid admin token")


def tg_user(x_telegram_init_data: str | None = Header(default=None)) -> dict | None:
    """Telegram Mini App user, if the request carries valid initData."""
    return tg.validate_init_data(x_telegram_init_data)


def require_tg_user(user: dict | None = Depends(tg_user)) -> dict:
    if user is None:
        raise HTTPException(status_code=401, detail="Open this inside Telegram")
    return user


# ---- Public API --------------------------------------------------------------

@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "name": APP_NAME, "version": APP_VERSION}


def _contact_url(contact: str) -> str | None:
    c = (contact or "").strip()
    if not c:
        return None
    if c.startswith("http"):
        return c
    if "@" in c and not c.startswith("@"):
        return f"mailto:{c}"
    return f"https://t.me/{c.lstrip('@')}"


@app.get("/api/pricing")
def pricing() -> dict:
    return {
        "price": PRICE_LABEL,
        "payment_url": PAYMENT_URL or None,
        "stars": STARS_PRICE,
        "pack_scans": PACK_SCANS,
        "telegram": tg.ENABLED,
        "bot_username": tg.BOT_USERNAME or None,
        "price_usd": PRICE_USD,
        "support": SUPPORT_CONTACT or None,
        "methods": {
            "stars": tg.ENABLED,
            "crypto": pay.CRYPTO_ENABLED,
            "manual": pay.MANUAL_ENABLED,
            "link": bool(PAYMENT_URL),
            # No requisites on the site → "write to the seller" option.
            "contact": bool(SUPPORT_CONTACT) and not pay.MANUAL_ENABLED,
        },
        "contact_url": _contact_url(SUPPORT_CONTACT),
        "manual_details": MANUAL_DETAILS or None,
        "manual_mode": "relay" if pay.RELAY_ENABLED else ("static" if pay.MANUAL_ENABLED else None),
    }


@app.post("/api/scan", response_model=ScanDetail)
async def create_scan(req: ScanRequest, db: Session = Depends(get_db),
                      user: dict | None = Depends(tg_user)) -> dict:
    # Pick a license BEFORE spending time on the scan: an explicit key wins,
    # otherwise a Telegram user's own paid license is used automatically.
    lic = None
    if req.license_key:
        lic = _check_license(db, req.license_key)
    elif user is not None:
        lic = tg.user_license(db, user["id"])

    # Decide what to scan: an explicit firebaseConfig, or the smart `target`
    # string (a URL, or Supabase URL + anon key, or a pasted config).
    result = await _dispatch_scan(req)

    scan = models.Scan(
        project_id=result["project_id"],
        target_label=req.label,
        scan_type=result.get("scan_type", "firebase"),
        stack=",".join(result.get("stack", [])) or None,
        status=result["status"],
        score=result["score"],
        grade=result["grade"],
        critical=result["critical"],
        high=result["high"],
        medium=result["medium"],
        low=result["low"],
        passed=result["passed"],
        duration_ms=result["duration_ms"],
        error=result["error"],
        tg_user_id=user["id"] if user else None,
    )
    for f in result["findings"]:
        scan.findings.append(models.Finding(
            check_id=f["check_id"], title=f["title"], severity=f["severity"],
            status=f["status"], description=f["description"],
            remediation=f["remediation"], evidence=f["evidence"], weight=f["weight"],
        ))

    if lic is not None:
        # A clean scan has nothing to unlock — don't charge a scan from the pack.
        if result["critical"] + result["high"] + result["medium"] + result["low"] > 0:
            lic.used += 1
        scan.unlocked = True
        scan.license_key = lic.key

    db.add(scan)
    db.commit()
    db.refresh(scan)
    return _serialize(scan)


@app.get("/api/scans/{scan_id}", response_model=ScanDetail)
def get_scan(scan_id: str, db: Session = Depends(get_db)) -> dict:
    scan = db.get(models.Scan, scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    return _serialize(scan)


@app.post("/api/scans/{scan_id}/unlock", response_model=ScanDetail)
def unlock_scan(scan_id: str, req: UnlockRequest, db: Session = Depends(get_db)) -> dict:
    scan = db.get(models.Scan, scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    if not scan.unlocked:
        lic = _check_license(db, req.license_key)
        if scan.critical + scan.high + scan.medium + scan.low > 0:
            lic.used += 1
        scan.unlocked = True
        scan.license_key = lic.key
        db.commit()
        db.refresh(scan)
    return _serialize(scan)


@app.get("/api/license/{key}")
def license_status(key: str, db: Session = Depends(get_db)) -> dict:
    lic = db.get(models.License, _normalize_key(key))
    if lic is None or not lic.active:
        raise HTTPException(status_code=404, detail="Invalid license key")
    return {"valid": True, "remaining": max(0, lic.max_scans - lic.used)}


@app.delete("/api/scans/{scan_id}")
def delete_scan(scan_id: str, db: Session = Depends(get_db)) -> JSONResponse:
    scan = db.get(models.Scan, scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    db.delete(scan)
    db.commit()
    return JSONResponse({"deleted": scan_id})


# ---- Telegram Mini App API (X-Telegram-Init-Data) ----------------------------

class InvoiceRequest(BaseModel):
    scan_id: str


@app.get("/api/tg/me")
def tg_me(user: dict = Depends(require_tg_user), db: Session = Depends(get_db)) -> dict:
    lic = tg.user_license(db, user["id"])
    return {
        "user": {"id": user["id"], "first_name": user.get("first_name", "")},
        "license": {"key": lic.key, "remaining": lic.max_scans - lic.used} if lic else None,
        "stars": STARS_PRICE,
        "pack_scans": PACK_SCANS,
    }


@app.get("/api/tg/scans", response_model=list[ScanDetail])
def tg_scans(user: dict = Depends(require_tg_user), db: Session = Depends(get_db)):
    stmt = (select(models.Scan).where(models.Scan.tg_user_id == user["id"])
            .order_by(models.Scan.created_at.desc()).limit(30))
    return [_serialize(s) for s in db.scalars(stmt)]


@app.post("/api/tg/invoice")
async def tg_invoice(req: InvoiceRequest, user: dict = Depends(require_tg_user),
                     db: Session = Depends(get_db)) -> dict:
    scan = db.get(models.Scan, req.scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    if scan.unlocked:
        raise HTTPException(status_code=409, detail="Already unlocked")
    try:
        link = await tg.create_invoice_link(scan.id, user["id"])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Telegram error: {exc}") from exc
    return {"invoice_link": link}


@app.post("/tg/webhook")
async def tg_webhook(request: Request,
                     x_telegram_bot_api_secret_token: str | None = Header(default=None)):
    if not tg.ENABLED or not x_telegram_bot_api_secret_token or \
            not hmac.compare_digest(x_telegram_bot_api_secret_token, TG_WEBHOOK_SECRET):
        raise HTTPException(status_code=401, detail="Bad secret")
    try:
        update = await request.json()
    except Exception:  # noqa: BLE001
        return {"ok": True}
    db = SessionLocal()
    try:
        await tg.handle_update(update, db)
    except Exception:  # noqa: BLE001
        logging.exception("webhook update failed")
        db.rollback()
    finally:
        db.close()
    return {"ok": True}  # always 200 so Telegram doesn't retry forever


# ---- Crypto & manual payments ------------------------------------------------

class PayRequest(BaseModel):
    scan_id: str


class ManualPayRequest(BaseModel):
    scan_id: str
    contact: str | None = None
    note: str | None = None


def _order_out(o: models.Order) -> dict:
    return {
        "id": o.id, "method": o.method, "status": o.status, "amount": o.amount,
        "scan_id": o.scan_id, "pay_url": o.pay_url, "mini_app_url": o.mini_app_url,
        # The key is only revealed once paid; order ids are unguessable (uuid4).
        "license_key": o.license_key if o.status == "paid" else None,
        "details": o.details,
        "buyer_paid": bool(o.buyer_paid),
    }


def _payable_scan(db: Session, scan_id: str) -> models.Scan:
    scan = db.get(models.Scan, scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    if scan.unlocked:
        raise HTTPException(status_code=409, detail="Already unlocked")
    return scan


@app.post("/api/pay/crypto")
async def pay_crypto(req: PayRequest, db: Session = Depends(get_db),
                     user: dict | None = Depends(tg_user)) -> dict:
    if not pay.CRYPTO_ENABLED:
        raise HTTPException(status_code=404, detail="Crypto payments are not enabled")
    scan = _payable_scan(db, req.scan_id)
    try:
        order = await pay.create_crypto_order(db, scan, user["id"] if user else None)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logging.exception("createInvoice failed")
        raise HTTPException(status_code=502, detail=f"CryptoBot error: {exc}") from exc
    return _order_out(order)


@app.post("/api/pay/manual")
async def pay_manual(req: ManualPayRequest, db: Session = Depends(get_db),
                     user: dict | None = Depends(tg_user)) -> dict:
    if not pay.MANUAL_ENABLED:
        raise HTTPException(status_code=404, detail="Manual payments are not enabled")
    # Static requisites: the buyer already paid → proof required. Relay: just a request.
    if not pay.RELAY_ENABLED and not (req.note or "").strip():
        raise HTTPException(status_code=422, detail="Tell us how you paid (tx hash, card last 4 digits or payer name)")
    if user is None and not pay.RELAY_ENABLED and not (req.contact or "").strip():
        raise HTTPException(status_code=422, detail="Leave a contact so we can reach you")
    scan = _payable_scan(db, req.scan_id)
    order = await pay.create_manual_order(db, scan, user, req.contact, req.note)
    return _order_out(order)


class PaidRequest(BaseModel):
    note: str


@app.post("/api/pay/order/{order_id}/paid")
async def pay_order_paid(order_id: str, req: PaidRequest, db: Session = Depends(get_db),
                         user: dict | None = Depends(tg_user)) -> dict:
    order = db.get(models.Order, order_id)
    if order is None or order.method != "manual":
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status != "pending":
        return _order_out(order)
    if not req.note.strip():
        raise HTTPException(status_code=422, detail="Tell us how you paid (tx hash, card last 4 digits or payer name)")
    await pay.mark_buyer_paid(db, order, req.note.strip(), tg_user=user)
    return _order_out(order)


@app.get("/api/pay/order/{order_id}")
async def pay_order_status(order_id: str, db: Session = Depends(get_db)) -> dict:
    order = db.get(models.Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.method == "cryptobot" and order.status == "pending":
        order = await pay.refresh_crypto_order(db, order)
    return _order_out(order)


@app.post("/pay/cryptobot/webhook")
async def cryptobot_webhook(request: Request,
                            crypto_pay_api_signature: str | None = Header(default=None)):
    raw = await request.body()
    if not pay.verify_cp_signature(raw, crypto_pay_api_signature):
        raise HTTPException(status_code=401, detail="Bad signature")
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return {"ok": True}
    db = SessionLocal()
    try:
        await pay.handle_cp_webhook(db, body)
    except Exception:  # noqa: BLE001
        logging.exception("cryptobot webhook failed")
        db.rollback()
    finally:
        db.close()
    return {"ok": True}


# ---- Admin API (X-Admin-Token) -----------------------------------------------

@app.get("/api/admin/orders", dependencies=[Depends(require_admin)])
def admin_list_orders(status: str | None = None, db: Session = Depends(get_db)) -> list[dict]:
    stmt = select(models.Order).order_by(models.Order.created_at.desc()).limit(200)
    if status:
        stmt = stmt.where(models.Order.status == status)
    return [{**_order_out(o), "contact": o.contact, "note": o.note, "tg_user_id": o.tg_user_id,
             "license_key": o.license_key, "created_at": o.created_at.isoformat()}
            for o in db.scalars(stmt)]


@app.post("/api/admin/orders/{order_id}/approve", dependencies=[Depends(require_admin)])
async def admin_approve_order(order_id: str, db: Session = Depends(get_db)) -> dict:
    lic = await pay.fulfill_order(db, order_id, source="admin api")
    if lic is None:
        raise HTTPException(status_code=409, detail="Order not found or not pending")
    return {"approved": order_id, "license_key": lic.key}


@app.post("/api/admin/orders/{order_id}/reject", dependencies=[Depends(require_admin)])
async def admin_reject_order(order_id: str, db: Session = Depends(get_db)) -> dict:
    if not await pay.reject_order(db, order_id):
        raise HTTPException(status_code=409, detail="Order not found or not pending")
    return {"rejected": order_id}

@app.post("/api/admin/licenses", response_model=LicenseOut,
          dependencies=[Depends(require_admin)])
def admin_create_license(req: LicenseCreate, db: Session = Depends(get_db)):
    lic = models.License(key=tg.new_key(), max_scans=req.max_scans, note=req.note)
    db.add(lic)
    db.commit()
    db.refresh(lic)
    return lic


@app.get("/api/admin/licenses", response_model=list[LicenseOut],
         dependencies=[Depends(require_admin)])
def admin_list_licenses(db: Session = Depends(get_db)):
    return list(db.scalars(select(models.License).order_by(models.License.created_at.desc())))


@app.post("/api/admin/licenses/{key}/revoke", response_model=LicenseOut,
          dependencies=[Depends(require_admin)])
def admin_revoke_license(key: str, db: Session = Depends(get_db)):
    lic = db.get(models.License, _normalize_key(key))
    if lic is None:
        raise HTTPException(status_code=404, detail="License not found")
    lic.active = False
    db.commit()
    db.refresh(lic)
    return lic


@app.get("/api/admin/scans", response_model=list[ScanSummary],
         dependencies=[Depends(require_admin)])
def admin_list_scans(limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db)):
    stmt = select(models.Scan).order_by(models.Scan.created_at.desc()).limit(limit)
    return list(db.scalars(stmt))


@app.get("/api/admin/payments", dependencies=[Depends(require_admin)])
def admin_list_payments(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(models.Payment).order_by(models.Payment.created_at.desc()).limit(200))
    return [{"charge_id": p.charge_id, "tg_user_id": p.tg_user_id, "scan_id": p.scan_id,
             "stars": p.stars, "license_key": p.license_key,
             "created_at": p.created_at.isoformat()} for p in rows]


# ---- Pages -------------------------------------------------------------------

@app.get("/")
def landing() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/app")
def scanner_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "app.html")


@app.get("/tg")
def tg_redirect() -> RedirectResponse:
    return RedirectResponse("/tg/")


@app.get("/tg/")
def tg_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "tg" / "index.html")


# Serve CSS/JS/assets. Mounted last so it doesn't shadow the routes above.
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
