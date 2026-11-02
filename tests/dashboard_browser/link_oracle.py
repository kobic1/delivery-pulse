#!/usr/bin/env python3
"""Link oracle (finding F14b): every link the page generates to Jira is checked, under a matrix of filter states, on the fictitious payload.

1. Every href: no NaN, undefined, null or "[object" token in it, and it is well formed (https, the Jira host, /issues/?jql=<non-empty, parseable JQL> or
   /browse/KEY-123; balanced parentheses and quotes; no dangling AND/OR; no empty IN ()).
2. In the Open Bugs, Customer-Found Bugs and Capitalization blocks every field a link's JQL uses is baked in the data, so the JQL is EVALUATED in Python
   (jql_eval.py) over the baked records and the number of matching issues must equal the number printed on the link.

Known defects this oracle is built to catch (reported, never hidden): in Quarter mode the Capitalization "All issues" row link and the data-quality
"no story points" link emit cf[10099] >= "0-NaN-01"; in Release mode the "Not plotted" and "no story points" links are unscoped. Each has its own test.

    python3 link_oracle.py [--live] [--only NAME]
"""
from __future__ import annotations

import json
import re
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import jql_eval as J                                                                # noqa: E402
import kit                                                                          # noqa: E402
import link_cycles as LC                                                            # noqa: E402  (epic_issue: a baked epic as the Jira fields the epic queries use)
import make_synthetic as MS                                                         # noqa: E402
from kit import ctx, T                                                              # noqa: E402

SUITE = kit.Suite("Delivery Pulse link oracle")
BAD_TOKEN = re.compile(r"NaN|undefined|\[object|\bnull\b")

STATES = [
    "", "r=26.4", "r=26.2&p=PMN", "p=PMN", "p=CXWFM|WFM", "p=PMN|CXCO|CXSUP", "TEAM", "p=PMN&TEAM", "c=Stretch", "ax=all", "ax=yes", "bp=P1|P2", "bp=P3&ax=all", "bp=P1|P2&ax=yes&cfb=yes", "cfb=yes", "cfb=no", "cfb=yes&p=PMN",
    "cg=quarter", "cg=month&p=CXCO", "g=quarter", "cpg=release", "cpg=release&cpm=count", "cpm=count", "cpg=release&p=PMN", "cpg=release&TEAM", "cpg=release&p=CXWFM|WFM&cpm=count",
    "p=CXINT&cpm=count", "p=WFM&cg=quarter&bp=P1|P2|P3&ax=all", "p=CXCO&ax=yes&cfb=no",
    "p=INT", "p=CXINT|INT&cfb=yes", "cpg=release&p=INT&cpm=count", "dp=blockedby", "dp=blocking", "dp=blocking&p=PMN",
]

COLLECT_JS = """(() => {
  const within = (a, sel) => { const h = document.querySelector(sel); return !!h && h.contains(a); };
  const sec = id => { const h = document.getElementById(id); return h ? (h.closest('section') || h.parentElement) : null; };
  const bugs = sec('h-bugs'), cfb = sec('h-cfb'), capHost = document.getElementById('capz-host'), capData = document.getElementById('capz-data');
  return [...document.querySelectorAll('a[href]')].map(a => {
    const tr = a.closest('tr'), block = (capHost && capHost.contains(a)) || (capData && capData.contains(a)) ? 'cap' : (cfb && cfb.contains(a)) ? 'cfb' : (bugs && bugs.contains(a)) ? 'bugs' : '';
    return {href: a.getAttribute('href'), text: (a.textContent || '').trim(), block, row: tr ? tr.innerText.replace(/\\s+/g, ' ').slice(0, 60) : (a.closest('[id]') || {}).id || '', inSr: !!a.closest('.sr, .hidden-table, [hidden]')};
  });
})()"""

_cache = {}


def fixture():
    if not _cache:
        data = MS.make(MS.il_today())
        _cache.update(data=data, url=ctx.write(kit.fragment_for(data), "oracle"),
                      bugs=[J.bug_issue(b, data["cfbAccount"]) for b in data["bugs"]], cap=J.cap_issues(data["cap"]),
                      team=data["cap"]["teams"][0], base=data["jiraBase"])
    return _cache


