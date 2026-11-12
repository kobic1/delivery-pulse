"""Which release of a non-CXone product is the running Major, the running Minor and the next Future one (rule v1).

The CXone projects share one release train (26.4, 27.1 ...) with dated Jira versions. EEM, WFM and ESP do not: their versions are named differently (9.4, 9.0, ESP27.1), some have no dates,
and some dated versions are overdue yet untouched. So the running release is chosen from the WORK in each version, and dates only break ties or raise a flag.

    resolve(project, rows, today, overrides)   a pure function: the same rows give the same answer (tested without Jira)
    collect_evidence(session, base, project)   reads the versions and five counts per candidate through the Jira REST API (read only)

Rule v1 (thresholds are assumptions to calibrate, kept as constants below):
  * candidates: unreleased, not archived, not a placeholder ("Future", "DO NOT CLONE", old "PI." names);
  * Major = two numeric segments (9.4, 27.1, ESP27.1); Minor = three or more (9.3.2.1, 8.1.10); anything else is ignored;
  * RUNNING = at least one open epic, at least 5 open issues, at least 3 updated in the last 14 days; a version with a recent update, fewer than 5 open issues and at least twice as many done as open is CLOSING OUT (a footnote, never running);
  * the running Major / Minor is the one with the most (open epics, open issues, recent updates); the dates only break an exact tie, nearest future release first;
  * Future = the next Major above the running one in version order, "starting" when an epic of it is already in progress;
  * confidence per tier: HIGH when the leader has at least twice the runner-up's open epics, MEDIUM from 1.2 times or when the dates contradict the work, LOW below that (a LOW tier asks for an override);
  * product_release_overrides.json can pin a tier (project -> {major|minor|future: version, reason, pinned_on, expires}); an expired pin is ignored with a warning.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import re
import urllib.request

RULE = "v1"
RUN_OPEN_EPICS, RUN_OPEN_ALL, RUN_RECENT = 1, 5, 3
HIGH_RATIO, MEDIUM_RATIO = 2.0, 1.2
PLACEHOLDER_RX = re.compile(r"future|do not clone", re.I)
OLD_PI_RX = re.compile(r"^PI\.")
NAME_RX = re.compile(r"^(?P<line>[A-Za-z_]*)(?P<nums>\d+(?:\.\d+)*)$")


def split_name(name: str) -> tuple[str, tuple[int, ...]] | None:
    """('ESP', (27, 1)) for ESP27.1; None for a name that is not a release number (ASC_2026Q1)."""
    m = NAME_RX.match(name.strip())
    return (m.group("line"), tuple(int(x) for x in m.group("nums").split("."))) if m else None


def tier_of(name: str) -> str | None:
    s = split_name(name)
    if not s or len(s[1]) < 2:
        return None
    return "major" if len(s[1]) == 2 else "minor"


def is_candidate(version: dict) -> bool:
    n = version["name"]
    return (not version.get("released") and not version.get("archived") and not PLACEHOLDER_RX.search(n) and not OLD_PI_RX.match(n) and tier_of(n) is not None)


def is_running(r: dict) -> bool:
    return r["open_epics"] >= RUN_OPEN_EPICS and r["open_all"] >= RUN_OPEN_ALL and r["recent"] >= RUN_RECENT


def is_closing_out(r: dict) -> bool:
    """Recently touched, almost nothing open, and most of its work already done (a brand-new version with three open issues is not closing out)."""
    done = (r["total"] or 0) - r["open_all"]
    return not is_running(r) and r["recent"] >= RUN_RECENT and r["open_all"] < RUN_OPEN_ALL and done >= max(r["open_all"], 1) * 2


def _days_to(date_s: str | None, today: dt.date) -> int | None:
    try:
        return (dt.date.fromisoformat(date_s[:10]) - today).days if date_s else None
    except ValueError:
        return None


def _rank(r: dict, today: dt.date) -> tuple:
    d = _days_to(r.get("release"), today)
    near = -d if d is not None and d >= 0 else float("-inf")       # a future release date wins an exact tie; an undated or past one does not
    return (r["open_epics"], r["open_all"], r["recent"], near)


def _confidence(leader: dict, others: list[dict], today: dt.date) -> str:
    d = _days_to(leader.get("release"), today)
    contradicts = d is not None and d < 0                          # a running version whose release date is already past
    if not others:
        return "MEDIUM" if contradicts else "HIGH"
    runner = max(others, key=lambda r: _rank(r, today))
    ratio = leader["open_epics"] / max(runner["open_epics"], 1)
    if ratio >= HIGH_RATIO:
        return "MEDIUM" if contradicts else "HIGH"
    return "MEDIUM" if ratio >= MEDIUM_RATIO else "LOW"


def _pick(rows: list[dict], today: dt.date) -> tuple[dict | None, str, list[dict]]:
    running = [r for r in rows if is_running(r)]
    if not running:
        return None, "NONE", []
    leader = max(running, key=lambda r: _rank(r, today))
    others = [r for r in running if r is not leader]
    return leader, _confidence(leader, others, today), others


def _ev(r: dict | None) -> dict | None:
    return None if r is None else {k: r.get(k) for k in ("name", "start", "release", "total", "open_all", "open_epics", "epics_in_progress", "recent")}


def default_release(rows: list[dict], today: dt.date) -> dict | None:
    """The release a multi-release product opens on: the unreleased version due soonest; with no dated version, the lowest version number."""
    dated = [r for r in rows if r.get("release") and (_days_to(r["release"], today) or 0) >= 0]
    if dated:
        return min(dated, key=lambda r: (_days_to(r["release"], today), split_name(r["name"])[1]))
    return min(rows, key=lambda r: split_name(r["name"])[1]) if rows else None


def resolve_all(project: str, rows: list[dict], today: dt.date) -> dict:
    """A product that ships many releases at once (every unreleased version is offered, one is the default). The record has the shape of resolve(): the default stands in as the major,
    and "releases" lists every version offered, oldest first. No work threshold applies: the reader picks the release."""
    warnings: list[str] = []
    cand = [dict(r, tier=tier_of(r["name"])) for r in rows]
    cand.sort(key=lambda r: split_name(r["name"])[1])
    d = default_release(cand, today)
    out = {"project": project, "rule": RULE, "mode": "all-unreleased", "asOf": today.isoformat(), "override": False, "warnings": warnings, "closingOut": [],
           "candidates": [_ev(r) | {"tier": r["tier"]} for r in cand], "releases": [r["name"] for r in cand],
           "major": None if d is None else {**_ev(d), "confidence": "DEFAULT"}, "minor": None, "future": None}
    if d is None:
        warnings.append(f"no unreleased version found for {project}")
    return out


def _override(overrides: dict, project: str, tier: str, today: dt.date, warnings: list) -> str | None:
    o = (overrides or {}).get(project, {}).get(tier)
    if not o:
        return None
    pin = o if isinstance(o, dict) else {"version": o}
    exp = pin.get("expires")
    if exp:
        try:
            if dt.date.fromisoformat(exp) < today:
                warnings.append(f"the pinned {tier} {pin.get('version')} expired on {exp} and is ignored")
                return None
        except ValueError:
            warnings.append(f"the pin for {tier} has an unreadable expiry date {exp!r} and is ignored")
            return None
    return pin.get("version")


def resolve(project: str, rows: list[dict], today: dt.date, overrides: dict | None = None) -> dict:
    """rows: one dict per candidate version with name, start, release, total, open_all, open_epics, epics_in_progress, recent. Returns the resolution record kept in the payload."""
    warnings: list[str] = []
    cand = [dict(r, tier=tier_of(r["name"])) for r in rows]
    majors = sorted((r for r in cand if r["tier"] == "major"), key=lambda r: split_name(r["name"])[1])
    minors = [r for r in cand if r["tier"] == "minor"]
    by_name = {r["name"]: r for r in cand}
    out = {"project": project, "rule": RULE, "asOf": today.isoformat(), "override": False, "warnings": warnings, "closingOut": [], "candidates": [_ev(r) | {"tier": r["tier"]} for r in cand]}

    pin = _override(overrides, project, "major", today, warnings)
    if pin and pin in by_name:
        major, conf = by_name[pin], "PINNED"
        out["override"] = True
    else:
        if pin:
            warnings.append(f"the pinned major {pin} is not an open version of {project} and is ignored")
        major, conf, _ = _pick(majors, today)
    out["major"] = None if major is None else {**_ev(major), "confidence": conf}

    pin = _override(overrides, project, "minor", today, warnings)
    if pin and pin in by_name:
        minor, mconf = by_name[pin], "PINNED"
        out["override"] = True
    else:
        minor, mconf, _ = _pick(minors, today)
    out["minor"] = None if minor is None else {**_ev(minor), "confidence": mconf}

    pin = _override(overrides, project, "future", today, warnings)
    future = None
    if pin and pin in by_name:
        future = by_name[pin]
        out["override"] = True
    elif major is not None:
        line, nums = split_name(major["name"])
        above = [r for r in majors if split_name(r["name"])[0] == line and split_name(r["name"])[1] > nums]
        future = above[0] if above else None
    if future is not None:
        out["future"] = {**_ev(future), "state": "starting" if (future["epics_in_progress"] or 0) > 0 else "planned"}
    else:
        out["future"] = None

    chosen = {r["name"] for r in (major, minor, future) if r}
    out["closingOut"] = [r["name"] for r in cand if is_closing_out(r) and r["name"] not in chosen]
    if major is not None and conf == "LOW":
        warnings.append(f"the Major {major['name']} leads by less than {MEDIUM_RATIO}x: pin it in product_release_overrides.json if it is wrong")
    if major is not None and (_days_to(major.get("release"), today) or 0) < 0 and conf != "PINNED":
        warnings.append(f"the release date of {major['name']} ({major.get('release')}) is already past")
    if major is None:
        warnings.append(f"no running Major found for {project}: nothing is shown until one is pinned or work starts")
    return out


# ---------------------------------------------------------------- the Jira reads (read only)
class Reader:
    """A read-only Jira REST reader over two callables, so the collector hands it its own authenticated session and a test hands it a fake: nothing here knows a token."""

    def __init__(self, get, post):
        self._get, self._post = get, post

    @classmethod
    def from_session(cls, session, base: str, timeout: int = 60):
        """A requests-style session (the collector's Jira session): get(url, timeout) and post(url, json, timeout), each answering .json()."""
        base = base.rstrip("/")
        return cls(lambda path: session.get(base + path, timeout=timeout).json(), lambda path, body: session.post(base + path, json=body, timeout=timeout).json())

    @classmethod
    def with_basic_auth(cls, base: str, email: str, token: str):
        """For a stand-alone script (python3 -I): stdlib only. The token stays inside the closure."""
        auth = "Basic " + base64.b64encode(f"{email}:{token}".encode()).decode()
        base = base.rstrip("/")

        def call(path, body=None):
            req = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(),
                                         headers={"Authorization": auth, "Accept": "application/json", "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        return cls(call, lambda path, body: call(path, body))

    def versions(self, project: str) -> list[dict]:
        return self._get(f"/rest/api/3/project/{project}/versions")

    def count(self, jql: str) -> int:
        return int(self._post("/rest/api/3/search/approximate-count", {"jql": jql}).get("count") or 0)


def collect_evidence(rd: Reader, project: str) -> list[dict]:
    rows = []
    for v in rd.versions(project):
        if not is_candidate(v):
            continue
        n = v["name"]
        base = f'project = {project} AND fixVersion = "{n}"'
        rows.append({"name": n, "start": v.get("startDate"), "release": v.get("releaseDate"),
                     "total": rd.count(base),
                     "open_all": rd.count(base + ' AND statusCategory != Done AND status != Resolved'),
                     "open_epics": rd.count(base + ' AND issuetype = Epic AND statusCategory != Done'),
                     "epics_in_progress": rd.count(base + ' AND issuetype = Epic AND statusCategory = "In Progress"'),
                     "recent": rd.count(base + ' AND updated >= -14d')})
    return rows
