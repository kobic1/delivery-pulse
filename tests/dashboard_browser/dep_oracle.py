#!/usr/bin/env python3
"""Dependency direction oracle: the Dependencies quick filter Blocked by External (hash dp=blocking), and the removal of Blocked by Outside Scope (an old dp=blockedby link opens the default view).

Blocked by External counts the open pairs where an item IN SCOPE (the dependent: the page's own scope of release, projects, teams and Commitment Types) waits on a PROVIDER whose Jira project
is not one of the selected projects and is not CXCROSS (whole project keys compared: OLDCXCROSS is not CXCROSS), at any issue type, whichever of Epics Only and All is chosen. A provider in CXCROSS, or in
a selected project that the release, team or Commitment Type filters leave out, is not external. Pairs with a Done end never count.

An independent Python recount of the open dependency pairs (from the baked links, epics and far-end issues; nothing of the page's code is reused) is compared with what the page prints, in several
filter states and under every quick filter that shows the board:

  * the chip counts, the 'Showing N of M open' line, the provider cards (the keys of each card's 'Open with Dependents' link), the Show data rows, and the Direction column;
  * the one headline clause, with the issues its link opens (the dependents and the external providers of every counted pair; the link is also run through the JQL evaluator over every issue the payload
    knows and must return exactly those issues, and its project clause must name the selected projects and CXCROSS) and the 6,000 character budget;
  * the cues in text (never color alone): 'Outside scope \u00b7 ' on the card meta line, 'Blocks outside scope:' against 'Also blocks outside scope:', the aria-label of the key link,
    and 'Planning data not tracked here' for a provider the page holds no planning data for;
  * the hash round trip, native radios in the one radiogroup, the 320 px layout, the empty state and the omitted headline clause.

Direction column: 'Waits on external scope' (a counted pair), 'Waits on outside scope' (the provider is outside scope but not external: CXCROSS, or a selected project outside the filters),
'Needed by outside scope' (the dependent is outside scope), 'Within scope'.
Seeded defects (swapped direction, CXCROSS providers counted, selected-project providers counted, CXCROSS matched loosely (a project key that merely contains it), non-epic providers dropped, Done pairs counted, the Direction column swapped,
the link's project clause without CXCROSS) must each be caught: a green oracle is not a blind one.

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
import jql_eval                                                                     # noqa: E402
import kit                                                                          # noqa: E402
import make_synthetic as MS                                                         # noqa: E402
from kit import ctx, T                                                              # noqa: E402

SUITE = kit.Suite("Delivery Pulse dependency direction")
KEYRE = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
URL_BUDGET = 6000
NO_TEAM = "(No Team)"
COMMITS = ("Committed", "Not Set", "Stretch")
DIR_TEXT = {"ext": "Waits on external scope", "in": "Waits on outside scope", "out": "Needed by outside scope", "within": "Within scope"}
FILTER_NAME = {"blocking": "Blocked by External"}
EXT_PHRASE = "where an item in the selected projects waits on an external provider (not selected, not CXCROSS)"


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
            return {"ty": "Epic", "s": e["s"], "held": True, "dd": e.get("dd"), "ts": e.get("ts"), "p": e["p"]}
        x = ext.get(k)
        if x:
            return {"ty": x.get("ty") or "Epic", "s": x["s"], "held": False, "dd": x.get("dd"), "ts": x.get("ts"), "p": x.get("p") or k.split("-")[0]}
        return {"ty": "", "s": "", "held": False, "dd": None, "ts": None, "p": k.split("-")[0]}

    pairs = {}
    for a, b, _ty in data["deps"]:
        pairs[(a, b)] = True                                           # the same pair as Dependency and as Blocks counts once
    out = {"ext": [], "inbound": [], "outbound": [], "within": [], "epics": [], "all": [], "done_ext_provider": 0, "done_ext_dependent": 0, "done_out": 0, "scope": scope, "rec": rec, "projects": projects,
           "issues": [{"key": k, "project": rec(k)["p"]} for k in sorted({k for a, b, _ in data["deps"] for k in (a, b)} | set(epics) | set(ext))]}
    for (a, b) in sorted(pairs):
        if a not in scope and b not in scope:
            continue
        ra, rb = rec(a), rec(b)
        if a in scope and b not in scope:                              # the dependent is in scope, the provider is not: external when the provider's project is neither selected nor CXCROSS
            direction = "ext" if (rb["p"] not in projects and rb["p"] != "CXCROSS") else "in"
        else:
            direction = "out" if (b in scope and a not in scope) else "within"
        if ra["s"] == "Done" or rb["s"] == "Done":
            if direction == "ext":
                out["done_ext_provider" if rb["s"] == "Done" else "done_ext_dependent"] += 1
            elif direction == "out":
                out["done_out"] += 1
            continue
        out["all"].append((a, b, direction))
        if ra["ty"] == "Epic" and rb["ty"] == "Epic":
            out["epics"].append((a, b, direction))
        out[{"ext": "ext", "in": "inbound", "out": "outbound", "within": "within"}[direction]].append((a, b, direction))
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
    return {"epics": O["epics"], "all": O["all"], "blocking": O["ext"]}[dp]


def check_ext_query(tag: str, href: str, O: dict, pairs) -> list[str]:
    """The headline link is a query: the dependents by key, and the providers by key AND a project clause. Run over every issue the payload knows it must return exactly the issues at both ends of the
    counted pairs, and its project clause must name the selected projects and CXCROSS (nothing else)."""
    jql = urllib.parse.parse_qs(urllib.parse.urlsplit(href).query).get("jql", [""])[0]
    m = re.search(r"project not in \(([^)]*)\)", jql)
    if not m:
        return [f"{tag} the headline link has no 'project not in (...)' clause: {jql[:160]}"]
    bad: list[str] = []
    named = {x.strip().strip('"') for x in m.group(1).split(",")}
    if named != set(O["projects"]) | {"CXCROSS"}:
        bad.append(f"{tag} the headline link's project clause names {sorted(named)}, expected the selected projects {sorted(O['projects'])} and CXCROSS")
    try:
        tree = jql_eval.parse(jql)
        got = {i["key"] for i in O["issues"] if jql_eval.evaluate(tree, i)}
    except (jql_eval.Malformed, jql_eval.Unsupported) as e:
        return bad + [f"{tag} the headline query cannot be evaluated: {e}: {jql[:160]}"]
    if got != pair_keys(pairs):
        bad.append(f"{tag} the headline query returns {len(got)} issues, the counted pairs have {len(pair_keys(pairs))}; extra {sorted(got - pair_keys(pairs))[:3]} missing {sorted(pair_keys(pairs) - got)[:3]}")
    return bad


def check_view(page: dict, O: dict, v: View, dp: str) -> list[str]:
    """Every difference between the page and the independent recount for this view and quick filter."""
    bad: list[str] = []
    tag = f"[{v.hash or 'default'} dp={dp}]"
    if page["console"]:
        bad.append(f"{tag} console errors {page['console'][:2]}")
        return bad
    chips = page["chips"]
    want = {"epics": len(O["epics"]), "all": len(O["all"]), "blocking": len(O["ext"])}
    for k, n in want.items():
        if chips.get(k, {}).get("n") != str(n):
            bad.append(f"{tag} chip {k} prints {chips.get(k, {}).get('n')}, the recount is {n}")
    if "blockedby" in chips:
        bad.append(f"{tag} the removed chip Blocked by Outside Scope is back")
    for k in ("blocking",):
        denom = len(O["all"])
        if chips.get(k, {}).get("title") != f"{want[k]} of {denom} open":
            bad.append(f"{tag} chip {k} hover says '{chips.get(k, {}).get('title')}', expected '{want[k]} of {denom} open'")
    if not chips.get(dp, {}).get("on"):
        bad.append(f"{tag} the {dp} radio is not checked")
    shown = expected_shown(O, dp)
    any_type = dp in ("all", "blocking")
    denom = len(O["all"] if any_type else O["epics"])
    # ---- the headline clause: pair counts at any issue type, whatever the quick filter
    sub, links = page["sub"], page["subLinks"]
    pairs = O["ext"]
    found = [a for a in links if re.search(r"waits on an external provider", a["tip"])]
    if pairs:
        if len(found) != 1:
            bad.append(f"{tag} headline: {len(found)} links, expected one")
        else:
            a = found[0]
            if a["text"] != str(len(pairs)):
                bad.append(f"{tag} headline prints {a['text']}, the recount is {len(pairs)}")
            if a["href"] and keys_of(a["href"]) != pair_keys(pairs):
                bad.append(f"{tag} headline link opens {len(keys_of(a['href']))} issues, the pairs have {len(pair_keys(pairs))}")
            if a["href"]:
                bad += check_ext_query(tag, a["href"], O, pairs)
            if a["href"] and len(a["href"]) > URL_BUDGET:
                bad.append(f"{tag} headline link is {len(a['href'])} characters")
            if not a["href"] and len(urllib.parse.quote("key in (" + ", ".join(sorted(pair_keys(pairs))) + ")")) < URL_BUDGET - 700:
                bad.append(f"{tag} headline is plain text although the list is short")
            if EXT_PHRASE not in sub:
                bad.append(f"{tag} headline lacks '{EXT_PHRASE}'")
    elif found or "external provider" in sub:
        bad.append(f"{tag} headline clause is shown although the recount is 0")
    if re.search(r"waits on a provider (?:outside scope|in scope)|where an epic waits|where an item outside scope", sub):
        bad.append(f"{tag} an old headline half is back: {sub[-200:]}")
    if not pairs and re.search(r"overdue\.\s*\d", sub):
        bad.append(f"{tag} a headline clause is shown with no external pair")
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
        prov_out = all(d in ("in", "ext") for _, d in pairs)               # the provider is outside scope exactly when every one of its pairs has the dependent in scope and the provider not
        if any(d in ("in", "ext") for _, d in pairs) != prov_out:
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


def run_views(url: str, data: dict, vs: list[View], dps=("epics", "all", "blocking")) -> list[str]:
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
    ext = [O["rec"](b) for _, b, _ in O["ext"]]
    notext = [O["rec"](b) for _, b, _ in O["inbound"]]
    dep = [O["rec"](a) for a, _, _ in O["outbound"]]
    t.check(len(O["ext"]) >= 6 and len(O["inbound"]) >= 5 and len(O["outbound"]) >= 3 and len(O["within"]) >= 3, f"external {len(O['ext'])}, inbound not external {len(O['inbound'])}, outbound {len(O['outbound'])}, within {len(O['within'])}")
    t.check({"Epic", "Task", "Bug", "Capability"} <= {p["ty"] for p in ext}, f"external provider types {sorted({p['ty'] for p in ext})}")
    t.check({"Epic", "Task", "Story"} <= {p["ty"] for p in dep}, f"outbound dependent types {sorted({p['ty'] for p in dep})}")
    t.check(any(not p["held"] and not p["dd"] and not p["ts"] for p in ext + notext) and any(not p["held"] and p["dd"] for p in ext + notext), "providers with and without planning data are both present")
    t.check(any(p["p"] == "CXCROSS" for p in notext) and not any(p["p"] == "CXCROSS" for p in ext), "a CXCROSS provider is in the data and is not external")
    t.check(any(p["p"] == "OLDCXCROSS" for p in ext), "an OLDCXCROSS provider (not CXCROSS) is external")
    t.check(any(p["p"] in F["data"]["projects"] for p in notext), "a provider in a selected project outside the release is in the data and is not external")
    t.check(O["done_ext_provider"] >= 1 and O["done_ext_dependent"] >= 1 and O["done_out"] >= 1, f"Done pairs of every kind (Done external provider {O['done_ext_provider']}, Done dependent {O['done_ext_dependent']}, outbound {O['done_out']})")
    pmn = recount(F["data"], View("r=27.1&p=PMN", projects={"PMN"}))
    t.check(any(O["rec"](b)["p"] == "CXCO" for _, b, _ in pmn["ext"]) and not any(O["rec"](b)["p"] == "CXCO" for _, b, _ in O["ext"]),
            "a provider in a tracked project is external when that project is not selected (PMN only) and is not when it is (all projects)")
    t.note(f"release 27.1, all projects: external {len(O['ext'])}, inbound not external {len(O['inbound'])}, outbound {len(O['outbound'])}, within {len(O['within'])}, epics only {len(O['epics'])}, all open {len(O['all'])}; "
           f"PMN only: external {len(pmn['ext'])}")


@SUITE.test("direction_chips_board_table_headline_and_cues_equal_an_independent_recount")
def _(t: T):
    F = fixture()
    bad = run_views(F["url"], F["data"], views(F["data"], F["team"]))
    for b in bad[:12]:
        t.failures.append(b)
    t.passed += 0 if bad else 1
    t.note(f"{len(views(F['data'], F['team']))} views x 3 quick filters compared")


@SUITE.test("direction_the_chip_is_a_native_radio_in_the_one_group_and_the_hash_round_trips")
def _(t: T):
    F = fixture()
    page = load(F["url"], "r=27.1&dp=blocking")
    t.check(page["group"] == "radiogroup", "the chips are in a radiogroup")
    t.check(all(r["type"] == "radio" and r["name"] == "f-dp" and r["tab"] is None for r in page["radios"]) and len(page["radios"]) == 7, f"seven native radios, no tabindex: {page['radios']}")
    t.check(page["chips"]["blocking"]["on"], "dp=blocking selects Blocked by External")
    t.check("Blocked by External" in page["chips"]["blocking"]["label"], f"Title Case label: {page['chips']['blocking']['label']}")
    ch = ctx.chrome
    click = "(() => { const i = document.querySelector('#f-dp input[value=\"%s\"]'); i.click(); return location.hash; })()"
    ch.js(click % "epics")
    time.sleep(0.2)
    t.check("dp=" not in ch.js("location.hash"), "Epics Only (the default) writes no dp")
    ch.js(click % "blocking")
    time.sleep(0.2)
    h = ch.js("location.hash")
    t.check("dp=blocking" in h, f"selecting Blocked by External writes dp=blocking: {h}")
    t.check(ch.js("document.querySelector('#f-dp input[value=\"blocking\"]').checked && document.getElementById('dep-showing').textContent.includes('Blocked by External')") is True, "and the board follows")
    page = load(F["url"], "r=27.1&dp=blocking")
    t.check(page["chips"]["blocking"]["on"], "dp=blocking round trips")
    page = load(F["url"], "r=27.1&dp=nonsense")
    t.check(page["chips"]["epics"]["on"], "an unknown dp value falls back to Epics Only")


@SUITE.test("direction_blocked_by_outside_scope_is_gone_and_an_old_link_opens_the_default_view")
def _(t: T):
    F = fixture()
    O = recount(F["data"], View("r=27.1"))
    page = load(F["url"], "r=27.1&dp=blockedby")
    t.check(not page["console"], f"an old dp=blockedby link raises errors: {page['console'][:2]}")
    t.check(page["chips"].get("epics", {}).get("on") and not any(c["on"] for k, c in page["chips"].items() if k != "epics"), f"dp=blockedby falls back to Epics Only: {page['chips']}")
    t.check("blockedby" not in page["chips"] and not any("Blocked by Outside Scope" in c["label"] for c in page["chips"].values()), f"a chip named Blocked by Outside Scope exists: {list(page['chips'])}")
    t.check(not any(r["value"] == "blockedby" for r in page["radios"]), "no radio has the value blockedby")
    t.check("dp=blockedby" not in page["hash"], f"the address still carries dp=blockedby: {page['hash']}")
    bad = check_view(page, O, View("r=27.1"), "epics")
    t.check(not bad, f"the fallback view differs from the default view: {bad[:2]}")
    t.check(ctx.chrome.js("!/Blocked by Outside Scope/.test(document.body.innerText)") is True, "the words Blocked by Outside Scope appear nowhere on the page")


@SUITE.test("direction_320px_chips_wrap_and_the_page_does_not_scroll_sideways")
def _(t: T):
    F = fixture()
    ch = ctx.chrome
    try:
        for w in (320, 800):
            ch.viewport(w, 900, mobile=False)
            load(F["url"], "r=27.1&dp=blocking")
            m = ch.js("(() => { const g = document.getElementById('f-dp').getBoundingClientRect(); return {sw: document.documentElement.scrollWidth, w: window.innerWidth, right: Math.max(...[...document.querySelectorAll('#f-dp .chip')].map(c => c.getBoundingClientRect().right)), "
                      "rows: new Set([...document.querySelectorAll('#f-dp .chip')].map(c => Math.round(c.getBoundingClientRect().top))).size}; })()")
            t.check(m["sw"] <= m["w"], f"{w} px: the page scrolls sideways ({m})")
            t.check(m["right"] <= m["w"] + 1, f"{w} px: a chip leaves the viewport ({m})")
            if w == 320:
                t.check(m["rows"] >= 2, f"{w} px: the seven chips are on one row ({m})")
    finally:
        ch.viewport(1400, 900)


def _variant_page(drop: set) -> str:
    F = fixture()
    data = copy.deepcopy(F["data"])
    data["deps"] = [d for d in data["deps"] if (d[0], d[1]) not in drop]
    return ctx.write(kit.fragment_for(data), "depvar"), data


@SUITE.test("direction_without_external_pairs_the_clause_is_omitted_and_the_empty_state_says_why")
def _(t: T):
    F = fixture()
    O = recount(F["data"], View("r=27.1"))
    ext, other = {(a, b) for a, b, _ in O["ext"]}, {(a, b) for a, b, _ in O["inbound"] + O["outbound"]}
    for name, drop in (("no external pairs", ext), ("no external and no other direction", ext | other)):
        url, data = _variant_page(drop)
        v = View("r=27.1")
        O2 = recount(data, v)
        t.check(bool(O2["all"]), f"{name}: the variant keeps other pairs")
        t.check(not O2["ext"], f"{name}: the variant still has external pairs")
        page = load(url, "r=27.1")
        sub = page["sub"]
        t.check("external provider" not in sub and not re.search(r"\b0 (?:dependenc|where)|0 and 0", sub), f"{name}: a clause or a zero is printed: {sub[-160:]}")
        t.check(sub.rstrip().split("overdue.")[-1].strip().startswith("Follows:"), f"{name}: something follows the overdue sentence: {sub[-120:]}")
        page = load(url, "r=27.1&dp=blocking")
        bad = check_view(page, O2, v, "blocking")
        t.check(not bad, f"{name} dp=blocking: {bad[:2]}")
        t.check(page["empty"] and "blocks an item in the selected projects" in page["empty"] and "Epics Only" in page["empty"], f"{name} dp=blocking: empty text '{page['empty']}'")
        t.check(page["chips"]["blocking"]["n"] == "0" and page["chips"]["blocking"]["title"] == f"0 of {len(O2['all'])} open", f"{name} dp=blocking: chip {page['chips']['blocking']}")


@SUITE.test("direction_no_open_pair_at_all_stays_calm_under_both_quick_filters")
def _(t: T):
    F = fixture()
    url, data = _variant_page({(d[0], d[1]) for d in F["data"]["deps"]})
    for dp in ("epics", "blocking"):
        page = load(url, f"r=27.1&dp={dp}")
        t.check(not page["console"], f"dp={dp}: console errors {page['console'][:2]}")
        t.check(page["empty"] is not None and "No open dependencies in view" in page["empty"] and not page["cards"] and not page["rows"], f"dp={dp}: empty state '{page['empty']}'")
        t.check("external provider" not in page["sub"], f"dp={dp}: a headline clause without pairs: {page['sub'][:120]}")
        t.check(page["chips"]["blocking"]["n"] == "0", f"dp={dp}: chip {page['chips']['blocking']['n']}")


@SUITE.test("direction_the_rule_in_plain_cases_cxcross_oldcxcross_and_selected_projects")
def _(t: T):
    """The oracle's own rule, spelled out with fixed fixture keys, so a wrong recount cannot make a wrong page look right."""
    F = fixture()
    prov = lambda page: {r["p"] for r in page["rows"]}
    page = load(F["url"], "r=27.1&dp=blocking")
    got = prov(page)
    t.check("CXCROSS-97010" not in got and "CXCROSS-97015" not in got, f"a CXCROSS provider is counted: {sorted(got)}")
    t.check("OLDCXCROSS-97014" in got, "OLDCXCROSS-97014 (a project that only ends in CXCROSS) is not counted")
    t.check({"EXA-97001", "EXB-97002", "EXC-97005", "EXE-97013"} <= got, f"providers in untracked projects missing: {sorted(got)}")
    t.check("PMN-97003" not in got, "a PMN provider outside the release is counted although PMN is selected")
    t.check("EXA-97006" not in got and "EXE-97017" not in got, "a Done external provider is counted")
    cx = {e["k"] for e in F["data"]["epics"] if e["p"] == "CXCO" and MS.CURRENT not in e["fv"]}
    t.check(not (cx & got), "a CXCO provider is counted although CXCO is selected")
    page = load(F["url"], "r=27.1&p=PMN&dp=blocking")
    t.check(bool(cx & prov(page)), "a CXCO provider is not counted although only PMN is selected")
    t.check("CXCROSS-97010" not in prov(page), "a CXCROSS provider is counted with PMN only")
    page = load(F["url"], "r=27.1&p=PMN|CXCO&dp=blocking")
    t.check(not (cx & prov(page)), "a CXCO provider is counted with PMN and CXCO selected")


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
        return run_views(url, F["data"], [View("r=27.1"), View("r=27.1&p=PMN", projects={"PMN"})], dps=("epics", "blocking"))
    finally:
        ctx.template = saved


