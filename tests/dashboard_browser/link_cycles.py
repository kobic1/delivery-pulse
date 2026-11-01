#!/usr/bin/env python3
"""Delivery Cycles links are QUERIES (the owner's rule): for every release x project set x cycle x node x kind, the epics the query finds equal the epics the page counts.

The page builds each link with cyQ(kind, node, cycle). This suite asks the page for the query of every number it prints (Planned, Done, Overdue, Stale, Due next 7 days, Flagged,
Carry-over, No planned date, Epics with Flags, the weekly table, After release end, the pod note, the No Pod Label rows, the epics of every pod, in flight, and the epics in flight of the pods over the
level), EVALUATES that query in Python (jql_eval.py over the baked epics, with the sprint-name rules of the real Jira) and compares the SET of keys with the list the page's model holds. A seeded mutant
must be caught. The payload is the fictitious one, plus a variant that reaches the branches the stock payload leaves empty (carry-over, planned after the release end, a Target Sprint the calendar does not
know, and a set of seeded pods: exactly 3 and exactly 4 epics in flight, Validation counted with In Progress, only Done, only outside the cycle, a label shared by two projects, case variants, two labels on
one epic, an in-flight epic with no pod label, labels that look like issue keys).

The Pods tiles are also recounted by an independent Python oracle (pod_oracle) from the baked epics in every view, and compared with the printed tile values, the opened lists and the facts line of the
detail views.

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
import pod_oracle as PO                                                             # noqa: E402
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
    const s = g ? d.s : cyStats(d.planned, d.carry);
    const add = (kind, list, arg) => { const u = cyQ(kind, g, c, arg); out.push({tag: sc.tag, kind: arg ? kind + ":w" + arg[2] : kind, jql: dec(u), len: u ? u.length : 0, exp: K(list)}); };
    add("planned", s.planned); add("done", s.done); add("over", s.over); add("stale", s.staleIn); add("next", s.next); add("nextNs", s.nextNs);
    add("flag", s.flag); add("flagCarry", s.flagCarry); add("carry", d.carry); add("noDue", d.noDue);
    if (g) { add("scope", g.epics); add("concerns", cyConcerns(d).map(r => r.e)); }
    else add("scope", M.epics);
    const len = CY_DAY(c.end) - CY_DAY(c.start) + 1, nw = Math.ceil(len / 7);
    for (let w = 0; w < nw; w++) {
      const ws = cyAdd(c.start, w * 7), we = cyAdd(c.start, Math.min(w * 7 + 6, len - 1)), list = d.planned.filter(e => e.due >= ws && e.due <= we);
      add("week", list, [ws, we, w]); add("weekDone", list.filter(cyDone), [ws, we, w]); add("weekOpen", list.filter(e => !cyDone(e)), [ws, we, w]);
    }
    if (!g) {
      const u = cyQ("after", null, last); out.push({tag: "top", kind: "after", jql: dec(u), len: u ? u.length : 0, exp: K(M.epics.filter(e => e.due && e.due > last.end))});
      if (cyLabelOk()) {
        add("podWith", M.epics.filter(e => e.pl.length)); add("podNone", M.epics.filter(e => !e.pl.length));
        const fig = cyPodFig(M.epics, M.planned()), addp = (kind, list, arg) => { const u = cyQ(kind, null, c, arg); out.push({tag: "top", kind, jql: dec(u), len: u ? u.length : 0, exp: K(list)}); };
        addp("podWip", fig.wipEpics, fig.wip);
        fig.pods.forEach(p => { addp("podEpics", p.epics, p); addp("podFlight", p.flight, p); });
      }
    }
  }
  return {asOf: CY.asOf, cycle: c.id, out};
})()"""

