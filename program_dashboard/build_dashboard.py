#!/usr/bin/env python3
"""Cross-project, cross-team program dashboard: one self-contained, filterable HTML page.

    python3 program_dashboard/build_dashboard.py            # fetch from Jira + render
    python3 program_dashboard/build_dashboard.py --reuse    # re-render from build/program_data.json

Built on the Program Intelligence Agent's definitions (branch claude/zealous-cannon-ls64p7,
program_intelligence/definitions/*.yaml), restated here so this file stands on its own:

  * status = Removed is excluded from EVERY figure; "Done" is the status NAME, never
    statusCategory (which also contains Removed).
  * scope = Fix Version + Commitment Type (customfield_10094). Target = Committed OR empty,
    Stretch excluded. Status never represents scoping.
  * no percentile or trend on fewer than 5 comparable completed items; releases still running
    are labelled provisional.
  * no ranking, scoring or per-person view of any team or person (rules/no-employee-evaluation.md).

The page is a snapshot: Jira is read once at build time and the numbers are baked in, so the
output (epic titles, internal figures) lives in program_dashboard/build/, which is git-ignored.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "dashboards"))     # reuse the weekly emails' Jira client + EDCT
import edct_from_jira as E  # noqa: E402

PROJECTS = ["PMN", "CXCO", "CXSUP"]
RELEASES = ["25.4", "26.1", "26.2", "26.3", "26.4", "27.1", "27.2"]
CURRENT_RELEASE = "27.1"
PROVISIONAL = ["27.1", "27.2"]          # still running or planned
FIELDS = ["summary", "status", "fixVersions", "created", "resolutiondate",
          "customfield_10094",   # Commitment Type (Committed / Stretch)
          "customfield_10040",   # Epic Team (multi-select)
          "customfield_10098",   # Team Name (single select)
          "customfield_15229",   # Implemented by AI Agent
          "customfield_15264",   # AI Model Used
          "customfield_10099",   # Closed
          "customfield_10139"]   # Issue Category

DATA_PATH = HERE / "build" / "program_data.json"
TEMPLATE = HERE / "dashboard.template.html"
OUT = HERE / "build" / "Program Dashboard.html"


def val(x):
    """Jira option fields arrive as {'value': ...}, lists of those, or plain strings."""
    if x is None:
        return None
    if isinstance(x, list):
        return [val(i) for i in x if i is not None]
    if isinstance(x, dict):
        return x.get("value") or x.get("name")
    return x


def day_counts(events, end: dt.date):
    """Days an epic ended in In Progress / Validation, flagged days excluded. Same day
    accounting as edct_from_jira.edct_days, split by status so the two can be shown apart."""
    events = sorted(events, key=lambda e: e[0])
    if not events:
        return 0, 0
    first = min(e[0].date() for e in events)
    status, flagged, idx, day, ip, vl = None, False, 0, first, 0, 0
    while day <= end:
        boundary = dt.datetime.combine(day, dt.time.max, tzinfo=events[0][0].tzinfo)
        while idx < len(events) and events[idx][0] <= boundary:
            _, kind, value = events[idx]
            if kind == "status":
                status = value
            else:
                flagged = bool(value)
            idx += 1
        if not flagged:
            ip += status == "In Progress"
            vl += status == "Validation"
        day += dt.timedelta(days=1)
    return ip, vl


def epic_metrics(j, key: str, resolved: dt.date):
    events = E.epic_events(j.changelog(key))
    ip, vl = day_counts(events, resolved)
    pipeline = E.edct_days(events, end=resolved, count_done_day=False)
    first_ip = next((e[0].date() for e in sorted(events, key=lambda e: e[0])
                     if e[1] == "status" and e[2] == "In Progress"), None)
    return {"ip": ip, "vl": vl, "edct": ip + vl, "pipeline_edct": pipeline,
            "cal": (resolved - first_ip).days if first_ip else None}


def fetch() -> dict:
    j = E.Jira()
    quoted = ", ".join(f'"{r}"' for r in RELEASES)
    epics = []
    for proj in PROJECTS:
        jql = (f'project = {proj} AND issuetype = Epic AND status != Removed '
               f'AND fixVersion in ({quoted})')
        got = j.search(jql, FIELDS)
        print(f"{proj}: {len(got)} epics", flush=True)
        for i in got:
            f = i["fields"]
            teams = [t for t in (val(f.get("customfield_10040")) or []) if t]
            tn = val(f.get("customfield_10098"))
            if tn and tn not in teams:
                teams.append(tn)
            ai = val(f.get("customfield_15229")) or []
            resolved = (f.get("resolutiondate") or "")[:10] or None
            epics.append({
                "k": i["key"], "p": proj, "t": f["summary"],
                "s": (f.get("status") or {}).get("name"),
                "fv": [v["name"] for v in f.get("fixVersions") or [] if v["name"] in RELEASES],
                "c": val(f.get("customfield_10094")),
                "tm": teams,
                "ai": "Yes" in ai if isinstance(ai, list) else ai == "Yes",
                "m": val(f.get("customfield_15264")),
                "rd": resolved,
                "cat": val(f.get("customfield_10139")),
            })

    done = [e for e in epics if e["s"] == "Done" and e["rd"]]
    print(f"computing cycle time for {len(done)} Done epics ...", flush=True)

    def work(e):
        try:
            return e["k"], epic_metrics(j, e["k"], dt.date.fromisoformat(e["rd"]))
        except Exception as exc:                                  # one bad epic must not sink the build
            return e["k"], {"error": str(exc)[:80]}

    results = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        for n, (k, m) in enumerate(pool.map(work, done), 1):
            results[k] = m
            if n % 100 == 0:
                print(f"  {n}/{len(done)}", flush=True)
    errors = [k for k, m in results.items() if "error" in m]
    drift = [k for k, m in results.items() if "edct" in m and m["edct"] != m["pipeline_edct"]]
    print(f"cycle time done: {len(results) - len(errors)} ok, {len(errors)} errors, "
          f"{len(drift)} differ from the email pipeline's EDCT", flush=True)
    for e in epics:
        m = results.get(e["k"])
        if m and "edct" in m:
            e["ip"], e["vl"], e["edct"], e["cal"] = m["ip"], m["vl"], m["edct"], m["cal"]

    return {"generated": dt.datetime.now().astimezone().isoformat(timespec="minutes"),
            "jiraBase": os.environ["JIRA_BASE_URL"].rstrip("/"),
            "projects": PROJECTS, "releases": RELEASES, "current": CURRENT_RELEASE,
            "provisional": PROVISIONAL, "epics": epics,
            "quality": {"cycleTimeErrors": errors, "edctDiffersFromEmail": drift}}


def render(data: dict) -> None:
    html = TEMPLATE.read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    OUT.write_text(html.replace("/*__DATA__*/null", payload), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB, {len(data['epics'])} epics)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reuse", action="store_true", help="render from build/program_data.json")
    args = ap.parse_args()
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    if args.reuse:
        data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    else:
        data = fetch()
        DATA_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    render(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
