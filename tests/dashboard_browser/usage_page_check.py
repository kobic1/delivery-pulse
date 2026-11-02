"""The "Delivery Pulse Usage" page (program_dashboard/usage_report.py, built here from its fictitious --demo data, from an empty export and from a v1-only export) in headless Chrome at 1400 and 390 px.

Asserted: no console error; no sideways scroll; the Demo data banner and the stale-export warning of the demo; the coverage ribbon is visible near the top and not inside a details element; the headings in order (one h1, then h2, no level skipped);
every chart has a text equivalent (the weekly chart and the daily chart carry a label with their numbers and sit next to a data table in a details element; every bar sits in a table row whose cells print the number); a guarded row prints '<5 users' and
draws no bar; the "What changed since last report" block and its Checked ledger; no user id anywhere; text contrast of at least 4.5:1 (3:1 for large text); every details element is a keyboard stop; the page uses no script; the empty state says
"No usage recorded yet" and shows no demo numbers. The page is an Artifact fragment; the test wraps it the way kit.wrap does.

    python3 usage_page_check.py [--live] [--only NAME]
"""
from __future__ import annotations

import datetime as dt
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "program_dashboard"))
import kit                                                                          # noqa: E402
import usage_report as UR                                                           # noqa: E402
from kit import ctx, T                                                              # noqa: E402

SUITE = kit.Suite("Delivery Pulse Usage page")
REF = dt.date(2026, 10, 29)                                                         # the day of the demo data (a Thursday); the demo export is 4 days old on NOW: the stale warning shows
AS_OF = dt.datetime(2026, 10, 29, 10, 0, tzinfo=UR.IL)
NOW = dt.datetime(2026, 11, 2, 10, 15, tzinfo=UR.IL)

CONTRAST_JS = r"""(() => {
  const lum = c => { const [r, g, b] = c.map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
  const rgb = s => { const m = s.match(/rgba?\(([^)]+)\)/); if (!m) return null; const p = m[1].split(",").map(x => parseFloat(x)); return {c: p.slice(0, 3), a: p.length > 3 ? p[3] : 1}; };
  const bgOf = el => { for (let e = el; e; e = e.parentElement) { const b = rgb(getComputedStyle(e).backgroundColor); if (b && b.a > 0.5) return b.c; } return [255, 255, 255]; };
  const bad = [];
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = w.nextNode(); n; n = w.nextNode()) {
    if (!n.textContent.trim()) continue; const el = n.parentElement, cs = getComputedStyle(el);
    if (cs.visibility === "hidden" || cs.display === "none" || el.closest("[hidden]")) continue;
    const fg = rgb(cs.color).c, bg = bgOf(el), l1 = lum(fg), l2 = lum(bg), ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
    const px = parseFloat(cs.fontSize), large = px >= 24 || (px >= 18.66 && parseInt(cs.fontWeight) >= 700);
    if (ratio < (large ? 3 : 4.5)) bad.push(n.textContent.trim().slice(0, 40) + " " + ratio.toFixed(2));
  }
  return bad;
})()"""

_cache: dict = {}


def page_url(kind: str = "demo") -> str:
    """The wrapped page of a kind: the demo, an empty export, or v1 records only."""
    if kind not in _cache:
        if kind == "demo":
            agg = UR.aggregate(UR.demo_bodies(REF), as_of=AS_OF, now=NOW, demo=True, calendar=UR.parse_calendar(UR.demo_calendar(REF)))
        elif kind == "empty":
            agg = UR.aggregate([], as_of=NOW, now=NOW)
        else:
            agg = UR.aggregate(UR.demo_bodies(dt.date(2026, 11, 1), v2_from=99), as_of=NOW, now=NOW)
        _cache[kind] = ctx.write(kit.wrap(UR.html_report(agg)), "usage_page_" + kind)
    return _cache[kind]


def open_at(width: int, kind: str = "demo"):
    ch = ctx.chrome
    ch.viewport(width, 900, mobile=width < 500)
    ch.goto(page_url(kind))
    time.sleep(0.5)
    return ch


