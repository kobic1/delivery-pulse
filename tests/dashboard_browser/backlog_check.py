#!/usr/bin/env python3
"""Needs Attention rule "Bugs Backlog Increase": a project fires when its open bugs now are at least 20% and at least 5 bugs higher than 14 days ago.

The fixture is fictitious and built so that every case is there (the open counts below are what the builder aims at, and the oracle recounts them from the bug records, never from the page's code):
  PMN 7 -> 14 (+7, +100%) fires | CXCO 14 -> 18 (+4, +29%) does not, under 5 more bugs | CXSUP 337 -> 354 (+17, +5%) does not, under 20% | CXWFM 25 -> 30 (+5, exactly +20%) fires
  WFM 0 -> 5 (from none) fires | CXINT 40 -> 47 (+7, +17.5%) does not | INT 30 -> 36 (+6, exactly +20%) fires.
Every project also holds the traps of the count: a closed bug with no resolution date (counts as closed), a bug in Validation that has a resolution date (open), a bug created and closed inside the window (in neither count),
a bug closed on the comparison day (closed by then) and one closed the day after (still open then), a bug created on the comparison day (open then).
Asserted: which projects fire, the counts in the row, the row text, the hover (rule, value, limit, source), the link's query, the accessible label, the group's name, count and severity, the summary chip, the Projects and Teams filters, and a seeded defect
(the open count 14 days ago counts a Validation bug with a resolution date as closed) that this check must catch.

    python3 backlog_check.py [--live] [--only NAME]
"""
from __future__ import annotations

import datetime as dt
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kit                                                                          # noqa: E402
import make_synthetic as MS                                                         # noqa: E402
from kit import ctx, T                                                              # noqa: E402

SUITE = kit.Suite("Delivery Pulse bugs backlog increase")
CLOSED = {"Done", "Ready for Deploy", "Closed", "Resolved", "Removed"}
PCT, MIN, DAYS = 20, 5, 14
CASES = {"PMN": (7, 14), "CXCO": (14, 18), "CXSUP": (337, 354), "CXWFM": (25, 30), "WFM": (0, 5), "CXINT": (40, 47), "INT": (30, 36)}
FIRES = ["PMN", "CXWFM", "WFM", "INT"]
TEAMS = ("Team Alpha", "Team Beta")


def asof(data) -> dt.date:
    return dt.date.fromisoformat(data["generated"][:10])


def fixture(data):
    now = asof(data)
    then = now - dt.timedelta(days=DAYS)
    day = lambda d: d.isoformat()
    bugs, n = [], [0]

    def add(proj, cr, s, rd=None, tm=None):
        n[0] += 1
        b = {"k": f"{proj}-{70000 + n[0]}", "p": proj, "cr": day(cr), "s": s, "pr": "P3", "tm": tm or ("Team Alpha" if proj == "PMN" else TEAMS[n[0] % 2])}
        if rd:
            b["rd"], b["rs"] = day(rd), "Fixed"
        bugs.append(b)

    for proj, (t, nn) in CASES.items():
        c = min(2, t)                              # open then, closed since
        stay = t - c                               # open then and still open
        new = nn - stay                            # created since, still open
        for i in range(stay):
            if i == 0:
                add(proj, then, "In Progress")                                   # created on the comparison day: open then
            elif i == 1:
                add(proj, then - dt.timedelta(days=30), "Validation", then - dt.timedelta(days=3))    # Validation with a resolution date: open
            else:
                add(proj, then - dt.timedelta(days=20 + i), "New")
        for i in range(c):
            add(proj, then - dt.timedelta(days=40 + i), "Done", then + dt.timedelta(days=1 if i == 0 else 9))   # closed after the comparison day: open then
        for i in range(new):
            add(proj, then + dt.timedelta(days=1 + (i % 12)), "New")
        add(proj, dt.date(2016, 7, 19), "Done")                                  # closed, no resolution date: closed
        add(proj, then - dt.timedelta(days=50), "Done", then)                    # closed on the comparison day: closed by then
        add(proj, then + dt.timedelta(days=2), "Done", then + dt.timedelta(days=5))   # created and closed inside the window
    data["bugs"] = bugs
    data["cfbx"] = {}
    return data


def oracle(data, projects=None, teams=None):
    """(then, now) open counts per project, counted day by day from the records."""
    now = asof(data)
    then = now - dt.timedelta(days=DAYS)
    out = {}
    for proj in CASES:
        if projects is not None and proj not in projects:
            continue
        mine = [b for b in data["bugs"] if b["p"] == proj and (not teams or b.get("tm") in teams)]

        def open_on(d):
            c = 0
            for b in mine:
                if dt.date.fromisoformat(b["cr"]) > d:
                    continue
                if b["s"] in CLOSED and ("rd" not in b or dt.date.fromisoformat(b["rd"]) <= d):
                    continue
                c += 1
            return c
        out[proj] = (open_on(then), open_on(now))
    return out


