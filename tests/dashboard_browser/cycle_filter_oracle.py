#!/usr/bin/env python3
"""Delivery Cycle filter oracle: the header filter (Cycle 1, Cycle 2) and what it changes, recounted independently in Python and compared with the page.

The filter changes the Delivery burnup and the Cycles section only. A cycle holds the epics whose planned date (the later of the due date and the Target Sprint end) falls in it:
Delivery Cycle 1 on or before the end of W6 (release start + 48 days; earlier dates included), Delivery Cycle 2 from the next day to the release end. An epic with no planned date,
or planned after the release end, is in neither cycle and counts only when every cycle is shown. This file spells the rule again, on purpose, and never imports it from the page.

  1. Burnup (several releases x Projects x Teams x Cycle 1 only / Cycle 2 only / both): Scope, Done and Remaining of every row of the "Show data" table, the Delivery Cycle 1 line (planned and
     Done at the cycle end, the fact line), the title line that names the cycle, and the Jira links (scope, target today, the Done link, the Delivery Cycle 1 links) evaluated with jql_eval.py over
     the baked epics: each must find exactly the epics the recount counts.
  2. Cycles section: the cycle selector offers the cycles that are shown and selects one of them; the five Overview figures of the selected cycle equal a recount; "After Release End" and the
     "No Planned Date, Active" list appear only when every cycle is shown, with their counts.
  3. The header control: present, no Commitment Type control, the hash round trip (dc), an older c= link ignored, the last cycle cannot be unticked, keyboard operation, no sideways scroll at 320 and
     800 px, a release with only Delivery Cycle 1 (Cycle 2 disabled with its reason; a stored dc=2 falls back to Cycle 1).
  4. Other sections do not read the filter (the page outside the burnup, the Cycles section and the filter bar is identical with Cycle 1 only, Cycle 2 only and both).
  5. Seeded defects must be caught: the burnup ignoring the filter, Cycles ignoring it, epics with no planned date counted in a cycle, Cycle 1 with a strict boundary at the end of W6,
     the cycles swapped, Done not narrowed with Scope, planned after the release end counted in Cycle 2, After Release End or the undated list shown for one cycle.

    python3 cycle_filter_oracle.py [--live] [--only NAME]
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import jql_eval as J                                                                # noqa: E402
import kit                                                                          # noqa: E402
import link_cycles as LC                                                            # noqa: E402  (variant payload, epic_issue)
import make_synthetic as MS                                                         # noqa: E402
from kit import ctx, T                                                              # noqa: E402

SUITE = kit.Suite("Delivery Pulse Delivery Cycle filter")
DASH = "–"
NO_TEAM = "(No Team)"
TEAM = "Team%20Alpha"
STATES = ["", "p=PMN", "p=PMN|CXCO", f"t={TEAM}"]
DCS = ["", "dc=1", "dc=2"]
RELEASES = ["27.1", "26.4", "27.2"]                      # running, closed, not started (the burnup before W1)

PROBE = r"""(async () => {
  await document.fonts.ready; updateCore();
  const t = n => n ? n.textContent.replace(/\s+/g, ' ').trim() : null;
  const links = root => root ? [...root.querySelectorAll('a[href]')].map(a => ({href: a.getAttribute('href'), text: t(a)})) : [];
  const cap = document.getElementById('bu-cap').cloneNode(true); cap.querySelectorAll('details').forEach(d => d.remove());
  const svg = document.querySelector('#burnup svg');
  const tiles = {}; document.querySelectorAll('#cy-kpis1 .kpi').forEach(k => { tiles[k.dataset.kpi] = t(k.querySelector('.v')); });
  return {asOf: iso(asOfDay()), release: state.release, projects: [...state.projects], teams: [...state.teams], dc: [...state.dc], hash: location.hash,
    sub: t(document.getElementById('bu-sub')), w6: t(document.getElementById('bu-w6')), w6Links: links(document.getElementById('bu-w6')), cap: t(cap), capLinks: links(cap),
    head: [...document.querySelectorAll('#bu-data thead th')].map(t), rows: [...document.querySelectorAll('#bu-data tbody tr')].map(r => [...r.children].map(t)),
    buLink: (document.getElementById('bu-link') || {getAttribute: () => null}).getAttribute('href'), svgText: svg ? t(svg) : null, svgAria: svg ? svg.getAttribute('aria-label') : null,
    empty: t(document.querySelector('#burnup .empty')),
    radios: [...document.querySelectorAll('#f-cy input')].map(i => ({v: i.value, on: i.checked})), tiles, after: t(document.getElementById('cy-after')), cySub: t(document.getElementById('cy-sub')),
    noDue: (() => { const h = [...document.querySelectorAll('#cy-panel h3')].find(x => /^No Planned Date, Active/.test(t(x))); return h ? t(h) : null; })(),
    dcChips: [...document.querySelectorAll('#f-dc input')].map(i => ({v: i.value, on: i.checked, off: i.disabled})), dcNote: t(document.getElementById('f-dc-note')),
    errors: []};
})()"""


# --------------------------------------------------------------------------------------------- the independent recount
def day(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


class Recount:
    def __init__(self, data: dict, rel: str, projects, teams, dc: set | None, asof: str):
        """dc: the cycles shown ({1}, {2}), None for every cycle (also the answer for a release with one cycle and a dc naming only the other)."""
        self.data, self.rel, self.asof = data, rel, day(asof)
        self.start, self.end = (day(x) for x in data["windows"][rel])
        self.w1, self.w6 = self.start + dt.timedelta(days=7), self.start + dt.timedelta(days=48)
        self.has2 = self.w6 < self.end
        ids = {1, 2} if self.has2 else {1}
        self.shown = ids if not dc or not (dc & ids) else dc & ids
        self.all = self.shown == ids
        self.sprint_end = {s["n"]: s["end"] for s in data["sprints"]}
        teams = set(teams)
        self.sel = [e for e in data["epics"] if e["p"] in projects and rel in e["fv"] and (not teams or teams & set(e.get("tm") or [NO_TEAM]))]

    def planned(self, e):
        ts, dd = self.sprint_end.get(e.get("ts")), e.get("dd")
        return max(dd, ts) if dd and ts else (dd or ts)

    def cycle(self, e):
        p = self.planned(e)
        if not p:
            return None
        return 1 if day(p) <= self.w6 else 2 if day(p) <= self.end else None

    def keep(self, e):
        return self.all or self.cycle(e) in self.shown

    # ---- burnup
    def burnup(self):
        tgt = [e for e in self.sel if (e.get("c") or "Not Set") in ("Committed", "Not Set")]
        members = [e for e in tgt if day((e.get("ad") or {}).get(self.rel) or self.start.isoformat()) <= self.w1]
        tgt_k, mem_k = [e for e in tgt if self.keep(e)], [e for e in members if self.keep(e)]
        done = [e for e in self.sel if e["s"] == "Done" and self.keep(e)]
        D = (self.end - self.w1).days
        clamp = lambda d: min(max(day(d), self.w1), self.end)
        times = sorted((clamp(e["rd"]) - self.w1).days for e in done if e.get("rd"))
        series = [sum(1 for x in times if x <= d) for d in range(D + 1)]
        snap_d = min(D, max(0, (self.asof - self.w1).days))
        committed = [e for e in self.sel if e.get("c") == "Committed"]
        within = [e for e in committed if self.planned(e) and day(self.planned(e)) <= self.w6]
        return dict(D=D, snap_d=snap_d, pre=self.asof < self.w1, N=len(mem_k), tgt=tgt_k, members=mem_k, done=done, series=series, committed=committed, within=within,
                    within_done=[e for e in within if e["s"] == "Done"], none=[e for e in committed if not self.planned(e)], all_done=[e for e in self.sel if e["s"] == "Done" and self.keep(e)])

    # ---- cycles
    def cycles_tiles(self, cid: int):
        lo, hi = (self.start, self.w6 if self.has2 else self.end) if cid == 1 else (self.w6 + dt.timedelta(days=1), self.end)
        pl = [e for e in self.sel if self.planned(e) and lo <= day(self.planned(e)) <= hi]
        nd = lambda e: e["s"] != "Done"
        over = [e for e in pl if nd(e) and day(self.planned(e)) < self.asof]
        nxt = [e for e in pl if nd(e) and self.asof <= day(self.planned(e)) <= self.asof + dt.timedelta(days=7)]
        return {"planned": len(pl), "done": sum(1 for e in pl if not nd(e)), "overdue": len(over), "next": len(nxt), "flagged": sum(1 for e in pl if nd(e) and e.get("fl"))}

    def after_count(self):
        return sum(1 for e in self.sel if self.planned(e) and day(self.planned(e)) > self.end)

    def nodue(self, project: str):
        return sum(1 for e in self.sel if e["p"] == project and e["s"] in ("In Progress", "Validation") and not self.planned(e))


# --------------------------------------------------------------------------------------------- pages
_cache: dict = {}


def payload(kind: str = "variant"):
    if kind not in _cache:
        d = MS.make(MS.il_today())
        if kind == "variant":
            d = LC.variant(d)
            LC.seed_pods(d)
        elif kind == "short":                                    # 26.4 ends 40 days after its start: no Delivery Cycle 2
            start = day(d["windows"]["26.4"][0])
            d["windows"]["26.4"] = [start.isoformat(), (start + dt.timedelta(days=40)).isoformat()]
        _cache[kind] = (d, ctx.write(kit.fragment_for(d), "dcf_" + kind), [LC.epic_issue(e) for e in d["epics"]])
    return _cache[kind]


def load(ch, url: str, h: str) -> dict:
    ch.goto(url + ("#" + h if h else ""))
    kit.wait_ready(ch)
    time.sleep(0.12)
    r = ch.js(PROBE)
    if not isinstance(r, dict) or "__error" in r:
        raise AssertionError(f"probe failed on #{h}: {str(r)[:200]}")
    r["errors"] = ch.console_errors()
    return r


def parse_state(h: str):
    q = {k: v for k, v in urllib.parse.parse_qsl(h, keep_blank_values=True)}
    rel = q.get("r", "27.1")
    projects = set(q["p"].split("|")) if q.get("p") else {"PMN", "CXCO", "CXSUP", "CXWFM", "WFM", "CXINT", "INT"}
    teams = {urllib.parse.unquote(x) for x in q["t"].split("|")} if q.get("t") else set()
    dc = {int(x) for x in q["dc"].split("|") if x in ("1", "2")} if q.get("dc") else None
    return rel, projects, teams, dc


def jql_of(href: str) -> str | None:
    if not href:
        return None
    q = urllib.parse.urlsplit(href)
    return urllib.parse.parse_qs(q.query, keep_blank_values=True).get("jql", [""])[0] if q.path.rstrip("/") == "/issues" else None


def keys_of(jql: str, universe: list) -> set:
    jql = re.sub(r'\s+AND\s+fixVersion WAS "[^"]*" ON "[^"]*"', "", jql)       # the page's "was in the release on W1" clause: Jira history, which the evaluator cannot judge; checked apart
    tree = J.parse(jql)
    return {i["key"] for i in universe if J.evaluate(tree, i)}


# --------------------------------------------------------------------------------------------- 1 + 2: the burnup and the Cycles section
def check_view(t_problems: list, data: dict, universe: list, h: str, r: dict, label: str = "") -> None:
    p = t_problems
    tag = f"[{label}#{h}]"
    rel, projects, teams, dc = parse_state(h)
    R = Recount(data, rel, projects, teams, dc, r["asOf"])
    if r["errors"]:
        p.append(f"{tag} console errors: {r['errors'][:2]}")
    B = R.burnup()
    word = "" if R.all else f"Delivery Cycle {sorted(R.shown)[0]} only"
    # ---- the chart says which cycles it shows
    if word:
        if word not in (r["sub"] or "") and not r["empty"]:
            p.append(f"{tag} the burnup subtitle does not say '{word}': {r['sub']!r}")
        if not r["empty"] and (word not in (r["svgText"] or "") or word not in (r["svgAria"] or "")):
            p.append(f"{tag} the chart itself (drawn text and aria-label) does not say '{word}'")
    elif r["sub"] and "only" in r["sub"].split("·")[-1]:
        p.append(f"{tag} the subtitle names a cycle with every cycle shown: {r['sub']!r}")
    if not B["tgt"] and not any(e["s"] == "Done" for e in B["all_done"]) and not R.all:
        if not r["empty"] or word.split(" only")[0] not in r["empty"]:
            p.append(f"{tag} nothing is planned in the cycle: expected the empty notice naming it, got {r['empty']!r}")
        return
    if r["empty"] is not None and r["rows"] == []:
        return                                                      # no release window or no epics at all: the whole-release empty notice, nothing to count
    # ---- every row of Show data: Scope, Done, Remaining
    N, series, snap_d, D = B["N"], B["series"], B["snap_d"], B["D"]
    head = r["head"]
    c1cols = ["Delivery Cycle 1 Planned", "Delivery Cycle 1 Done"]
    want_c1 = D >= 41 and 1 in R.shown
    if (head[5:] == c1cols) != want_c1:
        p.append(f"{tag} the Delivery Cycle 1 columns are {'present' if head[5:] == c1cols else 'absent'}, expected {'present' if want_c1 else 'absent'} (cycles shown {sorted(R.shown)}, {D} days)")
    for row in r["rows"]:
        d = (day(row[0]) - R.w1).days
        want = [str(N), str(series[d]) if d <= snap_d else DASH, str(max(0, N - series[d])) if d <= snap_d else DASH]
        if row[2:5] != want:
            p.append(f"{tag} row {row[0]}: Scope/Done/Remaining {row[2:5]}, the recount {want}")
            break
        if want_c1 and d == 41 and row[5:7] != [str(len(B["within"])), str(len(B["within_done"]))]:
            p.append(f"{tag} Delivery Cycle 1 columns at the cycle end {row[5:7]}, the recount {[len(B['within']), len(B['within_done'])]}")
    if not any(day(row[0]) == R.w1 + dt.timedelta(days=snap_d) for row in r["rows"]):
        p.append(f"{tag} no row for the latest day")
    # ---- the Delivery Cycle 1 line
    if want_c1:
        m = re.search(r"\(ends ([\d-]+)\): (\d+)(?: of (\d+))? Committed epics? planned; (\d+) Done, (\d+) not Done(?:, (\d+) undated)?\.", r["w6"] or "")
        if B["committed"] and not m:
            p.append(f"{tag} the Delivery Cycle 1 fact line is not in the expected form: {r['w6']!r}")
        elif m:
            a, of, dn, nd, un = m.group(2), m.group(3), m.group(4), m.group(5), m.group(6)
            wantf = (str(len(B["within"])), str(len(B["committed"])) if R.all else None, str(len(B["within_done"])), str(len(B["within"]) - len(B["within_done"])), str(len(B["none"])) if R.all else None)
            if (a, of, dn, nd, un) != wantf:
                p.append(f"{tag} the Delivery Cycle 1 line says {(a, of, dn, nd, un)}, the recount {wantf} (planned, of Committed, Done, not Done, undated)")
        if r["w6Links"] and keys_of(jql_of(r["w6Links"][0]["href"]), universe) != {e["k"] for e in B["within"]}:
            p.append(f"{tag} the Delivery Cycle 1 'planned' link does not find the recounted epics")
    elif 1 not in R.shown and D >= 41 and "not drawn" not in (r["w6"] or ""):
        p.append(f"{tag} with Delivery Cycle 2 only the Delivery Cycle 1 line must be replaced by a note: {r['w6']!r}")
    # ---- the links: scope and today (the target in the cycles), the Done link (every Done epic in the cycles)
    cap_jql = [(l, jql_of(l["href"])) for l in r["capLinks"]]
    if not R.all:
        want_today = {e["k"] for e in B["tgt"]}
        if not any(j for l, j in cap_jql):
            p.append(f"{tag} the burnup caption has no scope link")
        for i, (l, j) in enumerate(cap_jql):
            if j and keys_of(j, universe) != want_today:                        # the scope link (without its 'was in the release on W1' clause) and the target-today link: the target epics planned in the cycle
                p.append(f"{tag} the burnup caption link {i + 1} does not find the {len(want_today)} recounted target epics in the cycle")
        for l, j in cap_jql:
            if j and len(l["href"]) > 6000:
                p.append(f"{tag} a burnup link is over the 6,000 character budget ({len(l['href'])})")
        if r["buLink"]:
            got = keys_of(jql_of(r["buLink"]), universe)
            want = {e["k"] for e in B["all_done"]}
            if got != want:
                p.append(f"{tag} the Done link finds {len(got)} epics, the recount {len(want)}")
    # ---- the Cycles section
    want_radios = [f"DC{i}" for i in sorted(R.shown)]
    got_radios = [x["v"] for x in r["radios"]]
    if got_radios != want_radios:
        p.append(f"{tag} the cycle selector offers {got_radios}, expected {want_radios}")
    sel = [x["v"] for x in r["radios"] if x["on"]]
    if len(sel) != 1 or sel[0] not in want_radios:
        p.append(f"{tag} the selected cycle is {sel}, not one of {want_radios}")
        return
    want_t = R.cycles_tiles(int(sel[0][-1]))
    got_t = {k: (int(v.replace(",", "")) if re.fullmatch(r"[\d,]+", v or "") else v) for k, v in r["tiles"].items()}
    names = {"planned": "planned", "done": "done", "overdue": "overdue", "next": "next", "flagged": "flagged"}
    for k, v in want_t.items():
        if got_t.get(names[k]) != v:
            p.append(f"{tag} Cycles {sel[0]} {k}: the page shows {got_t.get(names[k])}, the recount {v}")
    after = R.after_count()
    shown_after = re.search(r"After Release End: ([\d,]+)", r["after"] or "")
    if R.all and after:
        if not shown_after or int(shown_after.group(1).replace(",", "")) != after:
            p.append(f"{tag} After Release End: the page says {r['after']!r}, the recount {after}")
    elif shown_after:
        p.append(f"{tag} After Release End is shown ({r['after']!r}) but {'there are none' if R.all else 'epics in no cycle are left out while one cycle is shown'}")
    if not R.all and "left out" not in (r["cySub"] or ""):
        p.append(f"{tag} the Cycles subtitle does not say that the filter bar narrows the section: {r['cySub']!r}")


@SUITE.test("burnup_and_cycles_equal_an_independent_recount_for_cycle_1_cycle_2_and_both")
def _(t: T):
    data, url, universe = payload("variant")
    ch = ctx.chrome
    probs: list[str] = []
    n = 0
    for rel in RELEASES:
        for s in STATES:
            for d in DCS:
                h = "&".join(x for x in (f"r={rel}", s, d) if x)
                check_view(probs, data, universe, h, load(ch, url, h), "variant")
                n += 1
    t.note(f"{n} views")
    for x in probs[:12]:
        t.check(False, x)
    t.check(not probs, f"{len(probs)} differences in {n} views")


def deep_check_cycles(ch, url, data, universe, probs):
    """The undated list sits in a detail view: open the first project's view in the three states and compare its count."""
    for rel in ("27.1", "27.2"):
        for d in DCS:
            h = "&".join(x for x in (f"r={rel}", "p=PMN", d, "ct=pmn") if x)
            r = load(ch, url, h)
            R = Recount(data, rel, {"PMN"}, set(), parse_state(h)[3], r["asOf"])
            want = R.nodue("PMN") if R.all else 0
            m = re.search(r"\((\d+)\)", r["noDue"] or "")
            got = int(m.group(1)) if m else 0
            if got != want:
                probs.append(f"[#{h}] No Planned Date, Active: the page lists {got}, the recount {want}")