# Every Cycles link the DOM holds: the printed number must equal what its query finds (links that are queries on the dates, the Target Sprint, the pod labels or the keys of epics with bugs).
DOM_JS = r"""(() => {
  document.querySelectorAll('details').forEach(d => { d.open = true; });
  const ex = document.querySelector('[data-cyact="expall"]'); if (ex) ex.click();
  const sec = document.querySelector('section[aria-labelledby="h-cycles"]'); if (!sec) return [];
  const grab = root => [...root.querySelectorAll('a[href]')].map(a => ({href: a.getAttribute('href'), text: (a.textContent || '').trim(), tip: (a.getAttribute('data-tip') || '').slice(0, 300)}));
  const out = grab(sec);
  if (!document.getElementById('cy-pods').hidden) document.querySelectorAll('#cy-kpis2 [data-cyact="pods"]').forEach(b => { b.click(); out.push(...grab(document.getElementById('cy-podlist'))); b.click(); });      // each list opened in turn, then closed
  return out;
})()"""
NODES_JS = "[...document.querySelectorAll('#cy-ovbody [data-cyact=\"open\"]')].map(b => b.dataset.cyval)"
QUERYISH = ("duedate", "cf[12697]", "labels is EMPTY", "labels in (", "key in (")

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




def seed_pods(d: dict) -> None:
    """Pods for the variant payload (release 27.1, fictitious labels). D1 is inside Delivery Cycle 1, D2 inside Delivery Cycle 2.
    Pod-Seed-Three: 3 In Progress (not over the level), planned in DC1. Pod-Seed-Four: 4 In Progress, DC1. Pod-Seed-Mix: 3 In Progress + 1 Validation, DC2. Pod-Seed-Done: 2 Done, DC1.
    Pod-Seed-Late: 2 New, DC2 only (idle in DC1). Pod-Seed-Undated: 1 epic with no planned date (idle in both). Pod-Seed-Shared: 4 In Progress in PMN and 2 in CXCO (over the level in one project only).
    Pod-Seed-Case / pod-seed-case / POD-SEED-CASE: 2 + 1 + 1 In Progress (one pod, 4 epics). Pod-Seed-TwoA and TwoB: 3 In Progress each plus ONE epic that carries both labels.
    4 In Progress epics with no pod label. POD-21 .. POD-24: 4 In Progress each, labels that look like issue keys."""
    start = dt.date.fromisoformat(d["windows"]["27.1"][0])
    d1, d2 = start + dt.timedelta(days=10), start + dt.timedelta(days=60)
    n = [95000]
    teams = {"PMN": ["Team Alpha", "Team Bravo"], "CXCO": ["Team Echo", "Team Foxtrot"]}

    def add(proj: str, labels, status: str, due) -> None:
        n[0] += 1
        e = {"k": f"{proj}-{n[0]}", "p": proj, "t": f"Seed epic {n[0]}", "s": status, "fv": ["27.1"], "c": "Committed", "tm": [teams[proj][n[0] % 2]], "ai": False, "m": None, "rd": None,
             "cr": (start - dt.timedelta(days=30)).isoformat(), "cat": None, "ad": {"27.1": start.isoformat()}, "ts": None, "dd": due.isoformat() if due else None, "ud": start.isoformat()}
        if status == "Done":
            e["rd"] = (start + dt.timedelta(days=12)).isoformat()
            e["ip"], e["vl"], e["edct"], e["cal"] = 5, 0, 5, 5
        if labels:
            e["pl"] = list(labels)
        d["epics"].append(e)

    for _ in range(3):
        add("PMN", ["Pod-Seed-Three"], "In Progress", d1)
    for _ in range(4):
        add("PMN", ["Pod-Seed-Four"], "In Progress", d1)
    for st in ("In Progress", "In Progress", "In Progress", "Validation"):
        add("PMN", ["Pod-Seed-Mix"], st, d2)
    for _ in range(2):
        add("PMN", ["Pod-Seed-Done"], "Done", d1)
        add("PMN", ["Pod-Seed-Late"], "New", d2)
    add("PMN", ["Pod-Seed-Undated"], "In Definition", None)
    for _ in range(4):
        add("PMN", ["Pod-Seed-Shared"], "In Progress", d1)
    for _ in range(2):
        add("CXCO", ["Pod-Seed-Shared"], "In Progress", d1)
    for label, k in (("Pod-Seed-Case", 2), ("pod-seed-case", 1), ("POD-SEED-CASE", 1)):
        for _ in range(k):
            add("PMN", [label], "In Progress", d1)
    for lab in ("Pod-Seed-TwoA", "Pod-Seed-TwoB"):
        for _ in range(3):
            add("PMN", [lab], "In Progress", d1)
    add("PMN", ["Pod-Seed-TwoA", "Pod-Seed-TwoB"], "In Progress", d1)
    for _ in range(4):
        add("PMN", None, "In Progress", d1)
    for i in range(21, 25):
        for _ in range(4):
            add("PMN", [f"POD-{i}"], "In Progress", d1)


