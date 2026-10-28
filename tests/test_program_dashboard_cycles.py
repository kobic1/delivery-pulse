"""Delivery Cycle Governance collector: synthetic fixtures only (fictitious pods page, labels, teams and dates)."""
import datetime as dt
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent / "program_dashboard"
sys.path.insert(0, str(HERE))
import cycles as CY  # noqa: E402

PAGE = """
<table><tbody>
<tr><th><p>PODs</p></th>
    <th><p>Pod 1 - 3<br />Alpha Group &amp; Co</p></th>
    <th><p>Pod 1:</p><p>Beta Group</p></th>
    <th><p>Pod 2-3: Gamma &lt;5-Min Group</p></th></tr>
<tr><th>GL</th><td><p>Leader A</p></td><td><p>Leader B</p></td><td><p>Leader C</p></td></tr>
<tr><th>Jira Pod Identification</th>
    <td><p>ALP-POD1</p><p>ALP-POD2</p><p>ALP-POD3</p></td>
    <td><p>BETA_POD_1</p></td>
    <td><p>GAM-R&amp;D-POD2</p><p>GAM-POD3</p></td></tr>
<tr><th>Members</th><td><p>First</p></td><td></td><td></td></tr>
</tbody></table>"""


def test_parse_page_variants():
    g = CY.parse_pods_page(PAGE)
    assert [x["id"] for x in g] == ["alpha-group-co", "beta-group", "gamma-5-min-group"]
    assert [x["name"] for x in g] == ["Alpha Group & Co", "Beta Group", "Gamma <5-Min Group"]
    assert [x["pods"] for x in g] == [[1, 2, 3], [1], [2, 3]]
    assert [x["leader"] for x in g] == ["Leader A", "Leader B", "Leader C"]
    assert [(x["l"], x["p"]) for x in g[2]["labels"]] == [("GAM-R&D-POD2", 2), ("GAM-POD3", 3)]


def test_parse_finds_rows_by_header_text_not_position():
    shuffled = PAGE.replace("<tr><th>GL</th>", "<tr><th>Notes</th><td>x</td><td>y</td><td>z</td></tr><tr><th>GL</th>")
    assert len(CY.parse_pods_page(shuffled)) == 3


@pytest.mark.parametrize("bad", [
    PAGE.replace("ALP-POD3", "ALP-POD9"),                          # pod number outside the header range
    PAGE.replace("GAM-POD3", "ALP-POD1"),                          # one label in two groups
    PAGE.replace("<p>BETA_POD_1</p>", ""),                         # a group without a label
    PAGE.replace("ALP-POD2", "ALP POD2"),                          # a space in a label
    PAGE.replace("Pod 1 - 3", "Alpha"),                            # no pod range
    "<table><tr><td>nothing here</td></tr></table>",               # no pods table at all
    PAGE.replace("<td><p>Leader B</p></td>", ""),                  # uneven row
])
def test_parse_fails_loudly(bad):
    with pytest.raises(CY.PodsPageError):
        CY.parse_pods_page(bad)


GROUPS = CY.parse_pods_page(PAGE)
CFG = {"projects": ["INT", "BETA"], "epic_team_field": "customfield_10040", "epic_teams": ["Team A", "Team B"], "confluence_page_id": "1",
       "cycles": [{"id": "DC1", "start": "2030-01-02", "weeks": 7}, {"id": "DC2", "start": "2030-02-20", "weeks": 6}]}


def test_cycle_ends_are_derived_from_start_and_weeks():
    c = CY.cycle_list(CFG)
    assert (c[0]["start"], c[0]["end"]) == ("2030-01-02", "2030-02-19")
    assert (c[1]["start"], c[1]["end"]) == ("2030-02-20", "2030-04-02")


