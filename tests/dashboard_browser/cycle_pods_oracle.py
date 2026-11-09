#!/usr/bin/env python3
"""The Cycles section's Took Over 7 Days tile and its Filter by Pod chips, against independent recounts.

Took Over 7 Days (third headline tile): the Done epics planned in the selected Delivery Cycles that have a cycle time (the EDCT of the Efficiency section) and are outside the Issue Categories Cycle Time per
Release leaves out (Maintenance, SOW); of them, those with a cycle time MORE than 7 days (strictly: exactly 7 is not over). The number opens the exact keys (a cycle time is not a Jira field); the sub line prints the
population and the share (from 5 epics). The recount is pod_oracle.long_tile (plain Python over the baked epics); the fixture holds epics of known cycle times (7, 8, 0, 9, 12), one with no cycle time, two in the
excluded categories, an In Progress epic that carries a 30, a Done epic of another release, and epics of Cycle 2, all in 'Team Seed Lng', in the closed release 26.4 so the running release's burnup does not move (make_synthetic.proactive_epics, case 5), so the boundary and the population are
also asserted by hand, not only by the recount. Two Done epics with NO cycle time are added by make_synthetic.long_cycle_extras to the payload of this suite only ("long" in link_cycles.page): in the stock fixture they
would put a fifth line into the Cycle Time per Release hover and break the word budget of link_guard.py.

Filter by Pod: a row of chips under the banner, only with EXACTLY ONE project selected (hash `pd=<pod>|<pod>|~none`, lower-case pod keys; read only with one project): All Pods, one chip per pod of that project with its
epic count (the project's epics of the release under the page filters, every cycle), No Pod Label. Choosing pods narrows every tile, list, table and Jira link of the section (the model is built once over the epics that
pass); the pods themselves are only the chosen ones. The independent recount is pod_oracle.pod_scope (a filter of the baked epics, then every existing recount of the section over what is left), run through
link_cycles.sweep in pod-filter views of both payloads: every printed number, the opened lists, the weekly table, the opened pod rows and every Jira query (evaluated over the baked epics) must agree.
The chips are also driven like a reader: choose, choose several, All Pods, Show All Pods, the address round trip, a change of project clears the choice, Reset Filters clears it and counts it, the empty state.

    python3 cycle_pods_oracle.py --live
"""
from __future__ import annotations

import collections
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kit                                                                          # noqa: E402
import link_cycles as LC                                                            # noqa: E402
import make_synthetic as MS                                                         # noqa: E402
import pod_oracle as PO                                                             # noqa: E402
from kit import ctx, T                                                              # noqa: E402

SUITE = kit.Suite("Delivery Pulse Cycles: Took Over 7 Days and Filter by Pod")
LNG = "r=26.4&p=PMN&t=Team%20Seed%20Lng"                                            # the fixed Took Over 7 Days cases (one team of PMN, in the closed release 26.4)
HEADLINE = ["Planned", "Done", "Took Over 7 Days", "Overdue", "Due Next 7 Days", "Flagged"]

STATE_JS = r"""(() => {
  const txt = n => n ? n.textContent.replace(/\s+/g, ' ').trim() : null, bar = document.getElementById('g-cypod'), lbl = bar.querySelector('.lbl');
  const tile = id => { const t = document.querySelector('[data-kpi="' + id + '"]'); return t ? {v: txt(t.querySelector('.v')), l: txt(t.querySelector('.l')), s: txt(t.querySelector('.s'))} : null; };
  const chips = [...document.querySelectorAll('#f-cypod .chip')].map(c => ({tok: c.dataset.cypod, name: c.firstChild.textContent.trim(), n: Number(c.querySelector('.cnt').textContent.replace(/,/g, '')),
    on: c.getAttribute('aria-pressed') === 'true', tip: c.getAttribute('data-tip'), cls: c.className, tag: c.tagName}));
  const note = document.getElementById('cy-podsline'), banner = document.getElementById('cy-banner');
  return {hidden: bar.hidden, shown: bar.getBoundingClientRect().height > 0, chips, label: txt(lbl), labelTip: (lbl.querySelector('.tt') || {getAttribute: () => null}).getAttribute('data-tip'), changed: bar.classList.contains('changed'),
    dot: getComputedStyle(lbl, '::before').content, note: note.hidden ? null : txt(note), noteBtn: !note.hidden && !!note.querySelector('button[data-cypod="all"]'), inBanner: banner.contains(note), barAfterBanner: banner.nextElementSibling === bar,
    barBeforeTiles: bar.nextElementSibling === document.getElementById('cy-kpis1'), hash: location.hash, pods: [...state.pods], projects: [...state.projects], release: state.release,
    reset: txt(document.getElementById('f-reset')), resetOff: document.getElementById('f-reset').disabled, heading: txt(document.getElementById('cy-pods-h')),
    headline: [...document.querySelectorAll('#cy-kpis1 .kpi')].map(k => k.dataset.kpi), labels1: [...document.querySelectorAll('#cy-kpis1 .kpi .l')].map(txt), labels2: [...document.querySelectorAll('#cy-kpis2 .kpi .l')].map(txt),
    long: tile('long'), planned: tile('planned'), empty: txt(document.querySelector('#cy-body .empty')), emptyBtn: !!document.querySelector('#cy-body .empty button[data-cypod="all"]'),
    focus: document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.cypod || null : null, weekly: !!document.getElementById('cy-wktable'), bodyHeads: [...document.querySelectorAll('#cy-body h3')].map(txt)};
})()"""


def load(h: str, kind: str = "stock") -> tuple[dict, str]:
    data, url = LC.page(kind)
    ch = ctx.chrome
    ch.goto(url + "#" + h)
    kit.wait_ready(ch)
    time.sleep(0.15)
    return data, ch.js(STATE_JS)


def natural(s: str) -> list:
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", s.lower())]


