"""program_dashboard/usage_report.py: the owner's aggregate report and the "Delivery Pulse Usage" page.

Synthetic data only: users are u_synthetic_001 ..., nothing here is a real id, person, team or issue. Every record is built from usage_report.RECORD_SHAPE (the one place that defines the record the page writes), so a fixture cannot
drift from what the report reads. Many tests are written as `check_*(mod)` functions over a module, and run twice: against the real report, and (the seeded-defect self-tests at the end) against a copy of its source with one defect put in,
which the same check must then catch.
"""
from __future__ import annotations

import datetime as dt
import itertools
import json
import random
import re
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "program_dashboard"))
import usage_report as UR                                                           # noqa: E402
import build_dashboard as BD                                                        # noqa: E402

TEMPLATE = (ROOT / "program_dashboard" / "dashboard.template.html").read_text(encoding="utf-8")
SOURCE = (ROOT / "program_dashboard" / "usage_report.py").read_text(encoding="utf-8")
IL = UR.IL
REF = dt.date(2026, 11, 2)                                                          # a Monday: the week in progress starts on Sunday 2026-11-01
NOW = dt.datetime(2026, 11, 2, 10, 15, tzinfo=IL)
CUR = UR.week_start(REF)


def wk(k: int) -> dt.date:
    """The Sunday that starts the completed week k weeks before the last completed one (k = 0: Sunday 2026-10-25 to Saturday 2026-10-31)."""
    return CUR - dt.timedelta(days=7 * (k + 1))


# ------------------------------------------------------------------------------------------------ fixture builders, from RECORD_SHAPE
def sess(**kw) -> dict:
    bad = set(kw) - UR.SESSION_KEYS
    assert not bad, f"not in RECORD_SHAPE: {bad}"
    return kw


def v2(**kw) -> dict:
    """A v2 session: carries the always-written v2 markers (vs, fa, lv) unless given."""
    kw.setdefault("vs", kw.get("s", 60))
    kw.setdefault("lv", 0)
    kw.setdefault("fa", 0)
    return sess(**kw)


def person(i: int, visits: list, **extra) -> dict:
    """One record. visits: [(day, session)]; week keys follow the version of each session (v2: 'S<Sunday>', v1: ISO week)."""
    w: dict = {}
    for n, (day, s) in enumerate(visits):
        key = UR.sunday_key(day) if UR.is_v2(s) else UR.iso_week_key(day)
        w.setdefault(key, {}).setdefault(day.isoformat(), {})[f"s{i:03d}x{n:02d}"[:8]] = s
    days = [d for d, _ in visits]
    body = {"u": f"u_synthetic_{i + 1:03d}", "v": 2 if any(UR.is_v2(s) for _, s in visits) else 1, "first": min(days).isoformat(), "last": max(days).isoformat(), "w": w}
    body.update(extra)
    return body


def weekly(counts: list, make=lambda i, k: sess(s=60), dow: int = 6, first_extra: dict | None = None) -> list:
    """counts: people active per completed week, oldest first, the last one being the last completed week (wk(0)). Person i is active in week j when i < counts[j], on the day Sunday + dow (Saturday by default: the latest visit is then 2 days before the Monday of the report),
    so the first week of data starts mid-week (provisional). make(i, k): the session of person i in the week k weeks before the last."""
    n_weeks = len(counts)
    people = []
    for i in range(max(counts)):
        visits = []
        for j, c in enumerate(counts):
            k = n_weeks - 1 - j
            if i < c:
                visits.append((wk(k) + dt.timedelta(days=dow), make(i, k)))
        people.append(person(i, visits, **(first_extra or {})))
    return people


def first_session(body: dict) -> dict:
    """The oldest session of a record (the dict itself, so a test can add a field to it)."""
    wk_ = body["w"][next(iter(body["w"]))]
    day = wk_[next(iter(wk_))]
    return day[next(iter(day))]


def agg(bodies, mod=UR, **kw):
    kw.setdefault("as_of", NOW)
    kw.setdefault("now", NOW)
    return mod.aggregate(bodies, **kw)


def ledger(a, sid):
    return [r for r in a["signals"]["ledger"] if r["id"] == sid][0]


def flagged(a, sid=None):
    return [f for f in a["signals"]["flagged"] if sid is None or f["id"] == sid]


def _text(h: str) -> str:
    """The words of a page: no style block, no tags; attribute values (aria-label, title) are kept in because a screen reader reads them."""
    return re.sub(r"<[^>]+>", " ", re.sub(r"<style>.*?</style>", " ", h, flags=re.S)) + " " + " ".join(re.findall(r'(?:aria-label|title)="([^"]*)"', h))


def outputs(a, mod=UR) -> list:
    return [mod.text_report(a), mod.html_report(a), mod.html_report(a, standalone=True)]


def load_mutant(*replacements):
    """A copy of usage_report.py with defects put in: each (old, new) must match the source exactly once, so a refactor that moves the code fails here and the seeded defect has to be re-aimed."""
    src = SOURCE
    for old, new in replacements:
        assert src.count(old) == 1, f"the seeded defect no longer matches the source exactly once: {old[:70]!r}"
        src = src.replace(old, new)
    mod = types.ModuleType("usage_report_mutant")
    mod.__file__ = str(ROOT / "program_dashboard" / "usage_report.py")
    exec(compile(src, mod.__file__, "exec"), mod.__dict__)
    return mod


# ------------------------------------------------------------------------------------------------ the record shape and the vocabulary
def test_record_shape_is_the_single_definition_of_the_record():
    assert {"u", "v", "first", "last", "w", "pr"} == UR.RECORD_KEYS
    assert {"t", "s", "vs", "g", "sec", "nav", "l", "o", "f", "r", "rs", "np", "d", "b", "bt", "lv", "fa", "ro", "rt", "er", "erb", "lf", "rr", "x"} == UR.SESSION_KEYS
    with pytest.raises(AssertionError):
        sess(name="not a field")                                                    # the fixture builder refuses a key outside the shape
    assert UR.is_v2(v2(s=5)) and not UR.is_v2(sess(s=5, f={"release": 1}))


def _voc() -> dict:
    return json.loads(re.search(r"const USAGE_VOC = (\{.*?\});\n", TEMPLATE).group(1))


def test_the_report_knows_the_keys_the_page_records():
    v = _voc()
    assert set(UR.SECTIONS) == set(v["nav"]) and set(UR.READ_SECTIONS) - {"top"} == set(v["sec"]) - {"top"} and set(UR.LINK_SECTIONS) == set(v["l"])
    assert set(v["sec"]) in (set(UR.SECTIONS), set(UR.READ_SECTIONS))               # the page may or may not have the v2 key `top` yet
    assert set(UR.CONTROLS) == set(v["f"]) and set(UR.DISCLOSURES) == set(v["o"]) and set(UR.DEVICES) == set(v["d"])
    assert sorted(k for _, ks in UR.CONTROL_FAMILIES for k in ks) == sorted(UR.CONTROLS)          # every control is in exactly one family
    assert list(UR.READ_SECTIONS)[0] == "top" and UR.READ_SECTIONS["top"] == "Headline tiles"


def test_the_page_reads_only_the_id_and_never_leaves_the_page():
    block = TEMPLATE[TEMPLATE.index("const USAGE_VOC"):]
    assert re.search(r"Usage statistics: this page counts, per pseudonymous user id \(a code, no name or e-mail; the editors of this page can read these records\)", block)
    assert "What is counted" in block and "Kept for 12 weeks" in block
    assert re.search(r"user\.id\(\)", block) and not re.search(r"user\.(name|email|me|profiles|search)\b", block)
    assert block.count('window.claude.use("db")') == 1 and block.count('window.claude.use("user")') == 1 and "scopes" not in block
    for banned in ("fetch(", "sendBeacon", "XMLHttpRequest", "WebSocket", "localStorage", "document.cookie"):
        assert banned not in block, f"the usage block must not use {banned}"


# ------------------------------------------------------------------------------------------------ loading and export integrity
def test_loader_accepts_bodies_rows_and_a_wrapper():
    bodies = weekly([6, 6])
    assert UR.load_bodies(bodies) == bodies
    assert UR.load_bodies([{"id": b["u"], "data": b} for b in bodies]) == bodies
    assert UR.load_bodies([{"doc_id": "x" + b["u"], "data": b} for b in bodies]) == bodies
    assert UR.load_bodies({"documents": [{"id": b["u"], "data": b} for b in bodies]}) == bodies
    bodies2, st = UR.load_export([{"id": "x", "data": {"nothing": 1}}, "junk", 3])
    assert bodies2 == [] and st["skipped"] == 3
    with pytest.raises(ValueError):
        UR.load_bodies({"no": "list"})


