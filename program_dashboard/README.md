# Delivery Pulse

One filterable page across projects and teams (PMN, CXCO, CXSUP, CXWFM, WFM, CXINT): the release status in the
shape of the weekly release status email, plus bugs, customer-found bugs (CFB), epic dependencies and a capability
view. Every issue count links to the matching Jira issues, and every chart mark has hover text and a Jira link.

Layout, top to bottom: five headline tiles (Epics Delivered, Forecast Epics, EDCT Days, Open Bugs, Epics by AI,
each with a plain-fact line and a kicker saying whether it is release, month-to-date or today), a collapsible
**Needs Attention** panel, then **Delivery** (burnup), **Efficiency** (EDCT against the 10-day target) and
**AI Adoption** (share of epics built by AI agents) with a Week / Month / Quarter switch, **Quality** (open bugs
trend, customer-found bugs), **Dependencies** (open dependencies on a board with a column per sprint, plus a
one-row-per-project capability status table), a separate **CXCROSS** section (status per project for each CXCROSS Capability, and which projects are behind), an **NFRs** section ("NFR Epics (Label or Category)", five tabs) and, under "Release Analysis", trend by release, by project, by team
and data quality. A quiet floating "Back to Top" button appears when you scroll up after reading well down the page (it stays hidden if the page cannot scroll). The header shows "Data as of ..." with a Refresh button. Monthly figures use the email's rules:
resolution month, AI-implemented epics for EDCT, Maintenance-category epics left out.

```bash
set -a && source .env && set +a
python3 program_dashboard/build_dashboard.py              # read Jira (a few minutes) and render
python3 program_dashboard/build_dashboard.py --reuse      # re-render from the last pull, no Jira calls
python3 program_dashboard/build_dashboard.py --add-deps   # add dependency links and capabilities to the last pull (no changelog calls), then render
python3 program_dashboard/build_dashboard.py --add-planning  # also add due dates, target sprints, the sprint calendar, status-since dates and bug updates
python3 program_dashboard/build_dashboard.py --add-hier      # add the CXCROSS Initiative > Capability hierarchy
python3 program_dashboard/build_dashboard.py --add-nfr       # flag the epics that carry the label NFR (the Issue Category is already in the data)
# The Atlassian site id for Refresh is read from the site (or from JIRA_CLOUD_ID); it is not stored in the repository.
```

Writes two files to `program_dashboard/build/` (git-ignored, they contain epic titles):

- `Delivery Pulse.html`: a single self-contained file (inline JS and SVG, no external libraries; the only external
  request is the Be Vietnam Pro font stylesheet, with Arial as fallback). Open it in a browser. Nothing is sent
  or published. The Refresh button there only explains that it needs the published page.
- `Delivery Pulse (artifact).html`: the same page as a fragment for the Artifact tool. Publish it with the `mcp`
  capability declared for the Atlassian connector and the single tool `searchJiraIssuesUsingJql`:
  `{"mcp": {"servers": [{"server": "Atlassian", "tools": ["searchJiraIssuesUsingJql"]}]}}`.

## Time base
Every timestamp on the page is shown in Israel time (labelled), and the as-of day used for ages, sprints and SLAs is the
Israel-local date of the snapshot or of the last Refresh, whatever the viewer's timezone.

## Snapshot, and Refresh in the published page
Jira is read once at build time and baked into the file; the build time is shown at the top. The pull is slow
because cycle time needs one changelog request per Done epic and the burnup needs one per epic (about 3,000).

In the published artifact, **Refresh from Jira** asks the viewer's own claude.ai Atlassian connector for what
changed since the snapshot (`updated >=` the day before) and merges it in: new, moved, Removed and Done epics,
new and fixed bugs, accessibility flags. The first click asks the viewer for Jira access. Failures say what to do
(not allowed, connector not connected, expired sign-in) and leave the data on screen unchanged.
Cycle time, release join dates, dependencies, capabilities, due dates, sprints and status-since dates for newly changed
epics need a rebuild (`--add-planning` is enough for the last five). Refresh is for the numbers moving, not a replacement for the build.

