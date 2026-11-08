#!/usr/bin/env python3
"""Delivery Cycle filter oracle: the header filter (Cycle 1, Cycle 2) and what it changes, recounted independently in Python and compared with the page.

The filter changes the Delivery burnup, the Cycles section and the Epics Delivered and Forecast Epics tiles only. A cycle holds the epics whose planned date (the due date, else the Target Sprint end; the burnup alone keeps the later of the due date and the Target Sprint end) falls in it:
Delivery Cycle 1 on or before the end of W6 (release start + 48 days; earlier dates included), Delivery Cycle 2 from the next day to the release end. An epic with no planned date,
or planned after the release end, is in neither cycle and counts only when every cycle is shown. This file spells the rule again, on purpose, and never imports it from the page.

  1. Burnup (several releases x Projects x Teams x Cycle 1 only / Cycle 2 only / both): the filter picks a TIME WINDOW of the whole-release chart, not epics. Scope, Done and Remaining of every row of
     the "Show data" table, the Delivery Cycle 1 fact line and its two columns, the title line that names the cycle, and the Jira links (scope, target today, the Done link, the day links, the Delivery
     Cycle 1 links) evaluated with jql_eval.py over the baked epics: each must find exactly the epics the recount counts, and the numbers are the same in the three views.
  1b. The window, the lines and the labels: Both cycles = day 0 to the release end, exactly the chart without the filter; Cycle 1 only = W1 to the end of W6 (day 0 to 41): no release scope, the dotted
     "Delivery Cycle 1 . N planned" marker at the end of the window, the even-pace line from 0 through it; Cycle 2 only = W7 to the release end (day 42 to the end): the even-pace line from its start
     (Done at the end of W6 once W6 has ended, N before: "planned start") to the release scope, the Done line only from W7. The week ticks, the last tick and the end marker, every day of the keyboard
     readout, the drawn lines read back from the SVG geometry, the plain-words line, the headline, the labels, the aria-label and the table days, for the as-of day before Delivery Cycle 1, inside it,
     on its last day, inside Delivery Cycle 2 and after the release end; a window of one day; a 390 px chart; the hash round trip and the re-draw on a click.
  2. Cycles section: it has NO selector of its own and follows this filter; a banner names the cycles it shows and their dates (Cycle 1, Cycle 2, or both combined); the five Overview figures equal a recount
     of the selected window (both ticked: every epic planned from the release start to the release end, counted once); "After Release End" and the "No Planned Date, Active" list appear only when every
     cycle is shown, with their counts. An older link with the removed key (cy=DC1) is ignored without an error.
  3. The header control: present, no Commitment Type control, the hash round trip (dc), an older c= link ignored, the last cycle cannot be unticked, keyboard operation, no sideways scroll at 320 and
     800 px, a release with only Delivery Cycle 1 (Cycle 2 disabled with its reason; a stored dc=2 falls back to Cycle 1).
  4. Other sections do not read the filter (the page outside the burnup, the Cycles section, the filter bar and the two epic-delivery tiles Epics Delivered and Forecast Epics, which tile_oracle.py checks, is identical with Cycle 1 only, Cycle 2 only and both).
  5. Seeded defects must be caught: Cycles ignoring the filter, both cycles counted as Cycle 1 only, the banner naming the wrong cycle, the removed selector coming back, the old key read again, After Release End or the undated list shown for one cycle, Cycle 1 ending a day early in the Cycles section; and for the burnup:
     Done or Scope narrowed to the cycle's epics, the domain not narrowed, Done restarting at zero in Cycle 2, the Done line or label drawn before W7, the Cycle 1 pace not through the end state,
     the Cycle 2 pace starting at scope minus N / ignoring the end of W6 / at Done now before W7, the planned-start label missing, the release scope drawn in the Cycle 1 view, the dotted marker
     missing at the end of Cycle 1 or drawn in Cycle 2, the snapshot marker outside the window, Cycle 2 treated as started before W7, the headline not stopping at the end of Cycle 1, the
     window-end link unbounded, the keyboard leaving the window, the plain line with both cycles ticked.
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
    banner: t(document.getElementById('cy-showing')), bannerCycles: (document.getElementById('cy-banner') || {dataset: {}}).dataset.cycles, point: t(document.getElementById('cy-point')), tiles, after: t(document.getElementById('cy-after')), cySub: t(document.getElementById('cy-sub')),
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

    def planned(self, e):                                   # the burnup's rule: the later of the due date and the Target Sprint end
        ts, dd = self.sprint_end.get(e.get("ts")), e.get("dd")
        return max(dd, ts) if dd and ts else (dd or ts)

    def planned_due(self, e):                               # the Cycles section's rule: the due date; the Target Sprint end only when there is no due date
        return e.get("dd") or self.sprint_end.get(e.get("ts"))

    def cycle(self, e):
        p = self.planned_due(e)
        if not p:
            return None
        return 1 if day(p) <= self.w6 else 2 if day(p) <= self.end else None

    def keep(self, e):
        return self.all or self.cycle(e) in self.shown

    # ---- burnup
    def burnup(self):
        tgt = [e for e in self.sel if (e.get("c") or "Not Set") in ("Committed", "Not Set")]
        members = [e for e in tgt if day((e.get("ad") or {}).get(self.rel) or self.start.isoformat()) <= self.w1]
        tgt_k, mem_k = tgt, members                                          # the burnup shows the whole release in every view: the filter picks a time window, not epics
        done = [e for e in self.sel if e["s"] == "Done"]
        D = (self.end - self.w1).days
        clamp = lambda d: min(max(day(d), self.w1), self.end)
        times = sorted((clamp(e["rd"]) - self.w1).days for e in done if e.get("rd"))
        series = [sum(1 for x in times if x <= d) for d in range(D + 1)]
        snap_d = min(D, max(0, (self.asof - self.w1).days))
        committed = [e for e in self.sel if e.get("c") == "Committed"]
        within = [e for e in committed if self.planned(e) and day(self.planned(e)) <= self.w6]
        return dict(D=D, snap_d=snap_d, pre=self.asof < self.w1, N=len(mem_k), tgt=tgt_k, members=mem_k, done=done, series=series, committed=committed, within=within,
                    within_done=[e for e in within if e["s"] == "Done"], none=[e for e in committed if not self.planned(e)], all_done=[e for e in self.sel if e["s"] == "Done"])

    # ---- the window of the burnup's X axis and the lines on it, spelled again here (days since W1 start)
    def axis(self, B: dict) -> dict:
        D, N, ser, snap_d = B["D"], B["N"], B["series"], B["snap_d"]
        kind, s, e = ("all", 0, D) if self.all else ("c1", 0, min(41, D)) if 1 in self.shown else ("c2", 42, D)
        nP = len(B["within"])                                               # the Committed epics planned by the end of W6: the end state of Delivery Cycle 1, the planned start of Delivery Cycle 2
        raw = (self.asof - self.w1).days                                    # the unclamped as-of day
        before = kind == "c2" and raw < s                                   # Delivery Cycle 2 has not started: no Done line, no snapshot marker, the pace starts at nP
        in_win = (s <= raw < e) if kind == "c2" else snap_d < e              # the snapshot marker and the "vs even pace" comparison
        closed = kind == "c1" and raw >= e
        d_end = min(snap_d, e)
        carry = ser[s - 1] if kind == "c2" else 0                           # the whole release's Done at the end of W6 (cumulative)
        p0 = min(nP if before else carry, N) if kind == "c2" else 0
        top = nP if kind == "c1" else N                                     # where the even-pace line ends: Cycle 1 at nP (the dotted marker), the others at the release scope

        def pace(d: int) -> float:
            if kind == "all":
                return N * d / D if D else 0
            if kind == "c1":
                return nP * d / e if e else 0
            return p0 + (N - p0) * ((d - s) / (e - s) if e > s else 1)

        grid = list(range(s, e + 1, 7))
        end_tick = kind != "all" and (e - s) % 7 != 0
        done_n = ser[d_end]
        pace_txt = raw >= 0 and in_win and top >= 5
        return dict(kind=kind, s=s, e=e, D=D, N=N, nP=nP, raw=raw, before=before, in_win=in_win, closed=closed, d_end=d_end, carry=carry, p0=p0, top=top, pace=pace, grid=grid, end_tick=end_tick,
                    done_n=done_n, dv=jround(done_n - pace(d_end)), pace_txt=pace_txt, start_level=ser[s - 1] if kind == "c2" else ser[0])

    def date(self, d: int) -> str:
        return (self.w1 + dt.timedelta(days=d)).isoformat()

    # ---- cycles
    def window(self):
        """The cycles that are shown as one window (the cycles are consecutive): the release start to the end of W6 for Cycle 1 only, the day after it to the release end for Cycle 2 only, the whole
        release for both. Also its name, as the banner words it."""
        c1_end = self.w6 if self.has2 else self.end
        lo = self.start if 1 in self.shown else self.w6 + dt.timedelta(days=1)
        hi = self.end if 2 in self.shown else c1_end
        name = "Delivery Cycles 1 and 2" if len(self.shown) > 1 else f"Delivery Cycle {min(self.shown)}"
        return lo, hi, name

    def cycles_tiles(self):
        lo, hi, _n = self.window()
        pl = [e for e in self.sel if self.planned_due(e) and lo <= day(self.planned_due(e)) <= hi]
        nd = lambda e: e["s"] != "Done"
        over = [e for e in pl if nd(e) and day(self.planned_due(e)) < self.asof]
        nxt = [e for e in pl if nd(e) and self.asof <= day(self.planned_due(e)) <= self.asof + dt.timedelta(days=7)]
        return {"planned": len(pl), "done": sum(1 for e in pl if not nd(e)), "overdue": len(over), "next": len(nxt), "flagged": sum(1 for e in pl if nd(e) and e.get("fl"))}

    def after_count(self):
        return sum(1 for e in self.sel if self.planned_due(e) and day(self.planned_due(e)) > self.end)

    def nodue(self, project: str):
        return sum(1 for e in self.sel if e["p"] == project and e["s"] in ("In Progress", "Validation") and not self.planned_due(e))


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
            if kind == "asof_pre":
                _shrink_scope(d, w1)
            if kind == "asof_w7":
                _closures_after_w6(d, w1)
        _cache[kind] = (d, ctx.write(kit.fragment_for(d), "dcf_" + kind), [LC.epic_issue(e) for e in d["epics"]])
    return _cache[kind]


ASOF_DAYS = {"pre": -3, "w6end": 41, "w7": 45, "after": 90}     # days since W1 start: before W1, the last day of Delivery Cycle 1, inside Delivery Cycle 2, after the release end (83 days)


def _shrink_scope(d: dict, w1: dt.date) -> None:
    """The stock 27.1 plans fewer Committed epics by the end of W6 than its target scope holds (the ordinary case). Move 130 target epics into the release after W1: the scope falls below the planned
    count, so the pre-W6 Cycle 2 pace start (the planned count) is above the scope and is held at it."""
    R = Recount(d, "27.1", set(d["projects"]), set(), None, "2026-01-01")
    for e in [e for e in R.sel if (e.get("c") or "Not Set") in ("Committed", "Not Set")][:130]:
        e["ad"] = {**(e.get("ad") or {}), "27.1": (w1 + dt.timedelta(days=10)).isoformat()}


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
    """The burnup's X axis and everything drawn on it, against the recount. The numbers are the whole release's in every view; the filter picks the window."""
    ax, kind, s, e, D, N, ser, nP = r["axis"], A["kind"], A["s"], A["e"], A["D"], A["N"], B["series"], A["nP"]
    nm = "" if kind == "all" else f"Delivery Cycle {1 if kind == 'c1' else 2} only"
    wide = int(float(ax["width"])) >= 900
    if ax["nan"]:
        p.append(f"{tag} the chart contains NaN or undefined")
    # ---- the week ticks (1400 px: one every 7 days) and the end marker
    pairs = [(t["t"], t["x"], ax["texts"][i + 1]["t"]) for i, t in enumerate(ax["texts"][:-1]) if re.fullmatch(r"\d{4}-\d\d-\d\d", t["t"] or "") and re.fullmatch(r"W\d+( end)?", ax["texts"][i + 1]["t"] or "")]
    want = [(R.date(d), f"W{d // 7 + 1}") for d in A["grid"]] + ([(R.date(e), f"W{min(e, D - 1) // 7 + 1} end")] if A["end_tick"] else [])
    if wide and [(a, c) for a, _x, c in pairs] != want:
        p.append(f"{tag} the week ticks are {[(a, c) for a, _x, c in pairs][:3]}..{[(a, c) for a, _x, c in pairs][-2:]} ({len(pairs)}), expected {want[:3]}..{want[-2:]} ({len(want)})")
    if pairs and (pairs[0][0] != R.date(s) or pairs[-1][0] != want[-1][0] and (kind != "all" or wide)):
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
    top_y = max([A["top"]] + (ser[max(0, s - 1):e + 1] if kind != "all" and not A["before"] else [nP] if A["before"] else ser))
    if ylabels and ylabels[-1] < top_y:
        p.append(f"{tag} the Y axis stops at {ylabels[-1]}, below the largest value {top_y}")
    # ---- the drawn lines
    def near(a, b, tol=0.02):
        return a is not None and abs(a - b) <= tol
    pace_l = [l for l in ax["lines"] if l["stroke"] == "#6E737C" and l["dash"] == "6 4"]
    if len(pace_l) != 1:
        p.append(f"{tag} {len(pace_l)} even-pace lines, expected 1")
    elif day_of and val_of:
        l = pace_l[0]
        got = (day_of(l["x1"]), val_of(l["y1"]), day_of(l["x2"]), val_of(l["y2"]))
        want_p = (s, A["p0"], e, A["top"])
        if not all(near(g, w, 0.02 if i % 2 == 0 else 0.3) for i, (g, w) in enumerate(zip(got, want_p))):
            p.append(f"{tag} the even-pace line runs {tuple(round(g, 2) for g in got)} (day, epics, day, epics), expected {want_p}")
    done_p = [q for q in ax["paths"] if q["stroke"] == "#025AFB"]
    if len(done_p) != (0 if A["before"] else 1):
        p.append(f"{tag} {len(done_p)} Done lines, expected {0 if A['before'] else 1} (the Done line is drawn only once W7 has started in Delivery Cycle 2)")
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
    # the dotted Delivery Cycle 1 marker: at day 41 inside the whole release, at the end of the window with Cycle 1 only (its end state), not in Cycle 2
    w6_l = [l for l in ax["lines"] if l["dash"] == "1 4"]
    want_w6 = kind != "c2" and D >= 41
    if len(w6_l) != (1 if want_w6 else 0):
        p.append(f"{tag} the dotted Delivery Cycle 1 marker is {'drawn' if w6_l else 'missing'}, expected {'drawn' if want_w6 else 'not drawn'} for {kind}")
    elif w6_l and day_of and not near(day_of(w6_l[0]["x1"]), 41):
        p.append(f"{tag} the dotted marker is at day {day_of(w6_l[0]['x1']):.2f}, expected day 41")
    if any(t and (t.startswith("Delivery Cycle 1 \u00b7") or t.endswith("epics planned")) for t in texts) != want_w6:
        p.append(f"{tag} the 'Delivery Cycle 1 \u00b7 N planned' label is {'drawn' if not want_w6 else 'missing'}, expected the opposite for {kind}")
    w6_dot = [dd for dd in ax["dots"] if dd["r"] == 4.5]
    if want_w6 and w6_dot and day_of and val_of and not (near(day_of(w6_dot[0]["cx"]), 41) and near(val_of(w6_dot[0]["cy"]), min(nP, ylabels[-1]), 0.3)):        # the dot stays on the chart's own scale (the whole-release chart's rule); the Cycle 1 scale always holds nP
        p.append(f"{tag} the end-state dot is at day {day_of(w6_dot[0]['cx']):.2f}, {val_of(w6_dot[0]['cy']):.2f} epics; expected day 41, {min(nP, ylabels[-1])}")
    if len(w6_dot) != (1 if want_w6 else 0):
        p.append(f"{tag} {len(w6_dot)} end-state dots, expected {1 if want_w6 else 0}")
    # the release scope: drawn (dot and label) in every view but Delivery Cycle 1
    dots = [dd for dd in ax["dots"] if dd["r"] == 4]
    hov = [dd for dd in ax["dots"] if dd["r"] == 9]                          # the transparent hover target of the scope dot
    if len(hov) != (0 if kind == "c1" else 1):
        p.append(f"{tag} {len(hov)} scope hover targets, expected {0 if kind == 'c1' else 1}")
    if len(dots) != (0 if kind == "c1" else 1):
        p.append(f"{tag} {len(dots)} release-scope dots, expected {0 if kind == 'c1' else 1}")
    elif dots and day_of and val_of and not (near(day_of(dots[0]["cx"]), e) and near(val_of(dots[0]["cy"]), N, 0.3)):
        p.append(f"{tag} the scope dot is at day {day_of(dots[0]['cx']):.2f}, {val_of(dots[0]['cy']):.2f} epics; expected day {e}, {N}")
    if (f"Scope {N:,}" in texts) != (kind != "c1") or (kind == "c1" and any(t and "since W1" in t for t in texts)):
        p.append(f"{tag} the Scope label is {'missing' if kind != 'c1' else 'drawn in the Delivery Cycle 1 view'}: Scope {N}")
    # ---- the labels
    done_t = [t for t in texts if t and re.match(r"Done [\d,]+", t)]
    want_done = f"Done {A['done_n']:,}" + (f" \u00b7 {'+' if A['dv'] >= 0 else UMINUS}{abs(A['dv'])} vs even pace" if A["pace_txt"] else "")
    if A["before"]:
        if done_t:
            p.append(f"{tag} a Done label is drawn before Delivery Cycle 2 starts: {done_t}")
    elif done_t != [want_done] and not (done_t == [f"Done {A['done_n']:,}"] and A["pace_txt"] and not wide and int(float(ax["width"])) < 520):
        p.append(f"{tag} the Done label reads {done_t}, expected {want_done!r}")
    if "Even pace" not in texts:
        p.append(f"{tag} the 'Even pace' label is missing")
    if ("planned start" in texts) != A["before"]:
        p.append(f"{tag} the 'planned start' label is {'missing' if A['before'] else 'drawn after W6 has ended'}")
    if any(t and ("already Done" in t or t.startswith("Starts ")) for t in texts):
        p.append(f"{tag} an 'already Done' or 'Starts' note is drawn")
    # ---- the headline, the plain-words line, the aria-label
    done_epics = len(B["all_done"])
    shown = ser[e] if A["closed"] else done_epics
    since = ser[B["snap_d"]] - ser[e] if A["closed"] else 0
    head = f"{shown:,} of {N:,} target scope epics delivered" + (" by the end of Delivery Cycle 1" + (f" \u00b7 {since:,} more Done since" if since > 0 else "") if A["closed"] else "") + (f" \u00b7 Delivery Cycle 2 starts {R.date(s)}" if A["before"] else "")
    if not ((r["sub"] or "") == head or (r["sub"] or "").startswith(head + " \u00b7")):
        p.append(f"{tag} the headline is {r['sub']!r}, expected it to start {head!r}")
    wa, wz = s // 7 + 1, (jround(D / 7) if kind != "c1" else e // 7 + 1)
    a_, z_ = R.date(s), R.date(e)
    plural = lambda n: "epic" if n == 1 else "epics"
    if kind == "all":
        want_plain = None
    elif A["before"]:
        want_plain = f"Delivery Cycle 2 starts {a_}. Planned pace from the {nP:,} {plural(nP)} Delivery Cycle 1 plans to deliver to the release scope; Done is shown from W{wa}."
    elif kind == "c1":
        want_plain = (f"Delivery Cycle 1: W{wa} to W{wz} ({a_} to {z_}). The numbers are the whole release's: Done is cumulative since the release start. "
                      f"The even-pace line goes from zero to the {nP:,} {plural(nP)} Delivery Cycle 1 plans to deliver by the end of W{wz}." + (f" Window closed on {z_}." if A["closed"] else ""))
    else:
        want_plain = (f"Delivery Cycle 2: W{wa} to W{wz} ({a_} to {z_}). The numbers are the whole release's: Done is cumulative since the release start, so the line starts at the "
                      f"{A['carry']:,} {plural(A['carry'])} Done at the end of W{wa - 1}. The even-pace line goes from there to the release scope at the release end.")
    got_plain = r.get("plain")
    if got_plain != want_plain:
        p.append(f"{tag} the plain-words line is {got_plain!r}, expected {want_plain!r}")
    if kind == "all" and ax["hasPlain"]:
        p.append(f"{tag} the plain-words element exists with every cycle shown")
    if kind != "all" and "whole release" not in (got_plain or "") and not A["before"]:
        p.append(f"{tag} the plain line does not say that the numbers are the whole release's")
    c1_part = f", {nP} planned by the end of the window" if kind == "c1" else f" against a scope of {N}"
    want_aria = f"Burnup for {R.rel}, weeks {wa} to {wz}: {A['done_n']} epics Done{c1_part}" + (f", {nm}" if nm else "") + (f"; {nm.split(' only')[0]} has not started" if A["before"] else "") + ". Daily values are in the data table below."
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
        if (f"Target scope {N}" in lines) != (kind != "c1"):
            bad.append("scope line" + (" in the Delivery Cycle 1 view" if kind == "c1" else ""))
        if f"Even pace {jround(A['pace'](d))}" not in lines:
            bad.append(f"even pace {[x for x in lines if x.startswith('Even')]} vs {jround(A['pace'](d))}")
        has_done = any(x.startswith("Done ") for x in lines)
        if has_done != (d <= B["snap_d"]) or (has_done and f"Done {ser[d]} (any Commitment Type)" not in lines):
            bad.append(f"Done {[x for x in lines if x.startswith('Done')]} vs {ser[d] if d <= B['snap_d'] else None}")
        bound = f'resolutiondate < "{R.date(d + 1)}"' in urllib.parse.unquote_plus(rd["href"])
        if bound != (d < D):
            bad.append(f"link bound={bound}")
        if bad:
            p.append(f"{tag} day {d} ({R.date(d)}) readout: {'; '.join(bad)}")
            break
    for i in sorted({0, len(reads) // 2, len(reads) - 1}):                       # the link of a day finds the epics Done up to it (or every Done epic on the last day)
        d, href = s + i, reads[i]["href"]
        if not jql_of(href):
            continue
        want_n = len(B["all_done"]) if d >= D else ser[d]
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
    if r["empty"] is not None and "planned in Delivery Cycle" in r["empty"]:
        p.append(f"{tag} the burnup shows a notice about epics planned in a cycle: the chart is the whole release, whatever cycle is ticked ({r['empty']!r})")
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
    if D >= 41:                                                    # the fact line is the whole release's in every view (Cycle 2's planned start reads it too)
        m = re.search(r"\(ends ([\d-]+)\): (\d+)(?: of (\d+))? Committed epics? planned; (\d+) Done, (\d+) not Done(?:, (\d+) undated)?\.", r["w6"] or "")
        if B["committed"] and not m:
            p.append(f"{tag} the Delivery Cycle 1 fact line is not in the expected form: {r['w6']!r}")
        elif m:
            a, of, dn, nd, un = m.group(2), m.group(3), m.group(4), m.group(5), m.group(6)
            wantf = (str(len(B["within"])), str(len(B["committed"])), str(len(B["within_done"])), str(len(B["within"]) - len(B["within_done"])), str(len(B["none"])))
            if (a, of, dn, nd, un) != wantf:
                p.append(f"{tag} the Delivery Cycle 1 line says {(a, of, dn, nd, un)}, the recount {wantf} (planned, of Committed, Done, not Done, undated)")
        if r["w6Links"] and keys_of(jql_of(r["w6Links"][0]["href"]), universe) != {e["k"] for e in B["within"]}:
            p.append(f"{tag} the Delivery Cycle 1 'planned' link does not find the recounted epics")
    # ---- the links: scope and today (the whole release's target), the Done link (every Done epic of the release)
    cap_jql = [(l, jql_of(l["href"])) for l in r["capLinks"]]
    if True:
        want_today = {e["k"] for e in B["tgt"]}
        if not any(j for l, j in cap_jql):
            p.append(f"{tag} the burnup caption has no scope link")
        for i, (l, j) in enumerate(cap_jql):
            if j and keys_of(j, universe) != want_today:                        # the scope link (without its 'was in the release on W1' clause) and the target-today link: the target epics planned in the cycle
                p.append(f"{tag} the burnup caption link {i + 1} does not find the {len(want_today)} recounted target epics of the release")
        for l, j in cap_jql:
            if j and len(l["href"]) > 6000:
                p.append(f"{tag} a burnup link is over the 6,000 character budget ({len(l['href'])})")
        if r["buLink"] and not A["closed"]:                                     # a closed Delivery Cycle 1 has a bounded Done link: check_axis
            got = keys_of(jql_of(r["buLink"]), universe)
            want = {e["k"] for e in B["all_done"]}
            if got != want:
                p.append(f"{tag} the Done link finds {len(got)} epics, the recount {len(want)}")
    # ---- the Cycles section
    lo, hi, cname = R.window()
    want_banner = f"Showing {cname}{' combined' if len(R.shown) > 1 else ''} \u00b7 {lo.isoformat()} to {hi.isoformat()}"
    if r["banner"] != want_banner:
        p.append(f"{tag} the banner says {r['banner']!r}, expected {want_banner!r}")
    if r["bannerCycles"] != "+".join(str(i) for i in sorted(R.shown)):
        p.append(f"{tag} the banner names the cycles {r['bannerCycles']!r}, expected {sorted(R.shown)}")
    if R.has2 and "Delivery Cycle filter" not in (r["point"] or ""):
        p.append(f"{tag} the banner does not point to the Delivery Cycle filter: {r['point']!r}")
    if R.has2 and len(R.shown) == 2 and "Both cycles together" not in (r["point"] or ""):
        p.append(f"{tag} both cycles are shown and the banner does not say they are counted together: {r['point']!r}")
    if R.has2 and len(R.shown) == 1 and "planned outside it are not counted" not in (r["point"] or ""):
        p.append(f"{tag} one cycle is shown and the banner does not say what is left out: {r['point']!r}")
    if not R.has2 and "no Delivery Cycle 2" not in (r["point"] or ""):
        p.append(f"{tag} a release with one cycle must say it has no Delivery Cycle 2: {r['point']!r}")
    want_t = R.cycles_tiles()
    got_t = {k: (int(v.replace(",", "")) if re.fullmatch(r"[\d,]+", v or "") else v) for k, v in r["tiles"].items()}
    names = {"planned": "planned", "done": "done", "overdue": "overdue", "next": "next", "flagged": "flagged"}
    for k, v in want_t.items():
        if got_t.get(names[k]) != v:
            p.append(f"{tag} Cycles ({cname}) {k}: the page shows {got_t.get(names[k])}, the recount {v}")
    after = R.after_count()
    shown_after = re.search(r"After Release End: ([\d,]+)", r["after"] or "")
    if R.all and after:
        if not shown_after or int(shown_after.group(1).replace(",", "")) != after:
            p.append(f"{tag} After Release End: the page says {r['after']!r}, the recount {after}")
    elif shown_after:
        p.append(f"{tag} After Release End is shown ({r['after']!r}) but {'there are none' if R.all else 'epics in no cycle are left out while one cycle is shown'}")
    if (r["cySub"] or "") != "Delivery Cycle 1: release start to the end of W6. Delivery Cycle 2: W7 to the release end.":      # the two definitions only: what the selection shows and leaves out is the banner's job, said once
        p.append(f"{tag} the Cycles subtitle is not just the two cycle definitions (the banner says what is shown, once): {r['cySub']!r}")


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


@SUITE.test("burnup_numbers_are_the_whole_release_whatever_cycle_is_ticked")
def _(t: T):
    """The filter picks a time window of the whole-release burnup, not epics: Scope, Done (the number the Epics Delivered tile shows), the Done and scope links and the table's Scope column are the same
    with Cycle 1, Cycle 2 and both ticked, and equal the recount of the whole release."""
    data, url, universe = payload("variant")
    ch = ctx.chrome
    for rel in ("27.1", "27.2", "26.4"):
        got = {}
        for d in DCS:
            r = load(ch, url, "&".join(x for x in (f"r={rel}", d) if x), axis=False)
            got[d] = (int(r["rows"][0][2]), r["sub"].split(" ")[0].replace(",", ""), r["buLink"], [l["href"] for l in r["capLinks"]], r["empty"])
        R = Recount(data, rel, set(data["projects"]), set(), None, load(ch, url, f"r={rel}", axis=False)["asOf"])
        B = R.burnup()
        t.check(got[""][0] == B["N"] and got[""][4] is None, f"{rel}: both ticked shows the recounted scope {B['N']}: {got['']}")
        if rel != "26.4":                                       # the closed release: Cycle 1 is over, its headline stops at the end of the cycle (own test)
            for d in ("dc=1", "dc=2"):
                t.check(got[d][0] == got[""][0], f"{rel} {d}: Scope {got[d][0]} is not the whole release's {got[''][0]}")
                t.check(got[d][1] == got[""][1] == str(len(B["all_done"])), f"{rel} {d}: headline Done {got[d][1]} / {got[''][1]}, the recount {len(B['all_done'])}")
                t.check(got[d][2] == got[""][2] and got[d][3] == got[""][3], f"{rel} {d}: the Done and scope links differ from the whole release's")
                t.check(got[d][4] is None, f"{rel} {d}: a notice replaces the chart: {got[d][4]!r}")
    t.check(Recount(data, "27.1", set(data["projects"]), set(), {2}, load(ch, url, "r=27.1&dc=2", axis=False)["asOf"]).burnup()["N"] == Recount(data, "27.1", set(data["projects"]), set(), None, load(ch, url, "r=27.1", axis=False)["asOf"]).burnup()["N"],
            "the recount itself is whole-release in every view")


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
    t.check(A2["carry"] > 0 and R.burnup()["series"][-1] > A2["carry"], f"Cycle 2 has a Done count at the end of W6 ({A2['carry']}) and epics Done inside its window")
    t.check(A2["p0"] == A2["carry"] < A2["N"], f"once W6 has ended the Cycle 2 pace starts at the Done count ({A2['p0']}), below the scope ({A2['N']})")
    for kind, want in (("variant", "planned"), ("asof_pre", "clamped")):                  # before W6 ends the pace starts at the planned count nP: below the scope in the stock payload, above it (held at the scope) in the shrunk one
        dd, _u, _x = payload(kind)
        Rp = Recount(dd, "27.1", set(dd["projects"]), set(), {2}, day(dd["generated"][:10]).isoformat())
        Ap = Rp.axis(Rp.burnup())
        ok = Ap["before"] and Ap["nP"] > 0 and Ap["p0"] == min(Ap["nP"], Ap["N"]) and ((Ap["nP"] > Ap["N"]) == (want == "clamped"))
        t.check(ok, f"{kind}: before W6 ends the Cycle 2 pace starts at nP={Ap['nP']} (scope {Ap['N']}, start {Ap['p0']})")
    t.check(B1["series"][B1["snap_d"]] - B1["series"][41] > 0, "epics of Cycle 1 were Done after its end (the 'more Done since' text)")


@SUITE.test("burnup_with_both_cycles_is_the_chart_without_the_filter_and_a_click_redraws_it")
def _(t: T):
    """Both cycles: the whole release (day 0 to the end, W1 to W12, the dotted Delivery Cycle 1 marker, no plain line). Pick Cycle 2 and Both cycles again: the very same SVG, table and headline come back; a tooltip
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
    t.check(not before["plain"] and ">W12<" in before["svg"] and ">W13<" not in before["svg"] and "release end" in before["svg"], "Both cycles: W1 to W12, no plain-words line")
    ch.js("document.getElementById('bu-link').dispatchEvent(new FocusEvent('focus'))")
    t.check(ch.js("getComputedStyle(document.getElementById('bu-tip')).display") == "block", "the focus opens the day readout")
    ch.js("document.querySelector('#f-dc input[value=\"2\"]').click()")
    time.sleep(0.4)
    mid = ch.js(snap)
    t.check(mid["plain"] and mid["svg"] != before["svg"] and "Delivery Cycle 2 only" in mid["svg"] and ">W1<" not in mid["svg"], "Cycle 2 picked: the axis is Cycle 2's and the plain-words line appears")
    t.check(mid["tip"] in ("none", "gone") and mid["cross"] in ("none", "gone"), f"no stale tooltip or crosshair after the filter changed: {mid['tip']} {mid['cross']}")
    t.check("dc=2" in ch.js("location.hash") and ">W7<" in mid["svg"], "the address names dc=2 and the chart starts at W7")
    ch.js("document.querySelector('#f-dc input[value=\"both\"]').click()")
    time.sleep(0.4)
    after = ch.js(snap)
    t.check(not after["plain"] and after == before, "Both cycles picked again: the SVG, the table, the headline and the fact line are exactly what they were")
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


