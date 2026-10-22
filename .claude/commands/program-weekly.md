---
description: Weekly program intelligence review - changes vs last week, risk movement, contradictions, top 3 investigations (usage: /program-weekly [projects])
argument-hint: [projects or scope]
---

Run this as an orchestrator from the main session (subagents cannot spawn subagents, so do not delegate the delegation). Target: WEEKLY PROGRAM INTELLIGENCE REVIEW for: $ARGUMENTS

1. Read `program_intelligence/context/*.md` and `definitions/*.yaml` for scope, window and definitions. If $ARGUMENTS is empty use the projects in `programs-and-projects.md`. Window: last 7 days compared with the prior 7 days plus the current Delivery Cycle baseline.
2. In ONE message, start these subagents in parallel, each given the scope, window, the cloudId, the standing rules (exclude status Removed from everything; never use statusCategory Done as completed; known conditions in `alert-rules.yaml` are tracked trends, not alerts) and a request for structured findings with JQL, window, cohort, sample size, source URI and confidence label:
   - `jira-flow-analyst` (flow, aging, scope churn, quality, hygiene)
   - `dependency-analyst` (links, blockers, release and milestone risk)
   - `evidence-correlator` (Jira keys against Teams, email, Confluence; contradictions; follow-through gaps)
3. Pass their findings to the `program-intelligence-agent` subagent to synthesise, prioritise and write the report. Use `program_intelligence/templates/weekly-review.md`.
4. Pass its draft to `governance-reviewer`. Fix every FAIL (or send back to the agent), then present the report. State coverage, window and retrieval time, and say which specialists ran.
5. Read-only: no writes to Jira, mail, Teams or Confluence. Emailing the report only when the user asks.
