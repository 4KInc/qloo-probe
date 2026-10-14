#!/usr/bin/env python3
"""Record each preset so the demo survives an exhausted quota.

Judging runs to 16 November. A public URL with no login will be crawled, and
the monthly quota is shared with development. A recorded run is the real
output of this pipeline against the live API, served verbatim and labelled
CACHED -- not a synthetic stand-in.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from engine import run_translation  # noqa: E402

presets = json.loads((HERE / "app" / "presets.json").read_text())["presets"]
out_dir = HERE / "app" / "cache"
out_dir.mkdir(parents=True, exist_ok=True)

for preset in presets:
    try:
        result = run_translation(preset)
    except Exception as exc:
        print("  %-20s FAILED %s: %s" % (preset["id"], type(exc).__name__,
                                         str(exc)[:120]))
        continue
    (out_dir / ("%s.json" % preset["id"])).write_text(json.dumps(result, indent=2))
    answered = len(result.get("markets") or [])
    note = "aborted" if result.get("aborted") else "%d markets" % answered
    print("  %-20s recorded (%s, %d calls)"
          % (preset["id"], note, result["evidence"]["summary"]["calls"]))