# --------------------------------------------------------------------------------------------- 2b: the section has no filter of its own; the banner says what it shows
SEC_JS = r"""(() => {
  const sec = document.getElementById('cy-sec'), t = n => n ? n.textContent.replace(/\s+/g, ' ').trim() : null;
  const ink = (el, prop) => { const m = getComputedStyle(el)[prop].match(/[\d.]+/g).map(Number); return m; };
  const lum = c => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const bn = document.getElementById('cy-banner'), sh = document.getElementById('cy-showing'), pt = document.getElementById('cy-point'), btn = document.getElementById('cy-tofilter');
  const bg = ink(bn, 'backgroundColor');
  return {removed: ['g-cy', 'f-cy', 'lbl-cy'].filter(id => document.getElementById(id)), radios: sec.querySelectorAll('input[type=radio]').length, groups: sec.querySelectorAll('[role=radiogroup], select, .periodbar').length,
    ownKey: Object.keys(state.cy), kick: [...document.querySelectorAll('#cy-kpis1 .kpi .k')].map(t), plannedCap: t(document.querySelector('#cy-kpis1 [data-kpi="planned"] .s')), idleCap: t(document.querySelector('#cy-kpis2 [data-kpi="idle"] .s')),
    headsTiles: bn.nextElementSibling === document.getElementById('cy-kpis1'), podScope: t(document.getElementById('cy-podscope')), sub: t(document.getElementById('cy-sub')), role: sh.getAttribute('role'), banner: t(sh), point: t(pt), hidden: bn.hidden, btn: btn ? {tag: btn.tagName, type: btn.type, tab: btn.tabIndex, text: t(btn), disabled: btn.disabled, label: btn.getAttribute('aria-label')} : null,
    contrast: {show: ratio(ink(sh, 'color'), bg), point: ratio(ink(pt, 'color'), bg), link: btn ? ratio(ink(btn, 'color'), bg) : null, edge: ratio(ink(bn, 'borderLeftColor'), [255, 255, 255])},
    ovMeta: t(document.querySelector('#cy-ovtable') && document.querySelector('#cy-ovtable').closest('.cyblock').querySelector('.cymeta')), hash: location.hash, errors: []};
})()"""


