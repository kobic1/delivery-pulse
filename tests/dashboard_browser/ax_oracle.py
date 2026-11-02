#!/usr/bin/env python3
"""The Accessibility Bugs control of the Quality section (hash `ax`): a three-way segmented control, All / Yes / No, that works like the CFB control next to it.

  No  (the default, no `ax` in the address)  accessibility bugs are left out, as in the weekly email
  All (`ax=all`)                             accessibility bugs and the other bugs
  Yes (`ax=yes`)                             only accessibility bugs
  `ax=1` (an older link, the ticked checkbox) opens as All.

The checks, all on the fictitious fixture (nothing real in this folder):

  * an independent Python recount of the Open Bugs tile, Open P1 and P2, Created and Resolved in the last 4 weeks, Net Backlog Change, the Open Bugs by Project and Priority
    table and the weekly series of the Open Bugs Trend (created, resolved, open at each week end, the peak), for Priority x CFB x Accessibility Bugs, compared with the page;
  * every link of the section (tiles, the headline sentence, the table cells, every mark of the trend and its data table) is evaluated with jql_eval.py over the baked bugs and
    must find exactly the bugs the recount puts behind that number, within the 6,000 character URL budget; the Accessibility clause of each link is the one the state calls for;
  * the default state keeps the numbers and the Open Bugs link it always had; the hash round trip; the control is markup-for-markup the CFB control and works from the keyboard
    the same way; the active-filter indicator and Reset; 320 px; the empty states; the Customer-Found Bugs section does not move with the control;
  * `oracle_selftest_*` seeds defects into a copy of the template (Yes behaving like All, All behaving like No, Yes excluding instead of selecting, a link that ignores the state,
    a trend that ignores the state, a hash that does not round trip, a regression of the CFB control ...) and requires the oracle to fail on each.

The fixture is used twice: as it is, and as a variant in which more bugs are flagged as accessibility bugs (open P1 and P2, created and resolved in the last 4 weeks, customer-found,
without a priority) so that every number under Yes is non-trivial. The shared fixture is not changed.

    python3 ax_oracle.py [--live] [--only NAME]
"""
from __future__ import annotations

import copy
import datetime as dt
import itertools
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import jql_eval as J                                                                # noqa: E402
import kit                                                                          # noqa: E402
import make_synthetic as MS                                                         # noqa: E402
from kit import ctx, T                                                              # noqa: E402

SUITE = kit.Suite("Delivery Pulse Accessibility Bugs control")

CLOSED = {"Done", "Ready for Deploy", "Closed", "Resolved", "Removed"}            # a bug is open while its status is none of these (spelled here, not read from the page)
PRIORITIES = ["P1", "P2", "P3", "P4"]
URL_BUDGET = 6000
AX_NO = ' AND summary !~ "\\"[Accessibility]*\\"" AND (labels != DWP_Accessibility_Defect OR labels is EMPTY)'
AX_YES = ' AND (summary ~ "\\"[Accessibility]*\\"" OR labels = DWP_Accessibility_Defect)'     # the clause the collector (AX_JQL) and the Refresh already use
WORDS = {"no": "excluding accessibility bugs", "all": "including accessibility bugs", "yes": "only accessibility bugs"}

# ---------------------------------------------------------------------------------------------------------------------------------------------------------------- the fixture
_cache: dict = {}


def fixture() -> dict:
    """The fixture as it is ('base') and a variant ('var') with more accessibility bugs, deterministic and derived from the first."""
    if not _cache:
        base = MS.make(MS.il_today())
        var = copy.deepcopy(base)
        asof = asof_day(var)
        lo, hi = asof - dt.timedelta(days=27), asof
        n = 0
        for b in sorted(var["bugs"], key=lambda b: b["k"]):
            num = int(b["k"].split("-")[1])
            open_ = b["s"] not in CLOSED
            cr = dt.date.fromisoformat(b["cr"])
            rd = dt.date.fromisoformat(b["rd"]) if b.get("rd") else None
            interesting = (open_ and b.get("pr") in ("P1", "P2")) or (lo <= cr <= hi) or (rd is not None and lo <= rd <= hi) or (b.get("cfb") and num % 3 == 0)
            if interesting and num % 4 == 0 and not b.get("ax"):
                b["ax"] = 1
                n += 1
        for i, b in enumerate(b for b in var["bugs"] if b["s"] in CLOSED and b.get("ax")):
            if i % 5 == 0 and "pr" in b:
                del b["pr"]                                                           # an accessibility bug without a priority
        _cache.update(base=base, var=var, var_flagged=n,
                      u_base=ctx.write(kit.fragment_for(base), "ax_base"), u_var=ctx.write(kit.fragment_for(var), "ax_var"),
                      universe_base=[J.bug_issue(b, base["cfbAccount"]) for b in base["bugs"]], universe_var=[J.bug_issue(b, var["cfbAccount"]) for b in var["bugs"]],
                      team=base["cap"]["teams"][0])
    return _cache


def asof_day(data: dict) -> dt.date:
    ts = data.get("refreshedAt") or data["generated"]
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(MS.IL).date()


# ---------------------------------------------------------------------------------------------------------------------------------------------------------------- the page
SNAP_JS = r"""(() => {
  const tx = e => e ? e.textContent.replace(/\s+/g, ' ').trim() : '';
  const q = (s, r = document) => [...r.querySelectorAll(s)];
  const hr = a => a ? a.getAttribute('href') : null;
  const tiles = q('#bug-kpis .kpi').map(k => ({label: tx(k.querySelector('.l')), value: tx(k.querySelector('.v')), sub: tx(k.querySelector('.s')), href: hr(k.querySelector('.v a'))}));
  const head = q('#kpis .kpi').filter(k => tx(k.querySelector('.l')) === 'Open Bugs').map(k => ({value: tx(k.querySelector('.v')), sub: tx(k.querySelector('.s')), href: hr(k.querySelector('.v a'))}))[0] || null;
  const sub = document.getElementById('bugs-sub');
  const series = q('#bug-data tbody tr').map(tr => { const c = [...tr.children];
    return {week: tx(c[0]), created: tx(c[1]), createdHref: hr(c[1].querySelector('a')), resolved: tx(c[2]), resolvedHref: hr(c[2].querySelector('a')), open: tx(c[3])}; });
  const marks = q('#bug-chart a.cl, #bug-chart g.cl').map(a => ({href: hr(a), tip: a.getAttribute('data-tip')}));
  const table = q('#bug-table tbody tr').map(tr => { const c = [...tr.children];
    return {label: tx(c[0]), cells: c.slice(1, 6).map(td => ({text: tx(td), href: hr(td.querySelector('a'))})), trend: tx(c[6])}; });
  const radios = id => q('#' + id + ' input').map(i => ({value: i.value, checked: i.checked, on: i.parentElement.classList.contains('on')}));
  const g = document.getElementById('g-ax'), rb = document.getElementById('f-reset');
  return {tiles, head, subText: tx(sub), subLinks: q('a', sub).map(a => ({t: tx(a), href: hr(a)})), series, marks, table,
          empty: tx(document.querySelector('#bug-chart .empty')), left: tx(document.querySelector('#bugs-sub details')),
          ax: radios('f-ax'), cfb: radios('f-cfb'), stateAx: state.ax, stateCfb: state.cfb, hash: location.hash,
          changed: !!g && g.classList.contains('changed'), reset: rb ? tx(rb) : null, resetDisabled: rb ? rb.disabled : null, filters: tx(document.getElementById('f-toggle')),
          axCheckbox: !!document.querySelector('input[type=checkbox]#f-ax'), errors: 0};
})()"""

_snaps: dict = {}


