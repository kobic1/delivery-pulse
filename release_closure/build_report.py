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
import statistics
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


def scope_keys(base, s, p, name, dev, excl_statuses):
    """Epics that were in release `name` at the end of W1, rebuilt from each epic's change history.

    JQL `fixVersion WAS ... ON` drops epics that a bulk edit removed and re-added in the same minute
    (they never left the release), which understated PMN's scope. Rules: created by the end of W1; in the
    release then (an edit that removes and re-adds it nets to still in; a first edit that only removes it
    means it was in from creation); not Removed then; not Removed or Stretch today."""
    cut = datetime.combine(dev + timedelta(days=6), datetime.max.time())
    cands = search(base, s, f'project = {p} AND issuetype = Epic AND fixVersion was "{name}"',
                   ["status", "customfield_10094", "fixVersions", "created"])

    def one(i):
        if datetime.strptime(i["fields"]["created"][:19], "%Y-%m-%dT%H:%M:%S") > cut:
            return None
        fv, st = [], []
        for h in histories(base, s, i["key"]):
            t = datetime.strptime(h["created"][:19], "%Y-%m-%dT%H:%M:%S")
            items = [x for x in h["items"] if x["field"] == "Fix Version" and name in (x.get("fromString"), x.get("toString"))]
            if items:
                added = any(x.get("toString") == name for x in items)
                removed = any(x.get("fromString") == name for x in items)
                fv.append((t, True if (added and removed) else not added, added or not removed))   # (time, in before, in after)
            st += [(t, x.get("fromString"), x.get("toString")) for x in h["items"] if x["field"] == "status"]
        fv.sort(key=lambda x: x[0])
        st.sort(key=lambda x: x[0])
        if not fv:
            was_in = any(v["name"] == name for v in i["fields"]["fixVersions"])
        else:
            before = [e for e in fv if e[0] <= cut]
            was_in = before[-1][2] if before else fv[0][1]
        b4 = [e for e in st if e[0] <= cut]
        status_then = b4[-1][2] if b4 else (st[0][1] if st else i["fields"]["status"]["name"])
        cur = i["fields"]["status"]["name"]
        stretch = (i["fields"].get("customfield_10094") or {}).get("value") == "Stretch"
        return i["key"] if (was_in and status_then not in excl_statuses and cur not in excl_statuses and not stretch) else None

    with ThreadPoolExecutor(8) as ex:
        return sorted(k for k in ex.map(one, cands) if k)


def release_windows(base, s, cfg):
    """{release: (start, end)} from the Jira version's own dates."""
    vers = {v["name"]: v for v in s.get(f"{base}/rest/api/3/project/{cfg['project']}/versions").json()}
    d = lambda x: datetime.strptime(x, "%Y-%m-%d").date()
    return {n: (d(vers[n]["startDate"]), d(vers[n]["releaseDate"])) for n in cfg["releases"]
            if n in vers and vers[n].get("startDate") and vers[n].get("releaseDate")}


