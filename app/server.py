#!/usr/bin/env python3
"""Public demo server.

The rules require a live app a judge can drive end to end, free, with no
login, until judging closes on 16 November. Three properties follow from that
and are built in from the start rather than bolted on at the end:

  1. The API key never leaves the server.
  2. A preset always works, even with the quota exhausted or the key missing,
     because preset answers are served from disk. Every response says plainly
     whether it is LIVE or CACHED.
  3. Refusals are routing decisions, not errors. A judge never sees a stack
     trace or an empty screen.

Runs on stdlib alone: no framework, nothing to install, identical locally and
in the container.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from app.budget import Budget  # noqa: E402
from qloo_client import load_dotenv  # noqa: E402

# In the container the key arrives as an env var; locally it lives in .env.
# Without this the server silently runs cache-only, which looks like working.
load_dotenv()

BUDGET = Budget()
PRESETS = json.loads((HERE / "presets.json").read_text())["presets"]
PRESET_BY_ID = {p["id"]: p for p in PRESETS}
CACHE_DIR = HERE / "cache"
START_LOCK = threading.Lock()


def has_key():
    return bool(os.environ.get("QLOO_API_KEY"))


def cached_result(preset_id):
    path = CACHE_DIR / ("%s.json" % preset_id)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except ValueError:
            return None
    return None


def run_live(preset, ip):
    """Live path. Returns None when the engine is not wired yet, so the caller
    falls back to cache rather than inventing a result."""
    allowed, reason = BUDGET.allow_live(ip)
    if not allowed:
        return None, reason
    try:
        from engine import run_translation  # noqa: F401
    except ImportError:
        return None, "engine_not_wired"
    try:
        result = run_translation(preset)
    except Exception as exc:                      # never surface a traceback
        return None, "engine_error:%s" % type(exc).__name__
    BUDGET.record_live(ip, result.get("quota_remaining"))
    return result, None


def answer(preset_id, ip):
    preset = PRESET_BY_ID.get(preset_id)
    if not preset:
        return {"error": "unknown preset", "known": list(PRESET_BY_ID)}, 404

    live, reason = (None, "no_key")
    if has_key():
        live, reason = run_live(preset, ip)

    if live:
        live.update({"source": "LIVE", "preset": preset})
        return live, 200

    cached = cached_result(preset_id)
    if cached:
        BUDGET.record_cached()
        cached.update({
            "source": "CACHED",
            "preset": preset,
            "cached_because": reason,
            "disclosure": ("Served from a recorded run. The result is real, "
                           "not synthetic: it is the stored output of the same "
                           "pipeline against the live API."),
        })
        return cached, 200

    return {
        "source": "UNAVAILABLE",
        "preset": preset,
        "reason": reason,
        "message": ("This preset has no recorded run yet and the live path is "
                    "not available. Nothing is being guessed in its place."),
    }, 503


def page_html():
    """The page lives in app/index.html so it can be edited as HTML rather than
    as a Python string."""
    return (HERE / "index.html").read_text()


class Handler(BaseHTTPRequestHandler):
    server_version = "travels-well"

    def _send(self, status, body, ctype="application/json; charset=utf-8"):
        payload = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def client_ip(self):
        fwd = self.headers.get("X-Forwarded-For", "")
        return fwd.split(",")[0].strip() if fwd else self.client_address[0]

    def do_GET(self):
        route = urlparse(self.path)
        # /healthz is intercepted by Google's frontend before it reaches the
        # container, so the health endpoint lives at /status.
        if route.path in ("/status", "/healthz"):
            return self._send(200, json.dumps(
                {"ok": True, "key_present": has_key(), **BUDGET.snapshot()}))
        if route.path == "/api/presets":
            return self._send(200, json.dumps(PRESETS))
        if route.path == "/api/run":
            params = parse_qs(route.query)
            preset_id = (params.get("preset") or [""])[0]
            body, status = answer(preset_id, self.client_ip())
            return self._send(status, json.dumps(body, default=str))
        if route.path == "/api/atlas":
            path = HERE / "atlas_view.json"
            if not path.exists():
                return self._send(503, json.dumps(
                    {"error": "atlas not built", "how": "run atlas_view.py"}))
            return self._send(200, path.read_text())
        if route.path in ("/slate", "/index.html", "/travels"):
            page = page_html().replace("__PRESETS__", json.dumps(PRESETS))
            return self._send(200, page, "text/html; charset=utf-8")
        if route.path in ("/pitch", "/pitch.html"):
            return self._send(200, (HERE / "pitch.html").read_text(),
                              "text/html; charset=utf-8")
        # The atlas is the front door: it is the surface that explains the
        # whole project in one screen. Travels Well moved to /slate.
        if route.path in ("/", "/atlas", "/atlas.html"):
            return self._send(200, (HERE / "atlas.html").read_text(),
                              "text/html; charset=utf-8")
        return self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        route = urlparse(self.path)
        if route.path != "/api/pitch":
            return self._send(404, json.dumps({"error": "not found"}))
        allowed, reason = BUDGET.allow_live(self.client_ip())
        if not allowed:
            return self._send(429, json.dumps({"error":
                "Rate limit reached (%s). This is a shared demo key; try again "
                "shortly, or explore the precomputed Atlas, which costs nothing."
                % reason}))
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, TypeError):
            return self._send(400, json.dumps({"error": "could not read request"}))
        if not has_key():
            return self._send(503, json.dumps({"error":
                "No Qloo key configured on this server."}))
        try:
            from qloo_client import QlooClient
            from taste.evidence import Trace
            from taste.pitch import PitchError, run as run_pitch
            client = QlooClient(log_name="pitch_calls.jsonl")
            trace = Trace()
            result = run_pitch(client,
                               payload.get("slate") or [],
                               payload.get("buyer") or [],
                               payload.get("home") or None,
                               trace=trace)
            BUDGET.record_live(self.client_ip(), client.quota_remaining)
            result["calls"] = trace.summary()["calls"]
            return self._send(200, json.dumps(result, default=str))
        except PitchError as exc:
            return self._send(200, json.dumps({"error": str(exc)}))
        except Exception as exc:               # never leak a traceback
            return self._send(500, json.dumps({"error":
                "The ranking failed (%s)." % type(exc).__name__}))

    def log_message(self, fmt, *args):   # keep container logs readable
        sys.stderr.write("%s %s\n" % (self.client_ip(), fmt % args))


def main():
    port = int(os.environ.get("PORT", "8080"))
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print("travels-well on :%d  key=%s  presets=%d"
          % (port, "yes" if has_key() else "no", len(PRESETS)), file=sys.stderr)
    srv.serve_forever()


if __name__ == "__main__":
    main()