def load(url: str, spec: str = "", team: str | None = None):
    """Open the page with the hash `spec` (TEAM stands for the first team of the fixture) and wait for it to draw."""
    ch = ctx.chrome
    ch.goto(url + ("#" + "&".join(f"t={urllib.parse.quote(team or '')}" if p == "TEAM" else p for p in spec.split("&")) if spec else ""))
    ok = kit.wait_ready(ch)
    return ok


def snapshot(url: str, spec: str = "", team: str | None = None) -> dict:
    key = (url, spec)
    if key not in _snaps:
        ch = ctx.chrome
        ok = load(url, spec, team)
        s = ch.js(SNAP_JS)
        if not isinstance(s, dict) or "__error" in s:
            s = {"__error": str(s)[:300]}
        s["errors"] = ch.console_errors()
        s["ready"] = ok
        _snaps[key] = s
    return _snaps[key]


# ---------------------------------------------------------------------------------------------------------------------------------------------------------------- the recount
def monday_weeks(asof: dt.date, n: int = 26) -> list[dt.date]:
    monday = asof - dt.timedelta(days=asof.weekday())
    return [monday - dt.timedelta(days=7 * i) for i in range(n - 1, -1, -1)]


def recount(data: dict, projects, teams, pri, cfb: str, ax: str) -> dict:
    """The Quality section's numbers and the bugs behind each, from the baked bugs alone. `pri` is the set of priorities ticked, `cfb` all|yes|no, `ax` no|yes|all."""
    asof = asof_day(data)
    pool = [b for b in data["bugs"] if b["p"] in projects and (not teams or (b.get("tm") or "(No Team)") in teams)]
    if ax == "no":
        pool = [b for b in pool if not b.get("ax")]
    elif ax == "yes":
        pool = [b for b in pool if b.get("ax")]
    if set(pri) != set(PRIORITIES):
        pool = [b for b in pool if b.get("pr") in pri]
    if cfb != "all":
        pool = [b for b in pool if bool(b.get("cfb")) == (cfb == "yes")]
    day = dt.date.fromisoformat
    opn = lambda b: b["s"] not in CLOSED
    weeks = monday_weeks(asof)
    series = []
    for w in weeks:
        e = w + dt.timedelta(days=7)
        cr = {b["k"] for b in pool if w <= day(b["cr"]) < e}
        rs = {b["k"] for b in pool if not opn(b) and b.get("rd") and w <= day(b["rd"]) < e}
        op = {b["k"] for b in pool if day(b["cr"]) < e and (opn(b) or (b.get("rd") and day(b["rd"]) >= e))}
        series.append({"w": w, "e": e, "created": cr, "resolved": rs, "open": op})
    last4 = series[-4:]
    open_now = {b["k"] for b in pool if opn(b)}
    p12 = {b["k"] for b in pool if opn(b) and b.get("pr") in ("P1", "P2")}
    created4 = set().union(*(s["created"] for s in last4))
    resolved4 = set().union(*(s["resolved"] for s in last4))
    peak = series[0]
    for s in series:
        if len(s["open"]) > len(peak["open"]):
            peak = s
    net = len(resolved4) - len(created4)
    thin = len(created4) + len(resolved4) < 5 or len(open_now) < 5
    # the table: one row per selected project that has bugs at all, then All Selected; the 2-week trend is open now against open at the end of the day 13 days ago
    then = asof - dt.timedelta(days=13)
    rows = []
    for p in [x for x in data["projects"] if x in projects and any(b["p"] == x for b in data["bugs"])] + [None]:
        sel = [b for b in pool if p is None or b["p"] == p]
        o = [b for b in sel if opn(b)]
        n_then = sum(1 for b in sel if day(b["cr"]) < then and (opn(b) or (b.get("rd") and day(b["rd"]) >= then)))
        rows.append({"label": p or "All Selected", "p": p, "open": {b["k"] for b in o}, "by": {k: {b["k"] for b in o if b.get("pr") == k} for k in PRIORITIES}, "d": len(o) - n_then})
    return {"asof": asof, "pool": pool, "open": open_now, "p12": p12, "created4": created4, "resolved4": resolved4, "series": series, "peak": peak, "net": net, "thin": thin,
            "last4": last4, "rows": rows}


def num(text: str):
    t = (text or "").replace(",", "").strip()
    return int(t) if t.isdigit() else None


def jql_of(href: str | None):
    if not href:
        return None
    q = urllib.parse.urlsplit(href)
    return urllib.parse.parse_qs(q.query, keep_blank_values=True).get("jql", [""])[0] if q.path.rstrip("/") == "/issues" else None


class Judge:
    """Evaluates the page's links with jql_eval over the baked bugs and compares what they find with the recount."""

    def __init__(self, universe, tag: str, problems: list):
        self.u, self.tag, self.p, self.n, self.cache = universe, tag, problems, 0, {}

    def found(self, jql: str):
        if jql not in self.cache:
            tree = J.parse(jql)
            self.cache[jql] = {x["key"] for x in self.u if J.evaluate(tree, x)}
        return self.cache[jql]

    def link(self, what: str, href, expect: set, printed=None, ax: str | None = None):
        if href is None:
            if num(printed) != 0 or expect:                                       # a zero is plain text, not a link (nothing to open)
                self.p.append(f"{self.tag} {what}: prints {printed!r} but is not a link, and the recount puts {len(expect)} bugs behind it")
            return
        self.n += 1
        jql = jql_of(href)
        if jql is None:
            self.p.append(f"{self.tag} {what}: not a Jira query link: {href[:100]}")
            return
        if len(href) > URL_BUDGET:
            self.p.append(f"{self.tag} {what}: the link is {len(href)} characters long")
        try:
            got = self.found(jql)
        except (J.Malformed, J.Unsupported) as e:
            self.p.append(f"{self.tag} {what}: the query cannot be evaluated ({e}): {jql[:140]}")
            return
        if got != expect:
            self.p.append(f"{self.tag} {what}: the query finds {len(got)} bugs, the recount puts {len(expect)} behind it ({len(got - expect)} too many, {len(expect - got)} missing): {jql[-170:]}")
        if printed is not None and num(printed) != len(expect):
            self.p.append(f"{self.tag} {what}: the page prints {printed}, the recount gives {len(expect)}")
        if ax is not None:
            want = {"no": AX_NO, "yes": AX_YES}.get(ax)
            if want and want not in jql:
                self.p.append(f"{self.tag} {what}: the query does not carry the Accessibility clause of {ax.upper()}: {jql[:200]}")
            if ax == "all" and re.search(r"accessib", jql, re.I):
                self.p.append(f"{self.tag} {what}: a query of the All state names accessibility: {jql[:200]}")
            if ax == "yes" and "!~" in jql:
                self.p.append(f"{self.tag} {what}: a query of the Yes state excludes accessibility bugs: {jql[:200]}")


def view_spec(pri, cfb: str, ax: str, extra: str = "") -> str:
    parts = [extra] if extra else []
    if set(pri) != set(PRIORITIES):
        parts.append("bp=" + "|".join(sorted(pri)))
    if cfb != "all":
        parts.append("cfb=" + cfb)
    if ax != "no":
        parts.append("ax=" + ax)
    return "&".join(parts)


