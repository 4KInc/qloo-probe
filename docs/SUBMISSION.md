# Devpost submission text

Paste-ready. Deliberately leads with the theme route verbatim, because Stage
One is a pass/fail check on whether this is an agentic tool.

---

## Elevator pitch (195/200 chars)

An agent that decides which titles in your catalog travel to a new market,
which local names carry the same signal, and which don't translate at all.
Ranked on Qloo's taste graph, evidence shown.

---

## About the project

**Travels Well is an agentic tool that wires Qloo's taste graph into a
decision companies currently make by guessing.**

A distributor with a slate that works at home, selling into Brazil, has to
pick which titles will land there. The instinct is to choose whatever is
famous locally — but fame and fit are different variables, and confusing them
is the expensive mistake. Ask a language model and it answers fluently from
how much a title is *written about*, which is popularity wearing a different
hat: the exact error the tool exists to catch.

### What the agent does

Give it a slate and a home market. It plans which markets to probe, choosing
the one least like home first, because a market that behaves like home teaches
least about travel. It re-probes with a different audience seed when a reading
comes back too flat to mean anything. It abstains when coverage is too thin.
Then for each market it reports:

- **Travels** — titles rising against the home ordering, with the shift.
- **Does not travel** — titles falling. No recommender gives you this, and it
  is usually the costlier mistake.
- **Evidence unstable** — titles withheld because two independent readings of
  the market disagree.

Every step records *why*, including the markets it passed over. Every verdict
cites the API calls behind it; a claim with no supporting call raises rather
than rendering.

### What makes it Qloo-powered

| Qloo surface | What it does here |
|---|---|
| `/search` | Resolves every title and anchor to a real entity; unresolvable names are reported, never guessed |
| `/v2/insights` + `filter.results.entities` | Scores the pinned slate inside one query, so ranks are comparable by construction |
| `/v2/insights` + `signal.interests.entities` | Carries the market: each market is modelled as its native taste anchors |
| `query.affinity` (never `popularity`) | Ranking uses affinity only, with no fallback to global fame |
| `feature.explainability` | Powers the evidence drawer |
| `/v2/tags`, `/v2/analysis/compare` | Used by the verification harness |

**Without Qloo there is no product.** The resolver has nothing to resolve
against, the market model has no anchors, and ranking collapses to whatever
the model remembers being famous. We did not assert this; we measured it.

### What we found out about the API

We built a verification harness with thresholds pre-registered and committed
*before* any data was collected, because the project rested on assumptions
that could kill it. Several widely-repeated claims turned out to be wrong:

- **`filter.location.query` is silently ignored for movies.** Affinities are
  identical to four decimals across New York, São Paulo, Tokyo, Mumbai and
  Berlin. Any project that pins a candidate set and varies location is reading
  a parameter the API never applied, and may mistake the flat result for an
  absence of regional taste.
- **`signal.location.query` on a pinned set is a filter, not a signal** — it
  collapses eight titles to one.
- **Affinity is not normalised per candidate set.** The same entity scored in
  two different pinned sets with the same signal returns an identical value.
  It varies with the signal, not the set.
- **Modelling a market as taste anchors works.** Eleven of eleven
  regionally-skewed titles rank highest in their home market (p = 0.0005), and
  ten of eleven survive replacing every anchor with a different artist.

### Where it refuses, and why that is the point

New York cannot serve as a baseline. Its two independent readings agree at
0.13 — Springsteen, Beyoncé and Taylor Swift are three audiences under one
city's name — so every shift measured against it would inherit that
instability. The agent detects this and aborts with the reason. Mumbai's
readings agree at 0.97 and work fine. One preset demonstrates the refusal
deliberately, because a tool that always answers is not trustworthy.

### Honest limits

Qloo knows brands, not products: this works for films, artists, places,
brands, books, shows, podcasts and games, not arbitrary retail SKUs. Market
anchors are hand-picked, and while swapping them does not change the verdict,
deriving them from the graph would be better. An external backtest against
Wikipedia pageview ranks — collected before any Qloo call — agrees in Mumbai
(tau 0.39) and Berlin (0.20) and not elsewhere; we report it either way, with
the reasons the two measures diverge.

### Try it

Three presets, no login, works cold. Answers are labelled LIVE or CACHED;
cached ones are recorded runs of the same pipeline, never synthetic.