def fires(counts):
    return [p for p, (t, n) in counts.items() if n - t >= MIN and n * 100 >= t * (100 + PCT)]


def page(template=None):
    data = fixture(MS.make(MS.il_today()))
    data["build"] = {"sha": "abc1234", "dirty": False, "at": "2026-01-01T00:00+02:00"}
    url = ctx.write(kit.wrap(MS.render_page(data, template) if template else MS.render_page(data, ctx.template)), "backlog")
    return url, data


READ = """(() => {
  attnUi.panel = true; attnUi.open.add('bug-backlog'); renderAttention();
  const g = document.querySelector('#attn [data-act="grp-bug-backlog"]');
  const rows = [...document.querySelectorAll('#ag-bug-backlog .arow')].map(li => { const a = li.querySelector('a.cl'); return {key: a.textContent.trim(), href: a.getAttribute('href'), aria: a.getAttribute('aria-label'),
    sub: li.querySelector('.a2').textContent.trim(), text: li.querySelector('.a3').textContent.trim(), tip: li.getAttribute('data-tip'), conf: li.querySelector('.a4').textContent.trim()}; });
  const chip = document.querySelector('#attn-sum .achip[data-chip="bug-backlog"]');
  return {name: g ? g.querySelector('.an').textContent : null, count: g ? g.querySelector('.ac').textContent : null, sev: g ? g.querySelector('.asev').textContent.trim() : null,
    chip: chip ? chip.textContent.trim() : null, rows, limits: document.querySelector('#attn details.vd .cap').textContent}; })()"""


def load(url, set_state=""):
    ch = ctx.chrome
    ch.cmd("Emulation.setTimezoneOverride", timezoneId="Asia/Jerusalem")
    ch.viewport(1400, 900, mobile=False)
    ch.goto(url + "#r=27.1")
    assert kit.wait_ready(ch), "the page did not draw: " + str(ch.console_errors()[:2])
    time.sleep(0.5)
    if set_state:
        ch.js(f"(() => {{ {set_state} }})()")
        time.sleep(0.4)
    return ch.js(READ)


def row_text(proj, t, n):
    inc = n - t
    return f"Open bugs: {t} on {{then}}, {n} now, +{inc}" + (f" (+{inc * 100 // t}%)" if t else "")


@SUITE.test("the_projects_that_grew_20_percent_and_5_bugs_fire_and_no_other")
def _(t: T):
    url, data = page()
    want = oracle(data)
    t.check(want == {p: (a, b) for p, (a, b) in CASES.items()}, f"the fixture does not hold the counts it aims at: {want}")
    r = load(url)
    t.check(sorted(x["key"] for x in r["rows"]) == sorted(fires(want)), f"rows {[x['key'] for x in r['rows']]}, expected {fires(want)}")
    t.check(sorted(fires(want)) == sorted(FIRES), f"the oracle fires {fires(want)}, the design says {FIRES}")
    t.check(r["name"] == "Bugs Backlog Increase" and r["count"] == str(len(FIRES)), f"group {r['name']!r} count {r['count']!r}")
    t.check(r["sev"] == "Medium", f"severity {r['sev']!r}")
    t.check(r["chip"] and r["chip"].startswith(str(len(FIRES))) and "Bugs Backlog Increase" in r["chip"], f"summary chip {r['chip']!r}")
    t.check([x["key"] for x in r["rows"]] == sorted(FIRES, key=lambda p: (-(want[p][1] - want[p][0]), p)), f"the rows are not in the order of the biggest increase first: {[x['key'] for x in r['rows']]}")


