#!/usr/bin/env python3
"""The CXCROSS section counts the Capabilities of other projects that sit under a CXCROSS Initiative, not only the Capabilities owned by CXCROSS.

Worked out here from the payload (fictitious data), never from the page's code: a Capability belongs to the section when its key is a CXCROSS key, or when its parent is a CXCROSS Initiative that is not Removed.
The fixture is extended with Capabilities of PMN, CXWFM and CXSUP so that every case is there:
  * a PMN Capability under a live CXCROSS Initiative            -> in the section, with its epics;
  * a CXWFM Capability under a Removed CXCROSS Initiative       -> not in it;
  * a PMN Capability under an Initiative of another project     -> not in it;
  * a CXSUP Capability the hierarchy does not know              -> not in it;
  * a CXCO Capability under a live CXCROSS Initiative with no epic -> not a row, but listed under "Capabilities with No Epics".
Rows, the 'Epics Under Them' tile, the link of each row and the none list are compared, for all projects and for PMN alone.

The table opens collapsed. The order is the one of the CrossCX Projects page when the payload has `cxPrio` (a band row above each priority group, then the Initiatives that are not on the page under their own
band, No Initiative last; Initiatives by band, row, title) and by title without it (no band rows, no error).

The table is grouped by the Initiative the Capabilities sit under (a Removed or unknown Initiative is the group "No Initiative", last). The groups are recounted here from the payload as well:
which Capability sits in which group, the order, the Capability count, the Done / total of every project cell, the Behind marking, the required fix versions, the footer as the sum of the groups, the epics
each group link asks for (evaluated with jql_eval), expand and collapse, the state across a filter change, the keyboard, at 1400 and 390 px; and two seeded defects (group by the Capability's own key, a
Capability counted twice in its group row) that this check must catch.

    python3 cx_check.py [--live] [--only NAME]
"""
from __future__ import annotations

import re
import sys
import time
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kit                                                                          # noqa: E402
import make_synthetic as MS                                                         # noqa: E402
import jql_eval                                                                     # noqa: E402
from kit import ctx, T                                                              # noqa: E402

SUITE = kit.Suite("Delivery Pulse CXCROSS section")
REL = "27.1"
NOT_ON_PAGE = "Not on the CrossCX Projects page"
NO_EPIC = "CXCO-98001"
LOWER_INI, LOWER_CAP = "CXCROSS-98900", "CXCROSS-98901"       # a live Initiative whose title starts in lower case and holds one Capability: a group of one, sorted by title without regard to case


def build():
    data = MS.make(MS.il_today())
    data["build"] = {"sha": "abc1234", "dirty": False, "at": "2026-01-01T00:00+02:00"}
    H = data["hier"]
    inis = sorted(k for k, r in H.items() if r["ty"] == "Initiative")
    live = next(k for k in inis if H[k]["s"] != "Removed")
    gone = next(k for k in inis if H[k]["s"] == "Removed")
    H["ZZINI-1"] = {"ty": "Initiative", "t": "another project initiative", "s": "In Progress", "fv": [REL], "p": "ZZINI"}
    pick = {}
    for proj in ("PMN", "CXWFM", "CXSUP"):                                          # a Capability of the project that holds epics of the release
        seen = {}
        for e in data["epics"]:
            c = e.get("cp")
            if c and not c.startswith("CXCROSS") and e["p"] == proj and REL in e["fv"]:
                seen.setdefault(c, 0)
                seen[c] += 1
        pick[proj] = sorted(seen, key=lambda c: (-seen[c], c))[:2]
    assert len(pick["PMN"]) == 2 and pick["CXWFM"] and pick["CXSUP"], pick
    rec = lambda c, par: {"ty": "Capability", "t": f"capability {c}", "s": "In Progress", "fv": [REL], "p": c.split("-")[0], **({"par": par} if par else {})}
    H[pick["PMN"][0]] = rec(pick["PMN"][0], live)                                  # under a live CXCROSS Initiative
    H[pick["CXWFM"][0]] = rec(pick["CXWFM"][0], gone)                              # under a Removed one
    H[pick["PMN"][1]] = rec(pick["PMN"][1], "ZZINI-1")                             # under an Initiative of another project
    H[NO_EPIC] = rec(NO_EPIC, live)                                                # ours, under a live Initiative, no epic anywhere
    data["_in"], data["_out"] = pick["PMN"][0], [pick["CXWFM"][0], pick["PMN"][1], pick["CXSUP"][0]]
    # the groups: a CXCROSS Capability with no parent at all (the group No Initiative), and an Initiative with one Capability whose title starts in lower case
    with_epics = sorted({e["cp"] for e in data["epics"] if e.get("cp", "").startswith("CXCROSS") and REL in e["fv"] and H.get(e["cp"], {}).get("s") != "Removed"})
    orphan, donor = with_epics[0], with_epics[1]
    H[orphan].pop("par", None)
    H[LOWER_INI] = {"ty": "Initiative", "t": "alpha initiative that sorts first only without regard to case", "s": "In Progress", "fv": [REL], "p": "CXCROSS"}
    H[LOWER_CAP] = {"ty": "Capability", "t": "zeta capability", "s": "In Progress", "fv": [REL, "Future Release"], "p": "CXCROSS", "par": LOWER_INI}
    next(e for e in sorted(data["epics"], key=lambda e: e["k"]) if e.get("cp") == donor and REL in e["fv"])["cp"] = LOWER_CAP        # one epic under it, so the group of one has something to count
    data["_orphan"] = orphan
    return data


def section_epics(data, projects, cx="all"):
    """The epics the section counts, worked out from the payload: the parent Capability is a CXCROSS one (its own key, or under a live CXCROSS Initiative), not Removed;
    the release, the projects and the Commitment Type radio apply."""
    H = data["hier"]
    want = {"all": None, "committed": "Committed", "notset": "Not Set", "stretch": "Stretch"}[cx]

    def ini_ok(c):
        p = (H.get(c) or {}).get("par")
        return bool(p and p in H and H[p]["s"] != "Removed" and p.startswith("CXCROSS"))
    is_cx = lambda c: bool(c) and (c.startswith("CXCROSS") or ini_ok(c))
    scope = [e for e in data["epics"] if e["p"] in projects and REL in e["fv"] and (want is None or (e.get("c") or "Not Set") == want)]
    return [e for e in scope if is_cx(e.get("cp")) and (H.get(e["cp"]) or {}).get("s") != "Removed"]


def expected(data, projects):
    eps = section_epics(data, projects)
    return {e["cp"] for e in eps}, len(eps)