def state_hash(spec: str, team: str) -> str:
    return "&".join(f"t={urllib.parse.quote(team)}" if p == "TEAM" else p for p in spec.split("&")) if spec else ""


_anchors: dict = {}


def anchors_for(spec: str, url: str | None = None) -> list:
    F = fixture()
    url = url or F["url"]
    if (url, spec) in _anchors:
        return _anchors[(url, spec)]
    ch = ctx.chrome
    ch.goto(url + ("#" + state_hash(spec, F["team"]) if spec else ""))
    kit.wait_ready(ch)
    res = ch.js(COLLECT_JS)
    err = ch.console_errors()
    for a in res:
        a["state"] = spec or "(default)"
        a["errors"] = err
    _anchors[(url, spec)] = res
    return res


def all_anchors():
    out = []
    for s in STATES:
        out += anchors_for(s)
    return out


def jql_of(href: str):
    q = urllib.parse.urlsplit(href)
    if q.path.rstrip("/") != "/issues":
        return None
    return urllib.parse.parse_qs(q.query, keep_blank_values=True).get("jql", [""])[0]


def describe(a, jql=None):
    j = jql if jql is not None else (jql_of(a["href"]) or a["href"])
    return f"[{a['state']}] '{a['text']}' ({a['row']}) -> {j[:150]}"


def numeric(a):
    s = a["text"].replace(",", "")
    return int(s) if s.isdigit() else None


def evaluate_anchor(a):
    """(status, detail): 'ok', 'mismatch', 'malformed', 'unsupported', 'skip'"""
    F = fixture()
    n = numeric(a)
    j = jql_of(a["href"])
    if n is None or j is None or not a["block"]:
        return "skip", ""
    universe = F["cap"] if a["block"] == "cap" else F["bugs"]
    try:
        got = J.count(j, universe)
    except J.Malformed as e:
        return "malformed", str(e)
    except J.Unsupported as e:
        return "unsupported", str(e)
    return ("ok" if got == n else "mismatch"), f"printed {n}, the query matches {got}"


# ================================================================ whole-page link checks
@SUITE.test("links_no_broken_tokens_in_any_state")
def _(t: T):
    bad = [a for a in all_anchors() if BAD_TOKEN.search(urllib.parse.unquote(a["href"]))]
    seen = {}
    for a in bad:
        seen.setdefault((a["row"], a["text"], BAD_TOKEN.search(urllib.parse.unquote(a["href"])).group(0)), []).append(a["state"])
    for (row, text, tok), states in list(seen.items())[:12]:
        t.failures.append(f"a link with '{tok}' in its URL: '{text}' ({row}) in {len(states)} state(s), e.g. #{states[0]}")
    t.passed += 1 if not bad else 0
    t.note(f"{sum(len(anchors_for(s)) for s in STATES)} links checked in {len(STATES)} states")


@SUITE.test("links_are_well_formed_in_every_state")
def _(t: T):
    F = fixture()
    base = urllib.parse.urlsplit(F["base"])
    problems, jqls = [], 0
    for a in all_anchors():
        h = a["href"]
        if h.startswith("#") or h == "":
            continue
        q = urllib.parse.urlsplit(h)
        if (q.scheme, q.netloc) != (base.scheme, base.netloc):
            problems.append(f"not a link to the Jira base: {describe(a, h)}")
            continue
        if q.path.startswith("/browse/"):
            if not re.fullmatch(r"/browse/[A-Z][A-Z0-9]*-\d+", q.path):
                problems.append(f"malformed issue link: {describe(a, h)}")
            continue
        if q.path.rstrip("/") != "/issues":
            problems.append(f"unexpected Jira path {q.path}: {describe(a, h)}")
            continue
        jql = urllib.parse.parse_qs(q.query, keep_blank_values=True).get("jql", [""])[0]
        if not jql.strip():
            problems.append(f"empty jql: {describe(a, h)}")
            continue
        jqls += 1
        try:
            J.parse(jql)
        except J.Malformed as e:
            problems.append(f"malformed JQL ({e}): {describe(a, jql)}")
        except J.Unsupported:
            pass
    for p in sorted(set(problems))[:15]:
        t.failures.append(p)
    t.passed += 0 if problems else 1
    t.note(f"{jqls} JQL links parsed")


