#!/usr/bin/env python3
"""Capabilities Commitment Level oracle: the Commitment Level filter of the Capabilities section (hash `clx`, the levels switched OFF; `~notset` is Not Set).

Commitment Level is the Jira field `cf[10136]` of a Capability (a single select: any value, or empty). The filter narrows the Capabilities of Table A "Capability Status Summary" and, because Table B
counts the child epics of those Capabilities, Table B follows. It does not touch the missing-parent line (epics), the Done Capabilities per Release chart or the CXCROSS section.

An independent Python recount of both tables from the baked `capList` and `capEpics` (nothing of the page's code is reused) is compared with the page's cells in several selections (all ticked, one level,
two levels, only Not Set, none, and other releases and projects):

  * every cell of Table A and Table B, the heads (Other Status only when needed), the % Done cell, the sub line count and its two links, the Child Epics outside-projects link;
  * every link in the section is a query Jira recounts: it is evaluated with `jql_eval.py` over the baked Capabilities (and epics) and must return exactly the Capabilities (epics) of the cell. The Commitment
    Level clause is `cf[10136] in ("A", "B")`, with `OR cf[10136] is EMPTY` inside parentheses when Not Set is ticked, and absent when every level is ticked;
  * the chips (native checkboxes in one group, alphabetical, Not Set last and only when a Capability in view has none, the tooltip with the count), the empty state, the hash round trip (also an unknown
    value and Reset Filters), keyboard operation (Space toggles, focus stays on the chip, Tab moves on), no sideways scroll at 320 and 800 px;
  * the missing-parent line, Done Capabilities per Release and CXCROSS are identical in every selection.

Seeded defects (filter ignored in Table A, ignored in the link, Not Set dropped from the clause or from the choices, an OR clause without parentheses, Table B not following, the state not written to the
hash) must each be caught: a green oracle is not a blind one.

    python3 cap_oracle.py [--live] [--only NAME]
"""
from __future__ import annotations

import copy
import re
import sys
import time
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import jql_eval                                                                     # noqa: E402
import kit                                                                          # noqa: E402
import make_synthetic as MS                                                         # noqa: E402
from kit import ctx, T                                                              # noqa: E402

SUITE = kit.Suite("Delivery Pulse capabilities commitment level")
STATUSES = ["New", "In Definition", "Ready for Dev", "In Progress", "Done"]
NOT_STARTED = ["Candidate", "New", "In Definition", "Ready for Dev"]
URL_BUDGET = 6000
NONE_TOKEN = "~notset"
KEYRE = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")


# --------------------------------------------------------------------------------------------- the independent recount
class View:
    def __init__(self, rel: str = "27.1", projects=None, off=()):
        self.rel, self.projects, self.off = rel, projects, set(off)

    @property
    def hash(self) -> str:
        h = f"r={self.rel}"
        if self.projects:
            h += "&p=" + "|".join(self.projects)
        if self.off:
            h += "&clx=" + "|".join(NONE_TOKEN if x == "" else x for x in sorted(self.off, key=lambda x: (x == "", x)))
        return h

    def __repr__(self):
        return self.hash


def rnd(a: int, b: int) -> int:
    return int(100 * a / b + 0.5)                                                      # JS Math.round on a positive value


