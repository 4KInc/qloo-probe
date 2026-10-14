"""Qloo backend for the agent loop, built on taste anchors.

Why anchors rather than a location parameter: measured on 13 October 2026,
`filter.location.query` is silently ignored for movies and
`signal.location.query` collapses a pinned candidate set to one or two
results. Neither can rank a catalog per market. Seeding the signal with
entities native to a market does, and it is a more defensible model anyway: a
market here is a taste profile, not a bounding box.

Implements the same three methods the recorded backend does, so the loop and
its tests are unchanged.
"""
from __future__ import annotations

import json
from pathlib import Path

from qloo_client import QlooClient, QlooError, affinity_of, entities_of, id_of
from stats import kendall_tau_b, rank_percentiles

HERE = Path(__file__).resolve().parent.parent
MARKETS = json.loads((HERE / "fixtures" / "markets.json").read_text())["markets"]


# A title is reported only when two independent anchor sets place it within
# this much of each other, measured in rank percentile. At 25 titles one
# position is about 0.04, so 0.25 is roughly six positions: wide enough that
# ordinary jitter does not suppress a result, narrow enough that a title the
# two sets genuinely disagree about is withheld rather than ranked.
DISAGREEMENT_TOLERANCE = 0.25
MIN_AGREED = 8            # fewer agreed titles than this is not a ranking


class QlooBackend:
    """Scores a catalog per market.

    In consensus mode every market is read twice, through two unrelated anchor
    sets, and only titles the two readings agree about are returned. The rest
    are withheld as uncertain rather than ranked.

    This exists because the stability check showed the fine ranking depends on
    which anchors were picked: Mumbai's two readings agree at tau 0.97, New
    York's at 0.13. Averaging the two would hide that. Reporting only the
    agreement, and naming what was withheld, does not.
    """

    def __init__(self, entity_type="urn:entity:movie", client=None, trace=None,
                 markets=None, consensus=True,
                 tolerance=DISAGREEMENT_TOLERANCE):
        self.client = client or QlooClient()
        self.entity_type = entity_type
        self.trace = trace
        self.markets = markets or MARKETS
        self.consensus = consensus
        self.tolerance = tolerance
        self._anchor_cache = {}
        self._name_by_id = {}
        self._image_by_id = {}
        self.last_call_id = None
        self.uncertain = {}        # market -> [entity_id withheld]
        self.agreement = {}        # market -> tau between the two readings

    # ----- helpers --------------------------------------------------------
    def _record(self, path, params, status, n):
        if self.trace:
            self.last_call_id = self.trace.record_call(path, params, status, n)
        return self.last_call_id

    def _resolve_one(self, name, entity_type):
        try:
            body = self.client.search(name, types=entity_type)
        except QlooError:
            return None
        hits = entities_of(body)
        self._record("/search", {"query": name, "types": entity_type}, 200,
                     len(hits))
        if not hits:
            return None
        eid = id_of(hits[0])
        # Qloo serves artwork from its own CDN, so the poster comes from the
        # same source as the affinity rather than a third-party image host.
        image = ((hits[0].get("properties") or {}).get("image") or {}).get("url")
        if eid and image:
            self._image_by_id[eid] = image
        return eid

    def _anchor_ids(self, market, which="primary"):
        key = (market, which)
        if key in self._anchor_cache:
            return self._anchor_cache[key]
        names = (self.markets.get(market) or {}).get(which) or []
        ids = [i for i in (self._resolve_one(n, "urn:entity:artist")
                           for n in names) if i]
        self._anchor_cache[key] = ids
        return ids

    # ----- the loop's interface ------------------------------------------
    def resolve(self, names):
        resolved, missing = [], []
        for name in names:
            eid = self._resolve_one(name, self.entity_type)
            if eid:
                resolved.append(eid)
                self._name_by_id[eid] = name
            else:
                missing.append(name)
        return resolved, missing

    def _score_once(self, market, ids, which):
        anchors = self._anchor_ids(market, which)
        if not anchors:
            return {}
        params = {
            "filter.type": self.entity_type,
            "filter.results.entities": ",".join(ids),
            "signal.interests.entities": ",".join(anchors),
            "take": len(ids),
        }
        try:
            status, body = self.client.insights(params, allow_error=True)
        except QlooError:
            return {}
        items = entities_of(body)
        self._record("/v2/insights", dict(params, **{
            "_market": market, "_anchor_set": which}), status, len(items))
        out = {}
        for item in items:
            eid, aff = id_of(item), affinity_of(item)
            # No fallback to popularity: an item without affinity is simply
            # not scored, and the loop abstains if too few are.
            if eid and aff is not None:
                out[eid] = aff
        return out

    def score(self, market, ids, seed=None):
        """Score the pinned catalog against this market's anchors.

        With consensus off, `seed` selects the anchor set, which is how the
        loop's widen-seed retry reaches a different reading. With consensus
        on, both sets are read and only their agreement is returned.
        """
        if not self.consensus:
            return self._score_once(market, ids, seed or "primary")

        primary = self._score_once(market, ids, "primary")
        alternate = self._score_once(market, ids, "alternate")
        if not primary:
            return {}
        if not alternate:
            # Nothing to cross-check against. Report the single reading rather
            # than nothing, but say so.
            self.uncertain[market] = []
            self.agreement[market] = None
            return primary

        pr, ar = rank_percentiles(primary), rank_percentiles(alternate)
        self.agreement[market] = kendall_tau_b(pr, ar)

        agreed, withheld = {}, []
        for eid in pr:
            if eid not in ar:
                withheld.append(eid)
                continue
            if abs(pr[eid] - ar[eid]) <= self.tolerance:
                # Mean of the two rank positions, not of the raw affinities:
                # the two readings answer different questions, and only their
                # ORDERING is being combined.
                agreed[eid] = (pr[eid] + ar[eid]) / 2.0
            else:
                withheld.append(eid)
        self.uncertain[market] = withheld
        return agreed if len(agreed) >= MIN_AGREED else {}

    def seeds(self, market):
        """Alternate readings available to the retry path."""
        available = (self.markets.get(market) or {})
        return [k for k in ("alternate",) if available.get(k)]

    def label(self, entity_id):
        return self._name_by_id.get(entity_id, entity_id)

    def image(self, entity_id):
        return self._image_by_id.get(entity_id)

    def image_for_title(self, title):
        for eid, name in self._name_by_id.items():
            if name == title:
                return self._image_by_id.get(eid)
        return None