def test_jql_quotes_reserved_words_and_keeps_unlabelled_epics():
    p = CY.jql_parts(CFG, GROUPS)
    assert 'project in ("INT", "BETA")' in p["base"] and "status != Removed" in p["base"]
    assert p["scope"].startswith('(labels in ("ALP-POD1"') and 'cf[10040] in ("Team A", "Team B")' in p["scope"]
    assert "NOT" not in p["scope"] and " OR " in p["scope"]
    assert CY.q('a"b') == '"a\\"b"'


def test_scope_without_a_pods_page_falls_back_to_team_only():
    p = CY.jql_parts(CFG, [])
    assert p["scope"] == '(cf[10040] in ("Team A", "Team B"))'


def test_assignment_and_mismatch_facts():
    assert CY.assign(["ALP-POD2"], GROUPS)[:2] == ("alpha-group-co", 2)
    assert CY.assign(["x"], GROUPS) == (CY.NOPOD, 0, [])
    gid, pod, gids = CY.assign(["GAM-POD3", "BETA_POD_1"], GROUPS)          # two groups: page order decides, M2 is raised
    assert (gid, pod, gids) == ("beta-group", 1, ["beta-group", "gamma-5-min-group"])
    assert [m["c"] for m in CY.mismatches(["BETA_POD_1", "GAM-POD3"], ["Team A"], CFG, GROUPS, gids)] == ["M2"]
    assert [m["c"] for m in CY.mismatches(["ALP-POD1"], [], CFG, GROUPS, ["alpha-group-co"])] == ["M3"]
    assert CY.mismatches(["OTHER-POD9"], ["Team A"], CFG, GROUPS, []) == [{"c": "M1", "l": ["OTHER-POD9"]}]
    assert CY.mismatches(["ALP-POD1"], ["Team A"], CFG, GROUPS, ["alpha-group-co"]) == []


class FakeJira:
    base = "https://example.invalid"

    def __init__(self, status=200, body=None):
        self.status, self.body = status, body

        class S:
            def get(s, url, params=None, timeout=0):
                class R:
                    status_code = status

                    def raise_for_status(r):
                        if status != 200:
                            raise RuntimeError(f"HTTP {status}")

                    def json(r):
                        return body
                return R()
        self.s = S()


def test_read_pods_caches_then_falls_back(tmp_path):
    cache = tmp_path / "cache.json"
    body = {"body": {"storage": {"value": PAGE}}, "version": {"number": 4, "when": "2030-01-01T00:00:00Z"}}
    live = CY.read_pods(FakeJira(200, body), "1", cache, dt.datetime(2030, 1, 3, 9, 0, tzinfo=dt.timezone.utc))
    assert live["source"] == "live" and live["version"] == 4 and len(live["groups"]) == 3 and cache.exists()
    down = CY.read_pods(FakeJira(500), "1", cache)
    assert down["source"] == "cache" and down["version"] == 4 and "last good read" in down["warning"]
    broken = CY.read_pods(FakeJira(200, {"body": {"storage": {"value": "<p>reshaped</p>"}}}), "1", cache)
    assert broken["source"] == "cache" and broken["warning"]
    none = CY.read_pods(FakeJira(500), "1", tmp_path / "missing.json")
    assert none["source"] == "none" and none["groups"] == [] and "unavailable" in none["warning"]


