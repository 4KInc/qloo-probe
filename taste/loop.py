"""The agent loop.

Stage One of judging is pass/fail on whether this is an agentic tool. A batch
scorer that fans out a fixed set of queries and renders a table is not one,
however good the table is. The difference is that an agent decides what to do
next from what it has just seen.

So the loop here genuinely chooses: which markets are worth probing, when a
reading is too ambiguous to accept and needs another seed, when coverage is
too thin to answer at all, and when it has enough to stop. Every one of those
decisions is recorded with the reason, including the options it rejected,
because an agent that cannot show why it did something is indistinguishable
from a script that got lucky.

The backend is injected. That keeps the loop testable without the API, and it
is how this runs against recorded data before the key arrives.
"""
from __future__ import annotations

from taste.abstain import Verdict, check_input, check_market, check_pair

MAX_STEPS = 24
AMBIGUOUS_SPREAD = 0.15     # ranks this flat tell us nothing; try another seed
MAX_SEEDS_PER_MARKET = 3
MIN_HOME_AGREEMENT = 0.40   # below this the home reading is not a baseline


class Step:
    def __init__(self, n, action, reason, observation=None, rejected=None):
        self.n = n
        self.action = action
        self.reason = reason
        self.observation = observation
        self.rejected = rejected or []

    def as_dict(self):
        return {"step": self.n, "action": self.action, "reason": self.reason,
                "observation": self.observation, "rejected": self.rejected}


class Goal:
    def __init__(self, catalog, candidate_markets, home_market, want=3):
        self.catalog = list(catalog)
        self.candidate_markets = list(candidate_markets)
        self.home_market = home_market
        self.want = want        # how many markets to deliver a verdict on


