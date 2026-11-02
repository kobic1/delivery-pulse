#!/usr/bin/env python3
"""Usage statistics oracle: the block at the end of dashboard.template.html that counts, per anonymous user id, which sections are read and which controls are used (`usage_*`).

The page may only record through the `db` capability, and only with a `user` id (an opaque `u_...` token; no name, no e-mail). `mock_claude.js` answers `claude.use("db")` and `claude.use("user")` with an in-memory fake store that has the documented
semantics (even/odd path grammar -> TypeError, `update` rejects on a missing document, `set` replaces, nested merge, a refusal by code, a write that fails once with `unavailable`) when a case sets CFG.usage; every other suite keeps getting null.
The page's timers (5 s tick, 30 s flush, 30 s first write, 60 s idle) are shortened through window.__dpUsageT, the way the call deadline is, and the browser's Date can be shifted (CFG.shift), so a case that needs a day or year boundary starts there.

What is asserted, each independently of the page's code (the vocabularies and the expectations are spelled out here on purpose):

  * nothing is written at load, before the first input, or before 30 s of visible time; the first write is a `get` then a `set`, every later one a nested-merge `update` of the visit's own session only, never overlapping, never when nothing changed;
  * after strip clicks, a skip link, a filter change, a Jira link click, disclosures, Refresh and Reset Filters the stored session equals an independent expectation (counters by key); nothing outside the allowlist is stored: no other key or value,
    no issue-key-shaped string, no '@', no team, pod, project or epic name of the fixture, no name or e-mail of the (mock) viewer, only the id `u_...`;
  * an idle, hidden or unfocused page accumulates no seconds; a write happens on `visibilitychange` to hidden and on `pagehide` without waiting for the 30 s window;
  * the privacy note shows exactly when logging is active (db and user resolved, an id of the documented shape) and the page works, with no console error, when db is null, user is null, the id is null or an e-mail, there is no claude at all;
  * every write rejected with invalid_argument (what a view-only viewer gets), resource_exhausted or quota_exceeded, or an `unavailable` that never clears: no more than 3 failed attempts, then silence; `unavailable` once is retried once and succeeds;
  * retention (8 ISO weeks, at most 30 sessions a day, well below 100 KiB, the only `set` on an existing record), caps of 40 keys a map, two visits of one person do not overwrite each other, a re-sent write changes nothing;
  * Israel day and ISO week across a day boundary, a year boundary (2026-W53 into 2027-W01) and a browser in another timezone;
  * the state and the page are the same with and without logging.

Seeded defects (a name recorded, an issue key recorded, idle time counted, hidden time counted, a write at load, a read before every update, a document per session, unbounded keys, the note shown when inactive, unlimited retries, the viewer's day,
overlapping writes, a write of unchanged data) must each be caught: a green oracle is not a blind one.

    python3 usage_oracle.py [--live] [--only NAME]
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kit                                                                          # noqa: E402
import make_synthetic as MS                                                         # noqa: E402
from kit import ctx, T                                                              # noqa: E402

SUITE = kit.Suite("Delivery Pulse usage statistics")
UID = "u_synthetic_001"
PATH = f"usage/{UID}"
FAST = {"tick": 100, "flush": 400, "first": 1500, "idle": 700, "retry": [40, 90]}      # the page's 5 s / 30 s / 30 s / 60 s, shortened
SEC_KEYS = ["attn", "burnup", "eff", "ai", "bugs", "deps", "nfr", "cx", "capview", "cycles", "analysis"]
VOC = {"sec": SEC_KEYS, "nav": SEC_KEYS, "l": SEC_KEYS + ["other"],
       "f": ["release", "projects", "multi", "teams", "dc", "ax", "cfb", "bugpri", "gran", "cfbgrp", "dp", "nfrtab", "cx", "caplevel", "capby", "capmeasure", "cycle", "cytab", "cystatus", "cypods"],
       "o": ["how", "data", "attn", "other"], "d": ["s", "m", "l"]}
SESSION_KEYS = {"t", "s", "sec", "nav", "f", "l", "o", "r", "rs", "np", "d", "b", "er", "x"}
KEYRE = re.compile(r"[A-Z][A-Z0-9]+-\d+")
DAYRE, WEEKRE, SIDRE = re.compile(r"^\d{4}-\d{2}-\d{2}$"), re.compile(r"^\d{4}-W\d{2}$"), re.compile(r"^[a-z0-9]{8}$")
NOTE_TEXT = "Usage statistics: this page counts, per anonymous user id (no name or e-mail), which sections are opened and which controls are used, to improve the dashboard. What is counted"
CAPS = {"db": {"rules": [{"path": "", "write": "admin"}, {"path": "usage", "read": "admin", "write": "admin"}, {"path": "usage/{self}", "read": "interact", "write": "interact"}]}, "user": {}}


# ------------------------------------------------------------------------------------------------ the page
_fx: dict = {}


def fixture() -> dict:
    if not _fx:
        data = MS.make(MS.il_today())
        data["build"] = {"sha": "abc1234", "dirty": False, "at": "2026-01-01T00:00+02:00"}
        _fx["data"] = data
    return _fx["data"]


def load(usage=..., shift_to: dt.datetime | None = None, hash_: str = "", tz: str | None = None, keep: bool = False, vp: tuple | None = None, claude: bool = True, wait: float = 0.6):
    """Open the page with the mocked connector. usage: None = no usage switches (db and user answer null); a dict = CFG.usage. shift_to: an aware datetime the page's clock starts at. Returns the browser."""
    ch = ctx.chrome
    data = fixture()
    cfg = dict(mode="denied", ls="recent", shift=0, slow=0, fastTimers=False, page1=[], page2=[], capsnodes=[], opencfb=[], linknodes=[], farnodes=[], leftcfb=[], capnodes=[], axkey="X-1", keep=keep)
    if shift_to is not None:
        cfg["shift"] = int(shift_to.timestamp() * 1000 - time.time() * 1000)
    if usage is not ... and usage is not None:
        u = dict(usage)
        u.setdefault("t", FAST)
        cfg["usage"] = u
    pre = ("<script data-harness>" + (HERE / "mock_claude.js").read_text().replace("/*__CFG__*/null", json.dumps(cfg).replace("</", "<\\/")).replace("/*__HOOK__*/null", "null") + "</script>") if claude else ""
    url = ctx.write(kit.wrap(kit.fragment_for(data), pre), "usage")
    ch.cmd("Emulation.setTimezoneOverride", timezoneId=tz or "Asia/Jerusalem")
    if vp:
        ch.viewport(*vp)
    ch.goto(url + (("#" + hash_) if hash_ else ""))
    assert kit.wait_ready(ch), "the page did not draw: " + str(ch.console_errors()[:2])
    time.sleep(wait)
    return ch


