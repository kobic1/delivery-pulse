"""The "Delivery Pulse Usage" page (program_dashboard/usage_report.py, built here from its fictitious --demo data, from an empty export and from a v1-only export) in headless Chrome at 1400 and 390 px.

Asserted: the week-so-far block sits in the weekly panel with the report's own sentence and rows and fits at both widths; no console error; no sideways scroll (also with every "Show data" open: a wide table scrolls inside its own box); the Demo data banner and the stale-export warning of the demo; the coverage ribbon is visible near the top, short, and not inside a details
element; the headings in order (one h1, then h2, no level skipped); the page is graph first (key figures with sparklines, a weekly and a daily chart, bars for sections and controls, the day-and-hour map, the cohort grid): every chart is a role=img
with a label that holds its numbers, every svg is named or hidden, and every chart sits in a unit with a "Show data" disclosure holding a table; a guarded row is a hatched stub that prints '<5 users', draws no length and no number; the page has no 'What changed' section and no chips while the stale-export banner stays; no user id anywhere; text contrast of at least 4.5:1 (3:1 for large text) with every disclosure open; every details element is a keyboard stop; bars stack their label above the bar at 390 px; the page uses no script; the empty state says
"No usage recorded yet" and shows no chart. The page is an Artifact fragment; the test wraps it the way kit.wrap does.

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


def live1_bodies() -> list:
    """One fictitious person, two visits on the first day of the data (a Monday, the week in progress): a glance on a wide window and a visit on a narrow one."""
    day = NOW.date()
    sess = {"vs": 5, "s": 0, "g": 1, "d": "l", "b": "aaa1111", "bt": 20759, "t": 498230, "lv": 0, "fa": 0}
    sess2 = {"vs": 105, "s": 0, "d": "s", "b": "aaa1111", "bt": 20759, "t": 498230, "lv": 0, "fa": 0}
    return [{"u": "u_synthetic_001", "v": 2, "first": day.isoformat(), "last": day.isoformat(), "w": {UR.sunday_key(day): {day.isoformat(): {"s0000001": sess, "s0000002": sess2}}}}]


def page_url(kind: str = "demo") -> str:
    """The wrapped page of a kind: the demo, an empty export, or v1 records only."""
    if kind not in _cache:
        if kind == "demo":
            agg = UR.aggregate(UR.demo_bodies(REF), as_of=AS_OF, now=NOW, demo=True, calendar=UR.parse_calendar(UR.demo_calendar(REF)))
        elif kind == "min1":
            agg = UR.aggregate(UR.demo_bodies(REF), as_of=AS_OF, now=NOW, demo=True, calendar=UR.parse_calendar(UR.demo_calendar(REF)), th={**UR.THRESHOLDS, "min_group": 1})
        elif kind == "live1":
            agg = UR.aggregate(live1_bodies(), as_of=NOW, now=NOW, th={**UR.THRESHOLDS, "min_group": 1})
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


@SUITE.test("usage_page_coverage_ribbon_is_visible_short_near_the_top_and_not_inside_a_details_element")
def _(t: T):
    for w in (1400, 390):
        ch = open_at(w)
        t.check(ch.js("(() => { const r = document.getElementById('coverage'); if (!r) return false; const b = r.getBoundingClientRect(); const cs = getComputedStyle(r); return b.height > 20 && b.top < 420 && cs.display !== 'none' && cs.visibility !== 'hidden' && !r.closest('details'); })()"), f"{w}: the ribbon is visible near the top, outside any details")
        t.check(ch.js("document.getElementById('coverage').textContent.includes('Pseudonymous, not anonymous') && document.getElementById('coverage').textContent.includes('Never used to rank or assess people or teams') && document.getElementById('coverage').textContent.includes('<5 users')"), f"{w}: the ribbon says what the governance is")
    ch = open_at(1400)
    t.check(ch.js("document.getElementById('coverage').getBoundingClientRect().height") < 75, "1400: the ribbon is two lines at most")
    ch = open_at(1400, "empty")
    t.check(ch.js("!!document.getElementById('coverage') && !document.getElementById('coverage').closest('details')"), "the ribbon is on the empty page too")
    ctx.chrome.viewport(1400, 900)


@SUITE.test("usage_page_headings_are_in_order_and_every_chart_is_named_and_has_its_table")
def _(t: T):
    for kind in ("demo", "v1", "empty"):
        ch = open_at(1400, kind)
        heads = ch.js("[...document.querySelectorAll('h1,h2,h3,h4')].map(h => +h.tagName[1])")
        t.check(heads[0] == 1 and heads.count(1) == 1 and all(b - a <= 1 for a, b in zip(heads, heads[1:])), f"{kind}: heading levels {heads}")
        t.check(ch.js("[...document.querySelectorAll('section[aria-labelledby]')].every(s => document.getElementById(s.getAttribute('aria-labelledby')))"), f"{kind}: every section is labelled by a heading that exists")
    for w in (1400, 390):
        ch = open_at(w)
        charts = ch.js("[...document.querySelectorAll('[role=img]')].map(c => ({label: (c.getAttribute('aria-label') || '').length, table: !!c.closest('.panel, #kpis') && !!c.closest('.panel, #kpis').querySelector('details.vd table tbody tr')}))")
        t.check(len(charts) >= 18 and all(c["label"] >= 30 and c["table"] for c in charts), f"{w}: every chart has a label with its numbers and a data table ({len(charts)} charts, bad {[c for c in charts if not (c['label'] >= 30 and c['table'])][:3]})")
        svgs = ch.js("[...document.querySelectorAll('svg')].map(s => s.getAttribute('aria-hidden') === 'true' || (s.getAttribute('role') === 'img' && (s.getAttribute('aria-label') || '').length > 10))")
        t.check(bool(svgs) and all(svgs), f"{w}: every svg is named (role=img with a label) or hidden ({len(svgs)})")
        t.check(ch.js("document.querySelectorAll('.kpis .kpi').length") == 5 and ch.js("document.querySelectorAll('.kpis .sparkwrap svg[role=img]').length") >= 3, f"{w}: five key figures with sparklines")
        t.check(ch.js("document.querySelectorAll('.plot').length") >= 2 and ch.js("document.querySelectorAll('.hbar').length") == 2 and ch.js("document.querySelectorAll('.ln2 path.l').length") >= 1, f"{w}: the weekly and daily charts, two hatched incomplete weeks, one line")
        t.check(ch.js("document.querySelectorAll('.hbars').length") >= 6 and ch.js("document.querySelectorAll('.hm .c').length") >= 40 and ch.js("document.querySelectorAll('.ch .cc').length") >= 5 and ch.js("document.querySelectorAll('.sb').length") >= 5, f"{w}: bars, the day-and-hour map, the cohort grid and stacked bars are drawn")
        t.check(ch.js("document.querySelectorAll('details.vd > summary').length") >= 12, f"{w}: the disclosures exist")
    t.check(ch.js("document.querySelectorAll('script').length - document.querySelectorAll('script[data-harness]').length") == 0, "the page has no script")
    ctx.chrome.viewport(1400, 900)


@SUITE.test("usage_page_the_page_is_graph_first_and_short_on_prose")
def _(t: T):
    ch = open_at(1400)
    order = ch.js("['coverage','kpis','trend','breakdowns','when','back','recording'].map(id => document.getElementById(id).getBoundingClientRect().top + scrollY)")
    t.check(order == sorted(order), f"the sections are in the analytics order {order}")
    t.check(ch.js("document.querySelector('#kpis').getBoundingClientRect().top < 360"), "the key figures start in the first screen")
    longp = ch.js("[...document.querySelectorAll('main p')].filter(p => !p.closest('details') && p.id !== 'governance' && !p.closest('#h-how') && p.getBoundingClientRect().height > 60 && !p.classList.contains('demo') && !p.classList.contains('warn') && !p.classList.contains('ribbon') && !p.closest('section.empty')).map(p => p.textContent.trim().slice(0, 50))")
    t.check(not longp, f"no paragraph above 2 short lines outside a disclosure: {longp}")
    ch = open_at(1400)
    text_chars = ch.js("[...document.querySelectorAll('main')].map(m => m.innerText.length)[0]")
    t.note(f"visible text: {text_chars} characters")


@SUITE.test("usage_page_has_no_what_changed_section_keeps_the_warning_and_the_growth_verdict")
def _(t: T):
    for w in (1400, 390):
        ch = open_at(w)
        t.check(ch.js("!document.getElementById('changed') && !document.querySelector('.chips, .chip, #checked, #nothing') && !document.body.innerText.includes('What changed since last report')"), f"{w}: no What changed section, chips or Checked ledger")
        t.check(ch.js("[...document.querySelectorAll('.warn')].some(w => w.textContent.includes('days old') && w.getBoundingClientRect().height > 0)"), f"{w}: the stale-export banner still shows for an old export")
        t.check(ch.js("(() => { const k = document.getElementById('kpis').getBoundingClientRect(), tr = document.getElementById('trend').getBoundingClientRect(); return tr.top >= k.bottom - 1 && tr.top - k.bottom < 120; })()"), f"{w}: the trend follows the key figures directly")
    t.check(ch.js("document.getElementById('growth').textContent.includes('Is adoption growing?')"), "the growth verdict sits under the weekly chart")
    ch = open_at(1400, "v1")
    t.check(ch.js("document.body.innerText.includes('not recorded in v1') || document.body.innerText.includes('Not recorded in v1')"), "the v1 page says what is not recorded")
    t.check(not ch.js("document.getElementById('kpi-glance')") and ch.js("!document.querySelector('.hm')"), "v1: no Glance scorecard and no day-and-hour map")
    ctx.chrome.viewport(1400, 900)


@SUITE.test("usage_page_a_small_group_is_a_hatched_stub_with_no_length_no_number_and_no_id_is_shown")
def _(t: T):
    for w in (1400, 390):
        ch = open_at(w)
        rows = ch.js("[...document.querySelectorAll('.hb')].filter(r => r.textContent.includes('<5 users')).map(r => ({stub: r.querySelectorAll('.gstub').length, w: r.querySelectorAll('.ht i[style]').length, val: r.querySelector('.hv').textContent}))")
        t.check(len(rows) >= 3 and all(r["stub"] == 1 and r["w"] == 0 and r["val"] == "<5 users" for r in rows), f"{w}: guarded rows {len(rows)}: a stub, no length, the text only")
        hatched = ch.js("document.querySelectorAll('.hm .c.h').length + document.querySelectorAll('.ch .cc.h').length + document.querySelectorAll('.sb .stubfull').length")
        t.check(hatched >= 3, f"{w}: hatched heatmap cells, cohort cells and bars: {hatched}")
        body = ch.js("document.body.innerText + document.documentElement.outerHTML")
        t.check("u_synthetic" not in body and "@" not in ch.js("document.body.innerText"), f"{w}: no user id or address on the page")
    t.check(ch.js("document.querySelector('#how summary').textContent") == "What is counted and what is not", "the measurement note is there")
    t.check(ch.js("document.getElementById('governance').textContent.includes('Pseudonymous, not anonymous')"), "the governance text is visible")


@SUITE.test("usage_page_device_is_one_of_the_scorecards_in_the_same_row_and_visible_without_a_disclosure")
def _(t: T):
    for w in (1400, 390):
        ch = open_at(w)
        t.check(ch.js("(() => { const d = document.getElementById('kpi-device'); if (!d) return false; const b = d.getBoundingClientRect(); return b.height > 60 && d.parentElement.classList.contains('kpis') && !d.closest('details') && getComputedStyle(d).display !== 'none'; })()"), f"{w}: Device is a scorecard inside the Key figures row, not inside a disclosure")
        t.check(ch.js("!document.getElementById('device') && document.querySelectorAll('.device').length") == 0, f"{w}: no separate device widget")
        t.check(ch.js("(() => { const k = [...document.querySelectorAll('.kpis .kpi')].map(c => ({h: !!c.querySelector('h3'), fig: !!c.querySelector('.fig'), sp: !!c.querySelector('.sp')})); return k.length === 5 && k.every(c => c.h && c.fig && c.sp); })()"), f"{w}: the Device card has the same anatomy as the others (title, value, sparkline area)")
        if w == 1400:
            t.check(ch.js("(() => { const r = [...document.querySelectorAll('.kpis .kpi')].map(c => Math.round(c.getBoundingClientRect().top)); return new Set(r).size === 1; })()"), "1400: the five scorecards are in one row")
        txt = ch.js("document.getElementById('kpi-device').innerText")
        t.check(("Desktop" in txt or "Phone" in txt) and "visit" in txt and "%" in txt, f"{w}: the card says the classes, shares and visits in words: {txt[:120]!r}")
        t.check(ch.js("(() => { const c = document.getElementById('kpi-device'); const s = c.querySelector('svg[role=img]'); const b = s.getBoundingClientRect(); return !!s && s.getAttribute('aria-label').startsWith('Device split of ') && b.width >= 72 && b.height >= 72 && c.querySelectorAll('.dlg li').length >= 1 && c.querySelectorAll('circle.dseg').length >= 1; })()"), f"{w}: the Device card holds the donut (an svg role=img with its summary, at least 72 px) and a legend")
        t.check(ch.js("(() => { const c = document.getElementById('kpi-device'); const d = c.querySelector('.donut').getBoundingClientRect(); return d.right <= c.getBoundingClientRect().right + 0.5 && c.querySelector('.dlg').getBoundingClientRect().right <= c.getBoundingClientRect().right + 0.5; })()"), f"{w}: the donut and its legend stay inside the card")
        t.check(not ch.js("document.getElementById('kpi-glance')") and "Glance visits" not in ch.js("document.getElementById('kpis').innerText"), f"{w}: the Glance scorecard is gone from Key figures")
        t.check(ch.js("document.querySelector('#kpi-device svg[role=img]').getBoundingClientRect().width") >= 110, f"{w}: the donut is at least 110 px")
        if w == 1400:
            t.check(ch.js("(() => { const h = [...document.querySelectorAll('.kpis .kpi')].map(c => Math.round(c.getBoundingClientRect().height)); return new Set(h).size === 1; })()"), "1400: the Device card is as tall as its neighbours")
            t.check(ch.js("(() => { const d = document.getElementById('kpi-device').getBoundingClientRect().width, n = document.getElementById('kpi-new').getBoundingClientRect().width; return d > 1.8 * n && d < 2.2 * n; })()"), "1400: the Device card is twice as wide as a neighbour")
            t.check(ch.js("(() => { const c = document.getElementById('kpi-device'), d = c.querySelector('.donut').getBoundingClientRect(), l = c.querySelector('.dlg').getBoundingClientRect(); return l.left >= d.right - 1 && Math.abs((l.top + l.height / 2) - (d.top + d.height / 2)) < d.height; })()"), "1400: the legend sits beside the donut")
        t.check("not device type" in ch.js("document.getElementById('device-caveat').innerText"), f"{w}: the caveat is printed under Key figures")
        t.check(ch.js("document.documentElement.scrollWidth - document.documentElement.clientWidth") <= 0 and ch.js("document.getElementById('kpi-device').getBoundingClientRect().right <= innerWidth + 1"), f"{w}: no sideways scroll")
        t.check(ch.js("!!document.querySelector('#kpis details table#device-table')"), f"{w}: the table equivalent is behind Show data")
    ctx.chrome.viewport(1400, 900)


@SUITE.test("usage_page_key_figures_show_their_values_when_there_is_only_the_week_in_progress")
def _(t: T):
    for w in (1400, 390):
        ch = open_at(w, "live1")
        t.check(not ch.console_errors(), f"{w}: console {ch.console_errors()[:2]}")
        t.check(ch.js("document.documentElement.scrollWidth - document.documentElement.clientWidth") <= 0, f"{w}: sideways scroll")
        k = ch.js("document.getElementById('kpis').innerText")
        t.check("Too early" not in k and "Not comparable" not in k and "Recording rules changed" not in k and "<5 users" not in k, f"{w}: no empty scorecard: {k[:200]!r}")
        t.check(ch.js("document.querySelector('#kpi-people .fig').innerText") == "1" and ch.js("document.querySelector('#kpi-device .fig').innerText").startswith("Desktop 50%") and "Device split of 2 visits: Desktop 50%, Phone 50%" in ch.js("document.querySelector('#kpi-device svg').getAttribute('aria-label')"), f"{w}: the numbers of the data to date")
        t.check("Data starts" in ch.js("document.getElementById('kpi-note').innerText") and "so far" in ch.js("document.getElementById('kpi-note').innerText").lower(), f"{w}: one line says why there is no comparison")
    ctx.chrome.viewport(1400, 900)


@SUITE.test("usage_page_week_so_far_block_sits_in_the_weekly_panel_with_its_sentence_and_figures_and_fits_the_width")
def _(t: T):
    for kind in ("demo", "live1"):
        a = (UR.aggregate(UR.demo_bodies(REF), as_of=AS_OF, now=NOW, demo=True, calendar=UR.parse_calendar(UR.demo_calendar(REF))) if kind == "demo"
             else UR.aggregate(live1_bodies(), as_of=NOW, now=NOW, th={**UR.THRESHOLDS, "min_group": 1}))
        title, rows = UR.wtd_title(a["wtd"]), UR.wtd_rows(a["wtd"])
        for w in (1400, 390):
            ch = open_at(w, kind)
            t.check(ch.js("!!document.querySelector('#p-weeks #wtd')"), f"{kind} {w}: the block is inside the weekly panel")
            t.check(ch.js("document.querySelector('#wtd .cap').innerText") == title, f"{kind} {w}: the sentence is not {title!r}")
            got = ch.js("[...document.querySelectorAll('#wtd-table tbody tr')].map(r => [...r.children].map(c => c.innerText))")
            t.check(got == [[n, c, p_, d or "-"] for n, c, p_, d in rows], f"{kind} {w}: the rows {got} against {rows}")
            t.check(ch.js("(() => { const b = document.getElementById('wtd').getBoundingClientRect(), p = document.getElementById('p-weeks').getBoundingClientRect(); return b.left >= p.left - 1 && b.right <= p.right + 1; })()"), f"{kind} {w}: the block fits the panel")
            t.check(ch.js("document.documentElement.scrollWidth - document.documentElement.clientWidth") <= 0, f"{kind} {w}: sideways scroll")
            t.check(ch.js("document.getElementById('wtd').compareDocumentPosition(document.getElementById('p-days')) & Node.DOCUMENT_POSITION_FOLLOWING") > 0, f"{kind} {w}: before the daily chart")
    ctx.chrome.viewport(1400, 900)


@SUITE.test("usage_page_min_group_1_shows_small_numbers_hatches_nothing_and_says_the_setting")
def _(t: T):
    for w in (1400, 390):
        ch = open_at(w, "min1")
        t.check(not ch.console_errors(), f"{w}: console {ch.console_errors()[:2]}")
        t.check(ch.js("document.documentElement.scrollWidth - document.documentElement.clientWidth") <= 0, f"{w}: sideways scroll")
        t.check(ch.js("document.querySelectorAll('.gstub, .hm .c.h, .ch .cc.h, .sb .stubfull').length") == 0 and "<1 users" not in ch.js("document.body.innerText") and "<5 users" not in ch.js("document.body.innerText"), f"{w}: nothing is hatched or withheld")
        t.check("Small groups are shown as they are" in ch.js("document.getElementById('coverage').innerText") and "keep this page private" in ch.js("document.getElementById('coverage').innerText"), f"{w}: the ribbon says the setting")
        ch.js("document.querySelectorAll('details').forEach(d => d.open = true)")
        bad = ch.js(CONTRAST_JS)
        t.check(not bad, f"{w}: low contrast {bad[:3]}")
    ctx.chrome.viewport(1400, 900)


@SUITE.test("usage_page_bars_stack_their_label_above_the_bar_in_a_narrow_panel")
def _(t: T):
    ch = open_at(390)
    t.check(ch.js("(() => { const r = document.querySelector('#p-sections .hb'); const l = r.querySelector('.hl').getBoundingClientRect(), b = r.querySelector('.ht').getBoundingClientRect(); return b.top >= l.bottom - 1 && b.width > 220; })()"), "390: the bar sits under its label and is wide")
    ch = open_at(1400)
    t.check(ch.js("(() => { const r = document.querySelector('#p-sections .hb'); const l = r.querySelector('.hl').getBoundingClientRect(), b = r.querySelector('.ht').getBoundingClientRect(); return b.left >= l.right - 1; })()"), "1400: the bar sits beside its label")
    t.check(ch.js("[...document.querySelectorAll('.plot, .hbars, .hm, .ch')].every(e => e.getBoundingClientRect().right <= innerWidth + 1)"), "1400: every chart fits")
    ctx.chrome.viewport(1400, 900)


@SUITE.test("usage_page_empty_state_says_no_usage_recorded_yet_and_shows_no_demo_numbers")
def _(t: T):
    for w in (1400, 390):
        ch = open_at(w, "empty")
        t.check(ch.js("document.querySelector('#empty h2').textContent") == "No usage recorded yet", f"{w}: the plain statement")
        t.check(ch.js("document.querySelectorAll('#empty li').length") == 3, f"{w}: three steps say what to do next")
        t.check(ch.js("!document.getElementById('demo-banner') && !document.querySelector('.kpis') && !document.querySelector('[role=img]') && !document.querySelector('.plot')"), f"{w}: no demo banner, key figures or chart")
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
    t.check(ch.js("document.activeElement.tagName") == "SUMMARY" and n >= 12, "Tab reaches a summary first")
    t.check(ch.js("getComputedStyle(document.activeElement).outlineStyle") != "none", "the focus ring is drawn")


if __name__ == "__main__":
    sys.exit(kit.cli(SUITE, __doc__))
