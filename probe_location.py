"""Test F: does the location signal reorder a catalog across markets?

This is the kill gate for Catalog Passport. The decision rule, fixed before
any data is seen:

    PASS  if at least two NON-US market pairs show Kendall tau-b < 0.70
          AND the control set moves less than the rest of the catalog
          AND the bootstrap upper bound stays below 0.85 for those pairs.

The control-set condition is the one that stops us fooling ourselves. Ranks
are zero-sum, so something always drops. Only a reordering that spares the
items we expect to be stable everywhere is evidence of a real signal.
"""
from __future__ import annotations

from qloo_client import affinity_of, entities_of, id_of
from stats import (bootstrap_tau, control_vs_catalog, jackknife_tau_se,
                   kendall_tau_b, rank_percentiles, tau_null_se, tau_z)

TAU_KILL = 0.70
BOOTSTRAP_CEILING = 0.85
MIN_OVERLAP = 12          # below this, tau-b carries no information
OPEN_TAKE = 500           # high enough that "absent" means not surfaced,
                          # rather than fell past the first page


def score_catalog_in_market(client, entity_type, catalog_ids, location_param,
                            market, audience=None, seed_entity=None):
    """One call per (market, audience seed). Ranks come from within that call,
    never across calls -- see probe_api Test B."""
    params = {
        "filter.type": entity_type,
        "filter.results.entities": ",".join(catalog_ids),
        "take": len(catalog_ids),
        location_param: market,
    }
    if audience:
        params["signal.demographics.audiences"] = audience
    if seed_entity:
        params["signal.interests.entities"] = seed_entity
    _, body = client.insights(params)
    scores = {}
    for item in entities_of(body):
        eid, aff = id_of(item), affinity_of(item)
        if eid and aff is not None:
            scores[eid] = aff
    return scores


def score_catalog_open(client, entity_type, catalog_ids, location_param, market,
                       audience=None, seed_entity=None, take=OPEN_TAKE):
    """Fallback when pinning bypasses the location signal (F0 verdict
    LOCATION_ONLY_ON_OPEN_QUERIES): run an OPEN per-market query and rank each
    catalog title by where it lands in that market's returned list. Titles the
    market does not return are absent rather than last -- treating them as last
    would manufacture the reordering we are trying to detect."""
    params = {"filter.type": entity_type, "take": take, location_param: market}
    if audience:
        params["signal.demographics.audiences"] = audience
    if seed_entity:
        params["signal.interests.entities"] = seed_entity
    _, body = client.insights(params)
    returned = entities_of(body)
    wanted = set(catalog_ids)
    scores = {}
    for position, item in enumerate(returned):
        eid = id_of(item)
        if eid in wanted:
            scores[eid] = -float(position)  # earlier position = higher score
    # If the response is exactly `take` long we are probably truncated, and an
    # "absent" title may simply have fallen off the end. That makes the absence
    # rate uninterpretable, so it is flagged rather than silently used.
    scores["__meta__"] = {"returned": len(returned), "truncated": len(returned) >= take}
    return scores


