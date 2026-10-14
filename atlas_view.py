#!/usr/bin/env python3
"""Turn the discovered clusters into a map.

Positions come from classical multidimensional scaling on the cluster-to-
cluster correlation matrix, so distance on the map IS taste distance rather
than a decorative layout. Implemented with the standard library: power
iteration with deflation on the double-centred matrix, which is plenty for
twenty nodes and keeps the project dependency-free.

Reads out/atlas.json (signatures + clusters) and fixtures/atlas_resolved.json
(poster art). Writes out/atlas_view.json, which the server ships as-is: the
map is precomputed, so opening it costs no Qloo calls.
"""
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import atlas_build as AB  # noqa: E402

THRESHOLD = 0.75          # the level measured to survive resampling
TOP_N = 6                 # films shown per audience


def centroid(sigs, members, films):
    out = {}
    for f in films:
        vals = [sigs[m][f] for m in members if f in sigs[m]]
        if vals:
            out[f] = sum(vals) / len(vals)
    return out


def pearson(a, b, keys):
    shared = [k for k in keys if k in a and k in b]
    if len(shared) < 12:
        return 0.0
    n = len(shared)
    ma, mb = sum(a[k] for k in shared) / n, sum(b[k] for k in shared) / n
    num = sum((a[k] - ma) * (b[k] - mb) for k in shared)
    da = sum((a[k] - ma) ** 2 for k in shared) ** 0.5
    db = sum((b[k] - mb) ** 2 for k in shared) ** 0.5
    return num / (da * db) if da and db else 0.0


def mds(corr, n, dims=2, iters=260):
    """Classical MDS. Distance = sqrt(2 * (1 - correlation)), the usual
    conversion from a correlation to a Euclidean-ish distance."""
    d2 = [[2.0 * (1.0 - corr[i][j]) for j in range(n)] for i in range(n)]
    row = [sum(d2[i]) / n for i in range(n)]
    total = sum(row) / n
    b = [[-0.5 * (d2[i][j] - row[i] - row[j] + total) for j in range(n)]
         for i in range(n)]

    coords = [[0.0] * dims for _ in range(n)]
    for d in range(dims):
        v = [math.sin(i * 1.7 + d * 2.3) for i in range(n)]   # deterministic start
        val = 0.0
        for _ in range(iters):
            w = [sum(b[i][j] * v[j] for j in range(n)) for i in range(n)]
            norm = math.sqrt(sum(x * x for x in w))
            if norm < 1e-12:
                break
            v = [x / norm for x in w]
            val = norm
        for i in range(n):
            coords[i][d] = v[i] * math.sqrt(max(val, 0.0))
        # deflate so the next dimension is orthogonal to this one
        for i in range(n):
            for j in range(n):
                b[i][j] -= val * v[i] * v[j]
    return coords