def collect(cfg):
    base, s = session()
    p, wins = cfg["project"], release_windows(base, s, cfg)
    excl = ", ".join(f'"{x}"' for x in cfg["excluded_epic_statuses"])
    with_tests = cfg.get("test_coverage", True)
    tclause = (f'labels in ({", ".join(cfg["test_labels"])}) AND priority in ({", ".join(cfg["test_priorities"])})') if with_tests else ""
    bug_scope = (f'project = {p} AND issuetype = Bug AND priority in (P1, P2, P3) '
                 f'AND summary !~ "\\"[Accessibility]*\\"" {cfg.get("bug_exclusions", "")}')
    if not wins:
        return base, [], {}
    first_dev = min(w[0] for w in wins.values()) + timedelta(days=IP_DAYS)
    bugs = [(datetime.strptime(i["fields"]["created"][:10], "%Y-%m-%d").date(),
             datetime.strptime(i["fields"]["resolutiondate"][:10], "%Y-%m-%d").date() if i["fields"]["resolutiondate"] else None)
            for i in (search(base, s, bug_scope + f' AND (created >= "{first_dev}" OR resolution is EMPTY OR resolutiondate >= "{first_dev}")',
                            ["created", "resolutiondate"]) if cfg.get("bugs", True) else [])]
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
        if (end - dev).days != 7 * WEEKS - 1:
            print(f"WARNING {p} {name}: delivery window is {(end - dev).days + 1} days, not {7 * WEEKS}; W12 will not end on the release date", file=sys.stderr)
        sk = scope_keys(base, s, p, name, dev, set(cfg["excluded_epic_statuses"]))
        scope_jql = f'key in ({", ".join(sk)}) ORDER BY key' if 0 < len(sk) <= 120 else ""
        open_wk = []
        for w in range(1, WEEKS + 1):
            e = dev + timedelta(days=7 * w)
            open_wk.append(sum(1 for c, r in bugs if c < e and (r is None or r >= e)))
        row = {
            "name": name, "start": start, "dev_start": dev, "end": end, "weeks": WEEKS,
            "done": len(done), "done_jql": base_jql + " AND status = Done", "buckets": buckets,
            "baseline": len(sk), "baseline_jql": scope_jql,
            "cycle_vals": cyc,
            "cycle_avg": int(sum(cyc) / len(cyc) + 0.5) if cyc else None, "cycle_n": len(cyc),
            "cycle_med": int(statistics.median(cyc) + 0.5) if cyc else None,
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


def merge(cfg, per_project):
    """Combine per-project release rows into one row per release (sums, pooled cycle times)."""
    import re
    import statistics
    out = []
    for name in cfg["releases"]:
        rows = [(p, {r["name"]: r for r in rr}[name]) for p, rr in per_project.items() if name in {r["name"] for r in rr}]
        if not rows:
            continue
        projs = [p for p, _ in rows]
        first = rows[0][1]
        plist = "project in (" + ", ".join(projs) + ")"
        swap = lambda j: re.sub(r"project = \w+", plist, j, count=1)
        buckets = {k: sum(r["buckets"][k] for _, r in rows) for k in first["buckets"]}
        cyc = [v for _, r in rows for v in r["cycle_vals"]]
        out.append({
            "name": name, "start": first["start"], "dev_start": first["dev_start"], "end": first["end"], "weeks": WEEKS,
            "done": sum(r["done"] for _, r in rows), "done_jql": swap(first["done_jql"]), "buckets": buckets,
            "baseline": sum(r["baseline"] for _, r in rows), "baseline_jql": "",
            "cycle_vals": cyc, "cycle_avg": int(sum(cyc) / len(cyc) + 0.5) if cyc else None, "cycle_n": len(cyc),
            "cycle_med": int(statistics.median(cyc) + 0.5) if cyc else None,
            "bugs_weekly": [sum(r["bugs_weekly"][w] for _, r in rows) for w in range(WEEKS)],
            "bugs_end_jql": "", "projects": projs,
            "tests": 0, "auto": 0, "auto_weekly": [0] * WEEKS, "tests_jql": "", "auto_jql": "",
        })
    return out


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
    if cfg.get("projects"):
        cfg["test_coverage"] = False
        per_project, base = {}, None
        for spec in cfg["projects"]:
            sub = {k: v for k, v in cfg.items() if k != "projects"}
            sub.update(spec)
            sub["test_coverage"] = False
            base, rr, _ = collect(sub)
            per_project[spec["project"]] = rr
            print(f'{spec["project"]}: {[r["name"] for r in rr]}', file=sys.stderr)
        rel, overall = merge(cfg, per_project), {"tests": 0, "auto": 0, "tests_jql": "", "auto_jql": ""}
    else:
        base, rel, overall = collect(cfg)
    out = Path(a.out) if a.out else HERE / "build"
    out.mkdir(parents=True, exist_ok=True)
    stem = out / f'{cfg.get("slug", cfg["project"])}_release_closure'
    Path(f"{stem}_email.html").write_text(render_email(cfg, base, rel, overall), encoding="utf-8")
    Path(f"{stem}.json").write_text(json.dumps(
        {"releases": [{**r, "start": str(r["start"]), "dev_start": str(r["dev_start"]), "end": str(r["end"]),
                       "buckets": {str(k): v for k, v in r["buckets"].items()}} for r in rel], "overall": overall}, indent=1))
    print(f"{stem}_email.html")


if __name__ == "__main__":
    main()
