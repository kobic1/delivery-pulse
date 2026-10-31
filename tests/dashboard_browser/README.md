# Delivery Pulse browser tests

Hermetic, committable tests for the Delivery Pulse page (`program_dashboard/dashboard.template.html`). They run the real page in headless
Chrome on a **fictitious** payload. Nothing reads Jira, nothing touches the network, nothing is written outside a temporary directory, and no
real issue key, team, person, pod label, cycle date or account id appears anywhere in this folder (the repository is public; `leak_check.py` enforces it).

## Run

```bash
python3 tests/dashboard_browser/run_dashboard_checks.py                      # everything, against the frozen v52 copy (about 90 s)
python3 tests/dashboard_browser/run_dashboard_checks.py --live               # against the live program_dashboard/dashboard.template.html
python3 tests/dashboard_browser/run_dashboard_checks.py --expect DEADLINE    # a fix has landed: its test must now pass
python3 tests/dashboard_browser/run_dashboard_checks.py --strict             # expected failures (XFAIL) fail the run
python3 tests/dashboard_browser/harness.py --only f15                        # one suite, a subset by name (also canary.py, link_oracle.py)
```

The runner does five things and exits 1 on any FAIL: `pytest tests/test_program_dashboard.py`; builds the fixture twice (it must be identical) and
renders it into the template; runs `harness.py`, `canary.py` and `link_oracle.py`; runs `leak_check.py`; prints a summary.
Needs Python 3.9+ and Google Chrome (`CHROME_BIN` overrides the path). Without Chrome the browser suites print `SKIP` with a clear message and
the rest still runs. Add `--keep` to keep the generated pages (the path is printed). `DP_TRACE=1` prints tracebacks of exceptions inside tests.

Results: `PASS`, `FAIL`, `XFAIL` (expected to fail until a fix lands, see below), `XPASS` (an expected failure that now passes: turn the flag on), `SKIP`.

## Files

| File | What it is |
|---|---|
| `make_synthetic.py` | The fictitious payload, same schema and keys as `build/program_data.json`. Seeded, dates relative to today (Israel time), issue numbers from 90001. Also `render_page` (the same single-placeholder substitution as `build_dashboard.render()`) and `canarify`. `python3 make_synthetic.py out.html` renders a page you can open. |
| `cdp.py` | A small Chrome DevTools driver (standard library only), temporary profile, free port, `wait_for` with a timeout. |
| `kit.py` | The tiny suite (PASS/FAIL/XFAIL/XPASS), the expectation flags, shared page helpers. |
| `mock_claude.js`, `probe.js` | The mocked `claude.use("mcp")` (the real shape of the Atlassian `searchJiraIssuesUsingJql` answer) and the in-page probe. |
| `harness.py` | The Refresh checks and the failure matrix (F15). |
| `canary.py` | The escaping canary (F16). |
| `link_oracle.py`, `jql_eval.py` | The link oracle (F14b) and the small JQL evaluator it uses. |
| `link_guard.py` | The owner's rule: every Jira link is a query Jira recalculates, never a frozen list of keys (an allowlist names the few populations Jira cannot search, and may only shrink), and no link is longer than 6,000 characters (also with every team ticked). |
| `link_cycles.py` | The Delivery Cycles links: for every release x project set x cycle x node x kind (Planned, Done, Due so far, Overdue, Stale, Due next 7 days, Flagged, Carry-over, No planned date, Epics with Flags, weekly rows, After release end, pod rows), the query the page builds is evaluated in Python over the baked epics and must find exactly the set of epics the page counts; the printed number of every link must equal its query's result; a link over the URL budget is plain text; two seeded defects (`<=` to `<`, a Target Sprint no longer excluded) must be caught. A variant payload reaches carry-over, planned after the release end and a Target Sprint the calendar does not know. |
| `leak_check.py` | Searches this folder for anything that appears in the real data (needs a real payload on the machine; otherwise it says so and skips). |
| `run_dashboard_checks.py` | The one entry. |

## What the tests guard

**Fixture** (`harness.py`): the generator's RCA template hashes equal the page's `h53`; the payload has the same top-level keys and record keys as the real
one (when `build/program_data.json` exists); every section renders with content and no uncaught error.

**Refresh, ported from the earlier scratch harness** (every assertion kept): incremental `updated` windows and cursor paging; merge-not-rebuild of epics, bugs,
planning fields and pod labels; the dependency card stays in its sprint; open CFBs (RCA classification by hash, left-the-set, regression flag); Capabilities;
dependency links; Capitalization delta for every quarter (updates, deletes, absence never deletes, fallback day); one header stamp; a failing step leaves its
own data byte-identical and never blocks the others (four steps); an empty response deletes nothing; denied consent; the automatic refresh on open
(once, button and progress, filters usable, `localStorage` blocked, skipped when recent, Retry rate-limited); a mocked clock a quarter later (F4).

**Failure matrix (F15)**, each its own test:

