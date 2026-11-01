"""Delivery Pulse: the wording of every "How this is calculated" disclosure that must stay true.

Static checks on program_dashboard/dashboard.template.html (no browser, no network). The copy of a disclosure is one `howBody({id: ..., bl, defs, left, know, more})`
call at the function that draws it; these tests read those calls. They catch the drift that used to be silent: a text that still says "read when the dashboard is
built" for data that Refresh updates, a "key list" claim for links that are queries, a field id or an ISO date in reader text, a bottom line that grew into a paragraph.
Synthetic strings only; nothing here names a real issue, team or pod.
"""
import re
from pathlib import Path

import pytest

TEMPLATE = (Path(__file__).resolve().parent.parent / "program_dashboard" / "dashboard.template.html").read_text(encoding="utf-8")
BL_MAX_WORDS = 40                 # a bottom line is one or two sentences: why you would open the disclosure
SHORT_MAX_WORDS = 20              # the always-visible line under a chart


def _skip_template(s: str, i: int) -> int:
    """i is just after an opening backtick: the index just after its closing backtick (handles ${ ... } with nested strings and templates)."""
    while i < len(s):
        c = s[i]
        if c == "`":
            return i + 1
        if c == "$" and s[i + 1:i + 2] == "{":
            i = _skip_braces(s, i + 2)
            continue
        i += 1
    raise AssertionError("unterminated template literal")


def _skip_braces(s: str, i: int) -> int:
    """i is just after '${' or '{': the index just after the matching '}'."""
    depth = 1
    while i < len(s) and depth:
        c = s[i]
        if c in "\"'":
            j = i + 1
            while s[j] != c:
                j += 2 if s[j] == "\\" else 1
            i = j + 1
            continue
        if c == "`":
            i = _skip_template(s, i + 1)
            continue
        depth += c == "{"
        depth -= c == "}"
        i += 1
    return i


def _call_end(s: str, i: int) -> int:
    """i is just after 'howBody(': the index of the matching ')'."""
    depth = 1
    while i < len(s):
        c = s[i]
        if c in "\"'":
            j = i + 1
            while s[j] != c:
                j += 2 if s[j] == "\\" else 1
            i = j + 1
            continue
        if c == "`":
            i = _skip_template(s, i + 1)
            continue
        depth += c == "("
        depth -= c == ")"
        if depth == 0:
            return i
        i += 1
    raise AssertionError("unterminated howBody call")


def blocks() -> dict:
    """id -> the source text of its howBody({...}) call (the helper's own definition is skipped)."""
    out = {}
    for m in re.finditer(r"howBody\(\{id: \"([a-z-]+)\"", TEMPLATE):
        out[m.group(1)] = TEMPLATE[m.start():_call_end(TEMPLATE, m.start() + len("howBody("))]
    return out


def strip_expressions(s: str) -> str:
    """The reader text of a block: every ${...} expression removed (the code in it is not copy)."""
    out, i = [], 0
    while i < len(s):
        if s[i] == "$" and s[i + 1:i + 2] == "{":
            i = _skip_braces(s, i + 2)
            out.append("X")
            continue
        out.append(s[i])
        i += 1
    return "".join(out)


def literal(block: str, key: str):
    m = re.search(rf"\n\s+{key}: `", block)
    if not m:
        return None
    end = _skip_template(block, m.end())
    return block[m.end():end - 1]


BLOCKS = blocks()
EXPECTED_IDS = {"cy", "bu", "eff", "ai", "trend", "ch-delivery", "ch-cycle", "ch-ai", "ch-nfr", "ch-capab", "capz", "bug", "cfb", "dep", "cap", "cx", "nfr", "attn", "page"}


