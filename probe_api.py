"""Tests A-E: what the hackathon key actually does.

Everything here is a claim sourced from entrant repositories rather than from
Qloo's documentation. Each test either confirms it against the live API or
marks it UNKNOWN. Nothing in the build plan may rest on an unconfirmed row.
"""
from __future__ import annotations

import json

from qloo_client import QlooClient, QlooError, affinity_of, entities_of, id_of, name_of

# Candidate spellings for the location parameter. Entrant repos disagree, and
# an unsupported parameter is accepted and ignored rather than rejected, so the
# only way to know which one works is to watch the results change.
LOCATION_PARAMS = [
    "signal.location.query",
    "filter.location.query",
    "signal.location",
    "filter.location",
]


def resolve(client, names, entity_type=None):
    """Resolve names to entity IDs, reporting what the graph does not know."""
    resolved, missing = {}, []
    for name in names:
        try:
            body = client.search(name, types=entity_type)
        except QlooError:
            missing.append(name)
            continue
        hits = entities_of(body)
        if not hits:
            missing.append(name)
            continue
        resolved[name] = {"id": id_of(hits[0]), "name": name_of(hits[0])}
    return resolved, missing


def test_a_endpoints(client, seed_entity_id, entity_type):
    """A: which endpoints answer at all on a hackathon key."""
    checks = [
        ("/search", {"query": "Radiohead"}),
        ("/v2/tags", {"filter.query": "jazz"}),
        ("/v2/audiences", {}),
        ("/v2/insights", {"filter.type": entity_type,
                          "signal.interests.entities": seed_entity_id, "take": 5}),
        ("/v2/analysis/compare", {"filter.type": entity_type,
                                  "a.signal.interests.entities": seed_entity_id,
                                  "b.signal.interests.entities": seed_entity_id}),
        ("/v2/trending", {"filter.type": entity_type, "take": 5}),
    ]
    out = {}
    for path, params in checks:
        try:
            status, body = client.get(path, params, allow_error=True)
            n = len(entities_of(body))
            out[path] = {"status": status, "results": n,
                         "verdict": "WORKS" if status == 200 and n >= 0 else "FAILS"}
        except QlooError as exc:
            out[path] = {"status": None, "verdict": "FAILS", "error": str(exc)[:200]}
    return out


def test_b_normalisation(client, entity_type, target_id, set_one, set_two):
    """B: is affinity comparable across calls?

    The same target entity is scored twice, inside two different candidate
    sets. If its affinity moves, Qloo normalises per query and every
    ratio-of-scores design (my original lift maths) is invalid.
    """
    def score_in(candidates):
        params = {
            "filter.type": entity_type,
            "filter.results.entities": ",".join(candidates),
            "signal.interests.entities": candidates[0],
            "take": len(candidates),
        }
        _, body = client.insights(params)
        for item in entities_of(body):
            if id_of(item) == target_id:
                return affinity_of(item)
        return None

    a = score_in([target_id] + set_one)
    b = score_in([target_id] + set_two)
    if a is None or b is None:
        return {"verdict": "UNKNOWN", "score_set_one": a, "score_set_two": b,
                "note": "target not present in one of the responses"}
    delta = abs(a - b)
    return {
        "verdict": "PER_QUERY_NORMALISED" if delta > 1e-6 else "GLOBALLY_COMPARABLE",
        "score_set_one": a,
        "score_set_two": b,
        "delta": delta,
        "implication": ("Ranks only. Cross-call ratios are meaningless."
                        if delta > 1e-6 else
                        "Cross-call ratios are defensible; lift maths survives."),
    }


def test_c_results_entities(client, entity_type, candidate_ids):
    """C: does filter.results.entities actually score MY list?"""
    params = {
        "filter.type": entity_type,
        "filter.results.entities": ",".join(candidate_ids),
        "signal.interests.entities": candidate_ids[0],
        "take": len(candidate_ids) + 10,
    }
    _, body = client.insights(params)
    returned = [id_of(i) for i in entities_of(body)]
    requested = set(candidate_ids)
    got = set(x for x in returned if x)
    extra = got - requested
    return {
        "verdict": "HONOURED" if got and got <= requested else
                   ("IGNORED" if extra else "PARTIAL"),
        "requested": len(requested),
        "returned": len(got),
        "missing": sorted(requested - got)[:10],
        "unrequested_returned": sorted(extra)[:10],
        "scored": sum(1 for i in entities_of(body) if affinity_of(i) is not None),
    }


def test_d_silent_ignore(client, entity_type, seed_entity_id):
    """D: confirm invalid parameters are swallowed, and that a valid one bites.

    Both halves matter. The negative control proves the API ignores nonsense;
    the positive control proves this harness can detect a parameter that works,
    so an 'ignored' verdict is not just our own blindness.
    """
    base_params = {"filter.type": entity_type,
                   "signal.interests.entities": seed_entity_id, "take": 20}
    _, base = client.insights(base_params)
    base_ids = [id_of(i) for i in entities_of(base)]

    nonsense = dict(base_params)
    nonsense["filter.totally_not_a_parameter"] = "xyzzy"
    _, bogus = client.insights(nonsense)
    bogus_ids = [id_of(i) for i in entities_of(bogus)]

    popular = dict(base_params)
    popular["filter.popularity.min"] = 0.95
    _, filtered = client.insights(popular, allow_error=True)
    filtered_ids = [id_of(i) for i in entities_of(filtered)]

    return {
        "nonsense_param_ignored": bogus_ids == base_ids,
        "positive_control_changed_results": filtered_ids != base_ids,
        "verdict": ("CONFIRMED_SILENT_IGNORE" if bogus_ids == base_ids
                    and filtered_ids != base_ids else "INCONCLUSIVE"),
        "note": ("Validate every parameter per filter.type before sending; a 200 "
                 "response is not evidence the parameter was applied."),
    }


