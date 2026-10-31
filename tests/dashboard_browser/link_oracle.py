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
import make_synthetic as MS                                                         # noqa: E402
from kit import ctx, T                                                              # noqa: E402

SUITE = kit.Suite("Delivery Pulse link oracle")
BAD_TOKEN = re.compile(r"NaN|undefined|\[object|\bnull\b")

STATES = [
    "", "r=26.4", "r=26.2&p=PMN", "p=PMN", "p=CXWFM|WFM", "p=PMN|CXCO|CXSUP", "TEAM", "p=PMN&TEAM", "c=Stretch", "ax=1", "bp=P1|P2", "bp=P3&ax=1", "cfb=yes", "cfb=no", "cfb=yes&p=PMN",
    "cg=quarter", "cg=month&p=CXCO", "g=quarter", "cpg=release", "cpg=release&cpm=count", "cpm=count", "cpg=release&p=PMN", "cpg=release&TEAM", "cpg=release&p=CXWFM|WFM&cpm=count",
    "p=CXINT&cpm=count", "p=WFM&cg=quarter&bp=P1|P2|P3&ax=1",
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


# ================================================================ the oracle must not be blind: seed each known defect into a copy of the template and require it to be caught
MUTATIONS = [
    ("a NaN date in the 'since the pull' range (Quarter mode defect)", "const START_R = [C.start, null]", 'const START_R = ["0-NaN-01", null]', quarter_mode_problems),
    ("an unscoped 'no story points' range in Release mode", 'const noSpRanges = by === "release" ? shownR : [START_R];', "const noSpRanges = [START_R];", release_mode_problems),
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
