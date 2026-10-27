"""Telegram integration: Bot API calls, Mini App auth, Stars payments, webhook.

Payments use Telegram Stars (currency "XTR") — the only allowed way to sell
digital goods inside Telegram. After a successful payment the bot:
  1. creates a license (PACK_SCANS scans) owned by the Telegram user,
  2. unlocks the scan the user paid from (spending 1 scan),
  3. sends the key in chat so it also works on the website.
"""
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from urllib.parse import parse_qsl

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from .config import (
    BOT_TOKEN,
    PACK_SCANS,
    PUBLIC_URL,
    STARS_PRICE,
    SUPPORT_CONTACT,
    TG_WEBHOOK_SECRET,
)

log = logging.getLogger("vibeguard.tg")

ENABLED = bool(BOT_TOKEN)
INIT_DATA_MAX_AGE = 24 * 3600

# Filled from getMe on startup (or BOT_USERNAME env) — used for t.me links on the landing.
BOT_USERNAME = os.getenv("BOT_USERNAME", "").strip().lstrip("@")


# ---- Bot API -----------------------------------------------------------------

async def call(method: str, **params) -> dict:
    """Call a Bot API method. Returns `result`, raises on API error."""
    if not ENABLED:
        raise RuntimeError("BOT_TOKEN is not configured")
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(f"https://api.telegram.org/bot{BOT_TOKEN}/{method}", json=params)
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"{method}: {data.get('description', resp.status_code)}")
    return data["result"]


async def safe_call(method: str, **params) -> dict | None:
    try:
        return await call(method, **params)
    except Exception as exc:  # noqa: BLE001
        log.warning("telegram %s failed: %s", method, exc)
        return None


def webapp_url() -> str:
    return f"{PUBLIC_URL}/tg/" if PUBLIC_URL else ""


async def setup_bot() -> None:
    """Register webhook, commands and the menu button. Runs on startup."""
    global BOT_USERNAME
    if not ENABLED:
        return
    me = await safe_call("getMe")
    if me and me.get("username"):
        BOT_USERNAME = me["username"]
    if not PUBLIC_URL:
        log.warning("BOT_TOKEN set but PUBLIC_URL unknown — webhook not registered")
        return
    await safe_call(
        "setWebhook",
        url=f"{PUBLIC_URL}/tg/webhook",
        secret_token=TG_WEBHOOK_SECRET,
        allowed_updates=["message", "pre_checkout_query", "callback_query"],
        drop_pending_updates=False,
    )
    await safe_call("setMyCommands", commands=[
        {"command": "start", "description": "Open VibeGuard"},
        {"command": "key", "description": "My license keys"},
        {"command": "paysupport", "description": "Payment support"},
        {"command": "help", "description": "How it works"},
    ])
    await safe_call("setChatMenuButton", menu_button={
        "type": "web_app", "text": "Scan", "web_app": {"url": webapp_url()},
    })
    log.info("telegram bot configured for %s", PUBLIC_URL)


# ---- Mini App auth -----------------------------------------------------------

def validate_init_data(init_data: str | None) -> dict | None:
    """Verify Telegram.WebApp.initData (HMAC-SHA256). Returns the user dict or None."""
    if not ENABLED or not init_data:
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError:
        return None
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        return None
    check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        return None
    try:
        if time.time() - int(pairs.get("auth_date", "0")) > INIT_DATA_MAX_AGE:
            return None
        user = json.loads(pairs.get("user", "{}"))
    except (ValueError, TypeError):
        return None
    return user if isinstance(user, dict) and user.get("id") else None


# ---- Licenses ----------------------------------------------------------------

def new_key() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I confusion
    parts = ["".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3)]
    return "VG-" + "-".join(parts)


