"""Per-entity-type parameter validation.

The hackathon API accepts parameters that do not apply to the requested
filter.type and ignores them silently, returning 200 with results that simply
do not reflect what was asked. A feature can therefore appear to work while
contributing nothing.

This table is the guard. Entries start as UNVERIFIED and are promoted only by
a differential test that proves removing the parameter changes the response.
The probe's Test D does exactly that; results are loaded from disk so the
product trusts measurement rather than documentation.
"""
from __future__ import annotations

import json
from pathlib import Path

UNVERIFIED, HONOURED, IGNORED = "unverified", "honoured", "ignored"

# Parameters believed universal. Still unverified until the probe says so.
COMMON = ["filter.type", "take", "page", "feature.explainability",
          "signal.interests.entities", "signal.interests.tags",
          "signal.demographics.audiences", "filter.tags",
          "filter.results.entities"]

BY_TYPE = {
    "urn:entity:movie": COMMON + ["filter.release_year.min",
                                  "filter.release_year.max"],
    "urn:entity:artist": COMMON,
    "urn:entity:place": COMMON + ["filter.location.query", "filter.location",
                                  "filter.radius"],
    "urn:entity:brand": COMMON,
    "urn:entity:book": COMMON,
    "urn:entity:tv_show": COMMON,
    "urn:entity:podcast": COMMON,
    "urn:entity:person": COMMON,
    "urn:entity:destination": COMMON,
    "urn:entity:video_game": COMMON,
}


class ParamGuard:
    def __init__(self, verified_path=None):
        self.status = {}
        if verified_path and Path(verified_path).exists():
            self.status = json.loads(Path(verified_path).read_text())

    def check(self, entity_type, params):
        """Return (kept, dropped, warnings). Never silently sends a parameter
        that is not on the type's list."""
        allowed = set(BY_TYPE.get(entity_type, COMMON))
        kept, dropped, warnings = {}, {}, []
        for key, value in params.items():
            base = key.split("[")[0]
            if base in allowed or base.startswith("signal.") or base.startswith("a.") \
                    or base.startswith("b."):
                kept[key] = value
                state = self.status.get(entity_type, {}).get(base, UNVERIFIED)
                if state == IGNORED:
                    warnings.append(
                        "%s is measured as IGNORED for %s: the response will "
                        "not reflect it" % (base, entity_type))
                elif state == UNVERIFIED:
                    warnings.append("%s unverified for %s" % (base, entity_type))
            else:
                dropped[key] = value
                warnings.append("%s is not valid for %s and was NOT sent"
                                % (base, entity_type))
        return kept, dropped, warnings

    def record(self, entity_type, param, honoured):
        self.status.setdefault(entity_type, {})[param] = (
            HONOURED if honoured else IGNORED)

    def save(self, path):
        Path(path).write_text(json.dumps(self.status, indent=2))