# ---------------------------------------------------------------------------------------------- the recount of the groups
REL_RE = re.compile(r"\d+\.\d+")
relnum = lambda v: int(v.split(".")[0]) * 1000 + int(v.split(".")[1])
natural = lambda k: (k.rsplit("-", 1)[0], int(k.rsplit("-", 1)[1]))
collate = lambda s: [(2, ch) if ch.isalpha() else (1, ch) if ch.isdigit() else (0, ch) for ch in s.casefold()]       # spaces and punctuation, then digits, then letters; case ignored


def rel_versions(fv):
    out = []
    for raw in fv or []:
        v = str(raw).strip()
        if REL_RE.fullmatch(v) and v not in out:
            out.append(v)
    return sorted(out, key=relnum)


has_unscheduled = lambda fv: any(str(v).strip().lower() == "future release" for v in fv or [])


def is_behind(data, cap, e):
    """Behind Required Fix Version: an open epic planned later than its Capability's latest release, or still open although that release has ended."""
    rel = rel_versions(data["hier"][cap].get("fv"))
    if not rel or e["s"] == "Done":
        return False
    latest, ev, win = rel[-1], rel_versions(e["fv"]), data["windows"].get(rel[-1])
    return bool(ev and relnum(ev[0]) > relnum(latest)) or bool(win and win[1] < MS.il_today().isoformat())


def expected_groups(data, projects, cx="all", prio=True):
    """The groups of the table, in order: [{key, band, prio, caps: [{key, cells: {project: {n, d, behind, keys}}, fv}], cells: {...}, fv}]. key '' is No Initiative.
    With cxPrio in the payload (and prio=True): the Initiatives on the page first, by band, row, then title; the others after them by title; No Initiative last. `band` is the label of the band row above the group
    (the page's group label, or 'Not on the CrossCX Projects page'), None without cxPrio."""
    H = data["hier"]
    by_cap = {}
    for e in section_epics(data, projects, cx):
        by_cap.setdefault(e["cp"], []).append(e)
    members = {}
    for c in by_cap:
        par = H[c].get("par")
        members.setdefault(par if par and par in H and H[par]["s"] != "Removed" else "", []).append(c)
    title = lambda k: collate((H.get(k) or {}).get("t", ""))
    P = data.get("cxPrio") if prio else None
    on_page = lambda g: P["map"].get(g) if P and g else None
    if P:
        order = sorted((g for g in members if g and on_page(g)), key=lambda g: (on_page(g)["g"], on_page(g)["r"], title(g), natural(g))) + \
            sorted((g for g in members if g and not on_page(g)), key=lambda g: (title(g), natural(g))) + ([""] if "" in members else [])
    else:
        order = sorted((g for g in members if g), key=lambda g: (title(g), natural(g))) + ([""] if "" in members else [])

    def cells(caps):
        out = {}
        for p in data["projects"]:
            es = [(c, e) for c in caps for e in by_cap[c] if e["p"] == p]
            if es:
                out[p] = {"n": len(es), "d": sum(e["s"] == "Done" for _, e in es), "behind": len({c for c, e in es if is_behind(data, c, e)}), "keys": {e["k"] for _, e in es}}
        return out

    def fv(caps):
        rels = sorted({v for c in caps for v in rel_versions(H[c].get("fv"))}, key=relnum)
        return {"versions": rels, "none": not rels, "unsched": any(has_unscheduled(H[c].get("fv")) for c in caps)}
    out = []
    for g in order:
        caps = sorted(members[g], key=lambda c: (title(c), natural(c)))
        band = (P["groups"][on_page(g)["g"]] if on_page(g) else NOT_ON_PAGE) if P else None
        out.append({"key": g, "band": band, "prio": on_page(g), "caps": [{"key": c, "cells": cells([c]), "fv": fv([c])} for c in caps], "cells": cells(caps), "fv": fv(caps)})
    return out


def epic_issues(data):
    """The payload's epics as the fields a query names, for jql_eval."""
    return [{"key": e["k"], "project": e["p"], "issuetype": "Epic", "status": e["s"], "fixversion": e["fv"], "parent": e.get("cp"), "cf[10094]": e.get("c") if e.get("c") in ("Committed", "Stretch") else None} for e in data["epics"]]


def asked(href, issues):
    """The epics a link asks Jira for, by evaluating its query on the payload."""
    jql = urllib.parse.parse_qs(urllib.parse.urlsplit(href).query)["jql"][0]
    tree = jql_eval.parse(jql)
    return {i["key"] for i in issues if jql_eval.evaluate(tree, i)}


TABLE_JS = """(() => { const tx = e => e ? e.textContent.replace(/\\s+/g, ' ').trim() : '';
  const t = document.getElementById('xt-cx'); if (!t) return null;
  const cellOf = td => { const a = td.querySelector('a'), tt = td.querySelector('.tt'), m = tx(td).match(/(\\d+)\\/(\\d+)/);
    return {n: m ? +m[2] : 0, d: m ? +m[1] : 0, behind: !!td.querySelector('.bhd'), href: a ? a.getAttribute('href') : null, tip: ((a || tt || {}).dataset || {}).tip || ''}; };
  const rows = [...t.querySelectorAll('tbody tr')].map(tr => { const th = tr.querySelector('th'), b = th.querySelector('.cytgl'), link = tr.dataset.lvl === 'ini' ? th.querySelector('.xtname a') : th.querySelector('.cysub a');
    if (tr.classList.contains('xtband')) return {lvl: 'band', id: tr.getAttribute('data-id'), hasData: [...tr.attributes].some(a => /^data-/.test(a.name)), text: tx(th), scope: th.getAttribute('scope'), span: th.colSpan, cells: tr.querySelectorAll('td').length, shown: getComputedStyle(tr).display !== 'none', hidden: tr.hidden, par: null, key: ''};
    const hov = th.querySelector('.cysub .tt');
    return {lvl: tr.dataset.lvl, id: tr.dataset.id, prioTip: hov ? hov.getAttribute('data-tip') : '', prioName: hov ? hov.getAttribute('aria-label') : '', par: tr.dataset.par, hidden: tr.hidden, shown: getComputedStyle(tr).display !== 'none', key: link ? link.getAttribute('href').split('/browse/')[1] : '', scope: th.getAttribute('scope'),
      sub: tx(th.querySelector('.cysub')), name: tx(th.querySelector('.xtname')), toggle: b ? {exp: b.getAttribute('aria-expanded'), label: b.getAttribute('aria-label'), ctl: (b.getAttribute('aria-controls') || '').split(' ').filter(Boolean)} : null,
      cells: [...tr.querySelectorAll('td.cxc')].map(cellOf), fv: tx(tr.querySelector('td.fvc'))}; });
  const foot = [...t.querySelectorAll('tfoot tr')].map(tr => ({label: tx(tr.querySelector('th')), cells: [...tr.querySelectorAll('td.cxc')].map(td => { const a = td.querySelector('a'); return {text: tx(td), href: a ? a.getAttribute('href') : null}; })}));
  return {rows, foot, projects: [...t.querySelectorAll('thead th.cxc')].map(tx), caption: tx(t.querySelector('caption')), ids: [...t.querySelectorAll('tbody tr')].map(tr => tr.id)}; })()"""