def check_view(F: dict, which: str, projects, teams, pri, cfb: str, ax: str, extra: str = "", links: bool = True) -> list[str]:
    """One filter state: the printed numbers, the table, the trend and (links=True) every link of the section against the recount."""
    data, url, universe = F[which], F["u_" + which], F["universe_" + which]
    spec = view_spec(pri, cfb, ax, extra)
    tag = f"[{which} {spec or '(default)'}]"
    s = snapshot(url, spec, F["team"])
    out: list[str] = []
    if "__error" in s or not s.get("ready") or s["errors"]:
        return [f"{tag} the page did not draw cleanly: {s.get('__error') or s['errors'][:2]}"]
    R = recount(data, projects, teams, pri, cfb, ax)
    tiles = {t["label"]: t for t in s["tiles"]}
    if list(tiles) != ["Open Bugs", "Open P1 and P2", "Created, Last 4 Weeks", "Resolved, Last 4 Weeks", "Net Backlog Change"]:
        return [f"{tag} the five Quality tiles are {list(tiles)}"]
    J_ = Judge(universe, tag, out)
    a = F["asof_fmt"] = R["asof"].isoformat()
    t = tiles["Open Bugs"]
    J_.link("Open Bugs tile", t["href"], R["open"], t["value"], ax if links else None)
    if t["sub"] != f"as of {a}":
        out.append(f"{tag} Open Bugs tile sub line '{t['sub']}', expected 'as of {a}'")
    t = tiles["Open P1 and P2"]
    J_.link("Open P1 and P2 tile", t["href"], R["p12"], t["value"], ax if links else None)
    n_open = len(R["open"])
    exp_sub = f"{round(100 * len(R['p12']) / n_open)}% of open bugs" if n_open >= 5 else f"{len(R['p12'])} of {n_open} open bugs" if n_open else "none open"
    if t["sub"].replace("%", "%") != exp_sub and not (n_open >= 5 and abs(int(t["sub"].split("%")[0]) - 100 * len(R["p12"]) / n_open) <= 0.5001):
        out.append(f"{tag} Open P1 and P2 sub line '{t['sub']}', expected '{exp_sub}'")
    t = tiles["Created, Last 4 Weeks"]
    J_.link("Created tile", t["href"], R["created4"], t["value"], ax if links else None)
    t = tiles["Resolved, Last 4 Weeks"]
    J_.link("Resolved tile", t["href"], R["resolved4"], t["value"], ax if links else None)
    net = tiles["Net Backlog Change"]["value"]
    exp_net = "–" if R["thin"] else "0" if R["net"] == 0 else f"{'▼' if R['net'] > 0 else '▲'} {abs(R['net'])}"
    if net.replace(",", "") != exp_net:
        out.append(f"{tag} Net Backlog Change '{net}', the recount gives '{exp_net}'")
    # the headline tile of the page
    h = s["head"]
    if not h:
        out.append(f"{tag} no Open Bugs tile in the headline")
    else:
        J_.link("headline Open Bugs tile", h["href"], R["open"], h["value"], ax if links else None)
        filtered = set(pri) != set(PRIORITIES) or cfb != "all"
        want = f"{WORDS[ax]}{'; Priority or CFB filter on' if filtered else ''}"
        if not h["sub"].startswith(want):
            out.append(f"{tag} the headline Open Bugs tile says '{h['sub']}', expected it to start with '{want}'")
    # the sentence under the title: open count and the peak
    pk = R["peak"]
    sl = s["subLinks"]
    if len(sl) < 2:
        out.append(f"{tag} the sentence under the title has {len(sl)} links, expected the open count and the peak")
    else:
        J_.link("sentence: open bugs", sl[0]["href"], R["open"], sl[0]["t"], ax if links else None)
        J_.link("sentence: peak", sl[1]["href"], pk["open"], sl[1]["t"], ax if links else None)
        if f"(week of {pk['w'].isoformat()})" not in s["subText"]:
            out.append(f"{tag} the sentence does not name the peak week {pk['w'].isoformat()}: {s['subText'][-140:]}")
    # the weekly data table = the series
    if len(s["series"]) != 26:
        out.append(f"{tag} the trend table has {len(s['series'])} weeks, expected 26")
    else:
        for w, row in zip(R["series"], s["series"]):
            d = w["w"].isoformat()
            if row["week"] != d:
                out.append(f"{tag} the trend table lists the week {row['week']}, expected {d}")
                continue
            J_.link(f"week {d} created", row["createdHref"], w["created"], row["created"], ax if links else None)
            J_.link(f"week {d} resolved", row["resolvedHref"], w["resolved"], row["resolved"], ax if links else None)
            if num(row["open"]) != len(w["open"]):
                out.append(f"{tag} week {d}: open at week end is {row['open']}, the recount gives {len(w['open'])}")
    # the marks of the chart: open at each week end, created, resolved (the series itself, with its links and hover text)
    seen = {"open at week end": {}, "created": {}, "resolved": {}}
    for m in s["marks"]:
        mm = re.match(r"Week of (\d{4}-\d\d-\d\d)(?: \(running\))?\n([\d,]+) (open at week end|created|resolved)", m["tip"] or "")
        if mm:
            seen[mm.group(3)][mm.group(1)] = (mm.group(2), m["href"])
    for w in R["series"]:
        d = w["w"].isoformat()
        for kind, field in (("open at week end", "open"), ("created", "created"), ("resolved", "resolved")):
            got = seen[kind].get(d)
            if not got:
                out.append(f"{tag} the chart has no '{kind}' mark for the week {d}")
                continue
            J_.link(f"chart mark {kind} {d}", got[1], w[field], got[0], ax if links else None)
    # the table by project and priority
    rows = {r["label"]: r for r in s["table"]}
    exp_labels = [r["label"] for r in R["rows"]]
    if [r["label"] for r in s["table"]] != exp_labels:
        out.append(f"{tag} the table rows are {[r['label'] for r in s['table']]}, expected {exp_labels}")
    else:
        for er in R["rows"]:
            row = rows[er["label"]]
            for k, c in zip(PRIORITIES, row["cells"][:4]):
                if er["by"][k] or num(c["text"]) is not None and c["href"]:
                    J_.link(f"table {er['label']} {k}", c["href"], er["by"][k], c["text"], ax if links else None)
                if (num(c["text"]) or 0) != len(er["by"][k]):
                    out.append(f"{tag} table {er['label']} {k}: {c['text']}, the recount gives {len(er['by'][k])}")
            tot = row["cells"][4]
            J_.link(f"table {er['label']} Total", tot["href"], er["open"], tot["text"], ax if links else None)
            if (num(tot["text"]) or 0) != len(er["open"]):
                out.append(f"{tag} table {er['label']} Total: {tot['text']}, the recount gives {len(er['open'])}")
            d = er["d"]
            want = ("▲ +" if d > 0 else "▼ −" if d < 0 else "") + f"{abs(d)}"
            if not row["trend"].startswith(want):
                out.append(f"{tag} table {er['label']} trend '{row['trend']}', expected it to start with '{want}'")
    if links and J_.n < 90:
        out.append(f"{tag} only {J_.n} links were judged (the check is blind)")
    s["judged"] = J_.n
    return out


PRI_SETS = [list(PRIORITIES), ["P1", "P2"], ["P3"]]
CFBS = ["all", "yes", "no"]
AXS = ["no", "yes", "all"]
ALL_PROJECTS = None                                                                  # filled from the payload


def projects_of(data: dict) -> list[str]:
    return list(data["projects"])


# ---------------------------------------------------------------------------------------------------------------------------------------------------------------- tests
@SUITE.test("ax_the_fixture_has_every_kind_of_bug_the_recount_needs")
def _(t: T):
    F = fixture()
    for which in ("base", "var"):
        d = F[which]
        a = asof_day(d)
        lo = a - dt.timedelta(days=27)
        bugs = d["bugs"]
        day = dt.date.fromisoformat
        opn = lambda b: b["s"] not in CLOSED
        ax = [b for b in bugs if b.get("ax")]
        t.check(len(ax) >= 20 and len([b for b in bugs if not b.get("ax")]) >= 200, f"{which}: {len(ax)} accessibility bugs among {len(bugs)}")
        t.check(len({b["p"] for b in ax}) >= 5, f"{which}: accessibility bugs in {len({b['p'] for b in ax})} projects")
        t.check(any(opn(b) for b in ax) and any(not opn(b) for b in ax), f"{which}: open and closed accessibility bugs")
        t.check(any(b.get("cfb") for b in ax) and any(not b.get("cfb") for b in ax), f"{which}: accessibility bugs that are customer-found and that are not")
        if which == "var":
            t.check(len([b for b in ax if opn(b) and b.get("pr") in ("P1", "P2")]) >= 3, "var: at least three open P1 or P2 accessibility bugs")
            t.check(len([b for b in ax if day(b["cr"]) >= lo]) >= 5, "var: at least five accessibility bugs created in the last four weeks")
            t.check(len([b for b in ax if b.get("rd") and day(b["rd"]) >= lo and not opn(b)]) >= 3, "var: at least three accessibility bugs resolved in the last four weeks")
            t.check(len([b for b in ax if opn(b) and b.get("cfb")]) >= 1, "var: an open customer-found accessibility bug")
            t.check(any("pr" not in b for b in ax) and any(b.get("pr") in ("P3", "P4") for b in ax), "var: accessibility bugs without a priority and with P3 or P4")
            t.check(len([b for b in ax if opn(b)]) >= 8, f"var: {len([b for b in ax if opn(b)])} open accessibility bugs")
    t.note(f"variant: {F['var_flagged']} more bugs flagged as accessibility bugs")