@SUITE.test("usage_page_loads_at_1400_and_390_without_errors_or_sideways_scroll")
def _(t: T):
    for kind in ("demo", "empty", "v1"):
        for w in (1400, 390):
            ch = open_at(w, kind)
            t.check(not ch.console_errors(), f"{kind} {w}: console {ch.console_errors()[:2]}")
            t.check(ch.js("document.documentElement.scrollWidth - document.documentElement.clientWidth") <= 0, f"{kind} {w}: sideways scroll")
            t.check(ch.js("document.title") == "Delivery Pulse Usage", f"{kind} {w}: the title")
    for w in (1400, 390):
        ch = open_at(w)
        t.check(ch.js("!!document.getElementById('demo-banner') && document.getElementById('demo-banner').textContent.startsWith('Demo data')"), f"{w}: the Demo data banner")
        t.check(ch.js("document.getElementById('asof').textContent") == "Data as of 2026-10-29 10:00 Israel time", f"{w}: the data stamp")
        t.check(ch.js("[...document.querySelectorAll('.warn')].some(w => w.textContent.includes('days old'))"), f"{w}: the demo's stale export is warned about")
    ctx.chrome.viewport(1400, 900)


@SUITE.test("usage_page_coverage_ribbon_is_visible_near_the_top_and_not_inside_a_details_element")
def _(t: T):
    for w in (1400, 390):
        ch = open_at(w)
        t.check(ch.js("(() => { const r = document.getElementById('coverage'); if (!r) return false; const b = r.getBoundingClientRect(); const cs = getComputedStyle(r); return b.height > 20 && b.top < 420 && cs.display !== 'none' && cs.visibility !== 'hidden' && !r.closest('details'); })()"), f"{w}: the ribbon is visible near the top, outside any details")
        t.check(ch.js("document.getElementById('coverage').textContent.includes('Not counted: people signed out') && document.getElementById('coverage').textContent.includes('Never used to rank or assess people or teams')"), f"{w}: the ribbon says what is not counted")
    ch = open_at(1400, "empty")
    t.check(ch.js("!!document.getElementById('coverage') && !document.getElementById('coverage').closest('details')"), "the ribbon is on the empty page too")
    ctx.chrome.viewport(1400, 900)


@SUITE.test("usage_page_headings_are_in_order_and_every_chart_has_a_text_equivalent")
def _(t: T):
    for kind in ("demo", "v1", "empty"):
        ch = open_at(1400, kind)
        heads = ch.js("[...document.querySelectorAll('h1,h2,h3,h4')].map(h => +h.tagName[1])")
        t.check(heads[0] == 1 and heads.count(1) == 1 and all(b - a <= 1 for a, b in zip(heads, heads[1:])), f"{kind}: heading levels {heads}")
        t.check(ch.js("[...document.querySelectorAll('section[aria-labelledby]')].every(s => document.getElementById(s.getAttribute('aria-labelledby')))"), f"{kind}: every section is labelled by a heading that exists")
    ch = open_at(1400)
    charts = ch.js("[...document.querySelectorAll('[role=img]')].map(c => ({label: (c.getAttribute('aria-label') || '').length, table: !!(c.closest('section') && c.closest('section').querySelector('details table tbody tr'))}))")
    t.check(len(charts) >= 2 and all(c["label"] > 100 and c["table"] for c in charts), f"every chart has a label with its numbers and a data table ({charts})")
    t.check(ch.js("document.querySelectorAll('.bars').length") >= 2 and ch.js("document.querySelectorAll('.bars .gap').length") >= 1 and ch.js("document.querySelectorAll('.bars .d.part').length") >= 1, "the charts draw the guarded, partial and ordinary columns")
    t.check(ch.js("document.querySelectorAll('details.vd > summary').length") >= 5, "the disclosures exist")
    bars = ch.js("[...document.querySelectorAll('.track')].map(b => { const r = b.closest('tr'); return !!r && r.querySelector('th').textContent.trim().length > 0 && /[0-9]/.test(r.querySelector('td.n').textContent); })")
    t.check(bool(bars) and all(bars), f"every bar sits in a row that prints its name and number ({len(bars)} bars)")
    t.check(ch.js("[...document.querySelectorAll('.track')].every(b => b.closest('td').getAttribute('aria-hidden') === 'true')"), "bars are decoration for a screen reader: the row carries the number")
    t.check(ch.js("document.querySelectorAll('script').length - document.querySelectorAll('script[data-harness]').length") == 0, "the page has no script")