def test_every_disclosure_is_written_by_the_one_helper_with_a_unique_id():
    assert set(BLOCKS) == EXPECTED_IDS, set(BLOCKS) ^ EXPECTED_IDS
    assert len(re.findall(r"howBody\(\{id:", TEMPLATE)) == len(EXPECTED_IDS)             # no id used twice
    assert 'id="${id}-more"' in TEMPLATE and "<summary>More detail</summary>" in TEMPLATE


def test_the_page_has_the_css_the_layout_needs():
    for rule in ("details.vd ul.dl", "details.vd .bl", "details.vd .lf", "details.vd details.more"):
        assert rule in TEMPLATE, rule


@pytest.mark.parametrize("id_", sorted(EXPECTED_IDS - {"ch-delivery", "ch-cycle", "ch-ai", "ch-nfr", "ch-capab"}))
def test_a_bottom_line_of_at_most_forty_words_opens_every_section_disclosure(id_):
    bl = literal(BLOCKS[id_], "bl")
    assert bl, f"{id_} has no bottom line"
    words = len(strip_expressions(bl).split())
    assert words <= BL_MAX_WORDS, f"{id_}: bottom line has {words} words"
    assert bl.startswith("Use this to ") or id_ == "page", f"{id_}: a bottom line says why you open it"


def test_a_chart_footer_has_a_short_line_and_definitions_but_no_second_bottom_line():
    for m in re.finditer(r"return \{svg: s, (?:rows, )?short: `([^`]*)`, how: howBody\(\{id: \"(ch-[a-z]+)\"", TEMPLATE):
        assert len(m.group(1).split()) <= SHORT_MAX_WORDS, m.group(2)
        assert "bl:" not in BLOCKS[m.group(2)]
    assert re.search(r'chartFoot\("capab", `[^`]*`, howBody\(\{id: "ch-capab"', TEMPLATE)


def test_reader_text_has_no_field_ids_no_project_count_no_internal_names_and_no_iso_dates():
    for id_, b in BLOCKS.items():
        t = strip_expressions(b)
        assert "customfield_" not in t and "cf[" not in t, id_
        for bad in ("seven projects", "six projects", "release train", "Program Intelligence Agent", "build values", "both ends included", "the dashboard's", "Field ids"):
            assert bad not in t, (id_, bad)
        dates = re.findall(r"\b20\d\d-\d\d(?:-\d\d)?\b", t.replace("from 2025-06 to", ""))      # the holiday list coverage is the one range that is wanted
        assert not dates, (id_, dates)


def test_the_page_footer_no_longer_cites_the_agent_or_describes_cycles_wrongly():
    assert "Definitions follow the Program Intelligence" not in TEMPLATE
    page = BLOCKS["page"]
    assert "nothing here ranks or scores a team or a person" in page                      # the one mandated "no ranking" sentence
    for stale in ("The last section has its own data", "not by Refresh", "its own delivery cycle and pod groups", "counts target epics (Committed + Not Set)", "CFB follows the release closure report"):
        assert stale not in TEMPLATE, stale
    assert "Cycles section" in page and "Release, Projects, Teams and Commitment Type filters" in page


def test_no_stale_statement_about_what_refresh_does_not_update():
    for stale in ("Refresh updates the current quarter only", "earlier quarters are as of the build", "Data is the Jira snapshot at", "read when the dashboard is built",
                  "epic bug links, Flagged and assignees are read", "Cycles pods are read only", "a refresh does not update status-since dates, due dates, sprints or dependencies", "Refresh does not update it."):
        # the one true use: status-since is not updated by Refresh (Needs Attention, data limits)
        hits = [m.start() for m in re.finditer(re.escape(stale), TEMPLATE)]
        for h in hits:
            assert stale == "Refresh does not update it." and "Status-since is held only" in TEMPLATE[max(0, h - 120):h], stale
    assert "Refresh updates Capabilities" in BLOCKS["cap"] + BLOCKS["ch-capab"]
    assert "Refresh updates all quarters" in BLOCKS["capz"]
    cy = BLOCKS["cy"]
    assert "Epics, due dates, Target Sprints, the Flagged-as-blocked mark and pod labels are updated by Refresh" in cy
    assert "Bugs under epics, the sprint calendar and the pod pattern are read only when the page is built" in cy


