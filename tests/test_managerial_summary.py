"""Tests for the managerial summary's once-a-day send guard."""
from unittest.mock import MagicMock

from src.messaging.managerial_summary import ManagerialSummaryReporter


def _reporter(tmp_path, sender, force=False, override=None):
    engine = MagicMock()
    engine.evaluate_all.return_value = []          # no matches → empty rollup, no Jira
    registry = MagicMock()
    registry.find_by_email.return_value = None     # fall back to email-prefix name
    return ManagerialSummaryReporter(
        engine=engine,
        formatter=MagicMock(),
        sender=sender,
        registry=registry,
        rules_path="config/rules.yaml",
        subscribers_by_project={"PMN": ["a@co.com", "b@co.com"]},
        state_path=str(tmp_path / "mgr.json"),
        force=force,
        override_recipient=override,
    )


def test_first_run_sends_all(tmp_path):
    sender = MagicMock(); sender.send.return_value = True
    stats = _reporter(tmp_path, sender).run()
    assert stats["sent"] == 2
    assert stats["skipped"] == 0


def test_second_run_same_day_skips(tmp_path):
    sender = MagicMock(); sender.send.return_value = True
    _reporter(tmp_path, sender).run()              # first send records the date
    stats = _reporter(tmp_path, sender).run()       # fresh instance, shared state file
    assert stats["sent"] == 0
    assert stats["skipped"] == 2
    assert sender.send.call_count == 2              # only the first run actually sent


def test_force_resends_same_day(tmp_path):
    sender = MagicMock(); sender.send.return_value = True
    _reporter(tmp_path, sender).run()
    stats = _reporter(tmp_path, sender, force=True).run()
    assert stats["sent"] == 2
    assert stats["skipped"] == 0


def test_override_bypasses_guard_and_is_not_recorded(tmp_path):
    sender = MagicMock(); sender.send.return_value = True
    _reporter(tmp_path, sender, override="kobi@co.com").run()   # test send, not recorded
    stats = _reporter(tmp_path, sender).run()                    # real run still sends
    assert stats["sent"] == 2


def test_failed_send_not_recorded_so_retry_works(tmp_path):
    sender = MagicMock(); sender.send.return_value = False
    _reporter(tmp_path, sender).run()               # both fail → nothing recorded
    sender.send.return_value = True
    stats = _reporter(tmp_path, sender).run()        # retry sends them
    assert stats["sent"] == 2


def test_custom_view_filters_rules_and_sends_one_message(tmp_path):
    from types import SimpleNamespace as NS
    def match(rule_id, key):
        rule = NS(id=rule_id, name=rule_id, priority=1, severity="high", emoji=None, message_template="x")
        issue = NS(key=key, summary="s", url="u")
        return NS(rule=rule, issue=issue, owner=None)
    engine = MagicMock()
    engine.evaluate_all.return_value = [NS(matches=[
        match("prod_bugs_sla_breached", "CXWFM-1"),
        match("some_other_rule", "CXWFM-2"),
        match("prod_bugs_sla_breached", "PMSTND-3"),   # project not in the view
    ])]
    registry = MagicMock(); registry.find_by_email.return_value = None
    formatter = MagicMock(); formatter._render_template.return_value = "detail"
    sender = MagicMock(); sender.send.return_value = True
    reporter = ManagerialSummaryReporter(
        engine=engine, formatter=formatter, sender=sender, registry=registry,
        rules_path="config/rules.yaml", subscribers_by_project={},
        state_path=str(tmp_path / "mgr.json"),
        custom_views=[{"recipient": "T@co.com", "projects": ["CXWFM", "PMN"], "rule_ids": ["prod_bugs_sla_breached"]}],
    )
    stats = reporter.run_custom_views()
    assert stats["sent"] == 1
    html = sender.send.call_args.args[0]["message"]
    assert sender.send.call_args.kwargs["recipient_email"] == "t@co.com"
    assert "CXWFM-1" in html
    assert "CXWFM-2" not in html and "PMSTND-3" not in html
    assert reporter.run_custom_views()["skipped"] == 1   # once-a-day guard
