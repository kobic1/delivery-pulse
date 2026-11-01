#!/usr/bin/env python3
"""Refresh and failure-matrix tests for the Delivery Pulse page, on the FICTITIOUS fixture, in headless Chrome.

The page is the template under test with make_synthetic.py's payload baked in; its only outside dependency, claude.use("mcp"), is answered
locally (mock_claude.js) in the real shape of the Atlassian searchJiraIssuesUsingJql tool. Nothing touches the network or Jira.

    python3 harness.py                       # the frozen v52 template
    python3 harness.py --live                # the live program_dashboard/dashboard.template.html
    python3 harness.py --only f15            # a subset by name
    python3 harness.py --expect DEADLINE     # a fix has landed: its test must now pass
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kit                                                                          # noqa: E402
import make_synthetic as MS                                                         # noqa: E402
from kit import ctx, stamp, il_day_of, T, Skip                                      # noqa: E402

SUITE = kit.Suite("Delivery Pulse refresh and failure matrix")
TODAY = MS.il_today()
TODAY_S = TODAY.isoformat()
DEADLINE_WAIT = float(os.environ.get("DP_DEADLINE_WAIT", "10"))
EDITED_TXT = "The root cause was a missed null check in the sync job; fixed and verified."
TEMPLATE_TXT = MS.RCA_TEMPLATES[0].upper()                                          # the page normalises case and spacing before hashing


# ---------------------------------------------------------------- the fixture and the cases' subjects
class Fx:
    """The payload plus the issues each case is about (chosen from the fictitious data, never named)."""
    pass


_FX: Fx | None = None


def need(x, what):
    assert x is not None, f"the fixture lacks {what}"
    return x


def build_fixture() -> Fx:
    global _FX
    if _FX:
        return _FX
    fx = Fx()
    data = MS.make(TODAY)
    ep, bugs, hier = data["epics"], data["bugs"], data["hier"]
    r27 = lambda e: e["fv"] == ["27.1"]                                              # in release 27.1 only (a "moved" epic must not already carry 27.2)
    top = max([int(k.split("-")[1]) for k in [e["k"] for e in ep] + [b["k"] for b in bugs] + list(data["capabilities"])] + [int(r.split(",")[0]) for r in data["cap"]["rows"].split(";")])
    assert top < 98000, "the generator's issue numbers reached the range the tests reserve for their own issues"
    deps = data["deps"]
    used = set()

    def pick(cond, what):
        e = need(next((e for e in ep if e["k"] not in used and cond(e)), None), what)
        used.add(e["k"])
        return e
    S = {}
    e_dep = pick(lambda e: e["p"] == "PMN" and r27(e) and e["s"] == "In Progress" and e.get("cp") and e.get("ts") and e.get("dd") and any(d[1] == e["k"] for d in deps), "a dependency provider epic")
    e_keep = pick(lambda e: e["s"] == "Done" and e.get("edct") is not None and e.get("dd") and e.get("ts") and e.get("cp") and r27(e), "a Done epic with every planning fact")
    e_status = pick(lambda e: e["p"] == "PMN" and r27(e) and e["s"] != "Done" and e["c"] in ("Committed", None), "an open committed PMN epic")
    e_removed = pick(lambda e: e["p"] == "PMN" and r27(e) and e["s"] != "Done", "an open PMN epic")
    e_moved = pick(lambda e: e["p"] == "PMN" and r27(e) and e["s"] != "Done", "an open PMN epic")
    pods = [pick(lambda e: e.get("pl") and r27(e) and e["p"] != "CXINT", "an epic with a pod label") for _ in range(3)]
    e_clear = pick(lambda e: e["s"] != "Done" and e.get("dd") and e.get("ts") and r27(e), "an open epic with a due date and a Target Sprint")
    open_bug = need(next((b for b in bugs if b["p"] == "PMN" and "rd" not in b and not b.get("ax") and not b.get("cfb")), None), "a plain open PMN bug")
    cfb_done = need(next((b for b in bugs if b.get("cl") and b.get("sf") and b.get("rb") and b.get("inc") is not None and b["s"] == "Done"), None), "a Done customer-found bug")
    closed = ("Done", "Closed", "Resolved", "Removed", "Ready for Deploy")
    open_cfbs = [b for b in bugs if b["p"] == "PMN" and b.get("cfb") and b["s"] not in closed and b["k"] in data["cfbx"]["bugs"]]
    cfb_open = need(next((b for b in open_cfbs if b.get("ud") and b.get("rb") and b.get("sf")), None), "an open CFB")
    oA, oB, oC, oD, oE = [b for b in open_cfbs if b["k"] != cfb_open["k"]][:5]
    # the capability whose fix version changed after the pull (the case: baseline 26.4, Jira now says 27.1)
    cap_key = need(next((k for k, h in hier.items() if h["ty"] == "Capability" and "27.1" in h["fv"] and h["s"] != "Removed" and h["p"] == "CXCROSS"), None), "a CXCROSS capability")
    hier[cap_key]["fv"] = ["26.4"]
    hier[cap_key]["s"] = "New"
    data["capList"][cap_key]["fv"], data["capList"][cap_key]["s"] = ["26.4"], "New"
    # dependency links: an epic that has pairs, and another epic it is not related to
    cnt = Counter(x for d in deps for x in d[:2] if x in {e["k"] for e in ep})
    E1 = next(k for k, n in cnt.items() if n >= 1)
    partners = {x for d in deps if E1 in d[:2] for x in d[:2]}
    E2 = next(e["k"] for e in ep if e["k"] != E1 and e["k"] not in partners)
    S.update(eStatus=e_status["k"], eRemoved=e_removed["k"], eMoved=e_moved["k"], newEpic="PMN-98001", newBug="PMN-98002", axBug="PMN-98003", openBug=open_bug["k"], eDep=e_dep["k"],
             eKeep=e_keep["k"], eClear=e_clear["k"], plSet=pods[0]["k"], plClear=pods[1]["k"], plKeep=pods[2]["k"], cfbDone=cfb_done["k"], cfbOpen=cfb_open["k"],
             oA=oA["k"], oB=oB["k"], oC=oC["k"], oD=oD["k"], oE=oE["k"], newCfb="PMN-98100", farKey="EXA-98001", cap=cap_key, tplHash=MS.h53(MS.norm_text(TEMPLATE_TXT)))
    fx.data, fx.S = data, S
    fx.ep = {k: next(e for e in ep if e["k"] == k) for k in (e_status["k"], e_removed["k"], e_moved["k"], e_dep["k"], e_keep["k"], e_clear["k"], *(p["k"] for p in pods))}
    fx.E1, fx.E2, fx.old_e1 = E1, E2, [d for d in deps if E1 in d[:2]]
    fx.sprint = {s["n"]: s for s in data["sprints"]}
    fx.gen_day = dt.date.fromisoformat(data["generated"][:10])
    fx.fragment = kit.fragment_for(data)

    # ---- the answers the mock gives (the real field names and shapes of the Atlassian tool)
    node = lambda key, typ, **f: {"id": "1", "key": key, "webUrl": "x", "fields": {"summary": f.pop("summary", "Test " + key), "issuetype": {"name": typ}, "status": {"name": f.pop("status")},
                                                                                     "created": f.pop("created", stamp(TODAY, "08:00")), **f}}
    team = lambda e: [{"value": t} for t in e["tm"]]
    fv27 = [{"name": "27.1"}]
    commit = lambda e: {"value": e["c"] or "Committed"}
    sp_of = lambda e: fx.sprint[e["ts"]]
    nodes = [
        node(e_status["k"], "Epic", status="Done", resolutiondate=stamp(TODAY, "09:00"), fixVersions=fv27, customfield_10094={"value": "Committed"}, customfield_10040=team(e_status), created=stamp(dt.date.fromisoformat(e_status["cr"]), "08:00")),
        node(e_removed["k"], "Epic", status="Removed", fixVersions=fv27),
        node(e_moved["k"], "Epic", status="In Progress", fixVersions=[{"name": "27.2"}], customfield_10094={"value": "Committed"}),
        node(S["newEpic"], "Epic", status="New", fixVersions=fv27, customfield_10094={"value": "Committed"}, customfield_10040=[{"value": MS.TEAMS["PMN"][0]}]),
        node(S["newBug"], "Bug", status="Open", priority={"name": "P2"}, customfield_10098={"value": MS.TEAMS["PMN"][0]}, reporter={"accountId": "someone"}),
        node(S["axBug"], "Bug", status="Open", priority={"name": "P1"}, reporter={"accountId": "someone"}),                                 # accessibility: excluded by default
        node(open_bug["k"], "Bug", status="Done", resolutiondate=stamp(TODAY, "10:00"), resolution={"name": "Fixed"}, priority={"name": open_bug.get("pr", "P3")}, reporter={"accountId": "someone"},
             created=stamp(dt.date.fromisoformat(open_bug["cr"]), "08:00")),
        # updated after the snapshot: the refresh returns its planning fields (Target Sprint as an option object, parent Capability); the due date stays inside the same sprint
        node(e_dep["k"], "Epic", status="Ready for Dev", fixVersions=fv27, customfield_10094={"value": "Committed"}, customfield_10040=team(e_dep),
             duedate=(dt.date.fromisoformat(sp_of(e_dep)["start"]) + dt.timedelta(days=4)).isoformat(), customfield_12697={"value": e_dep["ts"]}, assignee={"displayName": "Person Z"},
             parent={"key": e_dep["cp"], "fields": {"summary": "Cap", "issuetype": {"name": "Capability"}}}, updated=stamp(TODAY, "07:00"), customfield_10021=[], labels=[],
             created=stamp(dt.date.fromisoformat(e_dep["cr"]), "08:00")),
        # a Done epic whose response carries NO planning fields at all: dd/ts/cp/as/ud and the cycle time must all stay
        node(e_keep["k"], "Epic", status="Done", resolutiondate=stamp(dt.date.fromisoformat(e_keep["rd"] or TODAY_S), "09:00"), fixVersions=fv27, customfield_10094=commit(e_keep), customfield_10040=team(e_keep)),
        # the due date was removed in Jira (duedate null): dd goes; Target Sprint is absent, so ts stays
        node(e_clear["k"], "Epic", status=e_clear["s"], fixVersions=fv27, customfield_10094=commit(e_clear), customfield_10040=team(e_clear), duedate=None),
        node(pods[0]["k"], "Epic", status=pods[0]["s"], fixVersions=fv27, customfield_10094=commit(pods[0]), customfield_10040=team(pods[0]), labels=["Pod-Zulu-9", "other"]),
        node(pods[1]["k"], "Epic", status=pods[1]["s"], fixVersions=fv27, customfield_10094=commit(pods[1]), customfield_10040=team(pods[1]), labels=[]),
        node(pods[2]["k"], "Epic", status=pods[2]["s"], fixVersions=fv27, customfield_10094=commit(pods[2]), customfield_10040=team(pods[2])),
        # a Done customer-found bug whose response lacks reporter, case, Closed and incident fields: rb/sf/cl/inc stay
        node(cfb_done["k"], "Bug", status="Done", resolutiondate=stamp(dt.date.fromisoformat(cfb_done["rd"]), "10:00"), resolution={"name": cfb_done.get("rs", "Fixed")}, priority={"name": cfb_done.get("pr", "P3")},
             created=stamp(dt.date.fromisoformat(cfb_done["cr"]), "08:00")),
        # an open customer-found bug edited today: ud is today, rb/sf stay
        node(cfb_open["k"], "Bug", status=cfb_open["s"], priority={"name": cfb_open.get("pr", "P3")}, created=stamp(dt.date.fromisoformat(cfb_open["cr"]), "08:00"), updated=stamp(TODAY, "07:30")),
    ]
    fx.node, fx.nodes = node, nodes
    fx.page1, fx.page2 = nodes[:4], nodes[4:]

    # ---- Capitalization: the delta refresh covers every quarter; returned issues are judged by the population rule again; absence never deletes
    C = data["cap"]
    EP = dt.date.fromisoformat(C["epoch"])
    crow = lambda line: dict(zip("n p v sp cd t fb".split(), line.split(",")))
    day_of = lambda r: EP + dt.timedelta(days=int(r["cd"]))
    fx.crow, fx.day_of = crow, day_of
    rows = [crow(l) for l in C["rows"].split(";")]
    nonval = next(i for i, v in enumerate(C["values"]) if v.startswith("Non Capitalize"))
    capval = next(i for i, v in enumerate(C["values"]) if v.startswith("Capitalize"))
    QS = MS.q_start(TODAY)
    pmn = [r for r in rows if r["p"] == "0"]
    early = [r for r in pmn if day_of(r) < QS - dt.timedelta(days=100) and day_of(r) >= dt.date.fromisoformat(C["start"]) + dt.timedelta(days=20)]
    prev_q = [r for r in pmn if QS - dt.timedelta(days=92) <= day_of(r) < QS]
    curr = [r for r in pmn if day_of(r) >= QS]
    cA = next(r for r in early if int(r["v"]) == nonval)
    cB, cC = [r for r in early if r is not cA][:2]
    cD = prev_q[0]
    cE, cF = curr[0], curr[1]
    fx.cap = dict(cA=cA, cB=cB, cC=cC, cD=cD, cE=cE, cF=cF, nonval=nonval, capval=capval)
    capnode = lambda key, val=None, sp=None, closed=None, rd=None, status="Done": {"id": "1", "key": key, "webUrl": "x", "fields": {
        "customfield_10079": {"value": val} if val else None, "customfield_10038": sp, "customfield_10099": closed, "customfield_10098": None, "issuetype": {"name": "Story"}, "status": {"name": status},
        "resolutiondate": rd or stamp(TODAY)}}
    fx.capnode = capnode
    V = C["values"]
    fx.capnodes = [
        capnode(f"PMN-{cA['n']}", V[capval], 7, stamp(day_of(cA))),                                        # A: flips to capitalized, new points
        capnode(f"PMN-{cB['n']}", V[capval], 2, stamp(day_of(cB)), status="In Progress"),                  # B: no longer Done: deleted
        capnode(f"PMN-{cC['n']}", V[capval], 2, stamp(day_of(cC)), status="Removed"),                      # C: Removed: deleted
        capnode(f"PMN-{cD['n']}", V[capval], int(float(cD["sp"])), stamp(TODAY)),                          # D: Closed day now in the current quarter
        capnode(f"PMN-{cE['n']}", V[nonval], 9, stamp(day_of(cE))),                                        # E: points changed
        capnode("PMN-98901", V[capval], 4, None, stamp(TODAY, "11:00")),                                    # a new Done issue with no Closed date: the resolution date stands in
        capnode("PMN-98902", V[capval], 5, stamp(TODAY, "12:00")),                                          # a new Done issue closed today
    ]
    # ---- Open CFBs
    cfbnode = lambda key, status="In Progress", rca=None, rv=None, **f: {"id": "1", "key": key, "webUrl": "x", "fields": {
        "summary": "CFB " + key, "status": {"name": status}, "issuetype": {"name": "Bug"}, "priority": {"name": "P2"}, "created": stamp(TODAY, "06:00"), "updated": stamp(TODAY, "07:00"),
        "reporter": {"accountId": "someone"}, "customfield_10329": "SF-1", "customfield_10117": rca, "customfield_12643": {"value": rv} if rv else None, **f}}
    fx.cfbnode = cfbnode
    fx.opencfb = [cfbnode(oA["k"], rca=EDITED_TXT), cfbnode(oB["k"], rca=TEMPLATE_TXT), cfbnode(oE["k"], rca=TEMPLATE_TXT, customfield_10055={"value": "Yes"}), cfbnode(S["newCfb"], rca=EDITED_TXT, rv="Approved")]
    fx.leftcfb = [cfbnode(oC["k"], status="Done", resolutiondate=stamp(TODAY, "10:00"), resolution={"name": "Fixed"}, customfield_10099=stamp(TODAY, "10:00")),
                  cfbnode(oD["k"], status="Ready for Deploy", resolutiondate=stamp(TODAY, "10:00"), resolution={"name": "Fixed"}, customfield_10051=stamp(TODAY, "09:00"))]
    fx.oA, fx.oB, fx.oC, fx.oD, fx.oE = oA, oB, oC, oD, oE
    # ---- Capabilities
    fx.capsnodes = [{"id": "1", "key": cap_key, "webUrl": "x", "fields": {"summary": hier[cap_key]["t"], "status": {"name": "In Progress"}, "issuetype": {"name": "Capability"}, "fixVersions": fv27, "project": {"key": "CXCROSS"}, "customfield_10136": {"value": "Revised Level", "id": "12399"}}}]
    # ---- Dependency links: an epic whose links changed (one pair dropped, a Dependency to a known epic, a Blocks from an unknown far end, a link to a Removed issue, another link type)
    lnk = lambda ty, k, status="In Progress", outward=True: {"type": {"name": ty}, ("outwardIssue" if outward else "inwardIssue"): {"key": k, "fields": {"status": {"name": status}, "issuetype": {"name": "Epic"}}}}
    fx.linknodes = [{"id": "1", "key": E1, "webUrl": "x", "fields": {"status": {"name": "In Progress"}, "issuelinks": [lnk("Dependency", E2), lnk("Blocks", "EXA-98001", outward=False), lnk("Dependency", "EXA-98002", status="Removed"), lnk("Relates", "EXA-98003")]}}]
    fx.farnodes = [{"id": "1", "key": "EXA-98001", "webUrl": "x", "fields": {"summary": "Far end story", "status": {"name": "In Progress"}, "issuetype": {"name": "Story"}, "fixVersions": fv27, "project": {"key": "EXA"},
                                                                                "customfield_10098": {"value": MS.TEAMS["PMN"][0]}}}]
    fx.tplhash = S["tplHash"]
    _FX = fx
    return fx


# ---------------------------------------------------------------- running one scenario in the page
_CACHE: dict[str, dict] = {}


def js_json(x) -> str:
    return json.dumps(x, ensure_ascii=False).replace("</", "<\\/")


def scenario(mode="ok", ls="recent", click=True, shift_ms=0, hook=None, slow=0, fast=False, wait="done", timeout=25.0, extra="", settle=1.5, wait_js=None, cache=True, **over) -> dict:
    """Load the page with the mocked connector and return the page's own snapshot (before, after, status text, calls ...).
    wait: "done" (the refresh went busy and is usable again), "none" (a bounded settle, for tests that expect NO refresh) or "js" (wait_js)."""
    fx = build_fixture()
    cfg = dict(mode=mode, ls=ls, shift=int(shift_ms), slow=slow, fastTimers=fast, page1=fx.page1, page2=fx.page2, capsnodes=fx.capsnodes, opencfb=fx.opencfb, linknodes=fx.linknodes,
               farnodes=fx.farnodes, leftcfb=fx.leftcfb, capnodes=fx.capnodes, axkey=fx.S["axBug"])
    cfg.update(over)
    key = json.dumps([mode, ls, click, shift_ms, hook, slow, fast, wait, extra, wait_js, {k: v for k, v in over.items()}], sort_keys=True, default=str)
    if cache and key in _CACHE:
        return _CACHE[key]
    prelude = "<script data-harness>" + (HERE / "mock_claude.js").read_text().replace("/*__CFG__*/null", js_json(cfg)).replace("/*__HOOK__*/null", hook or "null") + "</script>"
    probe = "<script data-harness>" + (HERE / "probe.js").read_text().replace("/*__SUBJ__*/null", js_json(fx.S)) + "</script>"
    url = ctx.write(kit.wrap(fx.fragment, prelude, probe), "scn")
    ch = ctx.chrome
    ch.goto(url)
    assert ch.js("typeof window.__collect") == "function", "the probe did not load: " + str(ch.console_errors()[:3])
    if click:
        ch.js("document.getElementById('refresh').click()")
    if extra:
        ch.js(extra)
    timed_out = False
    if wait == "done":
        timed_out = not ch.wait_for("window.__done === true", timeout)
    elif wait == "js":
        timed_out = not ch.wait_for(wait_js, timeout)
    else:
        time.sleep(settle)
    res = json.loads(ch.js("JSON.stringify(window.__collect())"))
    res["timed_out"] = timed_out
    res["errors"] = ch.console_errors()
    res["statusKind"] = ch.js("(document.querySelector('#status .msg')||{}).className || ''")
    if cache:
        _CACHE[key] = res
    return res


def il_label(iso: str) -> str:
    """The page's ilLabel() of an ISO stamp: Israel-local 'YYYY-MM-DD HH:MM Israel time'."""
    x = re.sub(r"([+-]\d\d)(\d\d)$", r"\1:\2", iso.replace("Z", "+00:00"))
    return dt.datetime.fromisoformat(x).astimezone(MS.IL).strftime("%Y-%m-%d %H:%M") + " Israel time"


