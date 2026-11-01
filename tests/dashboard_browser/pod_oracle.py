"""The independent recount of the Delivery Cycles Pods tiles (used by link_cycles.py; not a suite of its own).

The page counts pods with podRegistry / cyPodsOf / cyPodFig. This module counts them again from the BAKED epics, in plain Python, from the definitions the owner decided and nothing else:

  * a POD is one pod label per project, compared without regard to case; an epic with several labels counts once under each pod; an epic with no label is in no pod;
  * Idle Pods: pods that carry at least one epic of the release (under the page's Release, Projects, Teams and Commitment Type filters) and have NO epic planned in the selected cycle;
  * Pods With More Than 3 Epics in Flight: more than POD_LEVEL epics In Progress or Validation among the epics of the release, and the number of those epics, each once.

The only things taken from the page are its filters and the planned date of each epic (plannedLater; the Target Sprint calendar is proven by the other kinds of link_cycles.py).
`check_pods` compares the printed tiles and the two lists opened in turn; `check_node` compares the facts line and the strip of a detail view.
"""
from __future__ import annotations

import collections
import json
import re

N_FLIGHT = ("In Progress", "Validation")
POD_LEVEL = 3                                    # the page's CY.podWip, the owner's reference level; spelled here on purpose, not read from the page
EPIC_IDS = ["planned", "done", "overdue", "next", "flagged"]
POD_IDS = ["idle", "wip"]

# What the strips print, what the page was asked (its own state, not its pod figures), and the pod lists opened in turn (the button is focused and clicked, then clicked again).
POD_JS = r"""(() => {
  const M = CYM; if (!M || M.none) return null;
  const tile = (box, id) => { const t = document.querySelector(box + ' [data-kpi="' + id + '"]'); return t ? {v: t.querySelector('.v').textContent.trim(), s: t.querySelector('.s').textContent.trim(), btn: !!t.querySelector('.v button')} : null; };
  const ids = box => [...document.querySelectorAll(box + ' [data-kpi]')].map(t => t.dataset.kpi);
  return {release: state.release, projects: [...state.projects], teams: [...state.teams], commit: [...state.commit], cycle: {start: M.c.start, end: M.c.end, name: M.c.name},
    due: Object.fromEntries(M.epics.map(e => [e.k, e.due])), ids1: ids('#cy-kpis1'), ids2: ids('#cy-kpis2'), tiles: {idle: tile('#cy-kpis2', 'idle'), wip: tile('#cy-kpis2', 'wip')},
    texts: [...document.querySelectorAll('#cy-kpis1 .kpi, #cy-kpis2 .kpi')].map(t => t.textContent), shown: document.getElementById('cy-pods').hidden === false,
    heading: document.getElementById('cy-pods-h').textContent};
})()"""
LIST_JS = r"""((kind) => {
  const b = document.querySelector('#cy-kpis2 [data-cyact="pods"][data-cyval="' + kind + '"]'), host = document.getElementById('cy-podlist'); if (!b) return null;
  const hash = location.hash; b.focus(); b.click();
  const rows = [...host.querySelectorAll('tbody tr')].map(r => ({name: r.querySelector('th').firstChild.textContent.trim(), cells: [...r.querySelectorAll('td')].map(c => c.textContent.trim())}));
  const out = {rows, hdr: [...host.querySelectorAll('thead th')].map(h => h.textContent.trim()), expanded: b.getAttribute('aria-expanded'), hidden: host.hidden, controls: b.getAttribute('aria-controls'), label: b.getAttribute('aria-label'),
    caption: !!host.querySelector('caption.sr'), colScopes: [...host.querySelectorAll('thead th')].every(h => h.getAttribute('scope') === 'col'), rowScopes: [...host.querySelectorAll('tbody th')].every(h => h.getAttribute('scope') === 'row'),
    region: !!host.querySelector('.tablewrap[role="region"][tabindex="0"]'), focus: document.activeElement === b, hashSame: location.hash === hash,
    other: [...document.querySelectorAll('#cy-kpis2 [data-cyact="pods"]')].filter(x => x !== b).map(x => x.getAttribute('aria-expanded'))};
  b.click(); out.closedHidden = host.hidden; out.closedExpanded = b.getAttribute('aria-expanded'); out.closedFocus = document.activeElement === b;
  return out;
})"""
NODE_JS = r"""(() => {
  const M = CYM, g = M && cyGroups().find(x => x.id === state.cy.tab); if (!g) return null;
  const f = document.getElementById('cy-gfacts');
  return {level: g.level, epics: g.epics.map(e => e.k), due: Object.fromEntries(M.epics.map(e => [e.k, e.due])), cycle: {start: M.c.start, end: M.c.end}, facts: f ? f.textContent : null,
    ids: [...document.querySelectorAll('#cy-gkpis [data-kpi]')].map(t => t.dataset.kpi), cls: document.getElementById('cy-gkpis').className, texts: [...document.querySelectorAll('#cy-gkpis .kpi')].map(t => t.textContent)};
})()"""
PODS_JS = "CYM.tabGroups.filter(n => n.level === 'pod' && !n.virtual).slice(0, 3).map(n => n.id)"


