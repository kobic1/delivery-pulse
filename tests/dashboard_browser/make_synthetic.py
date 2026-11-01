#!/usr/bin/env python3
"""A FICTITIOUS Delivery Pulse payload with the same schema as program_dashboard/build/program_data.json.

Nothing here comes from Jira: the project codes are the seven dashboard codes (plus CXCROSS, which the page hard-codes for its
own section), every issue number starts at 90001, teams are "Team Alpha" ..., people are "Person A" ..., titles are made of
invented words, and every date is relative to `today` (Israel-local, the page's time base) so the page's time logic works on
any day. The generator is deterministic: the same `today` and `seed` give the same payload.

    python3 make_synthetic.py out.html [--template PATH] [--canary]     # render a page
    python3 make_synthetic.py out.json                                   # just the payload

`render_page` replaces the single `/*__DATA__*/null` placeholder the same way build_dashboard.render() does.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import random
import sys
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    IL = ZoneInfo("Asia/Jerusalem")
except Exception:                                   # no tz database: a fixed offset is good enough for a fixture
    IL = dt.timezone(dt.timedelta(hours=2))

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
LIVE_TEMPLATE = REPO / "program_dashboard" / "dashboard.template.html"

BASE_PROJECTS = ["PMN", "CXCO", "CXSUP", "CXWFM", "WFM", "CXINT"]      # the first six share one random stream and one issue counter, in this order
PROJECTS = BASE_PROJECTS + ["INT"]                                      # INT is drawn from its own stream (Gen.stream) after everything else, so adding it left every other project's records as they were
RELEASES = ["25.4", "26.1", "26.2", "26.3", "26.4", "27.1", "27.2"]
CURRENT = "27.1"
PROVISIONAL = ["27.1", "27.2"]
JIRA_BASE = "https://jira.example.test"
CLOUD_ID = "00000000-0000-0000-0000-000000000000"
CFB_ACCOUNT = "acct:synthetic-cfb-reporter"
EPOCH = "2025-01-01"
OPEN_STATUSES = ["New", "Ready for Dev", "In Progress", "Validation"]
CANARY_A = '"><img src=x onerror=window.__x=1>'
CANARY_B = "<script>window.__x=1</script>"

TEAMS = {                                           # project -> the fictitious teams that work in it
    "PMN": ["Team Alpha", "Team Bravo", "Team Charlie", "Team Delta"],
    "CXCO": ["Team Echo", "Team Foxtrot", "Team Golf"],
    "CXSUP": ["Team Hotel", "Team India"],
    "CXWFM": ["Team Juliet", "Team Kilo", "Team Lima"],
    "WFM": ["Team Mike", "Team November", "Team Oscar"],
    "CXINT": ["Team Papa", "Team Quebec"],
}
TEAMS_ALL = {**TEAMS, "INT": ["Team Romeo", "Team Sierra"]}       # TEAMS stays the six projects' (the base draws pick from all of its teams); INT's teams are only ever picked by INT's own stream
EPICS_PER_RELEASE = {"PMN": 22, "CXCO": 12, "CXSUP": 6, "CXWFM": 14, "WFM": 12, "CXINT": 10, "INT": 8}
BUGS_PER_PROJECT = {"PMN": 330, "CXCO": 180, "CXSUP": 90, "CXWFM": 210, "WFM": 200, "CXINT": 110, "INT": 90}
CATEGORIES = [("Product - Feature work", 30), ("Product - Other", 10), ("R&D - Arch/infra refactoring", 10), ("Maintenance", 8), ("Product - Scale enhancement", 6),
              ("R&D - 3rd party upgrades", 5), ("Product - Security", 4), ("NFR", 3), ("SOW", 2), ("R&D Infra", 2), ("DevOps", 2), (None, 12)]
WORDS_A = ["Orbit", "Lattice", "Beacon", "Quill", "Harbor", "Prism", "Ember", "Cobalt", "Meadow", "Summit", "Tundra", "Willow", "Zephyr", "Granite", "Mosaic", "Nimbus"]
WORDS_B = ["sync service", "rollup", "gateway", "inspector", "planner", "exporter", "scheduler", "importer", "viewer", "validator", "mapper", "notifier"]
WORDS_C = ["phase 1", "phase 2", "hardening", "migration", "pilot", "rework", "refresh", "baseline"]
CAP_VALUES = ["Capitalize - New Feature", "Capitalize - Fix before release", "Capitalize - Architecture", "Non Capitalize - Research",
              "Non Capitalize - Fix in production", "Non Capitalize - NFR"]
RCA_TEMPLATES = ["Synthetic template text one", "Synthetic template text two", "Synthetic template text three", "Synthetic template text four"]


def il_today() -> dt.date:
    return dt.datetime.now(IL).date()


def h53(text: str, seed: int = 0) -> int:
    """cyrb53 over the UTF-16 units of the text, exactly as the page computes it (the RCA template hashes)."""
    m = 0xFFFFFFFF
    imul = lambda a, b: (a * b) & m
    h1, h2 = (0xDEADBEEF ^ seed) & m, (0x41C6CE57 ^ seed) & m
    units = text.encode("utf-16-le")
    for i in range(0, len(units), 2):
        ch = units[i] | (units[i + 1] << 8)
        h1, h2 = imul(h1 ^ ch, 2654435761), imul(h2 ^ ch, 1597334677)
    h1 = imul(h1 ^ (h1 >> 16), 2246822507) ^ imul(h2 ^ (h2 >> 13), 3266489909)
    h2 = imul(h2 ^ (h2 >> 16), 2246822507) ^ imul(h1 ^ (h1 >> 13), 3266489909)
    return 4294967296 * (2097151 & h2) + (h1 & m)


def norm_text(t: str) -> str:
    return " ".join(t.lower().split())


def il_stamp(day: dt.date, hour: int = 9, minute: int = 0) -> str:
    """An ISO stamp with minute precision and the Israel offset of that day, as the build writes `generated`."""
    when = dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=IL)
    off = when.utcoffset() or dt.timedelta(0)
    sign = "+" if off >= dt.timedelta(0) else "-"
    mins = abs(int(off.total_seconds() // 60))
    return when.strftime("%Y-%m-%dT%H:%M") + f"{sign}{mins // 60:02d}:{mins % 60:02d}"


def q_start(d: dt.date) -> dt.date:
    return dt.date(d.year, (d.month - 1) // 3 * 3 + 1, 1)


class Gen:
    def __init__(self, today: dt.date, seed: int):
        self.today = today
        self.seed = seed
        self.r = random.Random(seed)
        self.n = 90000                                  # every issue number is 90001 or more, from one counter
        self.seed, self.streams = seed, {}
        self.windows = {}
        self.cur_i = RELEASES.index(CURRENT)
        s = today - dt.timedelta(days=23)               # the current release started 23 days ago (the IP week plus two weeks)
        for i, rel in enumerate(RELEASES):
            a = s + dt.timedelta(days=91 * (i - self.cur_i))
            self.windows[rel] = [a, a + dt.timedelta(days=90)]
        self.generated_day = today - dt.timedelta(days=2)

    # ---- helpers
    @contextlib.contextmanager
    def stream(self, name: str):
        """Inside the block every draw and every issue number comes from the stream of `name` (its own random generator and counter), so what is drawn here cannot move anything drawn outside."""
        saved = (self.r, self.n)
        self.r, self.n = self.streams.get(name) or (random.Random(f"{self.seed}:{name}"), 90000)
        try:
            yield
        finally:
            self.streams[name] = (self.r, self.n)
            self.r, self.n = saved

    def num(self) -> int:
        self.n += self.r.randint(1, 2)
        return self.n

    def key(self, proj: str) -> str:
        return f"{proj}-{self.num()}"

    def pick(self, items, weights=None):
        return self.r.choices(items, weights=weights, k=1)[0]

    def title(self) -> str:
        return f"{self.r.choice(WORDS_A)} {self.r.choice(WORDS_B)}: {self.r.choice(WORDS_C)} {self.r.randint(1, 99)}"

    def d(self, day: dt.date) -> str:
        return day.isoformat()

    def between(self, a: dt.date, b: dt.date) -> dt.date:
        if b < a:
            b = a
        return a + dt.timedelta(days=self.r.randint(0, (b - a).days))

    # ---- sprints: 21-day sprints, four per release after a 7-day IP week
    def sprints(self, used: set) -> list:
        out, no = [], 100
        names = ["25.3"] + RELEASES + ["27.3"]
        for i, rel in enumerate(names):
            start = self.windows[RELEASES[0]][0] + dt.timedelta(days=91 * (i - 1)) if rel not in self.windows else self.windows[rel][0]
            for k in range(4):
                no += 1
                s = start + dt.timedelta(days=7 + 21 * k)
                lab = f"SPR.{rel}.{no} ({s.strftime('%d%b%y')})"
                out.append({"n": lab, "rel": rel, "no": no, "start": self.d(s), "end": self.d(s + dt.timedelta(days=20)), "real": lab in used})
        return out

    def build(self) -> dict:
        r, today = self.r, self.today
        gen_day = self.generated_day
        windows = {rel: [self.d(a), self.d(b)] for rel, (a, b) in self.windows.items()}
        cap_start = self.windows["25.4"][0] + dt.timedelta(days=30)             # release 25.4 starts before the pull does, so Release mode leaves it out (as in the real data)
        sprint_pool = self.sprints(set())
        by_rel = {}
        for s in sprint_pool:
            by_rel.setdefault(s["rel"], []).append(s)

        # ---- capabilities: CXCROSS ones (under initiatives) and ones in the dashboard projects
        caps, hier, cap_list = {}, {}, {}
        inis = []
        for i in range(6):
            k = self.key("CXCROSS")
            inis.append(k)
            hier[k] = {"ty": "Initiative", "t": f"{r.choice(WORDS_A)} initiative {i + 1}", "s": "Removed" if i == 5 else r.choice(["New", "In Progress"]), "fv": [CURRENT], "p": "CXCROSS", "ud": self.d(today - dt.timedelta(days=r.randint(0, 20)))}
        cx_caps = []
        for i in range(24):
            k = self.key("CXCROSS")
            cx_caps.append(k)
            fv = r.choice([[CURRENT], [CURRENT], ["26.4"], ["27.2"], [], [CURRENT, "27.2"]])
            rec = {"ty": "Capability", "t": f"{r.choice(WORDS_A)} capability {i + 1}: {r.choice(WORDS_B)}", "s": "Removed" if i == 23 else r.choice(["New", "In Progress", "In Progress", "Done"]),
                   "fv": fv, "p": "CXCROSS", "ud": self.d(today - dt.timedelta(days=r.randint(0, 30))), "par": r.choice(inis[:5]) if i % 6 else inis[5]}
            if r.random() < .5:
                rec["tm"] = [r.choice(sum(TEAMS.values(), []))]
            if r.random() < .3:
                rec["c"] = r.choice(["Committed", "Stretch"])
            if r.random() < .3:
                rec["dd"] = self.d(today + dt.timedelta(days=r.randint(-10, 60)))
            hier[k] = rec
            cap_list[k] = {"fv": fv, "p": "CXCROSS", "s": rec["s"], "t": rec["t"]}
            caps[k] = rec["t"]
        proj_caps = {p: [] for p in BASE_PROJECTS}
        for p in BASE_PROJECTS:
            for i in range(6):
                k = self.key(p)
                t = f"{r.choice(WORDS_A)} capability {p.lower()} {i + 1}"
                caps[k] = t
                proj_caps[p].append(k)
                s = r.choice(["New", "In Progress", "Done", "In Progress"])
                fv = r.choice([[CURRENT], ["26.4"], ["27.2"], [], [CURRENT, "27.2"]])
                cap_list[k] = {"fv": fv, "p": p, "s": s, "t": t}
        for p in ("EXA", "EXB"):                                   # Capabilities of projects the dashboard does not cover
            for i in range(3):
                k = self.key(p)
                caps[k] = f"{r.choice(WORDS_A)} capability {p.lower()} {i + 1}"
                cap_list[k] = {"fv": r.choice([[CURRENT], []]), "p": p, "s": r.choice(["New", "Done"]), "t": caps[k]}

        # ---- teams and epics
        used_ts = set()
        epics = []
        pod_names = {p: [f"Pod-{t.split()[1]}-{i}" for t in TEAMS[p] for i in (1, 2)] for p in BASE_PROJECTS}
        pod_names["CXCO"] = [f"CXCO-{t.split()[1]}-{i}" for t in TEAMS["CXCO"] for i in (1, 2)]
        for ri, rel in enumerate(RELEASES):
            ws, we = self.windows[rel]
            for proj in BASE_PROJECTS:
                for _ in range(EPICS_PER_RELEASE[proj]):
                    e = self.epic(proj, rel, ri, ws, we, by_rel, pod_names, proj_caps, cx_caps, used_ts)
                    epics.append(e)
        # a few epics that moved between releases: two fix versions
        for e in r.sample([x for x in epics if x["fv"] == [CURRENT] and x["s"] != "Done"], 6):
            e["fv"] = [CURRENT, "27.2"]
            e["ad"]["27.2"] = self.d(today - dt.timedelta(days=r.randint(1, 9)))
        epics.sort(key=lambda e: -int(e["k"].split("-")[1]))

        self.anchor_epics(epics, by_rel, used_ts, proj_caps)
        int_epics = self.int_epics(by_rel, caps, cap_list, cx_caps, used_ts)
        sprints = self.sprints(used_ts)

        # ---- bugs
        bugs = self.bugs(epics)
        self.anchor_bugs(bugs)

        # ---- the open CFB block
        cfbx = self.cfbx(bugs)

        # ---- dependency links, story links, bugs under epics, external issues
        deps, ext, sdeps, sinfo, eb = self.links(epics, bugs)
        self.anchor_deps(epics, deps)

        # ---- INT, last: its bugs, customer-found bugs, dependency links and issues under epics, from its own stream
        with self.stream("INT"):
            int_bugs = self.bugs(epics, ["INT"])
            icf = self.cfbx(int_bugs, ["INT"])
            ideps, isdeps, isinfo, ieb = self.int_links(int_epics, epics, int_bugs)
        cfbx["bugs"].update(icf["bugs"])
        cfbx["allOpenByProject"]["INT"] = icf["allOpenByProject"]["INT"]
        cfbx["allOpen"] += icf["allOpen"] - 5
        deps += ideps
        deps.sort(key=lambda d: (d[0], d[1]))
        sdeps += isdeps
        sinfo.update(isinfo)
        eb.update(ieb)
        bugs += int_bugs
        epics += int_epics

        # ---- capabilities' child epics and the no-fix-version count
        cap_epics = [[e["k"], e["p"], e["s"], [v for v in e["fv"] if v in RELEASES], e["cat"] or "", e["cp"]] for e in epics if e.get("cp")]
        for p in ("EXA", "EXB"):
            for i in range(4):
                cap_epics.append([self.key(p), p, r.choice(["New", "Done"]), [CURRENT] if i % 2 else [], "Product - Other", r.choice([k for k, c in cap_list.items() if c["p"] == p])])
        cap_nofv = [c for c in cap_list.values() if not c["fv"] and c["s"] != "Removed"]

        cap = self.capitalization(cap_start, windows)
        data = {
            "generated": il_stamp(gen_day, 8, 30), "jiraBase": JIRA_BASE, "projects": list(PROJECTS), "releases": list(RELEASES), "current": CURRENT,
            "windows": windows, "provisional": list(PROVISIONAL), "epics": epics, "bugs": bugs, "cfbAccount": CFB_ACCOUNT, "bugSince": windows[RELEASES[0]][0],
            "quality": {"cycleTimeErrors": [], "edctDiffersFromEmail": []},
            "deps": deps, "ext": ext, "capabilities": caps, "depsDropped": {"removed": 7}, "sprints": sprints, "hier": hier, "cloudId": CLOUD_ID,
            "cycles": {"asOf": self.d(gen_day), "cycles": [], "stale": 0, "next": 0, "page": None, "projects": [], "groups": [], "epics": [], "caps": [], "noCap": 0, "jql": "", "title": "Synthetic"},
            "cfbx": cfbx, "sdeps": sdeps, "sinfo": sinfo, "capList": cap_list, "capEpics": cap_epics,
            "capNoFv": {"total": len(cap_nofv), "done": sum(1 for c in cap_nofv if c["s"] == "Done")}, "capPulledAt": il_stamp(gen_day, 8, 44),
            "eb": eb, "podRx": {p: ("pod|^CXCO-[A-Za-z]+-\\d+$" if p == "CXCO" else "pod") for p in PROJECTS}, "cap": cap,
            "capPbi": pbi_payload(pbi_cached(today, self.seed), gen_day),
        }
        return data

    # ---- epics
    def epic(self, proj, rel, ri, ws, we, by_rel, pod_names, proj_caps, cx_caps, used_ts) -> dict:
        r, today = self.r, self.today
        cur, past = ri == self.cur_i, ri < self.cur_i
        if past:
            s = self.pick(["Done", "Done", "Done", "Done", "Done", "Done", "Done", "Done", "In Progress", "Validation"], None)
        elif cur:
            s = self.pick(["Done", "Validation", "In Progress", "Ready for Dev", "In Definition", "New"], [38, 6, 22, 14, 8, 12])
        else:
            s = self.pick(["New", "In Definition", "Ready for Dev"], [40, 25, 35])
        k = self.key(proj)
        cr = ws - dt.timedelta(days=r.randint(5, 120))
        teams = [] if r.random() < .08 else r.sample(TEAMS_ALL[proj], 2 if r.random() < .1 and len(TEAMS_ALL[proj]) > 1 else 1)
        ai = r.random() < (.05 + .08 * ri)
        e = {"k": k, "p": proj, "t": self.title(), "s": s, "fv": [rel], "c": self.pick(["Committed", "Stretch", None], [70, 15, 15]), "tm": teams, "ai": ai,
             "m": f"Model-{r.randint(1, 3)}" if ai else None, "rd": None, "cr": self.d(cr), "cat": self.pick([c for c, _ in CATEGORIES], [w for _, w in CATEGORIES])}
        # join date: most epics were in the release on the first day of W1 (the day after the IP week), some were added later
        w1 = ws + dt.timedelta(days=7)
        join = cr if r.random() < .85 else self.between(w1 + dt.timedelta(days=1), min(we, today))
        e["ad"] = {rel: self.d(max(join, cr))}
        if s == "Done":
            hi = min(we + dt.timedelta(days=4), today) if not cur else today
            rd = self.between(w1, hi)
            e["rd"] = self.d(rd)
            ip = r.randint(1, 30)
            vl = r.randint(0, 15)
            e["ip"], e["vl"], e["edct"], e["cal"] = ip, vl, ip + vl, ip + vl + (r.randint(0, 6) if r.random() < .2 else 0)
        else:
            if not past and r.random() < .5:
                e["ss"] = self.d(today - dt.timedelta(days=r.randint(0, 25)))
        sprs = by_rel.get(rel, [])
        if sprs and r.random() < (.65 if s != "Done" else .5):
            sp = r.choice(sprs)
            e["ts"] = sp["n"]
            used_ts.add(sp["n"])
            if r.random() < .5:
                a = dt.date.fromisoformat(sp["start"])
                e["dd"] = self.d(a + dt.timedelta(days=r.randint(0, 20)))
        e["ud"] = e["rd"] or self.d(today - dt.timedelta(days=r.choice([0, 0, 1, 2, 3, 5, 8, 14, 21])))
        if r.random() < .75:
            e["cp"] = r.choice(cx_caps[:23] if r.random() < .35 else proj_caps[proj])
        if r.random() < .08:
            e["nf"] = 1
        if r.random() < .3:
            e["pl"] = [r.choice(pod_names[proj])]
        if r.random() < .03 and s != "Done":
            e["fl"] = 1
        return e

    # ---- INT: capabilities, epics and links, all from INT's own stream (the base draws never see them)
    def int_epics(self, by_rel, caps, cap_list, cx_caps, used_ts) -> list:
        out, keys = [], []
        with self.stream("INT"):
            r = self.r
            for i in range(6):
                k = self.key("INT")
                keys.append(k)
                caps[k] = f"{r.choice(WORDS_A)} capability int {i + 1}"
                cap_list[k] = {"fv": r.choice([[CURRENT], ["26.4"], ["27.2"], [], [CURRENT, "27.2"]]), "p": "INT", "s": r.choice(["New", "In Progress", "Done", "In Progress"]), "t": caps[k]}
            pod_names = {"INT": [f"Pod-{t.split()[1]}-{i}" for t in TEAMS_ALL["INT"] for i in (1, 2)]}
            for ri, rel in enumerate(RELEASES):
                ws, we = self.windows[rel]
                for _ in range(EPICS_PER_RELEASE["INT"]):
                    out.append(self.epic("INT", rel, ri, ws, we, by_rel, pod_names, {"INT": keys}, cx_caps, used_ts))
            for e in r.sample([x for x in out if x["fv"] == [CURRENT] and x["s"] != "Done"], 2):
                e["fv"] = [CURRENT, "27.2"]
                e["ad"]["27.2"] = self.d(self.today - dt.timedelta(days=r.randint(1, 9)))
        out.sort(key=lambda e: -int(e["k"].split("-")[1]))
        assert sum(1 for e in out if e["fv"][0] == CURRENT and e["s"] != "Done") >= 3, "the generator drew too few INT release epics"
        return out

    def int_links(self, int_epics, epics, int_bugs):
        """Dependencies between INT epics and others (both directions), story-level links inside INT, and open bugs under INT epics. Call inside stream("INT")."""
        r = self.r
        mine = [e for e in int_epics if e["fv"][0] in (CURRENT, "26.4", "27.2")]
        others = [e for e in epics if e["fv"][0] in (CURRENT, "26.4", "27.2")]
        deps, seen = [], set()
        for i in range(14):
            a, b = (r.choice(mine), r.choice(others)) if i % 2 else (r.choice(others), r.choice(mine))
            if a["k"] == b["k"] or (a["k"], b["k"]) in seen:
                continue
            seen.add((a["k"], b["k"]))
            deps.append([a["k"], b["k"], r.choice(["D", "D", "B", "DB"])])
        sdeps, sinfo = [], {}
        for _ in range(4):
            a, b = self.key("INT"), self.key("INT")
            parent = r.choice(mine)["k"]
            sinfo[a] = {"s": r.choice(["New", "In Progress", "Done"]), "ty": r.choice(["Story", "Task", "Bug"]), "par": parent}
            sinfo[b] = {"s": r.choice(["New", "In Progress", "Done"]), "ty": r.choice(["Story", "Task"])}
            sdeps.append([a, b, r.choice(["B", "D"]), [parent]])
        open_bugs = [b for b in int_bugs if b["s"] not in ("Done", "Ready for Deploy", "Closed", "Resolved", "Removed")]
        eb = {}
        for e in r.sample([x for x in int_epics if x["fv"][0] == CURRENT], 5):
            eb[e["k"]] = [[b["k"], b["s"], b.get("pr", "P3")] for b in r.sample(open_bugs, r.randint(1, 3))]
        return deps, sdeps, sinfo, eb

    # ---- anchors: whatever the random draw gave, the tests need subjects with certain facts (kept small and explicit)
    def anchor_epics(self, epics, by_rel, used_ts, proj_caps):
        today = self.today
        pmn_open = [e for e in epics if e["p"] == "PMN" and e["fv"] == [CURRENT] and e["s"] != "Done"]
        pmn_done = [e for e in epics if e["p"] == "PMN" and e["fv"] == [CURRENT] and e["s"] == "Done"]
        assert len(pmn_open) >= 10 and len(pmn_done) >= 3, "the generator drew too few release epics for the anchors"
        sprs = by_rel[CURRENT]
        pmn_open[0]["c"] = "Committed"
        pmn_open[1]["c"] = None
        for i, e in enumerate(pmn_open[2:5]):                       # pod labels
            e["pl"] = [f"Pod-Alpha-{i + 1}"]
        e = pmn_open[5]                                             # a due date and a Target Sprint to clear
        e["ts"], e["dd"] = sprs[0]["n"], self.d(dt.date.fromisoformat(sprs[0]["start"]) + dt.timedelta(days=3))
        used_ts.add(e["ts"])
        e = pmn_open[6]                                             # the dependency provider that must stay in its sprint after a Refresh
        e["ts"], e["dd"], e["cp"], e["s"] = sprs[1]["n"], self.d(dt.date.fromisoformat(sprs[1]["start"]) + dt.timedelta(days=2)), proj_caps["PMN"][0], "In Progress"
        used_ts.add(e["ts"])
        e = pmn_done[0]                                             # a Done epic with every planning fact
        e["ts"], e["dd"], e["cp"] = sprs[0]["n"], self.d(dt.date.fromisoformat(sprs[0]["start"]) + dt.timedelta(days=5)), proj_caps["PMN"][1]
        e["ip"], e["vl"], e["edct"], e["cal"] = 4, 5, 9, 9
        used_ts.add(e["ts"])

    def anchor_bugs(self, bugs):
        today, r = self.today, self.r
        pmn = [b for b in bugs if b["p"] == "PMN"]
        open_cfb = [b for b in pmn if b.get("cfb") and b["s"] in OPEN_STATUSES]
        for i in range(max(0, 6 - len(open_cfb))):
            b = {"k": self.key("PMN"), "p": "PMN", "cr": self.d(today - dt.timedelta(days=3 + 5 * i)), "s": "In Progress", "pr": "P2", "tm": TEAMS["PMN"][0], "cfb": 1, "rb": 1, "sf": 1, "inc": 2.0, "ud": self.d(today - dt.timedelta(days=1))}
            bugs.append(b)
        for b in bugs:                                              # every open CFB carries a last-update day and both flags the Refresh test reads
            if b.get("cfb") and b["s"] in OPEN_STATUSES and b["p"] == "PMN":
                b["rb"] = b["sf"] = 1
                b.setdefault("inc", 1.0)
                b.setdefault("ud", self.d(today - dt.timedelta(days=2)))
                b.pop("ax", None)
                b.pop("rg", None)
        done_cfb = [b for b in bugs if b.get("cfb") and b["s"] == "Done" and b.get("cl") and b.get("sf") and b.get("rb") and b.get("inc") is not None]
        for i in range(max(0, 2 - len(done_cfb))):
            cr = today - dt.timedelta(days=40 + i)
            bugs.append({"k": self.key("PMN"), "p": "PMN", "cr": self.d(cr), "s": "Done", "pr": "P3", "rd": self.d(cr + dt.timedelta(days=10)), "rs": "Fixed", "tm": TEAMS["PMN"][1],
                         "cfb": 1, "rb": 1, "sf": 1, "inc": 3.0, "cl": self.d(cr + dt.timedelta(days=11))})
        pm = [b for b in bugs if b["p"] == "PMN" and not b.get("cfb") and not b.get("ax") and b["s"] in OPEN_STATUSES]
        assert pm, "no plain open PMN bug"
        bugs.sort(key=lambda b: -int(b["k"].split("-")[1]))

    def anchor_deps(self, epics, deps):
        scope = [e for e in epics if e["fv"] == [CURRENT] and e["p"] == "PMN" and e["s"] != "Done"]
        provider = next(e for e in scope if e.get("cp") and e.get("ts") and e["s"] == "In Progress")
        other = next(e for e in epics if e["fv"] == [CURRENT] and e["p"] != "PMN" and e["s"] != "Done")
        if not any(d[1] == provider["k"] for d in deps):
            deps.append([other["k"], provider["k"], "D"])
            deps.sort(key=lambda d: (d[0], d[1]))

    # ---- bugs
    def bugs(self, epics, projects=None) -> list:
        r, today = self.r, self.today
        since = self.windows[RELEASES[0]][0]
        out = []
        for proj in projects or BASE_PROJECTS:
            for _ in range(BUGS_PER_PROJECT[proj]):
                cr = self.between(since, today)
                age = (today - cr).days
                is_open = r.random() < (.9 if age < 10 else .5 if age < 30 else .12 if age < 120 else .03)
                if is_open:
                    s = self.pick(["New", "Ready for Dev", "In Progress", "Validation"], [45, 20, 25, 10])
                else:
                    s = self.pick(["Done", "Resolved", "Ready for Deploy"], [85, 10, 5])
                b = {"k": self.key(proj), "p": proj, "cr": self.d(cr), "s": s}
                pr = self.pick(["P1", "P2", "P3", "P4", "None", None], [10, 35, 35, 15, 3, 2])
                if pr:
                    b["pr"] = pr
                if not is_open:
                    rd = min(self.generated_day, cr + dt.timedelta(days=r.randint(1, 60)))      # a baked snapshot holds nothing closed after its own date
                    b["rd"] = self.d(rd)
                    b["rs"] = self.pick(["Fixed", "Not a bug", "Won't Fix", "Duplicate", "Cannot Reproduce", "Limitation", "Fixed - Config", "Works as Designed"], [55, 14, 6, 8, 6, 4, 4, 3])
                if r.random() < .9:
                    b["tm"] = r.choice(TEAMS_ALL[proj])
                if r.random() < .06:
                    b["rg"] = 1
                if r.random() < .12:
                    b["ax"] = 1
                if r.random() < .09:
                    b["cfb"] = 1
                    via_rep, via_case = r.random() < .8, r.random() < .9
                    if not (via_rep or via_case):
                        via_rep = True
                    if via_rep:
                        b["rb"] = 1
                    if via_case:
                        b["sf"] = 1
                    if r.random() < .8:
                        b["inc"] = float(r.randint(0, 12))
                    if not is_open and "rd" in b and r.random() < .9 and s == "Done":
                        b["cl"] = self.d(min(self.generated_day, dt.date.fromisoformat(b["rd"]) + dt.timedelta(days=r.randint(0, 3))))
                    if s == "Ready for Deploy" and "rd" in b:
                        b["rtd"] = b["rd"]
                    if is_open and r.random() < .6:
                        b["ud"] = self.d(today - dt.timedelta(days=r.randint(0, 15)))
                out.append(b)
        # a few fixed anchors so every table has a subject whatever the random draw gave
        out.sort(key=lambda b: -int(b["k"].split("-")[1]))
        return out

    def cfbx(self, bugs, projects=None) -> dict:
        r = self.r
        res = {}
        for b in bugs:
            if not b.get("cfb"):
                continue
            rec = {"t": f"{r.choice(WORDS_A)} {r.choice(WORDS_B)} reports a wrong value", "rca": 1 if r.random() < .4 else 0}
            if rec["rca"] and r.random() < .6:
                rec["rt"] = "The cause was a missed null check in the synthetic job; fixed and verified."
            if r.random() < .15:
                rec["rv"] = r.choice(["A", "N"])
            if r.random() < .12:
                rec["lk"] = [f"{b['p']}-{self.num()}"]
            res[b["k"]] = rec
        open_cfb = [b for b in bugs if b.get("cfb") and b["s"] not in ("Done", "Ready for Deploy", "Closed", "Resolved", "Removed")]
        return {"bugs": res, "templates": len(RCA_TEMPLATES), "tpl": [h53(norm_text(t)) for t in RCA_TEMPLATES], "allOpen": len(open_cfb) + 5,
                "allOpenByProject": {**{p: sum(1 for b in open_cfb if b["p"] == p) for p in projects or BASE_PROJECTS}, "EXA": 3, "EXB": 2}, "pulledAt": il_stamp(self.generated_day, 0, 36)}

    # ---- links
    def links(self, epics, bugs):
        r = self.r
        pool = [e for e in epics if e["fv"][0] in (CURRENT, "26.4", "27.2")]
        keys = {e["k"] for e in epics}
        ext = {}
        for i in range(10):
            p = r.choice(["EXA", "EXB", "EXC", "EXD"])
            k = self.key(p)
            ext[k] = {"p": p, "t": f"{r.choice(WORDS_A)} far-end {r.choice(WORDS_B)}", "s": r.choice(["New", "In Progress", "Done"]), "fv": [r.choice([CURRENT, "27.2"])],
                      "tm": [r.choice(sum(TEAMS.values(), []))], "ud": self.d(self.today - dt.timedelta(days=r.randint(0, 20))), "ty": r.choice(["Epic", "Story", "Task"])}
        deps, seen = [], set()
        for _ in range(110):
            a, b = r.choice(pool), r.choice(pool + [{"k": k} for k in list(ext)[:6]])
            if a["k"] == b["k"] or (a["k"], b["k"]) in seen:
                continue
            seen.add((a["k"], b["k"]))
            deps.append([a["k"], b["k"], r.choice(["D", "D", "B", "DB"])])
        for k in list(ext)[6:]:
            deps.append([r.choice(pool)["k"], k, "D"])
        deps.sort(key=lambda d: (d[0], d[1]))
        sdeps, sinfo = [], {}
        for _ in range(30):
            a, b = self.key(r.choice(BASE_PROJECTS)), self.key(r.choice(BASE_PROJECTS))
            parent = r.choice(pool)["k"]
            sinfo[a] = {"s": r.choice(["New", "In Progress", "Done"]), "ty": r.choice(["Story", "Task", "Bug"]), "par": parent}
            sinfo[b] = {"s": r.choice(["New", "In Progress", "Done", "Removed"]), "ty": r.choice(["Story", "Task", "Test"])}
            sdeps.append([a, b, r.choice(["B", "D"]), [parent]])
        open_bugs = [b for b in bugs if b["s"] not in ("Done", "Ready for Deploy", "Closed", "Resolved", "Removed")]
        eb = {}
        for e in r.sample([x for x in epics if x["fv"][0] == CURRENT], 40):
            eb[e["k"]] = [[b["k"], b["s"], b.get("pr", "P3")] for b in r.sample(open_bugs, r.randint(1, 3))]
        return deps, ext, sdeps, sinfo, eb

    # ---- capitalization rows "n,p,v,sp,cd,t,fb" (issue number, project index, value index, story points, closed day from the epoch, team index, fallback flag)
    def capitalization(self, start: dt.date, windows) -> dict:
        r, today = self.r, self.today
        epoch = dt.date.fromisoformat(EPOCH)
        teams = sorted({t for ts in TEAMS.values() for t in ts})
        rows = []
        total_days = (today - start).days
        for pi, proj in enumerate(BASE_PROJECTS):
            for _ in range(int(300 * EPICS_PER_RELEASE[proj] / 22) + 40):
                day = start + dt.timedelta(days=r.randint(0, total_days))
                v = r.randrange(len(CAP_VALUES)) if r.random() < .97 else -1
                sp = r.choice([0, 0, 1, 2, 3, 5, 8, 13]) if r.random() > .15 else 0
                t = teams.index(r.choice(TEAMS[proj])) if r.random() < .92 else -1
                rows.append((self.num(), pi, v, sp, (day - epoch).days, t, 1 if r.random() < .04 else 0))
        gap_end = self.windows["26.1"][0] - dt.timedelta(days=1)                   # enough issues in the left-out release for its "not plotted" link to be a range query, not a key list
        for _ in range(300):
            pi = r.randrange(len(BASE_PROJECTS))
            proj = BASE_PROJECTS[pi]
            day = start + dt.timedelta(days=r.randint(0, (gap_end - start).days))
            rows.append((self.num(), pi, r.randrange(len(CAP_VALUES)), r.choice([0, 1, 2, 3, 5, 8]), (day - epoch).days, teams.index(r.choice(TEAMS[proj])), 0))
        # the current quarter, the day before it and today carry rows too, so a delta refresh has neighbours
        qs = q_start(today)
        for i in range(4):                                         # PMN issues closed in the current quarter, whatever day of it today is
            d = qs + dt.timedelta(days=min((today - qs).days, i))
            rows.append((self.num(), 0, r.randrange(len(CAP_VALUES)), r.choice([1, 2, 3, 5]), (d - epoch).days, 0, 0))
        with self.stream("INT"):                                   # INT: its teams go after the sorted ones, so no other project's team index moves
            ri, pi = self.r, PROJECTS.index("INT")
            teams += TEAMS_ALL["INT"]
            for _ in range(int(300 * EPICS_PER_RELEASE["INT"] / 22) + 40):
                day = start + dt.timedelta(days=ri.randint(0, total_days))
                rows.append((self.num(), pi, ri.randrange(len(CAP_VALUES)) if ri.random() < .97 else -1, ri.choice([0, 0, 1, 2, 3, 5, 8, 13]) if ri.random() > .15 else 0,
                             (day - epoch).days, teams.index(ri.choice(TEAMS_ALL["INT"])) if ri.random() < .92 else -1, 1 if ri.random() < .04 else 0))
            for _ in range(40):                                    # the left-out release, so INT has "not plotted" issues in Release mode
                day = start + dt.timedelta(days=ri.randint(0, (gap_end - start).days))
                rows.append((self.num(), pi, ri.randrange(len(CAP_VALUES)), ri.choice([0, 1, 2, 3, 5, 8]), (day - epoch).days, teams.index(ri.choice(TEAMS_ALL["INT"])), 0))
            for i in range(2):                                     # closed in the current quarter
                d = qs + dt.timedelta(days=min((today - qs).days, i))
                rows.append((self.num(), pi, ri.randrange(len(CAP_VALUES)), ri.choice([1, 2, 3, 5]), (d - epoch).days, teams.index(TEAMS_ALL["INT"][0]), 0))
        rows.sort(key=lambda x: -x[0])
        return {"start": self.d(start), "prefix": "Capitalize", "epoch": EPOCH, "projects": list(PROJECTS), "values": list(CAP_VALUES), "teams": teams,
                "rows": ";".join(",".join(str(x) for x in row) for row in rows), "pulledAt": il_stamp(self.generated_day, 0, 30)}


# ---------------------------------------------------------------- the Power BI scope of the Capitalization chart: fictitious Jira issues, the payload section, and an independent oracle
PBI_SCOPE = ["PMN", "CXSUP", "CXINT", "CXWFM", "CXCO", "INT", "EEM", "EMOB", "ESP", "DCMLT", "PVDEV"]      # the project keys of the report (keys are not secret); the Jira project WFM is not one
PBI_START, PBI_FROM = "2025-10-01", "2025-04-01"
PBI_VALUES = ["Capitalize - Feature work", "Capitalize - Fix before release", "Non Capitalize - Research", "Non Capitalize - Fix in production", "Non capitalize - Not cloud", "Misc value", ""]
PBI_CLASSES = ["Capitalized", "Non capitalized", "Unmapped"]
PBI_FIRST = 130000                                  # issue numbers of this section start above the ones the other sections and the tests use
UTC = dt.timezone.utc


def pbi_class(value: str) -> int:
    return 0 if value.startswith("Capitalize") else 1 if value.startswith("Non Capitalize") else 2


def pbi_iso(when: dt.datetime) -> str:
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def pbi_parse(text: str) -> dt.datetime:
    t = text.replace("Z", "+0000")
    return dt.datetime.strptime(t, "%Y-%m-%dT%H:%M:%S.%f%z")


def pbi_universe(today: dt.date, seed: int = 20261030) -> dict:
    """Fictitious Jira issues around the Capitalization Power BI scope: {sprints: [...], issues: [...]}. Every issue is a dict
    {key, project, num, type, status, value, sp, sprints: [Jira sprint objects], resolutiondate}. Besides the Done Bugs, Stories and Tasks of the 11 projects the
    universe holds what the rule must leave out (sub-tasks and epics, issues that are not Done, the project WFM, a last sprint before the start) and what it must treat
    with care (sprint ids that do not follow the end dates, two sprints ending the same day, ends around midnight UTC at the quarter edges, a sprint without an end date,
    issues with no sprint, empty and unmapped Capitalize values, decimal story points)."""
    r = random.Random(seed + 7)
    q0 = q_start(today)
    quarters = []
    d = q0
    for _ in range(5):
        quarters.append(d)
        d = q_start(d - dt.timedelta(days=1))
    quarters.sort()
    ends = []                                                                       # (end datetime in UTC, text of the end as Jira writes it)
    for qs in quarters:
        e = dt.datetime(qs.year, qs.month, qs.day, 21, 0, tzinfo=UTC) + dt.timedelta(days=r.randint(6, 12))
        stop = dt.datetime(*q_next(qs).timetuple()[:3], tzinfo=UTC)
        while e < stop - dt.timedelta(days=3):
            ends.append((e, pbi_iso(e)))
            if r.random() < .3:
                ends.append((e, pbi_iso(e)))                                         # a second sprint that ends at the same instant (a tie)
            e += dt.timedelta(days=14)
    for qs in quarters[1:]:                                                          # around midnight UTC at the quarter edge: the quarter is the UTC one, not the Israel or the writer's
        prev = qs - dt.timedelta(days=1)
        ends += [(dt.datetime(prev.year, prev.month, prev.day, 23, 30, tzinfo=UTC), f"{prev.isoformat()}T23:30:00.000+0000"),
                 (dt.datetime(qs.year, qs.month, qs.day, 0, 30, tzinfo=UTC), f"{qs.isoformat()}T00:30:00.000+0000"),
                 (dt.datetime(prev.year, prev.month, prev.day, 22, 0, tzinfo=UTC), f"{qs.isoformat()}T01:00:00.000+0300"),         # 22:00 UTC on the last day: the old quarter
                 (dt.datetime(qs.year, qs.month, qs.day, 3, 30, tzinfo=UTC), f"{prev.isoformat()}T22:30:00.000-0500")]            # 03:30 UTC on the first day: the new quarter
    ends = [x for x in ends if x[0].date() <= today + dt.timedelta(days=30)]
    ids = list(range(20001, 20001 + len(ends)))
    r.shuffle(ids)                                                                   # ids that do not follow the end dates: the highest id is not the last sprint
    sprints = [{"id": i, "name": f"Sprint {i}", "state": "closed" if e[0].date() < today else "active", "startDate": pbi_iso(e[0] - dt.timedelta(days=14)), "endDate": e[1], "completeDate": None}
               for i, e in zip(ids, ends)]
    old = {"id": 20000, "name": "Sprint 20000", "state": "closed", "startDate": "2025-08-01T06:00:00.000Z", "endDate": "2025-08-15T21:00:00.000Z", "completeDate": "2025-08-15T21:00:00.000Z"}
    endless = [{"id": 29001, "name": "Sprint 29001", "state": "future", "startDate": None, "endDate": None, "completeDate": None},
               {"id": 29002, "name": "Sprint 29002", "state": "future", "startDate": None, "endDate": None, "completeDate": None}]
    sprints += [old] + endless
    dated = [s for s in sprints if s["endDate"] and s["id"] != 20000]
    by_q = {}
    for s in dated:
        by_q.setdefault(pbi_quarter(s["endDate"]), []).append(s)
    qkeys = sorted(by_q)
    weights = dict(zip(PBI_SCOPE, [30, 22, 12, 28, 10, 8, 18, 1, 9, 5, 26]))       # EMOB is tiny (a share needs 5 issues), CXCO is absent from the first quarter
    issues, n = [], PBI_FIRST

    def make(proj, status, typ, last, **kw):
        nonlocal n
        n += r.randint(1, 3)
        extra = [s for s in r.sample(dated, r.choice([0, 0, 1, 2])) if pbi_parse(s["endDate"]) < pbi_parse(last["endDate"])] if last else []
        pool = ([last] if last else []) + extra + ([r.choice(endless)] if last and r.random() < .08 else [])
        r.shuffle(pool)
        end = pbi_parse(last["endDate"]) if last else dt.datetime(today.year, today.month, today.day, 12, tzinfo=UTC) - dt.timedelta(days=r.randint(1, 250))
        res = (end - dt.timedelta(days=r.randint(0, 6), hours=r.randint(0, 5))).astimezone(IL)
        issues.append({"key": f"{proj}-{n}", "project": proj, "num": n, "type": typ, "status": status, "value": kw.get("value", r.choice(PBI_VALUES[:4] * 3 + PBI_VALUES[4:])),
                       "sp": kw.get("sp", r.choice([None, 0, 1, 2, 3, 5, 8, 13, 0.5, 2.5])), "sprints": pool, "resolutiondate": res.strftime("%Y-%m-%dT%H:%M:%S.000%z")})
        return issues[-1]

    for qk in qkeys:
        for proj in PBI_SCOPE:
            if proj == "CXCO" and qk == qkeys[0]:
                continue
            for _ in range(max(0, int(weights[proj] * r.uniform(.7, 1.3) * (.4 if qk == qkeys[-1] else 1)))):
                make(proj, "Done", r.choice(["Story", "Story", "Bug", "Task"]), r.choice(by_q[qk]))
    for proj in ("PMN", "CXWFM", "PVDEV", "ESP"):                                  # left out by the rule
        for _ in range(6):
            make(proj, "Done", "Sub-task", r.choice(dated))
            make(proj, "Done", "Epic", r.choice(dated))
            make(proj, r.choice(["In Progress", "Removed", "Validation"]), "Story", r.choice(dated))
            make("WFM", "Done", r.choice(["Story", "Bug"]), r.choice(dated))
    for proj in ("PMN", "PVDEV", "ESP", "INT"):                                    # Done, but the last sprint is before the start of 2025-Q4: not in the payload
        for _ in range(3):
            make(proj, "Done", "Bug", old)
    for proj in PBI_SCOPE * 3:                                                      # Done with no sprint at all, or only a sprint without an end date: counted apart
        i = make(proj, "Done", r.choice(["Story", "Bug", "Task"]), None)
        if r.random() < .25:
            i["sprints"] = [r.choice(endless)]
    for proj in ("PMN", "ESP"):                                                     # resolved before the pull window starts: not even counted
        for _ in range(2):
            i = make(proj, "Done", "Story", None)
            i["resolutiondate"] = "2025-03-20T10:00:00.000+0200"
    return {"sprints": sprints, "issues": issues}


def q_next(d: dt.date) -> dt.date:
    return dt.date(d.year + (d.month + 2) // 12, (d.month + 2) % 12 + 1, 1)


def pbi_quarter(end_text: str) -> str:
    e = pbi_parse(end_text).astimezone(UTC)
    return f"{e.year}-Q{(e.month - 1) // 3 + 1}"


def pbi_last(issue: dict):
    """The issue's last sprint by the rule (latest end date, a tie goes to the higher id), or None."""
    with_end = [s for s in issue["sprints"] if s["endDate"]]
    return max(with_end, key=lambda s: (pbi_parse(s["endDate"]), s["id"])) if with_end else None


