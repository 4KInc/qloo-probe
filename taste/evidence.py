"""Evidence trail.

Every user-visible claim points back to the request that produced it. This is
what makes the evidence drawer possible, and it is the cheapest way to answer
the one question a technical judge always asks: where did that number come
from?

It also enforces a rule the product cannot break: a claim with no supporting
call cannot be rendered. Nothing reaches the interface that the trace cannot
account for.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path


class UnsupportedClaim(RuntimeError):
    pass


class Trace:
    def __init__(self, run_id=None):
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self.calls = []
        self.claims = []
        self.started = time.time()

    def record_call(self, path, params, status, result_count, cached=False):
        call_id = "c%d" % (len(self.calls) + 1)
        self.calls.append({
            "id": call_id, "path": path, "params": params, "status": status,
            "results": result_count, "cached": cached, "t": time.time(),
        })
        return call_id

    def claim(self, text, call_ids, kind="fact", detail=None):
        """Attach a statement to the calls that support it."""
        if not call_ids:
            raise UnsupportedClaim(
                "refusing to record a claim with no supporting call: %r" % text)
        known = {c["id"] for c in self.calls}
        unknown = [c for c in call_ids if c not in known]
        if unknown:
            raise UnsupportedClaim("unknown call ids %s for claim %r"
                                   % (unknown, text))
        self.claims.append({"text": text, "calls": list(call_ids),
                            "kind": kind, "detail": detail})
        return self.claims[-1]

    def abstention(self, reason_code, message):
        """An abstention is part of the record, not an absence from it."""
        self.claims.append({"text": message, "calls": [], "kind": "abstention",
                            "detail": {"code": reason_code}})

    def summary(self):
        return {
            "run_id": self.run_id,
            "calls": len(self.calls),
            "cached_calls": sum(1 for c in self.calls if c["cached"]),
            "claims": sum(1 for c in self.claims if c["kind"] != "abstention"),
            "abstentions": sum(1 for c in self.claims if c["kind"] == "abstention"),
            "elapsed_s": round(time.time() - self.started, 2),
        }

    def save(self, directory="out/traces"):
        Path(directory).mkdir(parents=True, exist_ok=True)
        path = Path(directory) / ("%s.json" % self.run_id)
        path.write_text(json.dumps({"summary": self.summary(),
                                    "calls": self.calls,
                                    "claims": self.claims}, indent=2))
        return path
