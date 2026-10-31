#!/usr/bin/env python3
"""Escaping canary (finding F16): hostile strings in every free-text field of the fictitious payload must be shown as text, never run.

The two strings  "><img src=x onerror=window.__x=1>  and  <script>window.__x=1</script>  are put (make_synthetic.canarify) into epic titles, teams,
assignees, categories, models, pod labels, sprint names, statuses, capability and initiative names, fix versions, bug teams and resolutions, CFB
summaries, links and analysis text, capitalization values and teams, far-end issues, bugs under epics ... The page is then loaded in the default
state and in many filter states (the URL hash), every details block (Show data tables) is opened, every collapsed group is expanded and the hover
text of every mark is shown. After each state: window.__x must still be undefined, and the DOM must hold no <img> with src=x or an onerror, no inline
event-handler attribute and no script element beyond what the template itself has. A control proves the detector fires on an unescaped injection.
The refresh path is covered too: hostile strings in the (mocked) Jira responses are merged and rendered.

    python3 canary.py [--live] [--only NAME]
"""
from __future__ import annotations

import copy
import json
import sys
import time
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kit                                                                          # noqa: E402
import make_synthetic as MS                                                         # noqa: E402
from kit import ctx, T                                                              # noqa: E402

SUITE = kit.Suite("Delivery Pulse escaping canary")
A, B = MS.CANARY_A, MS.CANARY_B

STATES = [
    ("default", ""), ("release 26.4", "r=26.4"), ("release 27.2", "r=27.2"), ("one project", "p=PMN"), ("two projects", "p=PMN|CXWFM"),
    ("hostile team", "TEAM"), ("stretch only", "c=Stretch"), ("committed and not set", "c=Committed|Not%20Set"), ("accessibility, P1+P2", "ax=1&bp=P1|P2"),
    ("CFB yes", "cfb=yes"), ("CFB no", "cfb=no"), ("quarter groupings", "g=quarter&cg=quarter"), ("month CFB grouping", "cg=month"),
    ("dependencies all", "dp=all"), ("dependencies overdue", "dp=overdue"), ("dependencies external", "dp=external"), ("dependencies gap", "dp=gap"),
    ("NFR by category", "nt=category"), ("NFR by commitment", "nt=commitment"), ("NFR by capability", "nt=capability"), ("NFR by team", "nt=team"),
    ("CXCROSS committed", "cx=committed"), ("CXCROSS not set", "cx=notset"), ("CXCROSS stretch", "cx=stretch"),
    ("capitalization by release, count", "cpg=release&cpm=count"), ("cycle 2", "cy=DC2"), ("old release, all projects, hostile team", "r=26.2&TEAM"),
]

CHECK_JS = """(() => ({
  x: window.__x === undefined ? null : window.__x,
  badImgs: document.querySelectorAll('img[onerror], img[src="x"]').length,
  imgs: document.querySelectorAll('img').length,
  scripts: document.querySelectorAll('script:not([data-harness])').length,
  handlers: [...document.querySelectorAll('*')].filter(e => [...e.attributes].some(a => /^on/i.test(a.name))).length,
  tipBad: window.__tipBad || 0, tips: window.__tips || 0,
  shown: document.body.innerText.split('window.__x=1').length - 1,
}))()"""

PREPARE_JS = """(() => {
  document.querySelectorAll('details').forEach(d => { d.open = true; });                    // every "Show data" table and "How this is calculated"
  const all = document.getElementById('attn-all'); if (all && !all.hidden) all.click();
  [...document.querySelectorAll('#attn button[aria-expanded="false"], #cy-sec button[aria-expanded="false"], #cx-body button[aria-expanded="false"]')].slice(0, 30).forEach(b => { try { b.click(); } catch (e) {} });
  document.querySelectorAll('details').forEach(d => { d.open = true; });
  let bad = 0, n = 0; const tip = document.getElementById('gtip');                             // the hover text of every mark
  document.querySelectorAll('[data-tip]').forEach(el => { el.dispatchEvent(new MouseEvent('mouseover', {bubbles: true, clientX: 20, clientY: 20})); n++; if (tip.querySelector('img, script, [onerror]')) bad++; });
  window.__tipBad = bad; window.__tips = n;
  return n;
})()"""


def settle(ch):
    """An image whose load fails reports through an async event; a sentinel queued after the page's own work fires after theirs, so waiting for it is deterministic."""
    ch.js("window.__sentinel = 0; { const i = document.createElement('img'); i.src = 'sentinel-missing.png'; i.onerror = () => { window.__sentinel = 1; i.remove(); }; document.body.appendChild(i); }")
    return ch.wait_for("window.__sentinel === 1", 10)


def load(ch, url, hash_=""):
    ch.goto(url + ("#" + hash_ if hash_ else ""))
    return kit.wait_ready(ch)


def probe(ch, url, hash_=""):
    ok = load(ch, url, hash_)
    ch.js(PREPARE_JS)
    settle(ch)
    r = ch.js(CHECK_JS)
    r["loaded"] = ok
    r["errors"] = ch.console_errors()
    return r


_pages = {}


def pages():
    """(hostile page url, plain page url, the hostile team's name)"""
    if not _pages:
        plain = MS.make(kit.MS.il_today(), canary=False)
        hostile = MS.make(kit.MS.il_today(), canary=True)
        team = next(t for t in hostile["cap"]["teams"] if t.startswith("Team Alpha"))
        _pages.update(hostile=ctx.write(kit.fragment_for(hostile), "canary"), plain=ctx.write(kit.fragment_for(plain), "plain"), team=team, hostile_data=hostile)
    return _pages


