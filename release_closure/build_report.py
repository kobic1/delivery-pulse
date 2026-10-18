"""Release Closure Summary: Throughput, Cycle time, Predictability, Test coverage and Gating bugs
backlog per release, built from Jira and rendered as an email.

A release runs from the Jira version's start date to its release date. Its first week is the IP
(innovation and planning) week; the delivery window is the 12 weeks (4 sprints) after it. W1 is the
first delivery week.

    set -a && source .env && set +a
    python3 release_closure/build_report.py --config config_pmn.json
Writes release_closure/build/<project>_release_closure_email.html. Nothing is sent.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "dashboards"))
import edct_from_jira as E  # noqa: E402  (EDCT: the cycle-time definition the dashboards already use)
from email_style import render_email  # noqa: E402

IP_DAYS = 7
WEEKS = 12


def session():
    base = os.environ.get("JIRA_BASE_URL", "").rstrip("/")
    email, token = os.environ.get("JIRA_EMAIL", ""), os.environ.get("JIRA_API_TOKEN", "")
    if not (base and email and token):
        sys.exit("Set JIRA_BASE_URL, JIRA_EMAIL and JIRA_API_TOKEN.")
    s = requests.Session()
    s.auth = (email, token)
    return base, s


def search(base, s, jql, fields):
    out, tok = [], None
    while True:
        body = {"jql": jql, "fields": fields, "maxResults": 100}
        if tok:
            body["nextPageToken"] = tok
        r = s.post(f"{base}/rest/api/3/search/jql", json=body, timeout=90)
        r.raise_for_status()
        d = r.json()
        out += d["issues"]
        tok = d.get("nextPageToken")
        if not tok:
            return out


def count(base, s, jql):
    r = s.post(f"{base}/rest/api/3/search/approximate-count", json={"jql": jql}, timeout=90)
    r.raise_for_status()
    return r.json()["count"]


def histories(base, s, key):
    out, start = [], 0
    while True:
        r = s.get(f"{base}/rest/api/3/issue/{key}/changelog", params={"startAt": start, "maxResults": 100}, timeout=90)
        r.raise_for_status()
        d = r.json()
        out += d["values"]
        start += len(d["values"])
        if d.get("isLast", True) or not d["values"]:
            return out


def epic_facts(base, s, key, category):
    """(done date, cycle-time days or None). Done date = last move into Done."""
    hs = histories(base, s, key)
    last = None
    for h in hs:
        for i in h["items"]:
            if i["field"] == "status" and i["toString"] == "Done":
                last = h["created"]
    if not last:
        return None, None
    done = datetime.strptime(last[:10], "%Y-%m-%d").date()
    if category == E.EXCLUDED_CATEGORY:
        return done, None
    return done, E.edct_days(E.epic_events(hs), end=done)


def release_windows(base, s, cfg):
    """{release: (start, end)} from the Jira version's own dates."""
    vers = {v["name"]: v for v in s.get(f"{base}/rest/api/3/project/{cfg['project']}/versions").json()}
    d = lambda x: datetime.strptime(x, "%Y-%m-%d").date()
    return {n: (d(vers[n]["startDate"]), d(vers[n]["releaseDate"])) for n in cfg["releases"]}


