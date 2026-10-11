"""Rank statistics for the location-signal test.

Kendall's tau-b is implemented here rather than pulled from scipy so the probe
stays dependency-free. Tau-b is the tie-corrected variant, which matters
because Qloo can return equal affinities for several entities.
"""
from __future__ import annotations

import math
import random


def rank_percentiles(scores):
    """Map {key: score} to {key: percentile in [0,1]}, averaging tied ranks.

    Within-query percentiles are the unit the whole location test works in.
    Raw affinities are NOT comparable across calls if Qloo normalises per
    query -- that is precisely what probe_api Test B decides -- so every
    cross-market comparison here is built on ranks only.
    """
    items = sorted(scores.items(), key=lambda kv: kv[1])
    n = len(items)
    out = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and items[j + 1][1] == items[i][1]:
            j += 1
        avg_rank = (i + j) / 2.0
        for k in range(i, j + 1):
            out[items[k][0]] = avg_rank / (n - 1) if n > 1 else 0.5
        i = j + 1
    return out


def kendall_tau_b(a, b):
    """Tau-b over the keys the two mappings share. Returns None if < 3 shared."""
    keys = [k for k in a if k in b]
    if len(keys) < 3:
        return None
    conc = disc = tie_a = tie_b = 0
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            da = a[keys[i]] - a[keys[j]]
            db = b[keys[i]] - b[keys[j]]
            if da == 0 and db == 0:
                tie_a += 1
                tie_b += 1
            elif da == 0:
                tie_a += 1
            elif db == 0:
                tie_b += 1
            elif (da > 0) == (db > 0):
                conc += 1
            else:
                disc += 1
    n0 = len(keys) * (len(keys) - 1) / 2.0
    denom = math.sqrt((n0 - tie_a) * (n0 - tie_b))
    if denom == 0:
        return None
    return (conc - disc) / denom


def bootstrap_tau(a, b, iterations=400, seed=11):
    """Resample the shared entity set to get a CI on tau.

    A single tau below the kill threshold proves nothing if the catalog is
    small; the interval is what decides whether the reordering is real.
    """
    rng = random.Random(seed)
    keys = [k for k in a if k in b]
    if len(keys) < 4:
        return None
    taus = []
    for _ in range(iterations):
        sample = [rng.choice(keys) for _ in keys]
        sa = {}
        sb = {}
        for idx, k in enumerate(sample):
            sa["%s#%d" % (k, idx)] = a[k]
            sb["%s#%d" % (k, idx)] = b[k]
        t = kendall_tau_b(sa, sb)
        if t is not None:
            taus.append(t)
    if not taus:
        return None
    taus.sort()
    return {
        "median": taus[len(taus) // 2],
        "lo95": taus[int(0.025 * len(taus))],
        "hi95": taus[int(0.975 * len(taus))],
        "n": len(taus),
    }


def variance(values):
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return sum((v - mean) ** 2 for v in values) / (len(values) - 1)


def control_vs_catalog(per_market_ranks, control_ids):
    """Rank dispersion across markets, control set vs everything else.

    Ranks are zero-sum: something always finishes last, so movement alone is
    not evidence of a location signal. The control set is the anchor. If
    control items move as much as the rest, what we are seeing is noise.
    """
    all_ids = set()
    for ranks in per_market_ranks.values():
        all_ids.update(ranks.keys())
    control_var, other_var = [], []
    for eid in all_ids:
        series = [r[eid] for r in per_market_ranks.values() if eid in r]
        if len(series) < 2:
            continue
        (control_var if eid in control_ids else other_var).append(variance(series))
    return {
        "control_mean_variance": (sum(control_var) / len(control_var)) if control_var else None,
        "other_mean_variance": (sum(other_var) / len(other_var)) if other_var else None,
        "control_n": len(control_var),
        "other_n": len(other_var),
    }


def tau_null_se(n):
    """Standard error of Kendall's tau under the null, for n ranked items.

    With n=25 this is about 0.14, which means a single pair at 0.68 is not
    distinguishable from one at 0.75. This is why the decision rule requires
    two qualifying market pairs rather than one, and why the report prints the
    z-score next to every tau.
    """
    if n < 3:
        return None
    return math.sqrt(2.0 * (2 * n + 5) / (9.0 * n * (n - 1)))


def tau_z(tau, n):
    """How many null standard errors below 1.0 this tau sits."""
    se = tau_null_se(n)
    if se is None or tau is None:
        return None
    return (1.0 - tau) / se


def jackknife_tau_se(a, b):
    """Delete-one jackknife SE of the OBSERVED tau.

    tau_null_se above is the spread under independence (tau = 0). The sampling
    variance of tau shrinks as tau approaches 1, so using the null SE to judge
    a tau near the top overstates uncertainty and can make a real reordering
    look like noise. The jackknife estimates the spread of the tau we actually
    measured, and it is also the only honest uncertainty available when the API
    is deterministic -- there is no measurement noise to resample, only
    sensitivity to which titles were chosen.
    """
    keys = [k for k in a if k in b]
    n = len(keys)
    if n < 5:
        return None
    full = kendall_tau_b(a, b)
    if full is None:
        return None
    leave_one = []
    for drop in keys:
        sa = {k: a[k] for k in keys if k != drop}
        sb = {k: b[k] for k in keys if k != drop}
        t = kendall_tau_b(sa, sb)
        if t is not None:
            leave_one.append(t)
    if len(leave_one) < 3:
        return None
    mean = sum(leave_one) / len(leave_one)
    var = (n - 1.0) / n * sum((t - mean) ** 2 for t in leave_one)
    return math.sqrt(var)


def wilson(successes, total, z=1.96):
    """Wilson score interval for a proportion. Correct at small n and near 0,
    where the normal approximation is not."""
    if total == 0:
        return None
    p = successes / float(total)
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    halfwidth = (z / denom) * math.sqrt(p * (1 - p) / total +
                                        z * z / (4.0 * total * total))
    return {"p": p, "lo": max(0.0, centre - halfwidth),
            "hi": min(1.0, centre + halfwidth), "n": total}


def newcombe_diff(k1, n1, k2, n2, z=1.96):
    """Newcombe interval for the difference between two proportions, built from
    each arm's Wilson interval.

    A two-point gap and an eight-point gap can easily overlap at a few hundred
    verifications per arm, so the decision has to rest on the interval rather
    than the point estimate.
    """
    w1, w2 = wilson(k1, n1, z), wilson(k2, n2, z)
    if w1 is None or w2 is None:
        return None
    diff = w1["p"] - w2["p"]
    lo = diff - math.sqrt((w1["p"] - w1["lo"]) ** 2 + (w2["hi"] - w2["p"]) ** 2)
    hi = diff + math.sqrt((w1["hi"] - w1["p"]) ** 2 + (w2["p"] - w2["lo"]) ** 2)
    return {"diff": diff, "lo": lo, "hi": hi, "arm1": w1, "arm2": w2}