def recount(data: dict, v: View) -> dict:
    allp = data["projects"]
    sel = [p for p in allp if not v.projects or p in v.projects]
    caps_in_view = {k: c for k, c in data["capList"].items() if v.rel in c["fv"] and c["p"] in sel}
    levels = sorted({c.get("cl") or "" for c in caps_in_view.values()} - {""})
    choices = levels + ([""] if any(not (c.get("cl") or "") for c in caps_in_view.values()) else [])
    on = [x for x in choices if x not in v.off]
    caps = {k: c for k, c in caps_in_view.items() if (c.get("cl") or "") in on}
    other_st = any(c["s"] not in STATUSES for c in caps.values())
    cols = STATUSES + (["Other Status"] if other_st else [])

    def in_col(c, col):
        return c["s"] not in STATUSES if col == "Other Status" else c["s"] == col
    rows_a = []
    for p in sel + [None]:
        mine = {k for k, c in caps.items() if p is None or c["p"] == p}
        cells = [{k for k in mine if in_col(caps[k], col)} for col in cols] + [mine]
        rows_a.append({"label": p or "All Selected Projects (Each Capability Once)", "cells": cells})
    kids = [r for r in data["capEpics"] if r[5] in caps]

    def bst(r):
        return "ns" if r[2] in NOT_STARTED else "ip" if r[2] == "In Progress" else "val" if r[2] == "Validation" else "done" if r[2] == "Done" else "oth"
    has_oth = any(bst(r) == "oth" for r in kids)
    bcols = ["ns", "ip", "val", "done"] + (["oth"] if has_oth else [])
    by_p: dict = {}
    for r in kids:
        by_p.setdefault(r[1], []).append(r)
    order = [p for p in allp if p in by_p] + sorted(p for p in by_p if p not in allp)
    rows_b = []
    for p in order + [None]:
        mine = [r for r in kids if p is None or r[1] == p]
        done = sum(1 for r in mine if bst(r) == "done")
        rows_b.append({"label": p or "All Projects", "cells": [{r[0] for r in mine if bst(r) == c} for c in bcols] + [{r[0] for r in mine}],
                       "pct": (f"{rnd(done, len(mine))}%" if len(mine) >= 5 else "–")})
    return {"sel": sel, "caps_in_view": caps_in_view, "choices": choices, "on": on, "all_on": len(on) == len(choices), "caps": caps, "cols": cols, "rows_a": rows_a,
            "kids": kids, "bcols": bcols, "rows_b": rows_b, "outside": [r for r in kids if r[1] not in allp]}


def cap_issues(data: dict) -> list:
    return [{"key": k, "project": c["p"], "issuetype": "Capability", "status": c["s"], "fixversion": list(c["fv"]), "cf[10136]": c.get("cl") or None, "summary": "x", "labels": []}
            for k, c in data["capList"].items()]


def epic_issues(data: dict) -> list:
    return [{"key": r[0], "project": r[1], "issuetype": "Epic", "status": r[2], "parent": r[5], "summary": "x", "labels": []} for r in data["capEpics"]]


# --------------------------------------------------------------------------------------------- what the page prints
READ_JS = r"""(() => {
  const txt = e => (e ? e.textContent : '').replace(/\s+/g, ' ').trim();
  const cell = c => { const a = c.querySelector('a'); return {text: txt(c), href: a ? a.getAttribute('href') : null, tip: a ? (a.getAttribute('data-tip') || '') : ''}; };
  const tables = [...document.querySelectorAll('#capview table.captable')].map(tb => ({head: [...tb.tHead.rows[0].cells].map(txt),
    rows: [...tb.tBodies[0].rows].map(r => ({label: txt(r.cells[0]), cells: [...r.cells].slice(1).map(cell)}))}));
  const chips = [...document.querySelectorAll('#f-cl label.chip')].map(l => { const i = l.querySelector('input'); return {value: i.value, label: txt(l), checked: i.checked, on: l.classList.contains('on'), tip: l.getAttribute('data-tip') || '', type: i.type}; });
  const link = a => ({text: txt(a), href: a.getAttribute('href'), tip: a.getAttribute('data-tip') || ''});
  const blocks = [...document.querySelectorAll('#capview .cyblock')], g = document.getElementById('g-cl'), grp = document.getElementById('f-cl'), rs = document.getElementById('f-reset');
  const empty = document.querySelector('#capview .empty'), done = document.getElementById('capdone-data'), cx = document.getElementById('cx-body');
  return {tables, chips, sub: txt(document.getElementById('cap-sub')), subLinks: [...document.querySelectorAll('#cap-sub a')].map(link), empty: empty ? txt(empty) : null,
    outsideLinks: blocks[1] ? [...blocks[1].querySelectorAll('.cymeta a')].map(link) : [], dq: txt(document.getElementById('cap-dq')), defs: txt(document.getElementById('cap-cap')),
    done: done ? txt(done) : '', cx: cx ? txt(cx) : '', hash: location.hash, group: grp ? grp.getAttribute('role') : null, label: txt(document.getElementById('lbl-cl')), hint: txt(g.querySelector('.hintline')),
    changed: g.classList.contains('changed'), reset: rs ? txt(rs) : '', resetOff: rs ? rs.disabled : null, h2: txt(document.getElementById('h-capview'))};
})()"""


def load(url: str, hash_: str) -> dict:
    ch = ctx.chrome
    ch.goto(url + "#" + hash_)
    kit.wait_ready(ch)
    page = ch.js(READ_JS)
    page["console"] = ch.console_errors()
    return page


