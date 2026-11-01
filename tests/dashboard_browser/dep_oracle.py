#!/usr/bin/env python3
"""Dependency direction oracle: the two Dependencies quick filters Blocked by Outside Scope (hash dp=blockedby) and Blocking Outside Scope (dp=blocking).

An independent Python recount of the open dependency pairs (from the baked links, epics and far-end issues; nothing of the page's code is reused) is compared with what the page
prints, in several filter states and under every quick filter that shows the board:

  * the chip counts, the 'Showing N of M open' line, the provider cards (the keys of each card's 'Open with Dependents' link), the Show data rows, and the Direction column;
  * the two numbers in the headline clause, with the issues their links open (the keys at both ends of every counted pair) and the 6,000 character budget;
  * the cues in text (never color alone): 'Outside scope · ' on the card meta line, 'Blocks outside scope:' against 'Also blocks outside scope:', the aria-label of the key link,
    and 'Planning data not tracked here' for a provider the page holds no planning data for;
  * the hash round trip, native radios in the one radiogroup, the 320 px layout, the empty states and the omitted half of the headline clause.

The direction is the pair's own: inbound = the dependent is in scope and the provider is not (an epic in scope waits on something outside), outbound = the reverse; 'in scope' is the page's
scope (release, projects, teams and Commitment Types). Both directions read every OPEN pair (neither end Done) at ANY issue type, whichever of Epics Only and All is chosen.
Four seeded defects (swapped direction, non-epic providers dropped, Done pairs counted, the Direction column swapped) must each be caught: a green oracle is not a blind one.

    python3 dep_oracle.py [--live] [--only NAME]
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
import kit                                                                          # noqa: E402
import make_synthetic as MS                                                         # noqa: E402
from kit import ctx, T                                                              # noqa: E402

SUITE = kit.Suite("Delivery Pulse dependency direction")
KEYRE = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
URL_BUDGET = 6000
NO_TEAM = "(No Team)"
COMMITS = ("Committed", "Not Set", "Stretch")
DIR_TEXT = {"in": "Waits on outside scope", "out": "Needed by outside scope", "within": "Within scope"}
FILTER_NAME = {"blockedby": "Blocked by Outside Scope", "blocking": "Blocking Outside Scope"}


# --------------------------------------------------------------------------------------------- the independent recount
class View:
    def __init__(self, hash_: str, rel: str = "27.1", projects=None, teams=(), commits=COMMITS):
        self.hash, self.rel, self.projects, self.teams, self.commits = hash_, rel, projects, set(teams), set(commits)


def recount(data: dict, v: View) -> dict:
    epics = {e["k"]: e for e in data["epics"]}
    ext = data.get("ext") or {}
    projects = set(v.projects or {e["p"] for e in data["epics"]})
    scope = {e["k"] for e in data["epics"] if e["p"] in projects and v.rel in e["fv"] and (e.get("c") or "Not Set") in v.commits
             and (not v.teams or v.teams & set(e.get("tm") or [NO_TEAM]))}

    def rec(k: str) -> dict:
        e = epics.get(k)
        if e:
            return {"ty": "Epic", "s": e["s"], "held": True, "dd": e.get("dd"), "ts": e.get("ts")}
        x = ext.get(k)
        if x:
            return {"ty": x.get("ty") or "Epic", "s": x["s"], "held": False, "dd": x.get("dd"), "ts": x.get("ts")}
        return {"ty": "", "s": "", "held": False, "dd": None, "ts": None}

    pairs = {}
    for a, b, _ty in data["deps"]:
        pairs[(a, b)] = True                                           # the same pair as Dependency and as Blocks counts once
    out = {"inbound": [], "outbound": [], "within": [], "epics": [], "all": [], "done_in": 0, "done_out": 0, "scope": scope, "rec": rec}
    for (a, b) in sorted(pairs):
        if a not in scope and b not in scope:
            continue
        ra, rb = rec(a), rec(b)
        direction = "in" if (a in scope and b not in scope) else "out" if (b in scope and a not in scope) else "within"
        if ra["s"] == "Done" or rb["s"] == "Done":
            if direction == "in":
                out["done_in"] += 1
            elif direction == "out":
                out["done_out"] += 1
            continue
        out["all"].append((a, b, direction))
        if ra["ty"] == "Epic" and rb["ty"] == "Epic":
            out["epics"].append((a, b, direction))
        if direction == "in":
            out["inbound"].append((a, b, direction))
        elif direction == "out":
            out["outbound"].append((a, b, direction))
        else:
            out["within"].append((a, b, direction))
    return out


# --------------------------------------------------------------------------------------------- what the page prints
READ_JS = r"""(() => {
  const txt = e => (e ? e.textContent : '').replace(/\s+/g, ' ').trim();
  const chips = {}; document.querySelectorAll('#f-dp .chip').forEach(c => { const i = c.querySelector('input'); chips[i.value] = {n: txt(c.querySelector('.cnt')), title: c.title, on: i.checked, label: txt(c)}; });
  const link = a => ({text: txt(a), href: a.getAttribute('href'), tip: a.getAttribute('data-tip') || '', aria: a.getAttribute('aria-label') || ''});
  const sub = document.getElementById('dep-sub');
  const cards = [...document.querySelectorAll('#dep-body .bcard')].map(c => ({key: txt(c.querySelector('.bk a.cl')), aria: c.querySelector('.bk a.cl').getAttribute('aria-label'), meta: txt(c.querySelector('.bm')),
    labels: [...c.querySelectorAll('.blk .bl')].map(txt), notes: [...c.querySelectorAll('.bq')].map(txt), withHref: c.querySelector('.bwith a').getAttribute('href'), text: txt(c)}));
  const heads = [...document.querySelectorAll('#dep-body table.deptable thead th')].map(txt), di = heads.indexOf('Direction');
  const rows = [...document.querySelectorAll('#dep-body table.deptable tbody tr')].map(r => { const td = r.querySelectorAll('td'); return {d: txt(td[0].querySelector('.k')), p: txt(td[2].querySelector('.k')), dir: di < 0 ? null : txt(td[di]),
    planned: txt(td[5]), cells: td.length}; });
  const sh = document.getElementById('dep-showing'), empty = document.querySelector('#dep-body .empty'), group = document.getElementById('f-dp');
  return {chips, sub: txt(sub), subLinks: [...sub.querySelectorAll('a')].map(link), cards, heads, rows, showing: sh ? txt(sh) : null, empty: empty ? txt(empty) : null,
    radios: [...document.querySelectorAll('#f-dp input')].map(i => ({type: i.type, name: i.name, value: i.value, tab: i.getAttribute('tabindex')})), group: group ? group.getAttribute('role') : null,
    hash: location.hash, errors: 0};
})()"""


def keys_of(href: str | None) -> set:
    if not href:
        return set()
    q = urllib.parse.urlsplit(href)
    jql = urllib.parse.parse_qs(q.query).get("jql", [""])[0]
    return set(KEYRE.findall(jql))


def pair_keys(pairs) -> set:
    return {k for a, b, _ in pairs for k in (a, b)}


def load(url: str, hash_: str) -> dict:
    ch = ctx.chrome
    ch.goto(url + "#" + hash_)
    kit.wait_ready(ch)
    page = ch.js(READ_JS)
    page["console"] = ch.console_errors()
    return page


def expected_shown(O: dict, dp: str) -> list:
    return {"epics": O["epics"], "all": O["all"], "blockedby": O["inbound"], "blocking": O["outbound"]}[dp]


def check_view(page: dict, O: dict, v: View, dp: str) -> list[str]:
    """Every difference between the page and the independent recount for this view and quick filter."""
    bad: list[str] = []
    tag = f"[{v.hash or 'default'} dp={dp}]"
    if page["console"]:
        bad.append(f"{tag} console errors {page['console'][:2]}")
        return bad
    chips = page["chips"]
    want = {"epics": len(O["epics"]), "all": len(O["all"]), "blockedby": len(O["inbound"]), "blocking": len(O["outbound"])}
    for k, n in want.items():
        if chips.get(k, {}).get("n") != str(n):
            bad.append(f"{tag} chip {k} prints {chips.get(k, {}).get('n')}, the recount is {n}")
    for k in ("blockedby", "blocking"):
        denom = len(O["all"])
        if chips.get(k, {}).get("title") != f"{want[k]} of {denom} open":
            bad.append(f"{tag} chip {k} hover says '{chips.get(k, {}).get('title')}', expected '{want[k]} of {denom} open'")
    if not chips.get(dp, {}).get("on"):
        bad.append(f"{tag} the {dp} radio is not checked")
    shown = expected_shown(O, dp)
    any_type = dp in ("all", "blockedby", "blocking")
    denom = len(O["all"] if any_type else O["epics"])
    # ---- the headline clause: pair counts at any issue type, whatever the quick filter
    sub, links = page["sub"], page["subLinks"]
    for name, pairs, tipre, phrase in (("inbound", O["inbound"], r"waiting on a provider outside scope", "where an epic waits on a provider outside scope"),
                                       ("outbound", O["outbound"], r"where an item outside scope waits on a provider in scope", "where an item outside scope waits on a provider in scope")):
        found = [a for a in links if re.search(tipre, a["tip"])]
        if pairs:
            if len(found) != 1:
                bad.append(f"{tag} headline {name}: {len(found)} links, expected one")
                continue
            a = found[0]
            if a["text"] != str(len(pairs)):
                bad.append(f"{tag} headline {name} prints {a['text']}, the recount is {len(pairs)}")
            if a["href"] and keys_of(a["href"]) != pair_keys(pairs):
                bad.append(f"{tag} headline {name} link opens {len(keys_of(a['href']))} issues, the pairs have {len(pair_keys(pairs))}")
            if a["href"] and len(a["href"]) > URL_BUDGET:
                bad.append(f"{tag} headline {name} link is {len(a['href'])} characters")
            if not a["href"] and len(urllib.parse.quote("key in (" + ", ".join(sorted(pair_keys(pairs))) + ")")) < URL_BUDGET - 200:
                bad.append(f"{tag} headline {name} is plain text although the list is short")
            if phrase not in sub:
                bad.append(f"{tag} headline {name} lacks '{phrase}'")
        else:
            if found or phrase in sub:
                bad.append(f"{tag} headline {name} is shown although the recount is 0")
    if not O["inbound"] and not O["outbound"] and re.search(r"overdue\.\s*\d", sub):
        bad.append(f"{tag} a headline clause is shown with both directions at 0")
    if re.search(r"\b0 and 0\b|\b0 where\b", sub):
        bad.append(f"{tag} the headline says a zero: {sub[-160:]}")
    # ---- the board, the table and the 'Showing' line
    if not shown:
        if not page["empty"]:
            bad.append(f"{tag} nothing to show but no empty state")
        if page["cards"] or page["rows"]:
            bad.append(f"{tag} nothing to show but {len(page['cards'])} cards and {len(page['rows'])} rows")
        return bad
    got_cards = set()
    for c in page["cards"]:
        for dkey in keys_of(c["withHref"]):                                # the provider and every dependent it blocks
            if dkey != c["key"]:
                got_cards.add((dkey, c["key"]))
    if got_cards != {(a, b) for a, b, _ in shown}:
        bad.append(f"{tag} the cards hold {len(got_cards)} pairs, the recount {len(shown)}; missing {sorted({(a, b) for a, b, _ in shown} - got_cards)[:3]} extra {sorted(got_cards - {(a, b) for a, b, _ in shown})[:3]}")
    got_rows = [(r["d"], r["p"], r["dir"]) for r in page["rows"]]
    if sorted(got_rows) != sorted((a, b, DIR_TEXT[d]) for a, b, d in shown):
        bad.append(f"{tag} the table rows differ from the recount (or a Direction cell is wrong): page {len(got_rows)} rows, recount {len(shown)}; first differences {sorted(set(got_rows) ^ {(a, b, DIR_TEXT[d]) for a, b, d in shown})[:3]}")
    suffix = {"epics": "", "all": " (all issue types)"}.get(dp, f" (quick filter: {FILTER_NAME.get(dp)}, all issue types)")
    if page["showing"] != f"Showing {len(shown)} of {denom} open{suffix}.":
        bad.append(f"{tag} the Showing line says '{page['showing']}', expected 'Showing {len(shown)} of {denom} open{suffix}.'")
    if page["showing"] and "one card per provider" in page["showing"]:
        bad.append(f"{tag} the old tail is still in the Showing line")
    # ---- the cues in text
    by_prov: dict = {}
    for a, b, d in shown:
        by_prov.setdefault(b, []).append((a, d))
    for c in page["cards"]:
        pairs = by_prov.get(c["key"], [])
        if not pairs:
            bad.append(f"{tag} a card for {c['key']} that has no pair in the recount")
            continue
        prov_out = all(d == "in" for _, d in pairs)                        # the provider is outside scope exactly when every one of its pairs is inbound
        if any(d == "in" for _, d in pairs) != prov_out:
            bad.append(f"{tag} {c['key']}: a provider is both inside and outside scope in the recount")
        if prov_out != c["meta"].startswith("Outside scope · "):
            bad.append(f"{tag} {c['key']}: meta line '{c['meta'][:40]}', provider outside scope is {prov_out}")
        has_out = any(d == "out" for _, d in pairs)
        has_in_scope_dep = any(d in ("within",) for _, d in pairs)
        if has_out:
            want_label = "Also blocks outside scope:" if has_in_scope_dep else "Blocks outside scope:"
            if want_label not in c["labels"] or ("Also blocks outside scope:" in c["labels"]) != has_in_scope_dep:
                bad.append(f"{tag} {c['key']}: labels {c['labels']}, expected '{want_label}'")
        if has_out != ("needed by items outside scope" in c["aria"]):
            bad.append(f"{tag} {c['key']}: aria-label '{c['aria'][-60:]}', needed-by-outside is {has_out}")
        if prov_out != (", outside scope" in c["aria"]):
            bad.append(f"{tag} {c['key']}: aria-label '{c['aria'][-60:]}', provider outside scope is {prov_out}")
        rec = O["rec"](c["key"])
        untracked = (not rec["held"]) and not rec["dd"] and not rec["ts"]
        if untracked != ("Planning data not tracked here" in c["notes"]):
            bad.append(f"{tag} {c['key']}: planning note {c['notes']}, provider without planning data is {untracked}")
    for r in page["rows"]:
        rec = O["rec"](r["p"])
        if (not rec["held"] and not rec["dd"] and not rec["ts"]) != (r["planned"] == "Planning data not tracked here"):
            bad.append(f"{tag} row {r['d']} -> {r['p']}: Provider Planned says '{r['planned']}'")
    return bad


# --------------------------------------------------------------------------------------------- the fixture and the views
_cache: dict = {}


def fixture() -> dict:
    if not _cache:
        data = MS.make(MS.il_today())
        team = next(t for e in data["epics"] if e["p"] == "PMN" and MS.CURRENT in e["fv"] for t in (e.get("tm") or []))
        _cache.update(data=data, url=ctx.write(kit.fragment_for(data), "dep"), team=team)
    return _cache


def views(data: dict, team: str) -> list[View]:
    tq = urllib.parse.quote(team)
    return [View("r=27.1"), View("r=27.1&p=PMN", projects={"PMN"}), View("r=27.1&p=PMN|CXCO", projects={"PMN", "CXCO"}), View("r=26.4", rel="26.4"), View("r=27.2", rel="27.2"),
            View("r=27.1&c=Committed|Not%20Set", commits=("Committed", "Not Set")), View("r=27.1&c=Stretch", commits=("Stretch",)), View(f"r=27.1&t={tq}", teams={team})]


def run_views(url: str, data: dict, vs: list[View], dps=("epics", "all", "blockedby", "blocking")) -> list[str]:
    bad: list[str] = []
    for v in vs:
        O = recount(data, v)
        for dp in dps:
            page = load(url, v.hash + ("&" if v.hash else "") + f"dp={dp}")
            bad += check_view(page, O, v, dp)
    return bad


# --------------------------------------------------------------------------------------------- tests
@SUITE.test("direction_the_fixture_has_every_kind_of_pair")
def _(t: T):
    F = fixture()
    O = recount(F["data"], View("r=27.1"))
    prov = [O["rec"](b) for _, b, _ in O["inbound"]]
    dep = [O["rec"](a) for a, _, _ in O["outbound"]]
    t.check(len(O["inbound"]) >= 8 and len(O["outbound"]) >= 8 and len(O["within"]) >= 3, f"inbound {len(O['inbound'])}, outbound {len(O['outbound'])}, within {len(O['within'])}")
    t.check({"Epic", "Task", "Bug", "Story", "Capability"} <= {p["ty"] for p in prov}, f"inbound provider types {sorted({p['ty'] for p in prov})}")
    t.check({"Epic", "Task", "Story"} <= {p["ty"] for p in dep}, f"outbound dependent types {sorted({p['ty'] for p in dep})}")
    t.check(any(not p["held"] and not p["dd"] and not p["ts"] for p in prov) and any(not p["held"] and p["dd"] for p in prov), "providers with and without planning data are both present")
    t.check(O["done_in"] >= 1 and O["done_out"] >= 1, f"Done pairs of both directions (inbound {O['done_in']}, outbound {O['done_out']})")
    t.note(f"release 27.1, all projects: inbound {len(O['inbound'])} (epic providers {sum(1 for p in prov if p['ty'] == 'Epic')}), outbound {len(O['outbound'])}, within {len(O['within'])}, "
           f"epics only {len(O['epics'])}, all open {len(O['all'])}")


@SUITE.test("direction_chips_board_table_headline_and_cues_equal_an_independent_recount")
def _(t: T):
    F = fixture()
    bad = run_views(F["url"], F["data"], views(F["data"], F["team"]))
    for b in bad[:12]:
        t.failures.append(b)
    t.passed += 0 if bad else 1
    t.note(f"{len(views(F['data'], F['team']))} views x 4 quick filters compared")


@SUITE.test("direction_the_two_chips_are_native_radios_in_the_one_group_and_the_hash_round_trips")
def _(t: T):
    F = fixture()
    page = load(F["url"], "r=27.1&dp=blockedby")
    t.check(page["group"] == "radiogroup", "the chips are in a radiogroup")
    t.check(all(r["type"] == "radio" and r["name"] == "f-dp" and r["tab"] is None for r in page["radios"]) and len(page["radios"]) == 8, f"eight native radios, no tabindex: {page['radios']}")
    t.check(page["chips"]["blockedby"]["on"] and not page["chips"]["blocking"]["on"], "dp=blockedby selects Blocked by Outside Scope")
    t.check("Blocked by Outside Scope" in page["chips"]["blockedby"]["label"] and "Blocking Outside Scope" in page["chips"]["blocking"]["label"], "Title Case labels")
    ch = ctx.chrome
    click = "(() => { const i = document.querySelector('#f-dp input[value=\"%s\"]'); i.click(); return location.hash; })()"
    h = ch.js(click % "blocking")
    time.sleep(0.2)
    h = ch.js("location.hash")
    t.check("dp=blocking" in h, f"selecting Blocking Outside Scope writes dp=blocking: {h}")
    t.check(ch.js("document.querySelector('#f-dp input[value=\"blocking\"]').checked && document.getElementById('dep-showing').textContent.includes('Blocking Outside Scope')") is True, "and the board follows")
    ch.js(click % "epics")
    time.sleep(0.2)
    t.check("dp=" not in ch.js("location.hash"), "Epics Only (the default) writes no dp")
    page = load(F["url"], "r=27.1&dp=blocking")
    t.check(page["chips"]["blocking"]["on"], "dp=blocking round trips")
    page = load(F["url"], "r=27.1&dp=nonsense")
    t.check(page["chips"]["epics"]["on"], "an unknown dp value falls back to Epics Only")


@SUITE.test("direction_320px_chips_wrap_and_the_page_does_not_scroll_sideways")
def _(t: T):
    F = fixture()
    ch = ctx.chrome
    try:
        for w in (320, 800):
            ch.viewport(w, 900, mobile=False)
            load(F["url"], "r=27.1&dp=blockedby")
            m = ch.js("(() => { const g = document.getElementById('f-dp').getBoundingClientRect(); return {sw: document.documentElement.scrollWidth, w: window.innerWidth, right: Math.max(...[...document.querySelectorAll('#f-dp .chip')].map(c => c.getBoundingClientRect().right)), "
                      "rows: new Set([...document.querySelectorAll('#f-dp .chip')].map(c => Math.round(c.getBoundingClientRect().top))).size}; })()")
            t.check(m["sw"] <= m["w"], f"{w} px: the page scrolls sideways ({m})")
            t.check(m["right"] <= m["w"] + 1, f"{w} px: a chip leaves the viewport ({m})")
            t.check(m["rows"] >= 2, f"{w} px: the eight chips are on one row ({m})")
    finally:
        ch.viewport(1400, 900)


def _variant_page(drop: set) -> str:
    F = fixture()
    data = copy.deepcopy(F["data"])
    data["deps"] = [d for d in data["deps"] if (d[0], d[1]) not in drop]
    return ctx.write(kit.fragment_for(data), "depvar"), data


@SUITE.test("direction_a_half_with_zero_is_omitted_and_the_empty_state_says_why")
def _(t: T):
    F = fixture()
    O = recount(F["data"], View("r=27.1"))
    inb, outb = {(a, b) for a, b, _ in O["inbound"]}, {(a, b) for a, b, _ in O["outbound"]}
    for name, drop in (("no inbound pairs", inb), ("no outbound pairs", outb), ("neither direction", inb | outb)):
        url, data = _variant_page(drop)
        v = View("r=27.1")
        O2 = recount(data, v)
        t.check(bool(O2["all"]), f"{name}: the variant keeps other pairs")
        page = load(url, "r=27.1")
        sub = page["sub"]
        t.check(("waits on a provider outside scope" in sub) == bool(O2["inbound"]) and ("waits on a provider in scope" in sub) == bool(O2["outbound"]), f"{name}: headline clause halves wrong: {sub[-200:]}")
        t.check(not re.search(r"\b0 (?:dependenc|where)|0 and 0", sub), f"{name}: a zero is printed: {sub[-160:]}")
        if not O2["inbound"] and not O2["outbound"]:
            t.check(sub.rstrip().split("overdue.")[-1].strip().startswith("Follows:"), f"{name}: something follows the overdue sentence: {sub[-120:]}")
        for dp, left in (("blockedby", O2["inbound"]), ("blocking", O2["outbound"])):
            page = load(url, f"r=27.1&dp={dp}")
            bad = check_view(page, O2, v, dp)
            t.check(not bad, f"{name} dp={dp}: {bad[:2]}")
            if not left:
                t.check(page["empty"] and ("waits on a provider outside scope" if dp == "blockedby" else "waits on a provider in scope") in page["empty"] and "Epics Only" in page["empty"], f"{name} dp={dp}: empty text '{page['empty']}'")
                t.check(page["chips"][dp]["n"] == "0" and page["chips"][dp]["title"] == f"0 of {len(O2['all'])} open", f"{name} dp={dp}: chip {page['chips'][dp]}")


@SUITE.test("direction_no_open_pair_at_all_stays_calm_under_both_quick_filters")
def _(t: T):
    F = fixture()
    url, data = _variant_page({(d[0], d[1]) for d in F["data"]["deps"]})
    for dp in ("epics", "blockedby", "blocking"):
        page = load(url, f"r=27.1&dp={dp}")
        t.check(not page["console"], f"dp={dp}: console errors {page['console'][:2]}")
        t.check(page["empty"] is not None and "No open dependencies in view" in page["empty"] and not page["cards"] and not page["rows"], f"dp={dp}: empty state '{page['empty']}'")
        t.check("outside scope" not in page["sub"], f"dp={dp}: a headline clause without pairs: {page['sub'][:120]}")
        t.check(page["chips"]["blockedby"]["n"] == "0" and page["chips"]["blocking"]["n"] == "0", f"dp={dp}: chips {page['chips']['blockedby']['n']} / {page['chips']['blocking']['n']}")


# --------------------------------------------------------------------------------------------- seeded defects
def _mutant(src: str, old: str, new: str, name: str) -> Path:
    assert src.count(old) == 1, f"the seeding anchor for '{name}' is not in the template exactly once (found {src.count(old)}): the mutation test would be blind"
    p = Path(ctx.dir) / f"dep_mutant_{name}.html"
    p.write_text(src.replace(old, new, 1), encoding="utf-8")
    return p


def _caught(src: str, old: str, new: str, name: str) -> list[str]:
    F = fixture()
    p = _mutant(src, old, new, name)
    saved = ctx.template
    ctx.template = p
    try:
        url = ctx.write(kit.fragment_for(F["data"]), "depmut")
        return run_views(url, F["data"], [View("r=27.1"), View("r=27.1&p=PMN", projects={"PMN"})], dps=("epics", "blockedby", "blocking"))
    finally:
        ctx.template = saved


SEEDS = [
    ("swapped_direction", "inbound: inScope.has(a) && !inScope.has(b), outbound: !inScope.has(a) && inScope.has(b)}", "inbound: !inScope.has(a) && inScope.has(b), outbound: inScope.has(a) && !inScope.has(b)}"),
    ("counts_drop_non_epic_providers", "const inbound = all.filter(x => x.inbound), outbound = all.filter(x => x.outbound);", "const inbound = all.filter(x => x.inbound && x.epicsOnly), outbound = all.filter(x => x.outbound);"),
    ("board_drops_non_epic_providers", 'const depAnyType = () => state.depFilter === "all" || state.depFilter === "blockedby" || state.depFilter === "blocking";', 'const depAnyType = () => state.depFilter === "all";'),
    ("counts_include_done_pairs", "const inbound = all.filter(x => x.inbound), outbound = all.filter(x => x.outbound);", "const inbound = m.inView.filter(x => x.inbound), outbound = all.filter(x => x.outbound);"),
    ("direction_column_swapped", 'const depDirOf = x => x.inbound ? "Waits on outside scope" : x.outbound ? "Needed by outside scope" : "Within scope";', 'const depDirOf = x => x.inbound ? "Needed by outside scope" : x.outbound ? "Waits on outside scope" : "Within scope";'),
    ("provider_cue_dropped", 'c.provOut ? "Outside scope · " : ""', '""'),
    ("planning_note_dropped", "(!c.plan.sprint && !c.plan.outside && !c.plan.unknownTs && noPlanData(p) ? `<div class=\"bq\">${NO_PLAN_DATA}</div>` : \"\")", '""'),
]


def _seed_test(name: str, old: str, new: str):
    @SUITE.test(f"direction_seeded_defect_is_caught_{name}")
    def _(t: T):
        src = ctx.template.read_text(encoding="utf-8")
        bad = _caught(src, old, new, name)
        t.check(bool(bad), f"the seeded defect '{name}' was not caught by the recount")
        t.note(f"caught: {bad[0][:150] if bad else ''}")


for _n, _o, _w in SEEDS:
    _seed_test(_n, _o, _w)


if __name__ == "__main__":
    sys.exit(kit.cli(SUITE, __doc__))