_page: dict = {}


def page(kind: str = "stock") -> tuple[dict, str]:
    if kind not in _page:
        data = MS.make(MS.il_today())
        if kind == "variant":
            data = variant(data)
            seed_pods(data)
        _page[kind] = (data, ctx.write(kit.fragment_for(data), "cycles_" + kind))
    return _page[kind]


def views(full: bool, data: dict, name: str = "stock") -> list[str]:
    rels = data["releases"] if full else (["26.4", "27.1"] if name == "stock" else ["27.1", "27.2"])
    psets = ["", "p=PMN", "p=PMN|CXCO", "p=INT", "t=Team%20Alpha"] + (["p=CXWFM|WFM|CXINT|INT", "c=Stretch"] if full else [])
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
                   dom_links=0, dom_bad=[], skipped=[], links_by_kind=collections.Counter(), pod_bad=[], pod_seen=collections.Counter())
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
                PO.check_pods(res, data, ch.js(PO.POD_JS), f"{variant_name} {h}", ch)
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
                nodes = (ch.js(NODES_JS) or [])[: (None if full else 6)] if (kinds and variant_name == "variant" and h.endswith("cy=DC1")) else []
                if nodes:
                    nodes += [x for x in (ch.js(PO.PODS_JS) or []) if x not in nodes]                    # and a few pod leaves
                for nd in nodes:
                    ch.goto(url + "#" + h + "&ct=" + nd)
                    kit.wait_ready(ch)
                    anchors += ch.js(DOM_JS) or []
                    PO.check_node(res, data, ch.js(PO.NODE_JS), f"{variant_name} {h} {nd}")
                for a in anchors:
                    q = urllib.parse.urlsplit(a["href"])
                    jql = urllib.parse.parse_qs(q.query, keep_blank_values=True).get("jql", [""])[0]
                    txt = a["text"].replace(",", "")
                    if q.path.rstrip("/") != "/issues" or not txt.isdigit() or "issuetype = Epic" not in jql or not any(k in jql for k in QUERYISH) or "distinct pod labels" in a["tip"]:
                        continue                                                       # (the definition's count of pod LABELS per project prints labels, not the epics its query opens)
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


KINDS = ["planned", "done", "over", "stale", "next", "nextNs", "flag", "flagCarry", "carry", "noDue", "scope", "concerns",
         "week", "weekDone", "weekOpen", "after", "podWith", "podNone", "podWip", "podEpics", "podFlight"]
GONE = ["due", "dueDone", "staleAll", "staleCarry"]                                                  # the kinds of the removed tiles and columns: the page no longer builds them


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