def pbi_in_scope(issue: dict) -> bool:
    return issue["project"] in PBI_SCOPE and issue["status"] == "Done" and issue["type"] in ("Bug", "Story", "Task")


def pbi_oracle(issues: list) -> dict:
    """The expected numbers, computed straight from the issues (no payload, no page): {(quarter, project): {capSP, allSP, capN, allN, noSp, cls: [[n, sp] x 3]}} for the quarters from 2025-Q4 on,
    and 'none': {n, sp} for the Done issues with no sprint end date resolved on or after the pull day."""
    out, none = {}, {"n": 0, "sp": 0.0}
    for i in issues:
        if not pbi_in_scope(i) or i["key"] == "MS-21777":
            continue
        sp = float(i["sp"]) if isinstance(i["sp"], (int, float)) else 0.0
        last = pbi_last(i)
        if last is None:
            if i["resolutiondate"][:10] >= PBI_FROM:
                none["n"] += 1
                none["sp"] += sp
            continue
        if pbi_parse(last["endDate"]).astimezone(UTC).date().isoformat() < PBI_START:
            continue
        c = out.setdefault((pbi_quarter(last["endDate"]), i["project"]), {"capSP": 0.0, "allSP": 0.0, "capN": 0, "allN": 0, "noSp": 0, "cls": [[0, 0.0], [0, 0.0], [0, 0.0]]})
        k = pbi_class(i["value"])
        c["allSP"] += sp
        c["allN"] += 1
        c["noSp"] += 1 if sp == 0 else 0
        c["cls"][k][0] += 1
        c["cls"][k][1] += sp
        if k == 0:
            c["capSP"] += sp
            c["capN"] += 1
    return {"cells": out, "none": none}


