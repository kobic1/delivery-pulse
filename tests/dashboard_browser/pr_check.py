#!/usr/bin/env python3
"""Needs Attention rule "Pull Requests Open More Than 3 Business Days".

The rule: an open pull request that names a Jira key of a selected project, with some activity in the last 14 days, and more than 3 business days since it was marked ready for review.
Business days are Sunday to Thursday, Israeli public holidays left out (the same count as Epics in Validation). 7 business days or more is an escalation (a red flag, not a second group).

The fixture is fictitious. Every pull request below is placed by the number of business days it has waited, recounted here day by day (the holiday list is read from the page: it is data, the counting is not):
  PMN: 2 days (under the limit) | 3 days (exactly the limit: no row, the rule says MORE than 3) | 4 days | 7 days (escalation) | 12 days (escalation)
  PMN, 6 days, last activity 15 days ago (no row: inactive) | PMN, 6 days, last activity exactly 14 days ago (row: the window is 14 days) | PMN and CXCO together, 5 days (one row, whichever of the two is selected)
  CXSUP 5 days | CXWFM 9 days (escalation), checks failing, changes requested.
Asserted: which rows, their order (waiting longest first), the row text, the hover (rule, value, limit, source), the link (to GitHub, never to Jira), the accessible label, the second line (project, review state, checks), the group and its summary chip,
the Projects filter (a pull request that names two projects is one row), the Teams filter (the group is left out and the summary says so), a feed that could not be read (a notice, never an empty group), a feed that was not refreshed, a payload with no feed,
and a seeded defect (the limit read as "3 or more") that this check must catch.

    python3 pr_check.py [--live] [--only NAME]
"""
from __future__ import annotations

import datetime as dt
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kit                                                                          # noqa: E402
import make_synthetic as MS                                                         # noqa: E402
from kit import ctx, T                                                              # noqa: E402

SUITE = kit.Suite("Delivery Pulse pull requests waiting")
LIMIT, ESCALATE, ACTIVE = 3, 7, 14
SOURCE = "owner-supplied (the PR aging alert skill); only pull requests with activity in the last 14 days, owner decision 2026-11-15"


def asof(data) -> dt.date:
    return dt.date.fromisoformat(data["generated"][:10])


def bdays(ra: dt.date, now: dt.date, hol: set) -> int:
    """Working days d with ra < d <= now: Friday and Saturday are the weekend, and the holidays do not count."""
    n, d = 0, ra + dt.timedelta(days=1)
    while d <= now:
        if d.weekday() not in (4, 5) and d.isoformat() not in hol:
            n += 1
        d += dt.timedelta(days=1)
    return n


def ready_day(bd: int, now: dt.date, hol: set) -> dt.date:
    """The most recent day from which exactly `bd` business days have passed."""
    d = now
    while bdays(d, now, hol) != bd:
        d -= dt.timedelta(days=1)
    return d


def fixture(data, hol: set):
    now = asof(data)
    ago = lambda n: (now - dt.timedelta(days=n)).isoformat()
    rows = []

    def add(n, proj, bd, repo="svc-alpha", up=1, rv="none", ci="ok", title=None, rl=("27.1",), tm=(), pd=()):
        ra = ready_day(bd, now, hol)
        rows.append({"r": repo, "n": n, "t": title or f"Invented change {n}", "ra": ra.isoformat(), "up": ago(up), "rv": rv, "ci": ci, "pj": proj, "rl": list(rl), "tm": list(tm), "pd": list(pd)})
    add(101, ["PMN"], 2)
    add(102, ["PMN"], 3)
    add(103, ["PMN"], 4, rv="commented", tm=("Team Alpha",), pd=("POD-A",))
    add(104, ["PMN"], 7, repo="svc-bravo", rv="approved", ci="pend", tm=("Team Alpha", "Team Bravo"), pd=("POD-A", "POD-B"))              # the issues it names carry two teams and two pods
    add(105, ["PMN"], 12, repo="svc-bravo", rv="none", ci="none")
    add(106, ["PMN"], 6, up=ACTIVE + 1)
    add(107, ["PMN"], 6, up=ACTIVE, tm=("Team Alpha",))                  # a team and no pod
    add(108, ["PMN", "CXCO"], 5, tm=("Team Charlie",), pd=("POD-C",))
    add(109, ["CXSUP"], 5, repo="svc-charlie")
    add(110, ["CXWFM"], 9, repo="svc-charlie", rv="changes", ci="fail", tm=("Team Charlie",))
    add(111, ["PMN"], 6, repo="svc-delta", rl=("27.2",))                 # another release only
    add(112, ["PMN"], 8, repo="svc-delta", rl=())                        # no release at all: never a row
    add(113, ["PMN"], 5, repo="svc-delta", rl=("26.4", "27.1"))          # two releases: a row under each
    data["prs"] = {"org": "example-org", "at": f"{now.isoformat()}T09:00+02:00", "activeDays": ACTIVE, "found": len(rows) + 4, "kept": len(rows), "drafts": 0, "bots": 3, "labelled": 0, "noKey": 1, "unknownKeys": 0, "noRelease": 1, "list": rows}
    return data


