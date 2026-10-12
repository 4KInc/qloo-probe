"""Agent-loop tests, run against recorded outcome data instead of the API.

The backend replays the Wikipedia outcome ranks collected before any Qloo
call. That is enough to prove the loop makes decisions: the decisions are what
is under test here, not the data source.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from taste.evidence import Trace
from taste.loop import Agent, Goal

HOME = "New York, United States"
_passed = _failed = 0


def check(label, cond):
    global _passed, _failed
    if cond:
        _passed += 1
        print("  pass  %s" % label)
    else:
        _failed += 1
        print("  FAIL  %s" % label)


class RecordedBackend:
    """Replays per-market ranks. Options force thin coverage, flat ranks or an
    empty market so the loop's refusal paths can be exercised."""

    def __init__(self, ranks, thin=(), flat=(), empty=()):
        self.ranks = ranks
        self.thin, self.flat, self.empty = set(thin), set(flat), set(empty)
        self.calls = []

    def resolve(self, names):
        known = set()
        for market in self.ranks.values():
            known |= set(market)
        return ([n for n in names if n in known],
                [n for n in names if n not in known])

    def score(self, market, ids, seed=None):
        self.calls.append((market, seed))
        if market in self.empty:
            return {}
        data = {k: v for k, v in self.ranks.get(market, {}).items() if k in ids}
        if market in self.thin:
            data = dict(list(data.items())[:4])
        if market in self.flat and seed is None:
            data = {k: 0.5 for k in data}
        return data

    def seeds(self, market):
        return ["audience_a", "audience_b"]


def load_ranks():
    data = json.loads((Path(__file__).parent / "out" /
                       "backtest_outcomes.json").read_text())
    return data["rank_percentiles"]


def main():
    ranks = load_ranks()
    catalog = sorted({t for m in ranks.values() for t in m})
    others = [m for m in ranks if m != HOME]

    print("normal run")
    agent = Agent(RecordedBackend(ranks), trace=Trace())
    res = agent.run(Goal(catalog, others, HOME, want=3))
    check("answered the requested number of markets",
          len(res["markets_answered"]) == 3)
    check("recorded a step per decision", res["step_count"] >= 4)
    check("every step carries a reason", all(s["reason"] for s in res["steps"]))
    check("at least one step names what it passed over",
          any(s["rejected"] for s in res["steps"]))
    check("home market is not reported as a destination",
          HOME not in res["verdicts"])
    first = res["verdicts"][res["markets_answered"][0]]
    check("verdict separates travels from does_not_travel",
          "travels" in first and "does_not_travel" in first)

    print("thin coverage")
    res2 = Agent(RecordedBackend(ranks, thin={"Tokyo, Japan"})).run(
        Goal(catalog, others, HOME, want=4))
    check("thin market abstains instead of ranking",
          "Tokyo, Japan" in res2["abstained"])
    check("thin market is absent from verdicts",
          "Tokyo, Japan" not in res2["verdicts"])

    print("flat ranks")
    backend3 = RecordedBackend(ranks, flat={"Berlin, Germany"})
    res3 = Agent(backend3).run(Goal(catalog, others, HOME, want=4))
    check("flat ranks trigger a seed retry",
          any(s["action"] == "widen_seed" for s in res3["steps"]))
    check("retry used a different seed",
          any(m == "Berlin, Germany" and s is not None for m, s in backend3.calls))

    print("empty market")
    res4 = Agent(RecordedBackend(ranks, empty={"Mumbai, India"})).run(
        Goal(catalog, others, HOME, want=4))
    check("empty market abstains", "Mumbai, India" in res4["abstained"])

    print("unresolvable input")
    res5 = Agent(RecordedBackend(ranks)).run(
        Goal(["Nonexistent %d" % i for i in range(20)], others, HOME))
    check("abort when too little resolves", res5["aborted"] is not None)
    check("no verdicts invented after abort", res5["verdicts"] == {})

    print("\n%d passed, %d failed" % (_passed, _failed))
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
