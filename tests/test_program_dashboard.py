"""Delivery Pulse dashboard collector: synthetic fixtures only (fictitious labels, teams and dates)."""
import datetime as dt
import json
import re
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
    monkeypatch.setattr(BD, "PROJECTS", ["ZZNOCFG"])                                  # a project with no release planning configuration: the plain pattern
    assert BD.pod_patterns() == {"ZZNOCFG": BD.POD_DEFAULT_RX}


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


# ---------------------------------------------------------------- INT is a reserved JQL word: every query that names a project key quotes it
TEMPLATE_SRC = (HERE / "dashboard.template.html").read_text(encoding="utf-8")
BUILDER_SRC = (HERE / "build_dashboard.py").read_text(encoding="utf-8")


def bare_reserved(jql: str) -> list:
    """The reserved keys left unquoted in a query (a quoted string is blanked first, and INT-123 is an issue key, not the word)."""
    bare = re.sub(r'"(?:[^"\\]|\\.)*"', '""', jql)
    return [k for k in BD.JQL_RESERVED_KEYS if re.search(rf"(?<![\w-]){k}(?![\w-])", bare)]


def test_a_reserved_project_key_is_quoted_and_every_other_key_is_left_alone():
    assert BD.JQL_RESERVED_KEYS == ["INT"] and BD.PROJECTS[-1] == "WFM" and BD.PROJECTS[:6] == ["PMN", "CXCO", "CXSUP", "CXWFM", "CXINT", "INT"] and BD.PRODUCTS == ["WFM", "EEM", "ESP", "EMOB", "PMSTND"]
    assert BD.pkey("INT") == '"INT"' and BD.pkey("CXINT") == "CXINT" and BD.pkey("PMN") == "PMN"
    assert BD.pkeys(["PMN", "INT", "CXCROSS"]) == 'PMN, "INT", CXCROSS'
    assert BD.pkeys(["PMN", "CXCO"]) == "PMN, CXCO"                                    # the other projects' queries are byte-identical to before
    assert BD.definitions()["jqlReservedKeys"] == BD.JQL_RESERVED_KEYS


def test_no_query_the_collector_sends_names_the_reserved_key_bare(monkeypatch):
    """Runs every collector (and the main pull) against a recording Jira that answers nothing: each query that names INT must hold it in quotation marks."""
    sent = []

    class Resp:
        def json(self):
            return []

    class Session:
        def get(self, *a, **k):
            return Resp()

    class FakeJira:
        base, s = "https://example.invalid", Session()

        def search(self, jql, fields=None, **k):
            sent.append(jql)
            return []

        def changelog(self, key):
            return []

    monkeypatch.setenv("JIRA_BASE_URL", "https://example.invalid")
    monkeypatch.setattr(BD.E, "Jira", FakeJira)
    monkeypatch.setattr(BD.PRA, "collect", lambda keys, previous=None: {"org": "o", "at": "t", "kept": 0, "noKey": 0, "bots": 0, "activeDays": 14, "list": []})      # never GitHub from a unit test
    BD.fetch()
    j = FakeJira()
    BD.collect_bug_updates(j, [])
    BD.collect_pods(j, [])
    BD.collect_nfr(j, [])
    BD.collect_capitalization(j)
    BD.collect_capabilities(j, set())
    BD.collect_cfb(j)
    BD.collect_links(j, [])
    BD.collect_bugs(j)
    named = [q for q in sent if "INT" in q]
    assert len(named) >= 12, "the check is blind: too few queries named INT"
    assert all(not bare_reserved(q) for q in sent), [q for q in sent if bare_reserved(q)][:3]
    assert any(q.startswith('project = "INT" AND issuetype = Epic') for q in sent) and any('"INT"' in q and q.startswith("project in (") for q in sent)


# a project key interpolated into JQL must pass through the helper: `project = ${pkey(p)}`, `project in (${pkeys(list)})`; a bare `${p}` or `${list.join(", ")}` is the mistake this test is here for
TEMPLATE_SITE = re.compile(r"\bproject (?:not in|in|=) \(?\$\{(?!pkeys?\()")
BUILDER_SITE = re.compile(r"\bproject (?:not in|in|=) \(?\{(?!pkeys?\()")
ANY_SITE = r"\bproject (?:not in|in|=) \(?\$?\{"


