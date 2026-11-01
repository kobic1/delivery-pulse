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
python3 tests/dashboard_browser/harness.py --only f15                        # one suite, a subset by name (also canary.py, link_oracle.py, tile_oracle.py)
```

The runner does five things and exits 1 on any FAIL: `pytest tests/test_program_dashboard.py`; builds the fixture twice (it must be identical) and
renders it into the template; runs `harness.py`, `canary.py`, `link_oracle.py`, `link_guard.py`, `link_cycles.py`, `dep_oracle.py` and `tile_oracle.py`; runs `leak_check.py`; prints a summary.
Needs Python 3.9+ and Google Chrome (`CHROME_BIN` overrides the path). Without Chrome the browser suites print `SKIP` with a clear message and
the rest still runs. Add `--keep` to keep the generated pages (the path is printed). `DP_TRACE=1` prints tracebacks of exceptions inside tests.

Results: `PASS`, `FAIL`, `XFAIL` (expected to fail until a fix lands, see below), `XPASS` (an expected failure that now passes: turn the flag on), `SKIP`.

## Files

| File | What it is |
|---|---|
| `make_synthetic.py` | The fictitious payload, same schema and keys as `build/program_data.json`. Seeded, dates relative to today (Israel time), issue numbers from 90001. Seven projects: the first six share one random stream and one issue counter; INT (a reserved JQL word) is drawn last from its own stream, so adding it left every other project's records unchanged. Also `render_page` (the same single-placeholder substitution as `build_dashboard.render()`) and `canarify`. `python3 make_synthetic.py out.html` renders a page you can open. |
| `cdp.py` | A small Chrome DevTools driver (standard library only), temporary profile, free port, `wait_for` with a timeout. |
| `kit.py` | The tiny suite (PASS/FAIL/XFAIL/XPASS), the expectation flags, shared page helpers. |
| `mock_claude.js`, `probe.js` | The mocked `claude.use("mcp")` (the real shape of the Atlassian `searchJiraIssuesUsingJql` answer) and the in-page probe. The mock clears `dp.slowRuns` and `dp.slowData` at the start of every page (`CFG.keep` keeps them: the page is a reload of the previous one) and seeds the daily allowance with `CFG.sr`: `none`, `auto` (the first open of the day used), `one`, `used` (both clicks used), `yesterday`, `future`, `corrupt`, a raw string stored as it is, or an object such as `{"n": 0, "auto": 1}`; the Israel day is computed after the `CFG.shift` clock override. `CFG.ls`: `recent` seeds `dp.lastRefresh` and drops the page's automatic refresh (the case is about a click), `recentauto` seeds it and lets the automatic refresh run. The probe adds `dp.slowRuns` (`slowRaw`), `DATA.edctAt`, the Efficiency and Release Analysis notes and the 'Done Epics with No EDCT' row to the snapshot. |
| `harness.py` | The Refresh checks and the failure matrix (F15). |
| `canary.py` | The escaping canary (F16). |
| `link_oracle.py`, `jql_eval.py` | The link oracle (F14b) and the small JQL evaluator it uses. It also checks Cycle Time per Release (`cycle_time_per_release_*`): in six filter states the chart n, hover text, Release Analysis row, selected-release tile and the Jira link query (evaluated with `jql_eval.py` over the baked epics) equal an independent recount (Done, with an EDCT, Maintenance and SOW out, AI / not AI / empty all in, Flagged irrelevant; `cycle_time_per_release_ignores_the_flagged_field` flags Done epics and requires the same numbers), and six seeded defects must be caught (Maintenance or SOW counted again, non-AI dropped, the link losing the exclusion, the link keeping SOW, the link filtering on AI). |
| `link_guard.py` | The owner's rule: every Jira link is a query Jira recalculates, never a frozen list of keys (an allowlist names the few populations Jira cannot search, and may only shrink), and no link is longer than 6,000 characters (also with every team ticked). A quoted value is never an issue key (`n_keys` ignores it), so a pod label such as `POD-12` does not make a `labels in (...)` link a frozen list; the sweep also opens every list of the Pods block (the waiting-items key list of Waiting Dependents Due Soon is the one allowlist entry added for it, with its reason; its tooltip must say the list is exact). `tooltips_rendered_hovers_meet_the_word_budget_and_the_standard` reads the rendered hovers (about 2,600 distinct texts in 13 views, details opened, the Needs Attention panel expanded): the first block (the first two lines) is at most 25 words and there are at most 4 lines, except the documented exceptions (the EDCT sub line that `tile_oracle.py` asserts word for word, the exempt Issue Category list, the Needs Attention chip previews and the evidence of an item that meets two rules); a count of 1 never prints with a plural noun; no retired running-release wording; no hand-written "Opens N ... in Jira"; every `span.tt` is a keyboard stop with a name (the standard is in `program_dashboard/README.md`, "Tooltip standard"). |
| `link_cycles.py` | The Delivery Cycles links: for every release x project set x cycle x node x kind (Planned, Done, Overdue, Stale, Due next 7 days, Flagged, Carry-over, No planned date, Epics with Flags, weekly rows, After release end, pod rows, and the Pods kinds: `podEpics`, `podFlight`, `podWip`, and the links of the four proactive tiles: `nsSoon`, `nsSoonRfd`, `flightIn`, `noPodFlight`, `podNoneFlight`), the query the page builds is evaluated in Python over the baked epics and must find exactly the set of epics the page counts; the printed number of every link (also in the two opened pod lists) must equal its query's result; a link over the URL budget is plain text (also the in-flight union link of the Pods block); seeded defects must be caught (`<=` to `<`, a Target Sprint no longer excluded, 'more than 3' to '3 or more', In Progress only, Idle Pods ignoring the cycle, the union link without its project guard, a pod counted per team, and the eleven defects of the proactive tiles listed under `pod_oracle.py`). A variant payload reaches carry-over, planned after the release end, a Target Sprint the calendar does not know, and seeds fictitious pods (exactly 3 and exactly 4 in flight, 3 In Progress + 1 Validation, only Done, only outside the cycle, a label shared by two projects, case variants, one epic with two labels, an in-flight epic with no label, labels shaped like issue keys). Also: the strips hold exactly the tiles by `data-kpi` (five, then six pod tiles in the order nsSoon, wait, level, noPod, idle, wip, five in a detail view), the removed tiles and the two Overview columns are gone, and `cycles_pods_tiles_equal_an_independent_recount_in_every_view`. `cycles_links_caveat_is_in_how_this_is_calculated_not_on_every_number`: the caveat that Jira finds the epics again when a link is opened is said once, in the Links line of the Cycles How this is calculated, and on no number; no tooltip says it opens epics by key. |
| `dep_oracle.py` | The Blocked by External oracle (`dp=blocking`; the chip Blocked by Outside Scope is gone and `dp=blockedby` opens the default view): an independent Python recount of the open pairs where an item in scope (the dependent) waits on a provider whose Jira project is not a selected project and is not CXCROSS (whole keys: `OLDCXCROSS` counts; a CXCROSS provider, a provider in a selected project outside the release and a Done pair do not; every issue type in) over eight filter states (release, projects, a team, Commitment Types) and three quick filters. It compares the chip count and hover, the `Showing N of M open` line, the cards (keys of each card's Open with Dependents link), the Show data rows and the Direction column, the one headline number with the issues its link opens (the link is also run through the JQL evaluator over every issue of the payload and must return exactly the counted pairs' issues; its `project not in (...)` clause must name the selected projects and CXCROSS) and the 6,000 character budget, and the text cues (`Outside scope · `, `Blocks outside scope:` against `Also blocks outside scope:`, the key link's aria-label, `Planning data not tracked here`). Also: native radios in the one group (seven), no chip named Blocked by Outside Scope and `dp=blockedby` falling back to the default view without a console error, the hash round trip, 320 and 800 px wrapping with no sideways scroll, the headline clause omitted when zero, the empty state, the rule spelled out with fixed keys (CXCROSS, OLDCXCROSS, a selected project, an unselected tracked project), and eleven seeded defects that must each be caught (swapped direction, CXCROSS providers counted, selected-project providers counted, CXCROSS matched loosely, counts or board dropping non-epic providers, Done pairs counted, the Direction column swapped, the link's project clause without CXCROSS, a cue or the planning note dropped). `make_synthetic.py` adds fixed fictitious far-end issues and pairs for this (providers in untracked projects of every type, CXCROSS and OLDCXCROSS providers, a held epic of a selected project and of an unselected tracked project outside the release, Done pairs of both ends), without a random draw. |
| `tile_oracle.py` | The headline tiles EDCT Days and Epics by AI (`tiles_*`): both cover the **last 30 days**, the 30 days ending on the as-of day inclusive (`resolutiondate >= as-of minus 29 days AND < as-of plus 1 day`), with the 30 days before as the comparison ("Previous 30 days"); not the calendar month to date. For six as-of days (the 1st of a month, windows across a month, a year and a leap day) x seven filter states (Release and Commitment Type must not move the tiles) it recounts both tiles in Python from the baked epics (plus synthetic epics resolved on the window edges) and compares the value, sub lines, fact line, hover texts, labels and comparison; reads the bounds out of every tile link and evaluates each query with `jql_eval.py` to the same epics; checks that the Efficiency and AI Adoption charts stay on calendar periods. `tiles_oracle_selftest_*` seeds seven defects (calendar month instead of 30 days, a window ending a day early or a day late, 29 or 31 days, a previous window that overlaps, a calendar kicker) and requires the oracle to fail on each. |
| `pod_oracle.py` | The independent Python recount of the six Pods tiles (used by `link_cycles.py`): one pod = one label per project, case ignored; Idle Pods and Pods With More Than 3 Epics in Flight, and the four proactive tiles (`act_oracle`: Not-Started Epics Due Within 7 Days with the later of due date and Target Sprint end, Waiting Dependents Due Soon from the baked dependency links, Pods To Level by the 40% spread of the team's in-flight epics with at least 5 in flight, In-Flight Epics Without a Pod Label), each with its list rows, group headers and Jira links, recounted from the baked epics under the view's own filters (Release, Projects, Teams, Commitment Type incl. Stretch unticked), compared with the printed tiles, the two lists opened one after the other (rows, counts, alphabetical order, `aria-expanded`/`aria-controls`, a caption and scopes, focus kept on the button, a second click closes, the address unchanged) and the facts line and strip of the detail views. The thresholds (level 3, 7 days, 40%, minimum 5) are spelled in this file on purpose. The fixed cases they must hit (as-of + 0, 7 and 8 days, a later Target Sprint, Stretch; pods at 2/10/0, 3/2, 1/4, 2/2, 0/4, a single pod, 3/1/1 = exactly 40%, 4/2; providers with and without a pod, Done pairs, 7 and 8 days for the waiting item; pod labels shaped like issue keys) are in `make_synthetic.py` (`proactive_epics`, `proactive_deps`) and pinned by `cycles_the_fixed_proactive_cases_land_where_the_brief_puts_them`; seeded defects for each rule (7 -> 8 days, due date instead of later date, Stretch not excluded, 30% and 50%, no minimum, divide by the busiest, Done dependencies counted, provider without a pod counted as a pod, in flight without Validation, a changed label rule) must be caught. |
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
analysis text, capitalization values and teams, far-end issues, bugs under epics, the pod pattern). The page is loaded in 28 filter states (the URL hash), every
`details` (Show data) is opened, collapsed groups are expanded, the hover text of every mark is shown. After each: `window.__x` is undefined, no `img` with `src=x`
or `onerror`, no inline handler attribute and no script element beyond the template's own, no hostile node in the tooltip. A control test proves the detector fires on an
unescaped injection, and a test proves the payload is really rendered as text. The refresh path is covered with hostile strings in the mocked Jira responses.
Left untouched on purpose: project codes, release labels, issue keys, `jiraBase`, `cloudId`, `cfbAccount` (the page builds logic and URLs from them).

**Link oracle (F14b)**: under 29 filter states every `href` is checked for `NaN`, `undefined`, `null`, `[object` and for being well formed (https, the Jira host,
`/browse/KEY` or `/issues/?jql=` with parseable JQL). In the Open Bugs, CFB and Capitalization blocks the JQL of every link whose text is a number is
**evaluated in Python over the baked records** (`jql_eval.py`) and must match the printed number. Named tests cover the two Capitalization defects (Quarter mode
"All issues" and "no story points": no `NaN` date; Release mode "Not plotted" and "no story points": scoped). `links_reserved_project_key_INT_is_quoted_in_every_query` loads the page with INT selected, with INT among others and with everything selected, and requires every Jira query that names it to hold `"INT"` in quotation marks (INT is a reserved JQL word; `jql_eval.py` rejects a bare one as Jira does, and `mock_claude.js` answers a bare one with Jira's error, so a Refresh that forgets the quotes fails too). `oracle_selftest_catches_seeded_defects` copies the template,
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
