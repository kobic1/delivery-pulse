"""The headless Chrome helper of the browser suites retries a start that never opens its debugging port, and nothing else.

A busy machine (the CI runners do this now and then) can start Chrome without it ever answering on its port; one such start used to fail a whole test. The helper now tries again (3 times by default,
CHROME_START_TRIES), each time with a new port and profile, and raises the same error as before when every try fails.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "dashboard_browser"))
import cdp  # noqa: E402


def test_a_start_that_fails_once_is_tried_again_and_returns(capsys):
    calls = []

    def attempt(n):
        calls.append(n)
        if n == 0:
            raise RuntimeError(cdp.START_ERROR)
        return "started"

    assert cdp.start_with_retry(attempt, tries=3, pause=0) == "started"
    assert calls == [0, 1]
    assert "try 1 of 3" in capsys.readouterr().err               # one line in the log for the retry


def test_every_try_failing_raises_the_same_error_as_before():
    calls = []

    def attempt(n):
        calls.append(n)
        raise RuntimeError(cdp.START_ERROR)

    with pytest.raises(RuntimeError, match="^Chrome did not open its debugging port$"):
        cdp.start_with_retry(attempt, tries=3, pause=0)
    assert calls == [0, 1, 2]


def test_any_other_error_is_not_retried():
    calls = []

    def attempt(n):
        calls.append(n)
        raise RuntimeError("something else went wrong")

    with pytest.raises(RuntimeError, match="something else"):
        cdp.start_with_retry(attempt, tries=3, pause=0)
    assert calls == [0]


def test_one_try_means_no_retry_and_zero_is_one():
    calls = []

    def attempt(n):
        calls.append(n)
        raise RuntimeError(cdp.START_ERROR)

    for tries in (1, 0):
        calls.clear()
        with pytest.raises(RuntimeError):
            cdp.start_with_retry(attempt, tries=tries, pause=0)
        assert calls == [0]


def test_a_chrome_that_exits_at_once_is_retried_and_then_fails_with_the_same_error(monkeypatch, capsys):
    """A fake Chrome (a program that exits straight away): the helper must not wait the full time for its port, must try again, and must raise the old error."""
    monkeypatch.setenv("CHROME_BIN", "/usr/bin/false" if Path("/usr/bin/false").exists() else "/bin/false")
    monkeypatch.setattr(cdp, "START_TRIES", 2)
    monkeypatch.setattr(cdp.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="^Chrome did not open its debugging port$"):
        cdp.Chrome()
    assert capsys.readouterr().err.count("starting again") == 1


def test_the_real_chrome_still_starts_when_it_is_installed():
    if not cdp.find_chrome():
        pytest.skip("Chrome is not installed on this machine")
    ch = cdp.Chrome()
    try:
        assert ch.js("1 + 1") == 2
    finally:
        ch.close()
