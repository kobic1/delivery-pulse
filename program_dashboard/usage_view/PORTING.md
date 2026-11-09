# Porting usage_report.py to the browser (the rules every file follows)

Goal: the owner's live Usage view in the dashboard page shows the SAME report as `usage_report.py` makes (key figures, trend, reach, controls, devices, when people visit, come back,
recording health, how it is measured), computed in the browser from the `usage` records. The port is LITERAL so that the Python report is its exact oracle.

## Rules
1. **Same names.** Functions, classes, methods, attributes, constants and dict keys keep the Python name (snake_case, leading underscores). Same logic in the same order, same strings, same
   rounding, same HTML byte for byte. Do not simplify, reorder or "improve". If the Python looks wrong, port it as it is and tell the owner of the task (it is the oracle).
2. **Files.** Each file defines top-level `function` / `const` / `class` declarations in ONE shared scope (the build wraps all files in one function; see `usage_bundle.py`). No `export`, no
   imports, no `window.`, no DOM, no network: pure functions of their arguments (`document` is NOT available to the oracle's page logic). Do not edit another file; ask the owner.
3. **Data shapes.**
   - `dt.date` -> `'YYYY-MM-DD'` string (ISO strings sort and compare correctly with `<`, `>`, `===`). `dt.datetime` (tz-aware, Israel) -> ISO string with offset, e.g. `'2026-10-29T17:00:00+03:00'`.
   - `set` -> JS `Set` internally; in RESULTS (below) sorted arrays. `tuple` -> array. `None` -> `null` (use `null`, never `undefined`, in results). `True/False` -> booleans.
   - A Python dict with string keys -> plain object. A dict whose keys are ints, dates or tuples -> `Map` internally (a JS object would reorder integer-like keys and stringify the rest).
   - **Results are plain JSON.** `aggregate(...)` returns exactly the structure Python returns, as plain JSON-able values (objects with string keys, arrays, numbers, strings, booleans, null),
     except `model`, which is the `Model` instance. So `jsonable(a)` is nearly the identity (it converts any Set/Map/undefined left behind). Python int dict keys become string keys in JSON:
     renderers read them as strings (`d["0"]`). Dates inside results are ISO strings.
   - Python set iteration order is NOT insertion order; where the Python output depends on it, it sorts, and so must the port. Python `sorted` is stable and compares like Python (numbers, strings, tuples
     element by element): use `cmp_py`.
4. **Python semantics that JS gets wrong** (core.js provides these; use them, never `Math.round`, `toFixed`, `String(x)` for floats, `localeCompare`):
   `pyround(x, nd=0)` (round half to even on the exact value, like `round`), `rnd(x)` (the report's own), `pystr(x)` (`str()` of number/bool/null/string: `3.0` is `'3.0'`, `0.5` is `'0.5'`, `1e-05`),
   `pyfmt(x, spec)` (Python format-spec mini language for the specs the report uses: `.1f`, `,`, `.0%`, `d`, ...; Python `format(0.5, '.0f')` is `'0'`, `toFixed` gives `'1'`),
   `median(xs)` (statistics.median), `percentile` is the report's own, `cmp_py(a, b)`, `html_escape(x)` and `e(x)` (`html.escape(str(x), quote=True)`: `&`, `<`, `>`, `"` and `'` -> `&#x27;`),
   set helpers `set_union(...sets)`, `set_inter(a, b)`, `set_diff(a, b)`, `sorted_set(s)`.
   Dates (strings): `d_add(d, days)`, `d_diff(a, b)` (= `(a - b).days`), `d_weekday(d)` (Monday 0 ... Sunday 6, like `date.weekday()`), `d_isocalendar(d)` -> `[year, week, weekday 1..7]`, `d_min` (`'0001-01-01'`),
   `EPOCH` (`'1970-01-01'`), `dt_il_date(iso_datetime)` (the Israel date of a datetime), `dt_il_parts(iso_datetime)` -> `{year, month, day, hour, minute, second, offset_minutes, weekday}` (Israel time, DST
   as the tz database has it, via `Intl`), `dt_strftime(iso_datetime, fmt)` for the formats the report uses, `dt_isoformat`.
5. **Globals.** `set_min_group(n)` changes `MIN_USERS` and `SMALL` for the run, exactly like Python (module-level `let`).
6. **Out of scope:** `demo_*`, `text_report`, the CLI (`main`, `parse_as_of`, `load_thresholds`), `coverage_text` (used by text_report only; port it only if `html_report` reaches it). The style sheet `CSS`
   already exists in the bundle (injected from Python): use it as the Python does.
7. **Quality bar = the oracle.** `python3 tests/dashboard_browser/usage_port/port_check.py --stage STAGE [--only SCENARIO]` compares against the Python report on 20 fictitious scenarios (see its header). Work
   until your stage is equal on ALL scenarios; a comparison that is not equal is a bug in the port, never a reason to change the oracle or the tests. Fix the root cause: do not special-case a scenario.
8. No commits, no pushes, no edits outside your own files (plus scratch files in the scratchpad). Do not run the full browser suites. Report: what is done, the exact commands you ran and their last lines, and
   every place where the Python behaviour could not be matched or looked wrong.

## Files and Python line ranges (usage_report.py, as of this branch)
| file | Python lines | holds |
| --- | --- | --- |
| core.js | 1-612, 1025-1030 | constants, THRESHOLDS, helpers, loading, `Model`, `parse_calendar`, the Python-semantics helpers of rule 4, `jsonable`, `model_dump`, `load_export`/`load_bodies` (db records need no dedupe: keep the checks and the stats) |
| signals.js | 610-1030 | `_weeks_phrase`, `_confidence`, `_persist`, `_eval_*`, `detect_signals`, `_s7` |
| views.js | 1031-1488 | growth, habit, retention, sections, controls, use, health, calendar, event_windows, daily, `aggregate` |
| render_a.js | 1740-2618 | `export_warnings`, the chart and figure helpers, `device_*`, `_kpis`, `_chart_weeks`, `_week_table`, `_chart_days`, `_trend` |
| render_b.js | 2619-3160 | `_read_block` ... `_measure_block`, `ribbon_text`, `_period`, `html_report` |

`core.js` must contain the helper API of rules 3-5 and the `Model` FIRST (the other files depend on it): write those first and keep the file loadable at every step.
Stages of the oracle: `model` (core), `aggregate` (core + signals + views), `blocks` (a render file, needs core only), `html` (everything).