@SUITE.test("each_row_states_the_two_counts_the_change_the_rule_and_the_limit")
def _(t: T):
    url, data = page()
    want = oracle(data)
    then = (asof(data) - dt.timedelta(days=DAYS)).isoformat()
    r = load(url)
    by = {x["key"]: x for x in r["rows"]}
    for p in FIRES:
        a, b = want[p]
        x = by.get(p)
        if not t.check(x, f"no row for {p}"):
            continue
        t.check(x["text"] == row_text(p, a, b).format(then=then) or x["text"].startswith(row_text(p, a, b).format(then=then)), f"{p}: row text {x['text']!r}, expected {row_text(p, a, b).format(then=then)!r}")
        t.check(f"{b} open now vs {a} on {then}" in x["tip"] and f"limit +{PCT}% and +{MIN} bugs (owner decision, 2026-11-11)" in x["tip"], f"{p}: hover {x['tip']!r}")
        t.check("Open bugs of a project (all bugs, any priority) grew at least 20% and at least 5 bugs in 14 days." in x["tip"], f"{p}: the rule is not in the hover")
        t.check(x["aria"] == f"{p}, open bugs went from {a} to {b} in 14 days, +{b - a}" + (f" (+{(b - a) * 100 // a}%)" if a else "") + ". Evidence, opens in Jira.", f"{p}: aria {x['aria']!r}")
        t.check(x["sub"] == "All bugs, any priority" and x["conf"] == "Single-source", f"{p}: second line {x['sub']!r}, confidence {x['conf']!r}")
        jql = urllib.parse.parse_qs(urllib.parse.urlparse(x["href"] or "").query).get("jql", [""])[0]
        t.check(jql == f'project in ({chr(34) + p + chr(34) if p == "INT" else p}) AND issuetype = Bug AND status not in (Done, "Ready for Deploy", Closed, Resolved, Removed)', f"{p}: the link asks for {jql!r}")
    t.check("a project whose open bugs now are at least 20% and at least 5 bugs higher than 14 days ago" in r["limits"], "the Limits and Thresholds text has no definition")
    t.check("rebuilt from creation and resolution dates" in r["limits"], "the Limits and Thresholds text has no data limit")


@SUITE.test("a_percent_shown_on_a_row_is_never_below_the_limit_and_a_project_with_no_bugs_then_has_no_percent")
def _(t: T):
    url, data = page()
    r = load(url)
    by = {x["key"]: x for x in r["rows"]}
    t.check(by["WFM"]["text"].endswith("0 on %s, 5 now, +5" % (asof(data) - dt.timedelta(days=DAYS)).isoformat()), f"WFM (0 then): {by['WFM']['text']!r}")
    t.check("(+20%)" in by["CXWFM"]["text"] and "(+20%)" in by["INT"]["text"], f"the exact-20% rows: {by['CXWFM']['text']!r}, {by['INT']['text']!r}")


@SUITE.test("the_projects_and_teams_filters_change_the_rows")
def _(t: T):
    url, data = page()
    r = load(url, "state.projects = new Set(['PMN', 'INT']); update();")
    t.check(sorted(x["key"] for x in r["rows"]) == ["INT", "PMN"], f"two projects: {[x['key'] for x in r['rows']]}")
    for team in TEAMS:
        r = load(url, f"state.teams = new Set([{team!r}]); update();")
        want = oracle(data, teams={team})
        t.note(f"{team}: " + ", ".join(f"{x['key']} {oracle(data, teams={team})[x['key']]}" for x in r["rows"]))
        t.check(sorted(x["key"] for x in r["rows"]) == sorted(fires(want)), f"{team}: rows {[x['key'] for x in r['rows']]}, expected {fires(want)}")
        t.check(team != "Team Alpha" or "PMN" in [x["key"] for x in r["rows"]], "Team Alpha holds all of PMN's bugs and PMN grew, yet it has no row: the check is blind")
        for x in r["rows"]:
            a, b = want[x["key"]]
            t.check(f"{b} open now vs {a} on" in x["tip"], f"{team} {x['key']}: hover {x['tip']!r}, expected {b} vs {a}")
            t.check("cf%5B10098%5D" in (x["href"] or "") or "cf[10098]" in (x["href"] or ""), f"{team} {x['key']}: the link does not carry the team: {x['href']!r}")


@SUITE.test("selftest_the_check_fails_when_a_validation_bug_with_a_resolution_date_counts_as_closed")
def _(t: T):
    src = ctx.template.read_text(encoding="utf-8")
    marker = "const openOn = (b, day) => b.cr <= day && !(BUG_CLOSED.includes(b.s) && (!b.rd || b.rd <= day));"
    if marker not in src:
        raise kit.Skip("this template has no open-bug count to break")
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(src.replace(marker, "const openOn = (b, day) => b.cr <= day && !((BUG_CLOSED.includes(b.s) || b.rd) && (!b.rd || b.rd <= day));"))
    url, data = page(Path(f.name))
    Path(f.name).unlink()
    r = load(url)
    want = fires(oracle(data))
    t.check(sorted(x["key"] for x in r["rows"]) != sorted(want) or any(f"{b} open now vs {a} on" not in x["tip"] for x in r["rows"] for a, b in [oracle(data)[x["key"]]]), "the check passed with the Validation bug counted as closed: it is blind")


if __name__ == "__main__":
    sys.exit(kit.cli(SUITE, __doc__))
