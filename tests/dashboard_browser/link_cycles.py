#!/usr/bin/env python3
"""Delivery Cycles links are QUERIES (the owner's rule): for every release x project set x cycle x node x kind, the epics the query finds equal the epics the page counts.

The page builds each link with cyQ(kind, node, cycle). This suite asks the page for the query of every number it prints (Planned, Done, Due so far, Overdue, Stale, Due next 7 days, Flagged,
Carry-over, No planned date, Epics with Flags, the weekly table, After release end, the pod note, the No Pod Label rows), EVALUATES that query in Python (jql_eval.py over the baked epics, with
the sprint-name rules of the real Jira) and compares the SET of keys with the list the page's model holds. A seeded mutant must be caught. The payload is the fictitious one, plus a variant
that reaches the branches the stock payload leaves empty (carry-over, planned after the release end, a Target Sprint the calendar does not know).

    python3 link_cycles.py --live                       # about 60 s
    LINK_CYCLES_FULL=1 python3 link_cycles.py --live    # every release and project set
"""
from __future__ import annotations

import collections
import copy
import datetime as dt
import json
import os
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

SUITE = kit.Suite("Delivery Pulse Cycles links (queries)")

# The model the page holds, and the query of each number, for every node of the hierarchy. Kinds are the ones cyQ knows.
MODEL_JS = r"""(() => {
  const M = CYM; if (!M || M.none) return null;
  const K = l => l.map(e => e.k).sort(), dec = u => u ? decodeURIComponent(u.split("jql=")[1]) : null;
  const out = [], last = M.cycles[M.cycles.length - 1], c = M.c;
  const scopes = [{tag: "top", g: null}].concat(M.groups.map(n => ({tag: n.level + (n.virtual ? "-nopod" : ""), g: n})));
  for (const sc of scopes) {
    const g = sc.g, d = g ? cyGroupData(g) : {planned: M.planned(), carry: M.carry(), noDue: M.noDue, g: null, c};
    const s = g ? d.s : cyStats(d.planned, d.carry, d.noDue);
    const add = (kind, list, arg) => { const u = cyQ(kind, g, c, arg); out.push({tag: sc.tag, kind: arg ? kind + ":w" + arg[2] : kind, jql: dec(u), len: u ? u.length : 0, exp: K(list)}); };
    add("planned", s.planned); add("done", s.done); add("due", s.due); add("dueDone", s.dueDone); add("over", s.over); add("stale", s.staleIn);
    add("staleAll", s.staleIn.concat(s.staleCarry)); add("staleCarry", s.staleCarry); add("next", s.next); add("nextNs", s.nextNs);
    add("flag", s.flag); add("flagCarry", s.flagCarry); add("carry", s.carry); add("noDue", s.noDue);
    if (g) { add("scope", g.epics); add("concerns", cyConcerns(d).map(r => r.e)); }
    else add("scope", M.epics);
    const len = CY_DAY(c.end) - CY_DAY(c.start) + 1, nw = Math.ceil(len / 7);
    for (let w = 0; w < nw; w++) {
      const ws = cyAdd(c.start, w * 7), we = cyAdd(c.start, Math.min(w * 7 + 6, len - 1)), list = d.planned.filter(e => e.due >= ws && e.due <= we);
      add("week", list, [ws, we, w]); add("weekDone", list.filter(cyDone), [ws, we, w]); add("weekOpen", list.filter(e => !cyDone(e)), [ws, we, w]);
    }
    if (!g) {
      const u = cyQ("after", null, last); out.push({tag: "top", kind: "after", jql: dec(u), len: u ? u.length : 0, exp: K(M.epics.filter(e => e.due && e.due > last.end))});
      if (cyLabelOk()) { add("podWith", M.epics.filter(e => e.pl.length)); add("podNone", M.epics.filter(e => !e.pl.length)); }
    }
  }
  return {asOf: CY.asOf, cycle: c.id, out};
})()"""

