"""The independent recount of the Delivery Cycles Pods tiles (used by link_cycles.py; not a suite of its own).

The page counts pods with podRegistry / cyPodsOf / cyPodFig. This module counts them again from the BAKED epics, in plain Python, from the definitions the owner decided and nothing else:

  * a POD is one pod label per project, compared without regard to case; an epic with several labels counts once under each pod; an epic with no label is in no pod;
  * Pods Without Planned Epics (tile id idle): pods that carry at least one epic of the release (under the page's Release, Projects and Teams filters) and have NO epic planned in the selected Delivery Cycles (the Delivery Cycle filter:
    one cycle, or both combined = the release start to the release end);
  * Pods Over 3 Epics (tile id wip): more than POD_LEVEL epics whose status is In Progress (N_WIP, Validation NOT counted: the owner's decision for this tile and its list only) among the epics PLANNED IN THE
    SELECTED CYCLES (the Planned tile's epics), and the number of those epics, each once. Every other active figure (Busiest and Lightest Pods, Active Epics Without Pod, the release bars) keeps N_FLIGHT = In Progress or Validation ("active");
    all six Pods tiles count only the epics planned in the selected cycles (the pods themselves, for Pods Without Planned Epics, are the pods of the release);
  * the four proactive tiles (act_oracle below): Not Started Due Soon, Waiting Items Due Soon, Busiest and Lightest Pods, Active Epics Without Pod, with their lists;
  * Took Over 7 Days (long_tile): the Done epics planned in the selected cycles that have a cycle time (EDCT) and are outside CT_EXCLUDED; of them, those with a cycle time MORE than LONG_DAYS;
  * the pod filter (pod_scope): with exactly one project selected, an epic passes when it carries any chosen pod (or has no pod label and No Pod Label is chosen); every figure is recounted over the epics that pass, and
    only the chosen pods are pods (an epic with two pods, one chosen, is in the chosen pod only).

The window of the selected cycles is spelled here again from the release window and the ticked cycles (window_of), never read from the page, so a section that shows the wrong cycles is caught; the section's
six headline tiles and the banner are recounted the same way (epic_tiles). The only things taken from the page are its filters, the as-of date and the planned date of each epic (plannedDue; the due date, else the Target
Sprint calendar is proven by the other kinds of link_cycles.py).
`check_pods` compares the printed tiles and the two lists opened in turn; `check_page` compares the page-level Planned and Done by Week table (the weeks, the Before W1 row, the Result wording, the sum against the
Planned tile, the folded "after release end" number), the pod and team rows opened to their epics (every row's epics, week and flags recounted below), and checks that the removed features (detail views, status chips, the
Find box, the After Release End line, the explainer notes) are gone.
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import math
import re

N_FLIGHT = ("In Progress", "Validation")             # the other active figures of the page (CLASS.flight)
N_WIP = ("In Progress",)                         # the one tile Pods With More Than 3 Epics In Progress: Validation is not counted
POD_LEVEL = 3                                    # the page's CY.podWip, the owner's reference level; spelled here on purpose, not read from the page
EPIC_IDS = ["planned", "done", "long", "overdue", "next", "flagged"]     # the six headline tiles, in order: Took Over 7 Days is third
ACT_IDS = ["nsSoon", "wait", "level", "noPod", "idle", "wip"]     # the six tiles of #cy-kpis2, in order: the four proactive ones first, then Pods Without Planned Epics and Pods Over 3 Epics
LONG_DAYS = 7                                    # the page's CY.longCycle: Took Over 7 Days counts a cycle time MORE than this (strictly); spelled here on purpose
CT_EXCLUDED = ("maintenance", "sow")             # the Issue Categories Cycle Time per Release leaves out (the page's AI_EXCLUDED_CATEGORIES), compared without regard to case; spelled here on purpose
NO_POD = "~none"                                 # the token of the No Pod Label chip in the address (pd=...)

# What the strips print, what the page was asked (its own state, not its pod figures), and the pod lists opened in turn (the button is focused and clicked, then clicked again).
POD_JS = r"""(() => {
  const M = CYM; if (!M || M.none) return null;
  const tile = (box, id) => { const t = document.querySelector(box + ' [data-kpi="' + id + '"]'); return t ? {v: t.querySelector('.v').textContent.trim(), s: t.querySelector('.s').textContent.trim(), btn: !!t.querySelector('.v button')} : null; };
  const ids = box => [...document.querySelectorAll(box + ' [data-kpi]')].map(t => t.dataset.kpi);
  return {release: state.release, projects: [...state.projects], teams: [...state.teams], dc: [...state.dc], cycleName: M.c.name, banner: (document.getElementById('cy-showing') || {}).textContent, bannerCycles: (document.getElementById('cy-banner') || {dataset: {}}).dataset.cycles,
    point: (document.getElementById('cy-point') || {}).textContent, pods: [...state.pods],
    long: (() => { const t = document.querySelector('#cy-kpis1 [data-kpi="long"]'); if (!t) return null; const a = t.querySelector('.v a');
      return {v: t.querySelector('.v').textContent.trim(), s: t.querySelector('.s').textContent.trim(), l: t.querySelector('.l').textContent.trim(), href: a ? a.getAttribute('href') : null, tip: a ? a.getAttribute('data-tip') : null}; })(),
    tiles1: Object.fromEntries([...document.querySelectorAll('#cy-kpis1 [data-kpi]')].map(t => [t.dataset.kpi, t.querySelector('.v').textContent.trim()])), due: Object.fromEntries(M.epics.map(e => [e.k, e.due])), ids1: ids('#cy-kpis1'), ids2: ids('#cy-kpis2'), asof: CY.asOf, grid: document.getElementById('cy-kpis2').className, tiles: Object.fromEntries(ids('#cy-kpis2').map(id => [id, tile('#cy-kpis2', id)])),
    texts: [...document.querySelectorAll('#cy-kpis1 .kpi, #cy-kpis2 .kpi')].map(t => t.textContent), shown: document.getElementById('cy-pods').hidden === false,
    heading: document.getElementById('cy-pods-h').textContent,
    plannedCap: (() => { const t = document.querySelector('#cy-kpis1 [data-kpi="planned"] .s'); return {text: t.textContent.replace(/\s+/g, ' ').trim(), hrefs: [...t.querySelectorAll('a[href]')].map(a => ({href: a.getAttribute('href'), text: a.textContent.trim()}))}; })()};
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
# The page-level Planned and Done by Week table, the Projects, Teams and Pods table opened to the epics, and what must be gone.
PAGE_JS = r"""(() => {
  const M = CYM; if (!M || M.none) return null;
  const txt = n => n.textContent.replace(/\s+/g, ' ').trim();
  const wk = document.getElementById('cy-wktable');
  const heads = [...document.querySelectorAll('#cy-sec h3')].map(txt);
  const ov = document.getElementById('cy-ovtable'), ovBlock = ov && ov.closest('.cyblock');
  const hidden0 = ov ? [...ov.querySelectorAll('#cy-ovbody tr[data-id]')].map(r => ({id: r.dataset.id, lvl: r.dataset.lvl, hidden: r.hidden})) : [];
  const out = {
    release: state.release, projects: [...state.projects], teams: [...state.teams], dc: [...state.dc], pods: [...state.pods], asof: CY.asOf,
    weekly: wk ? {hdr: [...wk.querySelectorAll('thead th')].map(txt), hdrCls: [...wk.querySelectorAll('thead th')].map(h => h.className), rows: [...wk.querySelectorAll('tbody tr')].map(r => ({pctCls: r.children[5].className, pctLinks: r.children[5].querySelectorAll('a').length, cells: [...r.children].map((c, i) => i === 0 ? txt(c).replace(/^\u25cf\s*/, '') : txt(c)), cur: r.getAttribute('aria-current'), dot: !!r.querySelector('th .cydot'), weight: +getComputedStyle(r.children[0]).fontWeight, tint: getComputedStyle(r.children[1]).backgroundColor, cls: r.className, links: [...r.querySelectorAll('a[href]')].map(a => ({href: a.getAttribute('href'), text: txt(a)}))})), caption: txt(wk.querySelector('caption')), note: txt(document.querySelector('#cy-weekly > .cymeta'))} : null,
    order: ['cy-banner', 'cy-kpis1', 'cy-pods', 'cy-weekly', 'cy-ovtable', 'cy-cap'].map(id => { const e = document.getElementById(id); return e ? Math.round(e.getBoundingClientRect().top + scrollY) : null; }),
    heads, firstHeadings: [...document.querySelectorAll('#cy-sec > *')].map(e => e.id || e.className || e.tagName).slice(0, 8),
    gone: {find: !!document.getElementById('cy-find') || !!document.getElementById('cy-findstat'), chips: document.querySelectorAll('#cy-sec .pill, #cy-sec .chips:not(#f-cypod)').length, after: !!document.getElementById('cy-after'), sub: !!document.getElementById('cy-sub'),
      detail: !!document.querySelector('#cy-sec .cydetail, #cy-crumb, #cy-panel, #cy-gkpis, #cy-concerns, #cy-lists'), notes: !!document.getElementById('cy-notes'), nameButtons: document.querySelectorAll('#cy-sec .cyname button, #cy-sec button.cyname, #cy-sec [data-cyact="open"]').length,
      explainer: ovBlock ? [...ovBlock.children].some(c => c.classList.contains('cymeta')) : false, afterText: /After Release End/.test(document.getElementById('cy-sec').textContent)},
    ovBlock: ovBlock ? [...ovBlock.children].map(c => c.tagName + '.' + c.className) : null,
    toggles: ov ? [...ov.querySelectorAll('[data-cyact]')].map(b => b.dataset.cyact) : [], hidden0,
    bodyIds: [...document.querySelectorAll('#cy-body > *')].map(e => e.id || e.className)};
  return out;
})()"""
EXPAND_JS = r"""(() => {
  const ex = document.querySelector('[data-cyact="expall"]'); if (!ex) return null;
  ex.click();
  const txt = n => n.textContent.replace(/\s+/g, ' ').trim();
  const rows = [...document.querySelectorAll('#cy-ovbody tr[data-id]')], by = new Map(rows.map(r => [r.dataset.id, r]));
  const name = r => txt(r.querySelector('.cyname'));
  const lists = [], expandable = [];
  rows.forEach(r => {
    const tg = r.querySelector('.cytgl'); if (tg) expandable.push({lvl: r.dataset.lvl, name: name(r), expanded: tg.getAttribute('aria-expanded'), hasEpics: !!document.getElementById('cye-' + r.dataset.id), ctl: tg.getAttribute('aria-controls')});
    if (r.dataset.lvl !== 'epics') return;
    const node = by.get(r.dataset.par), team = node.dataset.lvl === 'pod' ? by.get(node.dataset.par) : node, proj = by.get(team.dataset.par);
    const tb = r.querySelector('table.cyepl');
    lists.push({lvl: node.dataset.lvl, project: name(proj), team: name(team), pod: node.dataset.lvl === 'pod' ? name(node) : null, shown: !r.hidden, parentShown: !node.hidden,
      hdr: [...tb.querySelectorAll(':scope > thead th')].map(txt), caption: !!tb.querySelector('caption'), epicsCell: txt(node.children[2]),
      rows: [...tb.querySelectorAll(':scope > tbody > tr')].map(x => ({key: txt(x.querySelector('th')), href: (x.querySelector('th a') || {getAttribute: () => null}).getAttribute('href'), cells: [...x.querySelectorAll('td')].map(txt)}))});
  });
  const allShown = rows.every(r => !r.hidden);
  return {lists, expandable, allShown, nodes: rows.filter(r => r.dataset.lvl !== 'epics').map(r => ({lvl: r.dataset.lvl, name: name(r), project: r.dataset.lvl === 'project' ? name(r) : name(by.get(r.dataset.par).dataset.lvl === 'project' ? by.get(r.dataset.par) : by.get(by.get(r.dataset.par).dataset.par)), par: r.dataset.par, id: r.dataset.id, epicsCell: txt(r.children[2])}))};
})()"""
COLLAPSE_JS = r"""(() => {
  const c = document.querySelector('[data-cyact="colall"]'); if (!c) return null; c.click();
  const rows = [...document.querySelectorAll('#cy-ovbody tr[data-id]')];
  const shown = rows.filter(r => !r.hidden).map(r => r.dataset.lvl);
  const pod = document.querySelector('#cy-ovbody tr[data-lvl="pod"]'), proj = document.querySelector('#cy-ovbody tr[data-lvl="project"]');
  return {shown, rows: rows.length};
})()"""


def pods_of(epics: list) -> dict:
    """One pod = (project, label lower-cased); an epic counts once under each of its pods; no label, no pod."""
    pods: dict = collections.defaultdict(list)
    for e in epics:
        for key in {(e["p"], lab.lower()) for lab in (e.get("pl") or [])}:
            pods[key].append(e)
    return pods


def wip_epics(es: list) -> list:
    """The epics the 'more than 3 In Progress' tile counts: status In Progress only (a Validation epic is not in it)."""
    return [e for e in es if e["s"] in N_WIP]


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
    """The six headline figures of the Cycles section from the baked epics: planned (planned date in the window), Done, Overdue (planned before the as-of day, not Done), due in the next 7 days, Flagged."""
    pl = [e for e in epics if planned_date(e, calendar) and win["start"] <= planned_date(e, calendar) <= win["end"]]
    nd = [e for e in pl if e["s"] != "Done"]
    hi = _days(asof, SOON_DAYS)
    return {"planned": len(pl), "done": len(pl) - len(nd), "long": len(long_tile(epics, asof, win, calendar)["keys"]), "overdue": sum(1 for e in nd if planned_date(e, calendar) < asof),
            "next": sum(1 for e in nd if asof <= planned_date(e, calendar) <= hi), "flagged": sum(1 for e in nd if e.get("fl"))}


def check_long(res: dict, st: dict, es: list, win: dict, cal: dict, tag: str) -> None:
    """The Took Over 7 Days tile against long_tile: the number, its sub line (the population and the share from MIN_SAMPLE), the label, the link (exactly the keys counted, nothing when 0) and the first hover block."""
    bad, seen = res["pod_bad"], res["pod_seen"]
    got, w = st.get("long"), long_tile(es, st["asof"], win, cal)
    if not got:
        bad.append(f"{tag}: there is no Took Over 7 Days tile")
        return
    n, m = len(w["keys"]), w["pop"]
    seen["long>0"] += n > 0
    seen["long==0"] += n == 0
    seen["long_nopop"] += m == 0
    if got["l"] != f"Took Over {LONG_DAYS} Days" or got["v"].replace(",", "") != str(n):
        bad.append(f"{tag}: the Took Over 7 Days tile prints {got['l']!r} {got['v']!r}, the recount is {n}")
    share = f" ({jround(100 * n / m)}%)" if m >= MIN_SAMPLE else ""
    want_s = f"of {m} Done {'epic' if m == 1 else 'epics'}{share}" if m else ("no Done epic has a cycle time to count" if w["done"] else "no epic is Done yet")
    if got["s"] != want_s:
        bad.append(f"{tag}: the Took Over 7 Days sub line is {got['s']!r}, the recount is {want_s!r} ({n} of {m} with a cycle time, {w['done']} Done)")
    if n:
        keys = _key_in(got["href"] or "")
        if keys != w["keys"] and (got["href"] or w["keys"]):
            bad.append(f"{tag}: the Took Over 7 Days link finds {sorted(keys)[:3]} ({len(keys)}), the recount is {sorted(w['keys'])[:3]} ({len(w['keys'])})")
        first = (got["tip"] or "").split("\n")
        want_tip = f"{n} Done {'epic' if n == 1 else 'epics'} planned in {win['name']} took more than {LONG_DAYS} days."
        if first[0] != want_tip or "Cycle time as in the Efficiency section." not in first[1:2]:
            bad.append(f"{tag}: the Took Over 7 Days hover is {first[:2]}, expected {want_tip!r} and the Efficiency line")
        if n > 3 and not re.search(r"exact", got["tip"] or "", re.I):
            bad.append(f"{tag}: a key list of {n} epics does not say it is an exact list")
    elif got["href"]:
        bad.append(f"{tag}: the Took Over 7 Days number is 0 and still a link")


def figures(epics: list, due: dict, cycle: dict) -> dict:
    pods = pods_of(epics)

    def planned(e):
        return bool(due.get(e["k"])) and cycle["start"] <= due[e["k"]] <= cycle["end"]

    idle = {k for k, es in pods.items() if not any(planned(e) for e in es)}
    wip = {k for k, es in pods.items() if len(wip_epics([e for e in es if planned(e)])) > POD_LEVEL}          # among the epics planned in the selected cycles
    return {"pods": pods, "idle": idle, "wip": wip, "wip_epics": {e["k"] for k in wip for e in wip_epics([x for x in pods[k] if planned(x)])}, "planned": planned}


def oracle(data: dict, st: dict) -> dict:
    """The recount of a view: the epics of the release under the view's Projects and Teams filters."""
    return figures(_scope(data, st), st["due"], window_of(data, st["release"], st["dc"]))


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
    win = window_of(data, st["release"], st["dc"])
    if not st["shown"] or st["heading"] != f"Pods in {win['name']}":
        bad.append(f"{tag}: the Pods block is hidden or its heading is '{st['heading']}', expected 'Pods in {win['name']}'")
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
    check_long(res, st, _scope(data, st), win, cal, tag)
    seen = res["pod_seen"]
    seen["pod_filter"] += bool(st.get("pods")) and len(st["projects"]) == 1
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
        m = re.match(r"([\d,]+) epics? In Progress in these pods", tw["s"])
        if wip and (not m or int(m.group(1).replace(",", "")) != len(exp["wip_epics"])):
            bad.append(f"{tag}: the In Progress sub-line prints '{tw['s']}', the recount is {len(exp['wip_epics'])} epics")
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
                want_n = len(es) if kind == "idle" else len(wip_epics([e for e in es if exp["planned"](e)]))
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
        want_hdr = ["Pod", "Project", "Teams", "Epics in Release", f"Planned in {window_of(data, st['release'], st['dc'])['name']}"] if kind == "idle" else ["Pod", "Project", "Teams", "Epics In Progress"]
        if got["hdr"] != want_hdr:
            bad.append(f"{tag}: the {kind} list header is {got['hdr']}")


def jround(x: float) -> int:
    return math.floor(x + 0.5)                                    # JavaScript's Math.round (halves go up), not Python's


def weeks_of(data: dict, release: str) -> list:
    """The release's weeks as the burnup numbers them: W1 starts 7 days after the release start, the end of W6 is start + 48 days, the end of the last week (W12 in a standard release) is the release end. Spelled here
    on purpose, from the release window alone: [(n, first day, last day)]."""
    start, end = (dt.date.fromisoformat(x) for x in data["windows"][release])
    n_weeks = round(((end - start).days - 7) / 7)
    out = []
    for n in range(1, n_weeks + 1):
        ws = start + dt.timedelta(days=7 * n)
        we = end if n == n_weeks else start + dt.timedelta(days=7 * n + 6)
        out.append((n, ws, we))
    return out


def week_label(e: dict, data: dict, release: str, cal: dict) -> str:
    """The week of an epic's planned date as an epic list prints it: W#, 'Before W1' (the first seven days of the release and anything earlier), 'After release end', or a dash with no planned date."""
    d = planned_date(e, cal)
    if not d:
        return "–"
    start, end = (dt.date.fromisoformat(x) for x in data["windows"][release])
    day = dt.date.fromisoformat(d)
    if day > end:
        return "After release end"
    for n, ws, we in weeks_of(data, release):
        if ws <= day <= we:
            return f"W{n}"
    return "Before W1"


def weekly_expected(data: dict, es: list, st: dict, win: dict, cal: dict) -> dict:
    """The rows the Planned and Done by Week table must hold for the epics `es` and the selected cycles: Cycle 1 shows W1 to W6, Cycle 2 shows W7 to W12, both show W1 to W12 (a release with fewer weeks, only those); one
    extra first row 'Before W1' (the first seven days of the release, a part of Cycle 1) only when it holds planned epics. Never a 13th week. Epics planned after the last shown week are the 'after release end' number."""
    start, end = (dt.date.fromisoformat(x) for x in data["windows"][st["release"]])
    asof = st["asof"]
    weeks = weeks_of(data, st["release"])
    first = 1 in win["shown"]
    lo = 1 if first else 7
    hi = max(n for n, _, _ in weeks) if 2 in win["shown"] else min(6, max(n for n, _, _ in weeks))
    spans = [(f"W{n}", ws, we) for n, ws, we in weeks if lo <= n <= hi]
    if first:
        spans.insert(0, ("Before W1", start, start + dt.timedelta(days=6)))
    rows = []
    for label, ws, we in spans:
        inw = [e for e in es if (d := planned_date(e, cal)) and ws.isoformat() <= d <= we.isoformat()]
        if label == "Before W1" and not inw:
            continue
        nd = sum(1 for e in inw if e["s"] != "Done")
        share = f"{jround(100 * (len(inw) - nd) / len(inw))}%" if len(inw) >= MIN_SAMPLE else "–"      # % Done: Done over Planned, from MIN_SAMPLE (5) planned epics, a dash under that and for 0; JavaScript's rounding
        res = "–" if not inw else (("All Done" if not nd else f"{nd} Not Done") if we.isoformat() < asof else ("Upcoming" if ws.isoformat() > asof else "Current Week"))
        rows.append([label, f"{ws.isoformat()} to {we.isoformat()}", str(len(inw)), str(len(inw) - nd), str(nd), share, res])
    planned = [e for e in es if (d := planned_date(e, cal)) and win["start"] <= d <= win["end"]]
    after = [e for e in es if (d := planned_date(e, cal)) and d > end.isoformat()] if win["all"] else []
    return {"rows": rows, "planned": len(planned), "after": len(after)}


def _live(e: dict, win: dict, cal: dict, asof: str) -> bool:
    """An epic keeps its row alive: planned in the selected cycles, carried over (not Done, planned before the window, once the window has started), or (with every cycle shown) active with no planned date."""
    d = planned_date(e, cal)
    if d and win["start"] <= d <= win["end"]:
        return True
    if d and e["s"] != "Done" and d < win["start"] and asof >= win["start"]:
        return True
    return win["all"] and not d and e["s"] in N_FLIGHT


def epic_flags(e: dict, asof: str, cal: dict) -> str:
    out = []
    d = planned_date(e, cal)
    if d and e["s"] != "Done" and d < asof:
        n = (dt.date.fromisoformat(asof) - dt.date.fromisoformat(d)).days
        out.append(f"{n} {'day' if n == 1 else 'days'} overdue")
    if e.get("fl") and e["s"] != "Done":
        out.append("Flagged as blocked in Jira")
    if not d:
        out.append("no planned date")
    return "; ".join(out)


def lists_expected(data: dict, es: list, st: dict, win: dict, cal: dict) -> dict:
    """Which epics each opened pod row (and each team row with no pod rows) must list: the epics of the row under Epics in Release (every status, any planned date), keyed (project, team, pod name lower-cased or '*')."""
    asof = st["asof"]
    by_team: dict = collections.defaultdict(list)
    for e in es:
        for t in _teams(e):
            by_team[(e["p"], t)].append(e)
    out = {}
    for (p, t), tes in by_team.items():
        pods = collections.defaultdict(list)
        for e in tes:
            for k in _pods(e):
                pods[k].append(e)
        none = [e for e in tes if not _pods(e)]
        live_pods = {k: v for k, v in pods.items() if any(_live(e, win, cal, asof) for e in v)}
        live_none = none if (pods and any(_live(e, win, cal, asof) for e in none)) else []        # the No Pod Label row exists only in a team that has pod labels
        if not any(_live(e, win, cal, asof) for e in tes):
            continue                                                                                  # a team with nothing live has no row at all
        if live_pods:
            for k, v in live_pods.items():
                out[(p, t, k)] = v
            if live_none:
                out[(p, t, "")] = live_none
        else:
            out[(p, t, "*")] = tes                                                                    # no pod rows: the team lists its own epics
    return out


def _check_week_caption_and_marker(res: dict, wk: dict, rows: list, asof: str, win: dict, tag: str) -> None:
    """The caption of the weekly table is one short sentence, "Epics by planned week in <cycles>. Weeks run <first weekday> to <last weekday>.", the weekdays read off the table's own dates (the first numbered
    week of seven days; spelled here with strftime, never fixed). The row whose dates hold the as-of day is marked: aria-current="date", a dot glyph in the week cell, bold, and a tint (a marker that does not rest on
    colour alone); exactly one row when the as-of day is inside the shown rows (Before W1 included when shown), none otherwise (Cycle 2 before W7, a closed release, a release not started)."""
    bad, seen = res["pod_bad"], res["pod_seen"]
    spans = [(r[1].split(" to ")[0], r[1].split(" to ")[1], r[0]) for r in rows]
    numbered = [x for x in spans if x[2] != "Before W1"]
    full = [x for x in numbered if (dt.date.fromisoformat(x[1]) - dt.date.fromisoformat(x[0])).days == 6] or numbered
    if full:
        a, b = (dt.date.fromisoformat(full[0][0]).strftime("%A"), dt.date.fromisoformat(full[0][1]).strftime("%A"))
        want = f"Epics by planned week in {win['name']}. Weeks run {a} to {b}."
        if wk["note"] != want:
            bad.append(f"{tag}: the weekly caption is {wk['note']!r}, expected {want!r}")
    marked = [i for i, (ws, we, _) in enumerate(spans) if ws <= asof <= we]
    got = [i for i, r in enumerate(wk["rows"]) if r["cur"] == "date" or "cycur" in r["cls"].split()]
    if got != marked or len(got) > 1:
        bad.append(f"{tag}: the marked weekly rows are {got}, the as-of day {asof} is in row(s) {marked} of {[x[2] for x in spans]}")
    seen["cur_marked" if marked else "cur_none"] += 1
    if any(r["cur"] not in (None, "date") for r in wk["rows"]):
        bad.append(f"{tag}: aria-current has a value other than date")
    others = [r for i, r in enumerate(wk["rows"]) if i not in got]
    for i in got:
        r = wk["rows"][i]
        if not (r["cur"] == "date" and r["dot"] and r["weight"] >= 700 and others and all(r["tint"] != o["tint"] for o in others)):
            bad.append(f"{tag}: the current-week row {r['cells'][0]} lacks its marker (aria-current {r['cur']!r}, dot {r['dot']}, weight {r['weight']}, tint {r['tint']} vs {others[0]['tint'] if others else None})")
    if any(r["dot"] or r["weight"] >= 700 for r in others):
        bad.append(f"{tag}: a row other than the current week is marked (dot or bold)")


def check_page(res: dict, data: dict, st, exp_st, tag: str, ch) -> None:
    """The page-level layout and numbers of the Cycles section (every difference goes to res['pod_bad']): the order of the blocks, the removed features, the weekly table against weekly_expected, the Planned caption,
    and every opened pod or team row against lists_expected. `st` is the PAGE_JS state, `exp_st` the POD_JS state of the same view."""
    bad, seen = res["pod_bad"], res["pod_seen"]
    if not st:
        bad.append(f"{tag}: no page state")
        return
    g = st["gone"]
    for k, v in g.items():
        if v:
            bad.append(f"{tag}: a removed feature is on the page ({k}: {v!r})")
    if st["firstHeadings"][:8] != ["seclabel", "h-cycles", "cy-banner", "g-cypod", "cy-kpis1", "cy-pods", "cy-body", "cy-cap"]:
        bad.append(f"{tag}: the top of the section is {st['firstHeadings']}")
    blk = [x for x in (st["ovBlock"] or []) if x != "DIV.scrollcue"]                                    # (the page adds the scroll cue itself)
    if st["ovBlock"] and blk != ["H3.", "DIV.cyfrow cytogglebar", "DIV.tablewrap freeze"]:      # the table sits in the frozen-header box
        bad.append(f"{tag}: the Projects table block is {st['ovBlock']} (heading, Expand/Collapse bar, table; no paragraph, no Find box)")
    if st["ovBlock"] and sorted(set(st["toggles"])) != ["tgl"]:
        bad.append(f"{tag}: the table has controls other than the row arrows: {sorted(set(st['toggles']))}")
    win = window_of(data, st["release"], st["dc"])
    cal = {s["n"]: s["end"] for s in data["sprints"]}
    es = _scope(data, st)
    want = weekly_expected(data, es, st, win, cal)
    wk = st["weekly"]
    if not want["planned"]:
        if wk:
            bad.append(f"{tag}: a weekly table is shown for a view with nothing planned in {win['name']}")
    else:
        if not wk:
            bad.append(f"{tag}: no weekly table, {want['planned']} epics are planned")
        else:
            seen["weekly_views"] += 1
            if wk["hdr"] != ["Week", "Dates", "Planned", "Done", "Not Done", "% Done", "Result"]:
                bad.append(f"{tag}: the weekly header is {wk['hdr']}")
            got = [r["cells"] for r in wk["rows"]]
            if got != want["rows"]:
                bad.append(f"{tag}: the weekly rows are {got[:3]}..., the independent recount {want['rows'][:3]}... ({len(got)} vs {len(want['rows'])} rows)")
            _check_week_caption_and_marker(res, wk, want["rows"], st["asof"], win, tag)
            labels = [r[0] for r in got]
            if any(re.fullmatch(r"W(1[3-9]|[2-9]\d)", x) for x in labels) or "Week 13" in labels:
                bad.append(f"{tag}: a week after W12 is shown: {labels}")
            seen["before_w1" if "Before W1" in labels else "no_before_w1"] += 1
            seen[f"weekly_{win['shown'][0]}_{win['shown'][-1]}"] += 1
            if sum(int(r[2]) for r in got) != want["planned"]:
                bad.append(f"{tag}: the weekly rows add up to {sum(int(r[2]) for r in got)}, the Planned tile recount is {want['planned']}")
            tiles = exp_st["tiles1"].get("planned", "").replace(",", "")
            if tiles != str(want["planned"]):
                bad.append(f"{tag}: the Planned tile prints {tiles}, the recount {want['planned']}")
            if wk["hdrCls"][2:6] != ["n"] * 4 or any(r["pctCls"] != "n" or r["pctLinks"] for r in wk["rows"]):
                bad.append(f"{tag}: the % Done column is not a right-aligned number column without links: {wk['hdrCls']}")
            seen["pct_share"] += sum(1 for r in wk["rows"] if r["cells"][5].endswith("%"))
            seen["pct_dash_small"] += sum(1 for r in wk["rows"] if r["cells"][5] == "–" and int(r["cells"][2]) > 0)
            for r in wk["rows"]:                                      # every count of the table above 0 is a Jira link with that number; a 0 is plain text
                texts = [x["text"] for x in r["links"]]
                for idx in (2, 3, 4):
                    n = r["cells"][idx]
                    if (n != "0") != (n in texts):
                        bad.append(f"{tag}: weekly row {r['cells'][0]}, column {idx}: the count {n} {'has no link' if n != '0' else 'is a link'}")
            if None in st["order"] or not (st["order"][0] < st["order"][1] < st["order"][2] < st["order"][3] < st["order"][4] < st["order"][5]):
                bad.append(f"{tag}: the blocks are not in the order banner, tiles, Pods, weekly table, Projects table, disclosure: {st['order']}")
    cap = exp_st["plannedCap"]
    after_txt = f" · {want['after']} after release end"
    if want["after"]:
        if not cap["text"].endswith(after_txt) or not cap["text"].startswith(f"epics planned in {win['name']}"):
            bad.append(f"{tag}: the Planned caption is {cap['text']!r}, the recount says {want['after']} planned after the release end")
        seen["after>0"] += 1
    elif "after release end" in cap["text"] or cap["text"] != f"epics planned in {win['name']}":
        bad.append(f"{tag}: the Planned caption is {cap['text']!r} but nothing is planned after the release end (or one cycle is shown)")
    else:
        seen["after==0"] += 1
    # ---- the table opened to the epics
    ex = ch.js(EXPAND_JS)
    if not ex:
        if es and any(_live(e, win, cal, st["asof"]) for e in es):
            bad.append(f"{tag}: no Projects table although epics are live")
        return
    exp = lists_expected(data, es, st, win, cal)
    got = {}
    for L in ex["lists"]:
        key = (L["project"], L["team"], "*" if L["pod"] is None else ("" if L["pod"] == "No Pod Label" else L["pod"].lower()))
        got[key] = L
    if set(got) != set(exp):
        bad.append(f"{tag}: the rows that open to epics differ from the recount: {sorted(set(got) ^ set(exp))[:3]}")
    else:
        for key, es_ in exp.items():
            L = got[key]
            seen["lists"] += 1
            seen["list_pod" if L["pod"] is not None else "list_team"] += 1
            seen["list_nopod" if L["pod"] == "No Pod Label" else "list_other"] += 1
            if L["hdr"] != ["Jira", "Summary", "Planned", "Week", "Status", "Flags"] or not L["caption"]:
                bad.append(f"{tag}: the epic list header is {L['hdr']}")
            if not L["shown"]:
                bad.append(f"{tag}: Expand All left the list of {key} hidden")
            rows = {r["key"]: r for r in L["rows"]}
            if len(rows) != len(L["rows"]) or set(rows) != {e["k"] for e in es_}:
                bad.append(f"{tag}: the list of {key} shows {sorted(rows)[:4]} ({len(L['rows'])}), the recount {sorted(e['k'] for e in es_)[:4]} ({len(es_)})")
                continue
            if L["epicsCell"].replace(",", "") != str(len(es_)):
                bad.append(f"{tag}: the row of {key} counts {L['epicsCell']} under Epics in Release, its list holds {len(es_)}")
            dd = [r["cells"][1][:10] if r["cells"][1] != "–" else "9999" for r in L["rows"]]
            if dd != sorted(dd):
                bad.append(f"{tag}: the list of {key} is not in planned-date order: {dd[:5]}")
            for e in es_:
                r = rows[e["k"]]
                summ, planned, week, status, flags = r["cells"]
                d = planned_date(e, cal)
                if (r["href"] or "").rsplit("/", 1)[-1] != e["k"] or "/browse/" not in (r["href"] or ""):
                    bad.append(f"{tag}: {e['k']} is not a link to its Jira page: {r['href']}")
                if summ != re.sub(r"\s+", " ", e["t"]).strip():
                    bad.append(f"{tag}: {e['k']} summary {summ!r}")
                if (planned[:10] if d else planned) != (d or "–"):
                    bad.append(f"{tag}: {e['k']} planned {planned!r}, the recount {d}")
                if week != week_label(e, data, st["release"], cal):
                    bad.append(f"{tag}: {e['k']} week {week!r}, the recount {week_label(e, data, st['release'], cal)!r}")
                if status != e["s"] or flags != epic_flags(e, st["asof"], cal):
                    bad.append(f"{tag}: {e['k']} status/flags {status!r} / {flags!r}, the recount {e['s']!r} / {epic_flags(e, st['asof'], cal)!r}")
                seen["flag_overdue"] += "overdue" in flags
                seen["flag_blocked"] += "Flagged" in flags
                seen["flag_nodate"] += "no planned date" in flags
    # every pod row, and every team row without pod rows, has the arrow; a team with pod rows lists pods, not epics
    pods_rows = [x for x in ex["expandable"] if x["lvl"] == "pod"]
    if any(not x["hasEpics"] for x in pods_rows) or any(x["lvl"] == "team" and x["hasEpics"] != x["ctl"].startswith("cye-") for x in ex["expandable"]):
        bad.append(f"{tag}: a pod or team arrow does not control its epic list: {[x for x in ex['expandable'] if x['lvl'] != 'project'][:3]}")
    if not ex["allShown"]:
        bad.append(f"{tag}: Expand All leaves a row hidden")
    col = ch.js(COLLAPSE_JS)
    if col and col["shown"] != ["project"] * col["shown"].count("project"):
        bad.append(f"{tag}: Collapse All leaves rows other than the projects: {col['shown'][:6]}")
    # the default state: one project selected opens to its teams (team rows shown, no pod or epic row); otherwise one row per project
    h0 = st["hidden0"]
    shown0 = collections.Counter(x["lvl"] for x in h0 if not x["hidden"])
    if len(st["projects"]) == 1:
        if shown0["pod"] or shown0["epics"]:
            bad.append(f"{tag}: one project selected must open to its teams only: {dict(shown0)}")
    elif shown0["team"] or shown0["pod"] or shown0["epics"]:
        bad.append(f"{tag}: several projects selected must show one row per project: {dict(shown0)}")


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------
# The four proactive tiles: Not Started Due Soon, Waiting Items Due Soon, Busiest and Lightest Pods, Active Epics Without Pod.
# Recounted from the baked payload in plain Python with the definitions the owner decided, spelled here on purpose (never read from the page):
NS_STATUSES = ("Candidate", "New", "In Definition", "Ready for Dev")
SOON_DAYS = 7                                    # the page's CY.next
LEVEL_SPREAD = 0.40                              # the page's CY.levelSpread: (busiest - lightest) / the team's active epics
MIN_SAMPLE = 5                                   # the page's MIN_N: a team is evaluated from this many active epics
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


def pod_scope(es: list, st: dict) -> list:
    """The pod filter, spelled here from its definition: only with exactly one project selected, and only when pods are chosen. An epic passes when it carries any chosen pod (a label compared without regard to
    case) or has no pod label and No Pod Label is chosen. An epic that passes is returned as a copy that holds ONLY its chosen pods (the page builds pods from the chosen ones), so every recount below, which
    reads an epic's labels, sees the pods the filtered page has."""
    chosen = {x.lower() for x in st.get("pods", [])}
    if len(st["projects"]) != 1 or not chosen:
        return es
    out = []
    for e in es:
        labels = e.get("pl") or []
        keep = [l for l in labels if l.lower() in chosen]
        if keep or (not labels and NO_POD in chosen):
            out.append(dict(e, pl=keep))
    return out


def _scope(data: dict, st: dict) -> list:
    teams, sel = set(st["teams"]), set(st["projects"])
    return pod_scope([e for e in data["epics"] if e["p"] in sel and st["release"] in e["fv"]
                      and (not teams or any(t in teams for t in (e.get("tm") or ["(No Team)"])))], st)


def long_tile(es: list, asof: str, win: dict, cal: dict) -> dict:
    """Took Over 7 Days from the baked epics: the Done epics planned in the selected cycles that have a cycle time (the EDCT) and whose Issue Category is not one Cycle Time per Release leaves out (the population);
    of them, those whose cycle time is MORE than LONG_DAYS (strictly: exactly 7 is not over)."""
    done = [e for e in es if e["s"] == "Done" and (d := planned_date(e, cal)) and win["start"] <= d <= win["end"]]
    pop = [e for e in done if e.get("edct") is not None and (e.get("cat") or "").lower() not in CT_EXCLUDED]
    return {"done": len(done), "pop": len(pop), "keys": {e["k"] for e in pop if e["edct"] > LONG_DAYS}}


def _teams(e: dict) -> list:
    return e.get("tm") or ["(No Team)"]


def _pods(e: dict) -> set:
    return {l.lower() for l in (e.get("pl") or [])}


def planned_date(e: dict, calendar: dict):
    """The due date; the end of the Target Sprint only when there is no due date (a Target Sprint outside the calendar counts as none)."""
    return e.get("dd") or calendar.get(e.get("ts"))


def act_oracle(data: dict, st: dict) -> dict:
    scope = _scope(data, st)
    asof = st["asof"]
    hi = _days(asof, SOON_DAYS)
    cal = {s["n"]: s["end"] for s in data["sprints"]}
    win = window_of(data, st["release"], st["dc"])
    P = {e["k"] for e in scope if (d := planned_date(e, cal)) and win["start"] <= d <= win["end"]}      # the population of the Pods tiles: epics planned in the selected cycles
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

    is_ns = lambda e: e["k"] in P and e["s"] in NS_STATUSES and (lambda d: bool(d) and asof <= d <= hi)(planned_date(e, cal))     # noqa: E731
    in_flight = lambda e: e["k"] in P and e["s"] in N_FLIGHT                                                      # noqa: E731
    ns = [e for e in scope if is_ns(e)]
    flight = [e for e in scope if in_flight(e)]
    nopod = [e for e in flight if not _pods(e)]
    # 2. Pods To Level
    level_rows, flagged, ends, multi = {}, [], set(), 0
    for (p, t), es in by_team.items():
        pods = sorted(k for k in team_pods[(p, t)] if any(k in _pods(e) and e["s"] != "Done" and e["k"] in P for e in es))
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
    by_key.update({e["k"]: e for e in scope})                      # a provider planned in the cycles is read as the pod filter leaves it (only its chosen pods)
    in_scope = P                                                   # the provider is an epic planned in the selected cycles
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
    if X["flight"] and s != f"of {X['flight']} active {'epic' if X['flight'] == 1 else 'epics'}{share}":
        bad.append(f"{tag}: noPod sub-line '{s}', the recount is {X['nopod']} of {X['flight']}{share}")
    if not X["flight"] and s != "no active epic":
        bad.append(f"{tag}: the noPod sub-line with no active epic is '{s}'")
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
    if got["hdr"] != ["Team", "Project", "Pod", "Active Epics", "Share of Team's Active Epics", "Position"]:
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
            bad.append(f"{tag}: level row {r['th']} / {r['cells'][1]} has {n} active epics and {len(r['hrefs'])} links")


def _check_nopod(bad, X, got, tag):
    if got["hdr"] != ["Team", "Project", "Without Pod Label", "Active", "Share Without"]:
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