def main():
    atlas = json.loads((HERE / "out" / "atlas.json").read_text())
    resolved = json.loads((HERE / "fixtures" / "atlas_resolved.json").read_text())
    sigs = {k: {kk: float(vv) for kk, vv in v.items()}
            for k, v in atlas["signatures"].items()}
    films = atlas["films"]

    groups = [g for g in AB.average_linkage(sigs, films, THRESHOLD) if len(g) > 1]
    groups.sort(key=len, reverse=True)
    print("%d audiences at threshold %.2f" % (len(groups), THRESHOLD))

    def art(title):
        rec = resolved.get("urn:entity:movie/%s" % title) or {}
        return rec.get("image")

    nodes = []
    cents = []
    for idx, members in enumerate(groups):
        cent = centroid(sigs, members, films)
        cents.append(cent)
        ranked = sorted(cent.items(), key=lambda kv: -kv[1])
        nodes.append({
            "id": "a%d" % idx,
            "size": len(members),
            "members": [{"domain": m.split("/")[0], "name": m.split("/")[1]}
                        for m in sorted(members)],
            "label": " + ".join(sorted(m.split("/")[1] for m in members)[:3]),
            # Short enough not to collide on the map; the full membership is
            # listed in the panel, so nothing is lost by abbreviating here.
            "short": (lambda ns: "%s + %s" % (ns[0], ns[1])
                      if len(ns) == 2 and len(ns[0]) + len(ns[1]) <= 20
                      else "%s +%d" % (ns[0], len(ns) - 1))(
                          sorted(m.split("/")[1] for m in members)),
            "loves": [{"title": t, "image": art(t), "score": round(s, 3)}
                      for t, s in ranked[:TOP_N]],
            "leaves": [{"title": t, "image": art(t), "score": round(s, 3)}
                       for t, s in ranked[-TOP_N:]][::-1],
        })

    n = len(nodes)
    corr = [[1.0 if i == j else pearson(cents[i], cents[j], films)
             for j in range(n)] for i in range(n)]
    coords = mds(corr, n)

    # MDS can place two audiences on top of each other. Relax overlaps with a
    # few gentle repulsion passes: positions stay faithful to taste distance,
    # the circles simply stop colliding.
    radii = [13 + len(g) * 2.3 for g in groups]
    scale = 1.0
    xs0 = [c[0] for c in coords]; ys0 = [c[1] for c in coords]
    spread = max(max(xs0) - min(xs0), max(ys0) - min(ys0), 1e-9)
    scale = 820.0 / spread            # work in roughly the on-screen units
    pts = [[c[0] * scale, c[1] * scale] for c in coords]
    for _ in range(140):
        moved = False
        for i in range(n):
            for j in range(i + 1, n):
                dx = pts[j][0] - pts[i][0]
                dy = pts[j][1] - pts[i][1]
                dist = math.hypot(dx, dy) or 1e-6
                want = radii[i] + radii[j] + 26
                if dist < want:
                    push = (want - dist) / 2.0 * 0.5
                    ux, uy = dx / dist, dy / dist
                    pts[i][0] -= ux * push; pts[i][1] -= uy * push
                    pts[j][0] += ux * push; pts[j][1] += uy * push
                    moved = True
        if not moved:
            break
    coords = pts

    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    spanx = max(max(xs) - min(xs), 1e-9)
    spany = max(max(ys) - min(ys), 1e-9)
    for i, node in enumerate(nodes):
        node["x"] = round((coords[i][0] - min(xs)) / spanx, 4)
        node["y"] = round((coords[i][1] - min(ys)) / spany, 4)

    edges = []
    for i in range(n):
        for j in range(i + 1, n):
            if corr[i][j] >= 0.55:
                edges.append({"a": nodes[i]["id"], "b": nodes[j]["id"],
                              "w": round(corr[i][j], 3)})

    far = min(((corr[i][j], i, j) for i in range(n) for j in range(i + 1, n)))
    near = max(((corr[i][j], i, j) for i in range(n) for j in range(i + 1, n)))
    print("  closest pair : %.2f  %s  <->  %s"
          % (near[0], nodes[near[1]]["label"], nodes[near[2]]["label"]))
    print("  furthest pair: %.2f  %s  <->  %s"
          % (far[0], nodes[far[1]]["label"], nodes[far[2]]["label"]))

    # Stability must be recomputed AT THIS THRESHOLD. out/atlas.json carries
    # the figure from whichever level that script chose, and quoting it here
    # would report the wrong number on the page.
    import random
    rng = random.Random(23)
    trials = 120
    together = {}
    for _ in range(trials):
        sample = [rng.choice(films) for _ in films]
        for g in AB.average_linkage(sigs, sample, THRESHOLD):
            for i in range(len(g)):
                for j in range(i + 1, len(g)):
                    key = tuple(sorted((g[i], g[j])))
                    together[key] = together.get(key, 0) + 1
    inside = []
    for g in groups:
        for i in range(len(g)):
            for j in range(i + 1, len(g)):
                inside.append(together.get(tuple(sorted((g[i], g[j]))), 0) / trials)
    survived = sum(1 for v in inside if v >= 0.8)
    print("  stability at %.2f: %d/%d pairings survive 80%% of resamples (%.0f%%)"
          % (THRESHOLD, survived, len(inside), 100 * survived / max(1, len(inside))))

    out = {
        "threshold": THRESHOLD,
        "stability_at_threshold": {"trials": trials,
                                   "within_cluster_pairs": len(inside),
                                   "survived_80pct": survived},
        "built_from": {"films": len(films), "anchors": len(sigs)},

        "nodes": nodes, "edges": edges,
        "note": ("Distance on this map is taste distance: positions come from "
                 "multidimensional scaling on the correlation between audience "
                 "film-affinity signatures. The map is precomputed, so opening "
                 "it costs no Qloo calls."),
    }
    (HERE / "app" / "atlas_view.json").write_text(json.dumps(out, indent=2))
    print("  wrote app/atlas_view.json  (%d nodes, %d edges)" % (len(nodes), len(edges)))


if __name__ == "__main__":
    main()