@SUITE.test("the_undated_list_is_shown_only_when_every_cycle_is_shown")
def _(t: T):
    data, url, universe = payload("variant")
    probs: list[str] = []
    deep_check_cycles(ctx.chrome, url, data, universe, probs)
    t.check(not probs, "; ".join(probs[:4]))
    r = load(ctx.chrome, url, "r=27.1&p=PMN&ct=pmn")
    R = Recount(data, "27.1", {"PMN"}, set(), None, r["asOf"])
    t.check(R.nodue("PMN") > 0, "the fixture has an active epic with no planned date in PMN on 27.1 (otherwise this test proves nothing)")
    t.check(Recount(data, "27.1", set(data["projects"]), set(), None, r["asOf"]).after_count() > 0, "the fixture has epics planned after the release end (the After Release End line is real)")


@SUITE.test("both_cycles_sum_to_the_whole_release_except_epics_in_no_cycle")
def _(t: T):
    """Scope(Cycle 1) + Scope(Cycle 2) + (epics in no cycle) = Scope(both), and the same for Done: nothing is counted twice or lost."""
    data, url, universe = payload("variant")
    ch = ctx.chrome
    for rel in ("27.1", "27.2"):
        got = {}
        for d in DCS:
            r = load(ch, url, "&".join(x for x in (f"r={rel}", d) if x))
            snap = [row for row in r["rows"] if row[3] != DASH]
            got[d] = (int(r["rows"][0][2]), int(snap[-1][3]) if snap else 0)
        R = Recount(data, rel, set(data["projects"]), set(), None, load(ch, url, f"r={rel}")["asOf"])
        tgt = [e for e in R.sel if (e.get("c") or "Not Set") in ("Committed", "Not Set")]
        mem = [e for e in tgt if day((e.get("ad") or {}).get(rel) or R.start.isoformat()) <= R.w1]
        none = sum(1 for e in mem if R.cycle(e) is None)
        t.check(got["dc=1"][0] + got["dc=2"][0] + none == got[""][0], f"{rel}: scope {got['dc=1'][0]} + {got['dc=2'][0]} + {none} in no cycle != {got[''][0]}")
        doneNone = sum(1 for e in R.sel if e["s"] == "Done" and R.cycle(e) is None)
        t.check(got["dc=1"][1] + got["dc=2"][1] + doneNone == got[""][1], f"{rel}: Done {got['dc=1'][1]} + {got['dc=2'][1]} + {doneNone} in no cycle != {got[''][1]}")
        t.check(got["dc=1"][0] > 0 and got["dc=2"][0] > 0 or rel == "27.2", f"{rel}: both cycles hold target epics in the fixture ({got})")