@SUITE.test("cycles_no_link_holds_a_list_of_keys")
def _(t: T):
    """The Open Bugs tile was the one Cycles link that opened a list of keys; it is gone, so no Cycles link may carry more than three issue keys. A quoted value (a pod label such as POD-21) is not a key:
    the variant payload seeds four labels that look like keys, and link_guard.n_keys must not count them."""
    import re
    import link_guard as G
    data, url = page("variant")
    ch = ctx.chrome
    keyre = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
    bad, keylike, exact = [], 0, []
    for h in ("r=27.1&cy=DC1", "r=27.1&cy=DC2", "r=27.1&p=PMN&cy=DC1"):
        ch.goto(url + "#" + h)
        kit.wait_ready(ch)
        for nd in [None] + (ch.js(NODES_JS) or [])[:6]:
            if nd:
                ch.goto(url + "#" + h + "&ct=" + nd)
                kit.wait_ready(ch)
            for a in ch.js(DOM_JS) or []:
                jql = urllib.parse.parse_qs(urllib.parse.urlsplit(a["href"]).query).get("jql", [""])[0]
                if G.n_keys(jql) > 3:
                    bad.append(f"{h} {a['tip'][:60]!r}")
                if len(set(keyre.findall(jql))) > 3:
                    keylike += 1                                                           # a link that carries 4+ labels that look like keys (the guard must still pass it)
                    if re.search(r"exact|by key", a["tip"], re.I):
                        exact.append(f"{h} {a['tip'][:60]!r}")
    t.check(not bad, f"{len(bad)} Cycles links open a list of keys: {bad[:3]}")
    t.check(keylike > 0, "no link carried labels that look like issue keys (the seeded pods POD-21..24 did not reach a link: a blind check)")
    t.check(not exact, f"a link with labels that look like keys says it is an exact list: {exact[:2]}")


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
    pod_budget(t, src, old)
    t.check(small["long"] == 0, f"{small['long']} Cycles links are longer than the budget")
    t.check(small["links"] < base["links"] and all(x for x in small["kpi"]), f"links {base['links']} -> {small['links']}; the numbers must stay: {small['kpi']}")


POD_PROBE = ("(() => { const t = document.querySelector('#cy-kpis2 [data-kpi=\"wip\"]'), a = t.querySelector('.s a'); return {v: t.querySelector('.v').textContent.trim(), btn: !!t.querySelector('.v button'), "
             "s: t.querySelector('.s').textContent.trim(), len: a ? a.getAttribute('href').length : 0, link: !!a, idle: document.querySelector('#cy-kpis2 [data-kpi=\"idle\"] .v').textContent.trim()}; })()")


def pod_budget(t: T, src: str, old: str) -> None:
    """The union link of 'Pods With More Than 3 Epics in Flight' is one URL; with a budget one character below its length it is plain text, the number stays, and the buttons keep working."""
    data, url = page("variant")
    ch = ctx.chrome
    ch.goto(url + "#r=27.1&cy=DC1")
    kit.wait_ready(ch)
    base = ch.js(POD_PROBE)
    t.check(base["link"] and base["len"] > 200, f"the control page has no in-flight link to cut ({base})")
    if not base["link"]:
        return
    tmp = Path(ctx.dir) / "cycles_pod_budget.html"
    tmp.write_text(MS.render_page(data, _tmp_template(src.replace(old, f"const CY_URL_MAX = {base['len'] - 1};"))), encoding="utf-8")
    ch.goto("file://" + str(tmp) + "#r=27.1&cy=DC1")
    kit.wait_ready(ch)
    small = ch.js(POD_PROBE)
    t.check(not small["link"] and small["s"] == base["s"] and small["v"] == base["v"] and small["btn"] and small["idle"] == base["idle"],
            f"over the budget the in-flight link must be plain text with the same number and the buttons kept: {base} -> {small}")


def _tmp_template(text: str) -> Path:
    p = Path(ctx.dir) / "cycles_budget_template.html"
    p.write_text(text, encoding="utf-8")
    return p