def _counts(t: T, block: str, label: str):
    evald, bad, unsupported = 0, {}, {}
    for a in all_anchors():
        if a["block"] != block:
            continue
        st, d = evaluate_anchor(a)
        if st == "skip":
            continue
        if st == "unsupported":
            unsupported[d] = unsupported.get(d, 0) + 1
            continue
        evald += 1
        if st != "ok":
            bad.setdefault((st, a["row"], a["text"], d), []).append(a)
    t.check(evald >= 20, f"the oracle evaluated {evald} {label} links against the baked records (at least 20 expected, or it is blind)")
    for (st, row, text, d), lst in list(bad.items())[:15]:
        t.failures.append(f"{st}: '{text}' in '{row}' - {d}; {len(lst)} state(s), e.g. {describe(lst[0])}")
    t.passed += 0 if bad else 1
    if unsupported:
        t.note(f"not judged (JQL the oracle does not evaluate): {unsupported}")
    t.note(f"{evald} {label} links evaluated in {len(STATES)} states")


@SUITE.test("links_open_bugs_counts_equal_their_queries")
def _(t: T):
    _counts(t, "bugs", "Open Bugs")


@SUITE.test("links_cfb_counts_equal_their_queries")
def _(t: T):
    _counts(t, "cfb", "CFB")


@SUITE.test("links_capitalization_counts_equal_their_queries")
def _(t: T):
    _counts(t, "cap", "Capitalization")


@SUITE.test("links_capitalization_are_queries_never_frozen_key_lists")
def _(t: T):
    """The owner's rule: a Capitalization number opens a QUERY (so Jira shows today's issues), never a hard-coded list of keys, however small the set is."""
    seen = 0
    for spec in ("", "p=PMN", "p=CXSUP", "p=PMN|CXCO", "TEAM", "cpg=release", "cpg=release&p=CXSUP", "cpm=count"):
        for a in anchors_for(spec):
            if a["block"] != "cap" or numeric(a) is None:
                continue
            seen += 1
            j = urllib.parse.unquote(a["href"])
            if re.search(r"\bkey\s+in\s*\(", j, re.I):
                t.check(False, f"[{spec or '(default)'}] '{a['text']}' ({a['row']}) opens a key list: {j[:120]}")
    t.check(seen > 20, f"{seen} Capitalization links inspected in 8 states, none is a key list")


# ================================================================ the reserved project key: INT must be quoted in every query
BARE_INT = re.compile(r"(?<![\w-])INT(?![\w-])")
QUOTED = re.compile(r'"(?:[^"\\]|\\.)*"')


def quoting_problems(url=None) -> list[str]:
    """Jira rejects `project = INT` ("'INT' is a reserved JQL word") and wants `project = "INT"`. With INT selected, and with every project selected, every JQL link must name it quoted;
    a link whose query names a project while INT is the only selection must carry `"INT"`. The count of links seen keeps the check from being blind."""
    out, quoted = [], 0
    for spec in ("p=INT", "p=CXINT|INT&cfb=yes", "cpg=release&p=INT&cpm=count", "", "r=26.4", "cpg=release", "cfb=yes", "TEAM"):
        for a in anchors_for(spec, url):
            j = jql_of(a["href"])
            if j is None:
                continue
            bare = QUOTED.sub('""', j)
            if BARE_INT.search(bare):
                out.append(f"[{spec or '(default)'}] a bare INT: {describe(a, j)}")
            elif '"INT"' in j:
                quoted += 1
            if spec == "p=INT" and re.search(r"\bproject\b", bare) and '"INT"' not in j and "CXCROSS" not in j:
                out.append(f"[p=INT] a query that names a project but not \"INT\": {describe(a, j)}")
    if quoted < 40:
        out.append(f"only {quoted} links name \"INT\" quoted (at least 40 expected, or the check is blind)")
    return out