def live_oldest(snap) -> str:
    """The oldest of the five live sources, from a page snapshot after a refresh (independent of the page's own sourceTimes())."""
    ts = [snap["refreshedAt"], snap["linksAt"], snap["capPulledAt"]]
    f = lambda x: dt.datetime.fromisoformat(re.sub(r"([+-]\d\d)(\d\d)$", r"\1:\2", x.replace("Z", "+00:00")))
    return min(ts, key=f)


def calls_of(r, frag):
    return [c for c in r["calls"] if frag in c["jql"]]


MAIN_Q = "issuetype in (Epic, Bug)"
rows_of = lambda crow, s: [crow(l) for l in s.split(";")]


def run(mode, label, **kw):
    return scenario(mode=mode, **kw)


# ================================================================ the fixture itself
@SUITE.test("fixture_h53_matches_the_page")
def _(t: T):
    """The template hashes the generator writes (RCA templates) must be the ones the page computes, or the RCA classification tests prove nothing."""
    build_fixture()
    r = scenario()                                                               # any page will do; h53 is a global function of the template
    ch = ctx.chrome
    for s in ("abc", "synthetic template text one", "unicode é中"):
        t.check(ch.js(f"h53({json.dumps(s)})") == MS.h53(s), f"h53({s!r}) is the same in Python and in the page")
    t.check(not r["errors"], f"no uncaught page errors while loading: {r['errors'][:2]}")


@SUITE.test("fixture_schema_parity_with_real_data")
def _(t: T):
    """Same top-level keys and record keys as build/program_data.json (read for its shape only, when the file exists)."""
    real = next((p for p in (kit.REPO / "program_dashboard" / "build" / "program_data.json", kit.FROZEN / "program_data.json") if p.exists()), None)
    if not real:
        raise Skip("no build/program_data.json here (it is git-ignored); the shape check needs it")
    R = json.loads(real.read_text())
    D = build_fixture().data
    SCHEMA2 = {"cycles", "quality", "bugsPulledAt", "linksPulledAt", "schema", "defs", "build"}       # schema 2 dropped the two dead sections and added two pull times; the synthetic payload also serves the frozen v52 page
    t.check(set(D) - SCHEMA2 == set(R) - SCHEMA2, f"top-level keys differ: only synthetic {sorted(set(D) - set(R) - SCHEMA2)}, only real {sorted(set(R) - set(D) - SCHEMA2)}")
    keys = lambda lst: set().union(*(set(x) for x in lst))
    t.check(keys(D["epics"]) == keys(R["epics"]), f"epic keys: synthetic {sorted(keys(D['epics']))} vs real {sorted(keys(R['epics']))}")
    t.check(keys(D["bugs"]) == keys(R["bugs"]), f"bug keys: synthetic {sorted(keys(D['bugs']))} vs real {sorted(keys(R['bugs']))}")
    t.check(set(D["cap"]) == set(R["cap"]), "capitalization block keys")
    t.check(set(D["cfbx"]) == set(R["cfbx"]), "cfbx block keys")
    for k in ("hier", "capList", "ext", "sinfo"):
        t.check(keys(D[k].values()) <= keys(R[k].values()), f"{k} record keys are a subset of the real ones")
    t.check(D["sprints"][0].keys() == R["sprints"][0].keys(), "sprint keys")


@SUITE.test("back_to_top_shows_on_scroll_up_hides_on_scroll_down_and_at_the_top_and_returns_to_the_top")
def _(t: T):
    """The button appears after a scroll up from deep in the page, goes away on scroll down and at the top, and a click returns to the top with the heading focused."""
    fx = build_fixture()
    ch = ctx.chrome
    ch.goto(ctx.write(fx.fragment, "plain"))
    kit.wait_ready(ch, 15)
    time.sleep(1.2)                                                # the page ignores scrolls for a moment after a redraw
    state = lambda: json.loads(ch.js("JSON.stringify({on: document.getElementById('totop').classList.contains('on'), hidden: document.getElementById('totop').hidden, y: Math.round(window.scrollY), h1: document.activeElement && document.activeElement.tagName})"))
    ch.js("window.scrollTo(0, window.innerHeight * 3)"); time.sleep(0.4)
    ch.js("window.scrollBy(0, -60)"); time.sleep(0.4)
    s = state()
    t.check(s["on"] and not s["hidden"], f"after a scroll up from deep in the page the button is shown: {s}")
    ch.js("window.scrollBy(0, 250)"); time.sleep(0.6)
    s = state()
    t.check(not s["on"] and s["hidden"], f"a scroll down hides it: {s}")
    ch.js("window.scrollTo(0, window.innerHeight * 3)"); time.sleep(0.3); ch.js("window.scrollBy(0, -60)"); time.sleep(0.4)
    ch.js("window.scrollTo(0, 0)"); time.sleep(0.6)
    s = state()
    t.check(not s["on"] and s["hidden"], f"at the top it is hidden: {s}")
    ch.js("window.scrollTo(0, window.innerHeight * 3)"); time.sleep(0.3); ch.js("window.scrollBy(0, -60)"); time.sleep(0.4)
    ch.js("document.getElementById('totop').click()"); time.sleep(2.0)
    s = state()
    t.check(s["y"] <= 2 and s["h1"] == "H1" and not s["on"], f"a click returns to the top with the heading focused and hides the button: {s}")


@SUITE.test("fixture_renders_every_section_without_errors")
def _(t: T):
    fx = build_fixture()
    url = ctx.write(fx.fragment, "plain")
    ch = ctx.chrome
    ch.goto(url)
    kit.wait_ready(ch, 15)
    t.check(not ch.console_errors(), f"no uncaught page errors: {ch.console_errors()[:2]}")
    for h in ("h-attn", "h-burnup", "h-eff", "h-ai", "h-bugs", "h-cfb", "h-deps", "h-capview", "h-cx", "h-nfr", "h-cycles", "h-analysis"):
        n = ch.js(f"(()=>{{const h=document.getElementById({h!r}); const s=h&&(h.closest('section')||h.parentElement); return s?s.innerText.length:-1}})()")
        t.check(n and n > 150, f"section {h} has content ({n} characters)")
    for sel, what in (("#capz-svg svg rect", "capitalization bars"), ("#bug-table table", "open bugs table"), ("#cfb-table table, #cfb-table .tablewrap", "CFB table"), (".bcard", "dependency cards"), ("#cx-body table", "CXCROSS table")):
        t.check(ch.js(f"document.querySelectorAll({sel!r}).length") > 0, f"{what} render")


