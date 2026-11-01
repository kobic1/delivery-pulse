#!/usr/bin/env python3
"""Headline tiles oracle: EDCT Days and Epics by AI cover the LAST 30 DAYS (not the calendar month to date), and the Jira links open exactly the epics counted.

The window is the 30 days ending on the as-of day, inclusive: [as-of minus 29 days, as-of plus 1 day). The comparison under Epics by AI is the 30 days before it
([as-of minus 59 days, as-of minus 29 days)). For several as-of days (the 1st of a month, a window across a month boundary, across a year boundary, across a leap day) and several
filter states, this suite

  1. recounts both tiles independently, in Python, from the baked epics (Done, resolved on a day of the window, Projects and Teams filters, Maintenance out of EDCT, Maintenance and
     SOW out of the AI figures, AI-implemented only for EDCT) and compares the printed values, the sub lines, the hover texts, the comparison line and the labels;
  2. reads the bounds out of every tile link (resolutiondate >= "<from>" AND resolutiondate < "<to>"), evaluates each link query with the repo's JQL evaluator (jql_eval.py) over
     all baked epics and requires exactly the epics the recount found (the EDCT link: the same epics, ignoring those that have no EDCT yet, which Jira cannot search for);
  3. checks that the charts of Efficiency and AI Adoption did not move (they stay on calendar periods) and that nothing in the tiles says "to Date";
  4. seeds three defects into a copy of the template (calendar month instead of 30 days, a window off by one day, a previous window that overlaps) and requires the same checks to fail.

  5. the EDCT average has no 5-epic minimum (EDCT_MIN_N = 1): the Efficiency chart, its head line, hover text and table, and the EDCT Days tile are recounted on fictitious teams with 0, 1, 3 and 4
     EDCT epics in a month (`edct_chart_*`); the AI share keeps its 5-epic rule.

    python3 tile_oracle.py [--live] [--only NAME]
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import jql_eval as J                                                                # noqa: E402
import kit                                                                          # noqa: E402
import link_cycles as LC                                                            # noqa: E402  (epic_issue: a baked epic as the Jira fields the epic queries use)
import make_synthetic as MS                                                         # noqa: E402
from kit import ctx, T                                                              # noqa: E402

SUITE = kit.Suite("Delivery Pulse headline tiles (last 30 days)")
MIN_N = 5                                                                           # shares, percentiles and trends (the AI chart and the Epics by AI tile still use it)
EDCT_MIN_N = 1                                                                      # owner decision: one Done epic contributes to the EDCT average (tile and Efficiency chart)
WINDOW = 30
EXCL = ("maintenance", "sow")

# the 1st of a month, a window across a month boundary, the 1st of the next month, across a year boundary, across a leap day, and a day in the middle of a month
AS_OF_DAYS = [dt.date(2026, 11, 1), dt.date(2026, 11, 12), dt.date(2026, 12, 1), dt.date(2027, 1, 10), dt.date(2028, 3, 1), dt.date(2026, 10, 20)]
# Release and Delivery Cycle must not move the tiles; Projects and Teams do
STATES = ["", "p=PMN", "p=PMN|CXCO", "TEAM", "p=CXWFM|WFM", "p=CXSUP", "r=26.2&dc=2"]

TILE_JS = r"""(() => {
  const txt = n => n ? n.textContent.replace(/\s+/g, ' ').trim() : null;
  const a2 = a => ({href: a.getAttribute('href'), text: txt(a), tip: a.getAttribute('data-tip')});
  const tiles = {};
  document.querySelectorAll('#kpis .kpi').forEach(k => {
    const l = k.querySelector('.l'); if (!l) return;
    const name = (l.firstChild ? l.firstChild.textContent : '').trim(), mark = l.querySelector('.infomark');
    tiles[name] = {kicker: txt(k.querySelector('.k')), v: txt(k.querySelector('.v')), vLinks: [...k.querySelectorAll('.v a')].map(a2), s: txt(k.querySelector('.s')),
      sLinks: [...k.querySelectorAll('.s a')].map(a2), sTips: [...k.querySelectorAll('.s .tt')].map(n => n.getAttribute('data-tip')), x: txt(k.querySelector('.x')),
      info: mark ? mark.getAttribute('data-tip') : null, all: txt(k)};
  });
  const h = id => { const n = document.getElementById(id); return n ? txt(n) : null; };
  return {asOf: iso(asOfDay()), tiles, projects: [...state.projects], teams: [...state.teams], gran: state.gran, effHead: h('eff-head'), aiHead: h('ai-head'), hint: txt(document.querySelector('#g-gran .hintline')),
    errors: [], effCap: h('eff-cap'), aiCap: h('ai-cap')};
})()"""


def jql_of(href: str):
    q = urllib.parse.urlsplit(href)
    if q.path.rstrip("/") != "/issues":
        return None
    return urllib.parse.parse_qs(q.query, keep_blank_values=True).get("jql", [""])[0]


def rnd(x: float) -> int:
    """JavaScript Math.round: halves go up."""
    import math
    return math.floor(x + .5)


def pct(a: int, b: int):
    return rnd(100 * a / b) if b else None


def window_days(as_of: dt.date, back: int = 0):
    """(first day, last day) inclusive, as ISO strings. back=0 the 30 days ending on the as-of day; back=1 the 30 days before them."""
    last = as_of - dt.timedelta(days=back * WINDOW)
    return (last - dt.timedelta(days=WINDOW - 1)).isoformat(), last.isoformat()


def recount(data: dict, projects, teams, first: str, last: str) -> dict:
    """The independent recount from the baked epics. Done, resolved on a day of the window, in the selected projects and teams."""
    pop = []
    for e in data["epics"]:
        if e["s"] != "Done" or not e.get("rd") or not (first <= e["rd"] <= last) or e["p"] not in projects:
            continue
        if teams and not (set(e.get("tm") or []) & set(teams)):
            continue
        pop.append(e)
    kept = [e for e in pop if str(e.get("cat") or "").lower() not in EXCL]
    ai = [e for e in kept if e.get("ai")]
    edct = [e for e in pop if e.get("cat") != "Maintenance" and e.get("ai") and e.get("edct") is not None]
    ai_edct_pop = [e for e in pop if e.get("cat") != "Maintenance" and e.get("ai")]                    # what the EDCT link lists (Jira cannot search for the EDCT)
    return {"pop": pop, "kept": kept, "ai": ai, "excl": len(pop) - len(kept), "edct": edct, "edctAvg": sum(e["edct"] for e in edct) / len(edct) if edct else None,
            "linkEdct": ai_edct_pop, "notAi": [e for e in kept if not e.get("ai")]}


def keys(es) -> set:
    return {e["k"] for e in es}


def bounds_of(jql: str):
    m = re.search(r'resolutiondate >= "(\d{4}-\d\d-\d\d)" AND resolutiondate < "(\d{4}-\d\d-\d\d)"', jql or "")
    return (m.group(1), m.group(2)) if m else None


def tip_kind(tip: str) -> str:
    t = tip or ""
    if t.startswith("The previous"):
        return "prev"
    if "not marked as AI, resolved" in t:
        return "notai"
    if re.search(r"epics? implemented by AI, resolved", t):
        return "ai"
    if re.match(r"\d+ epics? resolved in", t):
        return "done"
    return "other"


def check_state(res: dict, data: dict, as_of: dt.date, tag: str, universe: list, facts: list) -> list[str]:
    p = []
    if res.get("__error"):
        return [f"{tag} the page probe failed: {res['__error'][:200]}"]
    if res["asOf"] != as_of.isoformat():
        return [f"{tag} the page's as-of day is {res['asOf']}, the fixture was built for {as_of}"]
    first, last = window_days(as_of)
    pfirst, plast = window_days(as_of, 1)
    nxt = (as_of + dt.timedelta(days=1)).isoformat()                            # the exclusive end of the window
    pnxt = (as_of - dt.timedelta(days=WINDOW - 1)).isoformat()                  # the exclusive end of the previous window = the first day of the window
    cur, prev = recount(data, res["projects"], res["teams"], first, last), recount(data, res["projects"], res["teams"], pfirst, plast)
    edct_t, ai_t = res["tiles"].get("EDCT Days"), res["tiles"].get("Epics by AI")
    if not edct_t or not ai_t:
        return [f"{tag} a tile is missing: {sorted(res['tiles'])}"]
    inwin = f"in the last 30 days ({first} to {last})"

    # ---- labels: Last 30 Days, never a calendar month, never "to Date"
    for name, t in (("EDCT Days", edct_t), ("Epics by AI", ai_t)):
        if t["kicker"] != "Last 30 Days":
            p.append(f"{tag} {name}: the kicker is {t['kicker']!r}, not 'Last 30 Days'")
        if re.search(r"to date|month|so far", t["all"], re.I):
            p.append(f"{tag} {name}: the tile text still talks about a calendar period: {t['all'][:160]!r}")
    if "last 30 days" not in (res["hint"] or ""):
        p.append(f"{tag} the Group By hint does not say the tiles use the last 30 days: {res['hint']!r}")

    # ---- EDCT Days
    n_e, avg = len(cur["edct"]), cur["edctAvg"]
    want_v = str(rnd(avg)) if n_e >= EDCT_MIN_N else "–"
    if edct_t["v"] != want_v:
        p.append(f"{tag} EDCT Days prints {edct_t['v']!r}, the recount gives {want_v!r} (n={n_e}, window {first} to {last})")
    want_s = "average of AI-implemented epics" if n_e >= EDCT_MIN_N else "no AI-implemented epics with an EDCT"
    if edct_t["s"] != want_s:
        p.append(f"{tag} EDCT Days sub line is {edct_t['s']!r}, expected {want_s!r}")
    if n_e >= EDCT_MIN_N and not any(inwin in (x or "") and f"over {n_e} AI-implemented {'epic' if n_e == 1 else 'epics'} with an EDCT" in x for x in edct_t["sTips"]):
        p.append(f"{tag} EDCT Days hover text does not name the window and n={n_e} (singular for one epic): {edct_t['sTips']}")
    if n_e >= EDCT_MIN_N:
        over = rnd(avg) - 10
        want_x = f"{over} over the ≤10 target" if over > 0 else "Within the ≤10 target"
        if edct_t["x"] != want_x:
            p.append(f"{tag} EDCT Days fact line is {edct_t['x']!r}, expected {want_x!r}")
    elif edct_t["x"]:
        p.append(f"{tag} EDCT Days shows a target verdict for n={n_e}: {edct_t['x']!r}")

    # ---- Epics by AI
    done, ai = len(cur["kept"]), len(cur["ai"])
    want_v = f"{pct(ai, done)}%" if done >= MIN_N else "–"
    if ai_t["v"] != want_v:
        p.append(f"{tag} Epics by AI prints {ai_t['v']!r}, the recount gives {want_v!r} ({ai} of {done}, window {first} to {last})")
    if done:
        want_s = f"{ai} of {done} resolved{', too few for a share' if done < MIN_N else ''} · {done - ai} not AI"
        pdone, pai = len(prev["kept"]), len(prev["ai"])
        if done >= MIN_N and pdone >= MIN_N:
            want_s += f" · Previous 30 days {pct(pai, pdone)}%"
    else:
        want_s = "no epics resolved in the last 30 days"
    if ai_t["s"] != want_s:
        p.append(f"{tag} Epics by AI sub line is {ai_t['s']!r}, expected {want_s!r}")
    if f"{cur['excl']} resolved {inwin}" not in (ai_t["info"] or ""):
        p.append(f"{tag} the exclusion note does not say '{cur['excl']} resolved {inwin}': {ai_t['info']!r}")

    # ---- links: the bounds in the query, and the epics the query finds
    def found(href):
        j = jql_of(href)
        if j is None:
            return None, None, f"not a Jira issue search: {href}"
        try:
            tree = J.parse(j)
            return {x["key"] for x in universe if J.evaluate(tree, x)}, j, None
        except (J.Malformed, J.Unsupported) as exc:
            return None, j, f"cannot be evaluated: {exc}"

    def verify(name, href, want_keys, bounds, count_text=None, ignore_no_edct=False):
        got, j, err = found(href)
        if err:
            p.append(f"{tag} {name}: the link {err}")
            return
        if bounds_of(j) != bounds:
            p.append(f"{tag} {name}: the link bounds are {bounds_of(j)}, expected {bounds}: {j[:200]}")
        if ignore_no_edct:
            edct = {e["k"]: e.get("edct") for e in data["epics"]}
            got = {k for k in got if edct.get(k) is not None}
        if got != want_keys:
            p.append(f"{tag} {name}: the link query finds {len(got)} epics, the recount {len(want_keys)} (only in query: {sorted(got - want_keys)[:3]}, only in recount: {sorted(want_keys - got)[:3]})")
        if count_text is not None and count_text.replace(",", "") != str(len(want_keys)):
            p.append(f"{tag} {name}: the link prints {count_text}, the recount {len(want_keys)}")

    win_b, prev_b = (first, nxt), (pfirst, pnxt)
    if n_e >= EDCT_MIN_N:
        if len(edct_t["vLinks"]) != 1:
            p.append(f"{tag} EDCT Days value has {len(edct_t['vLinks'])} links")
        else:
            verify("EDCT Days link", edct_t["vLinks"][0]["href"], keys(cur["edct"]), win_b, ignore_no_edct=True)
    elif edct_t["vLinks"]:
        p.append(f"{tag} EDCT Days shows no number but has a link")
    if done >= MIN_N:
        if len(ai_t["vLinks"]) != 1:
            p.append(f"{tag} Epics by AI value has {len(ai_t['vLinks'])} links")
        else:
            verify("Epics by AI value link", ai_t["vLinks"][0]["href"], keys(cur["ai"]), win_b)
    want_kind = {"ai": (cur["ai"], win_b), "done": (cur["kept"], win_b), "notai": (cur["notAi"], win_b)}
    seen = {}
    for a in ai_t["sLinks"]:
        kd = tip_kind(a["tip"])
        seen[kd] = seen.get(kd, 0) + 1
        if kd in want_kind:
            es, b = want_kind[kd]
            verify(f"Epics by AI '{kd}' link", a["href"], keys(es), b, count_text=a["text"])
            if f"resolved {inwin}" not in a["tip"]:
                p.append(f"{tag} Epics by AI '{kd}' link hover does not say '{inwin}': {a['tip']!r}")
        elif kd == "prev":
            verify("Epics by AI previous-window link", a["href"], keys(prev["ai"]), prev_b)
            wants = f"The previous 30 days ({pfirst} to {plast}) were {pct(len(prev['ai']), len(prev['kept']))}%: {len(prev['ai'])} of {len(prev['kept'])} epics resolved"
            if wants not in a["tip"]:
                p.append(f"{tag} the previous-window hover is {a['tip']!r}, expected it to contain {wants!r}")
            if a["text"] != f"Previous 30 days {pct(len(prev['ai']), len(prev['kept']))}%":
                p.append(f"{tag} the comparison text is {a['text']!r}")
        else:
            p.append(f"{tag} Epics by AI has an unexpected link: {a}")
    expect_links = {"ai": 1 if ai else 0, "done": 1 if done else 0, "notai": 1 if done - ai else 0, "prev": 1 if "Previous 30 days" in want_s else 0}
    for kd, n in expect_links.items():
        if seen.get(kd, 0) != n:
            p.append(f"{tag} Epics by AI: {seen.get(kd, 0)} '{kd}' links, expected {n}")

    # ---- the two charts stay on their calendar periods: the current month of the AI chart is the calendar month, not the tile
    if res["gran"] == "month" and res["aiHead"] is not None:
        mon = as_of.isoformat()[:7]
        mp = [e for e in recount_month(data, res["projects"], res["teams"], mon)]
        mk = [e for e in mp if str(e.get("cat") or "").lower() not in EXCL]
        mai = [e for e in mk if e.get("ai")]
        if len(mk) >= MIN_N:
            if not res["aiHead"].startswith(f"{pct(len(mai), len(mk))}% {mon} so far · {len(mai)} of {len(mk)}"):
                p.append(f"{tag} the AI Adoption headline moved off the calendar month {mon}: {res['aiHead'][:120]!r}, expected {pct(len(mai), len(mk))}% {mon} so far · {len(mai)} of {len(mk)}")
        elif not res["aiHead"].startswith("–") or mon not in res["aiHead"]:
            p.append(f"{tag} the AI Adoption headline with fewer than {MIN_N} epics is {res['aiHead'][:120]!r}")
        if mon not in (res["effHead"] or ""):
            p.append(f"{tag} the Efficiency headline does not name the calendar month {mon}: {res['effHead']!r}")
        for name, cap in (("Efficiency", res["effCap"]), ("AI Adoption", res["aiCap"])):
            if "last 30 days" not in (cap or ""):
                p.append(f"{tag} the {name} disclosure does not say that the tile at the top uses the last 30 days")
    facts.append(f"{as_of} {tag.strip('[]')}: EDCT {edct_t['v']} (n={n_e}), AI {ai_t['v']} ({ai} of {done}), previous {len(prev['ai'])} of {len(prev['kept'])}")
    return p


def recount_month(data, projects, teams, mon):
    out = []
    for e in data["epics"]:
        if e["s"] != "Done" or not e.get("rd") or not e["rd"].startswith(mon) or e["p"] not in projects:
            continue
        if teams and not (set(e.get("tm") or []) & set(teams)):
            continue
        out.append(e)
    return out


_data: dict = {}


def data_for(as_of: dt.date) -> dict:
    """The fictitious payload built so that the page's as-of day (the generation day) is `as_of`: it is built for two days later."""
    if as_of not in _data:
        d = MS.make(as_of + dt.timedelta(days=2))
        _add_edge_epics(d, as_of)
        _data[as_of] = d
    return _data[as_of]