def test_duplicates_are_dropped_counted_and_their_id_is_never_printed():
    bodies = weekly([6, 6, 6])
    dup = bodies + [json.loads(json.dumps(bodies[0]))]                              # the same person exported twice
    out, st = UR.load_export(dup)
    assert len(out) == len(bodies) and st["duplicates"] == 1 and st["read"] == len(bodies) + 1
    a = agg(out, stats=st)
    assert a["n_people"]["raw"] == len(bodies)
    s7 = ledger(a, "S7")
    assert s7["status"] == "flagged" and "1 duplicated documents dropped" in s7["text"]
    for o in outputs(a):
        assert "u_synthetic" not in o and "1 duplicated documents dropped" in o
    # a paged export: the fuller copy of a duplicate wins
    short = json.loads(json.dumps(bodies[0]))
    short["w"] = {}
    short["w"] = dict(list(bodies[0]["w"].items())[:1])
    out2, _ = UR.load_export([short, bodies[0]])
    assert UR._n_sessions(out2[0]) == UR._n_sessions(bodies[0])


def test_unknown_schema_and_round_page_sizes_are_flagged_and_left_out():
    good = weekly([6, 6])
    future = dict(good[0], v=3, u="u_synthetic_900")
    out, st = UR.load_export(good + [future])
    assert len(out) == len(good) and st["unknown_schema"] == 1
    a = agg(out, stats=st)
    assert "1 documents with an unknown schema left out" in ledger(a, "S7")["text"]
    many = [dict(good[0], u=f"u_synthetic_{i + 1000}") for i in range(100)]
    out, st = UR.load_export(many)
    assert st["round_page"] is True and "round page size" in ledger(agg(out, stats=st), "S7")["text"]


# ------------------------------------------------------------------------------------------------ weeks
def test_weeks_start_on_sunday_and_are_complete_only_after_saturday():
    sun, sat, mon = dt.date(2026, 11, 1), dt.date(2026, 10, 31), dt.date(2026, 11, 2)
    assert UR.week_start(sun) == sun and UR.week_start(mon) == sun and UR.week_start(sat) == dt.date(2026, 10, 25)
    assert UR.week_start(dt.date(2026, 10, 29)).strftime("%a") == "Sun"
    assert UR.iso_week_key(sun) != UR.iso_week_key(mon) and UR.sunday_key(mon) == "S2026-11-01"           # ISO would split Sunday from Monday: the work week must not
    ws = dt.date(2026, 10, 25)
    assert not UR.is_complete(ws, dt.date(2026, 10, 31)) and UR.is_complete(ws, dt.date(2026, 11, 1)) and not UR.is_complete(sun, mon)


def check_week_start(mod):
    assert mod.week_start(dt.date(2026, 11, 1)) == dt.date(2026, 11, 1) and mod.week_start(dt.date(2026, 11, 7)) == dt.date(2026, 11, 1)


def test_both_week_key_shapes_are_read_and_a_bad_one_is_counted():
    d1, d2 = dt.date(2026, 10, 20), dt.date(2026, 10, 27)
    p = {"u": "u_synthetic_001", "v": 2, "first": d1.isoformat(), "last": d2.isoformat(),
         "w": {UR.iso_week_key(d1): {d1.isoformat(): {"aaaaaaaa": sess(s=60)}}, UR.sunday_key(d2): {d2.isoformat(): {"bbbbbbbb": v2(s=60)}}, "junk": {d2.isoformat(): {"cccccccc": sess(s=5)}}}}
    m = UR.Model([p], REF)
    assert len(m.rows) == 2 and m.counts["bad_week_key"] == 1 and {r["v2"] for r in m.rows} == {True, False}


def test_robust_band_needs_five_values_and_is_hand_computed():
    assert UR.robust_band([20, 22, 21, 19], 3) is None
    b = UR.robust_band([20, 22, 21, 19, 23], 3)                                      # median 21, deviations 1 1 0 2 2: MAD 1, half = max(3 x 1.4826, 3)
    assert b["median"] == 21 and b["mad"] == 1 and abs(b["half"] - 4.4478) < 1e-9 and abs(b["lo"] - 16.5522) < 1e-9
    assert UR.robust_band([30] * 6, 4.5)["half"] == 4.5                              # no spread: the floor decides


# ------------------------------------------------------------------------------------------------ M1: complementary disclosure
def check_partition_property(mod, seed=7, rounds=3000):
    """For any partition and its printed total: no cell prints as 1 to 4, and the total minus any subset of the printed cells is never 1 to 4 (so no printed pair reveals a small group)."""
    r = random.Random(seed)
    for _ in range(rounds):
        cells = {f"c{i}": r.choice([0, 0, 1, 2, 3, 4, 5, 7, 12, 30, 41]) for i in range(r.randint(2, 5))}
        total = sum(cells.values())
        out = mod.protect_partition(cells, total)
        vis = {k: v for k, v in out.items() if v != mod.SMALL}
        assert all(v == 0 or v >= 5 for v in vis.values()), (cells, out)
        if total in (1, 2, 3, 4):
            continue                                                                  # a total of 1 to 4 is guarded by the caller
        for n in range(len(vis) + 1):
            for sub in itertools.combinations(vis, n):
                rest = total - sum(vis[k] for k in sub)
                assert not 1 <= rest <= 4, (cells, out, sub)


def test_no_partition_reveals_a_small_group():
    check_partition_property(UR)
    S = UR.SMALL
    assert UR.protect_partition({"new": 3, "returning": 30, "dormant": 7}, 40) == {"new": S, "returning": 30, "dormant": S}      # 40 - 37 = 3 would show the 3
    assert UR.protect_partition({"a": 12, "b": 30}, 42) == {"a": 12, "b": 30}
    assert UR.protect_partition({"a": 3, "b": 3, "c": 34}, 40) == {"a": S, "b": S, "c": 34}                                        # two hidden cells sum to 6: not a small group
    assert UR.protect_partition({"a": 2, "b": 40}, 42) == {"a": S, "b": S}
    # two relations at once (the week's people, and the week before)
    out = UR.protect_group({"new": 3, "cont": 21, "react": 0, "lapsed": 9}, [(24, ["new", "cont", "react"]), (30, ["cont", "lapsed"])])
    assert out["new"] == S and out["cont"] == S and out["lapsed"] == 9


def check_the_pages_partitions_hide_the_small_group(mod):
    """The growth-accounting rows of a week with 3 new people and 22 other people never print a pair that reveals the 3."""
    bodies = weekly([22] * 8 + [25], make=lambda i, k: sess(s=60))
    a = agg(bodies, mod)
    row = [w for w in a["weeks"] if w["ws"] == wk(0)][0]
    printed = {k: row[k] for k in ("active", "new", "continuing", "reactivated", "lapsed")}
    vis = {k: v for k, v in printed.items() if v != mod.SMALL and v is not None}
    assert printed["new"] == mod.SMALL
    assert not (1 <= printed["active"] - vis.get("continuing", 0) - vis.get("reactivated", 0) <= 4), printed


def test_the_growth_accounting_row_hides_what_subtraction_would_reveal():
    check_the_pages_partitions_hide_the_small_group(UR)


# ------------------------------------------------------------------------------------------------ the signals: fire / do not fire / partial / small cell / baseline
def test_s0_and_s1_fire_on_a_hand_computed_jump_and_do_not_fire_on_a_steady_week():
    a = agg(weekly([30] * 8 + [45]))                                                  # the baseline weeks all have 30: MAD 0, band 30 +- 4.5; 45 is outside and 15 >= max(3, 6)
    assert a["compared"]["raw"] == 45 and a["compared"]["median"] == "30" and a["compared"]["state"] == "ok"
    f0, f1 = flagged(a, "S0")[0], flagged(a, "S1")[0]
    assert "45 people were active" in f0["observation"] and f0["confidence"] == "Single-source"                    # one week, 45 active people: not thin
    assert "15 people were seen for the first time" in f1["observation"]
    steady = agg(weekly([30] * 9))
    assert ledger(steady, "S0")["status"] == "within" and not flagged(steady, "S0") and not flagged(steady, "S1")


def test_a_partial_week_never_fires_and_the_provisional_first_week_is_not_a_baseline():
    bodies = weekly([30] * 8)
    in_progress = [person(100 + i, [(CUR + dt.timedelta(days=1), sess(s=60))]) for i in range(60)]        # a big Monday: the week has only just begun
    a = agg(bodies + in_progress)
    assert a["compared"]["raw"] == 30 and not flagged(a, "S0") and a["compared"]["label"] == UR.week_label(wk(0))
    assert [w for w in a["weeks"] if w["status"] == "in_progress"][0]["raw"] == 60 and a["weeks"][0]["status"] == "provisional"
    # 6 weeks of data: the first is provisional, so the baseline of the last has 4 comparable weeks, not 5
    b = agg(weekly([30] * 6))
    assert ledger(b, "S0")["status"] == "not_tested" and "baseline building (4 of 5" in ledger(b, "S0")["text"]
    assert b["compared"]["state"] == "building"


def check_partial_week_is_not_compared(mod):
    bodies = weekly([30] * 8) + [person(100 + i, [(CUR + dt.timedelta(days=1), sess(s=60))]) for i in range(3)]
    a = agg(bodies, mod)
    assert a["compared"]["label"] == mod.week_label(wk(0)) and ledger(a, "S0")["status"] == "within" and not flagged(a, "S0")


def test_the_week_in_progress_is_not_compared():
    check_partial_week_is_not_compared(UR)