READ = """(() => { const tx = e => e.textContent.replace(/\\s+/g, ' ').trim();
  const rows = [...document.querySelectorAll('#cx-body tbody tr[data-lvl=cap] .cysub a')].map(a => a.getAttribute('href').split('/browse/')[1]).filter(Boolean);
  const tiles = {}; document.querySelectorAll('#cx-kpis .kpi').forEach(c => { const l = c.querySelector('.l'); tiles[tx(l)] = tx(c.querySelector('.v')); });
  return {rows: [...new Set(rows)], tiles, none: tx(document.getElementById('cx-none')), errors: 0}; })()"""


def load_page(data, hash_, width=1400, url=None):
    ch = ctx.chrome
    ch.cmd("Emulation.setTimezoneOverride", timezoneId="Asia/Jerusalem")
    ch.viewport(width, 900 if width > 600 else 800)
    url = url or ctx.write(kit.wrap(MS.render_page(data)), "cx")
    ch.goto(url + "#" + hash_)
    assert kit.wait_ready(ch), "the page did not draw: " + str(ch.console_errors()[:2])
    time.sleep(0.5)
    ch._cx_url = url
    return ch


def fv_of(text):
    return {"versions": sorted(REL_RE.findall(text), key=relnum), "none": text.startswith("No Required Fix Version"), "unsched": "Unscheduled" in text}


def band_problems(data, got, want):
    """The band rows: the page's group labels in the recount's places and nowhere else (none at all without cxPrio), each a single cell across the table with a row-group header and no data attribute."""
    bad = []
    seq, last = [], None
    for g in want:
        if g["band"] is not None and g["band"] != last:
            seq.append(("band", g["band"]))
            last = g["band"]
        seq.append(("ini", g["key"]))
    page = [("band", r["text"]) if r["lvl"] == "band" else ("ini", r["key"]) for r in got["rows"] if r["lvl"] in ("band", "ini")]
    if page != seq:
        bad.append(f"the bands and groups are {[x[1] or 'No Initiative' for x in page]}, the recount is {[x[1] or 'No Initiative' for x in seq]}")
    for r in got["rows"]:
        if r["lvl"] != "band":
            continue
        if r["scope"] != "rowgroup" or r["span"] != len(data["projects"]) + 2 or r["hasData"] or r["id"] is not None or r["cells"] or not r["shown"] or r["hidden"]:
            bad.append(f"band {r['text']!r} is not a visible row-group header across the table without a data attribute: {r}")
    return bad


def group_problems(data, got, projects, cx="all"):
    """Everything about the grouped table that the recount can tell: [] when the page agrees."""
    bad = []
    want = expected_groups(data, projects, cx)
    issues = epic_issues(data)
    if got is None:
        return ["the grouped table (#xt-cx) is not on the page"]
    if got["projects"] != list(data["projects"]):
        bad.append(f"the project columns are {got['projects']}")
    bad += band_problems(data, got, want)
    rows, i = [r for r in got["rows"] if r["lvl"] != "band"], 0
    gl = [r for r in rows if r["lvl"] == "ini"]
    if [r["key"] for r in gl] != [g["key"] for g in want]:
        return bad + [f"the groups are {[r['key'] or 'No Initiative' for r in gl]}, the recount is {[g['key'] or 'No Initiative' for g in want]}"]
    totals = {p: {"n": 0, "d": 0, "behind": 0, "keys": set()} for p in data["projects"]}
    while i < len(rows):
        r = rows[i]
        g = want[sum(1 for x in rows[:i] if x["lvl"] == "ini")]
        name = g["key"] or "No Initiative"
        if r["lvl"] != "ini" or r["scope"] != "row":
            return bad + [f"row {i} is not a group row with a row header: {r['lvl']}/{r['scope']}"]
        kids = []
        i += 1
        while i < len(rows) and rows[i]["lvl"] == "cap":
            kids.append(rows[i])
            i += 1
        n = len(g["caps"])
        if r["sub"] != f"{n} {'Capability' if n == 1 else 'Capabilities'}":
            bad.append(f"{name}: the count line says {r['sub']!r}, the recount is {n}")
        if [k["key"] for k in kids] != [c["key"] for c in g["caps"]]:
            bad.append(f"{name}: its Capabilities are {[k['key'] for k in kids]}, the recount is {[c['key'] for c in g['caps']]}")
        want_tip = f"Priority from the CrossCX Projects page: {g['band']}, row {g['prio']['n']}" if g["prio"] else ""
        if r["prioTip"] != want_tip:
            bad.append(f"{name}: the priority hover is {r['prioTip']!r}, the recount is {want_tip!r}")
        if any(k["par"] != r["id"] for k in kids):
            bad.append(f"{name}: a Capability row does not name its group")
        for p, cell in zip(data["projects"], r["cells"]):
            w = g["cells"].get(p)
            if not w:
                if cell["n"] or cell["href"]:
                    bad.append(f"{name} {p}: the cell counts {cell['d']}/{cell['n']}, the recount has no epic")
                continue
            if (cell["d"], cell["n"]) != (w["d"], w["n"]):
                bad.append(f"{name} {p}: the cell is {cell['d']}/{cell['n']}, the recount is {w['d']}/{w['n']}")
            if cell["behind"] != bool(w["behind"]):
                bad.append(f"{name} {p}: Behind is {cell['behind']}, the recount says {w['behind']} Capability cells")
            elif w["behind"] and f"{w['behind']} Capability cell" not in cell["tip"]:
                bad.append(f"{name} {p}: the hover does not say how many cells are Behind ({w['behind']}): {cell['tip'][-120:]!r}")
            if not cell["href"]:
                bad.append(f"{name} {p}: the cell is not a link")
            else:
                got_keys = asked(cell["href"], issues)
                if got_keys != w["keys"]:
                    bad.append(f"{name} {p}: the link asks for {len(got_keys)} epics, the cell counts {len(w['keys'])} (difference {sorted(got_keys ^ w['keys'])[:4]})")
            t = totals[p]
            t["n"] += w["n"]
            t["d"] += w["d"]
            t["behind"] += w["behind"]
            t["keys"] |= w["keys"]
        if fv_of(r["fv"]) != g["fv"]:
            bad.append(f"{name}: the required fix versions are {r['fv']!r}, the recount is {g['fv']}")
        for k, c in zip(kids, g["caps"]):
            for p, cell in zip(data["projects"], k["cells"]):
                w = c["cells"].get(p)
                if not w:
                    if cell["n"]:
                        bad.append(f"{c['key']} {p}: the cell counts epics, the recount has none")
                    continue
                if (cell["d"], cell["n"], cell["behind"]) != (w["d"], w["n"], bool(w["behind"])):
                    bad.append(f"{c['key']} {p}: the cell is {cell['d']}/{cell['n']} behind={cell['behind']}, the recount is {w['d']}/{w['n']} behind={bool(w['behind'])}")
                elif cell["href"] and asked(cell["href"], issues) != w["keys"]:
                    bad.append(f"{c['key']} {p}: the link does not ask for the epics the cell counts")
            if fv_of(k["fv"]) != c["fv"]:
                bad.append(f"{c['key']}: the required fix versions are {k['fv']!r}, the recount is {c['fv']}")
    foot = {f["label"]: f for f in got["foot"]}
    for label, field in (("Epics", "n"), ("Done", "d"), ("Cells Behind", "behind")):
        f = foot.get(label)
        if not f:
            bad.append(f"the footer has no {label} row")
            continue
        for p, cell in zip(data["projects"], f["cells"]):
            w = totals[p][field]
            shown = int(cell["text"].replace(",", "")) if cell["text"].replace(",", "").isdigit() else None
            if shown != w:
                bad.append(f"footer {label} {p}: {cell['text']!r}, the sum of the groups is {w}")
            elif label == "Epics" and cell["href"] and asked(cell["href"], issues) != totals[p]["keys"]:
                bad.append(f"footer Epics {p}: the link does not ask for the epics the groups add up to")
    return bad


