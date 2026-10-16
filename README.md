# The Taste Atlas

**Audiences discovered from Qloo's taste graph, mapped by taste rather than
geography, and used to rank a film slate for any buyer you can describe.**

Live: https://travels-well-722527905604.us-central1.run.app
Built for the Qloo Agentic Hackathon. MIT licensed.

---

## The finding

Two audiences in the same city agree less than audiences six thousand
kilometres apart:

```
New York downtown  <->  Berlin techno       0.78
New York downtown  <->  New York hip-hop    0.26
```

So the agent stops assuming who an audience is and discovers it instead. The
groups that come out are smaller and stranger than marketing segments --
Racionais MC's with Snowfall and The Sopranos; Ben Klock with Fela Kuti,
Journey and Breath of the Wild.

## Three surfaces

| Page | What it does | Cost |
|---|---|---|
| `/` **The Atlas** | 18 audiences clustered from 73 anchors over 65 films, laid out by MDS so distance is taste distance. Each names itself from its members' Qloo tags. | precomputed, no API calls |
| `/pitch` **Pitch Desk** | Your slate, and a buyer described by what they have already licensed. Ranks your titles for them against your home audience. | ~32 calls |
| `/slate` **Travels Well** | The same engine on a fixed catalogue, including a preset the agent refuses. | ~10 calls |

## Evidence

- 11 of 11 regionally-skewed films rank highest with their home audience, p = 0.0005
- 10 of 11 survive replacing every anchor artist (p = 0.0059)
- 67% of within-cluster pairings survive bootstrap resampling at the shipped threshold
- Backtest ground truth collected from Wikipedia **before** any Qloo call, pre-registered and committed

Full record, including the negative results, in **[FINDINGS.md](FINDINGS.md)**.

## What we measured about the API

`filter.location.query` is **silently ignored for movies** (honoured for
places). `affinity` and `popularity` sit side by side and confusing them makes
every audience look identical. Affinity is **not** normalised per candidate
set. Cross-domain signal strength varies enormously: TV 0.06, games 0.08,
music 0.11, brands 0.39, books 0.70, podcasts 0.72, places none. `take` caps
at 50.

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
python3 run_agent.py --home "Mumbai · Bollywood playback"   # agent in the terminal
python3 atlas_build.py      # discover audiences: cluster + bootstrap
python3 atlas_view.py       # lay them out by MDS, write the map
python3 name_clusters.py    # let each audience name itself from its tags
python3 warm_cache.py       # record presets so the demo survives the quota
python3 test_taste.py && python3 test_loop.py   # 27 tests
```

## How it is built

```
taste/loop.py           the agent: chooses, retries, abstains, records why
taste/qloo_backend.py   consensus scoring over two anchor sets per audience
taste/pitch.py          your slate against a buyer's own catalogue
taste/rank.py           within-query ranks only; nothing divides across calls
taste/abstain.py        the refusal thresholds
taste/evidence.py       a claim with no supporting call cannot be rendered
atlas_build.py          discover audiences: signatures, average linkage, bootstrap
atlas_view.py           classical MDS layout, split-half consensus per cluster
name_clusters.py        names derived from members' shared tags, TF-IDF scored
engine.py               what the server calls for the fixed-catalogue view
app/server.py           public demo, stdlib HTTP, LIVE/CACHED labelled
run_all.py              the verification harness (see docs/HARNESS.md)
```

## Honest limits

Qloo knows brands, not products: films, artists, places, brands, books, shows,
podcasts and games, not arbitrary retail SKUs. Fifteen of the eighteen
clusters have too few members to split into halves that independently agree
and are labelled single-reading rather than implying a check that did not
happen. The external backtest agrees in Mumbai (tau 0.39) and Berlin (0.20)
and not elsewhere; reported either way, with the reasons.
