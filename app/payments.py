"""Crypto (@CryptoBot / Crypto Pay API) and manual (bank / wallet transfer) payments.

Flow for both methods:
    create Order(pending) → buyer pays → fulfill_order():
        1. new License with PACK_SCANS scans (owned by the Telegram user if any)
        2. unlock the scan the buyer paid from
        3. send the key in Telegram (if the buyer came from Telegram)

CryptoBot orders are confirmed automatically: by webhook, by the buyer's page
polling /api/pay/order/{id}, and by a background sweep — whichever comes first.
fulfill_order() is race-safe: only one caller can flip pending → paid.

Manual orders are confirmed by the admin (✅ button in Telegram, or the admin API).
"""
import asyncio
import hashlib
import hmac
import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from . import models
from . import telegram as tg
from .config import (
    ADMIN_TG_ID,
    CRYPTOPAY_ASSETS,
    CRYPTOPAY_TESTNET,
    CRYPTOPAY_TOKEN,
    MANUAL_DETAILS,
    PACK_SCANS,
    PRICE_USD,
    PUBLIC_URL,
)
from .database import SessionLocal

log = logging.getLogger("vibeguard.pay")

CRYPTO_ENABLED = bool(CRYPTOPAY_TOKEN)
CP_BASE = "https://testnet-pay.crypt.bot/api" if CRYPTOPAY_TESTNET else "https://pay.crypt.bot/api"


# ---- Crypto Pay API ------------------------------------------------------------

async def cp_call(method: str, **params) -> dict | list:
    if not CRYPTO_ENABLED:
        raise RuntimeError("CRYPTOPAY_TOKEN is not configured")
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(f"{CP_BASE}/{method}", json=params,
                                 headers={"Crypto-Pay-API-Token": CRYPTOPAY_TOKEN})
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"{method}: {data.get('error', resp.status_code)}")
    return data["result"]


def verify_cp_signature(raw_body: bytes, signature: str | None) -> bool:
    """crypto-pay-api-signature = hex(HMAC-SHA256(key=SHA256(token), msg=raw body))."""
    if not CRYPTO_ENABLED or not signature:
        return False
    secret = hashlib.sha256(CRYPTOPAY_TOKEN.encode()).digest()
    expected = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


async def create_crypto_order(db: Session, scan: models.Scan, tg_user_id: int | None) -> models.Order:
    order = models.Order(method="cryptobot", scan_id=scan.id, tg_user_id=tg_user_id, amount=PRICE_USD)
    db.add(order)
    db.flush()  # get order.id

    params = {
        "currency_type": "fiat",
        "fiat": "USD",
        "amount": PRICE_USD,
        "accepted_assets": CRYPTOPAY_ASSETS,
        "description": f"VibeGuard — full security report + {PACK_SCANS} full scans",
        "payload": order.id,
        "expires_in": 3600,
        "allow_comments": False,
    }
    back = _back_url(order)
    if back:
        params.update({"paid_btn_name": "callback", "paid_btn_url": back})

    inv = await cp_call("createInvoice", **params)
    order.invoice_id = str(inv["invoice_id"])
    order.pay_url = inv.get("web_app_invoice_url") or inv.get("bot_invoice_url")
    order.mini_app_url = inv.get("mini_app_invoice_url") or inv.get("bot_invoice_url")
    db.commit()
    db.refresh(order)
    return order


def _back_url(order: models.Order) -> str:
    """Where CryptoBot's 'paid' button sends the buyer."""
    if order.tg_user_id and tg.BOT_USERNAME:
        return f"https://t.me/{tg.BOT_USERNAME}"
    if PUBLIC_URL:
        return f"{PUBLIC_URL}/app?order={order.id}"
    return ""


