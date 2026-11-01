"""Delivery Pulse: the contract between the collector (build_dashboard.py) and the page (dashboard.template.html).

Synthetic data only. These tests need no browser and no network; they catch the drift that used to be silent: a definition changed on one side,
a Jira field id used by the page that the collector does not know, a payload layout the page does not expect, a build that overwrites the only snapshot.
"""
import json
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent / "program_dashboard"
sys.path.insert(0, str(HERE))
import build_dashboard as BD  # noqa: E402

TEMPLATE = (HERE / "dashboard.template.html").read_text(encoding="utf-8")


def js_array(name: str) -> list:
    """The fallback literal of `const NAME = DEFS.x || [ ... ];` or `const NAME = [ ... ];` in the template."""
    m = re.search(rf"const {name} = (?:DEFS\.\w+ \|\| )?(\[[^\]]*\])", TEMPLATE)
    assert m, f"{name} not found in the template"
    return json.loads(m.group(1))


def test_the_pages_fallback_definitions_equal_the_collectors():
    d = BD.definitions()
    assert js_array("BUG_CLOSED") == d["bugClosed"]
    assert js_array("NFR_CATEGORIES") == d["nfrCategories"]
    assert re.search(r'const NFR_LABEL = DEFS\.nfrLabel \|\| "([^"]+)"', TEMPLATE).group(1) == d["nfrLabel"]
    assert js_array("COMMIT") == d["commitTypes"]
    assert js_array("TARGET_COMMIT") == d["targetCommit"]


def test_the_page_reads_every_definition_the_collector_writes():
    read = set(re.findall(r"DEFS\.(\w+)", TEMPLATE))
    assert read == set(BD.definitions()), (read, set(BD.definitions()))


def test_page_and_collector_agree_on_the_payload_schema():
    assert int(re.search(r"const PAGE_SCHEMA = (\d+);", TEMPLATE).group(1)) == BD.SCHEMA


def test_the_power_bi_scope_is_one_list_and_the_page_falls_back_to_the_same_literal():
    d = BD.definitions()
    expected = ["PMN", "CXSUP", "CXINT", "CXWFM", "CXCO", "INT", "EEM", "EMOB", "ESP", "DCMLT", "PVDEV"]
    assert d["capPbiProjects"] == expected and "WFM" not in expected                      # the Jira project WFM is not in the Power BI report
    assert js_array("CAP_PBI_PROJECTS") == d["capPbiProjects"]
    assert js_array("CAP_PBI_EXCLUDE") == d["capPbiExclude"] == ["MS-21777"]
    assert "capPbiProjects" in set(re.findall(r"DEFS\.(\w+)", TEMPLATE)) and "capPbiExclude" in set(re.findall(r"DEFS\.(\w+)", TEMPLATE))


def test_the_power_bi_section_has_the_layout_the_page_and_the_fictitious_fixture_use():
    sys.path.insert(0, str(Path(__file__).resolve().parent / "dashboard_browser"))
    import make_synthetic as MS
    section = BD.cap_pbi_build([], BD.CAP_PBI_PROJECTS)
    assert set(section) == set(MS.make()["capPbi"]) == {"scope", "values", "opts", "start", "from", "sprints", "rows", "noSprint", "pulledAt", "refreshedAt"}
    assert set(section["noSprint"]) == {"n", "sp", "rows"} and section["start"] == MS.PBI_START and section["from"] == MS.PBI_FROM and section["values"] == MS.PBI_CLASSES
    assert BD.SCHEMA == 3 and "capPbi" in BD.EXPECTED                                       # the layout number moved with the new optional section


def test_every_jira_field_id_the_page_queries_is_known_to_the_collector():
    page = set(re.findall(r"customfield_(\d+)", TEMPLATE)) | set(re.findall(r"cf\[(\d+)\]", TEMPLATE))
    collector = set(re.findall(r"customfield_(\d+)", (HERE / "build_dashboard.py").read_text(encoding="utf-8"))) | set(re.findall(r"cf\[(\d+)\]", (HERE / "build_dashboard.py").read_text(encoding="utf-8")))
    assert page <= collector, f"field ids only the page uses: {sorted(page - collector)}"