def test_links_are_described_as_what_they_are():
    for id_ in ("cy", "capz"):
        t = strip_expressions(BLOCKS[id_])
        assert "not a saved list of epics" in t or "Jira shows today's issues" in t, id_
        assert "key list" not in t.lower() and "list of keys" not in t.lower(), id_
    dep = strip_expressions(BLOCKS["dep"])
    assert "by their keys" in dep and "not a search that Jira runs again" in dep           # the dependency links ARE fixed key lists (see link_guard's allowlist)


def test_populations_are_named_where_two_numbers_could_be_confused():
    assert "every epic with the status Done in the release, whatever its Commitment Type" in BLOCKS["bu"]
    assert "Cycle Time per Release also counts epics that AI did not implement, so the two are not comparable" in BLOCKS["eff"]
    cyc = BLOCKS["ch-cycle"].replace("${AI_EXCL_TEXT}", "Maintenance and SOW")
    assert "not limited to AI-implemented epics" in cyc and "it leaves out Maintenance and SOW, which Efficiency does not (Efficiency leaves out Maintenance only)" in cyc
    trend = BLOCKS["trend"]
    assert "Done Capabilities follows Projects only" in trend and "Commitment Type" in trend
    assert "Projects and Teams filters apply to every chart" not in TEMPLATE                  # the old sentence contradicted itself


def test_the_pod_tiles_are_defined_as_the_code_counts_them():
    cy = BLOCKS["cy"]
    assert "no epic planned in the selected cycle" in cy                                     # Idle Pods follows the cycle
    assert "counted over the whole release, not the selected cycle" in cy                   # the other tile does not
    assert "${CY.podWip}" in cy and "reference chosen by the owner, not a program rule" in cy
    assert "except the Pods tiles" in cy                                                   # their numbers open a list in the page, not Jira


def test_dependencies_have_one_disclosure_and_the_gap_rule_has_its_reason():
    assert 'id="dep-dq"' not in TEMPLATE and 'getElementById("dep-dq")' not in TEMPLATE
    assert len(re.findall(r'getElementById\("dep-cap"\)\.innerHTML = defs\(howBody', TEMPLATE)) == 1
    m = re.search(r'const GAP_RULE = "([^"]*(?:\\"[^"]*)*)";', TEMPLATE)
    assert m and "equal due dates are a gap" in m.group(1) and "X is not planned to finish before Y's sprint" in m.group(1)


MANDATED = ["test items not counted", "Open means a status other than Done, Ready for Deploy, Closed, Resolved or Removed", "Release windows run from the Jira version start",
            "values are printed on top of each bar", "The dependency board keeps the due date over the Target Sprint",
            "Rows are sorted by title and columns follow the standard project order", "Removed excluded", "implemented by an AI agent", "nothing here ranks or scores"]


@pytest.mark.parametrize("sentence", MANDATED)
def test_the_sentences_the_owner_asked_to_keep_are_still_in_the_text(sentence):
    assert sentence in TEMPLATE


def test_the_cfb_text_names_its_unit_from_its_own_table_not_a_variable_of_another_function():
    cfb = BLOCKS["cfb"]
    assert "CFB_UNIT[state.cfbGroup].noun" in cfb and "${U.noun}" not in cfb


