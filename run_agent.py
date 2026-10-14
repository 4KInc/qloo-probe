#!/usr/bin/env python3
"""Run the agent against the live Qloo API.

    python3 run_agent.py                 # 3 markets
    python3 run_agent.py --want 4
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from qloo_client import load_dotenv  # noqa: E402

load_dotenv()

from taste.evidence import Trace  # noqa: E402
from taste.loop import Agent, Goal  # noqa: E402
from taste.qloo_backend import QlooBackend  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--home", default="New York, United States")
    ap.add_argument("--want", type=int, default=3)
    args = ap.parse_args()

    catalog_spec = json.loads((HERE / "fixtures" / "catalog.json").read_text())
    titles = catalog_spec["control"] + catalog_spec["regional"]

    trace = Trace()
    backend = QlooBackend(entity_type=catalog_spec["entity_type"], trace=trace)
    markets = [m for m in backend.markets if m != args.home]

    result = Agent(backend, trace=trace).run(
        Goal(titles, markets, args.home, want=args.want))

    print("=== decision trace ===")
    for s in result["steps"]:
        print(" %d. %-13s %s" % (s["step"], s["action"], s["reason"][:92]))
        if s["rejected"]:
            print("      passed over: %s"
                  % ", ".join(r.get("market", "?").split(",")[0]
                              for r in s["rejected"]))

    print("\n=== verdicts ===")
    for market, v in result["verdicts"].items():
        print("\n %s   agreement with home %.2f, compared on %d titles"
              % (market, v["agreement_with_home"], v["compared_on"]))
        print("   travels:")
        for row in v["travels"][:3]:
            print("     %-28s %+.2f" % (backend.label(row["entity"])[:28],
                                        row["shift"]))
        if v["does_not_travel"]:
            print("   does not travel:")
            for row in v["does_not_travel"][:3]:
                print("     %-28s %+.2f" % (backend.label(row["entity"])[:28],
                                            row["shift"]))

    if result["abstained"]:
        print("\n=== abstained ===")
        for market, why in result["abstained"].items():
            print("  %s: %s" % (market, why[:100]))

    path = trace.save()
    print("\n%s" % json.dumps(trace.summary()))
    print("trace: %s" % path)


if __name__ == "__main__":
    main()
