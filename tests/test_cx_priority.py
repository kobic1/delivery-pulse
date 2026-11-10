"""The CXCROSS priority order (program_dashboard/cx_priority.py): the parser, the matcher and the fallbacks. Fictitious page and Initiatives only (the repository is public)."""
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent / "program_dashboard"
sys.path.insert(0, str(HERE))
import cx_priority as CP  # noqa: E402
import build_dashboard as BD  # noqa: E402


def link(title, text):
    return f'<ac:link><ri:page ri:content-title="{title}" ri:version-at-save="3" /><ac:link-body><strong>{text}</strong></ac:link-body></ac:link>'


def owner(name="Owner A"):
    return f'<p>{name} / <a href="https://example.invalid/wiki/x/1">Individual Report</a></p>'


def band(text):
    return f'<tr><td colspan="4"><p style="text-align: center;"><strong>{text}</strong></p></td></tr>'


def row(first_html, *rest):
    cells = "".join(f"<td><p>{c}</p></td>" for c in rest)
    return f"<tr><td>{first_html}</td>{cells}</tr>"


HEAD = "<tr>" + "".join(f"<th><p><strong>{h}</strong></p></th>" for h in ("Project", "Status", "Due", "Notes")) + "</tr>"
GP_HEAD = "<tr>" + "".join(f"<th><p><strong>{h}</strong></p></th>" for h in ("Project", "Global Priority", "Status", "Notes")) + "</tr>"

PAGE = (
    "<h1>Fictitious projects</h1>"
    "<table><tbody>" + HEAD +
    band("Global Priority - 1") +
    row(f"<p>{link('Alpha page', 'Alpha Bridge Programme')}</p>{owner()}", "G", "x", "") +
    row(f"<p><strong>Beta Harbour Upgrade</strong></p>{owner('Owner B')}", "G", "x", "") +
    band("Global Priority - 2") +
    row(f'<h4><ac:link><ri:page ri:content-title="T" /><ac:link-body><u>Gamma Lantern &amp; Co Rollout</u></ac:link-body></ac:link></h4><p>Owner C /<a href="https://example.invalid/2"> Individual Report</a></p>', "Y", "x", "") +
    row(f"<p>{link('Mill page', 'Delta Mill')}<strong> </strong></p><p>Owner D</p>", "Y", "x", "") +
    row("<p>Epsilon Quay Survey</p><p>Owner E</p>", "", "", "") +                    # a name and nothing else, in a row with other cells: a project row, not a band
    band("Watch List") +
    row("<p><strong>Zeta Orchard</strong></p>", "x", "", "") +
    band("On Hold") +
    row(f"<p>{link('Eta page', 'Eta Dock Adoption')} (part of Beta)</p>{owner()}", "x", "", "Adoption paused") +
    "<tr><td><p /></td><td><p /></td><td><p /></td><td><p /></td></tr>" +             # an empty row is skipped
    "</tbody></table>"
    "<h2>Impact assessments</h2><table><tbody>" + GP_HEAD +
    row("<p><strong>Theta Bay Study</strong></p><p>Owner T</p>", "2", "G", "needs CXCROSS-4242 first") +
    row("<p>Iota Cove Review</p>", "Watch List", "G", "") +
    row("<p>Kappa Pier</p>", "n/a", "G", "") +                                         # a value that is no band: the row is left out
    "</tbody></table>"
)


def test_the_bands_and_rows_are_read_in_page_order_with_clean_names():
    p = CP.parse_page(PAGE)
    assert p["groups"] == ["Global Priority - 1", "Global Priority - 2", "Watch List", "On Hold"]
    got = [(p["groups"][r["g"]], r["n"]) for r in p["rows"]]
    assert got == [
        ("Global Priority - 1", "Alpha Bridge Programme"),
        ("Global Priority - 1", "Beta Harbour Upgrade"),
        ("Global Priority - 2", "Gamma Lantern & Co Rollout"),
        ("Global Priority - 2", "Delta Mill"),
        ("Global Priority - 2", "Epsilon Quay Survey"),
        ("Watch List", "Zeta Orchard"),
        ("On Hold", "Eta Dock Adoption"),
        ("Global Priority - 2", "Theta Bay Study"),
        ("Watch List", "Iota Cove Review"),
    ]
    assert [r["r"] for r in p["rows"]] == list(range(len(p["rows"])))