def test_the_page_and_the_collector_quote_every_project_key_through_the_helper():
    bad = [m.group(0) + TEMPLATE_SRC[m.end():m.end() + 40] for m in TEMPLATE_SITE.finditer(TEMPLATE_SRC)]
    assert not bad, f"a project key goes into JQL without pkey/pkeys in the template: {bad[:3]}"
    bad = [m.group(0) + BUILDER_SRC[m.end():m.end() + 40] for m in BUILDER_SITE.finditer(BUILDER_SRC)]
    assert not bad, f"a project key goes into JQL without pkey/pkeys in build_dashboard.py: {bad[:3]}"
    assert len(re.findall(ANY_SITE, TEMPLATE_SRC)) >= 20 and len(re.findall(ANY_SITE, BUILDER_SRC)) >= 8, "the scan is blind: it found too few sites"
    assert not re.search(r"project (?:=|in \() ?INT\b", TEMPLATE_SRC + BUILDER_SRC), "a literal unquoted INT in a query"


def test_the_helper_exists_once_in_each_and_the_page_reads_the_reserved_list_from_the_payload():
    assert len(re.findall(r"^def pkey\(", BUILDER_SRC, re.M)) == 1 and len(re.findall(r"^def pkeys\(", BUILDER_SRC, re.M)) == 1
    assert len(re.findall(r"^const pkey = ", TEMPLATE_SRC, re.M)) == 1 and len(re.findall(r"^const pkeys = ", TEMPLATE_SRC, re.M)) == 1
    assert "DEFS.jqlReservedKeys" in TEMPLATE_SRC


def test_int_uses_the_plain_pod_pattern_without_a_configuration_file():
    assert BD.pod_patterns()["INT"] == BD.POD_DEFAULT_RX and not (HERE.parent / "release_planning" / "config_int.json").exists()


def test_a_capability_record_carries_its_commitment_level_or_an_empty_string():
    """capList records are {t, s, p, fv, cl}: cl is the option of customfield_10136 (a single select), "" when the field is empty; the field is requested in every Capability read."""
    asked = []

    def issue(key, level):
        f = {"summary": "A capability", "status": {"name": "New"}, "fixVersions": [{"name": "27.1"}], "project": {"key": key.split("-")[0]}}
        if level is not False:
            f["customfield_10136"] = level
        return {"key": key, "fields": f}

    class Jira:
        issues = [issue("AAA-1", {"value": "Committed", "id": "1"}), issue("AAA-2", None), issue("AAA-3", False), issue("AAA-4", {"value": "Stretch"})]

        def search(self, jql, fields):
            asked.append((jql, list(fields)))
            if "fixVersion is EMPTY" in jql:
                return []
            if jql.startswith("parent in"):
                return []
            return self.issues if "fixVersion in" in jql else []
    out = BD.collect_capabilities(Jira(), set())
    assert {k: v["cl"] for k, v in out["capList"].items()} == {"AAA-1": "Committed", "AAA-2": "", "AAA-3": "", "AAA-4": "Stretch"}
    assert set(out["capList"]["AAA-1"]) == {"t", "s", "p", "fv", "cl"}
    assert all("customfield_10136" in f for j, f in asked if "issuetype = Capability" in j and "fixVersion in" in j)


def test_the_sandbox_build_gets_its_own_title_and_a_banner_and_keeps_the_page_otherwise():
    page = '<title>Delivery Pulse</title>\n<style></style>\n<header class="top gutter"><h1>Delivery Pulse</h1></header>\n<main></main>'
    out = BD.sandbox_fragment(page, {"sha": "abc1234", "dirty": True, "at": "2026-01-01T00:00+02:00"})
    assert "<title>Delivery Pulse Sandbox</title>" in out and "<title>Delivery Pulse</title>" not in out
    assert out.count('class="sandbox-banner"') == 1 and out.index("sandbox-banner") < out.index('<header class="top gutter">')
    assert "commit abc1234 + uncommitted changes" in out and "not the live dashboard" in out
    assert out.replace(out[out.index('<div class="sandbox-banner"'):out.index('<header class="top gutter">')], "").replace(" Sandbox</title>", "</title>") == page


