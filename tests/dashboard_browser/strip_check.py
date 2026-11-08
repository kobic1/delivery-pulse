#!/usr/bin/env python3
"""The Section Strip lists no AI Adoption entry: Efficiency stands for it (on a wide screen the two sections sit side by side; on a phone they stack and the AI Adoption chart is reached by scrolling or by the skip link).

Asserted at 1400 and 390 px: the strip names the sections without AI Adoption; reading the AI Adoption section keeps Efficiency as the current entry (never another one); the 'Skip to AI Adoption'
link of the Efficiency section still lands on the AI Adoption heading; no console error.

    python3 strip_check.py [--live] [--only NAME]
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kit                                                                          # noqa: E402
import make_synthetic as MS                                                         # noqa: E402
from kit import ctx, T                                                              # noqa: E402

SUITE = kit.Suite("Delivery Pulse section strip")


def load(vp):
    ch = ctx.chrome
    data = MS.make(MS.il_today())
    data["build"] = {"sha": "abc1234", "dirty": False, "at": "2026-01-01T00:00+02:00"}
    url = ctx.write(kit.wrap(MS.render_page(data)), "strip")
    ch.cmd("Emulation.setTimezoneOverride", timezoneId="Asia/Jerusalem")
    ch.viewport(*vp, mobile=vp[0] < 500)
    ch.goto(url)
    assert kit.wait_ready(ch), "the page did not draw: " + str(ch.console_errors()[:2])
    time.sleep(0.4)
    return ch


def names(ch):
    return ch.js("[...document.querySelectorAll('#seclist a')].map(a => a.textContent.replace(/ \\(\\d+\\)$/, ''))")


def current(ch):
    return ch.js("(() => { const a = document.querySelector('#seclist a[aria-current]'); return a ? a.textContent.replace(/ \\(\\d+\\)$/, '') : null; })()")


@SUITE.test("the_strip_has_no_ai_adoption_entry_and_efficiency_stays_current_while_it_is_read")
def _(t: T):
    for vp in ((1400, 900), (390, 844)):
        ch = load(vp)
        n = names(ch)
        t.check("AI Adoption" not in n and "Efficiency" in n and n.index("Efficiency") + 1 < len(n) and n[n.index("Efficiency") + 1] == "Quality", f"{vp[0]} px: the strip is {n}")
        ch.js("const h = document.getElementById('h-ai'); window.scrollTo(0, h.getBoundingClientRect().top + window.scrollY - 220); window.dispatchEvent(new Event('scrollend'))")      # the heading a little below the sticky bars: the section is being read
        time.sleep(0.9)
        t.check(current(ch) == "Efficiency", f"{vp[0]} px: reading AI Adoption makes {current(ch)!r} the current entry, expected Efficiency")
        ch.js("window.scrollTo(0, 0)"); time.sleep(0.3)
        ch.js("document.querySelector('a.skip[data-skip=\"h-ai\"]').click()")
        time.sleep(1.0)
        top = ch.js("document.getElementById('h-ai').getBoundingClientRect().top")
        t.check(0 <= top < 600, f"{vp[0]} px: the skip link did not bring the AI Adoption heading into view (top {top})")
        t.check(not ch.console_errors(), f"{vp[0]} px: console error {ch.console_errors()[:2]}")


if __name__ == "__main__":
    sys.exit(kit.cli(SUITE, __doc__))
