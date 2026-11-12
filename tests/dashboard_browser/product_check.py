#!/usr/bin/env python3
"""The Product switch of the dashboard: a non-CXone product (WFM, EEM, ESP in the real page) is a payload of its own, run by the same page code on its own data.

The products are fictitious here (make_synthetic.product_sample): PRD1 has dated releases (7.4 Major, 7.4.1 Minor, 7.5 Future), PRD2 has none. Asserted:
  * with products in the payload the CXone view is unchanged (11 sections, its project chips, its release select) and shows a Product switch; with no usable product there is no switch at all;
  * a product view runs on the product's own data (the epics in view equal an independent recount from the payload), has six sections, hides the CXone-only controls and sections, and says in a notice
    which product and release it is, how the release was chosen and where the dates come from;
  * the release of a product is chosen for the reader: plain text, no Major, Minor or Future control, and a link to another release opens the Major;
  * the filter bar stays ONE row: adding the Product control adds no row to the CXone view, and a product view has one row;
  * a product with no dates says so and draws no burn-up; Refresh is unavailable in a product view and says why;
  * switching product reloads on the other dataset and back; the Teams menu lists only the teams of the product's epics.

    python3 product_check.py [--live] [--only NAME]
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kit                                                                          # noqa: E402
import make_synthetic as MS                                                         # noqa: E402
from kit import ctx, T                                                              # noqa: E402

SUITE = kit.Suite("Delivery Pulse products")
CX_STRIP = 11
PRODUCT_STRIP = ["Needs Attention", "Delivery", "Efficiency", "AI Adoption", "Quality", "Dependencies"]
# once the strip branch is merged the strip has no AI Adoption entry (Efficiency stands for it)
PRODUCT_STRIPS = [PRODUCT_STRIP, [x for x in PRODUCT_STRIP if x != "AI Adoption"]]
HIDDEN_HEADINGS = ["h-nfr", "h-cx", "h-capview", "h-cycles", "h-analysis"]


def load(prod="cxone", vp=(1400, 900), products="ok"):
    ch = ctx.chrome
    data = MS.make(MS.il_today())
    data["build"] = {"sha": "abc1234", "dirty": False, "at": "2026-01-01T00:00+02:00"}
    if products == "ok":
        data["productList"], data["products"] = ["PRD1", "PRD2"], MS.product_sample(data)
    elif products == "unavailable":
        data["productList"], data["products"] = ["PRD1"], {"PRD1": {"project": "PRD1", "unavailable": "no running Major"}}
    page = MS.render_page(data)
    url = ctx.write(kit.wrap(page), "prod")
    ch.cmd("Emulation.setTimezoneOverride", timezoneId="Asia/Jerusalem")
    ch.viewport(*vp, mobile=vp[0] < 500)
    ch.goto(url + "#prod=" + prod)
    assert kit.wait_ready(ch), "the page did not draw: " + str(ch.console_errors()[:2])
    time.sleep(0.4)
    return ch, data


def js(ch, code):
    return ch.js(f"(() => {{ {code} }})()")


def shown(ch, sel):
    return js(ch, f"const e = document.querySelector({sel!r}); return !!e && getComputedStyle(e).display !== 'none' && e.getBoundingClientRect().height > 0")


def bar_rows(ch):
    """How many rows the visible controls of the filter bar make (the distinct tops of its control groups; Reset Filters sits on the control line, lower than the labels, on purpose)."""
    return js(ch, "return new Set([...document.querySelectorAll('#filterbar > .fg:not([hidden])')].filter(e => e.getBoundingClientRect().height > 0).map(e => Math.round(e.getBoundingClientRect().top))).size")


def strip(ch):
    return js(ch, "return [...document.querySelectorAll('#seclist a')].map(a => a.textContent.replace(/ \\(\\d+\\)$/, ''))")      # the count on a label ("Needs Attention (1)") is not part of its name


def click(ch, sel):
    ch.js(f"document.querySelector({sel!r}).click()")
    time.sleep(0.35)


@SUITE.test("cxone_view_is_unchanged_and_shows_the_product_switch")
def _(t: T):
    ch, data = load("cxone")
    t.check(js(ch, "return [...document.querySelectorAll('#f-product option')].map(o => o.textContent.trim())") == ["CXone", "PRD1", "PRD2"], "the Product control does not list CXone and the two products")
    t.check(js(ch, "return document.getElementById('f-product').value") == "cxone", "CXone is not the selected product")
    t.check(len(strip(ch)) == CX_STRIP, f"the CXone strip has {len(strip(ch))} sections, expected {CX_STRIP}")
    t.check(shown(ch, "#g-projects") and shown(ch, "#g-release") and shown(ch, "#g-dc") and not shown(ch, "#prod-note") and not shown(ch, "#g-scope"), "the CXone filter bar changed")
    t.check(all(not js(ch, f"return document.getElementById({h!r}).closest('section').hidden") for h in HIDDEN_HEADINGS), "a CXone section is hidden")
    t.check(js(ch, "return PRODUCT") == "cxone" and js(ch, "return DATA.projects.join(',')") == ",".join(data["projects"]), "the CXone view does not run on the CXone data")
    ch1, _ = load("cxone", (1400, 900), products="none")
    t.check(bar_rows(ch) <= bar_rows(ch1), f"the Product control added a row to the filter bar: {bar_rows(ch)} rows against {bar_rows(ch1)} without it")
    for vp in ((1400, 900), (390, 844)):
        ch, _ = load("cxone", vp)
        t.check(js(ch, "return document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1") is True, f"sideways scroll at {vp[0]} px")
        t.check(not ch.console_errors(), f"console error at {vp[0]}: {ch.console_errors()[:2]}")


@SUITE.test("product_view_runs_on_its_own_data_with_six_sections_and_its_own_controls")
def _(t: T):
    ch, data = load("PRD1")
    pay = data["products"]["PRD1"]
    t.check(js(ch, "return PRODUCT") == "PRD1" and js(ch, "return state.release") == "7.4", "the product view did not open on the product's Major")
    want = sum(1 for e in pay["epics"] if "7.4" in e["fv"] and e["s"] != "Removed")
    t.check(js(ch, "return scopeOf(state.release).length") == want, f"the epics in view differ from the payload's {want}")
    t.check(strip(ch) in PRODUCT_STRIPS, f"the product strip is {strip(ch)}")
    t.check(all(js(ch, f"return document.getElementById({h!r}).closest('section').hidden") for h in HIDDEN_HEADINGS), "a CXone-only section is not hidden")
    t.check(not shown(ch, "#g-projects") and not shown(ch, "#g-dc") and shown(ch, "#g-release") and shown(ch, "#g-scope"), "the product filter bar shows the wrong controls")
    t.check(bar_rows(ch) == 1, f"the product filter bar has {bar_rows(ch)} rows, expected one")
    t.check(js(ch, "return document.getElementById('prod-scope').textContent") == "PRD1", "the project is not named")
    bar = js(ch, "return document.getElementById('filterbar').innerText") or ""
    t.check(not any(w in bar for w in ("Major", "Minor", "Future")), f"the product bar still has a release choice: {bar!r}")
    t.check(js(ch, "return [...document.querySelectorAll('#f-release option')].map(o => o.textContent.trim()).join('|')") == "7.4" and js(ch, "return document.getElementById('f-release').value") == "7.4", "the Release box does not hold the product's release alone")
    rtip = js(ch, "return document.getElementById('f-release').dataset.tip") or ""
    t.check("chosen automatically" in rtip and "running Major of PRD1" in rtip, f"the Release box does not say it is chosen for you: {rtip!r}")
    note = js(ch, "return document.getElementById('prod-note').textContent") or ""
    t.check("PRD1 7.4 is a product view" in note and "not comparable with the CXone views" in note and "Jira version dates" in note and "\n" not in note.strip(), f"the notice reads {note!r}")
    t.check(js(ch, "return document.getElementById('prod-note').getBoundingClientRect().height") < 40, "the notice is more than one line at 1400 px")
    tip = js(ch, "return document.querySelector('#prod-note [data-tip]').dataset.tip") or ""
    t.check("rule v1" in tip and "not shown: Minor 7.4.1, Future 7.5" in tip and "verified only for CXone" in tip and "1" in tip, f"the details on hover are incomplete: {tip!r}")
    t.check(js(ch, "return document.getElementById('refresh').classList.contains('unavail')") is True and "CXone projects" in (js(ch, "return document.getElementById('refresh-why').textContent") or ""), "Refresh is not unavailable with a reason")
    body = js(ch, "return document.body.innerText") or ""
    t.check("Delivery Cycle 1 (ends" not in body, "the burn-up draws the CXone Delivery Cycle 1 marker in a product view")
    t.check(not ch.console_errors(), f"console error: {ch.console_errors()[:2]}")
    ch0, _ = load("cxone")
    t.check("Delivery Cycle 1" in (js(ch0, "return document.body.innerText") or ""), "the CXone view lost its Delivery Cycle 1 text")


@SUITE.test("a_link_to_another_release_of_the_product_opens_the_major")
def _(t: T):
    ch, data = load("PRD1")
    pay = data["products"]["PRD1"]
    t.check(js(ch, "return DATA.releases.join(',')") == "7.4" and js(ch, "return state.release") == "7.4", "the product payload holds more than its running Major")
    want = sum(1 for e in pay["epics"] if e["s"] != "Removed")
    t.check(js(ch, "return scopeOf(state.release).length") == want, "the epics in view differ from the payload")
    ch.goto(ctx.write(kit.wrap(MS.render_page({**data, "productList": ["PRD1", "PRD2"]})), "prod") + "#prod=PRD1&r=7.5")
    assert kit.wait_ready(ch)
    t.check(js(ch, "return state.release") == "7.4", "a link to a release the product view does not hold did not open the Major")
    js(ch, "document.getElementById('f-reset').click()")
    t.check(js(ch, "return state.release") == "7.4" and not ch.console_errors(), f"Reset Filters changed the release or an error appeared: {ch.console_errors()[:2]}")


@SUITE.test("a_product_with_no_dates_says_so_and_draws_no_burnup")
def _(t: T):
    ch, _ = load("PRD2")
    note = js(ch, "return document.getElementById('prod-note').textContent") or ""
    tip = js(ch, "return document.querySelector('#prod-note [data-tip]').dataset.tip") or ""
    t.check("no dates in Jira" in note and "burn-up is not drawn" in note and "has no start and release date in Jira" in tip and "medium confidence" in tip, f"the notice reads {note!r}, the details {tip[:200]!r}")
    rel = js(ch, "return document.getElementById('f-release').value")
    t.check(rel == "Z31.1" and "Release date none" in tip, f"the Release box reads {rel!r}; the details {tip[:160]!r}")
    t.check("no timeline to draw" in (js(ch, "return document.body.innerText") or ""), "the Delivery section does not say it draws no timeline")
    t.check(strip(ch) in PRODUCT_STRIPS and not ch.console_errors(), f"strip {strip(ch)}, errors {ch.console_errors()[:2]}")


@SUITE.test("teams_menu_of_a_product_lists_only_its_teams")
def _(t: T):
    ch, data = load("PRD1")
    want = set()
    for e in data["products"]["PRD1"]["epics"]:
        if "7.4" in e["fv"] and e["s"] != "Removed":
            want.update(e.get("tm") or ["(No Team)"])
    click(ch, "#f-teams-btn")
    got = set(js(ch, "return [...document.querySelectorAll('#f-teams-list input[data-t]')].map(i => i.dataset.t)") or [])
    others = {x for e in data["epics"] if e["p"] != "CXCO" for x in (e.get("tm") or [])} - want
    t.check(got == want and not (got & others), f"the product's Teams menu lists {sorted(got ^ want)} too many or too few")


@SUITE.test("switching_product_reloads_on_the_other_data_and_back")
def _(t: T):
    ch, _ = load("cxone")
    ch.js("const s = document.getElementById('f-product'); s.value = 'PRD1'; s.dispatchEvent(new Event('change'))")
    ch.wait_for("typeof PRODUCT !== 'undefined' && PRODUCT === 'PRD1' && document.readyState === 'complete'", 8)
    time.sleep(0.5)
    t.check(js(ch, "return PRODUCT") == "PRD1" and strip(ch) in PRODUCT_STRIPS, f"after the switch the page is {js(ch, 'return PRODUCT')} with {strip(ch)}")
    ch.js("const s = document.getElementById('f-product'); s.value = 'cxone'; s.dispatchEvent(new Event('change'))")
    ch.wait_for("typeof PRODUCT !== 'undefined' && PRODUCT === 'cxone' && document.readyState === 'complete'", 8)
    time.sleep(0.5)
    t.check(js(ch, "return PRODUCT") == "cxone" and len(strip(ch)) == CX_STRIP and shown(ch, "#g-projects"), "switching back did not restore the CXone view")
    t.check(not ch.console_errors(), f"console error: {ch.console_errors()[:2]}")


def switch_to(ch, v):
    ch.js(f"const s = document.getElementById('f-product'); s.value = '{v}'; s.dispatchEvent(new Event('change'))")
    ch.wait_for(f"typeof PRODUCT !== 'undefined' && PRODUCT === '{v}' && document.readyState === 'complete'", 8)
    time.sleep(1.2)                                                                  # the page lands on the section while it settles


@SUITE.test("switching_between_products_keeps_the_section_to_or_from_cxone_opens_at_the_top")
def _(t: T):
    def at(ch):
        return js(ch, "return {cur: SEC.current(), top: SEC.top(), y: window.scrollY, want: landingY('h-bugs')}")
    # CXone -> product: the page opens at the top, whatever section was being read
    ch, _ = load("cxone")
    ch.js("SEC.go('h-bugs', false, true)"); time.sleep(0.8)
    t.check(js(ch, "return SEC.current()") == "h-bugs", f"setup: reading {js(ch, 'return SEC.current()')}, expected Quality")
    switch_to(ch, "PRD1")
    r = at(ch)
    t.check(r["y"] <= 4 and r["top"] is True, f"CXone Quality -> product: the page is at {r['y']}px, expected the top")
    # product -> product: the section being read stays
    ch.js("SEC.go('h-bugs', false, true)"); time.sleep(0.8)
    switch_to(ch, "PRD2")
    r = at(ch)
    t.check(r["cur"] == "h-bugs" and abs(r["y"] - r["want"]) <= 4, f"product Quality -> product: the page reads {r['cur']} at {r['y']}px, the section starts at {r['want']}px")
    # product -> CXone: the page opens at the top
    ch.js("SEC.go('h-bugs', false, true)"); time.sleep(0.8)
    switch_to(ch, "cxone")
    r = at(ch)
    t.check(r["y"] <= 4 and r["top"] is True, f"product Quality -> CXone: the page is at {r['y']}px, expected the top")
    # a section the other product does not exist in: between products every product has the same sections, so also the top of the page stays the top
    ch, _ = load("PRD1")
    switch_to(ch, "PRD2")
    t.check(js(ch, "return window.scrollY") <= 4, "from the top of the page the other product view opens at the top")
    t.check(not ch.console_errors(), f"console error: {ch.console_errors()[:2]}")


@SUITE.test("no_usable_product_means_no_switch_and_an_unknown_product_in_the_link_opens_cxone")
def _(t: T):
    for products in ("none", "unavailable"):
        ch, _ = load("PRD1", products=products)
        t.check(js(ch, "return PRODUCT") == "cxone" and not shown(ch, "#g-product") and len(strip(ch)) == CX_STRIP, f"products={products}: the page is not the plain CXone page")
    ch, _ = load("NOPE")
    t.check(js(ch, "return PRODUCT") == "cxone", "an unknown product in the link did not fall back to CXone")


def wfm_page(template=None):
    """The product list of the real page, with the first fictitious product named WFM: the one product whose reader-facing name differs from its key."""
    data = MS.make(MS.il_today())
    data["build"] = {"sha": "abc1234", "dirty": False, "at": "2026-01-01T00:00+02:00"}
    prods = MS.product_sample(data)
    prods["WFM"] = prods.pop("PRD1")
    data["productList"], data["products"] = ["WFM", "PRD2"], prods
    return ctx.write(kit.wrap(MS.render_page(data, template) if template else MS.render_page(data, ctx.template)), "prodwfm")


def wfm_read(url):
    ch = ctx.chrome
    ch.cmd("Emulation.setTimezoneOverride", timezoneId="Asia/Jerusalem")
    ch.viewport(1400, 900, mobile=False)
    ch.goto(url + "#prod=WFM")
    assert kit.wait_ready(ch), "the page did not draw: " + str(ch.console_errors()[:2])
    time.sleep(0.4)
    return {"opts": js(ch, "return [...document.querySelectorAll('#f-product option')].map(o => [o.value, o.textContent.trim()])"),
            "scope": js(ch, "return document.getElementById('prod-scope').textContent"), "prod": js(ch, "return PRODUCT"),
            "label": js(ch, "return document.getElementById('f-product').selectedOptions[0].textContent.trim()")}


@SUITE.test("the_WFM_product_is_named_IEX_WFM_for_the_reader_and_stays_WFM_in_the_link")
def _(t: T):
    r = wfm_read(wfm_page())
    t.check(r["opts"] == [["cxone", "CXone"], ["PRD2", "PRD2"], ["WFM", "IEX WFM"]], f"the Product list is {r['opts']}")
    t.check(r["prod"] == "WFM" and r["label"] == "IEX WFM" and r["scope"] == "IEX WFM", f"product {r['prod']!r}, selected {r['label']!r}, project text {r['scope']!r}")


@SUITE.test("selftest_the_IEX_WFM_check_fails_when_the_display_name_is_taken_out")
def _(t: T):
    src = ctx.template.read_text(encoding="utf-8")
    marker = 'PRODUCT_LABEL = {WFM: "IEX WFM"}'
    if marker not in src:
        raise kit.Skip("this template has no display name for WFM to take out")
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(src.replace(marker, "PRODUCT_LABEL = {}"))
    url = wfm_page(Path(f.name))
    Path(f.name).unlink()
    r = wfm_read(url)
    t.check(r["label"] != "IEX WFM", "the check passed without the display name: it is blind")


CLAUSE = '(issueLinkType is EMPTY OR issueLinkType != "clones")'


def bug_link_jql(prod, clause, template=None):
    """The JQL behind the open-bugs link of a fictitious product payload that carries (or not) a bug clause."""
    data = MS.make(MS.il_today())
    data["build"] = {"sha": "abc1234", "dirty": False, "at": "2026-01-01T00:00+02:00"}
    prods = MS.product_sample(data)
    if clause:
        prods[prod]["bugClause"] = clause
    data["productList"], data["products"] = list(prods), prods
    url = ctx.write(kit.wrap(MS.render_page(data, template) if template else MS.render_page(data, ctx.template)), "prodbug")
    ch = ctx.chrome
    ch.viewport(1400, 900, mobile=False)
    ch.goto(url + "#prod=" + prod)
    assert kit.wait_ready(ch), "the page did not draw: " + str(ch.console_errors()[:2])
    time.sleep(0.4)
    return js(ch, "return decodeURIComponent((jiraBugs({extra: OPEN_BUG_JQL}) || '').split('jql=')[1] || '')")


@SUITE.test("a_product_with_a_bug_clause_adds_it_to_every_bug_link_and_one_without_does_not")
def _(t: T):
    with_c, without = bug_link_jql("PRD1", CLAUSE), bug_link_jql("PRD2", None)
    t.check(with_c.endswith("AND " + CLAUSE) and with_c.count(CLAUSE) == 1, f"the link of the product with a clause is {with_c!r}")
    t.check("issueLinkType" not in without and "issuetype = Bug" in without, f"the link of the product without one is {without!r}")


@SUITE.test("selftest_the_bug_clause_check_fails_when_the_clause_is_not_added_to_links")
def _(t: T):
    src = ctx.template.read_text(encoding="utf-8")
    marker = "if (DATA.bugClause &&"
    if marker not in src:
        raise kit.Skip("this template has no bug clause to take out")
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(src.replace(marker, "if (false &&"))
    jql = bug_link_jql("PRD1", CLAUSE, Path(f.name))
    Path(f.name).unlink()
    t.check(CLAUSE not in jql, "the check passed without the clause in the links: it is blind")


if __name__ == "__main__":
    sys.exit(kit.cli(SUITE, __doc__))
