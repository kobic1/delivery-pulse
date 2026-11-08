#!/usr/bin/env python3
"""The sticky filter bar keeps ONE height whatever is filtered, and Reset Filters never meets another control.

The bug this guards: the button text grows from "Reset Filters" to "Reset Filters (1)" (and "(12)") when any filter changes anywhere on the page. When the button sat in the flex flow, the longer text no longer
fitted, the button wrapped to a new row and the whole sticky header grew by one row: the sections below jumped and more of the content was covered while scrolling.

Asserted, in the CXone view and in a product view (fewer controls, a Project label instead of project chips):
  * the bar's bounding height is identical with 0, 1, 2 and 10 changed filters, with each Delivery Cycle choice, with one team and with a very long team name selected, at the viewport widths 1208 (the width of the
    published frame), 1280, 1440, 1920, a tablet-sized desktop window (900) and a phone (390, collapsed and open);
  * the same holds at every window width from 761 to 1240 px in 4 px steps, because the bug only shows where the button just fits at rest, and a width that sits on that edge is different for every set of
    controls (one isolated width may sit exactly on an edge, a run of three fails);
  * Reset Filters overlaps no other visible control, label, chip or note of the bar at any of those widths (also with Multi-Select on);
  * the button stays a real, focusable button with the id f-reset, the text "Reset Filters" or "Reset Filters (N)", disabled with no change, and a target of at least 24 x 24 px; the page never scrolls sideways;
  * a self-test: the same checks run against a copy of the template with the old rules put back and must fail.

    python3 filterbar_height_check.py [--live] [--only NAME]
"""
from __future__ import annotations

import re
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kit                                                                          # noqa: E402
import make_synthetic as MS                                                         # noqa: E402
from kit import ctx, T                                                              # noqa: E402

SUITE = kit.Suite("Delivery Pulse filter bar height")
FRAME = 1208                                         # the widest the published artifact page gets inside its frame
WIDTHS = [FRAME, 1280, 1440, 1920, 900]                # the bar is 1208 px wide from a 1240 px window up (the page is capped at 1240 with 16 px gutters)
PHONE = (390, 844)
LONG_TEAM = "The Quite Remarkably Long Team Name Of Many Words"
# one more changed filter per step (each one is counted by "Reset Filters (N)"); the first is the P3 case of the report
LADDER = ["state.bugPri.delete('P3')", "state.cfb = 'yes'", "state.ax = 'all'", "state.gran = 'week'", "state.cfbGroup = 'quarter'", "state.depRel = DEP_REL[1]",
          "state.nfrTab = 'team'", "state.cx = 'stretch'", "state.cap.by = 'release'", "state.dc = new Set(['1'])"]

MEASURE = r"""(() => {
  const bar = document.getElementById('filterbar'), rs = document.getElementById('f-reset');
  const vis = e => { const s = getComputedStyle(e), r = e.getBoundingClientRect(); return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0 && !e.closest('[hidden]') && !e.closest('.teampanel') && !e.closest('.sr'); };
  const r0 = rs.getBoundingClientRect(), hits = [];
  const TEXT = 'label, .lbl, .fnote, .multihint, .prodauto', CTRL = 'select, button, .chip, input[type=search]';
  const boxes = e => { if (e.matches(TEXT)) { const g = document.createRange(); g.selectNodeContents(e); return [...g.getClientRects()]; } return [e.getBoundingClientRect()]; };      // a label is as wide as its group: only its text counts
  bar.querySelectorAll(TEXT + ', ' + CTRL).forEach(e => {
    if (e === rs || !vis(e)) return;
    if (boxes(e).some(r => r.width > 0 && Math.min(r.right, r0.right) - Math.max(r.left, r0.left) > 1 && Math.min(r.bottom, r0.bottom) - Math.max(r.top, r0.top) > 1)) hits.push((e.id || e.className || e.tagName) + ' "' + (e.textContent || '').trim().slice(0, 24) + '"');
  });
  const b = bar.getBoundingClientRect();
  return {h: Math.round(b.height * 10) / 10, w: Math.round(b.width), rs: {l: Math.round(r0.left), t: Math.round(r0.top - b.top), w: Math.round(r0.width), h: Math.round(r0.height), r: Math.round(b.right - r0.right)},
          hits, txt: rs.textContent.trim(), disabled: rs.disabled, tag: rs.tagName, side: document.documentElement.scrollWidth - document.documentElement.clientWidth,
          rowsTop: [...new Set([...bar.querySelectorAll(':scope > .fg')].filter(vis).map(e => Math.round(e.getBoundingClientRect().top - b.top)))].length};
})()"""