# --------------------------------------------------------------------------------------------- 4: other sections do not read the filter
OTHER_JS = r"""(async () => {
  await document.fonts.ready; updateCore();
  const m = document.querySelector('main').cloneNode(true);
  ['#filters', '#f-live', '#burnup', '#bu-sub', '#bu-w6', '#bu-cap', '#bu-data', '#bu-legend', '#cycles', '#cy-body', '#cy-kpis1', '#cy-kpis2', '#cy-pods', '#cy-after', '#cy-sub', '#cy-cap', '#cy-notes', '#g-cy', '#cy-podlist', '#cy-pods-h'].forEach(s => m.querySelectorAll(s).forEach(n => n.remove()));
  return m.innerHTML;
})()"""


@SUITE.test("every_other_section_keeps_its_numbers_whatever_the_filter_says")
def _(t: T):
    data, url, universe = payload("variant")
    ch = ctx.chrome
    for rel in ("27.1", "26.4"):
        pages = {}
        for d in DCS:
            ch.goto(url + "#" + "&".join(x for x in (f"r={rel}", d) if x))
            kit.wait_ready(ch)
            pages[d] = ch.js(OTHER_JS)
        t.check(len(pages[""]) > 20000, f"{rel}: the page body is really there")
        for d in ("dc=1", "dc=2"):
            if pages[d] != pages[""]:
                a, b = pages[d].replace("><", ">\n<").split("\n"), pages[""].replace("><", ">\n<").split("\n")
                import difflib
                diff = [x for x in difflib.unified_diff(b, a, n=0, lineterm="") if not x.startswith(("---", "+++", "@@"))]
                t.check(False, f"{rel} with {d}: {len(diff)} lines differ outside the burnup and Cycles, e.g. {diff[:2]}")


