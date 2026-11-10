#!/usr/bin/env python3
"""The browser port of usage_report.py against the Python report (the oracle), as a suite of the browser runner.

program_dashboard/usage_view/*.js is a literal port of the Python usage report, so the Python report decides what is right. Each test runs the bundle (program_dashboard/usage_bundle.py, the same code the
page build inlines) in headless Chrome on the fictitious exports of usage_port/fixtures.py and compares:
  model      the Model (every week's people, sections, controls, baselines, regimes) with the Python Model's dump
  aggregate  every number, string and list of `aggregate(...)` (27 scenarios: thresholds, audience, since, calendar, empty, v1-only, young, stale, Sunday, rollover, the week-so-far block in every state, and the key-figure strips with their incomplete weeks)
  blocks     each page block (_kpis, _trend, _breakdowns, _heatmap_block, _back_block, _health_block, _measure_block) and the helpers, byte for byte
  html       the whole page, byte for byte
  mutations  the demo export changed so that every signal fires (S0 to S9), under four threshold sets, with duplicates and a calendar, and 16 randomly generated exports: aggregate and page equal
The tools behind it, for a failure: usage_port/port_check.py (prints the first differences) and usage_port/port_mutations.py.

    python3 usage_port_check.py [--live] [--only NAME]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "usage_port"))
import kit                                                                          # noqa: E402
import fixtures as FX                                                               # noqa: E402
import port_check as PC                                                             # noqa: E402
import port_mutations as PM                                                         # noqa: E402
import usage_bundle as UB                                                           # noqa: E402
from kit import T                                                                   # noqa: E402

SUITE = kit.Suite("Delivery Pulse usage report port")


def _stage(stage: str):
    @SUITE.test(f"usage_port_{stage}_equals_the_python_report_on_every_scenario")
    def _(t: T):
        bundle = UB.build_js()
        for name, fx in FX.build().items():
            status, d = PC.diffs_for(stage, fx, bundle)
            t.check(status == "ok", f"{stage} {name}: {status}: " + " | ".join(x[:300] for x in d[:3]))


for _s in ("model", "aggregate", "blocks", "html"):
    _stage(_s)


@SUITE.test("usage_port_mutated_and_random_exports_equal_the_python_report")
def _(t: T):
    os.environ.setdefault("PORT_FUZZ", "16")
    n, failures, flagged = PM.run(quiet=True)
    t.check(n >= 50, f"only {n} mutated scenarios ran")
    for name, d in failures:
        t.check(False, f"{name}: " + " | ".join(x[:300] for x in d[:2]))
    fired = {k for k, _ in flagged.items()}
    missing = {f"S{i}" for i in range(10)} - fired
    t.check(not missing, f"the mutations no longer make every signal fire: missing {sorted(missing)}")
    t.note(f"{n} scenarios, signals fired: {dict(sorted(flagged.items()))}")


WTD_DEFECTS = [
    ("the previous window is the whole previous week", "aggregate", "const prev_rows = m.visits(prev_lo).filter((r) => r.day <= prev_hi);", "const prev_rows = m.visits(prev_lo);"),
    ("data starting inside the previous window is called a full comparison", "aggregate", 'else if (m.data_start && m.data_start > prev_lo) state = "partial";', 'else if (false) state = "partial";'),
    ("a difference printed against a withheld figure", "aggregate", " && sc !== SMALL && sp !== SMALL ?", " ?"),
    ("a percentage on a previous figure under the minimum denominator", "aggregate", "pct: d ? pct_of(Math.abs(d), prev_val, th) : null", "pct: d && prev_val ? rnd(100 * Math.abs(d) / prev_val) : null"),
    ("the block is not drawn under the weekly chart", "html", ' + _wtd_block(a["wtd"]), show_data(_week_table(a))', ", show_data(_week_table(a))"),
    ("a verdict word in the sentence", "html", "today still in progress) against the same days last week (", "today still in progress) a decline against the same days last week ("),
]


@SUITE.test("usage_port_week_so_far_block_is_exercised_in_every_state_and_a_defect_in_the_port_is_caught")
def _(t: T):
    fx = FX.build()
    w = {n: f["expected"]["a"]["wtd"] for n, f in fx.items()}
    t.check({"ok", "partial", "no_baseline", "no_current"} <= {x["state"] for x in w.values()}, f"the scenarios no longer cover every state: {sorted({x['state'] for x in w.values()})}")
    t.check(any(x["state"] == "ok" and x["n"] == 0 for x in w.values()), "no scenario reads the data on a Sunday with a session")
    t.check(any(x["people"]["cur"] == "<5 users" and x["people"]["diff"] is None for x in w.values()), "no scenario has a withheld figure")
    t.check(any(x["rules_changed"] for x in w.values()), "no scenario has a change of recording rules between the two windows")
    t.check(all('id="wtd"' in f["expected"]["html"] for n, f in fx.items() if f["expected"]["a"]["n_sessions"]), "a page without the week-so-far block")
    bundle = UB.build_js()
    for name, stage, old, new in WTD_DEFECTS:
        t.check(bundle.count(old) == 1, f"the seeded defect '{name}' no longer matches the port exactly once")
        mutant = bundle.replace(old, new)
        caught = [n for n, f in fx.items() if PC.diffs_for(stage, f, mutant)[0] != "ok"]
        t.check(bool(caught), f"the seeded defect '{name}' in the port was not caught by the {stage} comparison")


STRIP_DEFECTS = [
    ("a hatched point drawn as a solid one", "html", '<i class="ld pt" aria-hidden="true"', '<i class="ld" aria-hidden="true"'),
    ("the week in progress left out of the strips", "html", 'if (m.by_week.has(m.cur) && m.regime(m.cur) === rg && !(m.cur === m.rollover && rg === "v2")) out.push([m.cur, true]);', "if (false) out.push([m.cur, true]);"),
    ("the provisional first week left out of the strips", "html", "m.first_week === d_add(run[0], -7) && m.regime(m.first_week) === rg0) out.unshift", "false) out.unshift"),
    ("a group under the minimum drawn in the week in progress (the count, not the guarded figure)", "html", 'sser["people"].set(w, v["people"]);', 'sser["people"].set(w, v["n"]);'),
    ("a strip label that does not say it holds partial weeks", "html", "weeks including ${incl}${tail}.", "weeks${tail}."),
    ("the incomplete weeks leak into the changes and the table", "html", "const run = _comparable_run(m);\n  const grow", "const run = _strip_weeks(m).map(x => x[0]);\n  const grow"),
    ("a strip needs three points again", "html", "if (pts.length < 2) return", "if (pts.length < 3) return"),
]


@SUITE.test("usage_port_key_figure_strips_are_exercised_with_incomplete_weeks_and_a_defect_in_the_port_is_caught")
def _(t: T):
    fx = FX.build()
    html = {n: f["expected"]["html"] for n, f in fx.items()}
    drawn = [n for n, h in html.items() if 'class="ld pt"' in h]
    t.check(len(drawn) >= 5, f"too few scenarios draw a hatched point: {drawn}")
    t.check(any("including the partial first week and the week so far, ending at" in h for h in html.values()), "no scenario draws both incomplete weeks")
    t.check(any("including the week so far, ending at" in h for h in html.values()), "no scenario draws only the week so far")
    t.check(any("including the partial first week, ending at" in h for h in html.values()), "no scenario draws only the provisional first week")
    t.check(any("weeks including the partial first week and the week so far" in h and "last 2 weeks" in h for h in html.values()), "no scenario draws exactly two incomplete points")
    t.check(all('id="strip-note"' in h for n, h in html.items() if 'class="ld pt"' in h) and not any('id="strip-note"' in h for n, h in html.items() if 'class="ld pt"' not in h), "the note is there exactly when a hatched point is")
    bundle = UB.build_js()
    for name, stage, old, new in STRIP_DEFECTS:
        t.check(bundle.count(old) == 1, f"the seeded defect '{name}' no longer matches the port exactly once")
        mutant = bundle.replace(old, new)
        caught = any(PC.diffs_for(stage, f, mutant)[0] != "ok" for n, f in sorted(fx.items(), key=lambda kv: not kv[0].startswith("strip_")))
        t.check(caught, f"the seeded defect '{name}' in the port was not caught by the {stage} comparison")


if __name__ == "__main__":
    sys.exit(kit.cli(SUITE, __doc__))