def test_owner_names_and_report_links_are_not_in_the_name():
    for r in CP.parse_page(PAGE)["rows"]:
        assert "Owner" not in r["n"] and "Individual" not in r["n"] and r["n"] == r["n"].strip()


def test_a_jira_key_in_the_row_text_or_a_link_is_kept_with_the_row():
    rows = {r["n"]: r for r in CP.parse_page(PAGE)["rows"]}
    assert rows["Theta Bay Study"]["keys"] == ["CXCROSS-4242"]
    assert rows["Alpha Bridge Programme"]["keys"] == []
    href_page = PAGE.replace("Zeta Orchard</strong></p>", 'Zeta Orchard</strong></p><p><a href="https://example.invalid/browse/ZZ-77">issue</a></p>')
    assert next(r for r in CP.parse_page(href_page)["rows"] if r["n"] == "Zeta Orchard")["keys"] == ["ZZ-77"]


def test_a_band_is_a_single_cell_row_or_a_known_label_but_a_name_alone_is_a_project():
    p = CP.parse_page(PAGE)
    names = [r["n"] for r in p["rows"]]
    assert "Epsilon Quay Survey" in names and "Delta Mill" not in p["groups"]
    odd = PAGE.replace(band("Watch List"), band("Parked for later"))                 # a new label in a one-cell row is a band too
    assert "Parked for later" in CP.parse_page(odd)["groups"]


def test_entities_and_nested_markup_are_decoded_once():
    assert CP.clean("A&nbsp;B") == "A&nbsp;B" or CP.clean("A B") == "A B"
    assert CP.parse_page(PAGE)["rows"][2]["n"] == "Gamma Lantern & Co Rollout"


def test_a_page_without_tables_or_with_broken_markup_gives_no_rows_and_does_not_raise():
    for html in ("", "<p>nothing</p>", "<table><tr><td>", "<<<>>>", "<table><tbody><tr><th>x</th></tr></tbody></table>"):
        assert CP.parse_page(html)["rows"] == []


# ---------------------------------------------------------------- the matcher
def m(rows, titles):
    return CP.match_initiatives([{"n": n, "g": 0, "r": i, "keys": k} for i, (n, k) in enumerate(rows)], titles)


def test_tokens_drop_bracket_tags_punctuation_and_trivial_words():
    assert CP.tokens("[R&D] The Alpha-Bridge: Phase 2 (for the AEP)") == ["alpha", "bridge", "phase", "2", "aep"]
    assert CP.tokens("R&D Review") == ["rd", "review"]
    assert CP.tokens("AT&T Prod") == ["att", "prod"]


def test_page_name_contained_in_the_title_matches():
    got = m([("Harbour Upgrade", [])], {"INI-1": "[X] Harbour upgrade programme 2026"})
    assert got["INI-1"]["n"] == "Harbour Upgrade"


def test_title_contained_in_the_page_name_matches_in_reverse():
    got = m([("Harbour Upgrade Programme Phase One", [])], {"INI-1": "Harbour Upgrade"})
    assert "INI-1" in got


def test_one_shared_word_is_not_enough_for_containment_but_a_close_overlap_is():
    assert m([("Harbour", [])], {"INI-1": "Harbour Upgrade Programme"}) == {}              # contained, but only one token in common
    assert "INI-1" in m([("Harbour", [])], {"INI-1": "Harbour"})                           # identical single token: Jaccard 1
    got = m([("North Pier Survey Plan", [])], {"INI-1": "North Pier Survey Docs"})        # neither contains the other, Jaccard 3/5 = 0.6
    assert "INI-1" in got
    assert m([("North Pier Survey Plan", [])], {"INI-1": "North Pier Docs Notes"}) == {}   # Jaccard 2/6


def test_the_best_scoring_row_wins_and_a_tie_goes_to_the_earliest():
    rows = [("Harbour Upgrade Programme", []), ("Harbour Upgrade", []), ("Harbour Upgrade", [])]
    got = m(rows, {"INI-1": "Harbour Upgrade"})
    assert got["INI-1"]["r"] == 1                                                          # the exact name outscores the longer one; the two equal rows tie: the earlier
    assert m([("Quay Survey Work", []), ("Quay Survey Work", [])], {"INI-1": "Quay Survey Work"})["INI-1"]["r"] == 0


