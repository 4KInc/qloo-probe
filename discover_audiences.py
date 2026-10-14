#!/usr/bin/env python3
"""Discover audiences instead of assuming them, and test whether they hold.

Hand-picking three artists per scene is the weakest part of the method: the
audiences are mine, not the data's. This takes a pool of candidate anchors
across the domains measured to carry film signal (tv_show, videogame, artist),
computes each one's film-affinity signature, and clusters the signatures.

The audiences that fall out are whatever the graph says they are.

Stability is then tested by bootstrap: resample the film set, re-cluster, and
measure how often two anchors land together. A cluster that only exists for
one particular choice of films is not a finding.
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

CANDIDATES = [
    ("artist", "Jay-Z"), ("artist", "Nas"), ("artist", "Wu-Tang Clan"),
    ("artist", "Lou Reed"), ("artist", "Talking Heads"), ("artist", "Patti Smith"),
    ("artist", "A. R. Rahman"), ("artist", "Arijit Singh"),
    ("artist", "Tatsuro Yamashita"), ("artist", "Mariya Takeuchi"),
    ("artist", "Caetano Veloso"), ("artist", "Gilberto Gil"),
    ("artist", "Kraftwerk"), ("artist", "Ben Klock"),
    ("tv_show", "The Wire"), ("tv_show", "Snowfall"),
    ("tv_show", "Twin Peaks"), ("tv_show", "Fleabag"),
    ("tv_show", "Terrace House"), ("tv_show", "Dark"),
    ("videogame", "Grand Theft Auto V"), ("videogame", "Disco Elysium"),
    ("videogame", "Journey"), ("videogame", "NBA 2K24"),
]


def signatures(client, pinned, rev):
    sigs = {}
    for etype, name in CANDIDATES:
        hits = entities_of(client.search(name, types="urn:entity:%s" % etype))
        if not hits:
            continue
        eid = id_of(hits[0])
        _, body = client.insights({
            "filter.type": "urn:entity:movie",
            "filter.results.entities": pinned,
            "signal.interests.entities": eid,
            "take": 50}, allow_error=True)
        scores = {rev[id_of(i)]: affinity_of(i) for i in entities_of(body)
                  if id_of(i) in rev and affinity_of(i) is not None}
        if len(scores) >= 10:
            sigs["%s/%s" % (etype, name)] = rank_percentiles(scores)
    return sigs


def correlation(a, b, films):
    shared = [f for f in films if f in a and f in b]
    if len(shared) < 6:
        return None
    n = len(shared)
    ma = sum(a[f] for f in shared) / n
    mb = sum(b[f] for f in shared) / n
    num = sum((a[f] - ma) * (b[f] - mb) for f in shared)
    da = sum((a[f] - ma) ** 2 for f in shared) ** 0.5
    db = sum((b[f] - mb) ** 2 for f in shared) ** 0.5
    return num / (da * db) if da and db else None


def cluster(sigs, films, k_threshold=0.55):
    """Agglomerative by correlation, single pass: join anchors whose signatures
    correlate above the threshold. Deliberately simple -- the question is
    whether structure exists, not whether a fancy algorithm can find it."""
    names = list(sigs)
    parent = {n: n for n in names}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            c = correlation(sigs[names[i]], sigs[names[j]], films)
            if c is not None and c >= k_threshold:
                parent[find(names[i])] = find(names[j])
    groups = {}
    for n in names:
        groups.setdefault(find(n), []).append(n)
    return list(groups.values())


def main():
    client = QlooClient(cache=True, log_name="discover.jsonl")
    resolved = json.loads((HERE / "fixtures" / "resolved.json").read_text())
    film_ids = {t: v["id"] for t, v in resolved["movies"].items()}
    pinned = ",".join(film_ids.values())
    rev = {v: k for k, v in film_ids.items()}

    sigs = signatures(client, pinned, rev)
    films = sorted({f for s in sigs.values() for f in s})
    print("%d anchors with usable signatures over %d films (%d calls)\n"
          % (len(sigs), len(films), client.calls))

    base = cluster(sigs, films)
    print("clusters on the full film set:")
    for g in sorted(base, key=len, reverse=True):
        if len(g) > 1:
            print("  [%d] %s" % (len(g), ", ".join(sorted(g))))
    singles = [g[0] for g in base if len(g) == 1]
    if singles:
        print("  alone: %s" % ", ".join(sorted(singles)))

    # Bootstrap: does a pair stay together when the film set is resampled?
    rng = random.Random(23)
    together, trials = {}, 160
    for _ in range(trials):
        sample = [rng.choice(films) for _ in films]
        for g in cluster(sigs, sample):
            for i in range(len(g)):
                for j in range(i + 1, len(g)):
                    key = tuple(sorted((g[i], g[j])))
                    together[key] = together.get(key, 0) + 1

    print("\nmost stable pairings (share of %d resamples):" % trials)
    for key, n in sorted(together.items(), key=lambda kv: -kv[1])[:12]:
        print("  %4.0f%%  %s  +  %s" % (100 * n / trials, key[0], key[1]))

    strong = sum(1 for n in together.values() if n >= 0.8 * trials)
    print("\n  %d pairings survive 80%% of resamples" % strong)
    print("  verdict: %s" % ("STRUCTURE IS STABLE" if strong >= 5
                             else "TOO FRAGILE TO BUILD ON"))


if __name__ == "__main__":
    main()