class Agent:
    """Backend must provide:
         resolve(names)                      -> (resolved_ids, missing)
         score(market, ids, seed=None)       -> {id: affinity}
         seeds(market)                       -> [seed, ...]
    """

    def __init__(self, backend, trace=None):
        self.backend = backend
        self.trace = trace
        self.steps = []
        self.rankings = {}
        self.abstentions = {}
        self.call_for_market = {}   # market -> the call its ranking came from

    def _step(self, action, reason, observation=None, rejected=None):
        s = Step(len(self.steps) + 1, action, reason, observation, rejected)
        self.steps.append(s)
        return s

    @staticmethod
    def _spread(scores):
        if len(scores) < 2:
            return 0.0
        values = sorted(scores.values())
        return values[-1] - values[0]

    def _pick_market(self, goal, done):
        """Choose the next market to probe, and say what was passed over.

        Preference: markets furthest from home first, because a market that
        behaves like home teaches us least about whether the catalog travels.
        With nothing measured yet, fall back to declared order.
        """
        remaining = [m for m in goal.candidate_markets
                     if m not in done and m != goal.home_market]
        if not remaining:
            return None, []
        if goal.home_market in self.rankings:
            home = self.rankings[goal.home_market]
            scored = []
            for m in remaining:
                known = self.rankings.get(m)
                distance = 1.0 if known is None else 1.0 - (known.agreement_with(home) or 0)
                scored.append((distance, m))
            scored.sort(reverse=True)
            return scored[0][1], [m for _, m in scored[1:]]
        return remaining[0], remaining[1:]

    def run(self, goal):
        from taste.rank import Ranking

        resolved, missing = self.backend.resolve(goal.catalog)
        verdict, message = check_input(resolved, goal.catalog)
        self._step("resolve",
                   "bind every catalog name to a real entity before measuring "
                   "anything; an unresolvable name is reported, never guessed",
                   {"resolved": len(resolved), "missing": missing[:6]})
        if verdict != Verdict.ANSWER:
            if self.trace:
                self.trace.abstention(verdict, message)
            return self._result(goal, aborted=message)

        # Home market first: everything later is measured against it.
        home_scores = self.backend.score(goal.home_market, resolved)
        if home_scores:
            self.rankings[goal.home_market] = Ranking(goal.home_market, home_scores)
            home_call = getattr(self.backend, "last_call_id", None)
            if home_call:
                self.call_for_market[goal.home_market] = home_call
            home_agreement = (getattr(self.backend, "agreement", {})
                              or {}).get(goal.home_market)
            if home_agreement is not None and home_agreement < MIN_HOME_AGREEMENT:
                message = (
                    "%s cannot serve as the baseline: its own two anchor "
                    "readings agree at only %.2f, so every shift measured "
                    "against it would inherit that instability. This is a "
                    "property of the market, not of the catalog. A large "
                    "heterogeneous market is several audiences under one "
                    "name. Pick a market with a coherent taste profile, or "
                    "supply the home profile directly."
                    % (goal.home_market, home_agreement))
                self._step("abort_baseline",
                           "refusing to measure against an unstable baseline",
                           {"market": goal.home_market,
                            "anchor_agreement": home_agreement,
                            "required": MIN_HOME_AGREEMENT})
                if self.trace:
                    self.trace.abstention("abstain_unstable_baseline", message)
                return self._result(goal, aborted=message)
            self._step("score_home",
                       "establish the home ordering, so later markets are read "
                       "as movement rather than as raw popularity",
                       {"market": goal.home_market, "ranked": len(home_scores)})

        done = set()
        while len([m for m in self.rankings if m != goal.home_market]) < goal.want:
            if len(self.steps) >= MAX_STEPS:
                self._step("stop", "step budget reached before the goal was met")
                break
            market, passed_over = self._pick_market(goal, done)
            if market is None:
                self._step("stop", "no candidate markets left to probe")
                break
            done.add(market)

            scores = None
            used_seed = None
            tried = []
            for seed in ([None] + list(self.backend.seeds(market)))[:MAX_SEEDS_PER_MARKET]:
                candidate = self.backend.score(market, resolved, seed=seed)
                tried.append({"seed": seed, "returned": len(candidate),
                              "spread": round(self._spread(candidate), 3)})
                if not candidate:
                    continue
                if self._spread(candidate) < AMBIGUOUS_SPREAD:
                    # Flat ranks carry no information. Rather than reporting a
                    # meaningless order, try a different audience seed.
                    self._step("widen_seed",
                               "ranks for %s were flat (spread %.3f), which is "
                               "not a finding; re-probing with another audience "
                               "seed before accepting it"
                               % (market, self._spread(candidate)),
                               {"market": market, "attempt": tried[-1]})
                    scores, used_seed = candidate, seed
                    continue
                scores, used_seed = candidate, seed
                break

            if not scores:
                self.abstentions[market] = "no results returned"
                self._step("abstain", "%s returned nothing across %d seeds"
                           % (market, len(tried)), {"attempts": tried})
                if self.trace:
                    self.trace.abstention(Verdict.ABSTAIN_COVERAGE,
                                          "%s returned no results" % market)
                continue

            cov_verdict, cov_message = check_market(market, len(scores),
                                                    len(goal.catalog))
            if cov_verdict != Verdict.ANSWER:
                self.abstentions[market] = cov_message
                self._step("abstain",
                           "coverage too thin to rank honestly; reporting the "
                           "gap instead of a weak ordering",
                           {"market": market, "ranked": len(scores),
                            "catalog": len(goal.catalog)},
                           rejected=[{"market": m} for m in passed_over[:3]])
                if self.trace:
                    self.trace.abstention(cov_verdict, cov_message)
                continue

            self.rankings[market] = Ranking(market, scores)
            call_id = getattr(self.backend, "last_call_id", None)
            if call_id:
                self.call_for_market[market] = call_id
            withheld = (getattr(self.backend, "uncertain", {}) or {}).get(market) or []
            agreement = (getattr(self.backend, "agreement", {}) or {}).get(market)
            self._step("score_market",
                       "probed the market least like home first, since a market "
                       "that behaves like home teaches least about travel",
                       {"market": market, "ranked": len(scores),
                        "withheld_as_uncertain": len(withheld),
                        "anchor_agreement": agreement,
                        "seed": used_seed, "attempts": tried},
                       rejected=[{"market": m, "why": "lower expected divergence"}
                                 for m in passed_over[:3]])

        return self._result(goal)

    def _result(self, goal, aborted=None):
        home = self.rankings.get(goal.home_market)
        verdicts = {}
        for market, ranking in self.rankings.items():
            if market == goal.home_market or home is None:
                continue
            shared = len([e for e in ranking.percentiles if e in home.percentiles])
            pair_verdict, pair_message = check_pair(goal.home_market, market, shared)
            if pair_verdict != Verdict.ANSWER:
                self.abstentions[market] = pair_message
                continue
            shifts = ranking.shift_against(home)
            ordered = sorted(shifts.items(), key=lambda kv: -kv[1])
            # Every verdict cites the calls behind it. taste.evidence refuses
            # a claim with no supporting call, so an unsupported verdict
            # cannot reach the interface.
            supporting = [c for c in (self.call_for_market.get(market),
                                      self.call_for_market.get(goal.home_market))
                          if c]
            if self.trace and supporting:
                self.trace.claim(
                    "%s reorders the catalog against %s (tau %.2f over %d titles)"
                    % (market, goal.home_market,
                       ranking.agreement_with(home) or 0, shared),
                    supporting, kind="ranking")
            withheld = (getattr(self.backend, "uncertain", {}) or {}).get(market) or []
            verdicts[market] = {
                "supported_by": supporting,
                "anchor_agreement": (getattr(self.backend, "agreement", {})
                                     or {}).get(market),
                "withheld_as_uncertain": [
                    getattr(self.backend, "label", lambda x: x)(e) for e in withheld],
                "agreement_with_home": ranking.agreement_with(home),
                "travels": [{"entity": e, "shift": round(s, 3)}
                            for e, s in ordered[:5]],
                "does_not_travel": [{"entity": e, "shift": round(s, 3)}
                                    for e, s in ordered[-5:] if s < 0],
                "compared_on": shared,
            }
        return {
            "aborted": aborted,
            "markets_answered": list(verdicts),
            "abstained": self.abstentions,
            "verdicts": verdicts,
            "steps": [s.as_dict() for s in self.steps],
            "step_count": len(self.steps),
        }
