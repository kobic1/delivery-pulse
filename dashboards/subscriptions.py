#!/usr/bin/env python3
"""Who gets which email: one JSON document in the repository VARIABLE `EMAIL_SUBSCRIPTIONS`.

The repo is public, so no address is ever in a file. The variable is not a secret (it can be read and changed with `gh variable get/set`
and in Settings > Secrets and variables > Actions > Variables) and it is not in the git history. Shape:

    {
      "exclude": ["someone@example.com"],                      # removed from EVERY email, whatever list they are on
      "dashboards": {                                          # the release status emails, by name (the config's recipients_env without
        "phoenix": {"to": ["a@example.com", "b@example.com"],  #   the _DASHBOARD_RECIPIENTS suffix, lower case: pmn, cxco, ascenders,
                    "cc": []},                                 #   fellowship, cxsup, cv_tech, phoenix, cv_combined)
        "pmn": {"to": ["c@example.com"]}
      },
      "release_planning": {"PMN:Phoenix": ["d@example.com"]}   # the release planning emails, by their report key
    }

An entry here WINS over the same-named repository secret; where there is no entry the secret is used exactly as before, so each email can move
over on its own. "to"/"cc" may be a list or a semicolon/comma separated string, and `Name <address>` is accepted. A "cc" of [] means no Cc
(it hides the secret). Invalid JSON stops the send (fail closed: an old list in a secret must not be used by accident).

    python3 dashboards/subscriptions.py has-to NAME     exit 0 when the variable gives the email NAME at least one To address
"""
from __future__ import annotations

import json
import os
import re
import sys

ENV = "EMAIL_SUBSCRIPTIONS"
_ANGLE = re.compile(r"<([^<>]+)>")


def addresses(value) -> list[str]:
    """Bare addresses, in order, without duplicates (case-insensitive), from a list or a ;/, separated string; `Name <addr>` gives addr."""
    items = value if isinstance(value, (list, tuple)) else re.split(r"[;,]", str(value or ""))
    out, seen = [], set()
    for it in items:
        s = str(it).strip()
        m = _ANGLE.search(s)
        s = (m.group(1) if m else s).strip()
        if s and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return out


def rules() -> dict:
    raw = os.environ.get(ENV, "").strip()
    if not raw:
        return {}
    try:
        d = json.loads(raw)
    except ValueError as e:
        sys.exit(f"FATAL: the {ENV} variable is not valid JSON ({e}). Nothing was sent.")
    if not isinstance(d, dict):
        sys.exit(f"FATAL: the {ENV} variable must be a JSON object. Nothing was sent.")
    return d


def excluded() -> set[str]:
    return {a.lower() for a in addresses(rules().get("exclude"))}


def drop_excluded(addrs: list[str]) -> list[str]:
    ex = excluded()
    return [a for a in addrs if a.lower() not in ex]


def dashboard(name: str, kind: str = "to") -> list[str] | None:
    """The list the variable gives the dashboard email `name` ("to" or "cc"); None when it says nothing (then the secret applies)."""
    entry = (rules().get("dashboards") or {}).get(name)
    if not isinstance(entry, dict) or kind not in entry:
        return None
    return addresses(entry[kind])


def release_planning(key: str) -> list[str] | None:
    """The list for the release planning report `key` (for example "PMN" or "PMN:Phoenix"); None when the variable says nothing about it."""
    entry = (rules().get("release_planning") or {})
    return addresses(entry[key]) if key in entry else None


def key_of_env(env_name: str) -> str:
    """'PHOENIX_DASHBOARD_RECIPIENTS' / 'PHOENIX_DASHBOARD_CC' -> 'phoenix'."""
    return re.sub(r"_DASHBOARD_(RECIPIENTS|CC)$", "", env_name or "").lower()


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[1] == "has-to":
        return 0 if dashboard(argv[2], "to") else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
