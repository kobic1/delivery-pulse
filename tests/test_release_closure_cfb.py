"""The release closure report counts a customer-found bug the way the dashboard does: reported by the CFB account OR linked to a Salesforce case."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "release_closure"))
import cfb_kpis  # noqa: E402

CFG = {"project": "PMN", "cfb_reporter": "reporter-id"}


def test_cfb_query_includes_bugs_linked_to_a_salesforce_case():
    jql = cfb_kpis.cfb_jql(CFG)
    assert '(reporter = "reporter-id" OR cf[10329] is not EMPTY)' in jql


def test_window_query_keeps_the_resolution_rule_and_the_window():
    jql = cfb_kpis.window_jql(CFG, {"start": "2026-01-01", "end": "2026-02-01"})
    assert 'resolution in (Fixed, "Fixed - Config")' in jql
    assert 'resolutiondate >= "2026-01-01" AND resolutiondate < "2026-02-02"' in jql


def test_the_report_note_says_salesforce_bugs_count():
    assert "Salesforce" in cfb_kpis.NOTE