def _add_edge_epics(d: dict, as_of: dt.date) -> None:
    """Epics resolved ON the edges of both windows, so that a window that is one day too long, too short or shifted changes a number: AI-implemented, no Issue Category, with an EDCT.
    Offsets from the as-of day: +1 (after it: out), 0 and -29 (the window's last and first day: in), -30 (the previous window's last day), -59 and -60 (its first day: in; the day before: out)."""
    proto = next(e for e in d["epics"] if e["s"] == "Done" and e["p"] == "PMN" and e.get("ai") and e.get("edct") is not None and e.get("cat") != "Maintenance")
    for i, off in enumerate((1, 0, -29, -30, -59, -60)):
        e = dict(proto, k=f"PMN-99{900 + i}", rd=(as_of + dt.timedelta(days=off)).isoformat(), cat=None, ai=True, edct=7 + i)
        d["epics"].append(e)


def state_hash(spec: str, team: str) -> str:
    return "&".join(f"t={urllib.parse.quote(team)}" if x == "TEAM" else x for x in spec.split("&")) if spec else ""


def run_matrix(template: Path, as_ofs, states, label: str):
    """Return (problems, facts) for every (as-of day, filter state)."""
    probs, facts = [], []
    for day in as_ofs:
        data = data_for(day)
        team = data["cap"]["teams"][0]
        universe = [LC.epic_issue(e) for e in data["epics"]]
        url = ctx.write(MS.render_page(data, template), "tiles")
        for spec in states:
            ch = ctx.chrome
            ch.goto(url + "#" + state_hash("g=month" + ("&" + spec if spec else ""), team))
            kit.wait_ready(ch)
            res = ch.js(TILE_JS)
            err = ch.console_errors()
            probs += [f"[{label} {day}] page error: {e}" for e in err[:2]]
            probs += check_state(res, data, day, f"[{label} {day} {spec or '(default)'}]", universe, facts)
    return probs, facts


