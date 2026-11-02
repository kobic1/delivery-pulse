#!/usr/bin/env python3
"""Owner report for the Delivery Pulse usage statistics: an aggregate text report and a self-contained dashboard page ("Delivery Pulse Usage").

The published Delivery Pulse page keeps one small record per person, `usage/<opaque user id>`, in its own artifact database (see the "Usage statistics" section of
program_dashboard/README.md for the record, the vocabulary and the access rules). Export those documents with the ArtifactData tool (`list`, collection `usage`) into a JSON file and run:

    python3 program_dashboard/usage_report.py export.json                           # text report on the screen
    python3 program_dashboard/usage_report.py export.json --html usage.html --as-of 2026-11-02T10:15:00+02:00
    python3 program_dashboard/usage_report.py --demo --html usage_demo.html         # the same page from fictitious data (a "Demo data" banner), to review the layout

The input is a JSON list of the documents. Both shapes are accepted: the bodies themselves, or {"id": ..., "data": {body}} rows (also "doc_id"/"data", and a wrapper object holding the list under
"documents", "docs", "items", "rows" or "results"). The id of a document is never read: users are told apart by their position in the file, and no user id is ever printed or written to the page.

Privacy rule of the report: every breakdown that rests on fewer than 5 distinct people prints "<5 users" instead of a number (and its chart bar is not drawn), so that nobody can be picked out of a small group.
Counts, shares and percentiles are computed over what the people's browsers recorded; people who are signed out, who hold view-only access, who open an offline copy, or whose browser blocks the page's storage are not in the data.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import math
import random
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

# The vocabularies the page records (program_dashboard/dashboard.template.html, USAGE_VOC) with the plain names a reader of this report knows. tests/test_usage_report.py keeps the keys equal to the page's.
SECTIONS = {"attn": "Needs Attention", "burnup": "Delivery", "eff": "Efficiency", "ai": "AI Adoption", "bugs": "Quality", "deps": "Dependencies", "nfr": "NFRs", "cx": "CXCROSS", "capview": "Capabilities", "cycles": "Cycles", "analysis": "Release Analysis"}
LINK_SECTIONS = {**SECTIONS, "other": "Outside a section"}
CONTROLS = {"release": "Release", "projects": "Projects", "multi": "Multi-select toggle", "teams": "Teams", "dc": "Delivery Cycle", "ax": "Accessibility Bugs", "cfb": "Customer-Found Bugs", "bugpri": "Bug priority",
            "gran": "Week, Month or Quarter", "cfbgrp": "Customer-found bugs grouping", "dp": "Dependencies view", "nfrtab": "NFR tabs", "cx": "CXCROSS commitment type", "caplevel": "Capability commitment level",
            "capby": "Capitalization grouping", "capmeasure": "Capitalization measure", "cycle": "Cycle choice", "cytab": "Cycles detail tab", "cystatus": "Cycles status filter", "cypods": "Pod lists"}
DISCLOSURES = {"how": "How this is calculated", "data": "Show data", "attn": "Needs Attention details", "other": "Other details"}
DEVICES = {"s": "Small screen (up to 480 px)", "m": "Medium screen (up to 900 px)", "l": "Large screen"}


# ------------------------------------------------------------------------------------------------------------ loading
def load_bodies(raw) -> list[dict]:
    """The record bodies from the JSON an export holds: a list of bodies, a list of {id, data} rows, or an object wrapping such a list."""
    if isinstance(raw, dict):
        for k in ("documents", "docs", "items", "rows", "results"):
            if isinstance(raw.get(k), list):
                raw = raw[k]
                break
        else:
            raise ValueError("expected a list of documents (or an object with a list under documents, docs, items, rows or results)")
    if not isinstance(raw, list):
        raise ValueError("expected a list of documents")
    out = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        body = row["data"] if isinstance(row.get("data"), dict) and ("w" not in row or "id" in row or "doc_id" in row) else row
        if isinstance(body.get("w"), dict):
            out.append(body)
    return out


def iso_week_key(d: dt.date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def sessions_of(bodies: list[dict]) -> list[dict]:
    """One row per session: {u: position of the person in the file, day: date, week: key, s: the session body}. Rows that do not parse are skipped."""
    rows = []
    for u, b in enumerate(bodies):
        for wk, days in (b.get("w") or {}).items():
            if not isinstance(days, dict):
                continue
            for day, sess in days.items():
                try:
                    d = dt.date.fromisoformat(day)
                except (TypeError, ValueError):
                    continue
                for sid, s in (sess or {}).items():
                    if isinstance(s, dict):
                        rows.append({"u": u, "day": d, "week": wk, "s": s})
    return rows


# ------------------------------------------------------------------------------------------------------------ aggregation
def g(users: int, value):
    """The small-group guard: a figure resting on 1 to 4 distinct people is replaced by the text "<5 users" (an empty group is a plain 0: it points at nobody)."""
    return value if users == 0 or users >= MIN_USERS else SMALL


def is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def percentile(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    if len(xs) == 1:
        return xs[0]
    k = (len(xs) - 1) * p
    lo, hi = math.floor(k), math.ceil(k)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def _count(rows: list[dict], key: str, names: dict) -> dict:
    """Per key of a counter map ("f", "l", "o", "nav"): total and distinct people, guarded."""
    tot, who = defaultdict(int), defaultdict(set)
    for r in rows:
        for k, v in (r["s"].get(key) or {}).items():
            if k in names and is_num(v) and v > 0:
                tot[k] += int(v)
                who[k].add(r["u"])
    return {k: {"n": g(len(who[k]), tot[k]), "users": g(len(who[k]), len(who[k])), "raw_users": len(who[k])} for k in names if k in tot}


def aggregate(bodies: list[dict], today: dt.date | None = None, as_of: dt.datetime | None = None, demo: bool = False) -> dict:
    rows = sessions_of(bodies)
    days_seen = sorted({r["day"] for r in rows})
    today = today or (as_of.astimezone(IL).date() if as_of and as_of.tzinfo else (as_of.date() if as_of else (days_seen[-1] if days_seen else dt.datetime.now(IL).date())))
    users_all = {r["u"] for r in rows}
    n_users = len(users_all)
    first_day = days_seen[0] if days_seen else None
    history_days = (today - first_day).days + 1 if first_day else 0

    def users_on(lo: dt.date, hi: dt.date) -> set:
        return {r["u"] for r in rows if lo <= r["day"] <= hi}
    a7, p7 = users_on(today - dt.timedelta(days=6), today), users_on(today - dt.timedelta(days=13), today - dt.timedelta(days=7))
    by_day = defaultdict(set)
    for r in rows:
        by_day[r["day"]].add(r["u"])
    per_day = [{"day": today - dt.timedelta(days=i), "users": g(len(by_day.get(today - dt.timedelta(days=i), ())), len(by_day.get(today - dt.timedelta(days=i), ()))),
                "raw": len(by_day.get(today - dt.timedelta(days=i), ())), "has_data": bool(first_day and today - dt.timedelta(days=i) >= first_day)} for i in range(27, -1, -1)]
    by_week = defaultdict(set)
    sess_week = defaultdict(int)
    for r in rows:
        by_week[iso_week_key(r["day"])].add(r["u"])
        sess_week[iso_week_key(r["day"])] += 1
    weeks = []
    for i in range(11, -1, -1):
        d0 = today - dt.timedelta(days=7 * i)
        k = iso_week_key(d0)
        monday = d0 - dt.timedelta(days=d0.weekday())
        has = bool(first_day and monday + dt.timedelta(days=6) >= first_day)
        n = len(by_week.get(k, ()))
        weeks.append({"week": k, "monday": monday, "users": g(n, n) if has else None, "raw": n, "has_data": has, "partial": k == iso_week_key(today), "sessions": sess_week.get(k, 0) if has else None})
    # returning users: two or more distinct days in the window the page keeps
    days_per_user = defaultdict(set)
    for r in rows:
        days_per_user[r["u"]].add(r["day"])
    returning = sum(1 for d in days_per_user.values() if len(d) >= 2)
    # sessions this week and per active user
    this_week = "last 7 days"
    wk_rows = [r for r in rows if today - dt.timedelta(days=6) <= r["day"] <= today]
    wk_users = {r["u"] for r in wk_rows}
    # visible minutes per session (sessions with some active time)
    mins = [r["s"]["s"] / 60 for r in rows if is_num(r["s"].get("s")) and r["s"]["s"] > 0]
    mins_users = {r["u"] for r in rows if is_num(r["s"].get("s")) and r["s"]["s"] > 0}
    # time share per section
    secs, sec_users = defaultdict(float), defaultdict(set)
    for r in rows:
        for k, v in (r["s"].get("sec") or {}).items():
            if k in SECTIONS and is_num(v) and v > 0:
                secs[k] += v
                sec_users[k].add(r["u"])
    sec_total = sum(secs.values())
    section_time = [{"key": k, "name": SECTIONS[k], "seconds": secs[k], "share": g(len(sec_users[k]), round(100 * secs[k] / sec_total, 1) if sec_total else 0), "users": g(len(sec_users[k]), len(sec_users[k])),
                     "raw_share": 100 * secs[k] / sec_total if sec_total else 0, "raw_users": len(sec_users[k])} for k in SECTIONS if k in secs]
    section_time.sort(key=lambda x: -x["seconds"])
    controls = _count(rows, "f", CONTROLS)
    nav = _count(rows, "nav", SECTIONS)
    links = _count(rows, "l", LINK_SECTIONS)
    discl = _count(rows, "o", DISCLOSURES)
    # filters used by X% of the active users of the last 7 days
    w7 = [r for r in rows if today - dt.timedelta(days=6) <= r["day"] <= today]
    f_users = {r["u"] for r in w7 if any(is_num(v) and v > 0 for v in (r["s"].get("f") or {}).values())}
    def clicks(key):
        tot, who = 0, set()
        for r in rows:
            v = r["s"].get(key)
            if is_num(v) and v > 0:
                tot += int(v)
                who.add(r["u"])
        return {"n": g(len(who), tot), "users": g(len(who), len(who)), "raw_users": len(who)}
    # devices: people who used each class (one person can be in two)
    dev_users, dev_sess = defaultdict(set), defaultdict(int)
    for r in rows:
        d = r["s"].get("d")
        if d in DEVICES:
            dev_users[d].add(r["u"]); dev_sess[d] += 1
    # build: each person's latest session decides which version they are on
    latest: dict = {}
    for r in rows:
        t, b = r["s"].get("t"), r["s"].get("b")
        if isinstance(b, str) and is_num(t) and (r["u"] not in latest or t > latest[r["u"]][0]):
            latest[r["u"]] = (t, b)
    on_build = defaultdict(set)
    for u, (_, b) in latest.items():
        on_build[b].add(u)
    newest = max(latest.values())[1] if latest else None
    err_users = {r["u"] for r in rows if is_num(r["s"].get("er")) and r["s"]["er"] > 0}
    err_total = sum(int(r["s"]["er"]) for r in rows if is_num(r["s"].get("er")) and r["s"]["er"] > 0)
    return {
        "today": today, "as_of": as_of, "demo": demo, "n_docs": len(bodies), "n_sessions": len(rows), "history_days": history_days, "first_day": first_day,
        "users_total": {"n": g(n_users, n_users), "raw": n_users},
        "active7": {"n": g(len(a7), len(a7)), "raw": len(a7)}, "prev7": {"n": g(len(p7), len(p7)), "raw": len(p7)},
        "per_day": per_day, "per_week": weeks,
        "returning": {"n": g(n_users, returning), "of": g(n_users, n_users), "pct": g(n_users, round(100 * returning / n_users) if n_users else 0), "raw": returning, "raw_of": n_users},
        "this_week": {"week": this_week, "sessions": g(len(wk_users), len(wk_rows)), "users": g(len(wk_users), len(wk_users)), "raw_sessions": len(wk_rows), "raw_users": len(wk_users),
                      "per_user": g(len(wk_users), round(len(wk_rows) / len(wk_users), 1) if wk_users else 0)},
        "minutes": {"median": g(len(mins_users), round(statistics.median(mins), 1)) if mins else None, "p90": g(len(mins_users), round(percentile(mins, 0.9), 1)) if mins else None,
                    "sessions": len(mins), "users": g(len(mins_users), len(mins_users)), "raw_users": len(mins_users)},
        "section_time": section_time, "nav": nav, "controls": controls, "links": links, "disclosures": discl,
        "filters_used": {"users": g(len(f_users), len(f_users)), "of": g(len(a7), len(a7)), "pct": g(len(f_users), round(100 * len(f_users) / len(a7)) if a7 else 0), "raw": len(f_users), "raw_of": len(a7)},
        "refresh": clicks("r"), "reset": clicks("rs"),
        "devices": [{"key": k, "name": DEVICES[k], "users": g(len(dev_users[k]), len(dev_users[k])), "sessions": g(len(dev_users[k]), dev_sess[k]), "raw_users": len(dev_users[k])} for k in DEVICES if k in dev_users],
        "builds": sorted([{"build": b, "users": g(len(u), len(u)), "raw_users": len(u), "newest": b == newest} for b, u in on_build.items()], key=lambda x: (-x["raw_users"], x["build"])),
        "errors": {"total": g(len(err_users), err_total) if err_users else 0, "users": g(len(err_users), len(err_users)) if err_users else 0, "any": bool(err_users), "raw_users": len(err_users)},
    }


# ------------------------------------------------------------------------------------------------------------ the text report
def fmt(v, unit: str = "") -> str:
    return v if v == SMALL else ("-" if v is None else f"{v}{unit}")


def cnt(v, noun: str) -> str:
    """A count with its noun, or the guard text alone: '12 users' or '<5 users', never '<5 users users'."""
    return SMALL if v == SMALL else f"{v} {noun}"


def text_report(a: dict) -> str:
    L: list[str] = []
    add = L.append
    add(f"Delivery Pulse usage, as of {a['today']}" + ("   [DEMO DATA]" if a["demo"] else ""))
    add(f"{a['n_docs']} user records, {a['n_sessions']} sessions, {a['history_days']} days of history. Any figure resting on fewer than {MIN_USERS} people prints '{SMALL}'.")
    if not a["n_sessions"]:
        add("\nNo usage data yet.")
        return "\n".join(L) + "\n"
    if a["history_days"] < SHORT_HISTORY_DAYS:
        add(f"NOTE: only {a['history_days']} days of data so far: trends are not meaningful yet.")
    add("\nPeople")
    add(f"  distinct users in the data:        {fmt(a['users_total']['n'])}")
    add(f"  active in the last 7 days:         {fmt(a['active7']['n'])}   (the 7 days before: {fmt(a['prev7']['n'])})")
    add(f"  returning (2 or more days):        {fmt(a['returning']['n'])} of {fmt(a['returning']['of'])} ({fmt(a['returning']['pct'], '%')})")
    add("  distinct users per day, last 14 days:")
    for d in a["per_day"][-14:]:
        add(f"    {d['day']}  {fmt(d['users']) if d['has_data'] else '(before the data starts)'}")
    add("  distinct users per ISO week:")
    for w in a["per_week"]:
        add(f"    {w['week']}  {fmt(w['users']) if w['has_data'] else '(before the data starts)'}" + ("  (week in progress)" if w["partial"] else ""))
    tw = a["this_week"]
    add(f"\nVisits\n  last 7 days: {cnt(tw['sessions'], 'sessions')} by {cnt(tw['users'], 'users')}, {fmt(tw['per_user'])} per active user")
    add("  sessions per ISO week: " + ", ".join(f"{w['week']}={w['sessions']}" for w in a["per_week"] if w["has_data"] and w["raw"] >= MIN_USERS) + "  (weeks under 5 users left out)")
    m = a["minutes"]
    add(f"  visible minutes per session (sessions with some active time): median {fmt(m['median'])}, p90 {fmt(m['p90'])}   [{cnt(m['users'], 'users')}]")
    add("\nReading time per section")
    for s in a["section_time"]:
        add(f"  {s['name']:<18} {fmt(s['share'], '%'):>9}   {cnt(s['users'], 'users')}")
    add("\nControls changed")
    for k, c in sorted(a["controls"].items(), key=lambda kv: (-(kv[1]["n"] if is_num(kv[1]["n"]) else -1), kv[0])):
        add(f"  {CONTROLS[k]:<32} {fmt(c['n']):>9}   {cnt(c['users'], 'users')}   (changes)")
    f = a["filters_used"]
    add(f"  filters used by {fmt(f['pct'], '%')} of active users in the last 7 days ({fmt(f['users'])} of {fmt(f['of'])} people)")
    add("\nJira links followed, by section")
    for k, c in sorted(a["links"].items(), key=lambda kv: (-(kv[1]["n"] if is_num(kv[1]["n"]) else -1), kv[0])):
        add(f"  {LINK_SECTIONS[k]:<18} {fmt(c['n']):>9}   {cnt(c['users'], 'users')}   (clicks)")
    add("\nDetails opened")
    for k, c in discl_sorted(a):
        add(f"  {DISCLOSURES[k]:<26} {fmt(c['n']):>9}   {cnt(c['users'], 'users')}   (opens)")
    add(f"\nRefresh: {cnt(a['refresh']['n'], 'clicks')} by {cnt(a['refresh']['users'], 'users')}.  Reset Filters: {cnt(a['reset']['n'], 'clicks')} by {cnt(a['reset']['users'], 'users')}.")
    add("\nScreen size (a person can appear in more than one row)")
    for d in a["devices"]:
        add(f"  {d['name']:<30} {cnt(d['users'], 'users')}")
    add("\nPage version (each person's latest visit)")
    for b in a["builds"]:
        add(f"  {b['build']:<14} {cnt(b['users'], 'users')}" + ("  (newest seen)" if b["newest"] else ""))
    e = a["errors"]
    add(f"\nPage errors: {cnt(e['total'], 'errors')} recorded, {cnt(e['users'], 'users')} affected" + ("   NEEDS ATTENTION" if e["any"] else ""))
    return "\n".join(L) + "\n"


def discl_sorted(a: dict):
    return sorted(a["disclosures"].items(), key=lambda kv: (-(kv[1]["n"] if is_num(kv[1]["n"]) else -1), kv[0]))


# ------------------------------------------------------------------------------------------------------------ the demo data (fictitious)
def demo_bodies(today: dt.date, users: int = 40, weeks: int = 12, seed: int = 20261102) -> list[dict]:
    """About 40 fictitious people over 12 weeks. Ids are u_synthetic_001...; a few controls and sections are used by only a few people so that the small-group guard shows."""
    r = random.Random(seed)
    out = []
    w_sec = {"attn": 18, "burnup": 24, "eff": 8, "ai": 7, "bugs": 14, "deps": 9, "nfr": 4, "cx": 3, "capview": 5, "cycles": 11, "analysis": 6}
    w_ctl = {"release": 30, "projects": 22, "teams": 14, "multi": 9, "dc": 8, "ax": 5, "cfb": 7, "bugpri": 6, "gran": 10, "nfrtab": 4, "caplevel": 3, "capby": 3, "capmeasure": 2, "cycle": 6, "cytab": 5, "cystatus": 3, "dp": 5, "cfbgrp": 2, "cx": 2}
    builds = ["c0ffee1", "5ca1ab1"]
    for i in range(users):
        uid = f"u_synthetic_{i + 1:03d}"
        habit = r.choice([0.05, 0.1, 0.15, 0.25, 0.4, 0.55])                                 # how often this person opens the page on a weekday
        start = r.randint(0, 20) if i % 3 == 0 else 0                                 # some people arrive later: the trend grows
        dev = "s" if i % 9 == 0 else "m" if i % 6 == 0 else "l"
        wmap: dict = {}
        for day_i in range(weeks * 7 - 1, -1, -1):
            d = today - dt.timedelta(days=day_i)
            if d.weekday() in (4, 5) or (weeks * 7 - day_i) < start or r.random() > habit:
                continue
            for _ in range(1 if r.random() < 0.8 else 2):
                s_sec = max(5, int(r.lognormvariate(5.3, 0.9)) // 5 * 5)
                secs = {}
                budget = s_sec
                for k in r.sample(list(w_sec), r.randint(1, 5)):
                    if k in ("nfr", "cx") and i >= 3 + (r.random() < 0.2):          # NFRs and CXCROSS: read by only a handful of people
                        continue
                    share = min(budget, max(5, int(s_sec * w_sec[k] / 40) // 5 * 5))
                    secs[k] = share; budget -= share
                sess: dict = {"t": 29_900_000 + r.randint(0, 10_000_000), "s": sum(secs.values()), "sec": secs, "d": dev, "b": builds[0] if (today - d).days < 12 and i % 4 else builds[1], "np": r.choice([7, 7, 7, 3, 1])}
                nav = {k: r.randint(1, 3) for k in r.sample(list(w_sec), r.randint(0, 3)) if k not in ("nfr", "cx") or i < 3}
                if nav:
                    sess["nav"] = nav
                f = {k: r.randint(1, 3) for k, wgt in w_ctl.items() if r.random() < wgt / 160 and (k != "dp" or i < 4) and (k != "cypods" or i < 3)}
                if i < 3 and r.random() < 0.3:
                    f["cypods"] = r.randint(1, 4)                                     # three people only: shows '<5 users'
                if f:
                    sess["f"] = f
                lk = {k: r.randint(1, 4) for k in ("attn", "bugs", "deps", "burnup") if r.random() < 0.18}
                if i < 2 and r.random() < 0.4:
                    lk["capview"] = 1                                                 # two people only
                if lk:
                    sess["l"] = lk
                o = {k: 1 for k, p in (("how", 0.2), ("data", 0.12), ("attn", 0.1), ("other", 0.03)) if r.random() < p}
                if o:
                    sess["o"] = o
                if r.random() < 0.05:
                    sess["r"] = 1
                if r.random() < 0.04:
                    sess["rs"] = 1
                if i in (7, 19) and r.random() < 0.5:
                    sess["er"] = 1
                wmap.setdefault(iso_week_key(d), {}).setdefault(d.isoformat(), {})["".join(r.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(8))] = sess
        if wmap:
            first = min(d for wk in wmap.values() for d in wk)
            last = max(d for wk in wmap.values() for d in wk)
            out.append({"u": uid, "v": 1, "first": first, "last": last, "w": wmap})
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
.top { padding-top:20px; display:flex; flex-wrap:wrap; align-items:baseline; gap:4px 16px; }
.stamp { color:var(--muted); font-size:var(--t-cap); }
.lede { color:var(--muted); margin:2px 0 0; font-size:var(--t-body); }
.demo { margin:12px 0 0; padding:8px 12px; background:var(--warn-bg); border:1px solid var(--warn-line); border-radius:var(--radius-s); color:var(--warn-ink); font-weight:600; font-size:var(--t-body); }
.note { margin:12px 0 0; padding:8px 12px; background:var(--panel); border-radius:var(--radius-s); font-size:var(--t-body); }
.hero { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1.3fr); gap:12px 40px; align-items:end; padding:28px 0 24px; border-bottom:1px solid var(--line); }
.hero .fig { font-size:var(--t-hero); font-weight:600; line-height:1.05; font-variant-numeric:tabular-nums; margin:0; }
.hero .what { font-size:var(--t-sub); margin:4px 0 0; }
.hero .ctx { color:var(--muted); font-size:var(--t-body); margin:4px 0 0; }
.spark { display:block; width:100%; height:96px; }
.spark .ln { fill:none; stroke:var(--blue-ink); stroke-width:2.5; stroke-linejoin:round; stroke-linecap:round; vector-effect:non-scaling-stroke; }
.spark .dot { fill:var(--blue-ink); }
.sparkcap { display:flex; justify-content:space-between; gap:8px; color:var(--muted); font-size:var(--t-xs); margin-top:2px; }
.strip { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); border-bottom:1px solid var(--line); }
.strip > div { padding:16px 20px 16px 0; }
.strip > div + div { padding-left:20px; border-left:1px solid var(--line-soft); }
.strip .v { font-size:var(--t-fig); font-weight:600; line-height:1.15; font-variant-numeric:tabular-nums; margin:0; }
.strip .l { margin:2px 0 0; font-size:var(--t-body); }
.strip .c { margin:2px 0 0; color:var(--muted); font-size:var(--t-cap); }
section.blk { padding:28px 0 4px; }
section.blk .why { color:var(--muted); margin:0 0 12px; }
.days { display:flex; align-items:flex-end; gap:3px; height:150px; border-bottom:1px solid var(--ctl); }
.days .d { flex:1 1 0; min-width:0; background:var(--blue-ink); border-radius:2px 2px 0 0; }
.days .gap { flex:1 1 0; min-width:0; height:100%; display:flex; align-items:flex-end; justify-content:center; color:var(--muted); font-size:var(--t-xs); }
.dayaxis { display:flex; justify-content:space-between; color:var(--muted); font-size:var(--t-xs); margin-top:4px; }
table { border-collapse:collapse; width:100%; font-size:var(--t-body); }
th { text-align:left; font-weight:500; font-size:var(--t-xs); color:var(--muted); padding:6px 8px 6px 0; border-bottom:1px solid var(--line); }
td { padding:7px 8px 7px 0; border-bottom:1px solid var(--line-soft); vertical-align:middle; }
tbody th { font-weight:400; color:var(--ink); font-size:var(--t-body); padding:7px 8px 7px 0; border-bottom:1px solid var(--line-soft); }
th.n, td.n { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
td.bar { width:38%; }
.track { height:10px; background:var(--line-soft); border-radius:5px; overflow:hidden; }
.track i { display:block; height:100%; background:var(--blue-ink); border-radius:5px; }
.small { color:var(--muted); }
.cols { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:0 40px; }
.flag { display:flex; gap:8px; align-items:flex-start; padding:10px 12px; border-radius:var(--radius-s); border:1px solid var(--warn-line); background:var(--warn-bg); color:var(--warn-ink); font-weight:600; }
.ok { display:flex; gap:8px; align-items:flex-start; padding:10px 12px; border-radius:var(--radius-s); background:var(--panel); }
.flag svg, .ok svg { flex:none; width:18px; height:18px; margin-top:1px; }
details.vd { margin:10px 0 0; }
details.vd > summary { cursor:pointer; color:var(--blue-ink); font-size:var(--t-cap); }
details.vd > summary:focus-visible, a:focus-visible { outline:2px solid var(--blue-ink); outline-offset:2px; }
.cap { color:var(--muted); font-size:var(--t-cap); margin:6px 0 0; }
footer { padding:28px 0 64px; color:var(--muted); font-size:var(--t-cap); }
.empty { padding:40px 0; font-size:var(--t-sub); }
@media (max-width:760px) {
  .hero { grid-template-columns:minmax(0,1fr); padding-top:20px; }
  .hero .fig { font-size:40px; }
  .strip { grid-template-columns:minmax(0,1fr); }
  .strip > div, .strip > div + div { padding:12px 0; border-left:0; border-top:1px solid var(--line-soft); }
  .strip > div:first-child { border-top:0; }
  .cols { grid-template-columns:minmax(0,1fr); }
  td.bar { width:24%; }
  .days { gap:2px; }
}
"""

