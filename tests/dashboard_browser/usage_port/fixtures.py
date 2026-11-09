"""The oracle data for the browser port of usage_report.py: fictitious exports and what the Python report makes of each.

For every scenario `build()` returns {name: {"opts", "bodies", "expected"}} where `expected` is what the port must reproduce exactly:
  model   a dump of the Model (see model_dump)
  a       aggregate(...) without the model object, as plain JSON (dates as 'YYYY-MM-DD', sets as sorted lists, tuples as lists)
  blocks  the HTML (or text) of each page block and helper: _kpis, _trend, _breakdowns, _heatmap_block, _back_block, _health_block, _measure_block, _period, ribbon_text, export_warnings, il_stamp
  html    html_report(a), the whole page fragment
Everything is fictitious (usage_report.demo_bodies and small variations of it): no real record is read.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent.parent / "program_dashboard"))
import usage_report as UR  # noqa: E402

IL = UR.IL
REF = dt.date(2026, 10, 29)                                                          # a Thursday
NOW = dt.datetime(2026, 10, 29, 17, 0, tzinfo=IL)

CALENDAR = {"releases": [{"release": "27.1", "w1": "2026-09-27", "w6_end": "2026-11-07", "end": "2026-12-20"}, {"release": "26.4", "w1": "2026-08-02", "w6_end": "2026-09-12", "end": "2026-09-24"}],
            "sprints": [{"no": 41, "start": "2026-10-04", "end": "2026-10-17"}, {"no": 42, "start": "2026-10-18", "end": "2026-10-31"}, {"no": 43, "start": "2026-11-01", "end": "2026-11-14"}],
            "events": [{"date": "2026-10-14", "label": "never printed"}, {"date": "2026-10-21"}, "2026-10-28"], "quiet_weeks": ["2026-09-15"]}


def jsonable(x):
    if isinstance(x, (dt.datetime,)):
        return x.isoformat()
    if isinstance(x, dt.date):
        return x.isoformat()
    if isinstance(x, UR.Model):
        return None
    if isinstance(x, dict):
        return {str(k): jsonable(v) for k, v in x.items()}
    if isinstance(x, (set, frozenset)):
        return sorted((jsonable(v) for v in x), key=lambda v: (str(type(v)), v))
    if isinstance(x, (list, tuple)):
        return [jsonable(v) for v in x]
    if isinstance(x, float) and (x != x or x in (float("inf"), float("-inf"))):
        return None
    return x


def model_dump(m) -> dict:
    """What the JS Model must equal (tests: stage `model`). Dates are 'YYYY-MM-DD'; sets are sorted lists."""
    weeks_all = sorted(m.by_week)
    return jsonable({
        "ref": m.ref, "since": m.since, "cur": m.cur, "last": m.last, "cutoff": m.cutoff, "quiet": sorted(m.quiet), "counts": m.counts, "rows": len(m.rows), "people": list(m.people),
        "first_seen": {str(u): d for u, d in m.first_seen.items()}, "first_real": {str(u): d for u, d in m.first_real.items()}, "pre_golive": sorted(m.pre_golive),
        "first_day": m.first_day, "last_day": m.last_day, "data_start": m.data_start, "first_week": m.first_week, "provisional_first": m.provisional_first, "weeks": list(m.weeks),
        "n_bodies": m.n_bodies, "stale_records": m.stale_records, "pruned_records": m.pruned_records, "rollover": m.rollover, "n_full_weeks": m.n_full_weeks(),
        "by_week": {str(w): {"rows": len(m.by_week[w]), "active": sorted(m.active(w)), "new": sorted(m.new(w)), "established": sorted(m.established(w)),
                             "engaged": sum(1 for r in m.visits(w) if m.engaged(r)), "regime": m.regime(w), "usable": m.usable(w), "prov": m.is_prov(w),
                             "baseline": m.baseline(w), "secs": {str(u): {k: v for k, v in d.items()} for u, d in sorted(m.secs(w).items())},
                             "ctl": {k: sorted(us) for k, us in sorted(m.ctl(w).items())}} for w in weeks_all},
    })


def _thresholds(base: dict | None) -> dict:
    th = dict(UR.THRESHOLDS)
    th.update(base or {})
    return th


def _young(bodies: list, ref: dt.date, days: int) -> list:
    """The export of a page that went live `days` days ago: only the sessions of the last days."""
    cut = ref - dt.timedelta(days=days - 1)
    out = []
    for b in copy.deepcopy(bodies):
        w = {}
        for wk, ds in b["w"].items():
            kept = {d: s for d, s in ds.items() if dt.date.fromisoformat(d) >= cut}
            if kept:
                w[wk] = kept
        if w:
            b["w"] = w
            b["first"] = max(b["first"], cut.isoformat())
            out.append(b)
    return out


def wtd_bodies(people: list) -> list:
    """Fictitious records built by hand for the week-so-far block: people = [[(day, session), ...], ...]. A session with a v2 marker is a v2 session (week key 'S<Sunday>'), one without is a v1 session (ISO week key)."""
    out = []
    for i, visits in enumerate(people):
        w: dict = {}
        for n, (day, sess) in enumerate(visits):
            key = UR.sunday_key(day) if UR.is_v2(sess) else UR.iso_week_key(day)
            w.setdefault(key, {}).setdefault(day.isoformat(), {})[f"s{i:03d}x{n:02d}"[:8]] = sess
        days = [x for x, _ in visits]
        out.append({"u": f"u_synthetic_{i + 1:03d}", "v": 2 if any(UR.is_v2(x) for _, x in visits) else 1, "first": min(days).isoformat(), "last": max(days).isoformat(), "w": w})
    return out


def _wtd_people(more: int = 0) -> list:
    """Wednesday 11 Nov 2026 as the data day. Sunday 1 to Wednesday 4 Nov: 6 people with a v1 session (one of them twice; a seventh person on Thursday 5 is not the same days). Sunday 8 to Wednesday 11: 3 people with a v2 session,
    one of them a glance visit and one twice (`more` adds people with a v2 session on Tuesday 10). One person has an old v1 session from 20 Oct, so the data starts well before the previous window."""
    nov = lambda n: dt.date(2026, 11, n)
    v1 = lambda: {"s": 60, "d": "l"}
    v2 = lambda s=60, **kw: {"s": s, "vs": max(s, 10), "lv": 0, "fa": 0, "d": "m", **kw}
    people = [[(nov(1), v1()), (nov(4), v1())] + ([(nov(8), v2()), (nov(10), v2())] if i == 0 else [(nov(9), v2(2, g=1))] if i == 1 else [(nov(11), v2())] if i == 2 else [(nov(10), v2())] if i < 3 + more else []) for i in range(6)]
    people.append([(nov(5), v1())])
    people.append([(dt.date(2026, 10, 20), v1())])
    return people


def scenarios() -> dict:
    sa = dict(UR.SHOW_ALL)
    d = UR.demo_bodies
    sunday = dt.date(2026, 10, 25)
    sat, wed, sun2 = dt.date(2026, 10, 31), dt.date(2026, 11, 4), dt.date(2026, 11, 8)
    at = lambda day, h=10: dict(today=day, as_of=dt.datetime(day.year, day.month, day.day, h, 0, tzinfo=IL), now=dt.datetime(day.year, day.month, day.day, h, 30, tzinfo=IL))
    return {
        "demo_showall": dict(bodies=d(REF), today=REF, th=_thresholds(sa), demo=True),
        "demo_default": dict(bodies=d(REF), today=REF, th=_thresholds(None), demo=True),
        "demo_audience_since": dict(bodies=d(REF), today=REF, th=_thresholds(None), audience=120, since=dt.date(2026, 9, 6)),
        "demo_calendar": dict(bodies=d(REF), today=REF, th=_thresholds(sa), calendar=CALENDAR),
        "demo_calendar_default": dict(bodies=d(REF), today=REF, th=_thresholds(None), calendar=CALENDAR, demo=True),
        "empty": dict(bodies=[], today=REF, th=_thresholds(sa)),
        "v1_only": dict(bodies=d(REF, v2_from=99), today=REF, th=_thresholds(None), demo=True),
        "v1_only_showall": dict(bodies=d(REF, v2_from=99), today=REF, th=_thresholds(sa)),
        "young_5_days": dict(bodies=_young(d(REF), REF, 5), today=REF, th=_thresholds(sa)),
        "young_20_days_default": dict(bodies=_young(d(REF), REF, 20), today=REF, th=_thresholds(None)),
        "seed7_showall": dict(bodies=d(REF, seed=7), today=REF, th=_thresholds(sa)),
        "seed3_default_stale_export": dict(bodies=d(REF, seed=3), today=REF + dt.timedelta(days=4), th=_thresholds(None), as_of=NOW),
        "sunday_ref": dict(bodies=d(sunday), today=sunday, th=_thresholds(sa), as_of=dt.datetime(2026, 10, 25, 9, 0, tzinfo=IL), now=dt.datetime(2026, 10, 25, 9, 30, tzinfo=IL)),
        "mid_v2_rollover": dict(bodies=d(REF, v2_from=6), today=REF, th=_thresholds(None)),
        "wtd_saturday_showall": dict(bodies=d(sat), th=_thresholds(sa), **at(sat, 20)),
        "wtd_partial_wednesday_showall": dict(bodies=_young(d(wed), wed, 9), th=_thresholds(sa), **at(wed)),
        "wtd_hand_default": dict(bodies=wtd_bodies(_wtd_people()), th=_thresholds(None), **at(dt.date(2026, 11, 11))),
        "wtd_hand_default_five": dict(bodies=wtd_bodies(_wtd_people(2)), th=_thresholds(None), **at(dt.date(2026, 11, 11))),
        "wtd_hand_showall": dict(bodies=wtd_bodies(_wtd_people()), th=_thresholds(sa), **at(dt.date(2026, 11, 11))),
        "wtd_hand_sunday_showall": dict(bodies=wtd_bodies(_wtd_people()), th=_thresholds(sa), **at(sun2)),
        "wtd_hand_no_current_showall": dict(bodies=wtd_bodies([[(dt.date(2026, 11, 2), {"s": 60}), (dt.date(2026, 11, 7), {"s": 60})], [(dt.date(2026, 11, 3), {"s": 30})]]), th=_thresholds(sa), **at(sun2)),
    }


def opts_of(s: dict) -> dict:
    now = s.get("now", NOW)
    as_of = s.get("as_of", NOW)
    return {"ref": as_of.astimezone(IL).date().isoformat(), "today": s["today"].isoformat(), "as_of": (s.get("as_of", NOW)).isoformat(), "now": now.isoformat(), "demo": bool(s.get("demo", False)),
            "since": s["since"].isoformat() if s.get("since") else None, "audience": s.get("audience"), "calendar": s.get("calendar"), "th": s["th"],
            "stats": {"read": len(s["bodies"]), "skipped": 0, "duplicates": 0, "unknown_schema": 0, "no_id": 0, "round_page": False}}


def expected_of(s: dict) -> dict:
    o = opts_of(s)
    cal = UR.parse_calendar(s["calendar"]) if s.get("calendar") else None
    a = UR.aggregate(s["bodies"], today=s["today"], as_of=dt.datetime.fromisoformat(o["as_of"]), now=dt.datetime.fromisoformat(o["now"]), demo=o["demo"], since=s.get("since"),
                     audience=s.get("audience"), calendar=cal, th=s["th"], stats=o["stats"])
    UR.set_min_group(s["th"].get("min_group", 5))
    blocks = {"_measure_block": UR._measure_block(a), "_period": UR._period(a), "ribbon_text": UR.ribbon_text(a), "export_warnings": UR.export_warnings(a),
              "il_stamp": UR.il_stamp(dt.datetime.fromisoformat(o["as_of"]))}
    if a["n_sessions"]:                                                               # html_report draws these only when there is a session to show
        blocks.update({"_kpis": UR._kpis(a), "_trend": UR._trend(a), "_breakdowns": UR._breakdowns(a), "_heatmap_block": UR._heatmap_block(a), "_back_block": UR._back_block(a),
                       "_health_block": UR._health_block(a)})
    html = UR.html_report(a)
    m = a["model"]
    b = {k: v for k, v in a.items() if k != "model"}
    return {"model": model_dump(m), "a": jsonable(b), "blocks": blocks, "html": html}


_cache: dict = {}


def build(only: str | None = None) -> dict:
    out = {}
    for name, s in scenarios().items():
        if only and only not in name:
            continue
        if name not in _cache:
            _cache[name] = {"opts": opts_of(s), "bodies": s["bodies"], "expected": expected_of(s)}
        out[name] = _cache[name]
    return out


if __name__ == "__main__":
    fx = build()
    for k, v in fx.items():
        print(f"{k:32} bodies={len(v['bodies']):3} html={len(v['expected']['html']):7} people={v['expected']['a'].get('n_people', {})}")