@SUITE.test("tiles_are_the_last_30_days_and_every_link_opens_the_epics_counted")
def _(t: T):
    """EDCT Days and Epics by AI over the 30 days ending on the as-of day: value, sub lines, hover text, comparison and every link equal an independent recount; 6 as-of days x 7 filter states."""
    probs, facts = run_matrix(ctx.template, AS_OF_DAYS, STATES, "fixture")
    for x in probs[:20]:
        t.failures.append(x)
    t.passed += 0 if probs else 1
    t.check(len(facts) == len(AS_OF_DAYS) * len(STATES), f"every (as-of day, state) was compared: {len(facts)}")
    for f in facts[:len(STATES)] + facts[-2:]:
        t.note(f)


@SUITE.test("tiles_fixture_is_not_blind")
def _(t: T):
    """The recount must see every kind of epic the rules are about inside the windows (Maintenance, SOW, not AI, AI without an EDCT is not needed), and both sides of the 5-epic rule (which the AI share keeps; the EDCT average has none)."""
    seen = {"Maintenance in a window": 0, "SOW in a window": 0, "not AI in a window": 0, "AI in a window": 0, "window across a month boundary": 0, "a tile above 5 epics": 0, "a tile under 5 epics": 0,
            "an epic resolved after the as-of day": 0}
    for day in AS_OF_DAYS:
        data = data_for(day)
        first, last = window_days(day)
        if first[:7] != last[:7]:
            seen["window across a month boundary"] += 1
        for projects, teams in ((["PMN"], []), (["CXSUP"], []), (list(data["projects"]), []), (list(data["projects"]), [data["cap"]["teams"][0]])):
            c = recount(data, projects, teams, first, last)
            seen["Maintenance in a window"] += any(e.get("cat") == "Maintenance" for e in c["pop"])
            seen["SOW in a window"] += any(str(e.get("cat") or "").lower() == "sow" for e in c["pop"])
            seen["not AI in a window"] += bool(c["notAi"])
            seen["AI in a window"] += bool(c["ai"])
            seen["a tile above 5 epics"] += len(c["kept"]) >= MIN_N
            seen["a tile under 5 epics"] += len(c["kept"]) < MIN_N
        seen["an epic resolved after the as-of day"] += any(e["s"] == "Done" and e.get("rd") and e["rd"] > last for e in data["epics"])
    for k, v in seen.items():
        t.check(v > 0, f"the fixture matrix has {k}")
    t.note("; ".join(f"{k}: {v}" for k, v in seen.items()))