def pods_of(epics: list) -> dict:
    """One pod = (project, label lower-cased); an epic counts once under each of its pods; no label, no pod."""
    pods: dict = collections.defaultdict(list)
    for e in epics:
        for key in {(e["p"], lab.lower()) for lab in (e.get("pl") or [])}:
            pods[key].append(e)
    return pods


def flight(es: list) -> list:
    return [e for e in es if e["s"] in N_FLIGHT]


def figures(epics: list, due: dict, cycle: dict) -> dict:
    pods = pods_of(epics)

    def planned(e):
        return bool(due.get(e["k"])) and cycle["start"] <= due[e["k"]] <= cycle["end"]

    idle = {k for k, es in pods.items() if not any(planned(e) for e in es)}
    wip = {k for k, es in pods.items() if len(flight(es)) > POD_LEVEL}
    return {"pods": pods, "idle": idle, "wip": wip, "wip_epics": {e["k"] for k in wip for e in flight(pods[k])}}


def oracle(data: dict, st: dict) -> dict:
    """The recount of a view: the epics of the release under the view's Projects, Teams and Commitment Type filters."""
    teams, commit, sel = set(st["teams"]), set(st["commit"]), set(st["projects"])
    scope = [e for e in data["epics"] if e["p"] in sel and st["release"] in e["fv"] and (e.get("c") or "Not Set") in commit
             and (not teams or any(t in teams for t in (e.get("tm") or ["(No Team)"])))]
    return figures(scope, st["due"], st["cycle"])


def nat(s: str) -> list:
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", s.lower())]


