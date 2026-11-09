#!/usr/bin/env python3
"""Mutations of the fictitious export: does the port still equal the Python report when the data makes the signals fire?

The scenarios of fixtures.py never flag every signal. Here the demo export is changed in the ways that make S0 (fewer people), S1 (a surge of new people), S3/S4 (a section or control dropped or newly
used), S5 (page errors), S6 (old page versions), S7 (stale or pruned records, dropped keys), S8/S9 (snapshot and stale data) fire, each under four threshold sets (show-all, defaults, min group 1 and 10),
plus an export with duplicates, a round page and an unknown schema, and one with a calendar. For each the aggregate (every number) AND the whole page must equal Python's.

    python3 port_mutations.py [NAME_PART]
"""
from __future__ import annotations
import sys, copy, random, datetime as dt, json, collections
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent)); sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent.parent.parent / "program_dashboard"))
import kit, fixtures as FX, usage_bundle as UB, port_check as PC
import usage_report as UR
from kit import ctx
REF = FX.REF

def sessions(b):
    for wk, ds in b["w"].items():
        for d, ss in ds.items():
            for sid, s in ss.items():
                yield d, s

def mut_s0_fewer(bodies):
    # drop all sessions of the last completed week for 80% of the people
    out = copy.deepcopy(bodies); lo, hi = "2026-10-18", "2026-10-24"
    for i, b in enumerate(out):
        if i % 5:
            for wk in list(b["w"]):
                for d in list(b["w"][wk]):
                    if lo <= d <= hi: del b["w"][wk][d]
    return [b for b in out if any(b["w"][w] for w in b["w"])]
def mut_errors(bodies):
    out = copy.deepcopy(bodies)
    for i, b in enumerate(out):
        for d, s in sessions(b):
            if "2026-10-18" <= d <= "2026-10-24" and i % 2 == 0: s["er"] = 1
            if "2026-10-11" <= d <= "2026-10-17" and i % 3 == 0: s["er"] = 2
    return out
def mut_old_bt(bodies):
    out = copy.deepcopy(bodies)
    for i, b in enumerate(out):
        for d, s in sessions(b):
            s["bt"] = 20000 + (0 if i % 3 else -30) + (1 if d > "2026-10-20" else 0)
    return out
def mut_snap(bodies):
    out = copy.deepcopy(bodies)
    for i, b in enumerate(out):
        for d, s in sessions(b):
            s["lv"] = 1 if i % 2 else 0; s["fa"] = 3 if i % 3 == 0 else 0
    return out
def mut_stop(bodies):
    out = copy.deepcopy(bodies)
    for i, b in enumerate(out):
        for d, s in sessions(b):
            if d >= "2026-10-11" and s.get("f"): s["f"] = {k: v for k, v in s["f"].items() if k != "teams"}
    return out
def mut_new(bodies):
    out = copy.deepcopy(bodies)
    for i, b in enumerate(out):
        for d, s in sessions(b):
            if d < "2026-10-18" and s.get("f"): s["f"] = {k: v for k, v in s["f"].items() if k != "multi"}
    return out
def mut_stale(bodies):
    out = copy.deepcopy(bodies)
    for i, b in enumerate(out[:3]): b["last"] = "2026-05-01"
    for i, b in enumerate(out[3:5]): b["pr"] = 1
    for i, b in enumerate(out[5:20]):
        for d, s in sessions(b): s["x"] = 3
    return out
def mut_s1(bodies):
    out = copy.deepcopy(bodies)
    for b in out[:30]:
        pass
    # make 15 people first seen in the last completed week
    for b in out[-15:]:
        for wk in list(b["w"]):
            for d in list(b["w"][wk]):
                if d < "2026-10-18": del b["w"][wk][d]
        b["first"] = "2026-10-18"
    return [b for b in out if any(b["w"][w] for w in b["w"])]
def mut_all(bodies):
    return mut_snap(mut_old_bt(mut_errors(bodies)))

