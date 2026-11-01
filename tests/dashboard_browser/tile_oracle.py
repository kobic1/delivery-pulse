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
MIN_N = 5
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
    if "epics implemented by AI, resolved" in t:
        return "ai"
    if re.match(r"\d+ epics resolved in", t):
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
    want_v = str(rnd(avg)) if n_e >= MIN_N else "–"
    if edct_t["v"] != want_v:
        p.append(f"{tag} EDCT Days prints {edct_t['v']!r}, the recount gives {want_v!r} (n={n_e}, window {first} to {last})")
    want_s = "average of AI-implemented epics" if n_e >= MIN_N else f"only {n_e} epics, need {MIN_N}"
    if edct_t["s"] != want_s:
        p.append(f"{tag} EDCT Days sub line is {edct_t['s']!r}, expected {want_s!r}")
    if n_e >= MIN_N and not any(inwin in (x or "") and f"over {n_e} AI-implemented epics" in x for x in edct_t["sTips"]):
        p.append(f"{tag} EDCT Days hover text does not name the window and n={n_e}: {edct_t['sTips']}")
    if n_e >= MIN_N:
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
    if n_e >= MIN_N:
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
    """The recount must see every kind of epic the rules are about inside the windows (Maintenance, SOW, not AI, AI without an EDCT is not needed), and both sides of the 5-epic rule."""
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