def read_table(ch):
    return ch.js(TABLE_JS)


VIEWS = [(f"r={REL}", None, "all", 1400), (f"r={REL}&p=PMN", {"PMN"}, "all", 1400), (f"r={REL}&cx=stretch", None, "stretch", 1400), (f"r={REL}&cx=committed&p=PMN|CXWFM|WFM", {"PMN", "CXWFM", "WFM"}, "committed", 1400)]


@SUITE.test("capabilities_of_other_projects_under_a_cxcross_initiative_are_counted_and_the_others_are_not")
def _(t: T):
    data = build()
    for hash_, projects in ((f"r={REL}", set(data["projects"])), (f"r={REL}&p=PMN", {"PMN"})):
        ch = load_page(data, hash_)
        r = ch.js(READ)
        want_rows, want_epics = expected(data, projects)
        rows = set(r["rows"])
        t.check(rows == want_rows, f"[{hash_}] the rows are {sorted(rows ^ want_rows)} different from the recount ({len(rows)} rows, expected {len(want_rows)})")
        t.check(r["tiles"].get("Epics Under Them") == f"{want_epics:,}", f"[{hash_}] Epics Under Them is {r['tiles'].get('Epics Under Them')}, the recount is {want_epics}")
        if "PMN" in projects:
            t.check(data["_in"] in rows, f"[{hash_}] the PMN Capability under a live CXCROSS Initiative is not a row")
        t.check(not any(c in rows for c in data["_out"]), f"[{hash_}] a Capability that is not under a live CXCROSS Initiative is a row: {[c for c in data['_out'] if c in rows]}")
        t.check(not ch.console_errors(), f"[{hash_}] console error: {ch.console_errors()[:2]}")
    ch = load_page(data, f"r={REL}")
    r = ch.js(READ)
    t.check(NO_EPIC in r["none"], f"our Capability under a CXCROSS Initiative with no epic is not in the none list: {r['none'][:200]!r}")


@SUITE.test("every_row_opens_the_epics_it_counts_in_jira")
def _(t: T):
    data = build()
    ch = load_page(data, f"r={REL}")
    cells = ch.js("""(() => [...document.querySelectorAll('#cx-body tbody tr[data-lvl=cap]')].map(tr => ({cap: tr.querySelector('.cysub a').getAttribute('href').split('/browse/')[1],
      cells: [...tr.querySelectorAll('td a')].map(a => ({text: a.textContent.trim(), href: a.getAttribute('href') || ''}))})))()""")
    mine = next(r for r in cells if r["cap"] == data["_in"])
    got = sum(int(c["text"].split("/")[1]) for c in mine["cells"] if re.fullmatch(r"\d+/\d+", c["text"]))
    want = sum(1 for e in data["epics"] if e.get("cp") == data["_in"] and REL in e["fv"])
    t.check(got == want, f"the row of {data['_in']} counts {got} epics, the recount is {want}")
    t.check(all(f"parent%20%3D%20{data['_in']}" in c["href"] or f"parent = {data['_in']}" in c["href"] for c in mine["cells"] if re.fullmatch(r"\d+/\d+", c["text"])), "a cell of the row does not ask for the epics under the Capability")


# ---------------------------------------------------------------------------------------------- the groups
@SUITE.test("groups_the_table_is_grouped_by_initiative_and_every_group_matches_the_recount")
def _(t: T):
    data = build()
    try:
        for hash_, projects, cx, width in VIEWS + [(f"r={REL}", None, "all", 390)]:
            ch = load_page(data, hash_, width)
            projs = projects or set(data["projects"])
            got = read_table(ch)
            bad = group_problems(data, got, projs, cx)
            t.check(not bad, f"[{hash_} at {width}px] {len(bad)} differences from the recount: {bad[:4]}")
            t.check(not ch.console_errors(), f"[{hash_} at {width}px] console error: {ch.console_errors()[:2]}")
            if width == 1400 and not projects and cx == "all":
                keys = [g["key"] for g in expected_groups(data, projs, cx, prio=False)]                    # the title order (the page's order is checked in its own test)
                t.check("" in keys and keys[-1] == "" and data["_orphan"] in [c["key"] for c in expected_groups(data, projs, cx)[-1]["caps"]], "the fixture has no No Initiative group at the end (a blind check)")
                t.check(any(len(g["caps"]) == 1 for g in expected_groups(data, projs, cx)) and keys[0] == LOWER_INI, f"the fixture has no group of one Capability, sorted first by a lower-case title ({keys[:2]}): a blind check")
                t.check(any(g["fv"]["unsched"] for g in expected_groups(data, projs, cx)) and any(c["behind"] for g in expected_groups(data, projs, cx) for c in g["cells"].values()), "the fixture has no Unscheduled group or no Behind cell: a blind check")
                t.check(sum(len(g["caps"]) for g in expected_groups(data, projs, cx)) == len(expected(data, projs)[0]), "the groups do not hold every Capability once")
    finally:
        ctx.chrome.viewport(1400, 900)


toggle_sel = lambda i: f'#xt-cx tr[data-id="{i}"] .cytgl'


def vis(ch):
    r = read_table(ch)
    return [(x["lvl"], x["id"], x["shown"]) for x in r["rows"]], r


