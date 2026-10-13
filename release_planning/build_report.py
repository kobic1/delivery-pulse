#!/usr/bin/env python3
"""Release planning status report: how complete is epic planning for the next release?

One report per Jira project (no cross-project roll-up). Hierarchy: Project -> Epic Team -> Pod.
An epic is "fully planned" when it has all four of:
    Commitment type, Story points, a Pod label (a label containing "POD"),
    and a Target sprint inside this release's two milestones.
Epics with a status in excluded_statuses (Done, Removed) are left out of every figure.

Reads only Jira; sending goes through dashboards/send_email.py. Nothing here calls an LLM,
so a send costs no tokens.

Usage:
    python3 release_planning/build_report.py --config config_pmn.json --scope project
    python3 release_planning/build_report.py --config config_pmn.json --scope team --team Ascenders
    python3 release_planning/build_report.py --config config_pmn.json --scope all-teams
    ... --style a|b|c|d|e|f   (visual layout; default b; a = original, b = restyled, c = heat map, d = action-led, e = readiness, f = milestones)
    ... --audience none|test|managers   (none = build only; test = --to only; managers = secret)

Env: JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN; for sending POWER_AUTOMATE_EMAIL_URL and,
for --audience managers, RELEASE_PLANNING_RECIPIENTS (JSON map, see config note).
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from model import BUILD, HERE, NO_TEAM, build_model  # noqa: E402

STYLES = ["a", "b", "c", "d", "e", "f"]


def renderer(style: str):
    return importlib.import_module(f"style_{style}").render


# ---------------------------------------------------------------- send

def recipients(cfg: dict, key: str, audience: str, to: str | None) -> str:
    if audience == "test":
        if not to:
            sys.exit("--audience test needs --to.")
        return to
    try:
        found = json.loads(os.environ.get("RELEASE_PLANNING_RECIPIENTS", "") or "{}").get(key, "")
    except ValueError:
        found = ""
    if found:
        return found
    team = key.split(":", 1)[1] if ":" in key else None
    env = (cfg.get("team_recipients_env") or {}).get(team or "")
    return os.environ.get(env, "") if env else ""


def deliver(cfg: dict, key: str, subject: str, path: Path, audience: str, to: str | None) -> None:
    if audience == "none":
        n = len([a for a in recipients(cfg, key, "managers", None).split(";") if a.strip()])
        print(f"built {path.name} (not sent) -- would go to {n} recipient(s)")
        return
    rcpt = recipients(cfg, key, audience, to)
    if not rcpt:
        print(f"SKIP {key}: no recipients configured")
        return
    subprocess.run([sys.executable, str(HERE.parent / "dashboards" / "send_email.py"),
                    "--to", rcpt, "--subject", subject, "--body-file", str(path)], check=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--scope", choices=["project", "team", "all-teams"], default="project")
    ap.add_argument("--team")
    ap.add_argument("--audience", choices=["none", "test", "managers"], default="none")
    ap.add_argument("--to", help="recipient for --audience test")
    ap.add_argument("--style", choices=STYLES, default="b", help="visual layout (default b)")
    ap.add_argument("--out", help="output folder (default release_planning/build)")
    a = ap.parse_args()
    cfg = json.loads((HERE / a.config).read_text())
    epics = build_model(cfg)
    out = Path(a.out) if a.out else BUILD
    out.mkdir(parents=True, exist_ok=True)
    render = renderer(a.style)
    jobs: list[tuple[str, str | None]] = []
    if a.scope == "project":
        jobs = [(cfg["project"], None)]
    elif a.scope == "team":
        if not a.team:
            sys.exit("--scope team needs --team.")
        jobs = [(f'{cfg["project"]}:{a.team}', a.team)]
    else:
        jobs = [(f'{cfg["project"]}:{t}', t) for t in sorted({t for e in epics for t in e["teams"]}) if t != NO_TEAM]
    for key, team in jobs:
        subject = cfg["subject_prefix"] + (f" — {team}" if team else "")
        path = out / (re.sub(r"[^A-Za-z0-9]+", "_", key) + f"_{a.style}.html")
        path.write_text(render(cfg, epics, team), encoding="utf-8")
        deliver(cfg, key, subject, path, a.audience, a.to)


if __name__ == "__main__":
    main()