def check_pods(res: dict, data: dict, st, tag: str, ch) -> None:
    """The printed tiles, the lists behind them and the strips against the recount; every difference is appended to res['pod_bad']."""
    bad = res["pod_bad"]
    if not st:
        bad.append(f"{tag}: no Pods state")
        return
    if st["ids1"] != EPIC_IDS or st["ids2"] != POD_IDS:
        bad.append(f"{tag}: the tiles are {st['ids1']} and {st['ids2']}")
    if any(re.search(r"undefined|NaN|\[object", t) for t in st["texts"]):
        bad.append(f"{tag}: a tile prints undefined or NaN")
    if not st["shown"] or st["heading"] != f"Pods in {st['release']}":
        bad.append(f"{tag}: the Pods block is hidden or its heading is '{st['heading']}'")
    exp = oracle(data, st)
    n, idle, wip = len(exp["pods"]), len(exp["idle"]), len(exp["wip"])
    seen = res["pod_seen"]
    seen["views"] += 1
    seen["idle>0"] += idle > 0
    seen["wip>0"] += wip > 0
    seen["pods==0"] += n == 0
    ti, tw = st["tiles"]["idle"], st["tiles"]["wip"]
    if not ti or not tw:
        bad.append(f"{tag}: a Pods tile is missing")
        return
    want = (str(idle), str(wip)) if n else ("0", "0")
    if (ti["v"], tw["v"]) != want:
        bad.append(f"{tag}: the tiles print {ti['v']} / {tw['v']}; the independent recount is {want[0]} / {want[1]} of {n} pods")
    if n:
        m = re.match(r"of (\d+) pods? in", ti["s"])
        if not m or int(m.group(1)) != n:
            bad.append(f"{tag}: the idle sub-line '{ti['s']}' should name {n} pods")
        m = re.match(r"([\d,]+) epics? in flight in these pods", tw["s"])
        if wip and (not m or int(m.group(1).replace(",", "")) != len(exp["wip_epics"])):
            bad.append(f"{tag}: the in-flight sub-line prints '{tw['s']}', the recount is {len(exp['wip_epics'])} epics")
        if not wip and "no pod has more than" not in tw["s"]:
            bad.append(f"{tag}: the sub-line of 0 pods over the level is '{tw['s']}'")
        if ti["btn"] != bool(idle) or tw["btn"] != bool(wip):
            bad.append(f"{tag}: a value is a button only when above 0 (idle {ti['btn']}, wip {tw['btn']})")
    elif "no pods under these filters" not in ti["s"] or "no pods under these filters" not in tw["s"]:
        bad.append(f"{tag}: zero pods must say 'no pods under these filters'")
    for kind, keys in (("idle", exp["idle"]), ("wip", exp["wip"])):
        got = ch.js(LIST_JS + f"({json.dumps(kind)})")
        if not keys:
            if got is not None:
                bad.append(f"{tag}: a {kind} list can be opened with no pod to show")
            continue
        if not got:
            bad.append(f"{tag}: there is no {kind} button")
            continue
        rows = {(r["cells"][0], r["name"].lower()): r for r in got["rows"]}
        if set(rows) != set(keys):
            bad.append(f"{tag}: the {kind} list shows {len(rows)} pods, the recount {len(keys)}; differ on {sorted(set(rows) ^ set(keys))[:3]}")
        else:
            for (p, nm), r in rows.items():
                es = exp["pods"][(p, nm)]
                want_n = len(es) if kind == "idle" else len(flight(es))
                if int(r["cells"][2].replace(",", "")) != want_n or (kind == "idle" and r["cells"][3] != "0"):
                    bad.append(f"{tag}: {kind} row {nm} ({p}) prints {r['cells']}, the recount is {want_n}")
        order = [(r["name"], r["cells"][0]) for r in got["rows"]]
        if order != sorted(order, key=lambda x: (nat(x[0]), x[1])):
            bad.append(f"{tag}: the {kind} list is not alphabetical: {order[:4]}")
        ok = (got["expanded"] == "true" and not got["hidden"] and got["controls"] == "cy-podlist" and got["caption"] and got["colScopes"] and got["rowScopes"] and got["region"] and got["focus"]
              and got["hashSame"] and all(x == "false" for x in got["other"]) and got["closedHidden"] and got["closedExpanded"] == "false" and got["closedFocus"]
              and re.match(r"\d+ .*pods? .*, (show|hide) the list$", got["label"]) is not None)
        if not ok:
            bad.append(f"{tag}: the {kind} button or list misbehaves: {({k: v for k, v in got.items() if k != 'rows'})}")
        want_hdr = ["Pod", "Project", "Teams", "Epics in Release", f"Planned in {st['cycle']['name']}"] if kind == "idle" else ["Pod", "Project", "Teams", "Epics in Flight"]
        if got["hdr"] != want_hdr:
            bad.append(f"{tag}: the {kind} list header is {got['hdr']}")


def check_node(res: dict, data: dict, nd, tag: str) -> None:
    """A detail view: the strip of five, no 'flagged as blocked' in the facts line, and the two pod facts (project and team views only, only above 0) against the recount over the node's epics."""
    bad = res["pod_bad"]
    if not nd:
        bad.append(f"{tag}: no detail view")
        return
    if nd["ids"] != EPIC_IDS or "five" not in nd["cls"].split() or "six" in nd["cls"].split():
        bad.append(f"{tag}: the detail strip is {nd['ids']} ({nd['cls']})")
    if any(re.search(r"undefined|NaN", t) for t in nd["texts"]):
        bad.append(f"{tag}: a detail tile prints undefined or NaN")
    es = [e for e in data["epics"] if e["k"] in set(nd["epics"])]
    fig = figures(es, nd["due"], nd["cycle"])
    facts = nd["facts"] or ""
    if "flagged as blocked" in facts:
        bad.append(f"{tag}: the facts line still says 'flagged as blocked': {facts}")
    idle, wip = len(fig["idle"]), len(fig["wip"])
    if nd["level"] == "pod":
        if "idle pod" in facts or "epics in flight" in facts:
            bad.append(f"{tag}: a pod leaf shows pod facts: {facts}")
        return
    res["pod_seen"]["node_idle>0"] += idle > 0
    res["pod_seen"]["node_wip>0"] += wip > 0
    want_idle = f"{idle} idle {'pod' if idle == 1 else 'pods'}" if idle else None
    want_wip = f"{wip} {'pod' if wip == 1 else 'pods'} with more than {POD_LEVEL} epics in flight" if wip else None
    for what, w, present in (("idle", want_idle, "idle pod" in facts), ("wip", want_wip, "epics in flight" in facts)):
        if (w and w not in facts) or (not w and present):
            bad.append(f"{tag}: the facts line '{facts}' should {'say ' + repr(w) if w else 'not mention ' + what + ' pods'}")
