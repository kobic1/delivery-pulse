"""Delivery Pulse: the wording standard of the hover texts (tooltips), as static checks on program_dashboard/dashboard.template.html.

The standard is in program_dashboard/README.md ("Tooltip standard"): one pattern (number + what it counts + scope, then one line), one shared text per concept, one `nn` helper for every counted noun,
no hand-written "Opens N ... in Jira" beside the page's own "Click to open in Jira", no instruction about another element, one term per concept, every tooltip reachable on keyboard focus.
These tests read the template only (no browser, no network); `tests/dashboard_browser/link_guard.py` reads the rendered hovers of the fixture against the same word budget.
Synthetic strings only; nothing here names a real issue, team or pod.
"""
import re
from pathlib import Path

from tests.test_dashboard_copy import _skip_braces, _skip_template

TEMPLATE = (Path(__file__).resolve().parent.parent / "program_dashboard" / "dashboard.template.html").read_text(encoding="utf-8")

# wording that the rewrite retired; each one was a defect in the review of the hover texts
FORBIDDEN = [
    ("(in progress)", "a running release is always written (running)"),
    ("(current quarter)", "a running period is always written (running)"),
    ("Provisional:", "a running release is always written (running)"),
    ("hover or focus the flag", "a tooltip never tells the reader to hover or focus another element"),
    ("Hover a figure", "a tooltip never tells the reader to hover"),
    ("the number above opens", "a tooltip never points at another element"),
    (": rule ${", "rule a and b were unexplained shorthand in a hover"),
    ("release train", "internal vocabulary: say 'not a release on this page'"),
    ("CY_TIP", "the Cycles caveat is said once in How this is calculated, not on every number"),
    ("Jira finds these epics again", "the Cycles caveat is said once in How this is calculated, not on every number"),
    ("This opens the exact issues counted here", "the exact-list line is EXACT_NOTE(m), with the number of issues"),
    ("Click opens the issues in Jira", "the page adds 'Click to open in Jira' itself"),
    ("alert pipeline", "internal vocabulary"),
    ("live alert rule", "internal vocabulary: 'the same limit as the Teams alerts'"),
    ("Table A", "the page shows table titles, not letters"),
    ("complete pairs", "register: 'pairs with a Done end'"),
    ("Flagged field set", "the settled wording is 'The Flagged field is set'"),
]
HAND_WRITTEN_OPENS = re.compile(r"Opens (?:the )?\$\{[^}]*\} (?:epics|issues|Jira issues) in Jira|Opens \d+ (?:epics|issues) in Jira|opens \$\{[^}]*\} issues in Jira")


def _split_args(s: str, i: int):
    """i is just after 'name(': the top-level arguments of the call and the index of its closing ')'."""
    args, depth, start = [], 1, i
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
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth == 0:
                args.append(s[start:i].strip())
                return args, i
        elif c == "," and depth == 1:
            args.append(s[start:i].strip())
            start = i + 1
        i += 1
    raise AssertionError("unterminated call")


def _calls(name: str):
    for m in re.finditer(r"(?<![\w.])" + re.escape(name) + r"\(", TEMPLATE):
        # skip the declaration (const tlink = (text, h, tip) => ...) and calls inside comments
        line_start = TEMPLATE.rfind("\n", 0, m.start()) + 1
        if TEMPLATE[line_start:m.start()].lstrip().startswith("//"):
            continue
        args, _ = _split_args(TEMPLATE, m.end())
        yield m.start(), args


def _template_literal(arg: str):
    return arg[1:-1] if arg.startswith("`") and arg.endswith("`") else None


def test_the_retired_wording_is_gone():
    for text, why in FORBIDDEN:
        assert text not in TEMPLATE, f"{text!r}: {why}"
    for no, line in enumerate(TEMPLATE.splitlines(), 1):
        if "aria-label=" in line:                                                                   # an accessible name of its own ("... Opens 5 issues in Jira.") is not a tooltip
            continue
        assert not HAND_WRITTEN_OPENS.search(line), f"line {no}: a hand-written 'Opens N ... in Jira' sits beside the page's own 'Click to open in Jira'"


def test_the_exact_list_line_is_a_function_of_the_number_of_issues():
    assert "const EXACT_NOTE = m =>" in TEMPLATE
    assert 'Exact list of ${m} ${m === 1 ? "issue" : "issues"}; it will not follow later changes in Jira.' in TEMPLATE
    assert "tip + \"\\n\" + EXACT_NOTE(keyCount(h))" in TEMPLATE                           # the number is computed from the link, never typed
    assert "keyCount(h) > 3 && !/exact|by key/i.test(tip)" in TEMPLATE                      # a tip that already says it is exact is not given a second line
    assert 'const EXACT_NOTE = "' not in TEMPLATE