BASE = lambda n=0, **k: dict(bodies=UR.demo_bodies(REF, **k), today=REF)
muts = {"s0_fewer": mut_s0_fewer, "errors": mut_errors, "old_bt": mut_old_bt, "snap": mut_snap, "stop": mut_stop, "new": mut_new, "stale": mut_stale, "s1": mut_s1, "all": mut_all}
def scen():
    sa = dict(UR.SHOW_ALL)
    for name, f in muts.items():
        for thn, th in (("sa", FX._thresholds(sa)), ("def", FX._thresholds(None)), ("mg1", FX._thresholds({**sa, "min_group": 1})), ("mg10", FX._thresholds({"min_group": 10}))):
            yield f"{name}_{thn}", dict(bodies=f(UR.demo_bodies(REF)), today=REF + dt.timedelta(days=(4 if name == "stale" else 0)), th=th, as_of=FX.NOW)
    yield "dups_roundpage", dict(bodies=UR.demo_bodies(REF), today=REF, th=FX._thresholds(dict(UR.SHOW_ALL)), as_of=FX.NOW, _stats=dict(read=100, skipped=2, duplicates=3, unknown_schema=1, no_id=0, round_page=True))
    rnd = random.Random(20261105)                                       # a spread of whole generated exports: sizes, recording regimes and thresholds vary, so a figure that is a whole number only by chance still gets tested
    for i in range(int(__import__("os").environ.get("PORT_FUZZ", "16"))):
        seed, v2 = rnd.randrange(1, 10_000), rnd.choice([0, 3, 6, 9, 99])
        ref = REF + dt.timedelta(days=rnd.choice([0, 0, 1, 2, 3, 5, 6]))
        th = rnd.choice([FX._thresholds(dict(UR.SHOW_ALL)), FX._thresholds(None), FX._thresholds({"min_group": 3}), FX._thresholds({**UR.SHOW_ALL, "min_group": 2})])
        yield f"fuzz_{i:02d}_seed{seed}_v2{v2}", dict(bodies=UR.demo_bodies(ref, seed=seed, v2_from=v2), today=ref, th=th, as_of=dt.datetime(ref.year, ref.month, ref.day, rnd.choice([8, 12, 17, 23]), 5, tzinfo=FX.IL))
    yield "caltest", dict(bodies=UR.demo_bodies(REF), today=REF, th=FX._thresholds(dict(UR.SHOW_ALL)), calendar=FX.CALENDAR)

def run(only: str | None = None, quiet: bool = False):
    """Every mutated scenario: (number run, list of failing names with their first differences, the signals that fired)."""
    bundle = UB.build_js()
    flagged = collections.Counter(); failures = []; n = 0
    for name, s in scen():
        if only and only not in name: continue
        st = s.pop("_stats", None)
        o = FX.opts_of(s)
        if st: o["stats"] = st
        cal = UR.parse_calendar(s["calendar"]) if s.get("calendar") else None
        a = UR.aggregate(s["bodies"], today=s["today"], as_of=dt.datetime.fromisoformat(o["as_of"]), now=dt.datetime.fromisoformat(o["now"]), demo=False, since=None, audience=None, calendar=cal, th=s["th"], stats=o["stats"])
        b = {k: v for k, v in a.items() if k != "model"}
        exp = FX.jsonable(b)
        fx = {"opts": o, "bodies": s["bodies"], "expected": {"a": exp}}
        got, errs = PC.run_page(bundle, fx, PC.JS_AGG)
        n += 1
        html_py = UR.html_report(a)
        html_js, errs2 = PC.run_page(bundle, fx, PC.JS_HTML)
        for r in exp["signals"]["flagged"]: flagged[r["id"]] += 1
        if got is None or errs:
            failures.append((name, [f"load error {errs[:2]}"])); continue
        d = PC.deep_diff(exp, got, "", None)
        if html_js != html_py:
            d.append("html: " + PC.text_diff(html_py, html_js if isinstance(html_js, str) else str(html_js)))
        if d:
            failures.append((name, d[:5]))
            if not quiet: print("DIFF", name, len(d)); [print("   ", x) for x in d[:5]]
        elif not quiet: print("ok  ", name)
    return n, failures, flagged


def main():
    try:
        n, failures, flagged = run(sys.argv[1] if len(sys.argv) > 1 else None)
    finally:
        ctx.cleanup()
    print(n, "run,", len(failures), "different; flagged ids covered:", sorted(flagged.items()))
    return 1 if failures else 0


if __name__ == "__main__":
    ctx.template = kit.LIVE_TEMPLATE
    sys.exit(main())
