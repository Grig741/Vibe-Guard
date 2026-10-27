# VibeGuard 🛡️

Security scanner for **Firebase / vibe-coded apps**. Paste your `firebaseConfig`
and VibeGuard probes your project the way an attacker would — then grades it and
tells you exactly what to fix.

It catches the mistakes that ship in rushed/AI-generated apps:

| Check | Severity |
|---|---|
| Firestore readable by anyone | High |
| Firestore writable by anyone | Critical |
| Realtime Database open read | High |
| Realtime Database open write | Critical |
| Storage bucket files listable | High |
| Open email/password sign-up | Medium |
| Anonymous auth enabled | Medium |
| Unrestricted web API key | Low |

All probes are **read-only or self-cleaning** (write tests create a
`__vibeguard_probe__` entry and delete it; auth tests create a throwaway user
and delete it). The API key is **never stored** — only the project ID, the score
and the findings are saved.

> ⚠️ Scan only Firebase projects you own or are explicitly authorized to test.

## Free vs paid

| | Free | Full report (license key) |
|---|---|---|
| Grade & score | ✅ | ✅ |
| How many holes, per severity | ✅ | ✅ |
| Which holes exactly | — | ✅ |
| Evidence (the request that got through) | — | ✅ |
| Step-by-step fix + ready rules | — | ✅ |

Locked scans have their findings **stripped on the server** — nothing leaks via DevTools.

**How selling works**

1. Set `PAYMENT_URL` (e.g. a Stripe Payment Link) and `PRICE_LABEL`.
2. A buyer pays → you issue a key:
   ```bash
   curl -X POST https://YOUR-DOMAIN/api/admin/licenses \
     -H "X-Admin-Token: $ADMIN_TOKEN" -H "Content-Type: application/json" \
     -d '{"max_scans": 10, "note": "buyer@email.com"}'
   # → {"key": "VG-ABCD-EFGH-JKLM", ...}
   ```
3. They paste the key under the report → it unlocks. The key is saved in their
   browser, so their next scans come back unlocked automatically until the
   `max_scans` limit is spent.

Admin endpoints (all need `X-Admin-Token`): `POST /api/admin/licenses`,
`GET /api/admin/licenses`, `POST /api/admin/licenses/{key}/revoke`, `GET /api/admin/scans`.

---

## Run locally

```bash
cd vibeguard
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # optional; defaults are fine
uvicorn app.main:app --reload
```

Open http://localhost:8000. With no `DATABASE_URL`, it uses a local SQLite file
(`vibeguard.db`) — zero setup.

### Docker

```bash
docker build -t vibeguard .
docker run -p 8000:8000 vibeguard
```

---

## Deploy to Railway (recommended)

