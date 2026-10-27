"""Runtime configuration, loaded from environment variables."""
import hashlib
import os

from dotenv import load_dotenv

load_dotenv()


def _normalize_db_url(url: str) -> str:
    """Railway/Heroku give postgres://; SQLAlchemy needs postgresql+psycopg2://."""
    if not url:
        return ""
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


# Database. Falls back to a local SQLite file when DATABASE_URL is unset.
DATABASE_URL = _normalize_db_url(os.getenv("DATABASE_URL", "").strip()) \
    or "sqlite:///./vibeguard.db"

# Scanner tuning
SCAN_TIMEOUT = float(os.getenv("SCAN_TIMEOUT", "8"))

# Admin token for /api/admin/* (create license keys, see all scans).
# If empty, admin endpoints are disabled.
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "").strip()

# Monetization: where the "Buy full report" button sends people
# (Stripe Payment Link, Gumroad, Lemon Squeezy, Telegram…) and the price shown.
PAYMENT_URL = os.getenv("PAYMENT_URL", "").strip()
PRICE_LABEL = os.getenv("PRICE_LABEL", "$9").strip()

# ---- Telegram ----------------------------------------------------------------
# Bot token from @BotFather. Empty → bot / Mini App payments are disabled.
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Public https base URL of this deployment (for the webhook and Mini App button).
# On Railway it's derived automatically from RAILWAY_PUBLIC_DOMAIN.
_railway_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip()
PUBLIC_URL = (os.getenv("PUBLIC_URL", "").strip()
              or os.getenv("RENDER_EXTERNAL_URL", "").strip()   # set automatically on Render
              or (f"https://{_railway_domain}" if _railway_domain else "")).rstrip("/")

# Secret Telegram sends in X-Telegram-Bot-Api-Secret-Token. Derived from the bot
# token if not set, so it is stable across restarts.
TG_WEBHOOK_SECRET = os.getenv("TG_WEBHOOK_SECRET", "").strip() or (
    hashlib.sha256(("vg-webhook:" + BOT_TOKEN).encode()).hexdigest()[:48] if BOT_TOKEN else ""
)

# Price of the full report in Telegram Stars, and how many unlocked scans one purchase gives.
STARS_PRICE = int(os.getenv("STARS_PRICE", "450"))
PACK_SCANS = int(os.getenv("PACK_SCANS", "10"))

# Shown on /paysupport (required by Telegram for bots that take payments).
SUPPORT_CONTACT = os.getenv("SUPPORT_CONTACT", "").strip()

APP_NAME = "VibeGuard"
APP_VERSION = "1.2.0"