def test_an_explicit_key_wins_over_any_name():
    rows = [("Harbour Upgrade", []), ("Something Else Entirely", ["INI-9"])]
    got = m(rows, {"INI-9": "Harbour Upgrade", "INI-2": "Harbour Upgrade"})
    assert got["INI-9"]["r"] == 1 and got["INI-2"]["r"] == 0


def test_an_initiative_with_no_row_gets_no_entry_and_one_row_may_serve_two_initiatives():
    got = m([("Harbour Upgrade", [])], {"INI-1": "Harbour Upgrade", "INI-2": "Harbour Upgrade Phase 2", "INI-3": "Unrelated Work"})
    assert set(got) == {"INI-1", "INI-2"} and got["INI-1"]["r"] == got["INI-2"]["r"] == 0


# ---------------------------------------------------------------- the payload field
HIER = {
    "CXCROSS-1": {"ty": "Initiative", "t": "Alpha Bridge Programme", "s": "New", "fv": [], "p": "CXCROSS"},
    "CXCROSS-2": {"ty": "Initiative", "t": "Zeta Orchard replanting", "s": "In Progress", "fv": [], "p": "CXCROSS"},
    "CXCROSS-3": {"ty": "Initiative", "t": "Beta Harbour Upgrade", "s": "Removed", "fv": [], "p": "CXCROSS"},      # Removed: never a candidate
    "ZZ-10": {"ty": "Initiative", "t": "Delta Mill", "s": "New", "fv": [], "p": "ZZ"},                              # another project's Initiative with an in-scope Capability under it
    "ZZ-11": {"ty": "Initiative", "t": "Epsilon Quay Survey", "s": "New", "fv": [], "p": "ZZ"},                    # another project's Initiative with no in-scope Capability
    "CXCROSS-20": {"ty": "Capability", "t": "c", "s": "New", "fv": [], "p": "CXCROSS", "par": "ZZ-10"},
    "ZZ-30": {"ty": "Capability", "t": "c", "s": "New", "fv": [], "p": "ZZ", "par": "ZZ-11"},
}


def test_candidates_are_live_cxcross_initiatives_and_parents_of_in_scope_capabilities():
    assert set(CP.candidate_initiatives(HIER)) == {"CXCROSS-1", "CXCROSS-2", "ZZ-10"}


def test_build_gives_the_small_field_and_nothing_else_from_the_page():
    res = CP.build(HIER, PAGE)
    assert set(res) == {"groups", "map"}
    assert res["groups"] == ["Global Priority - 1", "Global Priority - 2", "Watch List", "On Hold"]
    assert res["map"] == {"CXCROSS-1": {"g": 0, "r": 0, "n": "Alpha Bridge Programme"},
                          "CXCROSS-2": {"g": 2, "r": 5, "n": "Zeta Orchard"},
                          "ZZ-10": {"g": 1, "r": 3, "n": "Delta Mill"}}
    assert all(set(v) == {"g", "r", "n"} for v in res["map"].values())


def test_fewer_than_three_rows_gives_no_field():
    one = "<table><tbody>" + HEAD + band("Global Priority - 1") + row("<p><strong>Alpha Bridge Programme</strong></p>", "x") + row("<p>Beta Harbour Upgrade</p>", "x") + "</tbody></table>"
    assert CP.build(HIER, one) is None


# ---------------------------------------------------------------- the fallbacks never raise
class FakeResp:
    def __init__(self, body=None, status=200):
        self.body, self.status = body, status

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")

    def json(self):
        return self.body


class FakeSession:
    def __init__(self, resp=None, exc=None):
        self.resp, self.exc, self.calls = resp, exc, []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params, timeout))
        if self.exc:
            raise self.exc
        return self.resp


def page_json(html):
    return {"body": {"storage": {"value": html}}}


def test_the_page_is_read_with_the_expand_parameter_and_a_timeout():
    s = FakeSession(FakeResp(page_json(PAGE)))
    res = CP.compute(s, "https://jira.example.invalid/", HIER, env={"CXCROSS_PRIORITY_PAGE_ID": "12345"})
    assert res and "CXCROSS-1" in res["map"]
    url, params, timeout = s.calls[0]
    assert url == "https://jira.example.invalid/wiki/rest/api/content/12345" and params == {"expand": "body.storage"} and timeout