# --------------------------------------------------------------------------------------------- 3: the header control
JS_FILTERS = r"""(() => ({
  groups: [...document.querySelectorAll('#filterbar .fg, #filterbar .periodbar')].map(g => g.id),
  barText: document.getElementById('filters').textContent.replace(/\s+/g, ' '),
  dcLabel: document.getElementById('lbl-dc') ? document.getElementById('lbl-dc').textContent : null,
  chips: [...document.querySelectorAll('#f-dc label')].map(l => ({text: l.textContent.trim(), on: l.querySelector('input').checked, off: l.querySelector('input').disabled, cls: l.className})),
  hideable: document.getElementById('g-dc') ? document.getElementById('g-dc').classList.contains('hideable') : null,
  changed: document.getElementById('g-dc') ? document.getElementById('g-dc').classList.contains('changed') : null,
  note: document.getElementById('f-dc-note') ? document.getElementById('f-dc-note').textContent : null,
  reset: document.getElementById('f-reset').textContent, live: document.getElementById('f-live').textContent, hash: location.hash, dc: [...state.dc],
  noCommit: !document.getElementById('f-commit') && !document.getElementById('g-commit') && typeof state.commit === 'undefined'
}))()"""


def space_on(ch, selector: str):
    ch.js(f"document.querySelector({json.dumps(selector)}).focus()")
    for ty in ("keyDown", "keyUp"):
        ch.cmd("Input.dispatchKeyEvent", type=ty, key=" ", code="Space", windowsVirtualKeyCode=32, **({"text": " "} if ty == "keyDown" else {}))
    time.sleep(0.3)


