#!/usr/bin/env python3
"""Leak check: this folder is committed to a public repository, so it must hold nothing from the real Jira data.

When a real payload exists on this machine (program_dashboard/build/program_data.json, git-ignored), a denylist is built from it IN MEMORY (epic and
capability titles over 25 characters, assignee names, team names, pod labels, issue keys, sprint labels, the account and site ids, the Jira host,
the cycle and release dates) and every file in this folder is searched for it. Findings are printed as category and file:line only, never the value.
Without a real payload there is nothing to compare with and the check says so.

    python3 leak_check.py          # exit code 1 when something real is found
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
CANDIDATES = [REPO / "program_dashboard" / "build" / "program_data.json", REPO / "program_dashboard" / "build" / "fallback_v52" / "program_data.json"]
KEY = re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d{3,7}\b")


def denylist(real: dict) -> dict[str, set[str]]:
    d = {k: set() for k in ("title", "person", "team", "pod", "key", "sprint", "id", "host", "date")}
    titles = [e.get("t") for e in real.get("epics", [])] + list((real.get("capabilities") or {}).values()) + [v.get("t") for k in ("hier", "capList", "ext") for v in (real.get(k) or {}).values()] \
        + [v.get("t") for v in ((real.get("cfbx") or {}).get("bugs") or {}).values()]
    d["title"] = {t for t in titles if isinstance(t, str) and len(t) > 25}
    d["person"] = {e["as"] for e in real.get("epics", []) if e.get("as")} | {v["as"] for k in ("ext",) for v in (real.get(k) or {}).values() if v.get("as")}
    teams = {t for e in real.get("epics", []) for t in e.get("tm", [])} | {b["tm"] for b in real.get("bugs", []) if b.get("tm")} | set((real.get("cap") or {}).get("teams", []))
    d["team"] = {t for t in teams if len(t) >= 4}
    d["pod"] = {p for e in real.get("epics", []) for p in e.get("pl", []) if len(p) >= 6}
    keys = {e["k"] for e in real.get("epics", [])} | {b["k"] for b in real.get("bugs", [])} | set(real.get("capabilities") or {}) | set(real.get("hier") or {}) | set(real.get("capList") or {}) | set(real.get("ext") or {})
    keys |= {k for dep in real.get("deps", []) for k in dep[:2]} | {r[0] for r in real.get("capEpics", [])}
    d["key"] = keys
    d["sprint"] = {s["n"] for s in real.get("sprints", [])} | {e["ts"] for e in real.get("epics", []) if e.get("ts")}
    d["id"] = {x for x in (real.get("cloudId"), real.get("cfbAccount")) if x}
    base = real.get("jiraBase") or ""
    d["host"] = {re.sub(r"^https?://", "", base)} if base else set()
    wins = {x for w in (real.get("windows") or {}).values() for x in w}
    cyc = real.get("cycles") or {}
    wins |= {c[k] for c in cyc.get("cycles", []) for k in ("start", "end") if c.get(k)}
    d["date"] = wins
    return d


def scan(files: list[Path], d: dict[str, set[str]]) -> list[tuple[str, str]]:
    found = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            for cat in ("title", "person", "pod", "sprint", "id", "host", "date"):
                if any(v in line for v in d[cat]):
                    found.append((cat, f"{f.name}:{n}"))
            for team in d["team"]:                                           # a team name counts only when it is the whole quoted string, so a fictitious "Team <X>" is not mistaken for a real team called <X>
                if f'"{team}"' in line or f"'{team}'" in line:
                    found.append(("team", f"{f.name}:{n}"))
                    break
            for k in KEY.findall(line):
                if k in d["key"]:
                    found.append(("key", f"{f.name}:{n}"))
    return found


def main() -> int:
    real_path = next((p for p in CANDIDATES if p.exists()), None)
    if not real_path:
        print("SKIP   leak check: no real program_data.json on this machine to compare with")
        return 0
    real = json.loads(real_path.read_text(encoding="utf-8"))
    d = denylist(real)
    files = [p for p in sorted(HERE.iterdir()) if p.is_file() and p.suffix in (".py", ".js", ".md", ".html", ".json", ".txt", "")]
    found = scan(files, d)
    sizes = ", ".join(f"{k} {len(v)}" for k, v in d.items())
    if found:
        print(f"FAIL   leak check: {len(found)} real identifiers found in {HERE.name}/ (denylist: {sizes})")
        for cat, where in sorted(set(found)):
            print(f"         - {cat} at {where}")
        return 1
    print(f"PASS   leak check: {len(files)} files searched, no real identifier from the real data (denylist: {sizes})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