def test_cycle_time_per_release_is_described_as_maintenance_and_sow_out_ai_or_flagged_not_involved():
    """Owner decision: Cycle Time per Release leaves out the Maintenance AND SOW Issue Categories (the one shared list), counts AI, non-AI and empty-AI Done epics with an EDCT, and has no relation to Flagged."""
    cyc = BLOCKS["ch-cycle"].replace("${AI_EXCL_TEXT}", "Maintenance and SOW")
    assert "Epics in the Maintenance and SOW Issue Categories" in cyc
    assert "whether Implemented by AI Agent is Yes, No or empty" in cyc
    trend = BLOCKS["trend"].replace("${esc(AI_EXCL_TEXT)}", "Maintenance and SOW")
    assert "Cycle Time per Release counts the Done epics that have an EDCT, outside Maintenance and SOW, whether or not AI implemented them" in trend
    for stale in ("count every Done epic of the release", "counts all Done epics", "counts every Done epic", "of every category", "SOW stays in", "SOW is not excluded"):
        assert stale not in TEMPLATE, stale
    assert "Maintenance only" not in cyc.replace("(Efficiency leaves out Maintenance only)", "") and "Maintenance only" not in trend     # only Efficiency is Maintenance-only
    # one list: the cycle population and its link are the AI list, not a second hard-coded copy
    assert 'const AI_EXCLUDED_CATEGORIES = ["Maintenance", "SOW"];' in TEMPLATE
    assert "const cycleExcluded = aiExcluded;" in TEMPLATE and "const CYCLE_KEPT_JQL = AI_KEPT_JQL;" in TEMPLATE
    assert "CYCLE_EXCLUDED_CATEGORY" not in TEMPLATE
    # Efficiency keeps its own Maintenance-only rule and query text
    assert 'const EFFICIENCY_KEPT_JQL = `(cf[10139] is EMPTY OR cf[10139] != "Maintenance")`;' in TEMPLATE
    assert 'basis === "edct" ? EFFICIENCY_KEPT_JQL :' in TEMPLATE
    assert 'e.cat !== "Maintenance" && e.ai && e.edct != null' in TEMPLATE


def test_cycle_time_per_release_has_no_relation_to_flagged():
    """The population (cycleStats), its link (cycleHref) and its copy never read or name Flagged. The EDCT definition sentence ("Flagged days ... not counted") describes the measure, not who is counted."""
    body = TEMPLATE[TEMPLATE.index("function cycleStats"):TEMPLATE.index("const EFFICIENCY_KEPT_JQL")]
    assert not re.search(r"flag|\.fl\b|\bfl\b", body, re.I), body
    cyc = BLOCKS["ch-cycle"]
    for sentence in re.split(r"(?<=\.)\s+", cyc):
        if re.search(r"flag", sentence, re.I):
            assert "Flagged days and the Done day are not counted" in sentence, sentence


def test_flagged_always_means_blocked_in_the_cycles_copy():
    assert "Flagged field set" not in TEMPLATE and "Jira Flagged field" not in TEMPLATE
    cy = BLOCKS["cy"]
    assert "flagged as blocked in Jira (the Flagged field is set)" in cy
    assert "flagged as blocked in Jira, carried over" in cy


def test_the_edct_target_is_still_called_a_target():
    assert "const EDCT_TARGET = 10;" in TEMPLATE
    assert "finish inside the ${EDCT_TARGET}-day target" in BLOCKS["eff"]
    assert "the ≤${EDCT_TARGET} target" in TEMPLATE
    assert not re.search(r"EDCT[^`\n]{0,40}reference", BLOCKS["eff"])


