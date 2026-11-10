#!/usr/bin/env python3
"""The CFB Fixed and Regressions chart marks the period that is current in every grouping.

Release: the selected release is solid, the others lighter, its table row highlighted (as before). Quarter and Month: the quarter or month that is running now is marked the same way: its bars solid with a dashed
outline, an asterisk on its label, its table row highlighted, and every other bar lighter. Checked at 1400 px on the fictitious page. A self-test puts the old rule back (the running period is not the selected one) and the check must fail.

    python3 cfb_period_check.py [--live] [--only NAME]
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

SUITE = kit.Suite("Delivery Pulse CFB current period")

READ = """(() => {
  const bars = [...document.querySelectorAll('#cfb-chart svg rect[fill="#025AFB"]')].map(r => ({op: r.getAttribute('opacity'), dash: !!r.getAttribute('stroke-dasharray')}));
  const regs = [...document.querySelectorAll('#cfb-chart svg rect[fill="#C77700"]')].map(r => ({op: r.getAttribute('opacity'), dash: !!r.getAttribute('stroke-dasharray')}));
  const labels = [...document.querySelectorAll('#cfb-chart svg text')].filter(t => t.getAttribute('fill') === '#4A4F57').map(t => t.textContent);
  const rows = [...document.querySelectorAll('#cfb-table tbody tr:not(.total)')].map(r => ({th: r.querySelector('th').textContent, sel: r.classList.contains('sel')}));
  return {mode: state.cfbGroup, rel: state.release, bars, regs, labels, rows}; })()"""


def page(template=None):
    data = MS.make(MS.il_today())
    data["build"] = {"sha": "abc1234", "dirty": False, "at": "2026-01-01T00:00+02:00"}
    return ctx.write(kit.wrap(MS.render_page(data, template) if template else MS.render_page(data, ctx.template)), "cfbp")


def read(url, group):
    ch = ctx.chrome
    ch.cmd("Emulation.setTimezoneOverride", timezoneId="Asia/Jerusalem")
    ch.viewport(1400, 900, mobile=False)
    ch.goto(url + "#r=27.1" + ("" if group == "version" else f"&cg={group}"))
    assert kit.wait_ready(ch), "the page did not draw: " + str(ch.console_errors()[:2])
    time.sleep(0.5)
    return ch.js(READ)


def problems(r):
    """The marks of the current period: the last bar pair of a quarter or month chart (the selected release of a Release chart)."""
    bad, n = [], len(r["bars"])
    if n < 2 or len(r["regs"]) != n:
        return [f"{r['mode']}: {n} CFB bars and {len(r['regs'])} regression bars, too few to judge"]
    solid = [i for i, b in enumerate(r["bars"]) if b["op"] is None]
    want = [n - 1] if r["mode"] != "version" else solid
    if r["mode"] == "version":
        if len(solid) != 1:
            bad.append(f"version: {len(solid)} bars are solid, expected the one of the selected release")
    elif solid != want:
        bad.append(f"{r['mode']}: the solid bars are {solid}, expected only the running {r['mode']} ({want})")
    for i, (b, g) in enumerate(zip(r["bars"], r["regs"])):
        if (b["op"] is None) != (g["op"] is None):
            bad.append(f"{r['mode']}: the CFB bar and the regression bar of period {i} do not share their emphasis")
        if i not in solid and b["op"] != ".55":
            bad.append(f"{r['mode']}: period {i} is neither solid nor lighter (opacity {b['op']})")
    if r["mode"] != "version":
        if not r["bars"][-1]["dash"]:
            bad.append(f"{r['mode']}: the running {r['mode']} has no dashed outline")
        if not r["labels"] or not r["labels"][-1].endswith("*"):
            bad.append(f"{r['mode']}: the label of the running {r['mode']} is {r['labels'][-1:]} , expected an asterisk")
        sel = [x["th"] for x in r["rows"] if x["sel"]]
        if len(sel) != 1 or not r["rows"][0]["sel"] or not r["rows"][0]["th"].endswith("*"):
            bad.append(f"{r['mode']}: highlighted table rows {sel}; the first row (the running {r['mode']}) must be the only one")
    return bad


@SUITE.test("quarter_and_month_mark_the_running_period_like_release_marks_the_selected_one")
def _(t: T):
    url = page()
    for group in ("version", "quarter", "month"):
        r = read(url, group)
        bad = problems(r)
        t.check(not bad, f"{group}: {bad}")
        t.note(f"{group}: {len(r['bars'])} periods, solid {[i for i, b in enumerate(r['bars']) if b['op'] is None]}, last label {r['labels'][-1:]}")
    t.check(not ctx.chrome.console_errors(), f"console error {ctx.chrome.console_errors()[:2]}")


@SUITE.test("selftest_the_check_fails_when_the_running_period_is_not_marked")
def _(t: T):
    src = ctx.template.read_text(encoding="utf-8")
    old = "running: i === 0, sel: i === 0, janFirst: mo === 0});"
    if old not in src:
        raise kit.Skip("this template has no marked running period to take out")
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(src.replace(old, "running: i === 0, sel: false, janFirst: mo === 0});"))
    url = page(Path(f.name))
    Path(f.name).unlink()
    bad = problems(read(url, "quarter")) + problems(read(url, "month"))
    t.check(bool(bad), "the check passed on a page that does not mark the running quarter or month: it is blind")


if __name__ == "__main__":
    sys.exit(kit.cli(SUITE, __doc__))
