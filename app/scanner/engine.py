"""Scan orchestrator: runs all probes, assembles findings, computes the score."""
import time

import httpx

from ..config import SCAN_TIMEOUT
from ..schemas import FirebaseConfig
from . import checks
from .rules import CHECKS, PASS_TITLES, SEVERITY_ORDER, grade_for

# Browser-like UA; these are ordinary Firebase REST endpoints.
_HEADERS = {
    "User-Agent": "VibeGuard/1.0 (+security-self-scan)",
    "Content-Type": "application/json",
}


async def run_scan(cfg: FirebaseConfig, extra_collections: list[str]) -> dict:
    """Execute every check and return a structured result dict.

    Returned shape:
        {
          "project_id", "status", "score", "grade",
          "critical", "high", "medium", "low", "passed",
          "duration_ms", "error", "findings": [ {...}, ... ]
        }
    """
    started = time.perf_counter()
    raw: list[dict] = []
    error: str | None = None

    limits = httpx.Limits(max_connections=10)
    timeout = httpx.Timeout(SCAN_TIMEOUT)
    try:
        async with httpx.AsyncClient(headers=_HEADERS, timeout=timeout,
                                     limits=limits, follow_redirects=True) as client:
            # Firestore (read+write), RTDB (read+write), Storage, Auth (3 checks)
            fs = await checks.check_firestore(client, cfg, extra_collections)
            rtdb = await checks.check_rtdb(client, cfg)
            storage = await checks.check_storage(client, cfg)
            auth = await checks.check_auth(client, cfg)
            raw = fs + rtdb + storage + auth
    except Exception as exc:  # noqa: BLE001
        error = str(exc)[:500]

    findings = _build_findings(raw)
    score, counts = _score(findings)
    duration_ms = int((time.perf_counter() - started) * 1000)

    return {
        "project_id": cfg.projectId,
        "status": "error" if error and not findings else "completed",
        "score": score,
        "grade": grade_for(score),
        "critical": counts["critical"],
        "high": counts["high"],
        "medium": counts["medium"],
        "low": counts["low"],
        "passed": counts["passed"],
        "duration_ms": duration_ms,
        "error": error,
        "findings": findings,
    }


def _build_findings(raw: list[dict]) -> list[dict]:
    """Turn raw check results into full findings using the rules catalog."""
    out: list[dict] = []
    for item in raw:
        cid = item["check_id"]
        meta = CHECKS.get(cid)
        if meta is None:
            continue
        status = item["status"]
        if status == "vulnerable":
            severity = meta.severity
        elif status == "ok":
            severity = "pass"
        else:  # skipped | error
            severity = "info"
        out.append({
            "check_id": cid,
            "title": PASS_TITLES.get(cid, meta.title) if status == "ok" else meta.title,
            "severity": severity,
            "status": status,
            "description": meta.description,
            "remediation": meta.remediation,
            "evidence": item.get("evidence", ""),
            "weight": meta.weight,
        })
    # Sort: vulnerabilities first (by severity), then passes, then info/skipped.
    out.sort(key=lambda f: (SEVERITY_ORDER.get(f["severity"], 9), f["check_id"]))
    return out


def _score(findings: list[dict]) -> tuple[int, dict]:
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "passed": 0}
    penalty = 0.0
    for f in findings:
        if f["status"] == "vulnerable":
            sev = f["severity"]
            if sev in counts:
                counts[sev] += 1
            penalty += f["weight"]
        elif f["status"] == "ok":
            counts["passed"] += 1
    score = max(0, min(100, round(100 - penalty)))
    return score, counts