@SUITE.test("usage_page_what_changed_block_and_the_checked_ledger")
def _(t: T):
    ch = open_at(1400)
    t.check(ch.js("document.querySelector('#changed h2').textContent") == "What changed since last report", "the block heading")
    t.check(ch.js("document.querySelectorAll('#changed li.sig').length") >= 2 and ch.js("[...document.querySelectorAll('#changed .tag')].every(g => ['Confirmed','Corroborated','Single-source','Weak signal','Unknown'].includes(g.textContent.trim()))"), "each flagged item carries a confidence label")
    t.check(ch.js("document.querySelector('#changed').textContent.includes('No previous report supplied; every flagged item is shown as new.')"), "the no-history sentence")
    t.check(ch.js("(() => { const d = document.getElementById('checked'); return !!d && d.tagName === 'DETAILS' && !d.open && d.querySelectorAll('tbody tr').length >= 10; })()"), "the Checked ledger is collapsed and lists every signal")
    t.check(ch.js("document.getElementById('growth').textContent.includes('Is adoption growing?')"), "the growth verdict is in the hero")
    ch = open_at(1400, "v1")
    t.check(ch.js("document.body.innerText.includes('not recorded in v1')"), "the v1 page says what is not recorded")
    ctx.chrome.viewport(1400, 900)


@SUITE.test("usage_page_a_small_group_prints_the_guard_and_draws_no_bar_and_no_id_is_shown")
def _(t: T):
    ch = open_at(1400)
    rows = ch.js("[...document.querySelectorAll('tbody tr')].filter(r => r.textContent.includes('<5 users')).map(r => ({bars: r.querySelectorAll('.track').length, text: r.textContent}))")
    t.check(len(rows) >= 3 and all(r["bars"] == 0 for r in rows), f"guarded rows: {len(rows)}, bars drawn: {[r['bars'] for r in rows]}")
    body = ch.js("document.body.innerText + document.documentElement.outerHTML")
    t.check("u_synthetic" not in body and "@" not in ch.js("document.body.innerText"), "no user id or address on the page")
    t.check(ch.js("document.querySelector('#how summary').textContent") == "What is counted and what is not", "the measurement note is there")
    t.check(ch.js("document.getElementById('governance').textContent.includes('Pseudonymous, not anonymous')"), "the governance text is visible")


@SUITE.test("usage_page_empty_state_says_no_usage_recorded_yet_and_shows_no_demo_numbers")
def _(t: T):
    for w in (1400, 390):
        ch = open_at(w, "empty")
        t.check(ch.js("document.querySelector('#empty h2').textContent") == "No usage recorded yet", f"{w}: the plain statement")
        t.check(ch.js("document.querySelectorAll('#empty li').length") == 3, f"{w}: three steps say what to do next")
        t.check(ch.js("!document.getElementById('demo-banner') && !document.querySelector('.hero') && !document.querySelector('.bars')"), f"{w}: no demo banner, hero or chart")
    ctx.chrome.viewport(1400, 900)


@SUITE.test("usage_page_text_contrast_is_at_least_4_5_to_1_at_both_widths")
def _(t: T):
    for kind in ("demo", "empty", "v1"):
        for w in (1400, 390):
            ch = open_at(w, kind)
            ch.js("document.querySelectorAll('details').forEach(d => d.open = true)")
            bad = ch.js(CONTRAST_JS)
            t.check(not bad, f"{kind} {w}: low contrast {bad[:4]}")
            t.check(ch.js("document.documentElement.scrollWidth - document.documentElement.clientWidth") <= 0, f"{kind} {w}: sideways scroll with every details open")
    ctx.chrome.viewport(1400, 900)


@SUITE.test("usage_page_summaries_are_keyboard_stops_and_the_focus_is_visible")
def _(t: T):
    ch = open_at(1400)
    n = ch.js("document.querySelectorAll('details > summary').length")
    for typ in ("keyDown", "keyUp"):                                                  # a real Tab: the first stop of the page
        ch.cmd("Input.dispatchKeyEvent", type=typ, key="Tab", code="Tab", windowsVirtualKeyCode=9)
    t.check(ch.js("document.activeElement.tagName") == "SUMMARY" and n >= 3, "Tab reaches a summary first")
    t.check(ch.js("getComputedStyle(document.activeElement).outlineStyle") != "none", "the focus ring is drawn")


if __name__ == "__main__":
    sys.exit(kit.cli(SUITE, __doc__))