def _states_variant():
    out = []
    for pri, cfb, ax in itertools.product(PRI_SETS, CFBS, AXS):
        out.append((pri, cfb, ax, ""))
    return out


@SUITE.test("ax_numbers_table_trend_and_every_link_equal_an_independent_recount")
def _(t: T):
    """Priority x CFB x Accessibility Bugs (27 states) on the variant, and CFB x Accessibility Bugs on the fixture itself, with a project and a team subset: the page equals the recount,
    and every link of the section, run through the JQL evaluator, finds exactly the bugs behind its number."""
    F = fixture()
    allp = projects_of(F["var"])
    bad, n, judged = [], 0, 0
    for pri, cfb, ax, extra in _states_variant():
        bad += check_view(F, "var", allp, set(), pri, cfb, ax)
        n += 1
        judged += _snaps[(F["u_var"], view_spec(pri, cfb, ax))].get("judged", 0)
    for cfb, ax in itertools.product(CFBS, AXS):
        bad += check_view(F, "base", allp, set(), PRIORITIES, cfb, ax)
        n += 1
    for ax in AXS:                                                                    # a project subset, and a project with a team
        bad += check_view(F, "var", ["PMN", "CXCO"], set(), PRIORITIES, "all", ax, "p=PMN|CXCO")
        bad += check_view(F, "var", ["PMN"], {F["team"]}, ["P1", "P2"], "no", ax, "p=PMN&TEAM")
        n += 2
    for b in sorted(set(bad))[:15]:
        t.failures.append(b)
    t.passed += 0 if bad else 1
    t.note(f"{n} filter states compared with the recount; {judged} links judged in the 27 variant states")


@SUITE.test("ax_the_states_differ_from_each_other_so_the_check_is_not_blind")
def _(t: T):
    F = fixture()
    allp = projects_of(F["var"])
    R = {ax: recount(F["var"], allp, set(), PRIORITIES, "all", ax) for ax in AXS}
    t.check(len(R["yes"]["open"]) >= 8 and len(R["no"]["open"]) > len(R["yes"]["open"]), f"open bugs: No {len(R['no']['open'])}, Yes {len(R['yes']['open'])}, All {len(R['all']['open'])}")
    t.check(len(R["all"]["open"]) == len(R["no"]["open"]) + len(R["yes"]["open"]), "All = No + Yes (the two halves do not overlap)")
    for k in ("p12", "created4", "resolved4"):
        t.check(len(R["yes"][k]) >= 2 and len(R["no"][k]) != len(R["all"][k]) and len(R["yes"][k]) != len(R["all"][k]), f"{k}: No {len(R['no'][k])}, Yes {len(R['yes'][k])}, All {len(R['all'][k])}")
    t.check(len({tuple(len(s["open"]) for s in R[ax]["series"]) for ax in AXS}) == 3, "the three trend series are three different series")
    t.check(R["yes"]["peak"]["w"] is not None and len(R["yes"]["peak"]["open"]) >= 3, f"the Yes peak is {len(R['yes']['peak']['open'])}")
    t.note(f"open bugs No {len(R['no']['open'])} / Yes {len(R['yes']['open'])} / All {len(R['all']['open'])}; peak No {len(R['no']['peak']['open'])} / Yes {len(R['yes']['peak']['open'])} / All {len(R['all']['peak']['open'])}")


@SUITE.test("ax_the_default_state_is_what_the_unticked_checkbox_gave")
def _(t: T):
    """No is the default: the address carries no `ax`, the numbers are the recount without accessibility bugs, and the Open Bugs link is the query it always was."""
    F = fixture()
    data = F["base"]
    s = snapshot(F["u_base"], "", None)
    t.check(s["stateAx"] == "no" and [r["value"] for r in s["ax"] if r["checked"]] == ["no"], f"the default is No: state {s['stateAx']}, radios {s['ax']}")
    t.check("ax" not in urllib.parse.parse_qs(s["hash"].lstrip("#")) and s["hash"] in ("", "#r=" + data["current"]), f"the default address carries no ax: {s['hash']}")
    tile = next(x for x in s["tiles"] if x["label"] == "Open Bugs")
    want = ("project in (" + ", ".join(kit.jqlkey(p) for p in data["projects"]) + ") AND issuetype = Bug" + AX_NO +
            ' AND status not in (Done, "Ready for Deploy", Closed, Resolved, Removed)')
    t.check(jql_of(tile["href"]) == want, f"the default Open Bugs link is the old query:\n  {jql_of(tile['href'])}\n  {want}")
    t.check(not s["changed"] and s["resetDisabled"] and s["reset"] == "Reset Filters" and s["filters"] == "Filters", f"nothing counts as changed in the default state: {s['reset']!r} {s['filters']!r} {s['changed']}")
    explicit = snapshot(F["u_base"], "ax=no", None)
    t.check(explicit["tiles"] == s["tiles"] and explicit["series"] == s["series"] and explicit["stateAx"] == "no", "an explicit ax=no is the default view")
    R = recount(data, projects_of(data), set(), PRIORITIES, "all", "no")
    t.check(num(tile["value"]) == len(R["open"]), f"default Open Bugs {tile['value']} = recount {len(R['open'])}")
    t.note(f"fixture default: Open Bugs {tile['value']}, peak {R['peak']['open'].__len__()}")