# ================================================================ the Efficiency EDCT chart and the AI Adoption chart (calendar months), and the tile against the chart
# Owner decision: the EDCT average is shown from ONE epic (tile and chart, EDCT_MIN_N). The share of "Epics by AI" keeps its 5-epic rule (MIN_N).
CHART_JS = r"""(() => {
  const txt = n => n ? n.textContent.replace(/\s+/g, ' ').trim() : null;
  const chart = (cid, did, hid) => {
    const host = document.getElementById(cid), svg = host.querySelector('svg');
    const groups = svg ? [...svg.querySelectorAll('a.cl, g.cl')].filter(g => !/^Target/.test(g.getAttribute('data-tip') || '')).map(g => ({tip: g.getAttribute('data-tip'), href: g.getAttribute('href'),
      bars: g.querySelectorAll('rect:not(.hit)').length, texts: [...g.querySelectorAll('text')].map(txt)})) : [];
    const ns = svg ? [...svg.children].filter(c => c.tagName === 'text').map(txt).filter(t => /^n=/.test(t)) : [];
    const rows = [...document.querySelectorAll('#' + did + ' tbody tr')].map(tr => [...tr.children].map(c => { const a = c.querySelector('a'); return {text: txt(c), href: a ? a.getAttribute('href') : null}; }));
    return {groups, ns, rows, head: txt(document.getElementById(hid)), empty: txt(host.querySelector('.empty')), hasSvg: !!svg, cap: txt(document.getElementById(hid.replace('head', 'cap')))};
  };
  return {asOf: iso(asOfDay()), gran: state.gran, projects: [...state.projects], teams: [...state.teams], eff: chart('eff-chart', 'eff-data', 'eff-head'), ai: chart('ai-chart', 'ai-data', 'ai-head')};
})()"""

EFF_EMPTY = "No resolved epic implemented by AI has an EDCT yet."


