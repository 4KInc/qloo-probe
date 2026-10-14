#!/usr/bin/env python3
"""Freeze entity resolution to a committed fixture.

The catalog and the anchor sets never change, yet every run re-resolved all of
them: 46 /search calls out of 65 per run, for answers that are identical every
time. With a monthly quota of 10,000 that caps the demo at about 150 runs for
the whole judging period.

This resolves once and writes fixtures/resolved.json. At runtime the backend
reads it and spends calls only on the insights queries that actually differ.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from qloo_client import load_dotenv  # noqa: E402

load_dotenv()

from qloo_client import QlooClient, entities_of, id_of  # noqa: E402

client = QlooClient(cache=False, log_name="resolve_build.jsonl")


def resolve(name, entity_type):
    hits = entities_of(client.search(name, types=entity_type))
    if not hits:
        return None
    hit = hits[0]
    return {
        "id": id_of(hit),
        "image": ((hit.get("properties") or {}).get("image") or {}).get("url"),
        "resolved_name": hit.get("name"),
    }


def main():
    catalog = json.loads((HERE / "fixtures" / "catalog.json").read_text())
    markets = json.loads((HERE / "fixtures" / "markets.json").read_text())["markets"]

    out = {"movies": {}, "artists": {}, "note":
           "Frozen entity resolution. Rebuild with build_resolution_cache.py "
           "whenever the catalog or an anchor set changes."}

    for title in catalog["control"] + catalog["regional"]:
        got = resolve(title, catalog["entity_type"])
        if got:
            out["movies"][title] = got
        print("  movie   %-34s %s" % (title, "ok" if got else "UNRESOLVED"))

    names = sorted({n for m in markets.values()
                    for key in ("primary", "alternate") for n in (m.get(key) or [])})
    for name in names:
        got = resolve(name, "urn:entity:artist")
        if got:
            out["artists"][name] = got
        print("  artist  %-34s %s" % (name, "ok" if got else "UNRESOLVED"))

    (HERE / "fixtures" / "resolved.json").write_text(json.dumps(out, indent=2))
    print("\n  %d movies, %d artists frozen; %d live calls spent building it"
          % (len(out["movies"]), len(out["artists"]), client.calls))


if __name__ == "__main__":
    main()