def expected_chips(data: dict, release: str, project: str, teams: set | None = None) -> dict:
    """The chips a one-project view must show, counted again from the baked epics: the epics of the project and the release under the Teams filter; a pod is a label compared without regard to case, named by its first
    spelling in the payload's epics; an epic with several labels counts once under each pod."""
    first: dict = {}
    for e in data["epics"]:
        for lab in e.get("pl") or []:
            first.setdefault(lab.lower(), lab)
    scope = [e for e in data["epics"] if e["p"] == project and release in e["fv"] and (not teams or any(t in teams for t in (e.get("tm") or ["(No Team)"])))]
    counts: dict = collections.Counter()
    for e in scope:
        for k in {x.lower() for x in (e.get("pl") or [])}:
            counts[k] += 1
    return {"all": len(scope), "pods": {k: (first[k], n) for k, n in counts.items()}, "none": sum(1 for e in scope if not e.get("pl"))}


def chip_problems(data: dict, st: dict, release: str, project: str, teams: set | None = None, chosen: set | None = None) -> list[str]:
    bad = []
    exp = expected_chips(data, release, project, teams)
    chosen = chosen or set()
    if st["hidden"] or not st["shown"]:
        return [f"the chips are hidden ({st['hidden']}) or have no height ({st['shown']}) with one project selected"]
    toks = [c["tok"] for c in st["chips"]]
    pods = [c for c in st["chips"] if c["tok"] not in ("all", "~none")]
    if toks[0] != "all" or st["chips"][0]["name"] != "All Pods":
        bad.append(f"the first chip is {toks[:1]}, it must be All Pods")
    if ("~none" in toks) != (exp["none"] > 0 or "~none" in chosen) or (toks and "~none" in toks and toks[-1] != "~none"):
        bad.append(f"No Pod Label is on the row: {'~none' in toks}, the recount has {exp['none']} epics without a pod label (it must be the last chip)")
    got = {c["tok"]: (c["name"], c["n"]) for c in pods}
    want = {k: v for k, v in exp["pods"].items()}
    for k in chosen:
        if k != "~none":
            want.setdefault(k, (got.get(k, (k, 0))[0], 0))                             # a chosen pod stays on the row, with the count it has now
    if got != want:
        bad.append(f"the pod chips differ from the recount: page-only {sorted(set(got.items()) - set(want.items()))[:3]}, recount-only {sorted(set(want.items()) - set(got.items()))[:3]}")
    if [c["name"] for c in pods] != sorted([c["name"] for c in pods], key=natural):
        bad.append(f"the pod chips are not alphabetical: {[c['name'] for c in pods][:5]}")
    allc = st["chips"][0]
    if allc["n"] != exp["all"]:
        bad.append(f"All Pods counts {allc['n']}, the recount is {exp['all']}")
    none = [c for c in st["chips"] if c["tok"] == "~none"]
    if none and (none[0]["name"] != "No Pod Label" or none[0]["n"] != exp["none"]):
        bad.append(f"No Pod Label chip is {none[0]['name']!r} {none[0]['n']}, the recount is {exp['none']}")
    on = {c["tok"] for c in st["chips"] if c["on"]}
    if on != (chosen or {"all"}):
        bad.append(f"the pressed chips are {sorted(on)}, expected {sorted(chosen or {'all'})}")
    if any(c["tag"] != "BUTTON" or not c["tip"] for c in st["chips"]):
        bad.append("a chip is not a button with a hover")
    return bad


@SUITE.test("pods_chips_appear_only_with_exactly_one_project_with_the_right_counts")
def _(t: T):
    """No chips with every project or with two; one chip per pod of the one project, with the count of that project's epics of the release, No Pod Label and All Pods; the Teams filter narrows the counts;
    an address that carries pd with several projects does not filter."""
    for h, project, teams in (("r=27.1&p=PMN", "PMN", None), ("r=27.1&p=CXCO", "CXCO", None), ("r=27.1&p=PMN&t=Team%20Alpha", "PMN", {"Team Alpha"}), ("r=26.4&p=PMN", "PMN", None)):
        data, st = load(h)
        for m in chip_problems(data, st, h.split("&")[0][2:], project, teams):
            t.failures.append(f"#{h}: {m}")
        t.check(st["pods"] == [] and "pd=" not in st["hash"] and not st["changed"] and not st["note"], f"#{h}: nothing is chosen: {st['pods']} {st['hash']} {st['note']}")
        t.check(st["label"] == "Filter by Pod" and st["barAfterBanner"] and st["barBeforeTiles"] and st["inBanner"], f"#{h}: the row is the label 'Filter by Pod' between the banner and the tiles, the line about chosen pods inside the banner: {st['label']!r}")
        t.check(st["labelTip"] == "Shows only epics of the chosen pods in every tile and table below. Choose several to combine them. All Pods clears the choice.", f"#{h}: the row hover is {st['labelTip']!r}")
    for h in ("r=27.1", "r=27.1&p=PMN|CXCO", "r=27.1&p=PMN|CXCO&pd=pod-lvl-a2", "r=27.1&pd=pod-lvl-a2|~none"):
        data, st = load(h)
        t.check(st["hidden"] and not st["shown"] and st["pods"] == [] and "pd=" not in st["hash"] and st["note"] is None, f"#{h}: no chips and no pod filter with {len(st['projects'])} projects: hidden {st['hidden']}, pods {st['pods']}, {st['hash']}")
        t.check(len(st["chips"]) == 0 or st["hidden"], f"#{h}: chips are rendered for several projects")
        pod_state = ctx.chrome.js(PO.POD_JS)
        res = dict(pod_bad=[], pod_seen=collections.Counter())
        PO.check_pods(res, data, pod_state, h, ctx.chrome)
        t.check(not res["pod_bad"], f"#{h}: a view with several projects is not the unfiltered recount: {res['pod_bad'][:2]}")


@SUITE.test("pods_chosen_pods_narrow_every_tile_list_table_and_link_to_the_recount_stock")
def _(t: T):
    """Chosen pods in the stock payload (known pods, No Pod Label, one and several, one cycle and both, a unknown pod that is dropped): every printed number, both opened lists, the weekly table, every opened pod
    row and every Jira query agree with pod_oracle (which filters the baked epics itself)."""
    r = LC.sweep(kinds=("stock",), hashes=STOCK_VIEWS)
    check_sweep(t, r, STOCK_VIEWS)