@SUITE.test("ax_the_checkbox_is_gone_and_the_group_is_the_cfb_group_in_markup")
def _(t: T):
    F = fixture()
    ch = ctx.chrome
    load(F["u_base"], "")
    m = ch.js(r"""(() => {
      const sig = id => { const g = document.getElementById(id), fg = g.closest('.fg'); const strip = h => h.replace(/\b(f|g|lbl)-(cfb|ax)\b/g, '$1-X').replace(/name="f-(cfb|ax)"/g, 'name="f-X"').replace(/value="[a-z]+"/g, 'value=V').replace(/ checked=""/g, '').replace(/class="chip on"/g, 'class="chip"');
        return {role: g.getAttribute('role'), labelledby: g.getAttribute('aria-labelledby'), cls: g.className, fgCls: fg.className.replace(/\bchanged\b/g, '').trim(),
                label: (document.getElementById(g.getAttribute('aria-labelledby')) || {}).textContent, labelTag: (document.getElementById(g.getAttribute('aria-labelledby')) || {}).tagName,
                values: [...g.querySelectorAll('input')].map(i => i.value), texts: [...g.querySelectorAll('label')].map(l => l.textContent.trim()), types: [...g.querySelectorAll('input')].map(i => i.type),
                names: [...new Set([...g.querySelectorAll('input')].map(i => i.name))], tabindex: [...g.querySelectorAll('input')].map(i => i.getAttribute('tabindex')), html: strip(fg.outerHTML.replace(/>\s+</g, '><')).replace(/Salesforce Connector|Accessibility Bugs/g, 'L').replace(/CFB \(Reported by L\)/, 'L')};
      };
      return {ax: sig('f-ax'), cfb: sig('f-cfb'), checkboxes: document.querySelectorAll('#g-ax input[type=checkbox], input#f-ax[type=checkbox]').length, body: document.body.innerText + ' ' + document.body.innerHTML.replace(/<[^>]+>/g, ' '),
              inBar: !!document.querySelector('.bugbar #g-ax'), order: [...document.querySelectorAll('.bugbar > *')].map(e => e.id)};
    })()""")
    a, c = m["ax"], m["cfb"]
    t.check(m["checkboxes"] == 0, "no checkbox is left in the Accessibility Bugs control")
    t.check("Include Accessibility Bugs" not in m["body"], "the words 'Include Accessibility Bugs' appear nowhere on the page")
    t.check(a["role"] == "radiogroup" and a["labelledby"] == "lbl-ax" and a["label"] == "Accessibility Bugs" and a["labelTag"] == "SPAN", f"a radiogroup named by its legend Accessibility Bugs: {a['role']} {a['labelledby']} {a['label']!r}")
    t.check(a["values"] == ["all", "yes", "no"] and a["texts"] == ["All", "Yes", "No"], f"three buttons All, Yes, No in that order: {a['values']} {a['texts']}")
    t.check(a["types"] == ["radio"] * 3 and a["names"] == ["f-ax"] and a["tabindex"] == [None] * 3, f"native radios of one group, no tabindex: {a['types']} {a['names']} {a['tabindex']}")
    t.check(a["cls"] == c["cls"] == "chips seg" and a["fgCls"] == c["fgCls"] == "fg", f"the same classes as CFB: '{a['cls']}' / '{c['cls']}', '{a['fgCls']}' / '{c['fgCls']}'")
    t.check(a["values"] == c["values"] and a["texts"] == c["texts"] and a["role"] == c["role"] and a["labelTag"] == c["labelTag"], "the same values, button texts, role and legend element as CFB")
    t.check(a["html"] == c["html"], f"the markup of the two groups is identical apart from ids, names and the legend text:\n  {a['html']}\n  {c['html']}")
    t.check(m["inBar"] and m["order"] == ["g-bpri", "g-cfb", "g-ax"], f"the control sits in the Quality filter row after CFB: {m['order']}")


def _hash_after(ch, js: str) -> str:
    ch.js(js)
    time.sleep(0.25)
    return ch.js("location.hash")


@SUITE.test("ax_hash_round_trip_and_the_old_link")
def _(t: T):
    F = fixture()
    ch = ctx.chrome
    url = F["u_base"]
    for spec, want in (("ax=yes", "yes"), ("ax=all", "all"), ("ax=1", "all"), ("ax=no", "no"), ("ax=maybe", "no"), ("ax=0", "no"), ("ax=YES", "no"), ("bp=P1|P2&ax=yes&cfb=no", "yes"), ("cfb=yes&ax=1", "all")):
        s = snapshot(url, spec, None)
        t.check(s["stateAx"] == want and [r["value"] for r in s["ax"] if r["checked"]] == [want] and [r["value"] for r in s["ax"] if r["on"]] == [want],
                f"#{spec} opens as {want.upper()}: state {s['stateAx']}, radios {s['ax']}")
        t.check(not s["errors"], f"#{spec} raises errors: {s['errors'][:2]}")
        t.check(s["tiles"][0]["sub"] != "" and WORDS[want] in next(x for x in [s["head"]])["sub"], f"#{spec}: the headline says '{WORDS[want]}': {s['head']['sub']}")
    sel = lambda v: f"(() => {{ const i = document.querySelector('#f-ax input[value=\"{v}\"]'); i.click(); return location.hash; }})()"
    load(url, "")
    for v in ("yes", "all", "no", "yes", "no"):
        h = _hash_after(ch, sel(v))
        q = urllib.parse.parse_qs(h.lstrip("#"))
        if v == "no":
            t.check("ax" not in q, f"No writes no ax: {h}")
        else:
            t.check(q.get("ax") == [v], f"{v.title()} writes ax={v}: {h}")
        t.check(ch.js("state.ax") == v and ch.js("document.querySelector('#f-ax input:checked').value") == v, f"clicking {v.title()} selects it")
    # the address survives a reload and keeps the other filters
    load(url, "")
    ch.js(sel("yes"))
    ch.js("document.querySelector('#f-cfb input[value=\"no\"]').click()")
    time.sleep(0.25)
    h = ch.js("location.hash")
    t.check("ax=yes" in h and "cfb=no" in h, f"both controls are in the address: {h}")
    ch.goto("about:blank")
    ch.goto(url + h)
    kit.wait_ready(ch)
    t.check(ch.js("state.ax + '/' + state.cfb") == "yes/no", f"a reload of that address restores both: {ch.js('state.ax + chr(47) + state.cfb')}")
    # the stored state of the published page: serialize() carries the same words
    t.check("ax=yes" in ch.js("serialize()") and "ax=" not in (ch.js("state.ax = 'no'; serialize()") or ""), "serialize() writes ax=yes and omits No")


KEYS = {"ArrowRight": (39, "ArrowRight", ""), "ArrowLeft": (37, "ArrowLeft", ""), "ArrowDown": (40, "ArrowDown", ""), "ArrowUp": (38, "ArrowUp", ""), "Space": (32, " ", " "), "Enter": (13, "Enter", "\r"),
        "Tab": (9, "Tab", "")}


def press(ch, name: str):
    code, key, text = KEYS[name]
    for ty in ("rawKeyDown", "keyDown", "keyUp") if text else ("rawKeyDown", "keyUp"):
        ch.cmd("Input.dispatchKeyEvent", type=ty, key=key, code=name if name != "Space" else "Space", windowsVirtualKeyCode=code, nativeVirtualKeyCode=code, text=text if ty == "keyDown" else "", unmodifiedText=text if ty == "keyDown" else "")
    time.sleep(0.2)


GROUP_JS = """(g, st) => ({checked: (document.querySelector('#f-' + g + ' input:checked') || {}).value, focus: document.activeElement && document.activeElement.closest && document.activeElement.closest('#f-' + g) ? document.activeElement.value : null,
  state: state[st], hash: location.hash, on: [...document.querySelectorAll('#f-' + g + ' input')].filter(i => i.parentElement.classList.contains('on')).map(i => i.value),
  tabbable: [...document.querySelectorAll('#f-' + g + ' input')].filter(i => i.tabIndex >= 0).length, ring: document.activeElement && document.activeElement.matches && document.activeElement.matches(':focus-visible')})"""


def drive(ch, g: str, st: str, start: str, seq: list[str]) -> list[dict]:
    """Focus the radio `start` of group g (selecting it by click first), press the keys one by one; the observations after each."""
    ch.js(f"(() => {{ const i = document.querySelector('#f-{g} input[value=\"{start}\"]'); i.click(); i.focus(); }})()")
    time.sleep(0.25)
    obs = []
    fn = GROUP_JS
    for k in seq:
        press(ch, k)
        r = ch.js(f"({fn})('{g}', '{st}')")
        h = urllib.parse.parse_qs((r.get("hash") or "").lstrip("#"))
        obs.append({"key": k, "checked": r["checked"], "focus": r["focus"], "state": r["state"], "on": r["on"], "inHash": h.get(st if g == "cfb" else "ax", [None])[0], "tabbable": r["tabbable"]})
    return obs


