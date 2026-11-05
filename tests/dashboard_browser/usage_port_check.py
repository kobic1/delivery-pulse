#!/usr/bin/env python3
"""The browser port of usage_report.py against the Python report (the oracle), as a suite of the browser runner.

program_dashboard/usage_view/*.js is a literal port of the Python usage report, so the Python report decides what is right. Each test runs the bundle (program_dashboard/usage_bundle.py, the same code the
page build inlines) in headless Chrome on the fictitious exports of usage_port/fixtures.py and compares:
  model      the Model (every week's people, sections, controls, baselines, regimes) with the Python Model's dump
  aggregate  every number, string and list of `aggregate(...)` (14 scenarios: thresholds, audience, since, calendar, empty, v1-only, young, stale, Sunday, rollover)
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


if __name__ == "__main__":
    sys.exit(kit.cli(SUITE, __doc__))