def month_periods(as_of: dt.date, n: int = 4) -> list:
    """The last n calendar months ending with the as-of day's month: (label, first day, first day of the next month, is the running one). Independent of the page."""
    out = []
    for i in range(n - 1, -1, -1):
        y, m = as_of.year, as_of.month - i
        while m < 1:
            y, m = y - 1, m + 12
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        out.append((f"{y}-{m:02d}" + ("*" if i == 0 else ""), dt.date(y, m, 1).isoformat(), dt.date(ny, nm, 1).isoformat(), i == 0))
    return out


def month_recount(data: dict, projects, teams, first: str, nxt: str) -> dict:
    """Done epics resolved in [first, nxt) in the selected projects and teams. EDCT population: AI-implemented, not Maintenance, with an EDCT. AI population: not Maintenance, not SOW."""
    pop = [e for e in data["epics"] if e["s"] == "Done" and e.get("rd") and first <= e["rd"] < nxt and e["p"] in projects and (not teams or set(e.get("tm") or []) & set(teams))]
    edct = [e for e in pop if e.get("cat") != "Maintenance" and e.get("ai") and e.get("edct") is not None]
    kept = [e for e in pop if str(e.get("cat") or "").lower() not in EXCL]
    return {"pop": pop, "edct": edct, "avg": sum(e["edct"] for e in edct) / len(edct) if edct else None, "kept": kept, "ai": [e for e in kept if e.get("ai")]}


def _epic_word(n: int) -> str:
    return "epic" if n == 1 else "epics"


def check_charts(res: dict, data: dict, tag: str, universe: list) -> list[str]:
    """Efficiency (EDCT average per calendar month) and AI Adoption (share) against an independent recount: bar or placeholder, hover text, head line, Show-data table, links."""
    p = []
    if res.get("__error"):
        return [f"{tag} the page probe failed: {res['__error'][:200]}"]
    as_of = dt.date.fromisoformat(res["asOf"])
    per = month_periods(as_of)
    rc = [month_recount(data, res["projects"], res["teams"], f, n) for _, f, n, _ in per]
    eff, ai = res["eff"], res["ai"]

    def keys_of(href):
        j = jql_of(href or "")
        if j is None:
            return None
        try:
            tree = J.parse(j)
            return {x["key"] for x in universe if J.evaluate(tree, x)}
        except (J.Malformed, J.Unsupported):
            return None

    edct_by_key = {e["k"]: e.get("edct") for e in data["epics"]}
    # ---- Efficiency
    if all(not c["edct"] for c in rc):
        if eff["hasSvg"] or eff["empty"] != EFF_EMPTY:
            p.append(f"{tag} Efficiency: no epic has an EDCT in any period, expected the empty text {EFF_EMPTY!r}, got {eff['empty']!r} (svg: {eff['hasSvg']})")
    elif not eff["hasSvg"]:
        p.append(f"{tag} Efficiency: no chart although an epic has an EDCT in a period (empty text {eff['empty']!r})")
    elif len(eff["groups"]) != len(per) or len(eff["ns"]) != len(per) or len(eff["rows"]) != len(per):
        p.append(f"{tag} Efficiency: {len(eff['groups'])} marks, {len(eff['ns'])} n labels, {len(eff['rows'])} table rows for {len(per)} periods")
    else:
        for i, ((label, _, _, running), c) in enumerate(zip(per, rc)):
            g, n, avg = eff["groups"][i], len(c["edct"]), c["avg"]
            ptip = f"{label.rstrip('*')} (running)" if running else label       # the hover names the running period in words, the axis label keeps the asterisk
            if eff["ns"][i] != f"n={n}":
                p.append(f"{tag} Efficiency {label}: the label under the bar is {eff['ns'][i]!r}, the recount has n={n}")
            if n >= EDCT_MIN_N:
                want_tip = f"{ptip}\nAverage EDCT {rnd(avg)} days\n{n} AI-implemented {_epic_word(n)} with an EDCT"
                if g["bars"] != 1 or str(rnd(avg)) not in g["texts"]:
                    p.append(f"{tag} Efficiency {label}: n={n} should show a bar labelled {rnd(avg)}, the mark has {g['bars']} bars and texts {g['texts']}")
            else:
                want_tip = f"{ptip}\nNo AI-implemented epics with an EDCT, so no average is shown"
                if g["bars"] != 0 or g["texts"] != ["–"]:
                    p.append(f"{tag} Efficiency {label}: n=0 should show no bar and '–', the mark has {g['bars']} bars and texts {g['texts']}")
            if g["tip"] != want_tip:
                p.append(f"{tag} Efficiency {label}: the hover text is {g['tip']!r}, expected {want_tip!r}")
            if re.search(r"fewer than|n&lt;|n<", (g["tip"] or "") + " ".join(g["texts"]), re.I):
                p.append(f"{tag} Efficiency {label}: a minimum is still named: {g['tip']!r} {g['texts']}")
            row = eff["rows"][i]
            want_val = str(rnd(avg)) if n >= EDCT_MIN_N else "–"
            if [row[0]["text"], row[1]["text"], row[2]["text"]] != [label, str(n), want_val]:
                p.append(f"{tag} Efficiency {label}: the Show-data row is {[x['text'] for x in row]}, expected {[label, str(n), want_val]}")
            for what, href in (("bar link", g["href"]), ("Epics link of the table", row[1]["href"])):
                if what == "Epics link of the table" and not n:
                    if href:
                        p.append(f"{tag} Efficiency {label}: the table links {n} epics")
                    continue
                got = keys_of(href)
                if got is None:
                    p.append(f"{tag} Efficiency {label}: the {what} cannot be evaluated: {href}")
                elif {k for k in got if edct_by_key.get(k) is not None} != keys(c["edct"]):
                    p.append(f"{tag} Efficiency {label}: the {what} finds {len({k for k in got if edct_by_key.get(k) is not None})} epics with an EDCT, the recount {n}")
        label, c = per[-1][0], rc[-1]
        n, avg = len(c["edct"]), c["avg"]
        mon = label.rstrip("*")
        if n >= EDCT_MIN_N:
            over = rnd(avg) - 10
            want = f"{rnd(avg)} days {mon} so far · {n} {_epic_word(n)} · {f'{over} over' if over > 0 else 'within'} the ≤10 target"
        else:
            want = f"– {mon} · no epics with an EDCT so far"
        if eff["head"] != want:
            p.append(f"{tag} Efficiency head line is {eff['head']!r}, expected {want!r}")
        if "fewer than" in (eff["head"] or "").lower() or "fewer than" in (eff["cap"] or "").lower() or "none is shown" in (eff["cap"] or "").lower():
            p.append(f"{tag} Efficiency still names a minimum number of epics: {(eff['head'] or '')[:80]!r} / {(eff['cap'] or '')[:80]!r}")
    # ---- AI Adoption: the 5-epic rule of the share is unchanged
    if all(len(c["kept"]) < MIN_N for c in rc):
        want_empty = f"Not enough resolved epics yet. Each month needs at least {MIN_N}."          # every period is under 5: nothing to plot, as before
        if ai["hasSvg"] or ai["empty"] != want_empty:
            p.append(f"{tag} AI Adoption: every period has under {MIN_N} epics, expected the empty text {want_empty!r}, got {ai['empty']!r} (svg: {ai['hasSvg']})")
        d, a = len(rc[-1]["kept"]), 0
        if ai["head"] != f"– {per[-1][0].rstrip('*')} · fewer than {MIN_N} epics so far":
            p.append(f"{tag} AI Adoption head line of an under-5 period is {ai['head']!r}")
    elif len(ai["groups"]) != len(per) or len(ai["rows"]) != len(per):
        p.append(f"{tag} AI Adoption: {len(ai['groups'])} marks, {len(ai['rows'])} table rows for {len(per)} periods")
    else:
        for i, ((label, _, _, running), c) in enumerate(zip(per, rc)):
            g, d, a = ai["groups"][i], len(c["kept"]), len(c["ai"])
            ptip = f"{label.rstrip('*')} (running)" if running else label       # the hover names the running period in words
            if d >= MIN_N:
                if g["bars"] != 1 or f"{pct(a, d)}%" not in g["texts"]:
                    p.append(f"{tag} AI Adoption {label}: {d} epics should show a bar labelled {pct(a, d)}%, the mark has {g['bars']} bars and texts {g['texts']}")
                if not (g["tip"] or "").startswith(f"{ptip}: {pct(a, d)}% marked as AI ({a} of {d})"):
                    p.append(f"{tag} AI Adoption {label}: the hover text is {g['tip']!r}")
            else:
                if g["bars"] != 0 or g["texts"] != ["n<5"]:
                    p.append(f"{tag} AI Adoption {label}: {d} epics (under {MIN_N}) should show 'n<5' and no bar, the mark has {g['bars']} bars and texts {g['texts']}")
                if not (g["tip"] or "").startswith(f"{ptip}\nFewer than {MIN_N} epics resolved, so no share is shown"):
                    p.append(f"{tag} AI Adoption {label}: the hover text of an under-5 period is {g['tip']!r}")
            row = ai["rows"][i]
            if [row[0]["text"], row[1]["text"], row[2]["text"]] != [per[i][0], str(d), f"{pct(a, d)}%" if d >= MIN_N else "–"]:
                p.append(f"{tag} AI Adoption {label}: the Show-data row is {[x['text'] for x in row][:3]}")
        label, c = per[-1][0].rstrip("*"), rc[-1]
        d, a = len(c["kept"]), len(c["ai"])
        if d < MIN_N and ai["head"] != f"– {label} · fewer than {MIN_N} epics so far":
            p.append(f"{tag} AI Adoption head line of an under-5 period is {ai['head']!r}")
        if d >= MIN_N and not (ai["head"] or "").startswith(f"{pct(a, d)}% {label} so far · {a} of {d}"):
            p.append(f"{tag} AI Adoption head line is {ai['head']!r}")
    return p


