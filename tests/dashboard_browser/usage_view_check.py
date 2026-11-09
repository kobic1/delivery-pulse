#!/usr/bin/env python3
"""The owner-only live usage view at the bottom of dashboard.template.html (`UV`, the block after the usage statistics block): in headless Chrome with the mocked db.

The view is for the artifact's owner and the people who have Editor access: for anybody else it stays hidden and reads nothing. The owner opens it, the page reads the collection `usage` (a list, never a write), draws the report of
usage_report.py (the browser port, program_dashboard/usage_view/*.js) in a shadow root and the owner can read again with "Refresh usage". What protects the records is the database rule
({"path": "usage", "read": "admin", "write": "admin"}), not this block; the test covers the page side of it. The port itself is checked against the Python report in usage_port/port_check.py.

Asserted:
  * a viewer who is neither the owner nor an Editor (and a page with no user capability) sees no usage view, and the page reads no `usage` collection;
  * an Editor who is not the owner sees the view and the Usage link and can open and refresh it;
  * the Usage link at the right end of the Section Strip is there for the owner only, opens the view and scrolls to it, and is not one of the strip's sections;
  * the owner sees the closed view, nothing is read before it is opened, opening it reads once, "Refresh usage" reads again and picks up a record added in between;
  * what the view draws IS the Python report: the shadow root equals usage_report.py's page for the same records (every minimum off, the page's own clock), and the dashboard's styles are not in it;
  * a refused or failed read shows a message and leaves the button usable, no console error; an empty collection says so;
  * the view never writes (no set, update or delete in the db log), no id, e-mail or name appears in it, no console error, no sideways scroll at 1400 and 390 px.

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
SHADOW = "document.getElementById('uv-out').shadowRoot"
_fx: dict = {}


def bodies() -> list:
    if "b" not in _fx:
        _fx["b"] = UR.demo_bodies(REF)
    return _fx["b"]


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


def shadow_text(ch) -> str:
    return ch.js(f"({SHADOW} ? [...{SHADOW}.children].filter(n => n.tagName !== 'STYLE').map(n => n.textContent).join(' ') : '')") or ""      # what is read, without the style sheet


def clean_like_the_page(html: str) -> str:
    """What the page does to the report's fragment before it goes into the shadow root, written again here on purpose."""
    html = re.sub(r"<title>[\s\S]*?</title>|<meta [^>]*>|<link [^>]*>", "", html)
    return re.sub(r"<style>([\s\S]*?)</style>", lambda m: "<style>" + re.sub(r"(^|\})\s*body\s*\{", r"\1:host{", re.sub(r":root\b", ":host", m.group(1))) + "</style>", html, count=1)


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


@SUITE.test("usage_view_an_editor_who_is_not_the_owner_sees_and_refreshes_it")
def _(t: T):
    ch = load(owner=False, editor=True)
    t.check(ch.js("document.getElementById('usageview').hidden") is False, "an Editor does not see the usage view")
    t.check(ch.js("document.getElementById('uv-link').hidden") is False, "an Editor does not see the Usage link in the strip")
    t.check(not reads(ch), "the page read the records before the Editor opened the view")
    ch.js("document.getElementById('uv-link').click()")
    t.check(wait_read(ch), "the Usage link did not open the view for an Editor: " + stamp(ch))
    t.check("Delivery Pulse Usage" in shadow_text(ch), "the report is not in the Editor's view")
    ch.js("document.getElementById('uv-refresh').click()")
    t.check(ch.wait_for("window.__dbLog.filter(e => e.op === 'list').length === 2", 6), "Refresh usage did not read again for an Editor")
    ch = load(owner=False, editor=False)
    t.check(ch.js("document.getElementById('usageview').hidden") is True and ch.js("document.getElementById('uv-link').hidden") is True, "a viewer who is neither owner nor Editor sees the view or its link")
    t.check(not reads(ch), "a viewer who is neither owner nor Editor caused a read")
    t.check(not ch.console_errors(), f"console error: {ch.console_errors()[:2]}")


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
    t.check("Delivery Pulse Usage" in shadow_text(ch), "the report is not in the view after the read")
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