def test_the_edct_and_ai_tiles_say_last_30_days_not_a_calendar_month():
    """Owner decision: the EDCT Days and Epics by AI tiles cover the last 30 days (a rolling window), so no text may call them month to date or equate them with the charts' running period."""
    assert "to = `Last ${WINDOW_DAYS} Days`" in TEMPLATE and "const WINDOW_DAYS = 30;" in TEMPLATE
    assert "`${mname} to Date`" not in TEMPLATE and "to Date`" not in TEMPLATE
    assert "mo = lastDays()" in TEMPLATE and "lastMonths(1)[0]" not in TEMPLATE                  # the tiles use the window, not the calendar month
    assert "lastDays(1)" in TEMPLATE and "lastMonths(2)[0]" not in TEMPLATE                      # the comparison is the 30 days before it
    assert "Previous ${WINDOW_DAYS} days" in TEMPLATE and "previous full month" not in TEMPLATE
    assert "tiles stay monthly" not in TEMPLATE and "the tiles use the last 30 days" in TEMPLATE
    assert "in the last ${WINDOW_DAYS} days (${windowWords(mo)})" in TEMPLATE                      # the hover texts name the window in words, with its dates
    start = TEMPLATE.index("function renderStatus()")
    tiles = TEMPLATE[start:TEMPLATE.index("function monthChart(", start)]
    tile_lines = "\n".join(l for l in tiles.splitlines() if "k: to," in l or "inWin" in l or "out.ai =" in l or "out.edct" in l)       # the two tiles and their comparison (the other tiles say "so far" about the target scope)
    assert tile_lines.count("inWin") >= 6
    for stale in ("to Date", "month-to-date", "so far", "previous month", "${mo.mon}", "${prev.mon}"):
        assert stale not in tile_lines, stale
    # the charts stay calendar-based and say that the tiles are a different window
    assert "The EDCT Days tile at the top is a different window" in BLOCKS["eff"]
    assert "The Epics by AI tile at the top is a different window" in BLOCKS["ai"]
    assert "const lastMonths" not in TEMPLATE and "function lastMonths(n = 4)" in TEMPLATE


def test_the_edct_average_has_no_five_epic_minimum_and_the_ai_share_keeps_it():
    """Owner decision: one Done epic contributes to the EDCT average (Efficiency chart, its head line and tooltip, the EDCT Days tile and its target line). The AI share and every percentile keep MIN_N."""
    assert "const MIN_N = 5;" in TEMPLATE and "const EDCT_MIN_N = 1;" in TEMPLATE
    start = TEMPLATE.index("function renderEfficiency()")
    eff = TEMPLATE[start:TEMPLATE.index("function renderAdoption()", start)]
    assert "MIN_N" not in eff.replace("EDCT_MIN_N", "")                                     # the Efficiency chart never reads the 5-epic constant
    assert "min: EDCT_MIN_N" in eff and "fewer than" not in eff.lower() and "Fewer than" not in eff
    assert "none is shown" not in BLOCKS["eff"].lower() and "fewer than" not in BLOCKS["eff"].lower() and "shown from one epic" in BLOCKS["eff"]
    assert "None is shown for fewer than 5." in BLOCKS["ai"]                                 # the share keeps its rule and says so
    # the tile and its target line use the same constant, never MIN_N
    assert "ms.edctN >= MIN_N" not in TEMPLATE and TEMPLATE.count("ms.edctN >= EDCT_MIN_N") == 3
    assert "only ${ms.edctN} epics, need" not in TEMPLATE
    # the shared monthChart: the placeholder and the empty text follow the chart's own minimum; the AI chart passes none and keeps MIN_N
    chart = TEMPLATE[TEMPLATE.index("function monthChart("):TEMPLATE.index("const defs = html")]
    assert "(o.min == null ? MIN_N : o.min) > 1" in chart and "o.empty ||" in chart
    ai = TEMPLATE[TEMPLATE.index("function renderAdoption()"):TEMPLATE.index("function renderAdoption()") + 1200]
    assert "min:" not in ai and "share: m.done >= MIN_N ? pct(m.ai, m.done) : null" in ai
    # the hover text gives the epic count in the right number
    assert "${r.n} AI-implemented ${epicWord(r.n)}" in eff and "Average over ${ms.edctN} AI-implemented ${epicWord(ms.edctN)} with an EDCT" in TEMPLATE
    # percentiles of Cycle Time per Release are untouched
    assert "ok: vals.length >= MIN_N" in TEMPLATE