# ---- the controlled fixture: fictitious teams whose epics put exactly 0, 1, 3, 4 and 5 epics into a month (as-of 2026-11-12: months 2026-08 .. 2026-11, the last one running)
CH_AS_OF = dt.date(2026, 11, 12)
CH_TEAMS = {"Team Zulu": "1 epic in 2026-10 (and an epic of every other kind that must not count), 4 in 2026-09, none in 2026-08 and 2026-11",
            "Team Yankee": "one epic in the running month 2026-11 and nothing else",
            "Team Xray": "no epic with an EDCT at all (not AI, or AI without an EDCT)",
            "Team Whiskey": "5 epics resolved in 2026-10, 3 of them AI-implemented with an EDCT; 4 AI-implemented epics in 2026-09 (the AI share still says n<5, the EDCT average shows)"}
_ch_data: dict = {}


def chart_data() -> dict:
    """Fictitious epics, each a copy of an existing Done PMN epic with its own key, team, day, Issue Category, AI flag and EDCT. Days are in the window of the tiles (2026-10-14 to 2026-11-12) when the tile is to agree with the chart."""
    if CH_AS_OF not in _ch_data:
        import copy
        d = copy.deepcopy(data_for(CH_AS_OF))
        proto = next(e for e in d["epics"] if e["s"] == "Done" and e["p"] == "PMN" and e.get("ai") and e.get("edct") is not None and e.get("cat") != "Maintenance")
        spec = [  # (team, day, AI-implemented, Issue Category, EDCT)
            ("Team Zulu", "2026-09-03", True, None, 8), ("Team Zulu", "2026-09-10", True, None, 12), ("Team Zulu", "2026-09-17", True, None, 15), ("Team Zulu", "2026-09-28", True, None, 11),
            ("Team Zulu", "2026-10-20", True, None, 17), ("Team Zulu", "2026-10-21", True, "Maintenance", 3), ("Team Zulu", "2026-10-22", False, None, 40), ("Team Zulu", "2026-10-23", True, None, None),
            ("Team Yankee", "2026-11-05", True, None, 14),
            ("Team Xray", "2026-10-12", False, None, 5), ("Team Xray", "2026-10-13", True, None, None),
            ("Team Whiskey", "2026-10-02", True, None, 6), ("Team Whiskey", "2026-10-03", True, None, 9), ("Team Whiskey", "2026-10-04", True, None, 12),
            ("Team Whiskey", "2026-10-12", False, None, 30), ("Team Whiskey", "2026-10-13", False, None, 25),
            ("Team Whiskey", "2026-09-08", True, None, 10), ("Team Whiskey", "2026-09-09", True, None, 10), ("Team Whiskey", "2026-09-10", True, None, 10), ("Team Whiskey", "2026-09-11", True, None, 13),
        ]
        for i, (team, day, ai, cat, edct) in enumerate(spec):
            e = dict(proto, k=f"PMN-998{i:02d}", rd=day, tm=[team], ai=ai, cat=cat, edct=edct, m=proto.get("m") if ai else None)
            e["ip"], e["vl"], e["cal"] = (edct, 0, edct) if edct is not None else (None, None, None)
            d["epics"].append(e)
        _ch_data[CH_AS_OF] = d
    return _ch_data[CH_AS_OF]