def test_the_sandbox_build_writes_other_files_than_the_live_ones():
    assert len({BD.OUT, BD.OUT_ARTIFACT, BD.OUT_SANDBOX, BD.OUT_SANDBOX_ARTIFACT}) == 4
    assert "sandbox" in BD.OUT_SANDBOX.name and "sandbox" in BD.OUT_SANDBOX_ARTIFACT.name


def test_the_sandbox_banner_is_added_before_the_usage_bundle_is_inlined():
    """The usage bundle holds strings with the page's own header markup; the banner step asserts exactly one header, so it has to run first."""
    src = (HERE / "build_dashboard.py").read_text()
    body = src[src.index("def render(data"):src.index("def main()")]
    assert body.index("sandbox_fragment(fragment") < body.index("usage_bundle.inline_into(fragment")


def test_the_cxcross_hierarchy_also_holds_our_capabilities_that_sit_under_a_cxcross_initiative():
    """collect_hier asks for the Capabilities of the dashboard projects under the CXCROSS Initiatives (so the CXCROSS view can count and list them), never for another project's, and not the Removed ones."""
    def issue(key, ty, par=None, st="In Progress"):
        f = {"summary": key.lower(), "status": {"name": st}, "issuetype": {"name": ty}, "fixVersions": [{"name": "27.1"}], "project": {"key": key.split("-")[0]}}
        if par:
            f["parent"] = {"key": par}
        return {"key": key, "fields": f}

    class Stub:
        def __init__(self):
            self.asked = []

        def search(self, jql, fields):
            self.asked.append(jql)
            if jql.startswith("project = CXCROSS"):
                return [issue("CXCROSS-1", "Initiative"), issue("CXCROSS-2", "Capability", "CXCROSS-1")]
            if jql.startswith("parent in (CXCROSS-1)"):
                assert "project in (" in jql and "status != Removed" in jql and "CXCROSS" not in jql.split("project in (")[1], jql
                return [issue("PMN-10", "Capability", "CXCROSS-1")]
            return []

    j = Stub()
    out = BD.collect_hier(j, [], {})["hier"]
    assert set(out) == {"CXCROSS-1", "CXCROSS-2", "PMN-10"} and out["PMN-10"]["par"] == "CXCROSS-1" and out["PMN-10"]["ty"] == "Capability"
    assert sum(q.startswith("parent in (CXCROSS-1)") for q in j.asked) == 1


def test_wfm_bug_pull_leaves_out_bugs_that_clone_and_cxwfm_is_untouched():
    assert BD.BUG_EXCLUDE_JQL == {"WFM": '(issueLinkType is EMPTY OR issueLinkType != "clones")'}
    assert "CXWFM" not in BD.BUG_EXCLUDE_JQL and "CXWFM" not in BD.PRODUCTS


def test_a_fixes_link_makes_a_cfb_for_the_non_cxone_products_only():
    link = {"type": {"name": "Fixes"}, "outwardIssue": {"key": "ZZ-9"}}
    other = {"type": {"name": "Blocks"}, "inwardIssue": {"key": "ZZ-8"}}
    base = {"key": "WFM-1", "fields": {"created": "2026-01-01T10:00:00.000+0200", "status": {"name": "Open"}, "reporter": {"accountId": "someone-else"}, "issuelinks": [other]}}
    assert "cfb" not in BD.bug_record(base, "WFM", set())                                       # another link type is not enough
    base["fields"]["issuelinks"] = [other, link]
    b = BD.bug_record(base, "WFM", set())
    assert b["cfb"] == 1 and b["fx"] == 1 and "rb" not in b and "sf" not in b
    assert "cfb" not in BD.bug_record(base, "CXWFM", set())                                      # a CXone project ignores the link
    assert all(p in BD.PRODUCTS for p in ("WFM", "EMOB", "EEM", "ESP")) and BD.CFB_LINK_JQL == 'issueLinkType = "fixes"'