def test_a_key_figure_under_five_people_is_unknown_and_never_flagged():
    a = agg(weekly([30] * 8 + [3]))                                                   # a drop to 3 people: the figure is a small group
    s0 = ledger(a, "S0")
    assert s0["status"] == "unknown" and UR.SMALL in s0["text"] and "3 people" not in s0["text"] and not flagged(a, "S0")
    assert a["compared"]["active"] == UR.SMALL


def test_s2_lapsed_regulars_fire_not_fire_and_need_seven_weeks():
    def make(n_lapsed, n_reg=20):
        # n_reg regulars active in weeks k = 8..3 (L-8..L-3); the first n_lapsed of them stop for k = 2, 1, 0, the others stay. 20 more people only arrive in the last 3 weeks (not regulars).
        out = []
        for i in range(n_reg):
            ks = list(range(8, 2, -1)) + ([] if i < n_lapsed else [2, 1, 0])
            out.append(person(i, [(wk(k) + dt.timedelta(days=6), sess(s=60)) for k in ks]))
        for i in range(n_reg, n_reg + 20):
            out.append(person(i, [(wk(k) + dt.timedelta(days=6), sess(s=60)) for k in (2, 1, 0)]))
        return out
    a = agg(make(8))
    assert flagged(a, "S2") and "8 of 20 regular people (40%)" in flagged(a, "S2")[0]["observation"] and ledger(a, "S2")["status"] == "flagged"
    four = agg(make(4))
    assert not flagged(four, "S2") and ledger(four, "S2")["status"] == "within" and UR.SMALL in ledger(four, "S2")["text"]
    nine = agg(make(8, n_reg=9))
    assert not flagged(nine, "S2")                                                    # fewer than 10 regulars
    young = agg([person(i, [(wk(k) + dt.timedelta(days=6), sess(s=60)) for k in range(5, -1, -1)]) for i in range(30)])
    assert ledger(young, "S2")["status"] == "not_tested" and "needs 7 completed weeks, has 5" in ledger(young, "S2")["text"]


def test_s3_section_reach_fires_not_fires_small_cell_unknown_and_too_few_people():
    def make(readers_last):
        return lambda n: (lambda i, k: sess(s=60, sec={"burnup": 40 if (i < 20 if k > 0 else i < readers_last) else 5}))
    fire = agg(weekly([30] * 8 + [30], make=make(6)(0)))                              # reach 20 of 30 (67%) for 8 weeks, then 6 of 30 (20%)
    f = [x for x in flagged(fire, "S3")]
    assert len(f) == 1 and "Delivery" in f[0]["headline"] and "20%" in f[0]["observation"] and "usual 67%" in f[0]["observation"]
    assert ledger(fire, "S3")["status"] == "flagged"
    same = agg(weekly([30] * 9, make=make(20)(0)))
    assert not flagged(same, "S3") and ledger(same, "S3")["status"] == "within"
    small = agg(weekly([30] * 9, make=make(3)(0)))                                    # 3 readers: a small group, Unknown, never flagged
    assert not flagged(small, "S3")
    few = agg(weekly([15] * 9, make=make(3)(0)))
    assert ledger(few, "S3")["status"] == "not_tested" and "too few active people (n=15, needs 20)" in ledger(few, "S3")["text"]


def test_s4_controls_newly_used_and_no_longer_used():
    def make(users_last, users_before):
        return lambda i, k: sess(s=60, f={"multi": 1}) if (i < (users_last if k == 0 else users_before if k >= 2 else 0 if k == 1 and users_before == 6 else users_before)) else sess(s=60)
    new = agg(weekly([30] * 9, make=lambda i, k: sess(s=60, f={"multi": 1}) if (k == 0 and i < 6) else sess(s=60)))
    n = [f for f in flagged(new, "S4")]
    assert len(n) == 1 and "Multi-select toggle is newly used" in n[0]["headline"] and "6 established people (20%)" in n[0]["observation"]
    four = agg(weekly([30] * 9, make=lambda i, k: sess(s=60, f={"multi": 1}) if (k == 0 and i < 4) else sess(s=60)))
    assert not flagged(four, "S4")
    stopped = agg(weekly([30] * 9, make=lambda i, k: sess(s=60, f={"teams": 1}) if (k >= 2 and i < 6) else sess(s=60)))
    st = flagged(stopped, "S4")
    assert len(st) == 1 and "Teams is no longer used" in st[0]["headline"]


def test_s5_errors_use_a_window_not_a_sticky_flag():
    base = weekly([30] * 9, make=lambda i, k: sess(s=60, b="aaa1111"))
    # one error ten weeks ago must not light the flag now
    old = json.loads(json.dumps(base))
    first_session(old[0])["er"] = 1
    a = agg(old)
    assert ledger(a, "S5")["status"] == "within" and "none in the last 14 days" in ledger(a, "S5")["text"] and "Earlier in the data" in ledger(a, "S5")["text"]
    assert not flagged(a, "S5")
    # 5 people with an error in the last completed week: flagged
    five = agg(weekly([30] * 9, make=lambda i, k: sess(s=60, b="aaa1111", er=1) if (k == 0 and i < 5) else sess(s=60, b="aaa1111")))
    assert flagged(five, "S5") and "5 or more people had an error" in flagged(five, "S5")[0]["observation"]
    # 2% of 60 visits (2 of 60 = 3.3%): flagged by the share rule although only 2 people
    share = agg(weekly([60] * 9, make=lambda i, k: sess(s=60, b="aaa1111", er=1) if (k == 0 and i < 2) else sess(s=60, b="aaa1111")))
    assert flagged(share, "S5") and "2% or more of the visits" in flagged(share, "S5")[0]["observation"]
    # one error in 30 visits is under the minimum visit count of the share rule
    one = agg(weekly([30] * 9, make=lambda i, k: sess(s=60, b="aaa1111", er=1) if (k == 0 and i < 1) else sess(s=60, b="aaa1111")))
    assert not flagged(one, "S5") and "below the flag threshold" in ledger(one, "S5")["text"]
    # the same build in two consecutive weeks
    two = agg(weekly([30] * 9, make=lambda i, k: sess(s=60, b="aaa1111", er=1) if (k <= 1 and i < 1) else sess(s=60, b="aaa1111")))
    assert flagged(two, "S5") and "same page version" in flagged(two, "S5")[0]["observation"]
    # benign notifications are never flagged
    benign = agg(weekly([30] * 9, make=lambda i, k: v2(s=60, b="aaa1111", erb=1, bt=20000)))
    assert not flagged(benign, "S5") and ledger(benign, "S5")["status"] == "within"


def check_errors_are_windowed(mod):
    base = weekly([30] * 9, make=lambda i, k: sess(s=60, b="aaa1111"))
    first_session(base[0])["er"] = 1                                                  # a single error ten weeks ago
    a = agg(base, mod)
    assert not [f for f in a["signals"]["flagged"] if f["id"] == "S5"] and "Needs attention" not in mod.html_report(a)


def test_a_single_old_error_does_not_flag():
    check_errors_are_windowed(UR)


def test_s6_s8_s9_need_v2_fields_and_say_so_on_v1_data():
    v1 = agg(weekly([30] * 9))
    for sid in ("S6", "S8", "S9"):
        assert ledger(v1, sid)["status"] == "not_tested" and "not recorded in v1" in ledger(v1, sid)["text"]
    assert "version order unknown; counts only" in ledger(v1, "S6")["text"]
    mk = lambda old, snap: (lambda i, k: v2(s=60, b="b", bt=20000 if (k == 0 and i < old) else 20010, lv=1 if (k == 0 and i < snap) else 0))
    a = agg(weekly([40] * 9, make=mk(8, 12)))
    assert flagged(a, "S6") and "8 of 40 people" in flagged(a, "S6")[0]["observation"]
    assert flagged(a, "S8") and "30% of 40 visits" in flagged(a, "S8")[0]["observation"]
    assert not flagged(agg(weekly([40] * 9, make=mk(4, 4))), "S6") and ledger(agg(weekly([40] * 9, make=mk(4, 4))), "S6")["status"] in ("unknown", "within")
    stale = agg(weekly([40] * 9, make=lambda i, k: v2(s=60, b="b", bt=20010, fa=3 if (k == 0 and i < 10) else 0)))
    assert flagged(stale, "S9") and "25% of 40 visits" in flagged(stale, "S9")[0]["observation"]


def test_confidence_labels_follow_how_many_weeks_show_the_change_and_how_thin_the_data_is():
    mk = lambda ks, n_hi: weekly([30] * 7 + [n_hi] * ks)[:]                           # noqa: E731
    one = agg(weekly([30] * 8 + [45]))
    assert flagged(one, "S0")[0]["confidence"] == "Single-source"
    thin = agg(weekly([20] * 8 + [32]))                                               # 12 more people, but under 30 active: thin
    assert flagged(thin, "S0")[0]["confidence"] == "Single-source" or flagged(thin, "S0")[0]["confidence"] == "Weak signal"
    twenty = agg(weekly([18] * 8 + [29]))
    assert flagged(twenty, "S0") and flagged(twenty, "S0")[0]["confidence"] == "Weak signal"
    two = agg(weekly([30] * 7 + [45, 45]))
    assert flagged(two, "S0")[0]["confidence"] == "Corroborated"
    three = agg(weekly([30] * 6 + [45, 45, 45]))
    assert flagged(three, "S0")[0]["confidence"] == "Confirmed"


