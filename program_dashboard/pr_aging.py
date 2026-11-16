"""Open pull requests for the Needs Attention rule "Pull Requests Open More Than 3 Business Days".

One GraphQL search per Jira key (open, not draft, active in the last 14 days), paged by cursor. Nothing else is called: no REST search (its secondary rate limit trips after
about a dozen requests), no loop over repositories or people. The page does the ageing (business days, Israeli holidays) from the dates held here.

What is kept per pull request: repository, number, title, the day it became ready for review, the last activity day, the review state, the check state, the
Jira project keys found in its title, description or branch name and, once attach_releases has run, the releases (fix versions) of those issues or of their parent epics. No author and no reviewer is read or held (the dashboard holds no person).
The output lives in program_dashboard/build/, which is git-ignored: this repository is public and the titles are internal.

    python3 program_dashboard/pr_aging.py            # fetch and print the summary (needs NICE_GH_READ_TOKEN or GH_TOKEN, or a signed-in gh)
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

ORG = "nice-cxone"
ENDPOINT = "https://api.github.com/graphql"
PAGE = 20                               # with the review and check fields a page of 50 or more makes GitHub answer 502 (the check state alone takes 9 s at 50)
ACTIVE_DAYS = 14                        # owner decision, 2026-11-15: only a pull request with some activity (push, comment, review, label) in the last 14 days; the open ones nobody touched for longer are not waiting on anyone
SEARCH_CAP = 1000                       # a GitHub search returns at most 1,000 results: a larger window is split in two, never truncated
MIN_QUOTA = 300                         # stop cleanly under this many remaining GraphQL points (the hourly budget is 5,000; one page costs 1)
BOTS = {"dependabot", "renovate", "copilot", "github-actions"}          # login without the [bot] suffix
SKIP_LABELS = {"do-not-review", "wip"}                                  # a pull request carrying one of these is not waiting for a review
IL = ZoneInfo("Asia/Jerusalem")

FIELDS = """number title createdAt updatedAt isDraft reviewDecision headRefName bodyText
  author { __typename login }
  repository { name }
  latestReviews(first: 1) { totalCount }
  commits(last: 1) { nodes { commit { statusCheckRollup { state } } } }
  timelineItems(last: 1, itemTypes: [READY_FOR_REVIEW_EVENT]) { nodes { ... on ReadyForReviewEvent { createdAt } } }
  labels(first: 10) { nodes { name } }"""
QUERY = """query($q: String!, $after: String, $n: Int!) {
  rateLimit { cost remaining resetAt }
  search(query: $q, type: ISSUE, first: $n, after: $after) {
    issueCount
    pageInfo { hasNextPage endCursor }
    nodes { ... on PullRequest { %s } }
  }
}""" % FIELDS


class PrFeedError(Exception):
    """The pull request feed could not be read completely; the page then says so instead of showing an empty list."""


def token() -> str:
    """NICE_GH_READ_TOKEN (the read-only organisation token), else GH_TOKEN, else the signed-in gh CLI (a local run only)."""
    for name in ("NICE_GH_READ_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(name, "").strip():
            return os.environ[name].strip()
    gh = shutil.which("gh") or os.path.expanduser("~/bin/gh")
    try:
        out = subprocess.run([gh, "auth", "token"], capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception:
        out = ""
    if out:
        return out
    raise PrFeedError("no GitHub token (set NICE_GH_READ_TOKEN)")


def refusal(exc: urllib.error.HTTPError) -> tuple[str, int]:
    """GitHub's own reason for a refusal (its message, short) and how many seconds it asks us to wait (0 when it does not say): the Retry-After header of a secondary rate limit, or
    the time to the reset of an exhausted hourly limit. Nothing here can hold a token: only the message text GitHub sends back is read."""
    try:
        msg = str(json.loads(exc.read() or b"{}").get("message", ""))
    except (ValueError, AttributeError, OSError):
        msg = ""
    h = getattr(exc, "headers", None) or {}
    wait = 0
    ra = str(h.get("Retry-After", ""))
    reset = str(h.get("x-ratelimit-reset", ""))
    if ra.isdigit():
        wait = int(ra)
    elif str(h.get("x-ratelimit-remaining", "")) == "0" and reset.isdigit():
        wait = max(0, int(reset) - int(time.time())) + 2
    return " ".join(msg.split())[:80], wait


def gql(tok: str, variables: dict, post=None, sleep=time.sleep) -> dict:
    """One GraphQL call. A 502/503/504 (GitHub timing out on a heavy page) is retried up to three times with a growing pause and a smaller page. A 403/429 that asks for a short
    wait (a secondary rate limit: up to two minutes) is retried after that wait, at most three times; any other refusal is a PrFeedError at once, naming GitHub's own reason (rate limit,
    access ...) so the page can say why. A GraphQL error is a PrFeedError at once; nothing is retried in a loop."""
    variables = dict(variables)
    for attempt in range(4):
        body = json.dumps({"query": QUERY, "variables": variables}).encode()
        req = urllib.request.Request(ENDPOINT, data=body, headers={"Authorization": f"bearer {tok}", "Content-Type": "application/json", "User-Agent": "delivery-pulse"})
        try:
            with (post or urllib.request.urlopen)(req, timeout=60) as r:
                res = json.loads(r.read())
            break
        except urllib.error.HTTPError as exc:
            if exc.code in (502, 503, 504) and attempt < 3:
                sleep(5 * 3 ** attempt); variables["n"] = max(5, variables["n"] // 2); continue
            if exc.code in (403, 429):
                why, wait = refusal(exc)
                if 0 < wait <= 120 and attempt < 3:
                    sleep(wait); continue
                raise PrFeedError(f"GitHub answered {exc.code}" + (f": {why}" if why else "") + (f" (asks to wait {wait // 60} min)" if wait > 120 else "")) from None
            raise PrFeedError(f"GitHub answered {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt < 3:
                sleep(5 * 3 ** attempt); continue
            raise PrFeedError(f"GitHub not reachable ({type(exc).__name__})") from None
    if res.get("errors") and not res.get("data"):
        raise PrFeedError("GitHub query error: " + str(res["errors"][0].get("message", ""))[:100])
    return res["data"]


def day_il(ts: str | None) -> str | None:
    """The Israel-local date (YYYY-MM-DD) of a GitHub UTC timestamp."""
    if not ts:
        return None
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(IL).date().isoformat()


def key_regex(keys) -> re.Pattern:
    """A Jira key of one of the dashboard's projects: whole-word, so INT-5 does not match inside CXINT-5 and WFM-5 not inside CXWFM-5."""
    alt = "|".join(sorted((re.escape(k) for k in keys), key=len, reverse=True))
    return re.compile(rf"(?<![A-Za-z0-9])({alt})-\d+", re.I)


