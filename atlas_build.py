#!/usr/bin/env python3
"""Build the audience atlas: resolve, signature, cluster, bootstrap.

Three fixes over the first attempt, each for a named failure:
  * a wider film set (65, spread across genre/era/region) -- a reference set of
    only arthouse titles makes every signature correlate and the clustering
    returns one blob;
  * 75 anchors instead of 23, drawn only from the domains measured to carry
    film signal;
  * AVERAGE linkage instead of single linkage -- single linkage chains, so one
    bridging anchor silently merges two real groups and the bootstrap then
    reports that blob as stable.

Writes out/atlas.json.
"""
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from qloo_client import load_dotenv  # noqa: E402

load_dotenv()

from qloo_client import QlooClient, affinity_of, entities_of, id_of  # noqa: E402
from stats import rank_percentiles  # noqa: E402

CACHE = HERE / "fixtures" / "atlas_resolved.json"


def resolve_all(client, spec):
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    def one(name, etype):
        key = "%s/%s" % (etype, name)
        if key in cache:
            return cache[key]
        hits = entities_of(client.search(name, types=etype))
        rec = None
        if hits:
            rec = {"id": id_of(hits[0]),
                   "image": ((hits[0].get("properties") or {}).get("image") or {}).get("url")}
        cache[key] = rec
        return rec

    films = {}
    for title in spec["films"]:
        rec = one(title, "urn:entity:movie")
        if rec and rec.get("id"):
            films[title] = rec
    anchors = {}
    for etype, names in spec["anchors"].items():
        for name in names:
            rec = one(name, "urn:entity:%s" % etype)
            if rec and rec.get("id"):
                anchors["%s/%s" % (etype, name)] = rec
    CACHE.write_text(json.dumps(cache, indent=2))
    return films, anchors


def signatures(client, films, anchors):
    ids = [v["id"] for v in films.values()]
    rev = {v["id"]: k for k, v in films.items()}
    sigs = {}
    # take is capped at 50 by the API, so the pinned set is scored in chunks
    chunks = [ids[i:i + 50] for i in range(0, len(ids), 50)]
    for label, rec in anchors.items():
        merged = {}
        for chunk in chunks:
            _, body = client.insights({
                "filter.type": "urn:entity:movie",
                "filter.results.entities": ",".join(chunk),
                "signal.interests.entities": rec["id"],
                "take": len(chunk)}, allow_error=True)
            for item in entities_of(body):
                eid, aff = id_of(item), affinity_of(item)
                if eid in rev and aff is not None:
                    merged[rev[eid]] = aff
        if len(merged) >= 20:
            sigs[label] = rank_percentiles(merged)
    return sigs


def correlation(a, b, films):
    shared = [f for f in films if f in a and f in b]
    if len(shared) < 12:
        return None
    n = len(shared)
    ma, mb = sum(a[f] for f in shared) / n, sum(b[f] for f in shared) / n
    num = sum((a[f] - ma) * (b[f] - mb) for f in shared)
    da = sum((a[f] - ma) ** 2 for f in shared) ** 0.5
    db = sum((b[f] - mb) ** 2 for f in shared) ** 0.5
    return num / (da * db) if da and db else None


def average_linkage(sigs, films, threshold):
    """Merge the two closest clusters while their AVERAGE correlation clears
    the threshold. Average linkage is the point: single linkage would let one
    bridging anchor join two groups that have nothing else in common."""
    names = list(sigs)
    corr = {}
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            c = correlation(sigs[names[i]], sigs[names[j]], films)
            if c is not None:
                corr[(names[i], names[j])] = corr[(names[j], names[i])] = c
    clusters = [[n] for n in names]

    def between(a, b):
        vals = [corr[(x, y)] for x in a for y in b if (x, y) in corr]
        return sum(vals) / len(vals) if vals else None

    while True:
        best, pair = None, None
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                v = between(clusters[i], clusters[j])
                if v is not None and (best is None or v > best):
                    best, pair = v, (i, j)
        if best is None or best < threshold:
            break
        i, j = pair
        clusters[i] = clusters[i] + clusters[j]
        clusters.pop(j)
    return clusters


def main():
    spec = json.loads((HERE / "fixtures" / "atlas.json").read_text())
    client = QlooClient(cache=True, log_name="atlas.jsonl")
    films, anchors = resolve_all(client, spec)
    print("resolved %d/%d films, %d/%d anchors"
          % (len(films), len(spec["films"]), len(anchors),
             sum(len(v) for v in spec["anchors"].values())))

    sigs = signatures(client, films, anchors)
    film_names = sorted(films)
    print("%d anchors with usable signatures over %d films (%d calls so far)\n"
          % (len(sigs), len(film_names), client.calls))

    print("threshold sweep (average linkage):")
    chosen = None
    for thr in (0.45, 0.55, 0.60, 0.65, 0.70, 0.75):
        groups = average_linkage(sigs, film_names, thr)
        multi = sorted([g for g in groups if len(g) > 1], key=len, reverse=True)
        biggest = len(multi[0]) if multi else 1
        print("  thr %.2f  clusters=%-3d  groups>1=%-3d  largest=%d"
              % (thr, len(groups), len(multi), biggest))
        # prefer a level with several real groups and no group swallowing half
        if multi and len(multi) >= 3 and biggest <= 0.4 * len(sigs) and chosen is None:
            chosen = (thr, groups)
    if chosen is None:
        chosen = (0.65, average_linkage(sigs, film_names, 0.65))
    thr, groups = chosen
    print("\nchosen threshold %.2f" % thr)
    for g in sorted(groups, key=len, reverse=True):
        if len(g) > 1:
            print("  [%d] %s" % (len(g), ", ".join(sorted(x.split("/")[1] for x in g))))

    rng = random.Random(23)
    trials = 120
    together = {}
    for _ in range(trials):
        sample = [rng.choice(film_names) for _ in film_names]
        for g in average_linkage(sigs, sample, thr):
            for i in range(len(g)):
                for j in range(i + 1, len(g)):
                    key = tuple(sorted((g[i], g[j])))
                    together[key] = together.get(key, 0) + 1

    inside = []
    for g in groups:
        for i in range(len(g)):
            for j in range(i + 1, len(g)):
                key = tuple(sorted((g[i], g[j])))
                inside.append(together.get(key, 0) / trials)
    stable = sum(1 for v in inside if v >= 0.8)
    print("\nbootstrap over %d resamples of the film set:" % trials)
    print("  %d of %d within-cluster pairings survive 80%% of resamples (%.0f%%)"
          % (stable, len(inside), 100 * stable / max(1, len(inside))))
    print("  verdict: %s" % ("STRUCTURE HOLDS" if inside and stable / len(inside) >= 0.6
                             else "TOO FRAGILE TO BUILD ON"))

    (HERE / "out").mkdir(exist_ok=True)
    (HERE / "out" / "atlas.json").write_text(json.dumps({
        "threshold": thr,
        "clusters": [sorted(g) for g in groups if len(g) > 1],
        "singletons": [g[0] for g in groups if len(g) == 1],
        "signatures": sigs, "films": film_names,
        "stability": {"trials": trials, "within_cluster_pairs": len(inside),
                      "survived_80pct": stable},
    }, indent=2))
    print("\n  saved out/atlas.json  (%d Qloo calls total)" % client.calls)


if __name__ == "__main__":
    main()