def synthetic_payload() -> dict:
    return {"generated": "2026-01-10T09:00+02:00", "jiraBase": "https://example.invalid", "projects": ["PMN"], "releases": ["26.1"], "current": "26.1",
            "windows": {"26.1": ["2030-01-01", "2030-03-31"]}, "epics": [{"k": "PMN-90001", "p": "PMN", "t": "Synthetic epic", "s": "Done", "fv": ["26.1"], "tm": []}],
            "bugs": [], "cfbAccount": "synthetic-account", "cloudId": "synthetic", "cycles": {"x": 1}, "quality": {"y": 2}}


def test_validate_stops_a_build_that_misses_required_data_and_warns_about_optional_sections():
    ok = synthetic_payload()
    warnings = BD.validate_payload(ok)
    assert any("hier" in w for w in warnings)                                  # optional sections are reported, not fatal
    broken = dict(ok); del broken["windows"]
    with pytest.raises(SystemExit) as e:
        BD.validate_payload(broken)
    assert "windows" in str(e.value)
    with pytest.raises(SystemExit):
        BD.validate_payload({**ok, "epics": "not a list"})


def test_an_unknown_target_sprint_label_is_a_soft_warning_not_a_failure():
    ok = synthetic_payload()
    ok["sprints"] = [{"n": "CX.26.1.1 (01Jan30)", "start": "2030-01-01", "end": "2030-01-21", "real": True}]
    ok["epics"][0]["ts"] = "CX.26.1.1 (01Jan30)"
    assert not any("Target Sprint" in w for w in BD.validate_payload(ok))
    ok["epics"][0]["ts"] = "Sprint of the unknown kind"
    warnings = BD.validate_payload(ok)                                         # warned about, the build goes on
    assert any("Target Sprint" in w and "1 epics" in w for w in warnings)
    assert BD.unknown_sprint_labels({"epics": ok["epics"], "sprints": []}) == {}      # no calendar at all is the "section missing" notice, not one warning per epic


def test_render_writes_schema_defs_and_build_stamp_and_drops_the_dead_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(BD, "OUT", tmp_path / "page.html")
    monkeypatch.setattr(BD, "OUT_ARTIFACT", tmp_path / "artifact.html")
    monkeypatch.setattr(BD, "PROJECTS", ["PMN"])
    monkeypatch.setattr(BD, "sprint_calendar", lambda labels: [])
    BD.render(synthetic_payload())
    page = (tmp_path / "artifact.html").read_text(encoding="utf-8")
    m = re.search(r"const DATA = (\{.*?\});\n", page, re.S)
    payload = json.loads(m.group(1))
    assert payload["schema"] == BD.SCHEMA and payload["defs"] == BD.definitions()
    assert set(payload["build"]) == {"sha", "dirty", "at"}
    assert "cycles" not in payload and "quality" not in payload
    assert "</" not in m.group(1)                                              # the payload cannot close the script element


