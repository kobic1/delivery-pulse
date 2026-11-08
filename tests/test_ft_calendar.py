"""program_dashboard/ft_calendar.py: which calendar events are FT enablement events, and what its parts are (fictitious titles)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "program_dashboard"))
import ft_calendar as FT  # noqa: E402


def ev(title, day="2026-11-10", color="#DE350B"):
    return {"title": title, "start": f"{day}T00:00:00.000+02:00", "backgroundColor": color, "id": title + day}


def test_status_tags_and_flags_come_off_the_title():
    assert FT.split_title("Enable 26.4 FTs on ZA1 CHG0000001") == ("Enable 26.4 FTs on ZA1 CHG0000001", "done", "")
    assert FT.split_title("(APPR) Enable 26.4 FTs on ZA1 CHG0000001")[1:] == ("appr", "")
    assert FT.split_title("(TENT) Enable 26.4 FT's on EU2 CHG0000002")[1:] == ("tent", "")
    assert FT.split_title("(r) Enable 26.4 FTs on B2, B32 CHG0000003")[1:] == ("ready", "")
    assert FT.split_title("ON HOLD (APPR) Enable 26.2 FTs on AE1 CHG0000004")[1:] == ("appr", "hold")
    assert FT.split_title("***ROLLED BACK THIS MORNING*** Enable 26.2 FTs on NA1 CHG0000005")[2] == "rollback"


def test_only_red_enable_events_of_release_26_or_later_are_kept():
    raw = [ev("Enable 26.4 FTs on ZA1 CHG0000001"), ev("(TENT) Enable 26.4 FT's on EU2 CHG0000002"), ev("Enable 25.4 FTs on AU1 CHG0000003"),
           ev("Enable 26.4 FTs on ZA1 CHG0000004", color="#0052CC"), ev("26.1 FT enablement for NA1 CHG0000005"), ev("26.3 thru CU1BF3 to LO26 CHG0000006"),
           ev("(TENT) 27.1 FT Enablement on M35", day="2027-02-01"), ev("(TENT) Re-Enable 26.3 FT on M35"), ev("Dev Done for 26.4")]
    got = FT.ft_events(raw)
    assert [(e["d"], e["r"], e["t"]) for e in got] == [("2026-11-10", "26.4", "ZA1"), ("2026-11-10", "26.4", "EU2"), ("2027-02-01", "27.1", "M35")]
    assert [e["s"] for e in got] == ["done", "tent", "tent"]


def test_target_change_number_and_note_are_split():
    p = FT.parse_target("Enable 26.3 FTs on NA1 EXCEPT C6, C8, C9 CHG0000007")
    assert (p["r"], p["t"], p["c"], p["n"]) == ("26.3", "NA1", "CHG0000007", "EXCEPT C6, C8, C9")
    p = FT.parse_target("Enable 26.4 FTs on UK2 - LO27 CHG0000008")
    assert (p["t"], p["c"]) == ("UK2 - LO27", "CHG0000008")
    p = FT.parse_target("27.1 FT Enablement on EU2, EU3")
    assert (p["r"], p["t"], p["c"]) == ("27.1", "EU2, EU3", "")


def test_the_day_is_the_israel_day_of_the_event():
    assert FT.ft_events([ev("Enable 26.4 FTs on CA1 CHG0000009", day="2026-11-09")])[0]["d"] == "2026-11-09"


def test_clusters_and_regions_of_a_target():
    assert FT.clusters_of("UK2 (UKSov) (LO26)") == ["UK2", "LO26"] and FT.regions_of(["UK2", "LO26"]) == ["UK", "Beta"]
    assert FT.clusters_of("NA3 (VA26)") == ["NA3"]                                            # an alias is not a cluster
    assert FT.regions_of(FT.clusters_of("B2, B32")) == ["Beta"] and FT.regions_of(FT.clusters_of("M35")) == ["Beta"]
    assert FT.regions_of(FT.clusters_of("C28, C33")) == ["C clusters"]                         # the title does not name the region
    assert FT.regions_of(FT.clusters_of("NA1 (C6, C8, C9)")) == ["NA"]                         # C-numbered clusters named under a region belong to it
    e = FT.ft_events([ev("(TENT) Enable 26.4 FTs on EU2, EU3 CHG0000010")])[0]
    assert e["k"] == ["EU2", "EU3"] and e["g"] == ["EU"]


def test_inline_puts_the_payload_in_the_page_and_a_failure_is_not_an_error(tmp_path):
    page = "x /*__FT_EVENTS__*/null y"
    out = FT.inline_into(page, payload={"asOf": "2026-11-05T12:00+02:00", "events": [{"d": "2026-11-10", "t": "ZA1</script>"}]})
    assert "/*__FT_EVENTS__*/" not in out and "<\\/script>" in out
    assert FT.inline_into("no placeholder", payload=None) == "no placeholder"
    class Boom:
        def get(self, *a, **k):
            raise OSError("down")
    cache = tmp_path / "c.json"
    env = {"FT_CALENDAR_SUBCALENDAR_ID": "x", "JIRA_BASE_URL": "https://example.invalid", "JIRA_EMAIL": "a", "JIRA_API_TOKEN": "b"}
    assert FT.load_payload(env, str(cache), session=Boom()) is None                          # nothing read, no copy
    cache.write_text('{"asOf": "t", "events": []}')
    assert FT.load_payload(env, str(cache), session=Boom()) == {"asOf": "t", "events": []}   # the last good copy
    assert FT.load_payload({}, None) is None                                                  # not configured


def test_the_sandbox_banner_goes_in_before_the_report_code_and_the_calendar():
    """The Sandbox step counts the page's own title and header; the usage report's page strings contain the same markup, so the banner must be added first (a Sandbox build broke on this once)."""
    src = (Path(__file__).resolve().parent.parent / "program_dashboard" / "build_dashboard.py").read_text(encoding="utf-8")
    body = src[src.index('fragment = fragment.replace("/*__DATA__*/null", payload)'):]
    assert body.index("sandbox_fragment(fragment") < body.index("usage_bundle.inline_into") < body.index("ft_calendar.inline_into")