def oracle(data, hol, projects=None, release="27.1"):
    """The rows the rule must give: (repo#n, business days, escalation), waiting longest first."""
    now, out = asof(data), []
    for x in data["prs"]["list"]:
        sel = [p for p in x["pj"] if projects is None or p in projects]
        if not sel or release not in x["rl"] or (now - dt.date.fromisoformat(x["up"])).days > ACTIVE:
            continue
        bd = bdays(dt.date.fromisoformat(x["ra"]), now, hol)
        if bd > LIMIT:
            out.append((f"{x['r']}#{x['n']}", bd, bd >= ESCALATE, sel, x))
    return sorted(out, key=lambda r: (-r[1], r[0]))


def page(template=None, mutate=None):
    data = MS.make(MS.il_today())
    data["build"] = {"sha": "abc1234", "dirty": False, "at": "2026-01-01T00:00+02:00"}
    hol = set(HOL())
    data = fixture(data, hol)
    if mutate:
        mutate(data)
    url = ctx.write(kit.wrap(MS.render_page(data, template) if template else MS.render_page(data, ctx.template)), "prs")
    return url, data, hol


def HOL():
    src = ctx.template.read_text(encoding="utf-8")
    i = src.index("HOLIDAYS: [") + len("HOLIDAYS: [")
    return [x.strip().strip('"') for x in src[i:src.index("]", i)].split(",")]


READ = """(() => {
  attnUi.panel = true; attnUi.open.add('pr-aging'); renderAttention();
  const g = document.querySelector('#attn [data-act="grp-pr-aging"]');
  const rows = [...document.querySelectorAll('#ag-pr-aging .arow')].map(li => { const a = li.querySelector('a.cl'); return {key: a.textContent.trim(), href: a.getAttribute('href'), aria: a.getAttribute('aria-label'),
    title: li.querySelector('.at') ? li.querySelector('.at').textContent.trim() : '', sub: li.querySelector('.a2').textContent.trim(), text: li.querySelector('.a3').textContent.trim(), tip: li.getAttribute('data-tip'),
    conf: li.querySelector('.a4').textContent.trim(), flag: li.querySelector('.a3 [data-sev], .a3 svg, .a3 .flag') ? li.querySelector('.a3').innerHTML.length : 0}; });
  const chip = document.querySelector('#attn-sum .achip[data-chip="pr-aging"]');
  const openAll = [...document.querySelectorAll('#ag-pr-aging .amore a')].map(a => a.textContent.trim());
  return {name: g ? g.querySelector('.an').textContent : null, count: g ? g.querySelector('.ac').textContent : null, sev: g ? g.querySelector('.asev').textContent.trim() : null,
    chip: chip ? chip.textContent.trim() : null, rows, openAll, sum: document.getElementById('attn-sum').innerText, limits: document.querySelector('#attn details.vd .cap').textContent}; })()"""


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