def test_pmstnd_is_a_product_that_keeps_the_standard_cfb_rule():
    assert "PMSTND" in BD.PRODUCTS and "PMSTND" in BD.ALL_RELEASE_PRODUCTS and "PMSTND" not in BD.PROJECTS
    assert BD.FIXES_LINK_PRODUCTS == ["WFM", "EEM", "ESP", "EMOB"]
    link = {"type": {"name": "Fixes"}, "outwardIssue": {"key": "ZZ-9"}}
    i = {"key": "PMSTND-1", "fields": {"created": "2026-01-01T10:00:00.000+0200", "status": {"name": "Open"}, "reporter": {"accountId": "someone-else"}, "issuelinks": [link]}}
    assert "cfb" not in BD.bug_record(i, "PMSTND", set())                                       # a Fixes link does not make a PMSTND bug customer-found
    assert BD.bug_record(i, "EMOB", set())["cfb"] == 1                                          # while it does for EMOB


def test_wfm_is_a_cxone_project_with_its_own_bug_rules_and_cxwfm_has_none():
    r = BD.proj_rules(BD.PROJECTS)
    assert list(r) == ["WFM"] and r["WFM"]["bugClause"] == BD.BUG_EXCLUDE_JQL["WFM"] and r["WFM"]["cfbLink"] == BD.CFB_LINK_JQL
    assert BD.proj_rules(["PMN", "CXWFM"]) == {}


def test_the_pull_request_feed_never_sinks_the_build_and_searches_every_project_and_product_key(monkeypatch):
    monkeypatch.setattr(BD.PRA, "collect", lambda keys, previous=None: (_ for _ in ()).throw(RuntimeError("boom")))
    res = BD.collect_prs()
    assert "list" not in res and res["unavailable"] == BD.PRA.PUBLIC_REASON and "boom" not in json.dumps(res) and res["org"]
    seen = []
    monkeypatch.setattr(BD.PRA, "collect", lambda keys, previous=None: seen.append(list(keys)) or {"org": "o", "at": "t", "kept": 0, "noKey": 0, "bots": 0, "activeDays": 14, "list": []})
    class J:
        def search(self, jql, fields):
            return []
    BD.collect_prs(J())
    assert seen == [BD.PROJECTS + BD.PRODUCTS] and "PMSTND" in seen[0] and "INT" in seen[0]


def test_pull_requests_read_but_not_resolved_to_releases_say_so_and_keep_no_working_field(monkeypatch):
    rec = {"r": "a", "n": 1, "t": "x", "ra": "2026-11-01", "up": "2026-11-10", "rv": "none", "ci": "ok", "pj": ["PMN"], "ik": ["PMN-1"]}
    monkeypatch.setattr(BD.PRA, "collect", lambda keys, previous=None: {"org": "o", "at": "t", "kept": 1, "noKey": 0, "bots": 0, "activeDays": 14, "list": [dict(rec)]})
    class Down:
        def search(self, jql, fields):
            raise RuntimeError("no")
    monkeypatch.setattr(BD.PRA, "release_lookup", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("jira down")))
    res = BD.collect_prs(Down())
    assert res["releasesUnavailable"] == "the Jira release lookup failed" and "jira down" not in json.dumps(res) and res["list"] and all("ik" not in x and "rl" not in x for x in res["list"])


