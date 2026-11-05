#!/usr/bin/env python3
"""Does the browser port of usage_report.py (program_dashboard/usage_view/*.js) give exactly what the Python report gives?

The port is literal, so the Python report is the oracle. For each fictitious scenario of fixtures.py the bundle is run in headless Chrome and compared stage by stage:

  model      UR.model_dump(new Model(bodies, ref, since, calendar, th)) against the Python Model's dump
  aggregate  UR.jsonable(UR.aggregate(bodies, opts)) (without `model`) against Python's aggregate(...) as JSON: every number, string and nested list
  blocks     each page block (_kpis, _trend, _breakdowns, _heatmap_block, _back_block, _health_block, _measure_block) and the helpers (_period, ribbon_text, export_warnings, il_stamp),
             given the PYTHON aggregate (so a block can be tested before the views are done)
  html       UR.html_report(UR.aggregate(...)) against html_report(...): the whole page, byte for byte

    python3 port_check.py [--stage model|aggregate|blocks|html] [--only SCENARIO_PART] [--diffs N] [--files core.js,views.js]

Exit code 0 only when every selected comparison is equal. A stage whose functions are not written yet is reported as MISSING (not as a pass).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTS = HERE.parent
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(TESTS.parent.parent / "program_dashboard"))
import kit  # noqa: E402
import fixtures as FX  # noqa: E402
import usage_bundle as UB  # noqa: E402
from kit import ctx  # noqa: E402


def deep_diff(exp, got, path="", out=None, tol=1e-9, limit=40):
    out = [] if out is None else out
    if len(out) >= limit:
        return out
    if isinstance(exp, dict) and isinstance(got, dict):
        for k in exp:
            if k not in got:
                out.append(f"{path}/{k}: missing in the port (expected {json.dumps(exp[k])[:120]})")
            else:
                deep_diff(exp[k], got[k], f"{path}/{k}", out, tol, limit)
        for k in got:
            if k not in exp:
                out.append(f"{path}/{k}: not in the Python result (port gave {json.dumps(got[k])[:120]})")
        ek, gk = list(exp), list(got)
        if not out and ek != gk:
            out.append(f"{path}: same keys, other order: python {ek[:8]} port {gk[:8]}")
    elif isinstance(exp, list) and isinstance(got, list):
        if len(exp) != len(got):
            out.append(f"{path}: length {len(exp)} expected, {len(got)} in the port; python {json.dumps(exp)[:100]} port {json.dumps(got)[:100]}")
        for i, (x, y) in enumerate(zip(exp, got)):
            deep_diff(x, y, f"{path}[{i}]", out, tol, limit)
    elif isinstance(exp, (int, float)) and isinstance(got, (int, float)) and not isinstance(exp, bool) and not isinstance(got, bool):
        if abs(exp - got) > tol * max(1, abs(exp)):
            out.append(f"{path}: {exp!r} expected, {got!r} in the port")
    elif exp != got:
        out.append(f"{path}: {json.dumps(exp)[:140]} expected, {json.dumps(got)[:140]} in the port")
    return out


def text_diff(exp: str, got: str, ctxw=90) -> str:
    n = next((i for i, (x, y) in enumerate(zip(exp, got)) if x != y), min(len(exp), len(got)))
    a, b = max(0, n - ctxw), n + ctxw
    return f"first difference at offset {n} (python {len(exp)} chars, port {len(got)}):\n    python: ...{exp[a:b]!r}\n    port:   ...{got[a:b]!r}"


def page_for(bundle: str, fx: dict) -> str:
    data = json.dumps({"opts": fx["opts"], "bodies": fx["bodies"], "a": fx["expected"]["a"]}).replace("</", "<\\/")
    safe = bundle.replace("</script", "<\\/script")
    return f"<!doctype html><meta charset=utf-8><body><script>window.__fx = {data};</script><script>{safe}</script></body>"


# What each stage runs inside the page; the page keeps the result in a JSON string.
JS_MODEL = """(() => { const f = window.__fx, o = f.opts;
  if (!UR.Model || !UR.model_dump) return JSON.stringify({__missing: 'Model and model_dump'});
  UR.set_min_group && UR.set_min_group(o.th.min_group);
  const cal = o.calendar && UR.parse_calendar ? UR.parse_calendar(o.calendar) : null;
  const m = new UR.Model(f.bodies, o.ref, o.since, cal, o.th);
  return JSON.stringify(UR.jsonable ? UR.jsonable(UR.model_dump(m)) : UR.model_dump(m)); })()"""
JS_AGG = """(() => { const f = window.__fx;
  if (!UR.aggregate || !UR.jsonable) return JSON.stringify({__missing: 'aggregate and jsonable'});
  const a = UR.aggregate(f.bodies, f.opts); const b = {}; for (const k of Object.keys(a)) if (k !== 'model') b[k] = a[k];
  return JSON.stringify(UR.jsonable(b)); })()"""
JS_HTML = """(() => { const f = window.__fx;
  if (!UR.aggregate || !UR.html_report) return JSON.stringify({__missing: 'aggregate and html_report'});
  return JSON.stringify(UR.html_report(UR.aggregate(f.bodies, f.opts))); })()"""
JS_BLOCKS = """(() => { const f = window.__fx, o = f.opts;
  const names = %s, out = {}, missing = [];
  // the blocks are given the Python aggregate (JSON) with a JS Model made from the same bodies, so each block can be tested before the views and signals exist
  if (!UR.Model) return JSON.stringify({__missing: 'Model (core.js)'});
  const cal = o.calendar && UR.parse_calendar ? UR.parse_calendar(o.calendar) : null;
  const a = Object.assign({}, f.a, {model: new UR.Model(f.bodies, o.ref, o.since, cal, o.th)});
  UR.set_min_group && UR.set_min_group(o.th.min_group);
  for (const n of names) { const fn = UR[n]; if (typeof fn !== 'function') { missing.push(n); continue; }
    try { out[n] = n === 'il_stamp' ? fn(o.as_of) : fn(a); } catch (e) { out[n] = {__error: String(e && e.stack || e).slice(0, 400)}; } }
  return JSON.stringify({out, missing}); })()"""
BLOCKS = ["_kpis", "_trend", "_breakdowns", "_heatmap_block", "_back_block", "_health_block", "_measure_block", "_period", "ribbon_text", "export_warnings", "il_stamp"]


def run_page(bundle: str, fx: dict, expr: str):
    ch = ctx.chrome
    url = ctx.write(page_for(bundle, fx), "port")
    ch.goto(url)
    time.sleep(0.2)
    errs = ch.console_errors()
    if ch.js("typeof UR") != "object":
        return None, errs
    raw = ch.js(expr)
    return json.loads(raw) if isinstance(raw, str) else raw, ch.console_errors()


def diffs_for(stage: str, fx: dict, bundle: str):
    """(status, differences) of one stage on one scenario: status 'ok', 'diff', 'missing' (not written yet) or 'load' (the bundle did not load or threw)."""
    exp = fx["expected"]
    expr = {"model": JS_MODEL, "aggregate": JS_AGG, "html": JS_HTML, "blocks": JS_BLOCKS % json.dumps(BLOCKS)}[stage]
    got, errs = run_page(bundle, fx, expr)
    if got is None:
        return "load", [f"the bundle did not load: {errs[:2]}"]
    if isinstance(got, dict) and "__missing" in got:
        return "missing", [f"{got['__missing']} not written yet"]
    if errs:
        return "load", [f"console error {errs[:2]}"]
    if stage == "model":
        d = deep_diff(exp["model"], got, "", None)
    elif stage == "aggregate":
        d = deep_diff(exp["a"], got, "", None)
    elif stage == "html":
        d = [] if got == exp["html"] else [text_diff(exp["html"], got)]
    else:
        d = []
        for n in BLOCKS:
            if n in got["missing"] or n not in exp["blocks"]:
                continue
            g = got["out"].get(n)
            if isinstance(g, dict) and "__error" in g:
                d.append(f"{n}: the port threw: {g['__error'][:300]}")
            elif exp["blocks"][n] != g:
                d.append(f"{n}: " + (text_diff(exp["blocks"][n], g) if isinstance(g, str) and isinstance(exp["blocks"][n], str) else "\n   " + "\n   ".join(deep_diff(exp["blocks"][n], g)[:3])))
        if got["missing"]:
            return "missing", [f"{', '.join(got['missing'])} not written yet"]
    return ("diff" if d else "ok"), d


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", choices=["model", "aggregate", "blocks", "html"], action="append", help="default: all four")
    ap.add_argument("--only", help="scenario name contains this")
    ap.add_argument("--diffs", type=int, default=6, help="differences printed per comparison")
    ap.add_argument("--files", help="comma list of the usage_view files to bundle (default: all that exist)")
    a = ap.parse_args()
    stages = a.stage or ["model", "aggregate", "blocks", "html"]
    bundle = UB.build_js(a.files.split(",") if a.files else None)
    fxs = FX.build(a.only)
    ok, missing, bad = 0, 0, 0
    try:
        for name, fx in fxs.items():
            for stage in stages:
                status, d = diffs_for(stage, fx, bundle)
                tag = f"{stage:9} {name}"
                if status == "missing":
                    missing += 1
                    print(f"MISSING {tag}: {d[0]}")
                elif status == "load":
                    bad += 1
                    print(f"FAIL  {tag}: {d[0]}")
                elif status == "diff":
                    bad += 1
                    print(f"FAIL  {tag}: {len(d)} difference(s)")
                    for line in d[: a.diffs]:
                        print("   " + line)
                else:
                    ok += 1
                    print(f"PASS  {tag}")
    finally:
        ctx.cleanup()
    print(f"\n{ok} equal, {bad} different, {missing} stage(s) missing")
    return 0 if bad == 0 and missing == 0 else 1


if __name__ == "__main__":
    ctx.template = kit.LIVE_TEMPLATE
    sys.exit(main())
