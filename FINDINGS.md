# Live API findings

Measured against the hackathon key on 13 October 2026. Every row here was
checked by differential test, not read from documentation. Several contradict
what circulating entrant reports claim, which is the reason the harness exists.

## What works

| Capability | Verdict | Note |
|---|---|---|
| `/search`, `/v2/tags`, `/v2/insights`, `/v2/analysis/compare` | **WORK** | |
| `/v2/audiences` | **WORKS** | needs one of `filter.parents.types`, `filter.results.audiences`, `filter.audience.types`; bare call is a 400 |
| `/v2/trending` | **WORKS** | requires `signal.interests.entities` **and** `filter.start_date`/`filter.end_date` |
| `filter.results.entities` | **HONOURED** | scores your own candidate list; the seed entity is excluded from its own results |
| `feature.explainability` | **WORKS** | appears as `query.explainability`, not at top level |
| `filter.release_year.min/max` | **HONOURED** | verified with a value that actually excludes the baseline |
| Determinism | **DETERMINISTIC** | identical queries return identical payloads |

## Affinity is not normalised per query

Circulating reports say affinity is normalised per query and scores from
different calls cannot be compared. **Measured: false, in the case that
matters.** The same entity scored inside two completely different candidate
sets, with the same signal, returned an identical affinity to the last decimal
(delta exactly 0.000000).

Affinity depends on the **signal**, not on the candidate set. Scores are
comparable across calls that share a signal, and not comparable across calls
with different signals. That is a different and much more workable rule than
the one in circulation.

## Affinity and popularity are different fields, and confusing them is fatal

Every result carries both:

```
popularity      = 0.9998     global property of the entity
query.affinity  = 0.9455     affinity for the signal in THIS query
```

An early version of this harness read top-level keys first, found
`popularity`, and returned that as the affinity. Popularity is identical in
every market by construction, so it would have made all markets look the same
and killed the project's premise for an entirely artificial reason. There is
now deliberately no fallback between the two: if affinity is missing, the
caller abstains.

## Location does not work the way the field assumes, at least for movies

| Combination | Result |
|---|---|
| `filter.location.query` + pinned entities | **Silently ignored.** Affinities identical to four decimals across New York, Sao Paulo, Tokyo, Mumbai and Berlin. |
| `signal.location.query` + pinned entities | Acts as a hard **filter**, not a signal: eight pinned titles collapse to one. |
| `signal.location.query` + open query | **Works.** Mumbai returns Andhadhun and The White Tiger where New York returns Knives Out and Uncut Gems. |

So a catalog cannot be scored per market by passing a location. This matters
beyond this project: an entry that pins a candidate set and varies
`filter.location.query` is reading a parameter the API never applied, and will
see a flat result it may mistake for an absence of regional taste.

## What does work: a market as a set of taste anchors

Model a market by entities native to it rather than by its coordinates. Score
the pinned catalog with `signal.interests.entities` set to local artists.

Mumbai anchored on A. R. Rahman, Lata Mangeshkar and Arijit Singh returns
Dangal, 3 Idiots and RRR at the top. Berlin anchored on Kraftwerk, Rammstein
and Nena returns Amelie, Pan's Labyrinth and Good Bye Lenin!. Sao Paulo
anchored on Anitta, Caetano Veloso and Racionais MC's returns Elite Squad
first.

**Eleven of eleven regionally-skewed titles rank higher in their home market
than in the average of the others. One-sided binomial p = 0.0005.**

## Where the backtest agrees, and where it does not

Against Wikipedia pageview ranks per language edition, collected before any
Qloo call:

| Market | tau vs outcome | jackknife SE |
|---|---|---|
| Mumbai | 0.39 | 0.23 |
| Berlin | 0.20 | 0.16 |
| New York | -0.03 | 0.17 |
| Sao Paulo | -0.01 | 0.16 |
| Tokyo | -0.15 | 0.14 |

Only Mumbai and Berlin lean positive, and neither clears two standard errors.
Stated plainly: **the anchor method reliably ranks a market's own films
highest, but it does not reproduce overall pageview orderings.**

The most likely reason is that the two measure different things. Pageviews in
the English edition track global anglophone attention, which is close to
popularity, and the anchor method is deliberately built to ignore popularity.
The home-market test is the sharper hypothesis and it passes decisively; the
rank-correlation test is the blunter one and it does not. Both are reported.

## Consensus scoring, and what it refuses

Swapping each market's three anchors for three unrelated ones leaves the
headline verdict intact (11 of 11 regional titles rank highest at home becomes
10 of 11, p=0.0059) but moves the fine ranking a great deal. Agreement between
the two readings:

| Market | anchor tau | titles agreed | withheld |
|---|---|---|---|
| Mumbai | 0.97 | 25 | 0 |
| Sao Paulo | 0.75 | 25 | 0 |
| Berlin | 0.52 | 19 | 6 |
| Tokyo | 0.42 | 19 | 6 |
| New York | 0.13 | 11 | 14 |

Stability tracks how coherent a market's anchors are. Mumbai's three are all
Bollywood playback singers and point at one audience. New York's span
Springsteen, Beyonce and Taylor Swift, which is three audiences wearing one
city's name.

So every market is now read twice and only titles the two readings place
within 0.25 rank percentile of each other are reported. The rest are withheld
and named. Averaging the two readings would have hidden the disagreement;
reporting only the agreement does not.

**A heterogeneous market cannot be a baseline.** With New York as home, every
pairwise overlap fell below the floor and the agent refused every market. That
is the correct answer rather than a bug: the thing everything was being
measured against was itself unreliable. The loop now checks the home market's
own anchor agreement first and aborts with that reason, instead of letting it
surface later as an unexplained overlap failure.

With Mumbai as home (anchor tau 0.97) the same run answers three markets and
abstains only on New York. Good Bye Lenin! is the top traveller into Berlin;
Elite Squad into Sao Paulo; 3 Idiots is the clearest non-traveller into Berlin.

This is the strongest honesty feature in the build: a verdict that says these
travel, these do not, and on these the evidence is unstable, is worth more
than a confident ranking of all 25.


## A market is an audience, not a city

The consensus check kept refusing New York, and the reason turned out to be
the market definition rather than the city. Anchors chosen as "whoever is
famous there" point at several audiences at once; anchors drawn from one scene
point at one.

| Definition | two readings agree |
|---|---|
| New York, whoever is famous (Springsteen, Beyonce, Taylor Swift) | 0.13 |
| New York, downtown (Lou Reed, Talking Heads, Patti Smith) | **0.91** |
| New York, hip-hop (Jay-Z, Nas, Notorious B.I.G.) | 0.67 |
| Tokyo, mixed era | 0.42 |
| Tokyo, city pop (Tatsuro Yamashita, Mariya Takeuchi, Anri) | **0.81** |
| Berlin, mixed era | 0.52 |
| Berlin, techno (Kalkbrenner, Ellen Allien, Modeselektor) | **0.73** |

Every market improves. And the scenes disagree with each other in a way that
is clearly not noise: the hip-hop audience's top films are Elite Squad, City
of God and La Haine, while the downtown audience's are Y Tu Mama Tambien,
Good Bye Lenin! and Amelie. Urban crime against European arthouse, same city.

So the product now models an audience rather than a city, which is also the
unit a distributor actually sells to. The incoherent New York definition is
kept as a preset, because a tool that detects a bad market description and
says so is worth more than one that always answers.

The home-market result survives the change: 11 of 11 regional titles still
rank highest with their own audience (p = 0.0005), 10 of 11 under the
alternate anchors (p = 0.0059).