@SUITE.test("edct_in_the_page_equals_the_collectors_day_accounting")
def _(t: T):
    """The page computes the cycle time of epics that closed after the build (epicDays); it must give exactly what the collector gives (day_counts over edct_from_jira.epic_events)
    on the same histories: day ends in the offset of the first change, flagged days excluded, the resolution day not counted, status changes after midnight."""
    sys.path.insert(0, str(kit.REPO / "program_dashboard")); sys.path.insert(0, str(kit.REPO / "dashboards"))
    import build_dashboard as BD
    import edct_from_jira as E
    st = lambda c, to: {"created": c, "items": [{"field": "status", "toString": to}]}
    fl = lambda c, to: {"created": c, "items": [{"field": "Flagged", "toString": to}]}
    cases = [
        ([st("2026-10-23T10:07:22.701+0300", "Done"), st("2026-10-23T10:07:14.473+0300", "Validation"), st("2026-10-15T15:32:43.189+0300", "In Progress"), st("2026-10-13T18:10:35.858+0300", "Ready for Dev")], "2026-10-23"),
        ([st("2026-10-23T10:07:22.701+0300", "Done"), fl("2026-10-19T09:00:00.000+0300", None), fl("2026-10-17T09:00:00.000+0300", "Impediment"), st("2026-10-15T15:32:43.189+0300", "In Progress")], "2026-10-23"),
        ([st("2026-03-01T23:59:00.000+0200", "In Progress"), st("2026-03-04T00:01:00.000+0200", "Validation"), st("2026-03-06T00:00:00.000+0200", "Done")], "2026-03-06"),
        ([st("2026-03-01T23:30:00.000-0500", "In Progress"), st("2026-03-02T22:00:00.000-0500", "Validation"), st("2026-03-09T09:00:00.000-0500", "Done")], "2026-03-09"),
        ([st("2026-05-02T10:00:00.000+0300", "In Progress"), st("2026-05-02T10:00:00.000+0300", "Validation"), st("2026-05-05T10:00:00.000+0300", "Done")], "2026-05-05"),
        ([st("2026-05-02T10:00:00.000+0300", "Done")], "2026-05-02"),
    ]
    fx = build_fixture()
    ch = ctx.chrome
    ch.goto(ctx.write(fx.fragment, "plain"))
    kit.wait_ready(ch, 15)
    for i, (hist, rd) in enumerate(cases):
        ip, vl = BD.day_counts(E.epic_events(hist), dt.date.fromisoformat(rd))
        got = json.loads(ch.js(f"JSON.stringify(epicDays({json.dumps(hist)}, {rd!r}))"))
        t.check(got["ip"] == ip and got["vl"] == vl, f"case {i}: page {got['ip']} + {got['vl']} days, collector {ip} + {vl}")


# ================================================================ the ported refresh checks (one scenario, many named groups)
def ok():
    return scenario("ok")


@SUITE.test("refresh_queries_are_incremental_and_cursor_driven")
def _(t: T):
    r = ok()
    C = r["calls"]
    t.check(any(c["jql"].startswith("project in (") and MAIN_Q in c["jql"] and "updated >=" in c["jql"] and "updated <" in c["jql"] for c in C), "the epic and bug query is read in `updated` windows (so a project can never hit the page limit)")
    t.check(any(c["token"] == "cursor-1" for c in C), "a later call carried the cursor from the first page as nextPageToken")
    t.check(all(c["server"] == "Atlassian" and c["tool"] in ("searchJiraIssuesUsingJql", "getJiraIssue") and c["opts"] == {"cache": False} for c in C), "every call used the declared server and a declared tool, uncached")
    t.check(all("updated >=" in c["jql"] for c in C if MAIN_Q in c["jql"] or "issuetype in (Bug, Story, Task)" in c["jql"]), "epic, bug and capitalization queries are incremental (updated >= since)")
    projs = ("PMN", "CXCO", "CXSUP", "CXWFM", "WFM", "CXINT", "INT")
    firsts = {p: next((x for x in C if x["jql"].startswith(f"project = {kit.jqlkey(p)} AND issuetype in (Bug, Story, Task)")), None) for p in projs}
    t.check(all(firsts.values()) and all(c["jql"].startswith(f"project = {kit.jqlkey(p)} AND issuetype in (Bug, Story, Task) AND updated >=") for p, c in firsts.items()) and not any("sprint" in c["jql"] for c in C),
            "one capitalization delta query per dashboard project (any status, by `updated`), no sprint in the query")
    t.check(any(c["jql"].startswith('project = "INT" AND issuetype in (Bug, Story, Task)') for c in C) and any('"INT"' in c["jql"] and c["jql"].startswith("project in (") for c in C),
            "the reserved project key INT is quoted in the per-project and the project-list queries (the mocked Jira refuses it bare, as the real one does)")
    t.check(any("issuetype = Capability AND (updated >=" in c["jql"] for c in C), "Capabilities changed since the snapshot are read")
    t.check(not ok()["errors"], f"no uncaught page errors: {ok()['errors'][:2]}")


@SUITE.test("refresh_merges_epics_and_bugs")
def _(t: T):
    fx, r = build_fixture(), ok()
    a, b, S = r["after"], r["before"], fx.S
    t.check(a["e_status"]["s"] == "Done" and a["e_status"]["rd"] == TODAY_S, "epic that became Done now shows Done with today's resolution date")
    t.check(a["e_status"].get("edct") == 6 and a["e_status"].get("cal") == 6, f"an epic that became Done is given its cycle time during the Refresh (history read through the connector: 3 days In Progress + 3 Validation) -> {a['e_status'].get('edct')}, {a['e_status'].get('cal')}")
    t.check(a["e_removed"] is False, "epic that became Removed was dropped")
    t.check(a["e_moved"]["fv"] == ["27.2"] and a["e_moved"]["ad"]["27.2"] == TODAY_S, "epic moved to 27.2 left 27.1 and joined 27.2 today")
    t.check(a["e_new"] and a["e_new"]["ad"]["27.1"] == TODAY_S and a["e_new"]["tm"] == [MS.TEAMS["PMN"][0]], "new epic added with its join date and team")
    t.check(a["b_new"] and not a["b_new"].get("ax") and a["b_new"]["tm"] == MS.TEAMS["PMN"][0], "new bug added (not accessibility) with its team")
    t.check(a["b_ax"] and a["b_ax"].get("ax") == 1, "bug found by the accessibility query is flagged and so excluded by default")
    t.check(a["b_resolved"].get("rd") == TODAY_S, "open bug that was fixed now carries a resolution date")
    t.check(a["pmn_open"] == b["pmn_open"] + 1 - 1, f"PMN open bugs (excl. accessibility): {b['pmn_open']} -> {a['pmn_open']} (+1 new bug, -1 fixed)")
    t.check(a["epics"] == b["epics"] - 1 + 1, f"epic count: {b['epics']} -> {a['epics']} (-1 removed, +1 new)")
    t.check(r["badge"] == "Refreshed" and "Refreshed" in r["meta"] and "10 epics and 5 bugs changed" in r["meta"], f"header says refreshed with counts: {r['meta'][:110]}")
    t.check(not r["disabled"] and r["btn"] == "Refresh from Jira", "button re-enabled with its normal label")


@SUITE.test("refresh_dependency_card_stays_in_its_sprint")
def _(t: T):
    fx, r = build_fixture(), ok()
    no = fx.sprint[fx.ep[fx.S["eDep"]]["ts"]]["no"]
    t.check(r["before"]["depCol"] and r["before"]["depCol"].startswith(f"Sprint {no},"), f"before: the dependency card of the provider epic sits in Sprint {no}: {r['before']['depCol']}")
    t.check(r["after"]["depCol"] and r["after"]["depCol"].startswith(f"Sprint {no},"), f"after Refresh: it still sits in Sprint {no} (not Not Planned): {r['after']['depCol']}")


@SUITE.test("refresh_planning_fields_merge_not_rebuild")
def _(t: T):
    fx, r = build_fixture(), ok()
    a, b = r["after"], r["before"]
    e = fx.ep[fx.S["eDep"]]
    dd = (dt.date.fromisoformat(fx.sprint[e["ts"]]["start"]) + dt.timedelta(days=4)).isoformat()
    t.check(a["dep"]["dd"] == dd and a["dep"]["ts"] == e["ts"] and a["dep"]["cp"] == e["cp"] and "as" not in a["dep"] and a["dep"]["ud"] == TODAY_S,
            "updated epic with planning fields in the response: dd, ts (option object normalised), cp set, ud = today, and the assignee in the response is not stored")
    t.check(all(a["keep"].get(k) == b["keep"].get(k) and k in a["keep"] for k in ("dd", "ts", "cp", "ud", "ip", "vl", "edct", "cal")), "epic whose response has no planning fields keeps dd, ts, cp, ud and its cycle time (ip, vl, edct, cal)")
    t.check("dd" not in a["clr"] and a["clr"]["ts"] == b["clr"]["ts"] and a["clr"].get("cp") == b["clr"].get("cp"), "due date null in the response clears dd only; absent Target Sprint and parent stay")
    t.check(all(a["cdone"].get(k) == b["cdone"].get(k) and k in a["cdone"] for k in ("cfb", "rb", "sf", "cl", "inc")), "Done CFB whose response lacks reporter, case, Closed, incidents keeps cfb, rb, sf, cl, inc")
    t.check(a["copen"]["ud"] == TODAY_S and a["copen"].get("rb") and a["copen"].get("sf") and a["copen"].get("cfb"), "open CFB edited today gets ud = today and keeps rb, sf")


@SUITE.test("refresh_pod_labels")
def _(t: T):
    r = ok()
    a, b = r["after"], r["before"]
    t.check(a["plset"]["pl"] == ["Pod-Zulu-9"], "labels returned with a new pod label: pl holds only the label the project pattern matches")
    t.check("pl" not in a["plclr"], "labels returned empty clears the pod labels")
    t.check(a["plkeep"]["pl"] == b["plkeep"]["pl"], "no labels field in the response: the pod labels stay")


@SUITE.test("refresh_status_checklist")
def _(t: T):
    r = ok()
    s = r["status"]
    t.check(s.startswith("Refreshed ") and " epics and " in s and " changed." in s, "the result is one plain sentence: when it refreshed and how many epics and bugs changed: " + s[:160])
    t.check("rebuild" not in s and "newly Done" not in s, "nothing needs a rebuild: the cycle time of the newly Done epic was read during the Refresh, and there is no standing boilerplate: " + s[:230])
    t.check("Capitalization" not in s and "open CFBs" not in s and len(s) < 220, f"it carries no per-step list: {len(s)} characters")


@SUITE.test("refresh_capitalization_delta_every_quarter")
def _(t: T):
    fx, r = build_fixture(), ok()
    a, b, K = r["after"], r["before"], fx.cap
    A = {(x["p"], x["n"]): x for x in rows_of(fx.crow, a["capRows"])}
    B = {(x["p"], x["n"]): x for x in rows_of(fx.crow, b["capRows"])}
    rowsA, rowsB = rows_of(fx.crow, a["capRows"]), rows_of(fx.crow, b["capRows"])
    day = lambda x: fx.day_of(x)
    t.check(int(A[("0", K["cA"]["n"])]["v"]) == K["capval"] and A[("0", K["cA"]["n"])]["sp"] == "7" and A[("0", K["cA"]["n"])]["cd"] == K["cA"]["cd"], "an EARLIER-quarter issue that was flagged capitalized after the pull is updated (value and points), its Closed day unchanged")
    t.check(("0", K["cB"]["n"]) not in A, "an earlier-quarter issue that left Done was deleted")
    t.check(("0", K["cC"]["n"]) not in A, "an earlier-quarter issue that was Removed was deleted")
    t.check(("0", K["cD"]["n"]) in A and day(A[("0", K["cD"]["n"])]) == TODAY, "an issue whose Closed day moved across a quarter boundary is stored with the new Closed day")
    t.check(A[("0", K["cE"]["n"])]["sp"] == "9" and int(A[("0", K["cE"]["n"])]["v"]) == K["nonval"], "a current-quarter issue with changed points and value is replaced")
    t.check(("0", K["cF"]["n"]) in A and A[("0", K["cF"]["n"])] == B[("0", K["cF"]["n"])], "a record the response did not return is untouched (absence never deletes)")
    t.check(("0", "98901") in A and A[("0", "98901")]["fb"] == "1" and day(A[("0", "98901")]) == TODAY, "a new Done issue with no Closed date is stored with its resolution date and the fallback flag")
    t.check(("0", "98902") in A and day(A[("0", "98902")]) == TODAY and A[("0", "98902")]["fb"] == "0", "a new Done issue closed today is inserted")
    t.check([",".join(x.values()) for x in rowsB if x["p"] != "0"] == [",".join(x.values()) for x in rowsA if x["p"] != "0"], "the records of every other project are byte-identical after the Refresh")
    t.check(len(rowsA) == len(rowsB) - 2 + 2, f"records: {len(rowsB)} -> {len(rowsA)} (two deleted, two new)")
    # Capitalization refreshes less often than the header's live sources, so its chart caption now names when it was last read (the old rule "no per-section stamp" is reversed on purpose)
    t.check(a["capAt"] is not None and f"refreshed {il_label(a['capAt'])}" in a["capNote"] and "as of" not in a["capNote"], f"after a Refresh the chart caption carries the refresh time of Capitalization: {a['capNote'][-70:]}")
    t.check("not refreshed yet" in b["capNote"] and "as of" not in b["capNote"], f"before it, the caption says it was not refreshed yet (there is no build value to show): {b['capNote'][-70:]}")


@SUITE.test("refresh_capabilities")
def _(t: T):
    fx, r = build_fixture(), ok()
    a, b = r["after"], r["before"]
    t.check(a["hierFv"] == ["27.1"] and b["hierFv"] == ["26.4"], f"the capability's fix version {b['hierFv']} -> {a['hierFv']} (a fix version moved after the pull) in the CXCROSS data")
    t.check(a["listFv"] == ["27.1"] and a["listS"] == "In Progress", f"the Capability list carries the new fix version and status: {a['listFv']} {a['listS']}")
    t.check(a["listCl"] == "Revised Level" and b["listCl"] != "Revised Level", f"the Capability's Commitment Level is read again (customfield_10136): {b['listCl']!r} -> {a['listCl']!r}")
    t.check(a["capNoFv"] == {"total": 2, "done": 1} and a["capPulledAt"] != b["capPulledAt"], f"the no-fix-version count is re-read: {a['capNoFv']}")