def structure_probs(ch, url) -> list[str]:
    """The structural facts of the section, as problems (empty = fine); the tests below assert it and the self-test runs it against the seeded defects."""
    p: list[str] = []
    for h, name, said in (("r=27.1", "Delivery Cycles 1 and 2", "Delivery Cycles 1 and 2 combined"), ("r=27.1&dc=1", "Delivery Cycle 1", "Delivery Cycle 1"), ("r=27.1&dc=2", "Delivery Cycle 2", "Delivery Cycle 2")):
        ch.goto(url + "#" + h)
        kit.wait_ready(ch)
        r = ch.js(SEC_JS)
        if r["removed"] or r["radios"] or r["groups"]:
            p.append(f"#{h}: the removed selector is still in the page: {r['removed']} radios {r['radios']} groups {r['groups']}")
        if "cycle" in " ".join(r["ownKey"]).lower():
            p.append(f"#{h}: the Cycles state still has a cycle key: {r['ownKey']}")
        if not (r["role"] == "status" and not r["hidden"] and r["banner"].startswith(f"Showing {said} \u00b7 ")):
            p.append(f"#{h}: the banner is not a status that says what is shown: {r['role']} {r['banner']!r}")
        if r["kick"]:
            p.append(f"#{h}: the headline tiles repeat the cycle in a kicker, the banner says it once: {r['kick']}")
        if not r["headsTiles"]:
            p.append(f"#{h}: the banner is not directly above the five tiles it heads (a picture of the tiles would not say the cycle)")
        if name not in (r["plannedCap"] or "") or name not in (r["idleCap"] or ""):
            p.append(f"#{h}: the Planned and Idle Pods captions (the figures counted against the cycle) must name it: {r['plannedCap']!r} {r['idleCap']!r}")
        if "The filter bar shows" in (r["sub"] or ""):
            p.append(f"#{h}: the subtitle says a second time what the banner says: {r['sub']!r}")
        if "Only Idle Pods follows the cycle" not in (r["podScope"] or ""):
            p.append(f"#{h}: the Pods block does not say which of its figures ignore the cycle: {r['podScope']!r}")
        if name not in (r["ovMeta"] or ""):
            p.append(f"#{h}: the Projects, Teams and Pods caption does not name the cycle: {r['ovMeta']!r}")
        b = r["btn"]
        if not (b and b["tag"] == "BUTTON" and b["type"] == "button" and b["tab"] == 0 and not b["disabled"] and b["text"] == "Delivery Cycle filter" and "Delivery Cycle filter" in (b["label"] or "")):
            p.append(f"#{h}: the pointer is not a real, keyboard-reachable button: {b}")
        c = r["contrast"]
        if not (c["show"] >= 4.5 and c["point"] >= 4.5 and (c["link"] or 9) >= 4.5 and c["edge"] >= 3):
            p.append(f"#{h}: the banner contrast is below WCAG AA: {c}")
        if "cy=" in r["hash"]:
            p.append(f"#{h}: the address carries the removed key: {r['hash']}")
        if h == "r=27.1" and "Both cycles together" not in (r["point"] or ""):
            p.append(f"#{h}: both cycles are shown and the banner does not say they are counted together: {r['point']!r}")
        if ch.console_errors():
            p.append(f"#{h}: console errors {ch.console_errors()[:2]}")
    # an older link with the removed key: the page is the same as without it, no error, the key does not stay in the address
    for base in ("r=27.1", "r=27.1&dc=1", "r=27.1&p=PMN&dc=2"):
        want = load(ch, url, base, axis=False)
        for old in ("cy=DC1", "cy=DC2", "cy=bogus"):
            h = f"{base}&{old}"
            got = load(ch, url, h, axis=False)
            if got["errors"]:
                p.append(f"#{h}: console errors {got['errors'][:2]}")
            if not all(got[k] == want[k] for k in ("banner", "bannerCycles", "tiles", "after", "cySub", "noDue", "dc")):
                p.append(f"#{h}: the page differs from #{base}: {got['banner']!r} {got['tiles']} vs {want['banner']!r} {want['tiles']}")
            if "cy=" in ch.js("location.hash"):
                p.append(f"#{h}: the removed key stays in the address: {ch.js('location.hash')}")
    ch.goto(url + "#cy=DC2&ct=overview&cs=all")
    kit.wait_ready(ch)
    if not ch.js(SEC_JS)["banner"].startswith("Showing Delivery Cycles 1 and 2"):
        p.append("a link with only the old key does not open on the defaults (both cycles combined)")
    # a redraw that changes nothing must not rewrite the banner (a polite status would be announced again)
    ch.goto(url + "#r=27.1")
    kit.wait_ready(ch)
    ch.js("window.__mut = 0; new MutationObserver(m => { window.__mut += m.length; }).observe(document.getElementById('cy-showing'), {childList: true, characterData: true, subtree: true}); document.querySelector('#f-bpri input').click();")
    time.sleep(0.3)
    if ch.js("window.__mut"):
        p.append("the banner is rewritten by a filter it does not depend on (a screen reader would announce it again)")
    return p


