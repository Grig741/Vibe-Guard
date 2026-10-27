"""Tiny in-memory abuse guard for the scan endpoint (single instance is enough
for a Render/Railway deployment).

* per-caller sliding windows: SCAN_PER_MIN per minute and SCAN_PER_HOUR per hour
* SCAN_SLOTS caps how many scans run at once, so a burst can't starve the box
* SCAN_HARD_TIMEOUT bounds a single scan
"""
import asyncio
import os
import time
from collections import defaultdict, deque

from fastapi import Request

SCAN_PER_MIN = int(os.getenv("SCAN_PER_MIN", "5"))
SCAN_PER_HOUR = int(os.getenv("SCAN_PER_HOUR", "30"))
SCAN_HARD_TIMEOUT = float(os.getenv("SCAN_HARD_TIMEOUT", "75"))
SCAN_SLOTS = asyncio.Semaphore(int(os.getenv("SCAN_CONCURRENCY", "3")))


class Limiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque] = defaultdict(deque)
        self._last_sweep = time.monotonic()

    def hit(self, key: str) -> int:
        """Record a request. Returns 0 if allowed, else seconds to wait."""
        now = time.monotonic()
        q = self._hits[key]
        while q and now - q[0] > 3600:
            q.popleft()
        last_min = sum(1 for t in q if now - t < 60)
        if last_min >= SCAN_PER_MIN:
            oldest = next(t for t in q if now - t < 60)
            return max(1, int(60 - (now - oldest)) + 1)
        if len(q) >= SCAN_PER_HOUR:
            return max(1, int(3600 - (now - q[0])) + 1)
        q.append(now)
        self._sweep(now)
        return 0

    def _sweep(self, now: float) -> None:
        if now - self._last_sweep < 600:
            return
        self._last_sweep = now
        for k in [k for k, q in self._hits.items() if not q or now - q[-1] > 3600]:
            del self._hits[k]


limiter = Limiter()


def client_ip(request: Request) -> str:
    """Real client IP behind Render/Cloudflare.

    CF-Connecting-IP is set by Cloudflare and can't be forged through it. Otherwise
    use the RIGHTMOST X-Forwarded-For entry (added by our own proxy) — the leftmost
    one is whatever the client chose to send.
    """
    h = request.headers
    if h.get("cf-connecting-ip"):
        return h["cf-connecting-ip"].strip()
    xff = h.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"