@SUITE.test("links_reserved_project_key_INT_is_quoted_in_every_query")
def _(t: T):
    probs = quoting_problems()
    for p in sorted(set(probs))[:12]:
        t.failures.append(p)
    t.passed += 0 if probs else 1


# ================================================================ the known defects, each on its own
def _row_links(spec: str, row_text: str, container: str):
    return [a for a in anchors_for(spec) if a["block"] == "cap" and row_text in a["row"] and numeric(a) is not None and container in ("any", a["row"])]


def _dq_links(spec: str):
    return [a for a in anchors_for(spec) if a["block"] == "cap" and a["row"] == "capz-dq" and numeric(a) is not None]


def quarter_mode_problems(url=None) -> list[str]:
    out = []
    for spec in ("", "p=PMN|CXCO", "p=CXWFM|WFM", "TEAM"):
        links = [a for a in anchors_for(spec, url) if a["block"] == "cap" and (a["row"].startswith("All issues") or a["row"] == "capz-dq")]
        if len(links) < 2:
            out.append(f"[{spec or '(default)'}] the All-issues row link and the data-quality links are missing ({len(links)} found)")
        for a in links:
            j = urllib.parse.unquote(a["href"])
            if BAD_TOKEN.search(j):
                out.append(f"[{spec or '(default)'}] '{a['text']}' ({a['row']}) has NaN/undefined in its query: {j[:140]}")
            st, d = evaluate_anchor(a)
            if st not in ("ok", "unsupported"):
                out.append(f"[{spec or '(default)'}] '{a['text']}' ({a['row']}): {st} {d}")
    return out


def release_mode_problems(url=None) -> list[str]:
    out = []
    for spec in ("cpg=release", "cpg=release&p=PMN", "cpg=release&TEAM", "cpg=release&p=CXWFM|WFM&cpm=count"):
        ls = [a for a in anchors_for(spec, url) if a["block"] == "cap" and (a["row"].startswith("Not plotted") or a["row"] == "capz-dq")]
        if not any(a["row"].startswith("Not plotted") for a in ls) and not spec.endswith("p=PMN"):
            out.append(f"[{spec}] the 'Not plotted' link is missing")
        for a in ls:
            st, d = evaluate_anchor(a)
            if st not in ("ok", "unsupported"):
                out.append(f"[{spec}] '{a['text']}' ({a['row']}): {st} {d}")
    return out


@SUITE.test("links_capitalization_quarter_mode_all_issues_and_no_story_points")
def _(t: T):
    """Quarter mode: the 'All issues under the filters' row link and the data-quality 'no story points' link must carry a real date and match their count."""
    probs = quarter_mode_problems()
    for p in probs[:12]:
        t.failures.append(p)
    t.passed += 0 if probs else 1


@SUITE.test("links_capitalization_release_mode_not_plotted_and_no_story_points_are_scoped")
def _(t: T):
    """Release mode: 'Not plotted' and 'no story points' must be limited to the periods they describe, so the query finds exactly the printed number."""
    probs = release_mode_problems()
    for p in probs[:12]:
        t.failures.append(p)
    t.passed += 0 if probs else 1



