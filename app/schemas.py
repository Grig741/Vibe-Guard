"""Pydantic request/response schemas."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class FirebaseConfig(BaseModel):
    """The public Firebase web config a developer pastes from their app."""
    apiKey: Optional[str] = Field(None, description="Firebase web API key")
    projectId: str = Field(..., description="Firebase project ID")
    databaseURL: Optional[str] = Field(None, description="Realtime DB URL")
    storageBucket: Optional[str] = Field(None, description="Storage bucket")
    authDomain: Optional[str] = None
    appId: Optional[str] = None
    messagingSenderId: Optional[str] = None


class ScanRequest(BaseModel):
    # Either paste a firebaseConfig object (config) OR a raw target string
    # (a website URL, or Supabase URL + anon key). `target` is the new smart
    # input; `config` is kept for the original Firebase flow and the API.
    config: Optional[FirebaseConfig] = None
    target: Optional[str] = None
    # Extra collection names to probe in Firestore besides the defaults.
    collections: List[str] = Field(default_factory=list)
    label: Optional[str] = None
    # If a valid license key is sent, the scan comes back fully unlocked.
    license_key: Optional[str] = None


class UnlockRequest(BaseModel):
    license_key: str


class FindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    check_id: str
    title: str
    severity: str
    status: str
    description: Optional[str] = None
    remediation: Optional[str] = None
    evidence: Optional[str] = None


class ScanSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    target_label: Optional[str] = None
    scan_type: str = "firebase"
    status: str
    score: int
    grade: str
    critical: int
    high: int
    medium: int
    low: int
    passed: int
    duration_ms: int
    unlocked: bool = False
    created_at: datetime


class ScanDetail(ScanSummary):
    """Full report when unlocked; findings are empty for a locked (free) scan."""
    error: Optional[str] = None
    issues: int = 0                 # number of vulnerabilities found
    locked: bool = True
    stack: List[str] = Field(default_factory=list)
    findings: List[FindingOut] = Field(default_factory=list)


class LicenseCreate(BaseModel):
    max_scans: int = Field(10, ge=1, le=100000)
    note: Optional[str] = None


class LicenseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    max_scans: int
    used: int
    note: Optional[str] = None
    active: bool
    created_at: datetime
