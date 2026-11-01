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
    assert "Epics, due dates, Target Sprints, Flagged and pod labels are updated by Refresh" in cy
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
    assert "Cycle Time per Release counts all Done epics, so the two are not comparable" in BLOCKS["eff"]
    assert "not only AI-implemented epics" in BLOCKS["ch-cycle"]
    trend = BLOCKS["trend"]
    assert "Done Capabilities follows Projects only" in trend and "Commitment Type" in trend
    assert "Projects and Teams filters apply to every chart" not in TEMPLATE                  # the old sentence contradicted itself


def test_the_pod_tiles_are_defined_as_the_code_counts_them():
    cy = BLOCKS["cy"]
    assert "no epic planned in the selected cycle" in cy                                     # Idle Pods follows the cycle
    assert "counted over the whole release, not the selected cycle" in cy                   # the other tile does not
    assert "${CY.podWip}" in cy and "reference chosen by the owner, not a program rule" in cy
    assert "except the two pod tiles" in cy                                                   # their numbers open a list in the page, not Jira


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