@SUITE.test("groups_collapsed_by_default_and_expand_collapse_work")
def _(t: T):
    data = build()
    ch = load_page(data, f"r={REL}")
    rows, r = vis(ch)
    groups = [x for x in r["rows"] if x["lvl"] == "ini"]
    caps = [x for x in r["rows"] if x["lvl"] == "cap"]
    bands = [x for x in r["rows"] if x["lvl"] == "band"]
    t.check(groups and all(g["toggle"] and g["toggle"]["exp"] == "false" and g["toggle"]["label"].startswith("Expand ") for g in groups), "a group is not collapsed at first")
    t.check(caps and not any(c["shown"] for c in caps) and all(c["hidden"] for c in caps), "a Capability row is visible before the reader opens its group")
    t.check(all(g["shown"] for g in groups) and all(b["shown"] for b in bands) and bands, "a group row or a band row is hidden at first")
    one = load_page(data, f"r={REL}&p=PMN")                                       # one project selected: the other expandable tables open their first level, this one must not
    r1p = read_table(one)
    t.check(all(g["toggle"]["exp"] == "false" for g in r1p["rows"] if g["lvl"] == "ini") and not any(c["shown"] for c in r1p["rows"] if c["lvl"] == "cap"), "with one project selected the table opens expanded")
    ch = load_page(data, f"r={REL}")
    bar = ch.js("(() => { const b = [...document.querySelectorAll('#cx-body .cytogglebar [data-xtact]')]; return {txt: b.map(x => x.textContent), tag: b.map(x => x.tagName), before: !!(b[0].compareDocumentPosition(document.getElementById('xt-cx')) & 4)}; })()")
    t.check(bar["txt"] == ["Expand All", "Collapse All"] and bar["tag"] == ["BUTTON", "BUTTON"] and bar["before"], f"Expand All and Collapse All above the table: {bar}")
    # Expand All shows every Capability row and leaves the band rows alone
    ch.js("document.querySelector('#cx-body [data-xtact=expall]').click()")
    _, r4 = vis(ch)
    t.check(all(c["shown"] for c in r4["rows"] if c["lvl"] == "cap") and all(g["toggle"]["exp"] == "true" for g in r4["rows"] if g["lvl"] == "ini"), "Expand All must show every Capability row")
    t.check([x["text"] for x in r4["rows"] if x["lvl"] == "band"] == [x["text"] for x in bands] and all(x["shown"] and not x["hasData"] for x in r4["rows"] if x["lvl"] == "band"), "Expand All changed a band row")
    # one toggle closes that group only
    g0 = groups[0]
    ch.js(f"document.querySelector({toggle_sel(g0['id'])!r}).click()")
    _, r1 = vis(ch)
    mine = [c for c in r1["rows"] if c["lvl"] == "cap" and c["par"] == g0["id"]]
    other = [c for c in r1["rows"] if c["lvl"] == "cap" and c["par"] != g0["id"]]
    b = next(x for x in r1["rows"] if x["id"] == g0["id"])["toggle"]
    t.check(mine and not any(c["shown"] for c in mine) and all(c["shown"] for c in other), "one toggle must hide the Capabilities of that group and no others")
    t.check(b["exp"] == "false" and b["label"].startswith("Expand Initiative ") and all(i in set(r1["ids"]) for i in b["ctl"]) and b["ctl"] == [c["id"] if False else f"xtr-cx-{c['id']}" for c in mine], f"the toggle after a click: {b}")
    ch.js(f"document.querySelector({toggle_sel(g0['id'])!r}).click()")
    _, r2 = vis(ch)
    t.check(all(c["shown"] for c in r2["rows"]), "a second click must open the group again")
    ch.js("document.querySelector('#cx-body [data-xtact=colall]').click()")
    _, r3 = vis(ch)
    t.check(all(g["shown"] for g in r3["rows"] if g["lvl"] in ("ini", "band")) and not any(c["shown"] for c in r3["rows"] if c["lvl"] == "cap"), "Collapse All must hide every Capability row and keep every group row and band row")
    t.check(all(g["toggle"]["exp"] == "false" and g["toggle"]["label"].startswith("Expand ") for g in r3["rows"] if g["lvl"] == "ini"), "after Collapse All every toggle says Expand")
    t.check(all(x["cells"] and x["fv"] for x in r3["rows"] if x["lvl"] == "ini"), "a collapsed group row lost its cells")
    t.check(r3["foot"] == r["foot"], "the footer changed when the groups were collapsed")
    t.check(not ch.console_errors(), f"console error: {ch.console_errors()[:2]}")


@SUITE.test("groups_the_open_and_closed_state_survives_a_filter_change")
def _(t: T):
    data = build()
    allp = set(data["projects"])
    small, big = expected_groups(data, allp, "stretch"), expected_groups(data, allp, "all")
    new = [g["key"] for g in big if g["key"] not in {x["key"] for x in small}]
    t.check(len(small) >= 2 and new, f"the fixture has no group that only the other Commitment Type brings in ({len(small)} groups for Stretch): a blind check")
    ch = load_page(data, f"r={REL}&cx=stretch")
    r = read_table(ch)
    inis = [x for x in r["rows"] if x["lvl"] == "ini"]
    first, second = inis[0], inis[1]
    ch.js(f"document.querySelector({toggle_sel(first['id'])!r}).click()")                    # the reader opens the first group of the collapsed table
    t.check(all(c["shown"] for c in read_table(ch)["rows"] if c["par"] == first["id"]), "the toggle did not open the first group")
    ch.js("document.querySelector('#f-cx input[value=all]').click()")
    time.sleep(0.4)
    r2 = read_table(ch)
    byid = {x["id"]: x for x in r2["rows"] if x["lvl"] == "ini"}
    t.check(first["id"] in byid and byid[first["id"]]["toggle"]["exp"] == "true" and all(c["shown"] for c in r2["rows"] if c["par"] == first["id"]), "the group the reader opened is closed again after a filter change")
    t.check(second["id"] in byid and byid[second["id"]]["toggle"]["exp"] == "false" and not any(c["shown"] for c in r2["rows"] if c["par"] == second["id"]), "a group the reader left closed was opened by a filter change")
    t.check(all(x["toggle"]["exp"] == "false" for x in r2["rows"] if x["lvl"] == "ini" and x["key"] in new), "a group that the filter brought in is not collapsed")
    t.check(group_problems(data, r2, allp, "all") == [], f"the table after the filter change differs from the recount: {group_problems(data, r2, allp, 'all')[:2]}")
    ch.js("document.querySelector('#cx-body [data-xtact=expall]').click()")
    ch.js("document.querySelector('#cx-body [data-xtact=colall]').click()")
    ch.js("document.querySelector('#f-cx input[value=stretch]').click()")
    time.sleep(0.4)
    r3 = read_table(ch)
    t.check(all(x["toggle"]["exp"] == "false" for x in r3["rows"] if x["lvl"] == "ini"), "Collapse All did not survive a filter change")
    ch.js("document.querySelector('#cx-body [data-xtact=expall]').click()")
    ch.js("document.querySelector('#f-cx input[value=all]').click()")
    time.sleep(0.4)
    r4 = read_table(ch)
    t.check(all(x["toggle"]["exp"] == "true" for x in r4["rows"] if x["lvl"] == "ini" and x["id"] in {y["id"] for y in r3["rows"]}), "Expand All did not survive a filter change for the groups it opened")
    t.check(not ch.console_errors(), f"console error: {ch.console_errors()[:2]}")