def load(prod="cxone", vp=(FRAME, 900), template=None):
    ch = ctx.chrome
    data = MS.make(MS.il_today())
    data["build"] = {"sha": "abc1234", "dirty": False, "at": "2026-01-01T00:00+02:00"}
    data["productList"], data["products"] = ["PRD1", "PRD2"], MS.product_sample(data)
    page = MS.render_page(data, template or ctx.template)
    url = ctx.write(kit.wrap(page), "fbh")
    ch.cmd("Emulation.setTimezoneOverride", timezoneId="Asia/Jerusalem")
    ch.viewport(*vp, mobile=vp[0] < 500)
    ch.goto(url + "#prod=" + prod)
    assert kit.wait_ready(ch), "the page did not draw: " + str(ch.console_errors()[:2])
    time.sleep(0.4)
    return ch, data


def set_state(ch, changes=0, cycle="both", team=None):
    """Put the page into one filter state: nothing, then `changes` ladder steps, a Delivery Cycle choice and a team."""
    ch.js("resetFilters(); update();")
    if changes:
        ch.js("(() => {" + ";".join(LADDER[:changes]) + "; update(); })()")
    if cycle != "both" and ch.js("!!document.querySelector('#f-dc input[value=\"%s\"]:not(:disabled)')" % cycle):
        ch.js("document.querySelector('#f-dc input[value=\"%s\"]').click()" % cycle)
    if team:
        if team == "FIRST":
            team = ch.js("document.querySelector('#f-teams-list input[data-t]').dataset.t")
        ch.js("state.teams = new Set([%r]); update();" % team)
    time.sleep(0.15)


def measure(ch):
    return ch.js(MEASURE)


def states(prod, teams=False):
    """(label, kwargs) of the filter states compared with one another; the first is the one the others must match. The team states are only compared where the bar has one row (a team name widens the
    Teams button by a capped amount; where the controls already wrap, that can move a control to another row, which is the controls' wrapping and not the button's)."""
    out = [("rest", {}), ("1 change", {"changes": 1}), ("2 changes", {"changes": 2}), ("10 changes", {"changes": 10}), ("cycle 1", {"cycle": "1"}), ("cycle 2", {"cycle": "2"}),
           ("cycle 2 + 10 changes", {"changes": 10, "cycle": "2"})]
    if teams:
        out += [("one team", {"team": "FIRST"}), ("long team name", {"team": LONG_TEAM}), ("long team + 10 changes", {"changes": 10, "team": LONG_TEAM})]
    return out


def height_problems(ch, prod, widths, sweep=False, teams=False):
    """Compare the bar height of every state at each width; returns (problems, observations)."""
    probs, obs = [], []
    seen = {}
    for label, kw in states(prod, teams):
        set_state(ch, **kw)
        for w in widths:
            if "team" in label and w < 1280:
                continue
            ch.viewport(w, 900)
            time.sleep(0.02)
            m = measure(ch)
            seen.setdefault(w, []).append((label, m))
    bad = []
    for w, rows in seen.items():
        base = rows[0][1]["h"]
        for label, m in rows:
            if abs(m["h"] - base) > 0.5:
                msg = f"{prod} viewport {w}px: the bar is {m['h']}px with {label} ({m['txt']!r}) and {base}px at rest"
                if sweep:
                    bad.append((w, msg))                  # judged below: one width can sit exactly on an edge
                else:
                    probs.append(msg)
            if m["hits"]:
                probs.append(f"{prod} {w}px {label}: Reset Filters overlaps {m['hits'][:3]}")
        obs.append((w, base, sorted({m["h"] for _, m in rows})))
    # In a sweep a width can sit exactly on the edge where a control fits or not (the selected Delivery Cycle option is semibold and 1 px wider than another): that is one isolated width.
    # The bug this file guards made a run of widths (the 21 px a longer label needs, 5 steps of 4 px) go wrong, so three widths or more fail.
    if len({w for w, _ in bad}) >= 3:
        probs += [m for _, m in bad[:6]] + [f"{prod}: {len({w for w, _ in bad})} widths of the sweep change the bar height with the filter state"]
    return probs, obs


def button_problems(ch, prod):
    """The button itself: a real button, its text, disabled with no change, a target of 24 x 24 px or more."""
    probs = []
    for n in (0, 1, 2, 10):
        set_state(ch, changes=n)
        m = measure(ch)
        counted = ch.js("Object.values(filterChanges()).filter(Boolean).length")          # the page's own count of changed filters
        want = f"Reset Filters ({counted})" if counted else "Reset Filters"
        if counted != n:
            probs.append(f"{prod}: the setup made {counted} changes, expected {n}")
        if m["tag"] != "BUTTON" or m["txt"] != want or m["disabled"] != (n == 0):
            probs.append(f"{prod}: with {n} changes the button is <{m['tag']}> {m['txt']!r} disabled={m['disabled']}, expected {want!r} disabled={n == 0}")
        if m["rs"]["h"] < 24 or m["rs"]["w"] < 24:
            probs.append(f"{prod}: the button target is {m['rs']['w']} x {m['rs']['h']}px, below 24 x 24")
    if not ch.js("(() => { const b = document.getElementById('f-reset'); b.focus(); return document.activeElement === b || b.disabled; })()"):
        probs.append(f"{prod}: the button cannot take focus")
    return probs


