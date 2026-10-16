#!/usr/bin/env python3
"""Let each discovered audience name itself from its members' Qloo tags.

Naming the clusters by hand would quietly undo the point of discovering them:
the groups would be the data's, but the labels would be mine. Instead each
cluster takes the tags its members share that other clusters do NOT, scored
TF-IDF style, so the name comes from the same graph the grouping did.

Writes fixtures/cluster_tags.json.
"""
import json
import math
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from qloo_client import load_dotenv  # noqa: E402

load_dotenv()

from qloo_client import QlooClient, entities_of  # noqa: E402

TAG_CACHE = HERE / "fixtures" / "anchor_tags.json"
# Qloo's own descriptive tags are useful; its mood adjectives ("Devoted",
# "Passionate") describe everything and name nothing.
USEFUL_PREFIXES = ("genre", "media", "category", "style", "subgenre")
STOP = {"soundtrack", "music", "film", "movie", "television", "video game",
        "drama", "general", "contemporary", "other"}


def tags_for(client, name, etype, cache):
    key = "%s/%s" % (etype, name)
    if key in cache:
        return cache[key]
    hits = entities_of(client.search(name, types=etype))
    out = []
    if hits:
        for t in (hits[0].get("tags") or []):
            if not isinstance(t, dict):
                continue
            tid = str(t.get("tag_id") or t.get("id") or "")
            kind = tid.split(":")[1] if ":" in tid else (t.get("type") or "")
            label = (t.get("name") or "").strip()
            if not label or label.lower() in STOP:
                continue
            if any(p in tid or p in str(t.get("type") or "") for p in USEFUL_PREFIXES):
                out.append(label)
    cache[key] = out
    return out


def main():
    atlas = json.loads((HERE / "app" / "atlas_view.json").read_text())
    client = QlooClient(cache=True, log_name="tags.jsonl")
    cache = json.loads(TAG_CACHE.read_text()) if TAG_CACHE.exists() else {}

    per_cluster = []
    for node in atlas["nodes"]:
        bag = Counter()
        for m in node["members"]:
            for t in tags_for(client, m["name"], "urn:entity:%s" % m["domain"], cache):
                bag[t] += 1
        per_cluster.append(bag)
    TAG_CACHE.write_text(json.dumps(cache, indent=2))

    # document frequency across clusters, so a tag everyone carries names nobody
    df = Counter()
    for bag in per_cluster:
        for t in bag:
            df[t] += 1
    n = len(per_cluster)

    names = {}
    for node, bag in zip(atlas["nodes"], per_cluster):
        size = max(1, len(node["members"]))
        scored = []
        for t, c in bag.items():
            if c < max(2, size * 0.5):       # must be shared, not one member's quirk
                continue
            scored.append((c / size * math.log(n / (1 + df[t])), t))
        scored.sort(reverse=True)
        picked = [t for _, t in scored[:3]]
        names[node["id"]] = picked
        print("  %-44s %s" % (node["label"][:44], ", ".join(picked) or "(no shared tags)"))

    (HERE / "fixtures" / "cluster_tags.json").write_text(json.dumps(names, indent=2))
    print("\n  wrote fixtures/cluster_tags.json (%d calls)" % client.calls)


if __name__ == "__main__":
    main()
