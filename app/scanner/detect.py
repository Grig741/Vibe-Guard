"""Find what a frontend ships: Firebase / Supabase configs, leaked secrets,
and the collection / table names the app actually uses.

Works on any text — a pasted firebaseConfig, a whole minified JS bundle, an
HTML page or a source map. Pure functions, no network.
"""
import base64
import json
import re
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Firebase
# ---------------------------------------------------------------------------

_Q = r"""["'`]"""
_FB_KEY = re.compile(r"""\bapiKey\s*["']?\s*[:=]\s*["'`](AIza[0-9A-Za-z_\-]{33,37})["'`]""")
_FB_FIELD = {
    "projectId": re.compile(r"""\bprojectId\s*["']?\s*[:=]\s*["'`]([a-z0-9][a-z0-9\-]{3,62})["'`]"""),
    "authDomain": re.compile(r"""\bauthDomain\s*["']?\s*[:=]\s*["'`]([\w.\-]+)["'`]"""),
    "storageBucket": re.compile(r"""\bstorageBucket\s*["']?\s*[:=]\s*["'`]([\w.\-]+)["'`]"""),
    "databaseURL": re.compile(r"""\bdatabaseURL\s*["']?\s*[:=]\s*["'`](https://[\w.\-]+(?:/)?)["'`]"""),
    "appId": re.compile(r"""\bappId\s*["']?\s*[:=]\s*["'`]([\w:\-]+)["'`]"""),
}
_FB_AUTHDOMAIN = re.compile(r"""\b([a-z0-9][a-z0-9\-]{3,62})\.firebaseapp\.com\b""")
_ANY_AIZA = re.compile(r"""\b(AIza[0-9A-Za-z_\-]{33,37})\b""")

# Collections the code touches: collection(db,"users"), .collection("users"),
# doc(db,"users",id), collectionGroup(db,"x") — also minified "(0,x.collection)(db,'users')".
_FS_COLL = [
    re.compile(r"""collection(?:Group)?\)?\(\s*[\w$.\[\]]+\s*,\s*["'`]([A-Za-z0-9_\-]{1,64})["'`]"""),
    re.compile(r"""\.collection(?:Group)?\(\s*["'`]([A-Za-z0-9_\-]{1,64})["'`]"""),
    re.compile(r"""\bdoc\)?\(\s*[\w$.\[\]]+\s*,\s*["'`]([A-Za-z0-9_\-]{1,64})["'`]\s*,"""),
]


@dataclass
class FirebaseFound:
    apiKey: Optional[str] = None
    projectId: Optional[str] = None
    authDomain: Optional[str] = None
    storageBucket: Optional[str] = None
    databaseURL: Optional[str] = None
    appId: Optional[str] = None
    where: str = ""

    def as_config(self) -> dict:
        return {k: v for k, v in {
            "apiKey": self.apiKey, "projectId": self.projectId, "authDomain": self.authDomain,
            "storageBucket": self.storageBucket, "databaseURL": self.databaseURL, "appId": self.appId,
        }.items() if v}


def find_firebase(text: str, where: str = "") -> Optional[FirebaseFound]:
    """Best Firebase config in `text`, or None."""
    m = _FB_KEY.search(text)
    if m:
        # Fields of one config object sit close together, even minified.
        lo, hi = max(0, m.start() - 1500), m.end() + 1500
        win = text[lo:hi]
        fb = FirebaseFound(apiKey=m.group(1), where=where)
        for name, rx in _FB_FIELD.items():
            fm = rx.search(win)
            if fm:
                setattr(fb, name, fm.group(1))
        if not fb.projectId:
            am = _FB_AUTHDOMAIN.search(win)
            if am:
                fb.projectId = am.group(1)
        if fb.projectId:
            return fb
    # Config split across env vars (NEXT_PUBLIC_FIREBASE_*) → literals only.
    am = _FB_AUTHDOMAIN.search(text)
    km = _ANY_AIZA.search(text)
    if am and km:
        return FirebaseFound(apiKey=km.group(1), projectId=am.group(1),
                             authDomain=am.group(0), where=where)
    return None