def is_bot(node: dict) -> bool:
    a = node.get("author") or {}
    login = (a.get("login") or "").lower()
    return a.get("__typename") == "Bot" or login.endswith("[bot]") or login in BOTS


def review_state(node: dict) -> str:
    """none (nobody has reviewed), commented, changes (changes requested), approved."""
    d = node.get("reviewDecision")
    if d == "APPROVED":
        return "approved"
    if d == "CHANGES_REQUESTED":
        return "changes"
    return "commented" if (node.get("latestReviews") or {}).get("totalCount") else "none"


def check_state(node: dict) -> str:
    """ok, fail, pend, or none when the last commit has no checks."""
    nodes = (node.get("commits") or {}).get("nodes") or []
    s = (((nodes[0] if nodes else {}).get("commit") or {}).get("statusCheckRollup") or {}).get("state")
    return {"SUCCESS": "ok", "FAILURE": "fail", "ERROR": "fail", "PENDING": "pend", "EXPECTED": "pend"}.get(s, "none")


def clock_start(node: dict) -> str:
    """The moment the wait began: the last time it was marked ready for review (a draft that became ready restarts the clock), else its creation."""
    ev = [x.get("createdAt") for x in (node.get("timelineItems") or {}).get("nodes") or [] if x and x.get("createdAt")]
    return day_il(ev[-1] if ev else node["createdAt"])


