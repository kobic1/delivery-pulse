#!/usr/bin/env python3
"""The Teams menu of the filter bar lists only the teams that work in the selected projects.

A team is listed by default when it has an epic of the release in one of the selected projects. Teams that only have a bug or a capitalization record (a Done Bug, Story or Task) there sit behind a 'Show N teams with no epics' link. The expectation is recounted here from the fictitious
fixture, never read from the page. A team of another project must not be listed when one project is selected; with every project selected the menu is the union.

    python3 teams_menu_check.py [--live] [--only NAME]
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

SUITE = kit.Suite("Delivery Pulse Teams menu")
NO_TEAM = "(No Team)"


def expected(data, projects, release):
    """(the teams with epics on the release, every team that works in the projects)."""
    epics = set()
    for e in data["epics"]:
        if e["p"] in projects and release in (e.get("fv") or []):
            epics.update(e.get("tm") or [NO_TEAM])
    out = set(epics)
    for b in data["bugs"]:
        if b["p"] in projects:
            out.add(b.get("tm") or NO_TEAM)
    cap = data["cap"]
    for row in cap["rows"].split(";"):
        a = row.split(",")
        if cap["projects"][int(a[1])] in projects:
            out.add(cap["teams"][int(a[5])] if int(a[5]) >= 0 else NO_TEAM)
    return epics, out


def listed(ch):
    return set(ch.js("[...document.querySelectorAll('#f-teams-list input[data-t]')].map(i => i.dataset.t)") or [])


def more_text(ch):
    return ch.js("(() => { const b = document.getElementById('f-teams-more'); return b ? b.textContent : null; })()")


@SUITE.test("teams_menu_lists_only_the_teams_of_the_selected_projects")
def _(t: T):
    data = MS.make(MS.il_today())
    ch = ctx.chrome
    ctx.write(kit.wrap(MS.render_page(data)), "teams")
    ch.cmd("Emulation.setTimezoneOverride", timezoneId="Asia/Jerusalem")
    ch.viewport(1400, 900)
    ch.goto(ctx.write(kit.wrap(MS.render_page(data)), "teams"))
    assert kit.wait_ready(ch), "the page did not draw: " + str(ch.console_errors()[:2])
    time.sleep(0.4)
    rel = ch.js("document.getElementById('f-release').value")
    projects = ch.js("[...document.querySelectorAll('#f-projects button.chip[data-p]')].map(b => b.dataset.p)")
    everyone = set(projects)
    t.check(len(projects) >= 3, f"the fixture has too few projects: {projects}")
    ep_all, full_all = expected(data, everyone, rel)
    t.check(listed(ch) == ep_all, f"all projects: by default the menu lists {sorted(listed(ch) ^ ep_all)} too many or too few (teams with epics only)")
    proved = 0
    for p in projects:
        ch.js(f"document.querySelector('#f-projects button.chip[data-p=\"{p}\"]').click()")
        time.sleep(0.3)
        epics, full = expected(data, {p}, rel)
        got = listed(ch)
        t.check(got == epics, f"{p}: by default the menu lists {sorted(got ^ epics)} too many or too few (teams with epics only)")
        dashed = full - epics
        txt = more_text(ch)
        t.check((txt is None) if not dashed else (txt == f"Show {len(dashed)} {'team' if len(dashed) == 1 else 'teams'} with no epics"), f"{p}: the link under the list says {txt!r}, expected {len(dashed)} teams with no epics")
        if dashed:
            ch.js("document.getElementById('f-teams-more').click()")
            time.sleep(0.2)
            t.check(listed(ch) == full, f"{p}: after Show the menu lists {sorted(listed(ch) ^ full)} too many or too few")
            t.check((more_text(ch) or "").startswith("Hide "), f"{p}: the link does not turn into Hide: {more_text(ch)!r}")
            ch.js("document.getElementById('f-teams-more').click()")
            time.sleep(0.2)
            t.check(listed(ch) == epics, f"{p}: Hide does not fold the teams with no epics away again")
            name = sorted(dashed)[0]                                                             # a search finds a team with no epics without opening the list
            ch.js(f"(() => {{ const q = document.getElementById('f-teams-search'); q.value = {name!r}; q.dispatchEvent(new Event('input')); }})()")
            t.check(name in listed(ch), f"{p}: searching for {name} does not find it")
            ch.js(f"[...document.querySelectorAll('#f-teams-list input[data-t]')].find(i => i.dataset.t === {name!r}).click()")      # select it, then clear the search
            ch.js("(() => { const q = document.getElementById('f-teams-search'); q.value = ''; q.dispatchEvent(new Event('input')); })()")
            time.sleep(0.2)
            t.check(name in listed(ch) and len(listed(ch)) == len(epics) + 1, f"{p}: a selected team with no epics ({name}) does not stay listed while the others are folded away: {sorted(listed(ch))}")
        proved += bool(full_all - full)
        ch.js("document.getElementById('f-reset').click()")
        time.sleep(0.2)
    t.check(proved >= 1, "no project leaves a team out, so the check proves nothing")
    t.check(not ch.console_errors(), f"console error: {ch.console_errors()[:2]}")


if __name__ == "__main__":
    sys.exit(kit.cli(SUITE, __doc__))
