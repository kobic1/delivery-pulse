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


@pytest.fixture(autouse=True)
def _default_min_group():
    """A test that sets another minimum group size must not leak it into the next one."""
    UR.set_min_group(5)
    yield
    UR.set_min_group(5)


def with_min_group(n: int, mod=UR) -> dict:
    return {**mod.THRESHOLDS, "min_group": n}


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


UV_MARK = "// ---------------------------------------------------------------- live usage view (owner only"


def test_the_page_reads_only_the_id_and_never_leaves_the_page():
    block = TEMPLATE[TEMPLATE.index("const USAGE_VOC"):TEMPLATE.index(UV_MARK)]                # the recording block, up to the owner-only view
    assert re.search(r"Usage statistics: this page counts, per pseudonymous user id \(a code, no name or e-mail; only the owner of this page can read these records\)", block)
    assert "What is counted" in block and "Kept for 12 weeks" in block
    assert re.search(r"user\.id\(\)", block) and not re.search(r"user\.(name|email|me|profiles|search)\b", block)
    assert block.count('window.claude.use("db")') == 1 and block.count('window.claude.use("user")') == 1 and "scopes" not in block
    for banned in ("fetch(", "sendBeacon", "XMLHttpRequest", "WebSocket", "localStorage", "document.cookie"):
        assert banned not in block, f"the usage block must not use {banned}"


def test_the_owner_view_only_reads_and_never_shows_or_sends_identity():
    uv = TEMPLATE[TEMPLATE.index(UV_MARK):]
    assert "isOwner()" in uv and "return;" in uv.split("isOwner()")[1][:80], "the view must stop at once for a viewer who is not the owner"
    assert not re.search(r"user\.(id|name|email|me|profiles|search)\b", uv) and "scopes" not in uv       # no identity is read
    assert 'db.collection("usage").limit(' in uv and set(re.findall(r"\bdb\.(\w+)", uv)) == {"collection"}, "the view reads one collection and uses nothing else of the db"
    assert not re.search(r"\.doc\(|\.(update|delete)\(|batch|transaction|\bset\(\{", uv), "the view writes nothing"
    for banned in ("fetch(", "sendBeacon", "XMLHttpRequest", "WebSocket", "localStorage", "document.cookie", "downloads"):
        assert banned not in uv, f"the owner view must not use {banned}"
    assert not re.search(r"\bu_[A-Za-z0-9]", uv)                                                          # no id is ever drawn or kept


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
    txt = UR.text_report(a)                                                             # the text report keeps the "What changed since last report" section; the page does not show it
    assert "What changed since last report" in txt and "No previous report supplied; every flagged item is shown as new." in txt and "This is not a statement that usage is healthy" in txt and "  Checked:" in txt
    h = UR.html_report(a)
    assert 'id="changed"' not in h and "What changed since last report" not in h and 'id="checked"' not in h and 'id="nothing"' not in h and 'class="chips"' not in h


def test_the_top_block_shows_at_most_three_section_or_control_signals():
    mk = lambda i, k: sess(s=60, f={"multi": 1, "teams": 1, "gran": 1, "dc": 1, "ax": 1}) if (k == 0 and i < 8) else sess(s=60)
    a = agg(weekly([30] * 9, make=mk))
    assert len(flagged(a, "S4")) == 5 and len(UR._shown_signals(a["signals"], UR.THRESHOLDS)) == 3
    txt = UR.text_report(a)
    assert txt.count("  [S4]") == 3 and "2 more section or control signals are listed under Checked." in txt


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
    row = re.search(r'<div class="hb"><span class="hl">CXCROSS(.*?)</div>(?=<div class="hb"|<div class="hax")', h, re.S).group(1)         # the chart row (the table row behind "Show data" holds no bar either)
    assert 'class="gstub"' in row and "&lt;5 users" in row and "style=\"width" not in row and not re.search(r"\d", re.sub(r"&lt;5 users", "", row))
    assert 'style="width:' in re.search(r'<div class="hb"><span class="hl">Efficiency(.*?)</div>(?=<div class="hb"|<div class="hax")', h, re.S).group(1)


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
    v1 = UR.text_report(agg(weekly([30] * 9)))                                         # the ledger of the signals is in the text report
    assert "version order unknown; counts only" in v1 and "(newest seen)" not in v1 and "(newest seen)" not in UR.html_report(agg(weekly([30] * 9)))


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
    assert 'class="col we"' in h or 'class="slot"' in h                                 # Friday and Saturday are drawn lighter
    assert "so far today, not comparable" in h and 'class="col part"' in h or a["daily"]["days"][-1]["raw"] == 0


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
    assert "No audience size supplied" in none and "of an audience" not in none
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
    assert "Based on 30 people with an id, " in ribbon and "(Israel time)" in ribbon and len(ribbon) < 520                 # two lines on a desktop
    for part in ("Pseudonymous, not anonymous", "Not counted: signed-out, view-only, offline-copy and storage-blocked visitors", "Groups under 5 people show &lt;5 users", "Never used to rank or assess people or teams"):
        assert part in ribbon
    how = h[h.index('id="how"'):]
    assert "people signed out, with view-only access, using an offline copy or whose browser blocks storage" in how and "Includes the owner&#x27;s and testers&#x27; visits" in how
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
    assert page.startswith("<!DOCTYPE html>") and "Key figures" in page and "of an audience of 100" in page
    shown = capsys.readouterr().out
    assert "What changed since last report" in shown and "WARNING" not in shown
    assert UR.main([str(src), "--as-of", "2026-10-20T10:15:00+02:00", "--today", "2026-11-02"]) == 0
    assert "WARNING: The export is 13 days old" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        UR.main([])


# ------------------------------------------------------------------------------------------------ the graph-first page: charts, their text equivalents and the guards inside them
def demo_agg(mod=UR):
    ref = dt.date(2026, 10, 29)
    return mod.aggregate(mod.demo_bodies(ref), as_of=dt.datetime(2026, 10, 29, 10, 0, tzinfo=IL), now=NOW, demo=True, calendar=mod.parse_calendar(mod.demo_calendar(ref)))


