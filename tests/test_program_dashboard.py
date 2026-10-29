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
