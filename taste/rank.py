"""Within-query ranking.

Affinity is reported as normalised per query, which makes a ratio of scores
drawn from two different calls meaningless. Everything downstream therefore
works in ranks taken from inside a single response, and the only cross-call
comparison permitted is between rank positions.

This module deliberately exposes no function that divides one call's score by
another's. The guard is structural, not a comment.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stats import kendall_tau_b, rank_percentiles  # noqa: E402


class Ranking:
    """One market's ranking of one candidate set, from one response."""

    def __init__(self, market, scores, request_id=None):
        if not scores:
            raise ValueError("empty score set: abstain instead of ranking nothing")
        self.market = market
        self.raw = dict(scores)
        self.percentiles = rank_percentiles(scores)
        self.request_id = request_id

    def position(self, entity_id):
        return self.percentiles.get(entity_id)

    def shift_against(self, other):
        """Rank movement between two markets, per entity.

        Positive means the entity sits higher here than there. Only entities
        present in BOTH rankings are compared: an entity a market never
        returned is absent, not last, and treating absence as the bottom would
        manufacture the very movement we are trying to detect.
        """
        shared = [e for e in self.percentiles if e in other.percentiles]
        if not shared:
            return {}
        # Percentiles must be RECOMPUTED over the shared set. A percentile
        # taken from a 20-title response is not on the same scale as one from
        # a 15-title response, so subtracting them directly would report
        # movement caused purely by how many titles each market returned.
        mine = rank_percentiles({e: self.raw[e] for e in shared})
        theirs = rank_percentiles({e: other.raw[e] for e in shared})
        return {e: mine[e] - theirs[e] for e in shared}

    def agreement_with(self, other):
        """Tau-b over the shared set, on a common scale."""
        shared = [e for e in self.percentiles if e in other.percentiles]
        if len(shared) < 3:
            return None
        mine = rank_percentiles({e: self.raw[e] for e in shared})
        theirs = rank_percentiles({e: other.raw[e] for e in shared})
        return kendall_tau_b(mine, theirs)

    def __len__(self):
        return len(self.percentiles)