def test_one_helper_for_every_counted_noun():
    assert 'const nn = (n, one, many) => `${n.toLocaleString("en-US")} ${n === 1 ? one : many}`;' in TEMPLATE
    assert "const runName = r => r + (isProv(r) ? \" (running)\" : \"\");" in TEMPLATE
    # a number printed in front of a plural noun inside a tlink tooltip must go through nn (or cyEp), so a count of 1 never reads "1 epics"
    bad = []
    for pos, args in _calls("tlink"):
        if len(args) < 3:
            continue
        lit = _template_literal(args[2])
        if lit is None:
            continue
        for m in re.finditer(r"\$\{([^{}]*)\} (epics|bugs|issues|Capabilities|dependencies|pods|items|cases|CFBs|regressions)\b", lit):
            if not re.search(r"\bnn\(|cyEp\(|\.length\s*===\s*1", m.group(1)) and m.group(1) not in ("pm.done", "p"):      # pm.done is at least 5 where it is printed; p is a project key ("PMN epics")
                bad.append((TEMPLATE.count("\n", 0, pos) + 1, m.group(0)))
    assert not bad, f"a count in front of a plural noun without nn(): {bad[:8]}"


def test_every_hover_only_span_is_focusable_and_read_by_a_screen_reader():
    assert "const tipSpan" not in TEMPLATE and "tipSpan(" not in TEMPLATE                  # one helper: tipFocus
    m = re.search(r"const tipFocus = \(text, tip, name\) => `<span class=\"tt\" tabindex=\"0\" role=\"img\" aria-label=\"([^\n]*)\" \$\{tipAttr\(tip, \"\"\)\}>\$\{text\}</span>`;", TEMPLATE)
    assert m, "tipFocus must be a focusable span with role img and an aria-label made from its text and its tip"
    assert "name || plainOf(text)" in m.group(1)
    assert len(re.findall(r'<span class="tt" ', TEMPLATE)) == 1, "a hover-only span must come from tipFocus"       # (the Back to Top label is a plain span with no tooltip)
    # an info mark and a chart mark keep their own focusable markup
    assert 'class="infomark" id="${id}" tabindex="0" role="img"' in TEMPLATE


def test_tipPass_does_not_read_text_from_labels_or_tiles():
    body = TEMPLATE[TEMPLATE.index("function tipPass() {"):TEMPLATE.index('window.addEventListener("resize", () => enhanceScrollers());')]
    for stale in ('closest(".kpi")', 'querySelector(".l")', "closest(\".key .it\")", "Done epics, and the scope", 'closest("#dq")', "#bu-cap\")"):
        assert stale not in body, stale
    assert "tb.dataset.noun" in body
    # the info mark's hidden text is not part of the name of the value link
    assert 'querySelectorAll(".infomark, .sr").forEach(x => x.remove())' in TEMPLATE


# the few tlink tooltips that open with words, not with the number: the line says what the figure is a comparison of
LITERAL_START_OK = ("The previous ${WINDOW_DAYS} days",)


def test_a_tlink_tooltip_starts_with_the_number_it_explains():
    bad = []
    for pos, args in _calls("tlink"):
        if len(args) < 3:
            continue
        lit = _template_literal(args[2])
        if lit is None or lit.startswith("${") or lit.startswith(LITERAL_START_OK):
            continue
        bad.append((TEMPLATE.count("\n", 0, pos) + 1, lit[:60]))
    assert not bad, f"a tooltip that does not start with a placeholder (the number): {bad[:8]}"


def test_the_target_scope_text_is_written_once():
    assert TEMPLATE.count("the first day of W1") >= 1
    tip = re.search(r"tip: !win \? (.*)\n\s+: `(.*)`};", TEMPLATE)
    assert tip, "targetBase must carry the one shared tooltip of the target scope"
    assert "Committed or Not Set." in tip.group(2) and "target epic" in tip.group(2)
    # the places that explain the target scope reuse TB.tip as it is: no extra first line in front of it
    assert not re.search(r"`[^`\n]*\\n\$\{TB\.tip\}`", TEMPLATE)


def test_a_cycles_number_has_no_repeated_caveat_and_names_its_row():
    assert "const cyNum = (list, what, detail, ...qa) => cyNumT(" in TEMPLATE
    assert "const cyRowOf = g => g ? cyCtx(g)" in TEMPLATE                                  # the second line of a row's number says which row it belongs to
    assert "Jira finds the epics again when you open a link" in TEMPLATE                   # the caveat stays once, in the Links line of How this is calculated


def test_the_dependency_card_has_no_hover_of_its_own():
    assert '<article class="bcard">' in TEMPLATE and "function cardTip" not in TEMPLATE