def jql_of(href: str) -> str:
    return urllib.parse.parse_qs(urllib.parse.urlsplit(href).query).get("jql", [""])[0]


def evaluate(href: str, issues: list) -> set:
    tree = jql_eval.parse(jql_of(href))
    return {i["key"] for i in issues if jql_eval.evaluate(tree, i)}


def check_cells(tag: str, table: dict, rows: list, heads: list, issues: list, bad: list, all_on: bool, level_clause: bool):
    if table["head"] != heads:
        bad.append(f"{tag} heads {table['head']}, expected {heads}")
    if [r["label"] for r in table["rows"]] != [r["label"] for r in rows]:
        bad.append(f"{tag} rows {[r['label'] for r in table['rows']]}, expected {[r['label'] for r in rows]}")
        return
    for pr, er in zip(table["rows"], rows):
        for ci, (c, keys) in enumerate(zip(pr["cells"], er["cells"])):
            where = f"{tag} {er['label']} / {heads[ci + 1] if ci + 1 < len(heads) else '?'}"
            if c["text"] != f"{len(keys):,}":
                bad.append(f"{where} prints '{c['text']}', the recount is {len(keys)}")
                continue
            if not keys:
                if c["href"]:
                    bad.append(f"{where} is 0 but a link")
                continue
            if not c["href"]:
                bad.append(f"{where} has {len(keys)} but no link")
                continue
            if len(c["href"]) > URL_BUDGET:
                bad.append(f"{where} link is {len(c['href'])} characters")
            jql = jql_of(c["href"])
            if level_clause and (("10136" in jql) == all_on):
                bad.append(f"{where} link {'has' if all_on else 'lacks'} a Commitment Level clause: {jql[:200]}")
            try:
                got = evaluate(c["href"], issues)
            except (jql_eval.Malformed, jql_eval.Unsupported) as e:
                bad.append(f"{where} query cannot be evaluated: {e}: {jql[:200]}")
                continue
            if got != keys:
                bad.append(f"{where} query returns {len(got)}, the cell counts {len(keys)}; extra {sorted(got - keys)[:3]} missing {sorted(keys - got)[:3]}: {jql[:220]}")