@SUITE.test("pods_chosen_pods_narrow_every_tile_list_table_and_link_to_the_recount_variant")
def _(t: T):
    """The seeded payload: a pod written in three spellings, an epic that carries two pods (one chosen: it is in the chosen pod only), a label shared by two projects, labels shaped like issue keys."""
    r = LC.sweep(kinds=("variant",), hashes=VARIANT_VIEWS)
    check_sweep(t, r, VARIANT_VIEWS)


STOCK_VIEWS = ["r=27.1&p=PMN&pd=pod-lvl-a2", "r=27.1&p=PMN&pd=pod-lvl-a2|pod-ns-a|pod-wip-four", "r=27.1&p=PMN&pd=~none", "r=27.1&p=PMN&pd=pod-lvl-a2|~none", "r=27.1&p=PMN&dc=1&pd=pod-lvl-a1|pod-lvl-a2",
               "r=26.4&p=PMN&dc=2&pd=pod-lng-a|pod-lng-b", "r=26.4&p=PMN&t=Team%20Seed%20Lng&pd=pod-lng-a", "r=27.1&p=PMN&pd=POD-LVL-A2", "r=27.1&p=PMN&pd=pod-does-not-exist", "r=27.1&p=CXCO&pd=~none",
               "r=26.4&p=PMN&pd=~none"]
VARIANT_VIEWS = ["r=27.1&p=PMN&pd=pod-seed-case", "r=27.1&p=PMN&pd=pod-seed-four|pod-seed-three", "r=27.1&p=PMN&pd=pod-seed-twoa", "r=27.1&p=PMN&dc=2&pd=pod-seed-mix|pod-seed-late|~none",
                 "r=27.1&p=CXCO&pd=pod-seed-shared", "r=27.1&p=PMN&pd=pod-seed-shared", "r=27.1&p=PMN&pd=pod-21|pod-22", "r=27.1&p=PMN&dc=1&pd=pod-seed-undated|pod-seed-done"]


def check_sweep(t: T, r: dict, views: list) -> None:
    t.check(not r["errors"], f"console errors or queries the evaluator cannot read: {r['errors'][:3]}")
    t.check(not r["skipped"], f"pages without a Cycles model: {r['skipped'][:3]}")
    t.check(r["loads"] == len(views), f"{r['loads']} of {len(views)} views were compared")
    t.check(not r["pod_bad"], f"{len(r['pod_bad'])} differences from the independent recount, e.g. {r['pod_bad'][:3]}")
    t.check(not any(r["bad"].values()), f"queries that find other epics than the page counts: {dict(r['bad'])}; {list(r['ex'].values())[:1]}")
    t.check(not r["dom_bad"], f"{len(r['dom_bad'])} printed numbers differ from their query: {r['dom_bad'][:3]}")
    t.check(not r["dropped"], f"{len(r['dropped'])} numbers lost their link: {r['dropped'][:2]}")
    seen = r["pod_seen"]
    t.check(seen["pod_filter"] >= len(views) - 2, f"only {seen['pod_filter']} of {len(views)} views had a pod filter in force (a blind check)")
    t.check(sum(r["nonempty"].values()) > 0 and r["links_by_kind"]["scope"] > 0, "no query was compared on a non-empty set under the pod filter")
    t.note(f"{r['loads']} views, {sum(r['n'].values())} query comparisons, {r['dom_links']} links read from the page, {seen['pod_filter']} views under a pod filter")


@SUITE.test("long_the_tile_is_third_in_the_strip_with_the_owners_labels")
def _(t: T):
    data, st = load("r=27.1")
    t.check(st["headline"] == ["planned", "done", "long", "overdue", "next", "flagged"], f"the headline strip is {st['headline']}")
    t.check(st["labels1"] == HEADLINE, f"the headline labels are {st['labels1']}")
    t.check(st["labels2"] == ["Not Started Due Soon", "Waiting Items Due Soon", "Busiest and Lightest Pods", "Active Epics Without Pod", "Pods Without Planned Epics", "Pods Over 3 Epics"], f"the Pods labels are {st['labels2']}")
    t.check(st["heading"] == "Pods in Delivery Cycles 1 and 2", f"the Pods heading is {st['heading']!r}")
    t.check(st["bodyHeads"] == ["Planned and Done by Week", "Projects, Teams and Pods"], f"the page-level headings are {st['bodyHeads']}")


LNG_KEYS_JS = "(() => Object.fromEntries(DATA.epics.filter(e => /^Fixed case lng_/.test(e.t)).map(e => [e.t.replace('Fixed case ', ''), e.k])))()"


