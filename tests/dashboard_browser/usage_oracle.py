#!/usr/bin/env python3
"""Usage statistics oracle: the block at the end of dashboard.template.html that counts, per pseudonymous user id, which sections are read and which controls are used (`usage_*`). Schema 2.

The page may only record through the `db` capability, and only with a `user` id (an opaque `u_...` token; no name, no e-mail). `mock_claude.js` answers `claude.use("db")` and `claude.use("user")` with an in-memory fake store that has the documented
semantics (even/odd path grammar -> TypeError, `update` rejects on a missing document, `set` replaces, nested merge, a refusal by code, a write that fails once with `unavailable`) when a case sets CFG.usage; every other suite keeps getting null.
The page's timers (5 s tick, 30 s flush, 30 s first write, 60 s idle, 30 min split) are shortened through window.__dpUsageT, the way the call deadline is, and the browser's Date can be shifted (CFG.shift), so a case that needs a day or year boundary starts there.

What is asserted, each independently of the page's code (the vocabularies and the expectations are spelled out here on purpose; every scripted scenario has its own expected record and the stored session is compared key by key, with no key allowed that is not expected):

  * nothing is written at load, before the first input, or before 30 s of visible time (a glance is written when the page is hidden or left, never earlier); the first write is a `get` then a `set`, every later one a nested-merge `update` of one session only, never overlapping, never when nothing changed;
  * the scripted reader (strip clicks, a skip link, filters, Jira links, disclosures, Refresh, Reset Filters) leaves exactly the expected counters, the schema 2 fields (`vs`, `bt`, `fa`, `lf`, `lv`, `ro`, `rr`, hour-granularity `t`) and nothing outside the allowlist: no other key or value,
    no issue-key-shaped string, no '@', no team, pod, project or epic name of the fixture, no name or e-mail of the (mock) viewer, only the id `u_...`;
  * a glance (visible 5 s or more, no input, under 30 s) is recorded on visibilitychange to hidden and on pagehide with g = 1, one under 5 s is not, a second look is a second visit; a visit with input or 30 s of reading is not a glance;
  * reading time goes to every section of the current side-by-side row (Efficiency and AI Adoption at 1400 px, Efficiency alone at 390 px) and to `top` above the first section anchor;
  * a new visit after 30 minutes without input (shortened) and at Israel midnight, with the week key of the Sunday-to-Saturday week across a Sunday and a year boundary; a middle click on a Jira link is a link followed; ResizeObserver notices are `erb`, never `er`;
  * Refresh declined / failed / ok / no connector give `lv`, `ro`, `r` and `rt`; the age of the data (`fa`) and the build day (`bt`) follow the data stamp and the build time;
  * an idle, hidden or unfocused page accumulates no active seconds (visible seconds `vs` count while unfocused, never while hidden); a write happens on `visibilitychange` to hidden and on `pagehide` without waiting for the 30 s window;
  * the privacy note (the word "pseudonymous", never "anonymous", the retention sentence) shows only after the first successful write of the visit (never when db is null, user is null, the id is null or malformed, or a refused write) and the page works,
    with no console error, when db is null, user is null, the id is null or an e-mail, there is no claude at all;
  * every write rejected with invalid_argument (what a view-only viewer gets), resource_exhausted or quota_exceeded, or an `unavailable` that never clears: no more than 3 failed attempts, then silence; `unavailable` once is retried once and succeeds;
  * retention (12 weeks of Sunday-keyed work weeks, schema 1 ISO keys still read, at most 10 sessions a day, below 100 KiB, the only `set` on an existing record, `pr` when the size cap dropped weeks), caps of 40 keys a map, two visits of one person do not overwrite each other, a re-sent write changes nothing;
  * Israel day and week key across a day boundary, a year boundary and a browser in another timezone;
  * the state and the page are the same with and without logging.

Seeded defects (a name, an issue key, a release or a project recorded, a field outside the list, idle or hidden time counted, a write at load, a read before every update, a document per session, unbounded keys, the note shown when inactive or saying "anonymous",
unlimited retries, the viewer's day, overlapping writes, a write of unchanged data, a glance not recorded or recorded under 5 s, only the first section of a row credited, `top` missing, minute-level `t`, benign errors counted as errors, no split after idle or at midnight,
a middle click not counted, `pr` not set, ISO instead of Sunday weeks, a stale-data bucket off, Refresh declined counted as a failure, the release counted in `lf`) must each be caught: a green oracle is not a blind one.

    python3 usage_oracle.py [--live] [--only NAME]
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kit                                                                          # noqa: E402
import make_synthetic as MS                                                         # noqa: E402
from kit import ctx, T                                                              # noqa: E402

SUITE = kit.Suite("Delivery Pulse usage statistics")
UID = "u_synthetic_001"
PATH = f"usage/{UID}"
IL = ZoneInfo("Asia/Jerusalem")
FAST = {"tick": 100, "flush": 400, "first": 1500, "idle": 700, "split": 4000, "retry": [40, 90]}      # the page's 5 s / 30 s / 30 s / 60 s / 30 min, shortened (a tick of 100 ms stands for 5 s)
SEC_KEYS = ["attn", "burnup", "eff", "ai", "bugs", "deps", "nfr", "cx", "capview", "cycles", "analysis"]
VOC = {"sec": SEC_KEYS + ["top"], "nav": SEC_KEYS, "l": SEC_KEYS + ["other"],
       "f": ["release", "projects", "multi", "teams", "dc", "ax", "cfb", "bugpri", "gran", "cfbgrp", "dp", "nfrtab", "cx", "caplevel", "capby", "capmeasure", "cycle", "cytab", "cystatus", "cypods"],
       "o": ["how", "data", "attn", "other"], "d": ["s", "m", "l"], "ro": ["ok", "fail", "declined"]}
SESSION_KEYS = {"t", "s", "vs", "sec", "nav", "f", "l", "o", "r", "rs", "rt", "np", "d", "b", "bt", "fa", "lf", "lv", "g", "rr", "ro", "er", "erb", "x"}
DOC_KEYS = {"u", "v", "first", "last", "w", "pr"}
KEYRE = re.compile(r"[A-Z][A-Z0-9]+-\d+")
DAYRE, WEEKRE, WEEKRE_V1, SIDRE = re.compile(r"^\d{4}-\d{2}-\d{2}$"), re.compile(r"^S\d{4}-\d{2}-\d{2}$"), re.compile(r"^\d{4}-W\d{2}$"), re.compile(r"^[a-z0-9]{8}$")
NOTE_TEXT = ("Usage statistics: this page counts, per pseudonymous user id (a code, no name or e-mail; only the owner and the editors of this page can read these records), "
             "which sections are opened and which controls are used, to improve the dashboard. What is counted")
NOTE_ITEMS = ["How long each visit lasts, counted only while the page is open in front of you and in use. A look of 5 seconds or more counts as a visit, even without a click.",
              "Which sections you read, and which section links you click.",
              "Which filters and buttons you use (the control, never what you chose), how many projects are selected, and whether you started with a saved filter.",
              "Which Jira links you follow, by section only: never the issue or the address.",
              "Which details you open, how often you press Refresh and Reset Filters and whether Refresh worked, your screen size (small, medium or large), the page version and how old its data was, and the number of page errors.",
              "Never counted: names, e-mail addresses, issue keys, project, team or pod names, search text.",
              "Kept for 12 weeks: older weeks are removed from your record when you next open the page, and the owner also deletes records not seen for 12 weeks."]
CAPS = {"db": {"rules": [{"path": "", "write": "admin"}, {"path": "usage", "read": "admin", "write": "admin"}, {"path": "usage/{self}", "read": "interact", "write": "interact"}]}, "user": {}}
NOTES: list[str] = []                                                                  # observations the tests print (sizes)


# ------------------------------------------------------------------------------------------------ the page
_fx: dict = {}


def fixture() -> dict:
    if not _fx:
        data = MS.make(MS.il_today())
        data["build"] = {"sha": "abc1234", "dirty": False, "at": "2026-01-01T00:00+02:00"}
        _fx["data"] = data
    return _fx["data"]


def il_stamp_of(when: dt.datetime) -> str:
    """An ISO stamp with minute precision and the Israel offset, as the build writes `generated`."""
    w = when.astimezone(IL)
    off = w.utcoffset()
    mins = int(off.total_seconds() // 60)
    return w.strftime("%Y-%m-%dT%H:%M") + f"{'+' if mins >= 0 else '-'}{abs(mins) // 60:02d}:{abs(mins) % 60:02d}"


def variant(age_minutes: float | None = None, build_at: str | None = ..., now: dt.datetime | None = None) -> dict:
    """The fixture with every live source stamped `age_minutes` before `now`, and/or another build time (None = no build time)."""
    d = copy.deepcopy(fixture())
    if age_minutes is not None:
        stamp = il_stamp_of((now or dt.datetime.now(dt.timezone.utc)) - dt.timedelta(minutes=age_minutes))
        for k in ("generated", "capPulledAt", "bugsPulledAt", "linksPulledAt"):
            if k == "generated" or k in d:
                d[k] = stamp
        if isinstance(d.get("cfbx"), dict):                                   # the Open CFBs block is a live source with its own stamp
            d["cfbx"]["pulledAt"] = stamp
    if build_at is not ...:
        if build_at is None:
            d["build"].pop("at", None)
        else:
            d["build"]["at"] = build_at
    return d


def load(usage=..., shift_to: dt.datetime | None = None, hash_: str = "", tz: str | None = None, keep: bool = False, vp: tuple | None = None, claude: bool = True, wait: float = 0.6,
         data: dict | None = None, mode: str = "denied", ls: str = "recent", sr: str | None = None):
    """Open the page with the mocked connector. usage: None = no usage switches (db and user answer null); a dict = CFG.usage. shift_to: an aware datetime the page's clock starts at.
    mode: what Jira answers (see mock_claude.js); ls "recent" drops the automatic Refresh on open, "recentauto" lets it run. Returns the browser."""
    ch = ctx.chrome
    data = data or fixture()
    cfg = dict(mode=mode, ls=ls, shift=0, slow=0, fastTimers=False, page1=[], page2=[], capsnodes=[], opencfb=[], linknodes=[], farnodes=[], leftcfb=[], capnodes=[], axkey="X-1", keep=keep)
    if sr:
        cfg["sr"] = sr
    if shift_to is not None:
        cfg["shift"] = int(shift_to.timestamp() * 1000 - time.time() * 1000)
    if usage is not ... and usage is not None:
        u = dict(usage)
        u.setdefault("t", FAST)
        cfg["usage"] = u
    pre = ("<script data-harness>" + (HERE / "mock_claude.js").read_text().replace("/*__CFG__*/null", json.dumps(cfg).replace("</", "<\\/")).replace("/*__HOOK__*/null", "null") + "</script>") if claude else ""
    url = ctx.write(kit.wrap(kit.fragment_for(data), pre), "usage")
    ch.cmd("Emulation.setTimezoneOverride", timezoneId=tz or "Asia/Jerusalem")
    ch.viewport(*(vp or (1400, 900)), mobile=bool(vp and vp[0] < 500))
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


def hide(ch, event: str = "visibilitychange"):
    ch.js("window.__vis = 'hidden'; document.dispatchEvent(new Event('visibilitychange'))" if event == "visibilitychange" else "window.__vis = 'hidden'; window.dispatchEvent(new Event('pagehide'))")


def settle(ch, timeout: float = 8, restore: bool = True):
    """Force the visit's final write (the page goes hidden) and wait for it, then show the page again (restore=False: leave it hidden, so no later tick writes again)."""
    hide(ch)
    ch.wait_for("(() => { const s = window.__dpUsageTest.snap(); return !s.inflight && !s.dirty; })()", timeout)
    time.sleep(0.15)
    if restore:
        ch.js("window.__vis = 'visible'")