def _stub_the_collectors(monkeypatch, order, chain_waits_for=None, fail=None):
    """Replaces every collector of fetch() by a stub that records its name; the optional event makes one chain step wait until a side collector has started."""
    import threading

    class J:
        pass

    monkeypatch.setenv("JIRA_BASE_URL", "https://example.invalid")
    monkeypatch.setattr(BD.E, "Jira", J)
    seen = {}

    def stub(name, value=None, started=None, wait=None):
        def f(*a, **k):
            order.append(name); seen[name] = (a, k)
            if started is not None:
                started.set()
            if wait is not None:
                assert wait.wait(5), f"{name} ran before the side collectors started: they are not running beside the chain"
            if fail == name:
                raise RuntimeError(f"{name} failed")
            return value
        return f
    prs_started = threading.Event()
    for name, value in (("pull_epics", [{"k": "PMN-1", "p": "PMN", "fv": ["27.1"]}]), ("collect_bugs", []), ("collect_links", {"capabilities": {}}), ("planning", {}), ("collect_hier", {"hier": {}}),
                        ("collect_cx_priority", {}), ("collect_nfr", None), ("collect_capabilities", {}), ("collect_cfb", {"c": 1}), ("collect_capitalization", {"z": 1}), ("fetch_windows", {"w": 1}),
                        ("fetch_products", {"WFM": {}})):
        monkeypatch.setattr(BD, name, stub(name, value))
    monkeypatch.setattr(BD, "add_changelog", stub("add_changelog", None, wait=prs_started if chain_waits_for else None))
    monkeypatch.setattr(BD, "collect_prs", stub("collect_prs", {"org": "o", "list": []}, started=prs_started))
    return seen


def test_the_pulls_that_do_not_depend_on_the_epics_run_beside_the_epic_chain(monkeypatch):
    order = []
    seen = _stub_the_collectors(monkeypatch, order, chain_waits_for="collect_prs")
    data = BD.fetch()                       # add_changelog waits (5 s at most) for the pull request read to have started: it can only have if the two run side by side
    assert sorted(order) == sorted(set(order)) and len(order) == 14, f"every collector exactly once: {order}"
    assert data["cfbx"] == {"c": 1} and data["cap"] == {"z": 1} and data["windows"] == {"w": 1} and data["products"] == {"WFM": {}} and data["prs"] == {"org": "o", "list": []}
    assert data["epics"] == [{"k": "PMN-1", "p": "PMN", "fv": ["27.1"]}]


def test_a_failure_in_a_side_pull_still_stops_the_build(monkeypatch):
    for name in ("collect_cfb", "fetch_products", "collect_prs", "collect_capitalization"):
        _stub_the_collectors(monkeypatch, [], fail=name)
        with pytest.raises(RuntimeError, match=f"{name} failed"):
            BD.fetch()


def test_the_earlier_pull_request_list_is_read_from_the_named_file_and_a_bad_file_means_a_full_read(monkeypatch, tmp_path):
    f = tmp_path / "prev.json"
    f.write_text(json.dumps({"at": "t", "list": []}))
    monkeypatch.setenv("PRS_PREVIOUS_FILE", str(f))
    assert BD.previous_prs() == {"at": "t", "list": []}
    f.write_text("{not json")
    assert BD.previous_prs() is None
    monkeypatch.setenv("PRS_PREVIOUS_FILE", str(tmp_path / "missing.json"))
    assert BD.previous_prs() is None
    monkeypatch.delenv("PRS_PREVIOUS_FILE")
    assert BD.previous_prs() is None
    order = []
    f.write_text(json.dumps({"at": "t", "list": []}))
    monkeypatch.setenv("PRS_PREVIOUS_FILE", str(f))
    seen = _stub_the_collectors(monkeypatch, order)
    BD.fetch()
    assert seen["collect_prs"][0][2] == {"at": "t", "list": []}, "fetch hands the earlier list to the pull request read"


# ---- the changelog cache and the parallel story-link read (faster epic chain) ----------------------------------------------------------------------------------------------------

NOW_C = dt.datetime(2026, 11, 16, 12, 0, tzinfo=dt.timezone.utc)


def _cached(entries, at="2026-11-16T08:00+00:00", v=None):
    return {"v": BD.CHANGELOG_CACHE_VERSION if v is None else v, "fullAt": at, "entries": entries}


def test_a_cached_changelog_is_reused_only_when_the_epics_updated_stamp_is_unchanged():
    c = BD.ChangelogCache(_cached({"A-1": {"u": "s1", "m": {"ad": {"27.1": "2026-01-01"}}}}), NOW_C)
    assert c.get("A-1", "s1") == {"ad": {"27.1": "2026-01-01"}} and c.hits == 1
    assert c.get("A-1", "s2") is None and c.get("A-1", None) is None and c.get("A-2", "s1") is None


