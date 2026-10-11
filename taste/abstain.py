"""Abstention.

Every concept needs to decline. Catalog Passport must say "this market is too
thinly covered to answer"; Preflight must mark an element uncovered rather
than scoring it a miss; Groundwork must report "no verdict" rather than
inventing a gap. A coverage hole scored as a low result is a false negative
presented as a finding, which is worse than silence.

Abstention is also the part of the agent loop a screener can see: an agent
that knows when it cannot answer reads differently from a dashboard.
"""
from __future__ import annotations

MIN_RESOLVED = 8          # below this, the input itself is unusable
MIN_PER_MARKET = 12       # below this, a market's ranking carries no signal
MIN_SHARED_FOR_TAU = 12   # matches the probe's overlap floor


class Verdict:
    ANSWER = "answer"
    ABSTAIN_INPUT = "abstain_input_unresolved"
    ABSTAIN_COVERAGE = "abstain_market_coverage"
    ABSTAIN_OVERLAP = "abstain_insufficient_overlap"


def check_input(resolved, requested):
    if len(resolved) < MIN_RESOLVED:
        return Verdict.ABSTAIN_INPUT, (
            "Only %d of %d inputs resolved to known entities. Too little to "
            "characterise what you gave me; add more, or name them differently."
            % (len(resolved), len(requested)))
    return Verdict.ANSWER, None


def check_market(market, ranking_size, catalog_size):
    if ranking_size < MIN_PER_MARKET:
        return Verdict.ABSTAIN_COVERAGE, (
            "%s surfaced %d of %d catalog items. That is too thin to rank, so "
            "no verdict is offered for this market. This is a coverage gap in "
            "the graph, not a judgement about the catalog."
            % (market, ranking_size, catalog_size))
    return Verdict.ANSWER, None


def check_pair(market_a, market_b, shared):
    if shared < MIN_SHARED_FOR_TAU:
        return Verdict.ABSTAIN_OVERLAP, (
            "%s and %s share only %d items. Comparing them would mostly "
            "compare the globally popular titles that survive a thin overlap, "
            "which biases agreement upward." % (market_a, market_b, shared))
    return Verdict.ANSWER, None