def run_chart_states(template: Path, label: str, with_tiles: bool = True):
    """Every controlled team (and the whole fixture) in month view: the two charts and, for the tiles, the same recount as the tile matrix. Returns (problems, per-team facts)."""
    probs, facts = [], {}
    data = chart_data()
    universe = [LC.epic_issue(e) for e in data["epics"]]
    url = ctx.write(MS.render_page(data, template), "edctchart")
    for spec in list(CH_TEAMS) + [None]:
        tag = f"[{label} {spec or 'all teams'}]"
        ch = ctx.chrome
        ch.goto(url + "#g=month" + (f"&t={urllib.parse.quote(spec)}" if spec else ""))
        kit.wait_ready(ch)
        res = ch.js(CHART_JS)
        probs += [f"{tag} page error: {e}" for e in ch.console_errors()[:2]]
        probs += check_charts(res, data, tag, universe)
        if with_tiles:
            tres = ch.js(TILE_JS)
            probs += check_state(tres, data, CH_AS_OF, tag, universe, [])
            facts[spec] = (res, tres)
    return probs, facts


@SUITE.test("edct_chart_and_tile_show_the_average_from_one_epic")
def _(t: T):
    """Efficiency EDCT chart (bars, 'n=' labels, hover text, head line, Show-data table, links), the AI Adoption chart and the EDCT Days tile against an independent recount, on fictitious teams
    with exactly 0, 1, 3 and 4 EDCT epics in a month. The AI share keeps its 5-epic rule."""
    probs, facts = run_chart_states(ctx.template, "fixture")
    for x in probs[:20]:
        t.failures.append(x)
    t.passed += 0 if probs else 1
    t.check(len(facts) == len(CH_TEAMS) + 1, f"every controlled team was compared: {sorted(k or 'all' for k in facts)}")
    # the fixture really holds the cases the brief names (recounted here, not read off the page)
    data = chart_data()
    ns = {}
    for team in CH_TEAMS:
        for label, first, nxt, _ in month_periods(CH_AS_OF):
            ns[(team, label)] = len(month_recount(data, ["PMN"], [team], first, nxt)["edct"])
    t.check(ns[("Team Zulu", "2026-10")] == 1 and ns[("Team Zulu", "2026-09")] == 4 and ns[("Team Zulu", "2026-08")] == 0 and ns[("Team Whiskey", "2026-10")] == 3 and ns[("Team Whiskey", "2026-09")] == 4 and ns[("Team Yankee", "2026-11*")] == 1,
            f"the fixture holds exactly 1, 4, 0 and 3 EDCT epics in the months the checks are about: {ns}")
    # the tile and the chart agree for the same window: Zulu's epics of 2026-10 and Yankee's of 2026-11 all lie in the tile window (2026-10-14 to 2026-11-12)
    for team, idx in (("Team Zulu", 2), ("Team Yankee", 3)):
        res, tres = facts[team]
        bar = res["eff"]["groups"][idx]["texts"]
        tile = tres["tiles"]["EDCT Days"]["v"]
        t.check(tile in bar and tile != "–", f"{team}: the EDCT Days tile ({tile}) and the chart bar of the same epics ({bar}) agree")
    w = facts["Team Whiskey"][0]
    t.check(w["eff"]["groups"][1]["texts"] == ["11"] and w["ai"]["groups"][1]["texts"] == ["n<5"] and w["ai"]["groups"][2]["texts"] == ["60%"],
            f"4 epics in 2026-09: the EDCT average shows ({w['eff']['groups'][1]['texts']}), the AI share still says n<5 ({w['ai']['groups'][1]['texts']}); 5 epics in 2026-10 give a share ({w['ai']['groups'][2]['texts']})")
    z = facts["Team Zulu"][1]["tiles"]["EDCT Days"]
    t.check(z["v"] == "17" and z["s"] == "average of AI-implemented epics" and z["x"] == "7 over the ≤10 target", f"one epic gives a tile, its sub line and its target line: {z['v']!r} {z['s']!r} {z['x']!r}")
    x = facts["Team Xray"]
    t.check(x[0]["eff"]["empty"] == EFF_EMPTY and x[1]["tiles"]["EDCT Days"]["v"] == "–", "with no EDCT epic at all the chart says so and the tile is '–'")
    for k, v in facts.items():
        t.note(f"{k or 'all teams'}: EDCT tile {v[1]['tiles']['EDCT Days']['v']}, chart {[g['texts'] for g in v[0]['eff']['groups']]}")


@SUITE.test("edct_chart_equals_an_independent_recount_in_the_filter_matrix")
def _(t: T):
    """The same chart check over the generated fixture: three as-of days x four filter states (months), all periods."""
    probs, n = [], 0
    for day in (dt.date(2026, 11, 1), dt.date(2026, 11, 12), dt.date(2027, 1, 10)):
        data = data_for(day)
        team = data["cap"]["teams"][0]
        universe = [LC.epic_issue(e) for e in data["epics"]]
        url = ctx.write(MS.render_page(data, ctx.template), "edctmatrix")
        for spec in ("", "p=PMN", "p=CXSUP", "TEAM"):
            ch = ctx.chrome
            ch.goto(url + "#" + state_hash("g=month" + ("&" + spec if spec else ""), team))
            kit.wait_ready(ch)
            res = ch.js(CHART_JS)
            probs += [f"[{day} {spec or '(default)'}] page error: {e}" for e in ch.console_errors()[:2]]
            probs += check_charts(res, data, f"[{day} {spec or '(default)'}]", universe)
            n += 1
    for x in probs[:20]:
        t.failures.append(x)
    t.passed += 0 if probs else 1
    t.check(n == 12, f"every state was compared: {n}")


