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
