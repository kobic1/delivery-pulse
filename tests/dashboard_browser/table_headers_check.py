#!/usr/bin/env python3
"""Every table that can be longer than a screen keeps its header row in view while the table is scrolled.

The fictitious page is opened with everything that can grow expanded (every Cycles row, every "Show data" panel, every expandable table). For each visible table with 8 or more body rows:
  * it sits in a scroll box (`.tablewrap`) that is no taller than the window and scrolls vertically;
  * its header cells are position:sticky;
  * after the box is scrolled by 300 px (when it has more to scroll) the header row is still at the top of the box and in view.
Checked at 1400 and 390 px. A self-test removes the frozen-header box from the page and the check must fail.

    python3 table_headers_check.py [--live] [--only NAME]
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kit                                                                          # noqa: E402
import make_synthetic as MS                                                         # noqa: E402
from kit import ctx, T                                                              # noqa: E402

SUITE = kit.Suite("Delivery Pulse table headers")
MIN_ROWS = 8

AUDIT = """(() => {
  document.querySelectorAll('.cytgl[aria-expanded=false]').forEach(b => b.click());
  document.querySelectorAll('details.vd, details.more').forEach(d => { d.open = true; });
  const out = [];
  document.querySelectorAll('table').forEach(t => {
    if (t.parentElement.closest('table') || !t.offsetParent) return;
    const rows = t.querySelectorAll('tbody tr').length; if (rows < %d) return;
    const w = t.closest('.tablewrap'), th = t.querySelector('thead th');
    const name = (t.id || (t.querySelector('caption') || {textContent: ''}).textContent.slice(0, 40) || t.className).trim();
    const o = {name, rows, wrap: !!w, sticky: th ? getComputedStyle(th).position : null};
    if (w) {
      const c = getComputedStyle(w); o.maxh = c.maxHeight; o.oy = c.overflowY; o.boxh = Math.round(w.getBoundingClientRect().height); o.more = w.scrollHeight > w.clientHeight + 40;
      if (o.more && th) { w.scrollTop = 300; w.dispatchEvent(new Event('scroll')); const wr = w.getBoundingClientRect(), tr = th.getBoundingClientRect(); o.topgap = Math.round(tr.top - wr.top); o.inview = tr.bottom > wr.top && tr.top < wr.bottom; w.scrollTop = 0; }
    }
    out.push(o);
  });
  return {win: window.innerHeight, tables: out}; })()""" % MIN_ROWS


def audit(url, vp):
    ch = ctx.chrome
    ch.cmd("Emulation.setTimezoneOverride", timezoneId="Asia/Jerusalem")
    ch.viewport(*vp, mobile=vp[0] < 500)
    ch.goto(url + "#r=27.1")
    assert kit.wait_ready(ch), "the page did not draw: " + str(ch.console_errors()[:2])
    time.sleep(0.8)
    r = ch.js(AUDIT)
    time.sleep(0.2)
    return r


def problems(r):
    bad = []
    for x in r["tables"]:
        tag = f"{x['name']} ({x['rows']} rows)"
        if not x["wrap"]:
            bad.append(f"{tag}: not in a scroll box")
            continue
        if x["sticky"] != "sticky":
            bad.append(f"{tag}: the header is {x['sticky']}, not sticky")
        if x["maxh"] == "none" or x["oy"] not in ("auto", "scroll") or x["boxh"] > r["win"] + 2:
            bad.append(f"{tag}: the box is {x['boxh']}px tall (max {x['maxh']}, overflow {x['oy']}) in a {r['win']}px window")
        if x.get("more") and (x.get("topgap") is None or abs(x["topgap"]) > 2 or not x.get("inview")):
            bad.append(f"{tag}: after scrolling the header is {x.get('topgap')}px from the top of the box")
    return bad


def page(template=None):
    data = MS.make(MS.il_today())
    data["build"] = {"sha": "abc1234", "dirty": False, "at": "2026-01-01T00:00+02:00"}
    return ctx.write(kit.wrap(MS.render_page(data, template) if template else MS.render_page(data, ctx.template)), "thead")


@SUITE.test("long_tables_keep_their_header_row_in_view_at_desktop_and_phone_width")
def _(t: T):
    url = page()
    for vp in ((1400, 900), (390, 800)):
        r = audit(url, vp)
        t.check(len(r["tables"]) >= 8, f"{vp[0]}px: only {len(r['tables'])} long tables were found, the audit is blind")
        bad = problems(r)
        t.check(not bad, f"{vp[0]}px: {len(bad)} tables: {bad[:4]}")
        t.note(f"{vp[0]}px: " + ", ".join(f"{x['name'][:18]}={x['rows']}" for x in r["tables"]))


@SUITE.test("selftest_the_check_fails_when_the_frozen_header_boxes_are_removed")
def _(t: T):
    src = ctx.template.read_text(encoding="utf-8")
    if "tablewrap freeze" not in src:
        raise kit.Skip("this template has no frozen-header boxes to take out")
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(src.replace("tablewrap freeze", "tablewrap"))
    url = page(Path(f.name))
    Path(f.name).unlink()
    bad = problems(audit(url, (1400, 900)))
    t.check(bool(bad), "the check passed on a page without the frozen-header boxes: it is blind")


FOLLOW = """(async (state) => {
  const click = sel => document.querySelectorAll(sel).forEach(b => b.click());
  click(state === 'collapsed' ? '[data-xtact=colall], [data-cyact=colall]' : '[data-xtact=expall], [data-cyact=expall]');
  await new Promise(r => setTimeout(r, 200));
  const out = [];
  for (const box of document.querySelectorAll('.tablewrap.tall, .tablewrap.freeze, details.vd .tablewrap')) {
    const t = box.querySelector('table'); if (!t || !box.offsetParent || t.querySelectorAll('tbody tr:not([hidden])').length < 4) continue;
    const head = t.querySelector('thead'), foot = t.querySelector('tfoot'), fh = foot ? foot.offsetHeight : 0;
    const r0 = box.getBoundingClientRect(); if (r0.height < head.offsetHeight + fh + 120) continue;
    const inner = box.scrollHeight > box.clientHeight + 1;
    window.scrollTo(0, window.scrollY + r0.top - STICK + Math.min(120, Math.floor(r0.height / 3)));
    await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(r, 60))));
    const r = box.getBoundingClientRect(), h = head.querySelector('th').getBoundingClientRect();
    const want = Math.min(STICK, r.bottom - head.offsetHeight - fh);
    out.push({name: t.id || t.className, inner, boxTop: Math.round(r.top), stick: STICK, headTop: Math.round(h.top), want: Math.round(want), shown: h.bottom > 0 && h.top < innerHeight});
  }
  return out; })"""


@SUITE.test("headers_follow_the_page_under_the_sticky_bars_when_tables_are_collapsed_or_expanded")
def _(t: T):
    url = page()
    ch = ctx.chrome
    for vp in ((1400, 800), (390, 800)):
        for state in ("collapsed", "expanded"):
            ch.cmd("Emulation.setTimezoneOverride", timezoneId="Asia/Jerusalem")
            ch.viewport(*vp, mobile=vp[0] < 500)
            ch.goto(url + "#r=27.1")
            assert kit.wait_ready(ch), "the page did not draw: " + str(ch.console_errors()[:2])
            time.sleep(0.8)
            rows = ch.js(f"{FOLLOW}({state!r})")
            t.check(len(rows) >= 4, f"{vp[0]}px {state}: only {len(rows)} long tables were measured, the check is blind")
            if state == "collapsed":
                t.check(any(not x["inner"] for x in rows), f"{vp[0]}px collapsed: every box still scrolls inside, so the case of a table with nothing to scroll was never measured")
            bad = [x for x in rows if abs(x["headTop"] - x["want"]) > 3 or not x["shown"]]
            t.check(not bad, f"{vp[0]}px {state}: {len(bad)} of {len(rows)} headers are not at the sticky bars after the page scrolled: {bad[:3]}")
            t.note(f"{vp[0]}px {state}: " + ", ".join(f"{x['name'][:14]}={'in' if x['inner'] else 'flat'}" for x in rows[:8]))


@SUITE.test("selftest_the_follow_check_fails_when_the_headers_do_not_follow_the_page")
def _(t: T):
    src = ctx.template.read_text(encoding="utf-8")
    marker = "function followHeads() {\n  headRaf = 0;"
    if marker not in src:
        raise kit.Skip("this template has no header-follow code to take out")
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(src.replace(marker, marker + " return;"))
    url = page(Path(f.name))
    Path(f.name).unlink()
    ch = ctx.chrome
    ch.cmd("Emulation.setTimezoneOverride", timezoneId="Asia/Jerusalem")
    ch.viewport(1400, 800, mobile=False)
    ch.goto(url + "#r=27.1")
    assert kit.wait_ready(ch)
    time.sleep(0.8)
    rows = ch.js(f"{FOLLOW}('collapsed')")
    bad = [x for x in rows if abs(x["headTop"] - x["want"]) > 3 or not x["shown"]]
    t.check(bool(bad), "the check passed with the header-follow code switched off: it is blind")


NESTED = """(async () => {
  const click = sel => document.querySelectorAll(sel).forEach(b => b.click());
  click('[data-cyact=expall]');
  await new Promise(r => setTimeout(r, 250));
  const box = document.querySelector('#cy-ovtable') && document.querySelector('#cy-ovtable').closest('.tablewrap');
  if (!box) return {found: false};
  const inner = [...box.querySelectorAll('table.cyepl thead th')].filter(th => th.offsetParent);
  if (!inner.length) return {found: true, nested: 0};
  box.style.maxHeight = '260px';                                  // the real table is long enough to scroll inside its box; the synthetic one needs a short box to do the same
  const r0 = box.getBoundingClientRect();
  window.scrollTo(0, window.scrollY + r0.top - STICK);
  box.scrollTop = 300;
  await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(r, 80))));
  const outer = [...box.querySelectorAll('#cy-ovtable > thead th')].map(th => th.getBoundingClientRect());
  const oTop = Math.min(...outer.map(r => r.top)), oBot = Math.max(...outer.map(r => r.bottom));
  const clash = inner.map(th => th.getBoundingClientRect()).filter(r => r.bottom > oTop + 1 && r.top < oBot - 1).length;
  return {found: true, nested: inner.length, scrolled: box.scrollTop > 0, clash, position: getComputedStyle(inner[0]).position};
})()"""


def nested_rows(url):
    ch = ctx.chrome
    ch.cmd("Emulation.setTimezoneOverride", timezoneId="Asia/Jerusalem")
    ch.viewport(1400, 800, mobile=False)
    ch.goto(url + "#r=27.1")
    assert kit.wait_ready(ch), "the page did not draw: " + str(ch.console_errors()[:2])
    time.sleep(0.8)
    return ch.js(NESTED)


@SUITE.test("the_epic_list_inside_a_pod_row_never_draws_its_header_over_the_table_header")
def _(t: T):
    r = nested_rows(page())
    t.check(r.get("found"), "the Projects, Teams and Pods table was not on the page, the check is blind")
    t.check(r.get("nested", 0) >= 1, "no epic list opened inside the table, the check is blind")
    t.check(r.get("scrolled"), "the table box did not scroll inside, the check is blind")
    t.check(r.get("position") == "static", f"the nested epic list header is {r.get('position')}, not static")
    t.check(r.get("clash") == 0, f"{r.get('clash')} nested epic-list header cells sit on the table's own header row")


@SUITE.test("selftest_the_nested_header_check_fails_when_the_nested_header_is_made_sticky_again")
def _(t: T):
    src = ctx.template.read_text(encoding="utf-8")
    marker = ".tablewrap.freeze table.cyepl thead th, "
    if marker not in src:
        raise kit.Skip("this template has no rule for the nested epic list header to take out")
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(src.replace(marker, ".nope-never table.cyepl thead th, "))
    url = page(Path(f.name))
    Path(f.name).unlink()
    r = nested_rows(url)
    t.check(r.get("clash"), "the check passed with the nested header sticky: it is blind")


if __name__ == "__main__":
    sys.exit(kit.cli(SUITE, __doc__))