def docs(ch) -> dict:
    return json.loads(ch.js("JSON.stringify(window.__dbRead ? window.__dbRead() : {})") or "{}")


def log(ch) -> list:
    return json.loads(ch.js("JSON.stringify(window.__dbLog || [])") or "[]")


def writes(ch) -> list:
    return [e for e in log(ch) if e["op"] in ("set", "update")]


def snap(ch) -> dict:
    return ch.js("window.__dpUsageTest ? JSON.parse(JSON.stringify(window.__dpUsageTest.snap())) : null") or {}


def settle(ch, timeout: float = 8):
    """Force the visit's final write (the page goes hidden) and wait for it, then show the page again."""
    ch.js("window.__vis = 'hidden'; document.dispatchEvent(new Event('visibilitychange'))")
    ch.wait_for("(() => { const s = window.__dpUsageTest.snap(); return !s.inflight && !s.dirty; })()", timeout)
    time.sleep(0.15)
    ch.js("window.__vis = 'visible'")


def session(ch, doc: dict | None = None) -> dict:
    s = snap(ch)
    d = (doc if doc is not None else docs(ch)).get(PATH) or {}
    return (((d.get("w") or {}).get(s.get("sessWeek")) or {}).get(s.get("sessDay")) or {}).get(s["S"]["sid"]) or {}


def forbidden(data: dict) -> set:
    out = {"Synthetic Person", "synthetic.person", "example.invalid", "jira.example.test", "Delivery Pulse"}
    out |= set(data["projects"])
    for e in data["epics"]:
        out |= set(e.get("tm") or []) | {e.get("t"), e.get("k"), e.get("pod")} | set(e.get("labels") or [])
    for b in data["bugs"]:
        out |= {b.get("k"), b.get("tm")}
    for v in (data.get("hier") or {}).values():
        out.add(v.get("t"))
    return {x for x in out if isinstance(x, str) and len(x) >= 3}


def allowlist_problems(doc: dict, data: dict, uid: str = UID) -> list[str]:
    bad: list[str] = []
    if not isinstance(doc, dict):
        return ["no record"]
    if set(doc) - {"u", "v", "first", "last", "w"}:
        bad.append(f"top-level keys outside the list: {sorted(set(doc) - {'u', 'v', 'first', 'last', 'w'})}")
    if doc.get("u") != uid or not re.match(r"^u_[A-Za-z0-9_-]+$", str(doc.get("u"))):
        bad.append("the id is not the opaque u_ token")
    if doc.get("v") != 1:
        bad.append("schema is not 1")
    for k in ("first", "last"):
        if k in doc and not DAYRE.match(str(doc[k])):
            bad.append(f"{k} is not a day")
    for wk, days in (doc.get("w") or {}).items():
        if not WEEKRE.match(wk):
            bad.append(f"week key {wk!r}")
        for day, sess in days.items():
            if not DAYRE.match(day):
                bad.append(f"day key {day!r}")
            for sid, s in sess.items():
                if not SIDRE.match(sid):
                    bad.append(f"session id {sid!r}")
                if set(s) - SESSION_KEYS:
                    bad.append(f"session keys outside the list: {sorted(set(s) - SESSION_KEYS)}")
                for m in ("sec", "nav", "f", "l", "o"):
                    for k, v in (s.get(m) or {}).items():
                        if k not in VOC[m]:
                            bad.append(f"{m} key outside the vocabulary: {k!r}")
                        if not (isinstance(v, int) and 0 < v <= 1000):
                            bad.append(f"{m}.{k} value {v!r}")
                    if len(s.get(m) or {}) > 40:
                        bad.append(f"{m} has more than 40 keys")
                for k in ("t", "s", "r", "rs", "np", "er", "x"):
                    if k in s and not (isinstance(s[k], int) and not isinstance(s[k], bool) and 0 <= s[k] < 10 ** 9):
                        bad.append(f"{k} value {s[k]!r}")
                if "d" in s and s["d"] not in VOC["d"]:
                    bad.append(f"d value {s['d']!r}")
                if "b" in s and not re.match(r"^[0-9a-f]{4,12}$", str(s["b"])):
                    bad.append(f"b value {s['b']!r}")
    text = json.dumps(doc)
    if "@" in text:
        bad.append("an '@' is stored")
    if KEYRE.search(text):
        bad.append(f"an issue-key-shaped string is stored: {KEYRE.search(text).group(0)}")
    hit = [x for x in forbidden(data) if x in text]
    if hit:
        bad.append(f"a name from the data or the viewer is stored: {hit[:3]}")
    if len(text.encode()) > 100 * 1024:
        bad.append("the record is over 100 KiB")
    return bad


def errors(ch) -> list:
    return [e for e in ch.console_errors()]


# ------------------------------------------------------------------------------------------------ the scripted reader
NOOPEN = "document.addEventListener('click', e => { const a = e.target.closest && e.target.closest('a[href]'); if (a && !a.getAttribute('href').startsWith('#')) e.preventDefault(); });"      # a Jira link must not navigate the test page


def click(ch, sel: str) -> bool:
    return bool(ch.js(f"(() => {{ const e = document.querySelector({json.dumps(sel)}); if (!e) return false; e.click(); return true; }})()"))