ICON_WARN = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/></svg>'
ICON_OK = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" d="M9 16.2 4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4z"/></svg>'


def e(x) -> str:
    return html.escape(str(x), quote=True)


def num(v, unit: str = "") -> str:
    """A figure for the page: the guard text when the group is small."""
    if v == SMALL:
        return e(SMALL)
    return "–" if v is None else e(f"{v:,}{unit}" if isinstance(v, int) else f"{v}{unit}")


def il_stamp(as_of: dt.datetime | None) -> str:
    if not as_of:
        return ""
    t = as_of.astimezone(IL) if as_of.tzinfo else as_of
    return t.strftime("%Y-%m-%d %H:%M") + " Israel time"


def bar_rows(rows: list[tuple], head: str, value_head: str, users_head: str | None = "People") -> str:
    """A table with an inline bar per row. rows: (name, value, users, bar_value or None, bar_max). A guarded row prints '<5 users' and draws no bar. users_head None: no People column."""
    body = []
    for name, val, users, bar, mx in rows:
        draw = is_num(bar) and mx and users != SMALL
        track = f'<div class="track"><i style="width:{max(1.5, 100 * bar / mx):.1f}%"></i></div>' if draw else ""
        body.append(f'<tr><th scope="row">{e(name)}</th><td class="bar" aria-hidden="true">{track}</td><td class="n">{num(val)}</td>' + (f'<td class="n">{num(users)}</td>' if users_head else "") + "</tr>")
    return (f'<table><thead><tr><th scope="col">{e(head)}</th><th scope="col" aria-hidden="true"></th><th scope="col" class="n">{e(value_head)}</th>' + (f'<th scope="col" class="n">{e(users_head)}</th>' if users_head else "")
            + f'</tr></thead><tbody>{"".join(body)}</tbody></table>')