def test_blocking_external_scope_is_the_only_outside_scope_chip_and_says_what_it_counts():
    """Owner decision: one chip, Blocked by External (dp=blocking): an item in scope waits on a provider whose project is not selected and is not CXCROSS.
    The chip Blocked by Outside Scope is gone: no chip, no hash value, no count, no label, no empty text. An old dp=blockedby link opens the default view."""
    assert 'value="blocking"> Blocked by External <span class="cnt" data-k="blocking">' in TEMPLATE
    assert 'value="blockedby"' not in TEMPLATE and 'data-k="blockedby"' not in TEMPLATE
    assert "blockedby" not in TEMPLATE and "Blocked by Outside Scope" not in TEMPLATE and "Blocking Outside Scope" not in TEMPLATE
    assert '"gap", "blocking"].includes(h.get("dp"))' in TEMPLATE                                # the whitelist: an old dp=blockedby falls back to the default view
    assert 'blocking: "Blocked by External"}' in TEMPLATE                                    # the Showing line's name for the filter
    # the rule: the provider's project is neither a selected project nor CXCROSS, compared as whole keys
    assert re.search(r'extBlock: inScope\.has\(a\) && !state\.projects\.has\(p\.p\) && p\.p !== DEP_CX\}', TEMPLATE)
    assert 'const DEP_CX = "CXCROSS";' in TEMPLATE and "startsWith(DEP_CX)" not in TEMPLATE and "includes(DEP_CX)" not in TEMPLATE
    assert 'state.depFilter === "blocking" ? x.extBlock' in TEMPLATE and "blocking: extBlock.length" in TEMPLATE
    # the headline clause, the empty state, the definition, the Direction column
    assert "where an item in the selected projects waits on an external provider (not selected, not CXCROSS)." in TEMPLATE
    assert "No external item (not selected, not CXCROSS) blocks an item in the selected projects." in TEMPLATE
    dep = BLOCKS["dep"]
    assert '["Blocked by External", `an item in the selected projects waits on a provider in a project that is not selected and is not CXCROSS' in dep
    assert "CXCROSS items are shown in the CXCROSS section." in dep
    assert "Blocked by outside scope" not in dep and "Blocking outside scope" not in dep
    assert 'x.extBlock ? "Waits on external scope"' in TEMPLATE
    # the headline link is a query with the project clause, inside the URL budget
    assert "project not in (${pkeys([...projectsAll.filter(p => state.projects.has(p)), DEP_CX])})" in TEMPLATE and "h.length <= CY_URL_MAX" in TEMPLATE


# ---- the four proactive tiles of the Cycles Pods block (Not-Started Epics Due Within 7 Days, Waiting Dependents Due Soon, Pods To Level, In-Flight Epics Without a Pod Label)
PROACTIVE_TILES = ["nsSoon", "wait", "level", "noPod"]
PROACTIVE_TITLES = ["Not-Started Epics Due Within ${CY.next} Days", "Waiting Dependents Due Soon", "Pods To Level", "In-Flight Epics Without a Pod Label"]
TIP_MAX_WORDS = 25                # the first line of a tile tooltip is the point, in about 25 words
DEF_MAX_WORDS = 70                # one short definition line per tile in How this is calculated


def _tiles_source() -> str:
    start = TEMPLATE.index("  nsSoon: ({c, act}) =>")
    return TEMPLATE[start:TEMPLATE.index("const CY_STRIP", start)]


def test_the_pods_block_has_six_tiles_in_one_order_on_a_three_column_grid():
    assert 'class="kpis three" id="cy-kpis2"' in TEMPLATE
    assert 'pods: ["nsSoon", "wait", "level", "noPod", "idle", "wip"]' in TEMPLATE         # the four 'act now' tiles first, then the two existing ones
    assert ".kpis.three { grid-template-columns:repeat(3," in TEMPLATE and "@media (max-width:1100px) { .kpis.three { grid-template-columns:repeat(2," in TEMPLATE
    assert ".kpis.six" not in TEMPLATE                                                         # the six-tile strip of the past stays removed (a different class is used)


