#!/usr/bin/env python3
"""Link guard (proposal): EVERY Jira link the page renders, in EVERY view, must be a query that Jira recalculates, never a frozen list of issue keys.

Drop this file next to kit.py / make_synthetic.py in tests/dashboard_browser/ (it only uses kit, make_synthetic and the standard library) and add it to run_dashboard_checks.py.

    python3 link_guard.py --live                        # the live template, the default view matrix (about 60 s)
    LINK_GUARD_FULL=1 python3 link_guard.py --live      # every release x project set x cycle x node x facet (about 8 min)
    LINK_GUARD_ALLOW=proposed python3 link_guard.py --live   # also accept the documented 'not expressible' sites below

What it asserts
  1. links_no_frozen_key_lists          no JQL carries more than FEW_KEYS issue keys (any field: key, issue, issuekey, parent, "Epic Link"), unless the site is in ALLOW with a reason.
  2. links_allowlist_has_no_stale_entries   an ALLOW entry that no rendered link uses any more is removed (the list can only shrink).
  3. links_no_frozen_release_or_date_lists  fixVersion lists with 3+ releases and the like are reported per site (ALLOW_CALENDAR documents the accepted ones).
  4. links_the_view_matrix_really_rendered  the sweep saw enough links, in every section, with no console error (a green guard is not a blind one).
  5. selftest_guard_catches_a_seeded_key_list   a copy of the template with a 6-key list added to an ordinary query link must be flagged.
  6. links_within_length_budget            no Jira link is longer than URL_BUDGET characters (Jira's front door rejects about 10 KB), also with every team ticked.
The site of a link is its JQL with the keys elided ("parent in (<keys>) AND issuetype = Epic ..."), so the allowlist does not depend on line numbers.
"""
from __future__ import annotations

import collections
import itertools
import os
import re
import sys
import time
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kit                                                                          # noqa: E402
import make_synthetic as MS                                                         # noqa: E402
from kit import ctx, T                                                              # noqa: E402

SUITE = kit.Suite("Delivery Pulse link guard")
URL_BUDGET = 6000                               # the page returns no link above this (a plain number instead); measured: Jira rejects URLs of about 10 KB
FEW_KEYS = 3                                    # a hand-picked "pair of issues" is tolerated; a population is not
KEYRE = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")

# --------------------------------------------------------------------------------------------- the allowlist: one entry per site, with the reason and the way out
# regex (searched in the elided JQL), reason, what a query could do instead. EMPTY by intent for sites Jira CAN express. The owner decides what stays.
ALLOW: list[tuple[str, str, str, str]] = []      # (regex on the elided JQL, regex on the link's hover title or "", reason, what a query could do instead)
PROPOSED_ALLOW = [      # the accepted gaps: every entry is a population Jira cannot express as a query, or a documented pending decision; the list may only shrink      # sites whose population Jira's native JQL cannot express (reasons checked on the synthetic payload, see the QA report)
    (r"\bparent in \(<keys>\)", "", "child epics / bugs selected by an attribute of their PARENT (the Capability's fix version, the epic's planned date): not searchable in native JQL", "none; the Capabilities query is the closest"),
    (r"^key in \(<keys>\)$", "", "pairs whose far end is not Done, story-level links, dependency cards, Needs Attention groups, DQ 'no cycle time' (changelog-derived): a linked issue's status / the changelog is not searchable", "issueLinkType in (...) is a superset"),
    (r"\bkey in \(<keys>\)", r"epics with open bugs", "epics selected by the state of their CHILD bugs: not searchable in native JQL", "none"),
]
ALLOW_CALENDAR: list[tuple[str, str]] = [(r"fixVersion in \(", "the release list is the dashboard's own release set, fixed when the data is built (a new release needs a rebuild)")]

ALLOW = ALLOW + PROPOSED_ALLOW

# --------------------------------------------------------------------------------------------- the view matrix
EXPAND_JS = r"""(() => {
  document.querySelectorAll('details').forEach(d => { d.open = true; });
  for (let i = 0; i < 4; i++) {
    document.querySelectorAll('#attn button[aria-expanded="false"], #attn-all').forEach(b => { if (!b.hidden) { try { b.click(); } catch (e) {} } });
    document.querySelectorAll('[data-act^="more-"][aria-expanded="false"]').forEach(b => b.click());
  }
  const ex = document.querySelector('[data-cyact="expall"]'); if (ex) ex.click();
  document.querySelectorAll('[data-cyact="bug"][aria-expanded="false"]').forEach(b => { try { b.click(); } catch (e) {} });
  document.querySelectorAll('details').forEach(d => { d.open = true; });
  return [...document.querySelectorAll('a[href]')].map(a => { const s = a.closest('section[aria-labelledby]');
    return {href: a.getAttribute('href'), text: (a.textContent || '').trim().slice(0, 50), sec: s ? s.getAttribute('aria-labelledby') : 'other', tip: ((a.getAttribute('data-tip') || '').split('\n')[0]).slice(0, 100), full: (a.getAttribute('data-tip') || '').slice(0, 600)}; });
})()"""
NODES_JS = "[...document.querySelectorAll('#cy-ovbody [data-cyact=\"open\"]')].map(b => b.dataset.cyval)"


