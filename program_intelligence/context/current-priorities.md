# Current priorities and calendar

Verified against live Jira on 2026-10-22 where stated; everything else comes from the second brain (last entry 2026-09-14) and is **stale until re-checked**. Auto-memory is never an authoritative source of program facts.

## Cadence (confirmed by Kobi 2026-10-22, dates from the Jira sprint field)
- Sprint = 3 weeks, numbered. **Delivery Cycle = 6 weeks = 2 sprints. Release = 12 weeks = 2 Delivery Cycles = 4 sprints**, named `27.x`. An IP week precedes each release's first sprint.
- **27.1** (current): IP 07-13 Oct 2026; sprint 197 (CX.27.1.197) 14 Oct - 03 Nov, active. Delivery Cycle 1 = sprints 197-198 (to ~24 Nov, projected). Delivery Cycle 2 = sprints 199-200 (~25 Nov - ~05 Jan, projected).
- **26.4** (previous): sprints 193-196; 194: 05-25 Aug, 195: 26 Aug-15 Sep, 196: 16 Sep-06 Oct. Closed.
- Commitment type is set per release, not per cycle. MVP is not used. No S/M/L sizing.
- Release dates (deploy dates) are not readable through the Jira tools available here: take them from the R&D Release Milestone Calendar (Confluence).
- Kobi availability: reserve duty from 2026-09-23 per the second brain; unconfirmed whether still ongoing.

## Release state from Jira (2026-10-22)
- PMN epics with Fix Version 26.4: 130, all in Done category (0 open) -> 26.4 is closed. The 2026-09-10 RED flag is historical, not current.
- PMN epics with Fix Version 27.1: 125, of which 33 Done (26%) at the start of Delivery Cycle 1. CXCO 27.1 items and CXCROSS items (13 on 26.4, 18 on 27.1, 31 "Future Release") also exist.
- Recent PMN epic mix (100 latest-updated): 67 on 27.1, 16 on 27.2, 9 on 26.4. A 27.2 version already holds work.

## Top watch items from the second brain (2026-09-14, re-verify before use)
1. **26.4 delivery risk**: PMN Release 26.4 flagged RED on 2026-09-10 (Fellowship team 5 of 26 target epics at day 57); CXCO 26.4 Yellow. 26.4 capacity contested (Cade Rasmussen, No ACD vs Hierarchies vs Lyra).
2. **Complex Hierarchies gap**: product expectation vs delivery; Edward Jones concern (no suite-data hierarchies even by 27.1 per Ben Johnson); UHG wants 4-5 levels.
3. **Accessibility / DWP ACR** due 2026-09-28; fixed bugs still reproducing on staging (CXDV-78069, CXDV-78119, PMN-21746).
4. **Release quality**: 26.3 deployment rolled back (Queue Counter widget regression, 2026-09-11); MI 02854450 (ClearView data stuck) and MI 02879596 (no-ACD ingestion failure).
5. **Capacity and budget**: SC Extension Post Q3 unresolved; Claude budget pressure; SW Capitalization methodology dispute.
6. **Strategic backlog health**: 204 net strategic items added Jan-Aug, 170 aged 90+ days (PMN+CXCO, Kobi's own report 2026-09-09); intake gating recommended.

## Baseline numbers (PMN Release Status automation, 2026-09-12)
43 epics delivered of 73 forecast, EDCT 20 days, 10 open bugs, 91.3% AI field adoption. Use as a comparison anchor only; recompute from Jira.