def reduce_nodes(nodes: list, keys, org: str = ORG) -> tuple[list, dict]:
    """Apply the exclusions, find the Jira keys and shape the compact records. Returns (records, counts); every dropped pull request is counted under its reason."""
    rx, out, cnt = key_regex(keys), [], {"drafts": 0, "bots": 0, "labelled": 0, "noKey": 0}
    canon = {k.upper(): k for k in keys}
    for n in nodes:
        if not n:
            continue
        if n.get("isDraft"):
            cnt["drafts"] += 1; continue
        if is_bot(n):
            cnt["bots"] += 1; continue
        if SKIP_LABELS & {(x.get("name") or "").lower() for x in (n.get("labels") or {}).get("nodes") or []}:
            cnt["labelled"] += 1; continue
        text = " ".join(filter(None, [n.get("title"), n.get("headRefName"), (n.get("bodyText") or "")[:3000]]))
        found = list(rx.finditer(text))
        pj = sorted({canon[m.group(1).upper()] for m in found})
        if not pj:
            cnt["noKey"] += 1; continue
        out.append({"r": n["repository"]["name"], "n": n["number"], "t": (n.get("title") or "")[:200], "ra": clock_start(n), "up": day_il(n.get("updatedAt")),
                    "rv": review_state(n), "ci": check_state(n), "pj": pj, "ik": sorted({m.group(0).upper() for m in found})})
    return out, cnt


def search_all(tok: str, query: str, sleep=time.sleep, post=None) -> tuple[list, int]:
    """Every pull request of one search, by cursor. Returns (nodes, issueCount GitHub reports). A window over the 1,000 cap is the caller's to split."""
    nodes, after, found = [], None, 0
    while True:
        d = gql(tok, {"q": query, "after": after, "n": PAGE}, post, sleep)
        rl = d["rateLimit"]
        if rl["remaining"] < MIN_QUOTA:
            raise PrFeedError(f"GitHub quota low ({rl['remaining']} left, resets {rl['resetAt']})")
        s = d["search"]
        found = s["issueCount"]
        nodes += [x for x in s["nodes"] if x]
        if not s["pageInfo"]["hasNextPage"]:
            return nodes, found
        after = s["pageInfo"]["endCursor"]
        sleep(0.3)


def fetch_nodes(tok: str, keys, org: str = ORG, post=None, sleep=time.sleep) -> tuple[list, int]:
    """The open, non-draft pull requests that mention one of the keys, from one search per key (the organisation has about 18,000 open pull requests, so a
    search of all of them is not an option). A search that is over the cap is split by creation date. Raises when the count GitHub reports for a search and the
    count received differ: a short list is never passed off as the whole list. Returns (nodes without duplicates, the sum of the counts GitHub reported; a pull request that names two keys is counted by both searches)."""
    seen, total_found = {}, 0
    def window(base: str, lo: dt.date, hi: dt.date) -> tuple[list, int]:
        q = f"{base} created:{lo.isoformat()}..{hi.isoformat()} sort:created-asc"
        total = gql(tok, {"q": q, "after": None, "n": 1}, post)["search"]["issueCount"]
        if total <= SEARCH_CAP or lo >= hi:
            nodes, found = search_all(tok, q, sleep, post)
            if len(nodes) != found:
                raise PrFeedError(f"GitHub reports {found} pull requests for one search, {len(nodes)} were received")
            return nodes, found
        mid = lo + (hi - lo) / 2
        a, fa = window(base, lo, mid); b, fb = window(base, mid + dt.timedelta(days=1), hi)
        return a + b, fa + fb
    for k in keys:
        since = (dt.datetime.now(IL).date() - dt.timedelta(days=ACTIVE_DAYS)).isoformat()
        nodes, found = window(f"org:{org} is:pr is:open draft:false updated:>={since} {k} in:title,body", dt.date(2015, 1, 1), dt.date.today() + dt.timedelta(days=1))
        total_found += found
        for n in nodes:
            seen[(n["repository"]["name"], n["number"])] = n
    return list(seen.values()), total_found


