"""Tests for the shared core. Run: python3 test_taste.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from taste.abstain import Verdict, check_input, check_market, check_pair
from taste.evidence import Trace, UnsupportedClaim
from taste.params import ParamGuard
from taste.rank import Ranking

passed = failed = 0


def check(label, cond):
    global passed, failed
    if cond:
        passed += 1
        print("  pass  %s" % label)
    else:
        failed += 1
        print("  FAIL  %s" % label)


print("rank")
a = Ranking("A", {"x": 0.9, "y": 0.5, "z": 0.1})
b = Ranking("B", {"x": 9.0, "y": 5.0, "z": 1.0, "w": 7.0})
check("different set sizes produce zero shift when order agrees",
      all(abs(v) < 1e-9 for v in a.shift_against(b).values()))
check("tau is 1.0 for identical ordering", a.agreement_with(b) == 1.0)
check("entity absent from one market is excluded", "w" not in a.shift_against(b))
try:
    Ranking("empty", {})
    check("empty ranking rejected", False)
except ValueError:
    check("empty ranking rejected", True)

print("params")
g = ParamGuard()
kept, dropped, warns = g.check("urn:entity:artist",
                               {"filter.type": "urn:entity:artist",
                                "filter.release_year.min": 2000})
check("movie-only parameter dropped for artists", "filter.release_year.min" in dropped)
check("valid parameter kept", "filter.type" in kept)
g.record("urn:entity:artist", "filter.tags", honoured=False)
_, _, warns2 = g.check("urn:entity:artist", {"filter.tags": "x"})
check("measured-ignored parameter raises a warning",
      any("IGNORED" in w for w in warns2))

print("abstain")
check("too few resolved inputs abstains",
      check_input(["a"] * 3, ["a"] * 25)[0] == Verdict.ABSTAIN_INPUT)
check("thin market abstains", check_market("Tokyo", 4, 25)[0] == Verdict.ABSTAIN_COVERAGE)
check("thin overlap abstains", check_pair("A", "B", 7)[0] == Verdict.ABSTAIN_OVERLAP)
check("healthy market answers", check_market("Tokyo", 20, 25)[0] == Verdict.ANSWER)

print("evidence")
t = Trace()
cid = t.record_call("/v2/insights", {"filter.type": "urn:entity:movie"}, 200, 20)
t.claim("Parasite ranks higher in Berlin than in New York", [cid])
try:
    t.claim("unsupported assertion", [])
    check("claim without a call is refused", False)
except UnsupportedClaim:
    check("claim without a call is refused", True)
try:
    t.claim("bad reference", ["c99"])
    check("claim citing an unknown call is refused", False)
except UnsupportedClaim:
    check("claim citing an unknown call is refused", True)
t.abstention("abstain_market_coverage", "Mumbai too thin to rank")
check("abstention is recorded, not dropped", t.summary()["abstentions"] == 1)

print("\n%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