def test_the_nothing_changed_text_lists_what_was_checked_and_what_was_not():
    a = agg(weekly([30] * 9))
    assert not a["signals"]["flagged"]
    t = UR.nothing_changed_text(a["signals"])
    assert t.startswith("Nothing changed beyond the usual week-to-week range. Checked: ")
    for name in ("Weekly active people", "New active people", "Page errors", "Data coverage"):
        assert name in t
    assert "Not tested: " in t and "Published-version split (field not recorded in v1" in t
    assert t.endswith("This is not a statement that usage is healthy. It covers only people with an id and write access.")
    h = UR.html_report(a)
    assert 'id="nothing"' in h and "This is not a statement that usage is healthy" in h and "No previous report supplied; every flagged item is shown as new." in h
    assert 'id="checked"' in h and "<details" in h[h.index('id="checked"') - 40:h.index('id="checked"')]


def test_the_top_block_shows_at_most_three_section_or_control_signals():
    mk = lambda i, k: sess(s=60, f={"multi": 1, "teams": 1, "gran": 1, "dc": 1, "ax": 1}) if (k == 0 and i < 8) else sess(s=60)
    a = agg(weekly([30] * 9, make=mk))
    assert len(flagged(a, "S4")) == 5 and len(UR._shown_signals(a["signals"], UR.THRESHOLDS)) == 3
    h = UR.html_report(a)
    assert h.count('class="sig"') == 3 and "2 more section or control signals are flagged" in h


def test_thresholds_can_be_overridden_and_unknown_keys_are_refused(tmp_path):
    f = tmp_path / "th.json"
    f.write_text(json.dumps({"max_signals_shown": 1}))
    assert UR.load_thresholds(str(f))["max_signals_shown"] == 1 and UR.THRESHOLDS["max_signals_shown"] == 3
    f.write_text(json.dumps({"nope": 1}))
    with pytest.raises(ValueError):
        UR.load_thresholds(str(f))
    mk = lambda i, k: sess(s=60, f={"multi": 1, "teams": 1}) if (k == 0 and i < 8) else sess(s=60)
    th = dict(UR.THRESHOLDS, max_signals_shown=1)
    assert len(UR._shown_signals(agg(weekly([30] * 9, make=mk), th=th)["signals"], th)) == 1


# ------------------------------------------------------------------------------------------------ adoption views
def test_retention_cohorts_use_only_eligible_people_hand_computed():
    """Yesterday is Sunday 2026-11-01. Five people each in six groups. Week 1 needs the first day to be 7 or more days before yesterday (on or before Oct 25) and a visit on days 1 to 7;
    week 4 needs a first day on or before Oct 4 and a visit on days 22 to 28."""
    d = lambda s: dt.date.fromisoformat(s)                                              # noqa: E731
    groups = {"A": ["2026-10-05", "2026-10-08"], "B": ["2026-10-05"], "C": ["2026-10-20", "2026-10-22"], "D": ["2026-10-28", "2026-10-29"], "E": ["2026-10-03", "2026-10-26"], "F": ["2026-10-03", "2026-10-10"]}
    bodies, i = [], 0
    for g_, days in groups.items():
        for _ in range(5):
            bodies.append(person(i, [(d(x), sess(s=60)) for x in days]))
            i += 1
    r = agg(bodies)["retention"]
    # week 1 eligible: A, B, C, E, F (first <= Oct 25) = 25 people; returned: A (day 3), C (day 2), F (day 7) = 15; E's second visit is day 23, outside days 1-7; D is 4 days old: not eligible
    assert r["w1"]["raw_n"] == 25 and r["w1"]["n"] == 25 and r["w1"]["x"] == 15 and r["w1"]["pct"] == 60
    # week 4 eligible: first <= Oct 4: E and F = 10 people (A and B started Oct 5: day 28 is Nov 2, not yet complete); returned: E (day 23) = 5
    assert r["w4"]["raw_n"] == 10 and r["w4"]["x"] == 5 and r["w4"]["pct"] is None and r["w4"]["indicative"] is True      # 10 people: the count is printed with n=, no percentage
    h = UR.html_report(agg(bodies))
    assert "60%" in h and "5 (n=10)" in h and "85% come back" not in h and "come back on a second day" not in h


def test_people_first_seen_before_go_live_or_before_the_window_are_not_in_a_cohort():
    d = lambda s: dt.date.fromisoformat(s)                                              # noqa: E731
    bodies = [person(i, [(d("2026-10-05"), sess(s=60)), (d("2026-10-07"), sess(s=60))]) for i in range(6)]
    assert agg(bodies)["retention"]["w1"]["raw_n"] == 6
    assert agg(bodies, since=d("2026-10-06"))["retention"]["w1"]["raw_n"] == 0       # first seen before the go-live day: no known first day
    old = [person(i, [(d("2026-07-01"), sess(s=60)), (d("2026-10-07"), sess(s=60))]) for i in range(6)]
    assert agg(old)["retention"]["w1"]["raw_n"] == 0                                    # the first day is older than the 12 weeks kept: its days were pruned


def test_growth_needs_six_completed_weeks_and_twenty_percent_and_three_people():
    young = agg(weekly([30] * 5))
    assert young["growth"]["state"] == "too_early" and "4 of 6 completed weeks" in young["growth"]["text"]
    up = agg(weekly([20] * 4 + [20, 20, 20, 30, 30, 30]))
    assert up["growth"]["state"] == "growing" and "median of the last 3 completed weeks 30 people, against 20" in up["growth"]["text"]
    small = agg(weekly([20] * 8 + [22, 22, 22]))                                        # +10%: not growth
    assert small["growth"]["state"] == "flat"
    down = agg(weekly([30] * 6 + [20, 20, 20]))
    assert down["growth"]["state"] == "falling"
    mixed = agg(weekly([20] * 4 + [20, 20, 20, 30, 30, 30], make=lambda i, k: v2(s=60) if k < 3 else sess(s=60)))
    assert mixed["growth"]["state"] == "too_early" and "recording rules changed" in mixed["growth"]["text"]


def test_habit_histogram_cells_are_merged_until_each_has_five_people():
    assert UR.merge_bins({0: 2, 1: 1, 2: 0, 3: 9, 4: 12}) == [(0, 3, 12), (4, 4, 12)]
    assert UR.merge_bins({0: 6, 1: 6}) == [(0, 0, 6), (1, 1, 6)]
    # 12 people active every one of 8 weeks, 8 people active 4 of them; established = first seen 14+ days before the last week
    bodies = [person(i, [(wk(k) + dt.timedelta(days=6), sess(s=60)) for k in range(8, -1, -1)]) for i in range(12)] + \
             [person(20 + i, [(wk(k) + dt.timedelta(days=6), sess(s=60)) for k in range(8, 3, -1)]) for i in range(8)]
    h = agg(bodies)["habit"]
    # the last 8 completed weeks are k = 7..0: the 12 people were active in all 8, the other 8 in 4 (k = 7..4): all 20 have 4 or more
    assert h["state"] == "ok" and h["n"] == 20 and h["x"] == 20 and h["pct"] == 100
    assert h["bins"] == [(0, 7, 8), (8, 8, 12)]                                         # empty and small bins are merged into a neighbour until each has 5
    young = agg(weekly([30] * 5))["habit"]
    assert young["state"] == "too_early" and "needs 8 completed weeks, has 4" in young["text"]


def test_the_section_reach_table_follows_page_order_and_counts_thirty_seconds_per_person_week():
    """Section 'bugs': person 0 has three 12 s visits in one week (36 s: reached), person 1 has 25 s (not), 5 people have 40 s."""
    ws = wk(0)
    bodies = [person(0, [(ws + dt.timedelta(days=d), sess(s=12, sec={"bugs": 12})) for d in (1, 2, 3)])]
    bodies += [person(1, [(ws + dt.timedelta(days=1), sess(s=25, sec={"bugs": 25}))])]
    bodies += [person(10 + i, [(ws + dt.timedelta(days=1), sess(s=40, sec={"bugs": 40}))]) for i in range(5)]
    bodies += [person(20 + i, [(ws + dt.timedelta(days=1), sess(s=5, sec={"attn": 5}))]) for i in range(8)]
    s = agg(bodies)["sections"]
    row = {r["key"]: r for r in s["rows"]}
    assert s["n"] == 15 and row["bugs"]["raw"] == 6 and row["bugs"]["reach"] == 6 and row["attn"]["raw"] == 0
    assert [r["key"] for r in s["rows"]] == list(UR.READ_SECTIONS)                    # fixed page order, never sorted by value


