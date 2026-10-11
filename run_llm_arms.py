#!/usr/bin/env python3
"""Run the two LLM arms of test G while the Qloo key is pending.

The verdict needs the Qloo control arm, so this cannot decide anything on its
own -- with one exception. If the GROUNDED arm's failure rate is already near
zero, Groundwork is dead whatever Qloo scores, because no gap can exist below
a floor of zero. That is worth knowing before the key arrives.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from qloo_client import load_dotenv  # noqa: E402

load_dotenv()
import probe_gap  # noqa: E402
import run_all  # noqa: E402

spec = json.loads((Path(__file__).parent / "fixtures" / "prompts.json").read_text())
prompts = run_all.build_prompts(spec)
print("running %d prompts x 2 arms, OSM-verified at 1 req/sec" % len(prompts))

out = probe_gap.run(prompts, client=None, arms=("ungrounded", "grounded"))
Path("out/gap_llm_arms.json").write_text(json.dumps(out, indent=2, default=str))

print("\n=== LLM ARMS ONLY (no Qloo control yet) ===")
for arm in ("ungrounded", "grounded"):
    a = out["arms"].get(arm, {})
    if "error" in a:
        print("  %-11s ERROR %s" % (arm, a["error"][:120]))
        continue
    w = a.get("wilson") or {}
    print("  %-11s %5.1f%% failed  (%d of %d)  95%% CI [%.1f%%, %.1f%%]"
          % (arm, 100 * (a.get("failure_rate") or 0),
             (a.get("nonexistent", 0) + a.get("wrong_city", 0)),
             a.get("places_checked", 0),
             100 * w.get("lo", 0), 100 * w.get("hi", 0)))

g = (out["arms"].get("grounded") or {}).get("failure_rate")
if g is not None and g <= 0.05:
    print("\n  Grounded arm is at or below 5%. No meaningful gap can exist below")
    print("  that floor: Groundwork is effectively dead before Qloo is measured.")
elif g is not None:
    print("\n  Grounded arm leaves room for a gap. The Qloo control decides it.")
