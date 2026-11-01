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

Burnup: Done is cumulative by resolution date; scope is cumulative by the date each epic was
added to the release (from its Fix Version history), judged on today's Commitment Type and with
epics later Removed left out. No projection line is drawn (agent rule: no point forecasts).

The page is a snapshot: Jira is read once at build time and the numbers are baked in, so the
output (epic titles, internal figures) lives in program_dashboard/build/, which is git-ignored.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "dashboards"))     # reuse the weekly emails' Jira client + EDCT
import edct_from_jira as E  # noqa: E402
sys.path.insert(0, str(HERE))
import importlib.util as _ilu  # noqa: E402
_spec = _ilu.spec_from_file_location("release_planning_model", HERE.parent / "release_planning" / "model.py")
RPM = _ilu.module_from_spec(_spec)                       # the release planning report's own pod rule (classify / pod_labels), reused rather than copied
_spec.loader.exec_module(RPM)

PROJECTS = ["PMN", "CXCO", "CXSUP", "CXWFM", "WFM", "CXINT", "INT"]
# Project keys that are reserved JQL words: Jira rejects INT as a bare project key ("'INT' is a reserved JQL word. You must surround it in quotation marks") and wants it quoted.
# EVERY query that names a project key goes through pkey / pkeys; the page has the same helper (JQL_RESERVED_KEYS reaches it through definitions()), and tests/test_program_dashboard.py fails on an unquoted interpolation.
JQL_RESERVED_KEYS = ["INT"]


def pkey(proj: str) -> str:
    """A project key as JQL names it: quoted when it is a reserved word, unchanged otherwise."""
    return f'"{proj}"' if proj in JQL_RESERVED_KEYS else proj


def pkeys(projects) -> str:
    return ", ".join(pkey(p) for p in projects)


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

DEP_TYPES = {"Dependency", "Blocks"}       # Jira link types that mean "this epic needs that one"
BUG_SINCE = "2025-07-09"                 # start of the first release window (25.4): bugs open then or later
BUG_FIELDS = ["summary", "status", "priority", "created", "resolutiondate", "resolution", "reporter",
              "customfield_10098",       # Team Name
              "customfield_10055",       # Regression
              "customfield_10068",       # Number of Incidents (PQCR Cases)
              "customfield_10329",       # SF Connection Case Reference: a Salesforce case makes a bug a customer-found bug
              "customfield_10099",       # Closed (date-time): the date a customer-found bug counts as fixed
              "customfield_10051"]       # Ready to Deploy Date: the fixed date of a Ready for Deploy bug that has no Closed date
# The weekly emails drop these from the backlog; the JQL is theirs, so the flag matches them exactly.
AX_JQL = '(summary ~ "\\"[Accessibility]*\\"" OR labels = DWP_Accessibility_Defect)'
CFB_ACCOUNT = os.environ.get("CFB_REPORTER_ID") or json.loads((HERE.parent / "release_closure" / "config_pmn.json").read_text())["cfb_reporter"]      # CFB_REPORTER_ID wins, so the id can leave the tracked config

DATA_PATH = HERE / "build" / "program_data.json"
TEMPLATE = HERE / "dashboard.template.html"
OUT = HERE / "build" / "Delivery Pulse.html"                      # standalone file, open in a browser
OUT_ARTIFACT = HERE / "build" / "Delivery Pulse (artifact).html"  # body-only page for the Artifact tool


def cloud_id() -> str:
    """Atlassian site id that the live refresh queries. Read from JIRA_CLOUD_ID or from the site's public tenant_info
    endpoint; it is deliberately not stored in the repository."""
    if os.environ.get("JIRA_CLOUD_ID"):
        return os.environ["JIRA_CLOUD_ID"]
    import requests
    r = requests.get(os.environ["JIRA_BASE_URL"].rstrip("/") + "/_edge/tenant_info", timeout=30)
    r.raise_for_status()
    return r.json()["cloudId"]


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


def release_added_dates(histories, created: str, releases: list[str]) -> dict:
    """Date each current release membership began: the latest 'Fix Version' history item that
    added it, or the creation date when it never changed (created with the version)."""
    added = {}
    items = []
    for h in histories:
        when = h["created"][:10]
        for it in h.get("items", []):
            if it.get("fieldId") == "fixVersions" or it.get("field") == "Fix Version":
                items.append((h["created"], when, it.get("fromString"), it.get("toString")))
    items.sort(key=lambda t: t[0])          # timestamp only: the other fields can be None
    for r in releases:
        last_add = None
        for _, when, frm, to in items:
            if to == r:
                last_add = when
            elif frm == r:
                last_add = None
        added[r] = last_add or created
    return added


def analyse(j, e: dict):
    """One changelog request per epic: cycle time for Done epics, release join dates for all."""
    histories = j.changelog(e["k"])
    out = {"ad": release_added_dates(histories, e["cr"], e["fv"])}
    if e["s"] == "Done" and e["rd"]:
        events = E.epic_events(histories)
        resolved = dt.date.fromisoformat(e["rd"])
        ip, vl = day_counts(events, resolved)
        first_ip = next((x[0].date() for x in sorted(events, key=lambda x: x[0])
                         if x[1] == "status" and x[2] == "In Progress"), None)
        out.update({"ip": ip, "vl": vl, "edct": ip + vl,
                    "pipeline_edct": E.edct_days(events, end=resolved, count_done_day=False),
                    "cal": (resolved - first_ip).days if first_ip else None})
    return out


SF_FIELD, CLOSED_FIELD = "customfield_10329", "customfield_10099"
# A customer-found bug (CFB) is a Bug reported by the CFB account OR linked to a Salesforce case. Broader than the alerting rules, which use the reporter only.
CFB_JQL = f'(reporter = "{CFB_ACCOUNT}" OR cf[10329] is not EMPTY)'