@SUITE.test("ax_keyboard_works_as_the_cfb_group_does")
def _(t: T):
    """The same key sequence on both groups, from the same starting button: the same outcomes (value moves with the arrows and wraps, Space selects the focused one, Enter changes nothing, focus stays on the
    chosen button after the page redraws, one Tab stop per group), the state and the address follow."""
    F = fixture()
    ch = ctx.chrome
    seqs = [["ArrowRight", "ArrowRight", "ArrowRight", "ArrowLeft", "ArrowDown", "ArrowUp", "Enter", "Space"], ["ArrowLeft", "ArrowLeft", "ArrowRight", "ArrowDown", "ArrowDown"]]
    for start in ("all", "yes", "no"):
        for seq in (seqs if start == "yes" else seqs[:1]):
            load(F["u_base"], "")
            a = drive(ch, "ax", "ax", start, seq)
            load(F["u_base"], "")
            c = drive(ch, "cfb", "cfb", start, seq)
            strip = lambda o: [{k: v for k, v in x.items() if k != "inHash"} for x in o]
            t.check(strip(a) == strip(c), f"start {start}, keys {seq}: the AX group behaves differently from CFB\n   AX  {[(x['key'], x['checked'], x['focus']) for x in a]}\n   CFB {[(x['key'], x['checked'], x['focus']) for x in c]}")
            for x in a:
                t.check(x["checked"] == x["state"] and x["checked"] == x["focus"] and x["on"] == [x["checked"]],
                        f"start {start}: after {x['key']} the value {x['checked']}, the state {x['state']}, the focus {x['focus']}, the highlighted {x['on']} disagree")
                t.check((x["inHash"] == x["checked"]) if x["checked"] != "no" else x["inHash"] is None, f"start {start}: after {x['key']} the address says {x['inHash']} for {x['checked']}")
    # Space on a focused, unselected button selects it (as in CFB); Enter on it does not
    for g, st in (("ax", "ax"), ("cfb", "cfb")):
        load(F["u_base"], "")
        ch.js(f"(() => {{ document.querySelector('#f-{g} input[value=\"no\"]').click(); document.querySelector('#f-{g} input[value=\"yes\"]').focus(); }})()")
        time.sleep(0.2)
        press(ch, "Enter")
        e1 = ch.js(f"state.{st}")
        press(ch, "Space")
        e2 = ch.js(f"state.{st}")
        t.check((e1, e2) == ("no", "yes"), f"{g}: Enter on an unselected button changes nothing, Space selects it: {(e1, e2)}")
    # Tab walks the row: the selected button of CFB, then the selected button of Accessibility Bugs, then out of the group (one stop per group)
    load(F["u_base"], "ax=yes&cfb=no")
    ch.js("document.querySelector('#f-cfb input:checked').focus()")
    where = lambda: ch.js("(() => { const a = document.activeElement; const g = a && a.closest && a.closest('.chips.seg'); return g ? g.id + ':' + a.value : (a && (a.id || a.tagName)); })()")
    t.check(where() == "f-cfb:no", f"the focus starts on the selected CFB button: {where()}")
    press(ch, "Tab")
    t.check(where() == "f-ax:yes", f"Tab from CFB lands on the selected Accessibility Bugs button: {where()}")
    press(ch, "Tab")
    t.check(not str(where()).startswith("f-ax:") and not str(where()).startswith("f-cfb:"), f"the next Tab leaves the group: {where()}")


@SUITE.test("ax_the_active_filter_indicator_and_reset_treat_the_states_as_cfb_is_treated")
def _(t: T):
    F = fixture()
    ch = ctx.chrome
    url = F["u_base"]
    for spec, n, ax_on in (("", 0, False), ("ax=yes", 1, True), ("ax=all", 1, True), ("ax=no", 0, False), ("ax=yes&cfb=yes", 2, True), ("ax=1&cfb=no", 2, True), ("cfb=yes", 1, False)):
        s = snapshot(url, spec, None)
        t.check(s["changed"] == ax_on, f"#{spec or '(default)'}: the Accessibility Bugs group is marked as changed: {s['changed']}, expected {ax_on}")
        want_reset = f"Reset Filters ({n})" if n else "Reset Filters"
        t.check(s["reset"] == want_reset and s["resetDisabled"] == (not n), f"#{spec or '(default)'}: the reset button says {s['reset']!r}, expected {want_reset!r}")
        t.check(s["filters"] == (f"Filters ({n} Applied)" if n else "Filters"), f"#{spec or '(default)'}: the filters toggle says {s['filters']!r}")
    # CFB: the same group states for comparison, and the dot in front of the legend
    load(url, "ax=yes&cfb=yes")
    dots = ch.js("({ax: getComputedStyle(document.querySelector('#g-ax > .lbl'), '::before').content, cfb: getComputedStyle(document.querySelector('#g-cfb > .lbl'), '::before').content})")
    t.check(dots["ax"] == dots["cfb"] and dots["ax"] not in ("none", "normal", '""'), f"a changed group shows the same marker in front of its legend as CFB: {dots}")
    # Reset puts both back and clears the address
    ch.js("document.getElementById('f-reset').click()")
    time.sleep(0.4)
    r = ch.js("({ax: state.ax, cfb: state.cfb, hash: location.hash, checked: document.querySelector('#f-ax input:checked').value, reset: document.getElementById('f-reset').textContent.trim()})")
    t.check(r["ax"] == "no" and r["cfb"] == "all" and r["checked"] == "no" and "ax=" not in r["hash"] and "cfb=" not in r["hash"], f"Reset Filters returns Accessibility Bugs to No: {r}")
    # the Open Bugs link of the headline tile says what it counts in the three states, and the About text says so
    for ax, left in (("no", "Accessibility bugs are excluded, as in the weekly email."), ("all", "Accessibility bugs are included."), ("yes", "Only accessibility bugs are counted.")):
        load(url, "" if ax == "no" else f"ax={ax}")
        txt = ch.js("(() => { const d = document.querySelector('#bugs-sub details'); return d ? d.textContent.replace(/\\s+/g, ' ') : ''; })()")
        t.check(left in txt, f"How this is calculated says '{left}' for {ax.upper()}: ...{txt[txt.find('Accessibility') - 20:txt.find('Accessibility') + 90] if 'ccessib' in txt else txt[-120:]}")
        t.check(txt.count("ccessibility") == 1, f"the About text of {ax.upper()} names accessibility once: {txt.count('ccessibility')}")


@SUITE.test("ax_the_customer_found_bugs_section_does_not_follow_the_control")
def _(t: T):
    F = fixture()
    ch = ctx.chrome
    js = """(() => { const h = document.getElementById('h-cfb'), sec = h.closest('section'); return {text: sec.innerText.replace(/\\s+/g, ' '), hrefs: [...sec.querySelectorAll('a[href]')].map(a => a.getAttribute('href'))}; })()"""
    for base in ("", "cfb=yes", "p=PMN&bp=P1|P2"):
        got = {}
        for ax in AXS:
            load(F["u_var"], "&".join(x for x in (base, "" if ax == "no" else f"ax={ax}") if x))
            got[ax] = ch.js(js)
            t.check(not any(re.search(r"accessib", urllib.parse.unquote(h), re.I) for h in got[ax]["hrefs"]), f"[{base or '(default)'} {ax}] a Customer-Found Bugs link names accessibility")
        t.check(got["no"] == got["yes"] == got["all"] and len(got["no"]["hrefs"]) > 20, f"[{base or '(default)'}] the Customer-Found Bugs section reads the same in the three states ({len(got['no']['hrefs'])} links)")