# ================================================================ Cycle Time per Release: the chart's n, the table's n, the tile and the Jira link query are one population
# Owner decision: Cycle Time per Release counts the Done epics with an EDCT of the release, the Issue Categories Maintenance AND SOW excluded (the same two as the AI figures), whatever Implemented by AI says
# (Yes, No, empty) and whatever the Flagged field says (it plays no part in who is counted).
CYCLE_EXCLUDED = ("maintenance", "sow")
CYCLE_STATES = ["", "p=PMN", "p=PMN|CXCO", "p=CXWFM|WFM&c=Stretch", "TEAM", "p=PMN&TEAM"]
CYCLE_JS = r"""(() => {
  const chart = document.querySelector('[data-chart="cycle"]'), svg = chart.querySelector('svg');
  const marks = [...svg.querySelectorAll('a.cl, g.cl')].map(a => ({href: a.getAttribute('href'), tip: a.getAttribute('data-tip')}));
  const ns = [...svg.querySelectorAll('text')].map(t => t.textContent.trim()).filter(t => /^n=\d+$/.test(t)).map(t => +t.slice(2));
  const lab = [...svg.querySelectorAll('text[fill="var(--chart-cycle-ink)"]')].map(t => +t.textContent);
  const rows = {};
  document.querySelectorAll('#trend-data tbody tr').forEach(tr => { const c = [...tr.children], a = c[8].querySelector('a');
    rows[c[0].textContent.replace('*', '')] = {p50: c[6].textContent.trim(), p90: c[7].textContent.trim(), n: c[8].textContent.trim(), nHref: a ? a.getAttribute('href') : null}; });
  const k = [...document.querySelectorAll('#an-kpis .kpi')].find(x => /Cycle Time P50/.test(x.textContent)), a = k && k.querySelector('.s a');
  const tile = k ? {text: k.textContent.replace(/\s+/g, ' ').trim(), href: a ? a.getAttribute('href') : null} : null;
  return {marks, ns, lab, rows, tile, release: state.release, rels: DATA.releases.slice(), projects: [...state.projects], teams: [...state.teams]};
})()"""


def _pct(vals, p):
    vals = sorted(vals)
    if not vals:
        return None
    i = (len(vals) - 1) * p
    lo, hi = int(i), min(int(i) + 1, len(vals) - 1)
    return vals[lo] + (vals[hi] - vals[lo]) * (i - lo)


def _fmt(v):
    """The page's fmt: one decimal at most, no trailing .0"""
    if v is None:
        return "–"
    r = round(v * 10) / 10
    return str(int(r)) if r == int(r) else str(r)


def cycle_expected(data: dict, rel: str, projects, teams):
    """The independent recount, from the baked epics: Done, in the release, in the selected projects and teams, Issue Category neither Maintenance nor SOW, with an EDCT. Nothing about AI, nothing about Flagged."""
    out = []
    for e in data["epics"]:
        if e["s"] != "Done" or rel not in e["fv"] or e["p"] not in projects or e.get("edct") is None:
            continue
        if teams and not (set(e.get("tm") or []) & set(teams)):
            continue
        if str(e.get("cat") or "").lower() in CYCLE_EXCLUDED:
            continue
        out.append(e)
    return out


def cycle_population_ok(data: dict) -> list[str]:
    """The fixture must contain the epics the rule is about, or the check is blind: Done epics with an EDCT that are Maintenance, SOW, not AI, AI, and have no Issue Category (Maintenance and SOW are the two categories the rule leaves out; the others must stay in)."""
    done = [e for e in data["epics"] if e["s"] == "Done" and e.get("edct") is not None]
    need = {"Maintenance with an EDCT": [e for e in done if e.get("cat") == "Maintenance"], "SOW with an EDCT": [e for e in done if e.get("cat") == "SOW"],
            "not AI with an EDCT": [e for e in done if not e.get("ai")], "AI with an EDCT": [e for e in done if e.get("ai")], "no Issue Category with an EDCT": [e for e in done if not e.get("cat")]}
    return [f"the fixture has no Done epic: {k}" for k, v in need.items() if not v]