@SUITE.test("refresh_dependency_links")
def _(t: T):
    fx, r = build_fixture(), ok()
    a, b = r["after"], r["before"]
    E1, E2 = fx.E1, fx.E2
    newd = {(d[0], d[1]): d[2] for d in a["deps"]}
    t.check(newd.get((E1, E2)) == "D", f"a new Dependency link from a refreshed epic is added as a pair ({E1} -> {E2})")
    t.check(newd.get((E1, "EXA-98001")) == "B", "a Blocks link read from the blocked side is stored with the blocked epic as the dependent")
    t.check(not any("EXA-98002" in k or "EXA-98003" in k for k in newd), "a link to a Removed issue and a link of another type (Relates) are left out")
    t.check(all(k not in newd for d in fx.old_e1 for k in [(d[0], d[1])] if (d[0], d[1]) not in {(E1, E2), (E1, "EXA-98001")}), f"the {len(fx.old_e1)} earlier pair(s) of the refreshed epic that Jira no longer has were dropped")
    t.check([d for d in a["deps"] if E1 not in d[:2]] == [d for d in b["deps"] if E1 not in d[:2]], "every pair that does not touch the refreshed epic is byte-identical, in the same order")
    e = a["ext1"]
    t.check(e and e["p"] == "EXA" and e["t"] == "Far end story" and e.get("ty") == "Story" and e["tm"] == [MS.TEAMS["PMN"][0]], f"an unknown far-end issue was read once and stored with project, summary, type and team: {e}")
    t.check(a["linksAt"] and not b["linksAt"], "the links stamp moves to the refresh time")


@SUITE.test("refresh_step_fails_alone_cycle_time")
def _(t: T):
    f = scenario("edctfail")
    s, a = f["status"], f["after"]
    t.check(s.startswith("Refreshed ") and "Not refreshed, data unchanged: Cycle time (history boom)" in s, f"the message names the failed step with its reason -> {s[:200]}")
    t.check("edct" not in a["e_status"], "the epic's cycle time stays blank, and the rest of the Refresh was applied")
    t.check("newly Done" in s and "rebuild" in s, "what is still missing is said once: the epic has no cycle time yet")


@SUITE.test("refresh_one_stamp")
def _(t: T):
    a = ok()["after"]
    t.check(a["stampTxt"].startswith("Refreshed ") and a["stampTxt"].count("Data as of") == 0, f"for a few seconds after a Refresh the one stamp slot reads the refresh time: {a['stampTxt']}")
    t.check(a["stampTip"].startswith("Updated from Jira ") and "Refreshing" not in a["stampTip"] and "Epics:" not in a["stampTip"] and "Built from commit" not in a["stampTip"], f"the stamp tooltip is short and says it is updated, not still refreshing -> {a['stampTip'][:140]}")


def step_fail(t: T, mode, label, reason, same, moved):
    f = scenario(mode)
    A, B = f["after"], f["before"]
    s = f["status"]
    t.check(s.startswith("Refreshed ") and f"Not refreshed, data unchanged: {label} ({reason})" in s, f"{mode}: the message names the failed step with its reason -> {s[s.find('Not refreshed'):][:110]}")
    t.check(all(json.dumps(A.get(k)) == json.dumps(B.get(k)) for k in same), f"{mode}: the failed step left its own data byte-identical ({', '.join(same)})")
    t.check(all(json.dumps(A.get(k)) != json.dumps(B.get(k)) for k in moved), f"{mode}: every OTHER step still applied ({', '.join(moved)})")
    t.check(A["epics"] != 0 and A["e_new"] is not None, f"{mode}: epics and bugs refreshed independently of the failure")
    return f


@SUITE.test("refresh_step_fails_alone_capitalization")
def _(t: T):
    f = step_fail(t, "capfail", "Capitalization", "capitalization boom", ["capRows"], ["hierFv"])
    t.check("not refreshed: capitalization boom" in f["after"]["capNote"] and "as of" in f["after"]["capNote"], f"capfail: the chart caption says what was not refreshed and keeps the as-of time -> {f['after']['capNote'][-90:]}")
    stamp_ = f["after"]["stampTxt"]
    t.check(stamp_.startswith("Data as of ") and stamp_ == "Data as of " + il_label(live_oldest(f["after"])), f"capfail: the header stamp is the oldest LIVE source time -> {stamp_}")
    t.check("Capitalization not refreshed yet" in f["after"]["stampTip"], f"capfail: the failed limited step is named in the tooltip, not in the header -> {f['after']['stampTip'][:120]}")


@SUITE.test("refresh_step_fails_alone_dependency_links")
def _(t: T):
    step_fail(t, "linksfail", "Dependency links", "links boom", ["deps", "ext1"], ["capRows"])


@SUITE.test("refresh_step_fails_alone_capabilities")
def _(t: T):
    step_fail(t, "capsfail", "Capabilities", "capabilities boom", ["hierFv", "listFv"], ["capRows"])


@SUITE.test("refresh_empty_capitalization_response_never_deletes")
def _(t: T):
    fx = build_fixture()
    e = scenario("emptycap")
    t.check(e and not e["timed_out"], "emptycap: runs")
    n_after, n_before = len(rows_of(fx.crow, e["after"]["capRows"])), len(rows_of(fx.crow, e["before"]["capRows"]))
    t.check(n_after == n_before, f"an empty response never deletes: records {n_before} -> {n_after}")


@SUITE.test("refresh_denied_consent_manual")
def _(t: T):
    d = scenario("denied")
    t.check("was not allowed" in d["status"] and d["after"]["epics"] == d["before"]["epics"] and not d["disabled"], f"denied consent: clear message, data unchanged, button usable -> {d['status'][:90]}")


# ---------------------------------------------------------------- automatic refresh on open
@SUITE.test("auto_refresh_stamp_settles_to_one_data_as_of")
def _(t: T):
    st = scenario("ok", ls="recent", click=True, fast=True, wait="js", wait_js="window.__done === true && document.getElementById('asof').textContent.startsWith('Data as of')")
    t.check(not st["timed_out"] and st["stamps"] == 1 and st["after"]["stampTxt"].startswith("Data as of ") and st["after"]["stampTxt"].count("Data as of") == 1 and ";" not in st["after"]["stampTxt"] and "Capabilities" not in st["after"]["stampTxt"],
            f"after the checklist the header shows exactly one 'Data as of' stamp and no per-source list -> {st['hidden_stamps']}")


MID = ("window.__slowSet = 1; setTimeout(() => { const b = document.getElementById('refresh'); const chip = [...document.querySelectorAll('#f-projects .chip')][2]; const before = localStorage.getItem('delivery-pulse-filters'); if (chip) chip.click(); "
       "window.__mid = {disabled: b.disabled, label: b.textContent.trim(), status: document.getElementById('status').textContent, filterChanged: localStorage.getItem('delivery-pulse-filters') !== before, stamp: document.getElementById('asof').textContent}; }, 700);")


def auto(**kw):
    return scenario("ok", ls="none", click=False, fast=True, wait="js", wait_js="window.__done === true && document.getElementById('asof').textContent.startsWith('Data as of')", **kw)


@SUITE.test("auto_refresh_on_open_runs_once_and_stays_usable")
def _(t: T):
    au = auto(slow=60, extra=MID)
    nrefresh = [c for c in au["calls"] if MAIN_Q in c["jql"]]
    first_pages = [c for c in nrefresh if not c["token"]]
    t.check(not au["timed_out"], "the automatic refresh finished")
    t.check(len(nrefresh) >= 1 and "Updated from Jira " in au["after"]["stampTip"], f"auto-refresh on open: one automatic Refresh ran after the first paint with no click -> {au['after']['stampTip'][-90:]}")
    t.check(len({c["jql"] for c in first_pages}) == len(first_pages), "auto-refresh on open: it ran ONCE (no identical query started twice)")
    t.check(au["mid"] and au["mid"]["disabled"] and au["mid"]["label"].startswith("Refreshing"), f"auto-refresh: while it runs the button is disabled and says Refreshing -> {au['mid']}")
    t.check(au["mid"] and au["mid"]["status"].startswith("Updating live data:"), f"auto-refresh: progress reads 'Updating live data: ...' -> {au['mid'] and au['mid']['status'][:70]}")
    t.check(au["mid"] and au["mid"]["filterChanged"], "auto-refresh: the filters stay usable while it runs (a project chip click changed the saved filters)")
    t.check(au["ls"] and abs(int(au["ls"]) / 1000 - time.time()) < 120, "auto-refresh: the successful refresh time is kept in localStorage (per-viewer convenience)")
    t.check(au["stamps"] == 1 and au["after"]["stampTxt"].startswith("Data as of "), f"the header shows exactly one 'Data as of' stamp in the DOM text (found {au['stamps']}): {au['after']['stampTxt']}")
    t.check(not au["disabled"] and au["btn"] == "Refresh from Jira", "auto-refresh: the button is usable again at the end")


@SUITE.test("auto_refresh_runs_even_when_the_last_refresh_was_recent")
def _(t: T):
    """The 15-minute guard is off (LIVE_GUARD_MS = 0): every open of the published page reads the live data, so a reload never shows older data. (ls="recent" in the other cases drops the automatic refresh in the mock, so they stay about clicks.)"""
    r = scenario("ok", ls="recentauto", click=False, cache=False)
    t.check(bool([c for c in r["calls"] if MAIN_Q in c["jql"]]), "auto-refresh runs although the last refresh was less than 15 minutes ago")


@SUITE.test("auto_refresh_runs_when_last_refresh_was_an_hour_ago")
def _(t: T):
    od = scenario("ok", ls="old", click=False)
    t.check([c for c in od["calls"] if MAIN_Q in c["jql"]], "auto-refresh runs when the last refresh was an hour ago")


@SUITE.test("auto_refresh_works_with_blocked_local_storage")
def _(t: T):
    bl = scenario("ok", ls="blocked", click=False)
    t.check("Updated from Jira " in bl["after"]["stampTip"], f"auto-refresh still works when localStorage is blocked (try/catch) -> {bl['after']['stampTip'][-60:]}")


@SUITE.test("auto_refresh_consent_declined_is_calm_and_retry_is_rate_limited")
def _(t: T):
    dn = scenario("denied", ls="none", click=False)
    t.check("Showing the snapshot from" in dn["status"] and "Refresh needs Jira access" in dn["status"] and dn["retry"], f"consent declined on open: a calm persistent note with a Retry button -> {dn['status'][:110]}")
    t.check(len(dn["calls"]) == 1, f"consent declined on open: exactly one attempt, no loop ({len(dn['calls'])} call)")
    t.check(not dn["disabled"] and dn["after"]["epics"] == dn["before"]["epics"], "consent declined on open: button usable, data unchanged")
    retry = ("setTimeout(() => { const r = document.getElementById('refresh-retry'); if (r) r.click(); }, 700); "
             "setTimeout(() => { const r = document.getElementById('refresh-retry'); if (r) r.click(); }, 900);")
    rt = scenario("denied", ls="none", click=False, extra=retry, wait="js", wait_js="window.__calls.length >= 2", settle=1.5)
    time.sleep(0.8)                                                                # a third call would arrive within this bounded settle
    n = ctx.chrome.js("window.__calls.length")
    t.check(2 <= n <= 3, f"Retry tries again but rapid repeats are rate-limited ({n} calls for 1 auto + 2 quick Retry clicks)")


@SUITE.test("mock_clock_quarter_gap_is_read_from_the_snapshot_day")
def _(t: T):
    """F4: the time-based delta resolves a quarter gap: an issue closed in the previous quarter AND one closed in the new quarter both arrive."""
    fx = build_fixture()
    nm = (TODAY.month - 1) // 3 * 3 + 4
    qn = dt.date(TODAY.year + (nm > 12), nm - 12 if nm > 12 else nm, 1)                                                     # the first day of the next calendar quarter
    clk, gap = qn + dt.timedelta(days=11), qn - dt.timedelta(days=2)
    target = dt.datetime(clk.year, clk.month, clk.day, 9, 0, 20, tzinfo=MS.IL)
    shift = int((target - dt.datetime.now(MS.IL)).total_seconds() * 1000)
    V = fx.data["cap"]["values"]
    nodes = [fx.capnode("PMN-98801", V[fx.cap["capval"]], 3, stamp(gap)), fx.capnode("PMN-98802", V[fx.cap["capval"]], 5, stamp(clk, "10:00"))]
    ck = scenario("ok", ls="none", click=False, shift_ms=shift, capnodes=nodes, timeout=40)
    t.check(not ck["timed_out"], "the refresh ran on the shifted clock")
    rowsK = {x["n"]: x for x in rows_of(fx.crow, ck["after"]["capRows"]) if x["p"] == "0"}
    calls = [c["jql"] for c in ck["calls"] if "issuetype in (Bug, Story, Task)" in c["jql"]]
    starts = sorted(re.findall(r'updated >= "(\d{4}-\d{2}-\d{2})"', " ".join(calls)))
    ends = sorted(re.findall(r'updated < "(\d{4}-\d{2}-\d{2})"', " ".join(calls)))
    t.check(bool(starts) and starts[0] <= fx.gen_day.isoformat() and ends[-1] > clk.isoformat(), f"clock {clk}: the delta reads from the snapshot day ({starts[:1]}), not from a quarter start, up to {ends[-1:]} -> {len(calls)} capitalization calls")
    t.check("98801" in rowsK and "98802" in rowsK, f"clock {clk}: an issue closed {gap} (previous quarter) AND one closed {clk} both arrive")
    t.check((ck["after"]["refreshedAt"] or "").startswith(clk.isoformat()) and ("Refreshed 09:0" in ck["after"]["stampTxt"] or clk.isoformat() in ck["after"]["stampTxt"]), f"clock {clk}: the stamp carries the new date -> {ck['after']['stampTxt']} {ck['after']['refreshedAt']}")


# ================================================================ F15: the failure matrix
FIRST_MAIN_PAGE = f"input.jql.includes({MAIN_Q!r}) && !input.nextPageToken"