def test_config_missing_and_invalid(tmp_path):
    assert CY.load_config(tmp_path / "nope.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"projects": ["A"]}))
    with pytest.raises(SystemExit):
        CY.load_config(bad)
    ok = tmp_path / "ok.json"
    ok.write_text(json.dumps(CFG))
    assert CY.load_config(ok)["stale_days"] == 30


def test_israel_today_is_not_the_utc_date():
    late = dt.datetime(2030, 1, 5, 22, 30, tzinfo=dt.timezone.utc)             # 00:30 on the 6th in Israel
    assert CY.israel_today(late) == dt.date(2030, 1, 6)


def epic(key, status, due, labels=(), teams=(), parent=None, flagged=False, assignee="Person X"):
    f = {"summary": f"Summary {key}", "status": {"name": status}, "duedate": due, "assignee": {"displayName": assignee},
         "labels": list(labels), "fixVersions": [], "resolutiondate": "2030-01-10T10:00:00.000+0200" if status == "Done" else None,
         "customfield_10040": [{"value": t} for t in teams], CY.FLAG_FIELD: [{"value": "Impediment"}] if flagged else None}
    if parent:
        f["parent"] = {"key": parent[0], "fields": {"issuetype": {"name": parent[1]}}}
    return {"key": key, "fields": f}


def test_epic_record_fields():
    r = CY.epic_record(epic("ALP-1", "In Progress", "2030-01-20", ["ALP-POD2", "misc"], ["Team A"], ("CAP-1", "Capability"), True), CFG, GROUPS)
    assert (r["g"], r["pod"], r["cp"], r["fl"], r["lb"]) == ("alpha-group-co", 2, "CAP-1", True, ["ALP-POD2"]) and "mm" not in r
    n = CY.epic_record(epic("ALP-2", "New", None, [], ["Team B"], ("INI-1", "Initiative")), CFG, GROUPS)
    assert (n["g"], n["pod"], n.get("cp"), n["pt"]) == (CY.NOPOD, 0, None, "Initiative")


# ---- Open CFBs: root cause analysis flags (synthetic texts only)
import build_dashboard as BD  # noqa: E402


def test_plain_text_reads_strings_and_atlassian_document_format():
    adf = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "First line"}]},
                                        {"type": "paragraph", "content": [{"type": "text", "text": "Second"}, {"type": "hardBreak"}, {"type": "text", "text": "third"}]}]}
    assert BD.plain_text(adf).replace("\n", "|") == "First line|Second|third"
    assert BD.plain_text("plain") == "plain" and BD.plain_text(None) == ""


def test_template_is_learned_from_repetition_and_only_a_flag_is_kept():
    tpl = "What happened?   Describe the impact.\nWhy?"
    texts = {f"B-{i}": tpl for i in range(1, 7)}                          # six bugs hold the same unedited text
    texts["B-7"] = tpl + " The queue was full."                            # edited
    texts["B-8"] = ""                                                      # empty
    texts["B-9"] = "A one-off analysis"                                    # unique text, not repeated
    flag, n = BD.rca_flags(texts)
    assert n == 1 and [flag[f"B-{i}"] for i in range(1, 7)] == [0] * 6
    assert (flag["B-7"], flag["B-8"], flag["B-9"]) == (1, 0, 1)
    four = {f"C-{i}": tpl for i in range(4)}                               # below the threshold nothing is a template
    assert set(BD.rca_flags(four)[0].values()) == {1}


def test_group_ids_are_slugs_of_the_names_and_do_not_depend_on_order():
    first = CY.parse_pods_page(PAGE)
    swapped = PAGE.replace("<th><p>Pod 1 - 3<br />Alpha Group &amp; Co</p></th>", "@@A@@").replace("<th><p>Pod 1:</p><p>Beta Group</p></th>", "<th><p>Pod 1 - 3<br />Alpha Group &amp; Co</p></th>").replace("@@A@@", "<th><p>Pod 1:</p><p>Beta Group</p></th>")
    assert CY.slugify("Alpha Group & Co") == "alpha-group-co" and CY.slugify("???") == "group"
    assert {g["id"] for g in first} == {"alpha-group-co", "beta-group", "gamma-5-min-group"}
    twin = PAGE.replace("Beta Group", "Alpha Group &amp; Co")                  # equal names get distinct ids
    ids = [g["id"] for g in CY.parse_pods_page(twin.replace("BETA_POD_1", "BETA_POD_1"))]
    assert len(set(ids)) == 3