def find_collections(text: str) -> list[str]:
    out: list[str] = []
    for rx in _FS_COLL:
        for m in rx.finditer(text):
            name = m.group(1)
            if name not in out and not name.isdigit():
                out.append(name)
    return out[:40]


# ---------------------------------------------------------------------------
# Supabase
# ---------------------------------------------------------------------------

_SB_URL = re.compile(r"""https://([a-z0-9]{20})\.supabase\.(?:co|in)\b""")
_JWT = re.compile(r"""\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}""")
_SB_PUBLISHABLE = re.compile(r"""\bsb_publishable_[A-Za-z0-9_\-]{20,}""")
_SB_SECRET = re.compile(r"""\bsb_secret_[A-Za-z0-9_\-]{20,}""")
# createClient("https://x.supabase.co", "eyJ…") — also catches self-hosted Supabase.
_SB_CREATE = re.compile(
    r"""createClient\)?\(\s*["'`](https?://[^"'`\s]{4,200}?)/?["'`]\s*,\s*["'`]([A-Za-z0-9_.\-]{20,})["'`]""")
_SB_FROM = re.compile(
    r"""\.from\(\s*["'`]([A-Za-z_][A-Za-z0-9_]{0,62})["'`]\s*\)\s*\.\s*(?:select|insert|update|upsert|delete|eq|order|limit|single|match|range)\b""")
_SB_STORAGE = re.compile(r"""storage\s*\.\s*from\(\s*["'`]([A-Za-z0-9_\-.]{1,63})["'`]\s*\)""")
_SB_RPC = re.compile(r"""\.rpc\(\s*["'`]([A-Za-z_][A-Za-z0-9_]{0,62})["'`]""")


def jwt_payload(token: str) -> dict:
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        data = json.loads(base64.urlsafe_b64decode(part.encode()))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


@dataclass
class SupabaseFound:
    url: Optional[str] = None
    anon_key: Optional[str] = None
    service_key: Optional[str] = None      # service_role JWT or sb_secret_ — must never ship
    tables: list = field(default_factory=list)
    buckets: list = field(default_factory=list)
    rpcs: list = field(default_factory=list)
    where: str = ""

    @property
    def ref(self) -> str:
        m = _SB_URL.search(self.url or "")
        return m.group(1) if m else (self.url or "")


def _classify_jwt(tok: str) -> Optional[str]:
    p = jwt_payload(tok)
    if p.get("iss") in ("supabase", "supabase-demo") or "ref" in p:
        return p.get("role")
    return None


def find_supabase(text: str, where: str = "") -> Optional[SupabaseFound]:
    sb = SupabaseFound(where=where)
    cm = _SB_CREATE.search(text)
    if cm:
        sb.url = cm.group(1).rstrip("/")
        key = cm.group(2)
        role = _classify_jwt(key) if key.startswith("eyJ") else None
        if role == "service_role" or key.startswith("sb_secret_"):
            sb.service_key = key
        else:
            sb.anon_key = key
    if not sb.url:
        um = _SB_URL.search(text)
        if um:
            sb.url = um.group(0)
    for tok in _JWT.findall(text):
        role = _classify_jwt(tok)
        if role == "anon" and not sb.anon_key:
            sb.anon_key = tok
            if not sb.url:
                ref = jwt_payload(tok).get("ref")
                if ref:
                    sb.url = f"https://{ref}.supabase.co"
        elif role == "service_role" and not sb.service_key:
            sb.service_key = tok
            if not sb.url:
                ref = jwt_payload(tok).get("ref")
                if ref:
                    sb.url = f"https://{ref}.supabase.co"
    if not sb.anon_key:
        pm = _SB_PUBLISHABLE.search(text)
        if pm:
            sb.anon_key = pm.group(0)
    if not sb.service_key:
        sm = _SB_SECRET.search(text)
        if sm:
            sb.service_key = sm.group(0)
    if not sb.url:
        return None
    sb.tables = _uniq(m.group(1) for m in _SB_FROM.finditer(text))[:60]
    sb.buckets = _uniq(m.group(1) for m in _SB_STORAGE.finditer(text))[:20]
    sb.rpcs = _uniq(m.group(1) for m in _SB_RPC.finditer(text))[:30]
    return sb