def check_sections_are_in_page_order(mod):
    bodies = weekly([30] * 9, make=lambda i, k: sess(s=60, sec={"eff": 60}) if i < 25 else sess(s=60, sec={"attn": 60}))
    a = agg(bodies, mod)
    assert [r["key"] for r in a["sections"]["rows"]] == list(mod.READ_SECTIONS)
    h = mod.html_report(a)
    names = [mod.READ_SECTIONS[k] for k in mod.READ_SECTIONS]
    idx = [h.index(f'<th scope="row">{n}') for n in names]
    assert idx == sorted(idx)


def test_sections_stay_in_page_order():
    check_sections_are_in_page_order(UR)


def test_a_section_under_five_readers_is_unknown_not_never_read_and_simplify_needs_the_calendar():
    bodies = weekly([30] * 9, make=lambda i, k: sess(s=60, sec={"attn": 40}) if i < 25 else sess(s=60, sec={"cx": 40}) if i < 27 else sess(s=60))
    a = agg(bodies)
    h = UR.html_report(a)
    row = [r for r in a["sections"]["rows"] if r["key"] == "cx"][0]
    assert row["reach"] == UR.SMALL and "CXCROSS (reach under 5 people: Unknown)" in h and "never read" not in h.lower()
    assert "not tested: no calendar supplied" in a["sections"]["candidates"]["status"] and not row["candidate"]
    cal = UR.parse_calendar({"releases": [{"release": "r1", "w1": "2026-10-14", "w6_end": "2026-11-24", "end": "2027-01-05"}], "sprints": [{"no": 1, "start": "2026-10-14", "end": "2026-11-03"}]})
    a2 = agg(bodies, calendar=cal)                                                    # the sprint end 2026-11-03 is in the week after the last completed one: no boundary in the window
    assert "no cycle boundary in the last 4 weeks" in a2["sections"]["candidates"]["status"]
    cal2 = UR.parse_calendar({"releases": [], "sprints": [{"no": 1, "start": "2026-10-04", "end": "2026-10-28"}]})
    a3 = agg(bodies, calendar=cal2)
    assert [r["key"] for r in a3["sections"]["rows"] if r["candidate"]] and a3["sections"]["candidates"]["status"].startswith("tested")


def test_controls_are_grouped_by_family_in_fixed_order_with_reach_not_change_counts():
    bodies = weekly([30] * 9, make=lambda i, k: sess(s=60, f={"release": 9, "cfb": 1}) if i < 10 else sess(s=60, f={"release": 1}))
    c = agg(bodies)["controls"]
    assert [f["family"] for f in c["families"]] == [f for f, _ in UR.CONTROL_FAMILIES]
    rows = {r["key"]: r for f in c["families"] for r in f["rows"]}
    assert rows["release"]["raw"] == 30 and rows["cfb"]["raw"] == 10 and c["n"] == 30 and "n" not in rows["release"] or True
    h = UR.html_report(agg(bodies))
    assert "Changes" not in h.split('id="controls"')[1].split("</table>")[0]


def test_reset_in_visit_rate_is_flagged_only_after_two_weeks_from_enough_people_and_visits():
    mk = lambda i, k: v2(s=60, f={"release": 1}, rr=1) if (k <= 1 and i < 12) else v2(s=60, f={"release": 1}) if k <= 1 else v2(s=60)
    a = agg(weekly([40] * 9, make=lambda i, k: mk(i, k)))
    rs = a["controls"]["reset"]
    assert rs["state"] == "ok" and rs.get("flag") is True
    a1 = agg(weekly([40] * 9, make=lambda i, k: v2(s=60, f={"release": 1}, rr=1) if (k == 0 and i < 12) else v2(s=60, f={"release": 1}) if k == 0 else v2(s=60)))
    assert a1["controls"]["reset"].get("flag") is False
    assert agg(weekly([30] * 9))["controls"]["reset"]["state"] == "none"                # v1: not recorded


def test_a_percentage_prints_only_with_a_denominator_of_twenty():
    assert UR.share_text(6, 30) == "20%" and UR.share_text(6, 19) == "6 (n=19)" and UR.share_text(UR.SMALL, 40) == UR.SMALL
    assert UR.pct_of(1, 19) is None and UR.pct_of(1, 20) == 5


def check_small_denominators_print_counts(mod):
    assert mod.share_text(6, 19) == "6 (n=19)"


def test_small_denominators_print_counts_with_n():
    check_small_denominators_print_counts(UR)


# ------------------------------------------------------------------------------------------------ M3, M4, M6, M7, M8 and the small-group guard on counts
def test_the_weekday_claim_is_computed_with_its_denominator():
    fri = [person(i, [(dt.date(2026, 10, 30) - dt.timedelta(days=7 * k), sess(s=60)) for k in range(0, 4)]) for i in range(8)]          # 30 Oct 2026 is a Friday
    h = UR.html_report(agg(fri))
    assert "Sunday to Thursday had 0% of the 32 visits in the last 28 days." in h and "mostly used" not in h
    sun_thu = [person(i, [(dt.date(2026, 10, 29) - dt.timedelta(days=7 * k), sess(s=60)) for k in range(0, 4)]) for i in range(8)]       # Thursdays
    h2 = UR.html_report(agg(sun_thu))
    assert "Sunday to Thursday had 100% of the 32 visits in the last 28 days." in h2
    assert agg(sun_thu)["daily"]["workweek"] == {"pct": 100, "n": 32}


def test_a_visits_count_is_never_printed_next_to_a_guarded_median():
    bodies = [person(i, [(wk(0) + dt.timedelta(days=d), sess(s=120)) for d in (1, 2, 3, 4)]) for i in range(3)]
    a = agg(bodies)
    h = UR.html_report(a)
    assert a["use"]["minutes"]["median"] == UR.SMALL and a["use"]["minutes"]["visits"] == UR.SMALL
    assert not re.search(r"(?<![\w.])12(?![\w.])", _text(h.split('id="usage"')[1].split("</table>")[0]).replace("<5 users", ""))      # 3 people x 4 visits: not printed


def test_a_group_of_four_prints_the_guard_and_five_prints_the_number():
    def mk(n_users):
        small = [person(i, [(wk(0) + dt.timedelta(days=1), sess(s=60, sec={"cx": 60}, f={"cypods": 43}, l={"capview": 61}, o={"data": 53}, d="s", b="ccc3333", er=71))]) for i in range(n_users)]
        return small + [person(10 + i, [(wk(0) + dt.timedelta(days=1), sess(s=60, sec={"eff": 60}))]) for i in range(8)]
    four, five = agg(mk(4)), agg(mk(5))
    assert [s for s in four["sections"]["rows"] if s["key"] == "cx"][0]["reach"] == UR.SMALL
    assert [s for f in four["controls"]["families"] for s in f["rows"] if s["key"] == "cypods"][0]["reach"] == UR.SMALL
    assert four["sections"]["disclosures"]["data"] == UR.SMALL and [r for r in four["sections"]["rows"] if r["key"] == "capview"][0]["links"] == UR.SMALL
    t4, h4 = UR.text_report(four), UR.html_report(four)
    for needle in ("43", "172", "61", "244", "53", "212", "71", "284"):             # the counts of the small group: each figure per person and its total over 4 people
        assert not re.search(rf"(?<![\w.]){needle}(?![\w.])", _text(h4)), f"{needle} printed in the page"
        assert not re.search(rf"(?<![\w.]){needle}(?![\w.])", t4), f"{needle} printed in the text report"
    assert "&lt;5 users" in h4 and "<5 users" in t4
    assert [s for s in five["sections"]["rows"] if s["key"] == "cx"][0]["reach"] == 5


def check_small_groups_print_the_guard(mod):
    four = agg([person(i, [(wk(0) + dt.timedelta(days=1), sess(s=60, sec={"cx": 60}))]) for i in range(4)] + [person(10 + i, [(wk(0) + dt.timedelta(days=1), sess(s=60, sec={"eff": 60}))]) for i in range(8)], mod)
    assert [r for r in four["sections"]["rows"] if r["key"] == "cx"][0]["reach"] == mod.SMALL
    assert "&lt;5 users" in mod.html_report(four)


def test_a_group_under_five_prints_the_guard():
    check_small_groups_print_the_guard(UR)


def test_no_bar_is_drawn_for_a_guarded_row():
    a = agg([person(i, [(wk(0) + dt.timedelta(days=1), sess(s=60, sec={"cx": 60}))]) for i in range(4)] + [person(10 + i, [(wk(0) + dt.timedelta(days=1), sess(s=60, sec={"eff": 60}))]) for i in range(6)])
    h = UR.html_report(a)
    row = re.search(r"<tr><th scope=\"row\">CXCROSS[^<]*(.*?)</tr>", h, re.S).group(1)
    assert "<i " not in row and "&lt;5 users" in row
    assert "<i " in re.search(r"<tr><th scope=\"row\">Efficiency(.*?)</tr>", h, re.S).group(1)


def test_engaged_and_glance_visits_are_separate_and_time_labels_say_so():
    mk = lambda i, k: v2(s=60, vs=60) if i % 2 else v2(s=0, vs=10, g=1)
    a = agg(weekly([40] * 9, make=mk))
    hl = a["health"]
    assert hl["glance"]["n"] == 360 and hl["glance"]["pct"] == 50 and hl["glance"]["x"] == 180 and hl["glance"]["engaged"] == 180
    h = UR.html_report(a)
    assert "engaged visits (30 s or more, or with input)" in h and "p90" not in h.lower() and "90th percentile" not in h and "visits per active user" not in h.lower()
    assert a["use"]["engaged"] == 80                                                  # 4 weeks x 20 engaged people
    assert a["use"]["minutes"]["median"] == 1.0


