#!/usr/bin/env python3
"""The Release Calendar section of the dashboard (FTC): the calendar of feature-toggle enablement events read from the R&D Release Management calendar at build time.

The events are fictitious here (make_synthetic.ft_sample): clusters, change numbers and releases are made up. Asserted:
  * the section, its Section Strip entry and the Month / List views are there, the strip entry jumps to the section; the page keeps working with no console error and no sideways scroll at 1400 and 390 px;
  * the List shows exactly the events the filters let through, and each filter is checked against an independent recount from the events (release, status, region, cluster, find by cluster, region and CHG
    number, filters together); no filter selected means all events;
  * a chip in the Month view names the event, a busy day says "+N more", a day or event click fills the details with the clusters, the region, the change number and the full title;
  * the Upcoming / All switch of the List; the legend and the sub line say the events are part of the page (Refresh does not update them);
  * a build without calendar data says so instead of drawing an empty calendar.

    python3 ft_calendar_check.py [--live] [--only NAME]
"""
from __future__ import annotations

import datetime as dt
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "program_dashboard"))
import kit                                                                          # noqa: E402
import make_synthetic as MS                                                         # noqa: E402
from kit import ctx, T                                                              # noqa: E402

SUITE = kit.Suite("Delivery Pulse Release Calendar")


