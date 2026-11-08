#!/usr/bin/env python3
"""The 'Even pace' label of the burnup never overlaps another text of the chart (the 'Done N · +M vs even pace' readout, the Scope label, the window labels), wherever today falls in the release.

The release window of the fictitious data is shifted so the as-of day sits at many points of the release (before it starts, early, middle, late, at the end), with Both cycles, Delivery Cycle 1 and
Delivery Cycle 2, at a wide and a narrow window. In each drawing 'Even pace' overlaps no other text. Other label pairs that touch when today is near the end of a window are counted and reported, not failed.

    python3 burnup_labels_check.py [--live] [--only NAME]
"""
from __future__ import annotations

import datetime as dt
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kit                                                                          # noqa: E402
import make_synthetic as MS                                                         # noqa: E402
from kit import ctx, T                                                              # noqa: E402

SUITE = kit.Suite("Delivery Pulse burnup labels")
SHIFTS = (-10, 0, 7, 14, 21, 28, 35, 42, 49, 56, 63, 70, 77)
READ = """(() => {
  const svg = document.querySelector('#burnup svg'); if (!svg) return null;
  const items = [...svg.querySelectorAll('text')].filter(t => t.textContent.trim() && getComputedStyle(t).display !== 'none').map(t => { const r = t.getBoundingClientRect(); return {t: t.textContent.trim(), l: r.left, r: r.right, top: r.top, b: r.bottom}; });
  const bad = [];
  for (let i = 0; i < items.length; i++) for (let j = i + 1; j < items.length; j++) {
    const a = items[i], b = items[j], w = Math.min(a.r, b.r) - Math.max(a.l, b.l), h = Math.min(a.b, b.b) - Math.max(a.top, b.top);
    if (w > 2 && h > 3) bad.push(a.t + ' / ' + b.t);
  }
  return {n: items.length, bad};
})()"""


def page(shift: int) -> str:
    data = MS.make(MS.il_today())
    data["build"] = {"sha": "abc1234", "dirty": False, "at": "2026-01-01T00:00+02:00"}
    s, e = data["windows"][data["current"]]
    mv = lambda d: (dt.date.fromisoformat(d) - dt.timedelta(days=shift)).isoformat()
    data["windows"][data["current"]] = [mv(s), mv(e)]
    return ctx.write(kit.wrap(MS.render_page(data)), f"bu{shift}")


@SUITE.test("no_two_texts_of_the_burnup_overlap_wherever_today_falls")
def _(t: T):
    ch = ctx.chrome
    ch.cmd("Emulation.setTimezoneOverride", timezoneId="Asia/Jerusalem")
    problems, others, drawn = [], 0, 0
    for width in (1400, 390):
        ch.viewport(width, 900, mobile=width < 500)
        for shift in SHIFTS:
            url = page(shift)
            for dc in ("", "&dc=1", "&dc=2"):
                ch.goto(url + "#r=27.1" + dc)
                if not kit.wait_ready(ch):
                    problems.append(f"{width}px shift {shift} {dc}: the page did not draw")
                    continue
                time.sleep(0.25)
                r = ch.js(READ)
                if not r:
                    continue
                drawn += 1
                mine = [b for b in r["bad"] if "Even pace" in b]
                others += len(r["bad"]) - len(mine)
                if mine:
                    problems.append(f"{width}px, today {shift} days later in the window, {dc or 'both cycles'}: {mine[:2]}")
    t.check(drawn >= 30, f"only {drawn} drawings were checked")
    t.check(not problems, f"{len(problems)} drawings have the Even pace label on another text: {problems[:4]}")
    t.note(f"{drawn} drawings checked; other label pairs that touch near the end of a window: {others}")


if __name__ == "__main__":
    sys.exit(kit.cli(SUITE, __doc__))