def reader(ch) -> tuple[dict, list[str]]:
    """The scripted reader. Returns the expected counters (worked out here, by key) and what could not be done."""
    exp = {"nav": {}, "f": {}, "l": {}, "o": {}, "r": 0, "rs": 0}
    miss: list[str] = []

    def add(m, k):
        exp[m][k] = exp[m].get(k, 0) + 1

    def do(ok, what):
        if not ok:
            miss.append(what)
        return ok
    ch.js(NOOPEN)
    for sec in ("eff", "deps"):
        if do(click(ch, f'#seclist a[data-jump="h-{sec}"]'), f"strip {sec}"):
            add("nav", sec)
        time.sleep(0.12)
    if do(click(ch, 'a.skip[data-skip="h-proj"]'), "skip link"):                          # By Project sits inside Release Analysis
        add("nav", "analysis")
    # a filter of every kind: the release select, a radio, a checkbox chip, a project chip, the multi-select toggle
    if do(ch.js("(() => { const s = document.getElementById('f-release'); const o = [...s.options].find(x => x.value !== s.value); if (!o) return false; s.value = o.value; s.dispatchEvent(new Event('change', {bubbles: true})); return true; })()"), "release"):
        add("f", "release")
    time.sleep(0.15)
    if do(click(ch, '#f-ax input[value="yes"]'), "ax"):
        add("f", "ax")
    time.sleep(0.15)
    if do(click(ch, '#f-bpri input[value="P4"]'), "bug priority"):
        add("f", "bugpri")
    time.sleep(0.15)
    if do(click(ch, "#f-multi"), "multi"):
        add("f", "multi")
    time.sleep(0.15)
    if do(click(ch, '#f-projects button.chip[data-p]'), "project chip"):
        add("f", "projects")
    time.sleep(0.15)
    # Jira links, classified by the section they sit in: a /browse/ link in Needs Attention, a query link in Quality, one in a sub-block of Release Analysis
    if do(click(ch, 'section[aria-labelledby="h-attn"] a[href^="https://jira.example.test/browse/"]'), "attn link"):
        add("l", "attn")
    if do(click(ch, 'section[aria-labelledby="h-bugs"] a[href^="https://jira.example.test/issues/"]'), "bugs link"):
        add("l", "bugs")
    if do(click(ch, '#tbl-projects a[href^="https://jira.example.test/"]'), "analysis link"):
        add("l", "analysis")
    # disclosures: opened with the summary, the way a reader does
    for sel, key in (('section[aria-labelledby="h-eff"] details > summary', "how"), ('section[aria-labelledby="h-burnup"] details.vd > summary:not(:first-child), section[aria-labelledby="h-burnup"] details > summary', None)):
        pass
    plan = [("how", 'section[aria-labelledby="h-eff"]', "How this is calculated"), ("data", 'section[aria-labelledby="h-eff"]', "Show data"), ("attn", 'section[aria-labelledby="h-attn"]', "More detail"), ("other", "footer", "How to Read This Page")]
    for key, within, text in plan:
        if do(ch.js(f"(() => {{ const s = [...document.querySelectorAll({json.dumps(within)} + ' details > summary')].find(x => x.textContent.trim().startsWith({json.dumps(text)}) && !x.parentElement.open); if (!s) return false; s.click(); return true; }})()"), f"details {key}"):
            add("o", key)
        time.sleep(0.15)
    if do(click(ch, "#refresh"), "refresh"):
        exp["r"] += 1
    time.sleep(0.4)
    if do(click(ch, "#f-reset:not([disabled])"), "reset"):
        exp["rs"] += 1
    time.sleep(0.2)
    return exp, miss


def compare(ch, exp: dict) -> list[str]:
    s = session(ch)
    bad = []
    for m in ("nav", "f", "l", "o"):
        if (s.get(m) or {}) != exp[m]:
            bad.append(f"{m}: stored {s.get(m)} but the reader did {exp[m]}")
    for k in ("r", "rs"):
        if (s.get(k) or 0) != exp[k]:
            bad.append(f"{k}: stored {s.get(k)} but the reader did {exp[k]}")
    if s.get("d") != "l":
        bad.append(f"device width class {s.get('d')} at 1400 px")
    if s.get("b") != "abc1234":
        bad.append(f"build {s.get('b')}")
    if s.get("np") != len(fixture()["projects"]):
        bad.append(f"np {s.get('np')}")
    return bad


# ------------------------------------------------------------------------------------------------ the batteries (each returns a list of problems; the tests and the seeded-defect checks use the same ones)
def b_main() -> list[str]:
    """Nothing before input; then the scripted reader; the stored session equals the expectation; the allowlist; one writer at a time; the shape of the calls."""
    bad: list[str] = []
    ch = load(usage={"latency": 150, "t": {**FAST, "flush": 100}})                  # a slow store and a short window: a second write would start while the first is in flight
    if log(ch):
        bad.append(f"something was written before any input: {log(ch)[:2]}")
    exp, miss = reader(ch)
    bad += [f"the reader could not do: {x}" for x in miss]
    settle(ch)
    bad += compare(ch, exp)
    d = docs(ch)
    bad += allowlist_problems(d.get(PATH), fixture())
    if set(d) != {PATH}:
        bad.append(f"documents other than {PATH}: {sorted(d)}")
    s = session(ch)
    if s.get("s", 0) % 5 or sum((s.get("sec") or {}).values()) > s.get("s", 0):
        bad.append(f"seconds {s.get('s')} / sec {s.get('sec')}")
    ops = [e for e in log(ch)]
    if [e["op"] for e in ops[:2]] != ["get", "set"]:
        bad.append(f"the first write is not a get then a set: {[e['op'] for e in ops[:3]]}")
    if any(e["op"] not in ("get", "set", "update") for e in ops) or any(e["path"] != PATH for e in ops):
        bad.append("a call to another path or another verb")
    if [e["op"] for e in ops].count("get") != 1 or [e["op"] for e in ops].count("set") != 1:
        bad.append(f"get/set are not once each: {[e['op'] for e in ops]}")
    for e in ops:
        if e["op"] == "update":
            w = (e["data"] or {}).get("w") or {}
            days = [d2 for v in w.values() for d2 in v.values()]
            if set(e["data"]) - {"last", "w", "first"} or len(w) != 1 or len(days) != 1 or len(days[0]) != 1:
                bad.append(f"an update that is not exactly one session: {list(e['data'])}")
                break
    if ch.js("window.__dbOverlap") != 0:
        bad.append("two writes to one document overlapped")
    if any(e["result"] != "ok" for e in ops):
        bad.append(f"a call failed: {[e['result'] for e in ops]}")
    bad += errors(ch)
    return bad