@SUITE.test("f15a_retryable_error_is_retried_once_then_succeeds")
def _(t: T):
    hook = f"async (input, c) => {{ if ({FIRST_MAIN_PAGE} && !window.__flaky) {{ window.__flaky = 1; throw {{code: 'tool_error', message: 'temporarily unavailable', retryable: true, retryAfterMs: 20}}; }} }}"
    r = scenario("ok", hook=hook)
    q = [c["jql"] for c in r["calls"] if MAIN_Q in c["jql"] and not c["token"]]
    first = q[0]
    t.check(q.count(first) == 2, f"the failed query was sent twice (one retry): {q.count(first)} times")
    t.check(r["status"].startswith("Refreshed ") and not r["timed_out"], f"after the retry the refresh completes normally -> {r['status'][:80]}")
    t.check(r["after"]["e_new"] is not None and r["after"]["e_status"]["s"] == "Done", "the data of the retried read was applied")
    # two retryable errors in a row: the page retries ONCE, then reports the error and applies nothing
    hook2 = f"async (input, c) => {{ if ({FIRST_MAIN_PAGE}) {{ throw {{code: 'tool_error', message: 'still unavailable', retryable: true, retryAfterMs: 20}}; }} }}"
    r2 = scenario("ok", hook=hook2)
    q2 = [c for c in r2["calls"] if MAIN_Q in c["jql"] and not c["token"]]
    t.check(len(q2) == 2, f"two retryable errors: exactly two attempts, no loop ({len(q2)})")
    t.check("Jira reported an error: still unavailable" in r2["status"], f"the second failure is shown with its message -> {r2['status'][:90]}")
    t.check(r2["after"]["epics"] == r2["before"]["epics"] and r2["after"]["e_new"] is None and not r2["disabled"], "nothing was applied and the button is usable again")
    t.check(not r["errors"] and not r2["errors"], "no uncaught page errors")


def _window_hook(truncate_all: bool) -> str:
    """Every window of the epic and bug query that spans more than one day returns endless pages (the page limit is hit); a one-day window answers with
    one epic of its own (or, with truncate_all, also endless pages)."""
    return f"""async (input, c) => {{
  if (!input.jql.includes({MAIN_Q!r})) return;
  const m = input.jql.match(/updated >= "(\\d{{4}}-\\d{{2}}-\\d{{2}})" AND updated < "(\\d{{4}}-\\d{{2}}-\\d{{2}})"/); if (!m) return;
  const days = (Date.parse(m[2]) - Date.parse(m[1])) / 86400000;
  if (days > 1 || {str(truncate_all).lower()}) return c.ok([], 'c' + c.idx);
  const key = 'PMN-982' + String(Math.round(Date.parse(m[1]) / 86400000) % 100).padStart(2, '0');
  return c.ok([{{id: '1', key, webUrl: 'x', fields: {{summary: 'Window ' + m[1], issuetype: {{name: 'Epic'}}, status: {{name: 'New'}}, created: '{TODAY_S}T08:00:00.000+0200', fixVersions: [{{name: '27.1'}}], customfield_10094: {{value: 'Committed'}}}}}}]);
}}"""


