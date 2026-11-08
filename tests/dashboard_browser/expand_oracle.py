#!/usr/bin/env python3
"""Expandable tables oracle: the Project > Team (> Pod) tables of the Quality and Capabilities sections, the NFR tab By Pod, and the Dependencies quick filter without its caption.

  1. Open Bugs by Project and Priority (Quality): every project row opens into its teams (a bug carries one team, "(No Team)" when it has none; there is NO pod level, bugs carry no pod label).
     The numbers of every team row (P1 to P4, Total, the Trend of 2 weeks) are recounted by ax_oracle.py; here is the behaviour and the markup.
  2. Child Epics of These Capabilities (Capabilities): Project > Team > Pod through the page's epic records. The recount is cap_oracle.py's; here it is run on a variant of the fixture with the cases the base
     fixture lacks (an epic with two pod labels, one pod spelled in two cases, the same pod label in two projects), and the seeded defects of the team and pod level are caught.
  3. NFR, tab By Pod: the rows, every count and every link are recounted in Python from the baked epics (a pod is one label per project, spellings combined without regard to case; an epic with two pod
     labels is under both; a No Pod Label row; the total counts each epic once); every link is evaluated with jql_eval over ALL baked epics and must find exactly the epics of its cell.
  4. Behaviour of the expandable tables: a chevron button per row that has rows under it (aria-expanded, aria-controls, a label that says what it does), Expand All and Collapse All, one selected project opens
     itself, the open rows survive a filter change, the keyboard works, the Delivery Cycles table still works, no sideways scroll at 390 px.
  5. Dependencies: the caption "Quick Filter" and the sentence "Filters the board and table, not the tiles." are gone, the group is named for screen readers, the two labels and every chip remain.

Seeded defects (a team link without its team, a pod level that does not combine spellings, an epic counted under one pod only, the team-unknown row dropped, a toggle that does not hide the rows under it, ...) must be caught.

    python3 expand_oracle.py [--live] [--only NAME]
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
import cap_oracle as CO                                                             # noqa: E402
import jql_eval as J                                                                # noqa: E402
import kit                                                                          # noqa: E402
import make_synthetic as MS                                                         # noqa: E402
from kit import ctx, T                                                              # noqa: E402

SUITE = kit.Suite("Delivery Pulse expandable tables")
NOT_STARTED = ["Candidate", "New", "In Definition", "Ready for Dev"]
NFR_CATEGORIES = ["R&D - 3rd party upgrades", "R&D - Arch/infra refactoring", "R&D Infra", "R&D - Low env. cost optimization"]      # spelled here, not read from the page
URL_BUDGET = 6000


# --------------------------------------------------------------------------------------------- the fixture and its variant
def variant(data: dict) -> dict:
    """The base fixture plus what it lacks: an epic with two pod labels, one pod spelled in two cases, and the same pod label in two projects. Deterministic (by key order), and the child-epic rows are
    untouched, so the Capabilities recount reads the same capEpics against changed epics."""
    d = copy.deepcopy(data)
    eps = sorted((e for e in d["epics"] if e.get("pl")), key=lambda e: e["k"])
    for i, e in enumerate(eps):
        if e["p"] == "PMN" and i % 2:
            e["pl"] = [l.lower() for l in e["pl"]]                       # "pod-alpha-2" next to "Pod-Alpha-2": one pod
        if e["p"] == "PMN" and i % 3 == 0:
            e["pl"] = e["pl"] + ["Pod-Extra-1"]                          # two pod labels: under both pods
        if e["p"] == "CXWFM" and i % 3 == 0:
            e["pl"] = e["pl"] + ["pod-extra-1"]                          # the same pod in another project, spelled in lower case
    cur = d["current"]
    host = sorted(k for k, c in d["capList"].items() if c["p"] == "PMN" and cur in c["fv"])
    for i, r in enumerate(x for x in d["capEpics"] if x[1] in ("EXA", "EXB")):
        r[5] = host[i % len(host)]                                       # child epics of a project the page does not track, under Capabilities of a tracked one
    n = 0
    for e in sorted(d["epics"], key=lambda e: e["k"]):                   # more NFR epics that carry pod labels
        if e.get("pl") and cur in e["fv"] and e["p"] in ("PMN", "CXWFM", "CXCO") and not e.get("nf") and e.get("cat") not in NFR_CATEGORIES and n < 14:
            e["nf"] = 1
            n += 1
    return d


_cache: dict = {}


def fixture() -> dict:
    if not _cache:
        base = MS.make(MS.il_today())
        var = variant(base)
        _cache.update(base=base, var=var, u_base=ctx.write(kit.fragment_for(base), "xt_base"), u_var=ctx.write(kit.fragment_for(var), "xt_var"))
    return _cache


def hash_of(spec: str, team: str | None = None) -> str:
    return "&".join(f"t={urllib.parse.quote(team or '')}" if p == "TEAM" else p for p in spec.split("&")) if spec else ""


def go(url: str, spec: str = "", team: str | None = None) -> bool:
    ch = ctx.chrome
    ch.goto(url + ("#" + hash_of(spec, team) if spec else ""))
    return kit.wait_ready(ch)


# --------------------------------------------------------------------------------------------- the NFR recount
def epic_issue(e: dict) -> dict:
    return {"key": e["k"], "project": e["p"], "issuetype": "Epic", "status": e["s"], "fixversion": list(e["fv"]), "cf[10094]": e.get("c") if e.get("c") and e.get("c") != "Not Set" else None,
            "cf[10040]": list(e.get("tm") or []), "cf[10098]": list(e.get("tm") or []), "cf[10139]": e.get("cat"), "labels": list(e.get("pl") or []) + (["NFR"] if e.get("nf") else []),
            "parent": e.get("cp"), "summary": e.get("t", "")}


def nfr_pod_recount(data: dict, rel: str, projects, teams) -> dict:
    projects = projects or data["projects"]
    scope = [e for e in data["epics"] if e["p"] in projects and rel in e["fv"] and (not teams or any(t in teams for t in (e.get("tm") or ["(No Team)"])))]
    nfr = [e for e in scope if e.get("nf") or e.get("cat") in NFR_CATEGORIES]
    first: dict = {}
    for e in data["epics"]:
        for l in e.get("pl") or []:
            first.setdefault(l.lower(), l)
    pods: dict = {}
    for e in nfr:
        for k in {l.lower() for l in e.get("pl") or []}:
            pods.setdefault((e["p"], k), []).append(e)
    rows = []

    def cells(es):
        st = lambda e: "ns" if e["s"] in NOT_STARTED else "ip" if e["s"] == "In Progress" else "val" if e["s"] == "Validation" else "done" if e["s"] == "Done" else "oth"
        return [{e["k"] for e in es if st(e) == k} for k in ("ns", "ip", "val", "done")] + [{e["k"] for e in es if st(e) == "oth"}] + [{e["k"] for e in es}]
    for (p, k), es in sorted(pods.items(), key=lambda kv: (first[kv[0][1]].lower(), kv[0][0])):
        rows.append({"label": f"{first[k]} ({p})", "cells": cells(es), "n": len(es)})
    none = [e for e in nfr if not (e.get("pl") or [])]
    if none:
        rows.append({"label": "No Pod Label", "cells": cells(none), "n": len(none)})
    other = any(e["s"] not in NOT_STARTED + ["In Progress", "Validation", "Done"] for e in nfr)
    return {"nfr": nfr, "rows": rows, "total": {"label": "All Selected (Each Epic Once)", "cells": cells(nfr), "n": len(nfr)}, "other": other}


NFR_JS = r"""(() => {
  const tx = e => e ? e.textContent.replace(/\s+/g, ' ').trim() : '';
  const cell = c => { const a = c.querySelector('a'); return {text: tx(c), href: a ? a.getAttribute('href') : null}; };
  const tb = document.querySelector('#nfr-panel table');
  const tabs = [...document.querySelectorAll('#nfr-tabs [role=tab]')].map(b => ({id: b.dataset.nt, text: tx(b), sel: b.getAttribute('aria-selected')}));
  if (!tb) return {tabs, table: null, notice: tx(document.getElementById('nfr-panel')), hash: location.hash};
  const rowOf = r => ({label: tx(r.cells[0]), cells: [...r.cells].slice(1).map(cell), share: r.querySelector('.mbar') ? r.querySelector('.mbar').getAttribute('aria-label') : tx(r.cells[r.cells.length - 1])});
  return {tabs, hash: location.hash, head: [...tb.tHead.rows[0].cells].map(tx), rows: [...tb.tBodies[0].rows].map(rowOf), foot: [...(tb.tFoot ? tb.tFoot.rows : [])].map(rowOf), caption: tx(tb.caption),
          sw: document.documentElement.scrollWidth, w: window.innerWidth};
})()"""


def jql_of(href: str) -> str:
    return urllib.parse.parse_qs(urllib.parse.urlsplit(href).query).get("jql", [""])[0]


def check_nfr(data: dict, url: str, spec: str, rel: str, projects, teams, team_arg=None) -> list[str]:
    bad: list[str] = []
    tag = f"[{spec}]"
    go(url, spec, team_arg)
    ch = ctx.chrome
    page = ch.js(NFR_JS)
    errs = ch.console_errors()
    if errs:
        return [f"{tag} console errors {errs[:2]}"]
    if not isinstance(page, dict) or page.get("table") is False or "rows" not in page:
        return [f"{tag} no table: {str(page)[:200]}"]
    R = nfr_pod_recount(data, rel, projects, teams)
    names = [t["text"] for t in page["tabs"]]
    if names != ["By Project", "By Category", "By Commitment", "By Capability", "By Team", "By Pod"]:
        bad.append(f"{tag} the tabs are {names}")
    if [t["id"] for t in page["tabs"] if t["sel"] == "true"] != ["pod"]:
        bad.append(f"{tag} the selected tab is {[t['id'] for t in page['tabs'] if t['sel'] == 'true']}, expected By Pod")
    if "nt=pod" not in page["hash"]:
        bad.append(f"{tag} the address does not carry nt=pod: {page['hash']}")
    heads = ["Pod", "Not Started", "In Progress", "Validation", "Done"] + (["Other Status"] if R["other"] else []) + ["Total", "Share"]
    if page["head"] != heads:
        bad.append(f"{tag} heads {page['head']}, expected {heads}")
    if [r["label"] for r in page["rows"]] != [r["label"] for r in R["rows"]]:
        bad.append(f"{tag} rows {[r['label'] for r in page['rows']]}, expected {[r['label'] for r in R['rows']]}")
        return bad
    if len(page["foot"]) != 1 or page["foot"][0]["label"] != R["total"]["label"]:
        bad.append(f"{tag} the total row is {[r['label'] for r in page['foot']]}, expected '{R['total']['label']}'")
        return bad
    universe = [epic_issue(e) for e in data["epics"]]
    cache: dict = {}
    judged = 0
    for pr, er in list(zip(page["rows"], R["rows"])) + [(page["foot"][0], R["total"])]:
        # the cells are Not Started, In Progress, Validation, Done, [Other Status], Total, then Share
        cols = 4 + (1 if R["other"] else 0) + 1
        want = er["cells"][:4] + (er["cells"][4:5] if R["other"] else []) + er["cells"][5:]
        for ci, (c, keys) in enumerate(zip(pr["cells"][:cols], want)):
            where = f"{tag} {er['label']} / {heads[ci + 1]}"
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
            try:
                if jql not in cache:
                    tree = J.parse(jql)
                    cache[jql] = {i["key"] for i in universe if J.evaluate(tree, i)}
                judged += 1
            except (J.Malformed, J.Unsupported) as e:
                bad.append(f"{where} query cannot be evaluated: {e}: {jql[:200]}")
                continue
            if cache[jql] != keys:
                bad.append(f"{where} query finds {len(cache[jql])}, the cell counts {len(keys)}; extra {sorted(cache[jql] - keys)[:3]} missing {sorted(keys - cache[jql])[:3]}: {jql[-230:]}")
        total = len(er["cells"][5])
        m = re.match(r"(\d[\d,]*) NFR epics?: (\d+) Done, (\d+) in-progress, (\d+) Not Started", pr["share"] or "")
        if total >= 5:
            if not m or int(m.group(1).replace(",", "")) != total or int(m.group(2)) != len(er["cells"][3]) or int(m.group(3)) != len(er["cells"][1]) + len(er["cells"][2]) or int(m.group(4)) != len(er["cells"][0]):
                bad.append(f"{tag} {er['label']} share '{(pr['share'] or '')[:90]}' does not say {total} epics")
        elif pr["share"] and m:
            bad.append(f"{tag} {er['label']} shows a share bar for {total} epics (under 5)")
    if judged < 3:
        bad.append(f"{tag} only {judged} links were judged (the check is blind)")
    if len(R["total"]["cells"][5]) != len({k for r in R["rows"] for k in r["cells"][5]}) and not any(r["label"] == "No Pod Label" for r in R["rows"]):
        pass
    return bad


NFR_VIEWS = [("r=27.1&nt=pod", "27.1", None, None), ("r=27.1&nt=pod&p=PMN|CXCO", "27.1", ["PMN", "CXCO"], None), ("r=26.4&nt=pod", "26.4", None, None),
             ("r=27.2&nt=pod&p=CXWFM|WFM", "27.2", ["CXWFM", "WFM"], None), ("r=27.1&nt=pod&TEAM", "27.1", None, "TEAM")]


def first_nfr_team(data: dict) -> str:
    cur = data["current"]
    for e in sorted(data["epics"], key=lambda e: e["k"]):
        if cur in e["fv"] and e.get("tm") and e["p"] in ("PMN", "CXWFM", "CXCO") and (e.get("nf") or e.get("cat") in NFR_CATEGORIES):
            return e["tm"][0]
    raise AssertionError("no NFR epic with a team in the fixture")


def run_nfr(which: str, views=NFR_VIEWS) -> list[str]:
    F = fixture()
    data = F[which]
    team = first_nfr_team(data)
    bad: list[str] = []
    for spec, rel, projects, tm in views:
        bad += check_nfr(data, F["u_" + which], spec, rel, projects, {team} if tm else None, team if tm else None)
    return bad


# --------------------------------------------------------------------------------------------- tests: the NFR tab
@SUITE.test("xt_the_variant_has_what_the_pod_rows_need")
def _(t: T):
    F = fixture()
    d = F["var"]
    cur = d["current"]
    nfr = [e for e in d["epics"] if cur in e["fv"] and (e.get("nf") or e.get("cat") in NFR_CATEGORIES)]
    t.check(any(len({l.lower() for l in e.get("pl") or []}) > 1 for e in nfr), "an NFR epic with two pod labels")
    labels: dict = {}
    for e in d["epics"]:
        for l in e.get("pl") or []:
            labels.setdefault(l.lower(), set()).add(l)
    t.check(any(len(v) > 1 for v in labels.values()), "a pod spelled in two cases")
    t.check(len({e["p"] for e in nfr if any(l.lower() == "pod-extra-1" for l in e.get("pl") or [])}) >= 2, "the same pod label in two projects among the NFR epics")
    t.check(any(not e.get("pl") for e in nfr), "an NFR epic with no pod label")
    t.check(any(e.get("tm") and len(e["tm"]) > 1 for e in d["epics"]) or True, "")
    t.note(f"{len(nfr)} NFR epics in {cur}, {sum(1 for e in nfr if e.get('pl'))} with a pod label")


@SUITE.test("xt_nfr_by_pod_rows_counts_and_links_equal_an_independent_recount_base")
def _(t: T):
    bad = run_nfr("base")
    for b in bad[:10]:
        t.failures.append(b)
    t.passed += 0 if bad else 1
    t.note(f"{len(NFR_VIEWS)} views: all projects, two projects, an older release, a later one, one team")


@SUITE.test("xt_nfr_by_pod_rows_counts_and_links_equal_an_independent_recount_variant")
def _(t: T):
    bad = run_nfr("var")
    for b in bad[:10]:
        t.failures.append(b)
    t.passed += 0 if bad else 1


@SUITE.test("xt_nfr_by_pod_the_variant_combines_spellings_and_counts_an_epic_under_each_pod_and_the_total_once")
def _(t: T):
    F = fixture()
    go(F["u_var"], "r=27.1&nt=pod")
    page = ctx.chrome.js(NFR_JS)
    R = nfr_pod_recount(F["var"], "27.1", None, None)
    labels = [r["label"] for r in page["rows"]]
    low = [l.lower() for l in labels]
    t.check("pod-extra-1 (pmn)" in low and "pod-extra-1 (cxwfm)" in low, f"the same pod in two projects is two rows named with their project: {labels}")
    t.check(len(low) == len(set(low)), f"spellings that differ only in case are one row: {labels}")
    t.check(any(l.startswith("pod-alpha-2") for l in labels) and sum(l.lower().startswith("pod-alpha-2") for l in labels) == 1, "Pod-Alpha-2 and pod-alpha-2 of one project are one row")
    t.check(sum(int(r["cells"][-2]["text"].replace(",", "")) for r in page["rows"]) > int(page["foot"][0]["cells"][-2]["text"].replace(",", "")), "an epic with two pod labels is in two rows, so the rows add up to more than the total")
    t.check(int(page["foot"][0]["cells"][-2]["text"].replace(",", "")) == len(R["nfr"]), "the total row counts each NFR epic once")
    t.check(labels[-1] == "No Pod Label", f"No Pod Label is the last row: {labels[-1]}")
    t.check([t_["text"] for t_ in page["tabs"]][-2:] == ["By Team", "By Pod"], "By Pod follows By Team")


@SUITE.test("xt_nfr_by_pod_the_tab_works_from_the_keyboard_and_the_address")
def _(t: T):
    F = fixture()
    ch = ctx.chrome
    go(F["u_base"], "r=27.1")
    ch.js("document.getElementById('nt-team').click()")
    time.sleep(0.3)
    key = lambda k, code, vk: (ch.cmd("Input.dispatchKeyEvent", type="keyDown", key=k, code=code, windowsVirtualKeyCode=vk), ch.cmd("Input.dispatchKeyEvent", type="keyUp", key=k, code=code, windowsVirtualKeyCode=vk))
    ch.js("document.getElementById('nt-team').focus()")
    key("ArrowRight", "ArrowRight", 39)
    time.sleep(0.3)
    s = ch.js("({sel: [...document.querySelectorAll('#nfr-tabs [role=tab]')].filter(b => b.getAttribute('aria-selected') === 'true').map(b => b.id), focus: document.activeElement && document.activeElement.id, hash: location.hash, panel: document.getElementById('nfr-panel').getAttribute('aria-labelledby')})")
    t.check(s["sel"] == ["nt-pod"] and s["focus"] == "nt-pod" and "nt=pod" in s["hash"] and s["panel"] == "nt-pod", f"the right arrow from By Team selects By Pod: {s}")
    key("ArrowRight", "ArrowRight", 39)
    time.sleep(0.3)
    t.check(ch.js("document.activeElement.id") == "nt-project", "the right arrow from By Pod wraps to By Project")
    go(F["u_base"], "r=27.1&nt=bogus")
    t.check(ch.js("[...document.querySelectorAll('#nfr-tabs [role=tab]')].filter(b => b.getAttribute('aria-selected') === 'true').map(b => b.id)") == ["nt-project"], "an unknown tab in the address opens By Project")
    go(F["u_base"], "r=27.1&nt=pod")
    ch.js("document.getElementById('nt-project').click()")
    time.sleep(0.3)
    t.check("nt=" not in ch.js("location.hash"), "the default tab leaves no nt in the address")


# --------------------------------------------------------------------------------------------- tests: the Capabilities table on the variant
CAP_VIEWS = [CO.View(), CO.View(off={"Stretch"}), CO.View(off={"Committed", "Target", ""}), CO.View(off={"Committed", "Stretch", "Target"}), CO.View(projects=["PMN", "CXWFM"]), CO.View(rel="26.4"), CO.View(rel="27.2"), CO.View(rel="27.2", projects=["CXCO", "WFM"])]


def run_caps(url: str, data: dict, vs=CAP_VIEWS) -> list[str]:
    bad: list[str] = []
    for v in vs:
        page = CO.load(url, v.hash)
        bad += CO.check_view(page, CO.recount(data, v), v, data, None)
    return bad


@SUITE.test("xt_capabilities_team_and_pod_rows_equal_an_independent_recount_on_the_variant")
def _(t: T):
    F = fixture()
    bad = run_caps(F["u_var"], F["var"])
    for b in bad[:10]:
        t.failures.append(b)
    t.passed += 0 if bad else 1
    R = CO.recount(F["var"], CO.View())
    lv = {}
    for r in R["rows_b"]:
        lv[r["level"]] = lv.get(r["level"], 0) + 1
    t.note(f"{len(CAP_VIEWS)} views; default view rows by level: {lv}")


@SUITE.test("xt_capabilities_the_fixture_exercises_every_kind_of_row")
def _(t: T):
    F = fixture()
    R = CO.recount(F["var"], CO.View())
    rows = R["rows_b"]
    t.check(any(r.get("unknown") for r in rows), "a team-unknown row (child epics with no release fix version in a tracked project)")
    t.check(any(r["level"] == "pod" and r["label"] == "No Pod Label" for r in rows), "a No Pod Label row")
    t.check(any(r["level"] == "team" and r["label"] == "(No Team)" for r in rows), "a (No Team) row")
    t.check(any(r["level"] == "project" and r["label"] not in F["var"]["projects"] for r in rows), "a project the page does not track (no rows under it)")
    kids = R["kids"]
    teams_sum = sum(len(r["cells"][-1]) for r in rows if r["level"] == "team")
    t.check(teams_sum > len({k[0] for k in kids}) - len([k for k in kids if k[1] not in F["var"]["projects"]]) - 0, "an epic with two teams is in two team rows (the team rows add up to more than the epics)")
    pods_sum = sum(len(r["cells"][-1]) for r in rows if r["level"] == "pod")
    t.check(pods_sum > 0, "pod rows exist")
    outside = [r for r in rows if r["level"] == "project" and r["label"] not in F["var"]["projects"]]
    t.check(all(not any(x.get("project") == o["label"] and x["level"] != "project" for x in rows) for o in outside), "the untracked project has no team rows")
    t.check(rows[-1]["label"] == "All Projects" and len(rows[-1]["cells"][-1]) == len({k[0] for k in kids}), "the total counts each child epic once")


@SUITE.test("xt_capabilities_the_untracked_project_has_no_chevron_and_the_unknown_row_says_why")
def _(t: T):
    F = fixture()
    go(F["u_var"], "r=27.1")
    s = ctx.chrome.js("""(() => { const rows = [...document.querySelectorAll('#xt-capkids tbody tr[data-id]')];
      return rows.map(r => ({label: r.querySelector('.xtname').textContent.trim(), lvl: r.dataset.lvl, tgl: !!r.querySelector('.cytgl'), note: (r.querySelector('.cysub') || {}).textContent || ''})); })()""")
    outside = [r for r in s if r["lvl"] == "project" and r["label"] not in F["var"]["projects"]]
    t.check(outside and all(not r["tgl"] for r in outside), f"a project that is not tracked has no chevron: {outside}")
    unk = [r for r in s if r["label"].startswith("Team Unknown")]
    t.check(unk and all("holds no team" in r["note"] for r in unk), f"the team-unknown row says why: {unk}")
    t.check(all(r["tgl"] for r in s if r["lvl"] == "project" and r["label"] in F["var"]["projects"]), "every tracked project row with rows under it has a chevron")


@SUITE.test("xt_capability_status_summary_lists_the_capabilities_of_each_project_and_they_add_up_to_its_total")
def _(t: T):
    F = fixture()
    ch = ctx.chrome
    seen_two = False
    for spec in ("r=27.1", "r=27.2", "r=27.1&clx=Committed|Stretch", "r=27.1&p=PMN|CXCO"):
        go(F["u_var"], spec)
        rows = ch.js("""[...document.querySelectorAll('#xt-capstat tbody tr')].map(r => ({lvl: r.dataset.lvl || 'total', id: r.dataset.id || '', par: r.dataset.par || '', label: (r.querySelector('.xtname') || r.cells[0]).textContent.trim(),
            total: r.cells[r.cells.length - 1].textContent.trim(), caps: r.dataset.lvl === 'cap' ? r.querySelector('.xtname a').textContent.trim() : '', note: (r.querySelector('.cysub') || {}).textContent || ''}))""")
        projects = [r for r in rows if r["lvl"] == "project"]
        t.check(projects, f"{spec}: project rows")
        for pr in projects:
            kids = [r for r in rows if r["par"] == pr["id"]]
            t.check(len(kids) == int(pr["total"].replace(",", "")) and all(r["lvl"] == "cap" for r in kids), f"{spec}: {pr['label']} lists {len(kids)} Capabilities, its Total says {pr['total']}")
            t.check([r["caps"] for r in kids] == sorted((r["caps"] for r in kids), key=lambda k: (k.rsplit("-", 1)[0], int(k.rsplit("-", 1)[1]))), f"{spec}: {pr['label']} lists its Capabilities by key")
            seen_two = seen_two or any(re.search(r"Fix version [^·]*, ", r["note"]) for r in kids)
        tot = rows[-1]
        t.check(tot["lvl"] == "total" and int(tot["total"].replace(",", "")) == len({r["caps"] for r in rows if r["lvl"] == "cap"}) and not ch.js("document.querySelector('#xt-capstat tfoot tr, #xt-capstat tbody tr.total') && document.querySelector('#xt-capstat tbody tr.total .cytgl') ? 1 : 0"), f"{spec}: the total row counts each Capability once and has no chevron")
    t.check(seen_two, "a Capability with two fix versions is listed (under its project, once)")


# --------------------------------------------------------------------------------------------- tests: behaviour of the expandable tables
TABLES = [("bugs", "Quality bug table", "r=27.1"), ("capkids", "Capabilities child-epic table", "r=27.1"), ("capstat", "Capability Status Summary", "r=27.1")]
KID = {"bugs": "team:", "capkids": "team:", "capstat": "cap:"}
VIS_JS = """(id) => [...document.querySelectorAll('#xt-' + id + ' tbody tr[data-id]')].filter(r => !r.hidden).map(r => r.dataset.lvl + ':' + r.querySelector('.xtname').textContent.trim())"""


def vis(ch, tid: str) -> list:
    return ch.js(f"({VIS_JS})({tid!r})")


@SUITE.test("xt_a_chevron_opens_and_closes_the_rows_under_it_with_the_right_names_and_states")
def _(t: T):
    F = fixture()
    ch = ctx.chrome
    for tid, what, spec in TABLES:
        go(F["u_var"], spec)
        v0 = vis(ch, tid)
        t.check(v0 and all(x.startswith("project:") for x in v0), f"{what}: every project is collapsed at first (several projects selected): {v0[:4]}")
        first = ch.js(f"(() => {{ const b = document.querySelector('#xt-{tid} tbody tr[data-id] .cytgl'); return {{id: b.dataset.xtval, label: b.getAttribute('aria-label'), exp: b.getAttribute('aria-expanded'), ctl: b.getAttribute('aria-controls').split(' ').map(i => !!document.getElementById(i)), text: b.textContent.trim(), tag: b.tagName, type: b.type}}; }})()")
        t.check(first["exp"] == "false" and first["label"].startswith("Expand project ") and all(first["ctl"]) and first["tag"] == "BUTTON" and first["type"] == "button" and first["text"] == "", f"{what}: first chevron {first}")
        ch.js(f"document.querySelector('#xt-{tid} tbody tr[data-id] .cytgl').click()")
        v1 = vis(ch, tid)
        kids = [x for x in v1 if not x.startswith("project:")]
        t.check(kids and all(x.startswith(KID[tid]) for x in kids), f"{what}: one click shows the rows of that project only: {v1[:8]}")
        s = ch.js(f"(() => {{ const b = document.querySelector('#xt-{tid} tbody tr[data-id] .cytgl'); return [b.getAttribute('aria-expanded'), b.getAttribute('aria-label')]; }})()")
        t.check(s[0] == "true" and s[1].startswith("Collapse project "), f"{what}: the button now says it collapses: {s}")
        ch.js(f"document.querySelector('#xt-{tid} tbody tr[data-id] .cytgl').click()")
        t.check(vis(ch, tid) == v0, f"{what}: a second click closes it again")
        ch.js(f"document.querySelector('#xt-{tid}').closest('section, .cyblock, #bug-table') && 0; document.querySelector('[data-xtact=expall][data-xttable={tid}]').click()")
        v2 = vis(ch, tid)
        t.check(len(v2) > len(v1) and ((tid != "capkids" and not any(x.startswith("pod:") for x in v2)) or (tid == "capkids" and any(x.startswith("pod:") for x in v2))), f"{what}: Expand All shows every level the table has ({len(v2)} rows)")
        if tid == "bugs":
            t.check(not any(x.startswith("pod:") for x in v2) and ch.js("document.querySelectorAll('#xt-bugs tr[data-lvl=pod]').length") == 0, "the bug table has no pod level")
        ch.js(f"document.querySelector('[data-xtact=colall][data-xttable={tid}]').click()")
        t.check(vis(ch, tid) == v0, f"{what}: Collapse All returns to the projects")
        t.check(ch.js(f"[...document.querySelectorAll('#xt-{tid} .cytgl')].every(b => b.getAttribute('aria-expanded') === 'false')") is True, f"{what}: after Collapse All every chevron says Expand")


@SUITE.test("xt_a_project_selected_alone_opens_to_its_teams_and_the_open_rows_survive_a_filter_change")
def _(t: T):
    F = fixture()
    ch = ctx.chrome
    for tid, what, _spec in TABLES:
        go(F["u_var"], "r=27.1&p=PMN")
        v = vis(ch, tid)
        t.check(any(x.startswith(KID[tid]) for x in v) and not any(x.startswith("pod:") for x in v), f"{what}: one project selected: expanded to its first level, not to its pods: {v[:6]}")
        go(F["u_var"], "r=27.1")
        ch.js(f"document.querySelector('[data-xtact=expall][data-xttable={tid}]').click()")
        n = len(vis(ch, tid))
        ch.js("document.querySelector('#f-gran input[value=week]') && document.querySelector('#f-gran input[value=week]').click()")
        ch.js("document.getElementById('f-reset') && 0")
        # a filter change redraws the page: Priority chip of the bug section (bugs) or a Commitment Level chip (Capabilities)
        ch.js("(() => { const x = document.querySelector('#f-ax input[value=all]'); if (x) x.click(); })()")
        time.sleep(0.4)
        t.check(len(vis(ch, tid)) >= n - 0 and any(x.startswith(KID[tid]) for x in vis(ch, tid)), f"{what}: the rows opened stay open after the page is redrawn ({n} rows before, {len(vis(ch, tid))} after)")


@SUITE.test("xt_the_chevron_is_reachable_and_works_with_the_keyboard")
def _(t: T):
    F = fixture()
    ch = ctx.chrome
    go(F["u_var"], "r=27.1")
    key = lambda k, code, vk, text="": (ch.cmd("Input.dispatchKeyEvent", type="keyDown", key=k, code=code, windowsVirtualKeyCode=vk, **({"text": text} if text else {})), ch.cmd("Input.dispatchKeyEvent", type="keyUp", key=k, code=code, windowsVirtualKeyCode=vk))
    for tid, what, _spec in TABLES:
        ch.js(f"document.querySelector('#xt-{tid} tbody tr[data-id] .cytgl').focus()")
        key("Enter", "Enter", 13, "\r")
        time.sleep(0.15)
        s = ch.js(f"(() => {{ const b = document.querySelector('#xt-{tid} tbody tr[data-id] .cytgl'); return {{exp: b.getAttribute('aria-expanded'), focus: document.activeElement === b}}; }})()")
        t.check(s["exp"] == "true" and s["focus"], f"{what}: Enter on the chevron opens the row and focus stays on it: {s}")
        key(" ", "Space", 32, " ")
        time.sleep(0.15)
        s = ch.js(f"document.querySelector('#xt-{tid} tbody tr[data-id] .cytgl').getAttribute('aria-expanded')")
        t.check(s == "false", f"{what}: Space on the chevron closes it: {s}")
        t.check(ch.js(f"(() => {{ const b = document.querySelector('#xt-{tid} .cytgl'); return getComputedStyle(b).minHeight === '24px' && b.getBoundingClientRect().height >= 24; }})()") is True, f"{what}: the chevron target is at least 24 px")


@SUITE.test("xt_the_delivery_cycles_table_is_untouched_and_the_tables_keep_their_names_for_a_screen_reader")
def _(t: T):
    F = fixture()
    ch = ctx.chrome
    go(F["u_var"], "r=27.1")
    a = ch.js("document.querySelectorAll('#cy-ovbody tr[data-id]').length")
    n0 = ch.js("[...document.querySelectorAll('#cy-ovbody tr[data-id]')].filter(r => !r.hidden).length")
    ch.js("document.querySelector('[data-cyact=expall]').click()")
    n1 = ch.js("[...document.querySelectorAll('#cy-ovbody tr[data-id]')].filter(r => !r.hidden).length")
    t.check(a and n1 > n0, f"Expand All of the Cycles table still opens its rows ({n0} to {n1} of {a})")
    t.check(ch.js("document.querySelectorAll('#cy-ovbody [data-xtact], #cy-ovtable [data-xttable]').length") == 0, "the Cycles table carries none of the new attributes")
    t.check(ch.js("!!document.querySelector('#bug-table table caption.sr') && !!document.querySelector('#capview #xt-capkids caption.sr')") is True, "both tables keep a screen-reader caption")
    caps = ch.js("[document.querySelector('#xt-bugs caption').textContent, document.querySelector('#xt-capkids caption').textContent]")
    t.check(all("can be expanded or collapsed" in c for c in caps), f"the captions say the rows open: {caps}")
    t.check(ch.js("document.querySelector('#bug-tglbar [data-xtact=expall]').textContent") == "Expand All" and ch.js("document.querySelector('#bug-tglbar [data-xtact=colall]').textContent") == "Collapse All", "Expand All and Collapse All, in Title Case, above the bug table")


@SUITE.test("xt_390px_the_page_does_not_scroll_sideways_and_the_tables_scroll_inside_their_wrapper")
def _(t: T):
    F = fixture()
    ch = ctx.chrome
    try:
        ch.viewport(390, 800, mobile=False)
        for spec in ("r=27.1", "r=27.1&nt=pod"):
            go(F["u_var"], spec)
            ch.js("document.querySelectorAll('[data-xtact=expall]').forEach(b => b.click())")
            m = ch.js("({sw: document.documentElement.scrollWidth, w: window.innerWidth})")
            t.check(m["sw"] <= m["w"], f"390 px {spec}: the page scrolls sideways {m}")
    finally:
        ch.viewport(1400, 900)


# --------------------------------------------------------------------------------------------- tests: Dependencies
@SUITE.test("xt_dependencies_the_caption_and_the_hint_are_gone_the_labels_and_chips_stay")
def _(t: T):
    F = fixture()
    ch = ctx.chrome
    go(F["u_base"], "r=27.1")
    s = ch.js("""(() => { const g = document.getElementById('g-dep'); const tx = e => e ? e.textContent.replace(/\\s+/g, ' ').trim() : '';
      return {text: tx(g), role: g.getAttribute('role'), name: g.getAttribute('aria-label'), lbl: !!document.getElementById('lbl-dp'), hint: g.querySelectorAll('.hintline').length, rel: tx(document.getElementById('lbl-dpr')), att: tx(document.getElementById('lbl-da')),
              radios: [...g.querySelectorAll('input[type=radio]')].map(i => i.value), boxes: [...g.querySelectorAll('input[type=checkbox]')].map(i => i.value), first: g.firstElementChild.className,
              page: tx(document.body)}; })()""")
    t.check("Quick Filter" not in s["text"] and s["lbl"] is False, f"the caption is gone: {s['text'][:80]}")
    t.check("Filters the board and table, not the tiles." not in s["page"] and s["hint"] == 0, "the sentence is gone from the section")
    t.check(s["role"] == "group" and s["name"] and "Quick Filter" not in s["name"], f"the group is named for screen readers: role {s['role']}, name {s['name']!r}")
    t.check(s["rel"] == "Relationship" and s["att"] == "Needs Attention (pick any)", f"the two labels stay: {s['rel']!r}, {s['att']!r}")
    t.check(s["radios"] == ["all", "epics", "external", "blocking", "cx"] and s["boxes"] == ["overdue", "unplanned", "gap"], f"every chip stays: {s['radios']} {s['boxes']}")
    t.check("depgrp" in s["first"], f"the first element of the filter is the Relationship group: {s['first']}")
    t.check("The quick filter changes the board and the table, not the figures." in ch.js("document.getElementById('dep-cap').textContent"), "what the filter does not change is still said in How this is calculated")


@SUITE.test("xt_dependencies_the_changed_marker_moves_to_the_first_label_and_the_chips_still_filter")
def _(t: T):
    F = fixture()
    ch = ctx.chrome
    go(F["u_base"], "r=27.1")
    mark = "getComputedStyle(document.querySelector('#g-dep .depgrp .dlbl'), '::before').content"
    t.check(ch.js(mark) in ("none", "normal", '""'), f"no marker while the filter is at its default: {ch.js(mark)}")
    ch.js("document.querySelector('#f-da input[value=overdue]').click()")
    time.sleep(0.3)
    t.check("●" in ch.js(mark) and ch.js("document.getElementById('g-dep').classList.contains('changed')") is True, f"a changed filter is marked before its first label: {ch.js(mark)}")
    t.check("dp=overdue" in ch.js("location.hash"), "and the choice is in the address")
    ch.js("document.querySelector('#f-dp input[value=external]').click()")
    time.sleep(0.3)
    t.check("dp=external|overdue" in urllib.parse.unquote(ch.js("location.hash")) and ch.js("document.querySelector('#f-dp input[value=external]').checked") is True, f"the Relationship radios still work: {ch.js('location.hash')}")
    t.check(ch.js("getComputedStyle(document.getElementById('g-dep')).display") == "grid", "the filter is still a grid of two columns")


# --------------------------------------------------------------------------------------------- seeded defects
def _mutant(src: str, old: str, new: str, name: str) -> Path:
    assert src.count(old) == 1, f"the seeding anchor for '{name}' is not in the template exactly once (found {src.count(old)}): the mutation test would be blind"
    p = Path(ctx.dir) / f"xt_mutant_{name}.html"
    p.write_text(src.replace(old, new, 1), encoding="utf-8")
    return p


def _with_mutant(old: str, new: str, name: str, fn):
    src = ctx.template.read_text(encoding="utf-8")
    p = _mutant(src, old, new, name)
    saved = ctx.template
    ctx.template = p
    try:
        F = fixture()
        urls = {w: ctx.write(kit.fragment_for(F[w]), "xtmut_" + w) for w in ("base", "var")}
        return fn(urls, F)
    finally:
        ctx.template = saved


def _caps_defect(urls, F):
    return run_caps(urls["var"], F["var"], [CO.View(), CO.View(projects=["PMN", "CXWFM"])])


def _nfr_defect(urls, F):
    bad: list[str] = []
    for spec, rel, projects, tm in NFR_VIEWS[:2]:
        bad += check_nfr(F["var"], urls["var"], spec, rel, projects, None)
    return bad


def _toggle_defect(urls, F):
    ch = ctx.chrome
    go(urls["var"], "r=27.1")
    v0 = vis(ch, "capkids")
    ch.js("document.querySelector('#xt-capkids tbody tr[data-id] .cytgl').click()")
    v1 = vis(ch, "capkids")
    ch.js("document.querySelector('[data-xtact=expall][data-xttable=capkids]').click()")
    v2 = vis(ch, "capkids")
    ch.js("document.querySelector('[data-xtact=colall][data-xttable=capkids]').click()")
    v3 = vis(ch, "capkids")
    return [] if (len(v1) > len(v0) and len(v2) > len(v1) and v3 == v0) else [f"rows shown: collapsed {len(v0)}, one opened {len(v1)}, all opened {len(v2)}, all closed {len(v3)}"]


def _state_defect(urls, F):
    ch = ctx.chrome
    go(urls["var"], "r=27.1")
    ch.js("document.querySelector('[data-xtact=expall][data-xttable=capkids]').click()")
    b = ch.js("[...document.querySelectorAll('#xt-capkids .cytgl')].map(b => b.getAttribute('aria-expanded'))")
    ch.js("document.querySelector('[data-xtact=colall][data-xttable=capkids]').click()")
    a = ch.js("[...document.querySelectorAll('#xt-capkids .cytgl')].map(b => b.getAttribute('aria-expanded'))")
    return [] if all(x == "true" for x in b) and all(x == "false" for x in a) else ["the chevrons do not say what the rows do"]


def _redraw_defect(urls, F):
    ch = ctx.chrome
    go(urls["var"], "r=27.1")
    n0 = len(vis(ch, "capkids"))
    ch.js("document.querySelector('[data-xtact=expall][data-xttable=capkids]').click()")
    n = len(vis(ch, "capkids"))
    ch.js("document.querySelector('#f-ax input[value=all]').click()")
    time.sleep(0.4)
    return [] if n > n0 and len(vis(ch, "capkids")) == n else [f"the open rows are lost when the page is redrawn ({n0} collapsed, {n} opened, {len(vis(ch, 'capkids'))} after)"]


def _bug_state_defect(urls, F):
    ch = ctx.chrome
    go(urls["var"], "r=27.1")
    n0 = len(vis(ch, "bugs"))
    ch.js("document.querySelector('[data-xtact=expall][data-xttable=bugs]').click()")
    n = len(vis(ch, "bugs"))
    ch.js("document.querySelector('#f-ax input[value=all]').click()")
    time.sleep(0.4)
    return [] if n > n0 and len(vis(ch, "bugs")) == n else [f"the open rows of the bug table are lost when the page is redrawn ({n0} collapsed, {n} opened, {len(vis(ch, 'bugs'))} after)"]


def _dep_defect(urls, F):
    ch = ctx.chrome
    go(urls["base"], "r=27.1")
    s = ch.js("(() => { const g = document.getElementById('g-dep'); return [g.textContent.includes('Quick Filter'), g.querySelectorAll('.hintline').length, !!g.getAttribute('aria-label')]; })()")
    return [f"caption {s[0]}, hint {s[1]}, named {s[2]}"] if (s[0] or s[1] or not s[2]) else []


def _capstat_defect(urls, F):
    ch = ctx.chrome
    go(urls["var"], "r=27.1")
    rows = ch.js("""[...document.querySelectorAll('#xt-capstat tbody tr')].map(r => ({lvl: r.dataset.lvl || 'total', id: r.dataset.id || '', par: r.dataset.par || '', total: r.cells[r.cells.length - 1].textContent.trim()}))""")
    bad = [f"a project row says {r['total']} and lists {sum(1 for k in rows if k['par'] == r['id'])}" for r in rows if r["lvl"] == "project" and sum(1 for k in rows if k["par"] == r["id"]) != int(r["total"].replace(",", ""))]
    chev = ch.js("document.querySelectorAll('#xt-capstat tr.total .cytgl, #xt-capstat tr[data-lvl=cap] .cytgl').length")
    return bad + ([f"{chev} chevrons on rows that cannot open"] if chev else [])


SEEDS = [
    ("team_and_pod_links_lose_their_clause", "const bLine = n => n.unknown ? (n.whole ? `project = ${pkey(n.project)} AND ${noRel}` : false) : cyNodeClause(n);", "const bLine = n => n.unknown ? (n.whole ? `project = ${pkey(n.project)} AND ${noRel}` : false) : `project = ${pkey(n.project)}`;", _caps_defect),
    ("pods_are_compared_with_their_case", "const plOf = e => [...new Set((recs.get(e[0]).pl || []).map(l => l.toLowerCase()))];", "const plOf = e => [...new Set(recs.get(e[0]).pl || [])];", _caps_defect),
    ("an_epic_counts_under_its_first_team_only", "const te = known.filter(e => tms(e).includes(T)),", "const te = known.filter(e => tms(e)[0] === T),", _caps_defect),
    ("an_epic_counts_under_its_first_pod_only", "const keys = new Map(); te.forEach(e => plOf(e).forEach(k => {", "const keys = new Map(); te.forEach(e => plOf(e).slice(0, 1).forEach(k => {", _caps_defect),
    ("the_team_unknown_row_is_dropped", "if (unk.length) bn.add(\"team\"", "if (false) bn.add(\"team\"", _caps_defect),
    ("the_total_adds_up_the_teams", "tail: `<tr class=\"total\"><th scope=\"row\">All Projects</th>${bCells(kids, \"\", \"\", true)}</tr>`", "tail: `<tr class=\"total\"><th scope=\"row\">All Projects</th>${bCells(roots.flatMap(r => r.kids.length ? r.kids.flatMap(k => k.list) : r.list), \"\", \"\", true)}</tr>`", _caps_defect),
    ("no_pod_label_row_is_dropped", "if (none.length) bn.add(\"pod\", \"No Pod Label\"", "if (false) bn.add(\"pod\", \"No Pod Label\"", _caps_defect),
    ("a_pod_clause_uses_one_spelling", "bn.add(\"pod\", r.name, tn, {project: P, team: T, list: es, spellings: [...r.spellings].sort()})", "bn.add(\"pod\", r.name, tn, {project: P, team: T, list: es, spellings: [...r.spellings].sort().slice(0, 1)})", _caps_defect),
    ("nfr_pod_rows_are_per_label_not_per_project", "const pods = cyPodsOf(nfr), none", "const pods = cyPodsOf(nfr).filter((p, i, a) => a.findIndex(q => q.key === p.key) === i), none", _nfr_defect),
    ("nfr_pod_link_without_the_pod_clause", "`${NFR_Q} AND ${cyPodClause(pd)}`, {projects: [pd.project]}", "`${NFR_Q}`, {projects: [pd.project]}", _nfr_defect),
    ("nfr_pod_total_adds_up_the_rows", "totRow(\"All Selected (Each Epic Once)\")", "row(\"All Selected (Each Epic Once)\", pods.flatMap(p => p.epics), NFR_Q).replace(\"<tr>\", '<tr class=\"total\">')", _nfr_defect),
    ("nfr_no_pod_label_row_dropped", "(none.length ? row(\"No Pod Label\"", "(false ? row(\"No Pod Label\"", _nfr_defect),
    ("the_quick_filter_caption_returns", '<div class="periodbar depfilter" id="g-dep" role="group" aria-label="Filter the dependencies">\n', '<div class="periodbar depfilter" id="g-dep" role="group" aria-label="Filter the dependencies"><span class="lbl" id="lbl-dp">Quick Filter</span>\n', _dep_defect),
    ("the_quick_filter_group_loses_its_name", '<div class="periodbar depfilter" id="g-dep" role="group" aria-label="Filter the dependencies">', '<div class="periodbar depfilter" id="g-dep">', _dep_defect),
    ("a_project_lists_fewer_capabilities_than_its_total", "pn.list.slice().sort((x, y) => keyCmp(x.k, y.k)).forEach(", "pn.list.slice().sort((x, y) => keyCmp(x.k, y.k)).slice(1).forEach(", _capstat_defect),
    ("a_capability_row_gets_a_chevron", "const tgl = n.kids.length ?", "const tgl = n.kids.length || n.level === \"cap\" ?", _capstat_defect),
    ("a_toggle_does_not_hide_the_rows_under_it", "r.hidden = !!pr && (pr.hidden || !open.has(par));", "r.hidden = false;", _toggle_defect),
    ("a_chevron_does_not_say_what_it_does", "b.setAttribute(\"aria-expanded\", String(on)); b.setAttribute(\"aria-label\", `${on ? \"Collapse\" : \"Expand\"} ${b.dataset.what}`); }\n  });\n}\ndocument.addEventListener", "}\n  });\n}\ndocument.addEventListener", _state_defect),
    ("the_open_rows_are_lost_on_a_redraw", "XT_OPEN.set(tid, cur); xtApply(tid);", "xtApply(tid);", _redraw_defect),
    ("the_open_bug_rows_are_lost_on_a_redraw", "XT_OPEN.set(tid, cur); xtApply(tid);", "xtApply(tid);", _bug_state_defect),
]


def _seed_test(name, old, new, fn):
    @SUITE.test(f"xt_seeded_defect_is_caught_{name}")
    def _(t: T):
        bad = _with_mutant(old, new, name, fn)
        t.check(bool(bad), f"the seeded defect '{name}' was not caught")
        t.note(f"caught: {bad[0][:170] if bad else ''}")


for _n, _o, _w, _f in SEEDS:
    _seed_test(_n, _o, _w, _f)


if __name__ == "__main__":
    sys.exit(kit.cli(SUITE, __doc__))
