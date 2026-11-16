"""The pull request feed (program_dashboard/pr_aging.py): exclusions, Jira keys, the clock, paging, the 1,000 cap and every way the feed can fail.
Synthetic data only; GitHub is replaced by a fake `post` that answers like its GraphQL endpoint."""
import datetime as dt
import io
import json
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "program_dashboard"))
import pr_aging as P  # noqa: E402

KEYS = ["PMN", "CXCO", "CXSUP", "CXWFM", "CXINT", "INT", "WFM", "EEM", "ESP", "EMOB", "PMSTND"]


def node(n, title="PMN-1 change", repo="svc-a", created="2026-11-01T08:00:00Z", updated="2026-11-10T08:00:00Z", draft=False, body="", branch="", author="a-person", typename="User",
         labels=(), decision=None, reviews=0, ci="SUCCESS", ready=None):
    return {"number": n, "title": title, "createdAt": created, "updatedAt": updated, "isDraft": draft, "reviewDecision": decision, "headRefName": branch, "bodyText": body,
            "author": {"__typename": typename, "login": author}, "repository": {"name": repo}, "latestReviews": {"totalCount": reviews},
            "commits": {"nodes": [{"commit": {"statusCheckRollup": {"state": ci} if ci else None}}]},
            "timelineItems": {"nodes": [{"createdAt": x} for x in (ready or [])]}, "labels": {"nodes": [{"name": x} for x in labels]}}


def test_a_key_matches_as_a_whole_word_so_int_is_not_cxint_and_wfm_is_not_cxwfm():
    rx = P.key_regex(KEYS)
    found = lambda s: sorted({m.group(1).upper() for m in rx.finditer(s)})
    assert found("CXINT-12 fix") == ["CXINT"] and found("INT-12 fix") == ["INT"]
    assert found("CXWFM-5 and WFM-6") == ["CXWFM", "WFM"]
    assert found("pmn-77: lower case") == ["PMN"] and found("SHA-256 and PRINT-5") == []
    assert found("feature/PMSTND-9-thing") == ["PMSTND"]


def test_drafts_bots_and_labelled_pull_requests_are_counted_and_left_out_and_no_key_is_counted_apart():
    nodes = [node(1), node(2, draft=True), node(3, author="dependabot", typename="Bot"), node(4, author="renovate[bot]"), node(5, labels=["WIP"]), node(6, title="no key here"),
             node(7, title="plain", body="Jira: CXCO-99")]
    recs, cnt = P.reduce_nodes(nodes, KEYS)
    assert [r["n"] for r in recs] == [1, 7]
    assert cnt == {"drafts": 1, "bots": 2, "labelled": 1, "noKey": 1}
    assert recs[1]["pj"] == ["CXCO"], "the key in the description counts"


def test_the_branch_name_counts_as_a_place_for_the_key_and_two_projects_are_both_kept_sorted():
    recs, _ = P.reduce_nodes([node(1, title="tidy up", branch="feature/PMN-5-and-CXCO-6")], KEYS)
    assert recs[0]["pj"] == ["CXCO", "PMN"]


def test_the_clock_is_the_last_ready_for_review_event_else_creation_in_israel_time():
    plain = node(1, created="2026-11-01T22:30:00Z")             # 22:30 UTC is already the next day in Israel
    again = node(2, created="2026-10-01T08:00:00Z", ready=["2026-10-05T08:00:00Z", "2026-11-03T08:00:00Z"])
    recs, _ = P.reduce_nodes([plain, again], KEYS)
    assert recs[0]["ra"] == "2026-11-02" and recs[1]["ra"] == "2026-11-03"


def test_review_and_check_states_and_no_person_is_held():
    nodes = [node(1, decision="APPROVED", ci="SUCCESS"), node(2, decision="CHANGES_REQUESTED", ci="FAILURE"), node(3, reviews=1, ci="PENDING"), node(4, ci=None), node(5, ci="ERROR")]
    recs, _ = P.reduce_nodes(nodes, KEYS)
    assert [(r["rv"], r["ci"]) for r in recs] == [("approved", "ok"), ("changes", "fail"), ("commented", "pend"), ("none", "none"), ("none", "fail")]
    assert all(set(r) == {"r", "n", "t", "ra", "up", "rv", "ci", "pj", "ik"} for r in recs), "a record holds only these fields (ik is the working list of issue keys): no author, no reviewer"
    assert "a-person" not in json.dumps(recs)


