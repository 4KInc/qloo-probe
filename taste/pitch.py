"""Pitch desk: rank YOUR slate for a buyer described by what they already hold.

The atlas answers with audiences we discovered. A sales agent needs the
opposite: her own titles, and a specific buyer who is not on our map. So a
buyer here is described the way the industry already describes one -- by their
catalogue -- and the profile is built from those films directly.

That also restores the consensus check the small clusters could not support: a
catalogue of eight titles splits into two halves of four, each half becomes an
independent reading, and any title the two halves rank very differently is
withheld rather than reported.
"""
from __future__ import annotations

from qloo_client import QlooError, affinity_of, entities_of, id_of
from stats import kendall_tau_b, rank_percentiles

MIN_SLATE = 4
MIN_BUYER = 4
SPLIT_MIN = 6          # below this a catalogue cannot be halved meaningfully
DISAGREE = 0.25        # rank-percentile gap above which a title is withheld
MAX_TITLES = 50        # the API caps take at 50


class PitchError(RuntimeError):
    pass


def resolve_titles(client, titles, entity_type="urn:entity:movie", trace=None):
    """Resolve, reporting what the graph does not know rather than dropping it."""
    found, missing = [], []
    for raw in titles:
        name = raw.strip()
        if not name:
            continue
        try:
            hits = entities_of(client.search(name, types=entity_type))
        except QlooError:
            hits = []
        if trace is not None:
            trace.record_call("/search", {"query": name}, 200, len(hits))
        if not hits:
            missing.append(name)
            continue
        props = hits[0].get("properties") or {}
        found.append({"asked": name,
                      "name": hits[0].get("name") or name,
                      "id": id_of(hits[0]),
                      "image": (props.get("image") or {}).get("url")})
    return found, missing


def _score(client, slate_ids, signal_ids, entity_type, trace=None, label=None):
    params = {"filter.type": entity_type,
              "filter.results.entities": ",".join(slate_ids),
              "signal.interests.entities": ",".join(signal_ids),
              "take": min(len(slate_ids), MAX_TITLES)}
    status, body = client.insights(params, allow_error=True)
    items = entities_of(body)
    if trace is not None:
        trace.record_call("/v2/insights", dict(params, _reading=label or "-"),
                          status, len(items))
    out = {}
    for item in items:
        eid, aff = id_of(item), affinity_of(item)
        if eid and aff is not None:        # never fall back to popularity
            out[eid] = aff
    return out


def profile(client, slate_ids, catalogue_ids, entity_type, trace=None, tag="buyer"):
    """Rank the slate for one taste profile, cross-checked by splitting the
    describing catalogue into halves. Returns (ranks, withheld, agreement)."""
    whole = _score(client, slate_ids, catalogue_ids, entity_type, trace, tag)
    if not whole:
        raise PitchError("Qloo returned no affinities for that combination")
    if len(catalogue_ids) < SPLIT_MIN:
        return rank_percentiles(whole), [], None

    half_a = catalogue_ids[0::2]
    half_b = catalogue_ids[1::2]
    ra = _score(client, slate_ids, half_a, entity_type, trace, tag + ":half A")
    rb = _score(client, slate_ids, half_b, entity_type, trace, tag + ":half B")
    if not ra or not rb:
        return rank_percentiles(whole), [], None
    pa, pb = rank_percentiles(ra), rank_percentiles(rb)
    shared = [e for e in pa if e in pb]
    withheld = [e for e in shared if abs(pa[e] - pb[e]) > DISAGREE]
    agreement = kendall_tau_b(pa, pb)
    return rank_percentiles(whole), withheld, agreement


def run(client, slate_titles, buyer_titles, home_titles=None,
        entity_type="urn:entity:movie", trace=None):
    slate, slate_missing = resolve_titles(client, slate_titles, entity_type, trace)
    if len(slate) < MIN_SLATE:
        raise PitchError(
            "Only %d of your titles resolved. At least %d are needed before a "
            "ranking means anything." % (len(slate), MIN_SLATE))
    buyer, buyer_missing = resolve_titles(client, buyer_titles, entity_type, trace)
    if len(buyer) < MIN_BUYER:
        raise PitchError(
            "Only %d of the buyer's titles resolved. At least %d are needed to "
            "describe what they like." % (len(buyer), MIN_BUYER))

    # Qloo excludes a signal entity from its own results, so any title that
    # appears both in the slate and in a describing catalogue comes back
    # unscored and would silently disappear. Take it out openly instead.
    describing = {b["id"] for b in buyer}
    home_pre, _ = (resolve_titles(client, home_titles, entity_type, trace)
                   if home_titles else ([], []))
    describing |= {h["id"] for h in home_pre}
    overlap = [s["name"] for s in slate if s["id"] in describing]
    slate = [s for s in slate if s["id"] not in describing]
    if len(slate) < MIN_SLATE:
        raise PitchError(
            "After removing titles that also appear in the catalogues you used "
            "to describe the buyer (%s), only %d of your titles are left. Qloo "
            "cannot score a title against itself."
            % (", ".join(overlap) or "none", len(slate)))

    slate_ids = [s["id"] for s in slate][:MAX_TITLES]
    by_id = {s["id"]: s for s in slate}

    buyer_ranks, withheld, buyer_agreement = profile(
        client, slate_ids, [b["id"] for b in buyer], entity_type, trace, "buyer")

    home_ranks, home_agreement, home = None, None, []
    if home_titles:
        home = home_pre
        if len(home) >= MIN_BUYER:
            home_ranks, home_withheld, home_agreement = profile(
                client, slate_ids, [h["id"] for h in home], entity_type,
                trace, "home")
            withheld = list(set(withheld) | set(home_withheld))

    rows, uncomparable = [], []
    for eid, rank in buyer_ranks.items():
        if eid in withheld or eid not in by_id:
            continue
        row = {"title": by_id[eid]["name"], "image": by_id[eid]["image"],
               "fit": round(rank, 3)}
        if home_ranks:
            if eid in home_ranks:
                row["shift"] = round(rank - home_ranks[eid], 3)
            else:
                # Scored for the buyer but not for home: no movement can be
                # computed, and reporting it as zero would be a lie.
                uncomparable.append(row)
                continue
        rows.append(row)
    key = "shift" if home_ranks else "fit"
    rows.sort(key=lambda r: -r[key])

    return {
        "mode": "shift" if home_ranks else "fit",
        "rows": rows,
        "withheld": [by_id[e]["name"] for e in withheld if e in by_id],
        "uncomparable": uncomparable,
        "excluded_overlap": overlap,
        "buyer": {"resolved": [b["name"] for b in buyer],
                  "missing": buyer_missing,
                  "halves_agree": (round(buyer_agreement, 3)
                                   if buyer_agreement is not None else None)},
        "home": {"resolved": [h["name"] for h in home],
                 "halves_agree": (round(home_agreement, 3)
                                  if home_agreement is not None else None)},
        "slate": {"resolved": len(slate), "missing": slate_missing},
    }