def test_a_cache_of_another_version_or_older_than_a_day_or_unreadable_is_ignored_and_a_young_one_keeps_its_time():
    e = {"A-1": {"u": "s", "m": {"ad": {}}}}
    assert BD.ChangelogCache(_cached(e, v=0), NOW_C).get("A-1", "s") is None
    assert BD.ChangelogCache(_cached(e, at="2026-11-15T11:59+00:00"), NOW_C).get("A-1", "s") is None
    assert BD.ChangelogCache(_cached(e, at="not a time"), NOW_C).get("A-1", "s") is None
    assert BD.ChangelogCache({"v": BD.CHANGELOG_CACHE_VERSION}, NOW_C).get("A-1", "s") is None and BD.ChangelogCache(None, NOW_C).get("A-1", "s") is None
    young = BD.ChangelogCache(_cached(e, at="2026-11-15T12:30+00:00"), NOW_C)
    assert young.get("A-1", "s") is not None and young.dump()["fullAt"] == "2026-11-15T12:30+00:00"      # the chain stops 24 hours after the last full read
    assert BD.ChangelogCache(None, NOW_C).dump()["fullAt"].startswith("2026-11-16T12:00")


def test_add_changelog_reads_only_the_epics_that_changed_and_gives_the_same_epics_as_a_full_read(monkeypatch):
    reads = []

    def fake(j, e):
        reads.append(e["k"])
        return {"ad": {r: e["cr"] for r in e["fv"]}, "ip": 2, "vl": 1, "edct": 3, "pipeline_edct": 3, "cal": 4} if e["s"] == "Done" else {"ad": {r: e["cr"] for r in e["fv"]}}
    monkeypatch.setattr(BD, "analyse", fake)

    def epics():
        return [{"k": "A-1", "s": "Done", "rd": "2026-02-01", "cr": "2026-01-01", "fv": ["27.1"], "_u": "u1"},
                {"k": "A-2", "s": "In Progress", "rd": None, "cr": "2026-01-02", "fv": ["27.1"], "_u": "u2"},
                {"k": "A-3", "s": "In Progress", "rd": None, "cr": "2026-01-03", "fv": ["27.2"], "_u": None}]
    monkeypatch.setattr(BD, "CHANGELOG_CACHE", None)
    full = epics()
    BD.add_changelog(None, full)
    assert reads == ["A-1", "A-2", "A-3"] and all("_u" not in e for e in full), "no cache: every changelog is read, and the transient stamp never reaches the payload"
    first = BD.ChangelogCache(None, NOW_C)
    monkeypatch.setattr(BD, "CHANGELOG_CACHE", first)
    reads.clear(); BD.add_changelog(None, epics())
    second = BD.ChangelogCache(first.dump(), NOW_C)
    monkeypatch.setattr(BD, "CHANGELOG_CACHE", second)
    reads.clear()
    again = epics(); again[1]["_u"] = "u2-edited"                   # A-2 was edited; A-3 has no stamp, so it is never cached
    BD.add_changelog(None, again)
    assert sorted(reads) == ["A-2", "A-3"] and second.hits == 1
    expected = epics(); BD.CHANGELOG_CACHE = None; BD.add_changelog(None, expected)
    assert again == expected, "the epics are the same with the cache as without it"
    assert set(second.dump()["entries"]) == {"A-1", "A-2"}


def test_a_failed_changelog_read_is_not_cached(monkeypatch):
    def boom(j, e):
        raise RuntimeError("503")
    monkeypatch.setattr(BD, "analyse", boom)
    c = BD.ChangelogCache(None, NOW_C)
    monkeypatch.setattr(BD, "CHANGELOG_CACHE", c)
    BD.add_changelog(None, [{"k": "A-1", "s": "Done", "rd": "2026-02-01", "cr": "2026-01-01", "fv": ["27.1"], "_u": "u"}])
    assert c.dump()["entries"] == {}