@SUITE.test("cycles_pods_tiles_equal_an_independent_recount_in_every_view")
def _(t: T):
    """Both Pods tiles, the two opened lists and the facts line of the detail views, against pod_oracle (Python, from the baked epics), in every view of the matrix."""
    r = full_sweep()
    t.check(not r["pod_bad"], f"{len(r['pod_bad'])} differences from the independent recount, e.g. {r['pod_bad'][:3]}")
    seen = r["pod_seen"]
    for k in ("views", "idle>0", "wip>0", "pods==0", "node_idle>0", "node_wip>0"):
        t.check(seen[k] > 0, f"the matrix never reached '{k}' (a blind recount): {dict(seen)}")
    t.note(f"{seen['views']} views recounted; idle>0 in {seen['idle>0']}, wip>0 in {seen['wip>0']}, no pods in {seen['pods==0']}; detail views: idle>0 {seen['node_idle>0']}, wip>0 {seen['node_wip>0']}")


@SUITE.test("cycles_the_seeded_pods_land_where_the_definitions_put_them")
def _(t: T):
    """Named cases of the variant payload (the recount above is general; this pins the owner's examples)."""
    data, url = page("variant")
    ch = ctx.chrome
    names = {}
    for cy in ("DC1", "DC2"):
        ch.goto(url + f"#r=27.1&cy={cy}")
        kit.wait_ready(ch)
        for kind in ("idle", "wip"):
            got = ch.js(PO.LIST_JS + f"({json.dumps(kind)})")
            names[cy, kind] = {(r["cells"][0], r["name"].lower()): r["cells"] for r in (got or {"rows": []})["rows"]}
    wip, idle1, idle2 = names["DC1", "wip"], names["DC2", "wip"], None
    over = {"pod-seed-four", "pod-seed-mix", "pod-seed-case", "pod-seed-twoa", "pod-seed-twob", "pod-21", "pod-22", "pod-23", "pod-24"}
    t.check(over <= {n for _, n in wip}, f"pods over the level missing from the list: {sorted(over - {n for _, n in wip})}")
    t.check(("PMN", "pod-seed-shared") in wip and ("CXCO", "pod-seed-shared") not in wip, "a label shared by two projects is over the level in PMN only (4 vs 2 epics)")
    t.check(not ({"pod-seed-three", "pod-seed-done", "pod-seed-late", "pod-seed-undated"} & {n for _, n in wip}), "exactly 3 epics in flight, only Done, outside the cycle and undated are not over the level")
    t.check(wip[("PMN", "pod-seed-case")][2] == "4" and wip[("PMN", "pod-seed-mix")][2] == "4", "case variants are one pod of 4; 3 In Progress + 1 Validation is 4 in flight")
    n1 = {n for _, n in names["DC1", "idle"]}
    n2 = {n for _, n in names["DC2", "idle"]}
    t.check({"pod-seed-late", "pod-seed-mix", "pod-seed-undated"} <= n1 and not ({"pod-seed-three", "pod-seed-four", "pod-seed-done", "pod-seed-shared", "pod-seed-case"} & n1), f"idle in Delivery Cycle 1: {sorted(n1)[:12]}")
    t.check({"pod-seed-three", "pod-seed-four", "pod-seed-done", "pod-seed-undated"} <= n2 and not ({"pod-seed-late", "pod-seed-mix"} & n2), f"idle in Delivery Cycle 2: {sorted(n2)[:12]}")
    ch.goto(url + "#r=27.1&cy=DC1")
    kit.wait_ready(ch)
    tile = ch.js(PO.POD_JS)["tiles"]["wip"]
    two = {e["k"] for e in data["epics"] if e.get("pl") and e["p"] == "PMN" and "27.1" in e["fv"] and set(e["pl"]) & {"Pod-Seed-TwoA", "Pod-Seed-TwoB"}}
    t.check(len(two) == 7, f"the seed: two pods share ONE epic that carries both labels (7 distinct epics), got {len(two)}")
    t.check(tile["btn"], "the tile value is a button")