## Filters
Release (bare numbers; a release that is running gets an "In Progress" chip), Projects (with an All Projects
option), Teams (searchable multi-select) and Commitment Type (**all three types by default**). Reset Filters counts
every changed control. Section-level controls: Week / Month / Quarter for the EDCT and AI charts, Priority, CFB
Yes/No and an accessibility toggle for the Bugs Backlog, and Version / Month / Quarter for the CFB chart and table.

In a file the filter state is kept in the URL hash, so a view can be shared as a link, e.g.
`#r=26.4&p=PMN&t=Ascenders&c=Committed|Not%20Set`: `r` release, `p` projects, `t` teams, `c` commitment types
(omitted when all three), `ax=1` include accessibility bugs, `bp` bug priorities, `cfb=yes|no`, `g=week|quarter`
(EDCT and AI period), `cg=month|quarter` (CFB grouping), `dp=overdue|external|unplanned` (dependency board quick filter); an empty Projects or Commitment Type selection is stored as `p=none` / `c=none`. In the published page the filters are remembered in the
viewer's browser instead. A section whose filters leave nothing to show says why.

## Definitions
Taken from the Program Intelligence Agent (`.claude/agents/program-intelligence-agent.md` and
`program_intelligence/definitions/*.yaml` on branch `claude/zealous-cannon-ls64p7`). They are restated in
`build_dashboard.py` and the template, so this tool does not need that branch at run time.

- **Removed is excluded from every figure.** Done means the status named Done, never Jira's Done category.
- **Scope is Fix Version plus Commitment Type** (customfield_10094). Status never defines scope.
- **The scope target never changes with the Commitment Type filter**: it is always Committed or no Commitment
  Type, with Stretch left out. **Forecast Epics is the target scope on the first day of W1** (the epics that were
  in the release on that day and still are); the burnup's scope label, point, tooltip, subtitle and caption and the
  even-pace reference read the same single value, and the tile adds how many were added since (and today's count,
  as a link). Before W1 it shows the target so far. The links use `fixVersion WAS "<release>" ON "<W1 date>"`.
  The Epics Delivered tile follows the Commitment Type filter and says so; its fact line gives the target-type
  delivered figure against the W1 scope.
- **Cycle time** is EDCT only: calendar days an epic ended in In Progress or Validation, flagged days excluded.
  Identical to `dashboards/edct_from_jira.py`; the build checks every epic against it and reports differences.
- **Burnup** (selected release): only the 12 delivery weeks W1 to W12, from the first day of the second week of
  the Jira release window (the IP week is not drawn) to the release date. Scope is one number, the target-type
  epics in the release on the first day of W1. Done is the target-type epics closed, cumulative by resolution
  date, with earlier closures counted at the start and later ones on the last day. The dashed line is an even pace
  from zero to that scope, a reference and not a forecast. Release windows come from the Jira versions.
- **Bugs backlog** (selected projects and teams; release and commitment filters do not apply): created, resolved
  and open per week for 26 weeks, Monday-aligned, using the same logic as the weekly email. Accessibility bugs
  (`summary ~ "[Accessibility]*"` or label `DWP_Accessibility_Defect`) are excluded unless switched on. Its own
  Priority and CFB filters apply to this section only and the Jira links carry them.
- **CFB**: Bug, status Done, reported by the CFB account (`release_closure/config_pmn.json`), resolution Fixed or
  Fixed - Config, counted by resolution date. Version = the release windows; Month = the last 12 calendar months
  (its total row says "Last 12 Months"); Quarter = calendar quarters since the data starts. Regressions use the
  Regression field; PQCR sums Number of Incidents.