def session(ch, doc: dict | None = None) -> dict:
    s = snap(ch)
    d = (doc if doc is not None else docs(ch)).get(PATH) or {}
    return (((d.get("w") or {}).get(s.get("sessWeek")) or {}).get(s.get("sessDay")) or {}).get(s["S"]["sid"]) or {}


def all_sessions(doc: dict | None) -> list[dict]:
    """Every stored session of the person, as {week, day, sid, s}."""
    d = (doc or {}).get(PATH) or {}
    out = [{"week": wk, "day": day, "sid": sid, "s": s} for wk, days in (d.get("w") or {}).items() for day, ss in days.items() for sid, s in ss.items()]
    return sorted(out, key=lambda x: (x["day"], x["s"].get("t", 0), x["sid"]))


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


def sunday_key(day: str) -> str:
    """The week key of a day, worked out here: 'S' and the date of the Sunday that starts its Sunday-to-Saturday week."""
    d = dt.date.fromisoformat(day)
    return "S" + (d - dt.timedelta(days=(d.weekday() + 1) % 7)).isoformat()


def day_number(day: str) -> int:
    return (dt.date.fromisoformat(day) - dt.date(1970, 1, 1)).days


def il_day_of(iso: str) -> str:
    return dt.datetime.fromisoformat(iso).astimezone(IL).date().isoformat()


