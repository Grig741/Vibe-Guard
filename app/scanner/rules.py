"""Severity model, check catalog and scoring.

Each check that can fail has a `weight`: how many points it subtracts from a
perfect score of 100 when the target is found vulnerable. Weights are tuned so
that a single world-readable+writable database alone drops the project to a
failing grade.
"""
from dataclasses import dataclass

# ---- Severity ----------------------------------------------------------------

SEVERITY_ORDER = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
    "info": 4,
    "pass": 5,
}


@dataclass(frozen=True)
class CheckMeta:
    id: str
    title: str
    severity: str  # severity when VULNERABLE
    weight: float
    description: str      # what the problem is
    remediation: str      # how to fix it


# ---- Catalog -----------------------------------------------------------------
# One entry per security check VibeGuard runs.

CHECKS = {
    "firestore_public_read": CheckMeta(
        id="firestore_public_read",
        title="Firestore readable by anyone",
        severity="high",
        weight=25,
        description=(
            "Your Cloud Firestore database returns documents to unauthenticated "
            "requests. Anyone with your project ID can read your data — user "
            "records, orders, messages — straight from the public REST API."
        ),
        remediation=(
            "Open Firestore → Rules and require auth. A safe baseline:\n"
            "rules_version = '2';\n"
            "service cloud.firestore {\n"
            "  match /databases/{database}/documents {\n"
            "    match /{document=**} {\n"
            "      allow read, write: if request.auth != null;\n"
            "    }\n"
            "  }\n"
            "}\n"
            "Then tighten per-collection so users only touch their own data."
        ),
    ),
    "firestore_public_write": CheckMeta(
        id="firestore_public_write",
        title="Firestore writable by anyone",
        severity="critical",
        weight=42,
        description=(
            "Unauthenticated clients can create and overwrite documents in your "
            "Firestore database. An attacker can poison, inflate or wipe your "
            "data and run up your bill at will."
        ),
        remediation=(
            "In Firestore → Rules, never leave `allow write: if true`. Gate every "
            "write behind `request.auth != null` and validate ownership, e.g. "
            "`allow write: if request.auth.uid == resource.data.ownerId;`"
        ),
    ),
    "rtdb_public_read": CheckMeta(
        id="rtdb_public_read",
        title="Realtime Database readable by anyone",
        severity="high",
        weight=25,
        description=(
            "Your Realtime Database responds to public reads. The entire tree can "
            "be downloaded as JSON by anyone who knows the database URL."
        ),
        remediation=(
            "In Realtime Database → Rules, replace `.read: true` with "
            '`".read": "auth != null"` and scope reads per path. Never ship the '
            "default open test-mode rules to production."
        ),
    ),
    "rtdb_public_write": CheckMeta(
        id="rtdb_public_write",
        title="Realtime Database writable by anyone",
        severity="critical",
        weight=42,
        description=(
            "Anyone can write to your Realtime Database without signing in. This "
            "lets attackers tamper with or destroy all stored data."
        ),
        remediation=(
            'In Realtime Database → Rules, set `".write": "auth != null"` at '
            "minimum and validate the shape of incoming data with `.validate`."
        ),
    ),
    "storage_public_list": CheckMeta(
        id="storage_public_list",
        title="Storage bucket files are listable publicly",
        severity="high",
        weight=22,
        description=(
            "Your Firebase Storage bucket lets unauthenticated clients list its "
            "objects. Uploaded files — user documents, invoices, ID scans — can be "
            "enumerated and downloaded."
        ),
        remediation=(
            "Open Storage → Rules and require auth:\n"
            "rules_version = '2';\n"
            "service firebase.storage {\n"
            "  match /b/{bucket}/o {\n"
            "    match /{allPaths=**} {\n"
            "      allow read, write: if request.auth != null;\n"
            "    }\n"
            "  }\n"
            "}"
        ),
    ),
    "auth_open_signup": CheckMeta(
        id="auth_open_signup",
        title="Email/password sign-up is open",
        severity="medium",
        weight=10,
        description=(
            "Email/password registration is enabled and open. On its own this is "
            "often intended, but combined with weak database rules it lets anyone "
            "mint an account and reach anything gated only by `auth != null`."
        ),
        remediation=(
            "If self-serve sign-up isn't needed, disable the Email/Password "
            "provider or create users server-side with the Admin SDK. If it is "
            "needed, enforce email verification and never trust `auth != null` "
            "alone for sensitive data."
        ),
    ),
    "auth_anonymous_open": CheckMeta(
        id="auth_anonymous_open",
        title="Anonymous authentication is enabled",
        severity="medium",
        weight=10,
        description=(
            "Anonymous auth is turned on, so anyone can obtain a valid `auth` "
            "token with no credentials. Rules that only check `auth != null` give "
            "these anonymous users the same access as real ones."
        ),
        remediation=(
            "Disable Anonymous sign-in if you don't use it (Authentication → "
            "Sign-in method). If you do, treat anonymous users as untrusted in "
            "your rules — check `auth.token.firebase.sign_in_provider`."
        ),
    ),
    "apikey_unrestricted": CheckMeta(
        id="apikey_unrestricted",
        title="Web API key has no application restriction",
        severity="low",
        weight=6,
        description=(
            "The Firebase web API key works from a non-browser origin, which "
            "indicates no HTTP-referrer / application restriction is set. The key "
            "is public by design, but restricting it limits quota abuse."
        ),
        remediation=(
            "In Google Cloud Console → APIs & Services → Credentials, edit the "
            "browser key and set Application restrictions → HTTP referrers to your "
            "own domains, and restrict which APIs the key may call."
        ),
    ),

    # ---- Supabase ----
    "supabase_service_key_exposed": CheckMeta(
        id="supabase_service_key_exposed",
        title="Supabase service_role key is in the frontend",
        severity="critical",
        weight=55,
        description=(
            "A service_role key was found in your shipped JavaScript. This key "
            "bypasses every Row Level Security policy — whoever reads it has full "
            "read/write access to your entire database and storage, as admin."
        ),
        remediation=(
            "Treat this key as compromised: in Supabase → Project Settings → API, "
            "roll (regenerate) the service_role key immediately. Never put it in "
            "frontend code or env vars prefixed NEXT_PUBLIC_/VITE_. Use it only on a "
            "server. In the browser use the anon (publishable) key, protected by RLS."
        ),
    ),
    "supabase_rls_read": CheckMeta(
        id="supabase_rls_read",
        title="Supabase table readable by anyone",
        severity="high",
        weight=25,
        description=(
            "A table returned rows to the public anon key. Row Level Security is "
            "off or allows anonymous SELECT, so anyone can read that table's data "
            "straight from the REST API."
        ),
        remediation=(
            "In Supabase → Authentication → Policies, enable RLS on the table and "
            "add a policy that scopes reads, e.g.\n"
            "  alter table public.<table> enable row level security;\n"
            "  create policy \"own rows\" on public.<table>\n"
            "    for select using (auth.uid() = user_id);\n"
            "Never leave a table with RLS disabled in production."
        ),
    ),
    "supabase_rls_write": CheckMeta(
        id="supabase_rls_write",
        title="Supabase table writable by anyone",
        severity="critical",
        weight=42,
        description=(
            "The public anon key could insert a row. Unauthenticated visitors can "
            "write to your database — spam, tamper with or inflate your data and "
            "your bill."
        ),
        remediation=(
            "Enable RLS and gate writes behind the signed-in user:\n"
            "  create policy \"insert own\" on public.<table>\n"
            "    for insert with check (auth.uid() = user_id);\n"
            "Add matching update/delete policies; never ship a table with RLS off."
        ),
    ),
    "supabase_storage_public": CheckMeta(
        id="supabase_storage_public",
        title="Supabase storage bucket is public",
        severity="high",
        weight=22,
        description=(
            "A storage bucket lists its objects to the anon key. Uploaded files can "
            "be enumerated and downloaded by anyone."
        ),
        remediation=(
            "In Supabase → Storage, turn the bucket Private unless it is meant to be "
            "public, and add storage policies that restrict object access to the "
            "owner (auth.uid())."
        ),
    ),
    "supabase_schema_exposed": CheckMeta(
        id="supabase_schema_exposed",
        title="Database schema is readable by anyone",
        severity="medium",
        weight=10,
        description=(
            "The anon key can read the PostgREST OpenAPI spec — a full list of your "
            "tables, views and columns. On its own it's just information, but it "
            "hands an attacker a complete map of your database to probe."
        ),
        remediation=(
            "This is expected when RLS is correctly enabled (the schema is listed "
            "but the data is protected). Make sure RLS is on for every table so the "
            "map leads nowhere, or restrict the exposed schema under Settings → API."
        ),
    ),

    # ---- Website (passive) ----
    "web_exposed_files": CheckMeta(
        id="web_exposed_files",
        title="Secret files are publicly downloadable",
        severity="critical",
        weight=48,
        description=(
            "Files that should never be served — like .env or the .git directory — "
            "are downloadable from your site. These typically contain API keys, "
            "database passwords or your full source history."
        ),
        remediation=(
            "Stop deploying these files: add .env, .git and backups to .gitignore "
            "and to your host's ignore/deploy settings. If a secret was served, "
            "rotate it now. On static hosts, ensure the build output folder contains "
            "no dotfiles or dumps."
        ),
    ),
    "web_source_maps": CheckMeta(
        id="web_source_maps",
        title="Source maps are shipped to production",
        severity="low",
        weight=5,
        description=(
            "Your production JavaScript references .map source maps, which let "
            "anyone reconstruct your original, unminified source code — including "
            "comments and any secrets left in it."
        ),
        remediation=(
            "Disable source maps in your production build (e.g. Vite "
            "`build.sourcemap: false`, Next.js `productionBrowserSourceMaps: false`, "
            "CRA `GENERATE_SOURCEMAP=false`), or stop uploading the .map files."
        ),
    ),
    "web_security_headers": CheckMeta(
        id="web_security_headers",
        title="Security headers are missing",
        severity="low",
        weight=6,
        description=(
            "Response is missing one or more hardening headers (Content-Security-"
            "Policy, HSTS, X-Content-Type-Options, X-Frame-Options). These are the "
            "browser-side defenses against XSS, clickjacking and MIME attacks."
        ),
        remediation=(
            "Add the headers at your host/CDN. A solid baseline:\n"
            "  Content-Security-Policy: default-src 'self';\n"
            "  Strict-Transport-Security: max-age=31536000; includeSubDomains\n"
            "  X-Content-Type-Options: nosniff\n"
            "  X-Frame-Options: DENY\n"
            "On Netlify/Vercel set these in _headers / vercel.json."
        ),
    ),
}

