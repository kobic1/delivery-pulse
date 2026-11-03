#!/usr/bin/env python3
"""Owner report for the Delivery Pulse usage statistics: an aggregate text report and a self-contained dashboard page ("Delivery Pulse Usage").

The published Delivery Pulse page keeps one small record per person, `usage/<opaque user id>`, in its own artifact database (see the "Usage statistics" section of
program_dashboard/README.md for the record, the vocabulary and the access rules). Export those documents with the ArtifactData tool (`list`, collection `usage`) into a JSON file and run:

    python3 program_dashboard/usage_report.py export.json --as-of 2026-11-02T10:15:00+02:00        # text report on the screen
    python3 program_dashboard/usage_report.py export.json --html usage.html --as-of ... --since 2026-10-14 --audience 120 --calendar build/usage_calendar.json
    python3 program_dashboard/usage_report.py --demo --html usage_demo.html --standalone            # the same page from fictitious data (a "Demo data" banner), to review the layout

Options: --min-group N (the smallest group of people a number is shown for, default 5), --since YYYY-MM-DD (the go-live day: earlier days are the Sandbox and are ignored), --audience N (the size of the intended audience: without it the page shows no adoption percentage),
--thresholds file.json (overrides of THRESHOLDS), --calendar usage_calendar.json (from `build_dashboard.py --emit-usage-calendar`: release milestones, sprint boundaries, optional owner review days and quiet weeks),
--as-of (when the export was taken; without it the current Israel date is used and the page says that no export time was given), --today (the Israel day to report about, default the current one).

The input is a JSON list of the documents. Both shapes are accepted: the bodies themselves, or {"id": ..., "data": {body}} rows (also "doc_id"/"data", and a wrapper object holding the list under
"documents", "docs", "items", "rows" or "results"). The id of a document is read ONLY to drop a duplicated document (it is hashed in memory and then forgotten); users are told apart by their position in the file,
and no user id, name, e-mail address, issue key or team name is ever printed or written to the page. A record is "pseudonymous, not anonymous": the editors of the published page can read the ids.

Privacy rule of the report (the minimum group size is 5 by default; --min-group N or the `min_group` threshold changes it, 1 shows every number as it is, and every sentence of the page and of the text report then says the setting in force): every breakdown that rests on fewer than 5 distinct people prints "<5 users" instead of a number (and its chart bar is not drawn); a figure that would reveal such a group by subtraction
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

MIN_USERS = 5                                                                         # the minimum group size (THRESHOLDS["min_group"]; set_min_group changes it for a run): a group of fewer people is withheld
SMALL = f"<{MIN_USERS} users"                                                         # what a withheld figure prints
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
    # privacy: the smallest group of distinct people the report shows a number for. 5 is the safe default; 1 shows every number as it is (a page for its owner alone: with few people the numbers describe individual visits).
    # The statistical guards (a percentage needs 20 in the denominator, a baseline 5 completed weeks, a weak signal under 30 active people, a growth verdict 6 weeks) are separate and do not move with it.
    "min_group": 5,
    # --show-all: what the views are drawn from and when they are drawn at all
    "show_partial_week": 0,             # 1: the views (section and control reach, devices, freshness, the day-and-hour map, the page version) include the week in progress, to date, besides the completed weeks
    "heatmap_min_visits": 50,           # engaged visits with a recorded opening time needed before the day-and-hour map is drawn
}


def set_min_group(n) -> None:
    """Set the minimum group size for the run (an integer of 1 or more): every guard (g, gn, protect_group, partition_cells, the charts) and every sentence about it reads the module values set here.
    aggregate, text_report and html_report call it with the setting of the thresholds they were given, so a report is always printed with the setting it was computed with."""
    global MIN_USERS, SMALL
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise ValueError("min_group must be a whole number of 1 or more")
    MIN_USERS = n
    SMALL = f"<{n} users"


def guard_note(template: str) -> str:
    """A sentence about the withheld groups ('{n}' = the minimum group size, '{g}' = the guard text): empty when the minimum is 1, because then no group is withheld."""
    return template.replace("{n}", str(MIN_USERS)).replace("{g}", SMALL) if MIN_USERS > 1 else ""


def small_rule(cap: bool = False, ribbon: bool = False) -> str:
    """The sentence that says what the small-group setting is, true for the setting in force."""
    if MIN_USERS <= 1:
        t = "small groups are shown as they are: with few people these numbers describe individual visits, so keep this page private and do not share screenshots of it."
        return t[0].upper() + t[1:] if cap or ribbon else t
    t = f"groups under {MIN_USERS} people {'show' if ribbon else 'print'} {SMALL}."
    return t[0].upper() + t[1:] if cap or ribbon else t

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
        "t": "opened at: v1 minutes since the epoch (not read by this report), (v2) hours since the epoch (UTC): read only for the hour of the day (Israel time) of the day-and-hour chart",
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
DEVICES = {"s": "Phone (narrow window)", "m": "Tablet (medium window)", "l": "Desktop (wide window)"}         # the page records the browser window width: 's' up to 480 px, 'm' up to 900 px, 'l' wider
DEVICE_ORDER = ("l", "m", "s")
DEVICE_CAVEAT = "By browser window width, not device type: a narrow desktop window counts as phone."
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
    return f"n={v}" if v != SMALL else f"count withheld: fewer than {MIN_USERS} people"


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
    wk = m.weeks[-k:] if m.weeks else []
    if m.th["show_partial_week"] and m.cur in m.by_week and m.cur not in wk:
        wk = wk + [m.cur]                                                           # the week in progress, to date
    return wk


def _weeks_phrase(m: Model, n: int) -> str:
    """'the last 4 completed weeks', or with --show-all 'the last 3 completed weeks and the week so far'; with no completed week 'the week so far'."""
    partial = bool(m.th["show_partial_week"] and m.cur in m.by_week)
    done = n - 1 if partial else n
    if not done:
        return "the week so far"
    return f"the last {done} completed week{'' if done == 1 else 's'}" + (" and the week so far" if partial else "")


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
            f"Newly used: under {MIN_USERS} people in every comparable week before." if new else f"Stopped: {th['s4_stop_pct']}% or more of established people in {th['s4_stop_weeks']} of the baseline weeks.",
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
    set_min_group(th.get("min_group", 5))
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
        "window": {"weeks": len(wk), "lo": wk[0] if wk else None, "hi": min(wk[-1] + dt.timedelta(days=6), ref) if wk else None, "label": f"{d_label(wk[0])} to {d_label(min(wk[-1] + dt.timedelta(days=6), ref))}" if wk else ""},
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


DEMO_HOUR_WEIGHTS = {7: 2, 8: 8, 9: 14, 10: 16, 11: 14, 12: 7, 13: 8, 14: 13, 15: 14, 16: 10, 17: 5, 18: 2, 19: 1}      # the opening hour of a demo visit (Israel time): a working day with a morning and an afternoon peak


def demo_open_hour(day: dt.date, rnd_: random.Random) -> int:
    """The `t` of a v2 session: hours since the epoch (UTC) of an opening hour drawn for the day."""
    hour = rnd_.choices(list(DEMO_HOUR_WEIGHTS), weights=list(DEMO_HOUR_WEIGHTS.values()))[0]
    local = dt.datetime(day.year, day.month, day.day, hour, 30, tzinfo=IL)
    return int(local.astimezone(dt.timezone.utc).timestamp() // 3600)


def demo_bodies(ref: dt.date, seed: int = 20261102, v2_from: int = 3) -> list:
    """About 50 fictitious people over 11 completed weeks and the week in progress, built to exercise the failure modes: the first week starts mid-week (provisional), the oldest weeks are v1 records and the rest v2
    (a mixture, with a rollover week), a lapsed group of regulars, a growing group of new people, a quiet week below 20 active people, one build with a single error, a section whose reach drops, a control newly used and one no longer used.
    v2_from: the index of the first v2 week (0 to 10; 99 = every week is a v1 record, the page of a data set from before the upgrade).
    Ids are u_synthetic_NNN; a few sections and controls are used by only a few people so that the small-group guard shows."""
    r = random.Random(seed)
    rt = random.Random(seed + 1)                                                         # the opening hours of the visits: a separate generator so that every other number of the demo is unchanged
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
                    if v2:
                        s["t"] = demo_open_hour(day, rt)                           # a plausible opening hour (Israel time) from its own generator: the numbers drawn above stay as they were
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

def coverage_not_counted() -> str:
    return ("Not counted: people signed out, with view-only access, using an offline copy or whose browser blocks storage. Includes the owner's and testers' visits. Aggregate counts only; " + small_rule() + " Never used to rank or assess people or teams.")


def fmt_date(d: dt.date) -> str:
    return f"{d.day} {d:%b %Y}"


def _who(a: dict) -> str:
    n = a["n_people"]["n"]
    return f"fewer than {MIN_USERS} people" if n == SMALL else (f"{n} person" if n == 1 else f"{n} people")


def coverage_text(a: dict) -> str:
    who = _who(a)
    span = f" between {fmt_date(a['first_day'])} and {fmt_date(a['last_day'])} (Israel time)" if a["first_day"] else ""
    aud = ""
    if a["audience"]:
        aud = f", of an audience of {a['audience']['size']} (a lower bound: only people with edit access and an id are recorded)"
    return f"Based on {who} with an id{span}{aud}. {coverage_not_counted()}"


def text_report(a: dict) -> str:
    """The aggregate text report: the same numbers as the page, in the same order (coverage, what changed, adoption, reading, use, rhythm, recording health). Nothing here names a person."""
    set_min_group(a["model"].th.get("min_group", 5))
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
    add(f"\nWhat people read: reach in {_weeks_phrase(a['model'], sv['weeks'])}, {fmt_n(sv['n_g'])} active people (in page order, not ranked)")
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
    dev_lines = device_period_lines(a)
    if dev_lines:
        lbl, dc = dev_lines[0]
        dv = device_card(dc, a["model"].th)
        add(f"  Device ({lbl}): " + ("no browser window width recorded" if dv["state"] == "none" else SMALL if dv["state"] == "hidden" else f"{dv['fig']}; {dv['sub']}"))
        add(f"  {DEVICE_CAVEAT}")
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


# ------------------------------------------------------------------------------------------------------------ the dashboard page (graph first)
# Order, as in an analytics report: key figures (scorecards), the trend, the breakdowns, the detail (the signals S0 to S9 are in the text report, not on the page); every chart has a one-line caption and a "Show data" table behind it.
# The charts are HTML and CSS with a little inline SVG (lines and sparklines): the text of a chart is real text, so it stays readable at 390 px. A chart is one role="img" with a label that holds its numbers.
CSS = """
:root {
  --bg:#FFFFFF; --panel:#F2F0EB; --ink:#21212B; --muted:#5A5F6B; --line:#DAD7D0; --line-soft:#ECEAE5; --ctl:#767B86;
  --blue:#3694FC; --blue-ink:#025AFB; --blue-tint:#E4F0FF; --teal-ink:#1C7A6C; --coral-ink:#B3234F; --indigo:#6100FF;
  --seq1:#E4F0FF; --seq2:#BCD9FE; --seq3:#7FB5FD; --seq4:#3694FC; --seq5:#025AFB;
  --amber:#C77700; --amber-ink:#8A5200; --warn-bg:#FFF6E5; --warn-line:#F0D9A8; --warn-ink:#6B4A00;
  --radius:12px; --radius-s:8px;
  --hatch:repeating-linear-gradient(135deg,#767B86 0 2px,#FFFFFF 2px 5px);
  --hatch-blue:repeating-linear-gradient(135deg,#025AFB 0 3px,#FFFFFF 3px 6px);
  --font:'Be Vietnam Pro', Arial, 'Segoe UI', -apple-system, sans-serif;
  --t-xs:12px; --t-cap:13px; --t-body:14px; --t-sub:16px; --t-title:20px;
  color-scheme:light;
}
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font-family:var(--font); font-size:var(--t-body); font-weight:400; line-height:1.5; }
.gutter { max-width:1180px; margin:0 auto; padding-left:max(16px, env(safe-area-inset-left, 0px)); padding-right:max(16px, env(safe-area-inset-right, 0px)); }
a { color:var(--blue-ink); }
h1 { font-size:var(--t-title); font-weight:600; line-height:1.25; margin:0; }
h2 { font-size:var(--t-sub); font-weight:600; line-height:1.3; margin:0 0 6px; }
h3 { font-size:var(--t-sub); font-weight:600; line-height:1.3; margin:0 0 2px; }
.top { padding-top:20px; display:flex; flex-wrap:wrap; align-items:baseline; gap:2px 16px; }
.stamp, .period { color:var(--muted); font-size:var(--t-cap); }
.demo { margin:12px 0 0; padding:8px 12px; background:var(--warn-bg); border:1px solid var(--warn-line); border-radius:var(--radius-s); color:var(--warn-ink); font-weight:600; font-size:var(--t-body); }
.warn { display:flex; gap:8px; align-items:flex-start; margin:12px 0 0; padding:8px 12px; background:var(--warn-bg); border:1px solid var(--warn-line); border-radius:var(--radius-s); color:var(--warn-ink); font-weight:600; }
.warn svg { flex:none; width:18px; height:18px; margin-top:2px; }
.ribbon { margin:12px 0 0; padding:8px 12px; background:var(--panel); border-radius:var(--radius-s); font-size:var(--t-cap); color:var(--ink); }
.note { margin:12px 0 0; padding:8px 12px; background:var(--panel); border-radius:var(--radius-s); font-size:var(--t-body); }
section.blk { padding:28px 0 0; }
section.blk > h2 { font-size:var(--t-sub); margin:0 0 8px; }
.cap { color:var(--muted); font-size:var(--t-cap); margin:0 0 10px; }
.cap.after { margin:8px 0 0; }
.small { color:var(--muted); font-size:var(--t-cap); }
/* key figures: one strip with hairline dividers, the first figure is the hero */
.kpis { display:grid; grid-template-columns:minmax(0,1.4fr) repeat(5,minmax(0,1fr)); gap:1px; background:var(--line); border:1px solid var(--line); border-radius:var(--radius); overflow:hidden; }
.kpi { background:var(--bg); padding:14px 16px 12px; display:flex; flex-direction:column; min-width:0; }
.kpi h3 { font-size:var(--t-cap); font-weight:500; color:var(--muted); margin:0; }
.kpi .fig { font-size:30px; font-weight:600; line-height:1.15; font-variant-numeric:tabular-nums; margin:4px 0 0; }
.kpi.hero .fig { font-size:52px; line-height:1.05; }
.kpi#kpi-device { grid-column:span 2; }
.kpi .fig.sm { font-size:21px; line-height:1.25; margin-top:6px; }
.kpi { container-type:inline-size; }
.dwrap { display:flex; flex-direction:column; align-items:flex-start; gap:6px; }
.donut { position:relative; width:96px; height:96px; flex:none; } .donut svg { display:block; width:100%; height:100%; }
.dn { position:absolute; inset:0; display:flex; flex-direction:column; align-items:center; justify-content:center; font-size:11px; line-height:1.1; color:var(--muted); text-align:center; } .dn b { font-size:16px; font-weight:600; color:var(--ink); font-variant-numeric:tabular-nums; }
.dp { position:absolute; transform:translate(-50%,-50%); padding:1px 0; font-size:10px; font-weight:600; line-height:1; font-variant-numeric:tabular-nums; }
.dlg { list-style:none; margin:0; padding:0; font-size:12px; line-height:1.3; min-width:0; } .dlg li { display:flex; gap:6px; align-items:flex-start; margin:1px 0; } .dlg .sw { width:10px; height:10px; margin-top:3px; border-radius:2px; flex:none; }
@container (min-width:250px) { .dwrap { flex-direction:row; align-items:center; gap:16px; } .donut { width:120px; height:120px; } .dn b { font-size:20px; } .dn { font-size:12px; } .dp { font-size:11px; } .dlg { font-size:13px; } }
.kpi .dl { font-size:var(--t-xs); font-weight:600; margin:4px 0 0; }
.kpi .dl.up { color:var(--teal-ink); } .kpi .dl.down { color:var(--coral-ink); } .kpi .dl.flat, .kpi .dl.nt { color:var(--muted); }
.kpi .den { font-size:var(--t-xs); color:var(--muted); margin:2px 0 0; }
.kpi .sp { margin-top:auto; padding-top:8px; }
.kpi.skel .fig { color:var(--muted); font-size:18px; font-weight:500; line-height:1.4; margin-top:10px; }
.kpi.skel.hero .fig { font-size:24px; }
.skbar { height:30px; border-radius:4px; background:repeating-linear-gradient(90deg,var(--line-soft) 0 6px,#FFFFFF 6px 9px); }
.spark { display:block; width:100%; height:30px; overflow:visible; }
.spark path.l { fill:none; stroke:var(--blue-ink); stroke-width:1.6; vector-effect:non-scaling-stroke; stroke-linejoin:round; }
.spark path.a { fill:#3694FC; fill-opacity:.16; stroke:none; }
.sparkwrap { position:relative; }
.sparkwrap .ld { position:absolute; width:7px; height:7px; margin:-3.5px 0 0 -3.5px; border-radius:50%; background:var(--blue-ink); }
details.vd { margin:10px 0 0; }
details.vd > summary { cursor:pointer; color:var(--blue-ink); font-size:var(--t-cap); padding:2px 0; }
details.vd > summary:focus-visible, a:focus-visible { outline:2px solid var(--blue-ink); outline-offset:2px; }
.scroll { overflow-x:auto; max-width:100%; }
.scroll:focus-visible { outline:2px solid var(--blue-ink); outline-offset:2px; }
/* panels and grids */
.panel { border:1px solid var(--line); border-radius:var(--radius); padding:14px 16px 12px; background:var(--bg); min-width:0; }
.row2 { display:grid; grid-template-columns:minmax(0,2fr) minmax(0,1fr); gap:16px; align-items:start; }
.row2e { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; align-items:start; }
.stk { display:flex; flex-direction:column; gap:16px; min-width:0; }
.sub { margin:16px 0 0; }
.sub:first-of-type { margin-top:0; }
.sub .st { font-size:var(--t-cap); font-weight:600; margin:0 0 6px; }
.verdict { margin:10px 0 0; padding:8px 12px; background:var(--panel); border-radius:var(--radius-s); font-size:var(--t-cap); }
.verdict b { font-weight:600; }
.leg { display:flex; flex-wrap:wrap; gap:2px 14px; margin:8px 0 0; font-size:var(--t-xs); color:var(--muted); list-style:none; padding:0; }
.leg li { display:flex; align-items:center; gap:6px; }
.sw { display:inline-block; width:14px; height:10px; flex:none; }
.sw.ln { height:0; border-top:3px solid var(--blue-ink); } .sw.bd { background:var(--blue-tint); border-top:1px dashed var(--blue-ink); border-bottom:1px dashed var(--blue-ink); }
.sw.hb { background:var(--hatch-blue); outline:1px solid var(--blue-ink); outline-offset:-1px; } .sw.hg { background:var(--hatch); outline:1px solid var(--ctl); outline-offset:-1px; }
.sw.tk { height:12px; width:0; border-left:1px dashed var(--amber-ink); } .sw.we { background:var(--blue); }
/* time-series plot */
.plot { display:grid; grid-template-columns:30px minmax(0,1fr); grid-template-rows:var(--ph,250px) auto; column-gap:6px; }
.ya { position:relative; }
.yl { position:absolute; right:0; transform:translateY(50%); font-size:11px; line-height:1; color:var(--muted); font-variant-numeric:tabular-nums; }
.pa { position:relative; border-bottom:1px solid var(--ctl); }
.gl { position:absolute; left:0; right:0; height:0; border-top:1px solid var(--line-soft); }
.slots { position:absolute; inset:0; display:grid; grid-template-columns:repeat(var(--n),minmax(0,1fr)); }
.slot { position:relative; min-width:0; }
.band { position:absolute; left:0; right:0; background:var(--blue-tint); border-top:1px dashed var(--blue-ink); border-bottom:1px dashed var(--blue-ink); }
.ln2 { position:absolute; inset:0; width:100%; height:100%; overflow:visible; }
.ln2 path.l { fill:none; stroke:var(--blue-ink); stroke-width:2.5; vector-effect:non-scaling-stroke; stroke-linejoin:round; }
.ln2 path.a { fill:#3694FC; fill-opacity:.16; stroke:none; }
.hbar { position:absolute; bottom:0; left:22%; right:22%; background:var(--hatch-blue); outline:1px solid var(--blue-ink); outline-offset:-1px; }
.col { position:absolute; bottom:0; left:12%; right:12%; background:var(--blue-ink); border-radius:2px 2px 0 0; }
.col.we { background:var(--blue); }
.col.part { background:var(--hatch-blue); outline:1px solid var(--blue-ink); outline-offset:-1px; }
.stub { position:absolute; bottom:0; left:22%; right:22%; height:9%; min-height:8px; background:var(--hatch); outline:1px solid var(--ctl); outline-offset:-1px; }
.zero { position:absolute; bottom:0; left:30%; right:30%; height:3px; background:var(--muted); }
.dot { position:absolute; left:50%; width:10px; height:10px; margin:0 0 -5px -5px; border-radius:50%; background:var(--blue-ink); box-shadow:0 0 0 2px #FFFFFF; }
.dot.big { width:14px; height:14px; margin:0 0 -7px -7px; }
.vl { position:absolute; left:50%; transform:translateX(-50%); font-size:11px; line-height:1; font-weight:600; font-variant-numeric:tabular-nums; white-space:nowrap; color:var(--ink); }
.tk { position:absolute; top:0; bottom:0; width:0; border-left:1px dashed var(--amber-ink); pointer-events:none; }
.tk .tl { position:absolute; top:calc(var(--r) * 15px + 2px); left:4px; font-size:11px; line-height:14px; color:var(--amber-ink); white-space:nowrap; background:rgba(255,255,255,.9); padding:0 3px; }
.tk.fl .tl { left:auto; right:4px; }
.tk.rc { border-left-color:var(--ctl); } .tk.rc .tl { color:var(--muted); }
.xa { grid-column:2; display:grid; grid-template-columns:repeat(var(--n),minmax(0,1fr)); margin-top:5px; }
.xa.day span:first-child { text-align:left; } .xa.day span:last-child { text-align:right; }
.xa span { text-align:center; font-size:11px; line-height:1.2; color:var(--muted); white-space:nowrap; }
.mk { grid-column:2; display:grid; grid-template-columns:repeat(var(--n),minmax(0,1fr)); height:12px; margin-top:2px; }
.mk span { text-align:center; font-size:10px; line-height:12px; color:var(--amber-ink); }
/* horizontal bars */
.hbars { display:flex; flex-direction:column; gap:5px; --hl:11.5rem; --hv:5.4rem; container-type:inline-size; }
.hb { display:grid; grid-template-columns:var(--hl) minmax(0,1fr) var(--hv); column-gap:10px; align-items:center; min-height:22px; }
.hl { font-size:var(--t-cap); line-height:1.25; min-width:0; }
.hl .tag { margin-left:4px; font-size:11px; padding:0 6px; }
.ht { position:relative; height:14px; border-left:1px solid var(--ctl); background:linear-gradient(var(--line-soft),var(--line-soft)) 50% 0/1px 100% no-repeat, linear-gradient(var(--line-soft),var(--line-soft)) 100% 0/1px 100% no-repeat; }
.ht i { display:block; height:100%; background:var(--blue-ink); border-radius:0 3px 3px 0; }
.ht i.alt { background:var(--blue); }
.ht i.gstub { width:16%; background:var(--hatch); outline:1px solid var(--ctl); outline-offset:-1px; border-radius:0; }
.hv { font-size:var(--t-cap); font-weight:600; text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
.hv.g { font-weight:500; color:var(--muted); }
.hg { font-size:var(--t-xs); font-weight:600; margin-top:8px; padding-bottom:2px; border-bottom:1px solid var(--line-soft); }
.hax { display:grid; grid-template-columns:var(--hl) minmax(0,1fr) var(--hv); column-gap:10px; font-size:11px; color:var(--muted); }
.hax span { grid-column:2; position:relative; display:block; height:14px; }
.hax b { position:absolute; top:0; font-weight:400; white-space:nowrap; }
.hax b:nth-child(1) { left:0; } .hax b:nth-child(2) { left:50%; transform:translateX(-50%); } .hax b:nth-child(3) { right:0; }
@container (max-width:470px) {
  .hbars { gap:9px; }
  .hb { grid-template-columns:minmax(0,1fr) auto; grid-template-areas:"l v" "t t"; row-gap:3px; }
  .hb .hl { grid-area:l; } .hb .ht { grid-area:t; } .hb .hv { grid-area:v; }
  .hg { margin-top:4px; }
  .hax { grid-template-columns:minmax(0,1fr); } .hax span { grid-column:1; }
}
.sbgrid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:18px 36px; } .sbgrid .sub { margin:0; }
.sr { position:absolute; width:1px; height:1px; overflow:hidden; clip:rect(0 0 0 0); white-space:nowrap; }
/* stacked bars */
.sb { display:flex; height:28px; gap:2px; border-radius:4px; overflow:hidden; }
.sb span { display:flex; align-items:center; justify-content:center; font-size:var(--t-xs); font-weight:600; min-width:0; overflow:hidden; white-space:nowrap; }
.sb .stubfull { flex:1 1 auto; background:var(--hatch); outline:1px solid var(--ctl); outline-offset:-1px; color:var(--ink); font-weight:500; }
.sb .stubfull b { background:#FFFFFF; padding:0 10px; font-weight:500; border-radius:3px; }
.c1 { background:var(--blue-ink); color:#FFFFFF; } .c2 { background:var(--blue); color:var(--ink); } .c3 { background:#BCD9FE; color:var(--ink); } .c4 { background:var(--indigo); color:#FFFFFF; }
.sl { display:flex; flex-wrap:wrap; gap:2px 14px; margin:6px 0 0; padding:0; list-style:none; font-size:var(--t-xs); color:var(--ink); }
.sl li { display:flex; align-items:center; gap:6px; }
.sl .sw { width:10px; height:10px; border-radius:2px; }
.sw.c1 { background:var(--blue-ink); } .sw.c2 { background:var(--blue); } .sw.c3 { background:#BCD9FE; } .sw.c4 { background:var(--indigo); }
/* heatmap and cohort grid */
.hm { display:grid; grid-template-columns:2.6rem repeat(var(--cols),minmax(0,1fr)); gap:2px; align-items:center; }
.hm .d, .hm .x, .ch .rl, .ch .x { font-size:11px; color:var(--muted); line-height:1.2; }
.hm .x, .ch .x { text-align:center; }
.hm .c { height:26px; border-radius:2px; background:#FFFFFF; box-shadow:inset 0 0 0 1px var(--line-soft); }
.hm .c.h, .ch .cc.h { background:var(--hatch); box-shadow:inset 0 0 0 1px var(--ctl); }
.v1 { background:var(--seq1) !important; } .v2 { background:var(--seq2) !important; } .v3 { background:var(--seq3) !important; } .v4 { background:var(--seq4) !important; } .v5 { background:var(--seq5) !important; }
.ramp { display:flex; align-items:center; flex-wrap:wrap; gap:4px 6px; margin:10px 0 0; font-size:var(--t-xs); color:var(--muted); }
.ramp i { display:inline-block; width:22px; height:12px; border-radius:2px; box-shadow:inset 0 0 0 1px var(--line-soft); }
.ramp i.h { background:var(--hatch); box-shadow:inset 0 0 0 1px var(--ctl); }
.ramp .sep { margin-left:10px; }
.ch { display:grid; grid-template-columns:var(--cl,8.2rem) repeat(var(--cols),minmax(0,1fr)); gap:2px; align-items:center; }
.ch .cc { font-style:normal; height:28px; display:flex; align-items:center; justify-content:center; font-size:11px; font-weight:600; font-variant-numeric:tabular-nums; border-radius:2px; background:#FFFFFF; box-shadow:inset 0 0 0 1px var(--line-soft); }
.ch .cc.n { background:var(--seq1); box-shadow:none; }
.ch .cc.dk { color:#FFFFFF; }
.ch .rl { text-align:right; padding-right:6px; }
.empty-note { padding:10px 12px; border:1px dashed var(--ctl); border-radius:var(--radius-s); color:var(--muted); font-size:var(--t-cap); }
table { border-collapse:collapse; width:100%; font-size:var(--t-body); }
th { text-align:left; font-weight:500; font-size:var(--t-xs); color:var(--muted); padding:6px 8px 6px 0; border-bottom:1px solid var(--line); }
td { padding:6px 8px 6px 0; border-bottom:1px solid var(--line-soft); vertical-align:top; }
tbody th { font-weight:400; color:var(--ink); font-size:var(--t-body); padding:6px 8px 6px 0; border-bottom:1px solid var(--line-soft); }
th.n, td.n { text-align:right; font-variant-numeric:tabular-nums; }
td.n { white-space:nowrap; }
table.two td.n { width:5.5em; }
tr.fam th { padding-top:12px; font-weight:600; font-size:var(--t-cap); color:var(--ink); border-bottom:1px solid var(--line); }
.cap2 { color:var(--muted); font-size:var(--t-cap); margin:2px 0 0; }
.gov { margin:8px 0 0; padding-left:18px; font-size:var(--t-cap); }
.gov li { margin:2px 0; }
footer { padding:28px 0 64px; color:var(--muted); font-size:var(--t-cap); }
.empty { padding:28px 0 8px; }
.empty h2 { font-size:var(--t-title); }
.empty ol { margin:10px 0 0; padding-left:20px; }
.wk-table { font-size:var(--t-cap); min-width:30rem; } .wk-table th, .wk-table td { padding-right:6px; }
@media (max-width:900px) {
  .kpis { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .kpi.hero { grid-column:1 / -1; }
  .kpi:last-child, .kpi:nth-child(4), .kpi#kpi-device { grid-column:1 / -1; }
  .row2, .row2e, .sbgrid { grid-template-columns:minmax(0,1fr); }
}
@media (max-width:560px) {
  .kpi { padding:12px 12px 10px; }
  .kpi.hero .fig { font-size:46px; }
  .panel { padding:12px 12px 10px; }
  .plot { --ph:210px; grid-template-columns:26px minmax(0,1fr); column-gap:4px; }
  .xa span.nk, .vl.nk { visibility:hidden; }
  .xa span:last-child { text-align:right; }
  .hm { grid-template-columns:2.2rem repeat(var(--cols),minmax(0,1fr)); gap:1px; } .hm .c { height:22px; }
  .ch { --cl:5.6rem; gap:1px; } .ch .cc { height:26px; font-size:10px; } .ch .rl { line-height:12px; font-size:10px; padding-right:4px; }
}
@media (prefers-reduced-motion: reduce) { * { animation:none !important; transition:none !important; scroll-behavior:auto !important; } }
"""

ICON_WARN = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/></svg>'
ICON_OK = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" d="M9 16.2 4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4z"/></svg>'
def gov() -> list:
    return ["Pseudonymous, not anonymous: a record holds a user id (a code, no name or e-mail); the editors of the published page can read these records.",
            "Kept for 12 weeks: older weeks are removed from a person's record when they next open the page, and the owner also deletes records not seen for 12 weeks.",
            "The exported JSON file is deleted after the report is built. Screenshots of this page carry the same rules as the page.",
            ((f"A group of 0 people prints as 0; a group of {'1' if MIN_USERS == 2 else '1 to ' + str(MIN_USERS - 1)} prints as {SMALL} and its neighbours are withheld when a subtraction would reveal it. " if MIN_USERS > 1 else "No group is withheld (the minimum group size is 1), so there is no group to protect by subtraction. ")
             + "A percentage prints only when its denominator is 20 or more; below that the counts are printed with n=." + ("" if MIN_USERS > 1 else " " + small_rule(cap=True))),
            "Wording: say readers of a section, reach and people active. Never rank, name or evaluate people or teams, and never state a reason for a change: a change coincides with, or is associated with, something worth investigating."]
HM_BUCKETS = 5


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


# ------------------------------------------------------------------------------------------------------------ chart building blocks
def nice_axis(v: float) -> tuple:
    """(top, step) of a value axis that starts at zero: 3 to 5 round gridlines and a little head room above the largest value."""
    v = max(v, 1)
    for step in (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000, 10000):
        if math.ceil(v * 1.06 / step) <= 5:
            return step * math.ceil(v * 1.06 / step), step
    return int(v), int(v)


def _grid(top: int, step: int) -> tuple:
    vals = list(range(0, top + 1, step))
    lines = "".join(f'<i class="gl" style="bottom:{100 * v / top:.2f}%"></i>' for v in vals if v)
    labels = "".join(f'<span class="yl" style="bottom:{100 * v / top:.2f}%">{v}</span>' for v in vals)
    return lines, labels


def _legend(items: list) -> str:
    return '<ul class="leg" aria-hidden="true">' + "".join(f'<li><span class="sw {cls}"></span>{e(txt)}</li>' for cls, txt in items) + "</ul>"


def show_data(inner: str, label: str = "Show data") -> str:
    """The table equivalent of a chart, behind a disclosure (a keyboard stop). A wide table scrolls inside its own box, never the page."""
    return f'<details class="vd"><summary>{e(label)}</summary><div class="scroll" tabindex="0" role="region" aria-label="Data table">{inner}</div></details>'


def panel(title: str, caption: str, body: str, data: str = "", hid: str = "", extra_cls: str = "") -> str:
    """A chart with a title (the metric or the takeaway), a one-line caption (what the marks are and the period), the chart and its data."""
    i = f' id="{hid}"' if hid else ""
    return f'<div class="panel {extra_cls}"{i}><h3>{e(title)}</h3><p class="cap">{e(caption)}</p>{body}{data}</div>'


def spark(vals: list, label: str) -> str:
    """A sparkline of a weekly series (None = a week that cannot be drawn: a gap). Drawn only from 3 numbers; autoscaled (a trend shape, not a magnitude)."""
    pts = [(i, v) for i, v in enumerate(vals) if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if len(pts) < 3:
        return '<div class="skbar" aria-hidden="true"></div>'
    lo, hi = min(v for _, v in pts), max(v for _, v in pts)
    pad = (hi - lo) * 0.12 or max(1.0, abs(hi) * 0.1)
    lo, hi = lo - pad, hi + pad
    n = max(len(vals) - 1, 1)
    xy = lambda i, v: (100 * i / n, 28 - 26 * (v - lo) / (hi - lo) + 1)
    runs, cur = [], []
    for i, v in enumerate(vals):
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            cur.append((i, v))
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    d_l = " ".join(("M" if k == 0 else "L") + "%.2f %.2f" % xy(i, v) for run in runs for k, (i, v) in enumerate(run))
    d_a = " ".join(" ".join(("M" if k == 0 else "L") + "%.2f %.2f" % xy(i, v) for k, (i, v) in enumerate(run)) + " L%.2f 29 L%.2f 29 Z" % (xy(run[-1][0], 0)[0], xy(run[0][0], 0)[0]) for run in runs)
    li, lv = pts[-1]
    lx, ly = xy(li, lv)
    return (f'<div class="sparkwrap"><svg class="spark" viewBox="0 0 100 30" preserveAspectRatio="none" role="img" aria-label="{e(label)}"><path class="a" d="{d_a}"/><path class="l" d="{d_l}"/></svg>'
            f'<i class="ld" aria-hidden="true" style="left:{lx:.1f}%;top:{100 * ly / 30:.1f}%"></i></div>')


def hbars(rows: list, scale: str = "0 to 100% of the people shown", axis: tuple = ("0", "50%", "100%")) -> tuple:
    """A horizontal bar chart. rows: {label, text (the value as printed), frac (0..1 of the axis, or None), guard (bool), tag, group, alt}. Returns (html, summary of the numbers for the label).
    A guarded row is a hatched stub of fixed length with the text '<5 users': its length says nothing. Bars start at zero; the axis is the same for every row."""
    out, summ = [], []
    for r in rows:
        if r.get("group"):
            out.append(f'<div class="hg">{e(r["group"])}</div>')
            summ.append(r["group"] + ":")
            continue
        tag = f' <span class="tag">{e(r["tag"])}</span>' if r.get("tag") else ""
        if r["guard"]:
            bar, val = '<i class="gstub"></i>', f'<span class="hv g">{e(SMALL)}</span>'
        else:
            w = 0 if not r.get("frac") else max(0.8, min(100.0, 100 * r["frac"]))
            bar = f'<i{" class=alt" if r.get("alt") else ""} style="width:{w:.1f}%"></i>' if w else ""
            val = f'<span class="hv">{e(r["text"])}</span>'
        out.append(f'<div class="hb"><span class="hl">{e(r["label"])}{tag}</span><span class="ht">{bar}</span>{val}</div>')
        summ.append(f'{r["label"]} {SMALL if r["guard"] else r["text"]}')
    ax = f'<div class="hax" aria-hidden="true"><span><b>{e(axis[0])}</b><b>{e(axis[1])}</b><b>{e(axis[2])}</b></span></div>'
    return f'<div class="hbars">{"".join(out)}{ax}</div>', "; ".join(summ)


def chart_img(inner: str, label: str, cls: str = "", style: str = "") -> str:
    s = f' style="{style}"' if style else ""
    return f'<div class="{cls}" role="img" aria-label="{e(label)}"{s}>{inner}</div>'


def stack_bar(cells: dict, names: dict, th=THRESHOLDS, unit: str = "visits") -> tuple:
    """A 100% stacked bar of a partition already protected by partition_cells / protect_partition (a withheld cell is SMALL).
    Only the printed cells are drawn, as shares of the printed cells: a withheld group gets no length, so the bar can never reveal it by subtraction (a bar with a withheld group is drawn only when 2 or more groups remain).
    Returns (html, summary, drawn): drawn = the numbers that are on the chart (for the tests)."""
    shown = [(k, v) for k, v in cells.items() if v != SMALL and v > 0]
    hidden = [k for k, v in cells.items() if v == SMALL]
    den = sum(v for _, v in shown)
    legend = [f'<li><span class="sw c{i % 4 + 1}"></span>{e(names[k])}</li>' for i, (k, _) in enumerate(shown)]
    legend += [f'<li><span class="sw hg"></span>{e(names[k])}: {e(SMALL)}</li>' for k in hidden]
    if len(shown) < (2 if hidden else 1) or not den:
        bar = f'<div class="sb" aria-hidden="true"><span class="stubfull"><b>{e(SMALL if hidden else "none")}</b></span></div>'
        return bar + f'<ul class="sl">{"".join(legend)}</ul>', ("; ".join(f"{names[k]} {SMALL}" for k in hidden) or "none"), []
    use_pct = den >= th["min_den"]
    segs, summ, drawn = [], [], []
    for i, (k, v) in enumerate(shown):
        p = 100 * v / den
        txt = f"{rnd(p)}%" if use_pct else str(v)
        drawn.append(txt)
        segs.append(f'<span class="c{i % 4 + 1}" style="flex:{p:.2f} 1 0">{e(txt) if p >= 9 else ""}</span>')
        summ.append(f"{names[k]} {txt}")
    summ += [f"{names[k]} {SMALL}" for k in hidden]
    note = f'{"share of the " + str(den) + " " + unit + " shown; groups under " + str(MIN_USERS) + " people are left out" if hidden else "n=" + str(den) + " " + unit}'
    bar = f'<div class="sb" aria-hidden="true">{"".join(segs)}</div><ul class="sl">{"".join(legend)}</ul>'
    return bar, "; ".join(summ) + f" ({note})", drawn


def stack_note(cells: dict, th=THRESHOLDS, unit: str = "visits") -> str:
    shown = [v for v in cells.values() if v != SMALL and v > 0]
    den = sum(shown)
    if not shown:
        return f"Withheld: a group under {MIN_USERS} people, and the figures next to it would reveal it." if SMALL in cells.values() else ""
    if SMALL in cells.values():
        return f"Share of the {den} {unit} shown; groups under {MIN_USERS} people are left out."
    return f"n={den} {unit}" + ("" if den >= th["min_den"] else " (counts: fewer than 20)")


# ------------------------------------------------------------------------------------------------------------ the weekly series behind the key figures
def _comparable_run(m: Model) -> list:
    """The completed weeks that end at the last completed week and share its recording rules (the weeks before a change of the rules, the rollover week and the provisional first week are left out)."""
    L = m.last
    rg = m.regime(L)
    run, w = [], L
    while rg is not None and m.usable(w) and m.regime(w) == rg and not (w == m.rollover and rg == "v2"):
        run.append(w)
        w -= dt.timedelta(days=7)
    return sorted(run)


def kpi_period(m: Model) -> dict:
    """The period the key figures describe: the last completed week when it can be used; otherwise everything recorded so far (marked 'so far': a period in progress or a provisional first week is never compared with complete weeks)."""
    L = m.last
    if m.usable(L):
        return {"kind": "week", "rows": m.visits(L), "label": week_label(L), "so_far": False}
    if m.rows:
        if m.first_day >= m.cur:
            label = f"so far, {d_label(m.cur)} to {d_label(m.ref)} (week in progress)"
        else:
            label = f"all data so far, {d_label(m.first_day)} to {d_label(m.last_day)}"
        return {"kind": "todate", "rows": m.rows, "label": label, "so_far": True}
    return {"kind": "none", "rows": [], "label": "", "so_far": True}


def period_values(rows: list, th: dict) -> dict:
    """The key figures (and the device split) of a set of visits, with the report's guards: engaged visits per active person needs the minimum group of people; the median active minutes needs it among the people with active time."""
    people = {r["u"] for r in rows}
    n = len(people)
    eng = [r for r in rows if not r["glance"]]
    pos = [r for r in eng if is_num(r["s"].get("s")) and r["s"]["s"] > 0]
    mp = {r["u"] for r in pos}
    out = {"n": n, "people": gn(n), "eng": len(eng), "vpp": round(len(eng) / n, 1) if n >= MIN_USERS else (SMALL if n else None),
           "pos": (len(pos), len(mp)), "min": g(len(mp), round(statistics.median([r["s"]["s"] / 60 for r in pos]), 1)) if pos else None, "dev": device_counts(rows)}
    return out


DEVICE_SHORT = {"l": "Desktop", "m": "Tablet", "s": "Phone"}


def device_card(dc: dict, th=THRESHOLDS) -> dict:
    """The Device key figure of a device_counts result: the largest window-width class with its share of the visits ('Desktop 50%'; on a tie the first of Desktop, Tablet, Phone), and in the sub line the other classes with their shares and the number of visits.
    Percentages always add up to 100 and carry their n, however small (the owner knows the base from the sub line and the centre of the donut). A class under the minimum group size (or one a printed total would reveal) prints the guard text and the
    denominator is the printed classes only, so a withheld class can never be rebuilt by subtraction."""
    n = dc["n"]
    if not n:
        return {"state": "none"}
    cells = dc["cells"]
    hidden = SMALL in cells.values()
    shown = [(k, cells[k]) for k in DEVICE_ORDER if cells[k] != SMALL and cells[k] > 0]
    if not shown:
        return {"state": "hidden"}
    den = sum(v for _, v in shown) if hidden else n
    sh_ = device_shares(dc)
    top = max(v for _, v in shown)
    lead = next(k for k, v in shown if v == top)
    rest = [k for k in ("s", "m", "l") if k != lead]
    parts = [f"{DEVICE_SHORT[k]} {SMALL if cells[k] == SMALL else str(sh_[k]) + '%'}" for k in rest]
    unit = f"{den} visit{'s' if den != 1 else ''}" + (" shown" if hidden else "")
    return {"state": "ok", "fig": f"{DEVICE_SHORT[lead]} {sh_[lead]}%", "sub": " · ".join(parts + [unit]), "desk": (sh_["l"] if (not hidden and den >= th["min_den"]) else None), "den": den, "hidden": hidden}


DONUT_COLORS = {"l": "#3694FC", "m": "#5B6B8C", "s": "#1C7A6C"}            # NiCE blue, a grey-blue and a teal, each at least 3:1 against white
DONUT_TEXT = {"l": "#21212B", "m": "#FFFFFF", "s": "#FFFFFF"}               # the label colour on each (4.5:1 or more)
DONUT_GAP_DEG = 4.0                                                          # about 2 px of white between neighbouring segments
DONUT_HATCH_DEG = 14.0                                                       # the fixed size of the hatched arc of a withheld class: its length says nothing about the class
DONUT_LABEL_MIN_PCT = 12                                                     # a segment of this share or more carries its percentage on itself


def device_donut(dc: dict, th=THRESHOLDS) -> tuple:
    """A small donut of the visits by window-width class, for the Device key figure. Returns (html, label, segments) with segments = [(class, degrees, hidden)] (for the tests).
    A class with no visits is not drawn; a class that is withheld (under the minimum group size, or one a printed total would reveal) is one hatched arc of a fixed size, and the other classes share the rest of the ring as shares of the
    printed classes only, so the ring can never reveal a withheld class by subtraction. Percentages add up to 100 (largest remainder) and are always shown, with the counts behind them in the legend; the centre says the number of visits
    (of the printed classes when one is withheld); the legend carries every number in words, so colour is never the only carrier."""
    cells = dc["cells"]
    hidden = [k for k in DEVICE_ORDER if cells[k] == SMALL]
    shown = [(k, cells[k]) for k in DEVICE_ORDER if cells[k] != SMALL and cells[k] > 0]
    den = sum(v for _, v in shown) if hidden else dc["n"]
    sh_ = device_shares(dc)
    avail = 360.0 - DONUT_HATCH_DEG * len(hidden)
    segs = [(k, avail * v / den, False) for k, v in shown] + [(k, DONUT_HATCH_DEG, True) for k in hidden]
    n_seg = len(segs)
    r = 34.0
    circles, labels, start = [], [], 0.0
    for k, deg, is_hidden in segs:
        length = deg if n_seg == 1 else max(1.0, deg - DONUT_GAP_DEG)
        off = start + (0 if n_seg == 1 else DONUT_GAP_DEG / 2)
        stroke = "url(#dev-hatch)" if is_hidden else DONUT_COLORS[k]
        circles.append(f'<circle class="dseg" data-deg="{deg:.2f}" cx="50" cy="50" r="{r:g}" fill="none" stroke="{stroke}" stroke-width="26" pathLength="360" stroke-dasharray="{length:.2f} {360 - length:.2f}" stroke-dashoffset="{-off:.2f}" transform="rotate(-90 50 50)"/>')
        if not is_hidden and sh_[k] >= DONUT_LABEL_MIN_PCT:
            mid = math.radians(start + deg / 2)
            labels.append(f'<span class="dp" style="left:{50 + r * math.sin(mid):.1f}%;top:{50 - r * math.cos(mid):.1f}%;color:{DONUT_TEXT[k]};background:{DONUT_COLORS[k]}">{sh_[k]}%</span>')
        start += deg
    parts, legend = [], []
    for k in DEVICE_ORDER:
        if cells[k] == SMALL:
            parts.append(f"{DEVICE_SHORT[k]} {SMALL}")
            legend.append(f'<li><span class="sw hg"></span><span>{e(DEVICE_SHORT[k])} {e(SMALL)}</span></li>')
        elif cells[k] > 0:
            parts.append(f"{DEVICE_SHORT[k]} {sh_[k]}%")
            legend.append(f'<li><span class="sw" style="background:{DONUT_COLORS[k]}"></span><span>{e(DEVICE_SHORT[k])} {sh_[k]}% ({cells[k]} of {den})</span></li>')
    label = f"Device split of {den} visit{'s' if den != 1 else ''}{' shown' if hidden else ''}: " + ", ".join(parts)
    svg = (f'<svg viewBox="0 0 100 100" role="img" aria-label="{e(label)}"><defs><pattern id="dev-hatch" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="5" height="5" fill="#FFFFFF"/>'
           f'<rect width="2" height="5" fill="#767B86"/></pattern></defs>{"".join(circles)}</svg>')
    centre = f'<div class="dn" aria-hidden="true"><b>{den}</b><span>visit{"s" if den != 1 else ""}{" shown" if hidden else ""}</span></div>'
    return f'<div class="dwrap"><div class="donut">{svg}{centre}{"".join(labels)}</div><ul class="dlg">{"".join(legend)}</ul></div>', label, segs


def kpi_series(a: dict) -> dict:
    """Weekly values of the key figures over the comparable run (the sparklines and the changes): the same period_values as the cards, one week at a time; the desktop share of the visits with a width needs 20 visits and no withheld class."""
    m, th = a["model"], a["model"].th
    run = _comparable_run(m)
    grow = {w["ws"]: w for w in a["weeks"]}
    ser = {k: {} for k in ("people", "new", "vpp", "min", "desk")}
    cnt_ = {"vpp": {}, "min": {}}
    for w in run:
        v = period_values(m.visits(w), th)
        ser["people"][w] = v["people"]
        ser["new"][w] = grow[w]["new"] if w in grow else None
        ser["vpp"][w] = v["vpp"]
        cnt_["vpp"][w] = (v["eng"], v["n"])
        ser["min"][w] = v["min"]
        cnt_["min"][w] = v["pos"]
        ser["desk"][w] = device_card(v["dev"], th).get("desk")
    return {"run": run, "ser": ser, "cnt": cnt_}


def _delta(cur, prev, pct_ok: bool, decimals: int = 0, unit: str = "", good_up: bool | None = None) -> tuple:
    """(css class, text) of the change against the previous week: an arrow and words, never colour alone. A figure that is withheld has no change."""
    if cur in (None, SMALL) or prev in (None, SMALL):
        return "nt", "Change not shown"
    d = round(cur - prev, decimals) if decimals else int(round(cur - prev))
    pct = f" ({rnd(100 * abs(d) / prev)}%)" if pct_ok and prev else ""
    fmt = (lambda x: f"{abs(x):.{decimals}f}") if decimals else (lambda x: str(abs(x)))
    if d == 0:
        return "flat", '- No change<span class="sr"> vs previous week</span>'
    up = d > 0
    cls = ("up" if up else "down") if good_up else "flat"
    return cls, f"{'&#9650; Up' if up else '&#9660; Down'} {fmt(d)}{unit}{pct}<span class=\"sr\"> vs previous week</span>"


def _kpi(title: str, fig: str, delta: tuple | None, den: str, spark_html: str, hero: bool = False, skel: str | None = None, hid: str = "", fig_cls: str = "") -> str:
    cls = "kpi" + (" hero" if hero else "") + (" skel" if skel else "")
    i = f' id="{hid}"' if hid else ""
    if skel:
        return f'<div class="{cls}"{i}><h3>{e(title)}</h3><p class="fig">{e(skel)}</p><p class="den">{e(den)}</p><div class="sp"><div class="skbar" aria-hidden="true"></div></div></div>'
    dl = f'<p class="dl {delta[0]}">{delta[1]}</p>' if delta else ""
    return f'<div class="{cls}"{i}><h3>{e(title)}</h3><p class="fig{" " + fig_cls if fig_cls else ""}">{fig}</p>{dl}<p class="den">{den}</p><div class="sp">{spark_html}</div></div>'


def device_counts(rows: list) -> dict:
    """Visits (engaged or glance) by the window-width class the page recorded, and the distinct people in each class. A visit without a width is not counted. The classes are a partition of the visits, protected like every other partition
    (a class under the minimum group size is withheld, and so is a class that a printed total would reveal)."""
    rows = [r for r in rows if r["s"].get("d") in DEVICES]
    groups = {k: ({r["u"] for r in rows if r["s"]["d"] == k}, sum(1 for r in rows if r["s"]["d"] == k)) for k in DEVICES}
    return {"n": len(rows), "people": {k: len(v[0]) for k, v in groups.items()}, "cells": partition_cells(groups) if rows else {k: 0 for k in DEVICES}}


def pct_split(values: list) -> list:
    """Whole percentages of the values that add up to exactly 100 (largest remainder: 1/3 each is 34, 33, 33); all zeros stay 0."""
    tot = sum(values)
    if not tot:
        return [0 for _ in values]
    raw = [100 * v / tot for v in values]
    base = [int(math.floor(x)) for x in raw]
    order = sorted(range(len(values)), key=lambda i: (-(raw[i] - base[i]), i))
    for i in order[:100 - sum(base)]:
        base[i] += 1
    return base


def device_shares(dc: dict) -> dict:
    """{class: whole percentage} over the printed classes of a device_counts result (a withheld class has none and the others share 100 between them), adding up to 100."""
    ks = [k for k in DEVICE_ORDER if dc["cells"][k] != SMALL]
    return dict(zip(ks, pct_split([dc["cells"][k] for k in ks])))


def device_texts(dc: dict, th=THRESHOLDS) -> dict:
    """{class: (share, full text)} for a device_counts result: always a percentage of the visits (a small base is shown by its n, here and in the card), adding up to 100, with the counts behind it. The denominator is the printed classes only when a class
    is withheld, so the total of a withheld class is never printed. A withheld class prints the guard text and nothing else."""
    cells = dc["cells"]
    hidden = SMALL in cells.values()
    den = sum(v for v in cells.values() if v != SMALL) if hidden else dc["n"]
    sh_ = device_shares(dc)
    out = {}
    for k in DEVICE_ORDER:
        c = cells[k]
        if c == SMALL:
            out[k] = (SMALL, SMALL)
            continue
        ppl = dc["people"][k]
        who = f"{ppl} {'person' if ppl == 1 else 'people'}"
        out[k] = (f"{sh_[k]}%", f"{sh_[k]}% ({c} of {den} visits, {who})")
    return out


def device_line(dc: dict, th=THRESHOLDS) -> str:
    """'Desktop (wide window) 80% | Tablet (medium window) 5% | Phone (narrow window) 15%' (the short form of device_texts)."""
    tx = device_texts(dc, th)
    return " | ".join(f"{DEVICES[k]} {tx[k][0]}" for k in DEVICE_ORDER)


def _pl(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _first_comparison_note(m: Model) -> str:
    """Why there is nothing to compare yet and when there will be: a week of data that starts mid-week is never compared, and a change needs two complete weeks."""
    first_usable = m.first_week + dt.timedelta(days=7) if m.provisional_first else m.first_week
    sat = first_usable + dt.timedelta(days=13)
    start = f"Data starts {d_label(m.data_start)}, mid-week: that week is not compared. " if m.provisional_first else f"Data starts {d_label(m.data_start)}. "
    return start + f"Comparisons appear after two complete weeks (from Sat {d_label(sat)})."


def device_period_lines(a: dict) -> list:
    """[(label, device_counts)] for the period of the key figures and, when it differs, all the recorded visits."""
    m = a["model"]
    P = kpi_period(m)
    out = []
    if P["kind"] != "none":
        out.append((P["label"], device_counts(P["rows"])))
        if P["kind"] == "week" and m.rows:
            out.append((f"all recorded visits, {d_label(m.first_day)} to {d_label(m.last_day)}", device_counts(m.rows)))
    return out


def _kpis(a: dict) -> str:
    """The five key figures: people active (the hero), new people, engaged visits per person, median visit length and the device (twice as wide; the glance share is under Recording health). Each shows its value for the period (the last completed week, or the data so far while there is none)
    with the number behind it; only the comparison (the change against the week before, the usual range, the sparkline) falls back to a short muted note when there is nothing comparable."""
    m, th = a["model"], a["model"].th
    c, au = a["compared"], a["audience"]
    P = kpi_period(m)
    ks = kpi_series(a)
    run, ser, cn = ks["run"], ks["ser"], ks["cnt"]
    vals = period_values(P["rows"], th)
    L = m.last
    prev = L - dt.timedelta(days=7)
    week_mode = P["kind"] == "week"
    has_prev = week_mode and prev in run and L in run
    weeks_n = len(run)
    if not week_mode:
        why = "No comparison yet: first week of data"
    elif L not in run:
        why = "No comparison: recording rules changed" if m.regime(L) is not None else "No comparison: no visits that week"
    elif not has_prev:
        why = "No comparison yet: first complete week"
    else:
        why = ""
    note = ("nt", why)
    so = ", so far" if P["so_far"] else ""
    arr = lambda key: [ser[key].get(w) if isinstance(ser[key].get(w), (int, float)) and not isinstance(ser[key].get(w), bool) else None for w in run]
    cells = []
    # 1 people active (hero)
    if vals["people"] == SMALL:
        cells.append(_kpi("People active", "", None, f"A group under {MIN_USERS} people is not shown", "", hero=True, skel=SMALL, hid="kpi-people"))
    else:
        cur = vals["n"]
        pp = ser["people"].get(prev)
        dl = _delta(cur, pp, pp not in (None, SMALL) and pp >= th["min_den"], good_up=True) if has_prev else note
        if week_mode and c and c["state"] == "ok":
            where = "above" if c["above"] else "below" if c["below"] else "inside"
            den = f"Usual {e(c['median'])} (range {e(c['lo'])} to {e(c['hi'])}): {where} the usual range"
        elif week_mode and c:
            den = f"Usual range building: {c['n_baseline']} of {th['baseline_min']} comparable weeks"
        else:
            den = e(P["label"][0].upper() + P["label"][1:]) + "<br>No usual range yet: it needs 5 complete weeks"
        if au:
            den += (f"<br>{num(au['x'])} of an audience of {au['size']}" + (f" ({au['pct']}%)" if au["pct"] is not None else "") + ", a lower bound") if (au["x"] is not None and week_mode) else f"<br>Audience of {au['size']} supplied"
        else:
            den += "<br>No audience size supplied"
        cells.append(_kpi("People active", num(vals["people"]), dl, den, spark(arr("people"), f"People active per week, last {weeks_n} comparable weeks, ending at {cur}."), hero=True, hid="kpi-people"))
    # 2 new people
    if week_mode:
        row = next((w for w in a["weeks"] if w["ws"] == L), None)
        new = row["new"] if row else None
    elif vals["n"]:
        new_n = sum(1 for u in m.people if m.first_seen[u] >= m.first_day)
        new = SMALL if 0 < vals["n"] < MIN_USERS else protect_partition({"new": new_n, "other": vals["n"] - new_n}, vals["n"])["new"]
    else:
        new = None
    if new is None:
        cells.append(_kpi("New people", "", None, "First week of data", "", skel="No data", hid="kpi-new"))
    elif new == SMALL:
        cells.append(_kpi("New people", "", None, f"A group under {MIN_USERS} people is not shown", "", skel=SMALL, hid="kpi-new"))
    else:
        pv = ser["new"].get(prev)
        dl = _delta(new, pv, False, good_up=True) if has_prev else note
        cells.append(_kpi("New people", num(new), dl, e(f"of {vals['people'] if vals['people'] == SMALL else _pl(vals['n'], 'person', 'people')} active{so}"), spark(arr("new"), f"New people per week, last {weeks_n} comparable weeks, ending at {new}."), hid="kpi-new"))
    # 3 engaged visits per active person
    v = vals["vpp"]
    if v is None:
        cells.append(_kpi("Engaged visits per person", "", None, "No visits in the period", "", skel="No visits", hid="kpi-vpp"))
    elif v == SMALL:
        cells.append(_kpi("Engaged visits per person", "", None, f"Fewer than {MIN_USERS} people", "", skel=SMALL, hid="kpi-vpp"))
    else:
        pv = ser["vpp"].get(prev)
        dl = _delta(v, pv, pv not in (None, SMALL) and cn["vpp"][prev][1] >= th["min_den"], 1, good_up=None) if has_prev else note
        cells.append(_kpi("Engaged visits per person", num(v), dl, e(f"{_pl(vals['eng'], 'engaged visit', 'engaged visits')}, {_pl(vals['n'], 'person', 'people')}{so}"), spark(arr("vpp"), f"Engaged visits per active person per week, last {weeks_n} comparable weeks, ending at {v}."), hid="kpi-vpp"))
    # 4 median active minutes
    v = vals["min"]
    if v is None:
        cells.append(_kpi("Median visit length", "", None, "No active seconds recorded in the period", "", skel="No active time", hid="kpi-min"))
    elif v == SMALL:
        cells.append(_kpi("Median visit length", "", None, f"Fewer than {MIN_USERS} people", "", skel=SMALL, hid="kpi-min"))
    else:
        pv = ser["min"].get(prev)
        dl = _delta(v, pv, False, 1, unit=" min", good_up=None) if has_prev else note
        cells.append(_kpi("Median visit length", f"{num(v)}<span class=\"small\"> min</span>", dl, e(f"active minutes, {_pl(vals['pos'][0], 'engaged visit', 'engaged visits')}{so}"), spark(arr("min"), f"Median active minutes per engaged visit per week, last {weeks_n} comparable weeks, ending at {v}."), hid="kpi-min"))
    # 5 device (twice as wide as the others: the donut and its legend sit side by side)
    dev = device_card(vals["dev"], th)
    if dev["state"] == "none":
        cells.append(_kpi("Device", "", None, "No browser window width recorded", "", skel="No width", hid="kpi-device"))
    elif dev["state"] == "hidden":
        cells.append(_kpi("Device", "", None, f"A group under {MIN_USERS} people is not shown", "", skel=SMALL, hid="kpi-device"))
    else:
        dk, pk = ser["desk"].get(L), ser["desk"].get(prev)
        dl = _delta(dk, pk, False, unit=" points", good_up=None) if (has_prev and dk is not None and pk is not None) else (note if not has_prev else ("nt", "Change not shown: under 20 visits"))
        cells.append(_kpi("Device", e(dev["fig"]), dl, e(dev["sub"]), device_donut(vals["dev"], th)[0], fig_cls="sm", hid="kpi-device"))
    # the table behind the sparklines and the cards
    body = []

    def trow(label, v_people, v_new, v_vpp, v_min):
        return f'<tr><th scope="row">{e(label)}</th><td class="n">{num(v_people)}</td><td class="n">{num(v_new)}</td><td class="n">{num(v_vpp)}</td><td class="n">{num(v_min)}</td></tr>'
    if not week_mode:
        body.append(trow(P["label"][0].upper() + P["label"][1:], vals["people"], new, vals["vpp"], vals["min"]))
    for w in reversed(run):
        body.append(trow(week_label(w), ser["people"].get(w), ser["new"].get(w), ser["vpp"].get(w), ser["min"].get(w)))
    usable_n = len([w for w in m.weeks if not m.is_prov(w)])
    table = ('<table id="kpi-table"><thead><tr><th scope="col">Period</th><th scope="col" class="n">People active</th><th scope="col" class="n">New people</th><th scope="col" class="n">Engaged visits per person</th><th scope="col" class="n">Median visit length (min)</th>'
             f'</tr></thead><tbody>{"".join(body)}</tbody></table>'
             + (f'<p class="cap2">{usable_n - len(run)} earlier completed week(s) are left out: the page recorded visits under other rules, so the figures are not comparable.</p>' if usable_n > len(run) else ""))
    drows = []
    for label, dc in device_period_lines(a):
        if not dc["n"]:
            drows.append(f'<tr><th scope="row">{e(label)}</th><td class="n">no browser window width recorded</td></tr>')
            continue
        tx = device_texts(dc, th)
        for k in DEVICE_ORDER:
            drows.append(f'<tr><th scope="row">{e(label)}: {e(DEVICES[k])}</th><td class="n">{e(tx[k][1])}</td></tr>')
    table += (f'<table id="device-table"><thead><tr><th scope="col">Window width class</th><th scope="col" class="n">Share of visits</th></tr></thead><tbody>{"".join(drows)}</tbody></table>'
              f'<p class="cap2">{e(DEVICE_CAVEAT)} Every visit counts, glance or engaged; a visit without a width is not counted.</p>')
    if week_mode:
        sub = f"Last completed week: {week_label(L)}. Each figure is compared with the week before; the line shows the weeks since the last change of the recording rules."
        if not has_prev:
            sub = f"Last completed week: {week_label(L)}. " + _first_comparison_note(m)
    elif P["kind"] == "todate":
        sub = P["label"][0].upper() + P["label"][1:] + ". " + _first_comparison_note(m)
    else:
        sub = "No data yet."
    return (f'<section class="blk" id="kpis" aria-labelledby="h-kpi"><h2 id="h-kpi">Key figures</h2><p class="cap" id="kpi-note">{e(sub)}</p><p class="cap" id="device-caveat">Device is by browser window width, not device type: a narrow desktop window counts as phone.</p>'
            f'<div class="kpis">{"".join(cells)}</div>{show_data(table)}</section>')


# ------------------------------------------------------------------------------------------------------------ the trend
def _tick_label(label: str) -> str:
    return ("W1 starts" if label.startswith("W1 starts") else "Delivery Cycle 1 ends" if label.startswith("End of W6") else "Release ends" if label.startswith("Release end") else label)


def _chart_weeks(a: dict) -> str:
    """People active per Sunday-to-Saturday week: a line and area for the complete weeks, hatched columns for the incomplete ones (the provisional first week and the week in progress), the usual range, the calendar events."""
    rows, comp, m = a["weeks"], a["compared"], a["model"]
    n = len(rows)
    vis = [w["raw"] for w in rows if w["active"] != SMALL]
    hi_band = comp["raw_hi"] if comp and comp.get("raw_hi") is not None else 0
    top, step = nice_axis(max(vis + [hi_band, 1]))
    lines, labels = _grid(top, step)
    slots, parts, runs, cur, ticks = [], [], [], [], []
    last_c = max((i for i, w in enumerate(rows) if w["status"] == "complete" and w["active"] != SMALL), default=None)
    for i, w in enumerate(rows):
        tag = "provisional, data starts mid-week" if w["status"] == "provisional" else "so far this week, not comparable" if w["status"] == "in_progress" else ""
        val = SMALL if w["active"] == SMALL else str(w["active"])
        parts.append(f"{w['label']}: {val} people" + (f" ({tag})" if tag else ""))
        tip = e(f"{w['label']}: {val} people" + (f" ({tag})" if tag else ""))
        y = 100 * w["raw"] / top
        keep = "" if (i in (0, n - 1, last_c) or w["raw"] == max(vis + [0])) else " nk"
        if w["status"] != "complete":
            if w["active"] == SMALL:
                slots.append(f'<div class="slot" title="{tip}"><i class="stub"></i></div>')
            elif w["raw"] == 0:
                slots.append(f'<div class="slot" title="{tip}"><i class="zero"></i></div>')
            else:
                slots.append(f'<div class="slot" title="{tip}"><i class="hbar" style="height:{max(1.5, y):.1f}%"></i><span class="vl{keep}" style="bottom:calc({y:.1f}% + 5px)">{w["raw"]}</span></div>')
            if cur:
                runs.append(cur)
                cur = []
        elif w["active"] == SMALL:
            slots.append(f'<div class="slot" title="{tip}"><i class="stub"></i></div>')
            if cur:
                runs.append(cur)
                cur = []
        else:
            cur.append((i, y))
            big = " big" if i == last_c else ""
            slots.append(f'<div class="slot" title="{tip}"><i class="dot{big}" style="bottom:{y:.1f}%"></i><span class="vl{keep}" style="bottom:calc({y:.1f}% + {13 if i == last_c else 10}px)">{w["raw"]}</span></div>')
    if cur:
        runs.append(cur)
    xy = lambda i, y: (100 * (i + 0.5) / n, 100 - y)
    d_l = " ".join(("M" if k == 0 else "L") + "%.2f %.2f" % xy(i, y) for run in runs for k, (i, y) in enumerate(run))
    d_a = " ".join(" ".join(("M" if k == 0 else "L") + "%.2f %.2f" % xy(i, y) for k, (i, y) in enumerate(run)) + " L%.2f 100 L%.2f 100 Z" % (xy(run[-1][0], 0)[0], xy(run[0][0], 0)[0]) for run in runs if len(run) > 1)
    svg = f'<svg class="ln2" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true" focusable="false"><path class="a" d="{d_a}"/><path class="l" d="{d_l}"/></svg>' if runs else ""
    band, band_txt = "", ""
    if comp and comp.get("raw_hi") is not None:
        lo, hi = max(0, comp["raw_lo"]), min(top, comp["raw_hi"])
        band = f'<div class="band" style="bottom:{100 * lo / top:.1f}%;height:{max(1.0, 100 * (hi - lo) / top):.1f}%"></div>'
        band_txt = f" Usual range of the last completed week: {comp['lo']} to {comp['hi']}."
    # calendar events and the change of recording rules
    first_ws, last_day = rows[0]["ws"], rows[-1]["ws"] + dt.timedelta(days=6)
    evs = [(d, _tick_label(lb), "") for d, lb, kind in calendar_marks(m, first_ws, last_day) if kind == "ms"]
    if m.rollover and first_ws <= m.rollover <= last_day:
        evs.append((m.rollover, "New recording rules", " rc"))
    tk, cal_txt = [], []
    for j, (d, lb, cls) in enumerate(sorted(evs)):
        idx = (week_start(d) - first_ws).days // 7
        x = 100 * (idx + ((d - week_start(d)).days + 0.5) / 7) / n
        r = j % 3                                                                          # neighbouring labels sit on different rows, so they never overlap
        fl = " fl" if x > 62 else ""
        tk.append(f'<div class="tk{cls}{fl}" style="left:{x:.2f}%;--r:{r}"><span class="tl">{e(lb)}</span></div>')
        cal_txt.append(f"{d_label(d)}: {lb}")
    xl = "".join(f'<span class="{"" if (n - 1 - i) % 3 == 0 else "nk"}">{e(w["label"])}</span>' for i, w in enumerate(rows))
    summary = (f"People active per Sunday-to-Saturday week, {rows[0]['label']} to {rows[-1]['label']}. " + "; ".join(parts) + "." + band_txt
               + (" Calendar: " + "; ".join(cal_txt) + "." if cal_txt else ""))
    inner = (f'<div class="ya" aria-hidden="true">{labels}</div><div class="pa" style="--n:{n}">{lines}{band}<div class="slots" style="--n:{n}">{"".join(slots)}</div>{svg}{"".join(tk)}</div>'
             f'<div class="xa" style="--n:{n}" aria-hidden="true">{xl}</div>')
    return chart_img(inner, summary, "plot")


def _week_table(a: dict) -> str:
    body = []
    for w in a["weeks"]:
        tag = "provisional: data starts mid-week" if w["status"] == "provisional" else "so far, not comparable" if w["status"] == "in_progress" else ""
        cells = "".join(f'<td class="n">{num(w[k]) if w[k] is not None else "-"}</td>' for k in ("new", "continuing", "reactivated", "lapsed"))
        body.append(f'<tr><th scope="row">{e(w["label"])}' + (f'<div class="cap2">{e(tag)}</div>' if tag else "") + f'</th><td class="n">{num(w["active"])}</td>{cells}</tr>')
    return ('<table class="wk-table" id="weeks"><thead><tr><th scope="col">Week starting (Sunday)</th><th scope="col" class="n">People</th><th scope="col" class="n">New</th><th scope="col" class="n">Continuing</th><th scope="col" class="n">Back after a gap</th>'
            f'<th scope="col" class="n">Lapsed</th></tr></thead><tbody>{"".join(body)}</tbody></table>')


def _chart_days(a: dict) -> str:
    dv = a["daily"]
    days = dv["days"]
    n = len(days)
    vis = [d["raw"] for d in days if d["users"] != SMALL]
    top, step = nice_axis(max(vis + [1]))
    lines, labels = _grid(top, step)
    mark_by_day = {}
    for d, label, kind in dv["marks"]:
        mark_by_day.setdefault(d, []).append((label, kind))
    slots, mrow, parts = [], [], []
    for d in days:
        we = " we" if d["weekend"] else ""
        state = ("before the data starts" if not d["has_data"] else SMALL if d["users"] == SMALL else str(d["raw"])) + (" (so far today, not comparable)" if d["partial"] else "") + (" (Friday or Saturday)" if d["weekend"] else "")
        tip = f"{d['day']:%a %d %b}: {state}"
        parts.append(tip)
        if not d["has_data"]:
            slots.append(f'<div class="slot" title="{e(tip)}"></div>')
        elif d["users"] == SMALL:
            slots.append(f'<div class="slot" title="{e(tip)}"><i class="stub"></i></div>')
        elif d["raw"] == 0:
            slots.append(f'<div class="slot" title="{e(tip)}"><i class="zero"></i></div>')
        else:
            slots.append(f'<div class="slot" title="{e(tip)}"><i class="col{we}{" part" if d["partial"] else ""}" style="height:{max(1.5, 100 * d["raw"] / top):.1f}%"></i></div>')
        mk = mark_by_day.get(d["day"])
        mrow.append("<span>&#9650;</span>" if mk else "<span></span>")
    xl = "".join(f'<span>{d_label(days[i]["day"]) if i in (0, n // 2, n - 1) else ""}</span>' for i in range(n))
    cal = "; ".join(f"{d_label(d)}: {lb}" for d, lb, _ in dv["marks"])
    summary = f"People active per day, last 28 days, {d_label(days[0]['day'])} to {d_label(days[-1]['day'])}. " + "; ".join(parts) + "." + (f" Calendar marks: {cal}." if cal else "")
    inner = (f'<div class="ya" aria-hidden="true">{labels}</div><div class="pa">{lines}<div class="slots" style="--n:{n}">{"".join(slots)}</div></div>'
             f'<div class="mk" style="--n:{n}" aria-hidden="true">{"".join(mrow)}</div><div class="xa day" style="--n:{n}" aria-hidden="true">{xl}</div>')
    return chart_img(inner, summary, "plot", "--ph:200px")


def _trend(a: dict) -> str:
    gv, dv = a["growth"], a["daily"]
    rows = a["weeks"]
    cap_w = f"Distinct people with a visit in each Sunday-to-Saturday week, {rows[0]['label']} to {rows[-1]['label']}."
    leg = _legend([("ln", "Complete week"), ("hb", "Incomplete week")] + ([("hg", SMALL)] if MIN_USERS > 1 else []) + ([("bd", "Usual range")] if a["compared"] and a["compared"].get("raw_hi") is not None else []) + [("tk", "Calendar event")])
    week = panel("People active per week", cap_w, _chart_weeks(a) + leg + f'<p class="verdict" id="growth"><b>Is adoption growing?</b> {e(gv["text"])}</p>', show_data(_week_table(a)), "p-weeks")
    cap_d = f"Distinct people per day, {d_label(dv['days'][0]['day'])} to {d_label(dv['days'][-1]['day'])}."
    leg_d = _legend([("hb", "Today so far"), ("we", "Friday, Saturday")] + ([("hg", SMALL)] if MIN_USERS > 1 else []))
    mk = "".join(f"<li>{d_label(d)}: {e(label)}</li>" for d, label, _ in dv["marks"])
    ww = f'<p class="cap2">Sunday to Thursday had {dv["workweek"]["pct"]}% of the {dv["workweek"]["n"]} visits in the last 28 days.</p>' if dv["workweek"] else ""
    extra = "".join(f'<p class="cap2">{e(x)}</p>' for x in (dv["note"], (dv["events"] or {}).get("text")) if x)
    tbl = ('<table id="days"><thead><tr><th scope="col">Day</th><th scope="col" class="n">People</th></tr></thead><tbody>'
           + "".join(f'<tr><td>{d["day"].isoformat()}{" (so far today, not comparable)" if d["partial"] else ""}</td><td class="n">{"before the data starts" if not d["has_data"] else num(d["users"])}</td></tr>' for d in reversed(dv["days"])) + "</tbody></table>"
           + (f'<ul class="gov" aria-label="Calendar marks">{mk}</ul>' if mk else "") + extra)
    day = panel("People active per day", cap_d, _chart_days(a) + leg_d + ww, show_data(tbl), "p-days")
    return f'<section class="blk" id="trend" aria-labelledby="h-trend"><h2 id="h-trend">Trend</h2><div class="row2">{week}{day}</div></section>'


# ------------------------------------------------------------------------------------------------------------ the breakdowns
def _read_block(a: dict) -> tuple:
    th = a["model"].th
    s = a["sections"]
    if not s["n"]:
        return '<div class="panel"><h3>Section reach</h3><p class="empty-note">Too early: no completed week yet.</p></div>', ""
    N = s["d"]
    rows = []
    for r in s["rows"]:
        guard = r["under5"]
        rows.append({"label": r["name"], "guard": guard, "text": share_text(r["reach"], N, th) if not guard else SMALL, "frac": (r["raw"] / N if (N != SMALL and N) else 0), "tag": r["candidate"]})
    if N == SMALL:
        chart, summ = f'<p class="empty-note">Fewer than {MIN_USERS} people were active: reach is not shown.</p>', ""
        body = chart
    else:
        chart, summ = hbars(rows)
        body = chart_img(chart, f"Section reach, share of the {N} people active in the window: {summ}.", "")
    body_rows = []
    for r in s["rows"]:
        nm = e(r["name"]) + (f" (reach under {MIN_USERS} people: Unknown)" if r["under5"] else "")
        cand = f' <span class="tag">{e(r["candidate"])}</span>' if r["candidate"] else ""
        body_rows.append(f'<tr><th scope="row">{nm}{cand}</th><td class="n">{sh(r["reach"], N, th)}</td><td class="n">{num(r["nav"]) if r["nav"] is not None else "-"}</td><td class="n">{num(r["links"])}</td><td class="n">{num(r["share"], "%") if r["share"] is not None else "-"}</td></tr>')
    ol = ", ".join(f"{DISCLOSURES[k]}: {num(v)}" for k, v in s["disclosures"].items())
    table = ('<table id="reach"><thead><tr><th scope="col">Section</th><th scope="col" class="n">Reach</th><th scope="col" class="n">Section Strip</th><th scope="col" class="n">Jira links</th><th scope="col" class="n">Reading time</th></tr></thead>'
             f'<tbody>{"".join(body_rows)}</tbody></table>'
             f'<p class="cap2">Reach: people with 30 seconds or more in the section in a week, of the {num(s["n_g"])} people active in {_weeks_phrase(a["model"], s["weeks"])}. Section Strip and Jira links: people using the strip or the skip links to jump to the section, or following a Jira link from it (a person is counted once). '
             f'Reading time: each person\'s own split, averaged over the sections shown; scroll position decides which section gets the time. {e(guard_note("A section with fewer than {n} readers shows {g} and is left out of that share."))} Simplify candidates: {e(s["candidates"]["status"])}. Details opened (people): {ol}.</p>')
    cap = f"Share of the {num(s['n_g'])} people active in {a['window']['label']} with 30 seconds or more in the section. Page order, not ranked."
    return panel("Section reach", cap, body, show_data(table), "p-sections"), ""


def _controls_block(a: dict) -> str:
    th = a["model"].th
    c = a["controls"]
    if not c["n"]:
        return '<div class="panel"><h3>Control reach</h3><p class="empty-note">Too early: no completed week yet.</p></div>'
    N = c["d"]
    rows = []
    for f in c["families"]:
        rows.append({"group": f["family"]})
        for r in f["rows"]:
            guard = r["reach"] == SMALL
            rows.append({"label": r["name"], "guard": guard, "text": share_text(r["reach"], N, th) if not guard else SMALL, "frac": (r["raw"] / N if (N != SMALL and N) else 0)})
    if N == SMALL:
        body = f'<p class="empty-note">Fewer than {MIN_USERS} people were active: reach is not shown.</p>'
    else:
        chart, summ = hbars(rows)
        body = chart_img(chart, f"Control reach, share of the {N} people active in the window that changed the control, by family: {summ}.")
    body_rows = []
    for f in c["families"]:
        body_rows.append(f'<tr class="fam"><th scope="colgroup" colspan="2">{e(f["family"])}</th></tr>')
        for r in f["rows"]:
            body_rows.append(f'<tr><th scope="row">{e(r["name"])}</th><td class="n">{sh(r["reach"], N, th)}</td></tr>')
    rs = c["reset"]
    reset = ("Not recorded in v1 records." if rs["state"] == "none" else f"{sh(rs['x'], rs['visits_g'], th)} of visits with a control change also pressed Reset Filters in the same visit ({nlabel(rs['visits_g'])})." + (" Flag: 25% or more in 2 consecutive weeks." if rs.get("flag") else ""))
    mv, pj = c["multi_vs_projects"]
    table = (f'<table id="controls"><thead><tr><th scope="col">Control</th><th scope="col" class="n">Reach</th></tr></thead><tbody>{"".join(body_rows)}</tbody></table>'
             f'<p class="cap2">Reach of each control among the {num(c["n_g"])} people active in {_weeks_phrase(a["model"], c["weeks"])}: people that changed it at least once. Any control: {sh(c["any"]["x"], N, th)}. Multi-select toggle: {num(mv)} people; Projects: {num(pj)} people. {e(reset)}</p>')
    cap = f"Share of the {num(c['n_g'])} people active in {a['window']['label']} that changed the control at least once. Fixed page order, not ranked."
    return panel("Control reach", cap, body, show_data(table), "p-controls")


def _actions_block(a: dict) -> str:
    """What people do with the page: four shares, each with its own base named in the row (people, or visits)."""
    th = a["model"].th
    c, u = a["controls"], a["use"]
    if not c["n"]:
        return ""
    lk, rf, rs = u["links"], u["refresh"], c["reset"]

    def row(label, x, den, pct_txt=None):
        """x: a count or SMALL; den: the number it is out of (an int)."""
        if x == SMALL:
            return {"label": label, "guard": True, "text": SMALL, "frac": 0}
        txt = share_text(x, den, th) if den else "-"
        return {"label": label, "guard": False, "text": txt, "frac": (x / den if den else 0), "alt": False}
    rows = [row("Changed any control (people)", c["any"]["x"], c["d"] if c["d"] != SMALL else 0),
            row("Pressed Refresh (people)", rf["x"], rf["n"]),
            row("Visits with a Jira link click (engaged visits)", lk["visits"] if lk["x"] != SMALL else SMALL, lk["of"]),
            row("Reset Filters after a control change (visits with a change)", ("-" if rs["state"] == "none" else rs["x"]), (rs["visits"] if rs["state"] != "none" else 0))]
    if rs["state"] == "none":
        rows[3] = {"label": "Reset Filters after a control change (visits with a change)", "guard": False, "text": "not recorded", "frac": 0}
    elif rs["x"] != SMALL and rs["visits_g"] == SMALL:
        rows[3] = {"label": rows[3]["label"], "guard": True, "text": SMALL, "frac": 0}
    chart, summ = hbars(rows)
    body = chart_img(chart, f"What people do: {summ}.")
    # the table behind it keeps every number of the use block
    mn = u["minutes"]
    fr = u["fresh"]

    def fresh_line(k):
        f = fr.get(k)
        if not f:
            return "not recorded in v1 records"
        txt = ", ".join(f"{nm}: " + (SMALL if cell == SMALL else (f"{f['shares'][nm]}%" if f["shares"][nm] is not None else str(cell))) for nm, cell in f["cells"].items())
        return txt + (f" (share of the {fmt_n(f['n_g'])} visits shown; rows under {MIN_USERS} people are left out)" if f["hidden"] else f" ({nlabel(f['n_g'])} visits)")
    ro = rf["outcomes"]
    refresh_out = ("Outcomes: " + "; ".join(f"{RO[k]} {cnt(v['people'], 'people')}" for k, v in ro.items()) + f"; automatic retries {fmt_n(rf['retries'])}") if rf["has_v2"] else "Outcomes are not recorded in v1 records"
    link_secs = "; ".join(f"{s['name']}: {s['pct']}% of engaged visits, {s['status']}" for s in lk["sections"] if s["pct"] is not None) or f"no section has {th['link_min_clicks']} clicks from {th['link_min_people']} people yet"
    trs_rows = [
        ("Median active minutes among engaged visits (30 s or more, or with input)", (num(mn["median"]) + " min") if mn["median"] not in (None, SMALL) else (num(mn["median"]) if mn["median"] == SMALL else "-"), f"over {num(mn['visits'])} engaged visits with some active time ({num(mn['people'])} people). Glance visits are reported under Recording health"),
        ("Engaged visits per active person", num(u["per_person"]["value"]), f"in {u['weeks']} weeks, of {num(u['per_person']['n'])} active people: a count of visits, not a measure of value"),
        ("Visits with a Jira link click", (f"{lk['pct']}%" if lk["pct"] is not None else num(lk["visits"])) if lk["x"] != SMALL else e(SMALL), f"of {fmt_n(u['engaged_g'])} engaged visits had a Jira link click, by {num(lk['x'])} people. By section: {e(link_secs)}"),
        ("Small-screen share", sh(u["phone"]["x"], u["phone"]["n_g"], th), f"of {fmt_n(u['phone']['n_g'])} engaged visits with a width recorded"),
        ("Refresh pressed by", sh(rf["x"], rf["n_g"], th), f"of {fmt_n(rf['n_g'])} active people. {e(refresh_out)}"),
        ("Connection at the visit", "-", e(fresh_line("lv"))),
        ("Age of the data at the start", "-", e(fresh_line("fa"))),
    ]
    trs = "".join(f'<tr><th scope="row">{e(n)}<div class="cap2">{d}</div></th><td class="n">{v}</td></tr>' for n, v, d in trs_rows)
    table = (f'<table id="usage" class="two"><thead><tr><th scope="col">Measure and basis</th><th scope="col" class="n">Result</th></tr></thead><tbody>{trs}</tbody></table>'
             '<p class="cap2">Engaged visits = 30 seconds or more, or with input. A control or link count is a count of people, not of effect. Do not use these figures to compare teams.</p>')
    cap = f"Share of people or of visits, as named on each row; {a['window']['label']}."
    return panel("What people do", cap, body, show_data(table), "p-actions")


def device_split(a: dict) -> dict:
    """Engaged visits of the window by width class (the page records small, medium or large), as a partition protected like every other partition of the report."""
    m = a["model"]
    rows = [r for r in _window_rows(m, window_weeks(m)) if not r["glance"] and r["s"].get("d") in DEVICES]
    groups = {k: ({r["u"] for r in rows if r["s"]["d"] == k}, sum(1 for r in rows if r["s"]["d"] == k)) for k in DEVICES}
    return {"cells": partition_cells(groups) if rows else {k: 0 for k in DEVICES}, "n": len(rows), "people": len({r["u"] for r in rows})}


def version_split(m: Model) -> dict:
    """S6 as a chart: the people of the last completed week by the newest build day they used: on the newest version (or under 7 days older) or more than 7 days older. Needs 20 people with a recorded build day.
    The same partition protection as S6: when the older group is under 5 people nothing about the newer group is drawn."""
    th = m.th
    L = m.last
    if not m.usable(L) and th["show_partial_week"] and m.cur in m.by_week:
        L = m.cur                                                                 # no completed week to read: the week in progress, to date
    elif not m.usable(L):
        return {"state": "none"}
    rows_bt = [x for x in m.visits(L) if is_num(x["s"].get("bt"))]
    all_bt = [x["s"]["bt"] for x in m.rows if is_num(x["s"].get("bt"))]
    if not rows_bt:
        return {"state": "v1"}
    latest: dict = {}
    for x in rows_bt:
        latest[x["u"]] = max(latest.get(x["u"], x["s"]["bt"]), x["s"]["bt"])
    n6 = len(latest)
    if n6 < th["min_den"]:
        return {"state": "few", "n": n6}
    newest = max(all_bt)
    stale = sum(1 for v in latest.values() if newest - v > th["s6_age_days"])
    pc = protect_partition({"old": stale, "new": n6 - stale}, n6)
    return {"state": "ok", "n": n6, "cells": pc, "days": th["s6_age_days"], "partial": L == m.cur}


def _stack_panel_parts(a: dict) -> tuple:
    """(html of the three stacked bars, the tables behind them)."""
    th, m = a["model"].th, a["model"]
    parts, tables = [], []

    def add(title, bar, summ, note, table_rows):
        parts.append(f'<div class="sub"><p class="st">{e(title)}</p>{chart_img(bar, f"{title}: {summ}")}<p class="cap2">{e(note)}</p></div>')
        tables.append(f'<table><caption class="cap2">{e(title)}</caption><thead><tr><th scope="col">Group</th><th scope="col" class="n">Share</th></tr></thead><tbody>{table_rows}</tbody></table>')

    def rows_of(cells, names, summ_drawn):
        return "".join(f'<tr><th scope="row">{e(names[k])}</th><td class="n">{e(SMALL) if v == SMALL else num(v)}</td></tr>' for k, v in cells.items())
    ds = device_split(a)
    if ds["n"]:
        bar, summ, _ = stack_bar(ds["cells"], DEVICES, th)
        add("Screen size, engaged visits", bar, summ, stack_note(ds["cells"], th) + f" ({a['window']['label']}).", rows_of(ds["cells"], DEVICES, None))
    vs = version_split(m)
    if vs["state"] == "ok":
        names = {"new": f"On the newest page version, or under {vs['days']} days older", "old": f"More than {vs['days']} days older"}
        cells = vs["cells"]
        bar, summ, _ = stack_bar(cells, names, th, unit="people")
        add("Page version, people active in the " + ("week so far" if vs.get("partial") else "last completed week"), bar, summ, (stack_note(cells, th, "people") if SMALL in cells.values() else f"n={vs['n']} people with a recorded build day."), rows_of(cells, names, None))
    elif vs["state"] in ("v1", "few"):
        why = "not recorded in v1 records" if vs["state"] == "v1" else f"too few people (n={vs['n']}, needs {th['min_den']})"
        add("Page version, people active in the " + ("week so far" if vs.get("partial") else "last completed week"), f'<div class="sb" aria-hidden="true"><span class="stubfull"><b>Not shown</b></span></div>', "not shown: " + why, "Not shown: " + why + ".", f'<tr><td colspan="2">{e(why)}</td></tr>')
    fr = a["use"]["fresh"]
    for key, title in (("lv", "Connection at the start of a visit"), ("fa", "Age of the data at the start of a visit")):
        f = fr.get(key)
        if not f:
            add(title, '<div class="sb" aria-hidden="true"><span class="stubfull"><b>Not recorded</b></span></div>', "not recorded in v1 records", "Not recorded in v1 records.", '<tr><td colspan="2">not recorded in v1 records</td></tr>')
            continue
        names = {nm: nm[0].upper() + nm[1:] for nm in f["cells"]}
        bar, summ, _ = stack_bar(f["cells"], names, th)
        add(title, bar, summ, stack_note(f["cells"], th), rows_of(f["cells"], names, None))
    return f'<div class="sbgrid">{"".join(parts)}</div>', "".join(tables)


def _devices_block(a: dict) -> str:
    body, tables = _stack_panel_parts(a)
    return panel("Where and how the page is opened", "Engaged visits by screen size and the freshness of the data; the page version of the people active in the last completed week.", body, show_data(tables), "p-devices")


def _breakdowns(a: dict) -> str:
    sec, _ = _read_block(a)
    left = f'<div class="stk">{sec}{_actions_block(a)}</div>'
    return (f'<section class="blk" id="breakdowns" aria-labelledby="h-break"><h2 id="h-break">What people read and use</h2><div class="row2e">{left}{_controls_block(a)}</div>'
            f'<div class="sub">{_devices_block(a)}</div></section>')


# ------------------------------------------------------------------------------------------------------------ day and hour
def hour_grid(m: Model) -> dict:
    """Engaged visits by weekday (Israel day of the visit) and hour of the day (Israel time, from the opening time the v2 page records in hours) over the completed weeks. A cell counts its visits and its distinct people; a cell of 1 to 4 people is
    withheld (hatched, no number). No total is printed next to the cells, so no cell can be reconstructed by subtraction. A visit whose opening time does not fall on its own day is not used (counted)."""
    done = set(m.weeks) | ({m.cur} if m.th["show_partial_week"] else set())
    cells: dict = defaultdict(lambda: [0, set()])
    used = skipped = 0
    for r in m.rows:
        if r["glance"] or not r["v2"] or r["ws"] not in done or not is_num(r["s"].get("t")):
            continue
        try:
            t = dt.datetime.fromtimestamp(r["s"]["t"] * 3600, dt.timezone.utc).astimezone(IL)
        except (OverflowError, OSError, ValueError):
            skipped += 1
            continue
        if t.date() != r["day"]:
            skipped += 1
            continue
        k = ((r["day"].weekday() + 1) % 7, t.hour)                                          # 0 = Sunday
        cells[k][0] += 1
        cells[k][1].add(r["u"])
        used += 1
    if used < m.th["heatmap_min_visits"] or used < 1 or len({u for c in cells.values() for u in c[1]}) < MIN_USERS:
        return {"state": "few", "used": used}
    out = {k: ({"state": "none"} if v[0] == 0 else {"state": "small"} if len(v[1]) < MIN_USERS else {"state": "ok", "visits": v[0], "people": len(v[1])}) for k, v in cells.items()}
    hours = sorted({h for _, h in out})
    lo, hi = min(hours), max(hours)
    vals = sorted(c["visits"] for c in out.values() if c["state"] == "ok")
    return {"state": "ok", "cells": out, "hours": list(range(lo, hi + 1)), "vals": vals, "used": used, "skipped": skipped}


def _bucket(v: int, vals: list) -> int:
    """1..HM_BUCKETS: the rank of a cell among the printed cells (quantile buckets), so one busy hour does not turn every other cell to the palest tint."""
    if len(vals) < 2:
        return HM_BUCKETS
    rank = sum(1 for x in vals if x <= v) / len(vals)
    return max(1, min(HM_BUCKETS, math.ceil(rank * HM_BUCKETS)))


def _heatmap_block(a: dict) -> str:
    m = a["model"]
    hg = hour_grid(m)
    head = '<section class="blk" id="when" aria-labelledby="h-when"><h2 id="h-when">When people visit</h2>'
    title = "Engaged visits by weekday and hour"
    if not any(r["v2"] for r in m.rows):
        return head + panel(title, "Israel time.", '<p class="empty-note">Not recorded in v1 records: the earlier page did not record the hour of a visit.</p>') + "</section>"
    if hg["state"] != "ok":
        return head + panel(title, "Israel time.", f'<p class="empty-note">Too early: needs {max(1, int(m.th["heatmap_min_visits"]))} engaged visit{"" if m.th["heatmap_min_visits"] <= 1 else "s"} with a recorded time{"" if MIN_USERS <= 1 else f", and {MIN_USERS} people"}.</p>') + "</section>"
    days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    hours = hg["hours"]
    cells_html, summ, trs = [], [], []
    for d in range(7):
        cells_html.append(f'<span class="d">{days[d]}</span>')
        cs = []
        for h in hours:
            c = hg["cells"].get((d, h), {"state": "none"})
            name = f"{days[d]} {h:02d}:00"
            if c["state"] == "ok":
                b = _bucket(c["visits"], hg["vals"])
                cells_html.append(f'<i class="c v{b}" title="{e(name)}: {c["visits"]} visits"></i>')
                cs.append(f'<td class="n">{c["visits"]}</td>')
                summ.append(f"{name} {c['visits']}")
            elif c["state"] == "small":
                cells_html.append(f'<i class="c h" title="{e(name)}: {e(SMALL)}"></i>')
                cs.append(f'<td class="n">{e(SMALL)}</td>')
                summ.append(f"{name} {SMALL}")
            else:
                cells_html.append(f'<i class="c" title="{e(name)}: none"></i>')
                cs.append('<td class="n">0</td>')
        trs.append(f'<tr><th scope="row">{days[d]}</th>{"".join(cs)}</tr>')
    xh = '<span class="x"></span>' + "".join(f'<span class="x">{h}</span>' for h in hours)
    busy = max(hg["vals"])
    inner = f'<div class="hm" style="--cols:{len(hours)}" aria-hidden="true">{xh}{"".join(cells_html)}</div>'
    ramp = ('<div class="ramp" aria-hidden="true"><span>Fewer visits</span>' + "".join(f'<i class="v{b}"></i>' for b in range(1, HM_BUCKETS + 1)) + f'<span>more (up to {busy} in one hour)</span>'
            '<span class="sep"></span>' + ('<i class="h"></i><span>' + e(SMALL) + '</span>' if MIN_USERS > 1 else '') + '<i></i><span>none</span></div>')
    label = f"Engaged visits by weekday and hour of the day, Israel time, all completed weeks. Cells with fewer than {MIN_USERS} people are withheld. " + "; ".join(summ[:400]) + "."
    table = ('<table id="hours"><thead><tr><th scope="col">Weekday</th>' + "".join(f'<th scope="col" class="n">{h}:00</th>' for h in hours) + f'</tr></thead><tbody>{"".join(trs)}</tbody></table>'
             f'<p class="cap2">Engaged visits per weekday and hour (Israel time) over the completed weeks; {len(hours)} hours from the first to the last hour with a visit. {e(guard_note("A cell of fewer than {n} people shows {g}. No total is shown: it would reveal a withheld cell."))}'
             + (f" {hg['skipped']} visit(s) with an opening time outside their own day were left out." if hg["skipped"] else "") + "</p>")
    cap = "Engaged visits per weekday (rows) and hour of the day (columns, Israel time), all completed weeks. Darker = more visits."
    return head + panel(title, cap, chart_img(inner, label) + ramp, show_data(table), "p-hours") + "</section>"


# ------------------------------------------------------------------------------------------------------------ do people come back
def cohort_grid(m: Model) -> dict:
    """Cohort retention: rows = the week people were first seen (a Sunday-start week), columns = weeks since, a cell = the people of the cohort that were active that week. Only people with a known first day (not before the go-live day,
    not before the 12 weeks kept) are in a cohort, and only completed weeks are columns. A cohort of fewer than 5 people is withheld; a cell is protected as the partition 'returned / not returned' of its cohort, like the week-1 and week-4 figures;
    a percentage is printed from a cohort of 20 people, below that the count."""
    th = m.th
    by_week: dict = defaultdict(list)
    for u in m.people:
        if u in m.pre_golive or m.first_real[u] < m.cutoff:
            continue
        by_week[week_start(m.first_real[u])].append(u)
    rows = []
    for ws in sorted(by_week):
        k_max = (m.last - ws).days // 7
        if k_max < 1:
            continue
        people = by_week[ws]
        n = len(people)
        row = {"ws": ws, "n": n, "n_g": gn(n), "cells": []}
        for k in range(1, k_max + 1):
            if n < MIN_USERS:
                row["cells"].append({"k": k, "state": "small"})
                continue
            w = ws + dt.timedelta(days=7 * k)
            x = sum(1 for u in people if u in m.active(w))
            pc = protect_partition({"ret": x, "not": n - x}, n)
            if pc["ret"] == SMALL:
                row["cells"].append({"k": k, "state": "small"})
            elif n >= th["min_den"]:
                row["cells"].append({"k": k, "state": "pct", "x": x, "pct": rnd(100 * x / n)})
            else:
                row["cells"].append({"k": k, "state": "count", "x": x})
        rows.append(row)
    eligible = [r for r in rows if r["n"] >= MIN_USERS]
    return {"rows": rows, "eligible": len(eligible), "kmax": max((len(r["cells"]) for r in rows), default=0)}


def _cohort_block(a: dict) -> str:
    m = a["model"]
    th = m.th
    cg = cohort_grid(m)
    r_ = a["retention"]
    if not cg["eligible"]:
        body = f'<p class="empty-note">Too early: needs a first-seen week with {MIN_USERS if MIN_USERS > 1 else 1} {"or more people" if MIN_USERS > 1 else "person"} and one completed week after it.</p>'
        table = ""
        summ = ""
    else:
        kmax = cg["kmax"]
        head = '<span class="x"></span>' + "".join(f'<span class="x">+{k}</span>' for k in range(1, kmax + 1))
        cells, trs, summ_l = [], [], []
        for r in cg["rows"]:
            small_row = r["n"] < MIN_USERS
            lbl = f'{d_label(r["ws"])}, ' + (e(SMALL) if small_row else f"n={r['n']}")
            cells.append(f'<span class="rl">{lbl}</span>')
            tds = []
            for ci, c in enumerate(r["cells"]):
                nm = f"{week_label(r['ws'])} cohort, week +{c['k']}"
                if c["state"] == "small":
                    if small_row:                                                           # a cohort under 5 people: one hatched bar for the whole row
                        if ci == 0:
                            cells.append(f'<i class="cc h" style="grid-column:span {len(r["cells"])}" title="{e(week_label(r["ws"]))} cohort: {e(SMALL)}"></i>')
                    else:
                        cells.append(f'<i class="cc h" title="{e(nm)}: {e(SMALL)}"></i>')
                    tds.append(f'<td class="n">{e(SMALL)}</td>')
                    summ_l.append(f"{nm} {SMALL}")
                elif c["state"] == "pct":
                    b = _bucket_pct(c["pct"])
                    cells.append(f'<i class="cc v{b}{" dk" if b >= 5 else ""}" title="{e(nm)}: {c["pct"]}%">{c["pct"]}%</i>')
                    tds.append(f'<td class="n">{c["pct"]}%</td>')
                    summ_l.append(f"{nm} {c['pct']}%")
                else:
                    cells.append(f'<i class="cc n" title="{e(nm)}: {c["x"]} of {r["n"]}">{c["x"]}</i>')
                    tds.append(f'<td class="n">{c["x"]} of {r["n"]}</td>')
                    summ_l.append(f"{nm} {c['x']} of {r['n']}")
            for _ in range(kmax - len(r["cells"])):
                cells.append('<i></i>')
            trs.append(f'<tr><th scope="row">{e(week_label(r["ws"]))}</th><td class="n">{e(SMALL) if small_row else r["n"]}</td>{"".join(tds)}</tr>')
        grid = f'<div class="ch" style="--cols:{kmax}" aria-hidden="true">{head}{"".join(cells)}</div>'
        ramp = ('<div class="ramp" aria-hidden="true"><span>0%</span>' + "".join(f'<i class="v{b}"></i>' for b in range(1, 6)) + '<span>100% back</span><span class="sep"></span><i class="cc n"></i><span>count (cohort under 20)</span>' + ('<i class="h"></i><span>' + e(SMALL) + '</span>' if MIN_USERS > 1 else '') + '</div>')
        label = "Cohort retention: for each week people were first seen, the people active again N weeks later. " + "; ".join(summ_l[:300]) + "."
        body = chart_img(grid, label) + ramp
        table = ('<table id="cohorts"><thead><tr><th scope="col">First seen in the week of</th><th scope="col" class="n">People</th>' + "".join(f'<th scope="col" class="n">+{k} wk</th>' for k in range(1, kmax + 1))
                 + f'</tr></thead><tbody>{"".join(trs)}</tbody></table><p class="cap2">Rows are the people first seen in a Sunday-to-Saturday week; people first seen before the go-live day or before the 12 weeks kept are not in a cohort. A cell is the people active again that many weeks later; '
                 f'a percentage needs a cohort of 20 people, a smaller cohort prints counts, {e(guard_note("a cohort or a cell of fewer than {n} people prints {g}."))} Use it to see whether newcomers stay; never to judge a person or a team.</p>')
    cap = "People active again N weeks after the week they were first seen (completed weeks only)."
    return panel("Do newcomers come back?", cap, body, show_data(table) if table else "", "p-cohorts")


def _bucket_pct(p: int) -> int:
    return 1 if p < 20 else 2 if p < 40 else 3 if p < 60 else 4 if p < 80 else 5


def _return_habit_block(a: dict) -> str:
    th = a["model"].th
    h, r = a["habit"], a["retention"]
    rows = []
    for key, label in (("w1", "Back within a week of the first visit"), ("w4", "Back in week 4 after the first visit")):
        x = r[key]
        if not x["raw_n"]:
            rows.append({"label": label + " (no eligible people yet)", "guard": False, "text": "none yet", "frac": 0})
        elif x["x"] == SMALL:
            rows.append({"label": f"{label} (eligible: {fmt_n(x['n'])})", "guard": True, "text": SMALL, "frac": 0})
        else:
            rows.append({"label": f"{label} (eligible: {x['raw_n']})", "guard": False, "text": share_text(x["x"], x["raw_n"], th), "frac": x["x"] / x["raw_n"]})
    hab_t = ""
    if h["state"] != "ok":
        hab_t = f'<p class="empty-note" id="habit">Habit: {e(h["text"])}</p>'
    else:
        nprint = h["n_print"]
        if nprint == SMALL or h["x"] == SMALL:
            rows.append({"label": f"Active in {h['min_weeks']} or more of the last {h['weeks']} weeks", "guard": True, "text": SMALL, "frac": 0})
        else:
            rows.append({"label": f"Active in {h['min_weeks']} or more of the last {h['weeks']} weeks (established: {nprint})", "guard": False, "text": share_text(h["x"], h["n"], th), "frac": h["x"] / h["n"]})
    chart, summ = hbars(rows)
    body = chart_img(chart, f"Return and habit: {summ}.")
    # the histogram of weeks active
    hist = ""
    data = ""
    if h["state"] == "ok" and h["n_print"] != SMALL and h["bins"]:
        bins = h["bins"]
        mx = max(c for _, _, c in bins) or 1
        lab = lambda lo, hi: f"{lo} week{'s' if lo != 1 else ''}" if lo == hi else f"{lo} to {hi} weeks"
        hrows = [{"label": lab(lo, hi), "guard": False, "text": str(c), "frac": c / mx, "alt": True} for lo, hi, c in bins]
        hchart, hsumm = hbars(hrows, axis=("0", "", f"{mx} people"))
        hlabel = "Weeks active out of the last %d among %s established people: %s." % (h["weeks"], h["n_print"], hsumm)
        hist = f'<div class="sub"><p class="st">Weeks active out of the last {h["weeks"]}, established people</p>{chart_img(hchart, hlabel)}<p class="cap2">{e(guard_note("Neighbouring groups are merged until each has at least {n} people.") or "Every group is shown as it is.")}</p></div>'
        brow = "".join(f'<tr><th scope="row">{e(lab(lo, hi))}</th><td class="n">{num(c)}</td></tr>' for lo, hi, c in bins)
        data = f'<table id="habit-table"><thead><tr><th scope="col">Weeks active</th><th scope="col" class="n">People</th></tr></thead><tbody>{brow}</tbody></table>'
    rrows = []
    for key, label, when in (("w1", "Week 1", "a visit on a later day within 7 days of the first visit"), ("w4", "Week 4", "a visit in days 22 to 28 after the first visit")):
        x = r[key]
        res = "no eligible people yet" if not x["raw_n"] else sh(x["x"], x["raw_n"], th) + (" (indicative)" if x["indicative"] else "")
        rrows.append(f'<tr><th scope="row">{label}: {e(when)}</th><td class="n">{num(x["n"])}</td><td class="n">{res}</td></tr>')
    table = (f'<table id="retention"><thead><tr><th scope="col">Retention</th><th scope="col" class="n">Eligible people</th><th scope="col" class="n">Came back</th></tr></thead><tbody>{"".join(rrows)}</tbody></table>'
             + (f'<p class="cap2" id="habit">Habit: {sh(h["x"], h["n"], th) if h["n_print"] != SMALL and h["x"] != SMALL else e(SMALL)} of {num(h["n_print"])} established people were active in {h["min_weeks"]} or more of the last {h["weeks"]} completed weeks ({e(h["window"])}). Established = first seen at least 14 days before the compared week.</p>' if h["state"] == "ok" else "")
             + data + '<p class="cap2">Retention follows people first seen at least 7 (or 28) days ago; people that arrived later are not in the figure yet. Indicative under 30 people.</p>')
    return panel("Return and habit", "Share of eligible people that came back, and of established people active in 4 or more of the last 8 weeks.", body + hist + hab_t, show_data(table), "p-habit")


def _back_block(a: dict) -> str:
    return (f'<section class="blk" id="back" aria-labelledby="h-back"><h2 id="h-back">Do people come back?</h2><div class="row2">{_cohort_block(a)}{_return_habit_block(a)}</div></section>')


# ------------------------------------------------------------------------------------------------------------ recording health
def _health_block(a: dict) -> str:
    th = a["model"].th
    m = a["model"]
    h = a["health"]
    rows = [("Visits in the data", f"{fmt_n(h['visits_g'])}", f"{fmt_n(h['v2_g'])} from the newer page, {num(h['v1_visits'])} from the earlier page ({num(h['v1_people'])} people)")]
    bars, stacks = [], ""
    if h["has_v2"]:
        gl = h["glance"]
        rows += [("Glance visits", sh(gl["x"], gl["n_g"], th), f"of {fmt_n(gl['n_g'])} visits; engaged visits {num(gl['engaged'])}. A glance is 5 seconds or more with no input and under 30 seconds. Engaged = 30 seconds or more, or with input."),
                 ("Visible, no active seconds", sh(h["focus"]["x"], h["focus"]["n_g"], th), "visits with visible time but no active seconds: a high share points at a focus problem in the page frame, not at idle readers"),
                 ("Real page errors", sh(h["errors_real"]["x"], h["errors_real"]["n_g"], th), "of visits (v2 pages)"),
                 ("Benign notifications", sh(h["errors_benign"]["x"], h["errors_benign"]["n_g"], th), "counted apart and never flagged")]
        cells = {"glance": gl["x"], "engaged": gl["engaged"]}
        sbar, ssum, _ = stack_bar(cells, {"glance": "Glance visits", "engaged": "Engaged visits"}, th)
        stacks = f'<div class="sub"><p class="st">Glance and engaged visits (newer page)</p>{chart_img(sbar, "Glance and engaged visits: " + ssum)}<p class="cap2">{e(stack_note(cells, th))}</p></div>'

        def share_row(label, d):
            if d["x"] == SMALL:
                return {"label": label, "guard": True, "text": SMALL, "frac": 0}
            return {"label": label, "guard": False, "text": share_text(d["x"], d["n"], th), "frac": (d["x"] / d["n"]) if d["n"] else 0}
        bars += [share_row("Real page errors (of visits)", h["errors_real"]), share_row("Benign notifications (of visits)", h["errors_benign"]), share_row("Visible but no active seconds (of visits)", h["focus"]), share_row("Visits that dropped keys (of visits)", h["dropped"])]
    else:
        rows.append(("Glance visits, focus, benign errors", "-", "not recorded in v1 records: the data holds only the earlier page's visits, so adoption is probably under-counted"))
        bars.append({"label": "Visits that dropped keys (of visits)", "guard": h["dropped"]["x"] == SMALL, "text": share_text(h["dropped"]["x"], h["dropped"]["n"], th) if h["dropped"]["x"] != SMALL else SMALL, "frac": (h["dropped"]["x"] / h["dropped"]["n"]) if (h["dropped"]["x"] != SMALL and h["dropped"]["n"]) else 0})
    if h["attributed"] is not None:
        bars.append({"label": "Active time attributed to a section", "guard": False, "text": f"{h['attributed']}%", "frac": h["attributed"] / 100, "alt": True})
    rows += [("Visits that dropped keys", sh(h["dropped"]["x"], h["dropped"]["n_g"], th), "at the 40-key cap"),
             ("Active time attributed to a section", num(h["attributed"], "%") if h["attributed"] is not None else "-", "of active seconds"),
             ("Records not opened for over 12 weeks", num(h["stale_records"]), f"their weeks are left out; delete them. {h['stale_sessions']} sessions older than 12 weeks were ignored"),
             ("Records cut by the size cap", num(h["pruned_records"]), "older weeks dropped to keep a record small")]
    chart, summ = hbars(bars)
    left = stacks or '<p class="empty-note">Glance and engaged visits: not recorded in v1 records.</p>'
    body = f'<div class="row2e"><div>{left}</div><div>{chart_img(chart, "Recording health: " + summ + ".")}</div></div>'
    trs = "".join(f'<tr><th scope="row">{e(n)}<div class="cap2">{e(d)}</div></th><td class="n">{v}</td></tr>' for n, v, d in rows)
    table = f'<table id="health" class="two"><thead><tr><th scope="col">Check and reading</th><th scope="col" class="n">Result</th></tr></thead><tbody>{trs}</tbody></table>'
    return ('<section class="blk" id="recording" aria-labelledby="h-health"><h2 id="h-health">Recording health</h2>'
            + panel("Can the measurement be trusted?", "How the page recorded visits, not how people use it; shares of visits unless named.", body, show_data(table), "p-health") + "</section>")


def _measure_block(a: dict | None = None) -> str:
    return ('<section class="blk" aria-labelledby="h-how"><h2 id="h-how">How this is measured</h2>'
            f'<ul class="gov" id="governance">{"".join(f"<li>{e(x)}</li>" for x in gov())}</ul>'
            '<details class="vd" id="how"><summary>What is counted and what is not</summary>'
            f'<p class="cap">{e(coverage_not_counted())}</p>'
            '<p class="cap">The published Delivery Pulse page counts, for each person with an id, which sections they read, which filters and buttons they use, which Jira links they follow (by section only), how long the page is open in front of them and in use, '
            'their screen size, the page version, how fresh the data was, the hour a visit opened and page errors. It records no names, e-mail addresses, issue keys, project, team or pod names or search text. People that are signed out or hold view-only access, that open an offline copy, '
            'or whose browser blocks the page&#39;s storage are not counted, so these are counts of people with an id, not of all visitors. A visit that is only looked at for 5 seconds or more is recorded as a glance; a visit with input or 30 seconds or more is an engaged visit. '
            f'Weeks run Sunday to Saturday and count as complete once Saturday has passed. {e(guard_note("Any figure that rests on fewer than {n} people shows {g}."))} Weeks before the first record show "before the data starts", not zero. '
            'This page is a snapshot of an export, not a live view.</p></details></section>')


def ribbon_text(a: dict) -> str:
    """The coverage ribbon: two lines at most on a desktop. The longer list of what is not counted is under 'How this is measured'. It says the small-group setting in force."""
    who = _who(a)
    span = f", {d_label(a['first_day'])} to {fmt_date(a['last_day'])} (Israel time)" if a["first_day"] else ""
    aud = f", of an audience of {a['audience']['size']} (a lower bound)" if a["audience"] else ""
    return (f"Based on {who} with an id{span}{aud}. Pseudonymous, not anonymous. Not counted: signed-out, view-only, offline-copy and storage-blocked visitors. "
            + small_rule(ribbon=True) + " Never used to rank or assess people or teams.")


def _period(a: dict) -> str:
    m = a["model"]
    if not m.weeks:
        return ""
    return f"Period: {len(m.weeks)} completed week{'s' if len(m.weeks) != 1 else ''}, {d_label(m.weeks[0])} to {d_label(m.weeks[-1] + dt.timedelta(days=6))} (Sunday to Saturday), and the week in progress."


def html_report(a: dict, standalone: bool = False) -> str:
    """The page: an Artifact fragment (own title, inline style, no script). Order, as in an analytics report: coverage ribbon, key figures with sparklines, the trend (people per week, per day),
    the breakdowns (sections, controls, actions, devices), when people visit, whether they come back, recording health, how this is measured."""
    set_min_group(a["model"].th.get("min_group", 5))
    stamp = il_stamp(a["as_of"]) or f"{a['ref']} (no export time given)"
    out: list = []
    add = out.append
    add('<title>Delivery Pulse Usage</title>\n<meta name="claude:viewport-fit-sides" content="cover">\n<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600&display=swap">')
    add(f"<style>{CSS}</style>")
    per = _period(a) if a["n_sessions"] else ""
    add(f'<header class="top gutter"><h1>Delivery Pulse Usage</h1><span class="stamp" id="asof">Data as of {e(stamp)}</span>' + (f'<span class="period" id="period">{e(per)}</span>' if per else "") + '</header>')
    add('<main class="gutter">')
    if a["demo"]:
        add('<p class="demo" id="demo-banner" role="note">Demo data: this page shows fictitious people and numbers so the layout can be reviewed. It says nothing about real use.</p>')
    for w in export_warnings(a):
        add(f'<p class="warn" role="status">{ICON_WARN}<span>{e(w)}</span></p>')
    add(f'<p class="ribbon" id="coverage"><b>Coverage.</b> {e(ribbon_text(a))}</p>')
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
            add(f'<p class="note" id="caveat">Only {a["history_days"]} day{"" if a["history_days"] == 1 else "s"} of data so far: trends are not meaningful yet.</p>')
        if a["audience"] and a["audience"]["stale"]:
            add('<p class="note" id="audience-note">The audience size looks out of date: more people are in the data than in the audience.</p>')
        add(_kpis(a))
        add(_trend(a))
        add(_breakdowns(a))
        add(_heatmap_block(a))
        add(_back_block(a))
        add(_health_block(a))
    add(_measure_block(a))
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


SHOW_ALL = {"min_group": 1, "min_den": 1, "heatmap_min_visits": 1, "show_partial_week": 1}      # --show-all: the minimums on what is drawn, off


def load_thresholds(path: str | None, base: dict | None = None) -> dict:
    th = {**THRESHOLDS, **(base or {})}
    if path:
        over = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(over, dict):
            raise ValueError("the thresholds file must be a JSON object")
        for k, v in over.items():
            if k not in THRESHOLDS:
                raise ValueError(f"unknown threshold {k!r}; known: {', '.join(sorted(THRESHOLDS))}")
            if not is_num(v):
                raise ValueError(f"threshold {k!r} must be a number")
            if k == "min_group" and (int(v) != v or v < 1):
                raise ValueError("threshold 'min_group' must be a whole number of 1 or more")
            th[k] = int(v) if k == "min_group" else v
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
    ap.add_argument("--min-group", type=int, help="the smallest group of people a number is shown for (default 5; 1 shows every number as it is: with few people the numbers describe individual visits, so keep the page private)")
    ap.add_argument("--show-all", action="store_true", help="remove the minimums on what is drawn: every number for any group size (min group 1), percentages for any denominator, the day-and-hour map from one visit, and the week in progress (to date) in the views that need a completed week. The statistical verdicts (growth, change signals, simplify candidates, habit) keep their own rules because they compare weeks; a thresholds file still overrides this")
    ap.add_argument("--text", action="store_true", help="also print the text report when --html is given")
    a = ap.parse_args(argv)
    now = dt.datetime.now(IL)
    as_of = parse_as_of(a.as_of)
    today = dt.date.fromisoformat(a.today) if a.today else None
    since = dt.date.fromisoformat(a.since) if a.since else None
    th = load_thresholds(a.thresholds, base=SHOW_ALL if a.show_all else None)
    if a.min_group is not None:
        if a.min_group < 1:
            ap.error("--min-group must be 1 or more")
        th["min_group"] = a.min_group
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