def merge_supabase(items: list[SupabaseFound]) -> Optional[SupabaseFound]:
    """Several bundles → one picture (the first URL wins)."""
    items = [i for i in items if i]
    if not items:
        return None
    base = next((i for i in items if i.anon_key), items[0])
    out = SupabaseFound(url=base.url, anon_key=base.anon_key, where=base.where)
    for i in items:
        if i.url and i.url != out.url and _SB_URL.search(i.url or "") is None:
            continue
        out.service_key = out.service_key or i.service_key
        out.anon_key = out.anon_key or i.anon_key
        out.tables = _uniq(out.tables + i.tables)
        out.buckets = _uniq(out.buckets + i.buckets)
        out.rpcs = _uniq(out.rpcs + i.rpcs)
    return out


def _uniq(it) -> list:
    out: list = []
    for x in it:
        if x not in out:
            out.append(x)
    return out


# ---------------------------------------------------------------------------
# Leaked secrets
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SecretRule:
    kind: str           # stable id, e.g. "openai"
    name: str           # human name
    severity: str
    rx: re.Pattern
    impact: str         # what an attacker gets


SECRET_RULES = [
    SecretRule("openai", "OpenAI API key", "critical",
               re.compile(r"""\bsk-(?:proj|svcacct|admin)-[A-Za-z0-9_\-]{40,}|\bsk-[A-Za-z0-9]{20}T3BlbkFJ[A-Za-z0-9]{20}\b"""),
               "Anyone can call OpenAI on your bill — people scrape sites for these and burn thousands of dollars in hours."),
    SecretRule("anthropic", "Anthropic (Claude) API key", "critical",
               re.compile(r"""\bsk-ant-(?:api|admin)\d{2}-[A-Za-z0-9_\-]{60,}"""),
               "Anyone can run Claude on your account and bill."),
    SecretRule("openrouter", "OpenRouter API key", "critical",
               re.compile(r"""\bsk-or-v1-[a-f0-9]{64}\b"""),
               "Anyone can use any model through your OpenRouter balance."),
    SecretRule("groq", "Groq API key", "high",
               re.compile(r"""\bgsk_[A-Za-z0-9]{48,}\b"""),
               "Anyone can use your Groq quota."),
    SecretRule("huggingface", "Hugging Face token", "high",
               re.compile(r"""\bhf_[A-Za-z0-9]{34,}\b"""),
               "Access to your Hugging Face account, private models and paid inference."),
    SecretRule("replicate", "Replicate API token", "high",
               re.compile(r"""\br8_[A-Za-z0-9]{37}\b"""),
               "Anyone can run paid models on your Replicate account."),
    SecretRule("stripe_live", "Stripe live secret key", "critical",
               re.compile(r"""\b(?:sk|rk)_live_[A-Za-z0-9]{20,}\b"""),
               "Full access to your Stripe account: refunds, payouts, customer data."),
    SecretRule("stripe_test", "Stripe test secret key", "medium",
               re.compile(r"""\b(?:sk|rk)_test_[A-Za-z0-9]{20,}\b"""),
               "Test-mode only, but proves secret keys are bundled into the frontend — the live one may follow."),
    SecretRule("aws", "AWS access key", "critical",
               re.compile(r"""\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"""),
               "Access to your AWS account (S3, EC2…) within the key's permissions."),
    SecretRule("github", "GitHub token", "critical",
               re.compile(r"""\bgh[pousr]_[A-Za-z0-9]{36,}\b|\bgithub_pat_[A-Za-z0-9_]{60,}"""),
               "Access to your repositories and code."),
    SecretRule("private_key", "Private key (PEM)", "critical",
               re.compile(r"""-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"""),
               "A private key in the frontend — often a Firebase Admin / Google service-account key with full project access."),
    SecretRule("telegram_bot", "Telegram bot token", "high",
               re.compile(r"""\b\d{8,10}:AA[A-Za-z0-9_\-]{33}\b"""),
               "Anyone can control your bot: read its messages and write to your users."),
    SecretRule("slack", "Slack token / webhook", "high",
               re.compile(r"""\bxox[abprs]-[A-Za-z0-9\-]{10,}|https://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]+"""),
               "Anyone can post to (or read) your Slack workspace."),
    SecretRule("discord_webhook", "Discord webhook", "medium",
               re.compile(r"""https://(?:ptb\.|canary\.)?discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_\-]+"""),
               "Anyone can spam your Discord channel."),
    SecretRule("sendgrid", "SendGrid API key", "critical",
               re.compile(r"""\bSG\.[A-Za-z0-9_\-]{22}\.[A-Za-z0-9_\-]{43}\b"""),
               "Anyone can send email as your domain — perfect for phishing."),
    SecretRule("resend", "Resend API key", "high",
               re.compile(r"""\bre_[A-Za-z0-9]{8,}_[A-Za-z0-9]{16,}\b"""),
               "Anyone can send email as your domain."),
    SecretRule("mailgun", "Mailgun API key", "high",
               re.compile(r"""\bkey-[0-9a-f]{32}\b"""),
               "Anyone can send email through your Mailgun account."),
    SecretRule("mapbox_secret", "Mapbox secret token", "medium",
               re.compile(r"""\bsk\.eyJ[A-Za-z0-9_\-]{30,}\.[A-Za-z0-9_\-]{10,}"""),
               "Secret Mapbox scopes usable by anyone."),
    SecretRule("db_url", "Database connection string with password", "critical",
               re.compile(r"""\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://[A-Za-z0-9_.%\-]+:[^@\s"'`/]{3,}@[A-Za-z0-9_.\-]+"""),
               "Direct access to your database, bypassing every rule."),
]