class Fake:
    """GitHub's GraphQL endpoint: searches answer by query text from `table` {substring: [nodes]}; `fail` is a list of HTTP codes to answer first, or of (code, message, headers)."""
    def __init__(self, table, fail=(), remaining=4000, count_override=None):
        self.table, self.fail, self.remaining, self.calls, self.override = table, list(fail), remaining, [], count_override or {}

    def __call__(self, req, timeout=0):
        body = json.loads(req.data)
        if self.fail:
            f = self.fail.pop(0)
            code, msg, hdrs = f if isinstance(f, tuple) else (f, "", {})
            raise urllib.error.HTTPError("u", code, "x", hdrs, io.BytesIO(json.dumps({"message": msg}).encode() if msg else b""))
        v = body["variables"]; self.calls.append(v)
        nodes = next((x for k, x in self.table.items() if k in v["q"]), [])
        total = self.override.get(v["q"], len(nodes))
        start = int(v["after"]) if v["after"] else 0
        page = nodes[start:start + v["n"]]
        more = start + v["n"] < len(nodes)
        data = {"rateLimit": {"cost": 1, "remaining": self.remaining, "resetAt": "2026-11-15T12:00:00Z"},
                "search": {"issueCount": total, "pageInfo": {"hasNextPage": more, "endCursor": str(start + v["n"])}, "nodes": page}}
        return io.BytesIO(json.dumps({"data": data}).encode())


def test_every_page_is_read_and_a_pull_request_named_by_two_searches_is_kept_once():
    a = [node(i, title=f"PMN-{i}") for i in range(1, 46)]                    # three pages of 20
    b = [node(45, title="PMN-45 and CXCO-45"), node(100, title="CXCO-100")]
    fake = Fake({" PMN in:": a, " CXCO in:": b})
    nodes, found = P.fetch_nodes("t", ["PMN", "CXCO"], post=fake, sleep=lambda s: None)
    assert len(nodes) == 46 and found == 47


def test_a_search_over_the_cap_is_split_by_creation_date_never_cut():
    nodes = [node(i) for i in range(1, 11)]
    fake, windows = Fake({" PMN in:": nodes}), []
    def post(req, timeout=0):
        v = json.loads(req.data)["variables"]
        windows.append(v["q"].split("created:")[1].split(" ")[0])
        if len(windows) == 1:                                          # the first probe, over the whole period, claims one result too many
            return io.BytesIO(json.dumps({"data": {"rateLimit": {"cost": 1, "remaining": 4000, "resetAt": "x"}, "search": {"issueCount": 1001, "pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": []}}}).encode())
        return fake(req, timeout)
    got, found = P.fetch_nodes("t", ["PMN"], post=post, sleep=lambda s: None)
    first = windows[0]
    lo, hi = first.split("..")
    halves = {w for w in windows[1:] if w.startswith(lo + "..") or w.endswith(".." + hi)}
    assert len(halves) == 2 and first not in windows[1:], f"the window was not split in two: {windows}"
    assert len(got) == 10 and found == 20, "each half answers for itself: the fake returns the same ten twice, one copy of each is kept and the counts add up"
    assert {n["number"] for n in got} == set(range(1, 11))


def test_a_count_that_differs_from_what_was_received_is_an_error_not_a_short_list():
    nodes = [node(i) for i in range(1, 6)]
    q = None
    fake = Fake({" PMN in:": nodes})
    orig = fake.__call__
    def post(req, timeout=0):
        res = json.loads(orig(req, timeout).read())
        if req.data and json.loads(req.data)["variables"]["n"] != 1:
            res["data"]["search"]["issueCount"] = 9               # GitHub says 9, five arrive
        return io.BytesIO(json.dumps(res).encode())
    with pytest.raises(P.PrFeedError, match="reports 9"):
        P.fetch_nodes("t", ["PMN"], post=post, sleep=lambda s: None)


def test_a_timeout_from_github_is_retried_with_a_smaller_page_and_a_refusal_is_not():
    fake = Fake({" PMN in:": [node(i) for i in range(1, 6)]}, fail=[502, 504])
    d = P.gql("t", {"q": "x PMN in:title", "after": None, "n": 20}, fake, sleep=lambda s: None)
    assert fake.calls[0]["n"] == 5, "the page was halved twice (20, 10, 5)"
    assert d["search"]["issueCount"] == 5
    with pytest.raises(P.PrFeedError, match="403"):
        P.gql("t", {"q": "x", "after": None, "n": 20}, Fake({}, fail=[403]), sleep=lambda s: None)
    with pytest.raises(P.PrFeedError, match="502"):
        P.gql("t", {"q": "x", "after": None, "n": 20}, Fake({}, fail=[502, 502, 502, 502]), sleep=lambda s: None)


def test_a_low_quota_stops_the_read_cleanly():
    with pytest.raises(P.PrFeedError, match="quota low"):
        P.search_all("t", "q PMN", post=Fake({" PMN": [node(1)]}, remaining=10), sleep=lambda s: None)