def check_view(page: dict, R: dict, v: View, data: dict, base: dict | None = None) -> list[str]:
    bad: list[str] = []
    tag = f"[{v.hash}]"
    if page["console"]:
        return [f"{tag} console errors {page['console'][:2]}"]
    caps, kids = R["caps"], R["kids"]
    # ---- the chips
    want = R["choices"]
    got = [c["value"] for c in page["chips"]]
    if got != [NONE_TOKEN if x == "" else x for x in want]:
        bad.append(f"{tag} chips {got}, expected {want} (alphabetical, Not Set last)")
    else:
        for c, lvl in zip(page["chips"], want):
            n = sum(1 for k in R["caps_in_view"].values() if (k.get("cl") or "") == lvl)
            if c["checked"] != (lvl in R["on"]) or c["on"] != c["checked"] or c["type"] != "checkbox":
                bad.append(f"{tag} chip {lvl or 'Not Set'}: checked {c['checked']}, on {c['on']}, expected {lvl in R['on']}")
            exp = f"{n} {'Capability' if n == 1 else 'Capabilities'} " + ("with no Commitment Level" if lvl == "" else f"with Commitment Level {lvl}")
            if c["tip"].split("\n")[0] != exp:
                bad.append(f"{tag} chip {lvl or 'Not Set'} tooltip '{c['tip'].split(chr(10))[0]}', expected '{exp}'")
            if c["label"] != (lvl or "Not Set"):
                bad.append(f"{tag} chip label '{c['label']}'")
    if page["changed"] != any(x in v.off for x in want):
        bad.append(f"{tag} the control is marked changed={page['changed']}")
    # ---- the sub line
    sub = page["sub"]
    if not caps and not R["caps_in_view"]:
        pass
    n, m = len(caps), len(kids)
    exp_head = f"{n} {'Capability carries' if n == 1 else 'Capabilities carry'} fix version {v.rel}, with {m:,} child {'epic' if m == 1 else 'epics'} under {'it' if n == 1 else 'them'}."
    if not sub.startswith(exp_head) or "Follows: Release · Projects · Commitment Level" not in sub:
        bad.append(f"{tag} sub line '{sub[:200]}', expected to start '{exp_head}' and follow Release, Projects and Commitment Level")
    issues_c = cap_issues(data)
    if n:
        if len(page["subLinks"]) != 2 and m:
            bad.append(f"{tag} the sub line has {len(page['subLinks'])} links")
        else:
            a = page["subLinks"][0]
            if a["text"] != str(n) or not a["href"] or evaluate(a["href"], issues_c) != set(caps):
                bad.append(f"{tag} the sub line Capability link {a['text']} does not return the {n} Capabilities")
            if a["href"] and (("10136" in jql_of(a["href"])) == R["all_on"]):
                bad.append(f"{tag} the sub line link {'has' if R['all_on'] else 'lacks'} a Commitment Level clause")
            if m:
                b = page["subLinks"][1]
                if b["text"] != f"{m:,}" or not b["href"] or evaluate(b["href"], epic_issues(data)) != {r[0] for r in kids}:
                    bad.append(f"{tag} the sub line child epic link {b['text']} does not return the {m} child epics")
    elif page["subLinks"]:
        bad.append(f"{tag} links in the sub line with no Capability")
    # ---- the tables, or the empty state
    if not caps:
        if page["tables"] or not page["empty"]:
            bad.append(f"{tag} no Capability but {len(page['tables'])} tables / empty {page['empty']}")
        if R["caps_in_view"] and not (page["empty"] and page["empty"].startswith("No Commitment Level is selected.")):
            bad.append(f"{tag} nothing ticked but the empty text is '{page['empty']}'")
    else:
        if len(page["tables"]) != 2 or page["empty"]:
            bad.append(f"{tag} expected two tables, got {len(page['tables'])} (empty '{page['empty']}')")
        else:
            check_cells(f"{tag} A", page["tables"][0], R["rows_a"], ["Project"] + R["cols"] + ["Total"], issues_c, bad, R["all_on"], True)
            bnames = {"ns": "Not Started", "ip": "In Progress", "val": "Validation", "done": "Done", "oth": "Other Status"}
            tb = page["tables"][1]
            check_cells(f"{tag} B", {"head": tb["head"][:-1], "rows": [{"label": r["label"], "cells": r["cells"][:-1]} for r in tb["rows"]]}, R["rows_b"],
                        ["Project"] + [bnames[c] for c in R["bcols"]] + ["Total"], epic_issues(data), bad, True, False)
            for pr, er in zip(tb["rows"], R["rows_b"]):
                if pr["cells"] and pr["cells"][-1]["text"] != er["pct"]:
                    bad.append(f"{tag} B {er['label']} % Done '{pr['cells'][-1]['text']}', expected '{er['pct']}'")
            outside = R["outside"]
            ol = [a for a in page["outsideLinks"] if "child epics in other projects" in a["tip"]]
            if bool(outside) != bool(ol) or (outside and (ol[0]["text"] != str(len(outside)) or evaluate(ol[0]["href"], epic_issues(data)) != {r[0] for r in outside})):
                bad.append(f"{tag} the outside-projects link {[a['text'] for a in ol]}, expected {len(outside)}")
    # ---- what must not move with the filter
    if base is not None:
        for k in ("dq", "done", "cx"):
            if page[k] != base[k]:
                bad.append(f"{tag} '{k}' changed with the Commitment Level filter")
    return bad


# --------------------------------------------------------------------------------------------- the fixture and the views
_cache: dict = {}


def fixture() -> dict:
    if not _cache:
        data = MS.make(MS.il_today())
        _cache.update(data=data, url=ctx.write(kit.fragment_for(data), "cap"))
    return _cache


def levels_of(data: dict, rel: str = MS.CURRENT) -> list:
    return recount(data, View(rel))["choices"]


def views(data: dict) -> list[View]:
    lv = levels_of(data)
    assert lv[:3] == ["Committed", "Stretch", "Target"] and lv[3:] == [""], f"the fixture's levels changed: {lv}"
    return [View(), View(off={"Stretch", "Target", ""}), View(off={"Target", ""}), View(off={"Committed", "Stretch", "Target"}), View(off=set(lv)), View(off={"Committed", "Stretch"}),
            View(off={"Stretch"}), View(projects=["EXA", "PMN"], off={"Committed"}), View(rel="26.4", off={""}), View(rel="27.2", off={"Stretch"}), View(rel="27.2", projects=["PMN"], off=set(levels_of(data, "27.2")))]