def delta_text(cur, prev) -> str:
    if cur == SMALL or prev == SMALL or cur is None or prev is None:
        return ""
    d = cur - prev
    return f"{abs(d)} more than the 7 days before ({prev})" if d > 0 else f"{abs(d)} fewer than the 7 days before ({prev})" if d < 0 else f"the same as the 7 days before ({prev})"


def html_report(a: dict, standalone: bool = False) -> str:
    stamp = il_stamp(a["as_of"]) or str(a["today"])
    out: list[str] = []
    add = out.append
    add('<title>Delivery Pulse Usage</title>\n<meta name="claude:viewport-fit-sides" content="cover">\n<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600&display=swap">')
    add(f"<style>{CSS}</style>")
    add('<header class="top gutter"><h1>Delivery Pulse Usage</h1><span class="stamp" id="asof">Data as of ' + e(stamp) + "</span></header>")
    add('<main class="gutter">')
    if a["demo"]:
        add('<p class="demo" id="demo-banner" role="note">Demo data: this page shows fictitious people and numbers so the layout can be reviewed. It says nothing about real use.</p>')
    add("<p class=\"lede\">Who opens Delivery Pulse, how often they come back, and what they read. Counts are people, never names.</p>")
    if not a["n_sessions"]:
        add('<p class="empty" id="empty">No usage data yet. Once people open the published page and use it, their visits appear here after the next export.</p>')
    else:
        if a["history_days"] < SHORT_HISTORY_DAYS:
            add(f'<p class="note" id="caveat">Only {a["history_days"]} days of data so far: trends are not meaningful yet.</p>')
        act, prv, ret, tw, mi = a["active7"], a["prev7"], a["returning"], a["this_week"], a["minutes"]
        # --- hero: the headline number with its comparison, and the weekly trend
        pts = [(i, w["users"]) for i, w in enumerate(a["per_week"]) if is_num(w["users"]) and not w["partial"]]      # the week in progress is not drawn: it would look like a drop
        mx = max([v for _, v in pts] + [1])
        spark = ""
        if len(pts) >= 2:
            xy = [(100 * i / 11, 36 - 34 * v / mx) for i, v in pts]
            path = " ".join(("M" if k == 0 else "L") + f"{x:.2f},{y:.2f}" for k, (x, y) in enumerate(xy))
            spark = (f'<svg class="spark" viewBox="0 0 100 38" preserveAspectRatio="none" role="img" aria-labelledby="trend-t"><title id="trend-t">Distinct users per completed ISO week: '
                     + "; ".join(f"{a['per_week'][i]['week']}: {v}" for i, v in pts) + f'</title><path class="ln" d="{path}"/></svg>'
                     f'<div class="sparkcap" aria-hidden="true"><span>{e(a["per_week"][pts[0][0]]["week"])}</span><span>{e(a["per_week"][pts[-1][0]]["week"])}</span></div><p class="cap">People per completed week; the busiest week had {mx}.</p>')
        else:
            spark = '<p class="cap">The weekly trend needs at least two weeks with 5 or more people.</p>'
        ctx = f"of {num(a['users_total']['n'])} people seen in the data. " + (delta_text(act["n"], prv["n"]) + "." if delta_text(act["n"], prv["n"]) else "")
        add(f'<section class="hero" aria-labelledby="h-hero"><div><h2 id="h-hero" class="what" style="font-weight:500">Active users in the last 7 days</h2><p class="fig">{num(act["n"])}</p>'
            f'<p class="ctx">{e(ctx.strip())}</p></div><div>{spark}</div></section>')
        # --- supporting strip
        add('<div class="strip">'
            f'<div><p class="v">{num(ret["pct"], "%") if ret["pct"] != SMALL else e(SMALL)}</p><p class="l">come back on a second day</p><p class="c">{num(ret["n"])} of {num(ret["of"])} people came on 2 or more days (last {a["history_days"]} days)</p></div>'
            f'<div><p class="v">{num(tw["per_user"])}</p><p class="l">visits per active user in the last 7 days</p><p class="c">{num(tw["sessions"])} visits by {num(tw["users"])} users</p></div>'
            f'<div><p class="v">{num(mi["median"])} min</p><p class="l">median visit length, 90th percentile {num(mi["p90"])} min</p><p class="c">{num(mi["sessions"])} visits with some active time, {num(mi["users"])} users. Only time the page is open, in front and in use counts.</p></div></div>')
        # --- daily active users
        days = a["per_day"]
        mxd = max([d["users"] for d in days if is_num(d["users"])] + [1])
        cols = []
        for d in days:
            if is_num(d["users"]) and d["users"] > 0:
                cols.append(f'<div class="d" style="height:{max(2.0, 100 * d["users"] / mxd):.1f}%"></div>')
            else:
                cols.append('<div class="gap"></div>')
        summary = ", ".join(f"{d['day'].strftime('%d %b')}: {d['users'] if d['has_data'] else 'before the data starts'}" for d in days)
        add(f'<section class="blk" aria-labelledby="h-daily"><h2 id="h-daily">People per day, last 28 days</h2><p class="why">Distinct people with a visit that day. Days with fewer than 5 people have no bar. The page is mostly used Sunday to Thursday.</p>'
            f'<div class="days" role="img" aria-label="Distinct users per day, last 28 days. {e(summary)}">{"".join(cols)}</div>'
            f'<div class="dayaxis" aria-hidden="true"><span>{days[0]["day"].strftime("%d %b")}</span><span>most in one day: {mxd}</span><span>{days[-1]["day"].strftime("%d %b")}</span></div>'
            '<details class="vd"><summary>Show data</summary><table><thead><tr><th scope="col">Day</th><th scope="col" class="n">People</th></tr></thead><tbody>'
            + "".join(f'<tr><td>{d["day"].isoformat()}</td><td class="n">{num(d["users"]) if d["has_data"] else "before the data starts"}</td></tr>' for d in reversed(days)) + "</tbody></table></details>"
            "<details class=\"vd\"><summary>Show weekly data</summary><table><thead><tr><th scope=\"col\">ISO week</th><th scope=\"col\" class=\"n\">People</th><th scope=\"col\" class=\"n\">Visits</th></tr></thead><tbody>"
            + "".join(f'<tr><td>{e(w["week"])}{" (in progress)" if w["partial"] else ""}</td><td class="n">{num(w["users"]) if w["has_data"] else "before the data starts"}</td><td class="n">{num(w["sessions"] if (w["has_data"] and is_num(w["users"])) else (SMALL if w["has_data"] else None))}</td></tr>' for w in reversed(a["per_week"]))
            + "</tbody></table></details></section>")
        # --- what people read
        st = a["section_time"]
        add('<section class="blk" aria-labelledby="h-read"><h2 id="h-read">What people read</h2><p class="why">Share of all reading time per section, where reading time is the seconds the page was in front, focused and in use. Sections read by fewer than 5 people show "&lt;5 users".</p>'
            + _share_table(st) + "</section>")
        # --- what people use
        c = a["controls"]
        order = sorted(c.items(), key=lambda kv: (-(kv[1]["n"] if is_num(kv[1]["n"]) else -1), kv[0]))
        mxc = max([v["n"] for _, v in order if is_num(v["n"])] + [1])
        f = a["filters_used"]
        add('<section class="blk" aria-labelledby="h-use"><h2 id="h-use">What people use</h2>'
            f'<p class="why">Filters used by {num(f["pct"], "%")} of active users: {num(f["users"])} of {num(f["of"])} people who visited in the last 7 days changed at least one filter or view control.</p>'
            + bar_rows([(CONTROLS[k], v["n"], v["users"], v["n"] if is_num(v["n"]) else None, mxc) for k, v in order], "Control", "Changes")
            + f'<p class="cap">Refresh: {num(a["refresh"]["n"])} presses by {num(a["refresh"]["users"])} users. Reset Filters: {num(a["reset"]["n"])} presses by {num(a["reset"]["users"])} users.</p></section>')
        # --- links and disclosures side by side
        lk = sorted(a["links"].items(), key=lambda kv: (-(kv[1]["n"] if is_num(kv[1]["n"]) else -1), kv[0]))
        mxl = max([v["n"] for _, v in lk if is_num(v["n"])] + [1])
        dl = discl_sorted(a)
        mxo = max([v["n"] for _, v in dl if is_num(v["n"])] + [1])
        add('<div class="cols"><section class="blk" aria-labelledby="h-links"><h2 id="h-links">Jira links followed</h2><p class="why">Clicks on links that open Jira, by the section they sit in.</p>'
            + bar_rows([(LINK_SECTIONS[k], v["n"], v["users"], v["n"] if is_num(v["n"]) else None, mxl) for k, v in lk], "Section", "Clicks") + '</section>'
            '<section class="blk" aria-labelledby="h-open"><h2 id="h-open">Details opened</h2><p class="why">How often people open the explanations and the data behind a chart.</p>'
            + bar_rows([(DISCLOSURES[k], v["n"], v["users"], v["n"] if is_num(v["n"]) else None, mxo) for k, v in dl], "Disclosure", "Opens") + "</section></div>")
        # --- reach and health
        dv = a["devices"]
        mxv = max([d["raw_users"] for d in dv if is_num(d["users"])] + [1])
        bl = a["builds"]
        mxb = max([b["raw_users"] for b in bl if is_num(b["users"])] + [1])
        add('<div class="cols"><section class="blk" aria-labelledby="h-dev"><h2 id="h-dev">Screen size</h2><p class="why">People who opened the page at each width. A person who used two sizes appears in both rows.</p>'
            + bar_rows([(d["name"], d["users"], d["users"], d["raw_users"] if is_num(d["users"]) else None, mxv) for d in dv], "Width", "People", None)
            + '</section><section class="blk" aria-labelledby="h-build"><h2 id="h-build">Page version</h2><p class="why">Which published version each person last used.</p>'
            + bar_rows([(b["build"] + (" (newest seen)" if b["newest"] else ""), b["users"], b["users"], b["raw_users"] if is_num(b["users"]) else None, mxb) for b in bl], "Version", "People", None) + "</section></div>")
        er = a["errors"]
        if er["any"]:
            who = "fewer than 5 users affected" if er["users"] == SMALL else f'{er["total"]} errors, {er["users"]} users affected'
            msg = f"Needs attention: page errors were recorded ({who}). Open the page in a browser with its developer console to find the cause."
            add(f'<section class="blk" aria-labelledby="h-err"><h2 id="h-err">Page errors</h2><div class="flag" id="errflag" role="status">{ICON_WARN}<span>{msg}</span></div></section>')
        else:
            add(f'<section class="blk" aria-labelledby="h-err"><h2 id="h-err">Page errors</h2><div class="ok" id="errflag">{ICON_OK}<span>No page errors recorded.</span></div></section>')
    add('<section class="blk" aria-labelledby="h-how"><h2 id="h-how">How this is measured</h2><details class="vd" id="how"><summary>What is counted and what is not</summary>'
        '<p class="cap">The published Delivery Pulse page counts, for each person who has an id, which sections they read, which filters and buttons they use, which Jira links they follow (by section only), how long the page is open in front of them and in use, their screen size, the page version and page errors. '
        'It records no names, e-mail addresses, issue keys, project, team or pod names or search text. People who are signed out, who hold view-only access, who open an offline copy, or whose browser blocks the page&#39;s storage are not counted, so these are counts of people with an id, not of all visitors. '
        f'A visit that only reads is recorded after 30 seconds. Each person&#39;s record keeps 12 weeks. Any figure that rests on fewer than {MIN_USERS} people shows "&lt;5 users", and its bar is not drawn. '
        'Visit length uses visits with some active time; the 90th percentile is interpolated between the two nearest visits. Weeks before the first record show "before the data starts", not zero. This page is a snapshot of an export, not a live view.</p></details></section>')
    add("</main>")
    add('<footer class="gutter">Delivery Pulse Usage. Counts only: this page never contains a user id.</footer>')
    frag = "\n".join(out)
    if standalone:
        return '<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1"></head><body>' + frag + "</body></html>"
    return frag