def test_e_explainability(client, entity_type, seed_entity_id):
    """E: does feature.explainability return the drivers behind each result?"""
    params = {"filter.type": entity_type, "signal.interests.entities": seed_entity_id,
              "feature.explainability": "true", "take": 5}
    _, body = client.insights(params, allow_error=True)
    items = entities_of(body)
    found = False
    sample = None
    for item in items:
        blob = json.dumps(item)[:4000]
        if "explain" in blob.lower():
            found = True
            sample = blob[:300]
            break
    return {"verdict": "WORKS" if found else "ABSENT", "sample": sample,
            "results": len(items)}


def test_f0_location_param(client, entity_type, seed_entity_id, market_a, market_b,
                           pinned_ids=None):
    """F0: which location spelling bites, and does it bite WITH pinned entities?

    The confound this exists to catch: filter.results.entities pins the
    candidate set, and a location parameter may only be applied during
    retrieval. Pinning skips retrieval. If we only tested location on open
    queries we could find a working spelling, build test F on pinned queries,
    get tau near 1, and wrongly conclude there is no regional signal when in
    truth the two parameters never combined.

    So every spelling is tried twice: open, and pinned. Only a spelling that
    reorders PINNED results can carry test F.
    """
    results = {}
    for param in LOCATION_PARAMS:
        row = {}
        for mode in ("open", "pinned"):
            if mode == "pinned" and not pinned_ids:
                continue
            try:
                pa = {"filter.type": entity_type,
                      "signal.interests.entities": seed_entity_id,
                      "take": 25, param: market_a}
                if mode == "pinned":
                    pa["filter.results.entities"] = ",".join(pinned_ids)
                    pa["take"] = len(pinned_ids)
                pb = dict(pa)
                pb[param] = market_b
                _, ba = client.insights(pa, allow_error=True)
                _, bb = client.insights(pb, allow_error=True)
                ids_a = [id_of(i) for i in entities_of(ba)]
                ids_b = [id_of(i) for i in entities_of(bb)]
                aff_a = [affinity_of(i) for i in entities_of(ba)]
                aff_b = [affinity_of(i) for i in entities_of(bb)]
                row[mode] = {
                    "results_a": len(ids_a),
                    "results_b": len(ids_b),
                    "ordering_changed": bool(ids_a) and ids_a != ids_b,
                    "affinities_changed": bool(aff_a) and aff_a != aff_b,
                    "overlap": len(set(ids_a) & set(ids_b)),
                }
            except QlooError as exc:
                row[mode] = {"error": str(exc)[:200], "ordering_changed": False,
                             "affinities_changed": False}
        results[param] = row

    def bites(row, mode):
        r = row.get(mode, {})
        # On pinned queries the set is fixed by construction, so a changed
        # ORDER or changed AFFINITIES both count as the signal landing.
        return bool(r.get("ordering_changed") or r.get("affinities_changed"))

    working_open = [p for p, r in results.items() if bites(r, "open")]
    working_pinned = [p for p, r in results.items() if bites(r, "pinned")]

    if working_pinned:
        verdict = "LOCATION_WORKS_WITH_PINNED_ENTITIES"
    elif working_open:
        verdict = "LOCATION_ONLY_ON_OPEN_QUERIES"
    else:
        verdict = "NO_LOCATION_EFFECT"

    return {
        "per_param": results,
        "working_open": working_open,
        "working_pinned": working_pinned,
        "verdict": verdict,
        "implication": {
            "LOCATION_WORKS_WITH_PINNED_ENTITIES":
                "Test F can proceed on pinned catalogs as designed.",
            "LOCATION_ONLY_ON_OPEN_QUERIES":
                "Pinning bypasses the location signal. Test F must be rebuilt on "
                "OPEN per-market queries, ranking the catalog by its position in "
                "each market's returned list -- do NOT read a tau near 1 from "
                "pinned queries as evidence of no regional signal.",
            "NO_LOCATION_EFFECT":
                "No spelling reaches the API at all. The cross-market premise is "
                "dead before test F runs.",
        }[verdict],
    }


def test_determinism(client, entity_type, seed_entity_id):
    """Is the API deterministic? Decides what the bootstrap can mean.

    If two identical queries return identical payloads, there is no measurement
    noise to estimate, and resampling the catalog measures sensitivity to which
    titles were chosen -- not a confidence interval on the API. The report must
    say which of the two it is.
    """
    params = {"filter.type": entity_type,
              "signal.interests.entities": seed_entity_id, "take": 20}
    # Second read bypasses the local cache so this is a real repeat call.
    _, a_body = client.get("/v2/insights", dict(params))
    b_params = dict(params)
    b_params["_cachebust"] = "1"
    _, b_body = client.get("/v2/insights", b_params, allow_error=True)
    a_ids = [(id_of(i), affinity_of(i)) for i in entities_of(a_body)]
    b_ids = [(id_of(i), affinity_of(i)) for i in entities_of(b_body)]
    identical = a_ids == b_ids and bool(a_ids)
    return {
        "verdict": "DETERMINISTIC" if identical else "VARIES_BETWEEN_CALLS",
        "results_first": len(a_ids),
        "results_second": len(b_ids),
        "note": ("No API noise to estimate: the bootstrap measures sensitivity to "
                 "catalog composition, and seed variation is the only meaningful "
                 "robustness check."
                 if identical else
                 "Responses vary between identical calls; repeat-call variance "
                 "must be reported alongside the catalog bootstrap."),
        "caveat": ("_cachebust is an unknown parameter, which test D shows is "
                   "silently ignored -- that is exactly why it is safe to use "
                   "here to defeat the local cache."),
    }