# Every Cycles link the DOM holds: the printed number must equal what its query finds (links that are queries on the dates, the Target Sprint, the pod labels or the keys of epics with bugs).
DOM_JS = r"""(() => {
  document.querySelectorAll('details').forEach(d => { d.open = true; });
  const ex = document.querySelector('[data-cyact="expall"]'); if (ex) ex.click();
  const sec = document.querySelector('section[aria-labelledby="h-cycles"]'); if (!sec) return [];
  return [...sec.querySelectorAll('a[href]')].map(a => ({href: a.getAttribute('href'), text: (a.textContent || '').trim(), tip: (a.getAttribute('data-tip') || '').slice(0, 300)}));
})()"""
NODES_JS = "[...document.querySelectorAll('#cy-ovbody [data-cyact=\"open\"]')].map(b => b.dataset.cyval)"
QUERYISH = ("duedate", "cf[12697]", "labels is EMPTY", "key in (")

BUDGET_NOTE = "a non-empty set whose link is null means the URL went over the budget (or the window is empty)"


def epic_issue(e: dict) -> dict:
    """A baked epic as the Jira fields the Cycles queries use (the same mapping the other oracles use)."""
    c = e.get("c")
    return {"key": e["k"], "project": e["p"], "issuetype": "Epic", "status": e["s"], "fixversion": list(e["fv"]), "cf[10094]": c if c and c != "Not Set" else None,
            "cf[10040]": list(e.get("tm") or []), "cf[10098]": list(e.get("tm") or []), "cf[10139]": e.get("cat"), "cf[15229]": "Yes" if e.get("ai") else None,
            "resolutiondate": e.get("rd"), "duedate": e.get("dd"), "cf[12697]": e.get("ts"), "labels": list(e.get("pl") or []) + (["NFR"] if e.get("nf") else []),
            "cf[10021]": "Impediment" if e.get("fl") else None, "parent": e.get("cp"), "summary": e.get("t", "")}


def variant(data: dict) -> dict:
    """The stock payload leaves carry-over and 'after the release end' empty and has no Target Sprint the calendar does not know: reach them, relative to the release windows."""
    d = copy.deepcopy(data)
    for rel in ("27.1", "27.2"):
        start, end = (dt.date.fromisoformat(x) for x in d["windows"][rel])
        mine = [e for e in d["epics"] if rel in e["fv"] and e["s"] not in ("Done", "Removed")]
        for e in mine[:4]:
            e["dd"], e["ts"] = (start - dt.timedelta(days=40)).isoformat(), None               # carried over, and stale
        mine[0]["fl"] = mine[4]["fl"] = 1                                                      # ... two of them flagged
        for e in mine[4:7]:
            e["dd"], e["ts"] = (start - dt.timedelta(days=2)).isoformat(), None                # carried over, not stale
        for e in mine[7:10]:
            e["dd"], e["ts"] = (end + dt.timedelta(days=20)).isoformat(), None                 # after the release end
        for e in mine[10:13]:
            e["dd"], e["ts"] = None, "SPR.unknown.1 (01Jan20)"                                 # a Target Sprint the calendar does not know: no planned date at all
        for e in mine[13:16]:
            e["dd"], e["ts"] = (start + dt.timedelta(days=9)).isoformat(), "SPR.unknown.2 (01Jan20)"      # ... and with a due date: the due date alone
        for e in mine[16:19]:
            e["fl"] = 1
        today = MS.il_today()                                                                  # epics ON the edges: the end of Delivery Cycle 1, yesterday, today plus 7, today minus 31
        for chunk, day in ((mine[19:21], start + dt.timedelta(days=48)), (mine[21:23], today - dt.timedelta(days=1)), (mine[23:25], today + dt.timedelta(days=7)), (mine[25:27], today - dt.timedelta(days=31))):
            for e in chunk:
                e["dd"], e["ts"] = day.isoformat(), None
    return d


_page: dict = {}


def page(kind: str = "stock") -> tuple[dict, str]:
    if kind not in _page:
        data = MS.make(MS.il_today())
        if kind == "variant":
            data = variant(data)
        _page[kind] = (data, ctx.write(kit.fragment_for(data), "cycles_" + kind))
    return _page[kind]