def pbi_payload(universe: dict, gen_day: dt.date) -> dict:
    """DATA.capPbi for the fictitious issues, encoded here on its own (not with the collector): rows 'number,project,class,points,sprint index'."""
    sprint_ix, table, rows, none, cap_vals, non_vals = {}, [], [], [], set(), set()
    for i in universe["issues"]:
        if not pbi_in_scope(i):
            continue
        k = pbi_class(i["value"])
        (cap_vals if k == 0 else non_vals if k == 1 else set()).add(i["value"])
        sp = float(i["sp"]) if isinstance(i["sp"], (int, float)) else 0.0
        last = pbi_last(i)
        pi = PBI_SCOPE.index(i["project"])
        if last is None:
            if i["resolutiondate"][:10] >= PBI_FROM:
                none.append((pi, i["num"], sp))
            continue
        day = pbi_parse(last["endDate"]).astimezone(UTC).date().isoformat()
        if day < PBI_START:
            continue
        if last["id"] not in sprint_ix:
            sprint_ix[last["id"]] = len(table)
            table.append([last["id"], day])
        rows.append((pi, i["num"], k, sp, sprint_ix[last["id"]]))
    rows.sort()
    none.sort()
    g = lambda v: ("%g" % v)
    return {"scope": list(PBI_SCOPE), "values": list(PBI_CLASSES), "opts": [sorted(cap_vals), sorted(non_vals)], "start": PBI_START, "from": PBI_FROM, "sprints": table,
            "rows": ";".join(f"{n},{pi},{k},{g(sp)},{si}" for pi, n, k, sp, si in rows),
            "noSprint": {"n": len(none), "sp": float(g(sum(x[2] for x in none))), "rows": ";".join(f"{n},{pi},{g(sp)}" for pi, n, sp in none)},
            "pulledAt": il_stamp(gen_day, 0, 40), "refreshedAt": None}


