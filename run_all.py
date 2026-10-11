#!/usr/bin/env python3
"""Day-one verification harness for the Qloo Agentic Hackathon.

One run answers both branches of the build decision:

  * Is affinity comparable across calls?        (breaks or saves the lift maths)
  * Does filter.results.entities work?          (the within-query scoring fix)
  * Does the location signal reorder a catalog? (Catalog Passport kill gate)
  * Do ungrounded LLM recommendations fail?     (Groundwork kill gate)

Usage:
    python3 run_all.py --dry-run        # exercise the harness, no API needed
    python3 run_all.py                  # full run (needs QLOO_API_KEY)
    python3 run_all.py --skip-gap       # Qloo probes only
    python3 run_all.py --only gap       # gap test only
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import probe_api  # noqa: E402
import probe_gap  # noqa: E402
import probe_location  # noqa: E402
import prereg  # noqa: E402
from qloo_client import QlooClient, QlooError, load_dotenv  # noqa: E402

OUT = HERE / "out"


def _pct(x):
    return "n/a" if x is None else "%.1f%%" % (100 * x)


def banner(text):
    print("\n" + "=" * 68)
    print(text)
    print("=" * 68)


def run_qloo(client, catalog_spec, stage="full"):
    results = {}
    entity_type = catalog_spec["entity_type"]
    titles = catalog_spec["control"] + catalog_spec["regional"]

    banner("RESOLVE  -- what the graph knows")
    resolved, missing = probe_api.resolve(client, titles, entity_type)
    print("  resolved %d/%d; missing: %s"
          % (len(resolved), len(titles), ", ".join(missing) or "none"))
    results["resolution"] = {
        "resolved": len(resolved), "requested": len(titles), "missing": missing,
        "coverage_rate": len(resolved) / float(len(titles)),
    }
    if len(resolved) < 8:
        results["resolution"]["verdict"] = "COVERAGE_TOO_THIN"
        return results, resolved
    ids = [v["id"] for v in resolved.values() if v["id"]]
    seed = ids[0]

    banner("TEST A  -- which endpoints answer")
    results["A_endpoints"] = probe_api.test_a_endpoints(client, seed, entity_type)
    for path, row in results["A_endpoints"].items():
        print("  %-24s %s" % (path, row["verdict"]))

    banner("TEST A2 -- is the API deterministic")
    try:
        results["A2_determinism"] = probe_api.test_determinism(client, entity_type, seed)
        print("  verdict:", results["A2_determinism"]["verdict"])
        print("  ", results["A2_determinism"]["note"])
    except QlooError as exc:
        results["A2_determinism"] = {"verdict": "ERROR", "error": str(exc)[:300]}

    banner("TEST C  -- does filter.results.entities score MY list")
    try:
        results["C_results_entities"] = probe_api.test_c_results_entities(
            client, entity_type, ids[:10])
        print("  verdict:", results["C_results_entities"]["verdict"])
    except QlooError as exc:
        results["C_results_entities"] = {"verdict": "ERROR", "error": str(exc)[:300]}
        print("  ERROR:", str(exc)[:200])

    banner("TEST B  -- is affinity comparable across calls")
    try:
        results["B_normalisation"] = probe_api.test_b_normalisation(
            client, entity_type, ids[0], ids[1:5], ids[5:9])
        print("  verdict:", results["B_normalisation"]["verdict"])
        print("  ", results["B_normalisation"].get("implication", ""))
    except QlooError as exc:
        results["B_normalisation"] = {"verdict": "ERROR", "error": str(exc)[:300]}
        print("  ERROR:", str(exc)[:200])

    banner("TEST D  -- are invalid parameters silently ignored")
    try:
        results["D_silent_ignore"] = probe_api.test_d_silent_ignore(
            client, entity_type, seed)
        print("  verdict:", results["D_silent_ignore"]["verdict"])
    except QlooError as exc:
        results["D_silent_ignore"] = {"verdict": "ERROR", "error": str(exc)[:300]}

    banner("TEST E  -- explainability")
    try:
        results["E_explainability"] = probe_api.test_e_explainability(
            client, entity_type, seed)
        print("  verdict:", results["E_explainability"]["verdict"])
    except QlooError as exc:
        results["E_explainability"] = {"verdict": "ERROR", "error": str(exc)[:300]}

    banner("TEST F0 -- which location parameter actually bites")
    markets = catalog_spec["markets"]
    try:
        f0 = probe_api.test_f0_location_param(
            client, entity_type, seed, markets[1], markets[2],
            pinned_ids=ids[:12])
        results["F0_location_param"] = f0
        print("  verdict:", f0["verdict"])
        print("  open-query spellings:  ", f0["working_open"] or "NONE")
        print("  pinned-query spellings:", f0["working_pinned"] or "NONE")
        print("  ", f0["implication"])
    except QlooError as exc:
        f0 = {"working_open": [], "working_pinned": [], "verdict": "ERROR",
              "error": str(exc)[:300]}
        results["F0_location_param"] = f0

    if not (f0.get("working_pinned") or f0.get("working_open")):
        results["F_location_signal"] = {
            "verdict": "FAIL",
            "interpretation": ("No location parameter changed the ordering. "
                               "Catalog Passport's premise fails at the first gate."),
        }
        return results, resolved

    if stage == "cheap":
        print("\n  [--stage cheap] stopping before test F. "
              "F0 verdict above decides whether F is worth the quota.")
        return results, resolved

    banner("TEST F  -- does the catalog reorder across markets (KILL GATE)")
    # If pinning bypasses the location signal, ranking pinned results would
    # produce tau near 1 for reasons that have nothing to do with geography.
    # Fall back to open per-market queries instead of reporting a false FAIL.
    if f0.get("working_pinned"):
        location_param, mode = f0["working_pinned"][0], "pinned"
    else:
        location_param, mode = f0["working_open"][0], "open"
    print("  using %s in %s mode" % (location_param, mode))
    try:
        results["F_location_signal"] = probe_location.run(
            client, entity_type, ids, 
            [resolved[t]["id"] for t in catalog_spec["control"] if t in resolved],
            markets, location_param,
            audiences=catalog_spec.get("audience_seeds") or [None],
            seed_entity=None, mode=mode)
        f = results["F_location_signal"]
        print("  verdict:", f["verdict"])
        for pair, row in f["pairs"].items():
            tau = row["tau_b"]
            jack = row.get("jackknife_se")
            flag = "  INSUFFICIENT_OVERLAP" if row.get("insufficient_overlap") else ""
            print("    %-34s tau_b=%-6s se=%-6s n=%-3s%s"
                  % (pair, "n/a" if tau is None else round(tau, 3),
                     "n/a" if jack is None else round(jack, 3),
                     row.get("shared_entities"), flag))
        for market, cov in (f.get("absence_per_market") or {}).items():
            trunc = "  (possibly truncated)" if cov.get("possibly_truncated") else ""
            print("    absent in %-26s %.0f%% of catalog%s"
                  % (market, 100 * (cov.get("absence_rate") or 0), trunc))
        print("  ", f["interpretation"])
    except QlooError as exc:
        results["F_location_signal"] = {"verdict": "ERROR", "error": str(exc)[:300]}
        print("  ERROR:", str(exc)[:200])

    return results, resolved


def build_prompts(spec):
    return [{"city": city, "domain": spec["domain"], "taste": taste}
            for city in spec["cities"] for taste in spec["tastes"]]


def write_report(results, digest, calls, quota):
    lines = ["# Qloo day-one probe", "",
             "Pre-registration sha256: `%s`" % digest,
             "", "Qloo calls made: %s. Monthly quota remaining: %s." % (calls, quota),
             "", "## Decisions", ""]

    f = results.get("qloo", {}).get("F_location_signal", {})
    g = results.get("gap", {})
    b = results.get("qloo", {}).get("B_normalisation", {})
    c = results.get("qloo", {}).get("C_results_entities", {})

    loc_pass = f.get("verdict") == "PASS"
    gap_alive = g.get("verdict") == "GROUNDWORK_ALIVE"

    if loc_pass and not gap_alive:
        decision = "**Build Catalog Passport** with the agent loop and the backtest."
    elif gap_alive and not loc_pass:
        decision = "**Build Groundwork.** The location premise failed."
    elif loc_pass and gap_alive:
        decision = ("**Build Catalog Passport**, and fold a small LLM-only vs "
                    "grounded panel in from Groundwork.")
    else:
        decision = ("**Neither premise cleared its gate. Build Preflight in "
                    "single-query form** -- narrowest data requirement of the three.")
    lines += [decision, "",
              "| Gate | Verdict |", "|---|---|",
              "| Location signal reorders catalog | %s |" % f.get("verdict", "NOT RUN"),
              "| Ungrounded agents fail | %s |" % g.get("verdict", "NOT RUN"),
              "| &nbsp;&nbsp;ungrounded / grounded / Qloo | %s / %s / %s |"
              % (_pct(g.get("ungrounded_failure_rate")),
                 _pct(g.get("grounded_failure_rate")),
                 _pct(g.get("qloo_failure_rate"))),
              "| &nbsp;&nbsp;gap, 95%% CI | %s %s |"
              % (_pct(g.get("gap_vs_best_llm_config")),
                 "" if not g.get("gap_interval_newcombe95") else
                 "[%s, %s]" % (_pct(g["gap_interval_newcombe95"]["lo"]),
                               _pct(g["gap_interval_newcombe95"]["hi"]))),
              "| Affinity comparable across calls | %s |" % b.get("verdict", "NOT RUN"),
              "| filter.results.entities honoured | %s |" % c.get("verdict", "NOT RUN"),
              ""]

    if b.get("verdict") == "PER_QUERY_NORMALISED":
        lines += ["> Cross-call ratio maths is invalid. Everything downstream uses "
                  "within-query ranks.", ""]
    det = results.get("qloo", {}).get("A2_determinism", {})
    if det.get("verdict") == "DETERMINISTIC":
        lines += ["> API is deterministic: the bootstrap figures measure catalog "
                  "composition sensitivity, not measurement error.", ""]
    f0 = results.get("qloo", {}).get("F0_location_param", {})
    if f0.get("verdict") == "LOCATION_ONLY_ON_OPEN_QUERIES":
        lines += ["> Location did not combine with pinned entities. Test F ran in "
                  "open-query mode; a pinned-mode tau near 1 would have been an "
                  "artefact, not a finding.", ""]
    if g.get("verdict") == "GROUNDWORK_WEAK":
        lines += ["> Gap is positive but under 10 points: real yet too small to "
                  "carry a submission.", ""]
    bad_overlap = (f.get("insufficient_overlap_pairs") or [])
    if bad_overlap:
        lines += ["> %d market pair(s) shared fewer than %s titles and could not "
                  "qualify: %s. Thin overlap biases tau upward, because the "
                  "surviving titles are the globally popular ones least likely "
                  "to reorder."
                  % (len(bad_overlap), f.get("min_overlap_required"),
                     ", ".join(bad_overlap)), ""]

    lines += ["## Raw results", "", "```json",
              json.dumps(results, indent=2, default=str)[:60000], "```"]
    (OUT / "report.md").write_text("\n".join(lines))
    return decision


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="exercise the harness offline; no API key needed")
    ap.add_argument("--skip-gap", action="store_true")
    ap.add_argument("--only", choices=["qloo", "gap"])
    ap.add_argument("--stage", choices=["cheap", "full"], default="full",
                    help="cheap = resolve, A, A2, B, C, D, E, F0 only. "
                         "Run this first: if F0 fails, nothing else matters.")
    args = ap.parse_args()

    load_dotenv()
    OUT.mkdir(exist_ok=True)
    digest = prereg.write()
    print("pre-registration frozen: %s" % digest)

    catalog_spec = json.loads((HERE / "fixtures" / "catalog.json").read_text())
    prompt_spec = json.loads((HERE / "fixtures" / "prompts.json").read_text())
    results = {}

    if args.dry_run:
        banner("DRY RUN -- harness self-check, no live calls")
        import stats
        a = {"x": 0.1, "y": 0.4, "z": 0.9, "w": 0.2, "v": 0.7}
        b_same = dict(a)
        b_rev = {k: 1 - v for k, v in a.items()}
        print("  tau(identical) =", stats.kendall_tau_b(a, b_same))
        print("  tau(reversed)  =", stats.kendall_tau_b(a, b_rev))
        print("  ranks          =", {k: round(v, 2) for k, v in
                                     stats.rank_percentiles(a).items()})
        boot = stats.bootstrap_tau(a, b_rev)
        print("  bootstrap      =", {k: (round(v, 3) if isinstance(v, float) else v)
                                     for k, v in boot.items()})
        print("  prompts built  =", len(build_prompts(prompt_spec)))
        print("  catalog titles =", len(catalog_spec["control"] +
                                        catalog_spec["regional"]))
        print("\n  Harness is sound. Supply QLOO_API_KEY and re-run without "
              "--dry-run.")
        return

    client = None
    if args.only != "gap":
        try:
            client = QlooClient()
        except QlooError as exc:
            print("\n!! %s\n" % exc)
            return
        qloo_results, _ = run_qloo(client, catalog_spec, stage=args.stage)
        results["qloo"] = qloo_results

    if args.only != "qloo" and not args.skip_gap and args.stage != "cheap":
        banner("TEST G  -- do ungrounded recommendations fail (KILL GATE)")
        try:
            gap_client = client
            if gap_client is None:
                try:
                    gap_client = QlooClient(log_name="calls_gap.jsonl")
                except QlooError:
                    gap_client = None  # runs without the control arm
            results["gap"] = probe_gap.run(build_prompts(prompt_spec),
                                           client=gap_client)
            g = results["gap"]
            print("\n  ungrounded LLM : %s" % _pct(g.get("ungrounded_failure_rate")))
            print("  grounded LLM   : %s" % _pct(g.get("grounded_failure_rate")))
            print("  Qloo control   : %s" % _pct(g.get("qloo_failure_rate")))
            iv = g.get("gap_interval_newcombe95")
            print("  gap vs %-8s: %s%s"
                  % (g.get("baseline_arm", "?"), _pct(g.get("gap_vs_best_llm_config")),
                     "" if not iv else "  95%% CI [%s, %s]"
                     % (_pct(iv["lo"]), _pct(iv["hi"]))))
            print("  verdict        : %s" % g["verdict"])
        except Exception as exc:
            results["gap"] = {"verdict": "ERROR", "error": str(exc)[:300]}
            print("  ERROR:", str(exc)[:200])

    (OUT / "results.json").write_text(json.dumps(results, indent=2, default=str))
    decision = write_report(results, digest,
                            client.calls if client else 0,
                            client.quota_remaining if client else "n/a")
    banner("DECISION")
    print("  " + decision.replace("**", ""))
    print("\n  Full report: out/report.md")
    print("  Raw calls:   out/calls.jsonl")


if __name__ == "__main__":
    main()
