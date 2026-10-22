---
description: Cross-source deep dive on one epic, release, capability or topic (usage: /program-investigate <Jira key | release | topic>)
argument-hint: <Jira key, release, capability or topic>
---

Use the `program-intelligence-agent` subagent for a cross-source deep dive on: $ARGUMENTS

Delegate Jira flow to `jira-flow-analyst`, links/release risk to `dependency-analyst`, and Jira-to-email/chat/meeting/document correlation to `evidence-correlator`. Return the evidence ledger, contradictions, follow-through gaps and recommended next investigations, each in Observation / Interpretation / Hypothesis / Recommendation form with a confidence label. Read-only; run `governance-reviewer` before presenting.
