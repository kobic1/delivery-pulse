# Programs and projects (agent reads this first)

Source: Kobi's "My Second Brain" (OneDrive: about-me.md, MEMORY.md through 2026-09-14, Projects/*.md). Items marked **VERIFY** are inferred, not stated. Refresh from the second brain each cycle; this file is context, not evidence.

## Jira projects in scope
| Key | Meaning | Notes |
|---|---|---|
| PMN | CXone Performance Management Native (primary product) | Quarterly releases `YY.Q`; Fix Version e.g. 26.4 |
| CXCO | CXone Coaching | Coaching program (ownership transition with Sampada Bhonsale / Prashant Deshpande); Pune team (Ojas Yadnik, Ashish Sheth) |
| CXCROSS | R&D-wide cross-CX initiatives (not a product) | e.g. CXCROSS-288 Customer-Centric SLI/SLO (Resiliency 2026), CXCROSS-266 DocPulse, CXCROSS-22 Angular 21 upgrade, secrets-management kickoff. Often tracked at Capability level |
| Adjacent (seen in threads) | PMSTND (PM Standalone, being decommissioned), CXDV (Data Viz), CXWFM, CXSUP, CXINT, EEM, WFMDEVOPS, ESP | In scope only when linked from PMN/CXCO/CXCROSS or an exception cites them. Note: Jira tickets created in the wrong project (CXDV instead of PMSTND) have occurred |

Owner context: Kobi is a Senior Program Manager, CX (confirmed 2026-10-22). Older second-brain notes call him Engineering Director because he does more than the role requires: do not assume engineering ownership or authority. PM and Data Visualization (DV) are the products in focus; the manager is Ben Johnson (Director, Analytics Applications). Tools: Jira, Confluence, Teams, Outlook, SharePoint/OneNote.

## Work hierarchy and fields
- Hierarchy used in reporting: Initiative > Capability > Epic > Story/Bug. Fix Version is used on Epics and Capabilities.
- Labels seen: `POD` labels, `AGENTIC_AI_CODE`; field "Commitment Type" (customfield_10094; Committed / Stretch); "CXone Offering"; Impact Assessment Status (Lyra).
- Capability IDs: no separate field found. **VERIFY**: capability is a Jira issue type (key e.g. CXCROSS-288, PMN-28368), not a free-form ID.
- Release names: `26.x`, `27.1` (current), `27.2` (planned). Fix Version values also include `CX.26.4.193` (sprint-named versions), `Future Release` and `Future release `. See current-priorities.md for the calendar.
- Statuses (verified in Jira 2026-10-22): see `definitions/workflow-status-map.yaml`. PMN epics: New, In Definition, Ready for Dev, In Progress, Validation, Done, Removed. PMN stories/bugs add Ready for Deploy. CXCROSS adds Candidate.
- Issue types seen: PMN Epic/Story/Bug; CXCROSS Initiative/Capability/Epic; CXCO Capability/Epic/Bug/Task plus Test and Test Execution (exclude from flow metrics).

## 26.4 roadmap priorities (stated order; 26.4 is now closed, carry-over goes to 27.1)
1. Tenant Segmentation (PMN-16279)
2. No ACD support / OOTB Data Integrations (PMN-15048 fix version 26.4)
3. Complex Hierarchies Phase 2
4. Project Lyra (PMN-28368)
5. Wallboard additionals / Wallboard Management V2 (PMN-28426)
Kobi's own 2026-07-30 framing: UHG Scalability, Complex Hierarchy, Lyra, Accessibility bugs, No ACD, Wallboard PH2 (Tenant Segmentation not mentioned: confirm).

## Active programs (one line each; details in the second brain Projects/ files)
- Accessibility / DWP ACR (target 2026-09-28; staging gap reported 2026-08-11)
- UHG scalability, UHG 3rd-party ETL decision, NPM/UHG platform requirements (Itay Reiner, Kevin Clukey)
- Resiliency Focus (25% of roadmap capacity through 27.1; Itay Grushka / Lou Corbeil)
- Platform Scale-40k (PMN-31485, CXSUP-256112)
- AI Metrics Reporting Mandate (from July 2026, on every user story)
- Agentic PM tool (Idan Kaizerman, Zvika Horev; AWS)
- SC Extension Post Q3 (Pune/Bolivia subcontractors)
- Notification Service v2 to v3 (PMN-30697)
- Coaching Program transition; PM Billing Lambda handover; PM NPS/availability metrics; SW Capitalization data-quality dispute

## Aliases and normalisation
Kizerman = Idan Kaizerman. Pradeep = Pradeep Sant. Robert = Robert Stovall (**VERIFY**). PM Standalone = PMSTND = ClearView (decommissioning). NPM = legacy NICE Performance Management. DV = Data Visualization. MI = Major Incident. CFB = customer-found bug. ACR = Accessibility Conformance Report. IP week = innovation/planning week.

## Authoritative channels
See `source-authority-map.md`.