@SUITE.test("header_has_the_delivery_cycle_filter_and_no_commitment_type_filter")
def _(t: T):
    data, url, _u = payload("variant")
    ch = ctx.chrome
    ch.goto(url + "#r=27.1")
    kit.wait_ready(ch)
    f = ch.js(JS_FILTERS)
    t.check(f["dcLabel"] == "Delivery Cycle", f"the group is labelled Delivery Cycle: {f['dcLabel']!r}")
    t.check([c["text"] for c in f["chips"]] == ["Cycle 1", "Cycle 2"] and all(c["on"] and not c["off"] for c in f["chips"]), f"two chips, both ticked by default: {f['chips']}")
    t.check(f["noCommit"] and "Commitment Type" not in f["barText"], f"no Commitment Type control, text or state in the header: {f['barText'][:200]!r}")
    t.check(f["groups"].index("g-dc") == f["groups"].index("teamsel") + 1 and f["hideable"], f"the group sits where Commitment Type was, after Teams, and hides on narrow screens: {f['groups']}")
    t.check(f["note"] == "Delivery chart and Cycles only" and not f["changed"] and f["reset"] == "Reset Filters", f"the note names the sections that follow it, nothing is marked changed: {f['note']!r}")
    t.check(not ch.console_errors(), f"no console errors: {ch.console_errors()[:2]}")