def b_idle() -> list[str]:
    bad: list[str] = []
    ch = load(usage={})
    snapv = lambda: snap(ch)["S"]["s"]

    def poke():
        ch.js("document.dispatchEvent(new Event('pointermove'))")
    for _ in range(8):                                                                   # a reader: input every 150 ms for 1.2 s
        poke(); time.sleep(0.15)
    used = snapv()
    if used < 15 or used % 5:
        bad.append(f"an active reader accumulated {used} s (expected a few ticks of 5)")
    time.sleep(1.7)                                                                      # idle: longer than the idle window plus a flush
    s1 = snapv(); w1 = len(writes(ch))
    time.sleep(1.4)
    if snapv() != s1:
        bad.append(f"an idle page kept counting: {s1} -> {snapv()}")
    if len(writes(ch)) != w1:
        bad.append(f"writes with nothing changed: {w1} -> {len(writes(ch))}")
    ch.js("window.__vis = 'hidden'; document.dispatchEvent(new Event('visibilitychange'))"); time.sleep(0.4)
    s2 = snapv()
    for _ in range(6):
        poke(); time.sleep(0.12)
    if snapv() != s2:
        bad.append(f"a hidden page counted: {s2} -> {snapv()}")
    ch.js("window.__vis = 'visible'; window.__focus = false")
    for _ in range(6):
        poke(); time.sleep(0.12)
    if snapv() != s2:
        bad.append(f"an unfocused page counted: {s2} -> {snapv()}")
    ch.js("window.__focus = true")
    for _ in range(6):
        poke(); time.sleep(0.12)
    if snapv() <= s2:
        bad.append("control: a visible, focused, used page did not count again")
    bad += errors(ch)
    return bad


def b_load() -> list[str]:
    bad: list[str] = []
    ch = load(usage={"t": None})                                                         # the real timers: 30 s
    time.sleep(2.5)
    if log(ch):
        bad.append(f"written within 2.5 s of load with no input: {log(ch)[:2]}")
    ch = load(usage={"t": {**FAST, "first": 60000}})
    time.sleep(1.5)
    if log(ch):
        bad.append("written before the first input")
    click(ch, '#seclist a[data-jump="h-eff"]')
    if not ch.wait_for("window.__dbLog.some(e => e.op === 'set' && e.result === 'ok')", 3):
        bad.append("no write after the first input")
    ch = load(usage={}, wait=0.1)                                                        # a visit that only reads: one write after the visible time, with no counters
    time.sleep(0.7)
    if log(ch):
        bad.append("written before the visible time was up")
    if not ch.wait_for("window.__dbLog.some(e => e.op === 'set' && e.result === 'ok')", 4):
        bad.append("a reading-only visit was never recorded")
    else:
        s = session(ch)
        if any(k in s for k in ("nav", "f", "l", "o", "sec")) or s.get("s", 0):
            bad.append(f"a visit with no input recorded activity: {s}")
    bad += errors(ch)
    return bad


def b_notice() -> list[str]:
    bad: list[str] = []
    cases = [("db null", dict(db=None)), ("user null", dict(user=None)), ("id null", dict(uid=None)), ("an e-mail as id", dict(uid="someone@example.invalid")), ("no u_ prefix", dict(uid="abc123")), ("no claude", None)]
    for name, u in cases:
        ch = load(usage=u if u is not None else None, claude=u is not None)
        time.sleep(1.0)
        if ch.js("!!document.getElementById('usage-note')"):
            bad.append(f"{name}: the note is shown")
        click(ch, '#seclist a[data-jump="h-eff"]'); time.sleep(1.2)
        if log(ch):
            bad.append(f"{name}: calls to the store: {log(ch)[:2]}")
        if not ch.js("document.getElementById('f-release') && document.querySelectorAll('section').length > 5"):
            bad.append(f"{name}: the page does not work")
        bad += [f"{name}: {e}" for e in errors(ch)]
    ch = load(usage={})
    note = ch.js("(() => { const n = document.getElementById('usage-note'); if (!n) return null; const b = n.querySelector('button'), l = document.getElementById('usage-what'); return {text: n.querySelector('p').textContent, hidden: n.hidden, inFooter: !!n.closest('footer'), exp: b.getAttribute('aria-expanded'), ctl: b.getAttribute('aria-controls'), listHidden: l.hidden, items: [...l.querySelectorAll('li')].map(x => x.textContent), lastInFooter: document.getElementById('footer').lastElementChild === n}; })()")
    if not note:
        return bad + ["logging is active and no note is shown"]
    if note["text"] != NOTE_TEXT:
        bad.append(f"the note reads {note['text']!r}")
    if note["hidden"] or not note["inFooter"] or not note["lastInFooter"]:
        bad.append("the note is not shown at the very bottom of the page")
    if note["exp"] != "false" or note["ctl"] != "usage-what" or not note["listHidden"]:
        bad.append("the toggle starts open or is not wired")
    click(ch, "#usage-note button")
    after = ch.js("({exp: document.querySelector('#usage-note button').getAttribute('aria-expanded'), hidden: document.getElementById('usage-what').hidden, n: document.querySelectorAll('#usage-what li').length, text: document.getElementById('usage-what').textContent})")
    if after["exp"] != "true" or after["hidden"] or after["n"] != 7 or "8 weeks" not in after["text"] or "Never counted" not in after["text"]:
        bad.append(f"the list does not open or lacks the retention and exclusions: {after}")
    ch.js(NOOPEN)
    ch = load(usage={"fault": "invalid"})                                                # a refused write: the note goes away (nothing is being recorded)
    click(ch, '#seclist a[data-jump="h-eff"]')
    ch.wait_for("window.__dbLog.some(e => e.result === 'invalid_argument')", 4); time.sleep(0.3)
    if ch.js("(() => { const n = document.getElementById('usage-note'); return !!n && !n.hidden; })()"):
        bad.append("the note stays after the visit stopped recording")
    bad += errors(ch)
    return bad