@SUITE.test("cycles_the_overview_table_and_tiles_lost_the_removed_columns_and_tiles")
def _(t: T):
    data, url = page("variant")
    ch = ctx.chrome
    gone_text = ("Due So Far", "Due Epics Done", "Stale (More Than", "Open Bugs", "Carry-Over", "No Planned Date")
    for h in ("r=27.1&cy=DC1", "r=27.1&p=PMN&cy=DC2"):
        ch.goto(url + "#" + h)
        kit.wait_ready(ch)
        info = ch.js("""(() => { document.querySelector('[data-cyact="expall"]').click(); const th = [...document.querySelectorAll('#cy-ovtable thead th')].map(x => x.textContent.trim());
            const cols = r => r.children.length; return {th, rows: [...document.querySelectorAll('#cy-ovtable tbody tr, #cy-ovtable tfoot tr')].map(cols), cap: document.querySelector('#cy-ovtable caption').textContent,
            tiles: [...document.querySelectorAll('#cy-kpis1 .l, #cy-kpis2 .l')].map(x => x.textContent.trim()), sixCss: [...document.styleSheets].some(s => { try { return [...s.cssRules].some(r => /\.kpis\.six/.test(r.cssText)); } catch (e) { return false; } })}; })()""")
        t.check(info["th"] == ["Project, Team and Pod", "Teams or Pods", "Epics in Release", "Planned", "Done", "Overdue", "Due Next 7 Days"], f"{h}: the Overview columns are {info['th']}")
        t.check(all(n == len(info["th"]) for n in info["rows"]), f"{h}: a row has {set(info['rows'])} cells, the header {len(info['th'])}")
        t.check(not any(x in info["cap"] for x in ("due so far", "Due so far")), f"{h}: the table caption still names Due so far")
        t.check(not any(any(x in lab for x in gone_text) for lab in info["tiles"]), f"{h}: a removed tile is still shown: {info['tiles']}")
        t.check(not info["sixCss"], "a .kpis.six CSS rule is still in the page")


# --------------------------------------------------------------------------------------------- the suite must fail on a seeded defect
MUTANTS = [
    ("a due date on the end day is left out (<= becomes <)", '(duedate is EMPTY OR duedate <= "${hi}")', '(duedate is EMPTY OR duedate < "${hi}")'),
    ("a Target Sprint that ends after the window is no longer excluded", "(${CY_TS} is EMPTY OR ${CY_TS} not in (${after}))", "(${CY_TS} is EMPTY)"),
    ("'more than 3' becomes '3 or more'", "const wip = pods.filter(p => p.flight.length > CY.podWip);", "const wip = pods.filter(p => p.flight.length >= CY.podWip);"),
    ("in flight counted as In Progress only", "p.flight = p.epics.filter(e => CLASS.flight.includes(e.s));", 'p.flight = p.epics.filter(e => e.s === "In Progress");'),
    ("Idle Pods ignores the selected cycle", "p.planned = p.epics.filter(e => ps.has(e)).length;", "p.planned = p.epics.filter(e => e.due).length;"),
    ("the in-flight union link drops the project guard", "arg.map(p => `(${cyPodClause(p)})`).join(\" OR \")", "arg.map(p => `(labels in (${p.sp.map(q).join(\", \")}))`).join(\" OR \")"),
    ("a pod is counted per team instead of once", "const k = l.toLowerCase(), id = e.p + \"\\n\" + k; if (seen.has(id)) return; seen.add(id);", "const k = l.toLowerCase(), id = e.p + \"\\n\" + k + \"\\n\" + e.tm.join(); if (seen.has(id)) return; seen.add(id);"),
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
        caught = sum(r["bad"].values()) + len(r["dom_bad"]) + len(r["pod_bad"])
        t.check(caught > 0, f"the suite did not notice the seeded defect: {what}")


if __name__ == "__main__":
    sys.exit(kit.cli(SUITE, __doc__))
