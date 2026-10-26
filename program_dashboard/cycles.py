"""Delivery Cycle Governance: the collector behind the dashboard's "Delivery Cycle Governance" section.

Facts only: per delivery cycle and pod group, what is planned (due date in the cycle), what is done, what is overdue, flagged
or carried over. No verdict, no ranking, no score. Removed epics are excluded from every figure; "Done" is the status NAME.

Everything that identifies the program (pods page id, Epic Team names, cycle dates, pod labels, group names) is configuration or
is read from the pods page at build time. None of it is stored in the repository: the configuration is a git-ignored JSON file
(see cycles.config.example.json) and the pulled data goes to build/program_data.json, which is git-ignored as well.

    set -a; source .env; set +a
    python3 program_dashboard/build_dashboard.py --add-cycles       # pull this section only, then render
    python3 program_dashboard/build_dashboard.py                    # the full build includes it when the configuration exists
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_CONFIG = HERE / "cycles.config.json"
POD_CACHE = HERE / "build" / "cycles_pods_cache.json"
NOPOD = "_nopod"                                  # epics that match by Epic Team but carry no pod label from the pods page
FLAG_FIELD = "customfield_10021"                  # Flagged (Impediment)
CHUNK = 80
BUG_CLOSED = ("Done", "Closed", "Resolved", "Removed")      # a bug is open while its status is not one of these (the dashboard's status rule)


# ----------------------------------------------------------------------------- configuration

def config_path() -> Path:
    return Path(os.environ.get("CYCLES_CONFIG") or DEFAULT_CONFIG)


def load_config(path: Path | None = None) -> dict | None:
    """None when there is no configuration file (the section is then left out). A file that is present but wrong stops the build."""
    path = path or config_path()
    if not path.exists():
        return None
    cfg = json.loads(path.read_text(encoding="utf-8"))
    problems = []
    for k in ("confluence_page_id", "projects", "epic_team_field", "epic_teams", "cycles"):
        if not cfg.get(k):
            problems.append(f"missing {k}")
    for c in cfg.get("cycles") or []:
        try:
            dt.date.fromisoformat(c["start"])
            assert int(c["weeks"]) > 0
        except Exception:
            problems.append(f"cycle {c.get('id')}: start must be YYYY-MM-DD and weeks a positive number")
    if problems:
        raise SystemExit(f"cycles configuration {path.name} is not usable: " + "; ".join(problems))
    cfg.setdefault("stale_days", 30)
    cfg.setdefault("next_days", 7)
    return cfg


def cycle_list(cfg: dict) -> list[dict]:
    """End dates are derived from start + weeks, so the two can never disagree."""
    out = []
    for n, c in enumerate(cfg["cycles"], 1):
        start = dt.date.fromisoformat(c["start"])
        end = start + dt.timedelta(days=7 * int(c["weeks"]) - 1)
        out.append({"id": c["id"], "name": c.get("name") or f"Delivery Cycle {n}", "start": start.isoformat(), "end": end.isoformat()})
    return out


# ----------------------------------------------------------------------------- pods page (Confluence storage format)

class PodsPageError(Exception):
    pass


_BLOCK = {"p", "br", "li", "div", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol"}


class _Tables(HTMLParser):
    """Every table of a storage-format page as rows of cells; a cell is the list of its paragraphs (p, li, br and div start a new one)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self.stack = [], []

    def _cell(self):
        if self.stack and self.stack[-1]["rows"] and self.stack[-1]["rows"][-1]:
            return self.stack[-1]["rows"][-1][-1]
        return None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.stack.append({"rows": []})
        elif tag == "tr" and self.stack:
            self.stack[-1]["rows"].append([])
        elif tag in ("td", "th") and self.stack and self.stack[-1]["rows"]:
            a = dict(attrs)
            self.stack[-1]["rows"][-1].append({"parts": [""], "span": int(a.get("colspan") or 1) * int(a.get("rowspan") or 1)})
        elif tag in _BLOCK and self._cell() is not None:
            self._cell()["parts"].append("")

    def handle_endtag(self, tag):
        if tag == "table" and self.stack:
            self.tables.append(self.stack.pop())
        elif tag in ("p", "li", "div") and self._cell() is not None:
            self._cell()["parts"].append("")

    def handle_data(self, data):
        c = self._cell()
        if c is not None:
            c["parts"][-1] += data