def user_license(db: Session, tg_user_id: int) -> models.License | None:
    """The user's active license with scans left (newest first)."""
    stmt = (select(models.License)
            .where(models.License.tg_user_id == tg_user_id, models.License.active.is_(True),
                   models.License.used < models.License.max_scans)
            .order_by(models.License.created_at.desc()))
    return db.scalars(stmt).first()


async def create_invoice_link(scan_id: str, tg_user_id: int) -> str:
    return await call(
        "createInvoiceLink",
        title="VibeGuard — full security report",
        description=(f"Every hole in your Firebase app, proof, and copy-paste fixes. "
                     f"Includes {PACK_SCANS} full scans."),
        payload=f"vg:{scan_id}:{tg_user_id}",
        currency="XTR",
        prices=[{"label": "Full report", "amount": STARS_PRICE}],
    )


# ---- Webhook -----------------------------------------------------------------

def _open_app_markup(text: str = "🛡 Open VibeGuard") -> dict | None:
    url = webapp_url()
    if not url:
        return None
    return {"inline_keyboard": [[{"text": text, "web_app": {"url": url}}]]}


def esc(s: str) -> str:
    return (str(s or "")).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def send_text(chat_id: int, text: str) -> None:
    await _send(chat_id, text, with_button=True)


async def send_key_message(chat_id: int, lic: models.License) -> None:
    left = lic.max_scans - lic.used
    await _send(chat_id, (
        "✅ <b>Payment received — full report unlocked.</b>\n\n"
        f"Your key: <code>{lic.key}</code>\n"
        f"{left} more full scans left. In the app they unlock automatically; "
        "on the website paste the key under the report."
    ), with_button=True)


async def _send(chat_id: int, text: str, with_button: bool = True) -> None:
    params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
              "disable_web_page_preview": True}
    markup = _open_app_markup() if with_button else None
    if markup:
        params["reply_markup"] = markup
    await safe_call("sendMessage", **params)


def _parse_payload(payload: str) -> tuple[str, int] | None:
    parts = (payload or "").split(":")
    if len(parts) != 3 or parts[0] != "vg":
        return None
    try:
        return parts[1], int(parts[2])
    except ValueError:
        return None


async def handle_update(update: dict, db: Session) -> None:
    # 1) Pre-checkout: must be answered within 10s.
    pcq = update.get("pre_checkout_query")
    if pcq:
        parsed = _parse_payload(pcq.get("invoice_payload", ""))
        ok = (parsed is not None and pcq.get("currency") == "XTR"
              and parsed[1] == pcq.get("from", {}).get("id")
              and db.get(models.Scan, parsed[0]) is not None)
        params = {"pre_checkout_query_id": pcq["id"], "ok": ok}
        if not ok:
            params["error_message"] = "This scan is no longer available. Run a new scan and try again."
        await safe_call("answerPreCheckoutQuery", **params)
        return

    # 1b) Admin pressed ✅ / ❌ on a manual payment.
    cq = update.get("callback_query")
    if cq:
        await _on_callback(db, cq)
        return

    msg = update.get("message")
    if not msg:
        return
    chat_id = msg["chat"]["id"]
    user_id = msg.get("from", {}).get("id")

    # 2) Successful payment → license + unlock + send key.
    sp = msg.get("successful_payment")
    if sp:
        await _on_payment(db, chat_id, user_id, sp)
        return

    # 3) Commands.
    text = (msg.get("text") or "").strip()
    cmd = text.split()[0].split("@")[0].lower() if text.startswith("/") else ""

    if cmd in ("/start", "/help") or not cmd:
        await _send(chat_id, (
            "<b>🛡 VibeGuard</b> — security scanner for Firebase &amp; vibe-coded apps.\n\n"
            "Paste your <code>firebaseConfig</code> and in seconds you'll know if anyone "
            "can read or wipe your database, list your storage, or sign up without limits.\n\n"
            "• <b>Free:</b> grade + how many holes you have\n"
            f"• <b>Full report:</b> every hole, proof and copy-paste fixes ({PACK_SCANS} scans) — "
            f"pay with ⭐ Stars, crypto or bank transfer\n\n"
            "Tap the button to start 👇"
        ))
    elif cmd == "/key":
        lics = list(db.scalars(select(models.License)
                               .where(models.License.tg_user_id == user_id)
                               .order_by(models.License.created_at.desc()).limit(5)))
        if not lics:
            await _send(chat_id, "You don't have a license yet. Unlock a full report in the app to get one.")
        else:
            lines = [f"<code>{l.key}</code> — {max(0, l.max_scans - l.used)} of {l.max_scans} scans left"
                     + ("" if l.active else " (revoked)") for l in lics]
            await _send(chat_id, "<b>Your keys</b>\n" + "\n".join(lines)
                        + "\n\nKeys also work on the website.")
    elif cmd == "/myid":
        await _send(chat_id, f"Your Telegram ID: <code>{user_id}</code>\n"
                             "Put it into ADMIN_TG_ID to receive manual payment requests.", with_button=False)
    elif cmd == "/paysupport":
        contact = SUPPORT_CONTACT or "reply to this chat"
        await _send(chat_id, (
            "<b>Payment support</b>\n"
            f"Problems with a payment or a refund request? Contact: {contact}\n"
            "Include the date of purchase and your key if you have one."
        ), with_button=False)
    else:
        await _send(chat_id, "Use the button below to scan your app, or /help.")


