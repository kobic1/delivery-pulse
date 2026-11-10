#!/usr/bin/env python3
"""The Back to Top button is easy to see and to hit.

It appears after a scroll up from deep in the page (the behaviour is tested in the harness). Here its look and place, at 1400 px, at 1800 px (a wide window) and at 390 px:
solid blue with white text (contrast of at least 4.5:1), at least 48 px tall and wide, a visible label on a desktop and an icon only on a phone (the accessible name stays), 24 px from the bottom right corner on a desktop
(16 px right, 20 px bottom on a phone), in the corner of the window at every width, also on a wide screen. A self-test puts the old small white button back and the check must fail.

    python3 backtotop_check.py [--live] [--only NAME]
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

SUITE = kit.Suite("Delivery Pulse Back to Top")

READ = """(async () => {
  window.scrollTo(0, innerHeight * 3); await new Promise(r => setTimeout(r, 400)); window.scrollBy(0, -60); await new Promise(r => setTimeout(r, 600));
  const b = document.getElementById('totop'), r = b.getBoundingClientRect(), c = getComputedStyle(b), lab = b.querySelector('.tt').getBoundingClientRect();
  const col = document.querySelector('.gutter'), cr = col ? col.getBoundingClientRect() : null;
  const rgb = s => (s.match(/[\\d.]+/g) || []).slice(0, 3).map(Number);
  return {on: b.classList.contains('on'), hidden: b.hidden, w: r.width, h: r.height, right: innerWidth - r.right, bottom: innerHeight - r.bottom, left: r.left,
    bg: rgb(c.backgroundColor), fg: rgb(c.color), labelVisible: lab.width > 10 && lab.height > 6, name: b.getAttribute('aria-label'), colRight: cr ? cr.right : null, vw: innerWidth}; })()"""


def lum(rgb):
    f = lambda v: (v / 255) / 12.92 if v / 255 <= 0.03928 else (((v / 255) + 0.055) / 1.055) ** 2.4
    r, g, b = (f(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def page(template=None):
    data = MS.make(MS.il_today())
    data["build"] = {"sha": "abc1234", "dirty": False, "at": "2026-01-01T00:00+02:00"}
    return ctx.write(kit.wrap(MS.render_page(data, template) if template else MS.render_page(data, ctx.template)), "totop")


def read(url, vp):
    ch = ctx.chrome
    ch.cmd("Emulation.setTimezoneOverride", timezoneId="Asia/Jerusalem")
    ch.viewport(*vp, mobile=vp[0] < 500)
    ch.goto(url + "#r=27.1")
    assert kit.wait_ready(ch), "the page did not draw: " + str(ch.console_errors()[:2])
    time.sleep(1.4)                                              # the page ignores scrolls for a moment after a draw
    return ch.js(READ)


def problems(r, vp):
    bad, phone = [], vp[0] < 500
    if not r["on"] or r["hidden"]:
        return [f"{vp[0]}px: the button is not shown after a scroll up ({r})"]
    if r["h"] < 47.5 or r["w"] < 47.5:
        bad.append(f"{vp[0]}px: the button is {r['w']:.0f} x {r['h']:.0f} px, expected at least 48 x 48")
    cr = contrast(r["fg"], r["bg"])
    if cr < 4.5:
        bad.append(f"{vp[0]}px: text {r['fg']} on {r['bg']} has contrast {cr:.1f}:1, expected 4.5:1 or more")
    if not (r["bg"][2] > r["bg"][0] + 100):
        bad.append(f"{vp[0]}px: the fill {r['bg']} is not the blue of the page")
    if r["name"] != "Back to Top":
        bad.append(f"{vp[0]}px: the accessible name is {r['name']!r}")
    if phone:
        if r["labelVisible"] or abs(r["w"] - 48) > 1:
            bad.append(f"{vp[0]}px phone: expected an icon-only 48 px button (label visible {r['labelVisible']}, width {r['w']:.0f})")
        if abs(r["right"] - 16) > 1 or abs(r["bottom"] - 20) > 1:
            bad.append(f"{vp[0]}px phone: {r['right']:.0f} px from the right and {r['bottom']:.0f} from the bottom, expected 16 and 20")
    else:
        if not r["labelVisible"]:
            bad.append(f"{vp[0]}px: the label is not visible on a desktop")
        if abs(r["bottom"] - 24) > 1:
            bad.append(f"{vp[0]}px: {r['bottom']:.0f} px from the bottom, expected 24")
        if abs(r["right"] - 24) > 1:
            bad.append(f"{vp[0]}px: {r['right']:.0f} px from the right, expected 24 (the corner of the window at every width)")
    return bad


@SUITE.test("back_to_top_is_big_blue_and_placed_clear_of_the_content")
def _(t: T):
    url = page()
    for vp in ((1400, 900), (1800, 900), (390, 844)):
        r = read(url, vp)
        bad = problems(r, vp)
        t.check(not bad, f"{bad}")
        t.note(f"{vp[0]}px: {r['w']:.0f} x {r['h']:.0f}, right {r['right']:.0f}, bottom {r['bottom']:.0f}, label {r['labelVisible']}")
    t.check(not ctx.chrome.console_errors(), f"console error {ctx.chrome.console_errors()[:2]}")


@SUITE.test("selftest_the_check_fails_on_the_old_small_white_button")
def _(t: T):
    src = ctx.template.read_text(encoding="utf-8")
    new = "height:48px; padding:0 20px 0 16px;"
    if new not in src:
        raise kit.Skip("this template has no new Back to Top button to take out")
    old = src.replace(new, "height:36px; padding:0 12px;").replace("color:#fff; background:var(--blue-ink); border:0;", "color:var(--ink); background:#fff; border:1px solid var(--ctl);", 1)
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(old)
    url = page(Path(f.name))
    Path(f.name).unlink()
    bad = problems(read(url, (1400, 900)), (1400, 900))
    t.check(bool(bad), "the check passed on the old small white button: it is blind")


if __name__ == "__main__":
    sys.exit(kit.cli(SUITE, __doc__))
