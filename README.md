# Qloo day-one probe

One run decides what to build for the Qloo Agentic Hackathon, and produces
numbers quotable in the submission either way.

## Why this exists

Three concepts were on the table and two of them rest on an unverified
premise. Rather than discover on day twelve that the premise is false, both
premises are tested first, against the live API, with thresholds fixed in
advance.

Every API claim this probe checks comes from entrant repositories rather than
from Qloo's documentation, which does not describe normalisation, locality
granularity or coverage. Treat all of it as unconfirmed until this harness
says otherwise.

## Run it, in this order

    python3 run_all.py --dry-run              # harness self-check, no key
    cp .env.example .env                      # QLOO_API_KEY + GEMINI_API_KEY
    git add out/prereg.json && git commit     # BEFORE any real run
    python3 run_all.py --stage cheap          # resolve, A, A2, B, C, D, E, F0
    python3 run_all.py --skip-gap             # adds F, only if F0 cleared
    python3 run_all.py --only gap             # G last: three arms, slowest

Stage one is cheap and decides everything downstream: if F0 finds no location
spelling that works, test F cannot mean anything and the cross-market premise
is already dead. Test G runs last because it is rate-limited by Nominatim at
one request per second, which makes a 3-arm, 30-prompt run the slowest part by
a wide margin.

The pre-registration is committed before the first real run on purpose. A hash
sitting in a local file cannot prove it came first.

Stdlib only. No install step, no virtualenv.

Get a hackathon key from the form linked in Qloo's developer guide
(docs.qloo.com). Keys are hackathon-scoped and do not work against production
or staging hosts.

## What each test decides

| Test | Question | Consequence |
|---|---|---|
| Resolve | How much of the catalog does the graph know? | Under 8 of 25 resolving stops the run |
| A | Which endpoints answer on a hackathon key | Scopes everything downstream |
| B | Is affinity comparable across calls? | If normalised per query, all ratio-of-scores maths is abandoned for within-query ranks |
| C | Does `filter.results.entities` score my own list? | This is the fix that makes rank comparison valid |
| D | Are invalid parameters silently ignored? | Includes a positive control, so "ignored" is not just our own blindness |
| E | Does `feature.explainability` return drivers? | Decides whether the evidence drawer is possible |
| A2 | Is the API deterministic? | Decides what the bootstrap can mean |
| F0 | Which location spelling bites, **and does it bite with pinned entities?** | Four spellings x two modes; no winner means the cross-market premise is dead |
| **F** | **Does the catalog reorder across markets?** | **Kill gate for Catalog Passport** |
| **G** | **Do ungrounded LLM recommendations fail?** | **Kill gate for Groundwork** |

## Decision rules, fixed in advance

**F passes** when at least two non-US market pairs show Kendall tau-b below
0.70, the bootstrap upper bound stays under 0.85, and the control set moves
less than the rest of the catalog.

Tau's standard error under the null is about 0.14 at n=25, so a single pair
at 0.68 is not distinguishable from one at 0.75. The report prints the z-score
beside every tau, and the rule requires two qualifying pairs for that reason.
Tau-b is used throughout because Qloo affinities tie at 2-3 decimals and tau-a
mishandles ties.

The control-set condition is the one that matters most. Ranks are zero-sum, so something
always drops; only a reordering that spares the titles expected to be stable
everywhere is evidence of a location signal rather than noise.

**G** is measured as a GAP, not as a rate. Three arms answer the same 30
prompts and all three are verified by the same instrument:

1. ungrounded LLM,
2. grounded LLM with search -- the configuration anyone shipping a
   recommendation agent would actually use,
3. Qloo's own place results.

The verdict uses `(best shipped LLM config) - (Qloo)`. Alive at 25 points or
more, dead at 10 or less.

The LLM's own failure rate is not the test. OpenStreetMap coverage is uneven
outside the US and EU and its name matching is fuzzy, so a real restaurant
absent from OSM counts as a hallucination. That bias hits every arm equally,
and only the gap cancels it. An ungrounded-only comparison would also have
been a straw man: if the grounded arm passes, Groundwork's premise fails no
matter how badly the ungrounded one does.

Then:

| F | G | Build |
|---|---|---|
| PASS | dead | Catalog Passport, with the agent loop and the backtest |
| FAIL | alive | Groundwork |
| PASS | alive | Catalog Passport plus a grounded-vs-ungrounded panel |
| FAIL | weak/dead | Preflight, single-query form |

## Pre-registration

`prereg.py` freezes the fixtures and the thresholds and hashes the content
(not the timestamp, so the digest is stable). Re-running with the same
fixtures leaves the original record untouched. Change a threshold afterwards
and the original is kept while the amendment is written to a separate file
with a warning. A threshold moved after seeing data is worthless, so the edit
is made visible rather than silent.

## Honesty constraints carried into the backtest

The planned backtest predicts relative country-level performance for the film
catalog from Qloo ranks alone and compares against public country box-office
splits. Two things must be said whenever that number is quoted:

- Qloo's graph is built partly from real consumption signal, so this is *less*
  circular than scoring Qloo with Qloo, not independent of it.
- Report N and the interval, never a bare correlation.

The Nominatim failure rate in test G is an upper bound: it misses legitimate
small venues. Spot-check a sample by hand before the number goes anywhere near
a submission.

## Output

    out/report.md      decision, gate table, raw results
    out/results.json   everything, machine readable
    out/calls.jsonl    every request and response status, for traceability
    out/prereg.json    the frozen rules and their hash (the one tracked file)
    out/cache/         response cache (gitignored -- do not commit Qloo data)

Caching is local and gitignored on purpose: one entrant reports organisers
disallow Qloo response data in a public repository, while another commits it.
Until that is settled in the Devpost discussions, keep it out of git.
