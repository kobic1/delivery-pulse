#!/usr/bin/env python3
"""Scan the tracked Delivery Pulse files for real Jira data before a commit.

The repository is public. This reads the local, git-ignored build/program_data.json (when it exists) to learn which real issue keys, epic titles,
people and team names the dashboard holds, plus generic patterns (Atlassian account ids, cloud ids, the tenant host), and fails when any of them
appears in a tracked file under program_dashboard/ or tests/dashboard_browser/.

It prints only file:line and the kind of match, never the matched text, so its output is safe to paste.

    python3 program_dashboard/leak_scan.py            # exit 1 when something is found
    python3 program_dashboard/leak_scan.py --staged   # scan only the staged files (for a pre-commit hook)
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "program_dashboard" / "build" / "program_data.json"
SCOPES = ("program_dashboard/", "tests/dashboard_browser/", "tests/test_program_dashboard.py", "tests/test_definitions_contract.py", "tests/test_dashboard_copy.py", ".github/workflows/dashboard-checks.yml")
OUTSIDE = ("config/", "release_closure/", "dashboards/", "release_planning/")      # other parts of the repo: reported, never failing (they predate the dashboard and belong to other pipelines)
SKIP = ("program_dashboard/build/", "leak_scan.py")          # this file spells the patterns it looks for; build/ is git-ignored
TEXT_SUFFIXES = {".py", ".md", ".html", ".js", ".json", ".yml", ".yaml", ".txt", ".css", ".toml", ".cfg", ".sh"}

PATTERNS = {
    "Atlassian account id": re.compile(r"\b(?:[0-9]{5,6}:[0-9a-f-]{20,}|[0-9a-f]{24})\b"),
    "cloud id (UUID)": re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"),
    "tenant host": re.compile(r"[a-z0-9-]+\.atlassian\.net", re.I),
}
GENERIC = {"Israel", "Other", "Others", "Unassigned", "(No Team)"}
KEY_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d{3,7}\b")      # any project: the data also holds issues of projects the dashboard does not list


def tracked(staged: bool) -> list[str]:
    cmd = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"] if staged else ["git", "ls-files"]
    out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=True).stdout.split("\n")
    files = [f for f in out if f and f.startswith(SCOPES) and not any(f.startswith(s) or f.endswith(s) for s in SKIP) and Path(f).suffix in TEXT_SUFFIXES]
    if not staged:      # new, not yet tracked files in scope are part of what is about to be committed
        extra = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split("\n")
        files += [f for f in extra if f and f.startswith(SCOPES) and not any(f.startswith(s) or f.endswith(s) for s in SKIP) and Path(f).suffix in TEXT_SUFFIXES]
    return sorted(set(files))


def denylist() -> dict[str, set[str]]:
    """Words that must not appear: taken from the local data, so it stays current without ever being written down in the repo."""
    deny: dict[str, set[str]] = {"real issue key": set(), "real epic title": set(), "person name": set(), "team name": set(), "site identifier": set()}
    if not DATA.exists():
        return deny
    d = json.loads(DATA.read_text(encoding="utf-8"))
    deny["real issue key"] = {e["k"] for e in d.get("epics", [])} | {b["k"] for b in d.get("bugs", [])} | set(d.get("capabilities", {}) or {}) | set(d.get("hier", {}) or {})
    deny["real epic title"] = {e["t"].strip() for e in d.get("epics", []) if len(e.get("t", "").strip()) > 25}
    deny["person name"] = {e["as"].strip() for e in d.get("epics", []) if e.get("as")} - {""}
    teams = {t for e in d.get("epics", []) for t in e.get("tm", [])} | {b.get("tm") for b in d.get("bugs", []) if b.get("tm")}
    deny["team name"] = {t.strip() for t in teams if t and len(t.strip()) >= 5} - GENERIC      # a team that shares its name with a place or an ordinary word would flag the code around it
    deny["site identifier"] = {x for x in (d.get("cloudId"), d.get("cfbAccount")) if x}
    return deny


def main() -> int:
    staged = "--staged" in sys.argv
    files, deny, hits = tracked(staged), denylist(), []
    if not DATA.exists():
        print("note: build/program_data.json is not here, so only the generic patterns are checked", flush=True)
    keyset = deny.pop("real issue key", set())
    for f in files:
        try:
            text = (ROOT / f).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        lines = text.split("\n")
        for n, line in enumerate(lines, 1):
            for kind, rx in PATTERNS.items():
                m = rx.search(line)
                if m and not set(m.group(0)) <= set("0-"):      # the all-zero UUID is the synthetic test fixture's cloud id
                    hits.append((f, n, kind))
            if keyset and any(k in keyset for k in KEY_RE.findall(line)):
                hits.append((f, n, "real issue key"))
        for kind, words in deny.items():                                  # substring test over the whole file first (fast), then find the lines
            for w in words:
                if w not in text:
                    continue
                rx = re.compile(rf"(?<![\w-]){re.escape(w)}(?![\w-])") if kind in ("team name", "person name") else None
                for n, line in enumerate(lines, 1):
                    if (rx.search(line) if rx else w in line):
                        hits.append((f, n, kind))
    for f, n, kind in sorted(set(hits)):
        print(f"{f}:{n}: {kind}")
    print(f"scanned {len(files)} files; {len(set(hits))} finding(s)")
    if not staged:
        report_outside(deny)
    return 1 if hits else 0


def report_outside(deny: dict[str, set[str]]) -> None:
    """Counts only, per file and kind, for the rest of the repository: an owner's overview of what else a public repository shows. Never changes the exit code."""
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split("\n")
    counts: dict[tuple[str, str], int] = {}
    for f in out:
        if not f.startswith(OUTSIDE) or Path(f).suffix not in TEXT_SUFFIXES:
            continue
        try:
            text = (ROOT / f).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for kind, rx in PATTERNS.items():
            n = len(rx.findall(text))
            if n:
                counts[(f, kind)] = n
        for w in deny.get("team name", ()):
            n = len(re.findall(rf"(?<![\w-]){re.escape(w)}(?![\w-])", text))
            if n:
                counts[(f, "team name")] = counts.get((f, "team name"), 0) + n
    print(f"outside the dashboard (report only, not a failure): {len(counts)} file/kind pair(s)")
    for (f, kind), n in sorted(counts.items()):
        print(f"  {f}: {kind} x{n}")


if __name__ == "__main__":
    sys.exit(main())