def b_fail() -> list[str]:
    bad: list[str] = []

    def drive(ch, seconds: float):
        end = time.time() + seconds
        while time.time() < end:
            click(ch, '#seclist a[data-jump="h-eff"]'); click(ch, '#seclist a[data-jump="h-bugs"]'); time.sleep(0.12)

    def run(name, usage, seconds=4.0, stops=True):
        ch = load(usage={"t": {**FAST, "flush": 300}, **usage})
        drive(ch, seconds)
        n1 = len(log(ch))
        drive(ch, 1.5)
        if stops and len(log(ch)) != n1:
            bad.append(f"{name}: more calls after the visit should have stopped: {n1} -> {len(log(ch))}")
        if not ch.js("document.querySelectorAll('#seclist a').length === 11"):
            bad.append(f"{name}: the page does not work")
        bad.extend(f"{name}: {e}" for e in errors(ch))
        return ch, log(ch)
    ch, lg = run("every write invalid_argument (a view-only viewer)", dict(fault="invalid"))
    if [e["op"] for e in lg] != ["get", "set"]:
        bad.append(f"invalid_argument: expected one get and one set, got {[(e['op'], e['result']) for e in lg]}")
    ch, lg = run("resource_exhausted", dict(fault="exhausted"))
    if [e["op"] for e in lg if e["op"] == "set"] != ["set"] * 3 or any(e["result"] != "resource_exhausted" for e in lg if e["op"] == "set"):
        bad.append(f"resource_exhausted: expected exactly 3 failed writes, got {[(e['op'], e['result']) for e in lg]}")
    ch, lg = run("quota_exceeded", dict(fault="quota"))
    if len([e for e in lg if e["op"] == "set"]) != 1:
        bad.append(f"quota_exceeded: expected one write, got {[(e['op'], e['result']) for e in lg]}")
    ch, lg = run("unavailable once", dict(fault="unavailable_once"), seconds=2.5, stops=False)
    st = [(e["op"], e["result"]) for e in lg if e["op"] in ("set", "update")]
    if st[:2] != [("set", "unavailable"), ("set", "ok")] or any(r != "ok" for _, r in st[2:]):
        bad.append(f"unavailable once: expected the write retried once and then ok, got {st[:5]}")
    if PATH not in docs(ch):
        bad.append("unavailable once: nothing was stored")
    ch, lg = run("unavailable for ever", dict(fault="unavailable_always"), seconds=5.5)
    if len([e for e in lg if e["op"] == "set"]) != 6:
        bad.append(f"unavailable for ever: expected 3 attempts of 2 tries, got {len([e for e in lg if e['op'] == 'set'])} writes")
    ch, lg = run("get fails", dict(getFault="resource_exhausted"))
    if [e["op"] for e in lg] != ["get"] * 3:
        bad.append(f"a failing get: expected 3 gets and nothing else, got {[(e['op'], e['result']) for e in lg]}")
    return bad


def b_day() -> list[str]:
    bad: list[str] = []
    cases = [("2026-12-31T21:59:50Z", "America/Los_Angeles", "2026-12-31", "2026-W53"),       # 23:59:50 in Israel; the browser is in Los Angeles
             ("2026-12-31T22:30:00Z", "America/Los_Angeles", "2027-01-01", "2026-W53"),       # already the next day in Israel, still the 31st in the browser and in UTC; 1 January 2027 is still ISO week 53 of 2026
             ("2027-01-04T05:00:00Z", "Pacific/Kiritimati", "2027-01-04", "2027-W01"),        # a Monday: week 1; the browser is a day ahead
             ("2026-11-02T10:00:00Z", None, "2026-11-02", "2026-W45")]
    for iso, tz, day, week in cases:
        when = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        ch = load(usage={}, shift_to=when, tz=tz)
        click(ch, '#seclist a[data-jump="h-eff"]'); time.sleep(0.5)
        settle(ch)
        d = docs(ch).get(PATH) or {}
        got = {wk: sorted(days) for wk, days in (d.get("w") or {}).items()}
        if got != {week: [day]}:
            bad.append(f"at {iso} ({tz}) the session is keyed {got}, expected {week} / {day}")
        if d.get("first") != day:
            bad.append(f"at {iso} first is {d.get('first')}, expected {day}")
    # a visit that runs across midnight stays on the day it opened; `last` moves on
    ch = load(usage={"t": {**FAST, "flush": 200}}, shift_to=dt.datetime(2026, 12, 31, 21, 59, 58, tzinfo=dt.timezone.utc))
    click(ch, '#seclist a[data-jump="h-eff"]'); time.sleep(0.3)
    ch.wait_for("Date.now() > Date.UTC(2026, 11, 31, 22, 0, 1)", 6)
    click(ch, '#seclist a[data-jump="h-bugs"]'); time.sleep(0.8); settle(ch)
    d = docs(ch).get(PATH) or {}
    if {wk: sorted(v) for wk, v in (d.get("w") or {}).items()} != {"2026-W53": ["2026-12-31"]} or d.get("last") != "2027-01-01":
        bad.append(f"a visit across midnight: {json.dumps(d)[:200]}")
    # the page's week function against Python's isocalendar for 900 consecutive days
    ch = load(usage={})
    days = [(dt.date(2025, 12, 20) + dt.timedelta(days=i)).isoformat() for i in range(900)]
    got = ch.js(f"{json.dumps(days)}.map(d => window.__dpUsageTest.weekOf(d))")
    want = [f"{(dt.date.fromisoformat(d).isocalendar()[0])}-W{dt.date.fromisoformat(d).isocalendar()[1]:02d}" for d in days]
    if got != want:
        i = next(i for i, (a, b) in enumerate(zip(got, want)) if a != b)
        bad.append(f"ISO week of {days[i]}: page {got[i]}, expected {want[i]}")
    return bad


def b_cap() -> list[str]:
    ch = load(usage={})
    out = ch.js("(() => { const m = {}; let x = 0; for (let i = 0; i < 60; i++) { if (window.__dpUsageTest.room(m, 'k' + i)) m['k' + i] = 1; else x++; } return {keys: Object.keys(m).length, x}; })()")
    return [] if out == {"keys": 40, "x": 20} else [f"a counter map took {out['keys']} keys and dropped {out['x']} (expected 40 and 20)"]


