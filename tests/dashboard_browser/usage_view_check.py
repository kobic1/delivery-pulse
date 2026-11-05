#!/usr/bin/env python3
"""The owner-only live usage view at the bottom of dashboard.template.html (`UV`, the block after the usage statistics block): in headless Chrome with the mocked db.

The view is for the artifact's owner alone: for anybody else it stays hidden and reads nothing. The owner opens it, the page reads the collection `usage` (a list, never a write), draws the figures
and the owner can read again with "Refresh usage". What protects the records is the database rule ({"path": "usage", "read": "owner"}), not this block; the test covers the page side of it.

Asserted:
  * a viewer who is not the owner (and a page with no user capability) sees no usage view, and the page reads no `usage` collection;
  * the Usage link at the right end of the Section Strip is there for the owner only, opens the view and scrolls to it, and is not one of the strip's sections;
  * the owner sees the closed view, nothing is read before it is opened, opening it reads once, "Refresh usage" reads again and picks up a record added in between;
  * the figures are the report's: people, active per week, engaged visits, section and control reach, minutes, refresh people equal usage_report.py's own numbers (--show-all) on the same fictitious data;
  * a refused or failed read shows a message and leaves the button usable, no console error; an empty collection says so;
  * the view never writes (no set, update or delete in the db log), no id, e-mail or name appears in it, no console error, no sideways scroll at 1400 and 390 px, every chart has a text table.

    python3 usage_view_check.py [--live] [--only NAME]
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "program_dashboard"))
import kit                                                                          # noqa: E402
import usage_report as UR                                                           # noqa: E402
from kit import ctx, T                                                              # noqa: E402

SUITE = kit.Suite("Delivery Pulse live usage view")
REF = dt.date(2026, 10, 29)                                                         # the Israel day the page's clock is set to
NOW = dt.datetime(2026, 10, 29, 12, 0, tzinfo=UR.IL)
IDRE = re.compile(r"u_[A-Za-z0-9_-]{3,}|@|synthetic", re.I)
_fx: dict = {}


def bodies() -> list:
    if "b" not in _fx:
        _fx["b"] = UR.demo_bodies(REF)
    return _fx["b"]


def expected() -> dict:
    """The report's own figures for the same bodies, with the minimums off (--show-all)."""
    if "e" not in _fx:
        th = dict(UR.THRESHOLDS)
        th.update(UR.SHOW_ALL)
        a = UR.aggregate(bodies(), today=REF, as_of=NOW, now=NOW, th=th)
        m = a["model"]
        _fx["e"] = {"people": len(m.people), "sessions": len(m.rows), "active_last": len(m.active(m.last)), "active_cur": len(m.active(m.cur)),
                    "engaged": a["use"]["engaged"], "window_people": a["sections"]["n"], "control_people": a["controls"]["any"]["raw"],
                    "minutes": a["use"]["minutes"]["median"], "per_person": a["use"]["per_person"]["value"], "refresh_people": a["use"]["refresh"]["x"],
                    "weeks": {str(w): len(m.active(w)) for w in sorted(m.by_week)},
                    "sections": {t["key"]: t["raw"] for t in a["sections"]["rows"]}, "controls": {r["key"]: r["raw"] for f in a["controls"]["families"] for r in f["rows"]}}
    return _fx["e"]


def seed(extra: int = 0) -> dict:
    out = {f"usage/{b['u']}": b for b in bodies()}
    for i in range(extra):
        out[f"usage/u_extra_{i:03d}"] = {"u": f"u_extra_{i:03d}", "v": 2, "first": REF.isoformat(), "last": REF.isoformat(),
                                         "w": {"S2026-10-25": {REF.isoformat(): {"abcdefgh": {"t": 480000, "s": 120, "vs": 130, "d": "l", "sec": {"top": 60}, "f": {"release": 1}}}}}}
    return out