@SUITE.test("groups_keyboard_and_accessible_names")
def _(t: T):
    data = build()
    ch = load_page(data, f"r={REL}")
    key = lambda k, code, vk, text="": (ch.cmd("Input.dispatchKeyEvent", type="keyDown", key=k, code=code, windowsVirtualKeyCode=vk, **({"text": text} if text else {})), ch.cmd("Input.dispatchKeyEvent", type="keyUp", key=k, code=code, windowsVirtualKeyCode=vk))
    r = read_table(ch)
    g0 = next(x for x in r["rows"] if x["lvl"] == "ini" and x["key"])
    sel = toggle_sel(g0["id"])
    ch.js(f"document.querySelector({sel!r}).focus()")
    key("Enter", "Enter", 13, "\r")
    time.sleep(0.15)
    s = ch.js(f"(() => {{ const b = document.querySelector({sel!r}); return {{exp: b.getAttribute('aria-expanded'), focus: document.activeElement === b, label: b.getAttribute('aria-label'), h: b.getBoundingClientRect().height, tag: b.tagName, type: b.type, text: b.textContent.trim()}}; }})()")
    t.check(s["exp"] == "true" and s["focus"], f"Enter on the toggle opens the group and focus stays on it: {s}")
    t.check(s["label"].startswith("Collapse Initiative " + g0["key"]) and len(s["label"]) > len("Collapse Initiative " + g0["key"]) + 3, f"the toggle is named by its Initiative: {s['label']!r}")
    t.check(s["tag"] == "BUTTON" and s["type"] == "button" and s["text"] == "" and s["h"] >= 24, f"the toggle is a button of at least 24 px: {s}")
    key(" ", "Space", 32, " ")
    time.sleep(0.15)
    t.check(ch.js(f"document.querySelector({sel!r}).getAttribute('aria-expanded')") == "false", "Space on the toggle does not close the group again")
    ch.js("document.querySelector('#cx-body [data-xtact=expall]').focus()")
    key("Enter", "Enter", 13, "\r")
    time.sleep(0.15)
    reached = False
    for _ in range(4):
        key("Tab", "Tab", 9)
        if ch.js("document.activeElement.classList.contains('cytgl')"):
            reached = True
            break
    t.check(reached, "the toggles cannot be reached by Tab from Expand All")
    ncap = ch.js("[...document.querySelectorAll('#xt-cx tr[data-lvl=cap]')].filter(r => !r.hidden).length")
    ch.js("document.querySelector('#cx-body [data-xtact=colall]').focus()")
    key("Enter", "Enter", 13, "\r")
    time.sleep(0.15)
    t.check(ncap and ch.js("[...document.querySelectorAll('#xt-cx tr[data-lvl=cap]')].filter(r => !r.hidden).length") == 0 and ch.js("document.activeElement.dataset.xtact") == "colall", "Enter on Collapse All does not collapse every group with focus kept")
    t.check(ch.js("[...document.querySelectorAll('#xt-cx tbody tr:not(.xtband)')].every(tr => tr.querySelector('th[scope=row]'))") is True, "a row has no row header")
    t.check(ch.js("[...document.querySelectorAll('#xt-cx tbody tr.xtband')].length > 0 && [...document.querySelectorAll('#xt-cx tbody tr.xtband')].every(tr => tr.children.length === 1 && tr.children[0].tagName === 'TH' && tr.children[0].getAttribute('scope') === 'rowgroup')") is True, "a band row is not a single row-group header cell")
    cap = ch.js("document.querySelector('#xt-cx caption').textContent")
    t.check("grouped by Initiative" in cap and "expanded or collapsed" in cap and "project and team" not in cap, f"the caption: {cap!r}")
    t.check(not ch.console_errors(), f"console error: {ch.console_errors()[:2]}")


HEADER_OVER = """(w => { const wrap = document.querySelector('.cxwrap'); wrap.style.maxHeight = '260px'; window.scrollTo(0, wrap.getBoundingClientRect().top + scrollY - 300); wrap.scrollTop = 0;
  const groups = [...wrap.querySelectorAll('tbody tr[data-lvl=ini]')], g = groups[1] || groups[0], thead = wrap.querySelector('thead');
  const hh = thead.querySelector('th').getBoundingClientRect().height; wrap.scrollTop = g.offsetTop - hh + 4;                       // the group row is now partly under the header
  const out = [];
  const wr = wrap.getBoundingClientRect();
  [...thead.querySelectorAll('th')].forEach((th, i) => { const r = th.getBoundingClientRect(); if (r.left + 12 > wr.right - 4) return;                  // a column scrolled out of the box is not under any point of it
    const top = document.elementFromPoint(r.left + 12, r.top + r.height / 2); out.push({i, ok: !!top && thead.contains(top)}); });
  const gr = g.getBoundingClientRect(), tr = thead.querySelector('th').getBoundingClientRect();
  return {cells: out, z: getComputedStyle(thead.querySelector('th')).zIndex, pos: getComputedStyle(thead.querySelector('th')).position, behind: gr.top < tr.bottom, sw: document.documentElement.scrollWidth, iw: innerWidth}; })()"""


@SUITE.test("groups_the_sticky_header_stays_above_the_group_rows_at_1400_and_390")
def _(t: T):
    data = build()
    try:
        for width in (1400, 390):
            ch = load_page(data, f"r={REL}", width)
            ch.js("document.querySelectorAll('[data-xtact=expall]').forEach(b => b.click())")
            r = ch.js(HEADER_OVER)
            t.check(r["pos"] == "sticky" and r["behind"], f"{width}px: the header is not sticky or the group row did not scroll under it: {r}")
            t.check(all(c["ok"] for c in r["cells"]), f"{width}px: a group row is drawn over the header: {[c['i'] for c in r['cells'] if not c['ok']]}")
            t.check(r["sw"] <= r["iw"], f"{width}px: the page scrolls sideways {r['sw']} > {r['iw']}")
    finally:
        ctx.chrome.viewport(1400, 900)