- **Dependencies** (open ones only): an explicit Jira link of type "Dependency" (outward "depends on") or "Blocks"
  where both ends are epics, normalised to a dependent and a provider. Only pairs where neither end is Done are
  shown (complete pairs are counted and left out). The board has one column per sprint plus "Not Planned", one card
  per provider epic. The **planned sprint** of the provider is the sprint containing its due date (the due date is
  stronger), otherwise its Target Sprint; when both exist and disagree the card, the hover and the View Data table
  show both ("Due 2026-09-04 (Sprint 195) overrides Target Sprint 199 (2026-11-25)"). A due date outside the sprint
  calendar, or a Target Sprint the calendar does not know, is said so, never silently replaced. Sprint windows come
  from the Target Sprint labels (the label date is the start, sprints run three weeks). The key on a card opens that
  ticket (`/browse/KEY`); a small "Open with Dependents" link opens the provider with the epics it blocks. A pair
  linked both as Dependency and as Blocks counts once. **Overdue** = the planned sprint has ended and the provider is not Done.
  **External** = the provider is in a different Jira project. Hovering a card lists the epics it blocks. Other link
  types do not count, links to Removed epics are left out, and a link means a dependency is recorded, not that it
  is risky (no link is not no dependency). Counts only; no aging logic beyond overdue. The **capability view** is one table, one row per project of the Capability (the Jira parent link), with the
  number of Capabilities and Not Started, In Progress, Validation and Done epic counts; epics without a Capability sit in
  their own project's row.
- **Needs Attention** (computed live from the data the page holds; thresholds in one `CFG` object in the template):
  production bugs (customer-found, not Ready for Deploy, Done, Closed, Resolved or Removed) out of SLA or due soon
  (age in whole calendar days from creation; SLA days: P1 3; P2 7 with a regression, 14 without; P3 and P4 7 with, 30
  without; due soon from 70% of the SLA; no priority means no SLA), production bugs with no update for 3 days,
  overdue dependencies, epics in Validation for more than 3 business days (Friday and Saturday and the Israeli public
  holidays are not counted; the holiday list, 2025-06 to 2027-12 in python-holidays style, is in the thresholds object
  and Chol HaMoed is not excluded; the panel says when the as-of date is past the list), open external dependencies and
  a hygiene group. The 42-day In Progress group was dropped. One row per Jira item, never ranked by team or person, and the
  panel states what it could not see (comments, story data, anything older than the snapshot).
- **CXCROSS** (separate section): epics of the six projects whose parent Capability lives in project CXCROSS, for the
  selected release and the global filters. One row per CXCROSS Capability (its Initiative as a muted subtitle), one
  column per project in the standard order, each cell showing done/total linked to Jira. A cell is **Behind Capability
  Fix Version** when an open epic of that project is planned later than the Capability (its earliest release version is
  later than the Capability's latest) or is not Done although the Capability's latest release-named fix version has
  ended. The Capability's Fix Version is taken to be the program's **Required Fix Version** (an owner assumption, not
  independently verified), shown as "Required Fix Version" and "Behind Required Fix Version". Facts only: no at-risk verdict, no due dates, no owners; rows and columns
  are never ordered by lateness. Only CXCROSS Capabilities that have epics under the six projects are counted; CXCROSS-owned epics are not included.
- **NFRs** ("NFR Epics (Label or Category)"): an epic is an NFR epic when it carries the label `NFR` (exact spelling) or
  its Issue Category (field 10139) is one of four values listed in `NFR_CATEGORIES` in the template. Both are
  self-reported in Jira, and the section says how each epic matched (label only, category only, both). It follows
  every global filter, excludes Removed and CXCROSS-owned epics, and prints its denominator. Five figures stay above
  five tabs (By Project, By Category, By Commitment, By Capability, By Team); the tab is kept in the URL as `nt=`
  (default By Project; Reset returns to it). Status classes are Not Started (including In Definition), In Progress,
  Validation and Done, with an Other Status column when a status fits none. No verdicts, rings or rankings.
- **Scroll anchoring:** when a filter changes and sections re-render, the block the reader is looking at is kept at the
  same screen position (a control the reader just used is held instead of the centre block). Open details panels
  stay open.
- **Guardrails:** no percentile, share or trend on fewer than 5 items (including the bug direction facts);
  running releases are provisional; epics listing several teams count under each team (the total row counts them once).
- **No ranking or scoring of any team or person.** Teams and capabilities are listed alphabetically and the views
  report scope and status, not performance (`rules/no-employee-evaluation.md`).

## Adding to it
Projects and releases are the `PROJECTS` / `RELEASES` lists at the top of `build_dashboard.py`;
`CURRENT_RELEASE` and `PROVISIONAL` set the default release and which releases are marked provisional.
Reuses `dashboards/edct_from_jira.py` for the Jira client and EDCT. The output contains epic titles and
internal figures: `program_dashboard/build/` is git-ignored, never commit it.