def cycle_check_page(url, data, spec: str, label: str):
    """Return (problems, facts) for one filter state: the chart n and labels, the hover text, the table row, the tile and the link query agree with the recount."""
    F = fixture()
    ch = ctx.chrome
    ch.goto(url + ("#" + state_hash(spec, F["team"]) if spec else ""))
    kit.wait_ready(ch)
    res = ch.js(CYCLE_JS)
    probs, facts = [], []
    tag = f"[{label}:{spec or '(default)'}]"
    universe = [LC.epic_issue(e) for e in data["epics"]]
    edct = {e["k"]: e.get("edct") for e in data["epics"]}
    rels, marks, ns, lab, li = res["rels"], res["marks"], res["ns"], res["lab"], 0
    if len(marks) != len(rels) or len(ns) != len(rels):
        return [f"{tag} the chart has {len(marks)} marks and {len(ns)} n labels for {len(rels)} releases"], facts
    for i, rel in enumerate(rels):
        exp = cycle_expected(data, rel, res["projects"], res["teams"])
        vals = [e["edct"] for e in exp]
        ok = len(vals) >= 5
        m = marks[i]
        got_labels = None
        if "P50" in m["tip"]:
            got_labels, li = lab[li:li + 2], li + 2
        # 1. the plotted n and percentiles against the recount
        if ns[i] != len(exp):
            probs.append(f"{tag} {rel}: the chart plots n={ns[i]}, the recount gives {len(exp)}")
        if ok != (got_labels is not None):
            probs.append(f"{tag} {rel}: plotted={got_labels is not None}, expected plotted={ok}")
        elif ok and [_fmt(_pct(vals, .5)), _fmt(_pct(vals, .9))] != [_fmt(x) for x in got_labels]:
            probs.append(f"{tag} {rel}: plotted P50/P90 {got_labels}, the recount gives {_fmt(_pct(vals, .5))}/{_fmt(_pct(vals, .9))}")
        # 2. the hover text names the same n
        hover_n = re.search(r"\n(\d+) Done epics\n", m["tip"])
        if not hover_n or int(hover_n.group(1)) != ns[i]:
            probs.append(f"{tag} {rel}: the hover text says {hover_n.group(1) if hover_n else None} Done epics, the chart plots n={ns[i]}")
        # 3. the table row
        row = res["rows"].get(rel)
        if not row or row["n"].replace(",", "") != str(ns[i]):
            probs.append(f"{tag} {rel}: the table says n={row and row['n']}, the chart plots n={ns[i]}")
        if row and ok and (row["p50"], row["p90"]) != (_fmt(_pct(vals, .5)), _fmt(_pct(vals, .9))):
            probs.append(f"{tag} {rel}: the table says P50/P90 {row['p50']}/{row['p90']}, the recount gives {_fmt(_pct(vals, .5))}/{_fmt(_pct(vals, .9))}")
        # 4. the links (bar and table) are the same query, and the query finds the same epics
        hrefs = {"chart": m["href"], "table": row and row["nHref"]}
        for name, h in hrefs.items():
            if h is None:
                if ns[i] or name == "chart":
                    probs.append(f"{tag} {rel}: the {name} has no Jira link for n={ns[i]}")
                continue
            j = jql_of(h)
            if not j or "cf[10139]" not in j or "Maintenance" not in j or "SOW" not in j:
                probs.append(f"{tag} {rel}: the {name} link does not exclude both Maintenance and SOW: {j}")
                continue
            if "cf[15229]" in j:
                probs.append(f"{tag} {rel}: the {name} link filters on Implemented by AI: {j}")
            if "flag" in j.lower():
                probs.append(f"{tag} {rel}: the {name} link mentions Flagged: {j}")
            try:
                tree = J.parse(j)
                found = [x for x in universe if J.evaluate(tree, x)]
            except (J.Malformed, J.Unsupported) as e:
                probs.append(f"{tag} {rel}: the {name} link cannot be evaluated: {e}")
                continue
            with_edct = [x for x in found if edct[x["key"]] is not None]
            if len(with_edct) != ns[i]:
                probs.append(f"{tag} {rel}: the {name} link query finds {len(found)} epics, {len(with_edct)} with an EDCT; the chart plots n={ns[i]}")
            if {x["key"] for x in with_edct} != {e["k"] for e in exp}:
                probs.append(f"{tag} {rel}: the {name} link query finds other epics than the recount")
        if rel == res["release"]:
            t = res["tile"]
            if not t or f"{ns[i]} Done epics" not in t["text"] or t["href"] != m["href"]:
                probs.append(f"{tag} {rel}: the selected-release tile does not agree with the chart (n={ns[i]}): {t}")
        facts.append(f"{rel} n={ns[i]} P50/P90={_fmt(_pct(vals, .5)) if ok else '-'}/{_fmt(_pct(vals, .9)) if ok else '-'}")
    return probs, facts