def collect(cfg):
    base, s = session()
    p, wins = cfg["project"], release_windows(base, s, cfg)
    excl = ", ".join(f'"{x}"' for x in cfg["excluded_epic_statuses"])
    with_tests = cfg.get("test_coverage", True)
    tclause = (f'labels in ({", ".join(cfg["test_labels"])}) AND priority in ({", ".join(cfg["test_priorities"])})') if with_tests else ""
    bug_scope = (f'project = {p} AND issuetype = Bug AND priority in (P1, P2, P3) '
                 f'AND summary !~ "\\"[Accessibility]*\\"" {cfg.get("bug_exclusions", "")}')
    first_dev = min(w[0] for w in wins.values()) + timedelta(days=IP_DAYS)
    bugs = [(datetime.strptime(i["fields"]["created"][:10], "%Y-%m-%d").date(),
             datetime.strptime(i["fields"]["resolutiondate"][:10], "%Y-%m-%d").date() if i["fields"]["resolutiondate"] else None)
            for i in search(base, s, bug_scope + f' AND (created >= "{first_dev}" OR resolution is EMPTY OR resolutiondate >= "{first_dev}")',
                            ["created", "resolutiondate"])]
    rel = []
    for name, (start, end) in wins.items():
        dev = start + timedelta(days=IP_DAYS)
        w1_end = dev + timedelta(days=6)
        base_jql = f'project = {p} AND issuetype = Epic AND fixVersion = "{name}"'
        epics = search(base, s, base_jql + f" AND status not in ({excl})", ["status", E.CF_ISSUE_CATEGORY])
        done = [(e["key"], (e["fields"].get(E.CF_ISSUE_CATEGORY) or {}).get("value")) for e in epics if e["fields"]["status"]["name"] == "Done"]
        with ThreadPoolExecutor(8) as ex:
            facts = list(ex.map(lambda kc: epic_facts(base, s, *kc), done))
        buckets = {"pre": 0, "post": 0, **{w: 0 for w in range(1, WEEKS + 1)}}
        for dd, _ in facts:
            if dd is None or dd < dev:
                buckets["pre"] += 1
            elif dd > end:
                buckets["post"] += 1
            else:
                buckets[min(WEEKS, (dd - dev).days // 7 + 1)] += 1
        cyc = [c for _, c in facts if c is not None]
        scope_jql = (f'project = {p} AND issuetype = Epic AND fixVersion WAS "{name}" ON "{w1_end}" '
                     f'AND NOT status WAS Removed ON "{w1_end}" AND status != Removed '
                     f'AND (cf[10094] is EMPTY OR cf[10094] != Stretch)')
        open_wk = []
        for w in range(1, WEEKS + 1):
            e = dev + timedelta(days=7 * w)
            open_wk.append(sum(1 for c, r in bugs if c < e and (r is None or r >= e)))
        row = {
            "name": name, "start": start, "dev_start": dev, "end": end, "weeks": WEEKS,
            "done": len(done), "done_jql": base_jql + " AND status = Done", "buckets": buckets,
            "baseline": count(base, s, scope_jql), "baseline_jql": scope_jql,
            "cycle_avg": round(sum(cyc) / len(cyc)) if cyc else None, "cycle_n": len(cyc),
            "cycle_med": round(sorted(cyc)[len(cyc) // 2] if len(cyc) % 2 else sum(sorted(cyc)[len(cyc) // 2 - 1:len(cyc) // 2 + 1]) / 2) if cyc else None,
            "bugs_weekly": open_wk,
            "bugs_end_jql": bug_scope + f' AND created < "{dev + timedelta(days=7 * WEEKS)}" AND (resolutiondate is EMPTY OR resolutiondate >= "{dev + timedelta(days=7 * WEEKS)}")',
            "tests": 0, "auto": 0, "auto_weekly": [0] * WEEKS, "tests_jql": "", "auto_jql": "",
        }
        if with_tests:
            tj = f'project = {p} AND issuetype = Test AND fixVersion = "{name}" AND {tclause}'
            aj = tj + " AND " + cfg["automated_clause"]
            tests = search(base, s, tj, ["customfield_10111", "customfield_10064"])
            cum, base_n = [0] * WEEKS, 0
            for x in tests:
                f = x["fields"]
                if (f["customfield_10111"] or {}).get("value") != "Yes" or not f["customfield_10064"]:
                    continue
                dd = datetime.strptime(f["customfield_10064"][:10], "%Y-%m-%d").date()
                if dd < dev:
                    base_n += 1
                elif dd <= end:
                    cum[min(WEEKS, (dd - dev).days // 7 + 1) - 1] += 1
            acc, run = base_n, []
            for w in range(WEEKS):
                acc += cum[w]
                run.append(acc)
            row.update(tests=len(tests), auto=count(base, s, aj), auto_weekly=run, tests_jql=tj, auto_jql=aj)
        rel.append(row)
    overall = {"tests": 0, "auto": 0, "tests_jql": "", "auto_jql": ""}
    if with_tests:
        allj = f"project = {p} AND issuetype = Test AND {tclause}"
        aj = allj + " AND " + cfg["automated_clause"]
        overall = {"tests": count(base, s, allj), "auto": count(base, s, aj), "tests_jql": allj, "auto_jql": aj}
    return base, rel, overall


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--out")
    a = ap.parse_args()
    cfg = json.loads((HERE / a.config).read_text())
    if cfg.get("sonarqube_file"):   # monthly SonarQube figures live in a gitignored local file (public repo)
        sq_path = HERE / cfg["sonarqube_file"]
        if sq_path.exists():
            cfg["sonarqube"] = json.loads(sq_path.read_text())
        else:
            print(f"note: {sq_path.name} not found, skipping the code coverage section")
    base, rel, overall = collect(cfg)
    out = Path(a.out) if a.out else HERE / "build"
    out.mkdir(parents=True, exist_ok=True)
    stem = out / f'{cfg["project"]}_release_closure'
    Path(f"{stem}_email.html").write_text(render_email(cfg, base, rel, overall), encoding="utf-8")
    Path(f"{stem}.json").write_text(json.dumps(
        {"releases": [{**r, "start": str(r["start"]), "dev_start": str(r["dev_start"]), "end": str(r["end"]),
                       "buckets": {str(k): v for k, v in r["buckets"].items()}} for r in rel], "overall": overall}, indent=1))
    print(f"{stem}_email.html")


if __name__ == "__main__":
    main()