def load(vp=(1400, 900), payload=...):
    import ft_calendar as FT
    ch = ctx.chrome
    data = MS.make(MS.il_today())
    data["build"] = {"sha": "abc1234", "dirty": False, "at": "2026-01-01T00:00+02:00"}
    page = MS.render_page(data)
    sample = MS.ft_sample(data)
    if payload is not ...:                                                           # another payload (or None: no calendar in this build)
        page = page.replace(FT.json.dumps(sample, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"), FT.json.dumps(payload, separators=(",", ":")))
    url = ctx.write(kit.wrap(page), "ft")
    ch.cmd("Emulation.setTimezoneOverride", timezoneId="Asia/Jerusalem")
    ch.viewport(*vp, mobile=vp[0] < 500)
    ch.goto(url)
    assert kit.wait_ready(ch), "the page did not draw: " + str(ch.console_errors()[:2])
    time.sleep(0.4)
    return ch, sample["events"]


def rows(ch):
    """What the List shows: (day, release, target, change) per row."""
    return ch.js("[...document.querySelectorAll('#ft-view .ftli')].map(b => [b.closest('.ftlist') && (() => { let p = b.previousElementSibling; while (p && !p.classList.contains('ftlg')) p = p.previousElementSibling; return p ? p.firstElementChild.textContent : ''; })(), b.querySelector('.ftrel').textContent, b.querySelector('.fttgt').textContent, b.querySelector('.ftchg').textContent])") or []


def click(ch, sel):
    ch.js(f"document.querySelector({sel!r}).click()")


def to_list(ch, all_=True):
    click(ch, "#ft-vl")
    click(ch, "#ft-ta" if all_ else "#ft-tu")


def reset(ch):
    ch.js("""(() => { let b; while ((b = document.querySelector('#ftc .chip.on[data-rel], #ftc .chip.on[data-st], #ftc .chip.on[data-rg]'))) b.click();      // a click redraws the chips, so take the first one each time
      const c = document.getElementById('ft-cl'); c.value = ''; c.dispatchEvent(new Event('change')); const q = document.getElementById('ft-q'); q.value = ''; q.dispatchEvent(new Event('input')); })()""")


def pick(ch, cluster):
    ch.js(f"(() => {{ const c = document.getElementById('ft-cl'); c.value = {cluster!r}; c.dispatchEvent(new Event('change')); }})()")


def setq(ch, text):
    ch.js(f"(() => {{ const q = document.getElementById('ft-q'); q.value = {text!r}; q.dispatchEvent(new Event('input')); }})()")


def expect(events, rel=(), st=(), rg=(), cl="", q=""):
    out = []
    for e in events:
        if rel and e["r"] not in rel or st and e["s"] not in st or rg and not set(e["g"]) & set(rg) or cl and cl not in e["k"]:
            continue
        if q and q.lower() not in " ".join([e["raw"], e["c"], e["t"], e["n"], e["r"], " ".join(e["k"]), " ".join(e["g"])]).lower():
            continue
        out.append(e)
    return sorted(out, key=lambda e: e["d"])


def same(ch, t, events, label, **kw):
    got = sorted((r[3], r[1], r[2]) for r in rows(ch))
    want = sorted((e["c"], e["r"], e["t"]) for e in expect(events, **kw))
    t.check(got == want, f"{label}: the list shows {got}, expected {want}")


@SUITE.test("ft_section_strip_entry_views_and_no_errors")
def _(t: T):
    ch, ev = load()
    t.check(ch.js("!!document.getElementById('ft-sec') && document.getElementById('h-ftenable').textContent") == "Release Calendar", "no Release Calendar section")
    t.check(ch.js("[...document.querySelectorAll('#seclist a')].map(a => a.textContent).includes('Release Calendar')") is True, "no Section Strip entry")
    click(ch, '#seclist a[data-jump="h-ftenable"]')
    ch.wait_for("(() => { const r = document.getElementById('h-ftenable').getBoundingClientRect(); return r.top < innerHeight * 0.6 && r.top > -5; })()", 6)
    t.check(ch.js("document.getElementById('h-ftenable').getBoundingClientRect().top < innerHeight * 0.6"), "the strip entry did not scroll to the section")
    t.check(ch.js("document.querySelectorAll('#ft-view .ftcal .ftday').length >= 28") is True, "the Month view has no calendar grid")
    t.check("Refresh does not update them" in (ch.js("document.getElementById('ft-sub').textContent") or ""), "the sub line does not say Refresh leaves the events alone")
    t.check(ch.js("document.querySelectorAll('#ft-legend .ftbadge').length") == 4, "the legend does not name the four statuses")
    # light by default: one toolbar row, the filters folded away, nothing in the detail box until a day is picked
    shown = lambda i: ch.js(f"getComputedStyle(document.getElementById('{i}')).display !== 'none' && document.getElementById('{i}').getBoundingClientRect().height > 0")      # what is on screen, not the attribute
    t.check(not shown("ft-fp") and not shown("ft-detail") and not shown("ft-gt") and not shown("ft-fc") and not shown("ft-clr"), "the filters, the details, the Upcoming/All switch, the count or Clear are on screen before anyone asked")
    t.check(ch.js("document.getElementById('ft-fb').getAttribute('aria-expanded')") == "false", "the Filters button starts expanded")
    t.check(ch.js("(() => { const b = document.querySelector('#ftc .ftbar').getBoundingClientRect(); return b.height < 60; })()") is True, "the toolbar is more than one row at 1400 px")
    click(ch, "#ft-fb")
    t.check(shown("ft-fp") and ch.js("document.getElementById('ft-fb').getAttribute('aria-expanded')") == "true", "the Filters button does not open the filters")
    click(ch, '#ftc [data-rel="26.4"]'); click(ch, '#ftc [data-rg="EU"]'); pick(ch, "EU2")
    t.check(ch.js("document.getElementById('ft-fc').textContent") == "3" and shown("ft-fc") and shown("ft-clr"), "the Filters button does not count the active filters")
    t.check("events match" in (ch.js("document.getElementById('ft-next').innerText") or ""), "no 'N of M events match' note while filtered")
    click(ch, "#ft-clr")
    t.check(not shown("ft-fc") and not shown("ft-clr") and ch.js("document.getElementById('ft-cl').value") == "" and ch.js("document.querySelectorAll('#ftc .chip.on[data-rel], #ftc .chip.on[data-rg], #ftc .chip.on[data-st]').length") == 0, "Clear does not reset the filters")
    for vp in ((1400, 900), (390, 844)):
        ch, ev = load(vp)
        click(ch, "#ft-vl"); click(ch, "#ft-ta")
        t.check(ch.js("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1") is True, f"sideways scroll at {vp[0]} px")
        t.check(ch.js("document.getElementById('ft-sec').scrollWidth <= document.getElementById('ft-sec').clientWidth + 1") is True, f"the section is wider than its box at {vp[0]} px")
        t.check(not ch.console_errors(), f"console error at {vp[0]}: {ch.console_errors()[:2]}")


@SUITE.test("ft_switching_view_does_not_move_the_page")
def _(t: T):
    ch, ev = load()
    ch.js("window.scrollTo(0, document.documentElement.scrollHeight)"); time.sleep(0.3)
    for sel, name in (("#ft-vl", "List"), ("#ft-vm", "Month"), ("#ft-vl", "List"), ("#ft-tu", "Upcoming"), ("#ft-ta", "All"), ("#ft-vm", "Month")):
        before = ch.js("[scrollY, document.getElementById('ft-vm').getBoundingClientRect().top]")
        click(ch, sel); time.sleep(0.2)
        after = ch.js("[scrollY, document.getElementById('ft-vm').getBoundingClientRect().top]")
        t.check(abs(after[0] - before[0]) < 2 and abs(after[1] - before[1]) < 2, f"{name}: the page moved, scroll {before[0]} -> {after[0]}, toolbar {before[1]} -> {after[1]}")


@SUITE.test("ft_list_columns_line_up_whether_or_not_a_change_number_exists")
def _(t: T):
    ch, ev = load()
    to_list(ch)
    cols = ch.js("""(() => { const r = [...document.querySelectorAll('#ft-view .ftli')]; const left = s => [...new Set(r.map(b => Math.round(b.querySelector(s).getBoundingClientRect().left)))];
      return {n: r.length, rel: left('.ftrel'), tgt: left('.fttgt'), badge: left('.ftbadge'), chg: left('.ftchg')}; })()""")
    t.check(cols["n"] > 5, "the list has no rows")
    t.check(all(len(cols[k]) == 1 for k in ("rel", "tgt", "badge", "chg")), f"a list column starts at different places from row to row: {cols}")
    t.check(any(e["c"] == "" for e in ev), "the sample has no event without a change number, so the check proves little")


@SUITE.test("ft_filters_release_status_region_cluster_and_find_equal_a_recount")
def _(t: T):
    ch, ev = load()
    to_list(ch)
    same(ch, t, ev, "no filter")
    t.check(len(rows(ch)) == len(ev), "no filter does not show every event")
    for r in ("26.3", "27.1"):
        click(ch, f'#ftc [data-rel="{r}"]'); same(ch, t, ev, f"release {r}", rel=(r,)); reset(ch)
    click(ch, '#ftc [data-st="appr"]'); same(ch, t, ev, "status approved", st=("appr",))
    click(ch, '#ftc [data-st="tent"]'); same(ch, t, ev, "approved or tentative", st=("appr", "tent")); reset(ch)
    click(ch, '#ftc [data-rg="EU"]'); same(ch, t, ev, "region EU", rg=("EU",))
    click(ch, '#ftc [data-rg="Beta"]'); same(ch, t, ev, "regions EU and Beta", rg=("EU", "Beta")); reset(ch)
    pick(ch, "EU2"); same(ch, t, ev, "cluster EU2", cl="EU2")
    pick(ch, "C28"); same(ch, t, ev, "cluster C28 named in a list", cl="C28"); reset(ch)
    setq(ch, "CHG9000006"); same(ch, t, ev, "find a change number", q="CHG9000006")
    setq(ch, "eu"); same(ch, t, ev, "find the region letters", q="eu")
    setq(ch, "lo27"); same(ch, t, ev, "find a beta cluster", q="lo27")
    setq(ch, "nothing-like-this"); t.check(not rows(ch), "find with no match still lists events")
    t.check("No upcoming events" in (ch.js("document.getElementById('ft-view').textContent") or "") or "No events" in (ch.js("document.getElementById('ft-view').textContent") or ""), "no message for an empty result"); reset(ch)
    click(ch, '#ftc [data-rel="26.4"]'); click(ch, '#ftc [data-st="tent"]'); click(ch, '#ftc [data-rg="EU"]'); same(ch, t, ev, "release, status and region together", rel=("26.4",), st=("tent",), rg=("EU",))
    t.check(not ch.console_errors(), f"console error: {ch.console_errors()[:2]}")
    regions = ch.js("[...document.querySelectorAll('#ft-rg .chip')].map(b => b.firstChild.textContent)")
    want = sorted({g for e in ev for g in e["g"]}, key=lambda g: ["NA", "EU", "UK", "AU", "JP", "JO", "KR", "CA", "ZA", "AE", "Beta", "C clusters"].index(g) if g in ["NA", "EU", "UK", "AU", "JP", "JO", "KR", "CA", "ZA", "AE", "Beta", "C clusters"] else 99)
    t.check(regions == want, f"region chips {regions}, expected {want}")


@SUITE.test("ft_upcoming_all_month_chips_details_and_empty_build")
def _(t: T):
    ch, ev = load()
    today = MS.il_today().isoformat()
    to_list(ch, all_=False)
    got = [r[3] for r in rows(ch)]
    want = [e["c"] for e in sorted(ev, key=lambda e: e["d"]) if e["d"] >= today]
    t.check(sorted(got) == sorted(want), f"Upcoming shows {len(got)} rows, expected {len(want)}")
    click(ch, "#ft-ta"); t.check(len(rows(ch)) == len(ev), "All does not show every event")
    # the Month view: go to the month of the busy day (today + 3), find its chips and the +N more note
    busy = (MS.il_today() + dt.timedelta(days=3)).isoformat()
    click(ch, "#ft-vm")
    for _ in range(3):
        if not ch.js(f"!!document.querySelector('[data-cell=\"{busy}\"]') && !document.querySelector('[data-cell=\"{busy}\"]').classList.contains('out')"):
            click(ch, "#ft-nx")
    cell = f"[data-cell=\"{busy}\"]"
    chips = ch.js(f"[...document.querySelectorAll('{cell} .ftev')].map(b => b.dataset.tip)")
    t.check(len(chips) == 3 and all("Enable 26.4" in c for c in chips), f"the busy day shows {chips}")
    t.check(ch.js(f"[...document.querySelectorAll('{cell} .ftev')].every(b => !b.hasAttribute('title') && /, (Approved|Tentative|Ready for CAB|Done)/.test(b.getAttribute('aria-label')))") is True, "a chip has a native title, or no accessible status")
    # the tooltip: the dashboard's own, readable, with the full title, the change number and the status
    ch.js(f"document.querySelector('{cell} .ftev').dispatchEvent(new MouseEvent('mouseover', {{bubbles: true, clientX: 300, clientY: 300}}))")
    tipt = ch.js("(() => { const g = document.getElementById('gtip'); return g.style.display === 'block' ? g.innerText : null; })()") or ""
    t.check("Enable 26.4 FTs on CA1 CHG9000004" in tipt and "Change CHG9000004" in tipt and "Approved" in tipt and "Region CA" in tipt, f"the tooltip does not show the full title, status, change and region: {tipt!r}")
    t.check(ch.js("(() => { const g = document.getElementById('gtip'), r = g.getBoundingClientRect(); return r.width > 150 && r.right <= innerWidth && r.bottom <= innerHeight && getComputedStyle(g).color !== getComputedStyle(g).backgroundColor; })()") is True, "the tooltip is too small, outside the window, or has no contrast")
    ch.js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))")
    t.check(ch.js("document.getElementById('gtip').style.display") == "none", "Esc does not close the tooltip")
    t.check("+1 more" in (ch.js(f"document.querySelector('{cell} .ftmore') && document.querySelector('{cell} .ftmore').textContent") or ""), "the busy day does not say '+1 more'")
    click(ch, f"{cell} .ftev")
    d = ch.js("document.getElementById('ft-detail').innerText") or ""
    t.check("CHG9000004" in d and "NA" not in d.split("Region")[0] and "Enable 26.4 FTs on CA1" in d and "CA" in d, f"details of a clicked event: {d[:200]!r}")
    click(ch, f"{cell} [data-day]")
    d2 = ch.js("document.getElementById('ft-detail').innerText") or ""
    t.check(all(c in d2 for c in ("CHG9000004", "CHG9000005", "CHG9000006", "CHG9000007")), "a day click does not list every event of the day")
    t.check("26.3" not in (ch.js("document.getElementById('ft-next').innerText") or "") and "26.4" in (ch.js("document.getElementById('ft-next').innerText") or ""), "the Next up line is not the first upcoming event")
    # no calendar in this build
    ch2, _ = load(payload=None)
    t.check("not part of this build" in (ch2.js("document.getElementById('ftc').textContent") or ""), "a build without events draws no explanation")
    t.check(not ch2.console_errors(), f"console error without events: {ch2.console_errors()[:2]}")


if __name__ == "__main__":
    sys.exit(kit.cli(SUITE, __doc__))