def hour_of(when: dt.datetime | None = None) -> int:
    return int((when.timestamp() if when else time.time()) // 3600)


def age_bucket(minutes: float) -> int:
    return 0 if minutes < 60 else 1 if minutes < 24 * 60 else 2 if minutes < 72 * 60 else 3


def fa_of(data: dict, now: dt.datetime | None = None) -> int:
    """The expected `fa`: the age of the oldest live source in the fixture."""
    live = [data.get(k) for k in ("generated", "capPulledAt", "bugsPulledAt", "linksPulledAt") if data.get(k)]
    oldest = min(dt.datetime.fromisoformat(x) for x in live)
    return age_bucket(((now or dt.datetime.now(dt.timezone.utc)) - oldest).total_seconds() / 60)


def week_end(key: str) -> dt.date:
    """The last day of a stored week key (schema 2 'S2026-11-08' or schema 1 '2026-W45')."""
    if key.startswith("S"):
        return dt.date.fromisoformat(key[1:]) + dt.timedelta(days=6)
    y, w = key.split("-W")
    return dt.date.fromisocalendar(int(y), int(w), 7)


def allowlist_problems(doc: dict, data: dict, uid: str = UID, v1_weeks: bool = False) -> list[str]:
    bad: list[str] = []
    if not isinstance(doc, dict):
        return ["no record"]
    if set(doc) - DOC_KEYS:
        bad.append(f"top-level keys outside the list: {sorted(set(doc) - DOC_KEYS)}")
    if doc.get("u") != uid or not re.match(r"^u_[A-Za-z0-9_-]+$", str(doc.get("u"))):
        bad.append("the id is not the opaque u_ token")
    if doc.get("v") != 2:
        bad.append("schema is not 2")
    if "pr" in doc and doc["pr"] != 1:
        bad.append(f"pr is {doc['pr']!r}")
    for k in ("first", "last"):
        if k in doc and not DAYRE.match(str(doc[k])):
            bad.append(f"{k} is not a day")
    for wk, days in (doc.get("w") or {}).items():
        if not (WEEKRE.match(wk) or (v1_weeks and WEEKRE_V1.match(wk))):
            bad.append(f"week key {wk!r}")
        for day, sess in days.items():
            if not DAYRE.match(day):
                bad.append(f"day key {day!r}")
            elif WEEKRE.match(wk) and sunday_key(day) != wk:
                bad.append(f"day {day} is under week {wk}, expected {sunday_key(day)}")
            for sid, s in sess.items():
                if not SIDRE.match(sid):
                    bad.append(f"session id {sid!r}")
                if set(s) - SESSION_KEYS:
                    bad.append(f"session keys outside the list: {sorted(set(s) - SESSION_KEYS)}")
                for m in ("sec", "nav", "f", "l", "o", "ro"):
                    for k, v in (s.get(m) or {}).items():
                        if k not in VOC[m]:
                            bad.append(f"{m} key outside the vocabulary: {k!r}")
                        if not (isinstance(v, int) and 0 < v <= 1000) and not (m == "sec" and isinstance(v, int) and 0 < v <= 86400):
                            bad.append(f"{m}.{k} value {v!r}")
                    if len(s.get(m) or {}) > 40:
                        bad.append(f"{m} has more than 40 keys")
                for k in ("t", "s", "vs", "r", "rs", "rt", "np", "er", "erb", "x"):
                    if k in s and not (isinstance(s[k], int) and not isinstance(s[k], bool) and 0 <= s[k] < 10 ** 9):
                        bad.append(f"{k} value {s[k]!r}")
                if "d" in s and s["d"] not in VOC["d"]:
                    bad.append(f"d value {s['d']!r}")
                if "b" in s and not re.match(r"^[0-9a-f]{4,12}$", str(s["b"])):
                    bad.append(f"b value {s['b']!r}")
                for k, ok in (("fa", range(0, 4)), ("lv", range(0, 3)), ("lf", range(0, 2)), ("g", [1]), ("rr", [1])):
                    if k in s and (isinstance(s[k], bool) or s[k] not in ok):
                        bad.append(f"{k} value {s[k]!r}")
                if "bt" in s and not (isinstance(s["bt"], int) and 10000 < s["bt"] < 100000):
                    bad.append(f"bt value {s['bt']!r}")
                if "vs" in s and "s" in s and s["vs"] < s["s"]:
                    bad.append(f"visible seconds {s['vs']} under active seconds {s['s']}")
                if "t" in s and "vs" in s and s["t"] > 10 ** 7:
                    bad.append(f"t {s['t']} is not an hour count")
    text = json.dumps(doc)
    if "@" in text:
        bad.append("an '@' is stored")
    keyish = re.sub(r"S\d{4}-\d{2}-\d{2}", "", text)                                   # a week key ('S2026-11-08') is a date, not an issue key
    if KEYRE.search(keyish):
        bad.append(f"an issue-key-shaped string is stored: {KEYRE.search(keyish).group(0)}")
    hit = [x for x in forbidden(data) if x in text]
    if hit:
        bad.append(f"a name from the data or the viewer is stored: {hit[:3]}")
    if len(text.encode()) > 100 * 1024:
        bad.append("the record is over 100 KiB")
    return bad


def errors(ch) -> list:
    return [e for e in ch.console_errors()]


# ------------------------------------------------------------------------------------------------ the expected record of a scenario, written here, compared key by key
M5 = ("m5", 0)                                                                         # an integer, a multiple of 5 (a tick is 5 s), at least 0
OPT = ("opt",)                                                                         # the key may be absent


def ge5(n: int) -> tuple:
    return ("m5", n)


def base_exp(data: dict | None = None, when: dt.datetime | None = None, width: str = "l", **over) -> dict:
    """What every schema 2 session of a page opened now has, whatever the reader did; `over` adds or replaces keys (None removes one)."""
    d = data or fixture()
    at = (d.get("build") or {}).get("at")
    e = {"t": ("hour", hour_of(when)), "s": M5, "vs": M5, "d": width, "b": "abc1234", "fa": fa_of(d, when), "lf": 0, "np": len(d["projects"])}
    if at:
        e["bt"] = day_number(il_day_of(at)) if re.match(r"^\d{4}-", at) else None
    e.update(over)
    return {k: v for k, v in e.items() if v is not None}


def match(s: dict, exp: dict, label: str) -> list[str]:
    """The stored session `s` equals `exp` key for key: no key that is not expected, none missing (except OPT), every value as spelled."""
    bad = []
    for k in sorted(set(s) - set(exp)):
        bad.append(f"{label}: unexpected key {k}={s[k]!r}")
    for k, v in exp.items():
        if k not in s:
            if v != OPT:
                bad.append(f"{label}: missing {k} (expected {v!r})")
            continue
        got = s[k]
        if v == OPT:
            continue
        if isinstance(v, tuple) and v[0] == "m5":
            if not (isinstance(got, int) and not isinstance(got, bool) and got % 5 == 0 and got >= v[1]):
                bad.append(f"{label}: {k}={got!r}, expected a multiple of 5 of at least {v[1]}")
        elif isinstance(v, tuple) and v[0] == "hour":
            if not (isinstance(got, int) and abs(got - v[1]) <= 1):
                bad.append(f"{label}: t={got!r} is not the hour {v[1]} (hours since the epoch, not minutes)")
        elif got != v:
            bad.append(f"{label}: {k}={got!r}, expected {v!r}")
    if s.get("vs") is not None and s.get("s") is not None and s["vs"] < s["s"]:
        bad.append(f"{label}: visible seconds {s['vs']} under active seconds {s['s']}")
    return bad


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


def expected_main(exp: dict) -> dict:
    """The whole expected session of the scripted reader at 1400 px, Jira answering 'access not allowed' to the Refresh press: the reader changed filters before pressing Reset (rr),
    the press was declined (ro, lv 1), the data is the fixture's snapshot."""
    over = {k: exp[k] for k in ("nav", "f", "l", "o", "r", "rs") if exp[k]}
    return base_exp(**over, rr=1 if exp["rs"] else None, ro={"declined": 1}, lv=1, sec=OPT)


# ------------------------------------------------------------------------------------------------ the batteries (each returns a list of problems; the tests and the seeded-defect checks use the same ones)
def b_main() -> list[str]:
    """Nothing before input; then the scripted reader; the stored session equals the expectation; the allowlist; one writer at a time; the shape of the calls."""
    bad: list[str] = []
    ch = load(usage={"latency": 150, "t": {**FAST, "flush": 100}})                  # a slow store and a short window: a second write would start while the first is in flight
    if log(ch):
        bad.append(f"something was written before any input: {log(ch)[:2]}")
    exp, miss = reader(ch)
    bad += [f"the reader could not do: {x}" for x in miss]
    settle(ch, restore=False)
    s = session(ch)
    bad += match(s, expected_main(exp), "the scripted reader")
    d = docs(ch)
    bad += allowlist_problems(d.get(PATH), fixture())
    if set(d) != {PATH}:
        bad.append(f"documents other than {PATH}: {sorted(d)}")
    if s.get("s", 0) % 5 or any(v > s.get("s", 0) for v in (s.get("sec") or {}).values()) or s.get("vs", 0) % 5:
        bad.append(f"seconds {s.get('s')} / visible {s.get('vs')} / sec {s.get('sec')}")
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
            if set(e["data"]) - {"last", "w", "first", "v"} or e["data"].get("v") != 2 or len(w) != 1 or len(days) != 1 or len(days[0]) != 1:
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
    snapvs = lambda: snap(ch)["S"]["vs"]

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
    if snapvs() < snapv() or snapvs() % 5:
        bad.append(f"visible seconds {snapvs()} under the active seconds {snapv()}")
    ch.js("window.__vis = 'hidden'; document.dispatchEvent(new Event('visibilitychange'))"); time.sleep(0.4)
    s2, v2 = snapv(), snapvs()
    for _ in range(6):
        poke(); time.sleep(0.12)
    if snapv() != s2 or snapvs() != v2:
        bad.append(f"a hidden page counted: active {s2} -> {snapv()}, visible {v2} -> {snapvs()}")
    ch.js("window.__vis = 'visible'; window.__focus = false")
    for _ in range(6):
        poke(); time.sleep(0.12)
    if snapv() != s2:
        bad.append(f"an unfocused page counted active seconds: {s2} -> {snapv()}")
    if snapvs() <= v2:
        bad.append(f"an unfocused but visible page did not count visible seconds: {v2} -> {snapvs()}")
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
        bad += match(s, base_exp(vs=ge5(5)), "a visit that only read for 30 s")
        if any(k in s for k in ("nav", "f", "l", "o", "sec", "g")) or s.get("s", 0):
            bad.append(f"a visit with no input recorded activity: {s}")
    ch = load(usage={"t": {**FAST, "first": 60000}})                                     # a glance is not written while the page is in front, however long: only when it is hidden or left
    time.sleep(1.5)
    if log(ch):
        bad.append(f"a glance was written before the page was hidden: {log(ch)[:2]}")
    bad += errors(ch)
    return bad


def has_note(ch) -> bool:
    return bool(ch.js("!!document.getElementById('usage-note')"))


def record_first(ch, timeout: float = 4) -> bool:
    """One strip click, then wait until the first write has succeeded and the page had time to react."""
    click(ch, '#seclist a[data-jump="h-eff"]')
    ok = ch.wait_for("window.__dbLog.some(e => e.op === 'set' && e.result === 'ok')", timeout)
    time.sleep(0.2)
    return bool(ok)


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
        if has_note(ch):
            bad.append(f"{name}: the note is shown after an interaction")
        if not ch.js("document.getElementById('f-release') && document.querySelectorAll('section').length > 5"):
            bad.append(f"{name}: the page does not work")
        bad += [f"{name}: {e}" for e in errors(ch)]
    ch = load(usage={})
    if has_note(ch):
        bad.append("the note is shown before anything has been recorded")
    if not record_first(ch):
        return bad + ["the first write never happened"]
    note = ch.js("(() => { const n = document.getElementById('usage-note'); if (!n) return null; const b = n.querySelector('button'), l = document.getElementById('usage-what'); return {text: n.querySelector('p').textContent, hidden: n.hidden, inFooter: !!n.closest('footer'), exp: b.getAttribute('aria-expanded'), ctl: b.getAttribute('aria-controls'), listHidden: l.hidden, items: [...l.querySelectorAll('li')].map(x => x.textContent), lastInFooter: document.getElementById('footer').lastElementChild === n}; })()")
    if not note:
        return bad + ["logging is active and no note is shown"]
    if note["text"] != NOTE_TEXT:
        bad.append(f"the note reads {note['text']!r}")
    if "anonymous" in (note["text"] + " ".join(note["items"])).lower() or "pseudonymous" not in note["text"]:
        bad.append("the note says 'anonymous' or does not say 'pseudonymous'")
    if note["items"] != NOTE_ITEMS:
        bad.append(f"the list reads {note['items']}")
    if note["hidden"] or not note["inFooter"] or not note["lastInFooter"]:
        bad.append("the note is not shown at the very bottom of the page")
    if note["exp"] != "false" or note["ctl"] != "usage-what" or not note["listHidden"]:
        bad.append("the toggle starts open or is not wired")
    click(ch, "#usage-note button")
    after = ch.js("({exp: document.querySelector('#usage-note button').getAttribute('aria-expanded'), hidden: document.getElementById('usage-what').hidden, n: document.querySelectorAll('#usage-what li').length, text: document.getElementById('usage-what').textContent})")
    if after["exp"] != "true" or after["hidden"] or after["n"] != 7 or "12 weeks" not in after["text"] or "Never counted" not in after["text"]:
        bad.append(f"the list does not open or lacks the retention and exclusions: {after}")
    bad += errors(ch)
    return bad


def b_note_after_write() -> list[str]:
    """The note appears only after the first SUCCESSFUL write of the visit: never for a viewer whose write is refused (nothing was recorded for them)."""
    bad: list[str] = []
    ch = load(usage={"fault": "invalid", "latency": 60})                                  # a view-only viewer: the write is refused with invalid_argument
    seen = [has_note(ch)]
    click(ch, '#seclist a[data-jump="h-eff"]')
    for _ in range(8):                                                                   # while the first write is under way, when it is refused, and afterwards
        seen.append(has_note(ch)); time.sleep(0.15)
    ch.wait_for("window.__dbLog.some(e => e.result === 'invalid_argument')", 4)
    click(ch, '#seclist a[data-jump="h-bugs"]'); time.sleep(0.8)
    seen.append(has_note(ch))
    if any(seen):
        bad.append("a view-only viewer saw the note")
    if any(e["result"] == "ok" and e["op"] in ("set", "update") for e in log(ch)):
        bad.append("something was recorded for a refused viewer")
    ch = load(usage={"fault": "invalid", "latency": 30, "t": {**FAST, "first": 60000}})   # a refused viewer who only glanced: one refusal, then silence
    time.sleep(0.5)
    hide(ch); time.sleep(0.6)
    ch.js("window.__vis = 'visible'"); time.sleep(0.5); hide(ch); time.sleep(0.6)
    if [e["op"] for e in log(ch)] != ["get", "set"] or has_note(ch):
        bad.append(f"a refused glance: expected one get and one set and no note, got {[(e['op'], e['result']) for e in log(ch)]}")
    ch = load(usage={"fault": "exhausted", "t": {**FAST, "flush": 300}})                   # every write fails: three attempts, never a note
    end = time.time() + 3.5
    seen = []
    while time.time() < end:
        click(ch, '#seclist a[data-jump="h-eff"]'); click(ch, '#seclist a[data-jump="h-bugs"]'); seen.append(has_note(ch)); time.sleep(0.12)
    if any(seen):
        bad.append("the note was shown although no write ever succeeded")
    ch = load(usage={"fault": "unavailable_once", "latency": 80})                          # the first write is retried once: the note comes with the success, not before
    if has_note(ch):
        bad.append("the note is shown at load")
    click(ch, '#seclist a[data-jump="h-eff"]')
    early = []
    end = time.time() + 3
    while time.time() < end and not ch.js("window.__dbLog.some(e => e.op === 'set' && e.result === 'ok')"):
        early.append(has_note(ch)); time.sleep(0.02)
    if any(early):
        bad.append("the note appeared before the first successful write")
    time.sleep(0.2)
    if not has_note(ch):
        bad.append("the note did not appear after the first successful write")
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
        if not ch.js("document.querySelectorAll('#seclist a').length === 10"):
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


def b_week() -> list[str]:
    """The Israel day and the Sunday-to-Saturday week key across a day boundary, a Sunday, a year boundary and a browser in another timezone; the page's week function against this file's for 900 days."""
    bad: list[str] = []
    cases = [("2026-12-31T21:59:50Z", "America/Los_Angeles", "2026-12-31"),            # 23:59:50 in Israel (a Thursday); the browser is in Los Angeles
             ("2026-12-31T22:30:00Z", "America/Los_Angeles", "2027-01-01"),            # already the next day in Israel (a Friday), still the 31st in the browser and in UTC: the same work week as the 31st
             ("2027-01-02T10:00:00Z", None, "2027-01-02"),                              # a Saturday: the last day of that week
             ("2027-01-03T05:00:00Z", "Pacific/Kiritimati", "2027-01-03"),            # a Sunday: the first day of a new week, a new year; the browser is a day ahead
             ("2026-11-01T10:00:00Z", None, "2026-11-01"),                              # a Sunday
             ("2026-10-31T10:00:00Z", None, "2026-10-31")]                              # the Saturday before
    for iso, tz, day in cases:
        when = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        ch = load(usage={}, shift_to=when, tz=tz)
        click(ch, '#seclist a[data-jump="h-eff"]'); time.sleep(0.5)
        settle(ch)
        d = docs(ch).get(PATH) or {}
        got = {wk: sorted(days) for wk, days in (d.get("w") or {}).items()}
        if got != {sunday_key(day): [day]}:
            bad.append(f"at {iso} ({tz}) the session is keyed {got}, expected {sunday_key(day)} / {day}")
        if d.get("first") != day:
            bad.append(f"at {iso} first is {d.get('first')}, expected {day}")
        s = session(ch, docs(ch))
        if s and not (isinstance(s.get("t"), int) and abs(s["t"] - hour_of(when)) <= 1):
            bad.append(f"at {iso} t is {s.get('t')}, expected the hour {hour_of(when)}")
    ch = load(usage={})
    days = [(dt.date(2025, 12, 20) + dt.timedelta(days=i)).isoformat() for i in range(900)]
    got = ch.js(f"{json.dumps(days)}.map(d => window.__dpUsageTest.weekOf(d))")
    want = [sunday_key(d) for d in days]
    if got != want:
        i = next(i for i, (a, b) in enumerate(zip(got, want)) if a != b)
        bad.append(f"week key of {days[i]}: page {got[i]}, expected {want[i]}")
    got = ch.js("['2026-W45', '2026-W53', '2027-W01', '2020-W53', 'S2026-11-08', 'junk'].map(k => window.__dpUsageTest.wkStart(k))")
    want = ["2026-11-02", "2026-12-28", "2027-01-04", "2020-12-28", "2026-11-08", None]
    if got != want:
        bad.append(f"the start of a stored week (schema 1 ISO keys are Mondays): page {got}, expected {want}")
    return bad


def across_midnight(start_utc: dt.datetime, active: bool) -> list[str]:
    """A visit that spans Israel midnight. active=False: a click before and a click after (two visits, one per day); active=True: a reader who keeps moving the pointer across midnight (the tick starts the new visit)."""
    bad: list[str] = []
    ch = load(usage={"t": {**FAST, "flush": 200, "first": 600}}, shift_to=start_utc)
    day1 = il_day_of(start_utc.isoformat())
    day2 = (dt.date.fromisoformat(day1) + dt.timedelta(days=1)).isoformat()
    if active:
        ch.js("window.__poker = setInterval(() => document.dispatchEvent(new Event('pointermove')), 80)")
    click(ch, '#seclist a[data-jump="h-eff"]'); time.sleep(0.3)
    midnight = int(dt.datetime.fromisoformat(day2 + "T00:00:00").replace(tzinfo=IL).timestamp() * 1000)
    ch.wait_for(f"Date.now() > {midnight + 600}", 8)
    if not active:
        click(ch, '#seclist a[data-jump="h-bugs"]')
    time.sleep(1.6 if active else 0.8)
    if active:
        ch.js("clearInterval(window.__poker)")
    settle(ch)
    d = docs(ch)
    ss = all_sessions(d)
    want_weeks = {sunday_key(day1), sunday_key(day2)}
    got_weeks = {x["week"] for x in ss}
    if got_weeks != want_weeks or any(x["week"] != sunday_key(x["day"]) for x in ss):
        bad.append(f"week keys {sorted(got_weeks)} for the days {[x['day'] for x in ss]}, expected {sorted(want_weeks)}")
    a = [x for x in ss if x["day"] == day1]
    b = [x for x in ss if x["day"] == day2]
    if len(a) != 1 or len(b) != 1:
        return bad + [f"expected one visit on {day1} and one on {day2}, got {[(x['day'], x['s'].get('nav')) for x in ss]}"]
    bad += match(a[0]["s"], base_exp(when=start_utc, nav={"eff": 1}, sec=OPT, s=ge5(0)), f"the visit on {day1}")
    if active:
        if not b[0]["s"].get("s"):
            bad.append("the visit after midnight has no active seconds although the reader kept going")
        bad += match(b[0]["s"], base_exp(when=start_utc + dt.timedelta(seconds=3), sec=OPT, nav=None), f"the visit on {day2}")
    else:
        bad += match(b[0]["s"], base_exp(when=start_utc + dt.timedelta(seconds=3), nav={"bugs": 1}, sec=OPT), f"the visit on {day2}")
    if a[0]["sid"] == b[0]["sid"]:
        bad.append("one visit id for both days")
    if (d.get(PATH) or {}).get("last") != day2:
        bad.append(f"last is {(d.get(PATH) or {}).get('last')}, expected {day2}")
    bad += errors(ch)
    return bad


def b_midnight() -> list[str]:
    """A visit is split at Israel midnight: across a Thursday/Friday and a year boundary (one Sunday-to-Saturday week), across a Saturday/Sunday (two weeks), with a click and with a reader who keeps going."""
    bad: list[str] = []
    bad += [f"year end: {x}" for x in across_midnight(dt.datetime(2026, 12, 31, 21, 59, 58, tzinfo=dt.timezone.utc), active=False)]
    bad += [f"Saturday to Sunday: {x}" for x in across_midnight(dt.datetime(2026, 10, 24, 20, 59, 58, tzinfo=dt.timezone.utc), active=False)]
    bad += [f"an active reader: {x}" for x in across_midnight(dt.datetime(2026, 12, 31, 21, 59, 58, tzinfo=dt.timezone.utc), active=True)]
    return bad


def b_cap() -> list[str]:
    ch = load(usage={})
    out = ch.js("(() => { const m = {}; let x = 0; for (let i = 0; i < 60; i++) { if (window.__dpUsageTest.room(m, 'k' + i)) m['k' + i] = 1; else x++; } return {keys: Object.keys(m).length, x}; })()")
    return [] if out == {"keys": 40, "x": 20} else [f"a counter map took {out['keys']} keys and dropped {out['x']} (expected 40 and 20)"]


def b_glance() -> list[str]:
    """Visible 5 s or more with no input and under 30 s: recorded when the page is hidden or left (g = 1), not before; under 5 s nothing; with input or after 30 s of reading it is not a glance; a second look is a second visit."""
    bad: list[str] = []
    for how in ("visibilitychange", "pagehide"):
        ch = load(usage={"t": {**FAST, "first": 60000}})                              # about 6 ticks (30 s of the page's timers) visible
        if log(ch):
            bad.append(f"{how}: written before the page was hidden: {log(ch)[:2]}")
        hide(ch, how)
        if not ch.wait_for("window.__dbLog.some(e => e.op === 'set' && e.result === 'ok')", 3):
            bad.append(f"{how}: the glance was not written")
            continue
        time.sleep(0.3)
        ss = all_sessions(docs(ch))
        if len(ss) != 1:
            bad.append(f"{how}: expected one visit, got {len(ss)}")
        else:
            bad += match(ss[0]["s"], base_exp(g=1, s=0, vs=ge5(5)), f"{how}: a glance")
        if [e["op"] for e in log(ch)] != ["get", "set"]:
            bad.append(f"{how}: the calls are {[e['op'] for e in log(ch)]}")
        if not has_note(ch):
            bad.append(f"{how}: no note after the glance was written")
        bad += errors(ch)
    # under 5 s: the page is hidden before the first 5 s tick: nothing is written
    ch = load(usage={"t": {**FAST, "tick": 3000, "first": 60000}}, wait=0.1)
    hide(ch); time.sleep(0.7)
    if log(ch) or has_note(ch):
        bad.append(f"a look under 5 s was written: {log(ch)[:2]}")
    # with input: not a glance, whatever the time
    ch = load(usage={"t": {**FAST, "first": 60000}})
    click(ch, '#seclist a[data-jump="h-eff"]'); time.sleep(0.3)
    settle(ch, restore=False)
    ss = all_sessions(docs(ch))
    if len(ss) != 1 or "g" in ss[0]["s"]:
        bad.append(f"a visit with a click is marked as a glance or is not recorded: {[x['s'] for x in ss]}")
    # 30 s of reading with no input: written by the 30 s rule, never a glance
    ch = load(usage={"t": {**FAST, "first": 600}}, wait=0.1)
    if not ch.wait_for("window.__dbLog.some(e => e.op === 'set' && e.result === 'ok')", 4):
        bad.append("30 s of reading was not written")
    settle(ch, restore=False)
    ss = all_sessions(docs(ch))
    if len(ss) != 1 or "g" in ss[0]["s"] or ss[0]["s"].get("vs", 0) < 5:
        bad.append(f"30 s of reading: {[x['s'] for x in ss]}")
    # a second look is a second visit with its own id
    ch = load(usage={"t": {**FAST, "first": 60000}})
    hide(ch)
    ch.wait_for("window.__dbLog.some(e => e.op === 'set' && e.result === 'ok')", 3)
    ch.js("window.__vis = 'visible'"); time.sleep(0.7)
    hide(ch)
    ch.wait_for("window.__dbLog.filter(e => e.op === 'update' && e.result === 'ok').length >= 1", 3); time.sleep(0.3)
    ss = all_sessions(docs(ch))
    if len(ss) != 2 or ss[0]["sid"] == ss[1]["sid"]:
        bad.append(f"two looks: expected two visits with their own ids, got {[(x['sid'], x['s'].get('vs'), x['s'].get('g')) for x in ss]}")
    else:
        for x in ss:
            bad += match(x["s"], base_exp(g=1, s=0, vs=ge5(5)), "a second look")
    return bad


def b_reading() -> list[str]:
    """Reading seconds go to every section of the current side-by-side row and to `top` above the first section anchor; worked out here from where the page was scrolled to, not from the page's code."""
    bad: list[str] = []

    def read_at(vp, js_move: str, row_expected: list[str], label: str):
        ch = load(usage={"t": {**FAST, "first": 60000}}, vp=vp)
        ch.js("window.__vis = 'hidden'")                                               # scroll with the page hidden: no tick counts while the scroll spy settles
        ch.js(js_move)
        time.sleep(0.6)
        cur = ch.js("(() => ({cur: [...document.querySelectorAll('#seclist a[aria-current]')].map(a => a.dataset.jump.replace(/^h-/, '')), co: [...document.querySelectorAll('#seclist a.co')].map(a => a.dataset.jump.replace(/^h-/, '')), y: window.scrollY}))()")
        ch.js("window.__vis = 'visible'")
        for _ in range(8):                                                               # a reader: a wheel turn (a real input, no scroll) and the pointer moving, for about 1 s
            ch.js("document.dispatchEvent(new WheelEvent('wheel', {deltaY: 0}))"); time.sleep(0.12)
        settle(ch, restore=False)
        s = session(ch)
        if not s.get("s"):
            return bad.append(f"{label}: no active seconds ({s})")
        return s, cur
    # (a) at the top of the page nothing has passed the first anchor: the headline tiles
    r = read_at(None, "window.scrollTo(0, 0)", ["top"], "top")
    if isinstance(r, tuple):
        s, cur = r
        if (s.get("sec") or {}) != {"top": s["s"]}:
            bad.append(f"at the top of the page the reading time is {s.get('sec')}, expected only top = {s['s']} (the strip says {cur})")
    # (b) Efficiency and AI Adoption stand side by side at 1400 px: both are being read, each for every active tick
    r = read_at(None, "document.getElementById('h-eff').scrollIntoView({block: 'start'}); window.scrollBy(0, -150)", ["eff", "ai"], "side by side")
    if isinstance(r, tuple):
        s, cur = r
        row = set(cur["cur"]) | set(cur["co"])
        if row != {"eff", "ai"}:
            bad.append(f"the strip does not show Efficiency and AI Adoption side by side at 1400 px: {cur}")
        if (s.get("sec") or {}) != {k: s["s"] for k in row}:
            bad.append(f"side by side: the reading time is {s.get('sec')}, expected {sorted(row)} for {s['s']} s each (the strip says {cur})")
    # (c) on a phone the same sections are stacked: only Efficiency
    r = read_at((390, 800), "document.getElementById('h-eff').scrollIntoView({block: 'start'}); window.scrollBy(0, -150)", ["eff"], "stacked")
    if isinstance(r, tuple):
        s, cur = r
        row = set(cur["cur"]) | set(cur["co"])
        if row != {"eff"}:
            bad.append(f"at 390 px the strip shows {cur}, expected Efficiency alone")
        if (s.get("sec") or {}) != {"eff": s["s"]} or s.get("d") != "s":
            bad.append(f"stacked: the reading time is {s.get('sec')} and the width class {s.get('d')}, expected eff = {s['s']} and s")
    return bad


def b_split() -> list[str]:
    """A new visit after 30 minutes without input (shortened to 1.5 s here); no new visit when the gap is shorter; the finished visit is written first."""
    bad: list[str] = []
    ch = load(usage={"t": {**FAST, "split": 1500}})
    click(ch, '#seclist a[data-jump="h-eff"]'); time.sleep(1.8)
    click(ch, '#seclist a[data-jump="h-bugs"]'); time.sleep(0.6)
    settle(ch, restore=False)
    ss = all_sessions(docs(ch))
    navs = sorted(json.dumps(x["s"].get("nav"), sort_keys=True) for x in ss)
    if len(ss) != 2 or navs != ['{"bugs": 1}', '{"eff": 1}'] or ss[0]["sid"] == ss[1]["sid"]:
        bad.append(f"after an idle gap longer than the split: expected two visits ({{eff}} and {{bugs}}), got {[(x['sid'], x['s'].get('nav')) for x in ss]}")
    for x in ss:
        bad += match(x["s"], base_exp(nav=x["s"].get("nav"), sec=OPT), "a visit after the split")
    if [e["op"] for e in log(ch)][:2] != ["get", "set"] or any(e["op"] == "set" for e in log(ch)[2:]):
        bad.append(f"the calls: {[e['op'] for e in log(ch)]}")
    ch = load(usage={"t": {**FAST, "split": 1500}})
    click(ch, '#seclist a[data-jump="h-eff"]'); time.sleep(0.7)
    click(ch, '#seclist a[data-jump="h-bugs"]'); time.sleep(0.6)
    settle(ch, restore=False)
    ss = all_sessions(docs(ch))
    if len(ss) != 1 or ss[0]["s"].get("nav") != {"eff": 1, "bugs": 1}:
        bad.append(f"a gap shorter than the split: expected one visit, got {[(x['sid'], x['s'].get('nav')) for x in ss]}")
    bad += errors(ch)
    return bad


def b_links() -> list[str]:
    """A middle click on a Jira link is a link followed (the right button is not); a left click too."""
    bad: list[str] = []
    ch = load(usage={})
    ch.js(NOOPEN)
    sel = 'section[aria-labelledby="h-attn"] a[href^="https://jira.example.test/browse/"]'
    send = lambda btn: ch.js(f"(() => {{ const a = document.querySelector({json.dumps(sel)}); if (!a) return false; a.dispatchEvent(new MouseEvent('auxclick', {{button: {btn}, bubbles: true, cancelable: true}})); return true; }})()")
    if not send(1):
        return ["no Jira link in Needs Attention to click"]
    time.sleep(0.2); send(2); time.sleep(0.2)
    ch.js("(() => { const a = document.querySelector('section[aria-labelledby=\"h-bugs\"] a[href^=\"https://jira.example.test/issues/\"]'); a && a.dispatchEvent(new MouseEvent('auxclick', {button: 1, bubbles: true, cancelable: true})); })()")
    time.sleep(0.3)
    ch.wait_for("window.__dbLog.some(e => e.op === 'set' && e.result === 'ok')", 3)
    click(ch, sel); time.sleep(0.3)
    settle(ch, restore=False)
    bad += match(session(ch), base_exp(l={"attn": 2, "bugs": 1}, sec=OPT), "a middle click on two Jira links, a right click and a left click")
    return bad


def b_errors() -> list[str]:
    """Script errors and unhandled rejections are `er`; a ResizeObserver notice is `erb` and never an error; no message is kept."""
    bad: list[str] = []
    ch = load(usage={})
    click(ch, '#seclist a[data-jump="h-eff"]'); time.sleep(0.3)
    ch.js("""(() => {
        for (const m of ['ResizeObserver loop completed with undelivered notifications.', 'ResizeObserver loop completed with undelivered notifications.', 'ResizeObserver loop limit exceeded']) window.dispatchEvent(new ErrorEvent('error', {message: m}));
        window.dispatchEvent(new ErrorEvent('error', {message: 'Uncaught TypeError: x.y is not a function'}));
        window.dispatchEvent(new ErrorEvent('error', {message: 'Script error.'}));
        const p = Promise.reject(new Error('later')); p.catch(() => {});
        window.dispatchEvent(new PromiseRejectionEvent('unhandledrejection', {promise: p, reason: 'x'}));
    })()""")
    time.sleep(0.3)
    settle(ch, restore=False)
    s = session(ch)
    bad += match(s, base_exp(nav={"eff": 1}, sec=OPT, er=3, erb=3), "3 benign notices, 2 script errors and 1 rejection")
    text = json.dumps(docs(ch).get(PATH))
    if "TypeError" in text or "ResizeObserver" in text or "later" in text:
        bad.append("an error message is stored")
    return bad


def wait_refresh_idle(ch, timeout: float = 12) -> bool:
    return bool(ch.wait_for("(() => { const b = document.getElementById('refresh'); return !!b && !b.disabled && !/Refreshing/.test(b.textContent); })()", timeout))


def b_refresh() -> list[str]:
    """Refresh declined, failed, ok and no connector: `lv`, `ro`, `r`, `rt`, each for the automatic run and for a press."""
    bad: list[str] = []
    # (label, usage extras, Jira's answer, what the reader does after the automatic run, expected extras)
    cases = [("auto, access not allowed", {}, "denied", None, dict(lv=1)),
             ("auto, a step fails", {}, "capsfail", None, dict(lv=2)),
             ("auto, every read fails", {}, "boom", None, dict(lv=2)),
             ("auto, success", {}, "ok", None, dict(lv=0)),
             ("auto, no connector", {"mcp": None}, "ok", None, dict(lv=1)),
             ("press, access not allowed", {}, "denied", "press", dict(lv=1, r=1, ro={"declined": 1})),
             ("press, a step fails", {}, "capsfail", "press", dict(lv=2, r=1, ro={"fail": 1})),
             ("press, success", {}, "ok", "press", dict(lv=0, r=1, ro={"ok": 1})),
             ("press, no connector", {"mcp": None}, "ok", "press", dict(lv=1, r=1, ro={"declined": 1})),
             ("retry link", {}, "denied", "retry", dict(lv=1, rt=1, ro={"declined": 1}))]
    for label, extra, mode, act, exp in cases:
        ch = load(usage=dict(extra), mode=mode, ls="recentauto", sr="used")
        time.sleep(0.9)                                                                  # the automatic run starts 600 ms after load
        if not wait_refresh_idle(ch):
            bad.append(f"{label}: the automatic Refresh did not finish")
            continue
        time.sleep(0.2)
        if act == "press":
            if not click(ch, "#refresh"):
                bad.append(f"{label}: no Refresh button"); continue
            time.sleep(0.5); wait_refresh_idle(ch)
        elif act == "retry":
            if not click(ch, "#refresh-retry"):
                bad.append(f"{label}: no Retry link after the automatic run"); continue
            time.sleep(0.5); wait_refresh_idle(ch)
        click(ch, '#seclist a[data-jump="h-eff"]'); time.sleep(0.3)
        settle(ch, restore=False)
        bad += match(session(ch), base_exp(nav={"eff": 1}, sec=OPT, **exp), label)
        bad += [f"{label}: {e}" for e in errors(ch)]
    return bad


def b_age() -> list[str]:
    """`fa`: the age of the data on screen at the start of the visit, in the buckets under 1 h, under 24 h, under 72 h, older; `bt`: the Israel day number of the build time."""
    bad: list[str] = []
    for minutes, want in ((55, 0), (65, 1), (23 * 60, 1), (25 * 60, 2), (71 * 60, 2), (73 * 60, 3)):
        d = variant(age_minutes=minutes)
        ch = load(usage={}, data=d)
        click(ch, '#seclist a[data-jump="h-eff"]'); time.sleep(0.3)
        settle(ch, restore=False)
        s = session(ch)
        if s.get("fa") != want:
            bad.append(f"data {minutes} minutes old: fa is {s.get('fa')}, expected {want}")
        bad += match(s, base_exp(data=d, nav={"eff": 1}, sec=OPT), f"data {minutes} min old")
    for at, label in (("2026-12-31T23:30+02:00", "a build late on the 31st in Israel"), ("2026-12-31T22:30:00+00:00", "the same instant written in UTC: already 1 January in Israel"), ("2026-06-30T21:30:00Z", "a summer build: 1 July in Israel"), ("yesterday", "an unreadable build time"), (None, "no build time")):
        d = variant(build_at=at)
        ch = load(usage={}, data=d)
        click(ch, '#seclist a[data-jump="h-eff"]'); time.sleep(0.3)
        settle(ch, restore=False)
        s = session(ch)
        want = None if at in (None, "yesterday") else day_number(il_day_of(at.replace("Z", "+00:00")))
        if s.get("bt") != want:
            bad.append(f"{label}: bt is {s.get('bt')}, expected {want}")
    return bad


def b_flags() -> list[str]:
    """`lf`: the visit started with a filter other than the defaults (not the release); `rr`: Reset Filters pressed after at least one control change in the visit, not a Reset alone."""
    bad: list[str] = []
    other_release = next(r for r in fixture()["releases"] if r != fixture()["current"])
    ch = load(usage={}, hash_="ax=yes")
    ch.js(NOOPEN)
    if not click(ch, "#f-reset:not([disabled])"):
        return ["Reset Filters cannot be pressed with a filter set"]
    time.sleep(0.3)
    settle(ch, restore=False)
    bad += match(session(ch), base_exp(lf=1, rs=1, sec=OPT), "a visit that started with a saved filter and pressed Reset without changing anything")
    ch = load(usage={}, hash_="r=" + other_release)
    click(ch, '#seclist a[data-jump="h-eff"]'); time.sleep(0.3)
    settle(ch, restore=False)
    bad += match(session(ch), base_exp(lf=0, nav={"eff": 1}, sec=OPT), "a visit that started on another release (the release is not looked at)")
    ch = load(usage={})
    click(ch, '#f-ax input[value="yes"]'); time.sleep(0.3); click(ch, "#f-reset:not([disabled])"); time.sleep(0.3)
    settle(ch, restore=False)
    bad += match(session(ch), base_exp(lf=0, f={"ax": 1}, rs=1, rr=1, sec=OPT), "a change and then Reset in one visit")
    return bad


def v2_full(i: int, w: int) -> dict:
    """A session with every counter at its largest realistic spread: every key of every map."""
    return {"t": 490_000 + i + 24 * w, "s": 300, "vs": 360, "sec": {k: 12 for k in VOC["sec"]}, "nav": {k: 3 for k in VOC["nav"]}, "f": {k: 2 for k in VOC["f"]}, "l": {k: 1 for k in VOC["l"]}, "o": {k: 1 for k in VOC["o"]},
            "ro": {k: 1 for k in VOC["ro"]}, "r": 4, "rs": 3, "rt": 1, "rr": 1, "np": 7, "d": "l", "b": "abc1234", "bt": 20454, "fa": 1, "lf": 0, "lv": 0, "er": 1, "erb": 2}


def v2_real(i: int, w: int) -> dict:
    """A realistic visit: a few sections read, a couple of controls, a link, a disclosure."""
    return {"t": 490_000 + i + 24 * w, "s": 240, "vs": 300, "sec": {"top": 30, "attn": 60, "burnup": 120, "bugs": 60}, "nav": {"eff": 1, "bugs": 1}, "f": {"release": 2, "teams": 1}, "l": {"attn": 1}, "o": {"how": 1}, "np": 7, "d": "l",
            "b": "abc1234", "bt": 20454, "fa": 1, "lf": 0, "lv": 0}


def b_retention() -> list[str]:
    """12 weeks of Sunday-keyed work weeks (schema 1 ISO keys still read), at most 10 sessions a day, a record below the size budget, the only `set` on an existing record, `pr` when the size cap dropped weeks."""
    bad: list[str] = []
    now = dt.datetime(2026, 11, 10, 10, 0, tzinfo=dt.timezone.utc)                      # a Tuesday: the work week of Sunday 8 November
    sun = dt.date(2026, 11, 8)
    weeks = [sun - dt.timedelta(days=7 * i) for i in range(0, 16)]
    wk = lambda d0: "S" + d0.isoformat()
    cut = dt.date(2026, 8, 23)                                                           # the Sunday 11 weeks before the current one
    twelve = [wk(sun - dt.timedelta(days=7 * i)) for i in range(11, -1, -1)]
    # (a) the worst case: 16 weeks, every day, 10 full sessions a day, one day with 70: far over 100 KiB. Weeks older than 12 go, a day is cut to 10, and the size limit drops the oldest weeks first; `pr` says so.
    seed = {wk(d0): {(d0 + dt.timedelta(days=j)).isoformat(): {f"s{i:07d}": v2_full(i, d0.toordinal() % 100) for i in range(70 if (d0, j) == (sun, 0) else 10)} for j in range(7)} for d0 in weeks}
    body = {"u": UID, "v": 2, "first": "2026-04-01", "last": "2026-11-09", "w": seed}
    ch = load(usage={"seed": {PATH: body}}, shift_to=now)
    if len(json.dumps(body)) <= 100 * 1024:
        bad.append("the seeded worst-case record is not large")
    click(ch, '#seclist a[data-jump="h-eff"]')
    ch.wait_for("window.__dbLog.some(e => e.op === 'set' && e.result === 'ok')", 4)
    time.sleep(0.3)
    d = docs(ch).get(PATH) or {}
    kept = sorted(d.get("w") or {})
    if not (kept and kept[0] >= twelve[0] and kept[-1] == twelve[-1] and 1 <= len(kept) <= 12):
        bad.append(f"worst case, weeks kept: {kept}")
    if d.get("pr") != 1:
        bad.append(f"worst case: the size cap dropped weeks and pr is {d.get('pr')!r}, expected 1")
    if any(len(v) > 10 for days in (d.get("w") or {}).values() for v in days.values()) or len(((d.get("w") or {}).get(wk(sun)) or {}).get("2026-11-10") or {}) != 10:
        bad.append("worst case: a day is not cut to the 10 newest sessions, the visit's own among them")
    if len(json.dumps(d).encode()) >= 100 * 1024:
        bad.append(f"worst case: the record is {len(json.dumps(d)) // 1024} KiB, not below 100 KiB")
    NOTES.append(f"absolute worst case (every day, 10 full sessions a day): {len(kept)} of 12 weeks kept, {len(json.dumps(d).encode()) // 1024} KiB, pr = {d.get('pr')}")
    own = snap(ch)["S"]["sid"]
    if own not in (((d.get("w") or {}).get(wk(sun)) or {}).get("2026-11-10") or {}):
        bad.append("worst case: the visit's own session is not kept")
    if d.get("first") != "2026-04-01":
        bad.append("worst case: first is not kept")
    click(ch, '#seclist a[data-jump="h-bugs"]'); time.sleep(0.9)
    if len([e for e in log(ch) if e["op"] == "set"]) != 1 or [e["op"] for e in log(ch)].count("get") != 1:
        bad.append(f"worst case: one get and one set, then updates only; got {[e['op'] for e in log(ch)]}")
    if ch.js("window.__dbOverlap") != 0 or errors(ch):
        bad.append("worst case: overlap or console error")
    # (b) a heavy but realistic pattern: 12 weeks, 5 days a week (Sunday to Thursday), 3 visits a day: all 12 weeks stay, nothing is rewritten, no `pr`, under the 90 KiB budget
    seed = {wk(d0): {(d0 + dt.timedelta(days=j)).isoformat(): {f"s{i:07d}": v2_real(i, d0.toordinal() % 100) for i in range(3)} for j in range(5)} for d0 in weeks[:12]}
    body = {"u": UID, "v": 2, "first": "2026-04-01", "last": "2026-11-09", "w": seed}
    ch = load(usage={"seed": {PATH: body}}, shift_to=now)
    click(ch, '#seclist a[data-jump="h-eff"]'); ch.wait_for("window.__dbLog.some(e => e.op === 'update' && e.result === 'ok')", 4); time.sleep(0.2)
    d = docs(ch).get(PATH) or {}
    size = len(json.dumps(d).encode())
    n = sum(len(v) for days in d["w"].values() for v in days.values())
    if sorted(d.get("w") or {}) != twelve or "set" in [e["op"] for e in log(ch)] or "pr" in d:
        bad.append(f"heavy pattern: all 12 weeks stay, nothing is replaced, no pr; got {sorted(d.get('w') or {})} {[e['op'] for e in log(ch)][:3]} pr={d.get('pr')}")
    if size >= 90 * 1024:
        bad.append(f"heavy pattern: the record is {size / 1024:.1f} KiB, not under 90 KiB")
    NOTES.append(f"the heavy realistic pattern (5 days a week, 3 visits a day, 12 weeks): {n} sessions, {size / 1024:.1f} KiB ({size // n} bytes a session); budget 90 KiB; the absolute worst case is held to 90 KiB by dropping the oldest weeks")
    # (c) a light record: older than 12 weeks goes, exactly the last 12 weeks stay, nothing dropped by size so no `pr`
    light = {"u": UID, "v": 2, "first": "2026-04-01", "last": "2026-11-09", "w": {wk(d0): {d0.isoformat(): {"zzzzzzz1": {"t": 1, "s": 5, "vs": 10}}} for d0 in weeks}}
    ch = load(usage={"seed": {PATH: light}}, shift_to=now)
    click(ch, '#seclist a[data-jump="h-eff"]'); ch.wait_for("window.__dbLog.some(e => e.op === 'set' && e.result === 'ok')", 4); time.sleep(0.2)
    d = docs(ch).get(PATH) or {}
    if sorted(d.get("w") or {}) != twelve or "pr" in d:
        bad.append(f"a light record: exactly the last 12 weeks stay and no pr; got {sorted(d.get('w') or {})} pr={d.get('pr')}")
    # (d) a schema 1 record (ISO week keys, minute-level t): small and current is merged into, never replaced; it becomes schema 2; the earlier visit is untouched
    small = {"u": UID, "v": 1, "first": "2026-11-01", "last": "2026-11-09", "w": {"2026-W46": {"2026-11-09": {"zzzzzzz1": {"t": 29_000_000, "s": 5}}}}}
    ch = load(usage={"seed": {PATH: small}}, shift_to=now)
    click(ch, '#seclist a[data-jump="h-eff"]'); ch.wait_for("window.__dbLog.some(e => e.op === 'update' && e.result === 'ok')", 4)
    d = docs(ch).get(PATH) or {}
    if [e["op"] for e in log(ch)][:2] != ["get", "update"] or "set" in [e["op"] for e in log(ch)]:
        bad.append(f"a small schema 1 record is merged into, never replaced: {[e['op'] for e in log(ch)]}")
    if d.get("v") != 2 or ((d.get("w") or {}).get("2026-W46") or {}).get("2026-11-09", {}).get("zzzzzzz1") != {"t": 29_000_000, "s": 5} or wk(sun) not in (d.get("w") or {}):
        bad.append(f"a schema 1 record: expected v 2, the old visit untouched under its ISO key and the new one under {wk(sun)}; got {json.dumps(d)[:200]}")
    # (e) schema 1 ISO weeks are kept while their last day is not before the cut
    iso = {f"2026-W{n}": {dt.date.fromisocalendar(2026, n, 3).isoformat(): {"zzzzzzz1": {"t": 29_000_000, "s": 5}}} for n in range(30, 47)}
    ch = load(usage={"seed": {PATH: {"u": UID, "v": 1, "first": "2026-04-01", "last": "2026-11-09", "w": iso}}}, shift_to=now)
    click(ch, '#seclist a[data-jump="h-eff"]'); ch.wait_for("window.__dbLog.some(e => e.op === 'set' && e.result === 'ok')", 4); time.sleep(0.2)
    d = docs(ch).get(PATH) or {}
    want = sorted([k for k in iso if week_end(k) >= cut] + [wk(sun)])
    if sorted(d.get("w") or {}) != want:
        bad.append(f"schema 1 weeks: kept {sorted(d.get('w') or {})}, expected {want}")
    return bad


def b_daycap() -> list[str]:
    """At most 10 sessions a day: a page load that finds 9 stored for today writes its first visit as the 10th; a later visit of the same load is not written."""
    bad: list[str] = []
    now = dt.datetime(2026, 11, 10, 10, 0, tzinfo=dt.timezone.utc)
    seed = {"u": UID, "v": 2, "first": "2026-11-01", "last": "2026-11-10", "w": {"S2026-11-08": {"2026-11-10": {f"zzzzzz{i:02d}": {"t": 490_000 + i, "s": 5, "vs": 5} for i in range(9)}}}}
    ch = load(usage={"seed": {PATH: seed}, "t": {**FAST, "split": 1500}}, shift_to=now)
    click(ch, '#seclist a[data-jump="h-eff"]'); ch.wait_for("window.__dbLog.some(e => e.op === 'update' && e.result === 'ok')", 4); time.sleep(0.3)
    first = snap(ch)["S"]["sid"]
    time.sleep(1.8)
    click(ch, '#seclist a[data-jump="h-bugs"]'); time.sleep(0.8)
    second = snap(ch)["S"]["sid"]
    settle(ch, restore=False)
    ids = set(((docs(ch).get(PATH) or {}).get("w", {}).get("S2026-11-08") or {}).get("2026-11-10") or {})
    if first == second:
        bad.append("no new visit after the idle gap")
    if first not in ids or second in ids or len(ids) != 10:
        bad.append(f"the day cap: expected the first visit stored as the 10th and the second not, got {len(ids)} sessions, first stored {first in ids}, second stored {second in ids}")
    return bad

# ------------------------------------------------------------------------------------------------ tests
@SUITE.test("usage_the_vocabularies_and_the_documented_access_rules_are_the_ones_in_the_page")
def _(t: T):
    src = ctx.template.read_text(encoding="utf-8")
    rec = src[src.index("const USAGE_VOC"):src.index("// ---------------------------------------------------------------- live usage view (owner only")]      # the recording block; the owner-only view after it is checked in test_usage_report.py and usage_view_check.py
    m = re.search(r"const USAGE_VOC = (\{.*?\});\n", src)
    t.check(bool(m), "the page has one USAGE_VOC literal")
    if m:
        t.check(json.loads(m.group(1)) == VOC, "the page's vocabulary equals the one spelled out in this oracle")
    t.check(json.dumps(CAPS)[1:-1] in src.replace('": ', '":').replace('", ', '",') or "usage/{self}" in src, "the access rules are written in the page")
    t.check('user.id()' in rec and 'user.name' not in rec and 'user.email' not in rec and 'scopes' not in rec, "the block reads only user.id(): no name, no e-mail, no scopes")
    t.check(rec.count("window.claude.use(\"db\")") == 1 and "fetch(" not in rec and "sendBeacon" not in src and "XMLHttpRequest" not in rec, "the only way out of the block is the db capability")




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


@SUITE.test("usage_the_note_says_pseudonymous_never_anonymous_shows_after_the_first_successful_write_and_the_page_works_without_logging")
def _(t: T):
    bad = b_notice()
    t.check(not bad, "; ".join(bad))


@SUITE.test("usage_the_note_appears_only_after_the_first_successful_write_never_for_a_refused_viewer")
def _(t: T):
    bad = b_note_after_write()
    t.check(not bad, "; ".join(bad))


@SUITE.test("usage_refused_or_failing_writes_stop_after_three_and_never_break_the_page")
def _(t: T):
    bad = b_fail()
    t.check(not bad, "; ".join(bad))


@SUITE.test("usage_the_israel_day_and_the_sunday_week_key_across_a_sunday_a_year_and_a_timezone")
def _(t: T):
    bad = b_week()
    t.check(not bad, "; ".join(bad))


@SUITE.test("usage_a_visit_is_split_at_israel_midnight_across_a_week_and_a_year_boundary")
def _(t: T):
    bad = b_midnight()
    t.check(not bad, "; ".join(bad))


@SUITE.test("usage_a_new_visit_starts_after_30_minutes_without_input_and_not_before")
def _(t: T):
    bad = b_split()
    t.check(not bad, "; ".join(bad))


@SUITE.test("usage_a_glance_of_5_seconds_or_more_is_recorded_when_the_page_is_hidden_or_left_and_a_shorter_look_is_not")
def _(t: T):
    bad = b_glance()
    t.check(not bad, "; ".join(bad))


@SUITE.test("usage_reading_time_goes_to_every_section_of_the_side_by_side_row_and_to_top_above_the_first_anchor")
def _(t: T):
    bad = b_reading()
    t.check(not bad, "; ".join(bad))


@SUITE.test("usage_a_middle_click_on_a_jira_link_is_a_link_followed")
def _(t: T):
    bad = b_links()
    t.check(not bad, "; ".join(bad))


@SUITE.test("usage_resize_observer_notices_are_benign_and_never_errors")
def _(t: T):
    bad = b_errors()
    t.check(not bad, "; ".join(bad))


@SUITE.test("usage_refresh_declined_failed_ok_and_without_a_connector_are_told_apart")
def _(t: T):
    bad = b_refresh()
    t.check(not bad, "; ".join(bad))


@SUITE.test("usage_the_age_of_the_data_and_the_build_day_follow_the_page_stamps")
def _(t: T):
    bad = b_age()
    t.check(not bad, "; ".join(bad))


@SUITE.test("usage_a_saved_filter_at_the_start_and_a_reset_after_a_change_are_flagged_not_the_release")
def _(t: T):
    bad = b_flags()
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




@SUITE.test("usage_retention_keeps_12_weeks_10_sessions_a_day_and_a_small_record_with_one_set_on_an_existing_record_and_pr_when_the_cap_drops_weeks")
def _(t: T):
    NOTES.clear()
    bad = b_retention()
    t.check(not bad, "; ".join(bad))
    for n in NOTES:
        t.note(n)


@SUITE.test("usage_a_page_load_never_stores_more_than_the_10_sessions_a_day_allows")
def _(t: T):
    bad = b_daycap()
    t.check(not bad, "; ".join(bad))


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
    t.check(record_first(ch), "the first write happened (the note comes with it)")
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
    ("name_recorded", [("uid = id; on = true;", "uid = id; try { S.n = await user.name(); } catch (e) {} on = true;"), ("const o = {t: s.t, s: s.s, vs: s.vs, d: width(), lf: s.lf}, sha", "const o = {t: s.t, s: s.s, vs: s.vs, d: width(), lf: s.lf, n: S.n}, sha")], b_main),
    ("issue_key_recorded", [('if (a && isJira(a)) bump("l", secOf(a) || "other");', 'if (a && isJira(a)) { const k = ((a.getAttribute("href") || "").match(/[A-Z][A-Z0-9]+-[0-9]+/) || ["other"])[0]; S.l[k] = (S.l[k] || 0) + 1; S.dirty = true; }')], b_main),
    ("a_project_name_recorded", [("if (BT != null) o.bt = BT;", "if (BT != null) o.bt = BT; o.pj = [...state.projects][0];")], b_main),
    ("the_release_viewed_recorded", [("if (BT != null) o.bt = BT;", "if (BT != null) o.bt = BT; o.rv = state.release;")], b_main),
    ("a_field_outside_the_allowlist_written", [("if (BT != null) o.bt = BT;", "if (BT != null) o.bt = BT; o.ua = navigator.language;")], b_main),
    ("minute_level_t", [("t: Math.floor(now / 36e5)", "t: Math.floor(now / 6e4)")], b_main),
    ("idle_time_counted", [("if (focused() && n - lastInput < T.idle) { S.s +=", "if (focused() && true) { S.s +=")], b_idle),
    ("hidden_time_counted", [("    if (visible()) {\n      const n = Date.now();", "    if (true) {\n      const n = Date.now();")], b_idle),
    ("visible_seconds_only_when_focused", [("S.vs = Math.min(S.vs + SEC_PER_TICK, VS_MAX);", "if (focused()) S.vs = Math.min(S.vs + SEC_PER_TICK, VS_MAX);")], b_idle),
    ("write_at_load", [("timer = setInterval(tick, T.tick);\n  }", "timer = setInterval(tick, T.tick); S.inter = true; S.dirty = true; flush();\n  }")], b_load),
    ("a_glance_written_at_load", [("timer = setInterval(tick, T.tick);\n  }", "timer = setInterval(tick, T.tick); S.g = 1; S.glanced = true; S.dirty = true; flush();\n  }")], b_load),
    ("counter_by_read_modify_write", [("if (ready) { await retrying(() => ref.update({v: SCHEMA, last: today, w: mine})); return; }", "if (ready) { await retrying(() => ref.get()); await retrying(() => ref.update({v: SCHEMA, last: today, w: mine})); return; }")], b_main),
    ("document_per_session", [('const ref = db.doc("usage/" + uid), today', 'const ref = db.doc("usage/" + uid + "_" + s.sid), today')], b_main),
    ("unbounded_keys", [("const room = (map, key) => key in map || Object.keys(map).length < MAP_CAP;", "const room = (map, key) => true;")], b_cap),
    ("note_shown_when_inactive", [("async function init() {\n    if (!RUNTIME) return;", "async function init() {\n    if (RUNTIME) note();\n    if (!RUNTIME) return;")], b_notice),
    ("note_says_anonymous", [("per pseudonymous user id", "per anonymous user id")], b_notice),
    ("note_shown_before_the_first_write", [("timer = setInterval(tick, T.tick);\n", "timer = setInterval(tick, T.tick); note();\n")], b_note_after_write),
    ("unlimited_retries", [("if (fails >= FAIL_MAX || !e", "if (!e")], b_fail),
    ("the_viewers_day_instead_of_israel", [("const dayOf = ms => ilDate(ms);", "const dayOf = ms => { const d = new Date(ms); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };")], b_week),
    ("iso_monday_weeks_instead_of_sunday_weeks", [("dayMs(day) - new Date(dayMs(day)).getUTCDay() * DAY);", "dayMs(day) - ((new Date(dayMs(day)).getUTCDay() + 6) % 7) * DAY);")], b_week),
    ("overlapping_writes", [("if (inflight || stopped || !on) return;\n    const s = pending();", "if (stopped || !on) return;\n    const s = pending();"), ("if (inflight) { if (force) again = true; return; }", "")], b_main),
    ("write_of_unchanged_data", [("(S.dirty && canWrite(S) ? S : null);", "(canWrite(S) ? S : null);")], b_idle),
    ("glance_not_recorded", [("if (!canWrite(S) && !S.mute && S.vs >= GLANCE_MIN) {", "if (false) {")], b_glance),
    ("glance_recorded_below_5_seconds", [("GLANCE_MIN = 5,", "GLANCE_MIN = 0,")], b_glance),
    ("a_glance_visit_is_reused_for_the_next_look", [("S.glanced = true; S.closed = true;", "S.glanced = true;")], b_glance),
    ("attribution_credits_only_the_first_section_of_the_row", [("function credit() { reading().forEach(", "function credit() { reading().slice(0, 1).forEach(")], b_reading),
    ("top_not_recorded", [('if (SEC.top()) return ["top"];', "if (SEC.top()) return [];")], b_reading),
    ("no_new_visit_after_30_minutes_idle", [("|| n - (lastInput || S.startMs) >= T.split)) rotate();", ")) rotate();")], b_split),
    ("no_new_visit_at_israel_midnight", [("(S.closed || (chk && dayOf(n) !== S.day) ||", "(S.closed ||"), ("if (n - lastInput < T.idle && dayOf(n) !== S.day) rotate();", "")], b_midnight),
    ("middle_click_not_counted", [('document.addEventListener("auxclick", onAux, o);', "")], b_links),
    ("benign_errors_counted_as_errors", [("const BENIGN = /^ResizeObserver loop/;", "const BENIGN = /^never matches/;")], b_errors),
    ("refresh_declined_counted_as_a_failure", [('lvNow = result === "ok" ? 0 : result === "declined" ? 1 : 2;', 'lvNow = result === "ok" ? 0 : 2;')], b_refresh),
    ("stale_data_bucket_off", [("a < 864e5 ? 1", "a < 1e9 ? 1")], b_age),
    ("the_release_counted_in_the_saved_filter_flag", [('.some(k => k !== "r") ? 1 : 0', ".some(k => true) ? 1 : 0")], b_flags),
    ("pr_not_set_when_the_size_cap_drops_weeks", [("while (size(out) > DOC_MAX) { out.pr = 1; ", "while (size(out) > DOC_MAX) { ")], b_retention),
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