1. Push this folder to a GitHub repo.
2. On [railway.app](https://railway.app) → **New Project → Deploy from GitHub repo** → pick the repo.
   Railway reads `railway.json` and builds the `Dockerfile` automatically.
3. (For persistent history) **New → Database → Add PostgreSQL**. Railway injects
   `DATABASE_URL` into the service — VibeGuard picks it up with no code changes.
   Without it, data lives in SQLite inside the container and resets on redeploy.
4. Open the generated domain. Done.

Optional env vars (Settings → Variables):

| Var | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | SQLite | Postgres connection (auto-set by the Railway plugin) |
| `SCAN_TIMEOUT` | `8` | Per-request probe timeout (seconds) |
| `ADMIN_TOKEN` | *(empty)* | **Set this.** Secret for issuing license keys |
| `PAYMENT_URL` | *(empty)* | Link for the "Get full report" button |
| `PRICE_LABEL` | `$9` | Price shown on the button |

## Getting paid: card, bank transfer, crypto wallet

1. Set `MANUAL_DETAILS` — your requisites, shown to buyers (use `\n` for new lines), e.g.
   `Card (AMD): 4318 …\nUSDT TRC20: TQ7x…`
2. Send `/myid` to your bot and put the number into `ADMIN_TG_ID`.
3. A buyer taps **Get full report → Card / bank / crypto wallet**, transfers the money and
   presses **I've paid** with a proof (tx hash or card last 4 digits + name).
4. You get a Telegram message with **✅ Approve / ❌ Reject**. Check your account → ✅.
   The buyer gets a key for `PACK_SCANS` full scans and the report unlocks by itself
   (in Telegram the key also arrives in the chat).

Without the bot you can approve via API: `GET /api/admin/orders?status=pending`,
`POST /api/admin/orders/{id}/approve` (header `X-Admin-Token`).

Optional extras: `CRYPTOPAY_TOKEN` (@CryptoBot, fully automatic crypto; webhook URL
`https://YOUR-DOMAIN/pay/cryptobot/webhook`, works without it too) and Telegram Stars
(always on when `BOT_TOKEN` is set).

### Telegram bot + Mini App (Stars payments)

1. In Telegram open **@BotFather** → `/newbot` → copy the token.
2. Railway → Variables → add `BOT_TOKEN=<token>` and `SUPPORT_CONTACT=@your_username`.
   Generate a domain for the service (Settings → Networking) so `RAILWAY_PUBLIC_DOMAIN`
   exists — or set `PUBLIC_URL=https://your-domain` yourself.
3. Redeploy. On startup the app itself registers the webhook, the bot commands
   and the **Scan** menu button that opens the Mini App. Nothing else to configure.
4. (Optional) In @BotFather → `/newapp` to get a `t.me/<bot>/<app>` direct link,
   with Web App URL = `https://your-domain/tg/`.

Payments use **Telegram Stars** (`STARS_PRICE`, default 450). After paying, the
user gets a key for `PACK_SCANS` full scans in the chat; the report unlocks
automatically, and the same key works on the website. Payments are logged at
`GET /api/admin/payments`. Stars are withdrawn via @BotFather → Bot → Payments/Balance.

| Page | URL |
|---|---|
| Landing | `/` |
| Web scanner | `/app` |
| Telegram Mini App | `/tg/` |

| Var | Default | Purpose |
|---|---|---|
| `BOT_TOKEN` | *(empty)* | Enables bot, Mini App auth and Stars payments |
| `PUBLIC_URL` | from `RAILWAY_PUBLIC_DOMAIN` | Public https URL for the webhook |
| `STARS_PRICE` | `450` | Price of the full report in Stars |
| `PACK_SCANS` | `10` | Full scans included in one purchase |
| `SUPPORT_CONTACT` | *(empty)* | Shown on `/paysupport` (Telegram requires it) |

### Deploy anywhere else

Any host that runs a Dockerfile or a `Procfile` works (Render, Fly.io, Koyeb…).
The start command is:

```
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

---

## API

| Method | Path | Body / notes |
|---|---|---|
| `POST` | `/api/scan` | `{ "config": {...}, "collections": ["habits"], "label": "Clarity prod", "license_key": "VG-..." }` (key optional) |
| `GET` | `/api/scans/{id}` | report (findings only if unlocked) |
| `POST` | `/api/scans/{id}/unlock` | `{ "license_key": "VG-..." }` |
| `GET` | `/api/license/{key}` | scans left on a key |
| `GET` | `/api/pricing` | price + payment link |
| `DELETE` | `/api/scans/{id}` | delete a scan |
| `GET` | `/api/health` | liveness probe |

Interactive docs at `/docs` (Swagger).

```bash
curl -X POST http://localhost:8000/api/scan \
  -H "Content-Type: application/json" \
  -d '{"config":{"projectId":"my-app","apiKey":"AIza...","databaseURL":"https://my-app-default-rtdb.firebaseio.com","storageBucket":"my-app.appspot.com"}}'
```

---

## Stack

FastAPI · SQLAlchemy · httpx (async probes) · vanilla JS frontend · Postgres/SQLite.

## Project layout

```
vibeguard/
├── app/
│   ├── main.py          # FastAPI app + routes
│   ├── config.py        # env-based settings
│   ├── database.py      # engine / session / init
│   ├── models.py        # Scan, Finding
│   ├── schemas.py       # Pydantic I/O
│   ├── scanner/
│   │   ├── engine.py    # orchestration + scoring
│   │   ├── checks.py    # the actual Firebase probes
│   │   └── rules.py     # severity catalog + remediation
│   └── static/          # index.html, style.css, app.js
├── Dockerfile
├── railway.json
├── Procfile
└── requirements.txt
```
