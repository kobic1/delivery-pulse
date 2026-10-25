# Program dashboard

One filterable page across projects and teams (PMN, CXCO, CXSUP): epics per release, cycle time,
AI-developed share, a by-project and by-team breakdown, a data-quality panel and a sortable epic list.
Every number links to the matching Jira issues.

```bash
set -a && source .env && set +a
python3 program_dashboard/build_dashboard.py           # read Jira (a few minutes) and render
python3 program_dashboard/build_dashboard.py --reuse   # re-render from the last pull, no Jira calls
```

Writes `program_dashboard/build/Program Dashboard.html`: a single self-contained file (inline JS and SVG,
no external libraries). Open it in a browser. Nothing is sent or published.

## It is a snapshot, not live
Jira is read once at build time and the numbers are baked into the file; the build time is shown at the
top. Refreshing means rebuilding. The pull is slow because cycle time needs one changelog request per
Done epic (about 900).

## Filters
Release, Projects, Teams (searchable multi-select), Commitment type, cycle-time basis, free-text search.
The filter state is kept in the URL hash, so a view can be shared as a link, e.g.
`#r=26.4&p=PMN&t=Ascenders&c=Committed|Not%20set|Stretch`
(`r` release, `p` projects, `t` teams, `c` commitment types, `d=cal` for calendar cycle time, `q` search).
Teams and commitment values are joined with `|`.

## Definitions
Taken from the Program Intelligence Agent (`.claude/agents/program-intelligence-agent.md` and
`program_intelligence/definitions/*.yaml` on branch `claude/zealous-cannon-ls64p7`). They are restated in
`build_dashboard.py` and the template, so this tool does not need that branch at run time.

- **Removed is excluded from every figure.** Done means the status named Done, never Jira's Done category.
- **Scope is Fix Version plus Commitment Type** (customfield_10094). Default scope = Committed or empty,
  Stretch excluded, the same rule as the weekly email targets. Status never defines scope.
- **Cycle time**, two bases (switch in the filter bar):
  - EDCT: calendar days an epic ended in In Progress or Validation, flagged days excluded. Identical to
    `dashboards/edct_from_jira.py`; the build checks every epic against it and reports differences.
  - Calendar: first In Progress to the resolution date.
- **Guardrails:** no percentile or trend on fewer than 5 Done epics; 27.1 and 27.2 are labelled
  provisional; epics listing several teams count under each team (the total row counts them once).
- **No ranking or scoring of any team or person.** Teams are listed alphabetically and the views report
  scope and status, not performance (`rules/no-employee-evaluation.md`).

## Adding to it
Projects and releases are the `PROJECTS` / `RELEASES` lists at the top of `build_dashboard.py`;
`CURRENT_RELEASE` and `PROVISIONAL` set the default release and which releases are marked provisional.
Reuses `dashboards/edct_from_jira.py` for the Jira client and EDCT. The output contains epic titles and
internal figures: `program_dashboard/build/` is git-ignored, never commit it.
