"""The browser port of usage_report.py: the five source files of program_dashboard/usage_view/ joined into one script.

The port is a literal translation (same names, same order, same output) so that the Python report is its exact oracle: tests/dashboard_browser/usage_port/port_check.py runs
this bundle in headless Chrome on the same fictitious exports and compares every number and the whole page with the Python report's.

    core.js      constants, date and number helpers, loading, the Model                (usage_report.py: constants to `class Model`)
    views.js     the views and `aggregate`                                              (the views, growth, habit, retention, health, daily, aggregate)
    signals.js   `detect_signals` and its evaluators                                    (detect_signals and the _eval_* functions)
    render_a.js  the page helpers, charts, key figures and the trend                    (CSS helpers to `_trend`)
    render_b.js  the read and use blocks, when people visit, come back, health, measure, `html_report`

The bundle defines `const UR = {...}`; `CSS` is the Python report's own style sheet, injected here so it exists once.
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "usage_view"
FILES = ["core.js", "views.js", "signals.js", "render_a.js", "render_b.js"]
EXPORTS = ["aggregate", "html_report", "model_dump", "jsonable", "set_min_group", "Model", "load_bodies", "load_export", "parse_calendar", "THRESHOLDS", "il_stamp", "ribbon_text",
           "export_warnings", "_period", "_kpis", "_trend", "_breakdowns", "_heatmap_block", "_back_block", "_health_block", "_measure_block", "detect_signals", "CSS"]


def build_js(files: list[str] | None = None) -> str:
    """The bundle: CSS (from usage_report.py), then the files in order, then the exports that exist (a missing one is simply absent, so a half-finished port can be tested part by part)."""
    import usage_report as UR
    parts = [f"const CSS = {json.dumps(UR.CSS)};\n"]
    for name in files or FILES:
        p = SRC / name
        if p.exists():
            parts.append(f"// ---- {name}\n" + p.read_text(encoding="utf-8") + "\n")
    ex = ", ".join(f"{n}: typeof {n} === 'undefined' ? undefined : {n}" for n in EXPORTS)
    return "const UR = (() => {\n\"use strict\";\n" + "".join(parts) + f"return {{{ex}}};\n}})();\n"


PLACEHOLDER = "/*__USAGE_REPORT_JS__*/"


def inline_into(fragment: str, calendar: dict | None = None) -> str:
    """Put the bundle where the template has its one placeholder line (the page is the only consumer; a template without it is left as it is).
    calendar: the build's usage calendar (release W1 and end of W6, sprint boundaries: dates and numbers only), given to the report so it can mark them."""
    if PLACEHOLDER not in fragment:
        return fragment
    assert fragment.count(PLACEHOLDER) == 1
    js = (f"const UR_CALENDAR = {json.dumps(calendar, separators=(',', ':'))};\n" if calendar else "") + build_js()
    return fragment.replace(PLACEHOLDER, js.replace("</script", "<\\/script"))