def test_each_proactive_tile_tooltip_is_the_point_in_about_25_words_then_where_it_opens():
    src = _tiles_source()
    tips = re.findall(r"tipFocus\(((?:`[^`]*`|\"[^\"]*\")), `([^`]*)`\)", src)
    assert len(tips) == 4, tips
    for (title, tip), want in zip(tips, PROACTIVE_TITLES):
        assert title.strip('`"') == want, title
        first, _, second = tip.partition("\\n")
        words = len(strip_expressions(first).split())
        assert words <= TIP_MAX_WORDS, (title, words)
        assert second == "Opens a list below", (title, second)
        assert "cf[" not in tip and "customfield" not in tip and "podRx" not in tip, title


def test_the_proactive_tiles_are_defined_in_the_cycles_disclosure_with_their_thresholds():
    cy = BLOCKS["cy"]
    for name in ("Not-started epics due within ${CY.next} days", "Waiting dependents due soon", "Pods to level", "In-flight epics without a pod label"):
        assert name in cy, name
    # the numbers come from the named constants, not from literals typed twice
    assert "${Math.round(CY.levelSpread * 100)}%" in cy and "at least ${MIN_N} in flight" in cy and "${CY.next} days later" in cy
    assert "the later date counts (the later of the due date and the Target Sprint end)" in cy              # the owner confirmed: the later date counts
    assert "the due date first, else the Target Sprint end" in cy                                          # the dependency rule for the waiting item
    assert "A team is flagged when its busiest and lightest pods differ by" in cy and "of the team's in-flight epics" in cy
    assert "A pod takes part when it has an epic in ${esc(state.release)} that is not Done" in cy
    for m in re.finditer(r"\n\s+\[(?:`|\")(Not-started epics due within|Waiting dependents due soon|Pods to level|In-flight epics without a pod label)[^\n]*", cy):
        words = len(strip_expressions(m.group(0)).split())
        assert words <= DEF_MAX_WORDS, (m.group(1), words)


def test_the_level_thresholds_are_named_constants_and_the_old_gap_rule_is_gone():
    m = re.search(r"const CY = \{([^}]*)\};", TEMPLATE)
    assert m and "levelSpread: 0.40" in m.group(1), m and m.group(1)
    assert "levelGap" not in TEMPLATE and "levelRatio" not in TEMPLATE
    assert "const flagged = total >= MIN_N && spread >= CY.levelSpread - 1e-9;" in TEMPLATE         # the minimum sample is the page's MIN_N
    assert "const MIN_N = 5;" in TEMPLATE


def test_the_proactive_tiles_reuse_the_page_rules_and_add_no_second_copy():
    src = TEMPLATE[TEMPLATE.index("const cyInFlight = e =>"):TEMPLATE.index("const CY_KPI = {")]
    assert "const cyInFlight = e => CLASS.flight.includes(e.s);" in src                              # the class of the existing tile
    assert 'cls(e.s) === "notStarted"' in src                                                         # the repo's status class (CLASS.notStarted), no second list of statuses
    assert "e.due >= CY.asOf" in src and "cyAdd(CY.asOf, CY.next)" in src                              # the page's as-of day and the one window length; e.due is plannedLater
    assert "depModel().openAll" in src and "x.pIn" in src                                              # the dependency model's own open pairs, the provider in scope; its code is not copied
    assert "podRxOf" not in src and "podLabelsOf" not in src                                           # the pod label rule is the one stored on each epic (pl)
    for status in ('"Candidate"', '"In Definition"'):
        assert status not in src, status


def test_the_pod_coverage_note_is_still_in_the_pods_block():
    assert 'id="cy-podnote"' in TEMPLATE and "epics carry a pod label;" in TEMPLATE and "have none (No Pod Label)" in TEMPLATE
