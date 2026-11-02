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
  1b. The burnup's X axis follows the filter (both ticked = day 0 to the release end, exactly the chart without the filter; Cycle 1 only = W1 to the end of W6, day 0 to 41; Cycle 2 only = W7
     to the release end, day 42 to the end): the week ticks, the last tick and the end marker, every day of the keyboard readout (scope, even pace, Done), the drawn lines (Done start and end,
     even-pace ends, scope dot, snapshot marker) read back from the SVG geometry, the plain-words line, the headline, the labels, the aria-label and the table days, for the as-of day before
     Delivery Cycle 1, inside it, on its last day, inside Delivery Cycle 2 and after the release end; a window of one day; a 390 px chart; the hash round trip and the re-draw on a click.
  3. The header control: present, no Commitment Type control, the hash round trip (dc), an older c= link ignored, the last cycle cannot be unticked, keyboard operation, no sideways scroll at 320 and
     800 px, a release with only Delivery Cycle 1 (Cycle 2 disabled with its reason; a stored dc=2 falls back to Cycle 1).
  4. Other sections do not read the filter (the page outside the burnup, the Cycles section and the filter bar is identical with Cycle 1 only, Cycle 2 only and both).
  5. Seeded defects must be caught: the burnup ignoring the filter, Cycles ignoring it, epics with no planned date counted in a cycle, Cycle 1 with a strict boundary at the end of W6,
     the cycles swapped, Done not narrowed with Scope, planned after the release end counted in Cycle 2, After Release End or the undated list shown for one cycle; and for the axis: the
     domain not narrowed, Done restarting at zero in Cycle 2, the even pace not re-anchored (Cycle 1 or Cycle 2), the dotted Delivery Cycle 1 marker drawn in Cycle 1, the snapshot marker
     outside the window, the pre-start state drawn as a chart, the headline not stopping at the end of Cycle 1, the window-end link unbounded, the keyboard leaving the window, the plain line
     with both cycles ticked.

    python3 cycle_filter_oracle.py [--live] [--only NAME]
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import math
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
    sub: t(document.getElementById('bu-sub')), plain: t(document.getElementById('bu-plain')), w6: t(document.getElementById('bu-w6')), w6Links: links(document.getElementById('bu-w6')), cap: t(cap), capLinks: links(cap),
    head: [...document.querySelectorAll('#bu-data thead th')].map(t), rows: [...document.querySelectorAll('#bu-data tbody tr')].map(r => [...r.children].map(t)),
    buLink: (document.getElementById('bu-link') || {getAttribute: () => null}).getAttribute('href'), svgText: svg ? t(svg) : null, svgAria: svg ? svg.getAttribute('aria-label') : null,
    empty: t(document.querySelector('#burnup .empty')),
    radios: [...document.querySelectorAll('#f-cy input')].map(i => ({v: i.value, on: i.checked})), tiles, after: t(document.getElementById('cy-after')), cySub: t(document.getElementById('cy-sub')),
    noDue: (() => { const h = [...document.querySelectorAll('#cy-panel h3')].find(x => /^No Planned Date, Active/.test(t(x))); return h ? t(h) : null; })(),
    dcChips: [...document.querySelectorAll('#f-dc input')].map(i => ({v: i.value, on: i.checked, off: i.disabled})), dcNote: t(document.getElementById('f-dc-note')),
    errors: []};
})()"""


# The burnup's drawing read back from the SVG (text, tick positions, the lines and their end points) and the keyboard readout of every day of the window (Home, ArrowRight ... End).
AXIS_JS = r"""(() => {
  const t = n => n ? n.textContent.replace(/\s+/g, ' ').trim() : null, num = (e, a) => parseFloat(e.getAttribute(a));
  const svg = document.querySelector('#burnup svg'); if (!svg) return null;
  const texts = [...svg.querySelectorAll('text')].map(x => ({t: t(x), x: num(x, 'x'), y: num(x, 'y'), anchor: x.getAttribute('text-anchor')}));
  const lines = [...svg.querySelectorAll('line')].map(l => ({x1: num(l, 'x1'), x2: num(l, 'x2'), y1: num(l, 'y1'), y2: num(l, 'y2'), dash: l.getAttribute('stroke-dasharray'), stroke: l.getAttribute('stroke'), id: l.id}));
  const paths = [...svg.querySelectorAll('path')].map(p => ({d: p.getAttribute('d'), stroke: p.getAttribute('stroke'), fill: p.getAttribute('fill')}));
  const dots = [...svg.querySelectorAll('circle')].map(c => ({cx: num(c, 'cx'), cy: num(c, 'cy'), r: num(c, 'r')}));
  const lk = document.getElementById('bu-link'), tip = document.getElementById('bu-tip'), reads = [], flags = {};
  const key = k => lk.dispatchEvent(new KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true}));
  const rd = () => ({tip: tip.innerHTML.replace(/<br>/g, '|').replace(/<[^>]+>/g, ''), href: lk.getAttribute('href') || '', aria: lk.getAttribute('aria-label') || ''});
  const first = (() => { lk.dispatchEvent(new FocusEvent('focus')); return rd(); })();
  key('Home'); let cur = rd(), prev = null;
  flags.leftStays = (key('ArrowLeft'), rd().tip === cur.tip);
  for (let i = 0; i < 400 && (!prev || cur.tip !== prev.tip); i++) { reads.push(cur); prev = cur; key('ArrowRight'); cur = rd(); }
  flags.rightStays = cur.tip === prev.tip; key('Home'); flags.home = rd().tip === reads[0].tip; key('End'); flags.end = rd().tip === reads[reads.length - 1].tip; key('Escape');
  flags.tipHidden = getComputedStyle(tip).display === 'none';
  return {texts, lines, paths, dots, reads, first, flags, width: svg.getAttribute('width'), nan: /NaN|undefined/.test(svg.outerHTML), hasPlain: !!document.getElementById('bu-plain')};
})()"""


# --------------------------------------------------------------------------------------------- the independent recount
def day(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def jround(x: float) -> int:
    return math.floor(x + 0.5)                                              # JavaScript's Math.round (halves go up), not Python's


UMINUS = "\u2212"


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

    # ---- the window of the burnup's X axis, spelled again here (days since W1 start)
    def axis(self, B: dict) -> dict:
        D, N, ser, snap_d = B["D"], B["N"], B["series"], B["snap_d"]
        kind, s, e = ("all", 0, D) if self.all else ("c1", 0, min(41, D)) if 1 in self.shown else ("c2", 42, D)
        raw = (self.asof - self.w1).days                                    # the unclamped as-of day
        before = kind == "c2" and raw < s
        in_win = (s <= raw < e) if kind == "c2" else snap_d < e              # the snapshot marker and the "vs even pace" comparison
        closed = kind == "c1" and raw >= e
        d_end = min(snap_d, e)
        carry = ser[s - 1] if kind == "c2" else 0                           # Done stays cumulative: Delivery Cycle 2 starts at the epics already Done before W7
        p0 = min(carry, N)

        def pace(d: int) -> float:
            if kind == "all":
                return N * d / D if D else 0
            if kind == "c1":
                return N * d / e if e else 0
            return p0 + (N - p0) * ((d - s) / (e - s) if e > s else 1)

        grid = list(range(s, e + 1, 7))
        end_tick = kind != "all" and (e - s) % 7 != 0
        done_n = ser[d_end]
        pace_txt = raw >= 0 and in_win and N >= 5
        return dict(kind=kind, s=s, e=e, D=D, N=N, raw=raw, before=before, in_win=in_win, closed=closed, d_end=d_end, carry=carry, p0=p0, pace=pace, grid=grid, end_tick=end_tick,
                    done_n=done_n, dv=jround(done_n - pace(d_end)), pace_txt=pace_txt, start_level=ser[s - 1] if kind == "c2" else ser[0])

    def date(self, d: int) -> str:
        return (self.w1 + dt.timedelta(days=d)).isoformat()

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
        elif kind == "tiny":                                     # 27.1 ends 42 days after W1 starts: Delivery Cycle 2 is a single day (the scale must not divide by zero)
            start = day(d["windows"]["27.1"][0])
            d["windows"]["27.1"] = [start.isoformat(), (start + dt.timedelta(days=49)).isoformat()]
            for e in [e for e in d["epics"] if "27.1" in e["fv"] and e["s"] not in ("Done", "Removed")][:5] + [e for e in d["epics"] if "27.1" in e["fv"] and e["s"] == "Done"][:2]:
                e["dd"], e["ts"] = (start + dt.timedelta(days=49)).isoformat(), None                # planned on the release end: the only day of Delivery Cycle 2
        elif kind.startswith("asof_"):                           # the same payload read on another day: the as-of day moves, the epics stay (a logic vector for the axis, not a time shift of the data)
            d = copy.deepcopy(payload("variant")[0])
            w1 = day(d["windows"]["27.1"][0]) + dt.timedelta(days=7)
            d["generated"] = MS.il_stamp(w1 + dt.timedelta(days=ASOF_DAYS[kind[5:]]), 8, 30)
            if kind == "asof_w7":
                _closures_after_w6(d, w1)
        _cache[kind] = (d, ctx.write(kit.fragment_for(d), "dcf_" + kind), [LC.epic_issue(e) for e in d["epics"]])
    return _cache[kind]


ASOF_DAYS = {"pre": -3, "w6end": 41, "w7": 45, "after": 90}     # days since W1 start: before W1, the last day of Delivery Cycle 1, inside Delivery Cycle 2, after the release end (83 days)


def _closures_after_w6(d: dict, w1: dt.date) -> None:
    """Give the as-of day in W7 something to count: Cycle 1 epics closed after W6 (the 'more Done since' case), Cycle 2 epics closed before W7 (the carry-in) and inside it."""
    R = Recount(d, "27.1", set(d["projects"]), set(), None, w1.isoformat())
    iso_ = lambda n: (w1 + dt.timedelta(days=n)).isoformat()
    for e in [e for e in R.sel if e["s"] == "Done" and R.cycle(e) == 1][:3]:
        e["rd"] = iso_(43)
    for e in [e for e in R.sel if e["s"] == "Done" and R.cycle(e) == 2][:2]:
        e["rd"] = iso_(44)
    opened = [e for e in R.sel if e["s"] not in ("Done", "Removed") and R.cycle(e) == 2]
    for e, n in zip(opened[:6], (10, 10, 20, 46, 46, 47)):
        e["s"], e["rd"] = "Done", iso_(n)


def load(ch, url: str, h: str, axis: bool = True) -> dict:
    ch.goto(url + ("#" + h if h else ""))
    kit.wait_ready(ch)
    time.sleep(0.12)
    r = ch.js(PROBE)
    if not isinstance(r, dict) or "__error" in r:
        raise AssertionError(f"probe failed on #{h}: {str(r)[:200]}")
    r["axis"] = ch.js(AXIS_JS) if axis else None
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

NUM = r"[-+\d.eE]+"


def check_axis(p: list, R: Recount, B: dict, A: dict, universe: list, r: dict, tag: str) -> None:
    """The burnup's X axis and everything drawn on it, against the recount: ticks and the end marker, the keyboard readout of every day, the lines read back from the SVG, the texts."""
    ax, kind, s, e, D, N, ser = r["axis"], A["kind"], A["s"], A["e"], A["D"], A["N"], B["series"]
    nm = "" if kind == "all" else f"Delivery Cycle {1 if kind == 'c1' else 2} only"
    if ax["nan"]:
        p.append(f"{tag} the chart contains NaN or undefined")
    # ---- the week ticks (1400 px: one every 7 days) and the end marker
    pairs = [(t["t"], t["x"], ax["texts"][i + 1]["t"]) for i, t in enumerate(ax["texts"][:-1]) if re.fullmatch(r"\d{4}-\d\d-\d\d", t["t"] or "") and re.fullmatch(r"W\d+( end)?", ax["texts"][i + 1]["t"] or "")]
    want = [(R.date(d), f"W{d // 7 + 1}") for d in A["grid"]] + ([(R.date(e), f"W{min(e, D - 1) // 7 + 1} end")] if A["end_tick"] else [])
    if int(float(ax["width"])) >= 900 and [(a, c) for a, _x, c in pairs] != want:
        p.append(f"{tag} the week ticks are {[(a, c) for a, _x, c in pairs][:3]}..{[(a, c) for a, _x, c in pairs][-2:]} ({len(pairs)}), expected {want[:3]}..{want[-2:]} ({len(want)})")
    if pairs and (pairs[0][0] != R.date(s) or pairs[-1][0] != want[-1][0] and (kind != "all" or int(float(ax["width"])) >= 900)):
        p.append(f"{tag} the axis runs from {pairs[0][0]} to {pairs[-1][0]}, expected {R.date(s)} to {want[-1][0]}")
    if any(not (R.date(s) <= a <= R.date(e)) for a, _x, _c in pairs):
        p.append(f"{tag} a tick lies outside the window {R.date(s)} .. {R.date(e)}")
    texts = [t["t"] for t in ax["texts"]]
    want_end = f"end of Delivery Cycle 1 {R.date(e)}" if kind == "c1" else f"release end {R.end.isoformat()}"
    if texts.count(want_end) != 1 or any(t and t.startswith(("release end", "end of Delivery")) and t != want_end for t in texts):
        p.append(f"{tag} the end marker should read {want_end!r}: {[t for t in texts if t and ('end' in t and '20' in t)]}")
    if kind == "c1" and any(re.fullmatch(r"W(7|8|9|1\d)( end)?", t or "") for t in texts) or kind == "c2" and any(re.fullmatch(r"W[1-6]( end)?", t or "") for t in texts):
        p.append(f"{tag} the axis shows a week outside its window")
    # ---- the mappings from pixels to days and to epics (from the ticks and the grid lines)
    day_of = None
    if len(pairs) >= 2 and pairs[-1][1] != pairs[0][1]:
        d0, d1 = (day(pairs[0][0]) - R.w1).days, (day(pairs[-1][0]) - R.w1).days
        day_of = lambda x: d0 + (x - pairs[0][1]) * (d1 - d0) / (pairs[-1][1] - pairs[0][1])
    grid = sorted({round(l["y1"], 3) for l in ax["lines"] if l["stroke"] == "#E6E3DC"}, reverse=True)
    ylabels = [int(t["t"]) for t in ax["texts"] if re.fullmatch(r"\d+", t["t"] or "") and t["anchor"] == "end"]
    val_of = (lambda y: (grid[0] - y) * (ylabels[-1] - ylabels[0]) / (grid[0] - grid[-1])) if len(grid) >= 2 and len(grid) == len(ylabels) else None
    if ylabels and ylabels[0] != 0:
        p.append(f"{tag} the Y axis does not start at 0: {ylabels}")
    top = max([N] + (ser[max(0, s - 1):e + 1] if kind != "all" else ser))
    if ylabels and ylabels[-1] < top:
        p.append(f"{tag} the Y axis stops at {ylabels[-1]}, below the largest value {top}")
    # ---- the drawn lines
    def near(a, b, tol=0.02):
        return a is not None and abs(a - b) <= tol
    pace_l = [l for l in ax["lines"] if l["stroke"] == "#6E737C" and l["dash"] == "6 4"]
    if len(pace_l) != (0 if A["before"] else 1):
        p.append(f"{tag} {len(pace_l)} even-pace lines, expected {0 if A['before'] else 1}")
    elif pace_l and day_of and val_of:
        l = pace_l[0]
        got = (day_of(l["x1"]), val_of(l["y1"]), day_of(l["x2"]), val_of(l["y2"]))
        want_p = (s, A["p0"], e, N)
        if not all(near(g, w, 0.02 if i % 2 == 0 else 0.3) for i, (g, w) in enumerate(zip(got, want_p))):
            p.append(f"{tag} the even-pace line runs {tuple(round(g, 2) for g in got)} (day, epics, day, epics), expected {want_p}")
    done_p = [q for q in ax["paths"] if q["stroke"] == "#025AFB"]
    if len(done_p) != (0 if A["before"] else 1):
        p.append(f"{tag} {len(done_p)} Done lines, expected {0 if A['before'] else 1}")
    elif done_p and day_of and val_of:
        m = re.match(rf"M({NUM}),({NUM})", done_p[0]["d"])
        hs, vs = re.findall(rf"H({NUM})", done_p[0]["d"]), re.findall(rf"V({NUM})", done_p[0]["d"])
        steps = sum(1 for i in range(s if kind == "c2" else 1, A["d_end"] + 1) if ser[i] != ser[i - 1])         # a step wherever the cumulative count changes
        if not (m and near(day_of(float(m.group(1))), s) and near(val_of(float(m.group(2))), A["start_level"], 0.3)):
            p.append(f"{tag} the Done line starts at day {day_of(float(m.group(1))) if m else None}, {val_of(float(m.group(2))) if m else None} epics; expected day {s}, {A['start_level']} epics")
        if not hs or not near(day_of(float(hs[-1])), A["d_end"]):
            p.append(f"{tag} the Done line ends at day {day_of(float(hs[-1])) if hs else None}, expected {A['d_end']}")
        if len(vs) != steps or (vs and not near(val_of(float(vs[-1])), ser[A["d_end"]], 0.3)) or (not vs and A["start_level"] != ser[A["d_end"]]):
            p.append(f"{tag} the Done line has {len(vs)} steps ending at {val_of(float(vs[-1])) if vs else None}, expected {steps} ending at {ser[A['d_end']]}")
    snap_l = [l for l in ax["lines"] if l["dash"] == "2 3"]
    if len(snap_l) != (1 if A["in_win"] else 0):
        p.append(f"{tag} {len(snap_l)} snapshot markers, expected {1 if A['in_win'] else 0} (as-of day {A['raw']}, window {s}..{e})")
    elif snap_l and day_of and not near(day_of(snap_l[0]["x1"]), B["snap_d"]):
        p.append(f"{tag} the snapshot marker is at day {day_of(snap_l[0]['x1']):.2f}, expected {A['raw']}")
    if any(t and t.startswith(("snapshot ", "refreshed ")) for t in texts) != A["in_win"]:
        p.append(f"{tag} the snapshot label is {'missing' if A['in_win'] else 'drawn outside the window'}")
    w6_l = [l for l in ax["lines"] if l["dash"] == "1 4"]
    want_w6 = kind == "all" and D >= 41
    if len(w6_l) != (1 if want_w6 else 0):
        p.append(f"{tag} the dotted Delivery Cycle 1 marker is {'drawn' if w6_l else 'missing'}, expected {'drawn' if want_w6 else 'not drawn'} for {kind}")
    if any(t and (t.startswith("Delivery Cycle 1 ·") or t.endswith("epics planned")) for t in texts) != want_w6:
        p.append(f"{tag} the 'Delivery Cycle 1 · N planned' label is {'drawn' if not want_w6 else 'missing'}, expected the opposite for {kind}")
    dots = [dd for dd in ax["dots"] if dd["r"] == 4]
    if dots and day_of and val_of and not (near(day_of(dots[0]["cx"]), e) and near(val_of(dots[0]["cy"]), N, 0.3)):
        p.append(f"{tag} the scope dot is at day {day_of(dots[0]['cx']):.2f}, {val_of(dots[0]['cy']):.2f} epics; expected day {e}, {N}")
    # ---- the labels
    done_t = [t for t in texts if t and re.match(r"Done [\d,]+", t)]
    want_done = f"Done {A['done_n']:,}" + (f" · {'+' if A['dv'] >= 0 else UMINUS}{abs(A['dv'])} vs even pace" if A["pace_txt"] else "")
    if A["before"]:
        if done_t:
            p.append(f"{tag} a Done label is drawn before Delivery Cycle 2 starts: {done_t}")
        if f"Starts {R.date(s)}" not in texts or f"{ser[B['snap_d']]:,} of {N:,} already Done" not in texts:
            p.append(f"{tag} the pre-start note is missing: {[t for t in texts if t and ('Starts' in t or 'already' in t)]}")
    else:
        if done_t != [want_done] and not (done_t == [f"Done {A['done_n']:,}"] and A["pace_txt"] and int(float(ax["width"])) < 520):
            p.append(f"{tag} the Done label reads {done_t}, expected {want_done!r}")
        if "Even pace" not in texts:
            p.append(f"{tag} the 'Even pace' label is missing")
        note = f"Already Done before W7: {A['carry']:,}"
        if (note in texts) != (kind == "c2" and A["carry"] > 0):
            p.append(f"{tag} the carry-in note {note!r} is {'missing' if kind == 'c2' and A['carry'] > 0 else 'drawn where it does not belong'}")
    if A["before"] and ("Even pace" in texts):
        p.append(f"{tag} the 'Even pace' label is drawn before Delivery Cycle 2 starts")
    if f"Scope {N:,}" not in texts:
        p.append(f"{tag} the Scope label is missing: Scope {N}")
    # ---- the headline, the plain-words line, the aria-label
    done_epics = len(B["all_done"])
    shown = ser[e] if A["closed"] else done_epics
    since = ser[B["snap_d"]] - ser[e] if A["closed"] else 0
    head = f"{shown:,} of {N:,} target scope epics delivered" + (f" by the end of Delivery Cycle 1" + (f" · {since:,} more Done since" if since > 0 else "") if A["closed"] else "") + (f" · Delivery Cycle 2 starts {R.date(s)}" if A["before"] else "")
    if not ((r["sub"] or "") == head or (r["sub"] or "").startswith(head + " ·")):
        p.append(f"{tag} the headline is {r['sub']!r}, expected it to start {head!r}")
    wa, wz = s // 7 + 1, (jround(D / 7) if kind != "c1" else e // 7 + 1)
    a_, z_ = R.date(s), R.date(e)
    if kind == "all":
        want_plain = None
    elif A["before"]:
        want_plain = f"Delivery Cycle 2 starts on {a_}. As of {R.asof.isoformat()}, {done_epics:,} of {N:,} epics planned in it are already Done."
    elif kind == "c1":
        want_plain = f"Delivery Cycle 1: W{wa} to W{wz} ({a_} to {z_}). Counts only epics planned in this cycle. Done is cumulative since W1. The even-pace line reaches the scope at the end of W{wz}." + (f" Window closed on {z_}." if A["closed"] else "")
    else:
        carry_txt = (f"so the line starts at the {A['carry']:,} {'epic' if A['carry'] == 1 else 'epics'} already Done before W{wa}. The even-pace line goes from there to the scope at the release end." if A["carry"]
                     else f"and none of them was Done before W{wa}, so the line starts at zero. The even-pace line goes from zero to the scope at the release end.")
        want_plain = f"Delivery Cycle 2: W{wa} to W{wz} ({a_} to {z_}). Counts only epics planned in this cycle. Done is cumulative since the release start, {carry_txt}"
    got_plain = r.get("plain")
    if got_plain != want_plain:
        p.append(f"{tag} the plain-words line is {got_plain!r}, expected {want_plain!r}")
    if kind == "all" and ax["hasPlain"]:
        p.append(f"{tag} the plain-words element exists with every cycle shown")
    if kind == "c2" and not A["before"] and "Done is cumulative" not in (got_plain or ""):
        p.append(f"{tag} the plain line does not say that Done is cumulative")
    wb = wz
    want_aria = f"Burnup for {R.rel}, weeks {wa} to {wb}: {A['done_n']} epics Done against a scope of {N}" + (f", {nm}" if nm else "") + (f"; {nm.split(' only')[0]} has not started" if A["before"] else "") + ". Daily values are in the data table below."
    if r["svgAria"] != want_aria:
        p.append(f"{tag} the aria-label is {r['svgAria']!r}, expected {want_aria!r}")
    # ---- the readout of every day of the window, the keyboard, the links
    reads = ax["reads"]
    first_want = max(s, min(e, B["snap_d"]))
    fl = ax["flags"]
    if not (fl["leftStays"] and fl["rightStays"] and fl["home"] and fl["end"] and fl["tipHidden"]):
        p.append(f"{tag} keyboard: ArrowLeft at the first day / ArrowRight at the last day stay, Home and End, Escape: {fl}")
    if len(reads) != e - s + 1:
        p.append(f"{tag} the keyboard walks {len(reads)} days, the window has {e - s + 1}")
        return
    if not (ax["first"]["tip"] or "").startswith(R.date(first_want)):
        p.append(f"{tag} focus starts on {ax['first']['tip'][:12]}, expected {R.date(first_want)}")
    for i, rd in enumerate(reads):
        d = s + i
        lines = rd["tip"].split("|")
        bad = []
        if not lines[0].startswith(f"{R.date(d)} (W{d // 7 + 1})"):
            bad.append(f"date/week {lines[0]!r}")
        if f"Target scope {N}" not in lines:
            bad.append("scope")
        if A["before"]:
            if not any("already Done; the cycle starts" in x for x in lines) or any(x.startswith("Even pace") for x in lines):
                bad.append("pre-start text")
        elif f"Even pace {jround(A['pace'](d))}" not in lines:
            bad.append(f"even pace {[x for x in lines if x.startswith('Even')]} vs {jround(A['pace'](d))}")
        has_done = any(x.startswith("Done ") for x in lines)
        if has_done != (d <= B["snap_d"]) or (has_done and f"Done {ser[d]} (any Commitment Type)" not in lines):
            bad.append(f"Done {[x for x in lines if x.startswith('Done')]} vs {ser[d] if d <= B['snap_d'] else None}")
        bound = f'resolutiondate < "{R.date(d + 1)}"' in urllib.parse.unquote_plus(rd["href"])
        if bound != (d < D and not A["before"]):
            bad.append(f"link bound={bound}")
        if bad:
            p.append(f"{tag} day {d} ({R.date(d)}) readout: {'; '.join(bad)}")
            break
    for i in sorted({0, len(reads) // 2, len(reads) - 1}):                       # the link of a day finds the epics Done up to it (or every Done epic on the last day)
        d, href = s + i, reads[i]["href"]
        if not jql_of(href):
            continue
        want_n = len(B["all_done"]) if d >= D or A["before"] else ser[d]
        got_n = len(keys_of(jql_of(href), universe))
        if got_n != want_n:
            p.append(f"{tag} the link of day {d} finds {got_n} epics, the recount {want_n}")
    # ---- the default Done link (the one the chart opens) and the headline number
    if r["buLink"] and jql_of(r["buLink"]):
        want_n = ser[e] if A["closed"] else len(B["all_done"])
        got_n = len(keys_of(jql_of(r["buLink"]), universe))
        if got_n != want_n or (r["sub"] or "").split(" ")[0].replace(",", "") != str(shown):
            p.append(f"{tag} the Done link finds {got_n} epics, the recount {want_n}; the headline number is {(r['sub'] or '').split(' ')[0]} (expected {shown})")
        if A["closed"] and 'resolutiondate < "' not in urllib.parse.unquote_plus(r["buLink"]):
            p.append(f"{tag} the Done link of a closed Delivery Cycle 1 is not bounded at its end")


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
    A = R.axis(B)
    want_days = set(A["grid"]) | ({snap_d, D} | ({41} if want_c1 else set()) if A["kind"] == "all" else ({snap_d} if not A["before"] and A["s"] <= snap_d <= A["e"] else set()) | {A["e"]})
    if [row[0] for row in r["rows"]] != [R.date(d) for d in sorted(want_days)]:
        p.append(f"{tag} the table rows are {[row[0] for row in r['rows']]}, expected the days {[R.date(d) for d in sorted(want_days)]}")
    for row in r["rows"]:
        d = (day(row[0]) - R.w1).days
        if d < 0 or d >= len(series):
            break
        want = [str(N), str(series[d]) if d <= snap_d else DASH, str(max(0, N - series[d])) if d <= snap_d else DASH]
        if row[2:5] != want:
            p.append(f"{tag} row {row[0]}: Scope/Done/Remaining {row[2:5]}, the recount {want}")
            break
        if row[1] != f"W{min(d, D - 1) // 7 + 1}":
            p.append(f"{tag} row {row[0]}: week {row[1]}, expected W{min(d, D - 1) // 7 + 1}")
        if want_c1 and d == 41 and row[5:7] != [str(len(B["within"])), str(len(B["within_done"]))]:
            p.append(f"{tag} Delivery Cycle 1 columns at the cycle end {row[5:7]}, the recount {[len(B['within']), len(B['within_done'])]}")
    if r.get("axis"):
        check_axis(p, R, B, A, universe, r, tag)
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
        if r["buLink"] and not A["closed"]:                                     # a closed Delivery Cycle 1 has a bounded Done link: check_axis
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
            got[d] = (int(r["rows"][0][2]), int(r["sub"].split(" ")[0].replace(",", "")))          # the Done now, from the headline: Cycle 2 before its start has no Done row (the table shows its days only)
        R = Recount(data, rel, set(data["projects"]), set(), None, load(ch, url, f"r={rel}")["asOf"])
        tgt = [e for e in R.sel if (e.get("c") or "Not Set") in ("Committed", "Not Set")]
        mem = [e for e in tgt if day((e.get("ad") or {}).get(rel) or R.start.isoformat()) <= R.w1]
        none = sum(1 for e in mem if R.cycle(e) is None)
        t.check(got["dc=1"][0] + got["dc=2"][0] + none == got[""][0], f"{rel}: scope {got['dc=1'][0]} + {got['dc=2'][0]} + {none} in no cycle != {got[''][0]}")
        doneNone = sum(1 for e in R.sel if e["s"] == "Done" and R.cycle(e) is None)
        t.check(got["dc=1"][1] + got["dc=2"][1] + doneNone == got[""][1], f"{rel}: Done {got['dc=1'][1]} + {got['dc=2'][1]} + {doneNone} in no cycle != {got[''][1]}")
        t.check(got["dc=1"][0] > 0 and got["dc=2"][0] > 0 or rel == "27.2", f"{rel}: both cycles hold target epics in the fixture ({got})")


# --------------------------------------------------------------------------------------------- 1b: the burnup's X axis follows the filter
AXIS_KINDS = ["variant", "asof_pre", "asof_w6end", "asof_w7", "asof_after"]


@SUITE.test("burnup_axis_follows_the_filter_for_every_as_of_day")
def _(t: T):
    """The as-of day before W1 (the IP week), inside Delivery Cycle 1 (the stock payload), on the last day of Delivery Cycle 1, inside Delivery Cycle 2 and after the release end,
    each with both cycles, Cycle 1 only and Cycle 2 only: ticks, end marker, lines, labels, headline, plain line, readout of every day, links."""
    ch = ctx.chrome
    probs: list[str] = []
    n = 0
    for kind in AXIS_KINDS:
        data, url, universe = payload(kind)
        for d in DCS:
            h = "&".join(x for x in ("r=27.1", d) if x)
            check_view(probs, data, universe, h, load(ch, url, h), kind)
            n += 1
    data, url, universe = payload("variant")
    for rel in ("26.4", "27.2"):                                                        # a closed release and one that has not started
        for d in DCS:
            h = "&".join(x for x in (f"r={rel}", d) if x)
            check_view(probs, data, universe, h, load(ch, url, h), "variant")
            n += 1
    t.note(f"{n} views")
    for x in probs[:12]:
        t.check(False, x)
    t.check(not probs, f"{len(probs)} differences in {n} views")


@SUITE.test("burnup_axis_fixture_reaches_the_cases_it_claims")
def _(t: T):
    """The states above must be real, or the test proves nothing: a pre-start Cycle 2, a carry-in above zero, epics Done after the end of Cycle 1, a snapshot inside each window."""
    for kind, dc, want in (("variant", {2}, "before"), ("variant", {1}, "in_win"), ("asof_pre", {2}, "before"), ("asof_w6end", {1}, "closed"), ("asof_w7", {1}, "closed"), ("asof_w7", {2}, "in_win"), ("asof_after", {2}, "none")):
        data, _u, _x = payload(kind)
        asof = (day(data["generated"][:10]))
        R = Recount(data, "27.1", set(data["projects"]), set(), dc, asof.isoformat())
        B = R.burnup()
        A = R.axis(B)
        if want == "none":
            t.check(not A["in_win"] and not A["before"], f"{kind} {dc}: after the release end no snapshot marker, no pre-start state")
        else:
            t.check(A[want], f"{kind} {dc}: expected {want}: {A['raw']} (window {A['s']}..{A['e']})")
    data, _u, _x = payload("asof_w7")
    R = Recount(data, "27.1", set(data["projects"]), set(), {2}, day(data["generated"][:10]).isoformat())
    A2 = R.axis(R.burnup())
    R1 = Recount(data, "27.1", set(data["projects"]), set(), {1}, day(data["generated"][:10]).isoformat())
    B1 = R1.burnup()
    t.check(A2["carry"] > 0 and R.burnup()["series"][-1] > A2["carry"], f"Cycle 2 has a carry-in ({A2['carry']}) and epics Done inside its window")
    t.check(B1["series"][B1["snap_d"]] - B1["series"][41] > 0, "epics of Cycle 1 were Done after its end (the 'more Done since' text)")


@SUITE.test("burnup_with_both_cycles_is_the_chart_without_the_filter_and_a_click_redraws_it")
def _(t: T):
    """Both ticked: the whole release (day 0 to the end, W1 to W12, the dotted Delivery Cycle 1 marker, no plain line). Untick and tick again: the very same SVG, table and headline come back; a tooltip
    that is open when the filter changes is gone; the hash round trip for dc=1 and dc=2."""
    data, url, universe = payload("variant")
    ch = ctx.chrome
    snap = r"""(() => { const g = id => (document.getElementById(id) || {}).innerHTML; const tip = document.getElementById('bu-tip'), cross = document.getElementById('bu-cross');
      return {svg: g('burnup').replace(/<div class="bu-tip"[^]*$/, ''), data: g('bu-data'), sub: g('bu-sub'), plain: !!document.getElementById('bu-plain'), w6: g('bu-w6'),
              tip: tip ? getComputedStyle(tip).display : 'gone', cross: cross ? cross.style.display : 'gone'}; })()"""
    ch.goto(url + "#r=27.1")
    kit.wait_ready(ch)
    ch.js("(async () => { await document.fonts.ready; updateCore(); })()")           # the burnup measures text with the page font: draw once the fonts are in, so the first draw and a later one agree
    time.sleep(0.2)
    before = ch.js(snap)
    t.check(not before["plain"] and ">W12<" in before["svg"] and ">W13<" not in before["svg"] and "release end" in before["svg"], "both ticked: W1 to W12, no plain-words line")
    ch.js("document.getElementById('bu-link').dispatchEvent(new FocusEvent('focus'))")
    t.check(ch.js("getComputedStyle(document.getElementById('bu-tip')).display") == "block", "the focus opens the day readout")
    ch.js("document.querySelector('#f-dc input[value=\"1\"]').click()")
    time.sleep(0.4)
    mid = ch.js(snap)
    t.check(mid["plain"] and mid["svg"] != before["svg"] and "Delivery Cycle 2 only" in mid["svg"] and ">W1<" not in mid["svg"], "Cycle 1 unticked: the axis is Cycle 2's and the plain-words line appears")
    t.check(mid["tip"] in ("none", "gone") and mid["cross"] in ("none", "gone"), f"no stale tooltip or crosshair after the filter changed: {mid['tip']} {mid['cross']}")
    t.check("dc=2" in ch.js("location.hash") and ">W7<" in mid["svg"], "the address names dc=2 and the chart starts at W7")
    ch.js("document.querySelector('#f-dc input[value=\"1\"]').click()")
    time.sleep(0.4)
    after = ch.js(snap)
    t.check(not after["plain"] and after == before, "both ticked again: the SVG, the table, the headline and the fact line are exactly what they were")
    for h, first, last in (("r=27.1&dc=1", ">W1<", ">W6 end<"), ("r=27.1&dc=2", ">W7<", ">W12 end<")):
        ch.goto(url + "#" + h)
        kit.wait_ready(ch)
        time.sleep(0.2)
        x = ch.js(snap)
        t.check(first in x["svg"] and last in x["svg"] and x["plain"], f"#{h}: the axis runs {first} to {last}")
        t.check((">W1<" in x["svg"]) == (first == ">W1<") and (">W7<" in x["svg"]) == (first == ">W7<"), f"#{h}: only its own weeks")
        t.check(not ch.console_errors(), f"#{h}: console errors {ch.console_errors()[:2]}")


@SUITE.test("burnup_axis_one_day_window_and_phone_width")
def _(t: T):
    """A Delivery Cycle 2 of one day (the release ends the day after W6) draws without NaN; at 390 px the chart keeps its window and does not scroll sideways."""
    ch = ctx.chrome
    data, url, universe = payload("tiny")
    probs: list[str] = []
    for d in DCS:
        h = "&".join(x for x in ("r=27.1", d) if x)
        r = load(ch, url, h)
        check_view(probs, data, universe, h, r, "tiny")
        t.check(r["axis"] is not None and not r["axis"]["nan"], f"{h}: the one-day window has no NaN in the chart")
    t.check(not probs, "; ".join(probs[:3]))
    try:
        ch.viewport(390, 900, mobile=True)
        for kind in ("variant", "asof_w7"):
            data, url, universe = payload(kind)
            for d in ("dc=1", "dc=2"):
                h = f"r=27.1&{d}"
                r = load(ch, url, h)
                pr: list[str] = []
                check_view(pr, data, universe, h, r, f"{kind} 390")
                t.check(not pr, "; ".join(pr[:3]))
                m = ch.js("(() => ({sw: document.documentElement.scrollWidth, w: window.innerWidth, svg: document.querySelector('#burnup svg').getBoundingClientRect().right}))()")
                t.check(m["sw"] <= m["w"] + 1 and m["svg"] <= m["w"] + 1, f"390 px {kind} {d}: the page scrolls sideways {m}")
                a = r["axis"]
                dates = [x["t"] for x in a["texts"] if re.fullmatch(r"\d{4}-\d\d-\d\d", x["t"] or "")]
                R = Recount(data, "27.1", set(data["projects"]), set(), parse_state(h)[3], r["asOf"])
                A = R.axis(R.burnup())
                t.check(dates[0] == R.date(A["s"]) and dates[-1] == R.date(A["e"]) and len(set(dates)) == len(dates), f"390 px {kind} {d}: first and last tick are the window's {dates}")
    finally:
        ch.viewport(1400, 900)


# --------------------------------------------------------------------------------------------- 4: other sections do not read the filter
OTHER_JS = r"""(async () => {
  await document.fonts.ready; updateCore();
  const m = document.querySelector('main').cloneNode(true);
  ['#filters', '#f-live', '#burnup', '#bu-sub', '#bu-plain', '#bu-w6', '#bu-cap', '#bu-data', '#bu-legend', '#cycles', '#cy-body', '#cy-kpis1', '#cy-kpis2', '#cy-pods', '#cy-after', '#cy-sub', '#cy-cap', '#cy-notes', '#g-cy', '#cy-podlist', '#cy-pods-h'].forEach(s => m.querySelectorAll(s).forEach(n => n.remove()));
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
    # the burnup's X axis
    ("the burnup axis ignores the filter", "const DM = win ? dcDomain(rel, dc) : null,", "const DM = win ? dcDomain(rel, {all: true, shown: dc.shown}) : null,"),
    ("Cycle 2 Done restarts at zero (the carry-in is dropped)", "let d = `M${x(ds)},${y(done[kind === \"c2\" ? ds - 1 : 0])}`;", "let d = `M${x(ds)},${y(kind === \"c2\" ? 0 : done[0])}`;"),
    ("the Cycle 1 even pace is not re-anchored (still to the release end)", "kind === \"c1\" ? (de ? N * d / de : 0)", "kind === \"c1\" ? (D ? N * d / D : 0)"),
    ("the Cycle 2 even pace starts at zero", "const p0 = Math.min(carry, N), paceAt", "const p0 = 0, paceAt"),
    ("the dotted Delivery Cycle 1 marker is drawn with Cycle 1 only", "const w6Mark = W6 && dc.all;", "const w6Mark = W6;"),
    ("the snapshot marker is drawn outside the window", "const inWin = kind === \"c2\" ? snapRaw >= ds && snapRaw < de : snapD < de;", "const inWin = snapD < D;"),
    ("the pre-start state is drawn as a chart", "const before = kind === \"c2\" && snapRaw < ds;", "const before = false;"),
    ("the headline does not stop at the end of Delivery Cycle 1", "const shownDone = closed ? done[de] : dn.length, since = closed ? done[snapD] - done[de] : 0;", "const shownDone = dn.length, since = 0;"),
    ("the Done link of a closed Delivery Cycle 1 is unbounded", "...(closed ? {extra: `resolutiondate < \"${iso(w1 + (de + 1) * DAY)}\"`} : {})", ""),
    ("the keyboard leaves the window", "kd = ev.key === \"Home\" ? ds : de; dayAt(kd);", "kd = ev.key === \"Home\" ? 0 : D; dayAt(kd);"),
    ("the plain-words line is shown with both cycles", "if (dc.all || !win) { if (pl0) pl0.remove(); }", "if (!win) { if (pl0) pl0.remove(); }"),
    ("the last day of a narrowed axis has no tick", "const endTick = kind !== \"all\" && (de - ds) % tickEvery !== 0;", "const endTick = false;"),
    ("the carry-in note is missing in Cycle 2", "else if (kind === \"c2\" && carry > 0) g +=", "else if (false) g +="),
    ("the Cycle 1 end marker says release end", "`end of ${cy1} ${shortDate(w1 + de * DAY)}`", "`release end ${shortDate(end)}`"),
    ("the even-pace readout ignores the window", "const pace = Math.round(paceAt(d));", "const pace = Math.round(D ? N * d / D : 0);"),
]
MUTANT_VIEWS = [("variant", "r=27.1&dc=1"), ("variant", "r=27.1&dc=2"), ("variant", "r=27.1"), ("asof_w7", "r=27.1&dc=1"), ("asof_w7", "r=27.1&dc=2"), ("asof_w7", "r=27.1")]


@SUITE.test("selftest_oracle_catches_seeded_defects")
def _(t: T):
    src = ctx.template.read_text(encoding="utf-8")
    ch = ctx.chrome
    for i, (what, old, new) in enumerate(MUTANTS):
        if src.count(old) != 1:
            raise kit.Skip(f"the seeding anchor for '{what}' is not in this template exactly once (found {src.count(old)})")
        tpl = _write_tmp(src.replace(old, new, 1))
        pages: dict = {}
        probs: list[str] = []
        views = MUTANT_VIEWS + ([("variant", "r=27.1&p=PMN&dc=2&ct=pmn"), ("variant", "r=27.1&p=PMN&ct=pmn")] if "undated" in what else [])
        for kind, h in views:
            data, _u, universe = payload(kind)
            if kind not in pages:
                f = Path(ctx.dir) / f"dcf_mutant_{i}_{kind}.html"
                f.write_text(MS.render_page(data, tpl), encoding="utf-8")
                pages[kind] = "file://" + str(f)
            check_view(probs, data, universe, h, load(ch, pages[kind], h), "mutant")
        if "undated" in what:
            data, _u, universe = payload("variant")
            deep_check_cycles(ch, pages["variant"], data, universe, probs)
        t.check(bool(probs), f"the oracle did not notice the seeded defect: {what}")


def _write_tmp(text: str) -> Path:
    p = Path(ctx.dir) / f"template_mutant_{abs(hash(text)) % 10**8}.html"
    p.write_text(text, encoding="utf-8")
    return p


if __name__ == "__main__":
    sys.exit(kit.cli(SUITE, __doc__))