@SUITE.test("f15b_window_over_the_cap_is_halved_and_nothing_is_lost")
def _(t: T):
    r = scenario("ok", hook=_window_hook(False), timeout=40)
    spans = []
    for c in r["calls"]:
        m = re.search(r'updated >= "(\d{4}-\d{2}-\d{2})" AND updated < "(\d{4}-\d{2}-\d{2})"', c["jql"])
        if m and MAIN_Q in c["jql"] and not c["token"]:
            spans.append((m[1], m[2], (dt.date.fromisoformat(m[2]) - dt.date.fromisoformat(m[1])).days))
    t.check(not r["timed_out"] and r["status"].startswith("Refreshed "), f"the refresh completes after halving -> {r['status'][:80]}")
    t.check(len(spans) > 1 and max(s[2] for s in spans) > 1 and min(s[2] for s in spans) == 1, f"a window that hit the limit was halved down to single days: spans {sorted({s[2] for s in spans})}")
    pages = Counter(c["jql"] for c in r["calls"] if MAIN_Q in c["jql"])
    t.check(max(pages.values()) <= 40, f"no window was read for more than the 40-page limit (most calls for one window: {max(pages.values())})")
    days = [s for s in spans if s[2] == 1]
    covered = sorted(s[0] for s in days)
    t.check(covered == sorted(set(covered)) and all((dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days == 1 for a, b in zip(covered, covered[1:])), f"the single-day windows are contiguous without gaps or repeats: {covered}")
    new_keys = ctx.chrome.js("DATA.epics.filter(e => /^PMN-982\\d\\d$/.test(e.k)).map(e => e.k)")
    t.check(len(new_keys) == len(days), f"every single-day window's epic arrived exactly once: {len(new_keys)} of {len(days)}")
    # a one-day window that still hits the limit is an error: nothing is applied half-way
    r2 = scenario("ok", hook=_window_hook(True), timeout=40)
    t.check("Jira reported an error: more than 4000 issues updated on" in r2["status"] and "ask for a full rebuild" in r2["status"], f"a one-day window that still hits the limit is reported -> {r2['status'][:110]}")
    t.check(r2["after"]["epics"] == r2["before"]["epics"] and r2["after"]["refreshedAt"] is None and not r2["disabled"], "and nothing was applied; the button is usable")


@SUITE.test("f15c_missing_end_cursor_does_not_loop_or_crash")
def _(t: T):
    nodes = js_json(build_fixture().page1)
    hook = f"async (input, c) => {{ if ({FIRST_MAIN_PAGE}) return {{payload: {{issues: {{nodes: {nodes}, pageInfo: {{hasNextPage: true, endCursor: null}}}}}}}}; }}"
    r = scenario("ok", hook=hook)
    q = [c for c in r["calls"] if MAIN_Q in c["jql"]]
    t.check(not r["timed_out"] and not r["disabled"], "the refresh finishes and the button is usable")
    t.check(len(q) == 1, f"the page does not follow a cursor it was not given (calls to the query: {len(q)})")
    t.check(not r["errors"], f"no uncaught page errors: {r['errors'][:2]}")
    t.note(f"OBSERVED today: the page treats that page as the last one; status kind '{r['statusKind']}': {r['status'][:100]}; page 2 data read: {r['after']['b_new'] is not None}")


@SUITE.test("f15c_missing_end_cursor_is_reported_as_incomplete", expect="CURSOR_GUARD")
def _(t: T):
    """hasNextPage=true without an endCursor means the read is incomplete; the page should say so (a warning) instead of reporting a clean Refresh."""
    nodes = js_json(build_fixture().page1)
    hook = f"async (input, c) => {{ if ({FIRST_MAIN_PAGE}) return {{payload: {{issues: {{nodes: {nodes}, pageInfo: {{hasNextPage: true, endCursor: null}}}}}}}}; }}"
    r = scenario("ok", hook=hook)
    warned = "warn" in r["statusKind"] or "bad" in r["statusKind"] or re.search(r"incomplete|only the first|could not read|more pages|cursor", r["status"], re.I)
    t.check(bool(warned), f"an incomplete read is flagged, not reported as a clean Refresh (kind '{r['statusKind']}': {r['status'][:90]})")


def _manual_error(code: str, msg: str = "boom"):
    hook = f"async (input, c) => {{ throw {{code: {code!r}, message: {msg!r}}}; }}"
    return scenario("ok", hook=hook)


@SUITE.test("f15d_needs_reauth_manual_refresh")
def _(t: T):
    r = _manual_error("needs_reauth")
    t.check("The Atlassian connection has expired. Reconnect it in claude.ai under Settings, then Connectors." in r["status"] and "warn" in r["statusKind"], f"the page says the connection expired (warn) -> {r['status'][:100]}")
    t.check(r["after"]["epics"] == r["before"]["epics"] and not r["disabled"] and len(r["calls"]) == 1, "data unchanged, button usable, one attempt")


@SUITE.test("f15d_blocked_by_policy_manual_refresh")
def _(t: T):
    r = _manual_error("blocked_by_policy")
    t.check("not allowed to read Jira for you (turned off or blocked by policy)" in r["status"] and "warn" in r["statusKind"], f"the page says reading Jira is blocked by policy (warn) -> {r['status'][:100]}")
    t.check(r["after"]["epics"] == r["before"]["epics"] and not r["disabled"] and len(r["calls"]) == 1, "data unchanged, button usable, one attempt")


@SUITE.test("f15d_reauth_and_policy_on_open_show_the_calm_snapshot_note")
def _(t: T):
    for code in ("needs_reauth", "blocked_by_policy"):
        hook = f"async (input, c) => {{ throw {{code: {code!r}, message: 'x'}}; }}"
        r = scenario("ok", ls="none", click=False, hook=hook)
        t.check("Showing the snapshot from" in r["status"] and r["retry"] and len(r["calls"]) == 1 and not r["disabled"], f"{code} on open: one attempt, a calm persistent note with Retry -> {r['status'][:100]}")
        t.note(f"OBSERVED today ({code}, automatic): {r['status'][:120]}")


@SUITE.test("f15e_a_call_that_never_resolves_ends_in_a_message", expect="DEADLINE")
def _(t: T):
    """Today nothing ends a callTool that never answers: the button stays on Refreshing for good. With a per-call deadline the page must
    re-enable the button and say what happened. The page's multi-second timers run 20 times faster here (mock_claude.js, fast=True), and a template that
    reads window.__dpCallDeadlineMs gets 800 ms, so a deadline of up to a minute fits the wait."""
    r = scenario("ok", hook="async (input, c) => new Promise(() => {})", fast=True, deadlineMs=800, timeout=DEADLINE_WAIT)           # every call hangs
    t.note(f"OBSERVED after up to {DEADLINE_WAIT:.0f}s (all calls hang): timed_out={r['timed_out']} button='{r['btn']}' disabled={r['disabled']} status='{r['status'][:90]}'")
    t.check(not r["timed_out"] and not r["disabled"] and r["btn"] == "Refresh from Jira", "the refresh ended and the button is usable again")
    t.check(re.search(r"timed out|did not respond|did not answer|no response|too long|timeout|not answer", r["status"], re.I) is not None, f"the status says Jira did not answer -> '{r['status'][:100]}'")
    t.check(not r["status"].startswith("Refreshed ") or "Not refreshed" in r["status"], "it is not reported as a clean Refresh")
    t.check(r["after"]["epics"] == r["before"]["epics"] and r["after"]["e_new"] is None, "nothing was applied half-way")
    # only the FIRST call hangs: a deadline with one retry may recover; either way the page must end usable and consistent
    r2 = scenario("ok", hook="async (input, c) => { if (c.idx === 0) return new Promise(() => {}); }", fast=True, deadlineMs=800, timeout=min(DEADLINE_WAIT, 6))
    t.note(f"OBSERVED (only the first call hangs): timed_out={r2['timed_out']} status='{r2['status'][:90]}'")
    t.check(not r2["timed_out"] and not r2["disabled"], "when only the first call hangs the refresh also ends and the button is usable")
    t.check((r2["status"].startswith("Refreshed ") and r2["after"]["e_new"] is not None) or (r2["after"]["epics"] == r2["before"]["epics"] and r2["after"]["e_new"] is None), "and the outcome is all or nothing: recovered with data applied, or a message with nothing applied")


def _fx_nodes():
    return build_fixture()


def _count_first_pages(r):
    return Counter(c["jql"] for c in r["calls"] if not c["token"])


@SUITE.test("f15f_timestamps_with_Z_and_plus_0300_get_the_israel_day")
def _(t: T):
    fx = build_fixture()
    V = fx.data["cap"]["values"]
    X = TODAY - dt.timedelta(days=3)
    cases = {"98801": f"{X}T22:30:00.000Z", "98802": f"{X}T23:30:00.000+0300", "98803": f"{X + dt.timedelta(days=1)}T01:30:00.000+0300", "98804": f"{X}T23:30:00.000-0500", "98805": f"{X}T00:15:00.000+0000"}
    capnodes = [fx.capnode(f"PMN-{n}", V[fx.cap["capval"]], 3, ts) for n, ts in cases.items()]
    zep = fx.node("PMN-98810", "Epic", status="Done", resolutiondate=f"{X}T22:30:00.000Z", fixVersions=[{"name": "27.1"}], customfield_10094={"value": "Committed"})
    r = scenario("ok", capnodes=fx.capnodes + capnodes, page2=fx.page2 + [zep])
    rows = {x["n"]: x for x in rows_of(fx.crow, r["after"]["capRows"]) if x["p"] == "0"}
    for n, ts in cases.items():
        got = fx.day_of(rows[n]).isoformat() if n in rows else None
        t.check(got == il_day_of(ts), f"capitalization day of {ts} is the Israel-local day {il_day_of(ts)} (page: {got})")
    ep = ctx.chrome.js("(DATA.epics.find(e => e.k === 'PMN-98810') || {}).rd")
    t.check(ep == f"{X}", f"an epic's resolution date keeps the date part Jira sent, exactly as the build does ([:10]) (page: {ep})")
    t.note(f"for a Z stamp at 22:30 the Israel day is {il_day_of(f'{X}T22:30:00.000Z')} but an epic's rd stays {X} (build parity: both slice the first 10 characters)")
    t.check(not r["errors"], f"no uncaught page errors: {r['errors'][:2]}")


@SUITE.test("f15g_an_issue_returned_in_two_windows_is_counted_once")
def _(t: T):
    """Shift the page clock 25 days forward so the snapshot is old and the page reads the `updated` range in weekly windows; the mock answers the SAME nodes in every window."""
    base = scenario("ok")
    r = scenario("ok", shift_ms=25 * 86400000, timeout=40)
    wins = {m for c in r["calls"] if MAIN_Q in c["jql"] and not c["token"] for m in re.findall(r'updated >= "(\d{4}-\d{2}-\d{2})"', c["jql"])}
    t.check(len(wins) >= 3, f"the read really was split into windows ({len(wins)} windows)")
    k = ctx.chrome.js("(() => { const c = a => { const m = new Map(); a.forEach(x => m.set(x.k, (m.get(x.k) || 0) + 1)); return [...m.values()].filter(n => n > 1).length; }; return [c(DATA.epics), c(DATA.bugs)]; })()")
    t.check(k == [0, 0], f"no epic or bug key appears twice in the data (duplicates: epics {k[0]}, bugs {k[1]})")
    t.check(r["after"]["refreshedStats"] == base["after"]["refreshedStats"], f"the changed-issue counts equal those of a one-window read: {r['after']['refreshedStats']} vs {base['after']['refreshedStats']}")
    t.check(r["after"]["epics"] == base["after"]["epics"] and r["after"]["bugs"] == base["after"]["bugs"], f"epics {r['after']['epics']} / bugs {r['after']['bugs']} equal the one-window read")
    rowsR = [x["p"] + "-" + x["n"] for x in rows_of(build_fixture().crow, r["after"]["capRows"])]
    t.check(len(rowsR) == len(set(rowsR)), "capitalization: every issue is stored once")
    t.check(r["after"]["capN"] == base["after"]["capN"], f"capitalization 'changed' count equals the one-window read ({r['after']['capN']} vs {base['after']['capN']})")
    t.check(not r["timed_out"] and r["status"].startswith("Refreshed "), f"refresh completed -> {r['status'][:70]}")


@SUITE.test("f15h_a_double_click_on_refresh_starts_one_refresh")
def _(t: T):
    base = scenario("ok")
    r = scenario("ok", click=False, slow=120, ls="recent", extra="const b = document.getElementById('refresh'); b.click(); b.click(); setTimeout(() => b.click(), 150); b.dispatchEvent(new MouseEvent('click', {bubbles: true}));", timeout=40)
    n_first = Counter(c["jql"] for c in r["calls"] if not c["token"])
    t.check(all(n == 1 for n in n_first.values()), f"each query was started once ({max(n_first.values())} at most)")
    t.check(len(r["calls"]) == len(base["calls"]), f"the number of calls equals a single refresh ({len(r['calls'])} vs {len(base['calls'])})")
    ctx.chrome.js("document.getElementById('refresh').click()")
    time.sleep(0.6)
    t.check(ctx.chrome.js("window.__calls.length") == len(r["calls"]), "a click after the refresh finished is rate-limited (no new calls within 10 s)")
    t.check(r["status"].startswith("Refreshed ") and not r["disabled"], f"the refresh completed once -> {r['status'][:60]}")
    # a real pointer double click (two mouse press and release pairs 40 ms apart) at the button
    r2 = scenario("ok", click=False, slow=120, ls="recent", extra="window.__dbl = 1;", wait="none", settle=0.1, cache=False)
    ch = ctx.chrome
    ch.js("document.getElementById('refresh').scrollIntoView({block: 'center'})")
    rect = ch.js("(() => { const r = document.getElementById('refresh').getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()")
    for n in (1, 2):
        for ty in ("mousePressed", "mouseReleased"):
            ch.cmd("Input.dispatchMouseEvent", type=ty, x=rect[0], y=rect[1], button="left", clickCount=n)
        time.sleep(0.04)
    ok_ = ch.wait_for("window.__done === true", 40)
    pointer = Counter(c["jql"] for c in ch.js("window.__calls") if not c["token"])
    t.check(ok_ and pointer and all(n == 1 for n in pointer.values()), f"a real double click also starts one refresh (max starts of one query: {max(pointer.values()) if pointer else 0}, finished: {ok_})")


@SUITE.test("f15i_a_tool_error_in_the_automatic_refresh_is_calm_and_retryable")
def _(t: T):
    hook = "async (input, c) => { throw {code: 'tool_error', message: 'jira boom 1234'}; }"
    r = scenario("ok", ls="none", click=False, hook=hook)
    t.check(len(r["calls"]) == 1 and not r["disabled"] and r["retry"], f"one attempt, the button is usable, a Retry button is offered ({len(r['calls'])} calls)")
    t.check("Showing the snapshot from" in r["status"] and r["after"]["epics"] == r["before"]["epics"], "a calm note keeps the snapshot and nothing is applied")
    t.note(f"OBSERVED today (automatic refresh, tool_error 'jira boom 1234'): {r['status'][:140]}")


@SUITE.test("f15i_automatic_tool_error_shows_the_real_reason", expect="REAL_ERROR_TEXT")
def _(t: T):
    hook = "async (input, c) => { throw {code: 'tool_error', message: 'jira boom 1234'}; }"
    r = scenario("ok", ls="none", click=False, hook=hook)
    t.check("jira boom 1234" in r["status"], f"the note carries the real reason of a tool_error, not only 'needs Jira access' -> '{r['status'][:110]}'")
    t.check("needs Jira access" not in r["status"], "an error that is not about access does not say the viewer needs Jira access")
    ap = scenario("ok", ls="none", click=False, hook="async (input, c) => { throw {code: 'approval_required', message: 'declined'}; }")
    t.check("Refresh needs Jira access" in ap["status"], "an access error (approval_required) still says Refresh needs Jira access")


@SUITE.test("f15j_a_capitalization_fetch_failing_on_its_last_call_leaves_everything_consistent", expect="ATOMIC_CAP")
def _(t: T):
    """The earlier projects return changes, the last project's fetch fails: no capitalization change may be applied, and the stamp, caption, counters and checklist must all say so."""
    fx = build_fixture()
    hook = ("async (input, c) => { if (input.jql.startsWith('project = \"INT\" AND issuetype in (Bug, Story, Task)')) { "
            "if (!input.nextPageToken) return c.ok([], 'cap-page-2'); throw {code: 'tool_error', message: 'cap last fetch boom'}; } }")        # the last project's SECOND page fails
    newval = fx.capnode("PMN-98903", "Capitalize - Synthetic New Value", 6, stamp(TODAY, "13:00"))      # a value and a team the page has not seen: they must not be added either
    newval["fields"]["customfield_10098"] = {"value": "Team Synthetic New"}
    r = scenario("ok", ls="none", click=False, hook=hook, capnodes=fx.capnodes + [newval])
    a, b = r["after"], r["before"]
    t.check(a["capRows"] == b["capRows"], "no record of any project was applied (the rows are byte-identical)")
    t.check(a["capVals"] == b["capVals"] and a["capTeams"] == b["capTeams"], "the value and team lists were not extended by the failed step")
    t.check(a["capAt"] is None and a["capN"] is None, f"no refresh time or changed-count was recorded for the data ({a['capAt']}, {a['capN']})")
    t.check(a["capFail"] == "cap last fetch boom", f"the failure is recorded: {a['capFail']}")
    t.check(r["ls"] is None, f"a refresh with a failed step does not mark the page as freshly refreshed, so the next open tries again (dp.lastRefresh = {r['ls']})")
    t.check("not refreshed: cap last fetch boom" in a["capNote"] and b["capNote"] != a["capNote"], f"the caption says what was not refreshed -> {a['capNote'][-90:]}")
    t.check(f"Not refreshed, data unchanged: Capitalization (cap last fetch boom)" in r["status"] and "Capitalization " not in r["status"].split("Not refreshed")[0], f"the checklist names the failed step and does not claim a Capitalization count -> {r['status'][:150]}")
    pulled = fx.data["cap"]["pulledAt"][:16].replace("T", " ")
    t.check(a["stampTxt"].startswith("Data as of ") and pulled in a["capNote"] and "Capitalization not refreshed yet" in a["stampTip"], f"the failure stays in the caption and the tooltip; the header is the oldest live source -> {a['stampTxt']}")
    # a later refresh without the failure applies the data and clears the note
    ch = ctx.chrome
    ch.js("window.__hook = null; refresh.last = 0; document.getElementById('refresh').click()")
    ok2 = ch.wait_for("window.__calls.length > " + str(len(r["calls"])) + " && !document.getElementById('refresh').disabled && /^Refreshed/.test(document.getElementById('status').textContent) && !/Not refreshed/.test(document.getElementById('status').textContent)", 30)
    s2 = json.loads(ch.js("JSON.stringify(window.__snap())"))
    t.check(ok2 and s2["capFail"] is None and s2["capRows"] != b["capRows"] and s2["capAt"], f"the next refresh applies the changes and clears the failure note (ok={ok2}, capFail={s2['capFail']})")


@SUITE.test("f10_a_failing_second_capabilities_read_leaves_the_capabilities_data_unchanged")
def _(t: T):
    """The Capabilities step reads the changed Capabilities and then the ones without a fix version: if the second read fails nothing of the step may have been applied."""
    hook = "async (input, c) => { if (input.jql.includes('issuetype = Capability AND status != Removed AND fixVersion is EMPTY')) throw {code: 'tool_error', message: 'nofv boom'}; }"
    r = scenario("ok", hook=hook)
    a, b = r["after"], r["before"]
    t.check(json.dumps(a.get("listFv")) == json.dumps(b.get("listFv")) and json.dumps(a.get("hierFv")) == json.dumps(b.get("hierFv")), "the Capability lists were not touched")
    t.check(a.get("capPulledAt") == b.get("capPulledAt") and json.dumps(a.get("capNoFv")) == json.dumps(b.get("capNoFv")), "neither the Capabilities stamp nor the no-fix-version count moved")
    t.check("Not refreshed, data unchanged: Capabilities" in r["status"], f"the checklist names the failed step -> {r['status'][:120]}")


@SUITE.test("f09_a_full_page_without_paging_information_is_an_incomplete_read")
def _(t: T):
    hook = "async (input, c) => { if (input.jql.includes('issuetype in (Epic, Bug)') && !input.nextPageToken) return {payload: {issues: {nodes: Array.from({length: 100}, (_, i) => ({...c.CFG.page1[i % c.CFG.page1.length], key: 'SYN-' + (1000 + i)}))}}}; }"
    r = scenario("ok", hook=hook, ls="none", click=True)
    t.check("paging information" in r["status"] and "Refreshed" not in r["status"].split("paging")[0], f"the refresh stops and says why -> {r['status'][:120]}")
    t.check(r["after"].get("e_new") == r["before"].get("e_new"), "nothing was applied from the partial read")


@SUITE.test("f09_the_read_is_checked_against_jiras_own_count")
def _(t: T):
    r = scenario("ok", ls="none", click=True, cache=False)
    n = json.loads(ctx.chrome.js("JSON.stringify(window.__countCalls || [])"))
    t.check(n and all("updated >=" in c["jql"] for c in n), f"every window of the main read is counted by Jira too ({len(n)} count calls)")
    t.check("Refreshed" in r["status"], f"a read that matches the count is applied -> {r['status'][:80]}")


@SUITE.test("f09_a_lost_page_is_caught_by_the_count_and_nothing_is_applied")
def _(t: T):
    r = scenario("ok", ls="none", click=True, countDelta=40, cache=False)
    t.check("Jira counted" in r["status"] and "nothing was applied" in r["status"], f"the refresh stops and says why -> {r['status'][:160]}")
    t.check(r["after"].get("e_new") == r["before"].get("e_new"), "nothing was applied from the short read")
    t.check(len([c for c in r["calls"] if "issuetype in (Epic, Bug)" in c["jql"] and not c["token"]]) == 2, "the window was read once more before giving up")


@SUITE.test("f09_a_late_arrival_or_a_missing_count_does_not_fail_the_refresh")
def _(t: T):
    r = scenario("ok", ls="none", click=True, countDelta=2, cache=False)
    t.check("Refreshed" in r["status"], f"two issues updated between the read and the count are not a lost page -> {r['status'][:80]}")
    r2 = scenario("nocount", ls="none", click=True, cache=False)
    t.check("Refreshed" in r2["status"], f"a connector answer without a count skips the check -> {r2['status'][:80]}")


@SUITE.test("f09_a_repeated_continuation_token_stops_the_read")
def _(t: T):
    hook = "async (input, c) => { if (input.jql.includes('issuetype in (Epic, Bug)')) return c.ok(c.CFG.page1, 'loop'); }"
    r = scenario("ok", hook=hook, ls="none", click=True)
    t.check("repeated a page" in r["status"], f"the refresh stops and says why -> {r['status'][:120]}")
    t.check(r["after"].get("e_new") == r["before"].get("e_new"), "nothing was applied")
    t.check(len([c for c in r["calls"] if "issuetype in (Epic, Bug)" in c["jql"]]) <= 3, "the read did not loop")


@SUITE.test("f16_connector_error_text_is_shown_as_text_never_as_markup")
def _(t: T):
    msg = "<img src=x onerror=window.__x=1>"
    cases = (("main query error, manual", "async (input, c) => { throw {code: 'tool_error', message: %s}; }" % json.dumps(msg), dict(ls="old", click=True)),
             ("main query error, automatic", "async (input, c) => { throw {code: 'tool_error', message: %s}; }" % json.dumps(msg), dict(ls="none", click=False, wait="none", settle=2.0)),
             ("one step fails (Capitalization)", "async (input, c) => { if (input.jql.includes('issuetype in (Bug, Story, Task)')) throw {code: 'tool_error', message: %s}; }" % json.dumps(msg), dict(ls="old", click=True)))
    for label, hook, kw in cases:
        scenario("ok", hook=hook, cache=False, **kw)
        ch = ctx.chrome
        t.check(not ch.js("window.__x === 1") and ch.js("document.querySelectorAll('#status img').length") == 0, f"{label}: the hostile text did not run and made no element")


@SUITE.test("refresh_accessibility_bug_follows_the_three_way_control")
def _(t: T):
    """A bug the Refresh reads through the accessibility query is flagged, and the Quality section places it by the Accessibility Bugs control: out under No, in under All, the only kind under Yes
    (a new plain bug is the other way round). Driven through the real buttons after the Refresh."""
    fx = build_fixture()
    r = scenario("ok", cache=False)
    t.check(not r["errors"], f"no uncaught page errors: {r['errors'][:2]}")
    ch = ctx.chrome
    js = ("(() => { const out = {}; for (const v of ['no', 'yes', 'all']) { document.querySelector('#f-ax input[value=\"' + v + '\"]').click(); const open = backlogBugs().filter(isOpenBug).map(b => b.k);"
          " out[v] = {ax: open.includes('%s'), plain: open.includes('%s'), n: open.length, tile: document.querySelector('#bug-kpis .kpi .v').textContent.replace(/,/g, '')}; } return out; })()") % (fx.S["axBug"], fx.S["newBug"])
    seen = ch.js(js)
    t.check(seen["no"]["ax"] is False and seen["no"]["plain"] is True, f"No: the new accessibility bug is out, the new plain bug is in: {seen['no']}")
    t.check(seen["yes"]["ax"] is True and seen["yes"]["plain"] is False, f"Yes: only the accessibility bug: {seen['yes']}")
    t.check(seen["all"]["ax"] is True and seen["all"]["plain"] is True, f"All: both: {seen['all']}")
    t.check(seen["all"]["n"] == seen["no"]["n"] + seen["yes"]["n"] and all(str(v["n"]) == v["tile"] for v in seen.values()), f"All = No + Yes and the tile shows the count: {seen}")


@SUITE.test("refresh_redraws_after_the_first_step_not_only_at_the_end")
def _(t: T):
    """Epics and bugs are merged first; the page must show them as soon as that step is done, while a later step (Dependency links) is still running."""
    hook = "async (input, c) => { if (input.jql.includes('issuetype = Epic AND status != Removed AND fixVersion in (')) { await new Promise(r => setTimeout(r, 60000)); } }"
    r = scenario("ok", ls="none", click=False, hook=hook, wait="js", timeout=20,
                 wait_js="window.__calls.some(c => c.jql.includes('issuetype = Epic AND status != Removed AND fixVersion in (')) && /^Refreshed/.test(document.getElementById('meta').textContent) && document.getElementById('refresh').disabled")
    t.check(not r["timed_out"], "the page header already says Refreshed (epics and bugs merged and drawn) while the Dependency links step is still running")
    ch = ctx.chrome
    tip = ch.js("document.getElementById('asof').dataset.tip || ''")
    t.check(tip.startswith("Refreshing from Jira"), f"the stamp tooltip says it is mid-refresh -> {tip[:90]}")
    t.check("Epics: " not in tip and "Built from commit" not in tip, "the tooltip carries no per-source list or build detail")
    t.check(not [c for c in r["calls"] if c["tool"] == "getJiraIssue" or "issuetype in (Bug, Story, Task)" in c["jql"]], "while Dependency links (a live step) is running no limited step has started: the live tier comes first")
    # the order of one whole refresh: epics, bugs and accessibility; then Dependency links, Capabilities; then cycle time and Capitalization
    calls = scenario("ok", ls="recent", click=True, cache=False)["calls"]
    first = [c["i"] for c in calls if MAIN_Q in c["jql"] or "[Accessibility]" in c["jql"]]
    live = [c["i"] for c in calls if "issuetype = Epic AND status != Removed AND fixVersion in (" in c["jql"] or "issuetype = Capability" in c["jql"]]
    limited = [c["i"] for c in calls if c["tool"] == "getJiraIssue" or "issuetype in (Bug, Story, Task)" in c["jql"]]
    t.check(first and live and limited and max(first) < min(live) and max(live) < min(limited), f"step 1 ({len(first)} calls), then the live steps ({len(live)}), then the limited steps ({len(limited)})")
    ed = [c["i"] for c in calls if c["tool"] == "getJiraIssue"]
    cap = [c["i"] for c in calls if "issuetype in (Bug, Story, Task)" in c["jql"]]
    t.check(ed and cap and max(ed) < min(cap), "within the limited tier: cycle time, then Capitalization")


# ================================================================ the two tiers of Refresh steps: the daily allowance of the limited tier, its stored result, the stamps and notes
SLOW_Q = "issuetype in (Bug, Story, Task)"
SENTENCE = "Cycle time and Capitalization were not refreshed: they update on the first two Refresh clicks each day, and those are used. They update again after midnight, Israel time."
RAW_SLOW = "(() => { try { return localStorage.getItem('dp.slowRuns'); } catch (e) { return 'blocked'; } })()"


def limited_calls(calls):
    """The calls of the limited tier: one getJiraIssue per epic waiting for a cycle time (EDCT), and the Capitalization reads of the Bugs, Stories and Tasks."""
    return [c for c in calls if c["tool"] == "getJiraIssue"], [c for c in calls if SLOW_Q in c["jql"] and c["tool"] != "getJiraIssue"]


def pend_js():
    """Put the newly Done epic of the mock back to 'no cycle time yet', so every click that runs the cycle-time step has something to read."""
    return f"(() => {{ const e = DATA.epics.find(x => x.k === {build_fixture().S['eStatus']!r}); if (e) delete e.edct; }})()"


def open_quiet(**kw):
    """The page with the connector, no automatic refresh (ls=recent drops it) and an empty allowance, ready for clicks."""
    kw.setdefault("ls", "recent")
    return scenario(kw.pop("mode", "ok"), click=False, wait="none", settle=0.3, cache=False, **kw)


def slow_state(raw):
    return None if raw in (None, "blocked") else json.loads(raw)


def click_run(prep="", timeout=40):
    """One Refresh click on the open page (the 10 s rate limit reset, as the multi-click tests do) and what it did."""
    ch = ctx.chrome
    n0 = ch.js("window.__calls.length")
    ch.js("window.__done = false; window.__sawBusy = false; refresh.last = 0; " + (prep or "0") + "; document.getElementById('refresh').click()")
    done = ch.wait_for("window.__done === true", timeout)
    calls = ch.js(f"window.__calls.slice({n0})")
    ed, cp = limited_calls(calls)
    return dict(done=done, calls=calls, edct=len(ed), cap=len(cp), live=len([c for c in calls if MAIN_Q in c["jql"]]), status=ch.js("document.getElementById('status').textContent"),
                kind=ch.js("(document.querySelector('#status .msg')||{}).className||''"), disabled=ch.js("document.getElementById('refresh').disabled"), slow=slow_state(ch.js(RAW_SLOW)),
                snap=json.loads(ch.js("JSON.stringify(window.__snap())")))


def ran_limited(c):
    return c["edct"] >= 1 and c["cap"] >= 6                                          # one Capitalization read per project (six)


def skipped_limited(c):
    return c["edct"] == 0 and c["cap"] == 0 and c["live"] >= 1 and any("issuetype = Epic AND status != Removed AND fixVersion in (" in x["jql"] for x in c["calls"])


def today_il():
    return ctx.chrome.js("ilDate(new Date())")


@SUITE.test("slow_tier_three_clicks_on_one_page_two_run_the_limited_tier")
def _(t: T):
    fx = build_fixture()
    open_quiet()
    c1, c2 = click_run(pend_js()), click_run(pend_js())
    rows2 = ctx.chrome.js("DATA.cap.rows")
    V = fx.data["cap"]["values"]
    extra = fx.capnode("PMN-98905", V[fx.cap["capval"]], 3, stamp(TODAY, "13:00"))
    c3 = click_run(pend_js() + f"; __CFG.capnodes.push({js_json(extra)})")
    t.check(ran_limited(c1) and ran_limited(c2), f"clicks 1 and 2 issue the cycle-time and the Capitalization reads (EDCT/cap calls: {c1['edct']}/{c1['cap']}, {c2['edct']}/{c2['cap']})")
    t.check(skipped_limited(c3), f"click 3 issues no limited call but still the live reads (EDCT/cap calls {c3['edct']}/{c3['cap']}, main query calls {c3['live']})")
    t.check(SENTENCE not in c1["status"] and SENTENCE not in c2["status"], "clicks 1 and 2 do not carry the sentence about the allowance")
    t.check(SENTENCE in c3["status"] and "info" in c3["kind"] and c3["status"].count("Refreshed") == 1 and "Not refreshed" not in c3["status"], f"click 3 says so, as a plain info message and not as a failed step -> {c3['status'][-200:]}")
    t.check(not c3["disabled"] and c3["done"], "the button is usable after click 3")
    t.check(ctx.chrome.js("DATA.cap.rows") == rows2 and "98905" not in rows2, "the Capitalization rows did not change on click 3 (a record the mock now offers was not read)")
    t.check(c3["slow"]["n"] == 2 and c3["slow"]["day"] == today_il(), f"storage: {c3['slow']}")
    t.check(not ctx.chrome.console_errors(), f"no uncaught page errors: {ctx.chrome.console_errors()[:2]}")


@SUITE.test("slow_tier_the_first_open_of_the_day_runs_it_without_using_a_click")
def _(t: T):
    r = scenario("ok", ls="old", click=False, cache=False)
    ed, cp = limited_calls(r["calls"])
    s = slow_state(r["after"]["slowRaw"])
    t.check(len(ed) >= 1 and len(cp) >= 6, f"the automatic refresh of the first open ran the limited tier (EDCT/cap calls {len(ed)}/{len(cp)})")
    t.check(s and s["auto"] == 1 and s["n"] == 0 and s["day"] == today_il(), f"it used the automatic allowance, not a click: {s}")
    t.check(r["after"]["edctAt"] and r["after"]["capAt"], "cycle time and Capitalization carry a refresh time")


@SUITE.test("slow_tier_the_second_open_of_the_day_is_live_only_and_clicks_are_still_available")
def _(t: T):
    r = scenario("ok", ls="old", click=False, sr={"n": 0, "auto": 1}, cache=False)
    ed, cp = limited_calls(r["calls"])
    t.check(not ed and not cp and any(MAIN_Q in c["jql"] for c in r["calls"]), f"the second automatic refresh of the day runs the live tier only (EDCT/cap calls {len(ed)}/{len(cp)})")
    t.check(slow_state(r["after"]["slowRaw"]) == {"day": today_il(), "n": 0, "auto": 1}, f"and spends nothing: {r['after']['slowRaw']}")
    t.check(SENTENCE not in r["status"] and "0 of 2" not in r["after"]["stampTip"] and "2 of 2 Refresh clicks left today." in r["after"]["stampTip"], f"no 'used' sentence while clicks remain; the tooltip says 2 of 2 are left -> {r['status'][-90:]}")
    c1, c2 = click_run(pend_js()), click_run(pend_js())
    t.check(ran_limited(c1) and ran_limited(c2), "both clicks still run the limited tier")
    t.check(skipped_limited(click_run(pend_js())), "a third click is live only")


@SUITE.test("slow_tier_a_new_day_resets_the_allowance")
def _(t: T):
    r = scenario("ok", ls="recent", click=True, sr="yesterday", cache=False)
    t.check(ran_limited({"edct": len(limited_calls(r["calls"])[0]), "cap": len(limited_calls(r["calls"])[1])}), "yesterday's used allowance does not block today's first click")
    t.check(slow_state(r["after"]["slowRaw"]) == {"day": today_il(), "n": 1, "auto": 0}, f"storage was reset to today with one click used: {r['after']['slowRaw']}")


@SUITE.test("slow_tier_midnight_crossing_run_counts_for_its_starting_day")
def _(t: T):
    now = dt.datetime.now(MS.IL)
    mid = (now + dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    shift = int((mid - dt.timedelta(seconds=14) - now).total_seconds() * 1000)                         # the page clock reads 23:59:46 when the run starts
    d0 = now.date().isoformat()
    hook = ("async (input, c) => { if (input.jql.includes('issuetype in (Bug, Story, Task)') && !window.__crossed) { const day = () => new Intl.DateTimeFormat('en-CA', {timeZone: 'Asia/Jerusalem'}).format(new Date());"
            f" while (day() === '{d0}') await new Promise(r => setTimeout(r, 100)); window.__crossed = true; }} }}")                  # the run is held inside the limited tier until the Israel day has changed
    r = scenario("ok", ls="recent", click=True, shift_ms=shift, slow=150, hook=hook, timeout=90, cache=False)
    s = slow_state(r["after"]["slowRaw"])
    t.check(not r["timed_out"] and s and s["day"] == d0 and s["n"] == 1, f"the run that crossed midnight counts for the day it started on ({d0}): {s}")
    t.check(len(limited_calls(r["calls"])[0]) >= 1 and len(limited_calls(r["calls"])[1]) >= 6, "and it ran the limited tier to the end (the day was not rechecked)")
    day_now = ctx.chrome.js("ilDate(new Date())")
    t.check(day_now > d0, f"the page clock is now on the next day ({day_now})")
    c2 = click_run(pend_js(), timeout=90)
    t.check(ran_limited(c2) and c2["slow"] == {"day": day_now, "n": 1, "auto": 0}, f"a click after midnight runs the limited tier and starts the new day at one click: {c2['slow']}")


@SUITE.test("slow_tier_blocked_storage_counts_in_memory_without_errors")
def _(t: T):
    r = scenario("ok", ls="blocked", click=False, cache=False)
    t.check(len(limited_calls(r["calls"])[0]) >= 1, "the automatic refresh on open ran the limited tier (the first of the day)")
    c1, c2, c3 = click_run(pend_js()), click_run(pend_js()), click_run(pend_js())
    t.check(ran_limited(c1) and ran_limited(c2), "clicks 1 and 2 run the limited tier")
    t.check(skipped_limited(c3) and SENTENCE in c3["status"], "click 3 is live only: the count is kept in memory for this page load")
    t.check(c3["slow"] is None or c3["slow"] == "blocked", f"nothing could be stored: {c3['slow']}")
    t.check(not ctx.chrome.console_errors(), f"no console errors with storage blocked: {ctx.chrome.console_errors()[:2]}")


@SUITE.test("slow_tier_unreadable_or_invalid_stored_values_reset_cleanly")
def _(t: T):
    seeds = ["corrupt", "future", "null", "[]", "123", {"n": 7, "auto": 0}, {"n": "1", "auto": 0}, {"n": 1.5, "auto": 0}, {"n": -1, "auto": 0}, {"day": "2026-13-45", "n": 0, "auto": 0}, {"n": 0, "auto": 5}]
    for sr in seeds:
        r = scenario("ok", ls="recent", click=True, sr=sr, cache=False)
        ed, cp = limited_calls(r["calls"])
        s = slow_state(r["after"]["slowRaw"])
        t.check(len(ed) >= 1 and len(cp) >= 6 and s == {"day": today_il(), "n": 1, "auto": 0} and not r["errors"] and r["status"].startswith("Refreshed "), f"seed {sr!r}: reset to today, one click used, the limited tier ran, no page errors -> {s} {r['errors'][:1]}")


@SUITE.test("slow_tier_the_allowance_is_read_at_click_time")
def _(t: T):
    open_quiet()
    ctx.chrome.js("localStorage.setItem('dp.slowRuns', JSON.stringify({day: ilDate(new Date()), n: 2, auto: 1}))")           # another tab used the allowance after this page loaded
    c = click_run(pend_js())
    t.check(skipped_limited(c) and SENTENCE in c["status"], f"the click is live only (EDCT/cap calls {c['edct']}/{c['cap']})")


@SUITE.test("slow_tier_a_failed_run_is_not_refunded")
def _(t: T):
    open_quiet(mode="capfail")
    c1 = click_run(pend_js())
    t.check("Not refreshed, data unchanged: Capitalization (capitalization boom)" in c1["status"] and "warn" in c1["kind"], f"click 1 names the failure -> {c1['status'][-120:]}")
    t.check(c1["slow"]["n"] == 1, f"and used a click: {c1['slow']}")
    d = slow_state(ctx.chrome.js("localStorage.getItem('dp.slowData')"))
    t.check(d and d.get("edctAt") and "cap" not in d and "capAt" not in d, f"only the step that succeeded was stored (cycle time yes, Capitalization no): {sorted(d or {})}")
    ctx.chrome.js("__CFG.mode = 'ok'")
    c2, c3 = click_run(pend_js()), click_run(pend_js())
    t.check(ran_limited(c2) and c2["slow"]["n"] == 2, "click 2 runs the limited tier and is the second one")
    t.check(skipped_limited(c3) and SENTENCE in c3["status"], "click 3 is live only (a refund of click 1 would have given it the limited tier)")


@SUITE.test("slow_tier_header_stamp_is_the_oldest_live_source_and_the_notes_say_the_rest")
def _(t: T):
    kw = dict(ls="recent", click=True, fast=True, wait="js", wait_js="window.__done === true && document.getElementById('asof').textContent.startsWith('Data as of')", cache=False)
    r = scenario("ok", sr="used", **kw)
    a = r["after"]
    t.check(not r["timed_out"] and a["stampTxt"] == "Data as of " + il_label(live_oldest(a)), f"after a live-only refresh the header is the oldest of the five live sources -> {a['stampTxt']}")
    t.check("Cycle time not refreshed yet; Capitalization not refreshed yet." in a["stampTip"] and "0 of 2 Refresh clicks left today." in a["stampTip"], f"the tooltip names the limited sources and the clicks left -> {a['stampTip']!r}")
    t.check(a["effNote"].startswith("Cycle time: not refreshed yet; Refresh updates it up to twice a day.") and a["raNote"] == "Cycle time and Capitalization: not refreshed yet; Refresh updates them up to twice a day.", f"Efficiency and Release Analysis say it -> {a['effNote']!r} {a['raNote']!r}")
    t.check("not refreshed yet" in a["capNote"], f"and so does the Capitalization caption -> {a['capNote'][-60:]}")
    t.check(not any("build" in x.lower() for x in (a["effNote"], a["raNote"], a["capNote"], a["stampTip"], r["status"])), "no note, caption, tooltip or status talks about a build")
    r2 = scenario("ok", sr="none", **kw)
    b = r2["after"]
    t.check(b["stampTxt"] == "Data as of " + il_label(live_oldest(b)), f"after a full refresh the header is still the oldest live source -> {b['stampTxt']}")
    t.check("not refreshed yet" not in b["stampTip"] and " as of " not in b["stampTip"] and "1 of 2 Refresh clicks left today." in b["stampTip"], f"the limited line is absent when the sources agree -> {b['stampTip']!r}")
    t.check(b["effNote"].startswith(f"Cycle time: refreshed {il_label(b['edctAt'])};") and b["raNote"].startswith("Cycle time and Capitalization: refreshed ") and f"refreshed {il_label(b['capAt'])}" in b["capNote"], f"the notes carry the refresh times -> {b['effNote']!r}")
    # a copy with no connector has no limited tier and none of these notes
    ch = ctx.chrome
    ch.goto(ctx.write(build_fixture().fragment, "plain"))
    kit.wait_ready(ch, 15)
    st = ch.js("({asof: document.getElementById('asof').textContent, tip: document.getElementById('asof').dataset.tip, eff: document.getElementById('eff-note').textContent, ra: document.getElementById('ra-note').textContent, cap: document.getElementById('capz-cap').textContent})")
    t.check(st["asof"].startswith("Snapshot from ") and "Refresh clicks" not in st["tip"] and st["eff"] == "" and st["ra"] == "" and "refreshed" not in st["cap"], f"the snapshot copy: {st['asof']!r}, no limited-tier notes")


@SUITE.test("slow_tier_an_epic_closed_since_the_last_cycle_time_run_is_pending_not_a_defect")
def _(t: T):
    r = scenario("ok", ls="recent", click=True, sr="used", cache=False)
    a, b = r["after"], r["before"]
    naive = ctx.chrome.js("DATA.epics.filter(e => cls(e.s) === 'done' && e.edct == null).length")
    t.check(a["noEdctRow"]["n"] == b["noEdctRow"]["n"] and naive == a["noEdctRow"]["n"] + 1, f"the newly Done epic is not counted as a missing cycle time (row {b['noEdctRow']['n']} -> {a['noEdctRow']['n']}, {naive} Done without one)")
    t.check("1 more wait for the next cycle-time refresh" in a["noEdctRow"]["note"], f"the row says it waits -> {a['noEdctRow']['note']}")
    t.check("rebuild" not in r["status"] and "newly Done" not in r["status"], f"the status does not say it needs a rebuild -> {r['status'][-120:]}")
    t.check("1 epic that closed since then is not counted yet." in a["effNote"], f"the Efficiency note counts it -> {a['effNote']!r}")
    t.check("wait for the next cycle-time refresh" in ctx.chrome.js("document.body.textContent"), "and the Needs Attention row shows the note")
    r2 = scenario("ok", ls="recent", click=True, sr="none", cache=False)
    t.check(r2["after"]["noEdctRow"]["n"] == b["noEdctRow"]["n"] and "wait for" not in r2["after"]["noEdctRow"]["note"] and "not counted yet" not in r2["after"]["effNote"], f"with the cycle-time step run the count is the same and nothing waits ({r2['after']['noEdctRow']})")


@SUITE.test("slow_tier_a_failed_cycle_time_step_is_called_out_in_efficiency")
def _(t: T):
    f = scenario("edctfail", ls="recent", click=True, cache=False)
    t.check(f["after"]["effNote"] == "Cycle time: not refreshed: history boom.", f"{f['after']['effNote']!r}")


@SUITE.test("live_tier_the_automatic_refresh_runs_on_every_open_even_when_the_last_refresh_was_recent")
def _(t: T):
    r = scenario("ok", ls="recentauto", click=False, cache=False)
    t.check(any(MAIN_Q in c["jql"] for c in r["calls"]), "a reload within 15 minutes of the last refresh still reads the live data")
    t.check(slow_state(r["after"]["slowRaw"])["auto"] == 1, "and it is the first open of the day, so it ran the limited tier")


@SUITE.test("slow_tier_an_automatic_refresh_that_fails_on_step_one_spends_nothing")
def _(t: T):
    r = scenario("denied", ls="none", click=False, sr={"n": 1, "auto": 0}, cache=False)
    t.check(slow_state(r["after"]["slowRaw"]) == slow_state(r["before"]["slowRaw"]) and r["before"]["slowRaw"] is not None, f"dp.slowRuns is untouched: {r['before']['slowRaw']} -> {r['after']['slowRaw']}")
    r2 = scenario("denied", ls="none", click=False, cache=False)
    t.check(r2["after"]["slowRaw"] is None, "and none is written")


# ---- what the limited tier last read is kept in the viewer's browser: a reload shows it
def _stored():
    return json.loads(ctx.chrome.js("localStorage.getItem('dp.slowData')"))


def _set_stored(obj):
    ctx.chrome.js(f"localStorage.setItem('dp.slowData', {json.dumps(obj if isinstance(obj, str) else json.dumps(obj))})")


def _reload(**kw):
    """The same page again with the connector denied: what it shows comes from the page and its storage only."""
    return scenario("denied", ls="none", click=False, keep=True, cache=False, **kw)


@SUITE.test("stored_limited_tier_a_reload_shows_the_last_refresh_without_the_connector")
def _(t: T):
    fx = build_fixture()
    r1 = scenario("ok", ls="recent", click=True, cache=False)
    a1, b1 = r1["after"], r1["before"]
    t.check(a1["capRows"] != b1["capRows"] and a1["e_status"]["edct"] == 6, "the first page: the refresh changed the Capitalization rows and read the cycle time of the newly Done epic")
    d = _stored()
    t.check(d["v"] == 1 and d["build"] == fx.data["generated"] and d["schema"] == 2 and d["edctAt"] == a1["edctAt"] and d["capAt"] == a1["capAt"] and sum(d["edct"][fx.S["eStatus"]][:2]) == 6, f"it was stored with the data version and the refresh times: {sorted(d)}")
    r2 = _reload()
    b2 = r2["before"]
    t.check(b2["capRows"] == a1["capRows"] and b2["e_status"] and b2["e_status"].get("edct") == 6, "a reload shows the refreshed Capitalization rows and the cycle time as soon as it loads (before any refresh)")
    t.check(b2["edctAt"] == a1["edctAt"] and b2["capAt"] == a1["capAt"], "with the stored refresh times, not newer ones")
    t.check(f"refreshed {il_label(a1['edctAt'])}" in b2["effNote"] and f"refreshed {il_label(a1['capAt'])}" in b2["capNote"] and il_label(min(a1["edctAt"], a1["capAt"])) in b2["raNote"], f"the notes show the stored refresh times -> {b2['effNote']!r} {b2['raNote']!r}")
    t.check(r2["calls"] and all(c["jql"] for c in r2["calls"]) and len(r2["calls"]) == 1 and r2["after"]["capRows"] == a1["capRows"], f"the connector answered nothing (denied; {len(r2['calls'])} attempt): the data on the page is the stored one")
    t.check(not r2["errors"], f"no uncaught page errors: {r2['errors'][:2]}")
    t.check(b2["keep"]["edct"] == b1["keep"]["edct"], "an epic that already had a cycle time keeps it")


@SUITE.test("stored_limited_tier_another_data_version_is_discarded")
def _(t: T):
    r1 = scenario("ok", ls="recent", click=True, cache=False)
    orig = r1["before"]
    good = _stored()
    for label, patch in (("another build", {"build": "2000-01-01T00:00:00Z"}), ("another schema", {"schema": 99}), ("another layout of the key", {"v": 2})):
        _set_stored({**good, **patch})
        r2 = _reload()
        t.check(r2["before"]["capRows"] == orig["capRows"] and r2["before"]["e_status"].get("edct") is None and r2["before"]["edctAt"] is None and r2["before"]["capAt"] is None, f"{label}: the stored values are not applied")
        t.check(ctx.chrome.js("localStorage.getItem('dp.slowData')") is None, f"{label}: the key was removed")
        t.check("not refreshed yet" in r2["before"]["effNote"] and "not refreshed yet" in r2["before"]["capNote"], f"{label}: the notes say not refreshed yet -> {r2['before']['effNote']!r}")


@SUITE.test("stored_limited_tier_a_corrupt_value_is_ignored_without_errors")
def _(t: T):
    orig = scenario("ok", ls="recent", click=False, wait="none", settle=0.2, cache=False)["before"]
    for bad in ("{not json", "null", "[]", "123", json.dumps({"v": 1}), json.dumps({"v": 1, "build": build_fixture().data["generated"], "schema": 2, "edctAt": "no date", "edct": {"x": 1}, "capAt": 5, "cap": "x"})):
        _set_stored(bad)
        r = _reload()
        t.check(not r["errors"] and r["before"]["capRows"] == orig["capRows"] and r["before"]["edctAt"] is None and r["before"]["capAt"] is None, f"{bad[:30]!r}: ignored, no page errors {r['errors'][:1]}")
        t.check(r["before"]["epics"] == orig["epics"], f"{bad[:30]!r}: the page is intact")


@SUITE.test("stored_limited_tier_never_overwrites_a_value_and_never_looks_newer_than_it_is")
def _(t: T):
    fx = build_fixture()
    r1 = scenario("ok", ls="recent", click=True, cache=False)
    orig, good = r1["before"], _stored()
    keep = orig["keep"]["edct"]
    t.check(keep is not None, "the fixture has a Done epic with a cycle time")
    _set_stored({**good, "edct": {fx.S["eKeep"]: [99, 99, 1], fx.S["eStatus"]: [4, 1, None], "NOPE-1": [1, 1, 1], fx.S["eDep"]: ["x", 1, 1]}})
    r2 = _reload()
    b = r2["before"]
    t.check(b["keep"]["edct"] == keep, f"a stored value does not replace an existing one ({b['keep']['edct']} stays {keep})")
    t.check(b["e_status"]["edct"] == 5 and b["e_status"]["ip"] == 4 and b["e_status"]["vl"] == 1, "a stored value fills an epic that has none")
    t.check(b["dep"].get("edct") is None, "a malformed stored value is skipped")
    # a refresh time in the future is not trusted; a Capitalization read not newer than the data's own pull is not applied
    _set_stored({**good, "edctAt": "2999-01-01T00:00:00Z", "capAt": "2999-01-01T00:00:00Z"})
    b3 = _reload()["before"]
    t.check(b3["edctAt"] is None and b3["capAt"] is None and b3["capRows"] == orig["capRows"], "a stored refresh time in the future is ignored")
    _set_stored({**good, "capAt": fx.data["cap"]["pulledAt"]})
    b4 = _reload()["before"]
    t.check(b4["capAt"] is None and b4["capRows"] == orig["capRows"], "a stored Capitalization read that is not newer than the data's own is not applied")


@SUITE.test("stored_limited_tier_blocked_storage_still_works")
def _(t: T):
    r = scenario("ok", ls="blocked", click=True, cache=False)
    t.check(not r["errors"] and r["status"].startswith("Refreshed ") and r["after"]["capAt"] and r["after"]["e_status"]["edct"] == 6, f"refresh with blocked storage: data applied, no page errors {r['errors'][:1]}")


if __name__ == "__main__":
    sys.exit(kit.cli(SUITE, __doc__))
