---
description: Daily program intelligence view - exceptions needing attention today (usage: /program-daily [projects, default from context])
argument-hint: [projects or scope]
---

Use the `program-intelligence-agent` subagent to produce the DAILY PROGRAM INTELLIGENCE view for: $ARGUMENTS

Scope: if empty, use the projects in `program_intelligence/context/programs-and-projects.md`. Window: last 24h for changes plus current state for open items (weekend-aware). Use `program_intelligence/templates/daily-view.md`. Read-only; run `governance-reviewer` before presenting. State coverage, window and retrieval time.