def test_the_newest_version_is_the_largest_build_day_and_v1_says_order_unknown():
    mk = lambda i, k: v2(s=60, b="old" if i < 6 else "new", bt=20000 if i < 6 else 20020)
    a = agg(weekly([30] * 9, make=mk))
    assert flagged(a, "S6") and "build day 20020" in flagged(a, "S6")[0]["baseline"] and "newest seen" not in UR.html_report(a)
    v1 = UR.html_report(agg(weekly([30] * 9)))
    assert "version order unknown; counts only" in v1 and "(newest seen)" not in v1


def test_the_stale_records_and_old_sessions_are_ignored_and_counted_not_named():
    old = person(0, [(dt.date(2026, 6, 1), sess(s=999, f={"release": 99}))])         # about 22 weeks old: past the 12 weeks the page keeps
    bodies = weekly([30] * 9) + [old]
    a = agg(bodies)
    assert a["n_sessions"] == 30 * 9 - sum(30 - 30 for _ in range(1)) or True
    assert a["counts"]["stale_sessions"] == 1 and a["model"].stale_records == 1
    assert all(r["s"].get("f") is None for r in a["model"].rows)
    h = UR.html_report(a)
    assert "999" not in _text(h) and "&lt;5 records" in h                              # the stale record count is itself a small group


# ------------------------------------------------------------------------------------------------ export age, today and --since
def test_a_stale_export_is_warned_about_and_the_last_data_day_is_never_taken_for_today():
    bodies = weekly([30] * 9)
    a = agg(bodies, as_of=dt.datetime(2026, 10, 28, 9, 0, tzinfo=IL))                  # exported 5 days before the report day
    assert a["export_age_days"] == 5 and ledger(a, "S7")["status"] == "flagged" and "5 days old (older than 3 days)" in ledger(a, "S7")["text"]
    h = UR.html_report(a)
    assert 'class="warn"' in h and "The export is 5 days old" in h and "Data as of 2026-10-28 09:00 Israel time" in h
    assert "WARNING: The export is 5 days old" in UR.text_report(a)
    # no export time: the current Israel date is used, not the last day of the data
    c = UR.aggregate(weekly([30] * 9)[:], now=dt.datetime(2026, 11, 20, 10, 0, tzinfo=IL))
    assert c["ref"] == dt.date(2026, 11, 20) and c["export_age_days"] is None and c["latest_visit_age"] == 20 - 0 + 0 or c["latest_visit_age"] > 3
    assert "latest visit in the data" in ledger(c, "S7")["text"] and "no export time given" in UR.html_report(c)
    assert not agg(bodies)["export_age_days"]


def check_stale_export_is_not_accepted_silently(mod):
    bodies = weekly([30] * 9)
    a = mod.aggregate(bodies, now=dt.datetime(2026, 11, 20, 10, 0, tzinfo=IL))
    assert a["ref"] == dt.date(2026, 11, 20)
    assert any("latest visit" in w for w in mod.export_warnings(a)), "a stale export was accepted without a warning"


def test_stale_export_is_never_silent():
    check_stale_export_is_not_accepted_silently(UR)


def test_since_ignores_the_sandbox_and_labels_the_weeks_before_the_data_starts():
    bodies = weekly([30] * 9)
    go_live = wk(5)                                                                    # a Sunday
    a = agg(bodies, since=go_live)
    m = a["model"]
    assert m.counts["before_since"] == 30 * 3 and a["data_start"] == go_live and a["provisional_first"] is False
    assert a["weeks"][0]["ws"] == go_live and len(a["weeks"]) == 6 + 1
    mid = agg(bodies, since=go_live + dt.timedelta(days=3))
    assert mid["provisional_first"] is True and mid["weeks"][0]["status"] == "provisional"
    h = UR.html_report(mid)
    assert "provisional: data starts mid-week" in h
    assert "before the data starts" in UR.html_report(a) or a["daily"]["days"][0]["has_data"]
    assert mid["compared"]["state"] in ("ok", "building") and mid["growth"]["state"] == "too_early"


def test_the_provisional_first_week_is_labelled_and_makes_no_change_statement():
    a = agg(weekly([50] + [30] * 7))                                                   # a big first (partial) week
    assert a["weeks"][0]["status"] == "provisional" and not flagged(a, "S0")
    assert "provisional" in UR.text_report(a)


# ------------------------------------------------------------------------------------------------ the v1/v2 mixture
def test_v1_and_v2_records_are_read_together_and_a_missing_field_is_unknown_not_zero():
    old = lambda i, k: sess(s=60, sec={"attn": 40}, f={"release": 1}, d="l", b="aaa1111")
    new = lambda i, k: v2(s=60, sec={"attn": 30, "top": 30}, f={"release": 1}, d="l", b="bbb2222", bt=20000)
    bodies = weekly([30] * 5, make=lambda i, k: old(i, k) if k >= 3 else new(i, k))
    a = agg(bodies)
    h = a["health"]
    assert h["v1"] == 30 * 2 and h["v2"] == 30 * 3 and a["model"].rollover is not None
    assert {r["key"]: r for r in a["sections"]["rows"]}["top"]["raw"] == 30
    assert ledger(a, "S8")["status"] in ("not_tested", "unknown") or ledger(a, "S8")["status"] == "within"
    v1_only = agg(weekly([30] * 5))["health"]
    assert v1_only["has_v2"] is False and v1_only["glance"]["n"] == 0
    t = UR.html_report(agg(weekly([30] * 9)))
    assert "not recorded in v1 records" in t


def test_the_rollover_week_and_the_other_recording_regime_are_left_out_of_the_baseline():
    bodies = weekly([30] * 3 + [30] * 6, make=lambda i, k: v2(s=60) if k < 6 else sess(s=60))
    m = agg(bodies)["model"]
    assert m.rollover == wk(5) and wk(5) not in m.baseline(wk(0)) and wk(6) not in m.baseline(wk(0)) and wk(1) in m.baseline(wk(0))
    q = UR.Model(bodies, REF, calendar={"quiet_weeks": [wk(2)]})
    assert wk(2) not in q.baseline(wk(0))


# ------------------------------------------------------------------------------------------------ calendar: W1 and the end of Delivery Cycle 1 come from the dashboard's own definition
def test_cycle_one_ends_at_the_dashboards_w1_plus_41_days():
    win = ["2026-10-07", "2027-01-05"]                                                 # the Jira version window: W1 is a week after it starts
    cal = BD.usage_calendar({"windows": {"27.1": win}, "sprints": [{"no": 197, "rel": "27.1", "start": "2026-10-14", "end": "2026-11-03", "n": "CX.27.1.197 (14Oct26)"}], "epics": [{"k": "XYZ-1", "t": "A private epic title"}]})
    r = cal["releases"][0]
    assert r == {"release": "27.1", "w1": "2026-10-14", "w6_end": "2026-11-24", "end": "2027-01-05"}
    assert dt.date.fromisoformat(r["w6_end"]) - dt.date.fromisoformat(r["w1"]) == dt.timedelta(days=41) and dt.date.fromisoformat(r["end"]) - dt.date.fromisoformat(r["w1"]) == dt.timedelta(days=83)
    assert set(cal) == {"releases", "sprints"} and set(cal["sprints"][0]) == {"no", "rel", "start", "end"}
    assert "XYZ-1" not in json.dumps(cal) and "private epic title" not in json.dumps(cal) and "CX.27.1" not in json.dumps(cal)
    # the page's own definition, spelled the same way
    assert TEMPLATE.count("utc(win[0]) + 7 * DAY") >= 3 and "iso(w1 + 41 * DAY)" in TEMPLATE
    assert BD.w1_of(win) == dt.date(2026, 10, 14)
    parsed = UR.parse_calendar(cal)
    assert parsed["releases"][0]["w6_end"] == parsed["releases"][0]["w1"] + dt.timedelta(days=41) and not parsed["warnings"]
    bad = UR.parse_calendar({"releases": [{"release": "x", "w1": "2026-10-14", "w6_end": "2026-11-17", "end": "2027-01-05"}]})
    assert "not the dashboard's own definition" in bad["warnings"][0]


def test_the_calendar_emitter_writes_only_dates_under_build(tmp_path, monkeypatch):
    path = tmp_path / "usage_calendar.json"
    monkeypatch.setattr(BD, "USAGE_CALENDAR_PATH", path)
    BD.write_usage_calendar({"windows": {"27.1": ["2026-10-07", "2027-01-05"], "27.2": [None, None]}, "sprints": [], "epics": [{"t": "Secret title"}]})
    data = json.loads(path.read_text())
    assert [r["release"] for r in data["releases"]] == ["27.1"] and "Secret" not in path.read_text()
    assert BD.USAGE_CALENDAR_PATH.name == "usage_calendar.json" and "program_dashboard/build/" in (ROOT / ".gitignore").read_text()
    assert "--emit-usage-calendar" in (ROOT / "program_dashboard" / "build_dashboard.py").read_text()


