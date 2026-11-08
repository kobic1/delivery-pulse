#!/usr/bin/env python3
"""The red "Enable ... FTs" events of the R&D Release Management calendar (Confluence Team Calendars), read with the Jira API token: no browser.

The calendar on the Release Management page is a Team Calendars macro; its events live in the calendar service, not in the page. The service answers the same API token that reads Jira
(`GET /wiki/rest/calendar-services/1.0/calendar/events.json`). The macro's own id is a container with no events; the events belong to its sub-calendars, one per colour. The service has no call that
lists them, so the id of the red sub-calendar is configuration (FT_CALENDAR_SUBCALENDAR_ID): it is the `subCalendarId` every event of that colour carries.

    FT_CALENDAR_SUBCALENDAR_ID=... python3 ft_calendar.py [--from 2026-01-01] [--to 2027-12-31] [--json out.json]

Credentials come from the environment, as for the rest of the dashboard: JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN. Read only.

What is kept (the rule of the FT Enablement Calendar): a red event whose title, after the status tag, starts with "Enable" and names release 26.x or later; and, for 27.x and later, titles worded "27.1 FT Enablement on ...".
Status comes from the Confluence legend on the page: no tag = deployed, (APPR) approved by CAB, (r) change request ready for CAB, (TENT) tentative. "ON HOLD", "RESCHEDULING" and "ROLLED BACK" in front of the title become a flag.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys

RED = "#DE350B"
STATUS_TAG = re.compile(r"^\((appr|tent|r)\)\s*", re.I)
FLAG_TAG = re.compile(r"^(on hold|rescheduling|\*{3}[^*]+\*{3}|rolled back)[:\s-]*", re.I)
STATUSES = {"appr": "appr", "tent": "tent", "r": "ready"}
FLAGS = {"on hold": "hold", "rolled back": "rollback", "rescheduling": "rescheduling"}


def fetch_events(base_url: str, auth: tuple, sub_calendar_id: str, start: dt.date, end: dt.date, session=None, window_days: int = 120) -> list:
    """Raw events of one sub-calendar between two days, asked for in windows (the service answers a long range, but a window keeps each answer small); duplicates by id and start are dropped."""
    import requests
    s = session or requests.Session()
    seen, out = set(), []
    day = start
    while day <= end:
        to = min(end, day + dt.timedelta(days=window_days))
        r = s.get(f"{base_url.rstrip('/')}/wiki/rest/calendar-services/1.0/calendar/events.json", auth=auth, timeout=60,
                  params={"subCalendarId": sub_calendar_id, "userTimeZoneId": "Asia/Jerusalem", "start": f"{day.isoformat()}T00:00:00Z", "end": f"{to.isoformat()}T00:00:00Z"})
        r.raise_for_status()
        body = r.json()
        if not body.get("success"):
            raise RuntimeError("the calendar service did not answer success: " + str(body)[:200])
        for e in body.get("events", []):
            k = (e.get("id"), e.get("start"))
            if k not in seen:
                seen.add(k)
                out.append(e)
        day = to + dt.timedelta(days=1)
    return out


def split_title(raw: str) -> tuple:
    """(text, status, flag): the title without its leading status tags and flags. status is done, appr, ready or tent; flag is '' or hold, rollback, rescheduling."""
    t, status, flag = " ".join(str(raw).split()), "done", ""
    while True:
        m = STATUS_TAG.match(t)
        if m:
            status, t = STATUSES[m.group(1).lower()], t[m.end():]
            continue
        m = FLAG_TAG.match(t)
        if m:
            key = m.group(1).lower().strip("*").strip()
            flag, t = next((v for k, v in FLAGS.items() if key.startswith(k)), "note"), t[m.end():]
            continue
        return t, status, flag


CLUSTER_RX = re.compile(r"\b(?:(?:NA|EU|UK|AU|JP|JO|KR|CA|ZA|AE)\d|LO\d+|B\d+|M\d+|C\d+)\b")
BETA_RX = re.compile(r"^(?:LO|B|M)\d+$")


def clusters_of(target: str) -> list:
    """The clusters a target names, in order, once each (NA1, EU2, LO27, B2, M35, C28 ...). An alias in brackets (VA26) or a word (UKSov) is not a cluster."""
    return list(dict.fromkeys(m.group(0) for m in CLUSTER_RX.finditer(target)))


def regions_of(clusters: list) -> list:
    """The regions of those clusters: the letters of NA1, EU2, UK3 ... ; 'Beta' for the beta and lower environments (B2, B32, M35, LO26, LO27); 'C clusters' when the title names only C-numbered clusters
    (the title does not say which region they are in)."""
    out = []
    for c in clusters:
        r = "Beta" if BETA_RX.match(c) else None if re.match(r"^C\d+$", c) else c[:2]
        if r and r not in out:
            out.append(r)
    if not out and clusters:
        out.append("C clusters")
    return out


def parse_target(text: str) -> dict:
    """Release, target clusters, change number and note of an enablement title (text without tags)."""
    rel = re.search(r"(\d\d\.\d)", text)
    body = re.sub(r"^(Enable\s+)?(\d\d\.\d)\s+FT['’]?s?\s*(Enablement)?\s*", "", text, flags=re.I)
    body = re.sub(r"^(on for|on|to)\s+", "", body, flags=re.I)
    parts = re.split(r"\s*CHG\d+\s*", body, maxsplit=1)
    target, tail, note = parts[0].strip(" ,-"), (parts[1].strip() if len(parts) > 1 else ""), ""
    ex = re.search(r"\b(EXCEPT\b.*|\(except.*\)|\(include.*\))$", target)
    if ex:
        note, target = ex.group(1), target[:ex.start()].strip(" ,-")
    chg = re.search(r"CHG\d+", text)
    ks = clusters_of(target)
    return {"r": rel.group(1) if rel else "", "t": target, "c": chg.group(0) if chg else "", "n": (note + " " + tail).strip(), "k": ks, "g": regions_of(ks)}


def ft_events(raw_events: list, min_major: int = 26, ft_wording_from: int = 27, color: str = RED) -> list:
    """The FT enablement events, oldest first: [{d, s, f, r, t, c, n, k, g, raw}] (d the Israel day, s status, f flag, r release, t target, c change number, n note, k clusters, g regions, raw the title)."""
    out = []
    for e in raw_events:
        if (e.get("backgroundColor") or e.get("borderColor") or "").upper() != color.upper():
            continue
        text, status, flag = split_title(e.get("title", ""))
        rel = re.search(r"(\d\d)\.(\d)", text)
        if not rel:
            continue
        major = int(rel.group(1))
        enable = re.match(r"enable\b", text, re.I) and major >= min_major
        wording = re.match(r"\d\d\.\d FT enablement\b", text, re.I) and major >= ft_wording_from
        if not (enable or wording):
            continue
        out.append({"d": str(e["start"])[:10], "s": status, "f": flag, **parse_target(text), "raw": text})
    return sorted(out, key=lambda x: x["d"])


PLACEHOLDER = "/*__FT_EVENTS__*/null"


def load_payload(env=None, cache_path=None, today: dt.date | None = None, session=None) -> dict | None:
    """{"asOf": ISO time, "events": [...]} read now, or the last good copy kept in cache_path when the calendar cannot be read, or None when it is not configured and there is no copy.
    The read needs FT_CALENDAR_SUBCALENDAR_ID, JIRA_BASE_URL, JIRA_EMAIL and JIRA_API_TOKEN in env (default: the process environment). A failure is a warning, never an error: the calendar is an extra."""
    env = os.environ if env is None else env
    today = today or dt.date.today()
    sub, base, email, token = (str(env.get(k, "")).strip() for k in ("FT_CALENDAR_SUBCALENDAR_ID", "JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"))
    if sub and base and email and token:
        try:
            raw = fetch_events(base, (email, token), sub, dt.date(today.year, 1, 1), dt.date(today.year + 1, 12, 31), session=session)
            payload = {"asOf": dt.datetime.now().astimezone().isoformat(timespec="minutes"), "events": ft_events(raw)}
            if cache_path:
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False)
            return payload
        except Exception as exc:                                                       # noqa: BLE001
            print(f"warning: the FT enablement calendar could not be read ({type(exc).__name__}); using the last copy if there is one", file=sys.stderr)
    if cache_path and os.path.exists(cache_path):
        try:
            with open(cache_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
    return None


def inline_into(fragment: str, cache_path=None, payload: dict | None = ..., env=None) -> str:
    """Put the payload where the template has its one placeholder (a template without it is left as it is). payload: given (tests), or read by load_payload."""
    if PLACEHOLDER not in fragment:
        return fragment
    assert fragment.count(PLACEHOLDER) == 1
    if payload is ...:
        payload = load_payload(env, cache_path)
    return fragment.replace(PLACEHOLDER, json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="start", default="2026-01-01")
    ap.add_argument("--to", dest="end", default="2027-12-31")
    ap.add_argument("--json", help="write the events to this file")
    a = ap.parse_args(argv)
    sub = os.environ.get("FT_CALENDAR_SUBCALENDAR_ID")
    if not sub:
        print("FT_CALENDAR_SUBCALENDAR_ID is not set (the subCalendarId of the red events)", file=sys.stderr)
        return 2
    base, email, token = (os.environ.get(k, "").strip() for k in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"))
    raw = fetch_events(base, (email, token), sub, dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.end))
    ev = ft_events(raw)
    print(f"{len(raw)} red events read, {len(ev)} kept; releases: " + ", ".join(f"{r} {sum(1 for e in ev if e['r'] == r)}" for r in sorted({e['r'] for e in ev})))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(ev, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