def load(owner: bool = True, usage_ok: bool = True, vp=(1400, 900), seeded: dict | None = None, **u):
    ch = ctx.chrome
    cfg = dict(mode="denied", ls="recent", shift=int(NOW.timestamp() * 1000 - time.time() * 1000), slow=0, fastTimers=False, page1=[], page2=[], capsnodes=[], opencfb=[], linknodes=[], farnodes=[],
               leftcfb=[], capnodes=[], axkey="X-1", keep=False)
    if usage_ok:
        cfg["usage"] = {"owner": owner, "uid": None, "seed": seeded if seeded is not None else seed(), **u}
    pre = "<script data-harness>" + (HERE / "mock_claude.js").read_text().replace("/*__CFG__*/null", json.dumps(cfg).replace("</", "<\\/")).replace("/*__HOOK__*/null", "null") + "</script>"
    import make_synthetic as MS
    data = MS.make(MS.il_today())
    data["build"] = {"sha": "abc1234", "dirty": False, "at": "2026-01-01T00:00+02:00"}
    url = ctx.write(kit.wrap(kit.fragment_for(data), pre + "<script>window.__dpUsageT={};</script>"), "uv")
    ch.cmd("Emulation.setTimezoneOverride", timezoneId="Asia/Jerusalem")
    ch.viewport(*vp, mobile=vp[0] < 500)
    ch.goto(url)
    assert kit.wait_ready(ch), "the page did not draw: " + str(ch.console_errors()[:2])
    time.sleep(0.6)
    return ch


def log(ch) -> list:
    return json.loads(ch.js("JSON.stringify(window.__dbLog || [])") or "[]")


def reads(ch) -> list:
    return [e for e in log(ch) if e["op"] == "list"]


def open_view(ch):
    ch.js("document.getElementById('uv-toggle').click()")


def stamp(ch) -> str:
    return ch.js("document.getElementById('uv-stamp').textContent") or ""


def wait_read(ch, timeout=8) -> bool:
    return ch.wait_for("/^Read \\d+ record/.test(document.getElementById('uv-stamp').textContent)", timeout)


@SUITE.test("usage_view_hidden_and_silent_for_a_viewer_who_is_not_the_owner")
def _(t: T):
    ch = load(owner=False)
    t.check(ch.js("document.getElementById('usageview').hidden") is True, "the usage view is visible to a viewer who is not the owner")
    t.check(ch.js("getComputedStyle(document.getElementById('usageview')).display") == "none", "the hidden view still takes room on the page")
    t.check(not reads(ch), "a viewer who is not the owner caused a read of the usage collection")
    t.check(not ch.console_errors(), f"console error: {ch.console_errors()[:2]}")
    ch = load(usage_ok=False)
    t.check(ch.js("document.getElementById('usageview').hidden") is True, "the usage view is visible on a page with no db and no user capability")
    t.check(not ch.console_errors(), f"console error without capabilities: {ch.console_errors()[:2]}")
    ch = load(owner=True, user=None)
    t.check(ch.js("document.getElementById('usageview').hidden") is True, "the usage view is visible when there is no user capability")


@SUITE.test("usage_view_owner_opens_reads_once_and_refresh_reads_again")
def _(t: T):
    ch = load(owner=True)
    t.check(ch.js("document.getElementById('usageview').hidden") is False, "the owner does not see the usage view")
    t.check(ch.js("document.getElementById('uv-body').hidden") is True, "the view is open before the owner asked")
    t.check(not reads(ch), "the page read the usage records before the owner opened the view")
    open_view(ch)
    t.check(wait_read(ch), "no 'Read N records' stamp after opening: " + stamp(ch))
    t.check(len(reads(ch)) == 1, f"opening the view read {len(reads(ch))} times, expected 1")
    t.check(f"Read {len(bodies())} records" in stamp(ch), f"stamp: {stamp(ch)}")
    ch.js("window.__dbDocs['usage/u_added_001'] = " + json.dumps(seed(1)["usage/u_extra_000"]) + "; void 0")
    ch.js("document.getElementById('uv-refresh').click()")
    t.check(ch.wait_for(f"document.getElementById('uv-stamp').textContent.startsWith('Read {len(bodies()) + 1} records')", 8), "Refresh usage did not pick up the added record: " + stamp(ch))
    t.check(len(reads(ch)) == 2, f"expected 2 reads in all, got {len(reads(ch))}")
    ch.js("document.getElementById('uv-toggle').click()")
    t.check(ch.js("document.getElementById('uv-body').hidden") is True, "the view did not close")
    ch.js("document.getElementById('uv-toggle').click()")
    time.sleep(0.4)
    t.check(len(reads(ch)) == 2, "re-opening the view read again by itself")
    t.check(not ch.console_errors(), f"console error: {ch.console_errors()[:2]}")