@SUITE.test("header_hash_round_trip_last_cycle_stays_and_an_old_c_link_is_ignored")
def _(t: T):
    data, url, universe = payload("variant")
    ch = ctx.chrome
    for h, want_dc, want_on in (("r=27.1&dc=1", [1], [True, False]), ("r=27.1&dc=2", [2], [False, True]), ("r=27.1&dc=1%7C2", [1, 2], [True, True]), ("r=27.1&dc=3", [1, 2], [True, True]), ("r=27.1&dc=", [1, 2], [True, True])):
        ch.goto(url + "#" + h)
        kit.wait_ready(ch)
        f = ch.js(JS_FILTERS)
        t.check(sorted(int(x) for x in f["dc"]) == want_dc and [c["on"] for c in f["chips"]] == want_on, f"#{h}: state {f['dc']}, chips {[c['on'] for c in f['chips']]}")
        t.check(("dc=" in f["hash"]) == (want_dc != [1, 2]) or want_dc == [1, 2] and "dc=" not in f["hash"], f"#{h}: the address after loading is {f['hash']}")
    # clicks: untick Cycle 1 -> dc=2 in the address; the last one cannot go; tick Cycle 1 again -> no dc
    ch.goto(url + "#r=27.1")
    kit.wait_ready(ch)
    ch.js("document.querySelector('#f-dc input[value=\"1\"]').click()")
    time.sleep(0.3)
    f = ch.js(JS_FILTERS)
    t.check(f["dc"] == ["2"] and "dc=2" in f["hash"] and f["changed"] and f["reset"] == "Reset Filters (1)" and "Cycle 2 only" in f["note"], f"Cycle 1 unticked: {f['dc']} {f['hash']} {f['reset']} {f['note']!r}")
    ch.js("document.querySelector('#f-dc input[value=\"2\"]').click()")
    time.sleep(0.5)
    f = ch.js(JS_FILTERS)
    t.check(f["dc"] == ["2"] and [c["on"] for c in f["chips"]] == [False, True] and "At least one delivery cycle must stay selected" in f["live"], f"the last cycle cannot be unticked: {f['dc']} {[c['on'] for c in f['chips']]} {f['live']!r}")
    ch.js("document.querySelector('#f-dc input[value=\"1\"]').click()")
    time.sleep(0.3)
    f = ch.js(JS_FILTERS)
    t.check(sorted(f["dc"]) == ["1", "2"] and "dc=" not in f["hash"] and f["reset"] == "Reset Filters", f"both ticked again: no dc in the address: {f['hash']} {f['reset']}")
    # Reset Filters clears it
    ch.js("document.querySelector('#f-dc input[value=\"2\"]').click()")
    time.sleep(0.3)
    ch.js("document.getElementById('f-reset').click()")
    time.sleep(0.4)
    f = ch.js(JS_FILTERS)
    t.check(sorted(f["dc"]) == ["1", "2"] and "dc=" not in f["hash"], f"Reset Filters ticks both cycles: {f['dc']} {f['hash']}")
    # an older link with the removed filter: ignored, no error, the same page as the plain release
    ch.goto(url + "#r=27.1")
    kit.wait_ready(ch)
    base = ch.js(OTHER_JS)
    for old in ("r=27.1&c=Stretch", "r=27.1&c=Committed|Not%20Set", "r=27.1&c=none", "c=Stretch&dc=1"):
        ch.goto(url + "#" + old)
        kit.wait_ready(ch)
        same = ch.js(OTHER_JS) == base
        f = ch.js(JS_FILTERS)
        t.check(not ch.console_errors() and "c=" not in f["hash"].replace("dc=", "") and (same or old.endswith("dc=1")), f"an older link {old}: no error, nothing named c in the address after loading ({f['hash']}), same page: {same}")