def cycle_problems(url=None) -> list[str]:
    F = fixture()
    url = url or F["url"]
    out = list(cycle_population_ok(F["data"]))
    seen = 0
    for spec in CYCLE_STATES:
        p, f = cycle_check_page(url, F["data"], spec, "fixture")
        out += p
        seen += len(f)
    if seen < len(CYCLE_STATES) * 5:
        out.append(f"only {seen} release figures were compared (the check is blind)")
    return out


@SUITE.test("cycle_time_per_release_n_and_the_jira_link_are_one_population")
def _(t: T):
    """The chart n, its hover text, the Release Analysis row, the selected-release tile and the Jira link (evaluated with the repo's JQL evaluator) all equal the independent recount:
    Done epics with an EDCT, Maintenance and SOW out, AI / not AI / empty all in, Flagged irrelevant. Run in six filter states."""
    F = fixture()
    probs = cycle_problems()
    for p in probs[:15]:
        t.failures.append(p)
    t.passed += 0 if probs else 1
    t.note("plotted (default filters): " + "; ".join(cycle_check_page(F["url"], F["data"], "", "fixture")[1]))


@SUITE.test("cycle_time_per_release_says_so_when_an_epic_has_no_edct")
def _(t: T):
    """Jira cannot search for an EDCT: when a Done epic has none, the link lists it and the hover text says that n is smaller by that many, instead of the two numbers silently differing."""
    import copy
    F = fixture()
    d = copy.deepcopy(F["data"])
    rel = "26.4"
    cand = [e for e in d["epics"] if e["s"] == "Done" and rel in e["fv"] and e["p"] == "PMN" and str(e.get("cat") or "").lower() not in CYCLE_EXCLUDED and e.get("edct") is not None][:2]
    t.check(len(cand) == 2, "the fixture has two PMN Done epics in 26.4 outside Maintenance and SOW")
    for e in cand:
        e["edct"] = None
    url = ctx.write(kit.fragment_for(d), "cycle_noedct")
    ch = ctx.chrome
    ch.goto(url + "#p=PMN")
    kit.wait_ready(ch)
    res = ch.js(CYCLE_JS)
    i = res["rels"].index(rel)
    m = res["marks"][i]
    t.check(res["ns"][i] == len(cycle_expected(d, rel, ["PMN"], [])), "the chart n leaves out the epics with no EDCT")
    t.check("2 of them have no EDCT yet" in m["tip"], f"the hover text says that 2 epics have no EDCT: {m['tip']!r}")
    found = J.count(jql_of(m["href"]), [LC.epic_issue(e) for e in d["epics"]])
    t.check(found == res["ns"][i] + 2, f"the link lists the {res['ns'][i]} counted epics plus the 2 without an EDCT (found {found})")



@SUITE.test("cycle_time_per_release_ignores_the_flagged_field")
def _(t: T):
    """Cycle Time per Release has no relation to Flagged: set Flagged on a few Done epics that have an EDCT (the fixture has none) and the plotted n, percentiles, hover, table, tile and link must still equal the
    recount, which never reads Flagged. The links must not mention Flagged either (checked in cycle_check_page)."""
    import copy
    F = fixture()
    d = copy.deepcopy(F["data"])
    hit = [e for e in d["epics"] if e["s"] == "Done" and e.get("edct") is not None and "26.4" in e["fv"]][:12]
    t.check(len(hit) == 12, "the fixture has twelve Done epics with an EDCT in 26.4 to flag")
    for e in hit:
        e["fl"] = True
    url = ctx.write(kit.fragment_for(d), "cycle_flagged")
    for spec in ("", "p=PMN"):
        probs, facts = cycle_check_page(url, d, spec, "flagged")
        for p in probs[:10]:
            t.failures.append(p)
        t.passed += 0 if probs else 1
        t.note(f"flagged Done epics, filter '{spec or '(default)'}': " + "; ".join(facts))