@SUITE.test("the_cycles_section_has_no_filter_of_its_own_and_a_banner_says_which_cycles_it_shows")
def _(t: T):
    data, url, universe = payload("variant")
    probs = structure_probs(ctx.chrome, url)
    t.note("3 selections, the old key in 9 links, a redraw that must not touch the banner")
    for x in probs[:8]:
        t.check(False, x)
    t.check(not probs, f"{len(probs)} problems")


@SUITE.test("the_banner_follows_the_header_filter_when_an_option_is_picked")
def _(t: T):
    data, url, universe = payload("variant")
    ch = ctx.chrome
    ch.goto(url + "#r=27.1")
    kit.wait_ready(ch)
    ch.js("window.__mut = 0; new MutationObserver(m => { window.__mut += m.length; }).observe(document.getElementById('cy-showing'), {childList: true, characterData: true, subtree: true});")
    for box, name, hashpart in (("2", "Delivery Cycle 2", "dc=2"), ("both", "Delivery Cycles 1 and 2 combined", ""), ("1", "Delivery Cycle 1", "dc=1"), ("both", "Delivery Cycles 1 and 2 combined", "")):
        before = ch.js("window.__mut")
        ch.js(f"document.querySelector('#f-dc input[value=\"{box}\"]').click()")
        time.sleep(0.4)
        r = ch.js(SEC_JS)
        t.check(r["banner"].startswith(f"Showing {name} \u00b7 ") and name.replace(" combined", "") in (r["plannedCap"] or ""), f"after picking {box}: the banner and the Planned caption say {name}: {r['banner']!r} {r['plannedCap']!r}")
        t.check(ch.js("window.__mut") > before, f"after picking {box}: the banner text changed in place (a polite status is announced)")
        t.check((hashpart in r["hash"]) if hashpart else "dc=" not in r["hash"], f"the address follows the filter: {r['hash']}")
    t.check(not ch.console_errors(), f"console errors {ch.console_errors()[:2]}")


@SUITE.test("the_banner_pointer_moves_focus_to_the_delivery_cycle_filter_also_on_a_phone")
def _(t: T):
    data, url, universe = payload("variant")
    ch = ctx.chrome
    focus = "(() => { const a = document.activeElement; return {id: a.id, inDc: !!a.closest('#f-dc'), type: a.type, vis: a.getBoundingClientRect().width > 0, bar: document.getElementById('filterbar').className, exp: document.getElementById('f-toggle').getAttribute('aria-expanded')}; })()"
    ch.goto(url + "#r=27.1")
    kit.wait_ready(ch)
    ch.js("document.getElementById('cy-tofilter').click()")
    f = ch.js(focus)
    t.check(f["inDc"] and f["type"] == "radio" and f["vis"], f"the pointer puts the focus on a Delivery Cycle option: {f}")
    try:
        ch.viewport(390, 900)                                                           # (the test page is a fragment with no viewport meta: a mobile emulation would lay it out at 980 px)
        ch.goto(url + "#r=27.1")
        ch.js("location.reload()")                                                      # the filter bar decides at load whether it starts collapsed
        time.sleep(0.5)
        kit.wait_ready(ch)
        before = ch.js(focus)
        t.check("collapsed" in before["bar"], f"the filter bar starts collapsed on a phone: {before}")
        ch.js("document.getElementById('cy-tofilter').click()")
        f = ch.js(focus)
        t.check(f["inDc"] and f["vis"] and "collapsed" not in f["bar"] and f["exp"] == "true", f"on a phone the pointer opens the filters and focuses the Delivery Cycle option: {f}")
        m = ch.js("({sw: document.documentElement.scrollWidth, w: window.innerWidth})")
        t.check(m["sw"] <= m["w"] + 1, f"390 px: the page scrolls sideways {m}")
        r = ch.js("(() => { const b = document.getElementById('cy-banner').getBoundingClientRect(); return {l: b.left, r: b.right, w: window.innerWidth}; })()")
        t.check(r["l"] >= 0 and r["r"] <= r["w"] + 1, f"390 px: the banner is inside the screen {r}")
    finally:
        ch.viewport(1400, 900)


