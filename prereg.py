"""Pre-registration: freeze the fixtures and the decision rules before any
data is seen.

The backtest and the kill gates are only worth anything if the thresholds were
chosen in advance. This writes a hashed record so that a sceptical reader --
or a judge -- can confirm the rules were not fitted to the result.
"""
from __future__ import annotations

import datetime
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).parent

RULES = {
    "location_signal_test": {
        "pass_if": ">=2 non-US market pairs with Kendall tau-b < 0.70, "
                   "bootstrap hi95 < 0.85, and control-set rank variance "
                   "below the rest of the catalog",
        "decides": "Catalog Passport is viable",
    },
    "groundwork_gap_test": {
        "alive_if": "combined existence+geo failure rate >= 25%",
        "dead_if": "<= 10%",
        "decides": "whether the Groundwork branch has a premise at all",
    },
    "normalisation_test": {
        "per_query_if": "the same entity's affinity changes between two "
                        "different candidate sets",
        "consequence": "all cross-call ratio maths is abandoned in favour of "
                       "within-query ranks",
    },
    "planned_backtest": {
        "design": "predict relative country-level performance for the catalog "
                  "from Qloo ranks alone, compare against public country box "
                  "office splits",
        "honesty_constraints": [
            "titles and metric fixed here, before outcomes are looked up",
            "Qloo's graph is built partly from real consumption signal, so this "
            "is less circular than scoring Qloo with Qloo, NOT independent of it",
            "report N and the confidence interval, never a bare correlation",
        ],
    },
}


def content_digest(catalog, prompts):
    """Hash the CONTENT only -- never the timestamp. A digest that changes on
    every run proves nothing about what was fixed in advance."""
    blob = json.dumps({"catalog": catalog, "prompts": prompts,
                       "decision_rules": RULES}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def write():
    catalog = json.loads((HERE / "fixtures" / "catalog.json").read_text())
    prompts = json.loads((HERE / "fixtures" / "prompts.json").read_text())
    digest = content_digest(catalog, prompts)
    out = HERE / "out" / "prereg.json"
    out.parent.mkdir(exist_ok=True)

    if out.exists():
        prior = json.loads(out.read_text())
        if prior.get("sha256") == digest:
            return digest  # same rules, same fixtures: leave the original alone
        # Fixtures or thresholds changed after registration. Keep the original
        # and record the amendment beside it, so the edit is visible rather
        # than silent. Thresholds moved after seeing data are worthless.
        amended = HERE / "out" / ("prereg_amended_%s.json" % digest[:12])
        amended.write_text(json.dumps({
            "amended_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "supersedes_sha256": prior.get("sha256"),
            "sha256": digest, "catalog": catalog, "prompts": prompts,
            "decision_rules": RULES,
            "warning": "Original pre-registration retained in prereg.json. "
                       "Any threshold changed after data was seen must be "
                       "disclosed when the numbers are quoted.",
        }, indent=2))
        print("  !! fixtures/rules changed after registration -> %s" % amended.name)
        return prior.get("sha256")

    out.write_text(json.dumps({
        "registered_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "sha256": digest, "catalog": catalog, "prompts": prompts,
        "decision_rules": RULES,
    }, indent=2))
    return digest


if __name__ == "__main__":
    print("pre-registration sha256:", write())