@SUITE.test("ax_320_px_the_group_wraps_like_cfb_and_nothing_scrolls_sideways")
def _(t: T):
    F = fixture()
    ch = ctx.chrome
    js = """(() => { const R = e => e.getBoundingClientRect(), box = id => { const g = document.getElementById(id), r = R(g), cs = [...g.querySelectorAll('.chip')].map(R); return {top: r.top, left: r.left, right: r.right, h: r.height, chips: cs.length,
      chipRight: Math.max(...cs.map(c => c.right)), chipLeft: Math.min(...cs.map(c => c.left)), rows: new Set(cs.map(c => Math.round(c.top))).size, chipH: cs[0].height, fg: R(g.closest('.fg')).right}; };
      return {sw: document.documentElement.scrollWidth, w: window.innerWidth, ax: box('f-ax'), cfb: box('f-cfb'), barRight: R(document.querySelector('.bugbar')).right, lbl: R(document.getElementById('lbl-ax')).right}; })()"""
    try:
        for w in (320, 360, 400, 800):
            ch.viewport(w, 900, mobile=False)
            for spec in ("", "ax=yes&cfb=yes"):
                load(F["u_base"], spec)
                m = ch.js(js)
                t.check(m["sw"] <= m["w"], f"{w} px: the page scrolls sideways ({m['sw']} > {m['w']})")
                t.check(m["ax"]["chips"] == 3 and m["ax"]["chipRight"] <= m["w"] + 1 and m["ax"]["chipLeft"] >= -1 and m["ax"]["fg"] <= m["w"] + 1 and m["lbl"] <= m["w"] + 1, f"{w} px: the Accessibility Bugs group leaves the viewport ({m['ax']})")
                t.check(m["ax"]["rows"] == m["cfb"]["rows"] == 1 and abs(m["ax"]["chipH"] - m["cfb"]["chipH"]) < 1, f"{w} px: the buttons are on one row of the same height as the CFB buttons ({m['ax']['rows']}/{m['cfb']['rows']}, {m['ax']['chipH']}/{m['cfb']['chipH']})")
                if w <= 400:
                    t.check(m["ax"]["top"] > m["cfb"]["top"] or m["ax"]["left"] >= m["cfb"]["right"], f"{w} px: the group wraps below or beside CFB without overlapping it ({m['ax']['top']}, {m['cfb']['top']})")
    finally:
        ch.viewport(1400, 900)


@SUITE.test("ax_the_empty_states_say_why")
def _(t: T):
    F = fixture()
    ch = ctx.chrome
    # 1. no accessibility bug at all in the payload: Yes says so, No and All do not
    d = copy.deepcopy(F["base"])
    for b in d["bugs"]:
        b.pop("ax", None)
    url = ctx.write(kit.fragment_for(d), "ax_noax")
    s = snapshot(url, "ax=yes", None)
    t.check(s["empty"] == "No accessibility bugs are recorded in the selected projects and teams. Set Accessibility Bugs to No or All to see the other bugs.", f"Yes with no accessibility bug at all: {s['empty']!r}")
    t.check(not s["errors"], f"errors: {s['errors'][:2]}")
    t.check([x["value"] for x in s["tiles"][:1]] == ["0"], f"the Open Bugs tile shows 0: {s['tiles'][0]}")
    for spec in ("", "ax=all"):
        s = snapshot(url, spec, None)
        t.check(s["empty"] == "" and num(s["tiles"][0]["value"]) > 0, f"#{spec or '(default)'} with no accessibility bug at all still shows the bugs")
    # 2. accessibility bugs exist, the other filters leave none: the general sentence names the control
    d2 = copy.deepcopy(F["base"])
    for b in d2["bugs"]:
        if b.get("ax") and b.get("pr") == "P1":
            b.pop("ax")
    url2 = ctx.write(kit.fragment_for(d2), "ax_nop1")
    for d_ in (d2,):
        t.check(not any(b.get("ax") and b.get("pr") == "P1" for b in d_["bugs"]) and any(b.get("ax") for b in d_["bugs"]), "the variant has accessibility bugs but none of priority P1")
    s = snapshot(url2, "ax=yes&bp=P1", None)
    t.check(s["empty"] == "No bugs match these filters. Priority, CFB and Accessibility Bugs also apply to this section.", f"Yes with a Priority that leaves nothing: {s['empty']!r}")
    ch2 = ctx.chrome.js("document.body.innerText.includes('accessibility switch')")
    t.check(ch2 is False, "the words 'accessibility switch' appear nowhere")


# ---------------------------------------------------------------------------------------------------------------------------------------------------------------- the oracle must not be blind
QUICK = [("var", ["PMN", "CXCO", "CXSUP", "CXWFM", "WFM", "CXINT", "INT"], set(), PRIORITIES, "all", "no"),
         ("var", None, set(), PRIORITIES, "all", "yes"), ("var", None, set(), PRIORITIES, "all", "all"),
         ("var", None, set(), ["P1", "P2"], "yes", "yes"), ("var", None, set(), ["P3"], "no", "all"), ("var", None, set(), ["P1", "P2"], "no", "yes")]


def numbers_problems(url: str) -> list[str]:
    """The numbers, trend and links in a handful of states, for a copy of the template at `url` (the seeded-defect runs)."""
    F = fixture()
    saved = F["u_var"]
    F["u_var"] = url
    _snaps_saved = dict(_snaps)
    try:
        out = []
        for which, projects, teams, pri, cfb, ax in QUICK:
            out += check_view(F, which, projects or projects_of(F["var"]), teams, pri, cfb, ax)
        return out
    finally:
        F["u_var"] = saved
        _snaps.clear()
        _snaps.update(_snaps_saved)


def behaviour_problems(url: str) -> list[str]:
    """The hash round trip, the old link, the indicator and the control's own behaviour for a copy of the template at `url`."""
    out = []
    ch = ctx.chrome
    for spec, want in (("ax=yes", "yes"), ("ax=all", "all"), ("ax=1", "all"), ("", "no"), ("ax=maybe", "no")):
        load(url, spec)
        s = ch.js("({ax: state.ax, checked: (document.querySelector('#f-ax input:checked') || {}).value})")
        if s.get("ax") != want or s.get("checked") != want:
            out.append(f"#{spec or '(default)'} opens as {s.get('ax')}/{s.get('checked')}, expected {want}")
    load(url, "")
    for v in ("yes", "all", "no"):
        ch.js(f"document.querySelector('#f-ax input[value=\"{v}\"]').click()")
        time.sleep(0.25)
        h = urllib.parse.parse_qs(ch.js("location.hash").lstrip("#"))
        if (h.get("ax") != [v]) if v != "no" else ("ax" in h):
            out.append(f"clicking {v} leaves the address at {h}")
        if ch.js("(document.querySelector('#f-ax input:checked') || {}).value") != v:
            out.append(f"clicking {v} does not select it")
    for spec, n in (("", 0), ("ax=yes", 1), ("ax=all", 1), ("cfb=yes", 1), ("cfb=yes&ax=yes", 2)):
        load(url, spec)
        r = ch.js("document.getElementById('f-reset').textContent.trim()")
        if r != (f"Reset Filters ({n})" if n else "Reset Filters"):
            out.append(f"#{spec or '(default)'}: the reset button says {r!r}")
    load(url, "ax=yes&cfb=yes")
    ch.js("document.getElementById('f-reset').click()")
    time.sleep(0.3)
    if ch.js("state.ax + '/' + state.cfb") != "no/all":
        out.append("Reset Filters does not restore No and All")
    # CFB itself: clicks, the address, the tile
    load(url, "")
    ch.js("document.querySelector('#f-cfb input[value=\"yes\"]').click()")
    time.sleep(0.25)
    if ch.js("state.cfb") != "yes" or "cfb=yes" not in ch.js("location.hash") or ch.js("document.querySelector('#f-cfb input:checked').value") != "yes":
        out.append("the CFB control no longer sets, writes and shows Yes")
    for spec, want in (("cfb=yes", "yes"), ("cfb=no", "no"), ("", "all")):
        load(url, spec)
        if ch.js("state.cfb + '/' + document.querySelector('#f-cfb input:checked').value") != f"{want}/{want}":
            out.append(f"CFB #{spec or '(default)'} does not open as {want}")
    return out