def test_the_power_bi_flag_pulls_saves_atomically_and_a_reuse_render_includes_it(tmp_path, monkeypatch):
    class FakeJira:
        issues = [{"key": f"{p}-9000{i}", "fields": {"customfield_10079": {"value": "Capitalize - X"}, "customfield_10038": 2, "customfield_10020": [{"id": 5, "endDate": "2030-02-10T21:00:00.000Z"}]}}
                  for i, p in enumerate(BD.CAP_PBI_PROJECTS)]

        def _of(self, jql):
            return [i for i in self.issues if i["key"].startswith(jql.split('project = "')[1].split('"')[0] + "-")]

        def search(self, jql, fields):
            return self._of(jql)

        def count(self, jql):
            return len(self._of(jql))
    target = tmp_path / "program_data.json"
    monkeypatch.setattr(BD, "DATA_PATH", target)
    monkeypatch.setattr(BD, "OUT", tmp_path / "page.html")
    monkeypatch.setattr(BD, "OUT_ARTIFACT", tmp_path / "artifact.html")
    monkeypatch.setattr(BD, "PROJECTS", ["PMN"])
    monkeypatch.setattr(BD, "sprint_calendar", lambda labels: [])
    monkeypatch.setattr(BD.E, "Jira", FakeJira)
    target.write_text(json.dumps(synthetic_payload()))
    monkeypatch.setattr(sys, "argv", ["build_dashboard.py", "--add-capitalization-pbi"])
    assert BD.main() == 0
    saved = json.loads(target.read_text())
    assert saved["capPbi"]["rows"].count(";") + 1 == 11 and saved["capPbi"]["pulledAt"] and target.with_suffix(".json.prev").exists() and not target.with_suffix(".json.tmp").exists()
    read = lambda: json.loads(re.search(r"const DATA = (\{.*?\});\n", (tmp_path / "artifact.html").read_text(encoding="utf-8"), re.S).group(1))
    assert read()["capPbi"] == saved["capPbi"] and read()["schema"] == BD.SCHEMA
    (tmp_path / "artifact.html").unlink()
    monkeypatch.setattr(sys, "argv", ["build_dashboard.py", "--reuse"])
    assert BD.main() == 0 and read()["capPbi"] == saved["capPbi"]               # a render from the saved file carries it


def test_save_data_is_atomic_keeps_the_previous_snapshot_and_refuses_what_it_cannot_read_back(tmp_path, monkeypatch):
    target = tmp_path / "program_data.json"
    monkeypatch.setattr(BD, "DATA_PATH", target)
    BD.save_data({**synthetic_payload(), "v": 1})
    BD.save_data({**synthetic_payload(), "v": 2})
    assert json.loads(target.read_text())["v"] == 2
    assert json.loads(target.with_suffix(".json.prev").read_text())["v"] == 1       # the last good snapshot survives
    assert not target.with_suffix(".json.tmp").exists()
    with pytest.raises(TypeError):
        BD.save_data({**synthetic_payload(), "v": object()})                   # not serialisable: nothing is written
    assert json.loads(target.read_text())["v"] == 2


def test_two_mode_flags_are_an_error_not_a_silently_skipped_second(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["build_dashboard.py", "--add-bugs", "--add-capitalization"])
    with pytest.raises(SystemExit) as e:
        BD.main()
    assert e.value.code == 2
    assert "one mode flag at a time" in capsys.readouterr().err


def test_a_bad_pull_never_replaces_the_snapshot_or_its_previous_copy(tmp_path, monkeypatch):
    target = tmp_path / "program_data.json"
    monkeypatch.setattr(BD, "DATA_PATH", target)
    BD.save_data(synthetic_payload())
    BD.save_data({**synthetic_payload(), "generated": "2026-01-11T09:00+02:00"})
    good, prev = target.read_text(), target.with_suffix(".json.prev").read_text()
    with pytest.raises(SystemExit):
        BD.save_data({**synthetic_payload(), "epics": []})                     # a failed pull: no epics
    assert target.read_text() == good and target.with_suffix(".json.prev").read_text() == prev


def test_no_person_is_held_in_the_payload_an_old_assignee_name_is_purged_on_save_and_render(tmp_path, monkeypatch):
    monkeypatch.setattr(BD, "DATA_PATH", tmp_path / "program_data.json")
    payload = synthetic_payload()
    payload["epics"][0]["as"] = "Synthetic Person"
    payload["ext"] = {"PMN-90002": {"p": "PMN", "t": "Far end", "s": "New", "as": "Synthetic Person"}}
    BD.save_data(payload)
    assert "Synthetic Person" not in (tmp_path / "program_data.json").read_text()
    assert not any("as" in rec for rec in payload["epics"] + list(payload["ext"].values()))
    assert "assignee" not in BD.PLAN_FIELDS