SEEDS = [
    ("swapped_direction", "extBlock: inScope.has(a) && !state.projects.has(p.p) && p.p !== DEP_CX};", "extBlock: inScope.has(b) && !state.projects.has(d.p) && d.p !== DEP_CX};"),
    ("cxcross_providers_counted", "extBlock: inScope.has(a) && !state.projects.has(p.p) && p.p !== DEP_CX};", "extBlock: inScope.has(a) && !state.projects.has(p.p)};"),
    ("selected_project_providers_counted", "extBlock: inScope.has(a) && !state.projects.has(p.p) && p.p !== DEP_CX};", "extBlock: inScope.has(a) && p.p !== DEP_CX};"),
    ("cxcross_matched_loosely", "extBlock: inScope.has(a) && !state.projects.has(p.p) && p.p !== DEP_CX};", "extBlock: inScope.has(a) && !state.projects.has(p.p) && !p.p.includes(DEP_CX)};"),
    ("counts_drop_non_epic_providers", "const extBlock = all.filter(x => x.extBlock);", "const extBlock = all.filter(x => x.extBlock && x.epicsOnly);"),
    ("board_drops_non_epic_providers", 'const depAnyType = () => state.depFilter === "all" || state.depFilter === "blocking";', 'const depAnyType = () => state.depFilter === "all";'),
    ("counts_include_done_pairs", "const extBlock = all.filter(x => x.extBlock);", "const extBlock = m.inView.filter(x => x.extBlock);"),
    ("direction_column_swapped", 'x.extBlock ? "Waits on external scope" : x.inbound ? "Waits on outside scope"', 'x.extBlock ? "Waits on outside scope" : x.inbound ? "Waits on external scope"'),
    ("link_project_clause_misses_cxcross", "pkeys([...projectsAll.filter(p => state.projects.has(p)), DEP_CX])", "pkeys([...projectsAll.filter(p => state.projects.has(p))])"),
    ("provider_cue_dropped", 'c.provOut ? "Outside scope \u00b7 " : ""', '""'),
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
