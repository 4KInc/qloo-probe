#!/usr/bin/env python3
"""Collect per-market outcome data for the pre-registered catalog.

Run BEFORE the Qloo key arrives, on purpose. Once outcomes are fixed and
committed, nobody can claim the comparison was tuned after seeing Qloo's
ranks -- including us.

Outcome signal: Wikipedia pageviews per language edition, over a fixed window.

Why this and not box office: territory-level grosses exist for maybe a third
of these titles and are reported inconsistently, which would silently reduce
the backtest to whichever films happen to have good records. Pageviews per
language edition are available uniformly for all of them, and they measure
ongoing cultural salience in a market, which is nearer to what a taste graph
claims to model than opening-weekend receipts are.

What is wrong with it, stated plainly:
  * A language edition is not a country. pt covers Brazil and Portugal, en
    covers the entire anglosphere, hi covers only part of India. This is a
    proxy for a market, not a measurement of one.
  * Per-article per-country data is not published by Wikimedia, for privacy
    reasons, so the proxy cannot be tightened.
  * Attention is not preference. A film can be read about and disliked.
  * Qloo's graph is built partly on public cultural signal, so agreement is
    LESS circular than scoring Qloo with Qloo, not independent of it.

All four go in the writeup wherever the number appears.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

UA = "qloo-hackathon-backtest/1.0 (cultural-equivalence research; contact via repo)"

# Market -> the language edition used as its proxy. Deliberately conservative:
# only editions where one market dominates the readership.
MARKET_WIKIS = {
    "New York, United States": "en",
    "Sao Paulo, Brazil": "pt",
    "Tokyo, Japan": "ja",
    "Berlin, Germany": "de",
    "Mumbai, India": "hi",
}

WINDOW = ("20251001", "20260930")  # one full year, fixed before collection


PACE_S = 1.1   # Wikimedia asks anonymous clients to serialise. An earlier
               # run at ~5 req/s was throttled, and the collector recorded the
               # throttling as "no article exists" for 16 of 25 titles.


def _get(url, tries=5):
    """Returns (data, error). The distinction matters: a failed request is not
    evidence that an article is missing, and conflating the two turns an
    instrument problem into a finding about coverage."""
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "application/json"})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
            time.sleep(PACE_S)
            return data, None
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                time.sleep(PACE_S)
                return None, None          # genuinely absent
            wait = float(exc.headers.get("Retry-After") or (2 ** attempt))
            if attempt == tries - 1:
                return None, "http_%s" % exc.code
            time.sleep(max(wait, PACE_S))
        except (urllib.error.URLError, ValueError) as exc:
            if attempt == tries - 1:
                return None, type(exc).__name__
            time.sleep(max(2 ** attempt, PACE_S))
    return None, "exhausted"


def find_article(title):
    """Returns (article_title, error)."""
    """Resolve a title to an English Wikipedia article, preferring the film."""
    for query in ("%s film" % title, title):
        url = ("https://en.wikipedia.org/w/api.php?action=query&list=search"
               "&srsearch=%s&srlimit=3&format=json"
               % urllib.parse.quote(query))
        data, err = _get(url)
        if err:
            return None, err
        if not data:
            continue
        hits = data.get("query", {}).get("search", [])
        if hits:
            return hits[0]["title"], None
    return None, "no_article"


def langlinks(article):
    """Map language code -> article title in that edition."""
    url = ("https://en.wikipedia.org/w/api.php?action=query&prop=langlinks"
           "&titles=%s&lllimit=500&format=json" % urllib.parse.quote(article))
    data, err = _get(url)
    out = {}
    if err or not data:
        return out
    for page in data.get("query", {}).get("pages", {}).values():
        for link in page.get("langlinks", []):
            out[link["lang"]] = link["*"]
    return out


def pageviews(lang, article):
    """Total pageviews for an article in one edition over the fixed window."""
    url = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
           "%s.wikipedia/all-access/user/%s/daily/%s/%s"
           % (lang, urllib.parse.quote(article.replace(" ", "_"), safe=""),
              WINDOW[0], WINDOW[1]))
    data, err = _get(url)
    if err or not data or "items" not in data:
        return None
    return sum(item.get("views", 0) for item in data["items"])


def main():
    catalog = json.loads((HERE / "fixtures" / "catalog.json").read_text())
    titles = catalog["control"] + catalog["regional"]
    out = {"window": WINDOW, "market_wikis": MARKET_WIKIS,
           "collected_before_any_qloo_call": True, "titles": {}}

    for i, title in enumerate(titles, 1):
        article, err = find_article(title)
        if not article:
            reason = err or "no_article"
            out["titles"][title] = {"article": None, "views": {},
                                    "failure": reason}
            print("  [%2d/%d] %-32s UNRESOLVED (%s)" % (i, len(titles), title,
                                                        reason))
            continue
        links = langlinks(article)
        views = {}
        for market, lang in MARKET_WIKIS.items():
            local = article if lang == "en" else links.get(lang)
            if not local:
                continue
            v = pageviews(lang, local)
            if v is not None:
                views[market] = {"lang": lang, "article": local, "views": v}
        out["titles"][title] = {"article": article, "views": views}
        print("  [%2d/%d] %-32s %-38s %d/%d markets"
              % (i, len(titles), title, article[:38], len(views),
                 len(MARKET_WIKIS)))

    # Per-market rank percentiles, the same unit test F produces for Qloo.
    from stats import rank_percentiles
    per_market = {}
    for market in MARKET_WIKIS:
        scores = {t: d["views"][market]["views"]
                  for t, d in out["titles"].items() if market in d.get("views", {})}
        if len(scores) >= 3:
            per_market[market] = rank_percentiles(scores)
    out["rank_percentiles"] = per_market
    out["coverage"] = {m: len(r) for m, r in per_market.items()}
    out["unresolved"] = {t: d["failure"] for t, d in out["titles"].items()
                         if d.get("failure")}
    out["request_failures"] = {t: r for t, r in out["unresolved"].items()
                               if r != "no_article"}

    (HERE / "out").mkdir(exist_ok=True)
    (HERE / "out" / "backtest_outcomes.json").write_text(json.dumps(out, indent=2))

    print("\ncoverage per market:")
    for market, n in out["coverage"].items():
        print("  %-26s %d/%d titles" % (market, n, len(titles)))
    if out["request_failures"]:
        print("\n  !! %d titles failed on REQUEST errors, not absence: %s"
              % (len(out["request_failures"]), out["request_failures"]))
        print("     Coverage above is a floor, not a measurement. Re-run.")
    print("\nsaved to out/backtest_outcomes.json")


if __name__ == "__main__":
    main()
