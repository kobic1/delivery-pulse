#!/usr/bin/env python3
"""Baseline equality: the page with every Delivery Cycle ticked (the default) renders exactly what an earlier build of the template rendered.

Used when a filter is added or removed (the Delivery Cycle filter replaced the Commitment Type filter): the earlier template is the baseline, both templates
are rendered with the SAME fictitious payload (or, on a developer's machine, a real one with --payload) and loaded in headless Chrome in several states
(Release x Projects x Teams x the Cycles section's own cycle); the whole page body outside the filter bar (every number, hover text, link and chart label: the
HTML of <main> without #filters) must be identical. The few sentences that were reworded on purpose are listed in REWORDED, so every deliberate difference of
the default state is written down here and nothing else may differ.

    python3 baseline_equality.py --baseline REV_OR_FILE [--template FILE | --live] [--payload program_data.json] [--quick]

REV_OR_FILE is a file or a git revision ("origin/dp-pod-proactive-kpis"). It is not part of run_dashboard_checks.py: a baseline is only meaningful while the change under
review is the only difference between the two templates.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kit                                                                          # noqa: E402
import link_cycles as LC                                                            # noqa: E402
import make_synthetic as MS                                                         # noqa: E402
from cdp import Chrome                                                              # noqa: E402

REPO = HERE.parent.parent

# (old, new): the sentences of the earlier build that named the removed Commitment Type filter, as the new build words them. Applied to the BASELINE html before comparing.
REWORDED: list[tuple[str, str]] = [
    ("the selected release and the Commitment Type, Projects and Teams filters; bug rules", "the selected release and the Projects and Teams filters; bug rules"),
    (" The Commitment Type filter does not change it.", ""),
    (" The Commitment Type checkboxes do not change the target scope.", ""),
    (" The Commitment Type checkboxes do not change it. A share needs", " A share needs"),
    ("The chart follows Projects and Teams, not Commitment Type.", "The chart follows Projects and Teams."),
    ("The Cycles section counts every Commitment Type selected in the filter.", "The Cycles section counts every Commitment Type."),
    ("Release and Commitment Type filters do not apply. The Priority", "The Release filter does not apply. The Priority"),
    ("outside the chosen release, projects, teams and Commitment Types. This is separate", "outside the chosen release, projects and teams. This is separate"),
    ("in the chosen release, teams and Commitment Types, waits on", "in the chosen release and teams, waits on"),
    ("outside the release, team or Commitment Type filters, is not counted", "outside the release or team filters, is not counted"),
    ("this provider is not in the chosen release, projects, teams and Commitment Types", "this provider is not in the chosen release, projects and teams"),
    ("Teams and Commitment Type do not apply: a Capability has neither,", "Teams do not apply: a Capability has no team,"),
    ("Teams and Commitment Type do not apply. A dashed", "Teams do not apply. A dashed"),
    ("Replaces the Commitment Type filter in this section.", "Applies to this section only."),
    ("the choice in this section replaces the filter bar checkboxes here.", "the choice in this section."),
    ("(Release, Projects, Teams, Commitment Type), out of all", "(Release, Projects, Teams), out of all"),
    ("under the Release, Projects, Teams and Commitment Type filters.</li>", "under the Release, Projects and Teams filters.</li>"),
    ("Tiles follow the Release, Projects, Teams and Commitment Type filters. The as-of date", "Tiles follow the Release, Projects and Teams filters. The Delivery Cycle filter in the filter bar decides which cycles the selector offers; with one cycle ticked, only that cycle is offered and epics in no cycle (no planned date, or planned after the release end) are left out of the lists, the After Release End line and the Epics with Flags. The Epics in Release column and the pod tiles that count the whole release do not follow it. The as-of date"),
    ("Follows: Projects · Teams · Commitment Type: not applied", "Follows: Projects · Teams"),
    ("Follows: Release · Projects · Teams · Commitment Type", "Follows: Release · Projects · Teams"),
    ('<li><b>Commitment Type</b>: changes no chart. It changes only the "selected types" columns of the table and the By Project and By Team tables.</li>', ""),
    ("Projects and Teams filters apply; Commitment Type does not.", "Projects and Teams filters apply."),
    ("Projects and Teams apply; Release and Commitment Type do not.", "Projects and Teams apply; Release does not."),
    ("epics of the selected commitment types, and cycle time", "epics in the release, and cycle time"),
    ("Epics in Scope (Selected Types)", "Epics in Scope"),
    ("Done (Selected Types)", "Done"),
    ("Epics in the release of the selected Commitment Types.", "Epics in the release."),
    ("Jira gaps that weaken the figures above; all commitment types.", "Jira gaps that weaken the figures above."),
    ("Forecast Epics and the burnup use it, whatever the Commitment Type filter shows.", "Forecast Epics and the burnup use it."),
    ("follows the Release, Projects, Teams and Commitment Type filters and has its own Delivery Cycle choice.", "follows the Release, Projects, Teams and Delivery Cycle filters, and its own cycle choice picks one of the cycles the filter leaves in."),
    ("\nThe Commitment Type checkboxes do not change the target scope.", ""),
    ("Follows: Release · Projects · Teams, Commitment Type: not applied", "Follows: Release · Projects · Commitment Level · Teams: not applied"),      # the Capabilities line: Commitment Level had been dropped by an earlier merge
    (", selected Commitment Types\"", "\""),
    (", selected Commitment Types. Opens", ". Opens"),
    (". The Commitment Type checkboxes do not change the target scope.", "."),
    ("Teams and the Commitment Type in the filter bar do not apply to Capabilities,", "Teams in the filter bar do not apply to Capabilities,"),
    ("Under the Projects, Teams and Commitment Type filters.", "Under the Projects and Teams filters."),
]

REWORDED_RE: list[tuple[str, str]] = []
# regexes deleted from the NEW html: text that the Delivery Cycle filter adds (its two entries in the burnup's How this is calculated)
ADDED = [r"<li>\s*<b>Delivery Cycle filter</b>.*?</li>", r"<li>\s*<b>Delivery Cycle filter, details</b>.*?</li>"]

SNAP_JS = r"""(async () => {
  await document.fonts.ready; updateCore();                       // the burnup measures text with the page font: draw again once the fonts are in, so a first load and a later one agree
  const m = document.querySelector('main').cloneNode(true);
  ['#filters', '#f-live'].forEach(s => { const n = m.querySelector(s); if (n) n.remove(); });
  return m.innerHTML;
})()"""


def baseline_file(spec: str, tmp: Path) -> Path:
    p = Path(spec)
    if p.is_file():
        return p
    out = tmp / "baseline.template.html"
    r = subprocess.run(["git", "show", f"{spec}:program_dashboard/dashboard.template.html"], cwd=REPO, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"cannot read the baseline template from {spec}: {r.stderr.strip()[:200]}")
    out.write_text(r.stdout, encoding="utf-8")
    return out


def states(data: dict, quick: bool) -> list[str]:
    rels = data["releases"][-2:] if quick else data["releases"]
    team = next((t for p in ("PMN",) for e in data["epics"] if e["p"] == p and e.get("tm") for t in e["tm"][:1]), None)
    import urllib.parse
    psets = ["", "p=PMN", "p=PMN|CXCO", "p=INT"] + ([f"t={urllib.parse.quote(team)}"] if team else [])
    cys = ["", "cy=DC1", "cy=DC2"] if not quick else ["", "cy=DC2"]
    return [f"r={r}&{p}&{c}".replace("&&", "&").strip("&") for r in rels for p in psets for c in cys]


def normalise(html: str, baseline: bool) -> list[str]:
    if baseline:
        for old, new in REWORDED:
            html = html.replace(old, new)
        for pat, rep in REWORDED_RE:
            html = re.sub(pat, rep, html)
    else:
        for pat in ADDED:
            html = re.sub(pat, "", html, flags=re.S)
    return html.replace("><", ">\n<").split("\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--template")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--payload", help="a payload JSON (a real one, on a developer's machine); default: the fictitious fixtures")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--show", type=int, default=12, help="differing lines to print per state")
    a = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="dp-baseline-"))
    base_t = baseline_file(a.baseline, tmp)
    new_t = Path(kit.LIVE_TEMPLATE if a.live or not a.template else a.template)
    if a.payload:
        payloads = [("real", json.loads(Path(a.payload).read_text(encoding="utf-8")))]
    else:
        stock = MS.make(MS.il_today())
        variant = LC.variant(MS.make(MS.il_today()))
        LC.seed_pods(variant)
        payloads = [("stock", stock), ("variant", variant)]
    bad, total = 0, 0
    with Chrome() as ch:
        for name, data in payloads:
            pages = {}
            for label, tpl in (("baseline", base_t), ("new", new_t)):
                f = tmp / f"{name}_{label}.html"
                f.write_text(MS.render_page(data, tpl), encoding="utf-8")
                pages[label] = "file://" + str(f)
            for h in states(data, a.quick):
                snaps = {}
                for label in ("baseline", "new"):
                    ch.goto(pages[label] + "#" + h)
                    kit.wait_ready(ch)
                    time.sleep(0.15)
                    errs = [e for e in ch.console_errors() if "link dropped" not in e]
                    snaps[label] = (ch.js(SNAP_JS), errs)
                total += 1
                if snaps["new"][1] != snaps["baseline"][1]:
                    bad += 1
                    print(f"DIFF   {name} #{h}: console errors baseline {snaps['baseline'][1][:2]} new {snaps['new'][1][:2]}")
                    continue
                b, n = normalise(snaps["baseline"][0], True), normalise(snaps["new"][0], False)
                if b == n:
                    continue
                bad += 1
                diff = [l for l in difflib.unified_diff(b, n, "baseline", "new", n=0, lineterm="") if not l.startswith(("---", "+++", "@@"))]
                print(f"DIFF   {name} #{h}: {len(diff)} differing lines")
                for l in diff[: a.show]:
                    print("        " + l[:260])
    print(f"\nbaseline equality: {total - bad} of {total} states identical" + (f", {bad} differ" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
