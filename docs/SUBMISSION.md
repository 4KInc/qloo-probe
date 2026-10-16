# Devpost submission text

Paste-ready. Leads with the theme route verbatim, because Stage One is a
pass/fail check on whether this is an agentic tool.

---

## Elevator pitch (197/200 chars)

An agent that discovers who audiences actually are from Qloo's taste graph,
maps them by taste rather than geography, and ranks your film slate for any
buyer you can describe.

---

## About the project

**The Taste Atlas is an agentic tool that wires Qloo's taste graph into the
decision a film sales agent makes forty times at a market: which five titles
to put in front of this buyer.**

Everyone building on a taste graph starts by assuming they know who the
audience is — a city, a country, a genre. We tested that assumption and it
failed. So the agent discovers audiences instead, and the answer is stranger
than a map of the world.

### Three surfaces, one engine

**The Atlas** — 18 audiences found by clustering 73 anchors (musicians, TV
shows, video games) by their film-affinity signatures over 65 films, laid out
by multidimensional scaling so distance on the map *is* taste distance. Each
audience names itself from the Qloo tags its members share. Click one to see
what it watches; set a home audience and the map routes a slate between any
two, with no API calls at all because every signature ships with the page.

**Pitch Desk** — bring your own slate and describe a buyer the way the
industry already does: by what they have already licensed. The agent builds
the buyer's profile from those titles, ranks your slate against it, and
measures the result against the audience your slate already plays to.

**Travels Well** — the same engine on a fixed catalogue, including one preset
that the agent refuses outright.

### What the agent actually does

It plans which audience to probe next, choosing the one least like home
because a market that behaves like home teaches least about travel. It
re-probes with a different anchor set when a reading comes back too flat to
mean anything. It abstains when coverage is too thin, and aborts entirely when
the baseline itself is unstable. Every step records its reason and what it
passed over, and no claim renders without the API call that supports it.

### What makes it Qloo-powered

| Qloo surface | What it does here |
|---|---|
| `/search` | Resolves every film, anchor and buyer title; unresolvable names are reported, never guessed |
| `/v2/insights` + `filter.results.entities` | Scores a pinned slate inside one query, so rank positions are comparable by construction |
| `/v2/insights` + `signal.interests.entities` | Carries an audience: anchors for the atlas, a buyer's own catalogue for the pitch desk |
| `query.affinity`, never `popularity` | Ranking uses affinity only, with no fallback to global fame |
| Entity `tags` | Audiences name themselves — Bollywood, East Coast Hip Hop, Minimal Techno — from tags their members share, scored against the other clusters |
| `properties.image` | Every poster on every screen comes from Qloo's own CDN |
| `/v2/tags`, `/v2/analysis/compare` | Used by the verification harness |

**Without Qloo there is no product.** The resolver has nothing to resolve
against, audiences cannot be discovered because there are no signatures to
cluster, and ranking collapses to whatever the model remembers being famous —
which is the exact error the tool exists to catch.

### What we measured about the API, before building on it

Thresholds were pre-registered and committed *before* any data was collected.
Several widely-repeated claims turned out to be wrong, and one of our own bugs
would have killed the project for an artificial reason.

- **`filter.location.query` is silently ignored for movies.** Affinities come
  back identical to four decimals across New York, São Paulo, Tokyo, Mumbai and
  Berlin. Any entry that pins a candidate set and varies location is reading a
  parameter the API never applied, and may mistake the flat result for an
  absence of regional taste. It *is* honoured for places.
- **`affinity` and `popularity` sit side by side in every response.** An early
  version of our client read popularity, which is identical in every market —
  every audience would have looked the same.
- **Affinity is not normalised per candidate set.** The same entity scored
  inside two different pinned sets with the same signal returns an identical
  value. It varies with the signal, not the set.
- **Cross-domain signal strength is measurable and varies enormously.** TV
  shows (0.06), video games (0.08) and music (0.11) discriminate film taste
  sharply; brands (0.39), books (0.70), podcasts (0.72) and places (0.67–0.98)
  barely or not at all. Anchors are drawn only from the three that work.
- `take` is capped at 50; a larger value returns a 400 that reads downstream
  as "no data".

### The finding

Two audiences in the same city agree less than audiences six thousand
kilometres apart. New York downtown and Berlin techno rank the same films at
0.78; New York downtown and New York hip-hop at 0.26.

Clustering confirms it. The groups the graph produces are smaller and stranger
than marketing segments: Racionais MC's with Snowfall and The Sopranos; Ben
Klock with Fela Kuti, Journey and Breath of the Wild. No city, no genre, no
postcode.

Validation: 11 of 11 regionally-skewed films rank highest with their own home
audience (one-sided binomial p = 0.0005), and 10 of 11 survive replacing every
anchor artist with a different one. Cluster membership was bootstrapped over
resamples of the film set: 67% of within-cluster pairings survive at the
threshold we ship, and we report the thresholds where it does not hold.

### Where it refuses, and why that is the point

A market whose two independent readings disagree about a title withholds that
title. A market too thinly covered abstains. A home audience whose own two
readings agree at only 0.13 — Springsteen, Beyoncé and Taylor Swift are three
audiences wearing one city's name — cannot anchor a comparison, so the agent
aborts and says so. That case ships as a preset on purpose. A tool that always
answers is not trustworthy.

### Honest limits

Qloo knows brands, not products: this works for films, artists, places,
brands, books, shows, podcasts and games, not arbitrary retail SKUs. Fifteen
of the eighteen clusters have too few members to split into halves that
independently agree, and are labelled single-reading rather than implying a
check that did not happen. An external backtest against Wikipedia pageview
ranks, collected before any Qloo call, agrees in Mumbai (tau 0.39) and Berlin
(0.20) and not elsewhere; we report it either way, with the reasons the two
measures diverge.

### Try it

The map costs nothing to explore — it is precomputed. The pitch desk runs
live against the API and arrives prefilled, so it works on the first click.