def release_lookup(search, keys: list, known: dict | None = None) -> tuple[dict, int]:
    """The releases (Jira fix versions) of each issue key: its own, plus those of its parent epic (a pull request usually names a story, task or bug, whose release is the
    epic's). `search(jql, fields)` is the Jira search; `known` maps an epic key to its releases when the page already holds it (saves a call). Returns ({key: set of releases},
    number of keys Jira did not know). A key Jira rejects (a typo in a title) never fails the lot: the chunk is split until the bad key stands alone."""
    rel, parent, bad = dict(known or {}), {}, set()
    rel = {k: set(v) for k, v in rel.items()}

    def read(batch: list, with_parent: bool) -> None:
        if not batch:
            return
        try:
            rows = search(f'key in ({", ".join(batch)})', ["fixVersions", "parent"])
        except Exception:
            if len(batch) == 1:
                bad.add(batch[0]); return
            mid = len(batch) // 2
            read(batch[:mid], with_parent); read(batch[mid:], with_parent); return
        for i in rows:
            f = i["fields"]
            rel[i["key"]] = {v["name"] for v in f.get("fixVersions") or []}
            pk = (f.get("parent") or {}).get("key")
            if pk and with_parent:
                parent[i["key"]] = pk

    todo = sorted({k for k in keys if k not in rel})
    for n in range(0, len(todo), 80):
        read(todo[n:n + 80], True)
    need = sorted({pk for pk in parent.values() if pk not in rel})
    for n in range(0, len(need), 80):
        read(need[n:n + 80], False)
    out = {k: set(rel.get(k, set())) | set(rel.get(parent.get(k), set())) for k in keys}
    unknown = len([k for k in keys if k not in rel])
    return out, unknown


def attach_releases(res: dict, search, known: dict | None = None) -> dict:
    """Adds `rl` (sorted releases of the issues a pull request names, or of their parent epics) to every record and drops the working field `ik`. The page keeps only the pull
    requests of the selected release. `unknownKeys` counts the keys Jira did not know; a pull request left with no release is never listed (it belongs to no release)."""
    recs = res.get("list") or []
    rel, unknown = release_lookup(search, sorted({k for x in recs for k in x.get("ik", [])}), known)
    for x in recs:
        x["rl"] = sorted(set().union(*[rel.get(k, set()) for k in x.get("ik", [])]))
        x.pop("ik", None)
    res["unknownKeys"] = unknown
    res["noRelease"] = sum(1 for x in recs if not x["rl"])
    return res


def collect(keys, tok: str | None = None, post=None, sleep=time.sleep) -> dict:
    """The payload section DATA.prs: the records, how many were found and dropped (so the page can show what it did not check), and when. On any failure the section
    carries `unavailable` instead of a list: the page then says the pull requests were not checked, never that nothing is waiting."""
    at = dt.datetime.now().astimezone().isoformat(timespec="minutes")
    try:
        nodes, found = fetch_nodes(tok or token(), keys, post=post, sleep=sleep)
        recs, cnt = reduce_nodes(nodes, keys)
        return {"org": ORG, "at": at, "activeDays": ACTIVE_DAYS, "found": len(nodes), "kept": len(recs), **cnt, "list": recs}
    except PrFeedError as exc:
        return {"org": ORG, "at": at, "unavailable": str(exc)[:120]}


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import build_dashboard as B
    res = collect(B.PROJECTS + B.PRODUCTS)
    print({k: v for k, v in res.items() if k != "list"})
    for r in sorted(res.get("list", []), key=lambda x: x["ra"])[:10]:
        print(r)
