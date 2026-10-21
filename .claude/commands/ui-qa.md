---
description: Run the UI/UX QA reviewer agent on a feature (usage: /ui-qa <feature, file, URL or screenshot path>)
argument-hint: <what to review>
---

Use the `ui-ux-qa-reviewer` subagent to review: $ARGUMENTS

Pass it the fields below, filling what is known from the conversation and the repo, and leaving the rest as "unknown" (do not invent them):

Feature name:
Feature goal:
Target users and roles:
Primary user task:
Requirements or user story:
Acceptance criteria:
Screenshots, video, prototype, or URL (or local HTML / Adaptive Card JSON path):
Available interaction or inspection tools:
Supported browsers:
Supported devices and viewports:
Supported operating systems:
Accessibility target (default WCAG 2.2 A/AA):
Permissions or role variations:
Design-system or component references:
Known constraints:
Out of scope:
Build or environment:
Test data:
Known risks or previous defects:

Ask the agent to: 1) state the evidence boundary; 2) derive missing test scenarios; 3) test or inspect using its master instruction; 4) separate confirmed defects, recommendations, assumptions and items needing verification; 5) give severity, priority, evidence, fixes, retest steps, regression coverage and a release recommendation.

Relay the agent's full report to the user.