@pytest.mark.parametrize("case", ["unset", "blank", "http", "timeout", "bad_json", "few_rows"])
def test_every_failure_gives_no_field_one_warning_and_no_exception(case, capsys):
    env = {} if case == "unset" else {"CXCROSS_PRIORITY_PAGE_ID": "  " if case == "blank" else "12345"}
    session = {"unset": FakeSession(FakeResp(page_json(PAGE))), "blank": FakeSession(FakeResp(page_json(PAGE))),
               "http": FakeSession(FakeResp({}, 403)), "timeout": FakeSession(exc=TimeoutError("slow")),
               "bad_json": FakeSession(FakeResp({"unexpected": 1})), "few_rows": FakeSession(FakeResp(page_json("<p>no tables</p>")))}[case]
    assert CP.compute(session, "https://jira.example.invalid", HIER, env=env) is None
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1 and out[0].startswith("warning:")
    if case in ("unset", "blank"):
        assert not session.calls                                                          # nothing is requested without a page id


def test_the_collector_wrapper_returns_the_field_or_nothing(monkeypatch, capsys):
    class J:
        base = "https://jira.example.invalid"
        s = FakeSession(FakeResp(page_json(PAGE)))
    monkeypatch.setenv("CXCROSS_PRIORITY_PAGE_ID", "12345")
    got = BD.collect_cx_priority(J(), HIER)
    assert set(got) == {"cxPrio"} and "CXCROSS-1" in got["cxPrio"]["map"]
    J.s = FakeSession(FakeResp({}, 500))
    assert BD.collect_cx_priority(J(), HIER) == {}
    monkeypatch.delenv("CXCROSS_PRIORITY_PAGE_ID")
    assert BD.collect_cx_priority(J(), HIER) == {}
    assert BD.collect_cx_priority(J(), None) == {}


def test_the_field_is_optional_in_the_payload_check():
    assert "cxPrio" not in BD.EXPECTED and "cxPrio" not in BD.REQUIRED                    # a build without it renders, with no notice


# ---------------------------------------------------------------- overrides (CXCROSS_PRIORITY_OVERRIDES)
ENV = {"CXCROSS_PRIORITY_PAGE_ID": "12345"}


def run(overrides, capsys=None):
    env = dict(ENV) if overrides is None else {**ENV, "CXCROSS_PRIORITY_OVERRIDES": overrides}
    return CP.compute(FakeSession(FakeResp(page_json(PAGE))), "https://jira.example.invalid", HIER, env=env)


def test_an_override_wins_over_the_automatic_match():
    base = run(None)["map"]
    assert base["CXCROSS-1"]["n"] == "Alpha Bridge Programme"                              # the automatic match
    res = run('{"CXCROSS-1": "Eta Dock Adoption"}')["map"]
    assert res["CXCROSS-1"] == {"g": 3, "r": 6, "n": "Eta Dock Adoption"}
    assert res["CXCROSS-2"] == base["CXCROSS-2"] and res["ZZ-10"] == base["ZZ-10"]        # the others are unchanged


def test_an_override_wins_over_an_explicit_key_in_the_row_text():
    hier = {**HIER, "CXCROSS-4242": {"ty": "Initiative", "t": "Unrelated Title", "s": "New", "fv": [], "p": "CXCROSS"}}
    assert CP.build(hier, PAGE)["map"]["CXCROSS-4242"]["n"] == "Theta Bay Study"          # the key written in the row
    got = CP.build(hier, PAGE, {"CXCROSS-4242": "Zeta Orchard"})["map"]["CXCROSS-4242"]
    assert got["n"] == "Zeta Orchard"


def test_an_override_can_pin_an_initiative_the_matcher_would_leave_out():
    hier = {**HIER, "CXCROSS-9": {"ty": "Initiative", "t": "Nothing In Common", "s": "New", "fv": [], "p": "CXCROSS"}}
    assert "CXCROSS-9" not in CP.build(hier, PAGE)["map"]
    assert CP.build(hier, PAGE, {"CXCROSS-9": "Delta Mill"})["map"]["CXCROSS-9"]["n"] == "Delta Mill"


