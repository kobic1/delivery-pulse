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
renders it into the template; runs `harness.py`, `canary.py`, `link_oracle.py`, `link_guard.py`, `link_cycles.py` and `pbi_scope.py`; runs `leak_check.py`; prints a summary.
Needs Python 3.9+ and Google Chrome (`CHROME_BIN` overrides the path). Without Chrome the browser suites print `SKIP` with a clear message and
the rest still runs. Add `--keep` to keep the generated pages (the path is printed). `DP_TRACE=1` prints tracebacks of exceptions inside tests.

Results: `PASS`, `FAIL`, `XFAIL` (expected to fail until a fix lands, see below), `XPASS` (an expected failure that now passes: turn the flag on), `SKIP`.

## Files

| File | What it is |
|---|---|
| `make_synthetic.py` | The fictitious payload, same schema and keys as `build/program_data.json` (including `capPbi`, the Power BI scope: `pbi_universe` makes fictitious Jira issues with full sprint lists, `pbi_oracle` computes the expected numbers from them on its own, `pbi_payload` encodes them, `pbi_node` is the connector's answer for one issue). Seeded, dates relative to today (Israel time), issue numbers from 90001. Also `render_page` (the same single-placeholder substitution as `build_dashboard.render()`) and `canarify`. `python3 make_synthetic.py out.html` renders a page you can open. |
| `cdp.py` | A small Chrome DevTools driver (standard library only), temporary profile, free port, `wait_for` with a timeout. |
| `kit.py` | The tiny suite (PASS/FAIL/XFAIL/XPASS), the expectation flags, shared page helpers. |
| `mock_claude.js`, `probe.js` | The mocked `claude.use("mcp")` (the real shape of the Atlassian `searchJiraIssuesUsingJql` answer) and the in-page probe. The mock clears `dp.slowRuns` and `dp.slowData` at the start of every page (`CFG.keep` keeps them: the page is a reload of the previous one) and seeds the daily allowance with `CFG.sr`: `none`, `auto` (the first open of the day used), `one`, `used` (both clicks used), `yesterday`, `future`, `corrupt`, a raw string stored as it is, or an object such as `{"n": 0, "auto": 1}`; the Israel day is computed after the `CFG.shift` clock override. `CFG.ls`: `recent` seeds `dp.lastRefresh` and drops the page's automatic refresh (the case is about a click), `recentauto` seeds it and lets the automatic refresh run. `CFG.pbinodes` are the issues the mock answers the Power BI scope query with (the query is told by its quoted project keys), `CFG.pbiCountDelta` makes Jira's count for that query disagree with the read, and the modes `pbifail` and `emptypbi` make it fail or answer nothing. The probe adds `dp.slowRuns` (`slowRaw`), the Power BI scope data (`pbi`, `pbiFail`), `DATA.edctAt`, the Efficiency and Release Analysis notes and the 'Done Epics with No EDCT' row to the snapshot. |
| `harness.py` | The Refresh checks and the failure matrix (F15). |
| `canary.py` | The escaping canary (F16). |
| `pbi_scope.py` | The Power BI scope view of Capitalization % (below): the control, the numbers against an independent oracle, every link evaluated, and its Refresh step. Uses `harness.py`'s scenario helpers; its own suite. |
| `link_oracle.py`, `jql_eval.py` | The link oracle (F14b) and the small JQL evaluator it uses. |
| `link_guard.py` | The owner's rule: every Jira link is a query Jira recalculates, never a frozen list of keys (an allowlist names the few populations Jira cannot search, and may only shrink), and no link is longer than 6,000 characters (also with every team ticked). |
| `link_cycles.py` | The Delivery Cycles links: for every release x project set x cycle x node x kind (Planned, Done, Due so far, Overdue, Stale, Due next 7 days, Flagged, Carry-over, No planned date, Epics with Flags, weekly rows, After release end, pod rows), the query the page builds is evaluated in Python over the baked epics and must find exactly the set of epics the page counts; the printed number of every link must equal its query's result; a link over the URL budget is plain text; two seeded defects (`<=` to `<`, a Target Sprint no longer excluded) must be caught. A variant payload reaches carry-over, planned after the release end and a Target Sprint the calendar does not know. |
| `leak_check.py` | Searches this folder for anything that appears in the real data (needs a real payload on the machine; otherwise it says so and skips). |
| `run_dashboard_checks.py` | The one entry. |

## What the tests guard

**Fixture** (`harness.py`): the generator's RCA template hashes equal the page's `h53`; the payload has the same top-level keys and record keys as the real
one (when `build/program_data.json` exists); every section renders with content and no uncaught error.

**Refresh, ported from the earlier scratch harness** (every assertion kept): incremental `updated` windows and cursor paging; merge-not-rebuild of epics, bugs,
planning fields and pod labels; the dependency card stays in its sprint; Capabilities;
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
analysis text, capitalization values and teams, far-end issues, bugs under epics, the pod pattern). The page is loaded in 29 filter states (the URL hash), every
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

