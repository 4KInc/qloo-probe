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

HERE = Path(__file__).resolve().parent.parent
MARKETS = json.loads((HERE / "fixtures" / "markets.json").read_text())["markets"]


class QlooBackend:
    def __init__(self, entity_type="urn:entity:movie", client=None, trace=None,
                 markets=None):
        self.client = client or QlooClient()
        self.entity_type = entity_type
        self.trace = trace
        self.markets = markets or MARKETS
        self._anchor_cache = {}
        self._name_by_id = {}
        self.last_call_id = None

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
        return id_of(hits[0]) if hits else None

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

    def score(self, market, ids, seed=None):
        """Score the pinned catalog against this market's anchors.

        `seed` selects which anchor set to use, which is how the loop's
        widen-seed retry reaches a different reading of the same market.
        """
        which = seed or "primary"
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

    def seeds(self, market):
        """Alternate readings available to the retry path."""
        available = (self.markets.get(market) or {})
        return [k for k in ("alternate",) if available.get(k)]

    def label(self, entity_id):
        return self._name_by_id.get(entity_id, entity_id)
