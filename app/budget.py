"""Quota and abuse guards.

Two different risks. The monthly Qloo quota is shared across everything, and
judging runs to 16 November, so a demo that burns the quota in week one is
dead when it matters most. And a public URL with no login will be hit by
crawlers.

Neither guard is allowed to break the demo: when a limit is reached the app
serves the cached preset and says so, rather than showing an error.
"""
from __future__ import annotations

import threading
import time

# Raised once a run cost 10 Qloo calls instead of 65. The quota floor below is
# the real protection: when the month runs low every answer serves from a
# recorded run, so the demo degrades rather than dying.
LIVE_CALLS_PER_IP_PER_HOUR = 20
LIVE_CALLS_GLOBAL_PER_HOUR = 200
QUOTA_FLOOR = 500          # stop live calls entirely below this many remaining


class Budget:
    def __init__(self):
        self._lock = threading.Lock()
        self._per_ip = {}
        self._global = []
        self.quota_remaining = None
        self.live_calls = 0
        self.served_cached = 0

    def _prune(self, stamps, now):
        return [t for t in stamps if now - t < 3600]

    def allow_live(self, ip):
        """Returns (allowed, reason). A refusal is a routing decision, not an
        error: the caller falls back to cache."""
        now = time.time()
        with self._lock:
            if self.quota_remaining is not None and self.quota_remaining < QUOTA_FLOOR:
                return False, "quota_floor"
            self._global = self._prune(self._global, now)
            if len(self._global) >= LIVE_CALLS_GLOBAL_PER_HOUR:
                return False, "global_hourly_cap"
            mine = self._prune(self._per_ip.get(ip, []), now)
            self._per_ip[ip] = mine
            if len(mine) >= LIVE_CALLS_PER_IP_PER_HOUR:
                return False, "per_ip_hourly_cap"
            return True, None

    def record_live(self, ip, quota_remaining=None):
        now = time.time()
        with self._lock:
            self._per_ip.setdefault(ip, []).append(now)
            self._global.append(now)
            self.live_calls += 1
            if quota_remaining is not None:
                self.quota_remaining = quota_remaining

    def record_cached(self):
        with self._lock:
            self.served_cached += 1

    def snapshot(self):
        with self._lock:
            return {"quota_remaining": self.quota_remaining,
                    "live_calls": self.live_calls,
                    "served_cached": self.served_cached}