def _pieces(cell) -> list[str]:
    return [p for p in (re.sub(r"\s+", " ", x).strip() for x in cell["parts"]) if p]


def slugify(name: str) -> str:
    """A stable id for a pod group, derived from its name (lower case letters, digits and hyphens), so a link survives a reordering of the pods page."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48] or "group"


POD_RANGE = re.compile(r"\bPods?\s*(\d+)(?:\s*[-\u2013]\s*(\d+))?", re.I)
LABEL_POD = re.compile(r"POD_?(\d+)$", re.I)


def parse_pods_page(storage: str) -> list[dict]:
    """Groups in page order: {id, name, leader, pods, labels: [{l, p}]}. The table is transposed (one column per pod group). Rows are
    found by the text of their first cell, never by position; anything that does not validate raises PodsPageError (no guessing)."""
    p = _Tables()
    p.feed(storage)
    p.close()
    table = None
    for t in p.tables:
        names = {" ".join(_pieces(r[0])).strip().rstrip(":").lower() for r in t["rows"] if r}
        if "gl" in names and "jira pod identification" in names:
            table = t
            break
    if table is None:
        raise PodsPageError("no table with the rows GL and Jira Pod Identification")
    rows = [r for r in table["rows"] if r]
    by_name = {" ".join(_pieces(r[0])).strip().rstrip(":").lower(): r for r in rows}
    head = next((r for r in rows if re.fullmatch(r"pods?", " ".join(_pieces(r[0])).strip().rstrip(":"), re.I)), rows[0])
    leader_row, label_row = by_name["gl"], by_name["jira pod identification"]
    if not (len(head) == len(leader_row) == len(label_row)):
        raise PodsPageError("the header, GL and Jira Pod Identification rows have different numbers of cells")
    if any(c["span"] > 1 for r in (head, leader_row, label_row) for c in r):
        raise PodsPageError("merged cells are not supported")
    groups, seen = [], {}
    for col in range(1, len(head)):
        pieces, labels = _pieces(head[col]), _pieces(label_row[col])
        if not pieces and not labels:
            continue                                               # an empty trailing column
        text = " ".join(pieces)
        m = POD_RANGE.search(text)
        if not m:
            raise PodsPageError(f"column {col}: no pod range in the header")
        lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
        if hi < lo:
            raise PodsPageError(f"column {col}: pod range runs backwards")
        rest = [POD_RANGE.sub("", x, count=1) if POD_RANGE.search(x) else x for x in pieces]
        name = re.sub(r"^[\s:\-\u2013]+|[\s:\-\u2013]+$", "", re.sub(r"\s+", " ", " ".join(x for x in rest if x.strip())))
        if not name:
            raise PodsPageError(f"column {col}: no group name in the header")
        if not labels:
            raise PodsPageError(f"group {len(groups) + 1}: no Jira label")
        items = []
        for lab in labels:
            if re.search(r"\s", lab):
                raise PodsPageError(f"group {len(groups) + 1}: a label contains a space")
            mm = LABEL_POD.search(lab)
            if not mm:
                raise PodsPageError(f"group {len(groups) + 1}: a label has no pod number")
            pod = int(mm.group(1))
            if not lo <= pod <= hi:
                raise PodsPageError(f"group {len(groups) + 1}: a label's pod number is outside the header range")
            if lab in seen:
                raise PodsPageError("a label appears in more than one place")
            seen[lab] = True
            items.append({"l": lab, "p": pod})
        gid, n = slugify(name), 2
        while gid in ("overview", "caps", NOPOD) or any(g["id"] == gid for g in groups):                  # two groups with the same name keep distinct ids
            gid, n = f"{slugify(name)}-{n}", n + 1
        groups.append({"id": gid, "name": name, "leader": " ".join(_pieces(leader_row[col])), "pods": list(range(lo, hi + 1)), "labels": items})
    if not groups:
        raise PodsPageError("no pod groups found")
    return groups


def read_pods(j, page_id: str, cache: Path = POD_CACHE, now: dt.datetime | None = None) -> dict:
    """Live read with validation; on any failure the last good read from the cache (with a visible warning), or no groups at all."""
    now = now or dt.datetime.now().astimezone()
    try:
        r = j.s.get(f"{j.base}/wiki/rest/api/content/{page_id}", params={"expand": "body.storage,version"}, timeout=60)
        r.raise_for_status()
        body = r.json()
        groups = parse_pods_page(body["body"]["storage"]["value"])
        got = {"groups": groups, "version": (body.get("version") or {}).get("number"), "when": (body.get("version") or {}).get("when"),
               "readAt": now.isoformat(timespec="minutes"), "source": "live", "warning": None}
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(got, ensure_ascii=False), encoding="utf-8")
        return got
    except Exception as exc:                                       # network, permission, shape of the page: never guess
        why = f"{type(exc).__name__}: {str(exc)[:140]}"
        if cache.exists():
            old = json.loads(cache.read_text(encoding="utf-8"))
            old.update({"source": "cache", "warning": f"The pods page could not be read on this build ({why}); the groups below are from the last good read."})
            return old
        return {"groups": [], "version": None, "when": None, "readAt": None, "source": "none",
                "warning": f"The pods page could not be read and there is no earlier read ({why}); pod groups are unavailable."}


# ----------------------------------------------------------------------------- scope and epics

def q(s) -> str:
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def jql_parts(cfg: dict, groups: list[dict]) -> dict:
    """base: every epic in scope (Removed excluded). scope: pod label from the page OR Epic Team in the configured list."""
    projects = ", ".join(q(p) for p in cfg["projects"])               # INT is a reserved JQL word: always quoted
    labels = [x["l"] for g in groups for x in g["labels"]]
    field = "cf[" + re.sub(r"\D", "", cfg["epic_team_field"]) + "]"
    ors = ([f"labels in ({', '.join(q(x) for x in labels)})"] if labels else []) + [f"{field} in ({', '.join(q(t) for t in cfg['epic_teams'])})"]
    return {"base": f"project in ({projects}) AND issuetype = Epic AND status != Removed", "scope": "(" + " OR ".join(ors) + ")",
            "labels": labels, "field": field, "projects": projects}


def assign(labels: list[str], groups: list[dict]) -> tuple[str, int, list[str]]:
    """(group id, pod, ids of every group the epic's labels point to). Page order decides when more than one group matches."""
    hit = []
    for gi, g in enumerate(groups):
        for x in g["labels"]:
            if x["l"] in labels:
                hit.append((gi, x["p"], g["id"]))
    if not hit:
        return NOPOD, 0, []
    hit.sort(key=lambda h: (h[0], h[1]))
    return hit[0][2], hit[0][1], sorted({h[2] for h in hit})


def mismatches(labels: list[str], teams: list[str], cfg: dict, groups: list[dict], group_ids: list[str]) -> list[dict]:
    """Facts shown on the epic, not a score. M1: a pod-style label that is not on the pods page. M2: pod labels of more than one
    group. M3: a pod label from the page but Epic Team empty or not in the configured list."""
    known = {x["l"] for g in groups for x in g["labels"]}
    out = []
    odd = sorted(x for x in labels if re.search(r"pod", x, re.I) and x not in known)
    if odd and groups:
        out.append({"c": "M1", "l": odd})
    if len(group_ids) > 1:
        out.append({"c": "M2", "l": group_ids})
    if group_ids and not any(t in cfg["epic_teams"] for t in teams):
        out.append({"c": "M3"})
    return out


def _val(x):
    if x is None:
        return None
    if isinstance(x, list):
        return [_val(i) for i in x if i is not None]
    if isinstance(x, dict):
        return x.get("value") or x.get("name")
    return x


def epic_record(i: dict, cfg: dict, groups: list[dict]) -> dict:
    f = i["fields"]
    labels = list(f.get("labels") or [])
    teams = [t for t in (_val(f.get(cfg["epic_team_field"])) or []) if t]
    gid, pod, gids = assign(labels, groups)
    par = f.get("parent")
    ptype = ((par or {}).get("fields") or {}).get("issuetype", {}).get("name") if par else None
    rec = {"k": i["key"], "t": f.get("summary") or "", "s": (f.get("status") or {}).get("name"),
           "due": f.get("duedate"), "rd": (f.get("resolutiondate") or "")[:10] or None,
           "as": (f.get("assignee") or {}).get("displayName"),
           "fl": bool(f.get(FLAG_FIELD)),
           "fv": [v["name"] for v in f.get("fixVersions") or []],
           "g": gid, "pod": pod, "tm": teams,
           "lb": [x for x in labels if re.search(r"pod", x, re.I)]}
    if par and ptype == "Capability":
        rec["cp"] = par["key"]
    elif par:
        rec["pt"] = ptype
    mm = mismatches(labels, teams, cfg, groups, gids)
    if mm:
        rec["mm"] = mm
    return rec


EPIC_FIELDS_BASE = ["summary", "status", "duedate", "assignee", "labels", "parent", "fixVersions", "resolutiondate", FLAG_FIELD]


def pull_epics(j, cfg: dict, groups: list[dict], cycles: list[dict]) -> list[dict]:
    parts = jql_parts(cfg, groups)
    fields = EPIC_FIELDS_BASE + [cfg["epic_team_field"]]
    seen: dict[str, dict] = {}

    def add(jql: str, note: str):
        got = j.search(jql, fields)
        print(f"cycles: {len(got):4d} {note}", flush=True)
        for i in got:
            seen.setdefault(i["key"], epic_record(i, cfg, groups))

    for c in cycles:
        add(f'{parts["base"]} AND {parts["scope"]} AND duedate >= "{c["start"]}" AND duedate <= "{c["end"]}"', f'epics due in {c["id"]}')
    add(f'{parts["base"]} AND {parts["scope"]} AND duedate < "{cycles[0]["start"]}" AND status != Done', "not done, due before the first cycle (carry-over)")
    add(f'{parts["base"]} AND {parts["scope"]} AND duedate is EMPTY AND status in ("In Progress", "Validation")', "active, no due date")
    return list(seen.values())


def pull_bugs(j, epics: list[dict]) -> None:
    """Bugs whose parent is the epic (type Bug exactly, Removed excluded). Open = status not Done, Closed, Resolved or Removed."""
    by = {e["k"]: e for e in epics}
    keys = sorted(by)
    total = 0
    for n in range(0, len(keys), CHUNK):
        jql = f'parent in ({", ".join(keys[n:n + CHUNK])}) AND issuetype = Bug AND status != Removed'
        for i in j.search(jql, ["summary", "status", "priority", "resolution", "parent"]):
            f = i["fields"]
            by[f["parent"]["key"]].setdefault("bugs", []).append(
                {"k": i["key"], "t": f.get("summary") or "", "s": (f.get("status") or {}).get("name"),
                 "pr": (f.get("priority") or {}).get("name"), "o": 0 if (f.get("status") or {}).get("name") in BUG_CLOSED else 1})
            total += 1
    print(f"cycles: {total} bugs under {sum(1 for e in epics if e.get('bugs'))} epics", flush=True)


def pull_capabilities(j, epics: list[dict], groups: list[dict]) -> tuple[list[dict], list[dict]]:
    """The parent Capabilities of the epics, the status of ALL their child epics (any team, any project), their Initiative."""
    caps_keys = sorted({e["cp"] for e in epics if e.get("cp")})
    no_cap = [{"k": e["k"], "pt": e.get("pt")} for e in epics if not e.get("cp")]
    cap = {}
    for n in range(0, len(caps_keys), CHUNK):
        for i in j.search(f'key in ({", ".join(caps_keys[n:n + CHUNK])})', ["summary", "status", "fixVersions", "parent"]):
            f = i["fields"]
            cap[i["key"]] = {"k": i["key"], "t": f.get("summary") or "", "s": (f.get("status") or {}).get("name"),
                             "fv": [v["name"] for v in f.get("fixVersions") or []], "_ip": (f.get("parent") or {}).get("key"),
                             "tot": 0, "dn": 0, "pn": 0, "tn": 0, "bn": 0}
    inits = {}
    want = sorted({c["_ip"] for c in cap.values() if c["_ip"]})
    for n in range(0, len(want), CHUNK):
        for i in j.search(f'key in ({", ".join(want[n:n + CHUNK])})', ["summary"]):
            inits[i["key"]] = i["fields"].get("summary") or ""
    for n in range(0, len(caps_keys), CHUNK):
        jql = f'parent in ({", ".join(caps_keys[n:n + CHUNK])}) AND issuetype = Epic AND status != Removed'
        for i in j.search(jql, ["status", "parent", FLAG_FIELD]):
            f = i["fields"]
            c = cap.get(f["parent"]["key"])
            if not c:
                continue
            s = (f.get("status") or {}).get("name")
            c["tot"] += 1
            c["dn"] += s == "Done"
            c["pn"] += s in ("In Progress", "Validation")
            c["tn"] += s not in ("Done", "In Progress", "Validation")
            c["bn"] += bool(f.get(FLAG_FIELD)) and s != "Done"
    order = {g["id"]: n for n, g in enumerate(groups)}
    order[NOPOD] = len(groups)
    out = []
    for k in caps_keys:
        c = cap.get(k)
        if not c:
            continue
        mine = [e for e in epics if e.get("cp") == k]
        c["init"] = {"k": c["_ip"], "t": inits.get(c["_ip"], "")} if c.get("_ip") else None
        del c["_ip"]
        c["sc"] = [e["k"] for e in mine]
        c["gs"] = sorted({e["g"] for e in mine}, key=order.get)
        out.append(c)
    print(f"cycles: {len(out)} capabilities, {len(no_cap)} epics without a parent Capability", flush=True)
    return out, no_cap


def pull_edct(j, epics: list[dict], as_of: dt.date, day_counts, epic_events) -> None:
    """EDCT by the dashboard's rule (the Efficiency chart's): days an epic ended in In Progress or Validation, flagged days excluded, the
    Done day not counted. Open epics count through the as-of day. Only In Progress, Validation and Done epics get a figure."""
    todo = [e for e in epics if e["s"] in ("In Progress", "Validation", "Done")]

    def work(e):
        try:
            events = epic_events(j.changelog(e["k"]))
            end = dt.date.fromisoformat(e["rd"]) if e["s"] == "Done" and e["rd"] else as_of
            return e["k"], day_counts(events, end)
        except Exception:
            return e["k"], None
    by = {e["k"]: e for e in epics}
    bad = 0
    with ThreadPoolExecutor(max_workers=6) as pool:
        for k, r in pool.map(work, todo):
            if r is None:
                bad += 1
                continue
            by[k]["ip"], by[k]["vl"] = r
            by[k]["edct"] = r[0] + r[1]
    print(f"cycles: cycle time read for {len(todo) - bad} epics ({bad} failed)", flush=True)


def israel_today(now: dt.datetime | None = None) -> dt.date:
    from zoneinfo import ZoneInfo
    return (now or dt.datetime.now(dt.timezone.utc)).astimezone(ZoneInfo("Asia/Jerusalem")).date()


def collect(j, cfg: dict, day_counts, epic_events, now: dt.datetime | None = None) -> dict:
    cycles = cycle_list(cfg)
    as_of = israel_today(now)
    pods = read_pods(j, str(cfg["confluence_page_id"]))
    groups = pods["groups"]
    epics = pull_epics(j, cfg, groups, cycles)
    pull_bugs(j, epics)
    caps, no_cap = pull_capabilities(j, epics, groups)
    pull_edct(j, epics, as_of, day_counts, epic_events)
    parts = jql_parts(cfg, groups)
    return {"asOf": as_of.isoformat(), "cycles": cycles, "stale": int(cfg["stale_days"]), "next": int(cfg["next_days"]),
            "page": {"version": pods["version"], "when": pods["when"], "readAt": pods["readAt"], "source": pods["source"], "warning": pods["warning"],
                     "id": str(cfg["confluence_page_id"]), "title": cfg.get("page_title")},
            "projects": list(cfg["projects"]), "groups": groups, "epics": epics, "caps": caps, "noCap": no_cap,
            "jql": {"base": parts["base"], "scope": parts["scope"]}, "title": cfg.get("report_name")}