# ------------------------------------------------------------------------------------------------ tests
@SUITE.test("usage_the_vocabularies_and_the_documented_access_rules_are_the_ones_in_the_page")
def _(t: T):
    src = ctx.template.read_text(encoding="utf-8")
    m = re.search(r"const USAGE_VOC = (\{.*?\});\n", src)
    t.check(bool(m), "the page has one USAGE_VOC literal")
    if m:
        t.check(json.loads(m.group(1)) == VOC, "the page's vocabulary equals the one spelled out in this oracle")
    t.check(json.dumps(CAPS)[1:-1] in src.replace('": ', '":').replace('", ', '",') or "usage/{self}" in src, "the access rules are written in the page")
    t.check('user.id()' in src and 'user.name' not in src and 'user.email' not in src and 'scopes' not in src[src.index("const USAGE_VOC"):], "the block reads only user.id(): no name, no e-mail, no scopes")
    t.check(src.count("window.claude.use(\"db\")") == 1 and "fetch(" not in src[src.index("const USAGE_VOC"):] and "sendBeacon" not in src and "XMLHttpRequest" not in src[src.index("const USAGE_VOC"):], "the only way out of the block is the db capability")


@SUITE.test("usage_nothing_is_written_at_load_before_input_or_before_30_seconds")
def _(t: T):
    bad = b_load()
    t.check(not bad, "; ".join(bad))


@SUITE.test("usage_the_stored_session_equals_an_independent_expectation_and_holds_only_the_allowlist")
def _(t: T):
    bad = b_main()
    t.check(not bad, "; ".join(bad))


@SUITE.test("usage_an_idle_hidden_or_unfocused_page_accumulates_no_seconds_and_nothing_unchanged_is_written")
def _(t: T):
    bad = b_idle()
    t.check(not bad, "; ".join(bad))


@SUITE.test("usage_the_note_shows_exactly_when_logging_is_active_and_the_page_works_without_it")
def _(t: T):
    bad = b_notice()
    t.check(not bad, "; ".join(bad))


@SUITE.test("usage_refused_or_failing_writes_stop_after_three_and_never_break_the_page")
def _(t: T):
    bad = b_fail()
    t.check(not bad, "; ".join(bad))


@SUITE.test("usage_the_israel_day_and_iso_week_keys_across_a_day_a_year_and_a_timezone")
def _(t: T):
    bad = b_day()
    t.check(not bad, "; ".join(bad))


@SUITE.test("usage_a_counter_map_holds_at_most_40_keys")
def _(t: T):
    bad = b_cap()
    t.check(not bad, "; ".join(bad))


@SUITE.test("usage_a_write_is_sent_on_visibilitychange_and_on_pagehide_without_waiting_for_the_window")
def _(t: T):
    ch = load(usage={"t": {**FAST, "flush": 60000}})
    click(ch, '#seclist a[data-jump="h-eff"]')
    t.check(ch.wait_for("window.__dbLog.some(e => e.op === 'set' && e.result === 'ok')", 3), "the first write follows the first input at once")
    n = len(writes(ch))
    click(ch, '#seclist a[data-jump="h-bugs"]'); time.sleep(0.8)
    t.check(len(writes(ch)) == n, "a change is held back inside the flush window")
    ch.js("window.__vis = 'hidden'; document.dispatchEvent(new Event('visibilitychange'))")
    t.check(ch.wait_for(f"window.__dbLog.filter(e => e.op === 'update' && e.result === 'ok').length >= 1", 3), "going hidden writes the held change")
    t.check((session(ch).get("nav") or {}) == {"eff": 1, "bugs": 1}, f"the session after the hidden write: {session(ch).get('nav')}")
    ch.js("window.__vis = 'visible'")
    click(ch, '#seclist a[data-jump="h-ai"]'); time.sleep(0.5)
    ch.js("window.dispatchEvent(new Event('pagehide'))")
    t.check(ch.wait_for("(session => true)() && window.__dbLog.filter(e => e.op === 'update' && e.result === 'ok').length >= 2", 3) and (session(ch).get("nav") or {}).get("ai") == 1, "leaving the page writes the held change")
    t.check(not errors(ch), f"console: {errors(ch)[:2]}")


