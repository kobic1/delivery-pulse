"""Shared plumbing for the Delivery Pulse browser tests: a tiny test suite with XFAIL support, the fixture build, and page helpers.

Expectation flags (the "expected to fail until the fix lands" tests). Flip a constant to True when the fix is in the template,
or set DP_EXPECT=DEADLINE,ATOMIC_CAP in the environment, or pass --expect DEADLINE to a script. While a flag is False, a test that
fails is reported as XFAIL (and does not fail the run unless --strict); a test that passes is reported as XPASS ("the fix has landed,
turn the flag on"). While a flag is True, the same test is an ordinary PASS or FAIL.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import make_synthetic as MS                                                         # noqa: E402
from cdp import Chrome, ChromeMissing, find_chrome                                  # noqa: E402,F401

REPO = HERE.parent.parent
FROZEN = REPO / "program_dashboard" / "build" / "fallback_v52"
LIVE_TEMPLATE = REPO / "program_dashboard" / "dashboard.template.html"

def jqlkey(project: str) -> str:
    """A project key as Jira wants it in JQL: INT is a reserved word and must be quoted. Spelled here on purpose, not imported from the page or the collector, so the tests do not repeat a mistake made there."""
    return f'"{project}"' if project == "INT" else project


# ---- the expectation flags: False = the fix has not landed yet, so the test is expected to fail (XFAIL)
EXPECT_DEADLINE = True             # F15e: a callTool that never resolves ends in a message and a usable button (per-call deadline)
EXPECT_REAL_ERROR_TEXT = True      # F15i: an automatic refresh that fails with a tool_error shows the real reason, not "needs Jira access"
EXPECT_ATOMIC_CAP = True           # F15j: a failing Capitalization fetch leaves data, stamp, caption and counters consistent
EXPECT_CURSOR_GUARD = True         # F15c: hasNextPage=true with no endCursor is reported as an incomplete read instead of being treated as the last page
EXPECT_FLAGS = {"DEADLINE": EXPECT_DEADLINE, "REAL_ERROR_TEXT": EXPECT_REAL_ERROR_TEXT, "ATOMIC_CAP": EXPECT_ATOMIC_CAP, "CURSOR_GUARD": EXPECT_CURSOR_GUARD}


def apply_expectations(names: list[str]):
    for n in names:
        n = n.strip().upper().replace("EXPECT_", "")
        if n:
            if n not in EXPECT_FLAGS:
                raise SystemExit(f"unknown expectation flag {n}; known: {', '.join(EXPECT_FLAGS)}")
            EXPECT_FLAGS[n] = True


apply_expectations(os.environ.get("DP_EXPECT", "").split(","))


# ---------------------------------------------------------------- a small suite
class T:
    """What a test function receives: check() records one assertion, note() records an observation that is printed but never fails."""

    def __init__(self):
        self.failures: list[str] = []
        self.passed = 0
        self.notes: list[str] = []

    def check(self, cond, msg: str) -> bool:
        if cond:
            self.passed += 1
        else:
            self.failures.append(msg)
        return bool(cond)

    def note(self, msg: str):
        self.notes.append(msg)


class Skip(Exception):
    pass


class Suite:
    def __init__(self, title: str):
        self.title = title
        self.tests = []

    def test(self, name: str, expect: str | None = None):
        def deco(fn):
            self.tests.append((name, expect, fn))
            return fn
        return deco

    def run(self, only: str | None = None, verbose: bool = True) -> list[dict]:
        results = []
        for name, expect, fn in self.tests:
            if only and only not in name:
                continue
            t0 = time.time()
            t = T()
            status, detail = None, ""
            try:
                fn(t)
            except Skip as s:
                status, detail = "SKIP", str(s)
            except Exception as exc:                                                 # an exception inside a test is a failure of that test only
                t.failures.append(f"exception: {type(exc).__name__}: {exc}")
                if os.environ.get("DP_TRACE"):
                    traceback.print_exc()
            if status is None:
                failed = bool(t.failures)
                flag_on = expect is None or EXPECT_FLAGS.get(expect, False)
                if flag_on:
                    status = "FAIL" if failed else "PASS"
                else:
                    status = "XFAIL" if failed else "XPASS"
                    detail = (f"(expected to fail until the fix lands: EXPECT_{expect})" if failed else f"(the fix has landed: turn EXPECT_{expect} on)")
            res = {"name": name, "status": status, "expect": expect, "checks": t.passed + len(t.failures), "failures": t.failures, "notes": t.notes, "detail": detail,
                   "seconds": round(time.time() - t0, 1)}
            results.append(res)
            if verbose:
                print(format_result(res), flush=True)
        return results


def format_result(r: dict) -> str:
    line = f"{r['status']:<6} {r['name']}  [{r['checks']} checks, {r['seconds']}s] {r['detail']}".rstrip()
    for f in r["failures"]:
        line += f"\n         - {f}"
    for n in r["notes"]:
        line += f"\n         . {n}"
    return line


def summarize(results: list[dict], strict: bool = False) -> tuple[str, int]:
    c = {}
    for r in results:
        c[r["status"]] = c.get(r["status"], 0) + 1
    bad = c.get("FAIL", 0) + (c.get("XFAIL", 0) if strict else 0)
    text = ", ".join(f"{c[k]} {k}" for k in ("PASS", "FAIL", "XFAIL", "XPASS", "SKIP") if c.get(k))
    return text or "no tests", 1 if bad else 0


def cli(suite: Suite, desc: str) -> int:
    ap = argparse.ArgumentParser(description=desc)
    ap.add_argument("--template", default=os.environ.get("DP_TEMPLATE", str(FROZEN / "dashboard.template.html")), help="dashboard.template.html to test (default: the frozen v52 copy)")
    ap.add_argument("--live", action="store_true", help="test the live repo template instead of the frozen copy")
    ap.add_argument("--only", help="run only tests whose name contains this text")
    ap.add_argument("--strict", action="store_true", help="expected-to-fail tests (XFAIL) count as failures")
    ap.add_argument("--expect", action="append", default=[], help="turn an expectation flag on, e.g. DEADLINE (repeatable)")
    ap.add_argument("--json", help="write the results as JSON to this file")
    ap.add_argument("--keep", action="store_true", help="keep the generated pages (printed path)")
    a = ap.parse_args()
    apply_expectations(a.expect)
    ctx.template = Path(LIVE_TEMPLATE if a.live else a.template)
    ctx.keep = a.keep
    if not find_chrome():
        must = a.strict or bool(os.environ.get("CI"))
        print(("FAIL" if must else "SKIP") + "   Google Chrome was not found (set CHROME_BIN); the browser tests were not run")
        if a.json:
            Path(a.json).write_text(json.dumps({"skipped": "Chrome not found", "results": []}))
        return 1 if must else 0
    try:
        results = suite.run(a.only)
    finally:
        ctx.cleanup()
    text, code = summarize(results, a.strict)
    print(f"\n{suite.title}: {text}" + (" (strict)" if a.strict else ""))
    if a.json:
        Path(a.json).write_text(json.dumps({"template": str(ctx.template), "results": results}, indent=1))
    return code


# ---------------------------------------------------------------- shared run context: one temp dir, one Chrome, the template under test
class Ctx:
    template: Path = FROZEN / "dashboard.template.html"
    keep = False
    _dir: str | None = None
    _chrome: Chrome | None = None
    _n = 0

    @property
    def dir(self) -> str:
        if not self._dir:
            self._dir = tempfile.mkdtemp(prefix="dp-hermetic-")
        return self._dir

    @property
    def chrome(self) -> Chrome:
        if not self._chrome:
            self._chrome = Chrome()
        return self._chrome

    def write(self, html: str, name: str = "page") -> str:
        self._n += 1
        p = Path(self.dir) / f"{name}_{self._n}.html"
        p.write_text(html, encoding="utf-8")
        return "file://" + str(p)

    def cleanup(self):
        if self._chrome:
            self._chrome.close()
            self._chrome = None
        if self._dir:
            if self.keep:
                print(f"pages kept in {self._dir}")
            else:
                shutil.rmtree(self._dir, ignore_errors=True)
            self._dir = None


ctx = Ctx()


def wait_ready(ch: Chrome, timeout: float = 20) -> bool:
    """The page has drawn its header (its script ran to the end). Gives up early when the page threw an error instead."""
    end = time.time() + timeout
    while time.time() < end:
        if ch.js("!!(document.getElementById('meta') && document.getElementById('meta').textContent.length > 0)") is True:
            return True
        if ch.console_errors():
            return False
        time.sleep(0.1)
    return False


def fragment_for(data: dict) -> str:
    return MS.render_page(data, ctx.template)


def wrap(fragment: str, prelude: str = "", probe: str = "") -> str:
    """The standalone shape the artifact runs in: the fragment (title, style, markup, script) inside a document, with an optional script before it
    (the mocked claude.use) and one after it (the probe)."""
    return ('<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f"{prelude}</head><body>{fragment}{probe}</body></html>")


def il_offset(day: dt.date, hour: int = 12) -> str:
    """The Israel UTC offset in Jira's +0200 form on that day."""
    off = dt.datetime(day.year, day.month, day.day, hour, tzinfo=MS.IL).utcoffset() or dt.timedelta(0)
    m = int(off.total_seconds() // 60)
    return f"{'+' if m >= 0 else '-'}{abs(m) // 60:02d}{abs(m) % 60:02d}"


def stamp(day: dt.date, hour: str = "09:00") -> str:
    """A Jira timestamp for an Israel-local day and time."""
    return f"{day.isoformat()}T{hour}:00.000{il_offset(day)}"


def il_day_of(ts: str) -> str:
    """The Israel-local day of a Jira timestamp (+0300, -0500 or Z), computed here, independently of the page."""
    t = ts.replace("Z", "+0000")
    when = dt.datetime.strptime(t, "%Y-%m-%dT%H:%M:%S.%f%z")
    return when.astimezone(MS.IL).date().isoformat()