def run(client, entity_type, catalog_ids, control_ids, markets, location_param,
        audiences=None, seed_entity=None, mode="pinned"):
    audiences = audiences or [None]
    per_market_ranks = {}
    coverage = {}
    truncation = {}

    for market in markets:
        seed_ranks = []
        for audience in audiences:
            if mode == "open":
                scores = score_catalog_open(
                    client, entity_type, catalog_ids, location_param, market,
                    audience=audience, seed_entity=seed_entity)
            else:
                scores = score_catalog_in_market(
                    client, entity_type, catalog_ids, location_param, market,
                    audience=audience, seed_entity=seed_entity)
            coverage.setdefault(market, []).append(len(scores))
            meta = scores.pop("__meta__", None)
            if meta:
                truncation.setdefault(market, []).append(meta)
            if scores:
                seed_ranks.append(rank_percentiles(scores))
        if not seed_ranks:
            continue
        # Average the rank percentile across audience seeds. A verdict that
        # only survives one seed is not a verdict.
        merged = {}
        for eid in set().union(*[set(r) for r in seed_ranks]):
            vals = [r[eid] for r in seed_ranks if eid in r]
            merged[eid] = sum(vals) / len(vals)
        per_market_ranks[market] = merged

    pairs = {}
    names = list(per_market_ranks)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            tau = kendall_tau_b(per_market_ranks[a], per_market_ranks[b])
            boot = bootstrap_tau(per_market_ranks[a], per_market_ranks[b])
            n_shared = len(set(per_market_ranks[a]) & set(per_market_ranks[b]))
            jack = jackknife_tau_se(per_market_ranks[a], per_market_ranks[b])
            # Distance from the DECISION THRESHOLD, in SEs of the observed tau.
            # Testing against 1.0 with a null SE would be two different
            # distributions mixed together.
            margin = ((TAU_KILL - tau) / jack
                      if (jack and jack > 0 and tau is not None) else None)
            pairs["%s vs %s" % (a, b)] = {
                "tau_b": tau,
                "jackknife_se": jack,
                "ses_below_threshold": margin,
                "insufficient_overlap": n_shared < MIN_OVERLAP,
                "null_se_sanity_only": tau_null_se(n_shared),
                "z_vs_random_sanity_only": tau_z(tau, n_shared),
                # NOT a confidence interval on the API. If test A2 says the API
                # is deterministic, this measures only how much the verdict
                # depends on WHICH titles were chosen.
                "catalog_composition_sensitivity": boot,
                "shared_entities": n_shared,
            }

    anchor = control_vs_catalog(per_market_ranks, set(control_ids))

    # Absence is a finding, not only noise: a market that surfaces few catalog
    # titles is evidence for Catalog Passport's coverage-sparsity path.
    absence = {}
    for market, ranks in per_market_ranks.items():
        seen = len(ranks)
        absence[market] = {
            "catalog_titles_surfaced": seen,
            "catalog_size": len(catalog_ids),
            "absence_rate": 1 - seen / float(len(catalog_ids)) if catalog_ids else None,
            "possibly_truncated": any(t.get("truncated")
                                      for t in truncation.get(market, [])),
        }

    non_us = [k for k in pairs
              if "United States" not in k and "US:" not in k]
    reordering_pairs = [
        k for k in non_us
        if pairs[k]["tau_b"] is not None and pairs[k]["tau_b"] < TAU_KILL
        and not pairs[k]["insufficient_overlap"]
        and (pairs[k]["catalog_composition_sensitivity"] is None
             or pairs[k]["catalog_composition_sensitivity"]["hi95"] < BOOTSTRAP_CEILING)
    ]
    control_tighter = (
        anchor["control_mean_variance"] is not None
        and anchor["other_mean_variance"] is not None
        and anchor["control_mean_variance"] < anchor["other_mean_variance"]
    )

    passed = len(reordering_pairs) >= 2 and control_tighter
    return {
        "verdict": "PASS" if passed else "FAIL",
        "mode": mode,
        "rule": (">=2 non-US pairs with tau_b < %.2f and bootstrap hi95 < %.2f, "
                 "and control set rank variance below catalog variance"
                 % (TAU_KILL, BOOTSTRAP_CEILING)),
        "pairs": pairs,
        "qualifying_pairs": reordering_pairs,
        "control_anchor": anchor,
        "absence_per_market": absence,
        "insufficient_overlap_pairs": [k for k, v in pairs.items()
                                       if v["insufficient_overlap"]],
        "min_overlap_required": MIN_OVERLAP,
        "control_tighter_than_catalog": control_tighter,
        "coverage_per_market": {k: v for k, v in coverage.items()},
        "markets_scored": len(per_market_ranks),
        "interpretation": (
            "Location signal reorders the catalog. Catalog Passport is viable."
            if passed else
            "No reliable cross-market reordering. Catalog Passport's premise fails; "
            "fall through to the Groundwork branch or Preflight."),
    }