@SUITE.test("usage_view_draws_exactly_the_python_report")
def _(t: T):
    ch = load(owner=True)
    t.check(ch.js("window.__dpUsageViewTest && window.__dpUsageViewTest.hasReport()") is True, "the report code is not in the page (the build did not inline usage_view/*.js)")
    open_view(ch)
    t.check(wait_read(ch), "no read: " + stamp(ch))
    last = json.loads(ch.js("JSON.stringify(window.__dpUsageViewTest.last)"))
    now = dt.datetime.fromisoformat(last["now"].replace("Z", "+00:00"))
    rows = [{"id": b["u"], "data": b} for b in bodies()]
    got, stats = UR.load_export(rows)
    th = {**UR.THRESHOLDS, **UR.SHOW_ALL}
    a = UR.aggregate(got, today=dt.date.fromisoformat(last["today"]), as_of=now, now=now, th=th, stats=stats)
    expect = clean_like_the_page(UR.html_report(a))
    same = ch.js("""(() => { const expect = %s, h = document.createElement('div'); document.body.append(h); const r = h.attachShadow({mode: 'open'}); r.innerHTML = expect;
      r.querySelectorAll('h1, h2, h3, h4, h5, h6').forEach(x => x.setAttribute('aria-level', String(Math.min(6, +x.tagName[1] + 2))));
      const real = document.getElementById('uv-out').shadowRoot.innerHTML, mine = r.innerHTML; h.remove(); return real === mine ? true : [real.length, mine.length, [...real].findIndex((c, i) => c !== mine[i])]; })()""" % json.dumps(expect))
    t.check(same is True, f"the page's report differs from usage_report.py's for the same records: {same}")
    heads = ch.js(f"[...{SHADOW}.querySelectorAll('h1, h2, h3, h4, h5, h6')].map(h => [+h.tagName[1], +h.getAttribute('aria-level')])")
    t.check(bool(heads) and all(lvl == min(6, tag + 2) for tag, lvl in heads), f"the report's headings are not nested under the view's own heading: {heads[:6]}")
    t.check(heads[0][1] == 3 and ch.js("document.getElementById('h-uv').tagName") == "H2", "the report's title is not level 3 under the view's h2")
    levels = [lvl for _, lvl in heads]
    t.check(all(b - a <= 1 for a, b in zip(levels, levels[1:])), f"a heading level is skipped inside the view: {levels}")
    t.check("Delivery Pulse Usage" in shadow_text(ch) and "Key figures" in shadow_text(ch) and "Recording health" in shadow_text(ch), "the report lacks its sections")
    t.check(ch.js(f"!!{SHADOW}.querySelector('#p-weeks #wtd #wtd-table') && {SHADOW}.querySelector('#wtd .cap').innerText.startsWith('This week so far')") is True, "the week-so-far block is not in the weekly panel of the view")
    t.check(ch.js(f"{SHADOW}.querySelector('style') && !{SHADOW}.querySelector('title, meta, link')") is True, "the shadow root holds the report's own style and no head elements")
    outside = ch.js(f"getComputedStyle({SHADOW}.querySelector('h1')).fontSize")
    t.check(outside == "20px", f"the report's own style does not apply inside the view (h1 font size {outside})")
    t.check(ch.js("getComputedStyle(document.querySelector('#kpis')).display") != "none", "the dashboard's own page changed")
    t.check(not ch.console_errors(), f"console error: {ch.console_errors()[:2]}")


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
    t.check("No usage recorded yet" in shadow_text(ch), "an empty collection is not said to be empty")
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
    text = shadow_text(ch) + (ch.js("document.getElementById('usageview').textContent") or "")                      # what a person reads
    markup = re.sub(r"<style>[\s\S]*?</style>", "", ch.js(f"{SHADOW}.innerHTML") or "")                                # the report's own markup (its style sheet holds @media rules)
    for what, where in (("text", text), ("markup", markup)):
        t.check(not IDRE.search(where), f"an id, e-mail or name is in the view's {what}: {IDRE.search(where) and IDRE.search(where).group(0)}")
        t.check(not re.search(r"[A-Z][A-Z0-9]+-\d+", where), f"an issue-key-shaped string is in the view's {what}")


@SUITE.test("usage_view_layout_has_no_sideways_scroll")
def _(t: T):
    for vp in ((1400, 900), (390, 844)):
        ch = load(owner=True, vp=vp)
        open_view(ch)
        t.check(wait_read(ch), f"no read at {vp[0]}")
        ch.js(f"{SHADOW}.querySelectorAll('details').forEach(d => d.open = true); void 0")
        time.sleep(0.3)
        t.check(ch.js("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1") is True, f"sideways scroll at {vp[0]} px")
        t.check(ch.js("document.getElementById('usageview').scrollWidth <= document.getElementById('usageview').clientWidth + 1") is True, f"the usage view is wider than its box at {vp[0]} px")
        n = ch.js(f"{SHADOW}.querySelectorAll('details.vd').length")
        t.check(isinstance(n, int) and n >= 5, f"the report's charts and their data tables are missing: {n}")
        t.check(not ch.console_errors(), f"console error at {vp[0]}: {ch.console_errors()[:2]}")


if __name__ == "__main__":
    sys.exit(kit.cli(SUITE, __doc__))
