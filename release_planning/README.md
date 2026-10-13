# Release planning status

Per-project report on how complete epic planning is for the next release, rolled up
Project -> Epic Team -> Pod. An epic is **fully planned** when it has a Commitment type,
Story points, a Pod label (any label containing "POD"), and a Target sprint inside the
release's two milestones. Done epics count as planned; Removed epics are excluded.

```bash
set -a && source .env && set +a
python3 release_planning/build_report.py --config config_pmn.json --scope project          # build only
python3 release_planning/build_report.py --config config_pmn.json --scope team --team Ascenders
python3 release_planning/build_report.py --config config_pmn.json --scope all-teams --audience test --to you@example.com
```

Sends on demand from GitHub: Actions -> "Release Planning Status" -> Run workflow.
Recipients come from the `RELEASE_PLANNING_RECIPIENTS` secret, never from this repo.
Next release: edit `release`, `milestones`, `sprint_release_token` in the config.

## Layouts

`--style` picks the email layout (workflow input `style`). Default is **b**.

| Style | Layout |
|---|---|
| b | Default. Matches the release-status emails: summary strip, white card, progress bars |
| a | The original first version |
| c | Heat map: cells shaded by completeness |
| d | Action-led: a card per team with a "To do" list |
| e | Readiness: ready / partly planned / not started bars |
| f | Milestones: 1st / 2nd / not scheduled bars |
| t | Teams paste: plain table, colored text and links only (Teams strips backgrounds). Open the HTML, copy, paste into Teams |

Code: `model.py` (Jira fetch and stats, shared), `style_<letter>.py` (one renderer each),
`build_report.py` (CLI and sending).
