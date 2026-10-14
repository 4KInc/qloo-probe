#!/usr/bin/env python3
"""Does anchor COHERENCE drive the agreement between two readings?

The claim to test: a market defined by artists from one scene produces two
readings that agree, while a market defined by whoever is famous there does
not. If true, the earlier New York refusal was the method correctly detecting
an incoherent market description rather than a fact about the city.

Each candidate supplies two anchor sets drawn from the SAME scene. A candidate
passes if its two readings agree better than the incumbent definition.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from qloo_client import load_dotenv  # noqa: E402

load_dotenv()

from stats import kendall_tau_b, rank_percentiles  # noqa: E402
from taste.qloo_backend import QlooBackend  # noqa: E402

CANDIDATES = {
    "New York, United States": {
        "incumbent (mixed fame)": (["Bruce Springsteen", "Beyonce", "Taylor Swift"],
                                   ["Jay-Z", "Lou Reed", "Billy Joel"]),
        "NY hip-hop":             (["Jay-Z", "Nas", "The Notorious B.I.G."],
                                   ["Wu-Tang Clan", "Mobb Deep", "A Tribe Called Quest"]),
        "downtown art rock":      (["Lou Reed", "Talking Heads", "Patti Smith"],
                                   ["Sonic Youth", "Television", "Blondie"]),
        "standards / Broadway":   (["Frank Sinatra", "Tony Bennett", "Barbra Streisand"],
                                   ["Ella Fitzgerald", "Billie Holiday", "Liza Minnelli"]),
    },
    "Tokyo, Japan": {
        "incumbent (mixed era)":  (["Hikaru Utada", "Ryuichi Sakamoto", "Yumi Matsutoya"],
                                   ["Southern All Stars", "Cornelius", "Ayumi Hamasaki"]),
        "city pop":               (["Tatsuro Yamashita", "Mariya Takeuchi", "Anri"],
                                   ["Taeko Onuki", "Toshiki Kadomatsu", "Junko Ohashi"]),
        "contemporary J-pop":     (["Hikaru Utada", "Ayumi Hamasaki", "Kenshi Yonezu"],
                                   ["Official Hige Dandism", "Aimyon", "King Gnu"]),
    },
    "Berlin, Germany": {
        "incumbent (mixed era)":  (["Kraftwerk", "Rammstein", "Nena"],
                                   ["Can", "Herbert Gronemeyer", "Paul Kalkbrenner"]),
        "krautrock / electronic": (["Kraftwerk", "Can", "Tangerine Dream"],
                                   ["Neu!", "Cluster", "Faust"]),
        "Berlin techno":          (["Paul Kalkbrenner", "Ellen Allien", "Modeselektor"],
                                   ["Apparat", "Ben Klock", "Marcel Dettmann"]),
    },
}


def main():
    spec = json.loads((HERE / "fixtures" / "catalog.json").read_text())
    titles = spec["control"] + spec["regional"]
    backend = QlooBackend(entity_type=spec["entity_type"], consensus=False)
    ids, missing = backend.resolve(titles)
    print("catalog %d/%d resolved\n" % (len(ids), len(titles)))

    results = {}
    for market, options in CANDIDATES.items():
        print("=== %s ===" % market)
        best = None
        for name, (primary, alternate) in options.items():
            backend.markets = dict(backend.markets)
            backend.markets[market] = {"primary": primary, "alternate": alternate}
            backend._anchor_cache = {}
            reads, resolved_counts = {}, {}
            for which, names in (("primary", primary), ("alternate", alternate)):
                aids = backend._anchor_ids(market, which)
                resolved_counts[which] = "%d/%d" % (len(aids), len(names))
                scores = backend._score_once(market, ids, which)
                if scores:
                    reads[which] = rank_percentiles(scores)
            if len(reads) < 2:
                print("  %-24s could not score both readings" % name)
                continue
            tau = kendall_tau_b(reads["primary"], reads["alternate"])
            top = sorted(reads["primary"].items(), key=lambda kv: -kv[1])[:3]
            print("  %-24s tau=%-6s anchors %s/%s   top: %s"
                  % (name, round(tau, 3), resolved_counts["primary"],
                     resolved_counts["alternate"],
                     ", ".join(backend.label(e) for e, _ in top)))
            if best is None or tau > best[1]:
                best = (name, tau, primary, alternate)
        if best:
            print("  -> best: %s (tau %.2f)\n" % (best[0], best[1]))
            results[market] = best
    return results


if __name__ == "__main__":
    main()