def test_collect_says_why_when_it_cannot_read_and_never_returns_an_empty_list_for_it(monkeypatch):
    for name in ("NICE_GH_READ_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(P.shutil, "which", lambda x: None)
    monkeypatch.setattr(P.os.path, "expanduser", lambda x: "/nonexistent/gh")
    res = P.collect(KEYS)
    assert "list" not in res and res["unavailable"] == P.PUBLIC_REASON and "no GitHub token" not in json.dumps(res)
    res = P.collect(KEYS, tok="t", post=Fake({}, fail=[401]), sleep=lambda s: None)
    assert "list" not in res and res["unavailable"] == P.PUBLIC_REASON and "401" not in json.dumps(res)


def test_collect_returns_the_records_the_counts_and_the_activity_window():
    fake = Fake({" PMN in:": [node(1, title="PMN-1"), node(2, title="no key"), node(3, title="PMN-3", draft=True)]})
    res = P.collect(KEYS, tok="t", post=fake, sleep=lambda s: None)
    assert res["activeDays"] == 14 and res["kept"] == 1 and res["noKey"] == 1 and res["drafts"] == 1 and res["found"] == 3
    assert [r["n"] for r in res["list"]] == [1]
    assert all("updated:>=" in c["q"] for c in fake.calls), "every search carries the activity window"


def fake_jira(issues, reject=()):
    """A Jira search that answers `key in (...)` from a dict {key: (fix versions, parent)}; a key in `reject` makes the whole query fail, as Jira does for a key that does not exist."""
    calls = []

    def search(jql, fields):
        keys = [k.strip() for k in jql[jql.index("(") + 1:jql.rindex(")")].split(",")]
        calls.append(keys)
        if set(keys) & set(reject):
            raise RuntimeError("An issue with key does not exist")
        return [{"key": k, "fields": {"fixVersions": [{"name": v} for v in issues[k][0]], "parent": ({"key": issues[k][1]} if issues[k][1] else None)}} for k in keys if k in issues]
    search.calls = calls
    return search


def test_the_records_keep_the_full_issue_keys_found_in_title_body_and_branch():
    recs, _ = P.reduce_nodes([node(1, title="PMN-12 a", body="see cxco-7 and INT-3", branch="feature/PMN-12-x")], KEYS)
    assert recs[0]["ik"] == ["CXCO-7", "INT-3", "PMN-12"] and recs[0]["pj"] == ["CXCO", "INT", "PMN"]


def test_a_story_takes_the_release_of_its_epic_and_an_epic_its_own_and_both_are_counted():
    s = fake_jira({"PMN-1": ([], "PMN-9"), "PMN-9": (["27.1"], None), "PMN-2": (["26.4"], None), "PMN-3": ([], None)})
    rel, unknown = P.release_lookup(s, ["PMN-1", "PMN-2", "PMN-3"])
    assert rel == {"PMN-1": {"27.1"}, "PMN-2": {"26.4"}, "PMN-3": set()} and unknown == 0


def test_an_issue_with_its_own_release_and_an_epic_in_another_has_both():
    rel, _ = P.release_lookup(fake_jira({"PMN-1": (["27.2"], "PMN-9"), "PMN-9": (["27.1"], None)}), ["PMN-1"])
    assert rel["PMN-1"] == {"27.1", "27.2"}


def test_an_epic_the_page_already_holds_is_not_asked_for_again():
    s = fake_jira({"PMN-1": ([], "PMN-9")})
    rel, _ = P.release_lookup(s, ["PMN-1"], known={"PMN-9": ["27.1"]})
    assert rel["PMN-1"] == {"27.1"} and s.calls == [["PMN-1"]]


def test_a_key_jira_rejects_is_split_off_and_counted_without_losing_the_others():
    s = fake_jira({"PMN-1": (["27.1"], None), "PMN-3": (["27.2"], None)}, reject={"PMN-2"})
    rel, unknown = P.release_lookup(s, ["PMN-1", "PMN-2", "PMN-3"])
    assert rel["PMN-1"] == {"27.1"} and rel["PMN-3"] == {"27.2"} and rel["PMN-2"] == set() and unknown == 1


def test_attach_releases_sets_rl_drops_ik_and_counts_the_pull_requests_in_no_release():
    res = {"list": [{"n": 1, "ik": ["PMN-1", "PMN-2"]}, {"n": 2, "ik": ["PMN-3"]}, {"n": 3, "ik": ["PMN-4"]}]}
    s = fake_jira({"PMN-1": (["27.1"], None), "PMN-2": (["26.4"], None), "PMN-3": ([], None)})
    out = P.attach_releases(res, s)
    assert [x["rl"] for x in out["list"]] == [["26.4", "27.1"], [], []] and all("ik" not in x for x in out["list"])
    assert out["noRelease"] == 2 and out["unknownKeys"] == 1


def test_a_jira_failure_is_a_failure_of_the_lookup_the_collector_turns_into_a_notice(monkeypatch):
    def down(jql, fields):
        raise RuntimeError("jira down")
    rel, unknown = P.release_lookup(down, ["PMN-1", "PMN-2"])
    assert unknown == 2 and rel == {"PMN-1": set(), "PMN-2": set()}


@pytest.fixture(autouse=True)
def _no_waiting_left_over():
    P._waited[0] = 0
    yield
    P._waited[0] = 0


def test_a_refusal_names_githubs_own_reason_and_a_short_secondary_limit_wait_is_retried():
    q = {"q": "x", "after": None, "n": 20}
    with pytest.raises(P.PrFeedError, match=r"403: Resource not accessible by personal access token"):
        P.gql("t", q, Fake({}, fail=[(403, "Resource not accessible by personal access token", {})]), sleep=lambda s: None)
    slept = []
    ok = Fake({" PMN in:": [node(1)]}, fail=[(403, "You have exceeded a secondary rate limit.", {"Retry-After": "7"}), (403, "You have exceeded a secondary rate limit.", {"Retry-After": "9"})])
    d = P.gql("t", {"q": "x PMN in:title", "after": None, "n": 20}, ok, sleep=slept.append)
    assert slept == [7, 9] and d["search"]["issueCount"] == 1
    far = {"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(int(__import__("time").time()) + 1800)}
    with pytest.raises(P.PrFeedError, match=r"429: API rate limit exceeded for user ID \d+\. \(asks to wait 30 min\)"):
        P.gql("t", q, Fake({}, fail=[(429, "API rate limit exceeded for user ID 42.", far)]), sleep=lambda s: None)
    with pytest.raises(P.PrFeedError) as e:
        P.gql("t", q, Fake({}, fail=[(403, "x" * 500, {})]), sleep=lambda s: None)
    assert len(str(e.value)) < 120 and "ghp_" not in str(e.value)
    assert [s for s in slept] == [7, 9], "a refusal with no wait is never slept on"
    with pytest.raises(P.PrFeedError, match=r"^GitHub answered 403$"):
        P.gql("t", q, Fake({}, fail=[403]), sleep=slept.append)
    assert slept == [7, 9]


def test_the_reason_of_a_failed_read_goes_to_the_log_and_never_into_the_payload(capsys):
    res = P.collect(KEYS, tok="t", post=Fake({}, fail=[(403, "API rate limit exceeded for user ID 42.", {"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(int(__import__("time").time()) + 1800)})]), sleep=lambda s: None)
    assert res["unavailable"] == "the GitHub read failed" and "rate limit" not in json.dumps(res) and "403" not in json.dumps(res)
    out = capsys.readouterr().out
    assert "warning: pull requests not read: GitHub answered 403: API rate limit exceeded for user ID 42. (asks to wait 30 min)" in out


def test_a_secondary_limit_asking_five_minutes_is_waited_out_and_one_asking_longer_than_ten_is_not():
    msg = "You have exceeded a secondary rate limit."
    slept = []
    ok = Fake({" PMN in:": [node(1)]}, fail=[(403, msg, {"Retry-After": "300"})])
    d = P.gql("t", {"q": "x PMN in:title", "after": None, "n": 20}, ok, sleep=slept.append)
    assert slept == [300] and d["search"]["issueCount"] == 1
    P._waited[0] = 0
    with pytest.raises(P.PrFeedError, match=r"403: .* \(asks to wait 10 min\)$|403: .* \(asks to wait 11 min\)$"):
        P.gql("t", {"q": "x", "after": None, "n": 20}, Fake({}, fail=[(403, msg, {"Retry-After": "601"})]), sleep=slept.append)
    assert slept == [300], "a request for more than 10 minutes was slept on"


def test_all_the_waiting_of_one_read_is_capped_so_a_build_never_sits_idle_for_an_hour():
    msg = "You have exceeded a secondary rate limit."
    slept = []
    P._waited[0] = 0
    fail = [(403, msg, {"Retry-After": "500"}), (403, msg, {"Retry-After": "500"})]
    with pytest.raises(P.PrFeedError, match="403"):
        P.gql("t", {"q": "x", "after": None, "n": 20}, Fake({}, fail=fail), sleep=slept.append)
    assert slept == [500] and P._waited[0] == 500, "the second wait would have brought the read past 900 s in total"
    P.collect(KEYS, tok="t", post=Fake({}), sleep=lambda s: None)
    assert P._waited[0] == 0, "collect() starts every read with a fresh budget"
