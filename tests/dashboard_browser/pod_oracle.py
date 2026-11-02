"""The independent recount of the Delivery Cycles Pods tiles (used by link_cycles.py; not a suite of its own).

The page counts pods with podRegistry / cyPodsOf / cyPodFig. This module counts them again from the BAKED epics, in plain Python, from the definitions the owner decided and nothing else:

  * a POD is one pod label per project, compared without regard to case; an epic with several labels counts once under each pod; an epic with no label is in no pod;
  * Idle Pods: pods that carry at least one epic of the release (under the page's Release, Projects and Teams filters) and have NO epic planned in the selected Delivery Cycles (the Delivery Cycle filter:
    one cycle, or both combined = the release start to the release end);
  * Pods With More Than 3 Epics In-Progress: more than POD_LEVEL epics In Progress or Validation among the epics of the release, and the number of those epics, each once;
  * the four proactive tiles (act_oracle below): Not-Started Epics Due Within 7 Days, Waiting Dependents Due Soon, Pods To Level, In-Progress Epics Without a Pod Label, with their lists.

The window of the selected cycles is spelled here again from the release window and the ticked cycles (window_of), never read from the page, so a section that shows the wrong cycles is caught; the section's
five headline tiles and the banner are recounted the same way (epic_tiles). The only things taken from the page are its filters, the as-of date and the planned date of each epic (plannedLater; the Target
Sprint calendar is proven by the other kinds of link_cycles.py).
`check_pods` compares the printed tiles and the two lists opened in turn; `check_node` compares the facts line and the strip of a detail view.
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import re

N_FLIGHT = ("In Progress", "Validation")
POD_LEVEL = 3                                    # the page's CY.podWip, the owner's reference level; spelled here on purpose, not read from the page
EPIC_IDS = ["planned", "done", "overdue", "next", "flagged"]
ACT_IDS = ["nsSoon", "wait", "level", "noPod", "idle", "wip"]     # the six tiles of #cy-kpis2, in order: the four proactive ones first, then Idle Pods and Pods With More Than 3 Epics In-Progress

# What the strips print, what the page was asked (its own state, not its pod figures), and the pod lists opened in turn (the button is focused and clicked, then clicked again).
POD_JS = r"""(() => {
  const M = CYM; if (!M || M.none) return null;
  const tile = (box, id) => { const t = document.querySelector(box + ' [data-kpi="' + id + '"]'); return t ? {v: t.querySelector('.v').textContent.trim(), s: t.querySelector('.s').textContent.trim(), btn: !!t.querySelector('.v button')} : null; };
  const ids = box => [...document.querySelectorAll(box + ' [data-kpi]')].map(t => t.dataset.kpi);
  return {release: state.release, projects: [...state.projects], teams: [...state.teams], dc: [...state.dc], cycleName: M.c.name, banner: (document.getElementById('cy-showing') || {}).textContent, bannerCycles: (document.getElementById('cy-banner') || {dataset: {}}).dataset.cycles,
    point: (document.getElementById('cy-point') || {}).textContent, podScope: (document.getElementById('cy-podscope') || {}).textContent,
    tiles1: Object.fromEntries([...document.querySelectorAll('#cy-kpis1 [data-kpi]')].map(t => [t.dataset.kpi, t.querySelector('.v').textContent.trim()])), due: Object.fromEntries(M.epics.map(e => [e.k, e.due])), ids1: ids('#cy-kpis1'), ids2: ids('#cy-kpis2'), asof: CY.asOf, grid: document.getElementById('cy-kpis2').className, tiles: Object.fromEntries(ids('#cy-kpis2').map(id => [id, tile('#cy-kpis2', id)])),
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
  const rows = [...document.querySelectorAll('#cy-weekly tbody tr')].map(r => [...r.children].map(c => c.textContent.trim()));
  return {level: g.level, epics: g.epics.map(e => e.k), due: Object.fromEntries(M.epics.map(e => [e.k, e.due])), release: state.release, dc: [...state.dc], asof: CY.asOf, facts: f ? f.textContent : null, weekly: rows,
    tilesV: Object.fromEntries([...document.querySelectorAll('#cy-gkpis [data-kpi]')].map(t => [t.dataset.kpi, t.querySelector('.v').textContent.trim()])),
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


def window_of(data: dict, release: str, dc) -> dict:
    """The cycles the Delivery Cycle filter leaves in, as one window: Delivery Cycle 1 runs from the release start to the end of W6 (start + 48 days), Delivery Cycle 2 from the next day to the release end; a
    release that ends by the end of W6 has Delivery Cycle 1 only; nothing ticked, or only a cycle the release does not have, means every cycle the release has. Spelled here on purpose."""
    start, end = (dt.date.fromisoformat(x) for x in data["windows"][release])
    w6 = start + dt.timedelta(days=48)
    cycles = {1: (start, end if w6 >= end else w6)}
    if w6 < end:
        cycles[2] = (w6 + dt.timedelta(days=1), end)
    ticked = [i for i in cycles if str(i) in {str(x) for x in dc}]
    shown = ticked or list(cycles)
    lo, hi = cycles[shown[0]][0], cycles[shown[-1]][1]
    name = f"Delivery Cycles {' and '.join(map(str, shown))}" if len(shown) > 1 else f"Delivery Cycle {shown[0]}"
    return {"start": lo.isoformat(), "end": hi.isoformat(), "name": name, "shown": shown, "all": len(shown) == len(cycles), "has2": 2 in cycles}


def epic_tiles(epics: list, asof: str, win: dict, calendar: dict) -> dict:
    """The five headline figures of the Cycles section from the baked epics: planned (planned date in the window), Done, Overdue (planned before the as-of day, not Done), due in the next 7 days, Flagged."""
    pl = [e for e in epics if planned_date(e, calendar) and win["start"] <= planned_date(e, calendar) <= win["end"]]
    nd = [e for e in pl if e["s"] != "Done"]
    hi = _days(asof, SOON_DAYS)
    return {"planned": len(pl), "done": len(pl) - len(nd), "overdue": sum(1 for e in nd if planned_date(e, calendar) < asof),
            "next": sum(1 for e in nd if asof <= planned_date(e, calendar) <= hi), "flagged": sum(1 for e in nd if e.get("fl"))}


def figures(epics: list, due: dict, cycle: dict) -> dict:
    pods = pods_of(epics)

    def planned(e):
        return bool(due.get(e["k"])) and cycle["start"] <= due[e["k"]] <= cycle["end"]

    idle = {k for k, es in pods.items() if not any(planned(e) for e in es)}
    wip = {k for k, es in pods.items() if len(flight(es)) > POD_LEVEL}
    return {"pods": pods, "idle": idle, "wip": wip, "wip_epics": {e["k"] for k in wip for e in flight(pods[k])}}


def oracle(data: dict, st: dict) -> dict:
    """The recount of a view: the epics of the release under the view's Projects and Teams filters."""
    teams, sel = set(st["teams"]), set(st["projects"])
    scope = [e for e in data["epics"] if e["p"] in sel and st["release"] in e["fv"]
             and (not teams or any(t in teams for t in (e.get("tm") or ["(No Team)"])))]
    return figures(scope, st["due"], window_of(data, st["release"], st["dc"]))


def nat(s: str) -> list:
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", s.lower())]


def check_pods(res: dict, data: dict, st, tag: str, ch) -> None:
    """The printed tiles, the lists behind them and the strips against the recount; every difference is appended to res['pod_bad']."""
    bad = res["pod_bad"]
    if not st:
        bad.append(f"{tag}: no Pods state")
        return
    if st["ids1"] != EPIC_IDS or st["ids2"] != ACT_IDS or "three" not in st["grid"].split():
        bad.append(f"{tag}: the tiles are {st['ids1']} and {st['ids2']}")
    if any(re.search(r"undefined|NaN|\[object", t) for t in st["texts"]):
        bad.append(f"{tag}: a tile prints undefined or NaN")
    if "Only Idle Pods follows the cycle" not in (st.get("podScope") or ""):
        bad.append(f"{tag}: the Pods block does not say that only Idle Pods follows the cycle: {st.get('podScope')!r}")
    if not st["shown"] or st["heading"] != f"Pods in {st['release']}":
        bad.append(f"{tag}: the Pods block is hidden or its heading is '{st['heading']}'")
    win = window_of(data, st["release"], st["dc"])
    cal = {s["n"]: s["end"] for s in data["sprints"]}
    want_banner = f"Showing {win['name']}{' combined' if len(win['shown']) > 1 else ''} · {win['start']} to {win['end']}"
    if st["banner"] != want_banner or st["cycleName"] != win["name"] or st["bannerCycles"] != "+".join(map(str, win["shown"])):
        bad.append(f"{tag}: the banner says {st['banner']!r} ({st['bannerCycles']}), the recount {want_banner!r}")
    if win["has2"] and "Delivery Cycle filter" not in (st["point"] or ""):
        bad.append(f"{tag}: the banner does not point to the Delivery Cycle filter: {st['point']!r}")
    if win["has2"] and win["all"] and "Both cycles together" not in (st["point"] or ""):
        bad.append(f"{tag}: both cycles shown, and the banner does not say they are counted together: {st['point']!r}")
    if win["has2"] and not win["all"] and "planned outside it are not counted" not in (st["point"] or ""):
        bad.append(f"{tag}: one cycle shown, and the banner does not say what is left out: {st['point']!r}")
    if not win["has2"] and "no Delivery Cycle 2" not in (st["point"] or ""):
        bad.append(f"{tag}: a release with one cycle must say it has no Delivery Cycle 2: {st['point']!r}")
    want_t = epic_tiles(_scope(data, st), st["asof"], win, cal)
    for k, v in want_t.items():
        got = st["tiles1"].get(k)
        if k == "flagged" and got == "–":
            continue                                               # the Flagged field is not in this build
        if got is None or got.replace(",", "") != str(v):
            bad.append(f"{tag}: the {k} tile prints {got}, the recount of {win['name']} ({win['start']} to {win['end']}) is {v}")
    seen = res["pod_seen"]
    seen["tiles:" + ("both" if win["all"] and win["has2"] else "one")] += 1
    check_act(res, data, st, tag, ch)
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
        m = re.match(r"([\d,]+) epics? in-progress in these pods", tw["s"])
        if wip and (not m or int(m.group(1).replace(",", "")) != len(exp["wip_epics"])):
            bad.append(f"{tag}: the in-progress sub-line prints '{tw['s']}', the recount is {len(exp['wip_epics'])} epics")
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
        want_hdr = ["Pod", "Project", "Teams", "Epics in Release", f"Planned in {window_of(data, st['release'], st['dc'])['name']}"] if kind == "idle" else ["Pod", "Project", "Teams", "Epics In-Progress"]
        if got["hdr"] != want_hdr:
            bad.append(f"{tag}: the {kind} list header is {got['hdr']}")


def check_weekly(res: dict, es: list, nd: dict, win: dict, cal: dict, tag: str) -> None:
    """The weekly table of a detail view: seven-day weeks from the start of the window (the release start when both cycles are shown), as many rows as the window has weeks, and in each row the Planned,
    Done and Not Done counts of the epics whose planned date falls in that week; the rows add up to the Planned tile."""
    bad = res["pod_bad"]
    start, end = dt.date.fromisoformat(win["start"]), dt.date.fromisoformat(win["end"])
    planned = [e for e in es if planned_date(e, cal) and win["start"] <= planned_date(e, cal) <= win["end"]]
    rows = nd["weekly"]
    if not planned:
        if rows:
            bad.append(f"{tag}: a weekly table is shown for a view with nothing planned in {win['name']}")
        return
    n_weeks = -(-((end - start).days + 1) // 7)
    res["pod_seen"]["weekly_rows>7" if n_weeks > 7 else "weekly_rows<=7"] += 1
    if len(rows) != n_weeks:
        bad.append(f"{tag}: the weekly table has {len(rows)} rows, {win['name']} has {n_weeks} weeks")
        return
    tot = 0
    for w, r in enumerate(rows):
        ws, we = start + dt.timedelta(days=7 * w), min(start + dt.timedelta(days=7 * w + 6), end)
        in_w = [e for e in planned if ws.isoformat() <= planned_date(e, cal) <= we.isoformat()]
        want = [f"Week {w + 1}", f"{ws.isoformat()} to {we.isoformat()}", str(len(in_w)), str(sum(1 for e in in_w if e["s"] == "Done")), str(sum(1 for e in in_w if e["s"] != "Done"))]
        got = [r[0], r[1]] + [x.replace(",", "") for x in r[2:5]]
        if got != want:
            bad.append(f"{tag}: weekly row {w + 1} is {got}, the recount {want}")
        tot += len(in_w)
    if tot != len(planned):
        bad.append(f"{tag}: the weekly rows add up to {tot}, the recount of planned is {len(planned)}")


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
    win = window_of(data, nd["release"], nd["dc"])
    fig = figures(es, nd["due"], win)
    cal = {s["n"]: s["end"] for s in data["sprints"]}
    for k, v in epic_tiles(es, nd["asof"], win, cal).items():
        got = nd["tilesV"].get(k)
        if not (k == "flagged" and got == "–") and (got is None or got.replace(",", "") != str(v)):
            bad.append(f"{tag}: the detail {k} tile prints {got}, the recount of {win['name']} is {v}")
    check_weekly(res, es, nd, win, cal, tag)
    facts = nd["facts"] or ""
    if "flagged as blocked" in facts:
        bad.append(f"{tag}: the facts line still says 'flagged as blocked': {facts}")
    idle, wip = len(fig["idle"]), len(fig["wip"])
    if nd["level"] == "pod":
        if "idle pod" in facts or "epics in-progress" in facts:
            bad.append(f"{tag}: a pod leaf shows pod facts: {facts}")
        return
    res["pod_seen"]["node_idle>0"] += idle > 0
    res["pod_seen"]["node_wip>0"] += wip > 0
    want_idle = f"{idle} idle {'pod' if idle == 1 else 'pods'}" if idle else None
    want_wip = f"{wip} {'pod' if wip == 1 else 'pods'} with more than {POD_LEVEL} epics in-progress" if wip else None
    for what, w, present in (("idle", want_idle, "idle pod" in facts), ("wip", want_wip, "epics in-progress" in facts)):
        if (w and w not in facts) or (not w and present):
            bad.append(f"{tag}: the facts line '{facts}' should {'say ' + repr(w) if w else 'not mention ' + what + ' pods'}")


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------
# The four proactive tiles: Not-Started Epics Due Within 7 Days, Waiting Dependents Due Soon, Pods To Level, In-Progress Epics Without a Pod Label.
# Recounted from the baked payload in plain Python with the definitions the owner decided, spelled here on purpose (never read from the page):
NS_STATUSES = ("Candidate", "New", "In Definition", "Ready for Dev")
SOON_DAYS = 7                                    # the page's CY.next
LEVEL_SPREAD = 0.40                              # the page's CY.levelSpread: (busiest - lightest) / the team's in-progress epics
MIN_SAMPLE = 5                                   # the page's MIN_N: a team is evaluated from this many in-progress epics
LEVEL_WORDS = {"busiest": "Busiest", "lightest": "Lightest", "between": "In between"}

LIST2_JS = r"""((kind) => {
  const b = document.querySelector('#cy-kpis2 [data-cyact="pods"][data-cyval="' + kind + '"]'), host = document.getElementById('cy-podlist'); if (!b) return null;
  const hash = location.hash, txt = n => n.textContent.replace(/\s+/g, ' ').trim(); b.focus(); b.click();
  const rows = [...host.querySelectorAll('tbody tr')].map(r => ({grp: r.classList.contains('cyinit'), th: txt(r.querySelector('th')), rep: !!r.querySelector('th .cysub'), cells: [...r.querySelectorAll('td')].map(txt),
    hrefs: [...r.querySelectorAll('a[href]')].map(a => a.getAttribute('href')), tips: [...r.querySelectorAll('a[data-tip]')].map(a => a.getAttribute('data-tip'))}));
  const out = {rows, hdr: [...host.querySelectorAll('thead th')].map(txt), expanded: b.getAttribute('aria-expanded'), hidden: host.hidden, controls: b.getAttribute('aria-controls'), label: b.getAttribute('aria-label'),
    caption: !!host.querySelector('caption.sr'), colScopes: [...host.querySelectorAll('thead th')].every(h => h.getAttribute('scope') === 'col'), rowScopes: [...host.querySelectorAll('tbody th')].every(h => ['row', 'rowgroup'].includes(h.getAttribute('scope'))),
    region: !!host.querySelector('.tablewrap[role="region"][tabindex="0"]'), focus: document.activeElement === b, hashSame: location.hash === hash, note: txt(host.querySelector('.cymeta')),
    noteHrefs: [...host.querySelectorAll('.cymeta a[href]')].map(a => a.getAttribute('href')),
    other: [...document.querySelectorAll('#cy-kpis2 [data-cyact="pods"]')].filter(x => x !== b).map(x => x.getAttribute('aria-expanded')), keyKind: document.activeElement === b};
  b.click(); out.closedHidden = host.hidden; out.closedExpanded = b.getAttribute('aria-expanded'); out.closedFocus = document.activeElement === b;
  return out;
})"""


def _days(iso: str, n: int) -> str:
    import datetime as dt
    return (dt.date.fromisoformat(iso) + dt.timedelta(days=n)).isoformat()


def _scope(data: dict, st: dict) -> list:
    teams, sel = set(st["teams"]), set(st["projects"])
    return [e for e in data["epics"] if e["p"] in sel and st["release"] in e["fv"]
            and (not teams or any(t in teams for t in (e.get("tm") or ["(No Team)"])))]


def _teams(e: dict) -> list:
    return e.get("tm") or ["(No Team)"]


def _pods(e: dict) -> set:
    return {l.lower() for l in (e.get("pl") or [])}


def planned_date(e: dict, calendar: dict):
    """The later of the due date and the end of the Target Sprint when both exist, else the one that exists (a Target Sprint outside the calendar counts as none)."""
    ts = calendar.get(e.get("ts"))
    dd = e.get("dd")
    return max(dd, ts) if dd and ts else (dd or ts)


def act_oracle(data: dict, st: dict) -> dict:
    scope = _scope(data, st)
    asof = st["asof"]
    hi = _days(asof, SOON_DAYS)
    cal = {s["n"]: s["end"] for s in data["sprints"]}
    by_team: dict = collections.defaultdict(list)                  # (project, team) -> the team's epics under the filters (every status)
    for e in scope:
        for t in _teams(e):
            by_team[(e["p"], t)].append(e)
    team_pods = {k: {p for e in es for p in _pods(e)} for k, es in by_team.items()}

    def rows_by_team(pred):
        """{(project, team, '*'): n} plus {(project, team, pod key or '' for No Pod Label): n} as the hierarchy shows them: pod rows only in a team that has pods at all."""
        out = {}
        for (p, t), es in by_team.items():
            hit = [e for e in es if pred(e)]
            if not hit:
                continue
            out[(p, t, "*")] = len(hit)
            for k in team_pods[(p, t)]:
                n = sum(1 for e in hit if k in _pods(e))
                if n:
                    out[(p, t, k)] = n
            if team_pods[(p, t)]:
                n = sum(1 for e in hit if not _pods(e))
                if n:
                    out[(p, t, "")] = n
        return out

    is_ns = lambda e: e["s"] in NS_STATUSES and (lambda d: bool(d) and asof <= d <= hi)(planned_date(e, cal))     # noqa: E731
    in_flight = lambda e: e["s"] in N_FLIGHT                                                                      # noqa: E731
    ns = [e for e in scope if is_ns(e)]
    flight = [e for e in scope if in_flight(e)]
    nopod = [e for e in flight if not _pods(e)]
    # 2. Pods To Level
    level_rows, flagged, ends, multi = {}, [], set(), 0
    for (p, t), es in by_team.items():
        pods = sorted(k for k in team_pods[(p, t)] if any(k in _pods(e) and e["s"] != "Done" for e in es))
        if len(pods) < 2:
            continue
        multi += 1
        n = {k: sum(1 for e in es if k in _pods(e) and in_flight(e)) for k in pods}
        total, top, low = sum(n.values()), max(n.values()), min(n.values())
        if total >= MIN_SAMPLE and (top - low) * 100 >= LEVEL_SPREAD * 100 * total - 1e-6:
            flagged.append((p, t))
            for k, v in n.items():
                role = "busiest" if v == top else "lightest" if v == low else "between"
                level_rows[(p, t, k)] = (v, int(100 * v / total + 0.5), LEVEL_WORDS[role])
                if role != "between":
                    ends.add((p, k))
    # 3. Waiting Dependents Due Soon
    by_key = {e["k"]: e for e in data["epics"]}
    in_scope = {e["k"] for e in scope}
    items, groups = {}, {}
    for a, b in {(d[0], d[1]) for d in data["deps"]}:
        prov = by_key.get(b)
        dep = by_key.get(a) or data["ext"].get(a)
        if b not in in_scope or not prov or not dep or dep["s"] == "Done" or prov["s"] == "Done":
            continue
        date = dep.get("dd") or cal.get(dep.get("ts"))             # the Dependencies rule for the waiting item: the due date wins over the Target Sprint
        if not date or not asof <= date <= hi:
            continue
        items[a] = (date, bool(items.get(a, ("", False))[1]) or bool(_pods(prov)))
        for t in _teams(prov):
            for k in sorted(_pods(prov)) or [""]:                    # under each of its pods; with none, under No Pod Label (or the team itself when the team has no pods: shown the same way)
                g = groups.setdefault((prov["p"], t, k), {"keys": set(), "pairs": set(), "first": date})
                g["keys"].add(a)
                g["pairs"].add((b, a))
                g["first"] = min(g["first"], date)
    return {"ns": {e["k"] for e in ns}, "ns_rfd": {e["k"] for e in ns if e["s"] == "Ready for Dev"}, "ns_rows": rows_by_team(is_ns),
            "flight": len(flight), "nopod": len(nopod), "nopod_rows": {(p, t): (len([e for e in es if in_flight(e) and not _pods(e)]), len([e for e in es if in_flight(e)]))
                                                                        for (p, t), es in by_team.items() if any(in_flight(e) and not _pods(e) for e in es)},
            "multi": multi, "flagged": flagged, "level_rows": level_rows, "level_pods": len(ends),
            "wait_items": items, "wait_pod": sum(1 for v in items.values() if v[1]), "wait_groups": groups}


def _num(s: str) -> int:
    return int(s.replace(",", ""))


def _key_in(href: str) -> set:
    import urllib.parse
    jql = urllib.parse.parse_qs(urllib.parse.urlsplit(href).query).get("jql", [""])[0]
    m = re.fullmatch(r"key in \(([^)]*)\)", jql)
    return {x.strip() for x in m.group(1).split(",")} if m else set()


def check_act(res: dict, data: dict, st: dict, tag: str, ch) -> None:
    """The six tiles and the four new lists against the recount; every difference goes to res['pod_bad']."""
    bad, seen = res["pod_bad"], res["pod_seen"]
    X = act_oracle(data, st)
    T = st["tiles"]
    if not all(T.get(i) for i in ACT_IDS):
        bad.append(f"{tag}: a Pods tile is missing: {list(T)}")
        return
    seen["ns>0"] += bool(X["ns"])
    seen["ns==0"] += not X["ns"]
    seen["wait>0"] += bool(X["wait_items"])
    seen["wait==0"] += not X["wait_items"]
    seen["level>0"] += X["level_pods"] > 0
    seen["level==0"] += X["level_pods"] == 0
    seen["noPod>0"] += X["nopod"] > 0
    seen["wait_withpod>0"] += X["wait_pod"] > 0
    seen["wait_nopod>0"] += len(X["wait_items"]) > X["wait_pod"]
    # ---- the tile values and sub-lines
    want = {"nsSoon": len(X["ns"]), "wait": len(X["wait_items"]), "level": X["level_pods"], "noPod": X["nopod"]}
    for k, w in want.items():
        t = T[k]
        if t["v"] != str(w):
            bad.append(f"{tag}: tile {k} prints {t['v']}, the independent recount is {w}")
        if t["btn"] != bool(w):
            bad.append(f"{tag}: tile {k} value is a button only when above 0 (button {t['btn']}, value {w})")
    s = T["nsSoon"]["s"]
    if X["ns"] and not re.fullmatch(rf"{len(X['ns_rfd'])} of them Ready for Dev", s):
        bad.append(f"{tag}: nsSoon sub-line '{s}', the recount is {len(X['ns_rfd'])} Ready for Dev")
    if not X["ns"] and not s.startswith("none planned"):
        bad.append(f"{tag}: nsSoon zero sub-line is '{s}'")
    s = T["wait"]["s"]
    if X["wait_items"] and s != f"{X['wait_pod']} wait on an epic with a pod label":
        bad.append(f"{tag}: wait sub-line '{s}', the recount is {X['wait_pod']} with a pod label")
    s = T["level"]["s"]
    if X["level_pods"] and s != f"in {len(X['flagged'])} of {X['multi']} {'team' if X['multi'] == 1 else 'teams'} with two or more pods":
        bad.append(f"{tag}: level sub-line '{s}', the recount is {len(X['flagged'])} of {X['multi']} teams")
    s = T["noPod"]["s"]
    share = f" ({int(100 * X['nopod'] / X['flight'] + 0.5)}%)" if X["flight"] >= MIN_SAMPLE else ""
    if X["flight"] and s != f"of {X['flight']} {'epic' if X['flight'] == 1 else 'epics'} in-progress{share}":
        bad.append(f"{tag}: noPod sub-line '{s}', the recount is {X['nopod']} of {X['flight']}{share}")
    # ---- the lists
    for kind in ("nsSoon", "wait", "level", "noPod"):
        got = ch.js(LIST2_JS + f"({json.dumps(kind)})")
        if not want[kind]:
            if got is not None:
                bad.append(f"{tag}: the {kind} list can be opened with nothing to show")
            continue
        if not got:
            bad.append(f"{tag}: there is no {kind} button")
            continue
        ok = (got["expanded"] == "true" and not got["hidden"] and got["controls"] == "cy-podlist" and got["caption"] and got["colScopes"] and got["rowScopes"] and got["region"] and got["focus"]
              and got["hashSame"] and all(x == "false" for x in got["other"]) and got["closedHidden"] and got["closedExpanded"] == "false" and got["closedFocus"]
              and re.search(r", (show|hide) the list$", got["label"]) is not None)
        if not ok:
            bad.append(f"{tag}: the {kind} button or list misbehaves: {({k: v for k, v in got.items() if k not in ('rows', 'tips')})}")
        if any(re.search(r"undefined|NaN|\[object", r["th"] + " ".join(r["cells"])) for r in got["rows"]):
            bad.append(f"{tag}: the {kind} list prints undefined or NaN")
        {"nsSoon": _check_ns, "level": _check_level, "noPod": _check_nopod, "wait": _check_wait}[kind](bad, X, got, tag)


def _check_ns(bad, X, got, tag):
    if got["hdr"] != ["Team", "Pod", "Project", "Epics"]:
        bad.append(f"{tag}: the nsSoon header is {got['hdr']}")
    rows = {}
    for r in got["rows"]:
        pod, proj, n = r["cells"]
        rows[(proj, r["th"], "*" if not r["rep"] else ("" if pod == "No Pod Label" else pod.lower()))] = _num(n)
    exp = X["ns_rows"]
    if rows != exp:                                                 # pod keys are lower case on both sides (the page shows the first spelling)
        bad.append(f"{tag}: the nsSoon rows differ from the recount: {sorted(set(rows.items()) ^ set(exp.items()))[:4]}")
    if f"{len(X['ns'])} not started" not in got["note"]:
        bad.append(f"{tag}: the nsSoon note does not name {len(X['ns'])} epics: {got['note'][:90]}")


def _check_level(bad, X, got, tag):
    if got["hdr"] != ["Team", "Project", "Pod", "Epics In-Progress", "Share of Team's In-Progress Epics", "Position"]:
        bad.append(f"{tag}: the level header is {got['hdr']}")
    rows = {}
    for r in got["rows"]:
        proj, pod, n, share, pos = r["cells"]
        rows[(proj, r["th"], pod.lower())] = (_num(n), int(share.rstrip("%")), pos)
    exp = {(p, t, k): v for (p, t, k), v in X["level_rows"].items()}
    if rows != exp:
        bad.append(f"{tag}: the level rows differ from the recount: {sorted(set(rows.items()) ^ set(exp.items()))[:4]}")
    if {w for _, _, w in rows.values()} - {"Busiest", "Lightest", "In between"}:
        bad.append(f"{tag}: a level position is not one of the three words")
    for r in got["rows"]:                                           # a count of 0 has no link; above 0 it is a Jira query
        n = _num(r["cells"][2])
        if bool(n) != bool(r["hrefs"]):
            bad.append(f"{tag}: level row {r['th']} / {r['cells'][1]} has {n} in-progress and {len(r['hrefs'])} links")


def _check_nopod(bad, X, got, tag):
    if got["hdr"] != ["Team", "Project", "Without Pod Label", "In-Progress", "Share Without"]:
        bad.append(f"{tag}: the noPod header is {got['hdr']}")
    rows = {}
    for r in got["rows"]:
        proj, n, fl, share = r["cells"]
        rows[(proj, r["th"])] = (_num(n), _num(fl), share)
    exp = {k: (n, f, f"{int(100 * n / f + 0.5)}%" if f >= MIN_SAMPLE else "–") for k, (n, f) in X["nopod_rows"].items()}
    if rows != exp:
        bad.append(f"{tag}: the noPod rows differ from the recount: {sorted(set(rows.items()) ^ set(exp.items()))[:4]}")


def _check_wait(bad, X, got, tag):
    if got["hdr"] != ["Epic Waited On", "Waiting Item", "Planned Date", "Status"]:
        bad.append(f"{tag}: the wait header is {got['hdr']}")
    groups, cur = {}, None
    rx = re.compile(r"^(?P<team>.+?), (?P<pod>[^,]+) \((?P<proj>[^)]+)\): (?P<n>[\d,]+) waiting, earliest (?P<d>\S+)$")
    for r in got["rows"]:
        if r["grp"]:
            m = rx.match(r["th"])
            if not m:
                bad.append(f"{tag}: a wait group header does not parse: {r['th']}")
                continue
            cur = (m["proj"], m["team"], "" if m["pod"] == "No Pod Label" else m["pod"].lower())
            groups[cur] = {"n": _num(m["n"]), "first": m["d"], "pairs": set(), "keys": _key_in(r["hrefs"][0]) if r["hrefs"] else None, "dates": []}
        elif cur:
            dep = r["cells"][0].split()[0]
            groups[cur]["pairs"].add((r["th"], dep))
            groups[cur]["dates"].append(r["cells"][1])
    exp = {k: g for k, g in X["wait_groups"].items()}
    if set(groups) != set(exp):
        bad.append(f"{tag}: the wait groups differ from the recount: {sorted(set(groups) ^ set(exp))[:3]}")
        return
    for k, g in exp.items():
        p = groups[k]
        if p["n"] != len(g["keys"]) or p["first"] != g["first"] or p["pairs"] != g["pairs"] or p["keys"] != g["keys"] or min(p["dates"]) != g["first"]:
            bad.append(f"{tag}: wait group {k} prints {p['n']} (earliest {p['first']}), {len(p['pairs'])} pairs; the recount is {len(g['keys'])} (earliest {g['first']}), {len(g['pairs'])} pairs; link keys equal: {p['keys'] == g['keys']}")
    note_keys = _key_in(got["noteHrefs"][0]) if got["noteHrefs"] else set()
    if note_keys != set(X["wait_items"]):
        bad.append(f"{tag}: the wait list's total link finds {len(note_keys)} items, the recount is {len(X['wait_items'])}")
    for r in got["rows"]:
        if r["grp"]:
            for tip, h in zip(r["tips"], r["hrefs"]):
                if len(_key_in(h)) > 3 and not re.search(r"exact", tip, re.I):
                    bad.append(f"{tag}: a key list of {len(_key_in(h))} says nothing about being exact")
