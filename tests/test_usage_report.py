"""program_dashboard/usage_report.py: the owner's aggregate report and the "Delivery Pulse Usage" page. Synthetic data only: users are u_synthetic_001 ..., nothing here is a real id, person, team or issue."""
import datetime as dt
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "program_dashboard"))
import usage_report as UR                                                           # noqa: E402

TEMPLATE = (ROOT / "program_dashboard" / "dashboard.template.html").read_text(encoding="utf-8")
TODAY = dt.date(2026, 11, 2)                                                        # a Monday
A, B = "2026-11-02", "2026-10-26"                                                   # today; 7 days before the start of the last-7-days window
WK = lambda d: UR.iso_week_key(dt.date.fromisoformat(d))


def body(i: int, sessions: dict) -> dict:
    """sessions: {day: [session, ...]}; one body per person, ids synthetic."""
    w: dict = {}
    for day, ss in sessions.items():
        for k, s in enumerate(ss):
            w.setdefault(WK(day), {}).setdefault(day, {})[f"s{i}x{k:06d}"[:8]] = s
    return {"u": f"u_synthetic_{i + 1:03d}", "v": 1, "first": min(sessions), "last": max(sessions), "w": w}


def fixture() -> list[dict]:
    """6 people. Today: persons 0-4 read Delivery and Needs Attention for 10 minutes, change Release twice and open How this is calculated; person 0 also follows 7 Jira links in Quality.
    A week earlier: all 6 people for 2 minutes in Efficiency; person 5 on a medium screen, a newer page version, and 2 page errors."""
    out = []
    for i in range(6):
        days = {B: [{"t": 50 + i, "s": 120, "sec": {"eff": 120}, "d": "m" if i == 5 else "l", "b": "bbb2222" if i == 5 else "aaa1111", **({"er": 2} if i == 5 else {})}]}
        if i < 5:
            s = {"t": 100 + i, "s": 600, "sec": {"burnup": 300, "attn": 300}, "d": "l", "b": "aaa1111", "f": {"release": 2}, "o": {"how": 1}}
            if i == 0:
                s["l"] = {"bugs": 7}
            days[A] = [s]
        out.append(body(i, days))
    return out


def _text(h: str) -> str:
    """The words of a page: no style block, no tags; attribute values (aria-label, title) are kept in because a screen reader reads them."""
    return re.sub(r"<[^>]+>", " ", re.sub(r"<style>.*?</style>", " ", h, flags=re.S)) + " " + " ".join(re.findall(r'(?:aria-label|title)="([^"]*)"', h))


# ------------------------------------------------------------------------------------------------ loading
def test_loader_accepts_bodies_rows_and_a_wrapper():
    bodies = fixture()
    assert UR.load_bodies(bodies) == bodies
    assert UR.load_bodies([{"id": b["u"], "data": b} for b in bodies]) == bodies
    assert UR.load_bodies([{"doc_id": "x", "data": b} for b in bodies]) == bodies
    assert UR.load_bodies({"documents": [{"id": "x", "data": b} for b in bodies]}) == bodies
    assert UR.load_bodies([{"id": "x", "data": {"nothing": 1}}, "junk", 3]) == []
    with pytest.raises(ValueError):
        UR.load_bodies({"no": "list"})


# ------------------------------------------------------------------------------------------------ the aggregates, worked out by hand for the fixture
def test_people_counts():
    a = UR.aggregate(fixture(), TODAY)
    assert a["users_total"]["raw"] == 6 and a["users_total"]["n"] == 6
    assert a["active7"]["n"] == 5 and a["prev7"]["n"] == 6
    assert (a["returning"]["raw"], a["returning"]["raw_of"], a["returning"]["pct"]) == (5, 6, 83)           # persons 0-4 came on two days
    days = {d["day"].isoformat(): d for d in a["per_day"]}
    assert days[A]["users"] == 5 and days["2026-11-01"]["users"] == 0                                           # an empty day is a plain 0
    weeks = {w["week"]: w for w in a["per_week"]}
    assert weeks[WK(A)]["users"] == 5 and weeks[WK(B)]["users"] == 6 and weeks[WK(A)]["partial"] is True
    assert a["per_week"][0]["users"] is None and a["per_week"][0]["has_data"] is False                         # before the data starts: not zero
    tw = a["this_week"]
    assert (tw["raw_sessions"], tw["raw_users"], tw["per_user"]) == (5, 5, 1.0)


def test_session_length_and_time_share():
    a = UR.aggregate(fixture(), TODAY)
    assert (a["minutes"]["median"], a["minutes"]["p90"], a["minutes"]["sessions"]) == (2.0, 10.0, 11)           # 6 visits of 2 minutes and 5 of 10
    share = {s["key"]: s for s in a["section_time"]}
    assert share["burnup"]["share"] == 40.3 and share["attn"]["share"] == 40.3 and share["eff"]["share"] == 19.4    # 1500, 1500 and 720 of 3720 seconds
    assert [s["key"] for s in a["section_time"]][-1] == "eff"                                                     # sorted by time
    assert share["eff"]["users"] == 6