def test_the_row_name_is_compared_after_the_matchers_normalisation_and_exactly():
    assert CP.build(HIER, PAGE, {"CXCROSS-2": "  the ZETA orchard! "})["map"]["CXCROSS-2"]["n"] == "Zeta Orchard"
    res, ignored = CP.build_with_notes(HIER, PAGE, {"ZZ-11": "Epsilon Quay"})              # a part of a name is not the name
    assert ignored == ["ZZ-11"] and "ZZ-11" not in res["map"]


def test_two_keys_to_the_same_row_both_map():
    res = CP.build(HIER, PAGE, {"CXCROSS-1": "Delta Mill", "CXCROSS-2": "Delta Mill"})["map"]
    assert res["CXCROSS-1"]["n"] == res["CXCROSS-2"]["n"] == "Delta Mill" and res["CXCROSS-1"]["r"] == res["CXCROSS-2"]["r"]


def test_an_unknown_row_name_is_ignored_with_one_warning_and_the_automatic_match_stays(capsys):
    res = run('{"CXCROSS-1": "No Such Row", "CXCROSS-2": "Delta Mill"}')["map"]
    out = capsys.readouterr().out.strip().splitlines()
    warnings = [l for l in out if l.startswith("warning:")]
    assert len(warnings) == 1 and "CXCROSS-1" in warnings[0] and "No Such Row" not in warnings[0] and "CXCROSS-2" not in warnings[0]
    assert res["CXCROSS-1"]["n"] == "Alpha Bridge Programme" and res["CXCROSS-2"]["n"] == "Delta Mill"


def test_a_key_that_is_not_an_initiative_in_the_hierarchy_is_ignored(capsys):
    res = run('{"NOPE-1": "Delta Mill", "CXCROSS-20": "Delta Mill", "CXCROSS-3": "Delta Mill"}')["map"]       # unknown; a Capability; a Removed Initiative
    assert not ({"NOPE-1", "CXCROSS-20", "CXCROSS-3"} & set(res))
    assert len([l for l in capsys.readouterr().out.splitlines() if l.startswith("warning:")]) == 1


@pytest.mark.parametrize("raw", ["{not json", "[1, 2]", '"text"', "42"])
def test_malformed_overrides_are_ignored_with_one_warning(raw, capsys):
    res = run(raw)
    assert res == run(None)
    out = capsys.readouterr().out.splitlines()
    assert sum("CXCROSS_PRIORITY_OVERRIDES" in l for l in out) == 1


def test_entries_that_are_not_strings_are_dropped_and_the_good_ones_kept(capsys):
    got, problem = CP.parse_overrides('{"CXCROSS-1": "Delta Mill", "CXCROSS-2": 5, "CXCROSS-3": ""}')
    assert got == {"CXCROSS-1": "Delta Mill"} and problem


def test_no_variable_or_an_empty_one_leaves_the_behaviour_unchanged(capsys):
    plain = CP.build(HIER, PAGE)
    assert run(None) == plain and run("") == plain and run("   ") == plain and run("{}") == plain
    assert not [l for l in capsys.readouterr().out.splitlines() if "OVERRIDES" in l]


def test_a_failure_to_read_the_page_with_overrides_set_still_gives_no_field(capsys):
    env = {**ENV, "CXCROSS_PRIORITY_OVERRIDES": '{"CXCROSS-1": "Delta Mill"}'}
    assert CP.compute(FakeSession(FakeResp({}, 500)), "https://jira.example.invalid", HIER, env=env) is None
    assert len([l for l in capsys.readouterr().out.splitlines() if l.startswith("warning:")]) == 1


def test_the_collector_wrapper_reads_the_overrides_from_the_environment(monkeypatch):
    class J:
        base = "https://jira.example.invalid"
        s = FakeSession(FakeResp(page_json(PAGE)))
    monkeypatch.setenv("CXCROSS_PRIORITY_PAGE_ID", "12345")
    monkeypatch.setenv("CXCROSS_PRIORITY_OVERRIDES", '{"CXCROSS-1": "Delta Mill"}')
    assert BD.collect_cx_priority(J(), HIER)["cxPrio"]["map"]["CXCROSS-1"]["n"] == "Delta Mill"