@SUITE.test("long_the_boundary_and_the_population_by_hand")
def _(t: T):
    """Known cycle times in one team: 7 is not over, 8 is; 0 is a cycle time; no cycle time, Maintenance and SOW are not in the population; an In Progress epic that carries a 30 and a Done epic of 27.2 are not counted;
    Cycle 2 holds one over and one exactly 7. Asserted by hand, then the page's key link must open exactly the epics named here."""
    for h, pop, over in (
        (LNG, ["lng_7", "lng_8", "lng_0", "lng_9", "lng_12_feature", "lng_nopod_8", "lng_dc2_8", "lng_dc2_7"], ["lng_8", "lng_9", "lng_12_feature", "lng_nopod_8", "lng_dc2_8"]),
        (LNG + "&dc=1", ["lng_7", "lng_8", "lng_0", "lng_9", "lng_12_feature", "lng_nopod_8"], ["lng_8", "lng_9", "lng_12_feature", "lng_nopod_8"]),
        (LNG + "&dc=2", ["lng_dc2_8", "lng_dc2_7"], ["lng_dc2_8"]),
    ):
        data, st = load(h, "long")
        keys = ctx.chrome.js(LNG_KEYS_JS)
        L = st["long"]
        share = f" ({PO.jround(100 * len(over) / len(pop))}%)" if len(pop) >= 5 else ""
        t.check(L["v"] == str(len(over)) and L["l"] == "Took Over 7 Days", f"#{h}: the tile prints {L['l']!r} {L['v']!r}, by hand {len(over)}")
        t.check(L["s"] == f"of {len(pop)} Done epics{share}", f"#{h}: the sub line is {L['s']!r}, by hand 'of {len(pop)} Done epics{share}'")
        href = ctx.chrome.js("(() => { const a = document.querySelector('#cy-kpis1 [data-kpi=\"long\"] .v a'); return a ? [a.getAttribute('href'), a.getAttribute('data-tip')] : null; })()")
        t.check(bool(href), f"#{h}: the number is not a link")
        if href:
            t.check(PO._key_in(href[0]) == {keys[n] for n in over}, f"#{h}: the link opens {sorted(PO._key_in(href[0]))[:3]}, by hand {sorted(keys[n] for n in over)[:3]}")
            first = href[1].split("\n")
            t.check(first[0] == f"{len(over)} Done {'epic' if len(over) == 1 else 'epics'} planned in {'Delivery Cycles 1 and 2' if h == LNG else 'Delivery Cycle ' + h[-1]} took more than 7 days." and first[1] == "Cycle time as in the Efficiency section.",
                    f"#{h}: the hover is {first[:2]}")
            t.check(len(re.findall(r"\bwords\b", href[1])) == 0 and ((len(over) > 3) == bool(re.search(r"Exact list of \d+ issues", href[1]))), f"#{h}: the exact-list line: {href[1]!r}")
    # the zero cases and the sub lines that have nothing to count
    for h, want_v, want_s in (("r=27.1&p=PMN&pd=pod-lvl-a3", "0", "no epic is Done yet"), ("r=26.4&p=PMN&pd=pod-lng-solo-a", "0", "no Done epic has a cycle time to count"),
                              ("r=26.4&p=PMN&pd=pod-lng-solo-b", "0", "no Done epic has a cycle time to count"), ("r=26.4&p=PMN&pd=pod-lng-b", "2", "of 2 Done epics"),
                              ("r=26.4&p=PMN&pd=~none&t=Team%20Seed%20Lng", "1", "of 1 Done epic")):
        data, st = load(h, "long")
        t.check((st["long"]["v"], st["long"]["s"]) == (want_v, want_s), f"#{h}: the tile prints {st['long']['v']!r} / {st['long']['s']!r}, by hand {want_v!r} / {want_s!r}")
        t.check(bool(ctx.chrome.js("!document.querySelector('#cy-kpis1 [data-kpi=\"long\"] .v a')")) == (want_v == "0"), f"#{h}: a 0 is plain text, a number above 0 is a link")


@SUITE.test("long_equals_the_recount_in_every_cycle_view_and_project_set")
def _(t: T):
    """The tile, its sub line, link and hover against pod_oracle.long_tile in the plain views (both cycles, each cycle, several projects, a closed release): the pod oracle runs inside check_pods."""
    views = ["r=27.1", "r=27.1&dc=1", "r=27.1&dc=2", "r=27.1&p=PMN", "r=27.1&p=PMN|CXCO", "r=26.4", "r=26.4&dc=1", "r=27.2", "r=27.1&t=Team%20Alpha", LNG, LNG + "&dc=2"]
    r = LC.sweep(kinds=("long", "variant"), hashes=views)
    t.check(not r["pod_bad"], f"{len(r['pod_bad'])} differences from the independent recount, e.g. {r['pod_bad'][:3]}")
    seen = r["pod_seen"]
    t.check(seen["long>0"] > 0 and seen["long==0"] > 0, f"the recount never reached both a non-empty and an empty Took Over 7 Days ({dict(seen)})")
    t.check(not r["errors"] and not r["skipped"], f"errors {r['errors'][:2]} skipped {r['skipped'][:2]}")


READ_JS = "(() => ({hash: location.hash, pods: [...state.pods], projects: [...state.projects], focus: document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.cypod || null : null}))()"


def click(ch, tok: str) -> None:
    ch.js(f"(() => {{ const b = document.querySelector('[data-cypod=\"{tok}\"]'); b.focus(); b.click(); }})()")
    time.sleep(0.15)