def test_the_changelog_cache_is_read_from_the_named_file_and_a_bad_file_means_a_full_read(monkeypatch, tmp_path):
    f = tmp_path / "cache.json"
    f.write_text(json.dumps({"v": 1, "entries": {}}))
    monkeypatch.setenv("CHANGELOG_CACHE_FILE", str(f))
    assert BD.previous_changelog_cache() == {"v": 1, "entries": {}}
    f.write_text("{no")
    assert BD.previous_changelog_cache() is None
    monkeypatch.setenv("CHANGELOG_CACHE_FILE", str(tmp_path / "missing.json"))
    assert BD.previous_changelog_cache() is None
    monkeypatch.delenv("CHANGELOG_CACHE_FILE")
    assert BD.previous_changelog_cache() is None


def test_story_links_read_in_parallel_equal_the_links_read_one_after_another():
    keys = [f"E-{n:03d}" for n in range(200)]                       # three chunks of 80
    rows = {}
    for n, k in enumerate(keys):
        a, b = f"S-{n}", f"S-{(n * 7) % 200}"
        rows[k] = [{"key": a, "fields": {"status": {"name": "Open"}, "issuetype": {"name": "Story"}, "parent": {"key": k}, "issuelinks": [
            {"type": {"name": "Dependency", "inward": "is a dependency of", "outward": "depends on"}, "outwardIssue": {"key": b, "fields": {"status": {"name": "Open"}, "issuetype": {"name": "Story"}}}}]}}]

    class J:
        def search(self, jql, fields):
            import re as _re
            return [r for k in _re.findall(r"E-\d+", jql) for r in rows.get(k, [])]
    parallel = BD.collect_story_links(J(), [{"k": k} for k in keys])

    class Serial(J):
        pass
    import concurrent.futures as cf
    original = BD.ThreadPoolExecutor
    BD.ThreadPoolExecutor = lambda max_workers=None: original(max_workers=1)
    try:
        serial = BD.collect_story_links(Serial(), [{"k": k} for k in keys])
    finally:
        BD.ThreadPoolExecutor = original
    assert parallel == serial and parallel["sdeps"], "same pairs, same infos, same order"


def test_a_product_pull_swaps_the_projects_and_releases_of_its_own_copy_of_the_module_never_of_the_one_the_cxone_pulls_read(monkeypatch):
    mine = BD.isolated_copy()
    assert mine is not BD and mine.PROJECTS == BD.PROJECTS and mine.PROJECTS is not BD.PROJECTS
    before = (list(BD.PROJECTS), list(BD.RELEASES), BD.CURRENT_RELEASE, list(BD.PROVISIONAL))
    seen = {}

    def pull_epics(j):
        seen["copy"] = (list(mine.PROJECTS), list(mine.RELEASES), mine.CURRENT_RELEASE)
        seen["main"] = (list(BD.PROJECTS), list(BD.RELEASES), BD.CURRENT_RELEASE, list(BD.PROVISIONAL))      # what a CXone pull reading its globals at this moment would see
        return []
    monkeypatch.setattr(mine, "pull_epics", pull_epics)
    for name, value in (("collect_bugs", []), ("add_changelog", None), ("collect_links", {}), ("planning", {}), ("product_windows", {}), ("derive_windows", [])):
        monkeypatch.setattr(mine, name, lambda *a, _v=value, **k: _v)
    out = mine.collect_product(None, "WFM", {"major": {"name": "9.1"}, "releases": ["9.1"], "candidates": []})
    assert out["projects"] == ["WFM"] and seen["copy"] == (["WFM"], ["9.1"], "9.1")
    assert seen["main"] == before, "the module the CXone pulls read was not touched"
    assert (mine.PROJECTS, mine.RELEASES) == (before[0], before[1]), "and the copy is restored afterwards"


def test_the_isolated_copy_shares_the_changelog_cache_so_product_epics_are_cached_too(monkeypatch):
    c = BD.ChangelogCache(None, NOW_C)
    monkeypatch.setattr(BD, "CHANGELOG_CACHE", c)
    assert BD.isolated_copy().CHANGELOG_CACHE is c
