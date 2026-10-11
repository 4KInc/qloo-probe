"""Test G: do ungrounded LLM recommendations actually fail?

The Groundwork kill gate. The published counter-evidence (Taste Day Japan:
OpenStreetMap matched 13/15 LLM-only places against 9/14 Qloo places) says
this may well come back negative, which is the point of running it on day one
rather than on day fifteen.

    >= 25% combined existence+geo failure  -> Groundwork branch is alive
    <= 10%                                 -> Groundwork is dead, per its own rule
    in between                             -> weak; prefer Catalog Passport

Verification deliberately does NOT use Qloo. Existence and location come from
OpenStreetMap via Nominatim, so the measurement cannot flatter the sponsor.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CACHE = Path(__file__).parent / "out" / "osm_cache.json"
UA = "qloo-day1-probe/1.0 (hackathon evaluation; contact via repo)"


# ----- the model under test ----------------------------------------------
DEFAULT_MODEL = "gemini-2.5-flash"
TEMPERATURE = 0.0


def call_llm(prompt, grounded=False):
    """Whichever provider has a key. Two configurations are tested: ungrounded,
    and grounded with search. If the grounded configuration passes, Groundwork's
    premise fails regardless of how badly the ungrounded one does."""
    if os.environ.get("GEMINI_API_KEY"):
        return _gemini(prompt, grounded=grounded)
    if os.environ.get("ANTHROPIC_API_KEY"):
        if grounded:
            raise RuntimeError("grounded arm requires GEMINI_API_KEY")
        return _anthropic(prompt)
    raise RuntimeError(
        "Set GEMINI_API_KEY or ANTHROPIC_API_KEY for the gap test "
        "(or run with --skip-gap to probe Qloo only).")


def _post(url, payload, headers):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read().decode())


def _gemini(prompt, grounded=False):
    """Model id and temperature are pinned in fixtures and hashed into the
    pre-registration: a re-run against a newer default model is a different
    experiment, not a replication."""
    model = os.environ.get("GAP_MODEL", DEFAULT_MODEL)
    url = ("https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent"
           % model)
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": TEMPERATURE},
    }
    if grounded:
        # The honest comparison. Nobody ships a recommendation agent with
        # search turned off, so an ungrounded-only result would be a straw man.
        payload["tools"] = [{"google_search": {}}]
    body = _post(url, payload,
                 {"Content-Type": "application/json",
                  "x-goog-api-key": os.environ["GEMINI_API_KEY"]})
    cand = body["candidates"][0]
    return "".join(part.get("text", "")
                   for part in cand.get("content", {}).get("parts", []))


def _anthropic(prompt):
    model = os.environ.get("GAP_MODEL", "claude-sonnet-5")
    body = _post("https://api.anthropic.com/v1/messages",
                 {"model": model, "max_tokens": 1024,
                  "messages": [{"role": "user", "content": prompt}]},
                 {"Content-Type": "application/json",
                  "x-api-key": os.environ["ANTHROPIC_API_KEY"],
                  "anthropic-version": "2023-06-01"})
    return "".join(b.get("text", "") for b in body.get("content", []))


# ----- non-Qloo verification ---------------------------------------------
def _load_cache():
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text())
        except ValueError:
            return {}
    return {}


def osm_lookup(name, city, cache):
    """Does a place of this name exist, and is it in the stated city?"""
    key = ("%s|%s" % (name, city)).lower()
    if key in cache:
        return cache[key]
    params = urllib.parse.urlencode({
        "q": "%s, %s" % (name, city), "format": "json", "limit": 3,
        "addressdetails": 1})
    req = urllib.request.Request(
        "https://nominatim.openstreetmap.org/search?" + params,
        headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            hits = json.loads(resp.read().decode())
    except (urllib.error.URLError, ValueError):
        hits = []
    time.sleep(1.1)  # Nominatim asks for <= 1 req/s. Respect it.

    result = {"exists": bool(hits), "geo_ok": False, "matched": None}
    city_token = city.split(",")[0].strip().lower()
    for hit in hits:
        addr = hit.get("address", {})
        blob = " ".join(str(v).lower() for v in addr.values())
        if city_token in blob or city_token in hit.get("display_name", "").lower():
            result["geo_ok"] = True
            result["matched"] = hit.get("display_name")
            break
    if hits and not result["matched"]:
        result["matched"] = hits[0].get("display_name")
    cache[key] = result
    return result


PROMPT_TEMPLATE = (
    "Recommend exactly 5 real {domain} in {city} for someone who loves "
    "{taste}. Reply ONLY with a JSON array of objects with keys "
    '"name" and "city". No prose, no markdown fence.')


def parse_items(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        items = json.loads(text[start:end + 1])
    except ValueError:
        return []
    return [i for i in items if isinstance(i, dict) and i.get("name")]


def qloo_places(client, city, taste_terms, take=5):
    """The control arm: Qloo's own answer to the same request.

    Without this, the LLM's OSM failure rate is uninterpretable. OpenStreetMap
    coverage is uneven outside the US and EU and its name matching is fuzzy, so
    a real restaurant absent from OSM counts as a hallucination. Running the
    SAME flawed verifier over Qloo's results cancels that bias: what matters is
    the GAP between the two rates, not either rate alone.
    """
    from qloo_client import entities_of, name_of
    resolved = []
    for term in taste_terms:
        try:
            hits = entities_of(client.search(term))
        except Exception:
            continue
        if hits:
            from qloo_client import id_of
            eid = id_of(hits[0])
            if eid:
                resolved.append(eid)
    if not resolved:
        return [], "no taste terms resolved"
    params = {
        "filter.type": "urn:entity:place",
        "signal.interests.entities": ",".join(resolved[:5]),
        "filter.location.query": city,
        "take": take,
    }
    try:
        _, body = client.insights(params, allow_error=True)
    except Exception as exc:
        return [], str(exc)[:160]
    return [name_of(i) for i in entities_of(body) if name_of(i)], None


def _counts(rows):
    total = sum(len(r.get("items", [])) for r in rows)
    fails = sum(1 for r in rows for c in r.get("items", [])
                if not c["exists"] or not c["geo_ok"])
    return fails, total


def _measure(rows):
    total = sum(len(r.get("items", [])) for r in rows)
    missing = sum(1 for r in rows for c in r.get("items", []) if not c["exists"])
    wrong = sum(1 for r in rows for c in r.get("items", [])
                if c["exists"] and not c["geo_ok"])
    return {
        "places_checked": total,
        "nonexistent": missing,
        "wrong_city": wrong,
        "failure_rate": (missing + wrong) / float(total) if total else None,
    }


def _run_arm(prompts, cache, arm, client=None, grounded=False, verbose=True):
    rows = []
    for idx, spec in enumerate(prompts, 1):
        if arm == "qloo":
            names, err = qloo_places(client, spec["city"],
                                     [t.strip() for t in spec["taste"].split(" and ")])
            if err:
                rows.append({"prompt": spec, "error": err})
                continue
            items = [{"name": n} for n in names]
        else:
            prompt = PROMPT_TEMPLATE.format(**spec)
            try:
                raw = call_llm(prompt, grounded=grounded)
            except Exception as exc:
                rows.append({"prompt": spec, "error": str(exc)[:200]})
                continue
            items = parse_items(raw)

        checked = []
        for item in items:
            res = osm_lookup(item["name"], spec["city"], cache)
            checked.append({"name": item["name"], **res})
        rows.append({"prompt": spec, "returned": len(items), "items": checked})
        if verbose:
            bad = sum(1 for c in checked if not c["geo_ok"])
            print("  [%-9s %2d/%d] %-22s %d returned, %d failed"
                  % (arm, idx, len(prompts), spec["city"].split(",")[0],
                     len(items), bad))
    return rows


def run(prompts, client=None, verbose=True, arms=("ungrounded", "grounded", "qloo")):
    """Three arms through one verifier.

    The decision rests on the GAP between the grounded LLM and Qloo, measured
    with the same imperfect instrument -- not on any single rate.
    """
    cache = _load_cache()
    out = {"arms": {}}

    for arm in arms:
        if arm == "qloo" and client is None:
            continue
        try:
            rows = _run_arm(prompts, cache, arm, client=client,
                            grounded=(arm == "grounded"), verbose=verbose)
        except Exception as exc:
            out["arms"][arm] = {"error": str(exc)[:300]}
            continue
        out["arms"][arm] = dict(_measure(rows), rows=rows)

    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(cache))

    from stats import newcombe_diff, wilson

    def arm_counts(name):
        a = out["arms"].get(name) or {}
        rows = a.get("rows") or []
        return _counts(rows) if rows else (None, None)

    for name in out["arms"]:
        k, n = arm_counts(name)
        if k is not None and n:
            out["arms"][name]["wilson"] = wilson(k, n)

    def rate(name):
        a = out["arms"].get(name) or {}
        return a.get("failure_rate")

    ungrounded, grounded, qloo = rate("ungrounded"), rate("grounded"), rate("qloo")
    # The honest baseline is the strongest configuration anyone would ship.
    baseline_name = "grounded" if grounded is not None else "ungrounded"
    bk, bn = arm_counts(baseline_name)
    qk, qn = arm_counts("qloo")

    interval = None
    if None not in (bk, bn, qk, qn) and bn and qn:
        interval = newcombe_diff(bk, bn, qk, qn)

    if interval is None:
        verdict = "NO_CONTROL"
    elif interval["lo"] > 0 and interval["diff"] >= 0.10:
        verdict = "GROUNDWORK_ALIVE"
    elif interval["lo"] <= 0:
        verdict = "GROUNDWORK_DEAD"
    else:
        verdict = "GROUNDWORK_WEAK"

    gap = interval["diff"] if interval else None

    out.update({
        "verdict": verdict,
        "ungrounded_failure_rate": ungrounded,
        "grounded_failure_rate": grounded,
        "qloo_failure_rate": qloo,
        "gap_vs_best_llm_config": gap,
        "baseline_arm": baseline_name,
        "gap_interval_newcombe95": interval,
        "rule": ("gap = (best shipped LLM config) - (Qloo), same verifier. "
                 "ALIVE needs a 95% lower bound above 0 AND a point estimate of "
                 ">=10 points. DEAD if the lower bound includes 0. A few hundred "
                 "verifications per arm cannot separate a 2-point gap from an "
                 "8-point one, so the interval decides, not the point estimate. "
                 "The LLM's own rate is NOT the test: OSM's blind spots hit every "
                 "arm, and only the gap cancels them."),
        "caveats": [
            "Nominatim misses legitimate small venues, so every rate here is an "
            "upper bound on real failure. Hand-check a sample before quoting.",
            "If the grounded arm is far better than the ungrounded one, an "
            "ungrounded-only comparison would have been a straw man.",
            "Qloo's place results are not constrained to the same cuisine or "
            "price intent as the prompt, so this control measures existence and "
            "location only -- never recommendation quality.",
        ],
    })
    return out
