"""Delivery Pulse dashboard collector: synthetic fixtures only (fictitious labels, teams and dates)."""
import datetime as dt
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent / "program_dashboard"
sys.path.insert(0, str(HERE))
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


def test_capitalization_day_uses_the_closed_field_in_israel_time_and_falls_back_to_the_resolution_date():
    day = BD.cap_day
    assert day({"customfield_10099": "2030-03-31T23:30:00.000+0000", "resolutiondate": "2030-01-01T10:00:00.000+0200"}) == ("2030-04-01", False)      # 23:30 UTC is 02:30 on April 1 in Israel
    assert day({"customfield_10099": "2030-02-10T09:00:00.000+0200", "resolutiondate": "2030-03-01T10:00:00.000+0200"}) == ("2030-02-10", False)      # Closed wins over the resolution date
    assert day({"customfield_10099": None, "resolutiondate": "2030-03-01T10:00:00.000+0200"}) == ("2030-03-01", True)                                 # empty Closed: the resolution date, flagged
    assert day({}) == (None, False)


def test_capitalization_values_and_record():
    assert BD.cap_is_capitalized("Capitalize - Bug Fix for release not yet in production")
    assert not BD.cap_is_capitalized("Non Capitalize - Tech research/POC") and not BD.cap_is_capitalized("") and not BD.cap_is_capitalized(None)
    issue = lambda **f: {"key": "AAA-7", "fields": {"customfield_10079": {"value": "Capitalize - New Product Dev"}, "customfield_10038": None, "customfield_10099": "2030-02-10T09:00:00.000+0200",
                                                      "customfield_10098": {"value": "Team A"}, "resolutiondate": "2030-02-01T10:00:00.000+0200", **f}}
    r = BD.cap_record(issue())
    assert r["cap"] and r["sp"] == 0.0 and r["day"] == "2030-02-10" and r["fallback"] is False and r["team"] == "Team A"          # blank points count as 0
    assert BD.cap_record(issue(customfield_10079=None))["cap"] is False and BD.cap_record(issue(customfield_10038=3.5))["sp"] == 3.5
    r2 = BD.cap_record(issue(customfield_10099=None))
    assert r2["day"] == "2030-02-01" and r2["fallback"] is True
    assert BD.cap_start() == "2025-10-01"                                                                                          # the start of 2025-Q4


# ---------------------------------------------------------------- Capitalization % in the Power BI scope (synthetic issues only)
def pbi_issue(key, value="Capitalize - Feature", sp=3, sprints=(), **extra):
    """A Done issue as Jira returns it; sprints are (id, endDate) pairs, endDate None for a sprint without one."""
    return {"key": key, "fields": {"customfield_10079": {"value": value} if value else None, "customfield_10038": sp, "issuetype": {"name": "Story"}, "status": {"name": "Done"},
                                   "resolutiondate": "2026-01-10T10:00:00.000+0200",
                                   "customfield_10020": [{"id": i, "name": f"Sprint {i}", "state": "closed", "startDate": "2026-01-01T09:00:00.000Z", "endDate": e} for i, e in sprints], **extra}}


class PbiJira:
    """search(jql, fields) and count(jql) over a list of issues; `lose` hides that many issues from the paged read only (a lost page)."""
    def __init__(self, issues, lose=0):
        self.issues, self.lose, self.searches = issues, lose, []

    def _of(self, jql):
        proj = jql.split('project = "')[1].split('"')[0]
        return [i for i in self.issues if i["key"].rsplit("-", 1)[0] == proj]

    def search(self, jql, fields):
        self.searches.append((jql, fields))
        got = self._of(jql)
        return got[: len(got) - self.lose] if self.lose else got

    def count(self, jql):
        return len(self._of(jql))


