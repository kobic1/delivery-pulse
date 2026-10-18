"""Shared data model for the release planning report: Jira fetch, classification, stats."""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
from collections import OrderedDict
from datetime import date
from pathlib import Path

import requests
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
NO_TEAM = "No epic team"
UNASSIGNED_POD = "Unassigned pod"

CRITERIA = [("commitment", "Commitment type"), ("points", "Story points"),
            ("pod", "Pod label"), ("sprint", "Target sprint")]


# ---------------------------------------------------------------- Jira

def jira_session() -> tuple[str, requests.Session]:
    base = os.environ.get("JIRA_BASE_URL", "").rstrip("/")
    email, token = os.environ.get("JIRA_EMAIL", ""), os.environ.get("JIRA_API_TOKEN", "")
    if not (base and email and token):
        sys.exit("Set JIRA_BASE_URL, JIRA_EMAIL and JIRA_API_TOKEN.")
    s = requests.Session()
    s.auth = (email, token)
    return base, s


def fetch_epics(cfg: dict) -> list[dict]:
    base, s = jira_session()
    f = cfg["fields"]
    fields = ["summary", "status", "labels", "assignee", *f.values()]
    jql = f'project = {cfg["project"]} AND issuetype = Epic AND fixVersion = "{cfg["release"]}"'
    out, token = [], None
    while True:
        body = {"jql": jql, "fields": fields, "maxResults": 100}
        if token:
            body["nextPageToken"] = token
        r = s.post(f"{base}/rest/api/3/search/jql", json=body, timeout=60)
        r.raise_for_status()
        data = r.json()
        out += data["issues"]
        token = data.get("nextPageToken")
        if not token:
            break
    return [{"base": base, **i} for i in out]


# ---------------------------------------------------------------- model

def sprint_milestone(value: str | None, cfg: dict) -> str | None:
    """Milestone name if the sprint value is one of this release's planned sprints."""
    if not value:
        return None
    for name, nums in cfg["milestones"].items():
        for n in nums:
            if f'.{cfg["sprint_release_token"]}.{n} ' in value + " ":
                return name
    return None


def classify(issue: dict, cfg: dict) -> dict:
    f, fid = issue["fields"], cfg["fields"]
    status = f["status"]["name"]
    pod_re = re.compile(cfg["pod_label_regex"], re.I)
    pods = sorted(l for l in f.get("labels") or [] if pod_re.search(l))
    teams = [t["value"] for t in f.get(fid["epic_team"]) or []] or [NO_TEAM]
    ct = f.get(fid["commitment_type"])
    sprint = (f.get(fid["target_sprint"]) or {}).get("value")
    sp = f.get(fid["story_points"])
    done = status == "Done"
    ms = sprint_milestone(sprint, cfg)
    ok = {
        "commitment": done or bool(ct),
        "points": done or bool(sp),
        "pod": done or bool(pods),
        "sprint": done or ms is not None,
    }
    return {
        "base": issue["base"], "key": issue["key"], "url": f'{issue["base"]}/browse/{issue["key"]}',
        "summary": f.get("summary", ""), "status": status, "done": done,
        "teams": teams, "pods": pods, "milestone": ms, "ok": ok,
        "stale_sprint": bool(sprint) and ms is None,
        "full": all(ok.values()),
    }


def build_model(cfg: dict) -> list[dict]:
    epics = [classify(i, cfg) for i in fetch_epics(cfg)]
    return [e for e in epics if e["status"] not in cfg["excluded_statuses"]]


def stats(epics: list[dict]) -> dict:
    n = len(epics)
    pct = lambda c: round(100 * c / n) if n else 0
    s = {"n": n, "full": pct(sum(e["full"] for e in epics)), "full_n": sum(e["full"] for e in epics)}
    for key, _ in CRITERIA:
        s[key] = pct(sum(e["ok"][key] for e in epics))
    return s


def team_rows(epics: list[dict], team: str) -> list[dict]:
    """Pod rows under one team. Epics with no POD label go to 'Unassigned pod'."""
    mine = [e for e in epics if team in e["teams"]]
    by_pod: OrderedDict[str, list] = OrderedDict()   # keyed case-insensitively: 'Pod-X' and 'pod-x' are one pod
    shown: dict[str, str] = {}
    for e in mine:
        seen: set[str] = set()
        for p in e["pods"] or [UNASSIGNED_POD]:
            k = p.lower()
            shown.setdefault(k, p)
            if k not in seen:                    # an epic carrying both spellings still counts once
                seen.add(k)
                by_pod.setdefault(k, []).append(e)
    return sorted(({"name": shown[k], "es": es, **stats(es)} for k, es in by_pod.items()),
                  key=lambda r: (r["name"] == UNASSIGNED_POD, r["name"].lower()))


def jira_link(base: str, keys: list[str], text: str, color: str, underline: bool = True) -> str:
    """Link that opens exactly these epics in Jira's issue navigator."""
    if not keys:
        return text
    jql = f'key in ({",".join(keys)}) ORDER BY key'
    deco = "underline" if underline else "none"
    return (f'<a href="{base}/issues/?jql={quote(jql)}" style="color:{color};'
            f'text-decoration:{deco};">{text}</a>')


def keys_link(es: list[dict], text: str, color: str, underline: bool = True) -> str:
    return jira_link(es[0]["base"], [e["key"] for e in es], text, color, underline) if es else text