def pbi_node(issue: dict) -> dict:
    """An issue as the connector's search answer carries it (the fields the page asks for)."""
    return {"id": "1", "key": issue["key"], "webUrl": "x", "fields": {
        "status": {"name": issue["status"]}, "issuetype": {"name": issue["type"]}, "customfield_10038": issue["sp"],
        "customfield_10079": {"value": issue["value"]} if issue["value"] else None, "customfield_10020": issue["sprints"] or None, "resolutiondate": issue["resolutiondate"]}}


_PBI: dict = {}


def pbi_cached(today: dt.date, seed: int = 20261030) -> dict:
    if (today, seed) not in _PBI:
        _PBI[(today, seed)] = pbi_universe(today, seed)
    return _PBI[(today, seed)]


# ---------------------------------------------------------------- the escaping canary
def canarify(data: dict) -> dict:
    """Put the two hostile strings into every free-text field the page renders. The mapping is consistent (the same text always becomes
    the same hostile text), so team filters, sprint lookups and capability names still match."""
    cache = {}

    def can(s):
        if not isinstance(s, str) or not s:
            return s
        if s not in cache:
            cache[s] = f"{s} {CANARY_A if len(cache) % 2 == 0 else CANARY_B}"
        return cache[s]

    for e in data["epics"]:
        for f in ("t", "m", "cat", "ts"):
            if e.get(f):
                e[f] = can(e[f])
        e["tm"] = [can(x) for x in e["tm"]]
        if e.get("pl"):
            e["pl"] = [can(x) for x in e["pl"]]
    for b in data["bugs"]:
        for f in ("tm", "rs"):
            if b.get(f):
                b[f] = can(b[f])
    for s in data["sprints"]:
        s["n"] = can(s["n"])
    for sec in ("capabilities",):
        data[sec] = {k: can(v) for k, v in data[sec].items()}
    for tab in ("hier", "capList", "ext"):
        for rec in data[tab].values():
            if rec.get("t"):
                rec["t"] = can(rec["t"])
            if rec.get("tm"):
                rec["tm"] = [can(x) for x in rec["tm"]]
            for f in ("ts",):
                if rec.get(f):
                    rec[f] = can(rec[f])
    for rec in data["cfbx"]["bugs"].values():
        rec["t"] = can(rec["t"])
        if rec.get("rt"):
            rec["rt"] = can(rec["rt"])
    data["cap"]["teams"] = [can(t) for t in data["cap"]["teams"]]
    data["cap"]["values"] = [can(v) for v in data["cap"]["values"]]                    # the Capitalize / Non Capitalize prefix still leads, so the page's rule is unchanged
    data["capPbi"]["values"] = [can(v) for v in data["capPbi"]["values"]]              # the class names and the Capitalize values the links name are rendered or sent to Jira as text
    data["capPbi"]["opts"] = [[can(v) for v in part] for part in data["capPbi"]["opts"]]
    for e in data["capEpics"]:
        e[4] = can(e[4])
    for tab in ("hier", "capList"):                                                    # a fix version the release train does not know is rendered too
        for rec in data[tab].values():
            if rec.get("fv") is not None:
                rec["fv"] = list(rec["fv"]) + [can("Unscheduled")]
    for rec in data["cfbx"]["bugs"].values():
        if rec.get("lk"):
            rec["lk"] = [can(k) for k in rec["lk"]]
    for k, rows in data["eb"].items():
        rows[0][1] = can("Blocked")
        rows[0][2] = can("P9")
    for k in list(data["ext"])[:2]:
        data["ext"][k]["ty"] = can("Spike")
    data["podRx"] = {p: rx + "|" + CANARY_A for p, rx in data["podRx"].items()}
    for e in data["epics"][:8]:                                                        # statuses outside every class render too
        if e["s"] != "Done":
            e["s"] = can("Blocked")
    for b in data["bugs"][:12]:
        if b["s"] not in ("Done", "Ready for Deploy", "Resolved"):
            b["s"] = can("Blocked")
    return data


def make(today: dt.date | None = None, seed: int = 20261030, canary: bool = False) -> dict:
    data = Gen(today or il_today(), seed).build()
    return canarify(data) if canary else data


def render_page(data: dict, template: Path = LIVE_TEMPLATE) -> str:
    """The same substitution as build_dashboard.render(): one placeholder, compact JSON, `</` escaped."""
    fragment = Path(template).read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    assert fragment.count("/*__DATA__*/null") == 1
    return fragment.replace("/*__DATA__*/null", payload)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("out", help="output file: .html renders the page, anything else writes the payload as JSON")
    ap.add_argument("--template", default=str(LIVE_TEMPLATE))
    ap.add_argument("--canary", action="store_true")
    ap.add_argument("--today", help="YYYY-MM-DD (default: today, Israel time)")
    a = ap.parse_args()
    data = make(dt.date.fromisoformat(a.today) if a.today else None, canary=a.canary)
    Path(a.out).write_text(render_page(data, Path(a.template)) if a.out.endswith(".html") else json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {a.out}: {len(data['epics'])} epics, {len(data['bugs'])} bugs, {data['cap']['rows'].count(';') + 1} capitalization rows, {data['capPbi']['rows'].count(';') + 1} Power BI scope rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