async def _on_payment(db: Session, chat_id: int, user_id: int, sp: dict) -> None:
    charge_id = sp.get("telegram_payment_charge_id") or ""
    if not charge_id:
        return
    if db.get(models.Payment, charge_id) is not None:
        return  # already processed (webhook retry)

    parsed = _parse_payload(sp.get("invoice_payload", ""))
    scan_id = parsed[0] if parsed else None

    lic = models.License(key=new_key(), max_scans=PACK_SCANS, used=0,
                         note=f"tg:{user_id} stars:{sp.get('total_amount')}",
                         tg_user_id=user_id)
    db.add(lic)

    scan = db.get(models.Scan, scan_id) if scan_id else None
    if scan is not None and not scan.unlocked:
        scan.unlocked = True
        scan.license_key = lic.key
        lic.used = 1

    db.add(models.Payment(charge_id=charge_id, tg_user_id=user_id, scan_id=scan_id,
                          stars=int(sp.get("total_amount") or 0), license_key=lic.key))
    db.commit()

    await send_key_message(chat_id, lic)


async def _on_callback(db: Session, cq: dict) -> None:
    from . import payments  # lazy: payments imports this module
    from .config import ADMIN_TG_ID

    data = cq.get("data") or ""
    from_id = (cq.get("from") or {}).get("id")
    msg = cq.get("message") or {}

    if not data.startswith("ord:"):
        await safe_call("answerCallbackQuery", callback_query_id=cq["id"])
        return
    if not ADMIN_TG_ID or from_id != ADMIN_TG_ID:
        await safe_call("answerCallbackQuery", callback_query_id=cq["id"], text="Not allowed", show_alert=True)
        return

    _, action, order_id = (data.split(":", 2) + ["", ""])[:3]
    if action == "ok":
        lic = await payments.fulfill_order(db, order_id, source="manual approve")
        result = f"✅ Approved — key {lic.key}" if lic else "ℹ️ Already processed"
    elif action == "no":
        result = "❌ Rejected" if await payments.reject_order(db, order_id) else "ℹ️ Already processed"
    else:
        result = "Unknown action"

    await safe_call("answerCallbackQuery", callback_query_id=cq["id"], text=result[:190])
    if msg.get("chat") and msg.get("message_id"):
        # Plain text edit: the original HTML formatting is gone in msg["text"], so no parse_mode.
        await safe_call("editMessageText", chat_id=msg["chat"]["id"], message_id=msg["message_id"],
                        text=(msg.get("text") or "") + "\n\n" + result)