def run_views(url: str, data: dict, vs: list[View]) -> list[str]:
    bad: list[str] = []
    bases: dict = {}
    for v in vs:
        key = (v.rel, tuple(v.projects or ()))
        if key not in bases:
            bases[key] = load(url, View(v.rel, v.projects).hash)
        page = load(url, v.hash)
        bad += check_view(page, recount(data, v), v, data, bases[key])
    return bad


# --------------------------------------------------------------------------------------------- tests
@SUITE.test("capcl_the_fixture_has_a_spread_of_levels_and_every_project_sees_them")
def _(t: T):
    F = fixture()
    data = F["data"]
    R = recount(data, View())
    t.check(R["choices"] == ["Committed", "Stretch", "Target", ""], f"choices {R['choices']}")
    t.check(all(sum(1 for c in R["caps"].values() if (c.get("cl") or "") == lv) >= 2 for lv in R["choices"]), "every level has at least two Capabilities in release 27.1")
    t.check(any(recount(data, View(projects=[p]))["choices"] != R["choices"] for p in R["sel"]), "a single project offers fewer levels than all projects (the choices follow the view)")
    t.note("27.1 levels: " + ", ".join(f"{lv or 'Not Set'} {sum(1 for c in R['caps'].values() if (c.get('cl') or '') == lv)}" for lv in R["choices"]) + f"; {len(R['caps'])} Capabilities, {len(R['kids'])} child epics")


@SUITE.test("capcl_tables_links_and_chips_equal_an_independent_recount")
def _(t: T):
    F = fixture()
    vs = views(F["data"])
    bad = run_views(F["url"], F["data"], vs)
    for b in bad[:12]:
        t.failures.append(b)
    t.passed += 0 if bad else 1
    t.note(f"{len(vs)} views compared: all ticked, one level, two levels, only Not Set, none, other releases and projects")


@SUITE.test("capcl_the_clause_is_in_the_link_and_parenthesised_exactly_as_the_rule_says")
def _(t: T):
    F = fixture()
    ch = ctx.chrome
    jqls = lambda page: [jql_of(c["href"]) for r in page["tables"][0]["rows"] for c in r["cells"] if c["href"]] + [jql_of(a["href"]) for a in page["subLinks"] if a["href"]]
    page = load(F["url"], View().hash)
    t.check(jqls(page) and not any("10136" in j for j in jqls(page)), "every level ticked: no clause at all")
    page = load(F["url"], View(off={"Stretch", "Target"}).hash)
    js = [j for j in jqls(page) if "10136" in j]
    t.check(js and all(re.search(r'AND \(cf\[10136\] in \("Committed"\) OR cf\[10136\] is EMPTY\)', j) for j in js), f"Committed + Not Set: {js[:1]}")
    page = load(F["url"], View(off={"Target", ""}).hash)
    js = [j for j in jqls(page) if "10136" in j]
    t.check(js and all(re.search(r'AND cf\[10136\] in \("Committed", "Stretch"\)(?! OR)', j) and "EMPTY" not in j.split("10136")[-1] for j in js), f"two levels: {js[:1]}")
    page = load(F["url"], View(off={"Committed", "Stretch", "Target"}).hash)
    js = [j for j in jqls(page) if "10136" in j]
    t.check(js and all(re.search(r"AND cf\[10136\] is EMPTY", j) and " in (" not in j.split("10136")[-1] for j in js), f"only Not Set: {js[:1]}")
    t.check(ch.js("!!document.querySelector('#capview .captable')") is True, "the table is drawn")


@SUITE.test("capcl_when_no_capability_lacks_a_level_there_is_no_not_set_choice_and_the_clause_follows")
def _(t: T):
    F = fixture()
    data = copy.deepcopy(F["data"])
    for k, c in data["capList"].items():
        if not c.get("cl"):
            c["cl"] = "Committed"
    url = ctx.write(kit.fragment_for(data), "capfull")
    R = recount(data, View())
    t.check(R["choices"] == ["Committed", "Stretch", "Target"], f"choices {R['choices']}")
    for v in (View(), View(off={"Stretch"}), View(off={"Stretch", "Target"}), View(off={"Committed", "Stretch", "Target"})):
        bad = check_view(load(url, v.hash), recount(data, v), v, data)
        t.check(not bad, f"{v}: {bad[:3]}")
    page = load(url, View().hash)
    t.check(not any(c["value"] == NONE_TOKEN for c in page["chips"]), "no Not Set chip")
    t.check(not any("10136" in (c["href"] or "") for r in page["tables"][0]["rows"] for c in r["cells"]) and "EMPTY" not in "".join(c["href"] or "" for r in page["tables"][0]["rows"] for c in r["cells"]), "all ticked: no clause")
    page = load(url, View(off={"Stretch"}).hash)
    t.check(all("EMPTY" not in jql_of(c["href"]) for r in page["tables"][0]["rows"] for c in r["cells"] if c["href"]), "a partial selection never adds the EMPTY branch when no Capability is empty")
    page = load(url, "r=27.1&clx=" + NONE_TOKEN)
    t.check(not page["console"] and all(c["checked"] for c in page["chips"]), "~notset in a view that has no empty level is ignored")