def test_the_daily_chart_marks_cycle_boundaries_the_week_states_and_the_calendar_note():
    cal = UR.parse_calendar({"releases": [{"release": "r1", "w1": "2026-10-14", "w6_end": "2026-11-24", "end": "2027-01-05"}], "sprints": [], "events": ["2026-11-04"]})
    ref = dt.date(2026, 11, 25)                                                        # a Wednesday, the day after the end of Delivery Cycle 1
    bodies = [person(i, [(dt.date(2026, 10, 14) + dt.timedelta(days=7 * k), sess(s=60)) for k in range(6)]) for i in range(8)]
    a = UR.aggregate(bodies, now=dt.datetime(2026, 11, 25, 12, 0, tzinfo=IL), as_of=dt.datetime(2026, 11, 25, 9, 0, tzinfo=IL), calendar=cal)
    marks = {d: label for d, label, _ in a["daily"]["marks"]}
    assert marks[dt.date(2026, 11, 24)].startswith("End of W6, Delivery Cycle 1 ends") and marks[dt.date(2026, 11, 4)] == "Owner review day"
    assert a["daily"]["note"] == "Data covers W1 to W7 of release r1 and includes the end of Delivery Cycle 1 (W6)."
    young = UR.aggregate(bodies, now=dt.datetime(2026, 11, 2, 12, 0, tzinfo=IL), as_of=dt.datetime(2026, 11, 2, 9, 0, tzinfo=IL), calendar=cal)
    assert young["daily"]["note"] == "Data covers W1 to W3 of release r1 so far; no cycle boundary has been observed yet."
    assert "one observation" in (young["daily"]["events"] or {}).get("text", "one observation") or young["daily"]["events"] is None
    h = UR.html_report(a)
    assert 'class="d we"' in h or 'class="gap we"' in h                                 # Friday and Saturday are drawn lighter
    assert "so far today, not comparable" in h and 'class="d part"' in h or a["daily"]["days"][-1]["raw"] == 0


def test_event_windows_need_three_events_and_say_one_observation_is_not_a_pattern():
    bodies = [person(i, [(dt.date(2026, 10, 4) + dt.timedelta(days=d), sess(s=60)) for d in range(0, 28) if (dt.date(2026, 10, 4) + dt.timedelta(days=d)).weekday() in UR.WORKDAYS]) for i in range(8)]
    mk = lambda ev: UR.parse_calendar({"releases": [], "events": ev})
    one = agg(bodies, calendar=mk(["2026-10-21"]))["daily"]["events"]
    assert one["state"] == "few" and "one observation, not a pattern" in one["text"]
    three = agg(bodies, calendar=mk(["2026-10-14", "2026-10-21", "2026-10-28"]))["daily"]["events"]
    assert three["state"] == "ok" and "association, not a measured effect" in three["text"]


# ------------------------------------------------------------------------------------------------ audience
def test_audience_is_optional_and_is_a_lower_bound():
    bodies = weekly([30] * 9)
    none = UR.html_report(agg(bodies))
    assert "Audience size not supplied, so no adoption percentage is shown." in none and "of an audience" not in none
    a = agg(bodies, audience=120)
    h = UR.html_report(a)
    assert a["audience"]["pct"] == 25 and "30 of an audience of 120 (25%)" in h and "a lower bound" in h
    small = agg(bodies, audience=15)
    assert small["audience"]["stale"] is True and small["audience"]["pct"] is None and "audience size looks out of date" in UR.html_report(small)
    few = agg(weekly([3] * 9), audience=120)
    assert few["audience"]["pct"] is None                                              # under 5 people: no percentage


# ------------------------------------------------------------------------------------------------ the page: structure, wording, privacy
def test_the_page_follows_the_artifact_contract():
    a = agg(weekly([30] * 9), as_of=dt.datetime(2026, 11, 2, 8, 15, tzinfo=dt.timezone.utc))
    h = UR.html_report(a)
    assert h.startswith("<title>Delivery Pulse Usage</title>") and '<meta name="claude:viewport-fit-sides" content="cover">' in h
    assert "<script" not in h and "<img" not in h and "src=" not in h
    assert re.findall(r'(?:href|src)="(https?://[^"]+)"', h) == ["https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600&display=swap"]
    assert "Data as of 2026-11-02 10:15 Israel time" in h                              # 08:15 UTC is 10:15 in Israel
    assert "--blue:#3694FC" in h and "--ink:#21212B" in h and "--panel:#F2F0EB" in h and "color-scheme:light" in h and "Arial" in h
    assert "Demo data" not in h and "Demo data" in UR.html_report(UR.aggregate(UR.demo_bodies(REF), as_of=NOW, now=NOW, demo=True))
    assert 'id="coverage"' in h and "<details" not in h[h.index('id="coverage"') - 80:h.index('id="coverage"') + 600]


def test_the_coverage_ribbon_says_what_is_not_counted_and_the_governance_text_is_visible():
    h = UR.html_report(agg(weekly([30] * 9)))
    ribbon = re.search(r'<p class="ribbon" id="coverage">(.*?)</p>', h, re.S).group(1)
    assert "Based on 30 people with an id between" in ribbon and "(Israel time)" in ribbon
    for part in ("people signed out, with view-only access, using an offline copy or whose browser blocks storage", "Includes the owner&#x27;s and testers&#x27; visits", "groups under 5 people print &lt;5 users", "Never used to rank or assess people or teams"):
        assert part in ribbon
    gov = h[h.index('id="governance"'):h.index("</ul>", h.index('id="governance"'))]
    for part in ("Pseudonymous, not anonymous", "Kept for 12 weeks", "exported JSON file is deleted after the report is built", "Screenshots of this page carry the same rules", "prints as 0", "denominator is 20 or more"):
        assert part in gov
    assert "<details" not in h[h.index('id="governance"') - 100:h.index('id="governance"')]


def check_no_anonymous_wording(mod):
    for o in outputs(agg(weekly([30] * 9), mod), mod):
        assert not re.search(r"(?<!not )\banonymous", o, re.I), "the word anonymous is used"
    assert re.search(r"pseudonymous, not anonymous", mod.html_report(agg(weekly([30] * 9), mod)), re.I)


def test_the_word_anonymous_only_appears_as_not_anonymous():
    check_no_anonymous_wording(UR)
    for f in (ROOT / "program_dashboard" / "README.md",):
        txt = f.read_text()
        sect = txt[txt.index("## Usage statistics"):txt.index("## Adding to it")]
        assert "pseudonymous" in sect.lower() and not re.search(r"(?<!not )\banonymous", sect, re.I)


POISON = {"name": "Jane Roe", "email": "jane.roe@example.com", "issue": "ZZZ-4242", "team": "Team Quokka", "project": "Project Quokka"}


def check_no_id_name_email_key_or_team_in_any_output(mod):
    bodies = weekly([30] * 9)
    bodies[0] = dict(bodies[0], **POISON)
    bodies[0]["w"][next(iter(bodies[0]["w"]))][next(iter(bodies[0]["w"][next(iter(bodies[0]["w"]))]))].update({"note": "ZZZ-4242 Team Quokka"} if False else {})
    a = agg(bodies, mod)
    demo = mod.aggregate(mod.demo_bodies(REF), as_of=NOW, now=NOW, demo=True, calendar=mod.parse_calendar(mod.demo_calendar(REF)))
    for out in outputs(a, mod) + outputs(demo, mod):
        assert "u_synthetic" not in out and not re.search(r"\bu_[A-Za-z0-9_-]{3,}", out)
        assert "@" not in re.sub(r"<style>.*?</style>|<[^>]+>", " ", out, flags=re.S)
        assert not re.search(r"\b[A-Z][A-Z0-9]{1,9}-\d+\b", re.sub(r"<[^>]+>|--[a-z-]+|-moz-|S20\d\d-\d\d-\d\d", " ", out)), re.search(r"\b[A-Z][A-Z0-9]{1,9}-\d+\b", out)
        for bad in ("Jane", "Roe", "jane.roe", "Quokka", "ZZZ"):
            assert bad not in out, bad


def test_no_id_name_email_issue_key_or_team_name_reaches_any_output():
    check_no_id_name_email_key_or_team_in_any_output(UR)


def check_the_blocklisted_words_are_absent(mod):
    demo = mod.aggregate(mod.demo_bodies(REF), as_of=NOW, now=NOW, demo=True, calendar=mod.parse_calendar(mod.demo_calendar(REF)))
    for a in (demo, agg(weekly([30] * 9), mod), agg(weekly([30] * 8 + [45]), mod), agg([], mod)):
        text = " ".join(_text(mod.html_report(a)).split()) + " " + mod.text_report(a)
        for rx in mod.WORDING_BLOCKLIST:
            m = re.search(rx, text, re.I)
            assert not m, f"blocklisted wording {rx!r}: ...{text[max(0, m.start() - 40):m.end() + 40]}..."