_PLACEHOLDER = re.compile(r"(?i)(x{6,}|your[_\-]?|example|placeholder|dummy|<|\*{4,}|0{12,})")


@dataclass
class SecretHit:
    kind: str
    name: str
    severity: str
    impact: str
    masked: str
    where: str


def mask(s: str) -> str:
    if len(s) <= 12:
        return s[:3] + "…"
    return f"{s[:8]}…{s[-4:]}"


def find_secrets(text: str, where: str = "") -> list[SecretHit]:
    hits: list[SecretHit] = []
    for rule in SECRET_RULES:
        for m in rule.rx.finditer(text):
            val = m.group(0)
            if _PLACEHOLDER.search(val):
                continue
            if rule.kind == "db_url" and re.search(r"(?i)(localhost|127\.0\.0\.1|user:pass|username:password)", val):
                continue
            hits.append(SecretHit(rule.kind, rule.name, rule.severity, rule.impact, mask(val), where))
            break  # one hit per rule per file is enough
    return hits


# ---------------------------------------------------------------------------
# Raw user input → what to scan
# ---------------------------------------------------------------------------

_URLISH = re.compile(r"""^(?:https?://)?(?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}(?::\d{2,5})?(?:[/?#]\S*)?$""", re.I)


def classify_input(raw: str) -> dict:
    """Decide what the user pasted.

    Returns {"type": "firebase"|"supabase"|"url"|"unknown", ...}.
    """
    raw = (raw or "").strip()
    if not raw:
        return {"type": "unknown"}
    fb = find_firebase(raw)
    sb = find_supabase(raw)
    # Supabase creds pasted as two lines: URL + key
    if sb and (sb.anon_key or sb.service_key):
        return {"type": "supabase", "supabase": sb}
    if fb:
        return {"type": "firebase", "firebase": fb}
    if "{" in raw and re.search(r"\bprojectId\b", raw):
        pm = _FB_FIELD["projectId"].search(raw)
        if pm:
            return {"type": "firebase", "firebase": FirebaseFound(projectId=pm.group(1))}
    one = raw.split()[0] if raw.split() else ""
    if _URLISH.match(one) or one.startswith(("http://", "https://")):
        return {"type": "url", "url": one}
    if sb:  # supabase URL but no key → nothing useful to probe server-side
        return {"type": "supabase", "supabase": sb}
    return {"type": "unknown"}