def views(full: bool, data: dict, name: str = "stock") -> list[str]:
    rels = data["releases"] if full else (["26.4", "27.1"] if name == "stock" else ["27.1", "27.2"])
    psets = ["", "p=PMN", "p=PMN|CXCO", "t=Team%20Alpha"] + (["p=CXWFM|WFM|CXINT", "c=Stretch"] if full else [])
    return [f"r={r}&{p}&cy={c}".replace("&&", "&") for r in rels for p in psets for c in ("DC1", "DC2")]


def sweep(template: Path | None = None, only_views: int | None = None, kinds: tuple = ("stock", "variant")) -> dict:
    """Loads the page in every view and compares, query by query, the set the query finds with the set the page counts."""
    old = ctx.template
    if template:
        ctx.template = template
        _page.clear()
    try:
        ch = ctx.chrome
        res = dict(n=collections.Counter(), nonempty=collections.Counter(), bad=collections.Counter(), ex=collections.defaultdict(list), dropped=[], errors=[], loads=0, maxlen=0, maxkind="",
                   dom_links=0, dom_bad=[], skipped=[], links_by_kind=collections.Counter())
        full = bool(os.environ.get("LINK_CYCLES_FULL"))
        for variant_name in kinds:
            data, url = page(variant_name)
            universe = [epic_issue(e) for e in data["epics"]]
            todo = views(full, data, variant_name)
            if only_views:
                todo = todo[:only_views]
            for h in todo:
                ch.goto(url + "#" + h)
                kit.wait_ready(ch)
                time.sleep(0.1)
                res["errors"] += [f"{variant_name} {h}: {e}" for e in ch.console_errors() if "link dropped" not in e]
                m = ch.js(MODEL_JS)
                if not m or (isinstance(m, dict) and "__error" in m):
                    res["skipped"].append(f"{variant_name} {h}: {str(m)[:80]}")
                    continue
                res["loads"] += 1
                for r in m["out"]:
                    tag = f"{variant_name} {h} {r['tag']}"
                    exp = set(r["exp"])
                    res["n"][r["kind"].split(":")[0]] += 1
                    if exp:
                        res["nonempty"][r["kind"].split(":")[0]] += 1
                    if not r["jql"]:
                        if exp:
                            res["dropped"].append((tag, r["kind"], len(exp)))
                        continue
                    res["links_by_kind"][r["kind"].split(":")[0]] += 1
                    if r["len"] > res["maxlen"]:
                        res["maxlen"], res["maxkind"] = r["len"], f"{tag} {r['kind']}"
                    try:
                        tree = J.parse(r["jql"])
                        got = {i["key"] for i in universe if J.evaluate(tree, i)}
                    except (J.Malformed, J.Unsupported) as exc:
                        res["errors"].append(f"{tag} {r['kind']}: the query cannot be evaluated: {exc}")
                        continue
                    if got != exp:
                        res["bad"][r["kind"].split(":")[0]] += 1
                        if len(res["ex"][r["kind"].split(":")[0]]) < 3:
                            res["ex"][r["kind"].split(":")[0]].append(f"{tag}: the page counts {len(exp)}, the query finds {len(got)}; differ on {sorted(exp ^ got)[:3]}")
                # the links the DOM holds: the printed number must equal what its query finds
                anchors = ch.js(DOM_JS) or []
                for nd in (ch.js(NODES_JS) or [])[: (None if full else 6)] if (kinds and variant_name == "variant" and h.endswith("cy=DC1")) else []:
                    ch.goto(url + "#" + h + "&ct=" + nd)
                    kit.wait_ready(ch)
                    anchors += ch.js(DOM_JS) or []
                for a in anchors:
                    q = urllib.parse.urlsplit(a["href"])
                    jql = urllib.parse.parse_qs(q.query, keep_blank_values=True).get("jql", [""])[0]
                    txt = a["text"].replace(",", "")
                    if q.path.rstrip("/") != "/issues" or not txt.isdigit() or "issuetype = Epic" not in jql or not any(k in jql for k in QUERYISH):
                        continue
                    res["dom_links"] += 1
                    try:
                        tree = J.parse(jql)
                        n = sum(1 for i in universe if J.evaluate(tree, i))
                    except (J.Malformed, J.Unsupported) as exc:
                        res["dom_bad"].append(f"{variant_name} {h}: {exc}")
                        continue
                    if n != int(txt):
                        res["dom_bad"].append(f"{variant_name} {h}: '{a['tip'].splitlines()[0] if a['tip'] else txt}' prints {txt}, its query finds {n}")
        return res
    finally:
        ctx.template = old
        if template:
            _page.clear()