@SUITE.test("header_keyboard_operation")
def _(t: T):
    data, url, universe = payload("variant")
    ch = ctx.chrome
    ch.goto(url + "#r=27.1")
    kit.wait_ready(ch)
    space_on(ch, '#f-dc input[value="2"]')
    f = ch.js(JS_FILTERS)
    t.check(f["dc"] == ["1"] and "dc=1" in f["hash"], f"Space on the Cycle 2 checkbox unticks it: {f['dc']} {f['hash']}")
    t.check(ch.js("document.activeElement && document.activeElement.closest('#f-dc') !== null"), "the focus stays in the Delivery Cycle group after the change")
    space_on(ch, '#f-dc input[value="1"]')
    f = ch.js(JS_FILTERS)
    t.check(f["dc"] == ["1"] and "At least one delivery cycle must stay selected" in f["live"], f"Space on the last ticked cycle changes nothing and says so: {f['dc']} {f['live']!r}")
    t.check(bool(ch.js("[...document.querySelectorAll('#f-dc input')].every(i => i.tabIndex >= 0)")), "both checkboxes are in the tab order")
    t.check(bool(ch.js("getComputedStyle(document.querySelector('#f-dc input').parentElement).outlineStyle !== undefined")), "the chip is a label around a native checkbox (the shared chip pattern)")


@SUITE.test("header_no_sideways_scroll_at_320_and_800_px")
def _(t: T):
    data, url, universe = payload("variant")
    ch = ctx.chrome
    try:
        for w in (320, 800, 1400):
            for h in ("r=27.1", "r=27.1&dc=2"):
                ch.viewport(w, 900, mobile=w < 700)
                ch.goto(url + "#" + h)
                kit.wait_ready(ch)
                ch.js("(() => { const b = document.getElementById('f-toggle'); if (b && getComputedStyle(b).display !== 'none' && b.getAttribute('aria-expanded') === 'false') b.click(); })()")
                time.sleep(0.2)
                m = ch.js("(() => { const g = document.getElementById('g-dc').getBoundingClientRect(); return {sw: document.documentElement.scrollWidth, w: window.innerWidth, right: Math.round(g.right), left: Math.round(g.left), vis: g.width > 0, bw: document.body.scrollWidth}; })()")
                t.check(m["sw"] <= m["w"] + 1 and m["bw"] <= m["w"] + 1, f"{w} px #{h}: the page scrolls sideways ({m})")
                t.check(m["vis"] and m["right"] <= m["w"] + 1 and m["left"] >= -1, f"{w} px #{h}: the Delivery Cycle group leaves the viewport ({m})")
                t.check(not ch.console_errors(), f"{w} px: console errors {ch.console_errors()[:2]}")
    finally:
        ch.viewport(1400, 900)


