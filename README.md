# VibeGuard 🛡️

Security scanner for **Firebase, Supabase & vibe-coded apps**. Give it your
app's **URL** — or paste a `firebaseConfig` / Supabase key — and VibeGuard
probes your project the way an attacker would, then grades it and tells you
exactly what to fix.

Three ways to scan:

* **URL** — VibeGuard fetches your live site, finds the Firebase/Supabase config
  in your bundle, sweeps the shipped JS for leaked secrets, and runs every
  applicable check.
* **firebaseConfig** — the classic deep Firebase scan.
* **Supabase URL + anon key** — RLS and storage checks.

It catches the mistakes that ship in rushed/AI-generated apps:

| Check | Severity |
|---|---|
| **Firebase** | |
| Firestore readable / writable by anyone | High / Critical |
| Realtime Database open read / write | High / Critical |
| Storage bucket files listable | High |
| Open email/password sign-up · anonymous auth | Medium |
| Unrestricted web API key | Low |
| **Supabase** | |
| `service_role` key shipped in the frontend | Critical |
| Table readable / writable by the anon key (RLS off) | High / Critical |
| Public storage bucket · exposed schema | High / Medium |
| **Website (URL scan)** | |
| Leaked API keys in the frontend (OpenAI, Stripe, AWS, GitHub…) | Critical–Medium |
| Public `.env` / `.git` / DB dumps | Critical |
| Production source maps · missing security headers | Low |

All active probes are **read-only or self-cleaning** (write tests create a
`__vibeguard_probe__` entry and delete it; auth tests create a throwaway user
and delete it). URL scans only ever issue GETs plus those self-cleaning probes,
and every outbound request is **SSRF-guarded** — private, loopback and
link-local addresses are refused on every redirect hop. Keys are **never
stored** — only the project ID, the score and the findings are saved.

> ⚠️ Scan only projects you own or are explicitly authorized to test.

**Passive by default.** Without `"authorized": true` (the *“This is my project”*
checkbox in the UI) only read-only checks run — no test writes, no sign-ups.
Scans started from the Telegram chat are always passive.

**Abuse limits** (env): `SCAN_PER_MIN` (5) and `SCAN_PER_HOUR` (30) per IP /
Telegram user, `SCAN_CONCURRENCY` (3) scans at once, `SCAN_HARD_TIMEOUT` (75 s).

**Keep Render awake:** `.github/workflows/keepalive.yml` pings `/api/health`
every 10 min. Set the repo variable `VG_URL` (Settings → Secrets and variables →
Actions → Variables) to your app URL.

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

Needs `BOT_TOKEN` and `ADMIN_TG_ID` (send `/myid` to your bot to get it).

**Default — you send the details through the bot** (`MANUAL_DETAILS` empty):
1. Buyer taps **Get full report → Card / bank / crypto wallet**.
2. You get *"Payment details requested"* in the bot. **Reply** to that message with your
   card / bank / wallet details — the bot forwards them to the buyer (Telegram chat
   and the web page).
3. Buyer pays, then taps **I've paid** (or sends a screenshot to the bot — it's forwarded to you).
4. You get ✅ / ❌. Tap ✅ → the buyer gets a key for `PACK_SCANS` scans, the report unlocks.

**Alternative — fixed details on the site:** set `MANUAL_DETAILS` (use `\n` for new
lines) and buyers see them immediately.

Admin extras: `/newkey 10 note` in the bot issues a key by hand.
Without the bot: `GET /api/admin/orders?status=pending`, `POST /api/admin/orders/{id}/approve`
(header `X-Admin-Token`). Optional: `CRYPTOPAY_TOKEN` (@CryptoBot, automatic crypto)
and Telegram Stars (on whenever `BOT_TOKEN` is set).

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