def phone_problems(ch, prod):
    """On a phone the bar is collapsed behind the Filters button; its height is the same collapsed and open for every state."""
    probs = []
    for opened in (False, True):
        ch.js("(() => { const b = document.getElementById('filterbar'); b.classList.toggle('collapsed', %s); })()" % ("false" if opened else "true"))
        base = None
        for label, kw in states(prod):
            set_state(ch, **kw)
            m = measure(ch)
            base = m["h"] if base is None else base
            if abs(m["h"] - base) > 0.5:
                probs.append(f"{prod} phone {'open' if opened else 'collapsed'}: the bar is {m['h']}px with {label} and {base}px at rest")
            if m["hits"]:
                probs.append(f"{prod} phone {'open' if opened else 'collapsed'} {label}: Reset Filters overlaps {m['hits'][:3]}")
            if m["side"] > 1:
                probs.append(f"{prod} phone {label}: the page scrolls sideways by {m['side']}px")
            if m["rs"]["h"] < 24:
                probs.append(f"{prod} phone: the button is {m['rs']['h']}px tall")
    return probs


def everything(template=None, quick=False):
    """Every check of this file on a template; the problems found (empty = fine) and the observations."""
    probs, obs = [], []
    step = 6 if quick else 4
    sweep = list(range(761, 1241, step)) + [1240]
    for prod in (("cxone",) if quick else ("cxone", "PRD1")):
        ch, data = load(prod, (FRAME, 900), template)
        if prod == "cxone" and not quick:
            team = ch.js("(() => { const t = [...document.querySelectorAll('#f-teams-list input[data-t]')].map(i => i.dataset.t); return t.sort((a, b) => b.length - a.length)[0] || null; })()")
            obs.append(("longest real team", team))
        # the synthetic page has seven project chips, the real one six (WFM is a product there); with WFM hidden the old bar fits on one row at rest at a bar width of 1208 (a 1240 px window or wider) and
        # not with "(1)" after the label: the case of the report
        ch.js("['WFM'].forEach(p => { const b = document.querySelector('#f-projects button.chip[data-p=\"' + p + '\"]'); if (b) b.hidden = true; })")
        probs += button_problems(ch, prod)
        if ch.js("document.documentElement.scrollWidth - document.documentElement.clientWidth") > 1:
            probs.append(f"{prod}: the page scrolls sideways at {FRAME}px")
        p, o = height_problems(ch, prod, WIDTHS if not quick else [FRAME], teams=True)
        probs += p
        obs += [(prod, "viewport") + x for x in o]
        p, o = height_problems(ch, prod, sweep, sweep=True)
        probs += p
        obs += [(prod, "sweep") + x for x in o[:1]]
        # Multi-Select on adds the hint to the label row of the Projects group: the button must still meet nothing
        if prod == "cxone":
            ch.js("document.getElementById('f-multi').click()")
            time.sleep(0.2)
            ch.viewport(FRAME, 900)
            set_state(ch, changes=1)
            m = measure(ch)
            if m["hits"]:
                probs.append(f"cxone Multi-Select on: Reset Filters overlaps {m['hits'][:3]}")
            ch.js("document.getElementById('f-multi').click()")
        if not quick:
            probs += phone_problems(load(prod, PHONE, template)[0], prod)
        if ch.console_errors():
            probs.append(f"{prod}: console error {ch.console_errors()[:1]}")
    return probs, obs


@SUITE.test("bar_height_is_the_same_in_every_filter_state_and_reset_never_overlaps")
def _(t: T):
    probs, obs = everything()
    for p in probs[:40]:
        t.check(False, p)
    t.check(not probs, f"{len(probs)} problems in all")
    t.note(f"observations: {obs[:6]}")


@SUITE.test("selftest_the_check_fails_on_the_old_rules")
def _(t: T):
    text = ctx.template.read_text(encoding="utf-8")
    new = re.search(r"@media \(min-width:761px\) and \(max-width:839px\)[^\n]*\n@media \(min-width:840px\)[^\n]*\n", text)
    if not new:
        raise kit.Skip("the template has no out-of-flow Reset rule to take out: it is already the old one")
    old = "@media (min-width:761px) { #filterbar .freset { margin-left:auto; } }\n"
    seeded = text[:new.start()] + old + text[new.end():]
    seeded = seeded.replace("#filterbar { align-items:flex-start; position:relative; }", "#filterbar { align-items:flex-start; }")
    t.check(seeded != text, "the seeded defect did not change the template")
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(seeded)
    probs, _ = everything(Path(f.name), quick=True)
    Path(f.name).unlink()
    if not probs:                                                       # a machine whose fonts are narrower than the page's own leaves room for the longer label even with the old rules: nothing to catch there
        raise kit.Skip("the fonts of this machine leave room for 'Reset Filters (N)' even with the old rules, so the seeded defect cannot show")
    t.check(any("the bar is" in p for p in probs), f"the old rules were not caught ({len(probs)} problems: {probs[:2]})")


if __name__ == "__main__":
    sys.exit(kit.cli(SUITE, __doc__))