CHART_MUTATIONS = [
    ("the 5-epic minimum still applied to the Efficiency chart", "avg: m.edctN >= EDCT_MIN_N ? m.edctAvg : null}; });", "avg: m.edctN >= MIN_N ? m.edctAvg : null}; });"),
    ("the 5-epic minimum still applied to the EDCT Days tile", 'v: ms.edctN >= EDCT_MIN_N ? tlink(', 'v: ms.edctN >= MIN_N ? tlink('),
    ("the 5-epic minimum still applied to the tile's target line", "if (ms.edctN >= EDCT_MIN_N) { const a = Math.round(ms.edctAvg)", "if (ms.edctN >= MIN_N) { const a = Math.round(ms.edctAvg)"),
    ("the 5-epic minimum still applied to the head line of the chart", "head.innerHTML = a == null ? `– <small>", "head.innerHTML = a == null || cur.n < MIN_N ? `– <small>"),
    ("the 5-epic minimum removed from the AI Adoption chart", "share: m.done >= MIN_N ? pct(m.ai, m.done) : null}", "share: m.done >= 1 ? pct(m.ai, m.done) : null}"),
    ("the average over Maintenance epics too", 'withEdct = pop.filter(e => e.cat !== "Maintenance" && e.ai && e.edct != null)', "withEdct = pop.filter(e => e.ai && e.edct != null)"),
    ("the average over epics that AI did not implement too", 'withEdct = pop.filter(e => e.cat !== "Maintenance" && e.ai && e.edct != null)', 'withEdct = pop.filter(e => e.cat !== "Maintenance" && e.edct != null)'),
    ("a hover text that says 'epics' for one epic", '${nn(r.n, "AI-implemented epic", "AI-implemented epics")} with an EDCT`', '${r.n} AI-implemented epics with an EDCT`'),
    ("a placeholder 'n<5' on a period with no epic", 'text-anchor="middle" font-size="11" fill="#5A5F6B">${(o.min == null ? MIN_N : o.min) > 1', 'text-anchor="middle" font-size="11" fill="#5A5F6B">${5 > 1'),
]


@SUITE.test("edct_chart_oracle_selftest_catches_seeded_defects")
def _(t: T):
    """Seeded defects: the minimum applied again on the chart, the tile, the target line or the head line; the minimum removed from the AI share; the wrong epic set averaged; a wrong hover text."""
    src = ctx.template.read_text(encoding="utf-8")
    ran = 0
    for label, old, new in CHART_MUTATIONS:
        if src.count(old) != 1:
            t.check(False, f"the pattern of the seeded defect '{label}' is not in the template exactly once")
            continue
        ran += 1
        tmp = Path(ctx.dir) / f"edct_mutant_{ran}.html"
        tmp.write_text(src.replace(old, new, 1), encoding="utf-8")
        probs, _ = run_chart_states(tmp, "mutant")
        t.check(bool(probs), f"seeded defect caught: {label} ({len(probs)} findings)")
    if not ran:
        raise kit.Skip("none of the seeded defects applies to this template version")


# ================================================================ the oracle must not be blind: seed each defect into a copy of the template and require it to be caught
LAST_DAYS = "const e = asOfDay() + DAY - back * n * DAY, s = e - n * DAY;"
MUTATIONS = [
    ("the calendar month (to date) instead of 30 days",
     LAST_DAYS, "const t = new Date(asOfDay()), s = Date.UTC(t.getUTCFullYear(), t.getUTCMonth() - back, 1), e = back ? Date.UTC(t.getUTCFullYear(), t.getUTCMonth(), 1) : asOfDay() + DAY;"),
    ("a window that ends the day before the as-of day", LAST_DAYS, "const e = asOfDay() - back * n * DAY, s = e - n * DAY;"),
    ("a window of 31 days", LAST_DAYS, "const e = asOfDay() + DAY - back * n * DAY, s = e - (n + 1) * DAY;"),
    ("a window that reaches one day past the as-of day", LAST_DAYS, "const e = asOfDay() + 2 * DAY - back * n * DAY, s = e - n * DAY;"),
    ("a window of 29 days", LAST_DAYS, "const e = asOfDay() + DAY - back * n * DAY, s = e - (n - 1) * DAY;"),
    ("a previous window that overlaps the window by one day", LAST_DAYS, "const e = asOfDay() + DAY - back * (n - 1) * DAY, s = e - n * DAY;"),
    ("the tiles still reading the calendar month of the as-of day for the kicker", "to = `Last ${WINDOW_DAYS} Days`", "to = `${iso(asOfDay()).slice(0, 7)} to Date`"),
]


@SUITE.test("tiles_oracle_selftest_catches_seeded_defects")
def _(t: T):
    src = ctx.template.read_text(encoding="utf-8")
    ran = 0
    for label, old, new in MUTATIONS:
        if src.count(old) != 1:
            t.check(False, f"the pattern of the seeded defect '{label}' is not in the template exactly once")
            continue
        ran += 1
        tmp = Path(ctx.dir) / f"tile_mutant_{ran}.html"
        tmp.write_text(src.replace(old, new, 1), encoding="utf-8")
        probs, _ = run_matrix(tmp, [dt.date(2026, 11, 1), dt.date(2026, 11, 12)], ["", "p=PMN|CXCO", "TEAM"], "mutant")
        t.check(bool(probs), f"seeded defect caught: {label} ({len(probs)} findings)")
    if not ran:
        raise kit.Skip("none of the seeded defects applies to this template version")


if __name__ == "__main__":
    sys.exit(kit.cli(SUITE, __doc__))
