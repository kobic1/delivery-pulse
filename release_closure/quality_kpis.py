"""Short quality KPI email: Customer-found bugs (CFB, Regressions, PQCR, from Jira), SonarQube code coverage and the bugs
backlog. Aurora look, for review.

    python3 quality_kpis.py --config config_cxco.json

Reads build/<project>_release_closure.json (run build_report.py first) for the bugs backlog."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import build_report as B
import cfb_kpis
import email_style_aurora as A
from email_style_aurora import FONT, INK, SUBTLE, LINE, PAGE, spacer, heading, banner, _logo_src, sonar_coverage, bugs_backlog

HERE = Path(__file__).resolve().parent


def render(cfg, base, rel, total, extra_note):
    p = cfg.get("display_name", cfg["project"])
    first, last = rel[0]["name"], rel[-1]["name"]
    z = cfg["sonarqube"]["monthly"][-1]
    n_cfb, n_reg = sum(r["cfb"]["cfb"] for r in rel), sum(r["cfb"]["reg"] for r in rel)
    note = (f'{n_cfb} customer-found bug{"" if n_cfb == 1 else "s"} fixed across {first}&ndash;{last}, {n_reg} of them regressions. '
            f'Code coverage has climbed to {z["coverage"]:.1f}% and the P1-P3 bugs backlog is at {rel[-1]["bugs_weekly"][-1]} at the end of {last}.')
    sections = [
        (cfb_kpis.TITLE, cfb_kpis.SUB, cfb_kpis.table(A, base, rel, total)),
        ("Code Coverage", "SonarQube coverage by month.", sonar_coverage(cfg)),
        (cfg.get("bugs_title", "Bugs backlog"), "Open bugs at the end of each week (counts). Last column: change from W1 to W12.", bugs_backlog(base, rel)),
    ]
    body = "".join(spacer(28 if i else 20) + heading(t, sub) + c for i, (t, sub, c) in enumerate(sections))
    foot = ('Release windows use the Jira release dates: ' + ", ".join(f'{r["name"]} {r["start"]} to {r["end"]}' for r in rel) + '.<br>'
            + cfb_kpis.NOTE + '<br>' + cfg.get("bug_exclusion_note", "Accessibility bugs are excluded") + '.<br>'
            'Code coverage: SonarQube, latest month to date. ' + extra_note)
    return (f'<table role="presentation" lang="en" width="100%" cellpadding="0" cellspacing="0" bgcolor="{PAGE}" style="background:{PAGE};">'
            f'<tr><td align="center" style="padding:24px 12px;"><table role="presentation" width="720" cellpadding="0" cellspacing="0" '
            f'style="width:100%;max-width:720px;table-layout:fixed;"><tr><td style="font-family:{FONT};color:{INK};">'
            f'<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;font-size:1px;line-height:1px;color:{PAGE};">{note}</div>'
            f'{banner(" Quality KPIs " + first + "&ndash;" + last, _logo_src(cfg), f"{p} Quality KPIs {first}" + chr(0x2013) + last, p)}'
            f'{spacer(18)}{heading("Summary", note)}'
            f'{body}{spacer(24)}<div style="font-size:12px;line-height:17px;color:{SUBTLE};border-top:1px solid {LINE};padding-top:12px;">{foot}</div>'
            f'</td></tr></table></td></tr></table>')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    a = ap.parse_args()
    cfg = json.loads((HERE / a.config).read_text())
    cfg["sonarqube"] = json.loads((HERE / cfg["sonarqube_file"]).read_text())
    rel = json.loads((HERE / "build" / f'{cfg["project"]}_release_closure.json').read_text())["releases"]
    base, s = B.session()
    total = cfb_kpis.attach(cfg, base, s, rel)
    out = HERE / "build" / f'{cfg["project"]}_quality_kpis_email.html'
    out.write_text(render(cfg, base, rel, total, "MTTR and Major Incidents are not included yet: they come from Power BI, which is not accessible from here."), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