@SUITE.test("capcl_the_empty_state_names_the_filter_and_the_other_filters_still_apply")
def _(t: T):
    F = fixture()
    v = View(off=set(levels_of(F["data"])))
    page = load(F["url"], v.hash)
    t.check(page["empty"] == "No Commitment Level is selected. Choose at least one in the Capabilities filter above the tables.", f"empty text '{page['empty']}'")
    t.check(not page["tables"] and not page["console"], f"tables {len(page['tables'])}, console {page['console'][:1]}")
    t.check(all(not c["checked"] and not c["on"] for c in page["chips"]) and len(page["chips"]) == 4, "all four chips are unticked and still offered")
    t.check(page["dq"], "the missing-parent line is still shown")


@SUITE.test("capcl_the_control_is_a_native_checkbox_group_in_title_case_and_the_hash_round_trips")
def _(t: T):
    F = fixture()
    ch = ctx.chrome
    page = load(F["url"], "r=27.1")
    t.check(page["group"] == "group" and page["label"] == "Commitment Level", f"group {page['group']}, label '{page['label']}'")
    t.check(page["hint"] == "Filters the Capabilities in this section only.", f"hint '{page['hint']}'")
    t.check(all(c["checked"] for c in page["chips"]) and len(page["chips"]) == 4, "the default has every level ticked")
    t.check("clx" not in page["hash"] and not page["changed"] and page["reset"] == "Reset Filters" and page["resetOff"], f"default hash '{page['hash']}', reset '{page['reset']}'")
    t.check(page["h2"] == "Capabilities by Status", "the heading is unchanged")
    click = "(() => { const i = [...document.querySelectorAll('#f-cl input')].find(x => x.value === %s); i.click(); return location.hash; })()"
    ch.js(click % '"Stretch"')
    time.sleep(0.25)
    h = ch.js("location.hash")
    t.check("clx=Stretch" in h, f"unticking Stretch writes clx=Stretch: {h}")
    ch.js(click % f'"{NONE_TOKEN}"')
    time.sleep(0.25)
    h = ch.js("location.hash")
    t.check(re.search(r"clx=Stretch(\||%7C)(~|%7E)notset", h) is not None, f"unticking Not Set adds ~notset: {h}")
    page = ch.js(READ_JS)
    t.check(page["reset"] == "Reset Filters (1)" and page["changed"], f"the active-filter indicator: '{page['reset']}', changed {page['changed']}")
    R = recount(F["data"], View(off={"Stretch", ""}))
    bad = check_view(dict(page, console=[]), R, View(off={"Stretch", ""}), F["data"])
    t.check(not bad, f"the page after two clicks: {bad[:2]}")
    page = load(F["url"], h.lstrip("#"))
    t.check({c["value"]: c["checked"] for c in page["chips"]} == {"Committed": True, "Stretch": False, "Target": True, NONE_TOKEN: False}, f"the hash restores the state: {[(c['value'], c['checked']) for c in page['chips']]}")
    ch.js("document.getElementById('f-reset').click()")
    time.sleep(0.25)
    page = ch.js(READ_JS)
    t.check("clx" not in page["hash"] and all(c["checked"] for c in page["chips"]) and page["reset"] == "Reset Filters", f"Reset Filters restores every level: '{page['hash']}'")
    ch.js(click % '"Target"')
    time.sleep(0.25)
    ch.js(click % '"Target"')
    time.sleep(0.25)
    t.check("clx" not in ch.js("location.hash"), "ticking the level again leaves the address clean")
    page = load(F["url"], "r=27.1&clx=Bogus|Stretch")
    t.check(not page["console"] and {c["value"]: c["checked"] for c in page["chips"]}["Stretch"] is False and all(c["checked"] for c in page["chips"] if c["value"] != "Stretch"), "an unknown level in the address is ignored, a known one kept")
    t.check("Bogus" not in ch.js("location.hash"), "and it is dropped from the address")
    page = load(F["url"], "r=27.1&clx=Bogus")
    t.check(all(c["checked"] for c in page["chips"]) and "clx" not in page["hash"], "only unknown levels: the default view")
    page = load(F["url"], "r=27.1&clx=Stretch&p=PMN|CXCO&c=Committed")
    t.check(page["hash"].count("clx=Stretch") == 1 and "c=Committed" in page["hash"], f"it lives with the other filters in one address: {page['hash']}")