@SUITE.test("a_release_with_only_cycle_1_disables_cycle_2_and_falls_back")
def _(t: T):
    data, url, universe = payload("short")
    ch = ctx.chrome
    ch.goto(url + "#r=26.4")
    kit.wait_ready(ch)
    f = ch.js(JS_FILTERS)
    t.check([c["off"] for c in f["chips"]] == [False, True] and [c["on"] for c in f["chips"]] == [True, False], f"Cycle 2 is disabled and not ticked, Cycle 1 ticked: {f['chips']}")
    t.check("No Cycle 2" in f["note"] and ch.js("document.querySelector('#f-dc label.dis').title").startswith("26.4 ends by the end of W6"), f"the reason is in plain words: {f['note']!r}")
    t.check(not f["changed"] and "Cycle" not in f["note"].replace("No Cycle 2", ""), f"with the only cycle ticked the group is not marked as a filter: {f['changed']} {f['note']!r}")
    r_default = load(ch, url, "r=26.4")
    r_stored2 = load(ch, url, "r=26.4&dc=2")                        # a stored dc naming a cycle the release does not have falls back to the cycles it has
    r_stored1 = load(ch, url, "r=26.4&dc=1")
    for k in ("sub", "rows", "w6", "cap", "radios", "tiles"):
        t.check(r_stored2[k] == r_default[k] == r_stored1[k], f"26.4 with dc=2 or dc=1 equals the default on {k}")
    t.check([x["v"] for x in r_default["radios"]] == ["DC1"], f"the Cycles selector offers Delivery Cycle 1 only: {r_default['radios']}")
    probs: list[str] = []
    for h in ("r=26.4", "r=26.4&dc=2", "r=26.4&dc=1", "r=27.1&dc=2"):
        check_view(probs, data, universe, h, load(ch, url, h), "short")
    t.check(not probs, "; ".join(probs[:3]))
    # the same release in the long payload does have two cycles (the fixture changed only the window)
    r_long = load(ch, payload("variant")[1], "r=26.4")
    t.check([c["off"] for c in r_long["dcChips"]] == [False, False], "the unchanged release has both cycles")
    ch.goto(url + "#r=26.4&dc=2")
    kit.wait_ready(ch)
    ch.js("document.querySelector('#f-dc input[value=\"1\"]').click()")
    time.sleep(0.3)
    f = ch.js(JS_FILTERS)
    t.check(f["dc"] == ["2"] and [c["on"] for c in f["chips"]] == [True, False] and "At least one delivery cycle" in f["live"], f"the only existing cycle cannot be unticked even when dc names the other: {f['dc']} {f['chips']} {f['live']!r}")
    # moving to a release that has two cycles brings the stored choice back
    ch.js("(() => { const s = document.getElementById('f-release'); s.value = '27.1'; s.dispatchEvent(new Event('change', {bubbles: true})); })()")
    time.sleep(0.4)
    f = ch.js(JS_FILTERS)
    t.check(f["dc"] == ["2"] and [c["on"] for c in f["chips"]] == [False, True], f"the stored dc=2 applies again on a release with two cycles: {f['dc']} {[c['on'] for c in f['chips']]}")


# --------------------------------------------------------------------------------------------- 5: seeded defects
MUTANTS = [
    ("the burnup ignores the filter", "keep = dcKeep(dc, rel), nm = dcWord(dc)", "keep = () => true, nm = dcWord(dc)"),
    ("Cycles ignores the filter", "dcs = dcState(), shown = cycles.filter(x => dcs.shown.includes(x.id.slice(2)));", "dcs = dcState(), shown = cycles;"),
    ("epics with no planned date are counted in Cycle 1", "const p = plannedLater(e), m = !p ? null : p <= w6", "const p = plannedLater(e), m = !p ? \"1\" : p <= w6"),
    ("Delivery Cycle 1 ends before the end of W6 (< instead of <=)", "m = !p ? null : p <= w6 ? \"1\"", "m = !p ? null : p < w6 ? \"1\""),
    ("the cycles are swapped", "p <= w6 ? \"1\" : p <= end ? \"2\" : null;", "p <= w6 ? \"2\" : p <= end ? \"1\" : null;"),
    ("Done is not narrowed with Scope", "const dlist = dc.all ? doneScope(rel) : doneScope(rel).filter(keep);", "const dlist = doneScope(rel);"),
    ("epics planned after the release end are counted in Cycle 2", "p <= end ? \"2\" : null; return m", "\"2\"; return m"),
    ("After Release End is shown with one cycle", "const after = M.dcAll ? M.epics.filter(", "const after = true ? M.epics.filter("),
    ("the undated list is shown with one cycle", "noDue: dcs.all ? eps.filter(", "noDue: true ? eps.filter("),
    ("the scope link ignores the cycle", "const scopeHref = dc.all ? TB.href : J(", "const scopeHref = true ? TB.href : J("),
]
MUTANT_VIEWS = ["r=27.1&dc=1", "r=27.1&dc=2", "r=27.1"]


@SUITE.test("selftest_oracle_catches_seeded_defects")
def _(t: T):
    src = ctx.template.read_text(encoding="utf-8")
    data, _u, universe = payload("variant")
    ch = ctx.chrome
    for i, (what, old, new) in enumerate(MUTANTS):
        if src.count(old) != 1:
            raise kit.Skip(f"the seeding anchor for '{what}' is not in this template exactly once (found {src.count(old)})")
        f = Path(ctx.dir) / f"dcf_mutant_{i}.html"
        f.write_text(MS.render_page(data, _write_tmp(src.replace(old, new, 1))), encoding="utf-8")
        url = "file://" + str(f)
        probs: list[str] = []
        views = MUTANT_VIEWS + (["r=27.1&p=PMN&dc=2&ct=pmn", "r=27.1&p=PMN&ct=pmn"] if "undated" in what else [])
        for h in views:
            r = load(ch, url, h)
            check_view(probs, data, universe, h, r, "mutant")
        if "undated" in what:
            deep_check_cycles(ch, url, data, universe, probs)
        t.check(bool(probs), f"the oracle did not notice the seeded defect: {what}")


def _write_tmp(text: str) -> Path:
    p = Path(ctx.dir) / f"template_mutant_{abs(hash(text)) % 10**8}.html"
    p.write_text(text, encoding="utf-8")
    return p


if __name__ == "__main__":
    sys.exit(kit.cli(SUITE, __doc__))