def test_pbi_last_sprint_is_the_one_with_the_latest_end_date_not_the_highest_id_or_the_first():
    last = BD.cap_pbi_last_sprint
    assert last([(1, "x")]) is None and last([]) is None and last(None) is None
    sprints = lambda *p: [{"id": i, "endDate": e} for i, e in p]
    assert last(sprints((50, "2026-02-01T21:00:00.000Z"), (7, "2026-05-01T21:00:00.000Z"), (90, "2026-03-01T21:00:00.000Z"))) == (7, "2026-05-01")      # the highest id (90) and the first (50) lose
    assert last(sprints((8, "2026-02-01T21:00:00.000Z"), (9, "2026-02-01T21:00:00.000Z"))) == (9, "2026-02-01")                                          # a tie goes to the higher id
    assert last(sprints((8, None), (9, "2026-02-01T21:00:00.000Z"), (10, None))) == (9, "2026-02-01")                                                    # a sprint without an end date is ignored
    assert last(sprints((8, None), (9, ""))) is None                                                                                                      # none with an end date: no last sprint
    assert last(sprints((8, "not a date"), (9, "2026-02-01T21:00:00.000Z"))) == (9, "2026-02-01")                                                         # an unreadable one is ignored, not a crash
    assert last(["a legacy string", {"id": 3, "endDate": "2026-02-01T21:00:00.000Z"}]) == (3, "2026-02-01")


def test_pbi_quarter_is_the_utc_day_of_the_end_date():
    last = BD.cap_pbi_last_sprint
    day = lambda e: last([{"id": 1, "endDate": e}])[1]
    assert day("2030-03-31T23:30:00.000+0000") == "2030-03-31"                  # still March in UTC (it is April 1 in Israel: the rule is UTC)
    assert day("2030-03-31T22:30:00.000-0500") == "2030-04-01"                  # 03:30 UTC the next day
    assert day("2030-04-01T01:00:00.000+0300") == "2030-03-31"                  # 22:00 UTC the day before
    assert day("2030-06-30T21:00:00.000Z") == "2030-06-30"
    # the later instant wins, whatever offset it is written in
    assert last([{"id": 1, "endDate": "2030-03-31T23:00:00.000+0000"}, {"id": 2, "endDate": "2030-04-01T00:30:00.000+0300"}]) == (1, "2030-03-31")


def test_pbi_unmapped_is_everything_that_is_not_capitalize_or_non_capitalize_by_prefix():
    cls = BD.cap_pbi_class
    assert cls("Capitalize - New Product Dev") == 0 and cls("Capitalize") == 0
    assert cls("Non Capitalize - Tech research/POC") == 1
    assert cls("") == 2 and cls(None) == 2 and cls("Something else") == 2
    assert cls("Non capitalize - Not cloud") == 2 and cls("non Capitalize - x") == 2 and cls("capitalize - x") == 2        # lower-case variants are not mapped: they stay in the total as Unmapped
    assert BD.cap_pbi_record(pbi_issue("PMN-90001", value=None))["cls"] == 2 and BD.cap_pbi_record(pbi_issue("PMN-90001", sp=None))["sp"] == 0.0        # blank points count as 0


def pbi_decode(section):
    """The rows back into (key, class, points, sprint id, end day): the round trip of the compact text."""
    out = []
    for text in section["rows"].split(";") if section["rows"] else []:
        n, pi, c, sp, si = text.split(",")
        out.append((f"{section['scope'][int(pi)]}-{n}", int(c), float(sp), section["sprints"][int(si)][0], section["sprints"][int(si)][1]))
    return out