@SUITE.test("capcl_the_chips_work_from_the_keyboard_and_focus_stays_on_the_chip")
def _(t: T):
    F = fixture()
    ch = ctx.chrome
    load(F["url"], "r=27.1")
    key = lambda k, code, vk, text="": (ch.cmd("Input.dispatchKeyEvent", type="keyDown", key=k, code=code, windowsVirtualKeyCode=vk, **({"text": text} if text else {})),
                                         ch.cmd("Input.dispatchKeyEvent", type="keyUp", key=k, code=code, windowsVirtualKeyCode=vk))
    ch.js("document.querySelector('#f-cl input').focus()")
    state = lambda: ch.js("(() => { const a = document.activeElement; return {v: a && a.value, in_: !!(a && a.closest('#f-cl')), hash: location.hash, checked: [...document.querySelectorAll('#f-cl input')].map(i => i.checked)}; })()")
    s = state()
    t.check(s["in_"] and s["v"] == "Committed", f"the first chip takes focus: {s}")
    key(" ", "Space", 32, " ")
    time.sleep(0.3)
    s = state()
    t.check(s["checked"] == [False, True, True, True] and "clx=Committed" in s["hash"], f"Space unticks the focused level: {s}")
    t.check(s["in_"] and s["v"] == "Committed", f"focus stays on the chip after the page redraws: {s}")
    key("Tab", "Tab", 9)
    time.sleep(0.15)
    s = state()
    t.check(s["in_"] and s["v"] == "Stretch", f"Tab moves to the next chip: {s}")
    key(" ", "Space", 32, " ")
    time.sleep(0.3)
    s = state()
    t.check(s["checked"] == [False, False, True, True], f"Space unticks the second: {s}")
    ch.js("document.querySelectorAll('#f-cl input')[0].focus()")
    key(" ", "Space", 32, " ")
    time.sleep(0.3)
    s = state()
    t.check(s["checked"] == [True, False, True, True] and "clx=Stretch" in s["hash"] and "Committed" not in s["hash"], f"Space ticks it again: {s}")
    t.check(ch.js("document.querySelector('#f-cl input').closest('label').matches(':focus-within')") is True, "the chip shows the focus ring through :focus-within")
    t.check(ch.js("(() => { const i = document.querySelector('#f-cl input'); return getComputedStyle(i).position === 'absolute' && !i.hidden && i.type === 'checkbox'; })()") is True, "the checkbox is a real input (screen readers see it), only visually folded into the chip")


@SUITE.test("capcl_320px_and_800px_chips_wrap_and_the_page_does_not_scroll_sideways")
def _(t: T):
    F = fixture()
    ch = ctx.chrome
    try:
        for w in (320, 800):
            ch.viewport(w, 900, mobile=False)
            for h in (View().hash, View(off={"Stretch"}).hash):
                load(F["url"], h)
                m = ch.js("(() => { const cs = [...document.querySelectorAll('#f-cl .chip')]; return {sw: document.documentElement.scrollWidth, w: window.innerWidth, right: Math.max(...cs.map(c => c.getBoundingClientRect().right)), left: Math.min(...cs.map(c => c.getBoundingClientRect().left)), rows: new Set(cs.map(c => Math.round(c.getBoundingClientRect().top))).size}; })()")
                t.check(m["sw"] <= m["w"], f"{w} px {h}: the page scrolls sideways ({m})")
                t.check(m["right"] <= m["w"] + 1 and m["left"] >= -1, f"{w} px {h}: a chip leaves the viewport ({m})")
                if w == 320:
                    t.check(m["rows"] >= 2, f"{w} px: the four chips fit on one row ({m})")
    finally:
        ch.viewport(1400, 900)