@SUITE.test("only_a_pull_request_over_the_limit_and_active_in_14_days_has_a_row_waiting_longest_first")
def _(t: T):
    url, data, hol = page()
    want = oracle(data, hol)
    t.check([w[0] for w in want] == ["svc-bravo#105", "svc-charlie#110", "svc-bravo#104", "svc-alpha#107", "svc-alpha#108", "svc-charlie#109", "svc-delta#113", "svc-alpha#103"],
            f"the fixture does not hold the cases it aims at: {[w[:3] for w in want]}")
    r = load(url)
    t.check([x["key"] for x in r["rows"]] == [w[0] for w in want], f"rows {[x['key'] for x in r['rows']]}, expected {[w[0] for w in want]}")
    t.check("svc-alpha#102" not in [x["key"] for x in r["rows"]], "exactly 3 business days is a row: the rule says MORE than 3")
    t.check("svc-alpha#106" not in [x["key"] for x in r["rows"]] and "svc-alpha#107" in [x["key"] for x in r["rows"]], "the 14-day activity window is not 'last activity at most 14 days ago'")
    t.check(r["name"] == "Pull Requests Open More Than 3 Business Days" and r["count"] == str(len(want)), f"group {r['name']!r} count {r['count']!r}")
    t.check(r["sev"] == "Medium", f"severity {r['sev']!r}")
    t.check(r["chip"] and r["chip"].startswith(str(len(want))) and "Pull Requests Open More Than 3 Business Days" in r["chip"], f"summary chip {r['chip']!r}")


@SUITE.test("each_row_states_the_wait_the_rule_the_limit_the_source_and_links_to_github")
def _(t: T):
    url, data, hol = page()
    want = oracle(data, hol)
    r = load(url)
    by = {x["key"]: x for x in r["rows"]}
    now = asof(data)
    for key, bd, esc, sel, rec in want:
        x = by.get(key)
        if not t.check(x, f"no row for {key}"):
            continue
        cal = (now - dt.date.fromisoformat(rec["ra"])).days
        t.check(x["text"] == f"{bd} business days since ready for review (limit 3{', escalation at 7' if esc else ''})", f"{key}: row text {x['text']!r}")
        t.check(f"{bd} business days ({cal} calendar days) since {rec['ra']}; last activity {rec['up']}; limit 3 business days ({SOURCE})." in x["tip"], f"{key}: hover {x['tip']!r}")
        t.check("Open pull request that has waited longer than the limit since it was marked ready for review" in x["tip"] and "with activity in the last 14 days" in x["tip"], f"{key}: the rule is not in the hover")
        t.check(x["href"] == f"https://github.com/example-org/{rec['r']}/pull/{rec['n']}", f"{key}: the link goes to {x['href']!r}")
        t.check(x["aria"] == f"{rec['r']} pull request {rec['n']}, {rec['t']}, {bd} business days since ready for review. Evidence, opens on GitHub.", f"{key}: aria {x['aria']!r}")
        rv = {"none": "no review yet", "commented": "reviewed, no decision", "changes": "changes requested", "approved": "approved, not merged"}[rec["rv"]]
        ci = {"ok": "checks passing", "fail": "checks failing", "pend": "checks running", "none": "no checks"}[rec["ci"]]
        team = (f"{', '.join(rec['tm'])} · " if rec["tm"] else "") + (f"{', '.join(rec['pd'])} · " if rec["pd"] else "")
        t.check(x["sub"] == f"{', '.join(sel)} · {team}{rv} · {ci}", f"{key}: second line {x['sub']!r}")
        t.check(x["conf"] == "Single-source" and x["title"] == rec["t"], f"{key}: confidence {x['conf']!r}, title {x['title']!r}")
    t.check(r["openAll"] == [] or all("Jira" not in a for a in r["openAll"]), f"the group offers an 'Open all in Jira' link for pull requests: {r['openAll']}")
    t.check("an open pull request of the example-org organisation" in r["limits"] and "more than 3 business days since it was last marked ready for review" in r["limits"]
            and "No author or reviewer is held." in r["limits"], "the Limits and Thresholds text has no definition")
    t.check("pull request rules follow the selected release and the Projects filter (not Teams)" in r["limits"], "the Limits text does not say which filters the rule follows")