def hash_for(spec: str, team: str) -> str:
    return "&".join(f"t={urllib.parse.quote(team)}" if p == "TEAM" else p for p in spec.split("&")) if spec else ""


def baseline(ch):
    P = pages()
    return probe(ch, P["plain"])


@SUITE.test("canary_control_the_detector_fires_on_an_unescaped_injection")
def _(t: T):
    ch = ctx.chrome
    P = pages()
    load(ch, P["plain"])
    ch.js(f"window.__x = undefined; document.body.insertAdjacentHTML('beforeend', {json.dumps(A)})")
    fired = ch.wait_for("window.__x === 1", 10)
    r = ch.js(CHECK_JS)
    t.check(fired, "an unescaped  \"><img src=x onerror=...>  set window.__x (the detector is not blind)")
    t.check(r["badImgs"] >= 1, "and the injected element is found in the DOM")


@SUITE.test("canary_the_payload_is_really_rendered_as_text")
def _(t: T):
    ch = ctx.chrome
    P = pages()
    r = probe(ch, P["hostile"])
    t.check(r["loaded"] and not r["errors"], f"the hostile page loads without uncaught errors: {r['errors'][:2]}")
    t.check(r["shown"] >= 50, f"the hostile strings are visible as text in many places (found {r['shown']}), so the fields really are rendered")
    t.check(r["tips"] > 100, f"hover text was shown for {r['tips']} marks")
    per = ch.js("""[...document.querySelectorAll('section')].map(s => [(s.querySelector('h2,h3') || {}).textContent, s.innerText.split('window.__x=1').length - 1]).filter(x => x[1])""")
    t.note("hostile text shown per section: " + "; ".join(f"{a} {n}" for a, n in per))
    t.check(len(per) >= 6, f"the hostile text reaches at least six different sections ({len(per)})")


@SUITE.test("canary_no_injection_in_default_and_filter_states")
def _(t: T):
    ch = ctx.chrome
    P = pages()
    base = baseline(ch)
    t.note(f"baseline (plain data): scripts {base['scripts']}, inline handlers {base['handlers']}, images {base['imgs']}")
    for name, spec in STATES:
        h = hash_for(spec, P["team"])
        r = probe(ch, P["hostile"], h)
        ok = r["loaded"] and r["x"] is None and r["badImgs"] == 0 and r["handlers"] <= base["handlers"] and r["scripts"] <= base["scripts"] and r["imgs"] <= base["imgs"] and r["tipBad"] == 0
        t.check(ok, f"state '{name}' (#{h}): window.__x={r['x']}, injected images {r['badImgs']}, handlers {r['handlers']} (base {base['handlers']}), scripts {r['scripts']} (base {base['scripts']}), "
                    f"images {r['imgs']} (base {base['imgs']}), hostile tooltip nodes {r['tipBad']}, errors {r['errors'][:1]}")


@SUITE.test("canary_no_injection_after_a_refresh_merges_hostile_jira_responses")
def _(t: T):
    import harness as H
    fx = H.build_fixture()
    nodes = copy.deepcopy(fx.nodes)
    for i, n in enumerate(nodes):
        f = n["fields"]
        f["summary"] = (A if i % 2 else B)
        if "customfield_10040" in f:
            f["customfield_10040"] = [{"value": B}, {"value": A}]
        if f["issuetype"]["name"] == "Bug":
            f["customfield_10098"] = {"value": A}
        f["assignee"] = {"displayName": B}
        if "labels" in f:
            f["labels"] = [A, "Pod-" + B]
        f["customfield_10139"] = {"value": A}
    cfb = copy.deepcopy(fx.opencfb)
    for n in cfb:
        n["fields"]["summary"] = A
        n["fields"]["customfield_10117"] = B + " an edited analysis"
    caps = copy.deepcopy(fx.capsnodes)
    caps[0]["fields"]["summary"] = B
    far = copy.deepcopy(fx.farnodes)
    far[0]["fields"]["summary"] = A
    capn = copy.deepcopy(fx.capnodes)
    for n in capn:
        n["fields"]["customfield_10079"] = {"value": "Capitalize - " + A}
        n["fields"]["customfield_10098"] = {"value": B}
    r = H.scenario("ok", page1=nodes[:4], page2=nodes[4:], opencfb=cfb, capsnodes=caps, farnodes=far, capnodes=capn, cache=False, timeout=30)
    ch = ctx.chrome
    t.check(not r["timed_out"] and r["status"].startswith("Refreshed "), f"the refresh with hostile responses completed -> {r['status'][:60]}")
    ch.js(PREPARE_JS)
    settle(ch)
    res = ch.js(CHECK_JS)
    base = baseline(ch)
    t.check(res["x"] is None and res["badImgs"] == 0 and res["handlers"] <= base["handlers"] and res["scripts"] <= base["scripts"] and res["tipBad"] == 0,
            f"after the refresh: window.__x={res['x']}, injected images {res['badImgs']}, handlers {res['handlers']}, scripts {res['scripts']}, hostile tooltip nodes {res['tipBad']}")
    t.check(res["shown"] >= 5, f"the merged hostile strings are rendered as text ({res['shown']} places)")


if __name__ == "__main__":
    sys.exit(kit.cli(SUITE, __doc__))