def test_controls_links_details_devices_builds_errors():
    a = UR.aggregate(fixture(), TODAY)
    assert (a["controls"]["release"]["n"], a["controls"]["release"]["users"]) == (10, 5)
    assert a["links"]["bugs"]["n"] == UR.SMALL and a["links"]["bugs"]["users"] == UR.SMALL                       # one person: guarded
    assert a["disclosures"]["how"]["n"] == 5
    assert a["filters_used"]["pct"] == 100 and a["filters_used"]["raw"] == 5 and a["filters_used"]["raw_of"] == 5
    dev = {d["key"]: d for d in a["devices"]}
    assert dev["l"]["users"] == 5 and dev["m"]["users"] == UR.SMALL
    bl = {b["build"]: b for b in a["builds"]}
    assert bl["aaa1111"]["users"] == 5 and bl["bbb2222"]["users"] == UR.SMALL and bl["bbb2222"]["raw_users"] == 1 and bl["aaa1111"]["newest"] is True      # person 0..4 visited last, on the older version string
    assert a["errors"]["any"] is True and a["errors"]["total"] == UR.SMALL


def test_percentile_is_interpolated():
    assert UR.percentile([1, 2, 3, 4], 0.5) == 2.5 and UR.percentile([5], 0.9) == 5 and UR.percentile([0, 10], 0.9) == 9


# ------------------------------------------------------------------------------------------------ the small-group guard
def test_a_group_of_four_prints_the_guard_and_five_prints_the_number():
    def mk(n_users):
        return [body(i, {A: [{"t": i, "s": 60, "sec": {"cx": 60}, "f": {"cypods": 43}, "l": {"capview": 61}, "o": {"data": 53}, "d": "s", "b": "ccc3333", "er": 71}]}) for i in range(n_users)] + \
               [body(10 + i, {A: [{"t": 99, "s": 60, "sec": {"eff": 60}}]}) for i in range(8)]
    four, five = UR.aggregate(mk(4), TODAY), UR.aggregate(mk(5), TODAY)
    assert [s for s in four["section_time"] if s["key"] == "cx"][0]["share"] == UR.SMALL
    assert four["controls"]["cypods"]["n"] == UR.SMALL and four["links"]["capview"]["n"] == UR.SMALL and four["disclosures"]["data"]["n"] == UR.SMALL
    assert four["devices"][0]["users"] == UR.SMALL and four["builds"][0]["users"] == UR.SMALL and four["errors"]["total"] == UR.SMALL
    assert five["controls"]["cypods"]["n"] == 5 * 43 and five["links"]["capview"]["n"] == 5 * 61 and five["errors"]["total"] == 5 * 71
    t4, h4 = UR.text_report(four), UR.html_report(four)
    for needle in ("43", "172", "61", "244", "53", "212", "71", "284"):             # the counts of the small group: each figure per person and its total over 4 people
        assert not re.search(rf"(?<![\w.]){needle}(?![\w.])", _text(h4)), f"{needle} printed in the page"
        assert not re.search(rf"(?<![\w.]){needle}(?![\w.])", t4), f"{needle} printed in the text report"
    assert "&lt;5 users" in h4 and "<5 users" in t4
    h5 = UR.html_report(five)
    assert re.search(r"(?<![\w.])215(?![\w.])", _text(h5))        # 5 people x 43: shown


def test_no_bar_is_drawn_for_a_guarded_row():
    a = UR.aggregate([body(i, {A: [{"t": i, "s": 60, "sec": {"cx": 60}}]}) for i in range(4)] + [body(10 + i, {A: [{"t": 1, "s": 60, "sec": {"eff": 60}}]}) for i in range(6)], TODAY)
    h = UR.html_report(a)
    row = re.search(r"<tr><th scope=\"row\">CXCROSS</th>(.*?)</tr>", h).group(1)
    assert "<i " not in row and "&lt;5 users" in row
    eff = re.search(r"<tr><th scope=\"row\">Efficiency</th>(.*?)</tr>", h).group(1)
    assert "<i " in eff


def test_the_daily_chart_draws_no_bar_under_five_people():
    a = UR.aggregate([body(i, {A: [{"t": i, "s": 60}]}) for i in range(4)] + [body(10 + i, {"2026-10-30": [{"t": 1, "s": 60}]}) for i in range(7)], TODAY)
    h = UR.html_report(a)
    chart = re.search(r'<div class="days".*?</div>(?=<div class="dayaxis")', h, re.S).group(0)
    assert chart.count('class="d"') == 1                                              # 30 October (7 people) only; today has 4 people: no bar
    assert f"<td>{A}</td><td class=\"n\">&lt;5 users</td>" in h


# ------------------------------------------------------------------------------------------------ no ids, empty state, caveat, page contract
def test_no_user_id_reaches_either_output():
    bodies = fixture()
    a = UR.aggregate(bodies, TODAY, dt.datetime(2026, 11, 2, 10, 15, tzinfo=UR.IL))
    for out in (UR.text_report(a), UR.html_report(a), UR.html_report(a, standalone=True)):
        assert "u_synthetic" not in out
        assert not re.search(r"\bu_[A-Za-z0-9_-]{3,}", out)
    demo = UR.aggregate(UR.demo_bodies(TODAY), TODAY, demo=True)
    assert not re.search(r"\bu_[A-Za-z0-9_-]{3,}", UR.html_report(demo) + UR.text_report(demo))