_cache: dict = {}


def full_sweep() -> dict:
    if "full" not in _cache:
        _cache["full"] = sweep()
    return _cache["full"]


KINDS = ["planned", "done", "due", "dueDone", "over", "stale", "staleAll", "staleCarry", "next", "nextNs", "flag", "flagCarry", "carry", "noDue", "scope", "concerns",
         "week", "weekDone", "weekOpen", "after", "podWith", "podNone"]


@SUITE.test("cycles_the_pages_rendered_and_every_kind_was_compared_on_a_non_empty_set")
def _(t: T):
    r = full_sweep()
    t.check(not r["errors"], f"console errors or queries the evaluator cannot read: {r['errors'][:3]}")
    t.check(not r["skipped"], f"pages without a Cycles model: {r['skipped'][:3]}")
    t.check(r["loads"] >= 30, f"only {r['loads']} page loads compared (a blind suite)")
    for k in KINDS:
        t.check(r["nonempty"][k] > 0, f"kind '{k}' was never compared on a non-empty set (the payload does not reach it)")
    t.note(f"{r['loads']} page loads, {sum(r['n'].values())} comparisons ({sum(r['nonempty'].values())} on non-empty sets); per kind (non-empty/all): " +
           ", ".join(f"{k} {r['nonempty'][k]}/{r['n'][k]}" for k in KINDS))


@SUITE.test("cycles_every_query_finds_exactly_the_epics_the_page_counts")
def _(t: T):
    r = full_sweep()
    for k in KINDS:
        if r["bad"][k]:
            t.failures.append(f"{k}: the query differs from the page's set in {r['bad'][k]} of {r['n'][k]} comparisons, e.g. {r['ex'][k][0]}")
        else:
            t.passed += 1


@SUITE.test("cycles_no_non_empty_set_lost_its_link")
def _(t: T):
    r = full_sweep()
    by = collections.Counter(k for _, k, _ in r["dropped"])
    t.check(not r["dropped"], f"{len(r['dropped'])} numbers have no link ({BUDGET_NOTE}): {dict(by)}; first: {r['dropped'][:2]}")


@SUITE.test("cycles_printed_numbers_equal_what_their_links_find")
def _(t: T):
    r = full_sweep()
    t.check(r["dom_links"] >= 200, f"only {r['dom_links']} Cycles links were read from the page (a blind check)")
    t.check(not r["dom_bad"], f"{len(r['dom_bad'])} links print a number their query does not find: {r['dom_bad'][:3]}")
    t.note(f"{r['dom_links']} links in the page, longest URL of a query: {r['maxlen']} characters ({r['maxkind']})")


@SUITE.test("cycles_no_link_holds_a_list_of_keys_except_epics_with_open_bugs")
def _(t: T):
    import re
    data, url = page("variant")
    ch = ctx.chrome
    keyre = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
    bad = []
    for h in ("r=27.1&cy=DC1", "r=27.1&cy=DC2", "r=27.1&p=PMN&cy=DC1"):
        ch.goto(url + "#" + h)
        kit.wait_ready(ch)
        for nd in [None] + (ch.js(NODES_JS) or [])[:6]:
            if nd:
                ch.goto(url + "#" + h + "&ct=" + nd)
                kit.wait_ready(ch)
            for a in ch.js(DOM_JS) or []:
                jql = urllib.parse.parse_qs(urllib.parse.urlsplit(a["href"]).query).get("jql", [""])[0]
                if len(set(keyre.findall(jql))) > 3 and "with open bugs" not in a["tip"] and "open bug" not in a["tip"]:
                    bad.append(f"{h} {a['tip'][:60]!r}")
    t.check(not bad, f"{len(bad)} Cycles links still open a list of keys: {bad[:3]}")