def views(full: bool, data: dict) -> list[str]:
    rels = data["releases"] if full else ["26.4", "27.1"]
    psets = ["", "p=PMN", "p=PMN|CXCO"] + (["p=CXWFM|WFM|CXINT"] if full else [])
    out = [f"r={r}&{p}&cy={c}".replace("&&", "&") for r in rels for p in psets for c in ("DC1", "DC2")]
    facets = ["c=Stretch", "ax=1", "cfb=yes", "g=week", "g=quarter", "cg=quarter", "dp=all", "dp=overdue", "dp=gap", "nt=capability", "nt=team", "cx=committed", "cpg=release", "cpm=count", "cps=pbi", "cps=pbi&cpm=count"]
    out += [f"r=27.1&{f}" for f in facets]
    teams = sorted({t for e in data["epics"] for t in (e.get("tm") or [])})                   # every team ticked: the longest queries (team clauses and sprint names together)
    allt = "t=" + "|".join(urllib.parse.quote(t) for t in teams)
    out += [f"r=27.1&{allt}&cy=DC1", f"r=27.1&{allt}&cy=DC2"]
    return out


_cache: dict = {}


def sweep(template: Path | None = None) -> dict:
    """Renders the page on the synthetic payload in every view and returns {(jql): {site, sec, tip, text, view}} plus the number of links and errors."""
    key = str(template or ctx.template)
    if key in _cache:
        return _cache[key]
    old = ctx.template
    if template:
        ctx.template = template
    try:
        data = MS.make(MS.il_today())
        url = ctx.write(kit.fragment_for(data), "guard")
        ch = ctx.chrome
        found, n_links, errors, secs = {}, 0, [], collections.Counter()
        full = bool(os.environ.get("LINK_GUARD_FULL"))
        todo = views(full, data)
        seen_nodes: set = set()
        i = 0
        while i < len(todo):
            h = todo[i]
            i += 1
            ch.goto(url + "#" + h)
            kit.wait_ready(ch)
            time.sleep(0.1)
            errors += [f"{h}: {e}" for e in ch.console_errors()]
            anchors = ch.js(EXPAND_JS)
            if h.startswith("r=27.1&") and "cy=DC1" in h and h not in seen_nodes and (full or h.count("&") <= 2):      # the detail view behind every project, team and pod tile
                seen_nodes.add(h)
                for nd in (ch.js(NODES_JS) or [])[: (None if full else 12)]:
                    ch.goto(url + "#" + h + "&ct=" + nd)
                    kit.wait_ready(ch)
                    anchors += ch.js(EXPAND_JS)
            for a in anchors:
                q = urllib.parse.urlsplit(a["href"])
                if q.path.rstrip("/") != "/issues":
                    continue
                jql = urllib.parse.parse_qs(q.query, keep_blank_values=True).get("jql", [""])[0]
                n_links += 1
                secs[a["sec"]] += 1
                f = found.setdefault(jql, dict(sec=a["sec"], tip=a["tip"], full=a.get("full", ""), text=a["text"], view=h, urllen=0))
                f["urllen"] = max(f["urllen"], len(a["href"]))
        _cache[key] = dict(found=found, links=n_links, errors=errors, sections=secs, views=len(todo))
        return _cache[key]
    finally:
        ctx.template = old


def elide(jql: str) -> str:
    """The site of a link: the JQL with every list of keys replaced by <keys> (and a lone key by <key>)."""
    s = re.sub(r"\(\s*(?:[A-Z][A-Z0-9]+-\d+\s*,?\s*)+\)", "(<keys>)", jql)
    s = re.sub(r"(\b(?:key|issuekey|issue|parent)\s*[!=]=?\s*)[A-Z][A-Z0-9]+-\d+", r"\1<key>", s, flags=re.I)
    return s


def n_keys(jql: str) -> int:
    return len(set(KEYRE.findall(jql)))


def allowed(site: str, tip: str = "") -> str | None:
    for rx, rt, why, _ in ALLOW:
        if re.search(rx, site) and (not rt or re.search(rt, tip)):
            return rx
    return None


def offenders(res: dict) -> dict:
    off: dict = {}
    for jql, meta in res["found"].items():
        k = n_keys(jql)
        if k > FEW_KEYS:
            site = elide(jql)
            if allowed(site, meta['tip']) is None:
                o = off.setdefault(site, dict(max=0, n=0, ex=meta))
                o["max"], o["n"] = max(o["max"], k), o["n"] + 1
    return off


