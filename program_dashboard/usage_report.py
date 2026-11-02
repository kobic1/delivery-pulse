#!/usr/bin/env python3
"""Owner report for the Delivery Pulse usage statistics: an aggregate text report and a self-contained dashboard page ("Delivery Pulse Usage").

The published Delivery Pulse page keeps one small record per person, `usage/<opaque user id>`, in its own artifact database (see the "Usage statistics" section of
program_dashboard/README.md for the record, the vocabulary and the access rules). Export those documents with the ArtifactData tool (`list`, collection `usage`) into a JSON file and run:

    python3 program_dashboard/usage_report.py export.json --as-of 2026-11-02T10:15:00+02:00        # text report on the screen
    python3 program_dashboard/usage_report.py export.json --html usage.html --as-of ... --since 2026-10-14 --audience 120 --calendar build/usage_calendar.json
    python3 program_dashboard/usage_report.py --demo --html usage_demo.html --standalone            # the same page from fictitious data (a "Demo data" banner), to review the layout

Options: --since YYYY-MM-DD (the go-live day: earlier days are the Sandbox and are ignored), --audience N (the size of the intended audience: without it the page shows no adoption percentage),
--thresholds file.json (overrides of THRESHOLDS), --calendar usage_calendar.json (from `build_dashboard.py --emit-usage-calendar`: release milestones, sprint boundaries, optional owner review days and quiet weeks),
--as-of (when the export was taken; without it the current Israel date is used and the page says that no export time was given), --today (the Israel day to report about, default the current one).

The input is a JSON list of the documents. Both shapes are accepted: the bodies themselves, or {"id": ..., "data": {body}} rows (also "doc_id"/"data", and a wrapper object holding the list under
"documents", "docs", "items", "rows" or "results"). The id of a document is read ONLY to drop a duplicated document (it is hashed in memory and then forgotten); users are told apart by their position in the file,
and no user id, name, e-mail address, issue key or team name is ever printed or written to the page. A record is "pseudonymous, not anonymous": the editors of the published page can read the ids.

Privacy rule of the report: every breakdown that rests on fewer than 5 distinct people prints "<5 users" instead of a number (and its chart bar is not drawn); a figure that would reveal such a group by subtraction
(a partition printed next to its total) is withheld too (`protect_partition`); a percentage prints only when its denominator is at least 20, otherwise the counts are printed with "n=".
The report never ranks or evaluates people or teams. Counts are computed over what the people's browsers recorded; people that are signed out or hold view-only access, that open an offline copy, or whose browser blocks
the page's storage are not in the data.

WEEKS are Sunday-start work weeks (Sunday to Saturday), complete only after Saturday has passed. Only completed weeks are compared; the week in progress and the first week of data (when the data starts mid-week) are never
used for a change statement. PROGRAM weeks (W1..W12 of a release) are used only for calendar annotations, from the calendar file the dashboard builder writes (the dashboard's own W1 definition).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import math
import random
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    IL = ZoneInfo("Asia/Jerusalem")
except Exception:                                                                    # pragma: no cover - a Python without time zone data
    IL = dt.timezone(dt.timedelta(hours=2))

MIN_USERS = 5
SMALL = "<5 users"
SHORT_HISTORY_DAYS = 14
SECTION_MIN_SECONDS = 30                                                              # a person "reached" a section in a week with at least this many seconds in it (summed over the week)

# ------------------------------------------------------------------------------------------------------------ the thresholds (approved defaults; override with --thresholds file.json)
THRESHOLDS = {
    # what counts as enough evidence
    "min_den": 20,                      # a percentage prints, and a share/reach/control signal is tested, only with at least this many people (or visits) behind the denominator
    "baseline_weeks": 6,                # the baseline is the median of up to this many completed weeks before the compared week
    "baseline_min": 5,                  # and needs at least this many comparable weeks, else "baseline building (n of 5)"
    "band_mad": 3.0,                    # the band is median +- max(band_mad x 1.4826 x MAD, floor)
    "floor_people_abs": 3, "floor_people_rel": 0.15,       # floor of the band for counts of people: max(3, 15% of the median)
    "floor_reach_pp": 10,               # floor of the band for reach, percentage points
    "change_people_abs": 3, "change_people_rel": 0.20,     # a material change in a count: at least max(3 people, 20%) ...
    "change_reach_pp": 15,              # ... or this many percentage points for a reach
    "established_days": 14,             # established = first seen at least this many days before the compared week
    "max_signals_shown": 3,             # at most this many section or control signals in the top block
    "weak_active_people": 30,           # a signal seen in one week with fewer active people than this is labelled Weak signal
    # S1 new people, S2 lapsed regulars
    "s1_min_new": 5,
    "s2_weeks_needed": 7, "s2_regular_weeks": 3, "s2_min_regulars": 10, "s2_min_lapsed": 5, "s2_lapsed_share": 0.20,
    # S3 section reach, S4 controls
    "s3_baseline_weeks_with_readers": 4,        # of the baseline weeks (5 or 6) at least this many (and 80%) had 5 or more readers
    "s4_stop_pct": 10, "s4_stop_weeks": 4, "s4_stop_consecutive": 2,
    "s4_new_pct": 10,
    # S5 errors (windowed, per build)
    "err_people": 5, "err_visit_share": 0.02, "err_visit_min": 50, "err_consecutive_weeks": 2, "err_quiet_days": 14,
    # S6..S9
    "s6_age_days": 7, "s6_min_people": 5, "s6_min_share": 0.15,
    "s7_export_stale_days": 3, "s7_dropped_keys_share": 0.05,
    "s8_share": 0.15, "s8_min_people": 10, "s9_share": 0.10,
    # adoption views
    "growth_weeks": 6, "growth_rel": 0.20, "growth_abs": 3,
    "habit_weeks": 8, "habit_min_weeks": 4,
    "retention_w1_days": 7, "retention_w4_days": 28,
    "window_weeks": 4,
    "simplify_reach_pct": 10, "simplify_weeks": 4,
    "reset_rate": 0.25, "reset_weeks": 2, "reset_min_people": 10, "reset_min_visits": 30,
    "link_min_clicks": 30, "link_min_people": 10,
    # calendar
    "event_min": 3, "event_days": 3,
    "workweek_min_visits": 30,
    # the retention promise of the page
    "retention_weeks": 12,
}

# ------------------------------------------------------------------------------------------------------------ the record shape this report reads
# ONE place that defines what a record looks like: the page (dashboard.template.html, the usage block) writes it, this report reads it, and the tests build their fictitious data from it.
# Schema v1 is the record the first version of the page wrote; v2 adds the fields marked (v2). A v2 page also writes the week key as "S<date of the Sunday>" and `t` in hours.
# A missing field in a v1 session means UNKNOWN, never 0. A session counts as v2 when it carries any of V2_MARKERS (every v2 session writes them).
RECORD_SHAPE = {
    "record": {
        "u": "the opaque user id (read only to drop a duplicated document, never printed)",
        "v": "schema version, 1 or 2; any other value is an unknown schema and the document is left out (counted)",
        "first": "ISO day (Israel) of the person's first recorded visit; never pruned; anchors cohorts",
        "last": "ISO day of the last recorded visit",
        "pr": "(v2) 1 = the size cap dropped older weeks of this record",
        "w": "{week key: {ISO day: {session id: S}}}; v1 week key = ISO week '2026-W44', v2 week key = 'S' + ISO date of the Sunday 'S2026-10-25'",
    },
    "session": {
        "t": "opened at: v1 minutes since the epoch, (v2) hours since the epoch; not read by this report",
        "s": "active seconds (page visible and focused or with input within 60 s)",
        "vs": "(v2) visible seconds, whether or not focused",
        "g": "(v2) 1 = glance visit: visible 5 s or more, no input, under 30 s visible",
        "sec": "{section key: seconds}; section keys are SECTIONS plus 'top' = the headline tiles before the first section anchor (v2)",
        "nav": "{section key: clicks on the Section Strip and the skip links}",
        "l": "{section key or 'other': Jira link clicks (middle click included in v2)}",
        "o": "{disclosure key: opens}",
        "f": "{control key: changes}",
        "r": "Refresh presses", "rs": "Reset Filters presses", "np": "number of projects selected",
        "d": "width class 's' | 'm' | 'l'", "b": "page version (short commit)",
        "bt": "(v2) day number (days since the epoch, Israel day) of the build time of the page version",
        "lv": "(v2) 0 live, 1 snapshot only (no connector or Jira access declined), 2 live with a failed step",
        "fa": "(v2) data age bucket at the start of the visit: 0 under 1 h, 1 under 24 h, 2 under 72 h, 3 older",
        "ro": "(v2) {'ok': n, 'fail': n, 'declined': n} Refresh outcomes", "rt": "(v2) Refresh retries",
        "er": "uncaught errors (a count, never the message); in v2 real errors only", "erb": "(v2) benign notifications (ResizeObserver loop and similar), never flagged",
        "lf": "(v2) 1 = the visit started with a non-default filter", "rr": "(v2) 1 = Reset Filters pressed after at least one control change in the same visit",
        "x": "keys dropped by the 40-key cap",
    },
}
SESSION_KEYS = set(RECORD_SHAPE["session"])
RECORD_KEYS = set(RECORD_SHAPE["record"])
V2_MARKERS = ("vs", "bt", "fa", "lv")                                                 # written by every v2 session
KNOWN_SCHEMAS = (1, 2)

# The vocabularies the page records (program_dashboard/dashboard.template.html, USAGE_VOC) with the plain names a reader of this report knows, in the fixed page order.
# tests/test_usage_report.py keeps the keys equal to the page's.
SECTIONS = {"attn": "Needs Attention", "burnup": "Delivery", "eff": "Efficiency", "ai": "AI Adoption", "bugs": "Quality", "deps": "Dependencies", "nfr": "NFRs", "cx": "CXCROSS", "capview": "Capabilities", "cycles": "Cycles", "analysis": "Release Analysis"}
READ_SECTIONS = {"top": "Headline tiles", **SECTIONS}                                 # `sec` also has `top` (v2); first on the page
LINK_SECTIONS = {**SECTIONS, "other": "Outside a section"}
CONTROLS = {"release": "Release", "projects": "Projects", "multi": "Multi-select toggle", "teams": "Teams", "dc": "Delivery Cycle", "ax": "Accessibility Bugs", "cfb": "Customer-Found Bugs", "bugpri": "Bug priority",
            "gran": "Week, Month or Quarter", "cfbgrp": "Customer-found bugs grouping", "dp": "Dependencies view", "nfrtab": "NFR tabs", "cx": "CXCROSS commitment type", "caplevel": "Capability commitment level",
            "capby": "Capitalization grouping", "capmeasure": "Capitalization measure", "cycle": "Cycle choice", "cytab": "Cycles detail tab", "cystatus": "Cycles status filter", "cypods": "Pod lists"}
CONTROL_FAMILIES = [("Scope", ["release", "projects", "multi", "teams"]),
                    ("Delivery and cycles", ["dc", "gran", "cycle", "cytab", "cystatus", "cypods"]),
                    ("Quality", ["ax", "cfb", "bugpri", "cfbgrp"]),
                    ("Dependencies and NFRs", ["dp", "nfrtab"]),
                    ("Capabilities and CXCROSS", ["cx", "caplevel", "capby", "capmeasure"])]
DISCLOSURES = {"how": "How this is calculated", "data": "Show data", "attn": "Needs Attention details", "other": "Other details"}
DEVICES = {"s": "Small screen (up to 480 px)", "m": "Medium screen (up to 900 px)", "l": "Large screen"}
LV = {0: "live", 1: "snapshot only", 2: "live with a failed step"}
FA = {0: "under 1 hour old", 1: "1 to 24 hours old", 2: "1 to 3 days old", 3: "older than 3 days"}
RO = {"ok": "succeeded", "fail": "failed", "declined": "declined"}

WEEK_KEY_RX = re.compile(r"^(\d{4}-W\d{2}|S\d{4}-\d{2}-\d{2})$")
EPOCH = dt.date(1970, 1, 1)
WORKDAYS = (6, 0, 1, 2, 3)                                                            # Sunday to Thursday (date.weekday(): Monday 0 ... Sunday 6)
WEEKEND = (4, 5)                                                                      # Friday, Saturday


# ------------------------------------------------------------------------------------------------------------ time
def iso_week_key(d: dt.date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def week_start(d: dt.date) -> dt.date:
    """The Sunday that starts the Sunday-to-Saturday work week of day d."""
    return d - dt.timedelta(days=(d.weekday() + 1) % 7)


def sunday_key(d: dt.date) -> str:
    """The v2 week key of the week of day d."""
    return "S" + week_start(d).isoformat()


def is_complete(ws: dt.date, ref: dt.date) -> bool:
    """A week is complete once its Saturday has passed: the day `ref` (the day of the data) is on or after the next Sunday."""
    return ws + dt.timedelta(days=6) < ref


def d_label(d: dt.date) -> str:
    return f"{d.day} {d:%b}"


def week_label(ws: dt.date) -> str:
    return f"{d_label(ws)} to {d_label(ws + dt.timedelta(days=6))}"


def parse_day(v):
    try:
        return dt.date.fromisoformat(v) if isinstance(v, str) else None
    except ValueError:
        return None


# ------------------------------------------------------------------------------------------------------------ small numbers and the guards
def is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def rnd(x: float) -> int:
    return int(math.floor(x + 0.5))


def g(users: int, value):
    """The small-group guard: a figure resting on 1 to 4 distinct people is replaced by the text "<5 users" (an empty group is a plain 0: it points at nobody)."""
    return value if users == 0 or users >= MIN_USERS else SMALL


def gn(n: int):
    """A count of people: 0 and 5 or more print as they are, 1 to 4 print the guard."""
    return g(n, n)


def percentile(xs: list, p: float) -> float:
    xs = sorted(xs)
    if len(xs) == 1:
        return xs[0]
    k = (len(xs) - 1) * p
    lo, hi = math.floor(k), math.ceil(k)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def protect_group(cells: dict, relations: list, hidden=None) -> dict:
    """Withhold what a printed partition would reveal by subtraction.

    cells: {name: count of people}; relations: [(total, [names])]: each says "the cells listed add up to this printed total"; hidden: names that are already withheld (a cell of 1 to 4 people).
    A cell of 1 to 4 is withheld ("<5 users"). If a relation holds a withheld cell and total minus the printed cells of that relation is under 5, that difference IS the small group: the smallest printed cell of the relation
    is withheld as well (repeat until no relation leaks). Returns {name: count or SMALL}. A total that is itself 1 to 4 is guarded by its caller: its relation is skipped.
    """
    out_hidden = set(hidden or ()) | {k for k, v in cells.items() if 0 < v < MIN_USERS}
    changed = True
    while changed:
        changed = False
        for total, names in relations:
            if not (total == 0 or total >= MIN_USERS):
                continue
            mine = [n for n in names if n in cells]
            if not any(n in out_hidden for n in mine):
                continue
            rem = total - sum(cells[n] for n in mine if n not in out_hidden)
            if rem < MIN_USERS:
                vis = [n for n in mine if n not in out_hidden and cells[n] > 0]
                if vis:
                    out_hidden.add(min(vis, key=lambda n: cells[n]))
                    changed = True
    return {k: (SMALL if k in out_hidden else v) for k, v in cells.items()}


def protect_partition(cells: dict, total: int, hidden=None) -> dict:
    """protect_group for the common case: one partition and its total (the cells add up to the total)."""
    return protect_group(cells, [(total, list(cells))], hidden)


def robust_band(values: list, floor: float, min_n: int = 5, mult: float = 3.0):
    """The normal range of a weekly series: median +- max(mult x 1.4826 x MAD, floor). None below min_n values."""
    if len(values) < min_n:
        return None
    m = statistics.median(values)
    mad = statistics.median(abs(v - m) for v in values)
    half = max(mult * 1.4826 * mad, floor)
    return {"median": m, "lo": m - half, "hi": m + half, "half": half, "mad": mad, "n": len(values), "min": min(values), "max": max(values)}


def pct_of(x: int, d: int, th=THRESHOLDS):
    """A rounded percentage, or None when the denominator is under the minimum (then the counts are printed with n=)."""
    return rnd(100 * x / d) if d >= th["min_den"] and d > 0 else None


# ------------------------------------------------------------------------------------------------------------ loading
def _unwrap(raw) -> list:
    if isinstance(raw, dict):
        for k in ("documents", "docs", "items", "rows", "results"):
            if isinstance(raw.get(k), list):
                return raw[k]
        raise ValueError("expected a list of documents (or an object with a list under documents, docs, items, rows or results)")
    if not isinstance(raw, list):
        raise ValueError("expected a list of documents")
    return raw


def _doc_id(row: dict, body: dict):
    for src in (body, row):
        for k in ("u", "id", "doc_id"):
            v = src.get(k)
            if isinstance(v, str) and v:
                return v
    return None


def _n_sessions(body: dict) -> int:
    return sum(len(s or {}) for days in (body.get("w") or {}).values() if isinstance(days, dict) for s in days.values() if isinstance(s, dict))


def load_export(raw) -> tuple:
    """(bodies, stats): the record bodies of an export (a list of bodies, a list of {id, data} rows, or an object wrapping such a list), a duplicated document dropped
    (its id is hashed in memory to compare and then forgotten, never printed), rows without the record shape skipped and documents with an unknown schema left out; all counted in stats."""
    rows = _unwrap(raw)
    stats = {"read": len(rows), "skipped": 0, "duplicates": 0, "unknown_schema": 0, "no_id": 0, "round_page": len(rows) in (100, 500, 1000)}
    out, seen = [], {}
    for row in rows:
        if not isinstance(row, dict):
            stats["skipped"] += 1
            continue
        body = row["data"] if isinstance(row.get("data"), dict) and ("w" not in row or "id" in row or "doc_id" in row) else row
        if not isinstance(body.get("w"), dict):
            stats["skipped"] += 1
            continue
        v = body.get("v")
        if isinstance(v, bool) or v not in KNOWN_SCHEMAS:
            stats["unknown_schema"] += 1
            continue
        did = _doc_id(row, body)
        if did is None:
            stats["no_id"] += 1
        else:
            key = hashlib.sha256(did.encode("utf-8")).hexdigest()
            if key in seen:
                stats["duplicates"] += 1
                i = seen[key]
                if (str(body.get("last") or ""), _n_sessions(body)) > (str(out[i].get("last") or ""), _n_sessions(out[i])):      # keep the fuller copy
                    out[i] = body
                continue
            seen[key] = len(out)
        out.append(body)
    return out, stats


def load_bodies(raw) -> list:
    """The record bodies of an export (see load_export)."""
    return load_export(raw)[0]


def is_v2(s: dict) -> bool:
    return any(k in s for k in V2_MARKERS)


def sessions_of(bodies: list) -> list:
    """One row per session: {u: position of the person in the file, day: date, week: week key, s: the session body, v2: bool}. Rows that do not parse are skipped."""
    rows = []
    for u, b in enumerate(bodies):
        for wk, days in (b.get("w") or {}).items():
            if not isinstance(days, dict):
                continue
            for day, sess in days.items():
                d = parse_day(day)
                if d is None:
                    continue
                for sid, s in (sess or {}).items():
                    if isinstance(s, dict):
                        rows.append({"u": u, "day": d, "week": wk, "s": s, "v2": is_v2(s)})
    return rows


# ------------------------------------------------------------------------------------------------------------ the calendar (optional)
def parse_calendar(raw) -> dict:
    """The calendar file written by `build_dashboard.py --emit-usage-calendar` (dates and release and sprint numbers only), optionally with the owner's `events` (review days: only the dates are read, a label is never printed)
    and `quiet_weeks` (dates inside weeks to leave out of every baseline). Returns {releases, sprints, events, quiet_weeks, warnings} with dates as date objects; a malformed entry is skipped and noted."""
    cal = {"releases": [], "sprints": [], "events": [], "quiet_weeks": [], "warnings": []}
    if not isinstance(raw, dict):
        raise ValueError("the calendar must be a JSON object")
    for r in raw.get("releases") or []:
        w1, w6, end = (parse_day(r.get(k)) if isinstance(r, dict) else None for k in ("w1", "w6_end", "end"))
        if not (w1 and w6 and end):
            cal["warnings"].append("a release entry of the calendar was skipped (dates missing)")
            continue
        if w6 != w1 + dt.timedelta(days=41):
            cal["warnings"].append(f"the calendar says the end of W6 is {w6}, but W1 + 41 days is {w1 + dt.timedelta(days=41)}: the calendar is not the dashboard's own definition")
        cal["releases"].append({"release": str(r.get("release", ""))[:12], "w1": w1, "w6_end": w6, "end": end})
    for s in raw.get("sprints") or []:
        a, b = (parse_day(s.get(k)) if isinstance(s, dict) else None for k in ("start", "end"))
        if a and b:
            cal["sprints"].append({"no": s.get("no"), "start": a, "end": b})
    for k, dst in (("events", "events"), ("quiet_weeks", "quiet_weeks")):
        for x in raw.get(k) or []:
            d = parse_day(x.get("date") if isinstance(x, dict) else x)
            if d:
                cal[dst].append(d)
    return cal


# ------------------------------------------------------------------------------------------------------------ the model: every row of the data window, organised by Sunday-start week
class Model:
    """The sessions of one export, cut to the data window and organised for the signals and the views.

    ref: the day of the data (the export day); weeks are complete once their Saturday has passed on `ref`. Sessions older than the 12 weeks the page keeps, newer than ref, or before `since` (the go-live day) are not used and are counted in .counts.
    People are told apart by their position in the file; `first_seen` is the first day of a person (the record's `first`, never earlier than `since`).
    """

    def __init__(self, bodies: list, ref: dt.date, since: dt.date | None = None, calendar: dict | None = None, th: dict | None = None):
        self.th = th or THRESHOLDS
        self.ref, self.since, self.cal = ref, since, calendar
        self.cur = week_start(ref)                                                      # the week in progress
        self.last = self.cur - dt.timedelta(days=7)                                     # the last completed week
        self.cutoff = self.cur - dt.timedelta(days=7 * (self.th["retention_weeks"] - 1))
        self.quiet = {week_start(d) for d in (calendar or {}).get("quiet_weeks", [])}
        self.counts = {"stale_sessions": 0, "future_sessions": 0, "before_since": 0, "bad_week_key": 0}
        rows = []
        for r in sessions_of(bodies):
            if not WEEK_KEY_RX.match(str(r["week"])):
                self.counts["bad_week_key"] += 1
            elif r["day"] > ref:
                self.counts["future_sessions"] += 1
            elif r["day"] < self.cutoff:
                self.counts["stale_sessions"] += 1
            elif since and r["day"] < since:
                self.counts["before_since"] += 1
            else:
                r["ws"] = week_start(r["day"])
                r["glance"] = r["s"].get("g") == 1
                rows.append(r)
        self.rows = rows
        self.by_week = defaultdict(list)
        for r in rows:
            self.by_week[r["ws"]].append(r)
        self.people = sorted({r["u"] for r in rows})
        earliest: dict = {}
        for r in rows:
            if r["u"] not in earliest or r["day"] < earliest[r["u"]]:
                earliest[r["u"]] = r["day"]
        self.first_seen, self.pre_golive = {}, set()
        for u in self.people:
            real = min(parse_day(bodies[u].get("first")) or earliest[u], earliest[u])
            if since and real < since:
                self.pre_golive.add(u)
            self.first_seen[u] = min(max(real, since) if since else real, earliest[u])
        self.first_real = {u: min(parse_day(bodies[u].get("first")) or earliest[u], earliest[u]) for u in self.people}
        self.first_day = min((r["day"] for r in rows), default=None)
        self.last_day = max((r["day"] for r in rows), default=None)
        start = max(since, self.cutoff) if since else self.first_day
        self.data_start = start
        self.first_week = week_start(start) if start else None
        self.provisional_first = bool(start and start > self.first_week)
        self.weeks = []                                                                 # the completed weeks from the first week of data
        if self.first_week:
            w = self.first_week
            while w <= self.last:
                self.weeks.append(w)
                w += dt.timedelta(days=7)
        self.n_bodies = len(bodies)
        cut = ref - dt.timedelta(days=7 * self.th["retention_weeks"])
        self.stale_records = sum(1 for b in bodies if (parse_day(b.get("last")) or dt.date.min) < cut)
        self.pruned_records = sum(1 for b in bodies if b.get("pr") == 1)
        self._memo: dict = {}
        v2_weeks = sorted(w for w, rs in self.by_week.items() if any(r["v2"] for r in rs))
        v1_before = bool(v2_weeks) and any(w < v2_weeks[0] and any(not r["v2"] for r in rs) for w, rs in self.by_week.items())
        self.rollover = v2_weeks[0] if v1_before else None                              # the first week of the new recording rules: it mixes both

    # -- weeks
    def is_prov(self, ws: dt.date) -> bool:
        return self.provisional_first and ws == self.first_week

    def usable(self, ws: dt.date) -> bool:
        """A week a change statement may use: completed, inside the data, not the provisional first week."""
        return self.first_week is not None and self.first_week <= ws <= self.last and not self.is_prov(ws)

    def n_full_weeks(self) -> int:
        return sum(1 for w in self.weeks if not self.is_prov(w))

    def regime(self, ws: dt.date):
        rs = self.by_week.get(ws)
        return None if not rs else ("v2" if any(r["v2"] for r in rs) else "v1")

    def baseline(self, ws: dt.date, den_fn=None) -> list:
        """The comparable completed weeks among the baseline_weeks before ws: not the provisional first week, not a quiet week, the same recording rules (a rollover week is left out), and (den_fn) with enough people."""
        out = []
        mine = self.regime(ws) or "v2"
        for i in range(1, self.th["baseline_weeks"] + 1):
            w = ws - dt.timedelta(days=7 * i)
            if self.first_week is None or w < self.first_week:
                break
            rg = self.regime(w)
            if self.is_prov(w) or w in self.quiet or (rg is not None and rg != mine) or (w == self.rollover and mine == "v2"):
                continue
            if den_fn and den_fn(w) < self.th["min_den"]:
                continue
            out.append(w)
        return sorted(out)

    # -- people per week
    def visits(self, ws):
        return self.by_week.get(ws, [])

    def active(self, ws) -> set:
        k = ("act", ws)
        if k not in self._memo:
            self._memo[k] = {r["u"] for r in self.by_week.get(ws, [])}
        return self._memo[k]

    def new(self, ws) -> set:
        return {u for u in self.active(ws) if self.first_seen[u] >= ws}

    def established(self, ws) -> set:
        cut = ws - dt.timedelta(days=self.th["established_days"])
        return {u for u in self.active(ws) if self.first_seen[u] <= cut}

    def secs(self, ws) -> dict:
        """{person: {section: seconds in the week}}"""
        k = ("secs", ws)
        if k not in self._memo:
            out: dict = defaultdict(lambda: defaultdict(float))
            for r in self.by_week.get(ws, []):
                for key, v in (r["s"].get("sec") or {}).items():
                    if key in READ_SECTIONS and is_num(v) and v > 0:
                        out[r["u"]][key] += v
            self._memo[k] = out
        return self._memo[k]

    def ctl(self, ws) -> dict:
        """{control: set of the people that changed it in the week}"""
        k = ("ctl", ws)
        if k not in self._memo:
            out: dict = defaultdict(set)
            for r in self.by_week.get(ws, []):
                for key, v in (r["s"].get("f") or {}).items():
                    if key in CONTROLS and is_num(v) and v > 0:
                        out[key].add(r["u"])
            self._memo[k] = out
        return self._memo[k]

    def readers(self, ws, key, among: set) -> int:
        s = self.secs(ws)
        return sum(1 for u in among if s.get(u, {}).get(key, 0) >= SECTION_MIN_SECONDS)

    def users_of_control(self, ws, key, among: set) -> int:
        return len(self.ctl(ws).get(key, set()) & among)

    # -- visits
    @staticmethod
    def engaged(r) -> bool:
        return not r["glance"]


# ------------------------------------------------------------------------------------------------------------ small helpers for the views and the signals
CONFIDENCE = ("Confirmed", "Corroborated", "Single-source", "Weak signal", "Unknown")


def gm(x) -> str:
    """A median or a baseline figure for print: rounded, and the guard text when it is a small group size."""
    v = rnd(x)
    return SMALL if 0 < v < MIN_USERS else str(v)


def nlabel(v) -> str:
    """'n=40', or the words for a count that is withheld because fewer than 5 people are behind it."""
    return f"n={v}" if v != SMALL else "count withheld: fewer than 5 people"


def fmt_n(v) -> str:
    return v if v == SMALL else ("-" if v is None else f"{v:,}" if isinstance(v, int) else f"{v}")


def share_text(x, d: int, th=THRESHOLDS) -> str:
    """'34%' when the denominator allows a percentage (at least min_den), else the count with n=, and the guard text for a small group."""
    if x == SMALL:
        return SMALL
    if d == SMALL:
        return str(x)
    p = pct_of(x, d, th)
    return f"{p}%" if p is not None else f"{x} (n={d})"


def partition_cells(groups: dict) -> dict:
    """groups: {name: (set of people, count of visits)}: disjoint groups of visits. Returns {name: count or SMALL}: a group of 1 to 4 people is withheld, and so is a cell a printed total would reveal by subtraction."""
    cells = {k: c for k, (p, c) in groups.items()}
    hidden = {k for k, (p, c) in groups.items() if 0 < len(p) < MIN_USERS}
    return protect_partition(cells, sum(cells.values()), hidden)


def window_weeks(m: Model) -> list:
    """The analysis window of the views: the last window_weeks completed weeks (fewer while the data is young), a provisional first week included."""
    k = m.th["window_weeks"]
    return m.weeks[-k:] if m.weeks else []


def _confidence(weeks_seen: int, active: int, th: dict, soft: bool = False) -> str:
    if weeks_seen >= 3:
        return "Confirmed"
    if weeks_seen == 2:
        return "Corroborated"
    return "Weak signal" if (active < th["weak_active_people"] or soft) else "Single-source"


def _persist(m: Model, ws, fn) -> int:
    """How many consecutive completed weeks ending at ws (at most 3) show the same flagged change in the same direction."""
    r0 = fn(ws)
    if not r0.get("fired"):
        return 0
    n = 1
    for i in (1, 2):
        w = ws - dt.timedelta(days=7 * i)
        if not m.usable(w):
            break
        r = fn(w)
        if r.get("fired") and r.get("dir") == r0["dir"]:
            n += 1
        else:
            break
    return n


def _eval_count(m: Model, ws, series, up_only: bool = False, min_cur=None) -> dict:
    """A weekly count against the normal range of the comparable weeks before it."""
    th = m.th
    bw = m.baseline(ws)
    if len(bw) < th["baseline_min"]:
        return {"state": "building", "n": len(bw), "cur": series(ws)}
    vals = [series(w) for w in bw]
    med = statistics.median(vals)
    b = robust_band(vals, max(th["floor_people_abs"], th["floor_people_rel"] * med), th["baseline_min"], th["band_mad"])
    cur = series(ws)
    change = cur - b["median"]
    outside = cur > b["hi"] or (not up_only and cur < b["lo"])
    material = abs(change) >= max(th["change_people_abs"], th["change_people_rel"] * b["median"])
    fired = outside and material and (min_cur is None or cur >= min_cur)
    return {"state": "ok", "cur": cur, "band": b, "change": change, "fired": fired, "dir": 1 if change > 0 else -1, "outside": outside, "weeks": bw}


def _eval_reach(m: Model, ws, kind: str, key: str) -> dict:
    """The reach (people with the section 30 s or more that week, or people who changed the control) among the established active people, against the comparable weeks before."""
    th = m.th

    def val(w):
        est = m.established(w)
        return (m.readers(w, key, est) if kind == "sec" else m.users_of_control(w, key, est)), len(est)
    n_now = len(m.established(ws))
    if n_now < th["min_den"]:
        return {"state": "few", "n": n_now}
    bw = m.baseline(ws, den_fn=lambda w: len(m.established(w)))
    if len(bw) < th["baseline_min"]:
        return {"state": "building", "n": len(bw)}
    ser = [val(w) for w in bw]
    pcts = [100 * x / n for x, n in ser]
    if kind == "sec" and sum(1 for x, _ in ser if x >= MIN_USERS) < max(th["s3_baseline_weeks_with_readers"], math.ceil(0.8 * len(bw))):
        return {"state": "sparse", "n": len(bw)}
    x, n = val(ws)
    b = robust_band(pcts, th["floor_reach_pp"], th["baseline_min"], th["band_mad"])
    pct = 100 * x / n
    change = pct - b["median"]
    if 0 < x < MIN_USERS:
        return {"state": "unknown", "x": x, "n": n, "pct": pct, "band": b}
    fired = (pct > b["hi"] or pct < b["lo"]) and abs(change) >= th["change_reach_pp"]
    return {"state": "ok", "x": x, "n": n, "pct": pct, "band": b, "change": change, "fired": fired, "dir": 1 if change > 0 else -1, "weeks": bw}


def _eval_control_event(m: Model, ws, key: str) -> dict:
    """S4: a control newly used (baseline under 5 people every week, now 5 or more and 10% or more) or no longer used (10% or more in 4 of the 5 baseline weeks, then under 5 in two consecutive weeks)."""
    th = m.th
    prev = ws - dt.timedelta(days=7)

    def val(w):
        est = m.established(w)
        return m.users_of_control(w, key, est), len(est)
    if len(m.established(ws)) < th["min_den"]:
        return {"state": "few", "n": len(m.established(ws))}
    bw = m.baseline(ws, den_fn=lambda w: len(m.established(w)))
    if len(bw) < th["baseline_min"]:
        return {"state": "building", "n": len(bw)}
    x, n = val(ws)
    ser = {w: val(w) for w in bw}
    if all(v[0] < MIN_USERS for v in ser.values()) and x >= MIN_USERS and 100 * x / n >= th["s4_new_pct"]:
        return {"state": "ok", "fired": True, "dir": 1, "kind": "new", "x": x, "n": n}
    if m.usable(prev):
        px, pn = val(prev)
        base = [w for w in bw if w != prev]
        if pn >= th["min_den"] and sum(1 for w in base if 100 * ser[w][0] / ser[w][1] >= th["s4_stop_pct"]) >= th["s4_stop_weeks"] and px < MIN_USERS and x < MIN_USERS:
            return {"state": "ok", "fired": True, "dir": -1, "kind": "stopped", "x": x, "n": n}
    return {"state": "ok", "fired": False, "x": x, "n": n}


# ------------------------------------------------------------------------------------------------------------ the signals S0 to S9
def detect_signals(m: Model, ctx: dict | None = None) -> dict:
    """What changed in the last completed week against the comparable weeks before it. Returns
    {compared: {...} or None, flagged: [signal records], ledger: [{id, name, status, text}] (every signal: flagged / within / not_tested / unknown), tested: [names], not_tested: [(name, reason)], cap_hidden: n}.
    A signal record: id, name, headline, observation (with n), baseline (with the number of weeks), threshold, confidence, not_show, next. Wording rule: only 'coincides with', 'is associated with', 'worth investigating'.
    ctx: {export_age_days, stats (load_export stats), stale_records, pruned_records} for S7; None leaves S7 untested."""
    th = m.th
    L = m.last
    out = {"compared": None, "flagged": [], "ledger": [], "tested": [], "not_tested": [], "cap_hidden": 0}
    led = lambda i, name, status, text: out["ledger"].append({"id": i, "name": name, "status": status, "text": text})
    SIG = lambda i, name, headline, obs, base, thr, conf, nshow, nxt: out["flagged"].append(
        {"id": i, "name": name, "headline": headline, "observation": obs, "baseline": base, "threshold": thr, "confidence": conf, "not_show": nshow, "next": nxt})

    def untested(i, name, reason):
        led(i, name, "not_tested", reason)
        out["not_tested"].append((name, reason))

    if not m.usable(L):
        why = "no completed week of data yet" if not m.weeks else "the only completed week is the first week of data, which starts mid-week and is provisional"
        for i, name in (("S0", "Weekly active people"), ("S1", "New active people"), ("S2", "Lapsed regular people"), ("S3", "Section reach"), ("S4", "Controls newly used or no longer used"),
                        ("S5", "Page errors"), ("S6", "Published-version split"), ("S8", "Snapshot-only visits"), ("S9", "Stale data seen")):
            untested(i, name, why)
        _s7(m, ctx, out, led, SIG, untested)
        return out
    act = m.active(L)
    n_act = len(act)
    est = m.established(L)
    out["compared"] = {"ws": L, "label": week_label(L), "active": gn(n_act), "raw_active": n_act, "established": len(est)}
    nb_all = len(m.baseline(L))
    out["compared"]["baseline_weeks"] = nb_all
    wk = week_label(L)

    # ---- S0 weekly active people
    ev = _eval_count(m, L, lambda w: len(m.active(w)))
    name = "Weekly active people"
    if ev["state"] == "building":
        untested("S0", name, f"baseline building ({ev['n']} of {th['baseline_min']} comparable weeks)")
    elif 0 < ev["cur"] < MIN_USERS:
        led("S0", name, "unknown", f"{SMALL} active in the compared week: Unknown")
        out["tested"].append(name)
    else:
        out["tested"].append(name)
        b = ev["band"]
        txt = f"{ev['cur']} people active; usual {gm(b['median'])} (normal range {gm(max(0, b['lo']))} to {gm(b['hi'])}, {b['n']} weeks)"
        if ev["fired"]:
            seen = _persist(m, L, lambda w: _eval_count(m, w, lambda x: len(m.active(x))))
            more = ev["dir"] > 0
            led("S0", name, "flagged", txt)
            SIG("S0", name, f"{'More' if more else 'Fewer'} people were active than usual", f"{ev['cur']} people were active in {wk}, against a usual {gm(b['median'])}.",
                f"Median of the {b['n']} comparable completed weeks before: {gm(b['median'])}; normal range {gm(max(0, b['lo']))} to {gm(b['hi'])}.",
                f"Outside the range and at least {max(th['change_people_abs'], rnd(th['change_people_rel'] * b['median']))} people ({rnd(100 * th['change_people_rel'])}%) from the median.",
                _confidence(seen, n_act, th), "The reason for the change: the count says nothing about any person or about what lies behind it. Visits are not counted here.",
                "Worth investigating: whether a message, a review meeting or a release milestone coincides with the change (see the calendar notes), and whether the change is in new or in established people (S1).")
        else:
            led("S0", name, "within", txt)

    # ---- S1 new active people
    ev = _eval_count(m, L, lambda w: len(m.new(w)), up_only=True, min_cur=th["s1_min_new"])
    name = "New active people"
    if ev["state"] == "building":
        untested("S1", name, f"baseline building ({ev['n']} of {th['baseline_min']} comparable weeks)")
    else:
        out["tested"].append(name)
        b = ev["band"]
        usual = f"usual {gm(b['median'])} (normal range up to {gm(b['hi'])}, {b['n']} weeks)" if rnd(b["hi"]) >= MIN_USERS and rnd(b["median"]) != 0 and rnd(b["median"]) >= MIN_USERS else f"usually under {MIN_USERS} a week ({b['n']} weeks)"
        txt = f"{gn(ev['cur'])} new; {usual}"
        if ev["fired"]:
            seen = _persist(m, L, lambda w: _eval_count(m, w, lambda x: len(m.new(x)), up_only=True, min_cur=th["s1_min_new"]))
            led("S1", name, "flagged", txt)
            SIG("S1", name, "More new people than usual", f"{ev['cur']} people were seen for the first time in {wk}, against a usual {gm(b['median']) if rnd(b['median']) >= MIN_USERS else 'under ' + str(MIN_USERS)}.",
                f"Median of the {b['n']} comparable completed weeks before: {gm(b['median']) if rnd(b['median']) >= MIN_USERS else 'under ' + str(MIN_USERS)}; upper end of the range {gm(b['hi']) if rnd(b['hi']) >= MIN_USERS else 'under ' + str(MIN_USERS)}.", f"At least {th['s1_min_new']} new people and above the range (increases only).",
                _confidence(seen, n_act, th), "Whether they come back: new people are reported separately from established people and are not in the reach or control signals.",
                "Worth investigating: whether an announcement or a change of the audience coincides with the new people; the cohort retention view shows whether they return.")
        else:
            led("S1", name, "within", txt)

    # ---- S2 lapsed regular people (aggregate only)
    name = "Lapsed regular people"
    k_full = sum(1 for w in m.weeks if not m.is_prov(w))
    if k_full < th["s2_weeks_needed"]:
        untested("S2", name, f"needs {th['s2_weeks_needed']} completed weeks, has {k_full}")
    else:
        out["tested"].append(name)

        def eval_s2(ws):
            if not all(m.usable(ws - dt.timedelta(days=7 * i)) for i in range(0, 7)):
                return {"fired": False}
            base = [ws - dt.timedelta(days=7 * i) for i in (6, 5, 4, 3)]
            regs = {u for u in m.people if sum(1 for w in base if u in m.active(w)) >= th["s2_regular_weeks"]}
            recent = [ws - dt.timedelta(days=7 * i) for i in (2, 1, 0)]
            lapsed = {u for u in regs if not any(u in m.active(w) for w in recent)}
            fired = len(regs) >= th["s2_min_regulars"] and len(lapsed) >= th["s2_min_lapsed"] and len(lapsed) >= th["s2_lapsed_share"] * len(regs)
            return {"fired": fired, "dir": -1, "regs": len(regs), "lapsed": len(lapsed)}
        r = eval_s2(L)
        txt = f"{gn(r['regs'])} regular people, {gn(r['lapsed'])} of them lapsed" if r["regs"] >= th["s2_min_regulars"] else f"fewer than {th['s2_min_regulars']} regular people: not enough to judge"
        if r["fired"]:
            seen = _persist(m, L, eval_s2)
            pc = protect_partition({"lapsed": r["lapsed"], "still": r["regs"] - r["lapsed"]}, r["regs"])
            led("S2", name, "flagged", txt)
            if pc["lapsed"] == SMALL:
                obs = f"A group of the {r['regs']} regular people has stopped visiting; its size is withheld because the remaining count would reveal a group under {MIN_USERS} people."
            else:
                obs = f"{r['lapsed']} of {r['regs']} regular people ({share_text(r['lapsed'], r['regs'], th)}) have not visited in the last 3 completed weeks."
            SIG("S2", name, "Regular people have stopped visiting", obs,
                f"Regular = active in {th['s2_regular_weeks']} of the 4 completed weeks from {d_label(L - dt.timedelta(days=42))} to {d_label(L - dt.timedelta(days=21) + dt.timedelta(days=6))}; lapsed = regular with no visit in the 3 weeks since.",
                f"At least {th['s2_min_regulars']} regulars, {th['s2_min_lapsed']} lapsed and {rnd(100 * th['s2_lapsed_share'])}% of the regulars.", _confidence(seen, n_act, th),
                "Whether they stopped for good, use another source or were away; the count is an aggregate and says nothing about any person.",
                "Worth investigating: whether a change of the audience, of the page or of a review routine coincides with the drop.")
        else:
            led("S2", name, "within", txt)

    # ---- S3 section reach, S4 controls
    th_min = th["min_den"]
    s3_flag, s3_n, s3_skip, s4_flag, s4_n, s4_skip = [], 0, defaultdict(int), [], 0, defaultdict(int)
    for key, nm in READ_SECTIONS.items():
        ev = _eval_reach(m, L, "sec", key)
        if ev["state"] in ("few", "building", "sparse"):
            s3_skip[ev["state"]] += 1
            continue
        s3_n += 1
        if ev["state"] == "ok" and ev["fired"]:
            seen = _persist(m, L, lambda w, key=key: _eval_reach(m, w, "sec", key))
            s3_flag.append((abs(ev["change"]), key, nm, ev, seen))
    for key, nm in CONTROLS.items():
        ev = _eval_control_event(m, L, key)
        if ev["state"] in ("few", "building"):
            s4_skip[ev["state"]] += 1
            continue
        s4_n += 1
        if ev["fired"]:
            seen = _persist(m, L, lambda w, key=key: _eval_control_event(m, w, key))
            s4_flag.append((ev["n"], key, nm, ev, seen))
    for i, name, n_t, skip, flagged_n in (("S3", "Section reach", s3_n, s3_skip, len(s3_flag)), ("S4", "Controls newly used or no longer used", s4_n, s4_skip, len(s4_flag))):
        unit = "sections" if i == "S3" else "controls"
        if n_t == 0:
            reason = ("too few active people (n=%d, needs %d)" % (len(est), th_min)) if skip.get("few") else (f"baseline building (fewer than {th['baseline_min']} comparable weeks)" if skip.get("building") else "baseline weeks had too few readers")
            untested(i, name, reason)
        else:
            out["tested"].append(name)
            extra = ""
            if skip:
                extra = "; not tested: " + ", ".join(f"{v} ({'too few readers in the baseline' if k == 'sparse' else k})" for k, v in skip.items())
            led(i, name, "flagged" if flagged_n else "within", f"{n_t} {unit} tested, {flagged_n} flagged{extra}")
    items = sorted(s3_flag, key=lambda t: -t[0])
    for _, key, nm, ev, seen in items:
        b = ev["band"]
        up = ev["dir"] > 0
        SIG("S3", f"Reach of {nm}", f"More people read {nm}" if up else f"Fewer people read {nm}",
            f"Reach {share_text(ev['x'], ev['n'], th)} of established active people in {wk} ({ev['x']} of n={ev['n']}), against a usual {rnd(b['median'])}%.",
            f"Median reach of the {b['n']} comparable completed weeks before: {rnd(b['median'])}% (normal range {rnd(max(0, b['lo']))}% to {rnd(min(100, b['hi']))}%).",
            f"Outside the range and at least {th['change_reach_pp']} percentage points from the median; reach = people with {SECTION_MIN_SECONDS} s or more in the section that week, among established people.",
            _confidence(seen, ev["n"], th),
            "Whether the section was useful: reach counts the people with time in it. A section can be read by few people on purpose. Scroll position decides which section gets the time.",
            "Worth investigating: whether a change of the page, a release milestone or a review routine coincides with the change in reach.")
    for n_, key, nm, ev, seen in sorted(s4_flag, key=lambda t: (-t[0], t[1])):
        new = ev["kind"] == "new"
        SIG("S4", f"Control: {nm}", f"{nm} is newly used" if new else f"{nm} is no longer used",
            (f"{ev['x']} established people ({share_text(ev['x'], ev['n'], th)}) changed this control in {wk}; in the {len(m.baseline(L))} weeks before, fewer than {MIN_USERS} people did."
             if new else f"Fewer than {MIN_USERS} established people changed this control in each of the last 2 completed weeks."),
            "Newly used: under 5 people in every comparable week before." if new else f"Stopped: {th['s4_stop_pct']}% or more of established people in {th['s4_stop_weeks']} of the baseline weeks.",
            f"Newly used: {MIN_USERS} or more people and {th['s4_new_pct']}% or more. Stopped: under {MIN_USERS} people in {th['s4_stop_consecutive']} consecutive weeks.", _confidence(seen, ev["n"], th),
            "Whether the control works or is wanted: a change counts the people that touched it, not the effect.",
            "Worth investigating: whether a change of the page or a new routine coincides with the change in use; the control may have moved or been renamed.")

    # ---- S5 page errors
    name = "Page errors"
    out["tested"].append(name)

    def eval_err(ws):
        rs = m.visits(ws)
        er = [r for r in rs if is_num(r["s"].get("er")) and r["s"]["er"] > 0]
        people = len({r["u"] for r in er})
        prev_b = {r["s"].get("b") for r in m.visits(ws - dt.timedelta(days=7)) if is_num(r["s"].get("er")) and r["s"]["er"] > 0 and isinstance(r["s"].get("b"), str)} if m.usable(ws - dt.timedelta(days=7)) else set()
        now_b = {r["s"].get("b") for r in er if isinstance(r["s"].get("b"), str)}
        a = people >= th["err_people"]
        b2 = bool(er) and len(rs) >= th["err_visit_min"] and len(er) >= th["err_visit_share"] * len(rs)
        c = bool(now_b & prev_b)
        return {"fired": a or b2 or c, "dir": 1, "people": people, "visits": len(er), "n": len(rs), "rules": [x for x, ok in (("people", a), ("share", b2), ("build", c)) if ok], "all_v1": bool(er) and not any(r["v2"] for r in er)}
    r = eval_err(L)
    recent = [x for x in m.rows if x["day"] >= m.ref - dt.timedelta(days=th["err_quiet_days"] - 1) and is_num(x["s"].get("er")) and x["s"]["er"] > 0]
    older = [x for x in m.rows if x["day"] < m.ref - dt.timedelta(days=th["err_quiet_days"] - 1) and is_num(x["s"].get("er")) and x["s"]["er"] > 0]
    hist = ""
    if older:
        ou = len({x["u"] for x in older})
        hist = f" Earlier in the data: errors were recorded for {cnt(gn(ou), 'users')}."
    if r["fired"]:
        seen = _persist(m, L, eval_err)
        led("S5", name, "flagged", f"{cnt(g(r['people'], r['visits']), 'visits')} with an error by {cnt(gn(r['people']), 'users')} in the compared week")
        why = {"people": f"{th['err_people']} or more people had an error", "share": f"{rnd(100 * th['err_visit_share'])}% or more of the visits had an error", "build": "the same page version had an error in two consecutive weeks"}
        SIG("S5", name, "Page errors need a look", f"{cnt(g(r['people'], r['visits']), 'visits')} ended with an uncaught error in {wk} ({cnt(gn(r['people']), 'users')}); " + "; ".join(why[k] for k in r["rules"]) + ".",
            f"Last completed week; errors in the last {th['err_quiet_days']} days: {cnt(g(len({x['u'] for x in recent}), len(recent)), 'visits')}.",
            f"{th['err_people']} or more people, or {rnd(100 * th['err_visit_share'])}% or more of the visits (at least {th['err_visit_min']} visits), or the same page version in {th['err_consecutive_weeks']} consecutive weeks.",
            _confidence(seen, n_act, th, soft=r["all_v1"]),
            "What the error was: the page records a count, never the message. In v1 records the count may include harmless browser notifications.",
            "Worth investigating: open the published page with the browser's developer console and compare with the page version that coincides with the errors.")
    else:
        if recent:
            ru = len({x["u"] for x in recent})
            led("S5", name, "within", f"{cnt(g(ru, len(recent)), 'visits')} with an error in the last {th['err_quiet_days']} days ({cnt(gn(ru), 'users')}): below the flag threshold." + hist)
        else:
            led("S5", name, "within", f"none in the last {th['err_quiet_days']} days." + hist)

    # ---- S6 published-version split
    name = "Published-version split"
    rows_bt = [x for x in m.visits(L) if is_num(x["s"].get("bt"))]
    all_bt = [x["s"]["bt"] for x in m.rows if is_num(x["s"].get("bt"))]
    if not rows_bt:
        untested("S6", name, "field not recorded in v1: version order unknown; counts only")
    else:
        latest: dict = {}
        for x in rows_bt:
            latest[x["u"]] = max(latest.get(x["u"], x["s"]["bt"]), x["s"]["bt"])
        newest = max(all_bt)
        n6 = len(latest)
        if n6 < th["min_den"]:
            untested("S6", name, f"too few active people (n={n6}, needs {th['min_den']})")
        else:
            out["tested"].append(name)
            stale = sum(1 for v in latest.values() if newest - v > th["s6_age_days"])
            pc = protect_partition({"old": stale, "new": n6 - stale}, n6)
            if pc["old"] == SMALL:
                led("S6", name, "unknown" if stale else "within", f"{SMALL} on an older published version" if stale else "no one on a version more than 7 days older than the newest")
            else:
                txt = f"{stale} of {n6} people on a version more than {th['s6_age_days']} days older than the newest ({share_text(stale, n6, th)})"
                if stale >= th["s6_min_people"] and stale >= th["s6_min_share"] * n6:
                    led("S6", name, "flagged", txt)
                    SIG("S6", name, "Some people are on an older published version", txt + ".", f"Compared with the newest page version seen in the data (build day {newest}).",
                        f"{th['s6_min_people']} or more people and {rnd(100 * th['s6_min_share'])}% or more of the people active in the week.", _confidence(1, n_act, th),
                        "Why they are on it: a tab left open for days or an old link is associated with it, but the data cannot tell.", "Worth investigating: whether the page is republished while people keep an old tab open, and whether that coincides with other signals.")
                else:
                    led("S6", name, "within", txt)

    # ---- S7 data coverage
    _s7(m, ctx, out, led, SIG, untested)

    # ---- S8 snapshot-only visits, S9 stale data seen
    v2 = [x for x in m.visits(L) if x["v2"]]
    for i, name, key, vals, share_min, people_min, txtname in (("S8", "Snapshot-only visits", "lv", (1,), th["s8_share"], th["s8_min_people"], "snapshot only (no live connection)"),
                                                              ("S9", "Stale data seen", "fa", (2, 3), th["s9_share"], 0, "data older than 24 hours at the start")):
        have = [x for x in v2 if is_num(x["s"].get(key))]
        if not have:
            untested(i, name, "field not recorded in v1")
            continue
        if len(have) < th["min_den"]:
            untested(i, name, f"too few visits (n={len(have)}, needs {th['min_den']})")
            continue
        out["tested"].append(name)
        hit = [x for x in have if x["s"][key] in vals]
        hp = {x["u"] for x in hit}
        rest = [x for x in have if x["s"][key] not in vals]
        pc = partition_cells({"hit": (hp, len(hit)), "rest": ({x["u"] for x in rest}, len(rest))})
        if pc["hit"] == SMALL or pc["rest"] == SMALL:
            led(i, name, "unknown", f"a group under {MIN_USERS} people: not shown (Unknown)")
            continue
        sh = len(hit) / len(have)
        txt = f"{share_text(len(hit), len(have), th)} of {fmt_n(g(n_act, len(have)))} visits were {txtname} ({gn(len(hp))} people)"
        if sh >= share_min and len(hp) >= max(people_min, MIN_USERS):
            led(i, name, "flagged", txt)
            SIG(i, name, "Many visits saw old or snapshot data" if i == "S9" else "Many visits were snapshot only", txt + ".", "Visits of the compared week that recorded the field (v2 pages only).",
                f"{rnd(100 * share_min)}% or more of the visits" + (f" and {people_min} or more people" if people_min else "") + ".", _confidence(1, n_act, th),
                "Whether anyone acted on old data. The visit starts from the data it finds.", "Worth investigating: whether the data refresh or the connector access coincides with these visits.")
        else:
            led(i, name, "within", txt)
    out["ledger"].sort(key=lambda r: r["id"])
    return out


def _s7(m: Model, ctx, out, led, SIG, untested):
    """S7 data coverage: the age of the export, duplicated or unknown records, records kept past 12 weeks, the share of visits that dropped keys, the size cap."""
    th = m.th
    name = "Data coverage"
    if ctx is None:
        untested("S7", name, "no export information supplied")
        return
    out["tested"].append(name)
    stats = ctx.get("stats") or {}
    issues, facts = [], []
    age, lv_age = ctx.get("export_age_days"), ctx.get("latest_visit_age")
    if age is None:
        facts.append("export time not supplied (read as taken today)")
    else:
        facts.append(f"export is {age} days old")
        if age > th["s7_export_stale_days"]:
            issues.append(f"the export is {age} days old (older than {th['s7_export_stale_days']} days): take a new one before reading a trend")
    if lv_age is not None and lv_age > th["s7_export_stale_days"]:
        issues.append(f"the latest visit in the data is {lv_age} days before the report day: the export may be stale")
    for k, label in (("duplicates", "duplicated documents dropped"), ("skipped", "rows skipped (not a record)"), ("unknown_schema", "documents with an unknown schema left out")):
        if stats.get(k):
            issues.append(f"{stats[k]} {label}")
    if stats.get("round_page"):
        issues.append(f"the export holds exactly {stats['read']} records, a round page size: confirm the tool's own total")
    st = m.stale_records
    if st:
        issues.append(f"{SMALL.replace('users', 'records') if st < MIN_USERS else str(st) + ' records'} not opened for over {th['retention_weeks']} weeks: delete them")
    pr = m.pruned_records
    if pr:
        issues.append(f"{SMALL.replace('users', 'records') if pr < MIN_USERS else str(pr) + ' records'} where the size cap dropped older weeks")
    xr = [r for r in m.rows if is_num(r["s"].get("x")) and r["s"]["x"] > 0]
    if m.rows and len(xr) >= th["s7_dropped_keys_share"] * len(m.rows) and len(xr) >= 1:
        issues.append(f"{rnd(100 * len(xr) / len(m.rows))}% of the visits dropped keys at the size cap")
    for w in ctx.get("calendar_warnings") or []:
        issues.append(w)
    out["data_issues"] = issues
    if issues:
        led("S7", name, "flagged", "; ".join(issues))
        SIG("S7", name, "The data itself needs a check", "; ".join(issues) + ".", "Facts about the export, not a comparison with earlier weeks.", "Any item listed.", "Confirmed",
            "Whether usage changed: these items concern how complete and how current the export is.", "Worth investigating: take a fresh export, then run the report again.")
    else:
        led("S7", name, "within", "; ".join(facts + ["no duplicated, skipped or unknown records"]))


def cnt(v, noun: str) -> str:
    """A count with its noun, or the guard text alone: '12 users' or '<5 users', never '<5 users users'."""
    return SMALL if v == SMALL else f"{v} {noun}"


# ------------------------------------------------------------------------------------------------------------ adoption views A1 to A8
def growth_accounting(m: Model) -> list:
    """A1: per completed week the people active and the growth accounting: new (first seen that week), continuing (active the week before), reactivated (back after a gap), lapsed (active the week before, not now).
    Every cell is guarded and protected as a partition (active = new + continuing + reactivated; the week before = continuing + lapsed). The week in progress is the last row, marked."""
    rows = []
    for ws in m.weeks:
        act = m.active(ws)
        n = len(act)
        prev = ws - dt.timedelta(days=7)
        row = {"ws": ws, "label": d_label(ws), "status": "provisional" if m.is_prov(ws) else "complete", "active": gn(n), "raw": n, "new": None, "continuing": None, "reactivated": None, "lapsed": None}
        if m.first_week is not None and prev >= m.first_week:
            pa = m.active(prev)
            cells = {"new": len(m.new(ws)), "continuing": sum(1 for u in act if u in pa and m.first_seen[u] < ws), "reactivated": sum(1 for u in act if u not in pa and m.first_seen[u] < ws), "lapsed": len(pa - act)}
            row.update(protect_group(cells, [(n, ["new", "continuing", "reactivated"]), (len(pa), ["continuing", "lapsed"])]))
        rows.append(row)
    n = len(m.active(m.cur))
    rows.append({"ws": m.cur, "label": d_label(m.cur), "status": "in_progress", "active": gn(n), "raw": n, "new": None, "continuing": None, "reactivated": None, "lapsed": None})
    return rows


def growth_verdict(m: Model) -> dict:
    """'Growing' only at +20% and +3 people over 6 completed weeks (median of the last 3 weeks against the median of the 3 before); otherwise 'too early' is a first-class answer."""
    th = m.th
    k = th["growth_weeks"]
    half = k // 2
    have = m.n_full_weeks()
    wl = [m.last - dt.timedelta(days=7 * i) for i in range(k - 1, -1, -1)]
    if not all(m.usable(w) for w in wl):
        return {"state": "too_early", "have": have, "need": k, "text": f"Too early to say: {have} of {k} completed weeks so far."}
    regimes = {m.regime(w) for w in wl} - {None}
    if len(regimes) > 1 or (m.rollover in wl):
        return {"state": "too_early", "have": have, "need": k, "text": "Too early to say: the recording rules changed within the last 6 weeks (glance visits are only recorded by the newer page), so the weeks are not comparable."}
    vals = [len(m.active(w)) for w in wl]
    a, b = statistics.median(vals[:half]), statistics.median(vals[half:])
    if a == 0 and b == 0:
        return {"state": "flat", "text": f"No clear growth: nobody was active in the last {k} completed weeks.", "have": have, "need": k}
    if 0 < rnd(a) < MIN_USERS or 0 < rnd(b) < MIN_USERS:
        return {"state": "unknown", "text": f"Unknown: a weekly median is under {MIN_USERS} people.", "have": have, "need": k}
    d = b - a
    need = max(th["growth_abs"], th["growth_rel"] * a)
    base = f"median of the last {half} completed weeks {rnd(b)} people, against {rnd(a)} in the {half} before"
    if d >= need:
        return {"state": "growing", "text": f"Growing: {base} (+{rnd(100 * d / a) if a else 0}%).", "have": have, "need": k, "a": rnd(a), "b": rnd(b)}
    if -d >= need:
        return {"state": "falling", "text": f"Falling: {base} ({rnd(100 * d / a)}%).", "have": have, "need": k, "a": rnd(a), "b": rnd(b)}
    return {"state": "flat", "text": f"No clear growth: {base}; growth needs +{rnd(100 * th['growth_rel'])}% and +{th['growth_abs']} people.", "have": have, "need": k, "a": rnd(a), "b": rnd(b)}


def merge_bins(counts: dict) -> list:
    """Merge neighbouring bins of a histogram (key = number of weeks) until every bin has at least MIN_USERS people. Returns [(lo, hi, n)]; a single bin under 5 people is withheld by the caller."""
    bins = [[k, k, counts[k]] for k in sorted(counts)]
    while len(bins) > 1 and min(b[2] for b in bins) < MIN_USERS:
        i = min(range(len(bins)), key=lambda j: (bins[j][2], j))
        nb = [j for j in (i - 1, i + 1) if 0 <= j < len(bins)]
        j = min(nb, key=lambda j: bins[j][2])
        lo, hi = min(i, j), max(i, j)
        bins[lo:hi + 1] = [[bins[lo][0], bins[hi][1], bins[lo][2] + bins[hi][2]]]
    return [tuple(b) for b in bins]


def habit_view(m: Model) -> dict:
    """A2: of the established people (first seen at least 14 days before the compared week) the share active in 4 or more of the last 8 completed weeks, and the weeks-active histogram (cells merged until each has 5)."""
    th = m.th
    need = th["habit_weeks"]
    wl = [m.last - dt.timedelta(days=7 * i) for i in range(need - 1, -1, -1)]
    if not all(m.usable(w) for w in wl):
        return {"state": "too_early", "have": m.n_full_weeks(), "need": need, "text": f"Too early: needs {need} completed weeks, has {m.n_full_weeks()}."}
    est = [u for u in m.people if m.first_seen[u] <= m.last - dt.timedelta(days=th["established_days"])]
    n = len(est)
    per = {u: sum(1 for w in wl if u in m.active(w)) for u in est}
    x = sum(1 for c in per.values() if c >= th["habit_min_weeks"])
    out = {"state": "ok", "n": n, "weeks": need, "min_weeks": th["habit_min_weeks"], "window": f"{d_label(wl[0])} to {d_label(wl[-1] + dt.timedelta(days=6))}"}
    if 0 < n < MIN_USERS:
        out.update({"x": SMALL, "pct": None, "bins": [], "n_print": SMALL})
        return out
    pc = protect_partition({"habit": x, "rest": n - x}, n)
    out["x"] = pc["habit"]
    out["pct"] = pct_of(x, n, th) if pc["habit"] != SMALL else None
    hist = merge_bins({k: sum(1 for c in per.values() if c == k) for k in range(need + 1)}) if n else []
    out["bins"] = [(lo, hi, c) for lo, hi, c in hist]
    out["n_print"] = n
    out["single_bin_small"] = len(hist) == 1 and hist[0][2] < MIN_USERS
    return out


def retention_view(m: Model) -> dict:
    """Cohort retention over eligible cohorts only. Week 1: people first seen at least 7 days before yesterday, with a visit on a later day within days 1 to 7 after their first day. Week 4: first seen at least 28 days before,
    a visit within days 22 to 28. People first seen before the go-live day (--since) or before the 12-week retention window have no known first day and are not in a cohort. Printed as 'x of n eligible'."""
    th = m.th
    last_full = m.ref - dt.timedelta(days=1)
    days = defaultdict(set)
    for r in m.rows:
        days[r["u"]].add(r["day"])
    out = {}
    for key, span, lo_off in (("w1", th["retention_w1_days"], 1), ("w4", th["retention_w4_days"], th["retention_w4_days"] - 6)):
        elig = [u for u in m.people if u not in m.pre_golive and m.first_real[u] >= m.cutoff and m.first_real[u] + dt.timedelta(days=span) <= last_full]
        ret = sum(1 for u in elig if any(m.first_real[u] + dt.timedelta(days=lo_off) <= d <= m.first_real[u] + dt.timedelta(days=span) for d in days[u]))
        n = len(elig)
        pc = protect_partition({"returned": ret, "not": n - ret}, n) if n >= MIN_USERS or n == 0 else {"returned": SMALL, "not": SMALL}
        out[key] = {"n": gn(n), "raw_n": n, "x": pc["returned"], "pct": pct_of(ret, n, th) if pc["returned"] != SMALL and pc["not"] != SMALL else None, "indicative": n < 30, "span": span}
    return out


def _window_rows(m: Model, wk: list) -> list:
    return [r for w in wk for r in m.visits(w)]


def sections_view(m: Model, wk: list) -> dict:
    """A3: reach per section in the window, in the fixed page order (never sorted by value): people with 30 s or more in the section in some week / the people active in the window; people using the Section Strip or the
    skip links to it; people following a Jira link from it; the person-weighted share of reading time among the rows shown (secondary). A 'simplify candidate' needs reach of 10% or less for 4 consecutive weeks, 20 or more
    active people in each, and a calendar check that shows no use around a cycle boundary."""
    th = m.th
    rows = _window_rows(m, wk)
    A = set().union(*[m.active(w) for w in wk]) if wk else set()
    N = len(A)
    reach = {k: {u for w in wk for u in A if m.secs(w).get(u, {}).get(k, 0) >= SECTION_MIN_SECONDS} for k in READ_SECTIONS}
    nav, links = defaultdict(set), defaultdict(set)
    for r in rows:
        for k, v in (r["s"].get("nav") or {}).items():
            if k in SECTIONS and is_num(v) and v > 0:
                nav[k].add(r["u"])
        for k, v in (r["s"].get("l") or {}).items():
            if k in LINK_SECTIONS and is_num(v) and v > 0:
                links[k].add(r["u"])
    tot = defaultdict(lambda: defaultdict(float))
    for w in wk:
        for u, d in m.secs(w).items():
            for k, v in d.items():
                tot[u][k] += v
    pw = defaultdict(float)
    for u, d in tot.items():
        s = sum(d.values())
        for k, v in d.items():
            pw[k] += v / s if s else 0
    shown = [k for k in READ_SECTIONS if len(reach[k]) >= MIN_USERS]
    pw_den = sum(pw[k] for k in shown)
    cand = _simplify_candidates(m)
    table = []
    for k, nm in READ_SECTIONS.items():
        n_r = len(reach[k])
        table.append({"key": k, "name": nm, "reach": gn(n_r), "raw": n_r, "pct": pct_of(n_r, N, th) if n_r >= MIN_USERS else None,
                      "nav": gn(len(nav[k])) if k in SECTIONS else None, "links": gn(len(links[k])), "share": (rnd(100 * pw[k] / pw_den) if pw_den and k in shown else (SMALL if 0 < n_r < MIN_USERS else (0 if n_r == 0 else None))),
                      "under5": 0 < n_r < MIN_USERS, "candidate": cand["by_key"].get(k)})
    ol = {k: gn(len({r["u"] for r in rows if (r["s"].get("o") or {}).get(k, 0) and is_num((r["s"].get("o") or {}).get(k)) and r["s"]["o"][k] > 0})) for k in DISCLOSURES}
    return {"n": N, "n_g": gn(N), "d": N if (N == 0 or N >= MIN_USERS) else SMALL, "weeks": len(wk), "rows": table, "candidates": cand, "disclosures": ol, "any_hidden": any(t["under5"] for t in table)}


def _boundary_weeks(m: Model) -> set:
    cal = m.cal or {}
    ds = []
    for r in cal.get("releases", []):
        ds += [r["w6_end"], r["end"]]
    ds += [s["end"] for s in cal.get("sprints", [])]
    return {week_start(d) for d in ds}


def _simplify_candidates(m: Model) -> dict:
    th = m.th
    k = th["simplify_weeks"]
    wl = [m.last - dt.timedelta(days=7 * i) for i in range(k - 1, -1, -1)]
    if not all(m.usable(w) for w in wl):
        return {"status": f"not tested: needs {k} completed weeks, has {m.n_full_weeks()}", "by_key": {}}
    if any(len(m.active(w)) < th["min_den"] for w in wl):
        return {"status": f"not tested: needs {th['min_den']} or more active people in each of the last {k} weeks", "by_key": {}}
    if not m.cal or not (m.cal.get("releases") or m.cal.get("sprints")):
        return {"status": "not tested: no calendar supplied, so use around a cycle boundary cannot be checked", "by_key": {}}
    bw = [w for w in wl if w in _boundary_weeks(m)]
    if not bw:
        return {"status": f"not tested: no cycle boundary in the last {k} weeks, so use around one cannot be checked", "by_key": {}}
    out = {}
    for key in READ_SECTIONS:
        if key == "top":
            continue
        low = all(100 * m.readers(w, key, m.active(w)) / len(m.active(w)) <= th["simplify_reach_pct"] for w in wl)
        if low:
            out[key] = "Simplify candidate"
    return {"status": f"tested: {len(out)} candidate(s) (reach {th['simplify_reach_pct']}% or less in each of the last {k} weeks and at a cycle boundary)", "by_key": out}


def controls_view(m: Model, wk: list) -> dict:
    """A4: control reach in the window, in fixed page order grouped by family (not ranked by changes), the share of active people that changed any control, the reset-in-visit rate and Multi-select against Projects."""
    th = m.th
    A = set().union(*[m.active(w) for w in wk]) if wk else set()
    N = len(A)
    users = defaultdict(set)
    any_f = set()
    for w in wk:
        for k, us in m.ctl(w).items():
            users[k] |= us
            any_f |= us
    fams = []
    for fam, keys in CONTROL_FAMILIES:
        rows = []
        for k in keys:
            n = len(users[k])
            rows.append({"key": k, "name": CONTROLS[k], "reach": gn(n), "raw": n, "pct": pct_of(n, N, th) if n >= MIN_USERS else None})
        fams.append({"family": fam, "rows": rows})
    # reset in the same visit (v2): visits with a reset after at least one control change / visits with at least one control change
    def changed(r):
        return any(is_num(v) and v > 0 for v in (r["s"].get("f") or {}).values())

    def wk_reset(ws):
        rs = [r for r in m.visits(ws) if r["v2"] and changed(r)]
        rr = [r for r in rs if r["s"].get("rr") == 1]
        return rs, rr
    rs_all = [r for w in wk for r in m.visits(w) if r["v2"] and changed(r)]
    rr_all = [r for r in rs_all if r["s"].get("rr") == 1]
    reset = {"state": "ok", "visits": len(rs_all), "n_users": len({r["u"] for r in rs_all})}
    reset["visits_g"] = g(reset["n_users"], len(rs_all))
    if not rs_all:
        reset["state"] = "none"
    else:
        rp = {r["u"] for r in rr_all}
        pc = partition_cells({"rr": (rp, len(rr_all)), "rest": ({r["u"] for r in rs_all if r not in rr_all}, len(rs_all) - len(rr_all))})
        reset["x"] = pc["rr"] if pc["rest"] != SMALL else SMALL
        reset["pct"] = pct_of(len(rr_all), len(rs_all), th) if reset["x"] != SMALL else None
        flagged = False
        wl = [m.last - dt.timedelta(days=7 * i) for i in range(th["reset_weeks"] - 1, -1, -1)]
        if all(m.usable(w) for w in wl):
            flagged = True
            for w in wl:
                a, b = wk_reset(w)
                if not (len({r["u"] for r in a}) >= th["reset_min_people"] and len(a) >= th["reset_min_visits"] and len(b) >= th["reset_rate"] * len(a)):
                    flagged = False
        reset["flag"] = flagged
    return {"n": N, "n_g": gn(N), "d": N if (N == 0 or N >= MIN_USERS) else SMALL, "weeks": len(wk), "families": fams, "any": {"x": gn(len(any_f)), "pct": pct_of(len(any_f), N, th) if len(any_f) >= MIN_USERS else None, "raw": len(any_f)}, "reset": reset,
            "multi_vs_projects": (gn(len(users["multi"])), gn(len(users["projects"])))}


def use_view(m: Model, wk: list) -> dict:
    """A5 link-follow rate, A6 phone share, A7 Refresh use, A8 data freshness, over the window (engaged visits = visits that are not glance visits)."""
    th = m.th
    rows = _window_rows(m, wk)
    eng = [r for r in rows if not r["glance"]]
    A = set().union(*[m.active(w) for w in wk]) if wk else set()
    out = {"engaged": len(eng), "engaged_g": g(len(A), len(eng)), "weeks": len(wk), "people": gn(len(A)), "n_people": len(A)}
    # A5
    def clicks(r, key=None):
        l = r["s"].get("l") or {}
        return sum(v for k, v in l.items() if k in LINK_SECTIONS and is_num(v) and v > 0 and (key is None or k == key))
    link_vis = [r for r in eng if clicks(r) > 0]
    lp = {r["u"] for r in link_vis}
    out["links"] = {"x": gn(len(lp)), "visits": g(len(lp), len(link_vis)), "pct": pct_of(len(link_vis), len(eng), th) if len(lp) >= MIN_USERS else None, "of": len(eng), "sections": []}
    for key, nm in LINK_SECTIONS.items():
        n_c = sum(clicks(r, key) for r in eng)
        ppl = {r["u"] for r in eng if clicks(r, key) > 0}
        if n_c >= th["link_min_clicks"] and len(ppl) >= th["link_min_people"]:
            vis = [r for r in eng if clicks(r, key) > 0]

            def rate(w, key=key):
                e_w = [r for r in m.visits(w) if not r["glance"]]
                return 100 * sum(1 for r in e_w if clicks(r, key) > 0) / len(e_w) if e_w else 0
            bw = m.baseline(m.last)
            status = f"baseline building ({len(bw)} of {th['baseline_min']} weeks)"
            if len(bw) >= th["baseline_min"] and m.usable(m.last):
                b = robust_band([rate(w) for w in bw], th["floor_reach_pp"], th["baseline_min"], th["band_mad"])
                cur = rate(m.last)
                status = "above its usual range" if cur > b["hi"] else "below its usual range" if cur < b["lo"] else "within its usual range"
            out["links"]["sections"].append({"name": nm, "pct": pct_of(len(vis), len(eng), th), "x": gn(len(ppl)), "status": status})
    mins = [r["s"]["s"] / 60 for r in eng if is_num(r["s"].get("s")) and r["s"]["s"] > 0]
    mp = {r["u"] for r in eng if is_num(r["s"].get("s")) and r["s"]["s"] > 0}
    out["minutes"] = {"median": g(len(mp), round(statistics.median(mins), 1)) if mins else None, "visits": g(len(mp), len(mins)), "people": gn(len(mp))}
    out["per_person"] = {"value": round(len(eng) / len(A), 1) if len(A) >= MIN_USERS else SMALL if A else None, "n": gn(len(A))}
    # A6
    dev = [r for r in eng if r["s"].get("d") in DEVICES]
    small = [r for r in dev if r["s"]["d"] == "s"]
    sp = {r["u"] for r in small}
    rest = [r for r in dev if r["s"]["d"] != "s"]
    pc = partition_cells({"small": (sp, len(small)), "rest": ({r["u"] for r in rest}, len(rest))}) if dev else {"small": 0, "rest": 0}
    out["phone"] = {"n": len(dev), "n_g": g(len(A), len(dev)), "x": pc["small"] if pc["rest"] != SMALL else SMALL, "pct": pct_of(len(small), len(dev), th) if SMALL not in pc.values() else None}
    # A7
    rp = {r["u"] for r in rows if is_num(r["s"].get("r")) and r["s"]["r"] > 0}
    out["refresh"] = {"x": gn(len(rp)), "pct": pct_of(len(rp), len(A), th) if len(rp) >= MIN_USERS else None, "n": len(A), "n_g": gn(len(A))}
    v2 = [r for r in rows if r["v2"]]
    ro = {}
    for k in RO:
        us = {r["u"] for r in v2 if is_num((r["s"].get("ro") or {}).get(k)) and r["s"]["ro"][k] > 0}
        ro[k] = {"people": gn(len(us)), "n": g(len(us), sum(int(r["s"]["ro"][k]) for r in v2 if is_num((r["s"].get("ro") or {}).get(k)) and r["s"]["ro"][k] > 0))}
    rt_users = {r["u"] for r in v2 if is_num(r["s"].get("rt")) and r["s"]["rt"] > 0}
    out["refresh"].update({"outcomes": ro, "retries": g(len(rt_users), sum(int(r["s"]["rt"]) for r in v2 if is_num(r["s"].get("rt")) and r["s"]["rt"] > 0)), "has_v2": bool(v2)})
    # A8
    fresh = {}
    for key, names, label in (("lv", LV, "Connection"), ("fa", FA, "Age of the data at the start of the visit")):
        have = [r for r in v2 if is_num(r["s"].get(key))]
        if not have:
            fresh[key] = None
            continue
        groups = {nm: ({r["u"] for r in have if r["s"][key] == code}, sum(1 for r in have if r["s"][key] == code)) for code, nm in names.items()}
        pc = partition_cells(groups)
        vis_sum = sum(c for c in pc.values() if c != SMALL)
        fresh[key] = {"label": label, "n": len(have), "n_g": g(len(A), len(have)), "cells": pc, "shares": {nm: (rnd(100 * c / vis_sum) if c != SMALL and vis_sum else None) for nm, c in pc.items()}, "hidden": SMALL in pc.values()}
    out["fresh"] = fresh
    return out


def health_view(m: Model) -> dict:
    """The Recording health block: can the measurement itself be trusted? Glance share, engaged against glance visits, visits with visible time but no active seconds (a focus problem), real against benign errors,
    visits that dropped keys, the share of active time attributed to a section, records kept past 12 weeks, records cut by the size cap."""
    th = m.th
    rows = m.rows
    v2 = [r for r in rows if r["v2"]]
    v1 = [r for r in rows if not r["v2"]]
    npp = len(m.people)
    out = {"visits": len(rows), "visits_g": g(npp, len(rows)), "v2": len(v2), "v2_g": g(len({r["u"] for r in v2}), len(v2)), "v1": len(v1), "has_v2": bool(v2)}
    out["v1_people"] = gn(len({r["u"] for r in v1}))
    out["v1_visits"] = g(len({r["u"] for r in v1}), len(v1))
    gl = [r for r in v2 if r["glance"]]
    en = [r for r in v2 if not r["glance"]]
    pc = partition_cells({"glance": ({r["u"] for r in gl}, len(gl)), "engaged": ({r["u"] for r in en}, len(en))})
    out["glance"] = {"x": pc["glance"], "engaged": pc["engaged"], "pct": pct_of(len(gl), len(v2), th) if SMALL not in pc.values() else None, "n": len(v2), "n_g": out["v2_g"]}

    def share_of(sel, den):
        p = {r["u"] for r in sel}
        x = g(len(p), len(sel))
        return {"x": x, "n": len(den), "n_g": g(len({r["u"] for r in den}), len(den)), "pct": pct_of(len(sel), len(den), th) if x != SMALL else None, "people": gn(len(p))}
    focus = [r for r in v2 if is_num(r["s"].get("vs")) and r["s"]["vs"] > 0 and not (is_num(r["s"].get("s")) and r["s"]["s"] > 0)]
    out["focus"] = share_of(focus, v2)
    out["errors_real"] = share_of([r for r in v2 if is_num(r["s"].get("er")) and r["s"]["er"] > 0], v2)
    out["errors_benign"] = share_of([r for r in v2 if is_num(r["s"].get("erb")) and r["s"]["erb"] > 0], v2)
    out["errors_v1"] = share_of([r for r in v1 if is_num(r["s"].get("er")) and r["s"]["er"] > 0], v1)
    out["dropped"] = share_of([r for r in rows if is_num(r["s"].get("x")) and r["s"]["x"] > 0], rows)
    s_tot = sum(r["s"]["s"] for r in rows if is_num(r["s"].get("s")) and r["s"]["s"] > 0)
    sec_tot = sum(v for r in rows for k, v in (r["s"].get("sec") or {}).items() if k in READ_SECTIONS and is_num(v) and v > 0)
    out["attributed"] = rnd(100 * min(1, sec_tot / s_tot)) if s_tot and len(m.people) >= MIN_USERS else None
    out["stale_records"] = m.stale_records if m.stale_records == 0 or m.stale_records >= MIN_USERS else SMALL
    out["pruned_records"] = m.pruned_records if m.pruned_records == 0 or m.pruned_records >= MIN_USERS else SMALL
    out["stale_sessions"] = m.counts["stale_sessions"]
    return out


# ------------------------------------------------------------------------------------------------------------ the daily view and the calendar notes
def calendar_marks(m: Model, lo: dt.date, hi: dt.date) -> list:
    """The calendar annotations that fall on a day from lo to hi: W1 start, end of W6 (the end of Delivery Cycle 1), the release end (end of W12), the sprint starts, the owner's review days."""
    marks = []
    cal = m.cal or {}
    for r in cal.get("releases", []):
        for d, label in ((r["w1"], f"W1 starts ({r['release']})"), (r["w6_end"], f"End of W6, Delivery Cycle 1 ends ({r['release']})"), (r["end"], f"Release end, end of W12 ({r['release']})")):
            if lo <= d <= hi:
                marks.append((d, label, "ms"))
    for s in cal.get("sprints", []):
        if lo <= s["start"] <= hi:
            marks.append((s["start"], "Sprint starts", "sp"))
    for d in cal.get("events", []):
        if lo <= d <= hi:
            marks.append((d, "Owner review day", "ev"))
    return sorted(marks)


def calendar_note(m: Model) -> str | None:
    """'Data covers W<a> to W<b> of the release so far; no cycle boundary has been observed yet', from the release whose W1 is the latest one on or before the day of the data."""
    cal = m.cal or {}
    rels = [r for r in cal.get("releases", []) if r["w1"] <= m.ref]
    if not rels or not m.data_start:
        return None
    r = max(rels, key=lambda x: x["w1"])
    wk = lambda d: (d - r["w1"]).days // 7 + 1
    a, b = max(1, wk(m.data_start)), min(12, wk(m.ref))
    bounds = [d for d in (r["w6_end"], r["end"]) if m.data_start <= d < m.ref]
    start = "" if m.data_start >= r["w1"] else " (the data starts before W1)"
    if bounds:
        return f"Data covers W{a} to W{b} of release {r['release']}{start} and includes {'the end of Delivery Cycle 1 (W6)' if r['w6_end'] in bounds else 'the release end'}."
    return f"Data covers W{a} to W{b} of release {r['release']}{start} so far; no cycle boundary has been observed yet."


def event_windows(m: Model, per_day: dict) -> dict | None:
    """Review-day windows: the people per day on the 3 working days ending on each owner review day against the median of the other 3-working-day windows. Needs 3 events with a complete window inside the data;
    with fewer it says 'one observation, not a pattern'. Friday and Saturday are never part of a baseline."""
    th = m.th
    ev = sorted((m.cal or {}).get("events", []))
    if not ev:
        return None
    work = sorted(d for d in per_day if d.weekday() in WORKDAYS and d < m.ref and (m.data_start and d >= m.data_start))
    idx = {d: i for i, d in enumerate(work)}
    wins = []
    for d in ev:
        e = max((x for x in work if x <= d), default=None)
        if e is None or idx[e] < th["event_days"] - 1:
            continue
        wins.append(idx[e])
    n_ev = len(ev)
    if len(wins) < th["event_min"]:
        return {"state": "few", "events": n_ev, "usable": len(wins), "text": f"{n_ev} review day{'s' if n_ev != 1 else ''} marked, {len(wins)} with a complete window: {'one observation' if len(wins) == 1 else 'too few observations'}, not a pattern (needs {th['event_min']})."}
    k = th["event_days"]
    ev_vals = [statistics.mean(per_day[work[i - j]] for j in range(k)) for i in wins]
    used = set()
    for i in wins:
        used |= set(range(i - k + 1, i + 1))
    others = [statistics.mean(per_day[work[i - j]] for j in range(k)) for i in range(k - 1, len(work)) if not (set(range(i - k + 1, i + 1)) & used)]
    if not others:
        return {"state": "few", "events": n_ev, "usable": len(wins), "text": "No other window to compare with."}
    a, b = statistics.median(ev_vals), statistics.median(others)
    return {"state": "ok", "events": n_ev, "usable": len(wins), "text": f"Average people per working day in the {k} days ending on a review day: {gm(a)} (median of {len(wins)} windows); in other {k}-day windows: {gm(b)} (median of {len(others)}). This is an association, not a measured effect."}


def daily_view(m: Model) -> dict:
    ref = m.ref
    by_day = defaultdict(set)
    for r in m.rows:
        by_day[r["day"]].add(r["u"])
    days = []
    for i in range(27, -1, -1):
        d = ref - dt.timedelta(days=i)
        n = len(by_day.get(d, ()))
        days.append({"day": d, "users": gn(n), "raw": n, "has_data": bool(m.data_start and d >= m.data_start), "weekend": d.weekday() in WEEKEND, "partial": d == ref})
    marks = calendar_marks(m, days[0]["day"], days[-1]["day"])
    per = {d["day"]: d["raw"] for d in days}
    rows28 = [r for r in m.rows if ref - dt.timedelta(days=27) <= r["day"] < ref]
    ww = None
    if len(rows28) >= m.th["workweek_min_visits"] and len({r["u"] for r in rows28}) >= MIN_USERS:
        ww = {"pct": rnd(100 * sum(1 for r in rows28 if r["day"].weekday() in WORKDAYS) / len(rows28)), "n": len(rows28)}
    return {"days": days, "marks": marks, "workweek": ww, "events": event_windows(m, per), "note": calendar_note(m)}


# ------------------------------------------------------------------------------------------------------------ the aggregate
def aggregate(bodies: list, today: dt.date | None = None, as_of: dt.datetime | None = None, now: dt.datetime | None = None, demo: bool = False, since: dt.date | None = None,
              audience: int | None = None, calendar: dict | None = None, th: dict | None = None, stats: dict | None = None) -> dict:
    """Everything the text report and the page print, computed from the record bodies.

    today: the Israel day the report is made (default: the current one). as_of: when the export was taken; the day of the data (`ref`) is its Israel date. Without as_of the data is read as taken today:
    the last day in the data is NEVER taken for today. since: the go-live day. audience: the size of the intended audience (optional). calendar: a parsed calendar (parse_calendar). stats: load_export's counts."""
    th = th or THRESHOLDS
    now = now or dt.datetime.now(IL)
    now_date = today or (now.astimezone(IL).date() if now.tzinfo else now.date())
    if as_of:
        t = as_of.astimezone(IL) if as_of.tzinfo else as_of
        ref, age = t.date(), (now_date - t.date()).days
    else:
        ref, age = now_date, None
    m = Model(bodies, ref, since, calendar, th)
    latest_age = (ref - m.last_day).days if m.last_day else None
    ctx = {"export_age_days": age, "latest_visit_age": latest_age, "stats": stats or {}, "calendar_warnings": (calendar or {}).get("warnings", [])}
    sig = detect_signals(m, ctx)
    wk = window_weeks(m)
    n_people = len(m.people)
    comp = None
    if m.usable(m.last):
        ev = _eval_count(m, m.last, lambda w: len(m.active(w)))
        comp = {"ws": m.last, "label": week_label(m.last), "active": gn(len(m.active(m.last))), "raw": len(m.active(m.last)), "state": ev["state"], "n_baseline": ev.get("n", len(ev.get("weeks", []))), "established": len(m.established(m.last))}
        if ev["state"] == "ok":
            b = ev["band"]
            comp.update({"median": gm(b["median"]), "lo": gm(max(0, b["lo"])), "hi": gm(b["hi"]), "raw_lo": max(0, b["lo"]), "raw_hi": b["hi"], "n_weeks": b["n"], "inside": not ev["outside"], "above": ev["cur"] > b["hi"], "below": ev["cur"] < b["lo"]})
    aud = None
    if audience:
        x = len(m.active(m.last)) if comp else None
        aud = {"size": audience, "people": gn(n_people), "x": gn(x) if x is not None else None, "stale": n_people > audience,
               "pct": rnd(100 * x / audience) if (x is not None and x >= MIN_USERS and audience >= th["min_den"] and n_people <= audience) else None}
    return {
        "demo": demo, "today": now_date, "ref": ref, "as_of": as_of, "export_age_days": age, "latest_visit_age": latest_age, "since": since,
        "n_docs": len(bodies), "n_sessions": len(m.rows), "n_people": {"raw": n_people, "n": gn(n_people)}, "first_day": m.first_day, "last_day": m.last_day,
        "history_days": (ref - m.first_day).days + 1 if m.first_day else 0, "data_start": m.data_start, "provisional_first": m.provisional_first, "first_week": m.first_week,
        "compared": comp, "signals": sig, "weeks": growth_accounting(m), "growth": growth_verdict(m), "habit": habit_view(m), "retention": retention_view(m),
        "window": {"weeks": len(wk), "lo": wk[0] if wk else None, "hi": (wk[-1] + dt.timedelta(days=6)) if wk else None, "label": f"{d_label(wk[0])} to {d_label(wk[-1] + dt.timedelta(days=6))}" if wk else ""},
        "sections": sections_view(m, wk), "controls": controls_view(m, wk), "use": use_view(m, wk), "health": health_view(m), "daily": daily_view(m), "audience": aud,
        "stats": stats or {}, "counts": m.counts, "model": m,
    }


# ------------------------------------------------------------------------------------------------------------ the demo data (fictitious)
DEMO_BUILDS = (("c0ffee1", "5ca1ab1"), 0)


def demo_calendar(ref: dt.date) -> dict:
    """A fictitious calendar for the demo, in the file's own shape: release 'demo' with W1 on a Wednesday 25 days before the week of the data, one review day."""
    cur = week_start(ref)
    w1 = cur - dt.timedelta(days=25)
    return {"releases": [{"release": "demo", "w1": w1.isoformat(), "w6_end": (w1 + dt.timedelta(days=41)).isoformat(), "end": (w1 + dt.timedelta(days=83)).isoformat()}],
            "sprints": [{"no": 1, "start": w1.isoformat(), "end": (w1 + dt.timedelta(days=20)).isoformat()}, {"no": 2, "start": (w1 + dt.timedelta(days=21)).isoformat(), "end": (w1 + dt.timedelta(days=41)).isoformat()}],
            "events": [(cur - dt.timedelta(days=11)).isoformat()]}


def demo_bodies(ref: dt.date, seed: int = 20261102, v2_from: int = 3) -> list:
    """About 50 fictitious people over 11 completed weeks and the week in progress, built to exercise the failure modes: the first week starts mid-week (provisional), the oldest weeks are v1 records and the rest v2
    (a mixture, with a rollover week), a lapsed group of regulars, a growing group of new people, a quiet week below 20 active people, one build with a single error, a section whose reach drops, a control newly used and one no longer used.
    v2_from: the index of the first v2 week (0 to 10; 99 = every week is a v1 record, the page of a data set from before the upgrade).
    Ids are u_synthetic_NNN; a few sections and controls are used by only a few people so that the small-group guard shows."""
    r = random.Random(seed)
    cur = week_start(ref)
    L = cur - dt.timedelta(days=7)
    week_of = lambda k: L - dt.timedelta(days=7 * (10 - k))                              # k = 0 .. 10 are the completed weeks, 11 the week in progress
    bt_new, bt_old = (L - dt.timedelta(days=3) - EPOCH).days, (cur - dt.timedelta(days=60) - EPOCH).days
    plan = []                                                                            # (first week, last week, habit)
    plan += [(0, 11, 0.92)] * 26                                                         # regulars
    plan += [(0, 7, 0.88)] * 8                                                           # lapsed after week L-3
    plan += [(s, 11, 0.7) for s in (4, 5, 5, 6, 6, 7, 8, 9, 10, 10, 10, 10, 10, 10)]      # new people, six of them in the last completed week
    plan += [(0, 2, 0.8)] * 3                                                            # v1 only: gone before the page was upgraded
    out = []
    for i, (k0, k1, habit) in enumerate(plan):
        sessions: dict = {}
        dev = "s" if i % 9 == 0 else "m" if i % 6 == 0 else "l"
        for k in range(k0, k1 + 1):
            ws = week_of(k) if k <= 10 else cur
            p = habit * (0.55 if k == 5 else 1.0)
            if r.random() > p:
                continue
            days = [d for d in range(5) if (k > 0 or d >= 2) and (k <= 10 or ws + dt.timedelta(days=(d - 1) % 7) <= ref)]        # Sunday .. Thursday as 0 .. 4; the first week starts on a Tuesday
            days = [d for d in days if ws + dt.timedelta(days=d) <= ref]
            if not days:
                continue
            for d in r.sample(days, min(len(days), r.choice([1, 1, 2, 3]))):
                day = ws + dt.timedelta(days=d)
                for _ in range(1 if r.random() < 0.8 else 2):
                    v2 = k >= v2_from
                    s = {}
                    glance = v2 and r.random() < 0.22
                    if glance:
                        vs = r.randrange(5, 30)
                        s = {"t": 490_000 + r.randint(0, 9_000), "s": 0 if r.random() < 0.2 else vs // 5 * 5, "vs": vs, "g": 1}
                    else:
                        secs = {}
                        w_sec = {"attn": 0.6, "burnup": 0.55, "bugs": 0.35, "cycles": 0.25, "eff": 0.25, "deps": 0.2, "ai": 0.2, "analysis": (0.9 if i % 5 == 1 else 0.0) if k == 10 else 0.85, "capview": 0.08 if i < 4 else 0, "nfr": 0.05 if i < 3 else 0, "cx": 0.05 if i < 3 else 0}
                        for key, pr_ in w_sec.items():
                            if r.random() < pr_:
                                secs[key] = 5 * r.randint(2, 20)
                        if not secs:
                            secs["attn"] = 5 * r.randint(2, 10)
                        if v2:
                            secs["top"] = 5 * r.randint(2, 8)
                        act = sum(secs.values())
                        s = {"t": 29_900_000 + r.randint(0, 10_000_000), "s": act, "sec": secs}
                        if v2:
                            s["t"] = 490_000 + r.randint(0, 9_000)
                            s["vs"] = act + r.randint(0, 60)
                            if r.random() < 0.05:
                                s["s"] = 0
                        f = {key: r.randint(1, 3) for key, pw_ in (("release", 0.35), ("projects", 0.25), ("teams", 0.15), ("gran", 0.1), ("dc", 0.1), ("bugpri", 0.08), ("cfb", 0.08), ("ax", 0.05)) if r.random() < pw_}
                        if i < 3 and r.random() < 0.3:
                            f["nfrtab"] = 1
                        if (k == 10 and i % 3 == 0 and r.random() < 0.9) or (k < 10 and i < 2 and r.random() < 0.3):
                            f["multi"] = 1                                          # newly used in the last completed week
                        if k <= 8 and i % 4 == 0 and r.random() < 0.6:
                            f["cfbgrp"] = 1                                         # no longer used since the week before the last but one
                        if i < 3 and r.random() < 0.3:
                            f["cypods"] = r.randint(1, 4)                           # three people only: shows '<5 users'
                        if f:
                            s["f"] = f
                        nav = {key: r.randint(1, 3) for key in r.sample(list(SECTIONS), r.randint(0, 2)) if key not in ("nfr", "cx") or i < 3}
                        if nav:
                            s["nav"] = nav
                        lk = {key: r.randint(1, 4) for key in ("attn", "bugs", "deps", "burnup") if r.random() < 0.18}
                        if i < 2 and r.random() < 0.4:
                            lk["capview"] = 1                                       # two people only
                        if lk:
                            s["l"] = lk
                        o = {key: 1 for key, p_ in (("how", 0.2), ("data", 0.12), ("attn", 0.1), ("other", 0.03)) if r.random() < p_}
                        if o:
                            s["o"] = o
                        if r.random() < 0.05:
                            s["r"] = 1
                            if v2:
                                s["ro"] = {"ok": 1} if r.random() < 0.8 else {"fail": 1}
                        if f and r.random() < 0.07 and v2:
                            s["rs"] = 1
                            s["rr"] = 1
                    s.update({"d": dev, "b": DEMO_BUILDS[0][0] if (v2 and k >= 4) else DEMO_BUILDS[0][1], "np": r.choice([7, 7, 7, 3, 1])})
                    if v2:
                        s["bt"] = bt_old if (8 <= i <= 10 and k >= 5) else bt_new if k >= 4 else bt_old
                        s["lv"] = 1 if r.random() < 0.08 else 0
                        s["fa"] = r.choices([0, 1, 2, 3], weights=[76, 17, 5, 2])[0]
                        if r.random() < 0.08:
                            s["erb"] = 1
                        if i == 3 and k == 9 and "er" not in s and not glance:
                            s["er"] = 1                                             # the single error of one page version
                            s["b"] = "bbb2222"
                    wkey = sunday_key(day) if v2 else iso_week_key(day)
                    sessions.setdefault(wkey, {}).setdefault(day.isoformat(), {})["".join(r.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(8))] = s
        if sessions:
            all_days = [d for wk_ in sessions.values() for d in wk_]
            v2_any = any(is_v2(s_) for wk_ in sessions.values() for dd in wk_.values() for s_ in dd.values())
            out.append({"u": f"u_synthetic_{i + 1:03d}", "v": 2 if v2_any else 1, "first": min(all_days), "last": max(all_days), "w": sessions})
    return out


# ------------------------------------------------------------------------------------------------------------ wording
# Words the page and the text report never use: they name or rank people, or claim a cause the data cannot show. tests/test_usage_report.py checks every output against this list.
WORDING_BLOCKLIST = [r"\bwho\b", r"top users?", r"least active", r"most active", r"engaged people", r"people who read", r"\bbecause\b", r"\bcaused?\b", r"\bdue to\b", r"leaderboard", r"\branking\b", r"(?<!not )\banonymous"]

COVERAGE_NOT_COUNTED = "Not counted: people signed out, with view-only access, using an offline copy or whose browser blocks storage. Includes the owner's and testers' visits. Aggregate counts only; groups under 5 people print <5 users. Never used to rank or assess people or teams."


def fmt_date(d: dt.date) -> str:
    return f"{d.day} {d:%b %Y}"


def coverage_text(a: dict) -> str:
    n = a["n_people"]["n"]
    who = "fewer than 5 people" if n == SMALL else f"{n} people"
    span = f" between {fmt_date(a['first_day'])} and {fmt_date(a['last_day'])} (Israel time)" if a["first_day"] else ""
    aud = ""
    if a["audience"]:
        aud = f", of an audience of {a['audience']['size']} (a lower bound: only people with edit access and an id are recorded)"
    return f"Based on {who} with an id{span}{aud}. {COVERAGE_NOT_COUNTED}"


def text_report(a: dict) -> str:
    """The aggregate text report: the same numbers as the page, in the same order (coverage, what changed, adoption, reading, use, rhythm, recording health). Nothing here names a person."""
    L: list = []
    add = L.append
    add(f"Delivery Pulse usage, data as of {a['ref']}" + ("   [DEMO DATA]" if a["demo"] else ""))
    add(coverage_text(a))
    for w in export_warnings(a):
        add(f"WARNING: {w}")
    if not a["n_sessions"]:
        add("\nNo usage recorded yet. Open the published Delivery Pulse page as a person with edit access, use it for 30 seconds, then export the documents of the collection `usage` and run this report again.")
        return "\n".join(L) + "\n"
    c, sg = a["compared"], a["signals"]
    add("\nWhat changed since last report")
    if c:
        add(f"  Compared week: {c['label']} (last completed Sunday-to-Saturday week), {fmt_n(c['active'])} people active. Baseline: " + (f"median of the previous {c['n_weeks']} completed weeks: {c['median']} (normal range {c['lo']} to {c['hi']})." if c["state"] == "ok" else f"building ({c['n_baseline']} of {a['model'].th['baseline_min']} comparable weeks)."))
    else:
        add("  No completed week of data to compare yet.")
    add("  No previous report supplied; every flagged item is shown as new.")
    if sg["flagged"]:
        shown = _shown_signals(sg, a["model"].th)
        for f in shown:
            add(f"  [{f['id']}] {f['headline']} ({f['confidence']}): {f['observation']} Does not show: {f['not_show']} {f['next']}")
        if len(sg["flagged"]) > len(shown):
            add(f"  {len(sg['flagged']) - len(shown)} more section or control signals are listed under Checked.")
    else:
        add("  " + nothing_changed_text(sg))
    add("  Checked:")
    for r in sg["ledger"]:
        add(f"    {r['id']} {r['name']}: {STATUS_WORD[r['status']]}. {r['text']}")
    add(f"\nIs adoption growing? {a['growth']['text']}")
    if a["audience"]:
        au = a["audience"]
        add("  " + (f"{fmt_n(au['x'])} of an audience of {au['size']}" + (f" ({au['pct']}%)" if au["pct"] is not None else "") + ", a lower bound." if au["x"] is not None else f"Audience of {au['size']} supplied."))
        if au["stale"]:
            add("  The audience size looks out of date: more people are in the data than the audience.")
    else:
        add("  Audience size not supplied: no adoption percentage is shown.")
    add("\nWeekly people (Sunday to Saturday; the first week and the week in progress are not comparable)")
    for w in a["weeks"]:
        tag = {"provisional": "  (provisional: data starts mid-week)", "in_progress": "  (so far this week, not comparable)"}.get(w["status"], "")
        extra = "" if w["new"] is None else f"  new {fmt_n(w['new'])}, returning after a gap {fmt_n(w['reactivated'])}, lapsed {fmt_n(w['lapsed'])}"
        add(f"  {w['label']:<7} {fmt_n(w['active']):>9}{tag}{extra}")
    h = a["habit"]
    add("\nDo people come back?")
    for key, label in (("w1", "week 1"), ("w4", "week 4")):
        r = a["retention"][key]
        add(f"  Retention {label}: " + (f"{share_text(r['x'], r['raw_n'], a['model'].th)} of {fmt_n(r['n'])} eligible people" if r["raw_n"] else "no eligible people yet") + (" (indicative, under 30 people)" if r["indicative"] and r["raw_n"] else ""))
    add("  Habit: " + (h["text"] if h["state"] != "ok" else f"{share_text(h['x'], h['n'], a['model'].th) if h['n_print'] != SMALL else SMALL} of {fmt_n(h['n_print'])} established people were active in {h['min_weeks']} or more of the last {h['weeks']} completed weeks ({h['window']})"))
    sv = a["sections"]
    add(f"\nWhat people read: reach in the last {sv['weeks']} completed weeks, {fmt_n(sv['n_g'])} active people (in page order, not ranked)")
    for r in sv["rows"]:
        add(f"  {r['name']:<18} reach {share_text(r['reach'], sv['d'], a['model'].th):>12}   strip {fmt_n(r['nav']) if r['nav'] is not None else '-':>9}   Jira links {fmt_n(r['links']):>9}" + (f"   {r['candidate']}" if r["candidate"] else ""))
    add(f"  {sv['candidates']['status']}")
    cv = a["controls"]
    add(f"\nWhat people use: reach in the same window, {fmt_n(cv['n_g'])} active people")
    for fam in cv["families"]:
        add(f"  {fam['family']}")
        for r in fam["rows"]:
            add(f"    {r['name']:<32} {share_text(r['reach'], cv['d'], a['model'].th):>12}")
    add(f"  Any control: {share_text(cv['any']['x'], cv['d'], a['model'].th)}")
    rs = cv["reset"]
    add("  Reset Filters in the same visit: " + ("not recorded in v1 records" if rs["state"] == "none" else f"{share_text(rs['x'], rs['visits_g'], a['model'].th)} of visits with a control change ({nlabel(rs['visits_g'])})") + (" (flag: 25% or more in 2 consecutive weeks)" if rs.get("flag") else ""))
    u = a["use"]
    lk = u["links"]
    add(f"\nHow people use it ({u['weeks']} weeks, {nlabel(u['engaged_g'])} engaged visits (30 s or more, or with input))")
    add(f"  Visits with a Jira link click: {SMALL if lk['x'] == SMALL else (str(lk['pct']) + '% of engaged visits' if lk['pct'] is not None else str(lk['visits']) + ' visits')}")
    add(f"  Small-screen share of engaged visits: {share_text(u['phone']['x'], u['phone']['n_g'], a['model'].th)} ({nlabel(u['phone']['n_g'])})")
    add(f"  Refresh pressed by {share_text(u['refresh']['x'], u['refresh']['n_g'], a['model'].th)} of active people")
    for key, fr in u["fresh"].items():
        if fr:
            add(f"  {fr['label']}: " + ", ".join(f"{nm} {fmt_n(c_)}" for nm, c_ in fr["cells"].items()))
    hl = a["health"]
    add("\nRecording health")
    add(f"  Visits in the data: {fmt_n(hl['visits_g'])} ({fmt_n(hl['v2_g'])} from the newer page, {fmt_n(hl['v1_visits'])} from the earlier page)")
    if hl["has_v2"]:
        gl = hl["glance"]
        add(f"  Glance visits: {share_text(gl['x'], gl['n_g'], a['model'].th)} of {fmt_n(gl['n_g'])} visits; engaged visits: {fmt_n(gl['engaged'])}")
        add(f"  Visible but no active seconds: {share_text(hl['focus']['x'], hl['focus']['n_g'], a['model'].th)}")
        add(f"  Real errors: {share_text(hl['errors_real']['x'], hl['errors_real']['n_g'], a['model'].th)}; benign notifications: {share_text(hl['errors_benign']['x'], hl['errors_benign']['n_g'], a['model'].th)}")
    else:
        add("  Glance visits, focus and benign errors: not recorded in v1 records")
    add(f"  Visits that dropped keys: {share_text(hl['dropped']['x'], hl['dropped']['n_g'], a['model'].th)}; active time attributed to a section: {hl['attributed']}%" if hl["attributed"] is not None else "  Active time attributed to a section: -")
    add(f"  Records not opened for over 12 weeks: {fmt_n(hl['stale_records'])}; records cut by the size cap: {fmt_n(hl['pruned_records'])}")
    dv = a["daily"]
    if dv["note"]:
        add("\n" + dv["note"])
    if dv["workweek"]:
        add(f"Sunday to Thursday had {dv['workweek']['pct']}% of the {dv['workweek']['n']} visits in the last 28 days.")
    return "\n".join(L) + "\n"


STATUS_WORD = {"flagged": "Flagged", "within": "Within range", "not_tested": "Not tested", "unknown": "Unknown"}


def _shown_signals(sg: dict, th: dict) -> list:
    """All signals, with at most max_signals_shown section or control signals (S3 and S4)."""
    out, k = [], 0
    for f in sg["flagged"]:
        if f["id"] in ("S3", "S4"):
            k += 1
            if k > th["max_signals_shown"]:
                continue
        out.append(f)
    return out


def nothing_changed_text(sg: dict) -> str:
    done = [r for r in sg["ledger"] if r["status"] in ("within", "unknown")]
    todo = [r for r in sg["ledger"] if r["status"] == "not_tested"]
    s = "Nothing changed beyond the usual week-to-week range. Checked: " + ("; ".join(f"{r['name']} ({r['text']})" for r in done) if done else "nothing could be tested yet") + "."
    if todo:
        s += " Not tested: " + "; ".join(f"{r['name']} ({r['text']})" for r in todo) + "."
    return s + " This is not a statement that usage is healthy. It covers only people with an id and write access."


def export_warnings(a: dict) -> list:
    """Warnings shown at the top: a stale export, duplicates, unknown records."""
    out = []
    for i in a["signals"].get("data_issues", []):
        out.append(i[0].upper() + i[1:])
    return out


# ------------------------------------------------------------------------------------------------------------ the dashboard page
CSS = """
:root {
  --bg:#FFFFFF; --panel:#F2F0EB; --ink:#21212B; --muted:#5A5F6B; --line:#DAD7D0; --line-soft:#ECEAE5; --ctl:#767B86;
  --blue:#3694FC; --blue-ink:#025AFB; --blue-tint:#E4F0FF; --teal-ink:#1C7A6C;
  --amber:#C77700; --amber-ink:#8A5200; --warn-bg:#FFF6E5; --warn-line:#F0D9A8; --warn-ink:#6B4A00;
  --radius:12px; --radius-s:8px;
  --font:'Be Vietnam Pro', Arial, 'Segoe UI', -apple-system, sans-serif;
  --t-xs:12px; --t-cap:13px; --t-body:14px; --t-sub:16px; --t-title:20px; --t-fig:28px; --t-hero:48px;
  color-scheme:light;
}
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font-family:var(--font); font-size:var(--t-body); font-weight:400; line-height:1.5; }
.gutter { max-width:1100px; margin:0 auto; padding-left:max(16px, env(safe-area-inset-left, 0px)); padding-right:max(16px, env(safe-area-inset-right, 0px)); }
a { color:var(--blue-ink); }
h1 { font-size:var(--t-title); font-weight:600; line-height:1.25; margin:0; }
h2 { font-size:var(--t-sub); font-weight:600; line-height:1.3; margin:0 0 4px; }
h3 { font-size:var(--t-body); font-weight:600; line-height:1.3; margin:18px 0 4px; }
.top { padding-top:20px; display:flex; flex-wrap:wrap; align-items:baseline; gap:4px 16px; }
.stamp { color:var(--muted); font-size:var(--t-cap); }
.demo { margin:12px 0 0; padding:8px 12px; background:var(--warn-bg); border:1px solid var(--warn-line); border-radius:var(--radius-s); color:var(--warn-ink); font-weight:600; font-size:var(--t-body); }
.warn { display:flex; gap:8px; align-items:flex-start; margin:12px 0 0; padding:8px 12px; background:var(--warn-bg); border:1px solid var(--warn-line); border-radius:var(--radius-s); color:var(--warn-ink); font-weight:600; }
.warn svg { flex:none; width:18px; height:18px; margin-top:2px; }
.ribbon { margin:12px 0 0; padding:8px 12px; background:var(--panel); border-radius:var(--radius-s); font-size:var(--t-cap); color:var(--ink); }
.note { margin:12px 0 0; padding:8px 12px; background:var(--panel); border-radius:var(--radius-s); font-size:var(--t-body); }
.hero { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1.4fr); gap:12px 40px; align-items:end; padding:24px 0 20px; border-bottom:1px solid var(--line); }
.hero .fig { font-size:var(--t-hero); font-weight:600; line-height:1.05; font-variant-numeric:tabular-nums; margin:0; }
.hero .what { font-size:var(--t-sub); margin:0 0 2px; font-weight:500; }
.hero .ctx { color:var(--muted); font-size:var(--t-body); margin:4px 0 0; }
.verdict { margin:12px 0 0; padding:8px 12px; border-left:4px solid var(--blue-ink); background:var(--panel); border-radius:0 var(--radius-s) var(--radius-s) 0; font-size:var(--t-body); }
.verdict b { font-weight:600; }
.chartwrap { position:relative; }
.bars { display:flex; align-items:flex-end; gap:3px; height:130px; border-bottom:1px solid var(--ctl); position:relative; }
.bars .d { flex:1 1 0; min-width:0; background:var(--blue-ink); border-radius:2px 2px 0 0; position:relative; z-index:1; }
.bars .d.we { background:var(--blue); }
.bars .d.part { background:repeating-linear-gradient(135deg,var(--blue-ink) 0 3px,#FFFFFF 3px 6px); outline:1px solid var(--blue-ink); outline-offset:-1px; }
.bars .gap { flex:1 1 0; min-width:0; height:100%; display:flex; align-items:flex-end; justify-content:center; }
.bars .gap.we { background:var(--line-soft); }
.bars .stub { display:block; width:100%; height:12%; background:repeating-linear-gradient(135deg,var(--ctl) 0 2px,#FFFFFF 2px 4px); }
.bars .dot { display:block; width:100%; max-width:8px; height:3px; background:var(--muted); }
.band { position:absolute; left:0; right:0; background:var(--blue-tint); border-top:1px dashed var(--blue-ink); border-bottom:1px dashed var(--blue-ink); z-index:0; }
.marks { display:flex; gap:3px; height:14px; margin-top:2px; }
.marks span { flex:1 1 0; min-width:0; text-align:center; font-size:10px; line-height:14px; color:var(--amber-ink); }
.marks span.sp { color:var(--muted); } .marks span.ev { color:var(--teal-ink); }
.axis { display:flex; justify-content:space-between; gap:8px; color:var(--muted); font-size:var(--t-xs); margin-top:4px; }
section.blk { padding:26px 0 4px; }
section.blk .why { color:var(--muted); margin:0 0 12px; }
.sigs { list-style:none; margin:12px 0 0; padding:0; }
.sigs > li { padding:12px 0; border-top:1px solid var(--line-soft); }
.sigs > li:first-child { border-top:0; padding-top:4px; }
.sh { display:flex; flex-wrap:wrap; align-items:baseline; gap:2px 10px; }
.sh strong { font-size:var(--t-sub); font-weight:600; }
.tag { display:inline-block; padding:0 8px; border:1px solid var(--ctl); border-radius:10px; font-size:var(--t-xs); color:var(--ink); background:var(--bg); }
.sid { color:var(--muted); font-size:var(--t-xs); }
.sigs p { margin:2px 0; }
.small { color:var(--muted); font-size:var(--t-cap); }
table { border-collapse:collapse; width:100%; font-size:var(--t-body); }
th { text-align:left; font-weight:500; font-size:var(--t-xs); color:var(--muted); padding:6px 8px 6px 0; border-bottom:1px solid var(--line); }
td { padding:7px 8px 7px 0; border-bottom:1px solid var(--line-soft); vertical-align:middle; }
tbody th { font-weight:400; color:var(--ink); font-size:var(--t-body); padding:7px 8px 7px 0; border-bottom:1px solid var(--line-soft); }
th.n, td.n { text-align:right; font-variant-numeric:tabular-nums; }
td.n { white-space:nowrap; vertical-align:top; }
table.two th[scope=row] .cap { margin:2px 0 0; }
table.two td.n { width:5.5em; }
td.bar { width:30%; }
tr.fam th { padding-top:14px; font-weight:600; font-size:var(--t-cap); color:var(--ink); border-bottom:1px solid var(--line); }
.track { height:10px; background:var(--line-soft); border-radius:5px; overflow:hidden; }
.track i { display:block; height:100%; background:var(--blue-ink); border-radius:5px; }
.cols { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:0 40px; }
.flag { display:flex; gap:8px; align-items:flex-start; padding:10px 12px; border-radius:var(--radius-s); border:1px solid var(--warn-line); background:var(--warn-bg); color:var(--warn-ink); font-weight:600; }
.ok { display:flex; gap:8px; align-items:flex-start; padding:10px 12px; border-radius:var(--radius-s); background:var(--panel); }
.flag svg, .ok svg { flex:none; width:18px; height:18px; margin-top:1px; }
details.vd { margin:10px 0 0; }
details.vd > summary { cursor:pointer; color:var(--blue-ink); font-size:var(--t-cap); }
details.vd > summary:focus-visible, a:focus-visible { outline:2px solid var(--blue-ink); outline-offset:2px; }
.cap { color:var(--muted); font-size:var(--t-cap); margin:6px 0 0; }
.gov { margin:8px 0 0; padding-left:18px; font-size:var(--t-cap); }
.gov li { margin:2px 0; }
footer { padding:28px 0 64px; color:var(--muted); font-size:var(--t-cap); }
.empty { padding:28px 0 8px; }
.empty h2 { font-size:var(--t-title); }
.empty ol { margin:10px 0 0; padding-left:20px; }
.wk-table { font-size:var(--t-cap); table-layout:fixed; } .wk-table th, .wk-table td { padding-right:4px; overflow-wrap:anywhere; } .wk-table th:first-child { width:30%; }
@media (max-width:760px) {
  .hero { grid-template-columns:minmax(0,1fr); padding-top:18px; }
  .hero .fig { font-size:40px; }
  .cols { grid-template-columns:minmax(0,1fr); }
  td.bar, th.barh { display:none; }
  .bars { gap:2px; height:110px; }
  table { font-size:var(--t-cap); }
  tbody th { font-size:var(--t-cap); }
  td, th { padding-right:5px; }
}
"""

ICON_WARN = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/></svg>'
ICON_OK = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" d="M9 16.2 4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4z"/></svg>'
GOV = ["Pseudonymous, not anonymous: a record holds a user id (a code, no name or e-mail); the editors of the published page can read these records.",
       "Kept for 12 weeks: older weeks are removed from a person's record when they next open the page, and the owner also deletes records not seen for 12 weeks.",
       "The exported JSON file is deleted after the report is built. Screenshots of this page carry the same rules as the page.",
       "A group of 0 people prints as 0; a group of 1 to 4 prints as <5 users and its neighbours are withheld when a subtraction would reveal it. A percentage prints only when its denominator is 20 or more; below that the counts are printed with n=.",
       "Wording: say readers of a section, reach and people active. Never rank, name or evaluate people or teams, and never state a reason for a change: a change coincides with, or is associated with, something worth investigating."]


def e(x) -> str:
    return html.escape(str(x), quote=True)


def num(v, unit: str = "") -> str:
    """A figure for the page: the guard text when the group is small."""
    if v == SMALL:
        return e(SMALL)
    return "-" if v is None else e(f"{v:,}{unit}" if isinstance(v, int) else f"{v}{unit}")


def sh(x, d: int, th=THRESHOLDS) -> str:
    return e(share_text(x, d, th))


def il_stamp(as_of: dt.datetime | None) -> str:
    if not as_of:
        return ""
    t = as_of.astimezone(IL) if as_of.tzinfo else as_of
    return t.strftime("%Y-%m-%d %H:%M") + " Israel time"


def bar_cell(frac, track_ok: bool) -> str:
    return f'<td class="bar" aria-hidden="true">' + (f'<div class="track"><i style="width:{max(1.5, 100 * frac):.1f}%"></i></div>' if track_ok and frac is not None else "") + "</td>"


def _verdict_icon(state: str) -> str:
    return ICON_OK if state in ("growing", "flat") else ICON_WARN if state in ("falling",) else ""


def _chart_weeks(a: dict) -> str:
    rows = a["weeks"]
    comp = a["compared"]
    vis = [w["raw"] for w in rows if w["active"] != SMALL]
    top = max(vis + ([comp["raw_hi"]] if comp and comp.get("raw_hi") else []) + [1])
    cols, parts = [], []
    for w in rows:
        tip = f"{w['label']}: " + ("provisional, data starts mid-week, " if w["status"] == "provisional" else "so far this week, not comparable, " if w["status"] == "in_progress" else "") + (SMALL if w["active"] == SMALL else str(w["active"])) + " people"
        parts.append(tip)
        cls = " part" if w["status"] != "complete" else ""
        if w["active"] == SMALL:
            cols.append(f'<div class="gap" title="{e(tip)}"><i class="stub"></i></div>')
        elif w["raw"] == 0:
            cols.append(f'<div class="gap" title="{e(tip)}"><i class="dot"></i></div>')
        else:
            cols.append(f'<div class="d{cls}" style="height:{max(2.0, 100 * w["raw"] / top):.1f}%" title="{e(tip)}"></div>')
    band = ""
    if comp and comp.get("raw_hi") is not None:
        lo, hi = max(0, comp["raw_lo"]), min(top, comp["raw_hi"])
        band = f'<div class="band" style="bottom:{100 * lo / top:.1f}%;height:{max(1.0, 100 * (hi - lo) / top):.1f}%"></div>'
    first, last = rows[0]["label"], rows[-1]["label"]
    legend = "Bars: people active per Sunday-to-Saturday week. Hatched: not comparable (the first week of data when it starts mid-week, and the week in progress). Grey hatch: under 5 people. Dot: nobody." + (" Shaded band: the usual range of the previous completed weeks." if band else "")
    return (f'<div class="chartwrap"><div class="bars" role="img" aria-label="People active per week. {e("; ".join(parts))}">{band}{"".join(cols)}</div></div>'
            f'<div class="axis" aria-hidden="true"><span>{e(first)}</span><span>{e(last)}</span></div><p class="cap">{e(legend)}</p>')


def _week_table(a: dict) -> str:
    body = []
    for w in a["weeks"]:
        tag = "provisional: data starts mid-week" if w["status"] == "provisional" else "so far, not comparable" if w["status"] == "in_progress" else ""
        cells = "".join(f'<td class="n">{num(w[k]) if w[k] is not None else "-"}</td>' for k in ("new", "continuing", "reactivated", "lapsed"))
        body.append(f'<tr><th scope="row">{e(w["label"])}' + (f'<div class="cap">{e(tag)}</div>' if tag else "") + f'</th><td class="n">{num(w["active"])}</td>{cells}</tr>')
    return ('<table class="wk-table"><thead><tr><th scope="col">Week starting (Sunday)</th><th scope="col" class="n">People</th><th scope="col" class="n">New</th><th scope="col" class="n">Continuing</th><th scope="col" class="n">Back after a gap</th>'
            f'<th scope="col" class="n">Lapsed</th></tr></thead><tbody>{"".join(body)}</tbody></table>')


def _hero(a: dict) -> str:
    c, gv, au = a["compared"], a["growth"], a["audience"]
    th = a["model"].th
    if c:
        fig = num(c["active"])
        if c["state"] == "ok":
            where = ("above" if c["above"] else "below" if c["below"] else "inside")
            ctx = f"{e(c['label'])}. Usual: {e(c['median'])} (normal range {e(c['lo'])} to {e(c['hi'])}, median of the previous {c['n_weeks']} completed weeks). " + ("Inside the usual range." if where == "inside" else f"{where.capitalize()} the usual range.")
        else:
            ctx = f"{e(c['label'])}. Baseline building: {c['n_baseline']} of {th['baseline_min']} comparable completed weeks, so no usual range yet."
    else:
        fig = "-"
        ctx = "No completed week of data yet: the first comparable week ends on a Saturday after the data starts."
    if au:
        ctx += (f" {num(au['x'])} of an audience of {au['size']}" + (f" ({au['pct']}%)" if au["pct"] is not None else "") + ": a lower bound, because only people with edit access and an id are recorded." if au["x"] is not None else f" Audience of {au['size']} supplied.")
        if au["stale"]:
            ctx += " The audience size looks out of date: more people are in the data than in the audience."
    else:
        ctx += " Audience size not supplied, so no adoption percentage is shown."
    icon = _verdict_icon(gv["state"])
    return ('<section class="hero" aria-labelledby="h-hero"><div><h2 id="h-hero" class="what">People active in the last completed week</h2>'
            f'<p class="fig">{fig}</p><p class="ctx">{ctx}</p>'
            f'<p class="verdict" id="growth"><b>Is adoption growing?</b> {e(gv["text"])}</p></div><div>{_chart_weeks(a)}'
            f'<details class="vd"><summary>Show weekly data</summary>{_week_table(a)}</details></div></section>')


def _changed(a: dict) -> str:
    sg, c, th = a["signals"], a["compared"], a["model"].th
    if c:
        base = (f"median of the previous {c['n_weeks']} completed weeks, {c['median']}" if c["state"] == "ok" else f"building ({c['n_baseline']} of {th['baseline_min']} comparable weeks)")
        head = f"Compared week: {c['label']}, the last completed Sunday-to-Saturday week. {fmt_n(c['active'])} people active. Baseline: {base}."
    else:
        head = "No completed week of data to compare yet."
    out = ['<section class="blk" id="changed" aria-labelledby="h-changed"><h2 id="h-changed">What changed since last report</h2>'
           f'<p class="why">{e(head)} No previous report supplied; every flagged item is shown as new.</p>']
    if sg["flagged"]:
        shown = _shown_signals(sg, th)
        items = []
        for f in shown:
            items.append(f'<li class="sig" id="sig-{e(f["id"])}"><div class="sh"><strong>{e(f["headline"])}</strong><span class="tag">{e(f["confidence"])}</span><span class="sid">{e(f["id"])}</span></div>'
                         f'<p>{e(f["observation"])}</p><p class="small">What it does not show: {e(f["not_show"])}</p><p class="small">{e(f["next"])}</p>'
                         f'<details class="vd"><summary>Baseline and threshold</summary><p class="cap">Baseline: {e(f["baseline"])} Threshold: {e(f["threshold"])}</p></details></li>')
        out.append(f'<ol class="sigs">{"".join(items)}</ol>')
        if len(sg["flagged"]) > len(shown):
            out.append(f'<p class="cap">{len(sg["flagged"]) - len(shown)} more section or control signals are flagged: see the Checked list.</p>')
    else:
        out.append(f'<p class="ok" id="nothing">{ICON_OK}<span>{e(nothing_changed_text(sg))}</span></p>')
    n_f = sum(1 for r in sg["ledger"] if r["status"] == "flagged")
    n_w = sum(1 for r in sg["ledger"] if r["status"] == "within")
    n_n = sum(1 for r in sg["ledger"] if r["status"] in ("not_tested", "unknown"))
    rows = "".join(f'<tr><th scope="row">{e(r["id"])} {e(r["name"])}</th><td>{e(STATUS_WORD[r["status"]])}</td><td>{e(r["text"])}</td></tr>' for r in sg["ledger"])
    out.append(f'<details class="vd" id="checked"><summary>Checked: {n_f} flagged, {n_w} within range, {n_n} not tested or unknown</summary>'
               f'<table><thead><tr><th scope="col">Signal</th><th scope="col">Result</th><th scope="col">Numbers</th></tr></thead><tbody>{rows}</tbody></table>'
               '<p class="cap">Confidence labels: Confirmed (the same change in 3 consecutive weeks, or a fact about the export), Corroborated (2 consecutive weeks), Single-source (one week), Weak signal (one week with fewer than '
               f'{th["weak_active_people"]} active people, or a soft measure), Unknown (a figure under 5 people). This is not a statement that usage is healthy. It covers only people with an id and write access.</p></details></section>')
    return "".join(out)


def _return_block(a: dict) -> str:
    th = a["model"].th
    h, r = a["habit"], a["retention"]
    rows = []
    for key, label, when in (("w1", "Week 1", "a visit on a later day within 7 days of the first visit"), ("w4", "Week 4", "a visit in days 22 to 28 after the first visit")):
        x = r[key]
        res = "no eligible people yet" if not x["raw_n"] else sh(x["x"], x["raw_n"], th) + (" (indicative)" if x["indicative"] else "")
        rows.append(f'<tr><th scope="row">{label}: {e(when)}</th><td class="n">{num(x["n"])}</td><td class="n">{res}</td></tr>')
    hab = ""
    if h["state"] != "ok":
        hab = f'<p class="cap" id="habit">Habit: {e(h["text"])}</p>'
    else:
        nprint = h["n_print"]
        bins = h["bins"]
        mx = max([c for _, _, c in bins] + [1])
        lab = lambda lo, hi: f"{lo} week{'s' if lo != 1 else ''}" if lo == hi else f"{lo} to {hi} weeks"
        brow = "".join(f'<tr><th scope="row">{e(lab(lo, hi))}</th>{bar_cell(c / mx, True)}<td class="n">{num(c)}</td></tr>' for lo, hi, c in bins) if nprint != SMALL else ""
        hab = (f'<h3>Habit</h3><p id="habit">{sh(h["x"], h["n"], th) if nprint != SMALL else e(SMALL)} of {num(nprint)} established people were active in {h["min_weeks"]} or more of the last {h["weeks"]} completed weeks ({e(h["window"])}). '
               'Established = first seen at least 14 days before the compared week.</p>'
               + (f'<table><thead><tr><th scope="col">Weeks active</th><th scope="col" class="barh" aria-hidden="true"></th><th scope="col" class="n">People</th></tr></thead><tbody>{brow}</tbody></table><p class="cap">Neighbouring groups are merged until each has at least 5 people.</p>' if brow else ""))
    return ('<section class="blk" aria-labelledby="h-back"><h2 id="h-back">Do people come back?</h2>'
            '<p class="why">Retention follows people first seen at least 7 (or 28) days ago; people that arrived later are not in the figure yet, and people first seen before the go-live day or before the 12 weeks kept are not in a cohort. '
            'Use it to see whether newcomers stay; never to judge a person or a team.</p>'
            f'<table id="retention"><thead><tr><th scope="col">Retention</th><th scope="col" class="n">Eligible people</th><th scope="col" class="n">Came back</th></tr></thead><tbody>{"".join(rows)}</tbody></table>{hab}</section>')


def _read_block(a: dict) -> str:
    th = a["model"].th
    s = a["sections"]
    if not s["n"]:
        return '<section class="blk" aria-labelledby="h-read"><h2 id="h-read">What people read</h2><p class="why">No completed week to report on yet.</p></section>'
    mx = max([r["raw"] for r in s["rows"]] + [1])
    body = []
    for r in s["rows"]:
        draw = not r["under5"] and r["raw"] > 0
        cand = f' <span class="tag">{e(r["candidate"])}</span>' if r["candidate"] else ""
        nm = e(r["name"]) + (" (reach under 5 people: Unknown)" if r["under5"] else "")
        body.append(f'<tr><th scope="row">{nm}{cand}</th>{bar_cell(r["raw"] / mx, draw)}<td class="n">{sh(r["reach"], s["d"], th)}</td><td class="n">{num(r["nav"]) if r["nav"] is not None else "-"}</td>'
                    f'<td class="n">{num(r["links"])}</td><td class="n">{num(r["share"], "%") if r["share"] is not None else "-"}</td></tr>')
    ol = ", ".join(f"{DISCLOSURES[k]}: {num(v)}" for k, v in s["disclosures"].items())
    return (f'<section class="blk" aria-labelledby="h-read"><h2 id="h-read">What people read</h2>'
            f'<p class="why">Reach: people with 30 seconds or more in a section in a week, of the {num(s["n_g"])} people active in the last {s["weeks"]} completed weeks ({e(a["window"]["label"])}). Sections are in page order, not ranked. '
            'A section read by few people can be right for them: this is a prompt to look, not a verdict. Scroll position decides which section gets the time, so reading time is a secondary column.</p>'
            '<table id="reach"><thead><tr><th scope="col">Section</th><th scope="col" class="barh" aria-hidden="true"></th><th scope="col" class="n">Reach</th><th scope="col" class="n">Section Strip</th><th scope="col" class="n">Jira links</th>'
            f'<th scope="col" class="n">Reading time</th></tr></thead><tbody>{"".join(body)}</tbody></table>'
            f'<p class="cap">Section Strip and Jira links: people using the strip or the skip links to jump to the section, or following a Jira link from it (a person is counted once). Reading time: each person\'s own split, averaged over the sections shown. '
            f'A section with fewer than 5 readers shows &lt;5 users and is left out of that share. Simplify candidates: {e(s["candidates"]["status"])}. Details opened (people): {ol}.</p></section>')


def _use_block(a: dict) -> str:
    th = a["model"].th
    c, u = a["controls"], a["use"]
    if not c["n"]:
        return '<section class="blk" aria-labelledby="h-use"><h2 id="h-use">What people use</h2><p class="why">No completed week to report on yet.</p></section>'
    mx = max([r["raw"] for f in c["families"] for r in f["rows"]] + [1])
    body = []
    for f in c["families"]:
        body.append(f'<tr class="fam"><th scope="colgroup" colspan="3">{e(f["family"])}</th></tr>')
        for r in f["rows"]:
            body.append(f'<tr><th scope="row">{e(r["name"])}</th>{bar_cell(r["raw"] / mx, r["raw"] >= MIN_USERS)}<td class="n">{sh(r["reach"], c["d"], th)}</td></tr>')
    rs = c["reset"]
    reset = ("Not recorded in v1 records." if rs["state"] == "none" else f"{sh(rs['x'], rs['visits_g'], th)} of visits with a control change also pressed Reset Filters in the same visit ({nlabel(rs['visits_g'])})." + (" Flag: 25% or more in 2 consecutive weeks." if rs.get("flag") else ""))
    mv, pj = c["multi_vs_projects"]
    lk = u["links"]
    fr = u["fresh"]

    def fresh_line(k):
        f = fr.get(k)
        if not f:
            return "not recorded in v1 records"
        txt = ", ".join(f"{nm}: " + (SMALL if cell == SMALL else (f"{f['shares'][nm]}%" if f["shares"][nm] is not None else str(cell))) for nm, cell in f["cells"].items())
        return txt + (f" (share of the {fmt_n(f['n_g'])} visits shown; rows under 5 people are left out)" if f["hidden"] else f" ({nlabel(f['n_g'])} visits)")
    ro = u["refresh"]["outcomes"]
    refresh_out = ("Outcomes: " + "; ".join(f"{RO[k]} {cnt(v['people'], 'people')}" for k, v in ro.items()) + f"; automatic retries {fmt_n(u['refresh']['retries'])}") if u["refresh"]["has_v2"] else "Outcomes are not recorded in v1 records"
    link_secs = "; ".join(f"{s['name']}: {s['pct']}% of engaged visits, {s['status']}" for s in lk["sections"] if s["pct"] is not None) or f"no section has {th['link_min_clicks']} clicks from {th['link_min_people']} people yet"
    mn = u["minutes"]
    rows = [
        ("Median active minutes among engaged visits (30 s or more, or with input)", (num(mn["median"]) + " min") if mn["median"] not in (None, SMALL) else (num(mn["median"]) if mn["median"] == SMALL else "-"), f"over {num(mn['visits'])} engaged visits with some active time ({num(mn['people'])} people). Glance visits are reported under Recording health"),
        ("Engaged visits per active person", num(u["per_person"]["value"]), f"in {u['weeks']} weeks, of {num(u['per_person']['n'])} active people: a count of visits, not a measure of value"),
        ("Visits with a Jira link click", (f"{lk['pct']}%" if lk["pct"] is not None else num(lk["visits"])) if lk["x"] != SMALL else e(SMALL), f"of {fmt_n(u['engaged_g'])} engaged visits had a Jira link click, by {num(lk['x'])} people. By section: {e(link_secs)}"),
        ("Small-screen share", sh(u["phone"]["x"], u["phone"]["n_g"], th), f"of {fmt_n(u['phone']['n_g'])} engaged visits with a width recorded"),
        ("Refresh pressed by", sh(u["refresh"]["x"], u["refresh"]["n_g"], th), f"of {fmt_n(u['refresh']['n_g'])} active people. {e(refresh_out)}"),
        ("Connection at the visit", "-", e(fresh_line("lv"))),
        ("Age of the data at the start", "-", e(fresh_line("fa"))),
    ]
    trs = "".join(f'<tr><th scope="row">{e(n)}<div class="cap">{d}</div></th><td class="n">{v}</td></tr>' for n, v, d in rows)
    return ('<section class="blk" aria-labelledby="h-use"><h2 id="h-use">What people use</h2>'
            f'<p class="why">Reach of each control among the {num(c["n_g"])} people active in the last {c["weeks"]} completed weeks ({e(a["window"]["label"])}): people that changed it at least once. Fixed page order, grouped by family; not ranked. '
            f'Any control: {sh(c["any"]["x"], c["d"], th)}. Multi-select toggle: {num(mv)} people; Projects: {num(pj)} people. {e(reset)}</p>'
            f'<table id="controls"><thead><tr><th scope="col">Control</th><th scope="col" class="barh" aria-hidden="true"></th><th scope="col" class="n">Reach</th></tr></thead><tbody>{"".join(body)}</tbody></table>'
            f'<h3>How people use it</h3><table id="usage" class="two"><thead><tr><th scope="col">Measure and basis</th><th scope="col" class="n">Result</th></tr></thead><tbody>{trs}</tbody></table>'
            '<p class="cap">Engaged visits = 30 seconds or more, or with input. A control or link count is a count of people, not of effect. Do not use these figures to compare teams.</p></section>')


def _chart_days(a: dict) -> str:
    dv = a["daily"]
    days = dv["days"]
    vis = [d["raw"] for d in days if d["users"] != SMALL]
    top = max(vis + [1])
    mark_by_day = {}
    for d, label, kind in dv["marks"]:
        mark_by_day.setdefault(d, []).append((label, kind))
    cols, mrow, parts = [], [], []
    for d in days:
        we = " we" if d["weekend"] else ""
        state = ("before the data starts" if not d["has_data"] else SMALL if d["users"] == SMALL else str(d["raw"])) + (" (so far today, not comparable)" if d["partial"] else "") + (" (Friday or Saturday)" if d["weekend"] else "")
        tip = f"{d['day']:%a %d %b}: {state}"
        parts.append(tip)
        if not d["has_data"]:
            cols.append(f'<div class="gap{we}" title="{e(tip)}"></div>')
        elif d["users"] == SMALL:
            cols.append(f'<div class="gap{we}" title="{e(tip)}"><i class="stub"></i></div>')
        elif d["raw"] == 0:
            cols.append(f'<div class="gap{we}" title="{e(tip)}"><i class="dot"></i></div>')
        else:
            cols.append(f'<div class="d{we}{" part" if d["partial"] else ""}" style="height:{max(2.0, 100 * d["raw"] / top):.1f}%" title="{e(tip)}"></div>')
        mk = mark_by_day.get(d["day"])
        mrow.append(f'<span class="{mk[0][1]}">&#9650;</span>' if mk else "<span></span>")
    return (f'<div class="chartwrap"><div class="bars" role="img" aria-label="People per day, last 28 days. {e("; ".join(parts))}">{"".join(cols)}</div></div>'
            f'<div class="marks" aria-hidden="true">{"".join(mrow)}</div>'
            f'<div class="axis" aria-hidden="true"><span>{d_label(days[0]["day"])}</span><span>most in one day: {top}</span><span>{d_label(days[-1]["day"])}</span></div>')


def _rhythm_block(a: dict) -> str:
    dv = a["daily"]
    mk = "".join(f"<li>{d_label(d)}: {e(label)}</li>" for d, label, _ in dv["marks"])
    ww = f'Sunday to Thursday had {dv["workweek"]["pct"]}% of the {dv["workweek"]["n"]} visits in the last 28 days. ' if dv["workweek"] else ""
    note = (e(dv["note"]) + " ") if dv["note"] else ""
    evt = (e(dv["events"]["text"]) + " ") if dv["events"] else ""
    table = ("<details class=\"vd\"><summary>Show data</summary><table><thead><tr><th scope=\"col\">Day</th><th scope=\"col\" class=\"n\">People</th></tr></thead><tbody>"
             + "".join(f'<tr><td>{d["day"].isoformat()}{" (so far today, not comparable)" if d["partial"] else ""}</td><td class="n">{"before the data starts" if not d["has_data"] else num(d["users"])}</td></tr>' for d in reversed(dv["days"])) + "</tbody></table></details>")
    return ('<section class="blk" aria-labelledby="h-daily"><h2 id="h-daily">People per day, last 28 days</h2>'
            f'<p class="why">{e(ww)}Distinct people with a visit that day. Hatched blue: today so far, not comparable. Grey hatch: under 5 people. Dot: nobody. Blank: before the data starts. Lighter columns: Friday and Saturday, never part of a baseline. {note}{evt}</p>'
            f'{_chart_days(a)}' + (f'<ul class="gov" aria-label="Calendar marks">{mk}</ul>' if mk else "") + table + "</section>")


def _health_block(a: dict) -> str:
    th = a["model"].th
    h = a["health"]
    rows = [("Visits in the data", f"{fmt_n(h['visits_g'])}", f"{fmt_n(h['v2_g'])} from the newer page, {num(h['v1_visits'])} from the earlier page ({num(h['v1_people'])} people)")]
    if h["has_v2"]:
        gl = h["glance"]
        rows += [("Glance visits", sh(gl["x"], gl["n_g"], th), f"of {fmt_n(gl['n_g'])} visits; engaged visits {num(gl['engaged'])}. A glance is 5 seconds or more with no input and under 30 seconds. Engaged = 30 seconds or more, or with input."),
                 ("Visible, no active seconds", sh(h["focus"]["x"], h["focus"]["n_g"], th), "visits with visible time but no active seconds: a high share points at a focus problem in the page frame, not at idle readers"),
                 ("Real page errors", sh(h["errors_real"]["x"], h["errors_real"]["n_g"], th), "of visits (v2 pages)"),
                 ("Benign notifications", sh(h["errors_benign"]["x"], h["errors_benign"]["n_g"], th), "counted apart and never flagged")]
    else:
        rows.append(("Glance visits, focus, benign errors", "-", "not recorded in v1 records: the data holds only the earlier page's visits, so adoption is probably under-counted"))
    rows += [("Visits that dropped keys", sh(h["dropped"]["x"], h["dropped"]["n_g"], th), "at the 40-key cap"),
             ("Active time attributed to a section", num(h["attributed"], "%") if h["attributed"] is not None else "-", "of active seconds"),
             ("Records not opened for over 12 weeks", num(h["stale_records"]), f"their weeks are left out; delete them. {h['stale_sessions']} sessions older than 12 weeks were ignored"),
             ("Records cut by the size cap", num(h["pruned_records"]), "older weeks dropped to keep a record small")]
    trs = "".join(f'<tr><th scope="row">{e(n)}<div class="cap">{e(d)}</div></th><td class="n">{v}</td></tr>' for n, v, d in rows)
    return ('<section class="blk" aria-labelledby="h-health"><h2 id="h-health">Recording health</h2><p class="why">Can the measurement itself be trusted? These figures describe how the page recorded visits, not how people use it.</p>'
            f'<table id="health" class="two"><thead><tr><th scope="col">Check and reading</th><th scope="col" class="n">Result</th></tr></thead><tbody>{trs}</tbody></table></section>')


def _measure_block() -> str:
    return ('<section class="blk" aria-labelledby="h-how"><h2 id="h-how">How this is measured</h2>'
            f'<ul class="gov" id="governance">{"".join(f"<li>{e(x)}</li>" for x in GOV)}</ul>'
            '<details class="vd" id="how"><summary>What is counted and what is not</summary>'
            '<p class="cap">The published Delivery Pulse page counts, for each person with an id, which sections they read, which filters and buttons they use, which Jira links they follow (by section only), how long the page is open in front of them and in use, '
            'their screen size, the page version, how fresh the data was and page errors. It records no names, e-mail addresses, issue keys, project, team or pod names or search text. People that are signed out or hold view-only access, that open an offline copy, '
            'or whose browser blocks the page&#39;s storage are not counted, so these are counts of people with an id, not of all visitors. A visit that is only looked at for 5 seconds or more is recorded as a glance; a visit with input or 30 seconds or more is an engaged visit. '
            f'Weeks run Sunday to Saturday and count as complete once Saturday has passed. Any figure that rests on fewer than {MIN_USERS} people shows "&lt;5 users". Weeks before the first record show "before the data starts", not zero. '
            'This page is a snapshot of an export, not a live view.</p></details></section>')


def html_report(a: dict, standalone: bool = False) -> str:
    """The page: an Artifact fragment (own title, inline style, no script). Order: coverage ribbon, the hero (people active in the last completed week and the growth verdict), what changed since last report, the adoption views,
    what people read and use, the daily rhythm with calendar notes, recording health, how this is measured."""
    stamp = il_stamp(a["as_of"]) or f"{a['ref']} (no export time given)"
    out: list = []
    add = out.append
    add('<title>Delivery Pulse Usage</title>\n<meta name="claude:viewport-fit-sides" content="cover">\n<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600&display=swap">')
    add(f"<style>{CSS}</style>")
    add(f'<header class="top gutter"><h1>Delivery Pulse Usage</h1><span class="stamp" id="asof">Data as of {e(stamp)}</span></header>')
    add('<main class="gutter">')
    if a["demo"]:
        add('<p class="demo" id="demo-banner" role="note">Demo data: this page shows fictitious people and numbers so the layout can be reviewed. It says nothing about real use.</p>')
    for w in export_warnings(a):
        add(f'<p class="warn" role="status">{ICON_WARN}<span>{e(w)}</span></p>')
    add(f'<p class="ribbon" id="coverage"><b>Coverage.</b> {e(coverage_text(a))}</p>')
    if not a["n_sessions"]:
        add('<section class="empty" id="empty" aria-labelledby="h-empty"><h2 id="h-empty">No usage recorded yet</h2>'
            '<p>The export holds no visit that this report can use, so there is nothing to show. Nothing on this page is an estimate.</p>'
            '<ol><li>Open the published Delivery Pulse page as a person with edit access and use it for 30 seconds.</li>'
            '<li>Export the documents of the collection <code>usage</code> with the ArtifactData tool.</li>'
            '<li>Run this report on that file with <code>--as-of</code> set to the export time (and <code>--since</code> to the go-live day).</li></ol></section>')
        if a["stats"].get("unknown_schema") or a["stats"].get("skipped") or a["counts"]["stale_sessions"]:
            add('<p class="cap">Some documents were skipped or are older than 12 weeks: see the warning above or the text report.</p>')
    else:
        if a["history_days"] < SHORT_HISTORY_DAYS:
            add(f'<p class="note" id="caveat">Only {a["history_days"]} days of data so far: trends are not meaningful yet.</p>')
        add(_hero(a))
        add(_changed(a))
        add(_return_block(a))
        add(_read_block(a))
        add(_use_block(a))
        add(_rhythm_block(a))
        add(_health_block(a))
    add(_measure_block())
    add("</main>")
    add('<footer class="gutter">Delivery Pulse Usage. Counts only: this page never contains a user id.</footer>')
    frag = "\n".join(out)
    if standalone:
        return '<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1"></head><body>' + frag + "</body></html>"
    return frag


# ------------------------------------------------------------------------------------------------------------ command line
def parse_as_of(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=IL)


def load_thresholds(path: str | None) -> dict:
    th = dict(THRESHOLDS)
    if path:
        over = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(over, dict):
            raise ValueError("the thresholds file must be a JSON object")
        for k, v in over.items():
            if k not in THRESHOLDS:
                raise ValueError(f"unknown threshold {k!r}; known: {', '.join(sorted(THRESHOLDS))}")
            if not is_num(v):
                raise ValueError(f"threshold {k!r} must be a number")
            th[k] = v
    return th


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("file", nargs="?", help="the exported documents (JSON)")
    ap.add_argument("--html", help="write the dashboard page (an Artifact fragment) to this file")
    ap.add_argument("--standalone", action="store_true", help="wrap the page in a full document so it opens in a browser as a file")
    ap.add_argument("--as-of", help="when the data was exported, ISO (the day of the data and the 'Data as of' stamp). Without it the export is read as taken now and the page says no export time was given")
    ap.add_argument("--today", help="YYYY-MM-DD, the Israel day the report is made (default: the current one); it is never taken from the last day in the data")
    ap.add_argument("--since", help="YYYY-MM-DD, the go-live day: earlier days (the Sandbox) are ignored and the weeks before it read 'before the data starts'")
    ap.add_argument("--audience", type=int, help="the size of the intended audience (optional): adds an adoption line with a lower-bound note; without it no adoption percentage is shown")
    ap.add_argument("--thresholds", help="a JSON file overriding THRESHOLDS (unknown keys are an error)")
    ap.add_argument("--calendar", help="usage_calendar.json from `build_dashboard.py --emit-usage-calendar`, optionally with owner `events` (dates) and `quiet_weeks` (dates)")
    ap.add_argument("--demo", action="store_true", help="use a fictitious data set (about 50 people, 11 completed weeks, built to exercise the failure modes) and show a Demo data banner")
    ap.add_argument("--text", action="store_true", help="also print the text report when --html is given")
    a = ap.parse_args(argv)
    now = dt.datetime.now(IL)
    as_of = parse_as_of(a.as_of)
    today = dt.date.fromisoformat(a.today) if a.today else None
    since = dt.date.fromisoformat(a.since) if a.since else None
    th = load_thresholds(a.thresholds)
    cal = parse_calendar(json.loads(Path(a.calendar).read_text(encoding="utf-8"))) if a.calendar else None
    stats = None
    if a.demo:
        today = today or now.date()
        as_of = as_of or (now - dt.timedelta(days=4))                                    # the demo export is stale on purpose: the warning shows
        ref = as_of.astimezone(IL).date()
        bodies = demo_bodies(ref)
        cal = cal or parse_calendar(demo_calendar(ref))
    else:
        if not a.file:
            ap.error("give the exported JSON file, or --demo")
        bodies, stats = load_export(json.loads(Path(a.file).read_text(encoding="utf-8")))
    agg = aggregate(bodies, today, as_of, now, demo=a.demo, since=since, audience=a.audience, calendar=cal, th=th, stats=stats)
    if a.html:
        Path(a.html).write_text(html_report(agg, standalone=a.standalone), encoding="utf-8")
        print(f"wrote {a.html} ({agg['n_docs']} user records, {agg['n_sessions']} sessions)")
    if not a.html or a.text:
        sys.stdout.write(text_report(agg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