# Titles shown when a check PASSES, so a green row never reads like a problem.
PASS_TITLES = {
    "firestore_public_read": "Firestore blocks anonymous reads",
    "firestore_public_write": "Firestore blocks anonymous writes",
    "rtdb_public_read": "Realtime Database blocks anonymous reads",
    "rtdb_public_write": "Realtime Database blocks anonymous writes",
    "storage_public_list": "Storage bucket is not publicly listable",
    "auth_open_signup": "Self-serve email sign-up is disabled",
    "auth_anonymous_open": "Anonymous sign-in is disabled",
    "apikey_unrestricted": "Web API key is referrer-restricted",
    "supabase_service_key_exposed": "No service_role key in the frontend",
    "supabase_rls_read": "Supabase blocks anonymous reads (RLS on)",
    "supabase_rls_write": "Supabase blocks anonymous writes (RLS on)",
    "supabase_storage_public": "Supabase storage is not publicly listable",
    "supabase_schema_exposed": "Database schema is not exposed",
    "web_exposed_files": "No secret files are publicly served",
    "web_source_maps": "No source maps shipped to production",
    "web_security_headers": "Security headers are present",
}

# Leaked-secret findings don't come from this catalog — their title/severity/
# fix are built from detect.SECRET_RULES by the engine. This is the shared
# remediation text for all of them.
SECRET_REMEDIATION = (
    "This secret is in your public frontend, so treat it as leaked:\n"
    "1. Revoke / rotate it now in the provider's dashboard.\n"
    "2. Move the call that needs it to a server (an API route, a Cloud Function, "
    "an edge function) and keep the key in a server-only env var.\n"
    "3. Never prefix a real secret with NEXT_PUBLIC_, VITE_ or REACT_APP_ — "
    "those are bundled into the browser."
)


# ---- Scoring -----------------------------------------------------------------

def grade_for(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 55:
        return "D"
    return "F"
