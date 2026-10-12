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


PAGE = """<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Travels Well</title>
<style>
:root{--ink:#16181d;--mute:#6b7280;--line:#e3e5ea;--live:#0f766e;--cache:#b45309;
 color-scheme:light}
*{box-sizing:border-box}
body{margin:0;font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
 color:var(--ink);background:#fcfcfd}
.wrap{max-width:860px;margin:0 auto;padding:28px 18px 64px}
h1{font-size:30px;letter-spacing:-.02em;margin:0 0 4px}
.sub{color:var(--mute);margin:0 0 22px}
.row{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:18px}
button{font:inherit;padding:9px 14px;border:1px solid var(--line);background:#fff;
 border-radius:7px;cursor:pointer}
button:hover{border-color:#aab}
button[aria-pressed=true]{background:var(--ink);color:#fff;border-color:var(--ink)}
.badge{display:inline-block;font-size:11px;font-weight:700;letter-spacing:.07em;
 padding:3px 8px;border-radius:10px;text-transform:uppercase}
.badge.LIVE{background:#d6f3ec;color:var(--live)}
.badge.CACHED{background:#fdf0dc;color:var(--cache)}
.badge.UNAVAILABLE{background:#f1f2f5;color:var(--mute)}
.panel{border:1px solid var(--line);border-radius:9px;padding:16px;background:#fff}
.note{color:var(--mute);font-size:13px;margin-top:10px}
pre{overflow:auto;font-size:12px;background:#16181d;color:#e8eaee;padding:14px;
 border-radius:7px}
footer{margin-top:30px;color:var(--mute);font-size:12px;border-top:1px solid var(--line);
 padding-top:12px}
@media (prefers-color-scheme:dark){
 :root:not([data-theme=light]){--ink:#e8eaee;--mute:#9aa1ad;--line:#2a2e36}
 :root:not([data-theme=light]) body{background:#101216}
 :root:not([data-theme=light]) .panel,:root:not([data-theme=light]) button{background:#171a1f}
}
</style>
<div class=wrap>
<h1>Travels Well</h1>
<p class=sub>Which titles travel to a new market, which local names carry the
same signal, and which do not translate at all.</p>
<div class=row id=presets></div>
<div class=panel id=out>Pick a market above.</div>
<footer>Every answer is labelled LIVE or CACHED. Cached answers are recorded
runs of the same pipeline, never synthetic stand-ins. Where coverage is too
thin to rank, this says so instead of guessing.</footer>
</div>
<script>
const P = __PRESETS__;
const row = document.getElementById('presets'), out = document.getElementById('out');
P.forEach(p => {
  const b = document.createElement('button');
  b.textContent = p.label; b.setAttribute('aria-pressed','false');
  b.onclick = () => {
    [...row.children].forEach(c => c.setAttribute('aria-pressed','false'));
    b.setAttribute('aria-pressed','true');
    out.textContent = 'Running…';
    fetch('/api/run?preset=' + encodeURIComponent(p.id))
      .then(r => r.json()).then(render).catch(e => { out.textContent = String(e); });
  };
  row.appendChild(b);
});
function render(d){
  out.innerHTML = '';
  const head = document.createElement('div');
  head.innerHTML = '<span class="badge ' + (d.source||'') + '">' + (d.source||'?') +
    '</span> <strong>' + (d.preset ? d.preset.label : '') + '</strong>';
  out.appendChild(head);
  if (d.message || d.disclosure) {
    const n = document.createElement('p'); n.className = 'note';
    n.textContent = d.message || d.disclosure;
    out.appendChild(n);
  }
  const pre = document.createElement('pre');
  pre.textContent = JSON.stringify(d, null, 2);
  out.appendChild(pre);
}
</script>
"""


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
        if route.path == "/healthz":
            return self._send(200, json.dumps(
                {"ok": True, "key_present": has_key(), **BUDGET.snapshot()}))
        if route.path == "/api/presets":
            return self._send(200, json.dumps(PRESETS))
        if route.path == "/api/run":
            params = parse_qs(route.query)
            preset_id = (params.get("preset") or [""])[0]
            body, status = answer(preset_id, self.client_ip())
            return self._send(status, json.dumps(body, default=str))
        if route.path in ("/", "/index.html"):
            page = PAGE.replace("__PRESETS__", json.dumps(PRESETS))
            return self._send(200, page, "text/html; charset=utf-8")
        return self._send(404, json.dumps({"error": "not found"}))

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