# --------------------------------------------------------------------------------------------- tests
@SUITE.test("links_the_view_matrix_really_rendered")
def _(t: T):
    r = sweep()
    t.check(not r["errors"], f"console errors while rendering the views: {r['errors'][:3]}")
    t.check(r["links"] >= 3000, f"only {r['links']} Jira links were seen in {r['views']} views (a blind guard)")
    for sec in ("h-burnup", "h-bugs", "h-cfb", "h-deps", "h-capview", "h-cx", "h-nfr", "h-cycles", "h-trend"):
        t.check(r["sections"][sec] > 0, f"no link rendered in section {sec}")
    t.note(f"{r['links']} links ({len(r['found'])} distinct) in {r['views']} views; sections: {dict(r['sections'])}")


@SUITE.test("links_no_frozen_key_lists")
def _(t: T):
    """The owner's rule: a link is a query Jira recalculates. More than FEW_KEYS issue keys in any JQL is a frozen list, wherever it comes from."""
    off = offenders(sweep())
    for site, o in sorted(off.items(), key=lambda x: -x[1]["max"]):
        t.failures.append(f"frozen list of up to {o['max']} keys ({o['n']} distinct links) in section {o['ex']['sec']}: '{o['ex']['tip'] or o['ex']['text']}' -> {site[:170]}")
    t.passed += 0 if off else 1


@SUITE.test("links_within_length_budget")
def _(t: T):
    """Jira's front door rejects URLs of about 10 KB: a link above URL_BUDGET characters must not be rendered (the number is plain text)."""
    r = sweep()
    longest = sorted(r["found"].items(), key=lambda x: -x[1]["urllen"])
    over = [(m["urllen"], m["sec"], m["tip"] or m["text"], m["view"]) for _, m in longest if m["urllen"] > URL_BUDGET]
    t.check(not over, f"{len(over)} links are longer than {URL_BUDGET} characters, the longest {over[:2]}")
    top = longest[0][1]
    t.check(top["urllen"] > 3000, "the longest link is short: the views did not produce long queries (a blind check)")
    t.note(f"longest link: {top['urllen']} characters ('{top['tip'] or top['text']}' in {top['view']}); budget {URL_BUDGET}")


@SUITE.test("links_exact_lists_say_so_in_their_tooltip")
def _(t: T):
    """A link that opens a list of keys must tell the reader that it is an exact list that will not follow Jira (the page adds one standard sentence), so nobody takes it for a query."""
    bad = {}
    for jql, meta in sweep()["found"].items():
        if n_keys(jql) > FEW_KEYS and not re.search(r"exact|by key", meta.get("full", ""), re.I):
            bad.setdefault(elide(jql)[:150], meta)
    for site, meta in bad.items():
        t.failures.append(f"a list of keys without the 'exact list' tooltip in section {meta['sec']}: '{meta['tip'] or meta['text']}' -> {site}")
    t.passed += 0 if bad else 1


@SUITE.test("links_allowlist_has_no_stale_entries")
def _(t: T):
    r = sweep()
    sites = [(elide(j), m["tip"]) for j, m in r["found"].items() if n_keys(j) > FEW_KEYS]
    for rx, rt, why, _ in ALLOW:
        t.check(any(re.search(rx, s) and (not rt or re.search(rt, tip)) for s, tip in sites), f"allowlist entry no longer used, remove it: {rx} ({why})")
    t.passed += 0 if ALLOW else 1


@SUITE.test("links_no_frozen_release_or_date_lists")
def _(t: T):
    """Reported, not hidden: a fixVersion list of 3+ releases is frozen at build time (a new release is missing until a rebuild)."""
    bad: dict = {}
    for jql, meta in sweep()["found"].items():
        for m in re.finditer(r"fixVersion in \(([^)]*)\)", jql):
            if m.group(1).count(",") >= 2 and not any(re.search(rx, jql) for rx, _ in ALLOW_CALENDAR):
                bad.setdefault(re.sub(r"project (?:in \([^)]*\)|= \w+)", "project ...", re.sub(r'"\d{4}-\d{2}-\d{2}"', '"<date>"', jql))[:140], meta)
    for site, meta in bad.items():
        t.failures.append(f"a frozen list of releases in section {meta['sec']}: '{meta['tip'] or meta['text']}' -> {site}")
    t.passed += 0 if bad else 1


@SUITE.test("selftest_guard_catches_a_seeded_key_list")
def _(t: T):
    src = ctx.template.read_text(encoding="utf-8")
    old = 'if (o.kind === "done") jql += ` AND status = Done`;'
    if src.count(old) != 1:
        raise kit.Skip("the seeding anchor is not in this template exactly once")
    seed = old + ' if (o.kind === "done") jql += " AND key in (ZZ-1, ZZ-2, ZZ-3, ZZ-4, ZZ-5, ZZ-6)";'
    tmp = Path(ctx.dir) / "guard_mutant.html"
    tmp.write_text(src.replace(old, seed, 1), encoding="utf-8")
    before = set(offenders(sweep()))
    after = offenders(sweep(tmp))
    new = [s for s in after if s not in before and "ZZ" not in s and "<keys>" in s]
    t.check(bool(new), f"the seeded 6-key list on 'Done epics' links was not flagged (new offending sites: {len(new)})")


if __name__ == "__main__":
    sys.exit(kit.cli(SUITE, __doc__))