def interaction_problems(kind: str = "stock") -> list[str]:
    """Drives the chips like a reader, on one page, and returns every difference from what the owner decided."""
    bad: list[str] = []
    data, url = LC.page(kind)
    ch = ctx.chrome
    base = "pod-lvl-a2" if kind == "stock" else "pod-seed-four"
    other = "pod-ns-a" if kind == "stock" else "pod-seed-three"

    def recount(tag: str) -> None:
        st = ch.js(PO.POD_JS)
        res = dict(pod_bad=[], pod_seen=collections.Counter())
        PO.check_pods(res, data, st, tag, ch)
        PO.check_page(res, data, ch.js(PO.PAGE_JS), st, tag, ch)
        bad.extend(res["pod_bad"][:2])

    ch.goto(url + "#r=27.1&p=PMN")
    kit.wait_ready(ch)
    time.sleep(0.15)
    s0 = ch.js(STATE_JS)
    n_reset0 = s0["reset"]
    # 1. choose one pod
    click(ch, base)
    s1 = ch.js(STATE_JS)
    if s1["pods"] != [base] or f"pd={base}" not in s1["hash"] or not s1["changed"] or "●" not in s1["dot"]:
        bad.append(f"choosing {base}: pods {s1['pods']}, hash {s1['hash']}, changed {s1['changed']}, marker {s1['dot']!r}")
    if s1["reset"] != "Reset Filters (2)" or n_reset0 != "Reset Filters (1)":
        bad.append(f"Reset Filters counts {n_reset0!r} before and {s1['reset']!r} after choosing a pod (one more filter)")
    if not s1["note"] or not s1["note"].startswith("Pods chosen: ") or not s1["note"].endswith("Tiles and tables count only their epics. Show All Pods") or not s1["inBanner"] or not s1["noteBtn"]:
        bad.append(f"the line under the banner is {s1['note']!r}")
    if s1["focus"] != base:
        bad.append(f"the focus left the chip after the click: {s1['focus']}")
    on = {c["tok"] for c in s1["chips"] if c["on"]}
    if on != {base}:
        bad.append(f"after choosing {base} the pressed chips are {sorted(on)}")
    recount(f"{kind} one pod")
    # 2. add a second, then the No Pod Label chip; four pods say '4 pods'
    click(ch, other)
    s2 = ch.js(STATE_JS)
    if set(s2["pods"]) != {base, other} or s2["reset"] != "Reset Filters (2)":
        bad.append(f"two pods: {s2['pods']}, {s2['reset']}")
    if not s2["note"] or s2["note"].count(",") < 1 or "pods" in s2["note"].split(".")[0]:
        bad.append(f"two pods chosen, the line is {s2['note']!r}")
    recount(f"{kind} two pods")
    click(ch, "~none")
    s3 = ch.js(STATE_JS)
    if set(s3["pods"]) != {base, other, "~none"} or "No Pod Label" not in (s3["note"] or ""):
        bad.append(f"No Pod Label chosen: {s3['pods']} {s3['note']!r}")
    recount(f"{kind} pods and No Pod Label")
    extra = [c["tok"] for c in s3["chips"] if c["tok"] not in ("all", "~none", base, other)][0]
    click(ch, extra)
    s3b = ch.js(STATE_JS)
    if not (s3b["note"] or "").startswith("Pods chosen: 4 pods. Tiles and tables count only their epics."):
        bad.append(f"four pods chosen, the line is {s3b['note']!r} (more than three say '4 pods')")
    # 3. the address round trip
    h = s3b["hash"]
    ch.goto(url + h)
    kit.wait_ready(ch)
    time.sleep(0.15)
    s4 = ch.js(STATE_JS)
    if sorted(s4["pods"]) != sorted(s3b["pods"]) or {c["tok"] for c in s4["chips"] if c["on"]} != set(s3b["pods"]):
        bad.append(f"the address {h} does not bring back the choice: {s4['pods']} vs {s3b['pods']}")
    recount(f"{kind} after the round trip")
    # 4. a chosen chip again turns it off; All Pods clears
    click(ch, extra)
    s5 = ch.js(STATE_JS)
    if extra in s5["pods"] or len(s5["pods"]) != 3:
        bad.append(f"a second click on {extra} must turn it off: {s5['pods']}")
    click(ch, "all")
    s6 = ch.js(STATE_JS)
    if s6["pods"] or "pd=" in s6["hash"] or s6["note"] is not None or s6["changed"] or s6["reset"] != "Reset Filters (1)" or s6["focus"] != "all":
        bad.append(f"All Pods: pods {s6['pods']}, hash {s6['hash']}, line {s6['note']!r}, changed {s6['changed']}, reset {s6['reset']!r}, focus {s6['focus']}")
    recount(f"{kind} All Pods")
    # 5. Show All Pods in the line under the banner
    click(ch, base)
    ch.js("document.querySelector('#cy-podsline button[data-cypod=\"all\"]').click()")
    time.sleep(0.15)
    s7 = ch.js(STATE_JS)
    if s7["pods"] or s7["note"] is not None:
        bad.append(f"Show All Pods in the line does not clear the choice: {s7['pods']} {s7['note']!r}")
    # 6. a change of project clears the choice (the row follows the new project), Reset Filters clears it and the count
    click(ch, base)
    ch.js("document.querySelector('#f-projects [data-p=\"CXCO\"]').click()")
    time.sleep(0.2)
    s8 = ch.js(STATE_JS)
    if s8["pods"] or "pd=" in s8["hash"] or s8["projects"] != ["CXCO"] or s8["note"] is not None:
        bad.append(f"after the project changed: pods {s8['pods']}, hash {s8['hash']}, projects {s8['projects']}")
    for m in chip_problems(data, s8, "27.1", "CXCO") if not s8["hidden"] else []:
        bad.append(f"after the project changed (CXCO): {m}")
    ch.js("document.querySelector('#f-projects [data-p=\"PMN\"]').click()")
    time.sleep(0.2)
    s9 = ch.js(STATE_JS)
    if s9["pods"] or [c["tok"] for c in s9["chips"] if c["on"]] != ["all"]:
        bad.append(f"back on PMN the earlier choice is back: {s9['pods']}")
    click(ch, base)
    ch.js("document.querySelector('#f-projects [data-all]').click()")
    time.sleep(0.2)
    s10 = ch.js(STATE_JS)
    if not s10["hidden"] or s10["pods"] or "pd=" in s10["hash"]:
        bad.append(f"All Projects: hidden {s10['hidden']}, pods {s10['pods']}, hash {s10['hash']}")
    ch.js("document.querySelector('#f-projects [data-p=\"PMN\"]').click()")
    time.sleep(0.2)
    click(ch, base)
    ch.js("document.getElementById('f-reset').click()")
    time.sleep(0.2)
    s11 = ch.js(STATE_JS)
    if s11["pods"] or "pd=" in s11["hash"] or not s11["resetOff"] or s11["reset"] != "Reset Filters" or not s11["hidden"] or len(s11["projects"]) < 2:
        bad.append(f"Reset Filters: pods {s11['pods']}, {s11['hash']}, button {s11['reset']!r} disabled {s11['resetOff']}, row hidden {s11['hidden']}, projects {s11['projects']}")
    # 7. the Release and Teams filters keep the choice (only the project selection clears it)
    ch.goto(url + f"#r=27.1&p=PMN&pd={base}")
    kit.wait_ready(ch)
    time.sleep(0.15)
    ch.js("(() => { const r = document.getElementById('f-release'); r.value = '26.4'; r.dispatchEvent(new Event('change', {bubbles: true})); })()")
    time.sleep(0.2)
    s12 = ch.js(STATE_JS)
    if s12["pods"] != [base] or s12["release"] != "26.4":
        bad.append(f"the Release filter changed the pod choice: {s12['pods']} {s12['release']}")
    for m in chip_problems(data, s12, "26.4", "PMN", None, {base}):
        bad.append(f"Release 26.4 with {base} chosen: {m}")
    recount(f"{kind} release changed under a choice")
    return bad


@SUITE.test("pods_chips_behave_like_the_owner_decided_stock")
def _(t: T):
    bad = interaction_problems("stock")
    t.check(not bad, f"{len(bad)} differences: {bad[:4]}")


@SUITE.test("pods_chips_behave_like_the_owner_decided_variant")
def _(t: T):
    bad = interaction_problems("variant")
    t.check(not bad, f"{len(bad)} differences: {bad[:4]}")


