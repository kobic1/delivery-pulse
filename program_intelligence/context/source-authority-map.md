# Source authority map

Which source wins for which fact when sources conflict (both claims are still shown). Seeded from Kobi's second brain; **VERIFY** rows are inferred.

In scope sources: Jira (PMN, CXCO, CXCROSS), Confluence, Outlook email, Teams chats. Meetings/transcripts and SharePoint are optional; SharePoint has historically surfaced little PMN-specific material.

| Fact | Authoritative source | Notes |
|---|---|---|
| Work status, size, assignee, due date, fix version, release commitment | Jira | structured system fact |
| Release and deployment dates, moratorium windows, cluster rollout | Confluence "R&D Release Milestone Calendar" / release management notices | **VERIFY** exact page; note the ACD Moratorium View (Jul 31 - Aug 17) |
| R&D-wide initiative status (Lyra, Resiliency, CXCROSS items) | Owner status emails (e.g. Tzlil Zigelman for Lyra, Radhika Moharir for Resiliency) and the Confluence trackers they reference | Resilience Scenario Tracker, Global Priority tracker (Abhishek Bhatia) |
| Risks | Confluence risk registers (e.g. "CXOne Coaching Risk Register 26.4") plus Kobi's End-of-Week Summary to Ben Johnson | **VERIFY** |
| Decisions | Email replies or meeting notes naming the decision-maker, with timestamp; Teams chat is Single-source unless confirmed | Example: Lyra excludes PM Standalone (email 2026-07-20) |
| Accessibility ACR status | "Accessibility Master File.xlsx" (CXOneAccessibility SharePoint site) and the DWP ACR owner (Shruti Rastogi) | |
| Budget and subcontractor decisions | Yoav Shulman / Ashish Sheth threads | |
| Release status KPIs | Kobi's PMN Release Status automation (derived from Jira); Jira wins on conflict | |
| Hierarchies / UHG product expectations | Itay Reiner and Ben Johnson threads (email), Jira for committed scope | known gap between product expectation and delivery |

## Known noise and limits (from daily-scan notes)
- Email and Confluence notification noise (R&D Release Milestone Calendar, QReport comments, Sys Ops Critical Updates Calendar) dominates date-range searches. Use sender or keyword queries and exact Jira keys.
- Teams search hits Graph 429 throttling regularly; report partial coverage ("N of M chats scanned") instead of implying completeness.
- Names for routing and attribution only. The 2026-09 memory log includes people-heavy notes: never use them to evaluate anyone.