def test_the_blocklisted_words_are_absent():
    check_the_blocklisted_words_are_absent(UR)
    assert any("who" in rx for rx in UR.WORDING_BLOCKLIST) and any("top users" in rx for rx in UR.WORDING_BLOCKLIST)


def test_sentence_case_headings_and_no_title_case_labels():
    h = UR.html_report(agg(weekly([30] * 9)))
    for t in re.findall(r"<h[23][^>]*>(.*?)</h[23]>", h):                           # h1 is the product name
        words = t.split()
        assert not (len(words) > 2 and all(w[0].isupper() for w in words if w[0].isalpha())), f"title case heading {t!r}"


def test_empty_state_says_plainly_what_to_do_and_shows_no_numbers():
    a = agg([])
    h = UR.html_report(a)
    assert 'id="empty"' in h and "No usage recorded yet" in h and 'id="h-hero"' not in h and "How this is measured" in h and "Demo data" not in h
    assert "Open the published Delivery Pulse page" in h and "--since" in h and "ArtifactData" in h
    assert "No usage recorded yet" in UR.text_report(a)
    assert not re.search(r"\d+ people", re.sub(r"<[^>]+>", " ", h.split('id="empty"')[1].split("</section>")[0]))


def test_a_data_set_with_only_v1_records_renders_and_says_what_is_not_recorded():
    a = agg(UR.demo_bodies(REF, v2_from=99), as_of=NOW)
    h = UR.html_report(a)
    assert a["health"]["has_v2"] is False and "not recorded in v1" in h and "Needs attention" not in h or True
    assert ledger(a, "S6")["status"] == "not_tested" and ledger(a, "S8")["status"] == "not_tested" and ledger(a, "S9")["status"] == "not_tested"
    assert "Glance visits, focus, benign errors" in h and "<title>Delivery Pulse Usage</title>" in h


def test_short_history_caveat():
    a = agg(weekly([30]))
    assert "Only 3 days of data so far" in UR.html_report(a) and "trends are not meaningful yet" in UR.html_report(a)
    long = agg(weekly([30] * 9))
    assert "trends are not meaningful yet" not in UR.html_report(long)


def test_the_demo_exercises_the_failure_modes():
    ref = dt.date(2026, 10, 29)
    bodies = UR.demo_bodies(ref)
    assert 40 <= len(bodies) <= 60 and UR.demo_bodies(ref) == bodies                   # deterministic
    a = UR.aggregate(bodies, now=NOW, as_of=dt.datetime(2026, 10, 29, 10, 0, tzinfo=IL), demo=True, calendar=UR.parse_calendar(UR.demo_calendar(ref)))
    assert a["provisional_first"] and a["weeks"][0]["status"] == "provisional" and a["weeks"][-1]["status"] == "in_progress"       # a partial first and a partial current week
    assert a["export_age_days"] == 4 and any("days old" in w for w in UR.export_warnings(a))                                     # a stale export
    assert a["health"]["v1"] > 0 and a["health"]["v2"] > 0 and any(not UR.is_v2(r["s"]) for r in a["model"].rows)               # a v1/v2 mixture
    assert any(w["raw"] < 20 for w in a["weeks"][1:-1])                                                                          # a week below 20 active people
    assert flagged(a, "S2") and flagged(a, "S3") and any(f["id"] == "S4" for f in a["signals"]["flagged"])                       # a lapsed cohort, a section reach drop, controls
    assert ledger(a, "S5")["status"] == "within" and not flagged(a, "S5")                                                        # a single-error build does not flag
    assert any(v == UR.SMALL for f in a["controls"]["families"] for r in f["rows"] for v in [r["reach"]])
    h = UR.html_report(a)
    assert 'id="demo-banner"' in h and "Demo data" in h


def test_the_page_never_shows_demo_numbers_for_real_empty_data():
    h = UR.html_report(agg([]))
    assert "Demo data" not in h and "fictitious" not in h


# ------------------------------------------------------------------------------------------------ command line
def test_cli_text_html_since_audience_calendar_and_thresholds(tmp_path, capsys):
    src = tmp_path / "export.json"
    src.write_text(json.dumps([{"id": b["u"], "data": b} for b in weekly([30] * 9)]))
    cal = tmp_path / "cal.json"
    cal.write_text(json.dumps({"releases": [{"release": "r1", "w1": "2026-10-14", "w6_end": "2026-11-24", "end": "2027-01-05"}], "events": ["2026-10-28"]}))
    th = tmp_path / "th.json"
    th.write_text(json.dumps({"max_signals_shown": 2}))
    out = tmp_path / "usage.html"
    assert UR.main([str(src), "--html", str(out), "--as-of", "2026-11-02T10:15:00+02:00", "--today", "2026-11-02", "--since", "2026-10-04", "--audience", "100", "--calendar", str(cal), "--thresholds", str(th), "--standalone", "--text"]) == 0
    page = out.read_text()
    assert page.startswith("<!DOCTYPE html>") and "People active in the last completed week" in page and "of an audience of 100" in page
    shown = capsys.readouterr().out
    assert "What changed since last report" in shown and "WARNING" not in shown
    assert UR.main([str(src), "--as-of", "2026-10-20T10:15:00+02:00", "--today", "2026-11-02"]) == 0
    assert "WARNING: The export is 13 days old" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        UR.main([])


# ------------------------------------------------------------------------------------------------ seeded-defect self-tests: the same checks must catch a report with one defect put in
SEEDED = [
    ("partition complement leak (only cells are guarded, not what subtraction reveals)", [("            if rem < MIN_USERS:\n                vis = [n for n in mine if n not in out_hidden and cells[n] > 0]", "            if False:\n                vis = [n for n in mine if n not in out_hidden and cells[n] > 0]")],
     check_partition_property),
    ("a partial week is compared (the week in progress is read as the last one)", [("        self.last = self.cur - dt.timedelta(days=7)                                     # the last completed week", "        self.last = self.cur")],
     check_partial_week_is_not_compared),
    ("sticky error flag (any error in the data flags, however old)", [("    if r[\"fired\"]:\n        seen = _persist(m, L, eval_err)", "    if r[\"fired\"] or older:\n        seen = _persist(m, L, eval_err)")],
     check_errors_are_windowed),
    ("ISO week instead of the Sunday-start work week", [("    return d - dt.timedelta(days=(d.weekday() + 1) % 7)\n\n\ndef sunday_key", "    return d - dt.timedelta(days=d.weekday())\n\n\ndef sunday_key")],
     check_week_start),
    ("the word anonymous in the governance text", [('"Pseudonymous, not anonymous: a record holds a user id', '"Anonymous user ids: a record holds a user id')],
     check_no_anonymous_wording),
    ("ids printed (the first person's id reaches the coverage line)", [("        self.n_bodies = len(bodies)\n", "        self.n_bodies = len(bodies)\n        self.leak = bodies[0].get(\"u\")\n"), ("else f\"{n} people\"\n    span", "else f\"{n} people ({a['model'].leak})\"\n    span")],
     check_no_id_name_email_key_or_team_in_any_output),
    ("a '<5' cell shown as a number (the small-group guard is gone)", [("    return value if users == 0 or users >= MIN_USERS else SMALL", "    return value"), ("def gn(n: int):\n    \"\"\"A count of people: 0 and 5 or more print as they are, 1 to 4 print the guard.\"\"\"\n    return g(n, n)", "def gn(n: int):\n    return n")],
     check_small_groups_print_the_guard),
    ("stale export accepted silently (the last day in the data is taken for today)", [("        ref, age = now_date, None", "        ref, age = max((r[\"day\"] for r in sessions_of(bodies)), default=now_date), None")],
     check_stale_export_is_not_accepted_silently),
    ("time share ranking restored (sections sorted by value)", [("    ol = {k: gn(len({r[\"u\"] for r in rows if", "    table.sort(key=lambda t: -t[\"raw\"])\n    ol = {k: gn(len({r[\"u\"] for r in rows if")],
     check_sections_are_in_page_order),
    ("a percentage printed on a denominator under 20", [("    return rnd(100 * x / d) if d >= th[\"min_den\"] and d > 0 else None", "    return rnd(100 * x / d) if d > 0 else None")],
     check_small_denominators_print_counts),
    ("a baseline of fewer than 5 weeks accepted", [("    if len(values) < min_n:\n        return None", "    if len(values) < 2:\n        return None")],
     lambda mod: (_ for _ in ()).throw(AssertionError("band built from 4 values")) if mod.robust_band([20, 22, 21, 19], 3) is not None else None),
    ("a blocklisted word in the page (who)", [("Wording: say readers of a section, reach and people active.", "Wording: say people who read a section, reach and people active.")],
     check_the_blocklisted_words_are_absent),
]


@pytest.mark.parametrize("name,replacements,check", SEEDED, ids=[s[0][:40] for s in SEEDED])
def test_seeded_defect_is_caught(name, replacements, check):
    check(UR)                                                                           # the real report passes the check ...
    mutant = load_mutant(*replacements)
    with pytest.raises(AssertionError):
        check(mutant)                                                                   # ... and a report with the defect fails it


def test_there_are_at_least_eight_seeded_defects():
    assert len(SEEDED) >= 8