| Test | Guards |
|---|---|
| `f15a_retryable_error...` | a retryable tool error on the first call is retried once, then succeeds; two in a row stop after one retry and show the error |
| `f15b_window_over_the_cap...` | a window that returns more than the page limit is halved down to single days with no gap or repeat; a one-day window still over the limit is an error and nothing is applied |
| `f15c_missing_end_cursor...` | `hasNextPage=true` with no `endCursor`: no loop, no crash (and, flagged `CURSOR_GUARD`, the read is reported as incomplete) |
| `f15d_needs_reauth / blocked_by_policy / ..._on_open` | the exact messages for both codes on a manual Refresh; the calm snapshot note with Retry on open |
| `f15e_a_call_that_never_resolves...` | a `callTool` that never answers: the button must come back and the page must say so (flag `DEADLINE`) |
| `f15f_timestamps_with_Z_and_plus_0300...` | `Z`, `+0300`, `-0500` stamps give the Israel-local day (capitalization day, CFB Closed day); an epic's resolution date keeps the date part, as the build does |
| `f15g_an_issue_returned_in_two_windows...` | the same key in several windows (old snapshot, clock shifted 25 days) is stored and counted once, also in Capitalization |
| `f15h_a_double_click...` | a JS double click and a real pointer double click start one refresh; a click after it is rate-limited |
| `f15i_a_tool_error_in_the_automatic_refresh...` | calm note, one attempt, Retry offered (stable); the real reason of a `tool_error` is shown (flag `REAL_ERROR_TEXT`) |
| `f15j_a_capitalization_fetch_failing...` | the last project's second page fails after earlier projects returned changes: rows, value and team lists, refresh time, counters, caption, checklist and header stamp stay consistent; the next refresh recovers (flag `ATOMIC_CAP`) |

**Escaping canary (F16)**: `"><img src=x onerror=window.__x=1>` and `<script>window.__x=1</script>` are put into every free-text field of the payload (epic title, team,
assignee, category, AI model, pod label, sprint name, status, capability and initiative names, fix versions, bug team and resolution, CFB summary, links and
analysis text, capitalization values and teams, far-end issues, bugs under epics, the pod pattern). The page is loaded in 27 filter states (the URL hash), every
`details` (Show data) is opened, collapsed groups are expanded, the hover text of every mark is shown. After each: `window.__x` is undefined, no `img` with `src=x`
or `onerror`, no inline handler attribute and no script element beyond the template's own, no hostile node in the tooltip. A control test proves the detector fires on an
unescaped injection, and a test proves the payload is really rendered as text. The refresh path is covered with hostile strings in the mocked Jira responses.
Left untouched on purpose: project codes, release labels, issue keys, `jiraBase`, `cloudId`, `cfbAccount` (the page builds logic and URLs from them).

**Link oracle (F14b)**: under 26 filter states every `href` is checked for `NaN`, `undefined`, `null`, `[object` and for being well formed (https, the Jira host,
`/browse/KEY` or `/issues/?jql=` with parseable JQL). In the Open Bugs, CFB and Capitalization blocks the JQL of every link whose text is a number is
**evaluated in Python over the baked records** (`jql_eval.py`) and must match the printed number. Named tests cover the two Capitalization defects (Quarter mode
"All issues" and "no story points": no `NaN` date; Release mode "Not plotted" and "no story points": scoped). `oracle_selftest_catches_seeded_defects` copies the template,
seeds each defect, and requires the oracle to catch it, so a green oracle is not a blind one. The evaluator knows the fields these blocks use; a query it cannot
judge is reported as "not judged", a query it cannot parse is a failure.

## The expectation flags

Some tests describe a fix that is being made. While the fix has not landed they are expected to fail:

| Flag (in `kit.py`) | Test |
|---|---|
| `EXPECT_DEADLINE` | `f15e_a_call_that_never_resolves_ends_in_a_message` |
| `EXPECT_REAL_ERROR_TEXT` | `f15i_automatic_tool_error_shows_the_real_reason` |
| `EXPECT_ATOMIC_CAP` | `f15j_a_capitalization_fetch_failing...` |
| `EXPECT_CURSOR_GUARD` | `f15c_missing_end_cursor_is_reported_as_incomplete` |

All four are `False`. With a flag `False` a failing test is reported as `XFAIL` and does not fail the run (unless `--strict`); a passing one is `XPASS`
("the fix has landed, turn the flag on"). Turn a flag on by editing the constant in `kit.py`, by `--expect DEADLINE` (repeatable) or by `DP_EXPECT=DEADLINE,ATOMIC_CAP`;
from then on the test is an ordinary PASS or FAIL.

## How the tests stay deterministic and fast

Fixed seed; dates relative to today in Israel time (the page's own time base); no network; every wait is a page condition with a timeout (the "no refresh expected"
cases use a short bounded settle). The page's multi-second timers (the 8 s checklist settle, a call deadline) are shortened 20 times in the scenarios that need
them (`fast=True`), and a template that reads `window.__dpCallDeadlineMs` gets 800 ms from `mock_claude.js` (a no-op for one that does not). The whole run takes about 90 s.

## Adding a test

A scenario is `scenario(mode, ls, click, shift_ms, hook, slow, fast, ..., **overrides)` in `harness.py`: it loads the page with the mocked connector and returns the page's
snapshot before and after. `hook` is the source of an async JavaScript function `(input, c) => ...` that can answer a call (`c.ok(nodes, nextCursor)`), throw
`{code, message, retryable}`, or never resolve; returning nothing falls through to the default answers. Overrides replace any of the mock's node lists.
