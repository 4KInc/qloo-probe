# Travels Well

**Which titles in a slate travel to another market, which do not, and which
the evidence cannot settle.**

A studio with twenty-five films that work at home, selling into Brazil, has to
guess which ones will land. The instinct is to pick whatever is famous there,
but fame and fit are different variables, and confusing them is the expensive
mistake. Travels Well answers the question from measured taste affinity
instead, and refuses to answer where the evidence will not support one.

Built for the Qloo Agentic Hackathon. MIT licensed.

---

## What it does

Give it a slate and a home market. For each target market it returns:

- **Travels** — titles that rise against the home ordering, with the size of the shift.
- **Does not travel** — titles that fall. This is the output no recommender gives, and usually the more costly mistake.
- **Evidence unstable** — titles withheld because two independent readings of the market disagree about them.

Every market is read **twice**, through unrelated sets of taste anchors, and
only what both readings agree on is reported.

## Why it needs Qloo

The question is which entities a particular audience actually prefers, and by
how much relative to another audience. That quantity lives in a taste graph
and nowhere else. A language model asked the same question answers fluently
from how much a title is *written about*, which is popularity wearing a
different hat — the exact error the product exists to catch.

## Endpoints used, and what each one does here

| Qloo surface | Where it appears |
|---|---|
| `/search` | Resolves every slate title and every market anchor to a real entity. An unresolvable name is reported, never guessed. |
| `/v2/insights` with `filter.results.entities` | Scores the pinned slate inside **one** query, so rank positions are comparable by construction. |
| `/v2/insights` with `signal.interests.entities` | Carries the market: each market is modelled as the taste anchors native to it. |
| `/v2/insights` affinity vs `popularity` | Ranking uses `query.affinity` only. There is deliberately no fallback to `popularity`. |
| `/v2/tags`, `/v2/analysis/compare` | Used by the verification harness to characterise the graph. |
| `feature.explainability` | Available per result for the evidence drawer. |

## What we measured about the API

Several widely-repeated claims about this API are wrong, and one of them would
have killed this project. The full record is in **[FINDINGS.md](FINDINGS.md)**;
the short version:

- **`filter.location.query` is silently ignored for movies.** Affinities come
  back identical to four decimals across five markets. An entry that pins a
  candidate set and varies location is reading a parameter the API never
  applied.
- **`signal.location.query` on a pinned set is a filter, not a signal** — it
  collapses eight titles to one.
- **Affinity is not normalised per candidate set.** The same entity scored
  inside two different pinned sets with the same signal returns an identical
  value. It varies with the *signal*, not the set.
- **A market modelled as taste anchors works.** Eleven of eleven
  regionally-skewed titles rank highest in their home market, p = 0.0005, and
  ten of eleven survive swapping every anchor for a different artist.

## Where it refuses

Refusing well is most of the product.

- A market whose two readings disagree about a title **withholds that title**.
- A market too thinly covered to rank **abstains**, naming the gap.
- A **home market whose own two readings disagree cannot be a baseline**. New
  York's agree at 0.13 — three audiences under one city's name — so the agent
  aborts and says why, rather than measuring everything against an unstable
  reference. Mumbai's agree at 0.97 and work fine. One preset demonstrates the
  refusal deliberately.
- A claim with no supporting API call **raises rather than rendering**.

## Run it

```bash
cp .env.example .env          # add QLOO_API_KEY
python3 app/server.py         # http://localhost:8080
```

Stdlib only: no dependencies, no build step. Also:

```bash
python3 run_agent.py --home "Mumbai, India"   # the agent, in the terminal
python3 warm_cache.py                         # record presets for offline demo
python3 test_taste.py && python3 test_loop.py # 27 tests
```

## How it is built

```
taste/loop.py           the agent: chooses, retries, abstains, records why
taste/qloo_backend.py   consensus scoring over two anchor sets per market
taste/rank.py           within-query ranks only; nothing divides across calls
taste/abstain.py        the refusal thresholds
taste/evidence.py       a claim with no supporting call cannot be rendered
engine.py               what the server calls
app/server.py           public demo, stdlib HTTP, LIVE/CACHED labelled
run_all.py              the verification harness (see docs/HARNESS.md)
```

## Honest limits

- Qloo knows brands, not products: this works for films, artists, places,
  brands, books, shows, podcasts and games — not arbitrary retail SKUs.
- Market anchors are hand-picked. They are shown to be swappable
  without changing the verdict, but deriving them from the graph would be better.
- The external backtest against Wikipedia pageview ranks agrees in Mumbai
  (tau 0.39) and Berlin (0.20) and not elsewhere. Reported either way;
  see FINDINGS.md for why the two measure different things.
