---
name: jira-epic-dashboard
description: Build a live, filterable, drill-down Jira epic dashboard (gradient hero with completion rings, tabs, group cards by commitment/capability/pod/category, sortable epic table, data-quality callout, every figure hyperlinked to the matching Jira issues). Use when Kobi asks for a new release/program dashboard from a JQL query, e.g. "NFR epics for 27.2", "dashboard of epics labelled X", or "same look as the NFR 27.1 dashboard".
---

# Jira epic dashboard

Reproduces the **NFR Epics 27.1** dashboard (https://claude.ai/artifact/CPRtfJeoxvKmKVEqvNxXwP) for any JQL. It is a Dashboard-type Artifact whose data is a **live query** on the Atlassian connector, so it re-reads Jira on every open and on "Refresh from Jira".

## Inputs to confirm (ask only what is missing)
1. The JQL (or a Jira filter URL: decode `jql=`). Epics only.
2. Title (e.g. "NFR epics · release 27.2").
3. Custom field ids if they differ from PMN: Commitment type (`customfield_10094`), Team/Pod (`customfield_10040`, multi-select), Work category (`customfield_10139`). Capability = the epic's `parent` link. Look them up with `getJiraIssueTypeMetaWithFields` if the project is not PMN.
4. Whether Done epics are included (the spec version includes them so the rings can show completion; a "not done" JQL hides them).

## Steps
1. **Check the data first.** Run the JQL with `searchJiraIssuesUsingJql` (cloudId = site hostname, `maxResults` 100, fields as in `assets/dataset-epics.json`). The result is large and is saved to a file; inspect it with `jq`. Confirm: issue count, `parent.fields.summary`/`parent.key`, status category, that custom fields come back as `{value}` objects (Pod is an array).
2. **Create the artifact.** `Artifact` quickstart (`intent: "other"`, `design_systems: false`), then publish with `type_url` of the Dashboard type, a title, `auto_open: "after_first_write"`. Read the type's reference files (`artifact-type/reference/*.md`) via `Artifact read` with `paths`. The type's `SKILL.md` rules win over anything here.
3. **Fill the page.** Copy `assets/dashboard-page.html`, edit the `CONFIG` block at the top of the script, and replace `{{TITLE}}`, `{{JQL}}` and `{{JIRA_ISSUES_URL}}` (the JQL URL-encoded after `…/issues?jql=`). Then write with `ArtifactData`:
   - `dash/meta` `{title}`
   - `datasets/epics` from `assets/dataset-epics.json` (set `jql` identical to `CONFIG.jql`)
   - `files/index.html` `{text: <page>}`. For large files build the JSON with Python and pass `file_path`, so the page does not pass through the conversation.
   Use one `batch` for first creation; later edits are `update` with `if_version`.
4. **Check.** Read `data/users/me` doc `check`. `checking` → read again (max 5). Document gone = passed. `failed` → fix only what the code confirms (max 2 fixes). Also read `runs` for failed datasets. Never claim the page "works"; say what you verified and what you could not.
5. **Hand over** briefly: link, what is live, that each viewer needs their own Atlassian access, that the page is private until shared from the Share menu.

## Look and feel (already in the template)
- Light lavender page `#F5F3FF`, white cards, soft indigo shadows. Hero gradient `#4F46E5 → #7C3AED → #0EA5E9`, three rings (Done green, In progress amber, To do indigo) computed from the filtered scope.
- Sticky tab bar: Overview, By commitment, By capability, By team/pod, By category, All epics.
- Overview: 8 KPI tiles with coloured left bar, committed-vs-stretch stacked bars, amber data-quality callout, capability group cards.
- Group card click → drill-down table with breadcrumb and "Back to groups". Table is sortable, status chips (green/amber/indigo), commitment tags, gradient AI badge, key links to Jira.
- Search box (key, title, assignee) with `/` shortcut, Reset, "Showing X of Y". The pill-filter rows were deliberately removed at the user's request; do not add them back unless asked.
- Footer shows the exact JQL and retrieval time. Read-only.
- Every figure is a dotted-underline link (`fig()` in the template) that opens the matching issues in Jira: it appends conditions (`statusCategory = Done`, `cf[…] = "x"`, `parent = KEY`, `… is EMPTY`, `duedate is EMPTY`, label clause) to the base JQL. Links do not include the search text; say so if asked.

## Hard-won rules (these caused the first version to show empty tiles)
- `dash.loader(...)` and `dash.calc(...)` must be at the **top level** of a script. Never wrap the page script in an IIFE.
- The loader must accept any wrapper the connector uses (string JSON, `{content:[{text}]}`, `structuredContent`, `{issues:{nodes}}`). The template's `unwrap` does this; keep it.
- Fonts: only Google Fonts links are allowed by the artifact CSP and the Dashboard type drops `<link>`; use a system font stack with IBM Plex listed first.
- No stored copies of Jira data unless asked; keep it a live query.
- Table marks: `data-source="epics" data-row-key="key"` on the `<table>`, `data-field` on each `<th>` naming a loader column; cell text must equal the data value.
- Use they/them for people; never rank individuals by assignee.

## Variations
- Release dropdown: keep the release in `dash/params` and use `{{release}}` in the JQL arg only after testing how the connector quotes it (it may insert quotes).
- Other groupings: add an entry to `DIMS` and a loader column; add a `dimCond` rule so the links work.
- Open questions from the original spec (ask the user if relevant): pod vs department as the team grouping; multi-release side-by-side.
