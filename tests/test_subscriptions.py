"""The EMAIL_SUBSCRIPTIONS variable: who gets which email (fictitious addresses only: the repository is public)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for sub in ("dashboards", "release_planning"):
    sys.path.insert(0, str(ROOT / sub))

import subscriptions as S  # noqa: E402


def setv(monkeypatch, value) -> None:
    if value is None:
        monkeypatch.delenv(S.ENV, raising=False)
    else:
        monkeypatch.setenv(S.ENV, value if isinstance(value, str) else json.dumps(value))


def test_addresses_accepts_lists_strings_and_display_names():
    assert S.addresses(["a@x.test", " b@x.test "]) == ["a@x.test", "b@x.test"]
    assert S.addresses("a@x.test; b@x.test, c@x.test") == ["a@x.test", "b@x.test", "c@x.test"]
    assert S.addresses("Ann Lee <a@x.test>; Bob <b@x.test>") == ["a@x.test", "b@x.test"]
    assert S.addresses(["A@x.test", "a@X.test", "b@x.test"]) == ["A@x.test", "b@x.test"]       # a duplicate is dropped whatever its case
    assert S.addresses(None) == [] and S.addresses("") == [] and S.addresses([]) == []


def test_without_the_variable_nothing_is_overridden_or_excluded(monkeypatch):
    setv(monkeypatch, None)
    assert S.rules() == {} and S.excluded() == set()
    assert S.dashboard("phoenix", "to") is None and S.release_planning("PMN") is None
    assert S.drop_excluded(["a@x.test"]) == ["a@x.test"]


def test_invalid_json_stops_the_send(monkeypatch):
    for bad in ("{not json", "[1, 2]", '"text"'):
        setv(monkeypatch, bad)
        with pytest.raises(SystemExit) as e:
            S.rules()
        assert "Nothing was sent" in str(e.value)


def test_dashboard_entries_and_an_empty_cc(monkeypatch):
    setv(monkeypatch, {"dashboards": {"phoenix": {"to": ["a@x.test", "b@x.test"], "cc": []}, "pmn": {"to": "c@x.test;d@x.test"}}})
    assert S.dashboard("phoenix", "to") == ["a@x.test", "b@x.test"]
    assert S.dashboard("phoenix", "cc") == []                        # an entry, even empty: it hides the secret
    assert S.dashboard("pmn", "to") == ["c@x.test", "d@x.test"]
    assert S.dashboard("pmn", "cc") is None                          # no cc entry: the secret (if any) applies
    assert S.dashboard("cxco", "to") is None


def test_exclude_is_case_insensitive_and_applies_to_any_list(monkeypatch):
    setv(monkeypatch, {"exclude": ["Gone@X.test"]})
    assert S.drop_excluded(["a@x.test", "gone@x.test", "b@x.test"]) == ["a@x.test", "b@x.test"]


def test_key_of_env_names():
    assert S.key_of_env("PHOENIX_DASHBOARD_RECIPIENTS") == "phoenix"
    assert S.key_of_env("PHOENIX_DASHBOARD_CC") == "phoenix"
    assert S.key_of_env("CV_TECH_DASHBOARD_RECIPIENTS") == "cv_tech"


def test_has_to_command(monkeypatch):
    setv(monkeypatch, {"dashboards": {"phoenix": {"to": ["a@x.test"]}, "pmn": {"to": []}}})
    assert S.main(["x", "has-to", "phoenix"]) == 0
    assert S.main(["x", "has-to", "pmn"]) == 1                       # an empty list is not a distribution list
    assert S.main(["x", "has-to", "cxco"]) == 1
    setv(monkeypatch, None)
    assert S.main(["x", "has-to", "phoenix"]) == 1


# ------------------------------------------------------------------------------------------------ the dashboards sender
@pytest.fixture
def bas(monkeypatch):
    pytest.importorskip("requests")
    import build_and_send
    return build_and_send


CFG = {"project": "PMN", "recipients_env": "PHOENIX_DASHBOARD_RECIPIENTS", "cc_env": "PHOENIX_DASHBOARD_CC"}


def test_the_variable_wins_over_the_secret(bas, monkeypatch):
    monkeypatch.setenv("PHOENIX_DASHBOARD_RECIPIENTS", "old@x.test")
    monkeypatch.setenv("PHOENIX_DASHBOARD_CC", "oldcc@x.test")
    setv(monkeypatch, {"dashboards": {"phoenix": {"to": ["a@x.test", "b@x.test"], "cc": []}}})
    assert bas.resolve_recipients(CFG, "managers") == ["a@x.test", "b@x.test"]
    assert bas.resolve_cc(CFG, "managers") == []                     # the empty cc entry hides the secret


def test_the_secret_is_used_where_the_variable_is_silent(bas, monkeypatch):
    monkeypatch.setenv("PHOENIX_DASHBOARD_RECIPIENTS", "old@x.test; other@x.test")
    monkeypatch.setenv("PHOENIX_DASHBOARD_CC", "oldcc@x.test")
    setv(monkeypatch, {"dashboards": {"pmn": {"to": ["z@x.test"]}}})
    assert bas.resolve_recipients(CFG, "managers") == ["old@x.test", "other@x.test"]
    assert bas.resolve_cc(CFG, "managers") == ["oldcc@x.test"]


def test_exclude_applies_to_the_secret_and_the_variable(bas, monkeypatch):
    monkeypatch.setenv("PHOENIX_DASHBOARD_RECIPIENTS", "old@x.test;gone@x.test")
    monkeypatch.setenv("PHOENIX_DASHBOARD_CC", "gone@x.test")
    setv(monkeypatch, {"exclude": ["gone@x.test"]})
    assert bas.resolve_recipients(CFG, "managers") == ["old@x.test"]
    assert bas.resolve_cc(CFG, "managers") == []
    setv(monkeypatch, {"exclude": ["gone@x.test"], "dashboards": {"phoenix": {"to": ["a@x.test", "gone@x.test"]}}})
    assert bas.resolve_recipients(CFG, "managers") == ["a@x.test"]


def test_no_list_at_all_still_refuses_to_guess(bas, monkeypatch):
    monkeypatch.delenv("PHOENIX_DASHBOARD_RECIPIENTS", raising=False)
    setv(monkeypatch, None)
    with pytest.raises(SystemExit) as e:
        bas.resolve_recipients(CFG, "managers")
    assert "Nothing was sent" in str(e.value)


def test_test_and_personal_copies_ignore_the_dashboard_lists(bas, monkeypatch):
    monkeypatch.setenv("PMN_DASHBOARD_TEST_RECIPIENT", "me@x.test")
    setv(monkeypatch, {"dashboards": {"phoenix": {"to": ["a@x.test"]}}})
    assert bas.resolve_recipients(CFG, "test") == ["me@x.test"]
    assert bas.resolve_cc(CFG, "test") == []


# ------------------------------------------------------------------------------------------------ release planning
def test_release_planning_recipients_order_of_precedence(monkeypatch):
    pytest.importorskip("requests")
    try:
        import build_report as BR
    except Exception as e:                                           # the report builder needs its own data modules
        pytest.skip(f"build_report not importable here: {e}")
    cfg = {"team_recipients_env": {"Phoenix": "PHOENIX_DASHBOARD_RECIPIENTS"}}
    monkeypatch.setenv("RELEASE_PLANNING_RECIPIENTS", json.dumps({"PMN": "secret@x.test"}))
    monkeypatch.setenv("PHOENIX_DASHBOARD_RECIPIENTS", "team-secret@x.test")
    setv(monkeypatch, None)
    assert BR.recipients(cfg, "PMN", "managers", None) == "secret@x.test"
    assert BR.recipients(cfg, "PMN:Phoenix", "managers", None) == "team-secret@x.test"
    setv(monkeypatch, {"release_planning": {"PMN": ["v@x.test"]}, "dashboards": {"phoenix": {"to": ["a@x.test"]}}})
    assert BR.recipients(cfg, "PMN", "managers", None) == "v@x.test"                     # the variable wins over the JSON secret
    assert BR.recipients(cfg, "PMN:Phoenix", "managers", None) == "a@x.test"             # a team report follows the team's dashboard list
    setv(monkeypatch, {"exclude": ["secret@x.test"]})
    assert BR.recipients(cfg, "PMN", "managers", None) == ""


# ------------------------------------------------------------------------------------------------ the shared sender
def test_send_email_drops_the_excluded_and_refuses_an_empty_to(monkeypatch, capsys):
    import send_email
    setv(monkeypatch, {"exclude": ["gone@x.test"]})
    monkeypatch.setattr(sys, "argv", ["send_email.py", "--to", "a@x.test;gone@x.test", "--cc", "gone@x.test;c@x.test", "--subject", "s", "--body", "<p>b</p>", "--dry-run"])
    assert send_email.main() == 0
    out = json.loads(capsys.readouterr().out.split("\n", 1)[1])
    assert out["to"] == "a@x.test" and out["cc"] == "c@x.test"
    monkeypatch.setattr(sys, "argv", ["send_email.py", "--to", "gone@x.test", "--subject", "s", "--body", "<p>b</p>", "--dry-run"])
    assert send_email.main() == 2


def test_send_email_is_unchanged_without_an_exclude_list(monkeypatch, capsys):
    import send_email
    setv(monkeypatch, {"dashboards": {"phoenix": {"to": ["a@x.test"]}}})
    monkeypatch.setattr(sys, "argv", ["send_email.py", "--to", "Ann <a@x.test>; b@x.test", "--subject", "s", "--body", "<p>b</p>", "--dry-run"])
    assert send_email.main() == 0
    out = json.loads(capsys.readouterr().out.split("\n", 1)[1])
    assert out["to"] == "Ann <a@x.test>; b@x.test"