async def refresh_crypto_order(db: Session, order: models.Order) -> models.Order:
    """Ask CryptoBot about a pending invoice; fulfill if it's paid."""
    if order.method != "cryptobot" or order.status != "pending" or not order.invoice_id:
        return order
    try:
        res = await cp_call("getInvoices", invoice_ids=order.invoice_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("getInvoices failed: %s", exc)
        return order
    items = res.get("items", []) if isinstance(res, dict) else res
    inv = next((i for i in items if str(i.get("invoice_id")) == order.invoice_id), None)
    if inv is None:
        return order
    if inv.get("status") == "paid":
        await fulfill_order(db, order.id, source=f"cryptobot {inv.get('paid_asset', '')} {inv.get('paid_amount', '')}".strip())
        db.refresh(order)
    elif inv.get("status") == "expired":
        db.execute(update(models.Order).where(models.Order.id == order.id, models.Order.status == "pending")
                   .values(status="expired"))
        db.commit()
        db.refresh(order)
    return order


async def handle_cp_webhook(db: Session, update_body: dict) -> None:
    if update_body.get("update_type") != "invoice_paid":
        return
    inv = update_body.get("payload") or {}
    order_id = inv.get("payload")
    order = db.get(models.Order, order_id) if order_id else None
    if order is None or order.invoice_id != str(inv.get("invoice_id")):
        log.warning("cryptobot webhook for unknown order %s", order_id)
        return
    await fulfill_order(db, order.id, source=f"cryptobot {inv.get('paid_asset', '')} {inv.get('paid_amount', '')}".strip())


# ---- Manual (requisites) -------------------------------------------------------
#
# Two modes:
#   static — MANUAL_DETAILS is set: the buyer sees your requisites right away.
#   relay  — MANUAL_DETAILS is empty but the bot + ADMIN_TG_ID are set: the buyer
#            requests details, you REPLY to the bot's notification with them, and the
#            bot forwards your reply to the buyer (Telegram chat and/or the web page).

RELAY_ENABLED = bool(tg.ENABLED and ADMIN_TG_ID and not MANUAL_DETAILS)
MANUAL_ENABLED = bool(MANUAL_DETAILS) or RELAY_ENABLED


def _buyer_label(order: models.Order, tg_user: dict | None) -> str:
    if tg_user:
        uname = tg_user.get("username")
        who = f"@{uname}" if uname else f"tg id {tg_user['id']}"
        return f"{tg.esc(who)} ({tg.esc(tg_user.get('first_name', ''))})"
    return "website visitor" + (f", contact: {tg.esc(order.contact)}" if order.contact else "")


def _approve_kb(order_id: str) -> dict:
    return {"inline_keyboard": [[
        {"text": "✅ Approve", "callback_data": f"ord:ok:{order_id}"},
        {"text": "❌ Reject", "callback_data": f"ord:no:{order_id}"},
    ]]}


async def create_manual_order(db: Session, scan: models.Scan, tg_user: dict | None,
                              contact: str | None, note: str | None) -> models.Order:
    """static mode: note = proof (buyer already paid). relay mode: note may be empty (= request details)."""
    existing = db.scalars(select(models.Order).where(
        models.Order.scan_id == scan.id, models.Order.method == "manual",
        models.Order.status == "pending")).first()
    if existing:
        if contact:
            existing.contact = contact[:255]
            db.commit()
        if note:
            await mark_buyer_paid(db, existing, note)
        return existing

    order = models.Order(method="manual", scan_id=scan.id, amount=PRICE_USD,
                         tg_user_id=tg_user["id"] if tg_user else None,
                         contact=(contact or "")[:255] or None)
    db.add(order)
    db.commit()
    db.refresh(order)

    if note:  # static mode: buyer paid to the published requisites
        await mark_buyer_paid(db, order, note, scan=scan, tg_user=tg_user)
    else:     # relay mode: ask the admin for requisites
        await notify_admin_request(db, order, scan, tg_user)
    return order


async def notify_admin_request(db: Session, order: models.Order, scan: models.Scan, tg_user: dict | None) -> None:
    if not (tg.ENABLED and ADMIN_TG_ID):
        log.warning("manual order %s: no BOT_TOKEN/ADMIN_TG_ID — cannot relay details", order.id)
        return
    text = (
        "🧾 <b>Payment details requested</b>\n\n"
        f"Amount: <b>${tg.esc(order.amount)}</b>\n"
        f"Buyer: {_buyer_label(order, tg_user)}\n"
        f"Project: <code>{tg.esc(scan.project_id)}</code>\n"
        f"Order: <code>{order.id}</code>\n\n"
        "↩️ <b>Reply to this message</b> with your card / bank / wallet details — "
        "I'll forward them to the buyer."
    )
    res = await tg.safe_call("sendMessage", chat_id=ADMIN_TG_ID, text=text, parse_mode="HTML",
                             reply_markup={"inline_keyboard": [[
                                 {"text": "❌ Cancel request", "callback_data": f"ord:no:{order.id}"}]]})
    if res and res.get("message_id"):
        order.admin_msg_id = int(res["message_id"])
        db.commit()


async def set_order_details(db: Session, admin_msg_id: int, details: str) -> models.Order | None:
    """Admin replied to a request → store details and forward them to the buyer."""
    order = db.scalars(select(models.Order).where(models.Order.admin_msg_id == admin_msg_id)).first()
    if order is None or order.status != "pending":
        return None
    order.details = details[:2000]
    db.commit()
    if order.tg_user_id:
        await tg.safe_call("sendMessage", chat_id=order.tg_user_id, parse_mode="HTML",
                           text=("💳 <b>Payment details</b>\n\n"
                                 f"Amount: <b>${tg.esc(order.amount)}</b>\n\n"
                                 f"{tg.esc(order.details)}\n\n"
                                 "After paying, tap <b>I've paid</b> in the app or send a screenshot here."),
                           reply_markup=tg.open_app_markup("🛡 I've paid — open VibeGuard"))
    return order


async def mark_buyer_paid(db: Session, order: models.Order, note: str,
                          scan: models.Scan | None = None, tg_user: dict | None = None) -> None:
    """Buyer says they paid → ask the admin to confirm (✅ / ❌)."""
    order.note = (note or "")[:1000] or order.note
    first_time = not order.buyer_paid
    order.buyer_paid = True
    db.commit()
    if not (tg.ENABLED and ADMIN_TG_ID) or (not first_time and not note):
        if not (tg.ENABLED and ADMIN_TG_ID):
            log.warning("manual order %s paid but ADMIN_TG_ID/BOT_TOKEN not set — approve via admin API", order.id)
        return
    scan = scan or (db.get(models.Scan, order.scan_id) if order.scan_id else None)
    text = (
        "💰 <b>Buyer says they paid</b>\n\n"
        f"Amount: <b>${tg.esc(order.amount)}</b>\n"
        f"Buyer: {_buyer_label(order, tg_user) if tg_user else (('tg id ' + str(order.tg_user_id)) if order.tg_user_id else _buyer_label(order, None))}\n"
        f"Proof: <code>{tg.esc(order.note or '—')}</code>\n"
        f"Project: <code>{tg.esc(scan.project_id if scan else '—')}</code>\n"
        f"Order: <code>{order.id}</code>\n\n"
        "Check your account, then approve or reject:"
    )
    await tg.safe_call("sendMessage", chat_id=ADMIN_TG_ID, text=text, parse_mode="HTML",
                       reply_markup=_approve_kb(order.id))


async def forward_buyer_proof(db: Session, msg: dict) -> bool:
    """A buyer with a pending manual order sent something to the bot (e.g. a screenshot)."""
    if not ADMIN_TG_ID:
        return False
    uid = (msg.get("from") or {}).get("id")
    order = db.scalars(select(models.Order).where(
        models.Order.tg_user_id == uid, models.Order.method == "manual",
        models.Order.status == "pending").order_by(models.Order.created_at.desc())).first()
    if order is None:
        return False
    await tg.safe_call("forwardMessage", chat_id=ADMIN_TG_ID, from_chat_id=msg["chat"]["id"],
                       message_id=msg["message_id"])
    await tg.safe_call("sendMessage", chat_id=ADMIN_TG_ID, parse_mode="HTML",
                       text=f"📎 Proof from the buyer · order <code>{order.id}</code> · ${tg.esc(order.amount)}",
                       reply_markup=_approve_kb(order.id))
    order.buyer_paid = True
    db.commit()
    await tg.safe_call("sendMessage", chat_id=msg["chat"]["id"],
                       text="👍 Got it — we'll check the payment and send your key here.")
    return True


async def reject_order(db: Session, order_id: str) -> bool:
    res = db.execute(update(models.Order).where(models.Order.id == order_id, models.Order.status == "pending")
                     .values(status="rejected"))
    db.commit()
    if res.rowcount != 1:
        return False
    order = db.get(models.Order, order_id)
    if order and order.tg_user_id:
        await tg.send_text(order.tg_user_id,
                           "❌ We couldn't confirm your payment. If you did pay, reply here with a screenshot "
                           "or use /paysupport.")
    return True


# ---- Fulfillment ---------------------------------------------------------------

async def fulfill_order(db: Session, order_id: str, source: str = "") -> models.License | None:
    """pending → paid exactly once; create license, unlock scan, notify buyer."""
    res = db.execute(update(models.Order).where(models.Order.id == order_id, models.Order.status == "pending")
                     .values(status="paid"))
    if res.rowcount != 1:
        db.rollback()
        return None  # someone else already fulfilled it (or it isn't pending)

    order = db.get(models.Order, order_id)
    lic = models.License(key=tg.new_key(), max_scans=PACK_SCANS, used=0,
                         note=f"{order.method} ${order.amount} {source}".strip()[:255],
                         tg_user_id=order.tg_user_id)
    db.add(lic)
    scan = db.get(models.Scan, order.scan_id) if order.scan_id else None
    if scan is not None and not scan.unlocked:
        scan.unlocked = True
        scan.license_key = lic.key
        if scan.critical + scan.high + scan.medium + scan.low > 0:
            lic.used = 1
    order.license_key = lic.key
    db.commit()
    log.info("order %s fulfilled → %s", order_id, lic.key)

    if order.tg_user_id:
        await tg.send_key_message(order.tg_user_id, lic)
    return lic


# ---- Background sweep ----------------------------------------------------------

async def sweep_loop() -> None:
    """Every 60s, check pending CryptoBot invoices from the last 2 hours.

    Makes payments go through even if the CryptoBot webhook isn't configured and
    the buyer closed the page right after paying.
    """
    while True:
        await asyncio.sleep(60)
        try:
            db = SessionLocal()
            try:
                since = datetime.now(timezone.utc) - timedelta(hours=2)
                pending = list(db.scalars(select(models.Order).where(
                    models.Order.method == "cryptobot", models.Order.status == "pending",
                    models.Order.created_at >= since).limit(50)))
                for o in pending:
                    await refresh_crypto_order(db, o)
            finally:
                db.close()
        except Exception:  # noqa: BLE001
            log.exception("payment sweep failed")