# ================================================================ the oracle must not be blind: seed each known defect into a copy of the template and require it to be caught
MUTATIONS = [
    ("a NaN date in the 'since the pull' range (Quarter mode defect)", "const START_R = [C.start, null]", 'const START_R = ["0-NaN-01", null]', quarter_mode_problems),
    ("an unscoped 'no story points' range in Release mode", 'const noSpRanges = by === "release" ? shownR : [START_R];', "const noSpRanges = [START_R];", release_mode_problems),
    ("the reserved project key INT left unquoted", "const pkey = k => JQL_RESERVED_KEYS.includes(k) ? q(k) : k;", "const pkey = k => k;", quoting_problems),
    ('Cycle Time per Release counting SOW epics again', 'const cycleExcluded = aiExcluded;', 'const cycleExcluded = e => String(e.cat || "").toLowerCase() === "maintenance";', cycle_problems),
    ('the Cycle Time per Release link keeping SOW epics (Maintenance-only query)', 'const CYCLE_KEPT_JQL = AI_KEPT_JQL;', 'const CYCLE_KEPT_JQL = `(cf[10139] is EMPTY OR cf[10139] != "Maintenance")`;', cycle_problems),
    ('Cycle Time per Release counting Maintenance epics again', 'const pop = list.filter(e => cls(e.s) === "done" && !cycleExcluded(e)),', 'const pop = list.filter(e => cls(e.s) === "done"),', cycle_problems),
    ('Cycle Time per Release dropping the epics AI did not implement', 'const pop = list.filter(e => cls(e.s) === "done" && !cycleExcluded(e)),', 'const pop = list.filter(e => cls(e.s) === "done" && !cycleExcluded(e) && e.ai),', cycle_problems),
    ('the Cycle Time per Release link losing the exclusion', 'const cycleHref = rel => jira({release: rel, kind: "done", commit: ALLC, extra: CYCLE_KEPT_JQL});', 'const cycleHref = rel => jira({release: rel, kind: "done", commit: ALLC});', cycle_problems),
    ('the Cycle Time per Release link filtering on AI', 'const cycleHref = rel => jira({release: rel, kind: "done", commit: ALLC, extra: CYCLE_KEPT_JQL});', 'const cycleHref = rel => jira({release: rel, kind: "done", commit: ALLC, extra: `${CYCLE_KEPT_JQL} AND cf[15229] = Yes`});', cycle_problems),
    ("accessibility bugs left in the Open Bugs links", "const AX_EXCLUDE = ", 'const AX_EXCLUDE = ""; const AX_EXCLUDE_UNUSED = ', None),
]


@SUITE.test("oracle_selftest_catches_seeded_defects")
def _(t: T):
    src = ctx.template.read_text(encoding="utf-8")
    F = fixture()
    ran = 0
    for label, old, new, fn in MUTATIONS:
        if src.count(old) != 1:
            t.note(f"not run: '{label}' (the pattern is not in this template exactly once)")
            continue
        ran += 1
        frag = MS.render_page(F["data"], ctx.template).replace(old, new, 1) if False else None
        text = src.replace(old, new, 1)
        tmp = Path(ctx.dir) / f"mutant_{ran}.html"
        payload = json.dumps(F["data"], ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
        tmp.write_text(text.replace("/*__DATA__*/null", payload), encoding="utf-8")
        url = "file://" + str(tmp)
        if fn is not None:
            probs = fn(url)
            t.check(bool(probs), f"seeded defect caught: {label} ({len(probs)} findings)")
        else:
            found = []
            for spec in ("", "ax=0&p=PMN"):
                for a in anchors_for(spec, url):
                    if a["block"] == "bugs":
                        st, d = evaluate_anchor(a)
                        if st == "mismatch":
                            found.append(a)
            t.check(bool(found), f"seeded defect caught: {label} ({len(found)} mismatching links)")
    if not ran:
        raise kit.Skip("none of the seeded defects applies to this template version")


if __name__ == "__main__":
    sys.exit(kit.cli(SUITE, __doc__))