@SUITE.test("cycles_tooltip_says_jira_finds_the_epics_again")
def _(t: T):
    data, url = page()
    ch = ctx.chrome
    ch.goto(url + "#r=27.1&cy=DC1")
    kit.wait_ready(ch)
    tips = ch.js("[...document.querySelectorAll('#h-cycles ~ * a[data-tip], section[aria-labelledby=\"h-cycles\"] a[data-tip]')].map(a => a.getAttribute('data-tip'))") or []
    t.check(any("Jira finds these epics again when you open the link" in x for x in tips), "no Cycles number says that Jira finds the epics again")
    t.check(not any("by key" in x for x in tips), "a Cycles tooltip still says it opens the epics by key")


@SUITE.test("cycles_a_link_over_the_url_budget_is_plain_text")
def _(t: T):
    """Above the budget the page renders the number without a link (and warns in the console); with a budget of 800 characters most Cycles numbers must lose their link and keep their number."""
    src = ctx.template.read_text(encoding="utf-8")
    old = "const CY_URL_MAX = 6000;"
    if src.count(old) != 1:
        raise kit.Skip("the budget constant is not in this template exactly once")
    data, url = page()
    tmp = Path(ctx.dir) / "cycles_budget.html"
    tmp.write_text(MS.render_page(data, _tmp_template(src.replace(old, "const CY_URL_MAX = 800;"))), encoding="utf-8")
    ch = ctx.chrome
    probe = ("(() => { const s = document.querySelector('section[aria-labelledby=\"h-cycles\"]'); return {long: [...s.querySelectorAll('a[href*=\"/issues/\"]')].filter(a => a.getAttribute('href').length > LIMIT).length, "
             "links: s.querySelectorAll('a[href*=\"/issues/\"]').length, kpi: [...document.querySelectorAll('#cy-kpis1 .v')].map(v => v.textContent.trim())}; })()")
    ch.goto(url + "#r=27.1&cy=DC1")
    kit.wait_ready(ch)
    base = ch.js(probe.replace("LIMIT", "800"))
    ch.goto("file://" + str(tmp) + "#r=27.1&cy=DC1")
    kit.wait_ready(ch)
    small = ch.js(probe.replace("LIMIT", "800"))
    t.check(base["long"] > 0, "the control page has no Cycles link longer than 800 characters (the check would be blind)")
    t.check(small["long"] == 0, f"{small['long']} Cycles links are longer than the budget")
    t.check(small["links"] < base["links"] and all(x for x in small["kpi"]), f"links {base['links']} -> {small['links']}; the numbers must stay: {small['kpi']}")


def _tmp_template(text: str) -> Path:
    p = Path(ctx.dir) / "cycles_budget_template.html"
    p.write_text(text, encoding="utf-8")
    return p


# --------------------------------------------------------------------------------------------- the suite must fail on a seeded defect
MUTANTS = [
    ("a due date on the end day is left out (<= becomes <)", '(duedate is EMPTY OR duedate <= "${hi}")', '(duedate is EMPTY OR duedate < "${hi}")'),
    ("a Target Sprint that ends after the window is no longer excluded", "(${CY_TS} is EMPTY OR ${CY_TS} not in (${after}))", "(${CY_TS} is EMPTY)"),
]


@SUITE.test("selftest_cycles_suite_catches_seeded_defects")
def _(t: T):
    src = ctx.template.read_text(encoding="utf-8")
    for i, (what, old, new) in enumerate(MUTANTS):
        if src.count(old) != 1:
            raise kit.Skip(f"the seeding anchor for '{what}' is not in this template exactly once")
        tmp = Path(ctx.dir) / f"cycles_mutant_{i}.html"
        tmp.write_text(src.replace(old, new, 1), encoding="utf-8")
        r = sweep(tmp, only_views=2, kinds=("variant",))
        caught = sum(r["bad"].values()) + len(r["dom_bad"])
        t.check(caught > 0, f"the suite did not notice the seeded defect: {what}")


if __name__ == "__main__":
    sys.exit(kit.cli(SUITE, __doc__))