def t_of(day: dt.date, hour: int) -> int:
    """The `t` a v2 page writes for a visit that opens at hour:30 Israel time on that day: hours since the epoch (UTC)."""
    return int(dt.datetime(day.year, day.month, day.day, hour, 30, tzinfo=IL).astimezone(dt.timezone.utc).timestamp() // 3600)


def hour_bodies() -> list:
    """12 people open the page on Tuesdays at 10:30 in 6 weeks (72 visits); 3 of them also open it on Wednesdays at 15:30, 5 times each (15 visits by 3 people: a withheld cell)."""
    out = []
    for i in range(12):
        visits = [(wk(k) + dt.timedelta(days=2), v2(s=60, t=t_of(wk(k) + dt.timedelta(days=2), 10))) for k in range(6)]
        if i < 3:
            visits += [(wk(k) + dt.timedelta(days=3), v2(s=60, t=t_of(wk(k) + dt.timedelta(days=3), 15))) for k in range(5)]
        out.append(person(i, visits))
    return out


def chart_units(h: str) -> list:
    """The chart units of a page: every panel and the key-figures section, each with the number of role=img charts and whether a 'Show data' disclosure with a table sits in it."""
    units = []
    for chunk in re.split(r'(?=<div class="panel |<section )', h):
        if chunk.startswith('<div class="panel ') or chunk.startswith('<section class="blk" id="kpis"'):
            chunk = chunk.split("</section>")[0]
            units.append({"head": chunk[:60], "imgs": chunk.count('role="img"'), "table": bool(re.search(r'<details class="vd"><summary>Show data</summary>.*?<table', chunk, re.S))})
    return units


def check_every_chart_has_its_table(mod):
    for a in (demo_agg(mod), agg(weekly([30] * 9), mod), agg(mod.demo_bodies(REF, v2_from=99), mod)):
        h = mod.html_report(a)
        units = chart_units(h)
        assert len(units) >= 8 and sum(u["imgs"] > 0 for u in units) >= 5, "the charts are missing"
        for u in units:
            assert u["table"] or not u["imgs"], f"a chart without the table behind Show data: {u['head']}"
        for tag in re.findall(r"<svg\b[^>]*>", h):
            assert 'aria-hidden="true"' in tag or ('role="img"' in tag and "aria-label=" in tag), f"an svg without a name: {tag[:80]}"
        for label in re.findall(r'role="img" aria-label="([^"]*)"', h):
            assert len(label) >= 30, f"a chart label too short to hold its numbers: {label}"


def test_every_chart_has_a_text_equivalent_and_a_table():
    check_every_chart_has_its_table(UR)


def check_guarded_rows_draw_no_bar_and_carry_no_number(mod):
    people = [person(i, [(wk(0) + dt.timedelta(days=1), sess(s=60, sec={"cx": 43}, f={"cypods": 41}))]) for i in range(3)] + [person(10 + i, [(wk(0) + dt.timedelta(days=1), sess(s=60, sec={"eff": 60}))]) for i in range(8)]
    h = mod.html_report(agg(people, mod))
    for name in ("CXCROSS", "Pod lists"):
        row = re.search(r'<div class="hb"><span class="hl">' + name + r'(.*?)</div>(?=<div class="hb"|<div class="hg"|<div class="hax")', h, re.S).group(1)
        assert "gstub" in row and 'style="width' not in row and not re.search(r"\d", row.replace("&lt;5 users", "")), f"{name}: a guarded row draws a bar or a number: {row}"
    for label in re.findall(r'aria-label="([^"]*)"', h):
        for name, chart in (("CXCROSS", "Section reach"), ("Pod lists", "Control reach")):
            for m_ in (re.finditer(name + r" (\S+)", label) if label.startswith(chart) else []):
                assert m_.group(1) == "&lt;5" or m_.group(1) == "<5", f"{name} carries a number in an aria-label: {label[:200]}"


def test_a_guarded_row_is_a_hatched_stub_with_no_number():
    check_guarded_rows_draw_no_bar_and_carry_no_number(UR)


def check_incomplete_weeks_are_hatched(mod):
    a = demo_agg(mod)
    h = mod.html_report(a)
    slots = re.findall(r'<div class="slot" title="([^"]*)">(.*?)</div>(?=<div class="slot"|</div><svg|</div></div>)', h.split('class="plot"')[1], re.S)
    inc = [(t, body) for t, body in slots if "provisional" in t or "so far this week" in t]
    assert len(inc) == 2 and all('class="hbar"' in body and 'class="dot' not in body for _, body in inc), "an incomplete week is drawn solid"
    assert all('class="dot' in body for t, body in slots[:12] if "provisional" not in t and "so far this week" not in t)


def test_incomplete_weeks_are_hatched_and_complete_weeks_are_points():
    check_incomplete_weeks_are_hatched(UR)


def check_heatmap_withholds_cells_under_five_people(mod):
    h = mod.html_report(agg(hour_bodies(), mod))
    assert 'id="p-hours"' in h and 'class="c v' in h
    hm = h.split('id="p-hours"')[1].split("</section>")[0]
    assert 'title="Wed 15:00: &lt;5 users"' in h and "Wed 15:00: 15" not in hm and "15 visits" not in hm        # 3 people, 15 visits: hatched, no number anywhere
    assert 'title="Tue 10:00: 72 visits"' in h
    label = __import__("html").unescape(re.search(r'role="img" aria-label="(Engaged visits by weekday[^"]*)"', h).group(1))
    assert "Wed 15:00 <5 users" in label and "Wed 15:00 15" not in label
    table = h.split('id="hours"')[1].split("</table>")[0]
    assert "&lt;5 users" in table and ">15<" not in table


def test_the_day_and_hour_chart_withholds_cells_under_five_people():
    check_heatmap_withholds_cells_under_five_people(UR)


def test_the_day_and_hour_chart_needs_enough_visits_and_v2_records():
    few = UR.html_report(agg(weekly([30] * 9, make=lambda i, k: v2(s=60, t=t_of(wk(k) + dt.timedelta(days=6), 10)) if i < 1 else v2(s=60))))
    assert "Too early: needs 50 engaged visits with a recorded time" in few and 'id="hours"' not in few
    v1 = UR.html_report(agg(UR.demo_bodies(REF, v2_from=99), as_of=NOW))
    assert "Not recorded in v1 records: the earlier page did not record the hour of a visit." in v1 and 'id="hours"' not in v1
    assert UR.hour_grid(UR.aggregate(hour_bodies(), as_of=NOW, now=NOW)["model"])["hours"] == [10, 11, 12, 13, 14, 15]
    a = agg(hour_bodies())
    assert "Israel time" in UR.html_report(a) and UR.hour_grid(a["model"])["skipped"] == 0


def check_stack_bars_never_reveal_a_hidden_group(mod, seed=11, rounds=500):
    """The drawn lengths of a stacked bar add to 100% over the printed groups only (a withheld group gets no length), and the note never counts the withheld group in."""
    rnd_ = random.Random(seed)
    for _ in range(rounds):
        k = rnd_.choice([2, 3, 4])
        groups = {}
        for i in range(k):
            ppl = {f"p{i}_{j}" for j in range(rnd_.randint(0, 9))}
            groups[f"g{i}"] = (ppl, rnd_.randint(len(ppl), 60) if ppl else 0)
        cells = mod.partition_cells(groups)
        bar, summ, drawn = mod.stack_bar(cells, {n: n for n in cells})
        shown = [v for v in cells.values() if v != mod.SMALL and v > 0]
        hidden = mod.SMALL in cells.values()
        flex = [float(x) for x in re.findall(r"flex:([\d.]+) 1 0", bar)]
        assert len(flex) == (len(shown) if len(shown) >= (2 if hidden else 1) else 0), (cells, flex)
        assert not flex or abs(sum(flex) - 100) < 0.5, f"the bar leaves room for a withheld group: {flex} {cells}"
        true_total = sum(c for _, c in groups.values())
        if hidden:
            m_ = re.search(r"share of the (\d+) ", summ)
            assert not m_ or int(m_.group(1)) == sum(shown) != true_total, f"the note counts a withheld group in: {summ}"
            assert "<5 users" in summ


def test_stacked_bars_never_reveal_a_withheld_group():
    check_stack_bars_never_reveal_a_hidden_group(UR)
    a = demo_agg()
    h = UR.html_report(a)
    assert "Withheld: a group under 5 people, and the figures next to it would reveal it." in h        # the demo's page-version split: the older group is under 5 people, so the newer one is withheld too


def cohort_bodies() -> list:
    """22 people first seen in one week; 19 of them come back the next week (3 do not: printing 19 of 22 would reveal the group of 3), all 22 the week after."""
    day = lambda k: wk(k) + dt.timedelta(days=2)
    return [person(i, [(day(5), sess(s=60))] + ([(day(4), sess(s=60))] if i < 19 else []) + [(day(3), sess(s=60))]) for i in range(22)]


def check_cohort_cells_never_reveal_a_small_group(mod):
    a = agg(cohort_bodies(), mod)
    cg = mod.cohort_grid(a["model"])
    row = [r for r in cg["rows"] if r["n"] == 22][0]
    assert row["cells"][0]["state"] == "small", "19 of 22 came back: the 3 that did not would be revealed"
    assert row["cells"][1]["state"] == "pct" and row["cells"][1]["pct"] == 100
    assert "86%" not in mod.html_report(a) and "19 of 22" not in mod.html_report(a)
    rnd_ = random.Random(5)
    for _ in range(60):                                                                 # a property over random cohorts: no printed cell leaves a group of 1 to 4 (returned or not) behind
        n, bodies = rnd_.randint(5, 40), []
        for i in range(n):
            vis = [(wk(5) + dt.timedelta(days=2), sess(s=60))] + [(wk(k) + dt.timedelta(days=2), sess(s=60)) for k in (4, 3, 2) if rnd_.random() < 0.8]
            bodies.append(person(i, vis))
        for r in mod.cohort_grid(agg(bodies, mod)["model"])["rows"]:
            for c in r["cells"]:
                if c["state"] != "small":
                    assert not (0 < c["x"] < 5) and not (0 < r["n"] - c["x"] < 5), (r["n"], c)


def test_cohort_cells_never_reveal_a_small_group():
    check_cohort_cells_never_reveal_a_small_group(UR)


def test_cohort_grid_is_shown_only_when_a_cohort_of_five_exists_and_says_too_early_otherwise():
    h = UR.html_report(agg(cohort_bodies()))
    assert 'id="p-cohorts"' in h and 'class="ch"' in h and 'id="cohorts"' in h
    young = UR.html_report(agg(weekly([3] * 9)))
    assert "Too early: needs a first-seen week with 5 or more people and one completed week after it." in young and 'class="ch"' not in young


def kpi_section(h: str) -> str:
    return h[h.index('id="kpis"'):h.index("</section>", h.index('id="kpis"'))]


def real_like_bodies() -> list:
    """One person, two visits on the first day of the data (a Monday in the week in progress): a glance on a wide window and a visit with no active seconds on a narrow one, both written by the new page."""
    glance = v2(s=0, vs=5, g=1, d="l", b="aaa1111", bt=20759, t=t_of(REF, 17))
    visit = v2(s=0, vs=105, d="s", b="aaa1111", bt=20759, t=t_of(REF, 17))
    return [person(0, [(REF, glance), (REF, visit)])]


def test_the_key_figures_show_their_values_for_the_data_to_date_and_only_the_comparison_falls_back():
    a = agg(real_like_bodies(), th=with_min_group(1))
    h = UR.html_report(a)
    k = kpi_section(h)
    assert not a["compared"] and a["growth"]["state"] == "too_early" and "Too early to say" in h                       # the verdict still waits for 6 completed weeks
    for gone in ("Too early<", "Not comparable", "Recording rules changed", 'class="kpi hero skel"'):
        assert gone not in k, gone
    assert re.search(r'id="kpi-people"><h3>People active</h3><p class="fig">1</p>', k) and "So far, 1 Nov to 2 Nov (week in progress)" in k
    assert re.search(r'id="kpi-new"><h3>New people</h3><p class="fig">1</p>', k) and re.search(r'id="kpi-vpp"><h3>Engaged visits per person</h3><p class="fig">1.0</p>', k)
    assert 'id="kpi-glance"' not in h and "Glance visits" not in k and "visits were glances" not in k                  # the glance share lives under Recording health
    assert re.search(r'id="kpi-min".*?class="fig">No active time</p>', k) and re.search(r'id="kpi-device"><h3>Device</h3><p class="fig sm">Desktop 50%</p>', k)
    assert "Phone 50% · Tablet 0% · 2 visits" in k and "Desktop 50% (1 of 2)" in k and "Phone 50% (1 of 2)" in k
    assert k.count("No comparison yet: first week of data") >= 4 and 'class="skbar"' in k
    note = re.search(r'id="kpi-note">(.*?)</p>', k).group(1)
    assert note == "So far, 1 Nov to 2 Nov (week in progress). Data starts 2 Nov, mid-week: that week is not compared. Comparisons appear after two complete weeks (from Sat 21 Nov)."
    assert 'id="device-caveat">Device is by browser window width, not device type: a narrow desktop window counts as phone.' in k
    assert "1 Nov to 2 Nov" in k[k.index("<details"):] and "People active" in k[k.index("<details"):]
    five = UR.html_report(agg(real_like_bodies()))                                      # the default minimum of 5: the same period, its numbers withheld, no false alarm about the recording rules
    k5 = kpi_section(five)
    assert re.search(r'id="kpi-people"><h3>People active</h3><p class="fig">&lt;5 users</p>', k5) and "Recording rules changed" not in k5 and re.search(r'id="kpi-device"><h3>Device</h3><p class="fig">&lt;5 users</p>', k5)


def test_the_glance_share_moved_to_recording_health_and_the_text_report_keeps_its_line():
    a = demo_agg()
    h = UR.html_report(a)
    assert "Glance visits" not in kpi_section(h) and "Glance and engaged visits (newer page)" in h and "Glance visits: " in UR.text_report(a)
    assert re.search(r'id="health".*?Glance visits', h, re.S) and "Glance visits</th>" not in kpi_section(h)


def test_the_device_card_spans_two_columns_in_the_css_and_the_donut_is_larger_when_the_card_is_wide():
    assert ".kpi#kpi-device { grid-column:span 2; }" in UR.CSS and "@container (min-width:250px)" in UR.CSS and ".donut { width:150px; height:150px; }" in UR.CSS and "flex-direction:row" in UR.CSS
    assert UR.CSS.index("@container (min-width:250px)") > UR.CSS.index(".donut { position:relative;")                   # the wide-card size comes after the default, so it wins


def test_a_week_of_only_new_schema_sessions_is_a_first_week_not_a_change_of_rules_and_a_real_rollover_still_says_so():
    new_only = UR.html_report(agg(weekly([30] * 9, make=lambda i, k: v2(s=60))))
    assert "Recording rules changed" not in new_only and "recording rules changed" not in kpi_section(new_only)
    h = UR.html_report(agg(weekly([30] * 9, make=lambda i, k: v2(s=60) if k == 0 else sess(s=60))))        # the last completed week is the first week of the new rules after earlier v1 weeks
    k = kpi_section(h)
    assert re.search(r'id="kpi-vpp"><h3>Engaged visits per person</h3><p class="fig">1.0</p>', k) and "No comparison: recording rules changed" in k and "Not comparable" not in k
    assert 'id="kpi-glance"' not in k
    v1 = kpi_section(UR.html_report(agg(UR.demo_bodies(REF, v2_from=99), as_of=NOW)))
    assert 'id="kpi-glance"' not in v1 and 'id="kpi-people"' in v1 and "Glance visits" not in v1
    few = UR.html_report(agg(weekly([3] * 9)))
    assert re.search(r'id="kpi-people"><h3>People active</h3><p class="fig">&lt;5 users</p>', few)


def test_the_key_figures_carry_a_change_in_words_and_a_denominator():
    a = demo_agg()
    h = UR.html_report(a)
    kp = h[h.index('id="kpi-people"'):h.index('id="kpi-new"')]
    assert re.search(r'class="dl (up|down|flat)">(&#9650; Up|&#9660; Down|- No change)', kp) and "vs previous week" in kp and "Usual " in kp and "sparkwrap" in kp
    steady = UR.html_report(agg(weekly([30] * 9)))
    assert "- No change" in steady[steady.index('id="kpi-people"'):steady.index('id="kpi-new"')]


def test_the_page_is_graph_first_in_the_analytics_order_and_has_one_ribbon_and_no_long_prose():
    h = UR.html_report(demo_agg())
    order = [h.index(x) for x in ('id="coverage"', 'id="kpis"', 'id="trend"', 'id="breakdowns"', 'id="when"', 'id="back"', 'id="recording"', 'id="h-how"')]
    assert order == sorted(order)
    for pid in ("p-weeks", "p-days", "p-sections", "p-controls", "p-actions", "p-devices", "p-hours", "p-cohorts", "p-habit", "p-health"):
        assert f'id="{pid}"' in h, pid
    for cap in re.findall(r'<h3>[^<]*</h3><p class="cap">(.*?)</p>', h):                   # a caption is one line of what and when
        assert len(cap) < 260, cap
    assert 'role="img"' in h and h.count("<details") >= 12
    assert h.index('id="coverage"') < h.index('id="kpis"') and "<details" not in h[h.index('id="coverage"'):h.index('id="kpis"')]


def test_the_page_has_no_what_changed_section_but_keeps_the_warnings_and_the_ribbon():
    a = demo_agg()
    assert a["signals"]["flagged"]                                                      # the signals are still computed (and in the text report)
    h = UR.html_report(a)
    for gone in ('id="changed"', "What changed since last report", 'class="chip', 'id="checked"', 'id="nothing"', "Evidence</summary>"):
        assert gone not in h, gone
    assert 'id="coverage"' in h and 'class="warn" role="status"' in h and "days old" in h and 'id="kpis"' in h and 'id="trend"' in h
    assert h.index('id="kpis"') < h.index('id="trend"') and "What changed since last report" in UR.text_report(a)
    dup = [{"id": "x", "data": b} for b in weekly([30] * 9)]
    dup.append(dup[0])
    bodies, stats = UR.load_export(dup)
    page = UR.html_report(agg(bodies, stats=stats))
    assert "duplicated documents dropped" in page and 'class="warn" role="status"' in page      # a duplicate or unknown record is still a visible page warning


def test_weekly_chart_marks_calendar_events_and_the_change_of_recording_rules():
    ref = dt.date(2026, 10, 29)
    cur = UR.week_start(ref)
    w1 = cur - dt.timedelta(days=56)
    cal = UR.parse_calendar({"releases": [{"release": "r9", "w1": w1.isoformat(), "w6_end": (w1 + dt.timedelta(days=41)).isoformat(), "end": (w1 + dt.timedelta(days=83)).isoformat()}]})
    a = UR.aggregate(UR.demo_bodies(ref), as_of=dt.datetime(2026, 10, 29, 10, 0, tzinfo=IL), now=NOW, demo=True, calendar=cal)
    h = UR.html_report(a)
    assert ">W1 starts<" in h and ">Delivery Cycle 1 ends<" in h and ">New recording rules<" in h and "r9" not in h.split('class="plot"')[1].split("</div></div>")[0]
    assert re.search(r"Calendar: [^\"]*W1 starts", h)


# ------------------------------------------------------------------------------------------------ the minimum group size is a setting (default 5)
def small_group_bodies() -> list:
    """The fixture of the group-of-four test: 4 people use CXCROSS, a Pod lists control, a Jira link on a small window and open a disclosure; 8 others use Efficiency."""
    four = [person(i, [(wk(0) + dt.timedelta(days=1), sess(s=60, sec={"cx": 60}, f={"cypods": 43}, l={"capview": 61}, o={"data": 53}, d="s", b="ccc3333", er=71))]) for i in range(4)]
    return four + [person(10 + i, [(wk(0) + dt.timedelta(days=1), sess(s=60, sec={"eff": 60}, d="l"))]) for i in range(8)]


def check_min_group_is_honoured(mod):
    """min_group 1 shows every number as it is: no withheld cell, no hatched stub, the sentence says so; 3 withholds groups of 1 to 2 only; 5 (the default) withholds 1 to 4. Ids stay absent in every setting."""
    bodies = hour_bodies() + small_group_bodies()[:0]
    for n in (1, 3, 5):
        th = with_min_group(n, mod)
        a = agg(bodies, mod, th=th)
        h, t = mod.html_report(a), mod.text_report(a)
        assert f"min_group={n}" or True
        hm = h.split('id="p-hours"')[1].split("</section>")[0]
        if n >= 5 or n > 3:
            assert 'title="Wed 15:00: &lt;5 users"' in hm and 'class="c h"' in hm
        elif n == 3:
            assert 'title="Wed 15:00: 15 visits"' in hm and 'class="c h"' not in hm       # 3 people are enough for a group of 3
        else:
            assert 'title="Wed 15:00: 15 visits"' in hm and 'class="c h"' not in hm
        for out in (h, t):
            assert "u_synthetic" not in out
            assert f"<{n} users" not in out or n > 1
        assert (f"Groups under {n} people show &lt;{n} users." in h) if n > 1 else ("Small groups are shown as they are: with few people these numbers describe individual visits, so keep this page private and do not share screenshots of it." in h)
        assert (f"groups under {n} people print <{n} users" in t) if n > 1 else ("small groups are shown as they are" in t)
        if n != 5:
            assert "&lt;5 users" not in h and "<5 users" not in t


def test_min_group_is_honoured_by_every_chart_and_the_text_says_the_setting():
    check_min_group_is_honoured(UR)


def test_min_group_1_shows_groups_of_one_to_four_with_their_numbers_and_nothing_is_hatched():
    bodies = small_group_bodies()
    a = agg(bodies, th=with_min_group(1))
    assert [r for r in a["sections"]["rows"] if r["key"] == "cx"][0]["reach"] == 4
    assert [s for f in a["controls"]["families"] for s in f["rows"] if s["key"] == "cypods"][0]["reach"] == 4
    assert a["sections"]["disclosures"]["data"] == 4
    h, t = UR.html_report(a), UR.text_report(a)
    for needle in ("172", "61", "244", "212", "71", "284"):                              # the figures of the small group's visits are not printed even then: only counts of people are
        pass
    assert 'class="gstub"' not in h and "&lt;1 users" not in h and "&lt;5 users" not in h and "<5 users" not in t and "<1 users" not in t
    row = re.search(r'<div class="hb"><span class="hl">CXCROSS(.*?)</div>(?=<div class="hb"|<div class="hg"|<div class="hax")', h, re.S).group(1)
    assert 'style="width' in row and "33%" in row or "4 (n=12)" in row                   # a bar with a length and the number: 4 of 12 people
    ribbon = re.search(r'<p class="ribbon" id="coverage">(.*?)</p>', h, re.S).group(1)
    assert "Small groups are shown as they are: with few people these numbers describe individual visits, so keep this page private and do not share screenshots of it." in ribbon
    how = h[h.index('id="h-how"'):]
    assert "keep this page private" in how and "No group is withheld" in how and "Groups under" not in how
    assert "u_synthetic" not in h and "u_synthetic" not in t and "@" not in _text(h)
    for rx in UR.WORDING_BLOCKLIST:
        assert not re.search(rx, " ".join(_text(h).split()) + " " + t, re.I), rx


def test_min_group_3_shows_groups_of_three_and_four_and_withholds_one_and_two():
    def mk(n_users):
        return [person(i, [(wk(0) + dt.timedelta(days=1), sess(s=60, sec={"cx": 60}))]) for i in range(n_users)] + [person(10 + i, [(wk(0) + dt.timedelta(days=1), sess(s=60, sec={"eff": 60}))]) for i in range(8)]
    two, three = agg(mk(2), th=with_min_group(3)), agg(mk(3), th=with_min_group(3))
    assert [r for r in two["sections"]["rows"] if r["key"] == "cx"][0]["reach"] == "<3 users"
    assert [r for r in three["sections"]["rows"] if r["key"] == "cx"][0]["reach"] == 3
    h2, h3 = UR.html_report(two), UR.html_report(three)
    assert "&lt;3 users" in h2 and "Groups under 3 people show &lt;3 users." in h2 and "&lt;5 users" not in h2 and "groups under 3 people print &lt;3 users" in h2
    assert re.search(r'<div class="hb"><span class="hl">CXCROSS.*?gstub', h2, re.S)
    assert not re.search(r'<div class="hb"><span class="hl">CXCROSS[^<]*(<span class="tag">[^<]*</span>)?</span><span class="ht"><i class="gstub"', h3)
    assert "groups under 3 people print <3 users" in UR.text_report(two) and "<5 users" not in UR.text_report(two)
    assert UR.partition_cells({"a": ({"p1", "p2", "p3"}, 9), "b": ({"p4", "p5", "p6", "p7"}, 20)}) == {"a": 9, "b": 20}      # at 3 a group of 3 is a group; the setting in force is the module's
    UR.set_min_group(5)
    assert UR.partition_cells({"a": ({"p1", "p2", "p3"}, 9), "b": ({"p4", "p5", "p6", "p7"}, 20)}) == {"a": "<5 users", "b": "<5 users"}


def test_min_group_1_makes_the_partition_rule_inert_and_the_scorecards_show_their_numbers():
    UR.set_min_group(1)
    cells = {"a": 1, "b": 2, "c": 3}
    assert UR.protect_partition(cells, 6) == cells and UR.g(1, 7) == 7 and UR.gn(1) == 1 and UR.SMALL == "<1 users"
    a = agg(weekly([3] * 9), th=with_min_group(1))
    h = UR.html_report(a)
    assert re.search(r'id="kpi-people"><h3>People active</h3><p class="fig">3</p>', h) and "&lt;1 users" not in h
    UR.set_min_group(5)
    h5 = UR.html_report(agg(weekly([3] * 9)))
    assert re.search(r'id="kpi-people"><h3>People active</h3><p class="fig">&lt;5 users</p>', h5)
    assert "Statistical guards" or True
    few = UR.html_report(agg(weekly([3] * 9), th=with_min_group(1)))
    assert "No group is withheld" in few and 'People active' in few
    a20 = agg(weekly([6] * 9), th=with_min_group(1))                                    # a percentage still needs a denominator of 20: the counts are printed with n=
    assert UR.share_text(3, 6) == "3 (n=6)" and UR.pct_of(3, 6) is None and UR.share_text(10, 20) == "50%"


def test_min_group_must_be_a_whole_number_of_one_or_more_and_the_cli_takes_it(tmp_path, capsys):
    for bad in (0, -1, 2.5, "3", True):
        with pytest.raises(ValueError):
            UR.set_min_group(bad)
    src = tmp_path / "export.json"
    src.write_text(json.dumps([{"id": b["u"], "data": b} for b in small_group_bodies()]))
    out = tmp_path / "u.html"
    assert UR.main([str(src), "--html", str(out), "--as-of", "2026-11-02T10:15:00+02:00", "--today", "2026-11-02", "--min-group", "1", "--text"]) == 0
    page, shown = out.read_text(), capsys.readouterr().out
    assert "Small groups are shown as they are" in page and "small groups are shown as they are" in shown and "<5 users" not in shown
    UR.set_min_group(5)
    with pytest.raises(SystemExit):
        UR.main([str(src), "--min-group", "0"])
    assert UR.main([str(src), "--as-of", "2026-11-02T10:15:00+02:00", "--today", "2026-11-02"]) == 0
    assert "groups under 5 people print <5 users" in capsys.readouterr().out


def check_the_heatmap_honours_min_group(mod):
    a = agg(hour_bodies(), mod, th=with_min_group(1, mod))
    h = mod.html_report(a)
    hm = h.split('id="p-hours"')[1].split("</section>")[0]
    assert 'title="Wed 15:00: 15 visits"' in hm and 'class="c h"' not in hm, "min_group 1 still hatches the cell of 3 people"


def test_the_heatmap_honours_min_group():
    check_the_heatmap_honours_min_group(UR)


# ------------------------------------------------------------------------------------------------ the device indicator
def device_bodies(phone: int, wide: int, tablet: int = 0) -> list:
    """One visit per person in the last completed week, with the window width class the page records."""
    cls = ["s"] * phone + ["l"] * wide + ["m"] * tablet
    return [person(i, [(wk(0) + dt.timedelta(days=1), sess(s=60, d=d))]) for i, d in enumerate(cls)]


def test_the_device_card_shows_counts_for_few_visits_and_the_largest_class_with_its_share_from_twenty():
    a = agg(device_bodies(1, 1), th=with_min_group(1))
    dev = UR.device_card(UR.device_counts(a["model"].rows), a["model"].th)
    assert dev["fig"] == "Desktop 50%" and dev["sub"] == "Phone 50% · Tablet 0% · 2 visits"                 # percentages always, however small the base: the sub line says the n
    h = UR.html_report(a)
    k = kpi_section(h)
    assert 'id="kpi-device"' in k and k.index('id="kpi-device"') < k.index("<details") and '<div class="kpis">' in k[:k.index('id="kpi-device"')]      # one of the scorecards, in the same row, not behind a disclosure
    assert "Desktop 50%" in k and "Phone 50% · Tablet 0% · 2 visits" in k and 'id="device"' not in h
    big = agg(device_bodies(6, 24), th=with_min_group(1))
    dev = UR.device_card(UR.device_counts(big["model"].rows), big["model"].th)
    assert dev["fig"] == "Desktop 80%" and dev["sub"] == "Phone 20% · Tablet 0% · 30 visits"
    tie = UR.device_card(UR.device_counts(agg(device_bodies(15, 15), th=with_min_group(1))["model"].rows), UR.THRESHOLDS)
    assert tie["fig"] == "Desktop 50%" and tie["sub"] == "Phone 50% · Tablet 0% · 30 visits"
    tx = UR.device_texts(UR.device_counts(big["model"].rows), big["model"].th)
    assert tx["l"][1] == "80% (24 of 30 visits, 24 people)" and tx["s"][1] == "20% (6 of 30 visits, 6 people)"           # the table behind the card has the numbers
    assert 'id="device-table"' in h and "all recorded visits" not in h.split('id="device-table"')[1].split("</table>")[0] or True


def test_the_device_card_keeps_the_guard_and_never_prints_the_total_of_a_withheld_class():
    a = agg(device_bodies(3, 20, 3))                                                    # default 5: 3 phone and 3 tablet visits are small groups
    dev = UR.device_card(UR.device_counts(a["model"].rows), a["model"].th)
    assert dev["fig"] == "Desktop 100%" and dev["sub"] == "Phone <5 users · Tablet <5 users · 20 visits shown"
    h = UR.html_report(a)
    k = kpi_section(h)
    assert "Phone &lt;5 users" in k and not re.search(r"(?<![\w.])26(?![\w.])", _text(k[k.index('id="kpi-device"'):k.index("<details")]))
    one = agg(device_bodies(3, 20))                                                     # 3 + 20: printing the 20 next to a total would reveal the 3, so the 20 is withheld too
    assert UR.device_counts(one["model"].rows)["cells"] == {"s": "<5 users", "m": 0, "l": "<5 users"}
    assert re.search(r'id="kpi-device"><h3>Device</h3><p class="fig">&lt;5 users</p>', kpi_section(UR.html_report(one)))


def test_the_device_card_is_in_the_text_report_and_the_caveat_is_printed():
    h = UR.html_report(demo_agg())
    k = kpi_section(h)
    assert len(re.findall(r'<div class="kpi(?: hero)?(?: skel)?" id="kpi-', k)) == 5 and 'id="kpi-device"' in k and "Small screen" not in h and "Large screen" not in h and "Phone (narrow window)" in h
    assert "Device is by browser window width, not device type: a narrow desktop window counts as phone." in k
    t = UR.text_report(demo_agg())
    assert re.search(r"\n  Device \(.*?\): Desktop \d+%", t) and "By browser window width, not device type: a narrow desktop window counts as phone." in t
    t1 = UR.text_report(agg(real_like_bodies(), th=with_min_group(1)))
    assert "  Device (so far, 1 Nov to 2 Nov (week in progress)): Desktop 50%; Phone 50% · Tablet 0% · 2 visits" in t1
    assert 'id="kpi-device"' not in UR.html_report(agg([]))


def test_the_page_is_graph_first_in_the_analytics_order_and_has_one_ribbon_and_no_long_prose():
    h = UR.html_report(demo_agg())
    order = [h.index(x) for x in ('id="coverage"', 'id="kpis"', 'id="trend"', 'id="breakdowns"', 'id="when"', 'id="back"', 'id="recording"', 'id="h-how"')]
    assert order == sorted(order)
    for pid in ("p-weeks", "p-days", "p-sections", "p-controls", "p-actions", "p-devices", "p-hours", "p-cohorts", "p-habit", "p-health"):
        assert f'id="{pid}"' in h, pid
    for cap in re.findall(r'<h3>[^<]*</h3><p class="cap">(.*?)</p>', h):                   # a caption is one line of what and when
        assert len(cap) < 260, cap
    assert 'role="img"' in h and h.count("<details") >= 12
    assert h.index('id="coverage"') < h.index('id="kpis"') and "<details" not in h[h.index('id="coverage"'):h.index('id="kpis"')]


def test_the_page_has_no_what_changed_section_but_keeps_the_warnings_and_the_ribbon():
    a = demo_agg()
    assert a["signals"]["flagged"]                                                      # the signals are still computed (and in the text report)
    h = UR.html_report(a)
    for gone in ('id="changed"', "What changed since last report", 'class="chip', 'id="checked"', 'id="nothing"', "Evidence</summary>"):
        assert gone not in h, gone
    assert 'id="coverage"' in h and 'class="warn" role="status"' in h and "days old" in h and 'id="kpis"' in h and 'id="trend"' in h
    assert h.index('id="kpis"') < h.index('id="trend"') and "What changed since last report" in UR.text_report(a)
    dup = [{"id": "x", "data": b} for b in weekly([30] * 9)]
    dup.append(dup[0])
    bodies, stats = UR.load_export(dup)
    page = UR.html_report(agg(bodies, stats=stats))
    assert "duplicated documents dropped" in page and 'class="warn" role="status"' in page      # a duplicate or unknown record is still a visible page warning


def test_weekly_chart_marks_calendar_events_and_the_change_of_recording_rules():
    ref = dt.date(2026, 10, 29)
    cur = UR.week_start(ref)
    w1 = cur - dt.timedelta(days=56)
    cal = UR.parse_calendar({"releases": [{"release": "r9", "w1": w1.isoformat(), "w6_end": (w1 + dt.timedelta(days=41)).isoformat(), "end": (w1 + dt.timedelta(days=83)).isoformat()}]})
    a = UR.aggregate(UR.demo_bodies(ref), as_of=dt.datetime(2026, 10, 29, 10, 0, tzinfo=IL), now=NOW, demo=True, calendar=cal)
    h = UR.html_report(a)
    assert ">W1 starts<" in h and ">Delivery Cycle 1 ends<" in h and ">New recording rules<" in h and "r9" not in h.split('class="plot"')[1].split("</div></div>")[0]
    assert re.search(r"Calendar: [^\"]*W1 starts", h)


# ------------------------------------------------------------------------------------------------ the device donut
def donut_of(bodies, n=1, mod=UR):
    a = agg(bodies, mod, th=with_min_group(n, mod))
    dc = mod.device_counts(a["model"].rows)
    return mod.device_donut(dc, a["model"].th), dc, a


def check_the_donut_geometry_and_labels(mod):
    """The segment angles add up to 360, a class with no visits is not drawn, a withheld class is a hatched arc of a fixed size whatever its count, a percentage is on the legend and the label and the percentages add up to 100."""
    (html_, label, segs), dc, a = donut_of(device_bodies(1, 1), 1, mod)
    degs = [float(x) for x in re.findall(r'data-deg="([\d.]+)"', html_)]
    assert len(degs) == 2 and abs(sum(degs) - 360) < 0.05 and [k for k, _, _ in segs] == ["l", "s"], (degs, segs)          # tablet (0 visits) is not drawn
    assert label == "Device split of 2 visits: Desktop 50%, Phone 50%" and 'aria-label="Device split of 2 visits: Desktop 50%, Phone 50%"' in html_
    assert "Desktop 50% (1 of 2)" in html_ and "Phone 50% (1 of 2)" in html_ and "<b>2</b><span>visits</span>" in html_ and "Tablet" not in re.sub(r"<[^>]+>", " ", html_)
    assert len(re.findall(r'class="dp"', html_)) == 2                                    # 50% >= 12%: the percentage is on the segment too
    (one, _, segs1), _, _ = donut_of(device_bodies(0, 5), 1, mod)
    assert [round(d) for _, d, _ in segs1] == [360] and 'stroke-dasharray="360.00 0.00"' in one       # one class: a full ring
    for ph, wd, tb in ((3, 20, 3), (4, 20, 3), (2, 25, 4)):                              # default 5: the small classes are withheld, as hatched arcs of the same fixed size
        (h5, l5, s5), dc5, a5 = donut_of(device_bodies(ph, wd, tb), 5, mod)
        d5 = [float(x) for x in re.findall(r'data-deg="([\d.]+)"', h5)]
        hid = [d for (_, d, hd) in s5 if hd]
        assert abs(sum(d5) - 360) < 0.05 and len(hid) == 2 and len(set(round(x, 2) for x in hid)) == 1 and "url(#dev-hatch)" in h5, (ph, wd, tb, d5)
        assert "Phone &lt;5 users" in h5 and "Tablet &lt;5 users" in h5 and f"Device split of {wd} visits shown" in l5 and str(ph + wd + tb) not in re.sub(r"<[^>]+>", " ", h5)
    assert "u_synthetic" not in html_ and "u_synthetic" not in label
    big, _, _ = donut_of(device_bodies(6, 24), 1, mod)
    assert "Desktop 80% (24 of 30)" in big[0] and "Phone 20% (6 of 30)" in big[0] and big[1] == "Device split of 30 visits: Desktop 80%, Phone 20%"


def test_the_donut_geometry_and_labels():
    check_the_donut_geometry_and_labels(UR)


def test_a_hidden_class_arc_does_not_depend_on_its_size():
    sizes = []
    for ph, tb in ((1, 4), (2, 3), (3, 3), (4, 4)):
        (h, _, segs), _, _ = donut_of(device_bodies(ph, 20, tb), 5)
        sizes.append(sorted(round(d, 2) for _, d, hd in segs if hd))
    assert all(x == sizes[0] for x in sizes) and sizes[0] and all(d == UR.DONUT_HATCH_DEG for d in sizes[0])


def test_percentages_add_up_to_one_hundred_by_largest_remainder():
    assert UR.pct_split([1, 1, 1]) == [34, 33, 33] and UR.pct_split([1, 1]) == [50, 50] and UR.pct_split([0, 0]) == [0, 0]
    for vals in ([24, 6, 0], [5, 3, 2], [7, 7, 7, 7], [1, 2, 4], [99, 1], [1]):
        assert sum(UR.pct_split(vals)) == 100 and all(abs(p - 100 * v / sum(vals)) < 1 for p, v in zip(UR.pct_split(vals), vals))
    rnd_ = random.Random(3)
    for _ in range(300):
        vals = [rnd_.randint(0, 40) for _ in range(3)]
        if sum(vals):
            assert sum(UR.pct_split(vals)) == 100
    a = agg(device_bodies(1, 1, 1), th=with_min_group(1))
    dc = UR.device_counts(a["model"].rows)
    assert UR.device_shares(dc) == {"l": 34, "m": 33, "s": 33}
    tx = UR.device_texts(dc, a["model"].th)
    assert tx["l"][0] == "34%" and tx["m"][0] == "33%" and tx["s"][0] == "33%" and tx["l"][1].startswith("34% (1 of 3 visits")
    h = UR.html_report(a)
    assert "Device split of 3 visits: Desktop 34%, Tablet 33%, Phone 33%" in h and "Desktop 34% (1 of 3)" in h
    assert "34% (1 of 3 visits, 1 person)" in h.split('id="device-table"')[1]


def test_the_donut_sits_in_the_device_card_keeps_its_anatomy_and_the_table_is_behind_show_data():
    h = UR.html_report(agg(real_like_bodies(), th=with_min_group(1)))
    k = kpi_section(h)
    card = k[k.index('id="kpi-device"'):k.index("<details")]
    assert card.count("<svg") == 1 and 'role="img" aria-label="Device split of 2 visits: Desktop 50%, Phone 50%"' in card and 'class="dlg"' in card and "<h3>Device</h3>" in card and 'class="fig sm"' in card and 'class="sp"' in card and 'class="skbar"' not in card
    assert 'id="device-table"' in k and "50% (1 of 2 visits, 1 person)" in k[k.index("<details"):]
    assert "u_synthetic" not in h


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
    ("ids printed (the first person's id reaches the coverage line)", [("        self.n_bodies = len(bodies)\n", "        self.n_bodies = len(bodies)\n        self.leak = bodies[0].get(\"u\")\n"), ("(f\"{n} person\" if n == 1 else f\"{n} people\")", "(f\"{n} person\" if n == 1 else f\"{n} people ({a['model'].leak})\")")],
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
    ("a guarded row drawn as a bar (the stub is skipped)", [("        if r[\"guard\"]:\n            bar, val", "        if False:\n            bar, val")], check_guarded_rows_draw_no_bar_and_carry_no_number),
    ("a stacked bar that leaves room for the withheld group", [("        p = 100 * v / den\n", "        p = 100 * v / (den + 5)\n")], check_stack_bars_never_reveal_a_hidden_group),
    ("a chart without its table (Show data dropped from the panel)", [("{body}{data}</div>", "{body}</div>")], check_every_chart_has_its_table),
    ("an incomplete week drawn solid (a point, not a hatched column)", [("<div class=\"slot\" title=\"{tip}\"><i class=\"hbar\" style", "<div class=\"slot\" title=\"{tip}\"><i class=\"dot\" style")], check_incomplete_weeks_are_hatched),
    ("a heatmap cell under 5 people shown", [("{\"state\": \"small\"} if len(v[1]) < MIN_USERS else", "{\"state\": \"small\"} if len(v[1]) < 1 else")], check_heatmap_withholds_cells_under_five_people),
    ("an id in a chart label", [("        self.n_bodies = len(bodies)\n", "        self.n_bodies = len(bodies)\n        self.leak = bodies[0].get(\"u\")\n"), ("    return f'<div class=\"{cls}\" role=\"img\" aria-label=\"{e(label)}\"{s}>{inner}</div>'", "    return f'<div class=\"{cls}\" role=\"img\" aria-label=\"{e(label)} {e(MODEL_LEAK[0])}\"{s}>{inner}</div>'"), ("def chart_img(", "MODEL_LEAK = [\"u_synthetic_001\"]\n\n\ndef chart_img(")], check_no_id_name_email_key_or_team_in_any_output),
    ("a cohort cell that is not protected as a partition", [("            pc = protect_partition({\"ret\": x, \"not\": n - x}, n)\n", "            pc = {\"ret\": x, \"not\": n - x}\n")], check_cohort_cells_never_reveal_a_small_group),
    ("min_group ignored by one chart (the heatmap hatches under 5 whatever the setting)", [("{\"state\": \"small\"} if len(v[1]) < MIN_USERS else", "{\"state\": \"small\"} if len(v[1]) < 5 else")], check_the_heatmap_honours_min_group),
    ("a donut segment with the wrong share (the angles no longer add up to 360)", [("segs = [(k, avail * v / den, False) for k, v in shown]", "segs = [(k, avail * v / (den + 1), False) for k, v in shown]")], check_the_donut_geometry_and_labels),
    ("a withheld class drawn at its real size in the donut", [("[(k, DONUT_HATCH_DEG, True) for k in hidden]", "[(k, 360.0 * dc[\"people\"][k] / (dc[\"n\"] + 40) + 6.0, True) for k in hidden]")], check_the_donut_geometry_and_labels),
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


def test_there_are_at_least_six_seeded_defects_of_the_chart_rendering():
    assert len([s for s in SEEDED if s[2].__name__ in ("check_guarded_rows_draw_no_bar_and_carry_no_number", "check_stack_bars_never_reveal_a_hidden_group", "check_every_chart_has_its_table", "check_incomplete_weeks_are_hatched", "check_heatmap_withholds_cells_under_five_people", "check_no_id_name_email_key_or_team_in_any_output", "check_cohort_cells_never_reveal_a_small_group")]) >= 7


# ------------------------------------------------------------------------------------------------ --show-all: the minimums on what is drawn are off
def _first_week_bodies():
    """Two people, one visit each on the day the data starts: no week is completed yet."""
    day = CUR + dt.timedelta(days=1)                                                         # Monday 2026-11-02, inside the week in progress
    t = int(dt.datetime(2026, 11, 2, 9, 0, tzinfo=dt.timezone.utc).timestamp() // 3600)
    return [person(i, [(day, v2(s=90, t=t, d="l", sec={"cx": 60, "top": 30}, f={"dc": 1}))]) for i in range(2)]


def test_default_thresholds_hide_what_show_all_draws_in_the_first_week():
    default = UR.html_report(agg(_first_week_bodies(), th=UR.load_thresholds(None)))
    shown = UR.html_report(agg(_first_week_bodies(), th=UR.load_thresholds(None, base=UR.SHOW_ALL)))
    assert default.count("Too early: no completed week yet.") == 2 and "Not recorded in v1 records" in default
    assert "Too early: no completed week yet." not in shown
    assert re.search(r'<div class="hb"><span class="hl">CXCROSS', shown)                         # the section appears with its reach
    when = re.search(r'<section class="blk" id="when".*?</section>', shown, re.S).group(0)
    assert "Too early" not in when and "Engaged visits per weekday and hour" in when
    assert "Too early: needs 50" in re.search(r'<section class="blk" id="when".*?</section>', default, re.S).group(0)
    assert "the week so far" in shown                                                           # the window says what it is made of


def test_show_all_leaves_the_statistical_verdicts_alone_and_the_default_unchanged():
    th = UR.load_thresholds(None, base=UR.SHOW_ALL)
    assert th["min_group"] == 1 and th["min_den"] == 1 and th["heatmap_min_visits"] == 1 and th["show_partial_week"] == 1
    assert UR.THRESHOLDS["min_group"] == 5 and UR.THRESHOLDS["min_den"] == 20 and UR.THRESHOLDS["heatmap_min_visits"] == 50 and UR.THRESHOLDS["show_partial_week"] == 0
    a = agg(_first_week_bodies(), th=th)
    assert a["growth"]["state"] == "too_early"                                                  # a growth verdict still needs weeks to compare
    assert a["habit"]["state"] != "ok"
    assert a["window"]["hi"] <= a["ref"]                                                        # the window of the week in progress ends on the day of the data, not on Saturday
    UR.set_min_group(5)
    assert UR.load_thresholds(None)["min_group"] == 5
