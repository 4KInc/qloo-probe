"""Engine: what the server calls to answer one preset.

Thin by design. The agent loop, the consensus backend and the evidence trail
already do the work; this shapes their output for the interface and keeps
anything the UI should not have to understand out of the response.
"""
from __future__ import annotations

import json
from pathlib import Path

from qloo_client import QlooClient, load_dotenv
from taste.evidence import Trace
from taste.loop import Agent, Goal
from taste.qloo_backend import QlooBackend

HERE = Path(__file__).resolve().parent
load_dotenv()


def _catalog():
    spec = json.loads((HERE / "fixtures" / "catalog.json").read_text())
    return spec, spec["control"] + spec["regional"]


def run_translation(preset):
    """Answer one preset. Raises nothing the server has to interpret: an
    abstention is a normal result, not an error."""
    spec, titles = _catalog()
    client = QlooClient(log_name="server_calls.jsonl")
    trace = Trace()
    backend = QlooBackend(entity_type=preset.get("entity_type",
                                                 spec["entity_type"]),
                          client=client, trace=trace, consensus=True)

    home = preset["home_market"]
    targets = [m for m in (preset.get("target_markets")
                           or list(backend.markets)) if m != home]
    result = Agent(backend, trace=trace).run(
        Goal(titles, targets, home, want=preset.get("want", 3)))

    markets = []
    for market, v in result["verdicts"].items():
        markets.append({
            "market": market,
            "agreement_with_home": v["agreement_with_home"],
            "anchor_agreement": v["anchor_agreement"],
            "compared_on": v["compared_on"],
            "travels": [{"title": backend.label(r["entity"]),
                         "image": backend.image(r["entity"]),
                         "shift": r["shift"]} for r in v["travels"]],
            "does_not_travel": [{"title": backend.label(r["entity"]),
                                 "image": backend.image(r["entity"]),
                                 "shift": r["shift"]}
                                for r in v["does_not_travel"]],
            "uncertain": [{"title": t, "image": backend.image_for_title(t)}
                          for t in v["withheld_as_uncertain"]],
            "supported_by": v["supported_by"],
        })

    return {
        "home_market": home,
        "aborted": result["aborted"],
        "markets": markets,
        "abstained": result["abstained"],
        "steps": [{"n": s["step"], "action": s["action"], "reason": s["reason"],
                   "rejected": [r.get("market") for r in s["rejected"]]}
                  for s in result["steps"]],
        "evidence": {"calls": trace.calls, "claims": trace.claims,
                     "summary": trace.summary()},
        "quota_remaining": client.quota_remaining,
    }
