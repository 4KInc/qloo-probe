#!/usr/bin/env python3
"""Does the verdict survive a change of anchors?

A market is modelled here as a handful of musicians native to it. Those names
are a judgement call sitting at the centre of the product, so the output has
to be shown to depend on the market rather than on which three artists were
picked. Three checks:

  1. rank agreement between the primary and alternate anchor sets per market;
  2. overlap of the travels / does-not-travel lists, which is what a user
     actually reads;
  3. whether the home-market result (regional titles ranking highest at home)
     still holds under the alternate anchors.

Check 3 is the one that matters most. If it survives an entirely different
anchor set, the effect belongs to the market.
"""
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from qloo_client import load_dotenv  # noqa: E402

load_dotenv()

from stats import jackknife_tau_se, kendall_tau_b, rank_percentiles  # noqa: E402
from taste.qloo_backend import QlooBackend  # noqa: E402

HOME = {
    "RRR": "Mumbai, India", "3 Idiots": "Mumbai, India", "Dangal": "Mumbai, India",
    "Your Name": "Tokyo, Japan", "Spirited Away": "Tokyo, Japan",
    "Shoplifters": "Tokyo, Japan", "Drive My Car": "Tokyo, Japan",
    "City of God": "Sao Paulo, Brazil", "Elite Squad": "Sao Paulo, Brazil",
    "Das Boot": "Berlin, Germany", "Good Bye Lenin!": "Berlin, Germany",
}


def binomial_p(wins, total):
    return sum(math.comb(total, k) for k in range(wins, total + 1)) / 2.0 ** total


def main():
    spec = json.loads((HERE / "fixtures" / "catalog.json").read_text())
    titles = spec["control"] + spec["regional"]
    backend = QlooBackend(entity_type=spec["entity_type"])
    ids, missing = backend.resolve(titles)
    print("catalog resolved %d/%d%s" % (len(ids), len(titles),
                                        (" missing %s" % missing) if missing else ""))

    by_set = {}
    for which in ("primary", "alternate"):
        by_set[which] = {}
        for market in backend.markets:
            scores = backend.score(market, ids, seed=None if which == "primary" else which)
            if scores:
                by_set[which][market] = rank_percentiles(scores)

    print("\n1. rank agreement between anchor sets")
    agreements = []
    for market in backend.markets:
        a = by_set["primary"].get(market)
        b = by_set["alternate"].get(market)
        if not a or not b:
            print("  %-26s one anchor set returned nothing" % market)
            continue
        tau = kendall_tau_b(a, b)
        se = jackknife_tau_se(a, b)
        agreements.append(tau)
        print("  %-26s tau=%-6s se=%-6s" % (market, round(tau, 3), round(se, 3)))

    print("\n2. overlap of what a user actually reads (top 5 / bottom 5)")
    for market in backend.markets:
        a, b = by_set["primary"].get(market), by_set["alternate"].get(market)
        if not a or not b:
            continue
        def ends(r):
            order = sorted(r.items(), key=lambda kv: -kv[1])
            return ({backend.label(e) for e, _ in order[:5]},
                    {backend.label(e) for e, _ in order[-5:]})
        ta, ba = ends(a)
        tb, bb = ends(b)
        print("  %-26s top %d/5 shared, bottom %d/5 shared"
              % (market, len(ta & tb), len(ba & bb)))

    print("\n3. home-market effect under each anchor set")
    for which in ("primary", "alternate"):
        wins = total = 0
        for title, home in HOME.items():
            ranks = by_set[which]
            eid = next((i for i in ids if backend.label(i) == title), None)
            if eid is None or home not in ranks or eid not in ranks[home]:
                continue
            here = ranks[home][eid]
            others = [ranks[m][eid] for m in ranks if m != home and eid in ranks[m]]
            if not others:
                continue
            total += 1
            wins += here > sum(others) / len(others)
        if total:
            print("  %-10s %d of %d regional titles rank highest at home, p=%.4f"
                  % (which, wins, total, binomial_p(wins, total)))

    verdict = ("STABLE" if agreements and min(agreements) >= 0.5
               else "SENSITIVE" if agreements else "NO DATA")
    print("\n  anchor sensitivity: %s (lowest pairwise tau %.2f)"
          % (verdict, min(agreements) if agreements else float("nan")))


if __name__ == "__main__":
    main()
