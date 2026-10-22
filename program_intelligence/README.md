# Program Intelligence Agent

A read-only program-data analyst and early-warning system for a Senior Program Manager, CX. It connects structured Jira facts with email, Teams, meetings and SharePoint evidence and reports what changed, what is deviating, where sources disagree, and what to investigate next. Source requirements: "Claude Master Program Intelligence Agent for NiCE" (OneDrive).

## Pieces

| Path | Purpose |
|---|---|
| `.claude/agents/program-intelligence-agent.md` | Master agent (instructions, evidence rules, boundaries) |
| `.claude/agents/{jira-flow-analyst,evidence-correlator,dependency-analyst,governance-reviewer}.md` | Restricted read-only subagents |
| `.claude/commands/program-{daily,weekly,investigate}.md` | `/program-daily`, `/program-weekly`, `/program-investigate` |
| `context/` | Program facts the agent must read first. **Fill the TODOs.** |
| `definitions/` | Metrics, status map, commitment classes, confidence rubric, alert rules. All thresholds live here |
| `rules/` | Evidence, privacy, no-employee-evaluation rules |
| `templates/` | Daily, weekly, finding templates |

## Operating model

- Read-only MVP. The agent's tool list contains only read tools; no Jira/mail/Teams/calendar write tools. This is the technical enforcement, since CLAUDE.md-style text is advisory.
- Reuses, not replaces: `dashboards/` for Jira analytics, `config/rules.yaml` pipeline for deterministic alerts (stays the notification engine until this agent proves equal or better precision).
- Adds: cross-source evidence ledger, contradiction and stale-statement detection, decision/action follow-through, communication gaps, theme analysis, confidence and suppression.
- Every finding: Observation / Interpretation / Hypothesis / Recommendation + Confirmed / Corroborated / Single-source / Weak signal / Unknown.

## Roadmap (from the requirements)

1. **MVP**: Jira read-only, dashboard reuse, daily exceptions, provenance, preview. Exit: every alert links Jira evidence; no unsupported fields; duplicate suppression works.
2. **Cross-source**: M365 retrieval, identifier normalisation, contradiction/follow-through. Exit: tests separate confirmed links from semantic coincidence.
3. **Proactive**: weekly/release skills, Cowork schedules where approved, acknowledgment and cooldown.
4. **Advanced analytics**: percentiles, aging distributions, robust anomalies, dependency clusters, empirical forecasts.
5. **Governed scale**: marketplace plugin, managed settings, audit logs, red-team tests, rollback.

Open verification: confirm the NiCE tenant exposes Cowork scheduled tasks, the M365 connector and an approved Jira MCP on the same surface; confirm retention/DLP rules.

## Validation checklist

Grounding (100% of facts have provenance) · no high-confidence link from semantic similarity · explicit time windows · both sides of contradictions kept · missing data reported as Unknown · duplicate/unchanged/stale cases suppressed · metric definitions, denominators, cohort, sample size visible · prompt-injection content cannot trigger tool or write actions · every external write needs explicit approval · no employee rating/ranking · each priority insight has a concrete next investigation.

## Maintenance

Each definition has owner, version, effective date, next review. Review after any Jira schema/process change; review false positives monthly; revalidate after model/connector/plugin updates; keep a changelog and a regression test set; auto-memory is never a source of program facts.