def test_empty_state():
    a = UR.aggregate([], TODAY)
    h = UR.html_report(a)
    assert 'id="empty"' in h and "No usage data yet" in h and 'id="h-hero"' not in h and "How this is measured" in h
    assert "No usage data yet" in UR.text_report(a)


def test_short_history_caveat():
    a = UR.aggregate(fixture(), TODAY)                                               # 8 days of history
    assert a["history_days"] == 8
    assert "Only 8 days of data so far: trends are not meaningful yet." in UR.html_report(a) and "only 8 days of data so far" in UR.text_report(a)
    long = fixture() + [body(7, {"2026-10-10": [{"t": 1, "s": 60}]})]
    a2 = UR.aggregate(long, TODAY)
    assert a2["history_days"] == 24
    assert "trends are not meaningful yet" not in UR.html_report(a2) and "trends are not meaningful yet" not in UR.text_report(a2)


def test_the_page_follows_the_artifact_contract():
    a = UR.aggregate(fixture(), TODAY, dt.datetime(2026, 11, 2, 8, 15, tzinfo=dt.timezone.utc))
    h = UR.html_report(a)
    assert h.startswith("<title>Delivery Pulse Usage</title>") and '<meta name="claude:viewport-fit-sides" content="cover">' in h
    assert "<script" not in h and "<img" not in h and "src=" not in h
    assert re.findall(r'(?:href|src)="(https?://[^"]+)"', h) == ["https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600&display=swap"]
    assert "Data as of 2026-11-02 10:15 Israel time" in h                              # 08:15 UTC is 10:15 in Israel
    assert "--blue:#3694FC" in h and "--ink:#21212B" in h and "--panel:#F2F0EB" in h and "color-scheme:light" in h
    assert "Demo data" not in h
    assert "Demo data" in UR.html_report(UR.aggregate(UR.demo_bodies(TODAY), TODAY, demo=True))
    assert "How this is measured" in h and "signed out" in h and "view-only" in h and "offline copy" in h


def test_the_errors_flag_shows_when_any_error_was_recorded():
    h = UR.html_report(UR.aggregate(fixture(), TODAY))
    assert 'id="errflag"' in h and "Needs attention" in h and "fewer than 5 users affected" in h
    clean = [body(i, {A: [{"t": i, "s": 60}]}) for i in range(6)]
    assert "No page errors recorded" in UR.html_report(UR.aggregate(clean, TODAY))


def test_the_demo_has_about_forty_people_and_eight_weeks_and_a_guarded_row():
    bodies = UR.demo_bodies(TODAY)
    assert 35 <= len(bodies) <= 40
    a = UR.aggregate(bodies, TODAY, demo=True)
    assert a["history_days"] >= 50 and any(v["n"] == UR.SMALL for v in a["controls"].values())
    assert UR.demo_bodies(TODAY) == bodies                                            # deterministic


def test_cli_text_and_html(tmp_path):
    src = tmp_path / "export.json"
    src.write_text(json.dumps([{"id": b["u"], "data": b} for b in fixture()]))
    out = tmp_path / "usage.html"
    assert UR.main([str(src), "--html", str(out), "--as-of", "2026-11-02T10:15:00+02:00", "--standalone"]) == 0
    page = out.read_text()
    assert page.startswith("<!DOCTYPE html>") and "Active users in the last 7 days" in page


# ------------------------------------------------------------------------------------------------ the report and the page speak the same vocabulary
def _voc() -> dict:
    return json.loads(re.search(r"const USAGE_VOC = (\{.*?\});\n", TEMPLATE).group(1))


def test_the_report_knows_exactly_the_keys_the_page_records():
    v = _voc()
    assert set(UR.SECTIONS) == set(v["sec"]) == set(v["nav"]) and set(UR.LINK_SECTIONS) == set(v["l"])
    assert set(UR.CONTROLS) == set(v["f"]) and set(UR.DISCLOSURES) == set(v["o"]) and set(UR.DEVICES) == set(v["d"])


def test_the_page_shows_a_usage_note_with_the_documented_wording_and_reads_only_the_id():
    block = TEMPLATE[TEMPLATE.index("const USAGE_VOC"):]
    assert "Usage statistics: this page counts, per anonymous user id (no name or e-mail), which sections are opened and which controls are used, to improve the dashboard. " in block
    assert "What is counted" in block and "Kept for 12 weeks" in block
    assert re.search(r"user\.id\(\)", block) and not re.search(r"user\.(name|email|me|profiles|search)\b", block)
    assert block.count('window.claude.use("db")') == 1 and block.count('window.claude.use("user")') == 1
    assert "scopes" not in block
    for banned in ("fetch(", "sendBeacon", "XMLHttpRequest", "WebSocket", "localStorage", "document.cookie"):
        assert banned not in block, f"the usage block must not use {banned}"