def test_closed_date_is_the_israel_local_day_and_a_salesforce_case_makes_a_cfb():
    assert BD.israel_date("2026-01-28T09:31:00.000+0200") == "2026-01-28"
    assert BD.israel_date("2026-04-29T23:30:00.000-0500") == "2026-04-30"            # 06:30 the next day in Israel
    assert BD.israel_date("2026-03-31T22:30:00.000+0000") == "2026-04-01"            # past midnight in Israel
    assert BD.israel_date(None) is None
    base = {"key": "AAA-1", "fields": {"created": "2026-01-01T10:00:00.000+0200", "status": {"name": "Done"}, "resolutiondate": "2026-01-19T10:00:00.000+0200",
                                       "resolution": {"name": "Fixed"}, BD.CLOSED_FIELD: "2026-01-28T09:31:00.000+0200", "reporter": {"accountId": "someone-else"}}}
    other = BD.bug_record(base, "AAA", set())
    assert "cfb" not in other                                                           # neither the CFB account nor a Salesforce case
    base["fields"][BD.SF_FIELD] = "SFCASE-0001"
    b = BD.bug_record(base, "AAA", set())
    assert b["cfb"] == 1 and b["sf"] == 1 and "rb" not in b and b["cl"] == "2026-01-28" and b["rd"] == "2026-01-19"
    base["fields"][BD.SF_FIELD] = None
    base["fields"]["reporter"] = {"accountId": BD.CFB_ACCOUNT}
    b = BD.bug_record(base, "AAA", set())
    assert b["cfb"] == 1 and b["rb"] == 1 and "sf" not in b


class SearchJira:
    """search(jql, fields) returns the issues for the first matching key of `by_jql`."""
    def __init__(self, issues):
        self.issues = issues

    def search(self, jql, fields):
        return [i for i in self.issues if i["key"].split("-")[0] in jql]


def test_a_field_emptied_in_jira_does_not_survive_from_an_earlier_pull():
    old = {"k": "AAA-1", "dd": "2030-01-03", "ts": "CX.99.1.900 (01Jan30)", "as": "Person One", "fl": 1, "ud": "2030-01-01", "cp": "AAA-9", "t": "kept"}
    epics = [dict(old), {"k": "AAA-2", "dd": "2030-01-03", "ts": "CX.99.1.900 (01Jan30)"}]
    issue = lambda key, **f: {"key": key, "fields": {"issuelinks": [], "parent": None, "updated": "2030-01-02T09:00:00.000+0200", **f}}
    # AAA-1: due date, Target Sprint, assignee, Flagged and parent Capability all emptied; AAA-2 keeps its due date and loses only the Target Sprint
    j = SearchJira([issue("AAA-1", duedate=None, customfield_12697=None, assignee=None, customfield_10021=[]),
                  issue("AAA-2", duedate="2030-01-04", customfield_12697=None)])
    saved = BD.PROJECTS
    BD.PROJECTS = ["AAA"]
    try:
        BD.collect_links(j, epics)
    finally:
        BD.PROJECTS = saved
    a, b = epics
    assert all(k not in a for k in ("dd", "ts", "as", "fl", "cp")) and a["ud"] == "2030-01-02" and a["t"] == "kept"
    assert b["dd"] == "2030-01-04" and "ts" not in b


def test_status_since_and_open_bug_update_dates_do_not_survive_when_no_longer_true():
    epics = [{"k": "AAA-1", "s": "Done", "ss": "2029-11-01"}, {"k": "AAA-2", "s": "New", "ss": "2029-11-02"}]
    BD.collect_status_since(SearchJira([]), epics)
    assert all("ss" not in e for e in epics)
    bugs = [{"k": "AAA-5", "ud": "2029-12-01"}, {"k": "AAA-6", "ud": "2029-12-02"}]
    saved = BD.PROJECTS
    BD.PROJECTS = ["AAA"]
    try:
        BD.collect_bug_updates(SearchJira([{"key": "AAA-6", "fields": {"updated": "2030-01-02T01:00:00.000+0200"}}]), bugs)
    finally:
        BD.PROJECTS = saved
    assert "ud" not in bugs[0] and bugs[1]["ud"] == "2030-01-02"