@SUITE.test("pods_the_empty_state_says_so_and_clears_with_one_click")
def _(t: T):
    """Pod-Lng-B has Done epics planned in Cycle 1 only: with Cycle 2 shown nothing is planned (and no epic is carried over), so the section says so in the owner's words and the button clears the choice."""
    data, st = load("r=26.4&p=PMN&dc=2&pd=pod-lng-b")
    win = PO.window_of(data, "26.4", ["2"])
    want = f"No epics planned in Delivery Cycle 2 ({win['start']} to {win['end']}) for the chosen pods. Choose other pods or Show All Pods."
    t.check(st["empty"] == want, f"the empty state is {st['empty']!r}, expected {want!r}")
    t.check(st["emptyBtn"] and not st["weekly"] and st["bodyHeads"] == [], f"the button is in the sentence ({st['emptyBtn']}), no table is drawn ({st['bodyHeads']})")
    t.check(st["planned"]["v"] == "0" and st["long"]["v"] == "0" and st["long"]["s"] == "no epic is Done yet", f"the tiles are zero: {st['planned']} {st['long']}")
    ctx.chrome.js("document.querySelector('#cy-body .empty button[data-cypod=\"all\"]').click()")
    time.sleep(0.2)
    st2 = ctx.chrome.js(STATE_JS)
    t.check(st2["pods"] == [] and st2["empty"] is None and st2["weekly"], f"Show All Pods in the sentence does not restore the section: {st2['pods']} {st2['empty']!r}")
    data, st3 = load("r=27.1&p=PMN&dc=2")
    t.check(st3["empty"] is None, "the empty state shows with no pod chosen")


@SUITE.test("pods_the_cycles_section_names_only_the_new_words")
def _(t: T):
    """The owner's wording: none of the retired labels and phrases is anywhere in the section (tiles, hovers, lists, definitions); the new ones are."""
    data, url = LC.page("stock")
    ch = ctx.chrome
    ch.goto(url + "#r=27.1&p=PMN")
    kit.wait_ready(ch)
    txt = ch.js("""(() => { document.querySelectorAll('#cy-sec details').forEach(d => { d.open = true; });
      const hov = [...document.querySelectorAll('#cy-sec [data-tip]')].map(e => e.getAttribute('data-tip')).join('\\n');
      const lists = []; document.querySelectorAll('#cy-kpis2 [data-cyact="pods"]').forEach(b => { b.click(); lists.push(document.getElementById('cy-podlist').textContent); b.click(); });
      return document.getElementById('cy-sec').textContent + '\\n' + hov + '\\n' + lists.join('\\n'); })()""")
    for gone in ("Idle Pods", "Pods To Level", "Pods to level", "Waiting Dependents", "Waiting dependents", "Not-Started Epics", "Not-started epics", "Pod health", "Weekly Plan vs. Actual", "of them stale", "Stale",
                 "In-Progress", "in-progress", "In-progress", "Without a Pod Label", "without a pod label,", "Pods With More Than", "run --add-planning", "Dependents Due"):
        t.check(gone not in txt, f"the retired wording {gone!r} is still in the Cycles section")
    for said in ("Took Over 7 Days", "Took over 7 days", "Active: status In Progress or Validation.", "Overdue more than 30 days", "Planned and Done by Week", "Pods Without Planned Epics", "Pods over 3 epics", "Busiest and lightest pods",
                 "Active epics without pod", "Not started due soon", "Waiting items due soon", "Filter by Pod", "Showing Delivery Cycles 1 and 2 combined"):
        t.check(said in txt, f"the new wording {said!r} is not in the Cycles section")
    t.check("Done epics planned in the selected Delivery Cycles whose cycle time is more than 7 days; cycle time as in Efficiency." in txt, "the definition of Took over 7 days does not give its rule")
    t.check("epics in Maintenance and SOW are left out, as in Cycle Time per Release" in txt, "the definition of Took over 7 days does not name the excluded Issue Categories")