def _share_table(st: list[dict]) -> str:
    top = max([s["raw_share"] for s in st if is_num(s["share"])] + [1])
    body = []
    for s in st:
        draw = is_num(s["share"])
        bar = f'<div class="track"><i style="width:{max(1.5, 100 * s["raw_share"] / top):.1f}%"></i></div>' if draw else ""
        body.append(f'<tr><th scope="row">{e(s["name"])}</th><td class="bar" aria-hidden="true">{bar}</td>'
                    f'<td class="n">{num(s["share"], "%")}</td><td class="n">{num(s["users"])}</td></tr>')
    return ('<table><thead><tr><th scope="col">Section</th><th scope="col" aria-hidden="true"></th><th scope="col" class="n">Share of reading time</th><th scope="col" class="n">People</th></tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table>')


# ------------------------------------------------------------------------------------------------------------ command line
def parse_as_of(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=IL)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("file", nargs="?", help="the exported documents (JSON)")
    ap.add_argument("--html", help="write the dashboard page (an Artifact fragment) to this file")
    ap.add_argument("--standalone", action="store_true", help="wrap the page in a full document so it opens in a browser as a file")
    ap.add_argument("--as-of", help="when the data was exported, ISO (for the 'Data as of' stamp and to decide today)")
    ap.add_argument("--today", help="YYYY-MM-DD, the Israel day the report is about (default: the day of --as-of, else the last day in the data)")
    ap.add_argument("--demo", action="store_true", help="use a fictitious data set (about 40 people, 12 weeks) and show a Demo data banner")
    ap.add_argument("--text", action="store_true", help="also print the text report when --html is given")
    a = ap.parse_args(argv)
    as_of = parse_as_of(a.as_of)
    today = dt.date.fromisoformat(a.today) if a.today else None
    if a.demo:
        today = today or (as_of.astimezone(IL).date() if as_of else dt.datetime.now(IL).date())
        bodies = demo_bodies(today)
        as_of = as_of or dt.datetime.now(IL)
    else:
        if not a.file:
            ap.error("give the exported JSON file, or --demo")
        bodies = load_bodies(json.loads(Path(a.file).read_text(encoding="utf-8")))
    agg = aggregate(bodies, today, as_of, demo=a.demo)
    if a.html:
        Path(a.html).write_text(html_report(agg, standalone=a.standalone), encoding="utf-8")
        print(f"wrote {a.html} ({agg['n_docs']} user records, {agg['n_sessions']} sessions)")
    if not a.html or a.text:
        sys.stdout.write(text_report(agg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