# ---------------------------------------------------------------------------------------------- self-tests: the grouping check must fail on seeded defects
def seeded(src_old, src_new, data):
    import tempfile
    src = ctx.template.read_text(encoding="utf-8")
    if src.count(src_old) != 1:
        raise kit.Skip(f"the seeding anchor is not in this template exactly once: {src_old[:60]!r}")
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(src.replace(src_old, src_new))
    ch = ctx.chrome
    ch.cmd("Emulation.setTimezoneOverride", timezoneId="Asia/Jerusalem")
    ch.viewport(1400, 900)
    url = ctx.write(kit.wrap(MS.render_page(data, Path(f.name))), "cxseed")
    Path(f.name).unlink()
    ch.goto(url + f"#r={REL}")
    kit.wait_ready(ch)
    time.sleep(0.5)
    return ch


@SUITE.test("groups_a_group_link_over_the_length_budget_is_the_number_without_a_link")
def _(t: T):
    """Jira rejects very long URLs: a group cell whose query would pass the budget (CY_URL_MAX) shows its number as plain text, still with its hover and still counted. The budget is lowered in a copy of the page."""
    data = build()
    got = read_table(load_page(data, f"r={REL}"))
    lens = sorted(len(c["href"]) for r in got["rows"] if r["lvl"] == "ini" for c in r["cells"] if c["href"])
    limit = lens[len(lens) // 2]
    t.check(lens[0] < limit < lens[-1], f"the group links all have the same length ({lens[0]} to {lens[-1]}): the budget cannot be tested")
    ch = seeded("const CY_URL_MAX = 6000;", f"const CY_URL_MAX = {limit};", data)
    r = read_table(ch)
    n_plain = n_link = 0
    for g in (x for x in r["rows"] if x["lvl"] == "ini"):
        for p, cell in zip(data["projects"], g["cells"]):
            if not cell["n"]:
                continue
            if cell["href"]:
                n_link += 1
                t.check(len(cell["href"]) <= limit, f"a group link of {len(cell['href'])} characters is over the budget of {limit}")
            else:
                n_plain += 1
                t.check(cell["tip"] and f"{cell['d']} of {cell['n']} Done" in cell["tip"], "a group cell without a link lost its hover text")
    t.check(n_plain and n_link, f"the lowered budget cut {n_plain} cells and kept {n_link}: a blind check")
    t.check(ch.js("document.querySelectorAll('#xt-cx td .tt[tabindex=\"0\"][aria-label]').length") >= n_plain, "a group cell without a link is not focusable with a name")
    t.check(not [b for b in group_problems(data, r, set(data["projects"])) if "not a link" not in b and "the link" not in b], "the counts of the table changed when the links were dropped")


@SUITE.test("selftest_the_check_fails_when_only_cxcross_owned_capabilities_count")
def _(t: T):
    data = build()
    ch = seeded("const all = scope.filter(e => isCxCap(H, e.cp)), removedCap", 'const all = scope.filter(e => e.cp && e.cp.startsWith("CXCROSS")), removedCap', data)
    r = ch.js(READ)
    t.check(data["_in"] not in r["rows"], "the seeded old rule still lists the Capability under a CXCROSS Initiative: the check is blind")


@SUITE.test("selftest_the_check_fails_when_the_groups_are_by_the_capabilitys_own_key")
def _(t: T):
    data = build()
    ch = seeded('const g = iniOf(c) || ""; if (!groups.has(g))', "const g = c; if (!groups.has(g))", data)
    bad = group_problems(data, read_table(ch), set(data["projects"]))
    t.check(bad, "the seeded grouping by the Capability's own key passes the recount: the check is blind")


@SUITE.test("selftest_the_check_fails_when_a_capability_is_counted_twice_in_its_group_row")
def _(t: T):
    data = build()
    ch = seeded("const l = cs.flatMap(r => r.cells.get(p).l), d =", "const l = cs.concat(cs.slice(0, 1)).flatMap(r => r.cells.get(p).l), d =", data)
    bad = group_problems(data, read_table(ch), set(data["projects"]))
    t.check(any("cell is" in b for b in bad), f"a Capability counted twice in its group row passes the recount: {bad[:2]}: the check is blind")


@SUITE.test("the_expand_arrow_of_an_open_group_points_down_not_sideways")
def _(t: T):
    data = build()
    ch = load_page(data, f"r={REL}")
    ch.js("document.querySelector('#cx-body [data-xtact=expall]').click()")
    r = ch.js("""(() => { const out = []; document.querySelectorAll('#cx-body .cytgl').forEach(b => { const g = b.querySelector('.xtc'), c = g ? getComputedStyle(g) : null;
      out.push({open: b.getAttribute('aria-expanded'), transform: c ? c.transform : null, glyph: c ? getComputedStyle(g, '::before').content : null}); }); return out; })()""")
    t.check(len(r) >= 3, f"too few group toggles found: {len(r)}")
    t.check(all(x["transform"] in ("none", None) for x in r), f"a toggle glyph is rotated: {[x for x in r if x['transform'] not in ('none', None)][:2]}")
    t.check(any(x["open"] == "true" and "25BE" in repr(x["glyph"]).upper().replace("\\U", "25") or "\u25be" in str(x["glyph"]).lower() for x in r), f"no open group shows the down arrow: {r[:2]}")


# ---------------------------------------------------------------------------------------------- the priority order
@SUITE.test("priority_the_initiatives_follow_the_page_in_bands_and_the_rest_come_last")
def _(t: T):
    data = build()
    allp = set(data["projects"])
    P = data["cxPrio"]
    for hash_, projects, cx, width in VIEWS:
        ch = load_page(data, hash_, width)
        got = read_table(ch)
        want = expected_groups(data, projects or allp, cx)
        bad = band_problems(data, got, want)
        t.check(not bad, f"[{hash_}] {bad[:2]}")
    ch = load_page(data, f"r={REL}")
    got = read_table(ch)
    want = expected_groups(data, allp)
    keys = [g["key"] for g in want]
    title_keys = [g["key"] for g in expected_groups(data, allp, prio=False)]
    t.check(keys != title_keys, "the priority order is the title order in this fixture: a blind check")
    on = [g for g in want if g["prio"]]
    off = [g for g in want if not g["prio"] and g["key"]]
    t.check(len(on) >= 3 and len({g["band"] for g in on}) >= 2 and off, f"the fixture has too few Initiatives on the page, in too few bands, or none off it ({len(on)}, {len({g['band'] for g in on})}, {len(off)}): a blind check")
    t.check([g["key"] for g in want[:len(on)]] == [g["key"] for g in on] and keys[-1] == "", "the Initiatives on the page are not first, or No Initiative is not last")
    bands = [r["text"] for r in got["rows"] if r["lvl"] == "band"]
    t.check(bands == [b for b in P["groups"] if b in {g["band"] for g in on}] + [NOT_ON_PAGE], f"the bands are {bands}")
    t.check(NOT_ON_PAGE == "Not on the CrossCX Projects page" and bands[-1] == NOT_ON_PAGE, "the last band is not 'Not on the CrossCX Projects page'")
    # the order inside a band is the row of the page, then the title
    for b in P["groups"]:
        rr = [g["prio"]["r"] for g in on if g["band"] == b]
        t.check(rr == sorted(rr), f"band {b}: the rows of the page are not in order: {rr}")
    # the hover of a matched Initiative, none on the others
    hov = {r["key"]: r["prioTip"] for r in got["rows"] if r["lvl"] == "ini"}
    for g in on:
        t.check(hov[g["key"]] == f"Priority from the CrossCX Projects page: {g['band']}, row {g['prio']['n']}", f"{g['key']}: the hover is {hov[g['key']]!r}")
    t.check(not any(hov[g["key"]] for g in off) and not hov[""], "an Initiative that is not on the page has a priority hover")
    first = next(r for r in got["rows"] if r["lvl"] == "ini" and r["key"] == on[0]["key"])
    t.check(first["prioName"].startswith(f"{len(on[0]['caps'])} {'Capability' if len(on[0]['caps']) == 1 else 'Capabilities'}. Priority from the CrossCX Projects page"), f"the accessible name of the count with the hover: {first['prioName']!r}")
    # the band rows are not touched by Expand All, Collapse All or a toggle
    for act in ("expall", "colall"):
        ch.js(f"document.querySelector('#cx-body [data-xtact={act}]').click()")
        r2 = read_table(ch)
        t.check([r["text"] for r in r2["rows"] if r["lvl"] == "band"] == bands and all(r["shown"] and not r["hasData"] for r in r2["rows"] if r["lvl"] == "band"), f"{act} changed a band row")
        t.check(not band_problems(data, r2, want), f"{act}: the bands or groups moved")
    t.check(not ch.console_errors(), f"console error: {ch.console_errors()[:2]}")


@SUITE.test("priority_without_the_page_the_order_is_by_title_with_no_bands_and_no_error")
def _(t: T):
    allp = set(build()["projects"])
    for label, edit in (("absent", lambda d: d.pop("cxPrio")), ("not a list of groups", lambda d: d.update(cxPrio={"groups": "x", "map": 5})),
                        ("empty", lambda d: d.update(cxPrio=None))):
        data = build()
        edit(data)
        ch = load_page(data, f"r={REL}")
        got = read_table(ch)
        plain = {k: v for k, v in data.items() if k != "cxPrio"}                  # the recount of a page that has no usable order
        want = expected_groups(plain, allp)
        t.check([r["key"] for r in got["rows"] if r["lvl"] == "ini"] == [g["key"] for g in want] and not [r for r in got["rows"] if r["lvl"] == "band"], f"cxPrio {label}: the order is not the title order or a band is drawn")
        t.check(not group_problems(plain, got, allp), f"cxPrio {label}: {group_problems(plain, got, allp)[:2]}")
        t.check(not ch.js("document.querySelectorAll('#xt-cx tr.xtband, #xt-cx .cysub .tt').length"), f"cxPrio {label}: a band or a priority hover is drawn")
        know = ch.js("document.querySelector('#cx-cap').textContent")
        t.check("Initiatives are sorted by title." in know and "follow the order of the CrossCX Projects page" not in know, f"cxPrio {label}: the How this is calculated text names the page order")
        t.check(not ch.console_errors(), f"cxPrio {label}: console error: {ch.console_errors()[:2]}")
    data = build()                                                      # an entry whose band does not exist is treated as not on the page
    ini = next(iter(data["cxPrio"]["map"]))
    data["cxPrio"]["map"][ini]["g"] = 99
    ch = load_page(data, f"r={REL}")
    got = read_table(ch)
    seq = [(r["text"] if r["lvl"] == "band" else r["key"]) for r in got["rows"] if r["lvl"] in ("band", "ini")]
    t.check(ini not in seq or seq.index(ini) > seq.index(NOT_ON_PAGE), f"an Initiative with an unknown band is not under '{NOT_ON_PAGE}': {seq}")
    t.check(not ch.console_errors(), f"unknown band: console error: {ch.console_errors()[:2]}")


@SUITE.test("priority_how_this_is_calculated_says_the_order_and_the_collapsed_table")
def _(t: T):
    data = build()
    ch = load_page(data, f"r={REL}")
    txt = ch.js("document.querySelector('#cx-cap').textContent.replace(/\\s+/g, ' ')")
    for sentence in ("Initiatives follow the order of the CrossCX Projects page; those not on it come last.", "The table opens collapsed."):
        t.check(sentence in txt, f"How this is calculated lacks: {sentence!r}")
    t.check("Rows are sorted by title and columns" not in txt, "How this is calculated still says rows are sorted by title with the page order on")


@SUITE.test("collapsed_the_seeded_expanded_table_is_really_open")
def _(t: T):
    data = build()
    ch = seeded("collapsed: true, bands,", "expanded: true, bands,", data)
    r = read_table(ch)
    t.check(any(c["shown"] for c in r["rows"] if c["lvl"] == "cap") and all(g["toggle"]["exp"] == "true" for g in r["rows"] if g["lvl"] == "ini"), "the seeded table that opens expanded is not open: the seeding did nothing")


# ---------------------------------------------------------------------------------------------- self-tests for the new behaviours
@SUITE.test("selftest_the_check_fails_when_the_order_ignores_the_page_groups")
def _(t: T):
    data = build()
    ch = seeded("const P = cxPrioOf(), pm = g =>", "const P = null, pm = g =>", data)
    bad = group_problems(data, read_table(ch), set(data["projects"]))
    t.check(bad and any("bands and groups" in b for b in bad), f"the seeded page that ignores the groups passes the recount: {bad[:2]}: the check is blind")


@SUITE.test("selftest_the_check_fails_when_a_band_row_is_a_data_row")
def _(t: T):
    data = build()
    ch = seeded('`<tr class="xtband"><th scope="rowgroup"', '`<tr class="xtband" data-id="band"><th scope="rowgroup"', data)
    bad = band_problems(data, read_table(ch), expected_groups(data, set(data["projects"])))
    t.check(bad, "a band row with a data-id passes the check: the check is blind")


@SUITE.test("selftest_the_check_fails_when_the_table_opens_expanded")
def _(t: T):
    data = build()
    ch = seeded("collapsed: true, bands,", "expanded: true, bands,", data)
    r = read_table(ch)
    shown = [c for c in r["rows"] if c["lvl"] == "cap" and c["shown"]]
    t.check(shown, "the seeded expanded table shows no Capability row: the check for 'collapsed by default' is blind")


if __name__ == "__main__":
    sys.exit(kit.cli(SUITE, __doc__))
