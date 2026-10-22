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

## Email themes and copy

- `email_style.py` is the original look and is used by every project by default.
- `email_style_aurora.py` is the newer look (gradient banner picture, Executive Summary card, Title Case headings).
  A project opts in with `"email_theme": "aurora"` in its config; CXone Coaching (CXCO) is the first.
- Aurora options: `display_name` (visible product name; the Jira project key stays in the queries), `summary_note`
  (a written line under the Executive Summary instead of the generated figures line), `lean_copy` (short section
  descriptions and a three-line footnote), `bugs_title` (name of the bug section).
- The banner title is drawn into a picture so the gradient survives mail clients that drop CSS gradients; the
  product name is white and the rest a softer white, in one typeface. The smile mark is read from `assets/` if present.

## Dashboard page

`dashboard_page.py` builds a self-contained HTML dashboard from the same data
(`python3 release_closure/dashboard_page.py --config config_pmn.json`, add `--artifact` for the publishable fragment).