@SUITE.test("capcl_the_how_this_is_calculated_text_names_the_filter_and_what_does_not_apply")
def _(t: T):
    F = fixture()
    page = load(F["url"], "r=27.1")
    d = page["defs"]
    t.check("Commitment Level: the Jira field of that name on a Capability" in d and "Not Set means the field is empty" in d, f"definition missing: {d[:300]}")
    t.check("Teams and the Commitment Type in the filter bar do not apply to Capabilities" in d, "the Teams / Commitment Type sentence is missing")
    t.check("the Commitment Level filter above them" in d and "Child Epics follow it" in d, "the filter is not named in the Know line")
    t.check("a Capability has neither" not in d and "Teams and Commitment Type do not apply" not in d, "the old sentence is still there")
    t.check("ignores Commitment Level, because it counts epics" in d, "the missing-parent line sentence is missing")


@SUITE.test("capcl_a_refresh_keeps_the_level_current_and_reads_the_field")
def _(t: T):
    src = ctx.template.read_text(encoding="utf-8")
    t.check('"parent", "customfield_10136"]' in src, "the Capability refresh does not request customfield_10136")
    t.check(src.count("(old.cl || \"\") === cl") == 1 and "fv, cl};" in src, "the refresh does not rebuild cl / treat a changed cl as a change")


# --------------------------------------------------------------------------------------------- seeded defects
def _mutant(src: str, old: str, new: str, name: str) -> Path:
    assert src.count(old) == 1, f"the seeding anchor for '{name}' is not in the template exactly once (found {src.count(old)}): the mutation test would be blind"
    p = Path(ctx.dir) / f"cap_mutant_{name}.html"
    p.write_text(src.replace(old, new, 1), encoding="utf-8")
    return p


def _caught(src: str, old: str, new: str, name: str, extra=None) -> list[str]:
    F = fixture()
    p = _mutant(src, old, new, name)
    saved = ctx.template
    ctx.template = p
    try:
        url = ctx.write(kit.fragment_for(F["data"]), "capmut")
        vs = [View(off={"Stretch", "Target"}), View(off={"Committed", "Stretch", "Target"}), View(off={"Target", ""}), View(off=set(levels_of(F["data"])))]
        bad = run_views(url, F["data"], vs)
        if extra:
            bad += extra(url)
        return bad
    finally:
        ctx.template = saved


def _hash_defect(url: str) -> list[str]:
    ch = ctx.chrome
    load(url, "r=27.1")
    ch.js("[...document.querySelectorAll('#f-cl input')].find(x => x.value === 'Stretch').click()")
    time.sleep(0.25)
    h = ch.js("location.hash")
    return [] if "clx=Stretch" in h else [f"the state is not in the address: {h}"]


SEEDS = [
    ("filter_ignored_in_table_a", "caps.filter(c => c.p === p), [p], false)", "capsAll.filter(c => c.p === p), [p], false)", None),
    ("filter_ignored_in_the_link", '${lv.clause ? " AND " + lv.clause : ""}`;', '`;', None),
    ("not_set_dropped_from_the_clause", 'if (on.has("")) parts.push("cf[10136] is EMPTY");', "", None),
    ("not_set_dropped_from_the_choices", "const vals = [...new Set(list.map(c => c.cl || \"\"))]", "const vals = [...new Set(list.map(c => c.cl || \"\"))].filter(v => v !== \"\")", None),
    ("or_clause_without_parentheses", 'parts.length > 1 ? `(${parts.join(" OR ")})` : parts[0] || ""', 'parts.join(" OR ")', None),
    ("table_b_does_not_follow", "const inSet = new Set(capKeys), kids", "const inSet = new Set(capsAll.map(c => c.k)), kids", None),
    ("state_not_written_to_the_address", 'if (state.capLvlOff.size) h.set("clx",', 'if (false) h.set("clx",', _hash_defect),
    ("level_label_dropped", "${esc(clLabel(v))}</label>", "</label>", None),
]


def _seed_test(name: str, old: str, new: str, extra):
    @SUITE.test(f"capcl_seeded_defect_is_caught_{name}")
    def _(t: T):
        src = ctx.template.read_text(encoding="utf-8")
        bad = _caught(src, old, new, name, extra)
        t.check(bool(bad), f"the seeded defect '{name}' was not caught by the recount")
        t.note(f"caught: {bad[0][:170] if bad else ''}")


for _n, _o, _w, _x in SEEDS:
    _seed_test(_n, _o, _w, _x)


if __name__ == "__main__":
    sys.exit(kit.cli(SUITE, __doc__))