@SUITE.test("the_second_line_shows_the_team_then_the_pod_after_the_project_and_nothing_for_what_is_missing_or_an_older_payload")
def _(t: T):
    url, data, hol = page()
    r = load(url)
    by = {x["key"]: x for x in r["rows"]}
    t.check(by["svc-alpha#103"]["sub"] == "PMN · Team Alpha · POD-A · reviewed, no decision · checks passing", f"team and pod: {by['svc-alpha#103']['sub']!r}")
    t.check(by["svc-bravo#104"]["sub"] == "PMN · Team Alpha, Team Bravo · POD-A, POD-B · approved, not merged · checks running", f"two teams and two pods: {by['svc-bravo#104']['sub']!r}")
    t.check(by["svc-alpha#107"]["sub"] == "PMN · Team Alpha · no review yet · checks passing", f"a team and no pod: {by['svc-alpha#107']['sub']!r}")
    t.check(by["svc-alpha#108"]["sub"] == "PMN, CXCO · Team Charlie · POD-C · no review yet · checks passing", f"two projects, a team and a pod: {by['svc-alpha#108']['sub']!r}")
    t.check(by["svc-bravo#105"]["sub"] == "PMN · no review yet · no checks", f"no team, no pod: {by['svc-bravo#105']['sub']!r}")
    # a payload from before the teams and pods were read: no key at all, no error, no 'undefined'
    def old(d):
        for x in d["prs"]["list"]:
            x.pop("tm", None); x.pop("pd", None)
    url2, data2, _ = page(mutate=old)
    r2 = load(url2)
    t.check(r2["rows"] and all("undefined" not in x["sub"] and x["sub"].count("·") == 2 for x in r2["rows"]), f"an older payload breaks the second line: {[x['sub'] for x in r2['rows']][:3]}")
    t.check(not ctx.chrome.console_errors(), f"console error: {ctx.chrome.console_errors()[:2]}")


@SUITE.test("a_pull_request_naming_two_projects_is_one_row_and_shows_only_the_selected_ones")
def _(t: T):
    url, data, hol = page()
    r = load(url)
    t.check([x["key"] for x in r["rows"]].count("svc-alpha#108") == 1, "a pull request that names two projects is not exactly one row")
    r = load(url, "state.projects = new Set(['CXCO']); update();")
    t.check([x["key"] for x in r["rows"]] == ["svc-alpha#108"] and r["rows"][0]["sub"].startswith("CXCO · "), f"CXCO only: {[(x['key'], x['sub']) for x in r['rows']]}")
    r = load(url, "state.projects = new Set(['PMN', 'CXWFM']); update();")
    t.check(sorted(x["key"] for x in r["rows"]) == sorted(w[0] for w in oracle(data, hol, {"PMN", "CXWFM"})), f"PMN and CXWFM: {[x['key'] for x in r['rows']]}")
    t.check(next(x for x in r["rows"] if x["key"] == "svc-alpha#108")["sub"].startswith("PMN · "), "the two-project row names the unselected project")


@SUITE.test("selecting_a_team_leaves_the_group_out_and_the_summary_says_why")
def _(t: T):
    url, data, hol = page()
    team = data["epics"][0]["tm"][0] if data["epics"][0].get("tm") else "Team Alpha"
    r = load(url, f"state.teams = new Set([{team!r}]); update();")
    t.check(r["name"] is None and r["chip"] is None, "the group is shown while a team is selected: a pull request carries no team")
    t.check("Pull requests are not shown while a team is selected, as they carry no team." in r["sum"], f"the summary does not say why: {r['sum']!r}")


@SUITE.test("a_feed_that_could_not_be_read_gives_a_notice_never_an_empty_group")
def _(t: T):
    url, data, hol = page(mutate=lambda d: d.__setitem__("prs", {"org": "example-org", "at": "2026-01-01T00:00+02:00", "unavailable": "GitHub answered 502"}))
    r = load(url)
    t.check(r["name"] is None, "a group is shown for an unread feed")
    t.check("Pull requests were not checked: GitHub answered 502." in r["sum"], f"no notice in the summary: {r['sum']!r}")
    t.check("Pull requests were not checked: GitHub answered 502." in r["limits"], "no notice in the Limits text")


@SUITE.test("a_feed_kept_from_an_earlier_read_says_it_was_not_refreshed_and_since_when")
def _(t: T):
    def m(d):
        d["prs"]["refreshFailed"] = "no GitHub token (set NICE_GH_READ_TOKEN)"
    url, data, hol = page(mutate=m)
    r = load(url)
    t.check(len(r["rows"]) == len(oracle(data, hol)), "the kept list is not used")
    t.check("Pull requests were not refreshed (no GitHub token (set NICE_GH_READ_TOKEN)); as of " in r["sum"], f"no notice: {r['sum']!r}")