@SUITE.test("usage_retention_keeps_8_weeks_30_sessions_a_day_and_a_small_record_with_one_set_on_an_existing_record")
def _(t: T):
    now = dt.datetime(2026, 11, 10, 10, 0, tzinfo=dt.timezone.utc)                      # ISO week 46 of 2026
    weeks = [(dt.date(2026, 11, 9) - dt.timedelta(days=7 * i)) for i in range(0, 16)]
    seed: dict = {}
    full = lambda i, w: {"t": 29_000_000 + i + 100 * w, "s": 300, "sec": {k: 12 for k in SEC_KEYS}, "nav": {k: 3 for k in SEC_KEYS}, "f": {k: 2 for k in VOC["f"]}, "l": {k: 1 for k in VOC["l"]}, "d": "l", "b": "abc1234"}
    for d0 in weeks:
        y, w, _ = d0.isocalendar()
        seed[f"{y}-W{w:02d}"] = {(d0 + dt.timedelta(days=j)).isoformat(): {f"s{i:07d}": full(i, w) for i in range(70 if (d0, j) == (dt.date(2026, 11, 9), 0) else 25)} for j in range(3)}
    seed["2026-W46"]["2026-11-10"] = {f"s{i:07d}": full(i, 99) for i in range(70)}
    body = {"u": UID, "v": 1, "first": "2026-04-01", "last": "2026-11-09", "w": seed}
    ch = load(usage={"seed": {PATH: body}}, shift_to=now)
    t.check(len(json.dumps(body)) > 100 * 1024, f"the seeded record is large ({len(json.dumps(body)) // 1024} KiB)")
    click(ch, '#seclist a[data-jump="h-eff"]')
    ch.wait_for("window.__dbLog.some(e => e.op === 'set' && e.result === 'ok')", 4)
    time.sleep(0.3)
    d = docs(ch)[PATH]
    kept = sorted(d["w"])
    t.check(kept[0] >= "2026-W39" and kept[-1] == "2026-W46" and 1 <= len(kept) <= 8, f"weeks kept: {kept}")
    t.check(all(len(v) <= 30 for days in d["w"].values() for v in days.values()) and len(d["w"]["2026-W46"]["2026-11-10"]) == 30, "the day with 70 sessions is cut to the 30 newest, the visit's own among them")
    t.check(all(len(v) <= 30 for days in d["w"].values() for v in days.values()), "at most 30 sessions a day")
    t.check(len(json.dumps(d).encode()) < 100 * 1024, f"the record is {len(json.dumps(d)) // 1024} KiB, below 100 KiB")
    sd = snap(ch)
    t.check(sd["S"]["sid"] in d["w"]["2026-W46"]["2026-11-10"], "the visit's own session is kept")
    t.check(d["first"] == "2026-04-01", "first is kept")
    click(ch, '#seclist a[data-jump="h-bugs"]'); time.sleep(0.9)
    sets = [e for e in log(ch) if e["op"] == "set"]
    t.check(len(sets) == 1 and [e["op"] for e in log(ch)].count("get") == 1, f"one get and one set, then updates only: {[e['op'] for e in log(ch)]}")
    t.check(ch.js("window.__dbOverlap") == 0 and not errors(ch), "no overlap, no console error")
    # a light record: older than 8 weeks goes, exactly the last 8 weeks stay
    light = {"u": UID, "v": 1, "first": "2026-04-01", "last": "2026-11-09", "w": {f"{d0.isocalendar()[0]}-W{d0.isocalendar()[1]:02d}": {d0.isoformat(): {"zzzzzzz1": {"t": 1, "s": 5}}} for d0 in weeks}}
    ch = load(usage={"seed": {PATH: light}}, shift_to=now)
    click(ch, '#seclist a[data-jump="h-eff"]'); ch.wait_for("window.__dbLog.some(e => e.op === 'set' && e.result === 'ok')", 4); time.sleep(0.2)
    t.check(sorted(docs(ch)[PATH]["w"]) == [f"2026-W{n}" for n in range(39, 47)], f"exactly the last 8 ISO weeks stay: {sorted(docs(ch)[PATH]['w'])}")
    # a record that is small and current is not rewritten: the first write is an update
    small = {"u": UID, "v": 1, "first": "2026-11-01", "last": "2026-11-09", "w": {"2026-W45": {"2026-11-09": {"zzzzzzz1": {"t": 1, "s": 5}}}}}
    ch = load(usage={"seed": {PATH: small}}, shift_to=now)
    click(ch, '#seclist a[data-jump="h-eff"]'); ch.wait_for("window.__dbLog.some(e => e.op === 'update' && e.result === 'ok')", 4)
    t.check([e["op"] for e in log(ch)][:2] == ["get", "update"] and "set" not in [e["op"] for e in log(ch)], f"an existing small record is merged into, never replaced: {[e['op'] for e in log(ch)]}")
    d = docs(ch)[PATH]
    t.check("zzzzzzz1" in d["w"]["2026-W45"]["2026-11-09"], "the earlier visit is untouched")


@SUITE.test("usage_two_visits_of_one_person_do_not_overwrite_each_other_and_a_resent_write_changes_nothing")
def _(t: T):
    ch = load(usage={"share": True})
    click(ch, '#seclist a[data-jump="h-eff"]'); click(ch, '#seclist a[data-jump="h-bugs"]'); time.sleep(0.4)
    settle(ch)
    a = snap(ch)["S"]["sid"]; d1 = docs(ch)[PATH]
    ch = load(usage={"share": True}, keep=True)                                            # the same person again (a second tab or a later visit): the same store
    b = snap(ch)["S"]["sid"]
    click(ch, '#seclist a[data-jump="h-ai"]'); time.sleep(0.4)
    settle(ch)
    d2 = docs(ch)[PATH]
    sess = {sid: s for wk in d2["w"].values() for day in wk.values() for sid, s in day.items()}
    t.check(a != b and set(sess) == {a, b}, f"both sessions are in the record: {sorted(sess)}")
    t.check(sess[a].get("nav") == {"eff": 1, "bugs": 1} and sess[b].get("nav") == {"ai": 1}, f"each keeps its own counters: {sess[a].get('nav')} {sess[b].get('nav')}")
    t.check([e["op"] for e in log(ch)][:2] == ["get", "update"], f"the second visit merges: {[e['op'] for e in log(ch)][:3]}")
    t.check(d2["first"] == d1["first"], "first is not moved")
    # a write that is sent twice (a retried write) leaves the record exactly as one write does
    before = json.dumps(docs(ch)[PATH], sort_keys=True)
    ch.js("""(async () => { const db = await window.claude.use('db'); const ref = db.doc('usage/u_synthetic_001'); const cur = (await ref.get()).data(); const wk = Object.keys(cur.w)[0], day = Object.keys(cur.w[wk])[0], sid = Object.keys(cur.w[wk][day])[0];
        const patch = {last: cur.last, w: {[wk]: {[day]: {[sid]: cur.w[wk][day][sid]}}}}; await ref.update(patch); await ref.update(patch); })()""")
    t.check(json.dumps(docs(ch)[PATH], sort_keys=True) == before, "the same update twice changes nothing")
    # the fake store has the documented semantics (so the other assertions mean something)
    out = ch.js("""(async () => { const db = await window.claude.use('db'); const r = {};
        try { db.doc('usage'); r.odd = 'no throw'; } catch (e) { r.odd = e.constructor.name; }
        try { db.collection('usage/x'); r.even = 'no throw'; } catch (e) { r.even = e.constructor.name; }
        try { db.doc('a//b'); r.empty = 'no throw'; } catch (e) { r.empty = e.constructor.name; }
        try { await db.doc('nothing/here').update({a: 1}); r.upd = 'ok'; } catch (e) { r.upd = e.code; }
        await db.doc('t/x').set({a: {b: 1, c: 2}, l: [1, 2]}); await db.doc('t/x').update({a: {b: 5}, l: [9]}); r.merged = (await db.doc('t/x').get()).data();
        await db.doc('t/x').set({z: 1}); r.replaced = (await db.doc('t/x').get()).data();
        try { await db.doc('t/y').set([1]); r.arr = 'ok'; } catch (e) { r.arr = e.code; }
        r.missing = (await db.doc('t/none').get()).exists; return r; })()""")
    t.check(out == {"odd": "TypeError", "even": "TypeError", "empty": "TypeError", "upd": "invalid_argument", "merged": {"a": {"b": 5, "c": 2}, "l": [9]}, "replaced": {"z": 1}, "arr": "invalid_argument", "missing": False}, f"mock semantics: {out}")