def israel_date(ts: str | None) -> str | None:
    """The Israel-local date (YYYY-MM-DD) of a Jira timestamp such as 2026-01-28T09:31:00.000+0200, the page's time base for period boundaries."""
    if not ts:
        return None
    from zoneinfo import ZoneInfo
    t = ts.strip()
    try:
        when = dt.datetime.strptime(t, "%Y-%m-%dT%H:%M:%S.%f%z") if "." in t else dt.datetime.strptime(t, "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        return t[:10]
    return when.astimezone(ZoneInfo("Asia/Jerusalem")).date().isoformat()


def bug_record(i: dict, proj: str, ax_keys: set) -> dict:
    """Compact bug row; absent keys mean false / empty. cfb = a customer-found bug: reported by the CFB account (rb) or linked to a Salesforce case (sf).
    cl = the Israel-local date of the Closed field, kept for customer-found bugs only (the date a fixed CFB counts in a period)."""
    f = i["fields"]
    b = {"k": i["key"], "p": proj, "cr": (f.get("created") or "")[:10],
         "s": (f.get("status") or {}).get("name")}
    for key, v in (("pr", (f.get("priority") or {}).get("name")),
                   ("rd", (f.get("resolutiondate") or "")[:10]),
                   ("rs", (f.get("resolution") or {}).get("name")),
                   ("tm", val(f.get("customfield_10098")))):
        if v:
            b[key] = v
    if i["key"] in ax_keys:
        b["ax"] = 1
    by_reporter = (f.get("reporter") or {}).get("accountId") == CFB_ACCOUNT
    has_case = bool(f.get(SF_FIELD))
    if by_reporter or has_case:
        b["cfb"] = 1
        if by_reporter:
            b["rb"] = 1
        if has_case:
            b["sf"] = 1
        cl = israel_date(f.get(CLOSED_FIELD))
        if cl:
            b["cl"] = cl
        rtd = israel_date(f.get("customfield_10051"))
        if rtd:
            b["rtd"] = rtd
    if val(f.get("customfield_10055")) == "Yes":
        b["rg"] = 1
    if f.get("customfield_10068"):
        b["inc"] = f["customfield_10068"]
    return b


def fetch_windows(j) -> dict:
    """Release start/end from the Jira versions (same source as release_closure). The three
    projects run the same release train, so the first project that has a dated version wins."""
    out = {}
    for proj in PROJECTS:
        vers = {v["name"]: v for v in j.s.get(f"{j.base}/rest/api/3/project/{proj}/versions", timeout=60).json()}
        for r in RELEASES:
            v = vers.get(r)
            if r not in out and v and v.get("startDate") and v.get("releaseDate"):
                out[r] = [v["startDate"], v["releaseDate"]]
    return out


PLAN_FIELDS = ["updated", "duedate", "customfield_12697", "customfield_10021"]      # Last update, Due date, Target Sprint, Flagged (no person is read from Jira)
SPRINT_RE = re.compile(r"^CX\.(\d+\.\d+)\.(\d+) \((\d{1,2})([A-Za-z]{3})(\d{2})\)$")


def plan_record(f) -> dict:
    """Planning facts on an epic: due date (dd), Target Sprint label (ts), last update (ud), Flagged (fl). Absent means empty."""
    out = {}
    if f.get("duedate"):
        out["dd"] = f["duedate"][:10]
    ts = val(f.get("customfield_12697"))
    if ts:
        out["ts"] = ts
    if f.get("updated"):
        out["ud"] = f["updated"][:10]
    if f.get("customfield_10021"):
        out["fl"] = 1
    return out


def sprint_calendar(labels) -> list:
    """Sprint windows. The numbering is regular: three-week (21-day) sprints, four per release, plus a seven-day IP week
    after every fourth sprint (sprint 197 starts 2026-10-14 and opens release 27.1). The calendar is generated from the
    numbering, so a sprint that nobody has planned work in is still on it, and checked against the Target Sprint labels
    ("CX.27.1.197 (14Oct26)": the label date is the sprint start); a label that disagrees keeps its own date."""
    anchor, anchor_no = dt.date(2026, 10, 14), 197
    seen = {}
    for lab in labels:
        m = SPRINT_RE.match(lab or "")
        if m:
            seen[int(m[2])] = (lab, dt.datetime.strptime(f"{m[3]}{m[4]}{m[5]}", "%d%b%y").date())
    if not seen:
        return []
    out = []
    for n in range(min(seen), max(seen) + 1):
        k = (n - anchor_no) // 4
        start = anchor + dt.timedelta(days=21 * (n - anchor_no) + 7 * k)
        lab = None
        if n in seen:
            lab, labelled = seen[n]
            if labelled != start:
                start = labelled
        rel = f"{27 + k // 4}.{k % 4 + 1}"
        out.append({"n": lab or f"CX.{rel}.{n} ({start.strftime('%d%b%y')})", "rel": rel, "no": n, "start": start.isoformat(),
                    "end": (start + dt.timedelta(days=20)).isoformat(), "real": n in seen})
    return out


def collect_status_since(j, epics) -> int:
    """Date each in-flight epic entered its current status (Validation or In Progress), from its changelog."""
    for e in epics:
        e.pop("ss", None)                                    # an earlier pull's day must not survive when the epic is no longer in that status
    todo = [e for e in epics if e["s"] in ("Validation", "In Progress")]

    def work(e):
        try:
            ev = E.epic_events(j.changelog(e["k"]))
            when = [x[0] for x in ev if x[1] == "status" and x[2] == e["s"]]
            return e["k"], max(when).date().isoformat() if when else None
        except Exception:
            return e["k"], None
    got = 0
    by_key = {e["k"]: e for e in epics}
    with ThreadPoolExecutor(max_workers=6) as pool:
        for k, d in pool.map(work, todo):
            if d:
                by_key[k]["ss"] = d
                got += 1
    return got


def collect_bug_updates(j, bugs) -> int:
    """Last update date of open customer-found bugs, for the no-activity insight."""
    by = {b["k"]: b for b in bugs}
    n = 0
    for b in bugs:
        b.pop("ud", None)                                    # a bug that is no longer an open customer-found bug must not keep an earlier pull's date
    for proj in PROJECTS:
        for i in j.search(f'project = {pkey(proj)} AND issuetype = Bug AND {CFB_JQL} AND status not in ({BUG_CLOSED_JQL})', ["updated"]):
            if i["key"] in by and i["fields"].get("updated"):
                by[i["key"]]["ud"] = i["fields"]["updated"][:10]
                n += 1
    return n


HIER_FIELDS = ["summary", "status", "issuetype", "fixVersions", "parent", "project", "duedate", "customfield_12697",
               "updated", "customfield_10040", "customfield_10098", "customfield_10094"]


def hier_record(i) -> dict:
    f = i["fields"]
    teams = [t for t in (val(f.get("customfield_10040")) or []) if t]
    tn = val(f.get("customfield_10098"))
    if tn and tn not in teams:
        teams.append(tn)
    par = f.get("parent")
    rec = {"ty": (f.get("issuetype") or {}).get("name"), "t": f["summary"], "s": (f.get("status") or {}).get("name"),
           "fv": [v["name"] for v in f.get("fixVersions") or []], "p": (f.get("project") or {}).get("key") or i["key"].split("-")[0]}
    if par:
        rec["par"] = par["key"]
    if teams:
        rec["tm"] = teams
    c = val(f.get("customfield_10094"))
    if c:
        rec["c"] = c
    rec.update(plan_record(f))
    return rec


def collect_hier(j, epics, caps) -> dict:
    """The Initiative > Capability > Epic hierarchy behind the CXCROSS view: every CXCROSS issue (Initiatives,
    Capabilities and CXCROSS-owned Epics), every Capability our epics point to, and the Initiatives above them."""
    hier = {}
    for i in j.search("project = CXCROSS AND status != Removed", HIER_FIELDS):
        hier[i["key"]] = hier_record(i)
    for _ in range(2):                                   # capabilities of our epics, then the parents we do not hold yet
        want = sorted(({e.get("cp") for e in epics if e.get("cp")} | {r.get("par") for r in hier.values() if r.get("par")}) - set(hier) - {None})
        for n in range(0, len(want), 80):
            for i in j.search(f'key in ({", ".join(want[n:n + 80])})', HIER_FIELDS):
                hier[i["key"]] = hier_record(i)
    kinds = {}
    for r in hier.values():
        kinds[r["ty"]] = kinds.get(r["ty"], 0) + 1
    print(f"hierarchy: {len(hier)} issues {kinds}", flush=True)
    return {"hier": hier}


NFR_LABEL = "NFR"
NFR_CATEGORIES = ["R&D - 3rd party upgrades", "R&D - Arch/infra refactoring", "R&D Infra", "R&D - Low env. cost optimization"]


POD_DEFAULT_RX = "pod"                                                      # a project without a release planning configuration uses the plain pattern


def pod_patterns() -> dict:
    """The pod_label_regex of each project, read from release_planning/config_<project>.json at build time (default: pod). Stored in the data, never hardcoded."""
    out = {}
    for proj in PROJECTS:
        f = HERE.parent / "release_planning" / f"config_{proj.lower()}.json"
        cfg = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        out[proj] = cfg.get("pod_label_regex") or POD_DEFAULT_RX
    return out


def group_pods(labels_by_epic: dict) -> dict:
    """The page's pod grouping, as a reference: {epic: matched pod labels} -> {pod key (lower case): {"name": first spelling found, "epics": [..]}}.
    Pods are grouped case-insensitively and shown with the first spelling; an epic with two spellings or two pods counts once per pod; an epic with none is not listed (the page shows it under No Pod Label)."""
    out: dict = {}
    for epic, pods in labels_by_epic.items():
        seen = set()
        for p in pods:
            k = p.lower()
            out.setdefault(k, {"name": p, "epics": []})
            if k not in seen:
                seen.add(k)
                out[k]["epics"].append(epic)
    return out


def collect_pods(j, epics) -> dict:
    """Pod labels of the epics (pl = the matched labels only, sorted, as spelled): the release planning report's rule, RPM.pod_labels, with each project's own pattern."""
    rx = pod_patterns()
    by_key = {e["k"]: e for e in epics}
    quoted = ", ".join(f'"{r}"' for r in RELEASES)
    for e in epics:
        e.pop("pl", None)                                                    # a label removed in Jira must not survive from an earlier pull
    n = 0
    for proj in PROJECTS:
        jql = f'project = {pkey(proj)} AND issuetype = Epic AND status != Removed AND fixVersion in ({quoted}) AND labels is not EMPTY'
        for i in j.search(jql, ["labels"]):
            if i["key"] in by_key:
                pods = RPM.pod_labels(i["fields"].get("labels"), rx[proj])
                if pods:
                    by_key[i["key"]]["pl"] = pods
                    n += 1
    print(f"pods: {n} epics carry a pod label; {len({l.lower() for e in epics for l in e.get('pl', [])})} distinct pods (case-insensitive)", flush=True)
    return rx


# ---------------------------------------------------------------- Capitalization % (owner's Jira logic, Closed-date rule)
# Population: Done Bugs, Stories and Tasks of the six projects with a Closed date (customfield_10099, the field the CFB section uses); a Done issue whose Closed field is empty uses its resolution
# date and is counted. No sprint, board or fix version is read. The page turns the Closed day (Israel-local) into a calendar quarter and into the release whose Jira version window contains it.
CAP_PREFIX = "Capitalize"                         # a customfield_10079 value that STARTS WITH this is capitalized ("Non Capitalize ..." and an empty value are not)
CAP_FIELD, CAP_SP_FIELD, CAP_TEAM_FIELD = "customfield_10079", "customfield_10038", "customfield_10098"
CAP_FIELDS = ["issuetype", "status", "resolutiondate", CLOSED_FIELD, CAP_FIELD, CAP_SP_FIELD, CAP_TEAM_FIELD]
CAP_START = "2025-10-01"                          # the start of 2025-Q4: 2025-Q4 and release 26.1 (its Jira window starts 2025-10-08) are complete
CAP_EPOCH = dt.date(2025, 1, 1)                   # the Closed day is stored as days since this date


def cap_start() -> str:
    return CAP_START


def cap_day(fields: dict):
    """(Israel-local Closed day as ISO text, True when the resolution date had to stand in for an empty Closed field); (None, False) when neither can be read."""
    closed = israel_date(fields.get(CLOSED_FIELD))
    if closed:
        return closed, False
    res = israel_date(fields.get("resolutiondate"))
    return (res, True) if res else (None, False)


def cap_is_capitalized(value) -> bool:
    """The option value starts with Capitalize; Non Capitalize ... and an empty value do not."""
    return bool(value) and str(value).startswith(CAP_PREFIX)


def cap_record(issue: dict) -> dict:
    """One issue: capitalized flag, story points (blank = 0), team, Closed day and whether it is the resolution-date fallback."""
    f = issue["fields"]
    val = f.get(CAP_FIELD)
    val = val.get("value") if isinstance(val, dict) else val
    team = f.get(CAP_TEAM_FIELD)
    team = team.get("value") if isinstance(team, dict) else team
    sp = f.get(CAP_SP_FIELD)
    day, fallback = cap_day(f)
    return {"key": issue["key"], "value": val or "", "cap": cap_is_capitalized(val), "sp": float(sp) if isinstance(sp, (int, float)) else 0.0, "team": team or "", "day": day, "fallback": fallback}


def collect_capitalization(j) -> dict:
    """Per project, every Done Bug, Story and Task closed since CAP_START as compact records. rows is one text, records separated by ';', fields by ',':
    key number, project index, value index (-1 empty), story points, Closed day (days since 2025-01-01), team index (-1 none), 1 when the resolution date stood in for the Closed date."""
    start = cap_start()
    wide = (dt.date.fromisoformat(start) - dt.timedelta(days=1)).isoformat()          # the query is a day wider than the rule: Jira reads the date in its own time zone, the rule in Israel's
    values, teams, rows, counts = [], [], [], {}
    fallbacks = 0
    t0 = time.time()
    for pi, proj in enumerate(PROJECTS):
        jql = (f'project = {pkey(proj)} AND status = Done AND issuetype in (Bug, Story, Task) AND '
               f'(cf[10099] >= "{wide}" OR (cf[10099] is EMPTY AND resolutiondate >= "{wide}"))')
        issues = j.search(jql, CAP_FIELDS)
        counts[proj] = 0
        for i in issues:
            r = cap_record(i)
            if r["day"] is None or r["day"] < start:
                continue
            counts[proj] += 1
            fallbacks += 1 if r["fallback"] else 0
            idx = lambda lst, x: lst.index(x) if x in lst else (lst.append(x) or len(lst) - 1)
            rows.append(",".join(str(x) for x in (int(r["key"].split("-")[1]), pi, idx(values, r["value"]) if r["value"] else -1, ("%g" % r["sp"]),
                                                  (dt.date.fromisoformat(r["day"]) - CAP_EPOCH).days, idx(teams, r["team"]) if r["team"] else -1, 1 if r["fallback"] else 0)))
    text = ";".join(rows)
    print(f"capitalization: {len(rows)} issues pulled ({', '.join(f'{k} {v}' for k, v in counts.items())}) in {time.time() - t0:.0f}s; {fallbacks} use the resolution date (no Closed date); "
          f"{len(values)} distinct field values; {len(text) / 1024:.0f} KB of records", flush=True)
    return {"start": start, "prefix": CAP_PREFIX, "epoch": CAP_EPOCH.isoformat(), "projects": PROJECTS,
            "values": values, "teams": teams, "rows": text,
            "pulledAt": dt.datetime.now().astimezone().isoformat(timespec="minutes")}


def collect_nfr(j, epics) -> int:
    """Flag (nf = 1) the epics that carry the NFR label. The other half of the NFR definition, an Issue Category in
    NFR_CATEGORIES, is already on every epic as cat."""
    by_key = {e["k"]: e for e in epics}
    quoted = ", ".join(f'"{r}"' for r in RELEASES)
    for e in epics:
        e.pop("nf", None)
    n = 0
    for proj in PROJECTS:
        jql = f'project = {pkey(proj)} AND issuetype = Epic AND status != Removed AND fixVersion in ({quoted}) AND labels = {NFR_LABEL}'
        for i in j.search(jql, ["labels"]):
            if i["key"] in by_key:
                by_key[i["key"]]["nf"] = 1
                n += 1
    print(f"NFR: {n} epics carry the {NFR_LABEL} label; "
          f"{sum(1 for e in epics if e.get('cat') in NFR_CATEGORIES)} are in the NFR issue categories", flush=True)
    return n


# ----------------------------------------------------------------------------- open customer-found bugs: root cause analysis flags
RCA_FIELD, RCA_REVIEW, RCA_CATEGORY = "customfield_10117", "customfield_12643", "customfield_12710"
BUG_CLOSED = ("Done", "Ready for Deploy", "Closed", "Resolved", "Removed")      # final statuses of a bug: Ready for Deploy counts as Done (epics keep Done = the status named Done)
BUG_CLOSED_JQL = ", ".join(f'"{x}"' if " " in x else x for x in BUG_CLOSED)
TEMPLATE_MIN = 5                      # a Root Cause Analysis text shared by this many CFBs is the unedited template, not an analysis


def plain_text(v) -> str:
    """The text of a textarea field: a string, or Atlassian document format (nested nodes with text leaves)."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    out = []

    def walk(n):
        if isinstance(n, dict):
            if n.get("type") == "text":
                out.append(n.get("text", ""))
            elif n.get("type") in ("hardBreak", "paragraph", "listItem") and out:
                out.append("\n")
            for c in n.get("content") or []:
                walk(c)
        elif isinstance(n, list):
            for c in n:
                walk(c)
    walk(v)
    return "".join(out)


def norm_text(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").strip().lower()


def h53(text: str, seed: int = 0) -> int:
    """cyrb53, a 53-bit string hash over the UTF-16 code units: the page computes the same number (Math.imul), so a Refresh can tell an edited analysis from the unedited template without the template text being stored."""
    u = text.encode("utf-16-le")
    units = [u[i] | (u[i + 1] << 8) for i in range(0, len(u), 2)]
    h1, h2 = 0xDEADBEEF ^ seed, 0x41C6CE57 ^ seed
    m32 = 0xFFFFFFFF

    def imul(a, b_):
        return (a * b_) & m32
    for c in units:
        h1 = imul(h1 ^ c, 2654435761)
        h2 = imul(h2 ^ c, 1597334677)
    h1 = imul(h1 ^ (h1 >> 16), 2246822507) ^ imul(h2 ^ (h2 >> 13), 3266489909)
    h2 = imul(h2 ^ (h2 >> 16), 2246822507) ^ imul(h1 ^ (h1 >> 13), 3266489909)
    return 4294967296 * (2097151 & (h2 & m32)) + (h1 & m32)


def rca_templates(texts: dict[str, str]) -> set[str]:
    counts: dict[str, int] = {}
    for t in texts.values():
        n = norm_text(t)
        if n:
            counts[n] = counts.get(n, 0) + 1
    return {n for n, c in counts.items() if c >= TEMPLATE_MIN}


def rca_flags(texts: dict[str, str]) -> tuple[dict[str, int], int]:
    """1 = the text was edited, 0 = empty or an unedited template. A template is learned, not hard-coded: the most repeated identical text
    (shared by TEMPLATE_MIN or more CFBs). Only the flag is kept for it, never the text."""
    counts: dict[str, int] = {}
    for t in texts.values():
        n = norm_text(t)
        if n:
            counts[n] = counts.get(n, 0) + 1
    templates = {n for n, c in counts.items() if c >= TEMPLATE_MIN}
    return {k: int(bool(norm_text(t)) and norm_text(t) not in templates) for k, t in texts.items()}, len(templates)


def collect_cfb(j) -> dict:
    """Every CFB (bug reported by the CFB account) of the six projects with its Root Cause Analysis state, plus the open count across ALL projects."""
    jql = f'project in ({pkeys(PROJECTS)}) AND issuetype = Bug AND {CFB_JQL}'
    got = j.search(jql, ["summary", "status", RCA_FIELD, RCA_REVIEW, "issuelinks"])
    texts = {i["key"]: plain_text(i["fields"].get(RCA_FIELD)) for i in got}
    flag, ntemplates = rca_flags(texts)
    tpl = sorted(h53(n) for n in rca_templates(texts))                 # the unedited-template texts as hashes, so Refresh can classify a new analysis
    bugs = {}
    for i in got:
        f = i["fields"]
        rv = val(f.get(RCA_REVIEW))
        lk = []
        for l in f.get("issuelinks") or []:
            if (l.get("type") or {}).get("name") == "Problem/Incident":
                other = l.get("outwardIssue") or l.get("inwardIssue")
                if other:
                    lk.append(other["key"])
        rec = {"t": f.get("summary") or "", "rca": flag[i["key"]]}
        if rv in ("Approved", "Not Required"):
            rec["rv"] = "A" if rv == "Approved" else "N"
        if lk:
            rec["lk"] = lk
        if flag[i["key"]] and (f.get("status") or {}).get("name") not in BUG_CLOSED:
            rec["rt"] = re.sub(r"\s+", " ", texts[i["key"]]).strip()[:320]      # an excerpt of an edited analysis, only for bugs that are still open
        bugs[i["key"]] = rec
    allopen = j.search(f'issuetype = Bug AND {CFB_JQL} AND status not in ({BUG_CLOSED_JQL})', ["project"])
    by = {}
    for i in allopen:
        pk = (i["fields"].get("project") or {}).get("key") or i["key"].split("-")[0]
        by[pk] = by.get(pk, 0) + 1
    print(f"CFB: {len(bugs)} bugs in the six projects ({sum(v['rca'] for v in bugs.values())} with an edited analysis, {ntemplates} template texts learned); "
          f"{len(allopen)} open across all projects", flush=True)
    return {"bugs": bugs, "templates": ntemplates, "tpl": tpl, "allOpen": len(allopen), "allOpenByProject": by,
            "pulledAt": dt.datetime.now().astimezone().isoformat(timespec="minutes")}


# ----------------------------------------------------------------------------- capabilities: the Capability list and all their child epics
CAP_PROJECTS = PROJECTS + ["CXCROSS"]
CAP_RELEASES = [r for r in RELEASES if r != "25.4"]                 # Capabilities are read for 26.1 to 27.2


def collect_capabilities(j, known: dict) -> dict:
    """capList: the Capabilities of the six projects and CXCROSS that carry a release fix version (26.1 to 27.2), plus the Capabilities our epics point to
    (any project), each as {t, s, p, fv, cl}: cl is the Commitment Level option ("" when empty). capEpics: ALL non-Removed child epics, in any project and with any fix version, of the six-project Capabilities, as compact rows
    [key, project, status, release fix versions, Issue Category, Capability]. capNoFv: Capabilities with no fix version at all (a count, no records)."""
    quoted = ", ".join(f'"{r}"' for r in CAP_RELEASES)
    fields = ["summary", "status", "fixVersions", "project", "customfield_10136"]      # customfield_10136: Commitment Level (a single select on Capabilities)

    def rec(i):
        f = i["fields"]
        return {"t": f["summary"], "s": (f.get("status") or {}).get("name"), "p": (f.get("project") or {}).get("key") or i["key"].split("-")[0],
                "fv": [v["name"] for v in f.get("fixVersions") or []], "cl": val(f.get("customfield_10136")) or ""}
    caps = {i["key"]: rec(i) for i in j.search(f'project in ({pkeys(CAP_PROJECTS)}) AND issuetype = Capability AND status != Removed AND fixVersion in ({quoted})', fields)}
    print(f"capabilities: {len(caps)} with a fix version in {CAP_RELEASES[0]} to {CAP_RELEASES[-1]}", flush=True)
    want = sorted(set(known) - set(caps))                            # the Capabilities that our epics (the release data) point to and that are not in the list yet
    extra = 0
    for n in range(0, len(want), 80):
        for i in j.search(f'key in ({", ".join(want[n:n + 80])}) AND status != Removed', fields):
            caps[i["key"]] = rec(i)
            extra += 1
    print(f"capabilities: {extra} more that our epics point to (any project)", flush=True)
    nofv = j.search(f'project in ({pkeys(CAP_PROJECTS)}) AND issuetype = Capability AND status != Removed AND fixVersion is EMPTY', ["status"])
    no_fv = {"total": len(nofv), "done": sum(1 for i in nofv if (i["fields"].get("status") or {}).get("name") == "Done")}
    keys = sorted(k for k, v in caps.items() if v["p"] in PROJECTS and any(r in CAP_RELEASES for r in v["fv"]))
    rows = []
    for n in range(0, len(keys), 80):
        for i in j.search(f'parent in ({", ".join(keys[n:n + 80])}) AND issuetype = Epic AND status != Removed',
                          ["status", "project", "fixVersions", "customfield_10139", "parent"]):
            f = i["fields"]
            rows.append([i["key"], (f.get("project") or {}).get("key") or i["key"].split("-")[0], (f.get("status") or {}).get("name"),
                         [v["name"] for v in f.get("fixVersions") or [] if v["name"] in RELEASES], val(f.get("customfield_10139")) or "", f["parent"]["key"]])
        if (n // 80) % 5 == 4:
            print(f"  child epics: {min(n + 80, len(keys))}/{len(keys)} capabilities read, {len(rows)} epics", flush=True)
    print(f"capabilities: {len(rows)} child epics of {len(keys)} six-project Capabilities; {no_fv['total']} Capabilities have no fix version", flush=True)
    return {"capList": caps, "capEpics": rows, "capNoFv": no_fv, "capPulledAt": dt.datetime.now().astimezone().isoformat(timespec="minutes")}


def collect_epic_bugs(j, epics) -> dict:
    """Bugs whose parent is an epic (type Bug exactly, Removed excluded), for every epic of the six projects: {epic: [[bug, status, priority]]}.
    A read of Jira found no other way a bug is tied to an epic (no issue links, no grandchildren), so the parent link is the whole relation."""
    keys = sorted(e["k"] for e in epics)
    out, total = {}, 0
    for n in range(0, len(keys), 80):
        for i in j.search(f'parent in ({", ".join(keys[n:n + 80])}) AND issuetype = Bug AND status != Removed', ["status", "priority", "parent"]):
            f = i["fields"]
            out.setdefault(f["parent"]["key"], []).append([i["key"], (f.get("status") or {}).get("name"), (f.get("priority") or {}).get("name")])
            total += 1
    print(f"epic bugs: {total} bugs under {len(out)} of {len(keys)} epics", flush=True)
    return out


def planning(j, epics, bugs, links) -> dict:
    """Everything the planning and insight views need beyond the basic pull."""
    labels = {e.get("ts") for e in epics} | {x.get("ts") for x in links["ext"].values()}
    got = collect_status_since(j, epics)
    nb = collect_bug_updates(j, bugs)
    sprints = sprint_calendar(labels)
    podrx = collect_pods(j, epics)
    print(f"planning: {sum(1 for e in epics if e.get('dd'))} epics with a due date, {sum(1 for e in epics if e.get('ts'))} with a target sprint, "
          f"{len(sprints)} sprints, status-since for {got} in-flight epics, last update for {nb} open CFB bugs", flush=True)
    return {"sprints": sprints, "eb": collect_epic_bugs(j, epics), "podRx": podrx}


def dep_pair(key, link):
    """For a Dependency or Blocks link on an epic return (dependent, provider, type, other end), else None. The other end may be ANY issue type
    (Epic, Initiative, Capability, Story, Task ...): one end is always the epic the link was read from.
    Dependency: outward "depends on", inward "is needed by". Blocks: outward "blocks", inward "is blocked by"."""
    t = link["type"]["name"]
    if t not in DEP_TYPES:
        return None
    out, inn = link.get("outwardIssue"), link.get("inwardIssue")
    other = out or inn
    if not other:
        return None
    ok = other["key"]
    if t == "Dependency":
        dependent, provider = (key, ok) if out else (ok, key)
    else:
        dependent, provider = (ok, key) if out else (key, ok)
    return dependent, provider, t, other


def collect_story_links(j, epics) -> dict:
    """Dependency or Blocks links that sit on the stories, tasks and bugs UNDER the epics of the release train (not on the epics themselves).
    Kept apart from the epic board: sdeps = [dependent, provider, "D"/"B"/"DB", [parent epics of the ends]]; sinfo = status, project and type of each end."""
    keys = sorted(e["k"] for e in epics)
    pairs, info = {}, {}
    for n in range(0, len(keys), 80):
        for i in j.search(f'parent in ({", ".join(keys[n:n + 80])}) AND status != Removed AND issueLinkType in ({", ".join(sorted(DEP_TYPES))})',
                          ["issuelinks", "status", "issuetype", "parent"]):
            f = i["fields"]
            pe = (f.get("parent") or {}).get("key")
            info[i["key"]] = {"s": (f.get("status") or {}).get("name"), "ty": (f.get("issuetype") or {}).get("name"), "par": pe}
            for link in f.get("issuelinks") or []:
                r = dep_pair(i["key"], link)
                if not r:
                    continue
                d, p, t, other = r
                if (other["fields"].get("status") or {}).get("name") == "Removed":
                    continue
                if other["key"] not in info:
                    info[other["key"]] = {"s": (other["fields"].get("status") or {}).get("name"), "ty": (other["fields"].get("issuetype") or {}).get("name")}
                rec = pairs.setdefault((d, p), {"t": set(), "pe": set()})
                rec["t"].add("D" if t == "Dependency" else "B")
                if pe:
                    rec["pe"].add(pe)
        if (n // 80) % 10 == 9:
            print(f"  story-level links: {min(n + 80, len(keys))}/{len(keys)} epics read", flush=True)
    sdeps = sorted([d, p, "".join(c for c in "DB" if c in rec["t"]), sorted(rec["pe"])] for (d, p), rec in pairs.items())
    print(f"story-level links: {len(sdeps)} pairs under {len({pe for r in sdeps for pe in r[3]})} epics", flush=True)
    return {"sdeps": sdeps, "sinfo": info}


def collect_links(j, epics) -> dict:
    """Dependencies between epics, and each epic's parent Capability. Epics at the far end of a link that are not in
    `epics` (other projects, other releases) are read once so the page can show their status, release and team."""
    by_key = {e["k"]: e for e in epics}
    quoted = ", ".join(f'"{r}"' for r in RELEASES)
    pairs, caps, dropped = set(), {}, {"removed": 0}
    other_type = {}                                           # issue type of the far end of each pair, read from the link itself
    for proj in PROJECTS:
        jql = f'project = {pkey(proj)} AND issuetype = Epic AND status != Removed AND fixVersion in ({quoted})'
        for i in j.search(jql, ["issuelinks", "parent"] + PLAN_FIELDS):
            f = i["fields"]
            if i["key"] in by_key:
                for gone in ("dd", "ts", "ud", "as", "fl", "cp"):      # a field emptied in Jira (a parent Capability too) must not survive from an earlier pull
                    by_key[i["key"]].pop(gone, None)
                by_key[i["key"]].update(plan_record(f))
            par = f.get("parent")
            if par and (par["fields"].get("issuetype") or {}).get("name") == "Capability":
                caps[par["key"]] = par["fields"]["summary"]
                if i["key"] in by_key:                      # epics created after the snapshot are not in the data yet
                    by_key[i["key"]]["cp"] = par["key"]
            for link in f.get("issuelinks") or []:
                r = dep_pair(i["key"], link)
                if not r:
                    continue
                d, p, t, other = r
                if (other["fields"].get("status") or {}).get("name") == "Removed":
                    dropped["removed"] += 1
                    continue
                other_type[other["key"]] = (other["fields"].get("issuetype") or {}).get("name") or "Epic"
                pairs.add((d, p, t))
    outside = sorted({k for d, p, t in pairs for k in (d, p)} - set(by_key))
    ext = {}
    for n in range(0, len(outside), 80):
        chunk = outside[n:n + 80]
        for i in j.search(f'key in ({", ".join(chunk)})',
                          ["summary", "status", "issuetype", "fixVersions", "parent", "customfield_10040", "customfield_10098", "project"] + PLAN_FIELDS):
            f = i["fields"]
            teams = [t for t in (val(f.get("customfield_10040")) or []) if t]
            tn = val(f.get("customfield_10098"))
            if tn and tn not in teams:
                teams.append(tn)
            rec = {"p": (f.get("project") or {}).get("key") or i["key"].split("-")[0], "t": f["summary"],
                   "s": (f.get("status") or {}).get("name"), "fv": [v["name"] for v in f.get("fixVersions") or []], "tm": teams,
                   **plan_record(f)}
            ty = (f.get("issuetype") or {}).get("name")
            if ty and ty != "Epic":
                rec["ty"] = ty                                  # absent means Epic
            par = f.get("parent")
            if par and (par["fields"].get("issuetype") or {}).get("name") == "Capability":
                caps[par["key"]] = par["fields"]["summary"]
                rec["cp"] = par["key"]
            ext[i["key"]] = rec
    kinds_n = {}
    for k in {k for d, p, t in pairs for k in (d, p)}:
        ty = by_key.get(k) and "Epic" or (ext.get(k) or {}).get("ty") or "Epic"
        kinds_n[ty] = kinds_n.get(ty, 0) + 1
    print(f"links: {len({(d, p) for d, p, t in pairs})} dependency pairs with an epic at one end ({dropped['removed']} to Removed issues left out); "
          f"{len(outside)} issues outside the release data; ends by type {dict(sorted(kinds_n.items()))}; {len(caps)} capabilities", flush=True)
    merged = {}                                                     # the same pair linked as Dependency and as Blocks is one dependency ("DB")
    for d, p, t in pairs:
        merged.setdefault((d, p), set()).add("D" if t == "Dependency" else "B")
    story = collect_story_links(j, epics)
    return {**story, "deps": sorted([d, p, "".join(c for c in "DB" if c in kinds)] for (d, p), kinds in merged.items()),
            "ext": ext, "capabilities": caps, "depsDropped": dropped,
            "linksPulledAt": dt.datetime.now().astimezone().isoformat(timespec="minutes")}      # per-source stamp: the header shows the oldest source, so a links-only re-pull must not read as older than it is


def collect_bugs(j) -> list:
    """Every Bug of the six projects open, created, resolved or closed since BUG_SINCE, as compact rows (see bug_record)."""
    bugs = []
    for proj in PROJECTS:
        base = (f'project = {pkey(proj)} AND issuetype = Bug AND (created >= "{BUG_SINCE}" '
                f'OR resolutiondate >= "{BUG_SINCE}" OR cf[10099] >= "{BUG_SINCE}" OR resolution is EMPTY)')
        ax_keys = {i["key"] for i in j.search(f"{base} AND {AX_JQL}", ["summary"])}
        got = j.search(base, BUG_FIELDS)
        bugs += [bug_record(i, proj, ax_keys) for i in got]
        print(f"{proj}: {len(got)} bugs ({len(ax_keys)} accessibility)", flush=True)
    n = sum(1 for b in bugs if b.get("cfb"))
    print(f"customer-found bugs: {n} (reported by the CFB account {sum(1 for b in bugs if b.get('rb'))}, with a Salesforce case {sum(1 for b in bugs if b.get('sf'))})", flush=True)
    return bugs


def fetch() -> dict:
    j = E.Jira()
    quoted = ", ".join(f'"{r}"' for r in RELEASES)
    epics = []
    for proj in PROJECTS:
        jql = (f'project = {pkey(proj)} AND issuetype = Epic AND status != Removed '
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
                "rd": resolved, "cr": (f.get("created") or "")[:10],
                "cat": val(f.get("customfield_10139")),
            })

    bugs = collect_bugs(j)
    bugs_at = dt.datetime.now().astimezone().isoformat(timespec="minutes")

    print(f"reading the changelog of {len(epics)} epics (cycle time + release join dates) ...", flush=True)

    def work(e):
        try:
            return e["k"], analyse(j, e)
        except Exception as exc:                                  # one bad epic must not sink the build
            return e["k"], {"error": str(exc)[:80]}

    results = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        for n, (k, m) in enumerate(pool.map(work, epics), 1):
            results[k] = m
            if n % 200 == 0:
                print(f"  {n}/{len(epics)}", flush=True)
    errors = [k for k, m in results.items() if "error" in m]
    drift = [k for k, m in results.items() if "edct" in m and m["edct"] != m["pipeline_edct"]]
    print(f"changelogs done: {len(results) - len(errors)} ok, {len(errors)} errors, "
          f"{len(drift)} cycle times differ from the email pipeline's EDCT", flush=True)
    for e in epics:
        m = results.get(e["k"])
        if m and "error" not in m:
            e["ad"] = m["ad"]
            if "edct" in m:
                e["ip"], e["vl"], e["edct"], e["cal"] = m["ip"], m["vl"], m["edct"], m["cal"]

    links = collect_links(j, epics)
    plan = planning(j, epics, bugs, links)
    plan.update(collect_hier(j, epics, links["capabilities"]))
    collect_nfr(j, epics)
    cfbx = collect_cfb(j)
    capx = collect_capabilities(j, {e["cp"] for e in epics if e.get("cp")})
    capz = collect_capitalization(j)
    return {"cfbx": cfbx, "cap": capz, **capx, "generated": dt.datetime.now().astimezone().isoformat(timespec="minutes"), **links, **plan,
            "jiraBase": os.environ["JIRA_BASE_URL"].rstrip("/"),
            "projects": PROJECTS, "releases": RELEASES, "current": CURRENT_RELEASE,
            "windows": fetch_windows(j),
            "provisional": PROVISIONAL, "epics": epics, "bugs": bugs,
            "cfbAccount": CFB_ACCOUNT, "bugSince": BUG_SINCE, "bugsPulledAt": bugs_at}


SCHEMA = 2           # the payload layout the page expects (PAGE_SCHEMA in dashboard.template.html must be the same number; tests/test_definitions_contract.py checks it)
REQUIRED = {"generated": str, "jiraBase": str, "projects": list, "releases": list, "current": str, "windows": dict, "epics": list, "bugs": list,
            "cfbAccount": str}          # without these the page cannot draw: stop the build instead of publishing an empty page
NONEMPTY = {"projects", "releases", "windows", "epics", "generated", "jiraBase"}      # an empty bug list is a real (if unlikely) state; an empty epic list is a failed pull
EXPECTED = {"hier": dict, "capabilities": dict, "capList": dict, "capEpics": list, "cfbx": dict, "deps": list, "cap": dict, "podRx": dict, "sprints": list}      # optional sections: a build without them still renders, the page shows a notice


def definitions() -> dict:
    """The definitions that the collector and the page must agree on, written once into the payload (DATA.defs). The page reads them from here;
    its own literals are only a fallback for an older payload, and tests/test_definitions_contract.py keeps the two equal."""
    return {"bugClosed": list(BUG_CLOSED), "nfrLabel": NFR_LABEL, "nfrCategories": list(NFR_CATEGORIES),
            "commitTypes": ["Committed", "Not Set", "Stretch"], "targetCommit": ["Committed", "Not Set"], "jqlReservedKeys": list(JQL_RESERVED_KEYS)}


def build_stamp() -> dict:
    """Which code produced this page: short commit, whether the working tree had uncommitted changes, when. Shown in the tooltip of the data stamp."""
    import subprocess
    def git(*a):
        return subprocess.run(["git", *a], cwd=HERE, capture_output=True, text=True, timeout=20).stdout.strip()
    try:
        sha = git("rev-parse", "--short", "HEAD"); dirty = bool(git("status", "--porcelain", "--", "."))
    except Exception:
        sha, dirty = "", False
    return {"sha": sha, "dirty": dirty, "at": dt.datetime.now().astimezone().isoformat(timespec="minutes")}


def validate_payload(data: dict) -> list[str]:
    """Hard problems raise (nothing is published); soft ones are returned as warnings."""
    bad = [k for k, t in REQUIRED.items() if not isinstance(data.get(k), t) or (k in NONEMPTY and not data.get(k))]
    if bad:
        raise SystemExit(f"program_data.json is missing required data: {', '.join(bad)}. Run a full build (no flag) or restore the last good build/program_data.json.prev.")
    warn = [f"optional section '{k}' is missing or has the wrong type; the page will show a notice for it" for k, t in EXPECTED.items() if not isinstance(data.get(k), t)]
    unknown = unknown_sprint_labels(data)
    if unknown:
        warn.append(f"{sum(unknown.values())} epics carry {len(unknown)} Target Sprint labels the sprint calendar does not know (e.g. {', '.join(sorted(unknown)[:3])}); "
                    "the page and the Delivery Cycles links count them as having no Target Sprint")
    return warn


def unknown_sprint_labels(data: dict) -> dict:
    """Target Sprint labels on epics that are not in the sprint calendar, with their epic counts (a label that does not follow the CX.<release>.<number> (<date>) pattern)."""
    cal = {x.get("n") for x in data.get("sprints") or []}
    if not cal:
        return {}
    out: dict = {}
    for e in data.get("epics") or []:
        if e.get("ts") and e["ts"] not in cal:
            out[e["ts"]] = out.get(e["ts"], 0) + 1
    return out


def drop_people(data: dict) -> None:
    """No person is held in the payload: an assignee name left in an older snapshot is removed on every save and render."""
    for rec in list(data.get("epics") or []) + list((data.get("ext") or {}).values()):
        rec.pop("as", None)


def save_data(data: dict) -> None:
    """Write build/program_data.json atomically and keep the previous file as .prev: a crash while writing, or a bad pull, never costs the only snapshot (a full pull is about 3,000 Jira calls)."""
    drop_people(data)
    validate_payload(data)                                                # a bad pull must not replace the snapshot (or, on a second run, its .prev)
    text = json.dumps(data, ensure_ascii=False)
    json.loads(text)                                                      # what is written must read back
    tmp = DATA_PATH.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8")
    if DATA_PATH.exists():
        shutil.copy2(DATA_PATH, DATA_PATH.with_suffix(".json.prev"))
    os.replace(tmp, DATA_PATH)


def render(data: dict) -> None:
    """The template is a body-only fragment (title, meta, style, markup, script), which is exactly what the
    Artifact tool wants. The standalone file wraps the same fragment in a document and hoists title and meta."""
    drop_people(data)
    labels = {e.get("ts") for e in data["epics"]} | {x.get("ts") for x in (data.get("ext") or {}).values()}
    data["sprints"] = sprint_calendar(labels) or data.get("sprints", [])
    if not data.get("cloudId"):
        try:
            data["cloudId"] = cloud_id()
        except Exception as exc:                                  # the page renders; only Refresh from Jira needs it
            print(f"warning: could not read the Atlassian site id ({exc}); set JIRA_CLOUD_ID to enable Refresh", flush=True)
            data["cloudId"] = ""
    data.pop("cycles", None); data.pop("quality", None)               # no longer read by the page (the Confluence cycles pull and the changelog error tally)
    data["schema"] = SCHEMA; data["defs"] = definitions(); data["build"] = build_stamp()
    for w in validate_payload(data):
        print("warning:", w, flush=True)
    # an older pull may hold projects that have since been dropped from PROJECTS: keep only the current ones
    data["projects"] = PROJECTS
    data["epics"] = [e for e in data["epics"] if e["p"] in PROJECTS]
    data["bugs"] = [b for b in data["bugs"] if b["p"] in PROJECTS]
    fragment = TEMPLATE.read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    assert fragment.count("/*__DATA__*/null") == 1
    fragment = fragment.replace("/*__DATA__*/null", payload)
    OUT_ARTIFACT.write_text(fragment, encoding="utf-8")

    head = ""
    for pattern in (r"<title>.*?</title>\s*", r'<meta name="claude:viewport-fit-sides"[^>]*>\s*'):
        m = re.search(pattern, fragment, re.S)
        head += m.group(0)
        fragment = fragment.replace(m.group(0), "", 1)
    OUT.write_text('<!DOCTYPE html>\n<html lang="en"><head><meta charset="UTF-8">'
                   '<meta name="viewport" content="width=device-width, initial-scale=1">'
                   f"{head}</head><body>\n{fragment}\n</body></html>", encoding="utf-8")
    print(f"wrote {OUT} and {OUT_ARTIFACT.name} ({OUT.stat().st_size // 1024} KB, "
          f"{len(data['epics'])} epics, {len(data['bugs'])} bugs)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reuse", action="store_true", help="render from build/program_data.json")
    ap.add_argument("--add-nfr", action="store_true", help="flag the epics that carry the NFR label in build/program_data.json, then render")
    ap.add_argument("--add-hier", action="store_true", help="add the CXCROSS Initiative > Capability hierarchy to build/program_data.json, then render")
    ap.add_argument("--add-planning", action="store_true", help="add due dates, target sprints, sprint calendar, status-since and bug updates to build/program_data.json, then render")
    ap.add_argument("--add-deps", action="store_true", help="read dependency links and capabilities into build/program_data.json (no changelog calls), then render")
    ap.add_argument("--add-bugs", action="store_true", help="re-read the bugs (customer-found bugs by reporter OR Salesforce case, Closed dates) and the Open CFB Root Cause Analysis state into build/program_data.json, then render")
    ap.add_argument("--add-pods", action="store_true", help="read the pod labels of the epics (each project's pod_label_regex from release_planning/config_*.json) into build/program_data.json, then render")
    ap.add_argument("--add-cfb-open", action="store_true", help="pull the root cause analysis state of the customer-found bugs (Open CFBs table) into build/program_data.json, then render")
    ap.add_argument("--add-capitalization", action="store_true", help="pull the Done Bugs, Stories and Tasks by Closed date (Capitalization %% chart: capitalize field, story points, fix versions, team; Closed day on or after 2025-10-01, Israel time, resolution date when Closed is empty) into build/program_data.json, then render")
    ap.add_argument("--add-capabilities", action="store_true", help="pull the Capability list and all their child epics (Capabilities section, Done Capabilities per Release) into build/program_data.json, then render")
    ap.add_argument("--add-cycles", action="store_true", help="no longer used (kept so old command lines still run): the Confluence pods pull was removed; Group By is Team or Pod from labels")
    args = ap.parse_args()
    modes = [a for a in ("reuse", "add_nfr", "add_hier", "add_planning", "add_deps", "add_bugs", "add_pods", "add_cfb_open", "add_capitalization", "add_capabilities", "add_cycles") if getattr(args, a)]
    if len(modes) > 1:      # the branches below are an if/elif chain: a second flag used to be skipped without a word
        ap.error("use one mode flag at a time (got " + ", ".join("--" + m.replace("_", "-") for m in modes) + "); run them one after another")
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    if args.add_nfr:
        data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        collect_nfr(E.Jira(), [e for e in data["epics"] if e["p"] in PROJECTS])
        save_data(data)
    elif args.add_pods:
        data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        data["podRx"] = collect_pods(E.Jira(), [e for e in data["epics"] if e["p"] in PROJECTS])
        save_data(data)
    elif args.add_hier:
        data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        data.update(collect_hier(E.Jira(), [e for e in data["epics"] if e["p"] in PROJECTS], data.get("capabilities", {})))
        save_data(data)
    elif args.add_planning:
        data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        eps = [e for e in data["epics"] if e["p"] in PROJECTS]
        data.update(collect_links(E.Jira(), eps))
        j = E.Jira()
        data.update(planning(j, eps, [b for b in data["bugs"] if b["p"] in PROJECTS], data))
        save_data(data)
    elif args.add_capitalization:
        data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        data["cap"] = collect_capitalization(E.Jira())
        save_data(data)
    elif args.add_capabilities:
        data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        data.update(collect_capabilities(E.Jira(), {e["cp"] for e in data["epics"] if e.get("cp")}))
        save_data(data)
    elif args.add_bugs:
        data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        j = E.Jira()
        data["bugs"] = collect_bugs(j)
        collect_bug_updates(j, data["bugs"])
        data["cfbx"] = collect_cfb(j)
        data["bugsPulledAt"] = dt.datetime.now().astimezone().isoformat(timespec="minutes")
        save_data(data)
    elif args.add_cfb_open:
        data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        data["cfbx"] = collect_cfb(E.Jira())
        save_data(data)
    elif args.add_cycles:
        print("--add-cycles does nothing any more: Delivery Cycle Governance groups by Epic Team or by pod label, both from the main pull (--add-pods for the labels).")
        return 0
    elif args.add_deps:
        data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        data.update(collect_links(E.Jira(), [e for e in data["epics"] if e["p"] in PROJECTS]))
        save_data(data)
    elif args.reuse:
        data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    else:
        data = fetch()
        save_data(data)
    had_cloud_id = bool(data.get("cloudId"))
    render(data)
    if not had_cloud_id and data.get("cloudId"):                  # keep it in the saved (git-ignored) data so offline re-renders still work
        save_data(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
