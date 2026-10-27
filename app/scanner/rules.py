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
}


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