@SUITE.test("long_six_tiles_lay_out_cleanly_at_1400_1100_760_and_390")
def _(t: T):
    """The headline strip holds six tiles: six columns on a wide screen, three from 1100 px down, two on a phone; no tile is clipped, none overlaps another and the page does not scroll sideways."""
    data, url = LC.page("stock")
    ch = ctx.chrome
    want = {1400: 6, 1100: 3, 760: 3, 390: 2}
    try:
        for w, cols in want.items():
            ch.viewport(w, 900, mobile=False)
            ch.goto(url + "#r=27.1")
            kit.wait_ready(ch)
            time.sleep(0.2)
            m = ch.js("""(() => { const g = document.getElementById('cy-kpis1'), tiles = [...g.children], rs = tiles.map(k => k.getBoundingClientRect());
              const tops = [...new Set(rs.map(r => Math.round(r.top)))].sort((a, b) => a - b), first = rs.filter(r => Math.round(r.top) === tops[0]).length;
              let overlap = 0; for (let i = 0; i < rs.length; i++) for (let j = i + 1; j < rs.length; j++) { const a = rs[i], b = rs[j]; if (a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1) overlap++; }
              return {n: tiles.length, cols: getComputedStyle(g).gridTemplateColumns.split(' ').length, first, rows: tops.length, overlap, clipped: tiles.filter(k => k.scrollWidth > k.clientWidth + 1).map(k => k.dataset.kpi),
                right: Math.max(...rs.map(r => r.right)), vw: document.documentElement.clientWidth, sx: document.documentElement.scrollWidth, lefts: Math.min(...rs.map(r => r.left)),
                labels: tiles.map(k => { const l = k.querySelector('.l'); return l.getBoundingClientRect().height; }) }; })()""")
            t.check(m["n"] == 6 and m["cols"] == cols and m["first"] == cols and m["rows"] == 6 // cols, f"{w} px: {m['n']} tiles, {m['cols']} columns (want {cols}), {m['first']} in the first row, {m['rows']} rows")
            t.check(m["overlap"] == 0 and not m["clipped"] and m["right"] <= m["vw"] + 1 and m["lefts"] >= -1 and m["sx"] <= m["vw"] + 1, f"{w} px: overlap {m['overlap']}, clipped {m['clipped']}, right edge {m['right']} of {m['vw']}, scroll width {m['sx']}")
    finally:
        ch.viewport(1400, 900)


# --------------------------------------------------------------------------------------------- the suite must fail on a seeded defect
MUT_VIEWS = ["r=26.4&p=PMN&t=Team%20Seed%20Lng", "r=27.1&p=PMN&pd=pod-lvl-a2|~none", "r=26.4&p=PMN&dc=2&pd=pod-lng-a|pod-lng-b", "r=27.1&p=PMN&pd=pod-ns-a|pod-wip-four"]
MUT_VARIANT = ["r=27.1&p=PMN&pd=pod-seed-twoa", "r=27.1&p=PMN&pd=pod-seed-case|pod-seed-four"]
LONG_MUTANTS = [
    ("7 days counts as took over (>= instead of >)", "const cyLong = e => cyCtPop(e) && e.ed > CY.longCycle;", "const cyLong = e => cyCtPop(e) && e.ed >= CY.longCycle;"),
    ("the threshold constant is 8", "longCycle: 7,", "longCycle: 8,"),
    ("the excluded Issue Categories are counted", "const cyCtPop = e => cyDone(e) && !e.ex && e.ed != null;", "const cyCtPop = e => cyDone(e) && e.ed != null;"),
    ("an epic that is not Done counts with its cycle time", "const cyCtPop = e => cyDone(e) && !e.ex && e.ed != null;", "const cyCtPop = e => !e.ex && e.ed != null;"),
    ("an epic with no cycle time is in the population", "const cyCtPop = e => cyDone(e) && !e.ex && e.ed != null;", "const cyCtPop = e => cyDone(e) && !e.ex;"),
    ("the share is out of every Done epic, not the population", "const n = s.long.length, m = s.ctPop.length;", "const n = s.long.length, m = s.done.length;"),
    ("the link opens the whole population, not the epics over 7 days", "tlink(n, cyKeyIn(s.long.map(e => e.k)),", "tlink(n, cyKeyIn(s.ctPop.map(e => e.k)),"),
    ("the cycle time is read from the calendar days, not the EDCT", "ed: cycleOf(e), ex: cycleExcluded(e)", "ed: e.cal === undefined ? cycleOf(e) : e.cal, ex: cycleExcluded(e)"),
    ("the share shows under 5 epics", "of ${m.toLocaleString(\"en-US\")} Done ${epicWord(m)}${cyShare(n, m)}", "of ${m.toLocaleString(\"en-US\")} Done ${epicWord(m)} (${pct(n, m)}%)"),
]
POD_MUTANTS = [
    ("an epic must carry ALL chosen pods, not any", "(e.pl.length ? e.pl.some(l => state.pods.has(l.toLowerCase())) : state.pods.has(CY_NOPOD))", "(e.pl.length ? e.pl.every(l => state.pods.has(l.toLowerCase())) : state.pods.has(CY_NOPOD))"),
    ("No Pod Label never passes", ": state.pods.has(CY_NOPOD))", ": false)"),
    ("the headline tiles ignore the pod filter", "const planned = M.planned(), x = {s: cyStats(planned, M.carry()),", "const planned = M.planned(), x = {s: cyStats(M.every.filter(e => e.due && e.due >= M.c.start && e.due <= M.c.end), M.carry()),"),
    ("the weekly table ignores the pod filter", "const c = M.c, planned = M.planned(), W = dcWeeks(state.release)", "const c = M.c, planned = M.every.filter(e => e.due && e.due >= M.c.start && e.due <= M.c.end), W = dcWeeks(state.release)"),
    ("Pods Without Planned Epics lists the pods of an epic that were not chosen", "const pods = cyPodsOf(epics).filter(p => !cyPodsOn() || state.pods.has(p.key)), ps = new Set(planned);", "const pods = cyPodsOf(epics), ps = new Set(planned);"),
    ("the pod rows of the table hold the pods of an epic that were not chosen", " || (cyPodsOn() && !state.pods.has(k))) return; seen.add(k);", ") return; seen.add(k);"),
    ("the Jira links ignore the chosen pods", "[cyNodeClause(g), cyPodFilterQ(), w].filter(Boolean)", "[cyNodeClause(g), w].filter(Boolean)"),
    ("the total row and the row links ignore the chosen pods", "extra: [n.level === \"pod\" ? podSpellingsClause(n.spellings) : \"\", cyPodFilterQ()].filter(Boolean).join(\" AND \")", "extra: n.level === \"pod\" ? podSpellingsClause(n.spellings) : \"\""),
    ("the Jira clause of a chosen pod leaves out its other spellings", "state.pods.forEach(k => (R.psp.get(proj + \"\\n\" + k) || []).forEach(l => sp.add(l)));", "state.pods.forEach(k => (R.psp.get(proj + \"\\n\" + k) || []).forEach(l => sp.size || sp.add(l)));"),
]
BEHAVIOUR_MUTANTS = [
    ("an address with pd and several projects still sets the choice", "{ const pd = state.projects.size === 1 ? (list(\"pd\") || []) : [];", "{ const pd = (list(\"pd\") || []);"),
    ("the chips show with every project", "const P = state.projects.size === 1 ? [...state.projects][0] : null,", "const P = [...state.projects][0],"),
    ("a change of project keeps the choice", "function projChanged(el) {\n  state.pods = new Set();", "function projChanged(el) {\n  "),
    ("the address does not carry the choice", "if (state.pods.size && state.projects.size === 1) h.set(\"pd\",", "if (false) h.set(\"pd\","),
    ("Reset Filters does not count the pods", "dc: !dcState().all, pods: state.pods.size > 0 && state.projects.size === 1,", "dc: !dcState().all, pods: false,"),
    ("the chip counts are the epics planned in the cycles", "const counts = new Map(); let none = 0;\n  if (R) M.every.forEach(", "const counts = new Map(); let none = 0;\n  if (R) M.epics.forEach("),
]


def mutated(src: str, i: int, what: str, old: str, new: str) -> Path | None:
    if src.count(old) != 1:
        raise kit.Skip(f"the seeding anchor for '{what}' is not in this template exactly once")
    tmp = Path(ctx.dir) / f"pods_mutant_{i}.html"
    tmp.write_text(src.replace(old, new, 1), encoding="utf-8")
    return tmp


ROWS_JS = r"""(() => { const ex = document.querySelector('[data-cyact="expall"]'); if (ex) ex.click();
  const link = c => { const a = c.querySelector('a[href]'); return a ? a.getAttribute('href') : null; };
  return [...document.querySelectorAll('#cy-ovbody tr[data-id]')].filter(r => r.dataset.lvl !== 'epics').map(r => ({name: r.querySelector('.cyname').textContent.trim(), lvl: r.dataset.lvl, n: r.children[2].textContent.trim(), href: link(r.children[2])}))
    .concat([...document.querySelectorAll('#cy-ovtable tfoot tr')].map(r => ({name: 'total', lvl: 'total', n: r.children[2].textContent.trim(), href: link(r.children[2])}))); })()"""


def row_link_problems(data: dict, url: str, hashes: list) -> list[str]:
    """The Epics in Release link of every row of the Projects, Teams and Pods table (and the total row) finds exactly the epics its number prints, under the chosen pods: evaluated over the baked epics."""
    import urllib.parse
    import jql_eval as J
    universe = [LC.epic_issue(e) for e in data["epics"]]
    bad = []
    ch = ctx.chrome
    for h in hashes:
        ch.goto(url + "#" + h)
        kit.wait_ready(ch)
        time.sleep(0.1)
        rows = ch.js(ROWS_JS) or []
        for r in rows:
            n = int(r["n"].replace(",", "") or 0)
            if not r["href"]:
                if n:
                    bad.append(f"#{h}: row {r['name']} prints {n} with no link")
                continue
            jql = urllib.parse.parse_qs(urllib.parse.urlsplit(r["href"]).query).get("jql", [""])[0]
            found = sum(1 for i in universe if J.evaluate(J.parse(jql), i))
            if found != n:
                bad.append(f"#{h}: the {r['lvl']} row {r['name']} prints {n}, its query finds {found}")
    return bad


@SUITE.test("pods_row_and_total_links_find_the_epics_they_print")
def _(t: T):
    """The Epics in Release link of every project, team and pod row and of the total row carries the chosen pods as a Jira clause: the query finds exactly the epics the number prints."""
    data, url = LC.page("stock")
    bad = row_link_problems(data, url, ["r=27.1&p=PMN&pd=pod-lvl-a2|~none", "r=27.1&p=PMN&pd=pod-ns-a|pod-wip-four", "r=27.1&p=PMN&pd=~none", "r=27.1&p=PMN"])
    t.check(not bad, f"{len(bad)} row links differ from their number: {bad[:3]}")
    data, url = LC.page("variant")
    bad = row_link_problems(data, url, ["r=27.1&p=PMN&pd=pod-seed-twoa", "r=27.1&p=PMN&pd=pod-seed-case|~none"])
    t.check(not bad, f"{len(bad)} row links differ from their number (seeded pods): {bad[:3]}")


def sweep_caught(tmp: Path, kinds: tuple, hashes: list) -> int:
    r = LC.sweep(tmp, kinds=kinds, hashes=hashes)
    return sum(r["bad"].values()) + len(r["dom_bad"]) + len(r["pod_bad"]) + len(r["errors"])


def rows_caught(tmp: Path, hashes: list) -> int:
    old = ctx.template
    LC._page.clear()
    ctx.template = tmp
    try:
        data, url = LC.page("stock")
        return len(row_link_problems(data, url, hashes))
    finally:
        ctx.template = old
        LC._page.clear()


@SUITE.test("selftest_pod_and_long_recounts_catch_seeded_defects")
def _(t: T):
    src = ctx.template.read_text(encoding="utf-8")
    for i, (what, old, new) in enumerate(LONG_MUTANTS):
        tmp = mutated(src, i, what, old, new)
        t.check(sweep_caught(tmp, ("long",), MUT_VIEWS[:1] + ["r=26.4&p=PMN&t=Team%20Seed%20Lng&dc=1", "r=26.4&p=PMN&t=Team%20Seed%20Lng&dc=2", "r=26.4&p=PMN&pd=pod-lng-solo-a", "r=27.1"]) > 0, f"the Took Over 7 Days recount did not notice the seeded defect: {what}")
    for i, (what, old, new) in enumerate(POD_MUTANTS):
        tmp = mutated(src, 100 + i, what, old, new)
        a = sweep_caught(tmp, ("stock",), MUT_VIEWS[1:] + ["r=27.1&p=PMN|CXCO"])
        b = sweep_caught(tmp, ("variant",), MUT_VARIANT) if not a else 1
        c = rows_caught(tmp, ["r=27.1&p=PMN&pd=pod-lvl-a2|~none"]) if not (a or b) else 1
        t.check(a + b + c > 0, f"the pod filter recount did not notice the seeded defect: {what}")


@SUITE.test("selftest_pod_chip_behaviour_catches_seeded_defects")
def _(t: T):
    src = ctx.template.read_text(encoding="utf-8")
    old_tpl = ctx.template
    for i, (what, old, new) in enumerate(BEHAVIOUR_MUTANTS):
        tmp = mutated(src, 200 + i, what, old, new)
        LC._page.clear()
        ctx.template = tmp
        try:
            try:
                bad = interaction_problems("stock") + chips_view_problems()
            except Exception as exc:                                                       # a seeded defect may break the page so badly that the drive cannot go on: that is noticed too
                bad = [f"exception: {type(exc).__name__}: {exc}"]
        finally:
            ctx.template = old_tpl
            LC._page.clear()
        t.check(bool(bad), f"the chip behaviour checks did not notice the seeded defect: {what}")


def chips_view_problems() -> list[str]:
    """The appearance rule of the chips on the current template: no row with every project or two, the row with one."""
    bad = []
    for h, hidden in (("r=27.1", True), ("r=27.1&p=PMN|CXCO", True), ("r=27.1&p=PMN|CXCO&pd=pod-lvl-a2", True), ("r=27.1&p=PMN", False)):
        data, st = load(h)
        if st["hidden"] != hidden or (hidden and st["pods"]):
            bad.append(f"#{h}: the row is hidden {st['hidden']}, the choice is {st['pods']}")
        elif not hidden:
            bad += chip_problems(data, st, "27.1", "PMN")
    return bad


if __name__ == "__main__":
    sys.exit(kit.cli(SUITE, __doc__))