@SUITE.test("usage_view_header_link_only_for_the_owner_opens_and_scrolls_to_the_view")
def _(t: T):
    ch = load(owner=False)
    t.check(ch.js("document.getElementById('uv-link').hidden") is True, "the Usage link is visible to a viewer who is not the owner")
    t.check(ch.js("getComputedStyle(document.getElementById('uv-link')).display") == "none", "the hidden Usage link still takes room in the strip")
    t.check(ch.js("document.getElementById('secnav').classList.contains('hasuv')") is False, "the strip reserves room for a Usage link nobody sees")
    ch = load(owner=True)
    t.check(ch.js("document.getElementById('uv-link').hidden") is False, "the owner does not see the Usage link")
    t.check(ch.js("document.querySelectorAll('#seclist a').length") == 11, "the Usage link joined the section list the scrollspy and the usage counters read")
    box = ch.js("(() => { const l = document.getElementById('uv-link').getBoundingClientRect(), n = document.getElementById('secnav').getBoundingClientRect(); return [Math.round(n.right - l.right), l.top >= n.top - 1 && l.bottom <= n.bottom + 1]; })()")
    t.check(box == [0, True], f"the Usage link is not at the right end of the strip: {box}")
    t.check(not reads(ch), "the page read the records before the owner opened the view")
    ch.js("document.getElementById('uv-link').click()")
    t.check(wait_read(ch), "the Usage link did not open the view and read the records: " + stamp(ch))
    ch.wait_for("(() => { const r = document.getElementById('usageview').getBoundingClientRect(); return r.top < window.innerHeight * 0.5; })()", 6)
    top = ch.js("Math.round(document.getElementById('usageview').getBoundingClientRect().top)")
    t.check(isinstance(top, (int, float)) and top < 400, f"the view is not scrolled into place after the link: top {top}")
    ch.js("document.getElementById('uv-link').click()")
    time.sleep(0.4)
    t.check(len(reads(ch)) == 1, "a second click on the link read again")
    t.check(not ch.console_errors(), f"console error: {ch.console_errors()[:2]}")


@SUITE.test("usage_view_figures_equal_the_report")
def _(t: T):
    e = expected()
    ch = load(owner=True)
    open_view(ch)
    t.check(wait_read(ch), "no read: " + stamp(ch))
    kp = ch.js("[...document.querySelectorAll('#uv-out .uvkpi b')].map(x => x.textContent)")
    t.check(kp == [str(e["people"]), str(e["active_last"]), str(e["active_cur"]), str(e["engaged"]), f"{e['minutes']} min", str(e["per_person"])], f"key figures {kp} against the report {e}")
    m = ch.js("JSON.parse(JSON.stringify(window.__dpUsageViewTest.compute(Object.values(window.__dbRead()), '" + REF.isoformat() + "')))")
    t.check(m["people"] == e["people"] and m["sessions"] == e["sessions"], f"people/sessions {m['people']}/{m['sessions']} against {e['people']}/{e['sessions']}")
    t.check(m["window"]["people"] == e["window_people"], f"window people {m['window']['people']} against {e['window_people']}")
    t.check({w["week"]: w["people"] for w in m["weeks"] if w["people"]} == e["weeks"], "people active per week differ from the report")
    t.check({s["key"]: s["people"] for s in m["sections"]} == e["sections"], "section reach differs from the report")
    t.check({s["key"]: s["people"] for s in m["controls"]} == e["controls"], "control reach differs from the report")
    t.check(m["controlPeople"] == e["control_people"] and m["refreshPeople"] == e["refresh_people"], "control or refresh people differ from the report")
    rows = ch.js("[...document.querySelectorAll('#uv-out .uvbar')].map(r => [r.children[0].textContent, r.children[2].textContent])")
    secs = {UR.READ_SECTIONS[k]: n for k, n in e["sections"].items()}
    t.check(all(secs[a] == int(b.split()[0]) for a, b in rows if a in secs), "a section bar prints another number than the report's")


