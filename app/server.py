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


PAGE = """<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Travels Well</title>
<style>
:root{--ink:#16181d;--mute:#6b7280;--line:#e4e6ea;--card:#fff;--bg:#fbfbfc;
 --up:#0f766e;--down:#b91c1c;--warn:#b45309;--accent:#1d4ed8;color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){
 --ink:#e8eaee;--mute:#99a0ac;--line:#2a2e36;--card:#171a1f;--bg:#101216;
 --up:#34d399;--down:#f87171;--warn:#fbbf24;--accent:#7da2ff}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
 font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:900px;margin:0 auto;padding:30px 18px 70px}
h1{font-size:31px;letter-spacing:-.022em;margin:0 0 5px}
.sub{color:var(--mute);margin:0 0 20px;max-width:62ch}
.row{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px}
button{font:inherit;padding:9px 14px;border:1px solid var(--line);
 background:var(--card);color:var(--ink);border-radius:8px;cursor:pointer}
button:hover{border-color:var(--accent)}
button[aria-pressed=true]{background:var(--ink);color:var(--bg);border-color:var(--ink)}
.badge{display:inline-block;font-size:10.5px;font-weight:700;letter-spacing:.08em;
 padding:3px 8px;border-radius:10px;text-transform:uppercase;vertical-align:2px}
.badge.LIVE{background:#d6f3ec;color:#0f766e}
.badge.CACHED{background:#fdf0dc;color:#b45309}
.badge.UNAVAILABLE{background:#eceef2;color:#6b7280}
.card{border:1px solid var(--line);border-radius:10px;padding:15px 17px;
 background:var(--card);margin-bottom:12px}
.card h3{margin:0 0 3px;font-size:16px}
.meta{color:var(--mute);font-size:12.5px;margin:0 0 11px}
.lane{margin:9px 0}
.lane b{font-size:11px;letter-spacing:.07em;text-transform:uppercase;color:var(--mute)}
.item{display:flex;justify-content:space-between;gap:12px;padding:3px 0;
 border-bottom:1px dotted var(--line)}
.item:last-child{border-bottom:0}
.up{color:var(--up);font-variant-numeric:tabular-nums}
.down{color:var(--down);font-variant-numeric:tabular-nums}
.chips{display:flex;flex-wrap:wrap;gap:5px;margin-top:5px}
.chip{font-size:12px;padding:2px 8px;border-radius:9px;background:var(--bg);
 border:1px solid var(--line);color:var(--mute)}
.notice{border-left:3px solid var(--warn);background:var(--card);
 padding:11px 13px;border-radius:0 7px 7px 0;margin-bottom:12px}
details{margin-top:10px}
summary{cursor:pointer;color:var(--accent);font-size:13.5px}
pre{overflow:auto;font-size:11.5px;background:#16181d;color:#e8eaee;
 padding:12px;border-radius:7px;margin-top:8px}
ol.steps{margin:8px 0 0;padding-left:20px;font-size:13.5px;color:var(--mute)}
ol.steps li{margin-bottom:5px}
footer{margin-top:28px;padding-top:12px;border-top:1px solid var(--line);
 color:var(--mute);font-size:12.5px}
</style>
<div class=wrap>
<h1>Travels Well</h1>
<p class=sub>Which titles in a slate travel to another market, which do not,
and which the evidence cannot settle. Every market is read twice through
unrelated taste anchors, and only what both readings agree on is reported.</p>
<div class=row id=presets></div>
<div id=out><div class=card>Pick a slate above.</div></div>
<footer>Answers are labelled LIVE or CACHED; cached ones are recorded runs of
this same pipeline, never synthetic. Where two readings of a market disagree,
the title is withheld rather than ranked. Where a market is too thinly
covered, or a baseline too unstable to measure against, the agent says so
instead of guessing.</footer>
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
    out.innerHTML = '<div class=card>Running\u2026</div>';
    fetch('/api/run?preset=' + encodeURIComponent(p.id))
      .then(r => r.json()).then(d => render(d, p))
      .catch(e => { out.innerHTML = '<div class=card>' + e + '</div>'; });
  };
  b.dataset.id = p.id;
  row.appendChild(b);
});
// Deep link: /?preset=<id> runs that slate on load, so a result can be shared
// as a URL rather than as instructions to click the second button.
const want = new URLSearchParams(location.search).get('preset');
if (want) {
  const target = [...row.children].find(c => c.dataset.id === want);
  if (target) target.click();
}
function el(tag, cls, text){const e=document.createElement(tag);
  if(cls)e.className=cls; if(text!==undefined)e.textContent=text; return e;}
function lane(title, items, cls){
  if(!items || !items.length) return null;
  const d = el('div','lane'); d.appendChild(el('b',null,title));
  items.forEach(i => {
    const r = el('div','item');
    r.appendChild(el('span',null,i.title));
    r.appendChild(el('span',cls,(i.shift>=0?'+':'')+i.shift.toFixed(2)));
    d.appendChild(r);
  });
  return d;
}
function render(d, p){
  out.innerHTML = '';
  const head = el('div','card');
  const h = el('div'); h.innerHTML = '<span class="badge '+(d.source||'')+'">'+
    (d.source||'?')+'</span> <strong>'+(p.label)+'</strong>';
  head.appendChild(h);
  if(d.disclosure) head.appendChild(el('p','meta', d.disclosure));
  if(d.message) head.appendChild(el('p','meta', d.message));
  if(p.note) head.appendChild(el('p','meta', p.note));
  out.appendChild(head);

  if(d.aborted){
    const n = el('div','notice'); n.appendChild(el('strong',null,'No verdict. '));
    n.appendChild(document.createTextNode(d.aborted));
    out.appendChild(n);
  }
  (d.markets||[]).forEach(m => {
    const c = el('div','card');
    c.appendChild(el('h3',null,m.market));
    c.appendChild(el('p','meta',
      'compared on '+m.compared_on+' titles \u00b7 anchor agreement '+
      (m.anchor_agreement==null?'n/a':m.anchor_agreement.toFixed(2))+
      ' \u00b7 agreement with home '+
      (m.agreement_with_home==null?'n/a':m.agreement_with_home.toFixed(2))));
    const a = lane('Travels', m.travels, 'up'); if(a) c.appendChild(a);
    const b2 = lane('Does not travel', m.does_not_travel, 'down'); if(b2) c.appendChild(b2);
    if(m.uncertain && m.uncertain.length){
      const u = el('div','lane');
      u.appendChild(el('b',null,'Evidence unstable \u2014 withheld ('+m.uncertain.length+')'));
      const chips = el('div','chips');
      m.uncertain.forEach(t => chips.appendChild(el('span','chip',t)));
      u.appendChild(chips); c.appendChild(u);
    }
    out.appendChild(c);
  });
  Object.entries(d.abstained||{}).forEach(([mk,why]) => {
    const n = el('div','notice');
    n.appendChild(el('strong',null, mk+': ')); n.appendChild(document.createTextNode(why));
    out.appendChild(n);
  });
  if(d.steps && d.steps.length){
    const c = el('div','card'); c.appendChild(el('h3',null,'How it decided'));
    const ol = el('ol','steps');
    d.steps.forEach(s => {
      const li = el('li', null, s.action+' \u2014 '+s.reason);
      if(s.rejected && s.rejected.length)
        li.appendChild(el('div','meta','passed over: '+s.rejected.join(', ')));
      ol.appendChild(li);
    });
    c.appendChild(ol);
    if(d.evidence){
      const det = el('details');
      det.appendChild(el('summary',null,'Evidence \u2014 every call behind these numbers'));
      const pre = el('pre', null, JSON.stringify(d.evidence, null, 2));
      det.appendChild(pre); c.appendChild(det);
    }
    out.appendChild(c);
  }
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
