"""The release resolver for non-CXone products (rule v1): fictitious versions and counts only, never a real project's numbers."""
import datetime as dt
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent / "program_dashboard"
sys.path.insert(0, str(HERE))
import product_releases as PR  # noqa: E402

TODAY = dt.date(2026, 11, 8)


def row(name, total, open_all, open_epics, in_prog=0, recent=0, start=None, release=None):
    return {"name": name, "start": start, "release": release, "total": total, "open_all": open_all, "open_epics": open_epics, "epics_in_progress": in_prog, "recent": recent}


def names(res):
    return [(res[t] or {}).get("name") for t in ("major", "minor", "future")]


# ---------------------------------------------------------------- names and candidates
def test_names_are_classified_by_their_number_of_segments_and_line_prefix():
    assert PR.tier_of("7.4") == "major" and PR.tier_of("ZZ31.2") == "major" and PR.tier_of("31.2") == "major"
    assert PR.tier_of("7.4.1") == "minor" and PR.tier_of("6.1.9.2") == "minor"
    assert PR.tier_of("ASC_2026Q1") is None and PR.tier_of("12") is None
    assert PR.split_name("Mob_3.8.1") == ("Mob_", (3, 8, 1)) and PR.tier_of("Mob_3.8.1") == "minor" and PR.tier_of("Mob_3.9") == "major"
    assert PR.split_name("ZZ31.2") == ("ZZ", (31, 2)) and PR.split_name("7.4.1") == ("", (7, 4, 1))


def test_placeholders_released_archived_and_old_pi_names_are_not_candidates():
    ok = {"name": "7.4", "released": False, "archived": False}
    assert PR.is_candidate(ok)
    assert not PR.is_candidate({**ok, "released": True}) and not PR.is_candidate({**ok, "archived": True})
    for bad in ("Future 7.4", "7.4 DO NOT CLONE", "PI.2024.3", "Hotfixes"):
        assert not PR.is_candidate({**ok, "name": bad})


# ---------------------------------------------------------------- the pick
def test_open_epics_decide_not_open_issues_so_a_bug_heavy_version_does_not_win():
    rows = [row("7.4", 400, 40, 12, 3, 50, release="2026-12-01"), row("7.0", 3000, 500, 3, 1, 300, release="2027-01-30")]       # 7.0 has far more open issues, but they are bugs
    assert names(PR.resolve("PX", rows, TODAY))[0] == "7.4"


def test_confidence_high_when_the_leader_has_twice_the_runner_up_medium_close_low_when_level():
    high = PR.resolve("PX", [row("7.4", 100, 30, 20, 2, 9), row("7.3", 100, 30, 9, 2, 9)], TODAY)
    medium = PR.resolve("PX", [row("7.4", 100, 30, 14, 2, 9), row("7.3", 100, 30, 10, 2, 9)], TODAY)
    low = PR.resolve("PX", [row("7.4", 100, 30, 10, 2, 9), row("7.3", 100, 30, 10, 2, 9)], TODAY)
    assert [high["major"]["confidence"], medium["major"]["confidence"], low["major"]["confidence"]] == ["HIGH", "MEDIUM", "LOW"]
    assert any("pin it" in w for w in low["warnings"])


def test_a_dated_tie_goes_to_the_nearest_future_release_and_an_undated_one_loses_it():
    a = row("7.4", 100, 30, 10, 2, 9, release="2026-12-20")
    b = row("7.3", 100, 30, 10, 2, 9, release="2026-11-20")
    c = row("7.2", 100, 30, 10, 2, 9)
    assert PR.resolve("PX", [a, b, c], TODAY)["major"]["name"] == "7.3"
    assert PR.resolve("PX", [a, c], TODAY)["major"]["name"] == "7.4"


def test_a_running_major_whose_release_date_has_passed_is_medium_and_says_so():
    res = PR.resolve("PX", [row("7.4", 100, 30, 20, 2, 9, release="2026-10-01"), row("7.3", 100, 30, 5, 2, 9)], TODAY)
    assert res["major"]["confidence"] == "MEDIUM" and any("already past" in w for w in res["warnings"])


def test_the_minor_is_picked_apart_from_the_major_and_is_none_when_nothing_runs():
    rows = [row("7.4", 100, 30, 10, 2, 9), row("7.4.1", 60, 40, 6, 1, 9), row("7.3.2.1", 20, 1, 0, 0, 9)]
    assert names(PR.resolve("PX", rows, TODAY))[:2] == ["7.4", "7.4.1"]
    assert PR.resolve("PX", [row("7.4", 100, 30, 10, 2, 9)], TODAY)["minor"] is None


def test_the_future_is_the_next_major_above_the_running_one_and_says_starting_when_work_began():
    rows = [row("7.4", 100, 30, 10, 2, 9), row("7.5", 10, 10, 4, 0, 2), row("7.6", 3, 3, 2, 0, 0)]
    res = PR.resolve("PX", rows, TODAY)
    assert res["future"]["name"] == "7.5" and res["future"]["state"] == "planned"
    started = PR.resolve("PX", [row("7.4", 100, 30, 10, 2, 9), row("7.5", 10, 10, 4, 1, 2)], TODAY)
    assert started["future"]["state"] == "starting"
    assert PR.resolve("PX", [row("7.4", 100, 30, 10, 2, 9)], TODAY)["future"] is None