@SUITE.test("usage_view_failed_read_and_empty_collection")
def _(t: T):
    ch = load(owner=True, listFault="permission_denied")
    open_view(ch)
    t.check(ch.wait_for("/could not be read/.test(document.getElementById('uv-stamp').textContent)", 8), "no message for a refused read: " + stamp(ch))
    t.check("permission_denied" in stamp(ch), "the message does not name the refusal code: " + stamp(ch))
    t.check(ch.js("document.getElementById('uv-refresh').disabled") is False, "Refresh usage stays disabled after a failed read")
    t.check(not ch.console_errors(), f"console error after a refused read: {ch.console_errors()[:2]}")
    ch = load(owner=True, seeded={})
    open_view(ch)
    t.check(wait_read(ch), "no stamp for an empty collection: " + stamp(ch))
    t.check("No usage recorded yet" in (ch.js("document.getElementById('uv-out').textContent") or ""), "an empty collection is not said to be empty")
    ch = load(owner=True, latency=12000)
    open_view(ch)
    t.check(ch.wait_for("/took too long/.test(document.getElementById('uv-stamp').textContent)", 16), "a read that never answers is not given up on: " + stamp(ch))


@SUITE.test("usage_view_never_writes_and_shows_no_identity")
def _(t: T):
    ch = load(owner=True)
    open_view(ch)
    t.check(wait_read(ch), "no read")
    ch.js("document.getElementById('uv-refresh').click()")
    time.sleep(0.6)
    ops = {e["op"] for e in log(ch)}
    t.check(ops <= {"list"}, f"the view did something besides reading: {ops}")
    text = (ch.js("document.getElementById('usageview').textContent") or "") + (ch.js("document.getElementById('usageview').innerHTML") or "")
    t.check(not IDRE.search(text), f"an id, e-mail or name is on the view: {IDRE.search(text) and IDRE.search(text).group(0)}")
    t.check(not re.search(r"[A-Z][A-Z0-9]+-\d+", text), "an issue-key-shaped string is on the view")


@SUITE.test("usage_view_layout_charts_have_text_and_no_sideways_scroll")
def _(t: T):
    for vp in ((1400, 900), (390, 844)):
        ch = load(owner=True, vp=vp)
        open_view(ch)
        t.check(wait_read(ch), f"no read at {vp[0]}")
        ch.js("document.querySelectorAll('#usageview details').forEach(d => d.open = true); void 0")
        t.check(ch.js("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1") is True, f"sideways scroll at {vp[0]} px")
        t.check(ch.js("document.getElementById('usageview').scrollWidth <= document.getElementById('usageview').clientWidth + 1") is True, f"the usage view is wider than its box at {vp[0]} px")
        n = ch.js("[document.querySelectorAll('#uv-out .uvcols').length, document.querySelectorAll('#uv-out details table').length]")
        t.check(n == [2, 2], f"charts and their tables: {n}")
        t.check(ch.js("[...document.querySelectorAll('#uv-out .uvcols')].every(c => c.getAttribute('role') === 'img' && c.getAttribute('aria-label'))") is True, "a chart has no name")
        t.check(ch.js("[document.querySelectorAll('#usageview h2').length, document.querySelectorAll('#usageview h3').length > 0]") == [1, True], "heading structure of the view")
        t.check(not ch.console_errors(), f"console error at {vp[0]}: {ch.console_errors()[:2]}")


if __name__ == "__main__":
    sys.exit(kit.cli(SUITE, __doc__))
