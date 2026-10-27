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
from . import telegram as tg
from .config import (
    ADMIN_TOKEN,
    APP_NAME,
    APP_VERSION,
    PACK_SCANS,
    PAYMENT_URL,
    PRICE_LABEL,
    STARS_PRICE,
    TG_WEBHOOK_SECRET,
)
from .database import SessionLocal, get_db, init_db
from .scanner import run_scan
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


# ---- Helpers -----------------------------------------------------------------

def _serialize(scan: models.Scan) -> dict:
    """Build the API response; strip details unless the scan is unlocked."""
    issues = scan.critical + scan.high + scan.medium + scan.low
    data = ScanSummary.model_validate(scan).model_dump()
    data.update({
        "error": scan.error,
        "issues": issues,
        "locked": not scan.unlocked,
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


@app.get("/api/pricing")
def pricing() -> dict:
    return {
        "price": PRICE_LABEL,
        "payment_url": PAYMENT_URL or None,
        "stars": STARS_PRICE,
        "pack_scans": PACK_SCANS,
        "telegram": tg.ENABLED,
        "bot_username": tg.BOT_USERNAME or None,
    }


@app.post("/api/scan", response_model=ScanDetail)
async def create_scan(req: ScanRequest, db: Session = Depends(get_db),
                      user: dict | None = Depends(tg_user)) -> dict:
    if not req.config.projectId:
        raise HTTPException(status_code=422, detail="config.projectId is required")

    # Pick a license BEFORE spending time on the scan: an explicit key wins,
    # otherwise a Telegram user's own paid license is used automatically.
    lic = None
    if req.license_key:
        lic = _check_license(db, req.license_key)
    elif user is not None:
        lic = tg.user_license(db, user["id"])

    result = await run_scan(req.config, req.collections)

    scan = models.Scan(
        project_id=result["project_id"],
        target_label=req.label,
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


# ---- Admin API (X-Admin-Token) -----------------------------------------------

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
