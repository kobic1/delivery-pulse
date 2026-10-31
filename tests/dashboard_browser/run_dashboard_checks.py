#!/usr/bin/env python3
"""One entry for the Delivery Pulse checks.

  1. tests/test_program_dashboard.py and tests/test_definitions_contract.py with pytest (the collector's unit tests and the collector/page contract);
  2. the fictitious fixture: built twice (it must be identical), rendered into the template under test;
  3. the browser suites in headless Chrome: harness.py (Refresh and the failure matrix), canary.py (escaping), link_oracle.py (links);
  4. leak_check.py (nothing real in this folder, when a real payload is on the machine);
  5. a pass/fail summary. Exit code 1 on any FAIL. Tests that are expected to fail until a fix lands (XFAIL) are listed apart and
     do not fail the run unless --strict.

    python3 tests/dashboard_browser/run_dashboard_checks.py                    # the frozen v52 template
    python3 tests/dashboard_browser/run_dashboard_checks.py --live             # the live program_dashboard/dashboard.template.html
    python3 tests/dashboard_browser/run_dashboard_checks.py --expect DEADLINE  # a fix has landed: its test must now pass
    python3 tests/dashboard_browser/run_dashboard_checks.py --strict           # XFAIL counts as a failure

Without Google Chrome the browser suites are skipped with a clear message (set CHROME_BIN to point at it); pytest and the fixture check still run.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
import kit                                                                          # noqa: E402
import make_synthetic as MS                                                         # noqa: E402

SUITES = [("harness", "harness.py"), ("canary", "canary.py"), ("link oracle", "link_oracle.py"), ("link guard", "link_guard.py")]


def step_pytest() -> dict:
    t0 = time.time()
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run([sys.executable, "-m", "pytest", "tests/test_program_dashboard.py", "tests/test_definitions_contract.py", "-q", "-p", "no:cacheprovider"], cwd=REPO, capture_output=True, text=True, env=env)
    lines = [l for l in p.stdout.strip().splitlines() if l.strip()]
    summary = next((l for l in reversed(lines) if " passed" in l or " failed" in l or "error" in l.lower()), lines[-1] if lines else p.stderr.strip()[-200:])
    ok = p.returncode == 0
    print(f"{'PASS' if ok else 'FAIL':<6} pytest collector + definitions contract: {summary.strip('= ')}  [{time.time() - t0:.1f}s]")
    if not ok:
        print("\n".join("         " + l for l in lines[-25:]))
    return {"name": "pytest collector + definitions contract", "ok": ok, "detail": summary}


def step_fixture(template: Path) -> dict:
    t0 = time.time()
    a, b = MS.make(), MS.make()
    same = json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    page = MS.render_page(a, template)
    ok = same and "/*__DATA__*/null" not in page and len(page) > 100_000
    print(f"{'PASS' if ok else 'FAIL':<6} fictitious fixture: {len(a['epics'])} epics, {len(a['bugs'])} bugs, {a['cap']['rows'].count(';') + 1} capitalization rows; deterministic: {same}; "
          f"rendered into {template.parent.name}/{template.name} ({len(page) // 1024} KB)  [{time.time() - t0:.1f}s]")
    return {"name": "fixture", "ok": ok, "detail": f"deterministic={same}"}


def run_suite(label: str, script: str, args: list[str], env: dict) -> list[dict] | None:
    out = Path(tempfile.mkdtemp(prefix="dp-run-")) / "r.json"
    print(f"\n--- {label} ({script}) ---", flush=True)
    p = subprocess.run([sys.executable, str(HERE / script), "--json", str(out), *args], env=env)
    if not out.exists():
        print(f"FAIL   {script} produced no result (exit code {p.returncode})")
        return [{"name": f"{label}: no result", "status": "FAIL", "failures": [f"exit code {p.returncode}"], "notes": [], "detail": ""}]
    data = json.loads(out.read_text())
    if data.get("skipped"):
        if "--strict" in args or os.environ.get("CI"):          # a gate that cannot run is not a pass
            print(f"FAIL   {label}: {data['skipped']} (not allowed to skip under --strict or CI)")
            return [{"name": f"{label}: could not run", "status": "FAIL", "failures": [data["skipped"]], "notes": [], "detail": ""}]
        print(f"SKIP   {label}: {data['skipped']}")
        return None
    return data["results"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true", help="test the live repo template instead of the frozen v52 copy")
    ap.add_argument("--template", help="a dashboard.template.html to test")
    ap.add_argument("--strict", action="store_true", help="XFAIL (expected to fail until a fix lands) counts as a failure")
    ap.add_argument("--expect", action="append", default=[], help="turn an expectation flag on (DEADLINE, REAL_ERROR_TEXT, ATOMIC_CAP, CURSOR_GUARD); repeatable")
    ap.add_argument("--skip-pytest", action="store_true")
    ap.add_argument("--only", help="run only tests whose name contains this text (browser suites)")
    ap.add_argument("--keep", action="store_true", help="keep the generated pages")
    a = ap.parse_args()
    template = Path(kit.LIVE_TEMPLATE if a.live else (a.template or kit.FROZEN / "dashboard.template.html"))
    args = ["--template", str(template)]
    for e in a.expect:
        args += ["--expect", e]
    if a.strict:
        args.append("--strict")
    if a.only:
        args += ["--only", a.only]
    if a.keep:
        args.append("--keep")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    t0 = time.time()
    steps, all_results = [], []
    print(f"Delivery Pulse checks on {template}" + (" (strict)" if a.strict else ""))
    if not a.skip_pytest:
        steps.append(step_pytest())
    steps.append(step_fixture(template))
    for label, script in SUITES:
        res = run_suite(label, script, args, env)
        if res:
            all_results += [dict(r, suite=label) for r in res]
    leak = subprocess.run([sys.executable, str(HERE / "leak_check.py")], env=env, capture_output=True, text=True)
    print("\n" + leak.stdout.strip())
    steps.append({"name": "leak check", "ok": leak.returncode == 0, "detail": leak.stdout.strip()})

    c = {}
    for r in all_results:
        c[r["status"]] = c.get(r["status"], 0) + 1
    print("\n================ summary ================")
    for s in steps:
        print(f"{'PASS' if s['ok'] else 'FAIL':<6} {s['name']}")
    for status in ("FAIL", "XFAIL", "XPASS", "SKIP"):
        rows = [r for r in all_results if r["status"] == status]
        if rows:
            print(f"\n{status} ({len(rows)}):")
            for r in rows:
                print(f"  [{r['suite']}] {r['name']} {r.get('detail', '')}")
                for f in r["failures"][:4]:
                    print(f"      - {f[:230]}")
    print(f"\nbrowser tests: " + (", ".join(f"{c[k]} {k}" for k in ("PASS", "FAIL", "XFAIL", "XPASS", "SKIP") if c.get(k)) or "none run") + f"   [{time.time() - t0:.0f}s]")
    bad = any(not s["ok"] for s in steps) or c.get("FAIL", 0) > 0 or (a.strict and c.get("XFAIL", 0) > 0)
    print("RESULT: " + ("FAIL" if bad else "PASS") + (f" (XFAIL tests are expected failures; --strict would fail on them)" if c.get("XFAIL") and not a.strict else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
