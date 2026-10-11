"""Shared core for whichever concept survives the day-one gates.

Catalog Passport, Groundwork and Preflight all need the same four things:
resolve names to real entities, score a candidate set inside ONE query,
abstain when coverage is too thin to answer, and keep a trace that ties every
claim back to the call that produced it. None of that changes with the
decision, so it is built before the decision.
"""
