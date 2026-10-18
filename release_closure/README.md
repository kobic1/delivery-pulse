# Release closure summary

Per-release email for a project: Throughput, Cycle time, Predictability, optional Code coverage
(SonarQube) or Test coverage (Xray/Jira), and Gating bugs backlog.

```bash
set -a && source .env && set +a
python3 release_closure/build_report.py --config config_pmn.json
```

Writes `release_closure/build/<PROJECT>_release_closure_email.html` (Outlook-safe tables, inline
styles). Nothing is sent; send the file with any HTML email sender.

- A release runs from the Jira version's start date to its release date. Its first week is the
  IP (planning) week; W1-W12 are the four 3-week sprints after it.
- **Predictability**: cumulative epics Done as a % of the scope at the end of W1 (Committed or empty
  Commitment Type, excluding Stretch and Removed). Can exceed 100%.
- **Cycle time**: the EDCT definition from `dashboards/edct_from_jira.py`.
- **Gating bugs backlog**: open P1-P3 bugs at each week end, excluding [Accessibility].
- `test_coverage: false` turns the Jira test section off; `sonarqube_file` points at a local,
  gitignored JSON of monthly SonarQube figures (`{"monthly": [{"month", "coverage", "lines", "projects"}]}`).

## Combined report across projects

`config_wfm_org.json` lists several projects under `projects` and produces one aggregate report
(`build/WFM_ORG_release_closure_email.html`): counts and bug backlogs are summed, cycle time is pooled
across all epics. Only projects on the 26.x release train apply; a project without a dated Jira version
for a release is skipped for it. Per-project overrides: `bugs: false` leaves a project out of the bug
backlog, `bug_exclusions` adds JQL.