POD_RX_DEFAULT = "pod"
POD_RX_PREFIX = r"pod|^XYZ-[A-Za-z]+-\d+$"                                     # the shape of a project pattern with a second alternative (fictitious names throughout)


def test_pod_labels_use_the_release_planning_rule_case_insensitively():
    labels = ["POD-Alpha-Integrations", "Beta_PMN_POD1", "AlphaTechPod-CR", "Gamma-Pod-3", "unrelated", "NFR", "pod"]
    assert BD.RPM.pod_labels(labels, POD_RX_DEFAULT) == sorted(["POD-Alpha-Integrations", "Beta_PMN_POD1", "AlphaTechPod-CR", "Gamma-Pod-3", "pod"])      # the text anywhere counts
    assert BD.RPM.pod_labels(None, POD_RX_DEFAULT) == [] and BD.RPM.pod_labels([], POD_RX_DEFAULT) == []
    # the second alternative: a label of the form XYZ-Name-1 counts, XYZ-12345 does not, and the plain pattern alone counts neither
    assert BD.RPM.pod_labels(["XYZ-Falcons-2", "XYZ-12345", "XYZ-Falcons"], POD_RX_PREFIX) == ["XYZ-Falcons-2"]
    assert BD.RPM.pod_labels(["XYZ-Falcons-2"], POD_RX_DEFAULT) == []
    assert BD.RPM.pod_labels(["xyz-falcons-2"], POD_RX_PREFIX) == ["xyz-falcons-2"]


def test_pod_patterns_are_read_from_the_release_planning_configuration(tmp_path, monkeypatch):
    rx = BD.pod_patterns()
    assert set(rx) == set(BD.PROJECTS) and all(v for v in rx.values())
    assert rx["WFM"] == BD.POD_DEFAULT_RX                                            # no configuration for the project: the plain pattern


def test_pods_group_case_insensitively_with_the_first_spelling_and_count_an_epic_once_per_pod():
    g = BD.group_pods({"AAA-1": ["Pod-Delta-1"], "AAA-2": ["pod-delta-1", "Pod-Epsilon"], "AAA-3": ["POD-DELTA-1", "pod-delta-1"], "AAA-4": []})
    assert list(g) == ["pod-delta-1", "pod-epsilon"]
    assert g["pod-delta-1"] == {"name": "Pod-Delta-1", "epics": ["AAA-1", "AAA-2", "AAA-3"]}          # first spelling shown, AAA-3 carries two spellings and counts once
    assert g["pod-epsilon"]["epics"] == ["AAA-2"]                                                    # an epic with two pods counts under each; AAA-4 has no pod
    assert all("AAA-4" not in v["epics"] for v in g.values())


def test_collect_pods_clears_a_label_removed_in_jira_and_stores_only_the_matched_labels():
    class J:
        def search(self, jql, fields):
            return [{"key": "AAA-1", "fields": {"labels": ["Pod-Zeta", "other", "NFR"]}}, {"key": "AAA-2", "fields": {"labels": ["other"]}}]
    epics = [{"k": "AAA-1"}, {"k": "AAA-2", "pl": ["Pod-Old"]}, {"k": "AAA-3", "pl": ["Pod-Gone"]}]
    saved = BD.PROJECTS
    BD.PROJECTS = ["AAA"]
    try:
        monkey = BD.pod_patterns
        BD.pod_patterns = lambda: {"AAA": "pod"}
        rx = BD.collect_pods(J(), epics)
    finally:
        BD.PROJECTS = saved
        BD.pod_patterns = monkey
    assert rx == {"AAA": "pod"} and epics[0]["pl"] == ["Pod-Zeta"] and "pl" not in epics[1] and "pl" not in epics[2]