def test_a_line_prefix_keeps_its_own_order_so_zz31_1_is_followed_by_zz31_2_not_by_a_plain_number():
    rows = [row("ZZ31.1", 100, 60, 38, 5, 60), row("ZZ31.2", 8, 6, 2, 0, 1), row("40.0", 5, 5, 3, 0, 1)]
    assert names(PR.resolve("PY", rows, TODAY)) == ["ZZ31.1", None, "ZZ31.2"]


def test_a_version_with_no_dates_at_all_resolves_from_work_alone():
    res = PR.resolve("PY", [row("ZZ31.1", 100, 60, 38, 5, 60), row("ZZ31.0", 400, 5, 1, 0, 9)], TODAY)
    assert res["major"]["name"] == "ZZ31.1" and res["major"]["release"] is None


def test_closing_out_versions_are_footnotes_never_running_and_a_new_small_version_is_not_one():
    rows = [row("7.4", 100, 30, 10, 2, 9), row("7.3", 164, 2, 0, 0, 60, release="2026-10-30"), row("7.6", 3, 3, 3, 0, 3)]
    res = PR.resolve("PX", rows, TODAY)
    assert res["closingOut"] == ["7.3"] and res["major"]["name"] == "7.4"


def test_nothing_running_says_none_and_warns():
    res = PR.resolve("PX", [row("7.4", 100, 2, 0, 0, 1)], TODAY)
    assert res["major"] is None and any("no running Major" in w for w in res["warnings"])


# ---------------------------------------------------------------- overrides
def test_a_pin_wins_and_is_marked():
    rows = [row("7.4", 100, 30, 20, 2, 9), row("7.3", 100, 30, 5, 2, 9)]
    res = PR.resolve("PX", rows, TODAY, {"PX": {"major": {"version": "7.3", "reason": "owner", "pinned_on": "2026-11-08", "expires": "2026-12-31"}}})
    assert res["major"]["name"] == "7.3" and res["major"]["confidence"] == "PINNED" and res["override"] is True


def test_an_expired_or_unknown_pin_is_ignored_with_a_warning():
    rows = [row("7.4", 100, 30, 20, 2, 9), row("7.3", 100, 30, 5, 2, 9)]
    expired = PR.resolve("PX", rows, TODAY, {"PX": {"major": {"version": "7.3", "expires": "2026-11-01"}}})
    unknown = PR.resolve("PX", rows, TODAY, {"PX": {"major": "9.9"}})
    for res in (expired, unknown):
        assert res["major"]["name"] == "7.4" and res["override"] is False and res["warnings"]


def test_an_override_for_another_project_is_not_applied():
    rows = [row("7.4", 100, 30, 20, 2, 9), row("7.3", 100, 30, 5, 2, 9)]
    assert PR.resolve("PX", rows, TODAY, {"PQ": {"major": "7.3"}})["major"]["name"] == "7.4"


# ---------------------------------------------------------------- windows (the collector side, no Jira)
def test_a_release_with_only_a_release_date_starts_the_day_its_first_epic_was_created_and_is_flagged():
    import build_dashboard as BD
    res = PR.resolve("PX", [row("7.4", 100, 30, 10, 2, 9, release="2027-01-29"), row("7.5", 10, 10, 4, 0, 2, start="2026-03-01", release="2026-10-30")], TODAY)
    epics = [{"fv": ["7.4"], "cr": "2025-06-10"}, {"fv": ["7.4"], "cr": "2024-02-01"}, {"fv": ["7.5"], "cr": "2026-03-03"}]
    wins = BD.product_windows(res, ["7.4", "7.5"])
    assert wins == {"7.5": ["2026-03-01", "2026-10-30"]}                                  # only a version with both dates has a window of its own
    assert BD.derive_windows(res, ["7.4", "7.5"], epics, wins) == ["7.4"]
    assert wins["7.4"] == ["2024-02-01", "2027-01-29"]


def test_a_release_with_no_dates_gets_no_window():
    import build_dashboard as BD
    res = PR.resolve("PY", [row("ZZ31.1", 100, 60, 38, 5, 60)], TODAY)
    wins = BD.product_windows(res, ["ZZ31.1"])
    assert BD.derive_windows(res, ["ZZ31.1"], [{"fv": ["ZZ31.1"], "cr": "2026-01-01"}], wins) == [] and wins == {}


# ---------------------------------------------------------------- a product that offers every unreleased version
def test_resolve_all_lists_every_version_oldest_first_and_opens_on_the_one_due_soonest():
    rows = [row("Xp_2.9.0", 3, 3, 2), row("Xp_2.8.1", 8, 5, 1, release="2026-11-25"), row("Xp_2.10.0", 0, 0, 0), row("Xp_2.8.0", 9, 0, 0, release="2026-10-23")]
    res = PR.resolve_all("PX", rows, TODAY)
    assert res["releases"] == ["Xp_2.8.0", "Xp_2.8.1", "Xp_2.9.0", "Xp_2.10.0"]            # numeric order: 2.10 comes after 2.9
    assert res["major"]["name"] == "Xp_2.8.1" and res["minor"] is None and res["future"] is None and res["mode"] == "all-unreleased"


def test_resolve_all_without_a_dated_version_opens_on_the_lowest_and_without_versions_on_none():
    assert PR.resolve_all("PX", [row("Xp_2.9.0", 1, 1, 1), row("Xp_2.8.1", 1, 1, 1)], TODAY)["major"]["name"] == "Xp_2.8.1"
    empty = PR.resolve_all("PX", [], TODAY)
    assert empty["major"] is None and empty["releases"] == [] and empty["warnings"]