@SUITE.test("a_payload_with_no_feed_has_no_group_and_the_limits_text_says_the_pull_requests_were_not_read")
def _(t: T):
    url, data, hol = page(mutate=lambda d: d.pop("prs"))
    r = load(url)
    t.check(r["name"] is None and "Pull requests were not" not in r["sum"], f"a payload without the feed shows {r['name']!r} / {r['sum']!r}")
    t.check("The pull requests were not read in this build." in r["limits"], "the Limits text does not say the pull requests were not read")


@SUITE.test("only_the_pull_requests_of_the_selected_release_are_listed_and_one_with_no_release_never_is")
def _(t: T):
    url, data, hol = page()
    r = load(url)
    keys = [x["key"] for x in r["rows"]]
    t.check("svc-delta#111" not in keys and "svc-delta#112" not in keys, f"a pull request of another release or of none is listed under 27.1: {keys}")
    t.check("svc-delta#113" in keys, "a pull request in two releases is missing under 27.1")
    r = load(url, "state.release = '27.2'; update();")
    t.check([x["key"] for x in r["rows"]] == [w[0] for w in oracle(data, hol, release="27.2")] == ["svc-delta#111"], f"27.2: {[x['key'] for x in r['rows']]}")
    r = load(url, "state.release = '26.4'; update();")
    t.check([x["key"] for x in r["rows"]] == ["svc-delta#113"], f"26.4: {[x['key'] for x in r['rows']]}")
    t.check("of release 26.4" in r["limits"] and "belong to other releases or to none" in r["limits"], f"the Checked text does not name the release: {r['limits'][:400]!r}")
    r = load(url, "state.release = '25.4'; update();")
    t.check(r["name"] is None, "a group is shown for a release no pull request belongs to")


@SUITE.test("releases_that_could_not_be_read_give_a_notice_never_a_list_of_every_release")
def _(t: T):
    url, data, hol = page(mutate=lambda d: d["prs"].__setitem__("releasesUnavailable", "HTTPError: 503"))
    r = load(url)
    t.check(r["name"] is None, "a group is shown although the releases are unknown")
    t.check("Pull requests were not checked against the release: HTTPError: 503." in r["sum"], f"no notice: {r['sum']!r}")
    url, data, hol = page(mutate=lambda d: [x.pop("rl") for x in d["prs"]["list"]])
    r = load(url)
    t.check(r["name"] is None and "were not checked against the release: their releases were not read in this build." in r["sum"], f"a payload without releases: {r['name']!r} / {r['sum']!r}")


@SUITE.test("selftest_the_check_fails_when_the_limit_is_read_as_3_or_more")
def _(t: T):
    src = ctx.template.read_text(encoding="utf-8")
    marker = "const bd = businessDaysSince(x.ra); if (bd <= prCfg.days) return;"
    if marker not in src:
        raise kit.Skip("this template has no pull request limit to break")
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(src.replace(marker, "const bd = businessDaysSince(x.ra); if (bd < prCfg.days) return;"))
    url, data, hol = page(Path(f.name))
    Path(f.name).unlink()
    r = load(url)
    t.check([x["key"] for x in r["rows"]] != [w[0] for w in oracle(data, hol)], "the check passed with exactly 3 business days counted: it is blind")


@SUITE.test("selftest_the_check_fails_when_the_team_is_left_out_of_the_second_line")
def _(t: T):
    src = ctx.template.read_text(encoding="utf-8")
    marker = '${[Array.isArray(x.tm) && x.tm.length ? x.tm.join(", ") : "", Array.isArray(x.pd) && x.pd.length ? x.pd.join(", ") : ""].filter(Boolean).map(v => v + " · ").join("")}'
    if marker not in src:
        raise kit.Skip("this template does not show the team")
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(src.replace(marker, ""))
    url, data, hol = page(Path(f.name))
    Path(f.name).unlink()
    r = load(url)
    by = {x["key"]: x for x in r["rows"]}
    t.check("Team Alpha" not in by["svc-alpha#103"]["sub"], "the seeded page without teams still shows one: the check is blind")


if __name__ == "__main__":
    sys.exit(kit.cli(SUITE, __doc__))