**Two tiers of Refresh steps** (the `slow_tier_*`, `stored_limited_tier_*` and `live_tier_*` tests; each clicks the way the multi-click tests do, with `refresh.last = 0` and `cache=False`). The live tier (epics, bugs and accessibility, then Open CFBs, Dependency links, Capabilities) runs on every open and click; the limited tier (cycle time = a `getJiraIssue` call per epic waiting; Capitalization = the `issuetype in (Bug, Story, Task)` reads) runs on the first open of the Israel day and the first two clicks.

| Test | Guards |
|---|---|
| `slow_tier_three_clicks...` | clicks 1 and 2 issue both limited calls, click 3 issues none but still the live reads, shows the sentence as an info message, leaves the button enabled and the Capitalization rows unchanged |
| `slow_tier_the_first_open_of_the_day...` / `..._second_open...` | the first open runs the limited tier and uses the automatic allowance (`auto` 1, `n` 0); the second is live only and both clicks are still available |
| `slow_tier_a_new_day...` / `..._midnight_crossing...` | yesterday's allowance resets; a run that crosses midnight (clock at 23:59:46, held inside the limited tier) counts for its starting day, and a click after midnight runs the tier and starts the new day at one |
| `slow_tier_blocked_storage...` | storage blocked: the count lives in memory (clicks 1 and 2 limited, click 3 live only), no console errors |
| `slow_tier_unreadable_or_invalid...` | not JSON, `null`, a list, a number, `n` out of range, not an integer or negative, not a date, a day in the future: all reset to today without page errors |
| `slow_tier_the_allowance_is_read_at_click_time` | a value written by another tab after load is honoured |
| `slow_tier_a_failed_run_is_not_refunded` | a failed Capitalization read uses a click; the third click is live only; only the step that succeeded is stored |
| `slow_tier_header_stamp...` | the header is the oldest of the five live sources (computed independently in Python), the tooltip, the Efficiency, Release Analysis and Capitalization notes say "not refreshed yet" or the refresh time, nothing talks about a build, and a copy without a connector shows none of it |
| `slow_tier_an_epic_closed_since...` | with the cycle-time step skipped the newly Done epic is not a 'Done Epics with No EDCT' defect (row note: "wait for the next cycle-time refresh"), the status does not say "rebuild"; with the step run the count is the same |
| `slow_tier_an_automatic_refresh_that_fails_on_step_one...` | `dp.slowRuns` untouched |
| `live_tier_the_automatic_refresh_runs_on_every_open...` | no 15-minute skip: a reload with a recent `dp.lastRefresh` still reads the live data |
| `stored_limited_tier_*` | a reload (the same page, connector denied) shows the refreshed Capitalization rows, the cycle time and the stored refresh times before any refresh; another build, schema or layout, and a corrupt value, are discarded or ignored without errors; a stored value never overwrites an existing one and a future time is not trusted; blocked storage still works |
| `refresh_redraws_after_the_first_step...` | also the order of one refresh: step 1, then the live steps, then cycle time, then Capitalization |

Assertions changed for the two tiers: `refresh_capitalization_delta_every_quarter` (the chart caption now carries "refreshed <time>" after a Refresh and "not refreshed yet" before it; the old rule "no per-section stamp" is reversed on purpose), `refresh_step_fails_alone_capitalization` and the stamp check of `f15j...` (a failed limited step no longer drags the header stamp back: it names the step in the tooltip), and `auto_refresh_skipped_when_last_refresh_was_recent` (now `auto_refresh_runs_even_when_the_last_refresh_was_recent`: the 15-minute guard is off).

**Power BI scope view of Capitalization % (`pbi_scope.py`)**, each its own test; the expected numbers come from `make_synthetic.pbi_oracle` (a second implementation of the rule over the same fictitious issues), never from the page:

| Test | Guards |
|---|---|
| `pbi_control_is_a_radio_group...` | two real radios in one named group in a fieldset with the legend Scope, third after Group By and Measure; the arrow keys (real key events) move it |
| `pbi_switch_hash_round_trip...` | the default is Closed date and its numbers are untouched; `cps=pbi` in the address and back; the polite live message; the filter summary; Reset Filters; no page errors |
| `pbi_choice_is_saved_in_the_browser_storage...` | the choice is written to and read back from the viewer's storage like the other Capitalization state |
| `pbi_release_is_disabled...` | Release is disabled with a reason, Quarter is the grouping even for `cpg=release`, and the Release choice returns in the Closed-date view |
| `pbi_table_equals_the_independent_oracle...` | every cell of the project by quarter table (capitalized and all issues, both story-point sums, the share and its n < 5 rule) and the total row, both measures; the class table (Capitalized, Non capitalized, Unmapped); one bar per quarter with its n and its two-decimal share |
| `pbi_parity_with_the_report...` | what the rule leaves out (sub-tasks, epics, not Done, the project WFM, a last sprint before 2025-Q4) is left out; the fixture can tell the latest end date apart from the highest sprint id and from the first sprint |
| `pbi_projects_and_teams_filters_do_not_apply...` | the same table and bars under project, team, commitment and release filters; the caption says so |
| `pbi_no_sprint_footnote_and_the_provisional_bar` | the footnote count equals the oracle, plain text with the reason, singular wording; only the current quarter is dashed and its hover text says so |
| `pbi_without_the_section...` | a build without `capPbi`, or with another project list, shows a notice; the other view works |
| `pbi_links_every_number_is_a_query...` | every bar and number in six views (both measures, release address, filters) opens a query whose evaluated set (`jql_eval` over the fictitious issues' full sprint lists: `sprint in`, `sprint not in`, `project`, the `cf[10079]` classes) has exactly the printed count; the query shape; no key lists; within the URL budget |
| `pbi_links_oracle_selftest...` | three seeded defects (later sprints not excluded, Unmapped without the empty value, the project clause of a cell dropped) are caught |
| `pbi_links_a_query_over_the_url_budget...` | a quarter with 700 more sprints loses its links (the number stays as text) |
| `delta_inserts_replaces_deletes_and_moves...` | one Refresh with a response that changes a value and points, reopens one issue, removes one, gives one a later last sprint in another quarter, gives a no-sprint issue its first sprint, adds Done issues (unknown sprint, no sprint, a tie of two sprints, an end around midnight UTC with an offset, blank points, a sprint without an end date beside a dated one, a last sprint before the start, a new Capitalize value) and returns a not-Done issue and a sub-task: the rows, the no-sprint list and the link values equal the outcome computed from the changed issues; 400+ rows the response did not return are unchanged; the table equals the oracle after the Refresh; the caption carries the refresh time |
| `delta_an_empty_answer_deletes_nothing`, `delta_a_failed_step...`, `delta_a_lost_page...`, `delta_a_read_overtaken...` | an empty answer changes nothing; a failing step (also a failing second page after a first that returned changes) leaves the data byte-identical, names the step and the reason, keeps the others applied and is not stored; Jira's count disagreeing with the read stops the step; a read that was overtaken by another is dropped |
| `delta_runs_in_the_limited_tier...` | clicks 1 and 2 read the scope after Capitalization (one allowance, not one per step), click 3 does not; the query and its six fields |
| `delta_the_stored_result...` | the result is stored with the data version and the refresh time and shown after a reload; six kinds of bad stored value (rows pointing outside the sprint list, another project list, a future time, a read not newer than the data's own, not an object, a time that does not match its data) and another data version are ignored without errors |
| `delta_notes_and_the_stamp_tooltip...` | the tooltip, the Release Analysis note and the caption name the step in plain words, with the refresh time or "not refreshed yet" or the failure; nothing talks about a build |

Assertions changed for the Power BI scope: `slow_tier_header_stamp_is_the_oldest_live_source_and_the_notes_say_the_rest` (the tooltip now also names "Capitalization (Power BI scope) not refreshed yet" and the Release Analysis note ends with "Capitalization in Power BI scope: not refreshed yet"), `stored_limited_tier_a_reload_shows_the_last_refresh_without_the_connector` (the payload layout number is 3, and the stored value also holds `pbiAt`) and the corrupt-value case of `stored_limited_tier_a_corrupt_value_is_ignored_without_errors` (its schema literal is 3, so the value is rejected for its content, not for the old schema). The link guard's views and the canary's states now include `cps=pbi`.

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