def test_pbi_section_keeps_the_rule_and_the_rows_round_trip():
    jan, apr, old = "2026-01-20T21:00:00.000Z", "2026-04-10T21:00:00.000Z", "2025-08-01T21:00:00.000Z"
    issues = [
        pbi_issue("PMN-90001", sprints=[(11, jan)], sp=5),
        pbi_issue("PMN-90002", "Non Capitalize - Research", sprints=[(11, jan), (12, apr)], sp=2.5),         # last sprint is the later one
        pbi_issue("CXCO-90003", None, sprints=[(12, apr)], sp=None),                                         # empty value: Unmapped, no points
        pbi_issue("INT-90004", "Non capitalize - Not cloud", sprints=[(12, apr)], sp=1),                     # lower-case variant: Unmapped
        pbi_issue("PMN-90005", sprints=[(10, old)], sp=8),                                                    # last sprint before 2025-Q4: not in the payload
        pbi_issue("PVDEV-90006", sprints=[], sp=4),                                                           # no sprint: counted apart
        pbi_issue("PVDEV-90007", sprints=[(13, None)], sp=2),                                                 # a sprint without an end date: the same
        pbi_issue("MS-21777", sprints=[(11, jan)], sp=99),                                                   # the excluded key
        pbi_issue("ZZZ-90008", sprints=[(11, jan)], sp=99),                                                  # not in the scope
    ]
    s = BD.cap_pbi_build(issues, BD.CAP_PBI_PROJECTS)
    got = {r[0]: r for r in pbi_decode(s)}
    assert set(got) == {"PMN-90001", "PMN-90002", "CXCO-90003", "INT-90004"}
    assert got["PMN-90002"][3:] == (12, "2026-04-10") and got["PMN-90002"][1:3] == (1, 2.5)
    assert got["CXCO-90003"][1:3] == (2, 0.0) and got["INT-90004"][1] == 2 and got["PMN-90001"][1:3] == (0, 5.0)
    assert s["noSprint"]["n"] == 2 and s["noSprint"]["sp"] == 6.0 and s["noSprint"]["rows"] == "90006,10,4;90007,10,2"
    assert sorted(x[0] for x in s["sprints"]) == [11, 12] and s["values"] == ["Capitalized", "Non capitalized", "Unmapped"]
    assert s["opts"] == [["Capitalize - Feature"], ["Non Capitalize - Research"]]                             # the values a link will name
    assert s["scope"] == BD.CAP_PBI_PROJECTS and s["pulledAt"] is None and s["start"] == "2025-10-01"
    assert all(len(t.split(",")) == 5 for t in s["rows"].split(";"))
    again = BD.cap_pbi_build(list(reversed(issues)), BD.CAP_PBI_PROJECTS)                                   # the section does not depend on the order the pages came in
    assert sorted(pbi_decode(again)) == sorted(pbi_decode(s)) and again["noSprint"] == s["noSprint"]
    assert BD.cap_pbi_build([], BD.CAP_PBI_PROJECTS)["rows"] == ""


def test_pbi_collector_reads_every_project_of_the_scope_and_checks_each_read_against_jiras_count(capsys):
    issues = [pbi_issue(f"{p}-9000{i}", sprints=[(20 + i, "2026-02-10T21:00:00.000Z")]) for i, p in enumerate(BD.CAP_PBI_PROJECTS)]
    j = PbiJira(issues)
    out = BD.collect_capitalization_pbi(j)
    assert len(j.searches) == len(BD.CAP_PBI_PROJECTS) and out["rows"].count(";") + 1 == len(issues) and out["pulledAt"]
    for (jql, fields), proj in zip(j.searches, BD.CAP_PBI_PROJECTS):
        assert jql == f'project = "{proj}" AND status = Done AND issuetype in (Bug, Story, Task) AND resolutiondate >= "2025-04-01"'          # every key quoted, INT included
        assert sorted(fields) == sorted(["issuetype", "status", "resolutiondate", "customfield_10038", "customfield_10079", "customfield_10020"])
    assert "Power BI scope" in capsys.readouterr().out


def test_pbi_collector_refuses_a_read_that_lost_a_page_and_a_repeated_issue():
    issues = [pbi_issue(f"PMN-{90000 + i}", sprints=[(11, "2026-02-10T21:00:00.000Z")]) for i in range(10)]
    with pytest.raises(SystemExit) as e:
        BD.collect_capitalization_pbi(PbiJira(issues, lose=4))                     # Jira counts 10, the paged read returned 6: nothing is saved
    assert "counts 10" in str(e.value) and "6 were read" in str(e.value)
    BD.collect_capitalization_pbi(PbiJira(issues, lose=2))                         # within the slack (issues change while a long read runs)

    class Twice(PbiJira):
        def search(self, jql, fields):
            return super().search(jql, fields) + [issues[0]]
    with pytest.raises(SystemExit) as e2:
        BD.collect_capitalization_pbi(Twice(issues))
    assert "twice" in str(e2.value)


def test_pbi_scope_is_one_list_shared_with_the_page_and_the_flag_is_a_mode_flag(monkeypatch, capsys):
    d = BD.definitions()
    assert d["capPbiProjects"] == BD.CAP_PBI_PROJECTS and len(d["capPbiProjects"]) == 11 and "WFM" not in d["capPbiProjects"] and d["capPbiExclude"] == ["MS-21777"]
    monkeypatch.setattr(sys, "argv", ["build_dashboard.py", "--add-capitalization", "--add-capitalization-pbi"])
    with pytest.raises(SystemExit) as e:
        BD.main()
    assert e.value.code == 2 and "one mode flag at a time" in capsys.readouterr().err
