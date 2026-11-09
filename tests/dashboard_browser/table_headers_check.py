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


if __name__ == "__main__":
    sys.exit(kit.cli(SUITE, __doc__))