# --------------------------------------------------------------------------------------------- 4: other sections do not read the filter
OTHER_JS = r"""(async () => {
  await document.fonts.ready; updateCore();
  const m = document.querySelector('main').cloneNode(true);
  ['#filters', '#f-live', '#burnup', '#bu-sub', '#bu-plain', '#bu-w6', '#bu-cap', '#bu-data', '#bu-legend', '#cycles', '#cy-body', '#cy-kpis1', '#cy-kpis2', '#cy-pods', '#cy-after', '#cy-sub', '#cy-cap', '#cy-notes', '#cy-banner', '#cy-podlist', '#cy-pods-h'].forEach(s => m.querySelectorAll(s).forEach(n => n.remove()));
  [...m.querySelectorAll('#kpis .kpi')].filter(k => /^(Epics Delivered|Forecast Epics)$/.test(k.querySelector('.l').textContent.trim())).forEach(n => n.remove());      // the two epic-delivery tiles follow the filter (tile_oracle.py); the three others must not
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
JS_FILTERS = r"""(() => { const opts = [...document.querySelectorAll('#f-dc label')].map(l => { const i = l.querySelector('input'); return {text: l.textContent.trim(), value: i.value, type: i.type, on: i.checked, off: i.disabled, cls: l.className, title: l.title, tab: i.tabIndex}; }); return {
  groups: [...document.querySelectorAll('#filterbar .fg, #filterbar .periodbar')].map(g => g.id),
  barText: document.getElementById('filters').textContent.replace(/\s+/g, ' '),
  dcLabel: document.getElementById('lbl-dc') ? document.getElementById('lbl-dc').textContent : null,
  role: document.getElementById('f-dc').getAttribute('role'), labelledby: document.getElementById('f-dc').getAttribute('aria-labelledby'), describedby: document.getElementById('f-dc').getAttribute('aria-describedby'),
  opts, sel: opts.filter(o => o.on).map(o => o.value),
  hideable: document.getElementById('g-dc') ? document.getElementById('g-dc').classList.contains('hideable') : null,
  changed: document.getElementById('g-dc') ? document.getElementById('g-dc').classList.contains('changed') : null,
  status: document.getElementById('f-dc-status') ? document.getElementById('f-dc-status').textContent : null,
  note: document.getElementById('f-dc-note') ? document.getElementById('f-dc-note').textContent : null,
  reset: document.getElementById('f-reset').textContent, live: document.getElementById('f-live').textContent, hash: location.hash, dc: [...state.dc],
  noCommit: !document.getElementById('f-commit') && !document.getElementById('g-commit') && typeof state.commit === 'undefined'
}; })()"""
OPTS = ["both", "1", "2"]
LABELS = {"both": "Both cycles", "1": "Cycle 1", "2": "Cycle 2"}
DC_OF = {"both": ["1", "2"], "1": ["1"], "2": ["2"]}
HASH_OF = {"both": "", "1": "&dc=1", "2": "&dc=2"}


def want_status(window: list, choice: str) -> str:
    """The line under the control, spelled again from the release window: Cycle 1 is W1 to W6 (shorter when the release ends first), Cycle 2 is W7 to the last delivery week (the frame 'Week n of N' counts in)."""
    weeks = round(((day(window[1]) - day(window[0])).days - 7) / 7)
    two = (day(window[1]) - day(window[0])).days > 48
    if choice == "both" and two:
        return f"Showing both cycles: W1 to W{weeks}"
    if choice == "2":
        return f"Showing Cycle 2: W7 to W{weeks}"
    return f"Showing Cycle 1: W1 to W{min(6, weeks)}"


def space_on(ch, selector: str):
    ch.js(f"document.querySelector({json.dumps(selector)}).focus()")
    for ty in ("keyDown", "keyUp"):
        ch.cmd("Input.dispatchKeyEvent", type=ty, key=" ", code="Space", windowsVirtualKeyCode=32, **({"text": " "} if ty == "keyDown" else {}))
    time.sleep(0.3)


def arrow_on(ch, selector: str, key: str):
    ch.js(f"document.querySelector({json.dumps(selector)}).focus()")
    code = {"ArrowRight": 39, "ArrowLeft": 37, "ArrowDown": 40, "ArrowUp": 38}[key]
    for ty in ("keyDown", "keyUp"):
        ch.cmd("Input.dispatchKeyEvent", type=ty, key=key, code=key, windowsVirtualKeyCode=code)
    time.sleep(0.35)


def pick(ch, v: str):
    ch.js(f"document.querySelector('#f-dc input[value=\"{v}\"]').click()")
    time.sleep(0.35)


def header_probs(ch, url: str, short_url: str, data: dict, short_data: dict, full: bool = True) -> list[str]:
    """The header control, end to end: what it is, what its default is, and that ONE click on any option selects exactly that option from any starting state (the failure of the earlier checkbox chips:
    a click on 'Cycle 1' unticked it and showed Cycle 2). Used by the test and by the seeded-defect self-test, which must see every defect here."""
    p: list[str] = []
    win = data["windows"]["27.1"]
    ch.goto(url + "#r=27.1")
    kit.wait_ready(ch)
    f = ch.js(JS_FILTERS)
    if f["role"] != "radiogroup" or any(o["type"] != "radio" for o in f["opts"]):
        p.append(f"the control is not a radio group: role {f['role']!r}, inputs {[o['type'] for o in f['opts']]}")
    if [o["text"] for o in f["opts"]] != [LABELS[v] for v in OPTS]:
        p.append(f"the options are {[o['text'] for o in f['opts']]}, expected Both cycles, Cycle 1, Cycle 2 in that order")
    if f["sel"] != ["both"] or f["dc"] != ["1", "2"] or "dc=" in f["hash"]:
        p.append(f"the default is not Both cycles: selected {f['sel']}, state {f['dc']}, address {f['hash']}")
    if f["status"] != want_status(win, "both"):
        p.append(f"the default status line says {f['status']!r}, expected {want_status(win, 'both')!r}")
    if any(o["off"] for o in f["opts"]):
        p.append(f"an option is disabled on a release with two cycles: {f['opts']}")
    if f["changed"] or f["reset"] != "Reset Filters":
        p.append(f"the default state is marked as a changed filter: {f['changed']} {f['reset']!r}")
    # the failure that was reported: from the default, ONE click on Cycle 1 must show Cycle 1 and nothing else
    pick(ch, "1")
    f = ch.js(JS_FILTERS)
    if f["sel"] != ["1"] or f["dc"] != ["1"] or "dc=1" not in f["hash"]:
        p.append(f"from the default, one click on Cycle 1 gives selected {f['sel']}, state {f['dc']}, address {f['hash']}: it must show Cycle 1 and nothing else")
    r = ch.js(SEC_JS)
    if not (r["banner"] or "").startswith("Showing Delivery Cycle 1 · "):
        p.append(f"from the default, one click on Cycle 1: the Cycles banner says {r['banner']!r}")
    # every option from every starting state: one click selects exactly that option
    for start in OPTS:
        for to in OPTS:
            pick(ch, start)
            if ch.js(JS_FILTERS)["sel"] != [start]:
                p.append(f"could not select {LABELS[start]} as the starting state")
                continue
            pick(ch, to)
            f = ch.js(JS_FILTERS)
            tag = f"{LABELS[start]} then one click on {LABELS[to]}"
            if f["sel"] != [to]:
                p.append(f"{tag}: selected {f['sel']}, expected only {to}")
            if sorted(f["dc"]) != DC_OF[to]:
                p.append(f"{tag}: the page state is {f['dc']}, expected {DC_OF[to]}")
            if ("dc=" in f["hash"]) != (to != "both") or (to != "both" and f"dc={to}" not in f["hash"]):
                p.append(f"{tag}: the address is {f['hash']}")
            if f["status"] != want_status(win, to):
                p.append(f"{tag}: the status line says {f['status']!r}, expected {want_status(win, to)!r}")
            if (f["note"] or "") != ("" if to == "both" else "Delivery chart, Cycles and 2 tiles only"):
                p.append(f"{tag}: the scope note says {f['note']!r}")
            if f["changed"] != (to != "both") or f["reset"] != ("Reset Filters" if to == "both" else "Reset Filters (1)"):
                p.append(f"{tag}: the changed-filter marker is {f['changed']} and the button says {f['reset']!r}")
            if not full and (start, to) not in (("both", "2"), ("2", "both"), ("1", "1")):
                continue
            r = ch.js(PROBE)
            want_banner = {"both": "Showing Delivery Cycles 1 and 2 combined · ", "1": "Showing Delivery Cycle 1 · ", "2": "Showing Delivery Cycle 2 · "}[to]
            if not (r["banner"] or "").startswith(want_banner):
                p.append(f"{tag}: the Cycles banner says {r['banner']!r}")
            only = f"Delivery Cycle {to} only"
            if (to != "both") != (only in (r["svgText"] or "")) or (to == "both" and "only" in (r["svgAria"] or "").split("Delivery Cycle")[-1][:14]):
                p.append(f"{tag}: the burnup does not follow ({r['svgAria']!r})")
            kick = ch.js("(document.querySelector('#kpis .kpi .k') || {textContent: ''}).textContent.replace(/\\s+/g, ' ').trim()")
            if kick != ("Release 27.1" if to == "both" else f"Release 27.1 · Delivery Cycle {to}"):
                p.append(f"{tag}: the Epics Delivered tile kicker says {kick!r}")
    # a cycle that is already selected: a second click changes nothing
    pick(ch, "2")
    pick(ch, "2")
    f = ch.js(JS_FILTERS)
    if f["sel"] != ["2"] or f["dc"] != ["2"]:
        p.append(f"a second click on the selected Cycle 2 changed the state: {f['sel']} {f['dc']}")
    # older links (dc=1, dc=2) open the matching option; the address after loading is the same
    for h, want in (("r=27.1&dc=1", "1"), ("r=27.1&dc=2", "2"), ("r=27.1&dc=1%7C2", "both"), ("r=27.1&dc=3", "both"), ("r=27.1&dc=", "both")):
        ch.goto(url + "#" + h)
        kit.wait_ready(ch)
        f = ch.js(JS_FILTERS)
        if f["sel"] != [want] or f["status"] != want_status(win, want) or (("dc=" in f["hash"]) != (want != "both")):
            p.append(f"#{h}: selected {f['sel']} (expected {want}), status {f['status']!r}, address {f['hash']}")
    # a release with one cycle: Both cycles and Cycle 2 are disabled with the reason, Cycle 1 is selected, a click on a disabled option does nothing
    ch.goto(short_url + "#r=26.4")
    kit.wait_ready(ch)
    f = ch.js(JS_FILTERS)
    swin = short_data["windows"]["26.4"]
    if [o["off"] for o in f["opts"]] != [True, False, True] or f["sel"] != ["1"]:
        p.append(f"a release with one cycle: disabled {[o['off'] for o in f['opts']]}, selected {f['sel']}; expected Both cycles and Cycle 2 disabled, Cycle 1 selected")
    if f["status"] != want_status(swin, "both") or "No Cycle 2" not in (f["note"] or ""):
        p.append(f"a release with one cycle: status {f['status']!r} note {f['note']!r}")
    if not all(o["title"].startswith("26.4 ends by the end of W6") for o in f["opts"] if o["off"]):
        p.append(f"a disabled option does not say why: {[o['title'] for o in f['opts']]}")
    if f["changed"]:
        p.append("a release with one cycle marks the Delivery Cycle group as a changed filter")
    ch.js("document.querySelector('#f-dc input[value=\"2\"]').click(); document.querySelector('#f-dc input[value=\"both\"]').click();")
    time.sleep(0.3)
    f = ch.js(JS_FILTERS)
    if f["sel"] != ["1"] or f["dc"] != ["1", "2"] or "dc=" in f["hash"]:
        p.append(f"a click on a disabled option changed something: selected {f['sel']}, state {f['dc']}, address {f['hash']}")
    return p


@SUITE.test("header_has_the_delivery_cycle_filter_and_no_commitment_type_filter")
def _(t: T):
    data, url, _u = payload("variant")
    ch = ctx.chrome
    ch.goto(url + "#r=27.1")
    kit.wait_ready(ch)
    f = ch.js(JS_FILTERS)
    t.check(f["dcLabel"] == "Delivery Cycle", f"the group is labelled Delivery Cycle: {f['dcLabel']!r}")
    t.check(f["role"] == "radiogroup" and f["labelledby"] == "lbl-dc" and "f-dc-status" in f["describedby"] and "f-dc-note" in f["describedby"], f"a radio group named by its label and described by the status line and the note: {f['role']} {f['labelledby']} {f['describedby']}")
    t.check([(o["text"], o["value"], o["type"]) for o in f["opts"]] == [("Both cycles", "both", "radio"), ("Cycle 1", "1", "radio"), ("Cycle 2", "2", "radio")] and f["sel"] == ["both"] and not any(o["off"] for o in f["opts"]), f"three options in the order Both cycles, Cycle 1, Cycle 2; Both cycles selected by default: {f['opts']}")
    t.check(f["noCommit"] and "Commitment Type" not in f["barText"], f"no Commitment Type control, text or state in the header: {f['barText'][:200]!r}")
    t.check(f["groups"].index("g-dc") == f["groups"].index("teamsel") + 1 and f["hideable"], f"the group sits where Commitment Type was, after Teams, and hides on narrow screens: {f['groups']}")
    t.check(f["status"] == "Showing both cycles: W1 to W12" and f["note"] == "" and not f["changed"] and f["reset"] == "Reset Filters", f"the status line says what is shown; with both cycles nothing is narrowed, so there is no scope note; nothing is marked changed: {f['status']!r} {f['note']!r}")
    sib = ch.js("(() => { const g = id => [...document.querySelectorAll('#' + id + ' label')].map(l => l.className.includes('chip')); const bg = id => { const l = document.querySelector('#' + id + ' label.on'); return l ? getComputedStyle(l).backgroundColor : null; }; return {dc: bg('f-dc'), ax: bg('f-ax'), gran: bg('f-gran'), proj: getComputedStyle(document.querySelector('#f-projects .chip.on')).backgroundColor, chips: g('f-dc')}; })()")
    t.check(all(sib["chips"]) and sib["dc"] == sib["gran"] == sib["proj"] and sib["dc"] not in (None, "rgb(255, 255, 255)"), f"the selected option is filled like the selected option of the other segmented controls: {sib}")
    t.check(not ch.console_errors(), f"no console errors: {ch.console_errors()[:2]}")


@SUITE.test("header_one_click_selects_exactly_that_option_from_every_state")
def _(t: T):
    """The reported failure: with the two checkbox chips, a click on 'Cycle 1' UNTICKED it and the page showed Cycle 2 only. The control is a choice of one now: from every starting state one click on
    an option selects exactly that option (state, address, status line, changed marker, Cycles banner, burnup, tile kicker), a second click on it changes nothing, an older dc= link opens the matching option,
    and on a release with one cycle the options it cannot offer are disabled with their reason."""
    data, url, universe = payload("variant")
    sdata, surl, _su = payload("short")
    probs = header_probs(ctx.chrome, url, surl, data, sdata)
    for x in probs[:10]:
        t.check(False, x)
    t.check(not probs, f"{len(probs)} problems")
    t.check(not ctx.chrome.console_errors(), f"console errors {ctx.chrome.console_errors()[:2]}")


@SUITE.test("header_status_line_per_state_and_the_announcement")
def _(t: T):
    data, url, universe = payload("variant")
    ch = ctx.chrome
    win = data["windows"]["27.1"]
    ch.goto(url + "#r=27.1")
    kit.wait_ready(ch)
    for v, say in (("1", "Showing Delivery Cycle 1 only"), ("2", "Showing Delivery Cycle 2 only"), ("both", "Showing every delivery cycle")):
        pick(ch, v)
        f = ch.js(JS_FILTERS)
        t.check(f["status"] == want_status(win, v), f"{LABELS[v]}: the status line says {f['status']!r}, expected {want_status(win, v)!r}")
        t.check(f["live"].startswith(say), f"{LABELS[v]}: a polite announcement for a screen reader: {f['live']!r}")
        t.check(ch.js("getComputedStyle(document.getElementById('f-dc-status')).display") != "none", f"{LABELS[v]}: the status line is visible")
        t.check((f["note"] or "") == ("" if v == "both" else "Delivery chart, Cycles and 2 tiles only"), f"{LABELS[v]}: the scope note (what one cycle changes) shows while a single cycle is selected: {f['note']!r}")
        t.check(ch.js("getComputedStyle(document.getElementById('f-dc-note')).display === 'none'") == (v == "both"), f"{LABELS[v]}: the empty note takes no room")
    # the status line is what the page shows, so it follows a release change too (this fixture's 27.2 has the same 12 weeks)
    ch.js("(() => { const s = document.getElementById('f-release'); s.value = '27.2'; s.dispatchEvent(new Event('change', {bubbles: true})); })()")
    time.sleep(0.4)
    pick(ch, "2")
    f = ch.js(JS_FILTERS)
    t.check(f["status"] == want_status(data["windows"]["27.2"], "2"), f"27.2, Cycle 2: {f['status']!r}")


@SUITE.test("header_hash_round_trip_and_an_old_c_link_is_ignored")
def _(t: T):
    data, url, universe = payload("variant")
    ch = ctx.chrome
    for h, want in (("r=27.1&dc=1", "1"), ("r=27.1&dc=2", "2"), ("r=27.1&dc=1%7C2", "both"), ("r=27.1&dc=3", "both"), ("r=27.1&dc=", "both")):
        ch.goto(url + "#" + h)
        kit.wait_ready(ch)
        f = ch.js(JS_FILTERS)
        t.check(f["sel"] == [want] and sorted(f["dc"]) == DC_OF[want], f"#{h}: option {f['sel']}, state {f['dc']}")
        t.check(("dc=" in f["hash"]) == (want != "both") and (want == "both" or f"dc={want}" in f["hash"]), f"#{h}: the address after loading is {f['hash']}")
    # clicks write the address: Cycle 1 -> dc=1, Cycle 2 -> dc=2, Both cycles -> no dc; the address opens the same option again
    ch.goto(url + "#r=27.1")
    kit.wait_ready(ch)
    for v in ("1", "2", "both"):
        pick(ch, v)
        f = ch.js(JS_FILTERS)
        t.check(f["sel"] == [v] and (("dc=" + v) in f["hash"] if v != "both" else "dc=" not in f["hash"]), f"{LABELS[v]} picked: the address is {f['hash']}")
        if v != "both":
            h = f["hash"].lstrip("#")
            ch.goto(url + "#" + h)
            kit.wait_ready(ch)
            t.check(ch.js(JS_FILTERS)["sel"] == [v], f"{LABELS[v]}: the address {h} opens the same option again")
            ch.goto(url + "#r=27.1")
            kit.wait_ready(ch)
            pick(ch, v)
    # Reset Filters brings Both cycles back
    pick(ch, "2")
    t.check(ch.js(JS_FILTERS)["reset"] == "Reset Filters (1)", "Cycle 2 counts as one applied filter")
    ch.js("document.getElementById('f-reset').click()")
    time.sleep(0.4)
    f = ch.js(JS_FILTERS)
    t.check(f["sel"] == ["both"] and sorted(f["dc"]) == ["1", "2"] and "dc=" not in f["hash"] and not f["changed"] and f["status"] == "Showing both cycles: W1 to W12", f"Reset Filters selects Both cycles again: {f['sel']} {f['hash']} {f['status']!r}")
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
    """A radio group like Accessibility Bugs and Group CFB By: one Tab stop (the selected option), the arrow keys move AND select (wrapping), Space selects the focused option, the focus stays in the group."""
    data, url, universe = payload("variant")
    ch = ctx.chrome
    ch.goto(url + "#r=27.1")
    kit.wait_ready(ch)
    f = ch.js(JS_FILTERS)
    t.check(len([o for o in f["opts"] if o["tab"] >= 0]) >= 1 and ch.js("[...document.querySelectorAll('#f-dc input')].every(i => i.tabIndex >= 0)"), "the options are in the tab order (the browser's radio group makes the selected one the single Tab stop)")
    arrow_on(ch, '#f-dc input[value="both"]', "ArrowRight")
    f = ch.js(JS_FILTERS)
    t.check(f["sel"] == ["1"] and f["dc"] == ["1"] and "dc=1" in f["hash"], f"ArrowRight from Both cycles selects Cycle 1: {f['sel']} {f['hash']}")
    t.check(ch.js("document.activeElement && document.activeElement.closest('#f-dc') !== null && document.activeElement.value") == "1", "the focus moves with the selection and stays in the Delivery Cycle group")
    arrow_on(ch, '#f-dc input[value="1"]', "ArrowDown")
    t.check(ch.js(JS_FILTERS)["sel"] == ["2"], "ArrowDown selects the next option, Cycle 2")
    arrow_on(ch, '#f-dc input[value="2"]', "ArrowRight")
    t.check(ch.js(JS_FILTERS)["sel"] == ["both"], "ArrowRight on the last option wraps to Both cycles")
    arrow_on(ch, '#f-dc input[value="both"]', "ArrowLeft")
    t.check(ch.js(JS_FILTERS)["sel"] == ["2"], "ArrowLeft on the first option wraps to Cycle 2")
    space_on(ch, '#f-dc input[value="1"]')
    f = ch.js(JS_FILTERS)
    t.check(f["sel"] == ["1"] and f["dc"] == ["1"], f"Space on Cycle 1 selects it: {f['sel']}")
    space_on(ch, '#f-dc input[value="1"]')
    t.check(ch.js(JS_FILTERS)["sel"] == ["1"], "Space on the selected option keeps it selected (never a toggle)")
    vis = ch.js("(() => { const l = document.querySelector('#f-dc input[value=\"2\"]').parentElement; l.querySelector('input').focus(); return getComputedStyle(l).outlineStyle; })()")
    t.check(bool(ch.js("CSS.supports('selector(:has(*))')")), "the browser can draw the focus ring on the label (:has)")
    t.check(bool(ch.js("[...document.styleSheets].some(s => [...s.cssRules].some(r => r.selectorText && r.selectorText.includes('.chip:has(input:focus-visible)')))")), f"the chip draws a focus ring when its radio has the keyboard focus (outline {vis})")
    # a release with one cycle: the arrow keys skip the disabled options
    sdata, surl, _su = payload("short")
    ch.goto(surl + "#r=26.4")
    kit.wait_ready(ch)
    arrow_on(ch, '#f-dc input[value="1"]', "ArrowRight")
    f = ch.js(JS_FILTERS)
    t.check(f["sel"] == ["1"] and f["dc"] == ["1", "2"], f"on a release with one cycle the arrow keys stay on Cycle 1: {f['sel']} {f['dc']}")
    t.check(not ch.console_errors(), f"console errors {ch.console_errors()[:2]}")


@SUITE.test("header_target_size_and_no_sideways_scroll_at_320_390_800_1100_1400_px")
def _(t: T):
    data, url, universe = payload("variant")
    ch = ctx.chrome
    try:
        for w in (320, 390, 800, 1100, 1400):
            for h in ("r=27.1", "r=27.1&dc=2"):
                ch.viewport(w, 900)                                                 # (not a mobile emulation: the test page is a fragment with no viewport meta, which a mobile emulation would lay out at 980 px)
                ch.goto(url + "#" + h)
                kit.wait_ready(ch)
                ch.js("location.reload()")                                          # the filter bar decides at load whether it starts collapsed
                time.sleep(0.4)
                kit.wait_ready(ch)
                ch.js("(() => { const b = document.getElementById('f-toggle'); if (b && getComputedStyle(b).display !== 'none' && b.getAttribute('aria-expanded') === 'false') b.click(); })()")
                time.sleep(0.2)
                m = ch.js("""(() => { const r = x => x.getBoundingClientRect(), g = r(document.getElementById('g-dc')), f = r(document.getElementById('f-dc')), ls = [...document.querySelectorAll('#f-dc label')].map(r);
                  return {sw: document.documentElement.scrollWidth, w: window.innerWidth, right: Math.round(g.right), left: Math.round(g.left), vis: g.width > 0, bw: document.body.scrollWidth, minH: Math.round(Math.min(...ls.map(x => x.height))), minW: Math.round(Math.min(...ls.map(x => x.width))),
                    inside: ls.every(x => x.left >= f.left - 1 && x.right <= f.right + 1), tops: new Set(ls.map(x => Math.round(x.top))).size, clipped: [...document.querySelectorAll('#f-dc label')].some(l => l.scrollWidth > l.clientWidth + 1)}; })()""")
                t.check(m["sw"] <= m["w"] + 1 and m["bw"] <= m["w"] + 1, f"{w} px #{h}: the page scrolls sideways ({m})")
                t.check(m["vis"] and m["right"] <= m["w"] + 1 and m["left"] >= -1, f"{w} px #{h}: the Delivery Cycle group leaves the viewport ({m})")
                t.check(m["minH"] >= (44 if w <= 760 else 32) and m["minW"] >= 44 and not m["clipped"], f"{w} px #{h}: every option is at least {44 if w <= 760 else 32} px tall and 44 px wide and none is clipped ({m})")
                if w >= 390:
                    t.check(m["tops"] == 1, f"{w} px #{h}: the three options sit in one row ({m})")
                t.check(not ch.console_errors(), f"{w} px: console errors {ch.console_errors()[:2]}")
    finally:
        ch.viewport(1400, 900)


@SUITE.test("a_release_with_only_cycle_1_disables_both_and_cycle_2_and_falls_back")
def _(t: T):
    data, url, universe = payload("short")
    ch = ctx.chrome
    ch.goto(url + "#r=26.4")
    kit.wait_ready(ch)
    f = ch.js(JS_FILTERS)
    t.check([o["off"] for o in f["opts"]] == [True, False, True] and f["sel"] == ["1"], f"Both cycles and Cycle 2 are disabled, Cycle 1 is selected: {f['opts']}")
    t.check("No Cycle 2" in f["note"] and ch.js("document.querySelector('#f-dc label.dis').title").startswith("26.4 ends by the end of W6"), f"the reason is in plain words: {f['note']!r}")
    t.check(f["status"] == want_status(data["windows"]["26.4"], "1"), f"the status line shows the one cycle: {f['status']!r}")
    t.check(not f["changed"] and "Cycle" not in f["note"].replace("No Cycle 2", ""), f"with the only cycle shown the group is not marked as a filter: {f['changed']} {f['note']!r}")
    r_default = load(ch, url, "r=26.4")
    r_stored2 = load(ch, url, "r=26.4&dc=2")                        # a stored dc naming a cycle the release does not have falls back to the cycles it has
    r_stored1 = load(ch, url, "r=26.4&dc=1")
    for k in ("sub", "rows", "w6", "cap", "banner", "tiles"):
        t.check(r_stored2[k] == r_default[k] == r_stored1[k], f"26.4 with dc=2 or dc=1 equals the default on {k}")
    t.check(r_default["banner"].startswith("Showing Delivery Cycle 1 · ") and "no Delivery Cycle 2" in r_default["point"], f"the Cycles banner shows Delivery Cycle 1 and says there is no Cycle 2: {r_default['banner']!r} {r_default['point']!r}")
    probs: list[str] = []
    for h in ("r=26.4", "r=26.4&dc=2", "r=26.4&dc=1", "r=27.1&dc=2"):
        check_view(probs, data, universe, h, load(ch, url, h), "short")
    t.check(not probs, "; ".join(probs[:3]))
    # the same release in the long payload does have two cycles (the fixture changed only the window)
    r_long = load(ch, payload("variant")[1], "r=26.4")
    t.check([c["off"] for c in r_long["dcChips"]] == [False, False, False], "the unchanged release has every option")
    ch.goto(url + "#r=26.4&dc=2")
    kit.wait_ready(ch)
    f = ch.js(JS_FILTERS)
    t.check(f["sel"] == ["1"] and f["dc"] == ["2"], f"a stored dc=2 on a release with one cycle shows Cycle 1 (the cycles it has): {f['sel']} {f['dc']}")
    ch.js("document.querySelector('#f-dc input[value=\"1\"]').click()")
    time.sleep(0.3)
    t.check(ch.js(JS_FILTERS)["sel"] == ["1"], "a click on the only cycle keeps it selected")
    # moving to a release that has two cycles brings the stored choice back
    ch.js("(() => { const s = document.getElementById('f-release'); s.value = '27.1'; s.dispatchEvent(new Event('change', {bubbles: true})); })()")
    time.sleep(0.4)
    f = ch.js(JS_FILTERS)
    t.check(f["dc"] == ["2"] and f["sel"] == ["2"], f"the stored dc=2 applies again on a release with two cycles: {f['dc']} {f['sel']}")


# --------------------------------------------------------------------------------------------- 5: seeded defects
# the epics of the ticked cycles by their planned date (the rule the burnup no longer applies): what a defect that narrows the burnup's population would use
KEEP_JS = 'e => { const p = plannedDue(e), w = DATA.windows[rel], m = !p ? null : p <= cyAdd(w[0], 48) ? "1" : p <= w[1] ? "2" : null; return dc.all || (m !== null && dc.shown.includes(m)); }'
MUTANTS = [
    ("Cycles ignores the filter", "dcs = dcState(), shown = cycles.filter(x => dcs.shown.includes(x.id.slice(2)));", "dcs = dcState(), shown = cycles;"),
    ("After Release End is shown with one cycle", "const after = M.dcAll ? M.epics.filter(", "const after = true ? M.epics.filter("),
    ("the undated list is shown with one cycle", "noDue: dcs.all ? eps.filter(", "noDue: true ? eps.filter("),
    ("Delivery Cycle 1 ends a day early in the Cycles section", "const w6 = cyAdd(w[0], 48);", "const w6 = cyAdd(w[0], 47);"),
    ("both cycles are counted as Cycle 1 only", "end: sel[sel.length - 1].end,", "end: sel[0].end,"),
    ("the Cycle 2 epics are dropped from the combined view", "e.due >= cc.start && e.due <= cc.end);", "e.due >= cc.start && e.due <= (cc.multi ? cc.set[0].end : cc.end));"),
    ("the banner shows the wrong cycle", "const head = `Showing ${c.name}", "const head = `Showing ${c.first}"),
    ("the banner does not say the cycles are counted together", "${c.multi ? \"Both cycles together: an epic planned in either counts once. \" : \"Epics planned outside it are not counted. \"}", ""),
    ("the banner line a picture shows does not say 'combined'", "`Showing ${c.name}${c.multi ? \" combined\" : \"\"}`", "`Showing ${c.name}`"),
    ("the Planned tile repeats the cycle in a kicker", "planned: ({s, c, g}) => ({c: \"cy\", v:", "planned: ({s, c, g}) => ({c: \"cy\", k: esc(c.name), v:"),
    ("the Planned caption lost the cycle", "l: \"Planned\", s: `epics planned in ${c.name}`})", "l: \"Planned\", s: `epics planned`})"),
    ("the banner is moved away from the tiles it heads", '<div class="kpis five" id="cy-kpis1"></div>\n    <div class="sub" id="cy-after"></div>', '<div class="sub" id="cy-after"></div>\n    <div class="kpis five" id="cy-kpis1"></div>'),
    ("the subtitle says a second time what the banner says", "Delivery Cycle 2: W7 to the release end.\";\n  const planned", "Delivery Cycle 2: W7 to the release end. The filter bar shows one cycle.\";\n  const planned"),
    ("the Pods block does not say which figures ignore the cycle", "These count the whole release in every cycle. Only Idle Pods follows the cycle shown above.", "Pods."),
    ("the banner pointer has no name of its own", " aria-label=\"Go to the Delivery Cycle filter\"", ""),
    ("the removed selector is back", '<div class="cybanner" id="cy-banner">', '<div class="periodbar" id="g-cy"><div class="chips seg" id="f-cy" role="radiogroup"><input type="radio" name="f-cy"></div></div><div class="cybanner" id="cy-banner">'),
    ("the removed key is read again", "// the section's own cycle (cy=DC1 or DC2, an older link) is not read:", "if (/^DC[12]$/.test(h.get(\"cy\") || \"\")) state.dc = new Set([h.get(\"cy\").slice(2)]); //"),
    ("the banner is rewritten at every redraw", "if (host.textContent !== txt) host.innerHTML", "if (true) host.innerHTML"),
    # the burnup: a time window of the whole release
    ("the burnup Done is narrowed to the epics planned in the cycle", "const dlist = doneScope(rel);", "const dlist = doneScope(rel).filter(" + KEEP_JS + ");"),
    ("the burnup scope is narrowed to the epics planned in the cycle", "const target = list, baseScope = TB.N, J = jira;", "const target = list.filter(" + KEEP_JS + "), baseScope = TB.members.filter(" + KEEP_JS + ").length, J = jira;"),
    ("the burnup axis ignores the filter", "const DM = win ? dcDomain(rel, dc) : null,", "const DM = win ? dcDomain(rel, {all: true, shown: dc.shown}) : null,"),
    ("Cycle 2 Done restarts at zero", "let d = `M${x(ds)},${y(done[kind === \"c2\" ? ds - 1 : 0])}`;", "let d = `M${x(ds)},${y(kind === \"c2\" ? 0 : done[0])}`;"),
    ("the Done line is drawn before W7", "if (!before) {\n    g += `<path d=", "if (true) {\n    g += `<path d="),
    ("the Done label is drawn before W7", "if (!before) {\n    g += `<text x=\"${tx}\"", "if (true) {\n    g += `<text x=\"${tx}\""),
    ("the Cycle 1 even pace does not go through the end state (readout)", "kind === \"c1\" ? (de ? nP * d / de : 0)", "kind === \"c1\" ? (de ? N * d / de : 0)"),
    ("the Cycle 1 even-pace line is drawn to the release scope", "y2=\"${y(kind === \"c1\" ? nP : N)}\"", "y2=\"${y(N)}\""),
    ("the Cycle 2 pace starts at the scope minus N (rejected)", "Math.min(before ? nP : w6Done, N)", "Math.max(0, N - nP)"),
    ("the Cycle 2 pace ignores the end of W6 (planned start after W6 has ended)", "Math.min(before ? nP : w6Done, N)", "Math.min(nP, N)"),
    ("the Cycle 2 pace starts at Done now before W7", "Math.min(before ? nP : w6Done, N)", "Math.min(before ? done[snapD] : w6Done, N)"),
    ("the planned start label is missing before W6 ends", "if (before) g += `<text pointer-events=\"none\" x=\"${x(ds) + 8}\"", "if (false) g += `<text pointer-events=\"none\" x=\"${x(ds) + 8}\""),
    ("the Delivery Cycle 1 view shows the release scope", "if (kind !== \"c1\") {  ", "if (true) {  "),
    ("the Delivery Cycle 1 view keeps the scope hover", "if (kind !== \"c1\") g += ga(", "if (true) g += ga("),
    ("the dotted marker is missing at the end of the Delivery Cycle 1 window", "const w6Mark = W6 && kind !== \"c2\";", "const w6Mark = W6 && kind === \"all\";"),
    ("the dotted marker is drawn in Delivery Cycle 2", "const w6Mark = W6 && kind !== \"c2\";", "const w6Mark = W6;"),
    ("the snapshot marker is drawn outside the window", "const inWin = kind === \"c2\" ? snapRaw >= ds && snapRaw < de : snapD < de;", "const inWin = snapD < D;"),
    ("Delivery Cycle 2 is treated as started before W7", "const before = kind === \"c2\" && snapRaw < ds;", "const before = false;"),
    ("the headline does not stop at the end of Delivery Cycle 1", "const shownDone = closed ? done[de] : dn.length, since = closed ? done[snapD] - done[de] : 0;", "const shownDone = dn.length, since = 0;"),
    ("the Done link of a closed Delivery Cycle 1 is unbounded", "...(closed ? {extra: `resolutiondate < \"${iso(w1 + (de + 1) * DAY)}\"`} : {})", ""),
    ("the keyboard leaves the window", "kd = ev.key === \"Home\" ? ds : de; dayAt(kd);", "kd = ev.key === \"Home\" ? 0 : D; dayAt(kd);"),
    ("the plain-words line is shown with both cycles", "if (dc.all || !win) { if (pl0) pl0.remove(); }", "if (!win) { if (pl0) pl0.remove(); }"),
    ("the last day of a narrowed axis has no tick", "const endTick = kind !== \"all\" && (de - ds) % tickEvery !== 0;", "const endTick = false;"),
    ("the Cycle 1 end marker says release end", "`end of ${cy1} ${shortDate(w1 + de * DAY)}`", "`release end ${shortDate(end)}`"),
    ("the even-pace readout ignores the window", "const pace = Math.round(paceAt(d));", "const pace = Math.round(D ? N * d / D : 0);"),
]
STRUCTURAL = {"the removed selector is back", "the removed key is read again", "the banner is rewritten at every redraw", "the banner does not say the cycles are counted together", "the banner line a picture shows does not say 'combined'",
              "the Planned tile repeats the cycle in a kicker", "the Planned caption lost the cycle", "the banner is moved away from the tiles it heads", "the subtitle says a second time what the banner says",
              "the Pods block does not say which figures ignore the cycle", "the banner pointer has no name of its own"}      # caught by structure_probs, not by the numbers
MUTANT_VIEWS = [("variant", "r=27.1&dc=1"), ("variant", "r=27.1&dc=2"), ("variant", "r=27.1"), ("asof_pre", "r=27.1&dc=2"), ("asof_w7", "r=27.1&dc=1"), ("asof_w7", "r=27.1&dc=2"), ("asof_w7", "r=27.1")]


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
        if what in STRUCTURAL:
            probs += structure_probs(ch, pages["variant"])
        t.check(bool(probs), f"the oracle did not notice the seeded defect: {what}")


# the header control: every way it could go back to the failure that was reported (a click on an option toggles it, so one click on Cycle 1 shows Cycle 2) or lose what it promises
HEADER_MUTANTS = [
    ("a click on an option toggles it instead of selecting it", "state.dc = new Set(e.target.value === \"both\" ? DC_IDS : [e.target.value]);",
     "{ const v = e.target.value; if (v === \"both\") state.dc = new Set(DC_IDS); else { state.dc.has(v) ? state.dc.delete(v) : state.dc.add(v); if (!state.dc.size) state.dc = new Set(DC_IDS); } }"),
    ("a click on a cycle adds it to the ones shown instead of replacing them", "state.dc = new Set(e.target.value === \"both\" ? DC_IDS : [e.target.value]);",
     "state.dc = e.target.value === \"both\" ? new Set(DC_IDS) : new Set([...state.dc, e.target.value]);"),
    ("Both cycles is not the default", "dc: new Set(DC_IDS), ax:", "dc: new Set([\"1\"]), ax:"),
    ("the status line ends every cycle at W6", "hi = shown.includes(\"2\") ? W : Math.min(6, W);", "hi = Math.min(6, W);"),
    ("the status line names the wrong cycle", "`Cycle ${shown[0]}`}: W${lo}", "`Cycle ${3 - shown[0]}`}: W${lo}"),
    ("the status line is empty", "st.textContent = dcStatus(d);", "st.textContent = \"\";"),
    ("the address does not carry the cycle", "if (state.dc.size !== DC_IDS.length) h.set(\"dc\"", "if (false) h.set(\"dc\""),
    ("an older dc= link is not read", "{ const d = (list(\"dc\") || []).filter(x => DC_IDS.includes(x)); if (d.length) state.dc = new Set(d); }", ""),
    ("a disabled option can be clicked", "i.disabled = !has;", "i.disabled = false;"),
    ("a disabled option does not say why", "i.parentElement.title = has ? \"\" :", "i.parentElement.title = true ? \"\" :"),
    ("the options are in the wrong order", "const DC_OPTS = [[\"both\", \"Both cycles\"], [\"1\", \"Cycle 1\"], [\"2\", \"Cycle 2\"]];", "const DC_OPTS = [[\"1\", \"Cycle 1\"], [\"2\", \"Cycle 2\"], [\"both\", \"Both cycles\"]];"),
    ("the control is a group of checkboxes again", "<input type=\"radio\" name=\"f-dc\" value=\"${v}\">", "<input type=\"checkbox\" name=\"f-dc\" value=\"${v}\">"),
    ("the group is not a radio group", "role=\"radiogroup\" aria-labelledby=\"lbl-dc\"", "role=\"group\" aria-labelledby=\"lbl-dc\""),
    ("the selected option does not follow the state", "i.checked = i.value === pick;", "i.checked = i.value === \"both\";"),
    ("a single cycle is not marked as a changed filter", "dc: !dcState().all,", "dc: false,"),
    ("the scope note is missing while one cycle is selected", "d.all ? \"\" : \"Delivery chart, Cycles and 2 tiles only\"", "\"\""),
    ("a release with one cycle keeps Both cycles enabled", "const dcHas = (d, v) => v === \"both\" ? d.has2 : d.ids.includes(v);", "const dcHas = (d, v) => v === \"both\" ? true : d.ids.includes(v);"),
]


@SUITE.test("selftest_header_oracle_catches_seeded_defects")
def _(t: T):
    src = ctx.template.read_text(encoding="utf-8")
    ch = ctx.chrome
    data, _u, _universe = payload("variant")
    sdata, _su, _suniverse = payload("short")
    for i, (what, old, new) in enumerate(HEADER_MUTANTS):
        if src.count(old) != 1:
            raise kit.Skip(f"the seeding anchor for '{what}' is not in this template exactly once (found {src.count(old)})")
        tpl = _write_tmp(src.replace(old, new, 1))
        urls = {}
        for kind, d in (("variant", data), ("short", sdata)):
            f = Path(ctx.dir) / f"dcf_hmutant_{i}_{kind}.html"
            f.write_text(MS.render_page(d, tpl), encoding="utf-8")
            urls[kind] = "file://" + str(f)
        probs = header_probs(ch, urls["variant"], urls["short"], data, sdata, full=False)
        t.check(bool(probs), f"the header oracle did not notice the seeded defect: {what}")


def _write_tmp(text: str) -> Path:
    p = Path(ctx.dir) / f"template_mutant_{abs(hash(text)) % 10**8}.html"
    p.write_text(text, encoding="utf-8")
    return p


if __name__ == "__main__":
    sys.exit(kit.cli(SUITE, __doc__))
