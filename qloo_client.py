"""Minimal stdlib Qloo client for the day-one probe.

Deliberately dependency-free: system python3 runs it with no install step.
Every request and response is logged to JSONL so that any number this harness
reports can be traced back to the exact call that produced it.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = os.environ.get("QLOO_BASE", "https://hackathon.api.qloo.com")
OUT = Path(__file__).parent / "out"


class QlooError(RuntimeError):
    pass


class QlooClient:
    def __init__(self, api_key=None, log_name="calls.jsonl", cache=True, dry_run=False):
        self.api_key = api_key or os.environ.get("QLOO_API_KEY", "")
        self.dry_run = dry_run
        if not self.api_key and not dry_run:
            raise QlooError(
                "No QLOO_API_KEY. Export it, put it in .env next to this file, "
                "or pass --dry-run to exercise the harness without the API."
            )
        OUT.mkdir(exist_ok=True)
        self.log_path = OUT / log_name
        self.cache_dir = OUT / "cache"
        if cache:
            self.cache_dir.mkdir(exist_ok=True)
        self.cache = cache
        self.quota_remaining = None
        self.calls = 0

    # ----- plumbing -------------------------------------------------------
    def _cache_key(self, path, params):
        raw = path + "?" + urllib.parse.urlencode(sorted(params.items()))
        import hashlib

        return hashlib.sha256(raw.encode()).hexdigest()[:24]

    def _log(self, record):
        with self.log_path.open("a") as fh:
            fh.write(json.dumps(record) + "\n")

    def get(self, path, params, allow_error=False):
        """GET against the hackathon host. Returns (status, body_dict)."""
        params = {k: v for k, v in params.items() if v is not None}
        key = self._cache_key(path, params)
        cache_file = self.cache_dir / (key + ".json") if self.cache else None

        if cache_file is not None and cache_file.exists():
            body = json.loads(cache_file.read_text())
            self._log({"t": time.time(), "path": path, "params": params,
                       "status": 200, "cached": True})
            return 200, body

        if self.dry_run:
            raise QlooError("dry-run mode cannot make live calls")

        url = BASE + path + "?" + urllib.parse.urlencode(params, doseq=True)
        req = urllib.request.Request(url, headers={
            "X-Api-Key": self.api_key,
            "Accept": "application/json",
            "User-Agent": "qloo-day1-probe/1.0",
        })

        backoff = 2.0
        for attempt in range(5):
            try:
                with urllib.request.urlopen(req, timeout=45) as resp:
                    raw = resp.read().decode("utf-8", "replace")
                    self._capture_quota(resp.headers)
                    status = resp.status
                break
            except urllib.error.HTTPError as exc:
                raw = exc.read().decode("utf-8", "replace")
                self._capture_quota(exc.headers)
                status = exc.code
                if status == 429 and attempt < 4:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                break
            except urllib.error.URLError as exc:
                if attempt < 4:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                raise QlooError("network failure: %s" % exc)

        try:
            body = json.loads(raw)
        except ValueError:
            body = {"_raw": raw[:2000]}

        self.calls += 1
        self._log({"t": time.time(), "path": path, "params": params,
                   "status": status, "cached": False,
                   "quota_remaining": self.quota_remaining,
                   "body_keys": list(body.keys())[:10] if isinstance(body, dict) else None})

        if status != 200 and not allow_error:
            raise QlooError("%s %s -> %s: %s" % (path, params, status, str(body)[:400]))

        if status == 200 and cache_file is not None:
            cache_file.write_text(json.dumps(body))

        # Politeness: entrants report 5 req/s. Stay well under it.
        time.sleep(0.25)
        return status, body

    def _capture_quota(self, headers):
        for name in ("x-month-ratelimit-remaining", "X-Month-RateLimit-Remaining"):
            val = headers.get(name)
            if val is not None:
                try:
                    self.quota_remaining = int(val)
                except ValueError:
                    self.quota_remaining = val
                return

    # ----- endpoints ------------------------------------------------------
    def search(self, query, types=None):
        params = {"query": query}
        if types:
            params["types"] = types
        return self.get("/search", params)[1]

    def insights(self, params, allow_error=False):
        return self.get("/v2/insights", params, allow_error=allow_error)

    def tags(self, params=None):
        return self.get("/v2/tags", params or {})[1]


def load_dotenv():
    """Read KEY=VALUE lines from a .env beside this file, without overwriting
    anything already exported in the environment."""
    env_file = Path(__file__).parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def entities_of(body):
    """Pull the results list out of an insights response without assuming one
    envelope shape -- entrant repos disagree about where results live."""
    if not isinstance(body, dict):
        return []
    for path in (("results", "entities"), ("results",), ("entities",), ("data",)):
        node = body
        ok = True
        for part in path:
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                ok = False
                break
        if ok and isinstance(node, list):
            return node
    return []


def affinity_of(item):
    """Taste affinity for the signal in THIS query. Never popularity.

    A response carries both: `popularity` at the top level, which is a global
    property of the entity, and `query.affinity`, which is its affinity for the
    signal that was asked about. An earlier version of this function checked
    top-level keys first, found `popularity`, and returned that -- which would
    have ranked every market by global fame and made them all look identical.
    Confusing the two is the exact error this project exists to catch, so there
    is deliberately no fallback from one to the other: if affinity is absent,
    this returns None and the caller abstains.
    """
    if not isinstance(item, dict):
        return None
    q = item.get("query")
    if isinstance(q, dict):
        for key in ("affinity", "affinity_score", "score"):
            v = q.get(key)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return float(v)
        m = q.get("measurements")
        if isinstance(m, dict) and isinstance(m.get("affinity"), (int, float)):
            return float(m["affinity"])
    v = item.get("affinity")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    return None


def popularity_of(item):
    """Global popularity, kept strictly separate from affinity."""
    if isinstance(item, dict):
        v = item.get("popularity")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
    return None


def id_of(item):
    for key in ("entity_id", "id", "urn"):
        if isinstance(item, dict) and key in item:
            return item[key]
    return None


def name_of(item):
    for key in ("name", "title"):
        if isinstance(item, dict) and key in item:
            return item[key]
    return None