@SUITE.test("usage_the_state_and_the_page_are_the_same_with_and_without_logging")
def _(t: T):
    def run(usage):
        ch = load(usage=usage, hash_="")
        ch.js(NOOPEN)
        for sel in ('#f-ax input[value="yes"]', '#f-bpri input[value="P4"]', '#f-capby input[value="release"]', '#seclist a[data-jump="h-bugs"]'):
            click(ch, sel); time.sleep(0.2)
        time.sleep(0.5)
        return ch.js("""({ls: localStorage.getItem('delivery-pulse-filters'), body: [...document.body.querySelectorAll('main, header')].map(e => e.innerText).join('\\n'), cur: (document.querySelector('#seclist a[aria-current]') || {}).textContent, errs: 0})""") | {"errors": errors(ch)}
    a, b = run(None), run({})
    t.check(a["ls"] == b["ls"] and "ax=yes" in (a["ls"] or "") and "bp=" in (a["ls"] or ""), f"the stored filters are identical: {a['ls']} / {b['ls']}")
    t.check(a["body"] == b["body"], "every word of the page is identical")
    t.check(a["cur"] == b["cur"] and not a["errors"] and not b["errors"], f"scroll position and console: {a['errors']} {b['errors']}")


@SUITE.test("usage_the_note_is_in_the_pages_caption_style_and_follows_the_copy_rules")
def _(t: T):
    ch = load(usage={})
    r = ch.js("""(() => { const p = document.querySelector('#usage-note p'), c = document.querySelector('#footer .cap'); const a = getComputedStyle(p), b = getComputedStyle(c);
        return {size: a.fontSize, color: a.color, ref: [b.fontSize, b.color], text: document.getElementById('usage-note').innerText}; })()""")
    t.check(r["size"] == r["ref"][0] and r["color"] == r["ref"][1], f"the note uses the caption size and colour: {r['size']} {r['color']} against {r['ref']}")
    t.check("In Progress" not in r["text"] and "  " not in r["text"], "no stray wording")
    for line in [NOTE_TEXT] + ch.js("[...document.querySelectorAll('#usage-what li')].map(x => x.textContent)"):
        t.check(line[0].isupper() and not re.search(r"\b(telemetry|analytics|tracking|PII|cookie)\b", line, re.I) and line.split()[0] not in ("Usage",) or line.startswith("Usage statistics:"), f"sentence case, no jargon: {line}")


# ------------------------------------------------------------------------------------------------ seeded defects
def _mutant(src: str, pairs: list, name: str) -> Path:
    for old, new in pairs:
        assert src.count(old) == 1, f"the seeding anchor for '{name}' is not in the template exactly once (found {src.count(old)}): the mutation test would be blind: {old[:70]!r}"
        src = src.replace(old, new, 1)
    p = Path(ctx.dir) / f"usage_mutant_{name}.html"
    p.write_text(src, encoding="utf-8")
    return p


def _caught(name: str, pairs: list, battery) -> list[str]:
    src = ctx.template.read_text(encoding="utf-8")
    p = _mutant(src, pairs, name)
    saved = ctx.template
    ctx.template = p
    try:
        return battery()
    finally:
        ctx.template = saved


SEEDS = [
    ("name_recorded", [("uid = id; on = true;", "uid = id; try { S.n = await user.name(); } catch (e) {} on = true;"), ("const o = {t: S.t, s: S.s, d: width()}, sha", "const o = {t: S.t, s: S.s, d: width(), n: S.n}, sha")], b_main),
    ("issue_key_recorded", [('if (a && isJira(a)) bump("l", secOf(a) || "other");', 'if (a && isJira(a)) { const k = ((a.getAttribute("href") || "").match(/[A-Z][A-Z0-9]+-[0-9]+/) || ["other"])[0]; S.l[k] = (S.l[k] || 0) + 1; dirty = true; }')], b_main),
    ("idle_time_counted", [("Date.now() - lastInput < T.idle", "true")], b_idle),
    ("hidden_time_counted", [("    if (visible()) {\n      vis += T.tick;", "    if (true) {\n      vis += T.tick;")], b_idle),
    ("write_at_load", [("timer = setInterval(tick, T.tick); note();", "timer = setInterval(tick, T.tick); note(); interacted = true; dirty = true; flush();")], b_load),
    ("counter_by_read_modify_write", [("if (ready) { await retrying(() => ref.update({last: today, w: mine})); return; }", "if (ready) { await retrying(() => ref.get()); await retrying(() => ref.update({last: today, w: mine})); return; }")], b_main),
    ("document_per_session", [('const ref = db.doc("usage/" + uid), today', 'const ref = db.doc("usage/" + uid + "_" + S.sid), today')], b_main),
    ("unbounded_keys", [("const room = (map, key) => key in map || Object.keys(map).length < MAP_CAP;", "const room = (map, key) => true;")], b_cap),
    ("note_shown_when_inactive", [("async function init() {\n    if (!RUNTIME) return;", "async function init() {\n    if (RUNTIME) note();\n    if (!RUNTIME) return;")], b_notice),
    ("unlimited_retries", [("if (fails >= FAIL_MAX || !e", "if (!e")], b_fail),
    ("the_viewers_day_instead_of_israel", [("const dayOf = ms => ilDate(ms);", "const dayOf = ms => { const d = new Date(ms); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };")], b_day),
    ("overlapping_writes", [("if (inflight || stopped || !on) return;\n    inflight = true;", "if (stopped || !on) return;\n    inflight = true;"), ("if (inflight) { if (force) again = true; return; }", "")], b_main),
    ("write_of_unchanged_data", [("if (!dirty || stopped || !on || !canWrite()) return;", "if (stopped || !on || !canWrite()) return;")], b_idle),
]


def _seed_test(name, pairs, battery):
    @SUITE.test(f"usage_seeded_defect_is_caught_{name}")
    def _(t: T):
        bad = _caught(name, pairs, battery)
        t.check(bool(bad), f"the seeded defect '{name}' was not caught by {battery.__name__}")
        t.note(f"caught: {bad[0][:160] if bad else ''}")


for _n, _p, _b in SEEDS:
    _seed_test(_n, _p, _b)


if __name__ == "__main__":
    sys.exit(kit.cli(SUITE, __doc__))