def cfb_problems(url: str) -> list[str]:
    """The CFB filter of the Open Bugs section against the recount (CFB is the control the new one copies; a regression of it must be seen)."""
    F = fixture()
    saved = F["u_var"]
    F["u_var"] = url
    saved_snaps = dict(_snaps)
    try:
        out = []
        for cfb in ("yes", "no"):
            out += check_view(F, "var", projects_of(F["var"]), set(), PRIORITIES, cfb, "no")
        return out
    finally:
        F["u_var"] = saved
        _snaps.clear()
        _snaps.update(saved_snaps)


def keyboard_problems(url: str) -> list[str]:
    ch = ctx.chrome
    out = []
    for start in ("all", "no"):
        load(url, "")
        a = drive(ch, "ax", "ax", start, ["ArrowRight", "ArrowRight", "ArrowLeft"])
        load(url, "")
        c = drive(ch, "cfb", "cfb", start, ["ArrowRight", "ArrowRight", "ArrowLeft"])
        strip = lambda o: [{k: v for k, v in x.items() if k != "inHash"} for x in o]
        if strip(a) != strip(c) or any(x["checked"] != x["state"] or x["focus"] != x["checked"] for x in a):
            out.append(f"start {start}: the AX group's keyboard behaviour differs from CFB or from its state")
    return out


def markup_problems(url: str) -> list[str]:
    ch = ctx.chrome
    load(url, "")
    m = ch.js("({cb: document.querySelectorAll('input[type=checkbox]#f-ax').length, vals: [...document.querySelectorAll('#f-ax input')].map(i => i.value).join(), role: document.getElementById('f-ax').getAttribute('role')})")
    out = []
    if m["cb"] or m["vals"] != "all,yes,no" or m["role"] != "radiogroup":
        out.append(f"the control is {m}")
    return out


# (label, [(old, new)], the checks that must fail)
MUTANTS = [
    ("Yes behaving like All (the bug filter)", [('(state.ax === "all" || (state.ax === "yes") === !!b.ax)', '(state.ax !== "no" || (state.ax === "yes") === !!b.ax)')], [numbers_problems]),
    ("All behaving like No (the bug filter)", [('(state.ax === "all" || (state.ax === "yes") === !!b.ax)', '(false || (state.ax === "yes") === !!b.ax)')], [numbers_problems]),
    ("Yes excluding instead of selecting (the bug filter)", [('(state.ax === "all" || (state.ax === "yes") === !!b.ax)', '(state.ax === "all" || (state.ax === "no" || state.ax === "yes") !== !!b.ax)')], [numbers_problems]),
    ("Yes excluding instead of selecting (the links)", [('state.ax === "yes" ? AX_ONLY : AX_EXCLUDE', 'AX_EXCLUDE')], [numbers_problems]),
    ("the Yes clause naming only the summary (a label-only accessibility bug is missed by the link)", [('AX_ONLY = ` AND (summary ~ "\\\\"[Accessibility]*\\\\"" OR labels = DWP_Accessibility_Defect)`', 'AX_ONLY = ` AND (summary ~ "\\\\"[Accessibility]*\\\\"")`')], [numbers_problems]),
    ("the links ignoring the state (always excluding)", [('if (!o.keepAx && state.ax !== "all") jql += state.ax === "yes" ? AX_ONLY : AX_EXCLUDE;', 'if (!o.keepAx) jql += AX_EXCLUDE;')], [numbers_problems]),
    ("the links ignoring the state (never restricting)", [('if (!o.keepAx && state.ax !== "all") jql += state.ax === "yes" ? AX_ONLY : AX_EXCLUDE;', '')], [numbers_problems]),
    ("the trend ignoring the state", [('const bugs = backlogBugs(), weeks = weekStarts();', 'const bugs = bugsBase().filter(b => !b.ax && (state.bugPri.size === PRI_ALL.length || state.bugPri.has(b.pr)) && (state.cfb === "all" || (state.cfb === "yes") === !!b.cfb)), weeks = weekStarts();')], [numbers_problems]),
    ("the headline wording of Yes", [('yes: "only accessibility bugs"', 'yes: "excluding accessibility bugs"')], [numbers_problems]),
    ("the default being All", [('commit: new Set(DEFAULT_COMMIT), ax: "no", bugPri', 'commit: new Set(DEFAULT_COMMIT), ax: "all", bugPri')], [numbers_problems, behaviour_problems]),
    ("the hash not written", [('if (state.ax !== "no") h.set("ax", state.ax);', '')], [behaviour_problems]),
    ("the hash not read for Yes", [('if (["all", "yes"].includes(h.get("ax"))) state.ax = h.get("ax");', 'if (["all"].includes(h.get("ax"))) state.ax = h.get("ax");')], [behaviour_problems]),
    ("the old ax=1 link no longer opening as All", [('else if (h.get("ax") === "1") state.ax = "all";', '')], [behaviour_problems]),
    ("Yes not counted as a changed filter", [('ax: state.ax !== "no", period', 'ax: state.ax === "all", period')], [behaviour_problems]),
    ("the control not following the state (radios not synced)", [('document.querySelectorAll("#f-ax input").forEach(i => { i.checked = i.value === state.ax; i.parentElement.classList.toggle("on", i.checked); });', '')], [behaviour_problems]),
    ("the checkbox still there", [('<div class="fg" id="g-ax"><span class="lbl" id="lbl-ax">Accessibility Bugs</span>', '<div class="fg" id="g-ax"><span class="lbl" id="lbl-ax">Accessibility Bugs</span><input type="checkbox" id="f-ax">')], [markup_problems]),
    ("a CFB regression: Yes and No swapped in the bug filter", [('(state.cfb === "all" || (state.cfb === "yes") === !!b.cfb))', '(state.cfb === "all" || (state.cfb === "no") === !!b.cfb))')], [cfb_problems]),
    ("a CFB regression: the control no longer sets the state", [('document.getElementById("f-cfb").onchange = e => { state.cfb = e.target.value;', 'document.getElementById("f-cfb").onchange = e => { state.cfb = "all";')], [behaviour_problems]),
    ("a CFB regression: the CFB link clause dropped", [('if (state.cfb !== "all") jql += ` AND ${state.cfb === "yes" ? CFB_Q() : NOT_CFB_Q()}`;', '')], [cfb_problems]),
    ("a keyboard regression: the group redrawn without its focus", [('document.getElementById("f-ax").onchange = e => { state.ax = e.target.value; update({hold: holdSel(e.target)}); };', 'document.getElementById("f-ax").onchange = e => { state.ax = e.target.value; update(); document.activeElement.blur(); };')], [keyboard_problems]),
]


@SUITE.test("oracle_selftest_catches_seeded_defects")
def _(t: T):
    src = ctx.template.read_text(encoding="utf-8")
    F = fixture()
    payload = json.dumps(F["var"], ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    ran = 0
    for label, edits, checks in MUTANTS:
        text = src
        usable = True
        for old, new in edits:
            if text.count(old) != 1:
                usable = False
                t.failures.append(f"the seeded defect '{label}' does not apply: its pattern is in the template {text.count(old)} times (it must be exactly once)")
                break
            text = text.replace(old, new, 1)
        if not usable:
            continue
        ran += 1
        tmp = Path(ctx.dir) / f"ax_mutant_{ran}.html"
        tmp.write_text(text.replace("/*__DATA__*/null", payload), encoding="utf-8")
        url = "file://" + str(tmp)
        probs = []
        for fn in checks:
            probs += fn(url)
        t.check(bool(probs), f"seeded defect caught: {label} ({len(probs)} findings: {probs[0][:110] if probs else ''})")
    t.note(f"{ran} seeded defects run")
    # the unmodified template passes every one of those quick checks (so a finding is the defect's, not the check's)
    url = F["u_var"]
    clean = numbers_problems(url) + behaviour_problems(url) + cfb_problems(url) + keyboard_problems(url) + markup_problems(url)
    t.check(not clean, f"the unmodified template trips the quick checks: {clean[:3]}")


if __name__ == "__main__":
    sys.exit(kit.cli(SUITE, __doc__))
