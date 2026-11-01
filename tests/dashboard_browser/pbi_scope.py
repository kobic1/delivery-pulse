#!/usr/bin/env python3
"""The 'Power BI scope' view of the Capitalization % chart, on the FICTITIOUS fixture, in headless Chrome.

The view reproduces the Power BI "Capitalization" report: Done Bugs, Stories and Tasks of 11 projects, the quarter is the quarter (UTC) of the end date of the issue's LAST
sprint (the latest end date), Unmapped stays in the denominator. The fictitious issues come from make_synthetic.pbi_universe (full sprint lists, issues the rule must leave out,
ties, midnight-UTC edges); the expected numbers are computed from those issues by make_synthetic.pbi_oracle, a second implementation that shares nothing with the page.

    python3 pbi_scope.py --live              # the live program_dashboard/dashboard.template.html
    python3 pbi_scope.py --live --only delta # a subset by name

What it guards: the control (radios in a fieldset with a legend, arrow keys, hash `cps=pbi`, live message), Release disabled, the one-line caption, the filters that do not apply,
the table equal to the oracle (per quarter and project, both measures, the class table, the bars and their n), the no-sprint footnote, the provisional bar, every number a query whose
evaluated set has exactly the printed count (and two seeded defects must be caught), the URL budget, the limited-tier refresh step (insert, replace, delete, move to another quarter,
no-sprint list, a stale read, a failed step, a lost page, an empty answer, the order and the allowance, the stored result) and the notes that name it.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import re
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import harness as H                                                                 # noqa: E402  (its scenario helpers; its tests are not run here)
import jql_eval as J                                                                # noqa: E402
import kit                                                                          # noqa: E402
import make_synthetic as MS                                                         # noqa: E402
from kit import ctx, T                                                              # noqa: E402

SUITE = kit.Suite("Delivery Pulse Power BI scope")
TODAY = MS.il_today()
STEP = "Capitalization (Power BI scope)"
CAPTION = "Power BI scope: 11 projects, quarter of the last sprint's end date; Projects and Teams filters do not apply"
_C: dict = {}


# ---------------------------------------------------------------- the fixture, the oracle and a page helper
def fx():
    if not _C:
        data = MS.make(TODAY)
        u = MS.pbi_cached(TODAY)
        _C.update(data=data, universe=u, oracle=MS.pbi_oracle(u["issues"]), eval=J.pbi_issues(u["issues"]), url=ctx.write(kit.fragment_for(data), "pbi"))
    return _C


def open_page(hash_: str = "", url: str | None = None):
    ch = ctx.chrome
    ch.goto("about:blank")                                                  # a fresh load every time: a change of the address alone would only fire hashchange
    ch.goto((url or fx()["url"]) + ("#" + hash_ if hash_ else ""))
    assert kit.wait_ready(ch), "the page did not draw: " + str(ch.console_errors()[:2])
    return ch


TABLE_JS = """(() => { const t = document.querySelector('#capz-data table'); if (!t) return null;
  return {head: [...t.tHead.rows[0].cells].map(c => c.textContent.trim()), rows: [...t.tBodies[0].rows].map(r => [...r.cells].map(c => c.textContent.trim().replace(/\\s+/g, ' ')))}; })()"""
CLS_JS = """(() => { const t = document.querySelectorAll('#capz-data table')[1]; if (!t) return null;
  return {head: [...t.tHead.rows[0].cells].map(c => c.textContent.trim()), rows: [...t.tBodies[0].rows].map(r => [...r.cells].map(c => c.textContent.trim().replace(/\\s+/g, ' ')))}; })()"""
BARS_JS = """(() => [...document.querySelectorAll('#capz-svg a.cl, #capz-svg g.cl')].map(a => ({tip: a.getAttribute('data-tip'), href: a.getAttribute('href'),
  label: [...a.querySelectorAll('text')].map(x => x.textContent).join('|'), dashed: !!a.querySelector('rect[stroke-dasharray]')})))()"""
CELL = re.compile(r"^([\d,]+) of ([\d,]+) issues · ([\d.,]+) of ([\d.,]+) SP · (.+)$")
num = lambda s: float(s.replace(",", ""))


def expected_cell(c: dict, sp: bool):
    """(capN, allN, capSP, allSP, share text or None) for one oracle cell; the share follows the page's rule (5 issues, 5 with story points)."""
    plotted = c["allN"] >= 5 and (not sp or c["allN"] - c["noSp"] >= 5)
    val = (100 * c["capSP"] / c["allSP"] if c["allSP"] else None) if sp else 100 * c["capN"] / c["allN"]
    return c["capN"], c["allN"], c["capSP"], c["allSP"], (val if plotted and val is not None else None)


def merge(cells) -> dict:
    t = {"capSP": 0.0, "allSP": 0.0, "capN": 0, "allN": 0, "noSp": 0, "cls": [[0, 0.0], [0, 0.0], [0, 0.0]]}
    for c in cells:
        for k in ("capSP", "allSP", "capN", "allN", "noSp"):
            t[k] += c[k]
        for i in range(3):
            t["cls"][i][0] += c["cls"][i][0]
            t["cls"][i][1] += c["cls"][i][1]
    return t


def compare_table(t: T, oracle: dict, sp: bool, label: str, table=None):
    """The page's project x quarter table against the oracle: every cell (capitalized and all issues, both story-point sums, the share) and the total row."""
    table = table or ctx.chrome.js(TABLE_JS)
    quarters = sorted({q for q, _ in oracle["cells"]})
    heads = [h.rstrip("*") for h in table["head"][1:]]
    t.check(heads == quarters, f"{label}: the quarters are {quarters}, the page shows {heads}")
    scope = MS.PBI_SCOPE
    t.check([r[0] for r in table["rows"]] == scope + ["All projects"], f"{label}: one row per project of the scope, then the total -> {[r[0] for r in table['rows']]}")
    bad, checked = [], 0
    for r in table["rows"]:
        for qi, text in enumerate(r[1:]):
            q = quarters[qi]
            cell = oracle["cells"].get((q, r[0])) if r[0] != "All projects" else merge([c for (qq, _), c in oracle["cells"].items() if qq == q])
            if not cell or not cell["allN"]:
                if text != "–":
                    bad.append(f"{r[0]} {q}: expected no issues, the page shows {text!r}")
                continue
            m = CELL.match(text)
            if not m:
                bad.append(f"{r[0]} {q}: unreadable cell {text!r}")
                continue
            capN, allN, capSP, allSP, val = expected_cell(cell, sp)
            got = (int(num(m.group(1))), int(num(m.group(2))), num(m.group(3)), num(m.group(4)))
            checked += 1
            if got[:2] != (capN, allN) or abs(got[2] - capSP) > 0.006 or abs(got[3] - allSP) > 0.006:
                bad.append(f"{r[0]} {q}: page {got}, oracle {(capN, allN, round(capSP, 2), round(allSP, 2))}")
            share = m.group(5)
            if val is None and not share.startswith("n &lt;") and not share.startswith("n <") and share != "–":
                bad.append(f"{r[0]} {q}: share {share!r}, expected the n < 5 notice")
            if val is not None and (not share.endswith("%") or abs(num(share[:-1]) - val) > 0.051):
                bad.append(f"{r[0]} {q}: share {share!r}, oracle {val:.2f}")
    t.check(not bad, f"{label}: {len(bad)} cells differ from the oracle, e.g. {bad[:3]}")
    t.check(checked >= 40, f"{label}: only {checked} cells were compared (a blind test)")
    return checked


# ---------------------------------------------------------------- the control and the caption
@SUITE.test("pbi_control_is_a_radio_group_in_a_fieldset_with_a_legend_and_the_arrow_keys_move_it")
def _(t: T):
    ch = open_page()
    info = ch.js("""(() => { const fs = document.getElementById('f-capscope').closest('fieldset'), inputs = [...fs.querySelectorAll('input')];
      return {legend: fs.querySelector('legend').textContent, types: inputs.map(i => i.type), names: [...new Set(inputs.map(i => i.name))], values: inputs.map(i => i.value), checked: inputs.filter(i => i.checked).map(i => i.value),
              labels: [...fs.querySelectorAll('label')].map(l => l.textContent.trim()), others: [...document.querySelectorAll('#capz-card fieldset')].map(f => f.querySelector('legend').textContent)}; })()""")
    t.check(info["legend"] == "Scope" and info["types"] == ["radio", "radio"] and info["names"] == ["f-capscope"] and info["values"] == ["closed", "pbi"], f"two real radios in one named group with a legend: {info}")
    t.check(info["labels"] == ["Closed date", "Power BI scope"] and info["checked"] == ["closed"], f"the labels and the default (Closed date): {info['labels']} {info['checked']}")
    t.check(info["others"] == ["Group By", "Measure", "Scope"], f"the third control after Group By and Measure: {info['others']}")
    ch.js("document.querySelector('#f-capscope input[value=closed]').focus()")
    ch.cmd("Input.dispatchKeyEvent", type="keyDown", key="ArrowRight", code="ArrowRight", windowsVirtualKeyCode=39)
    ch.cmd("Input.dispatchKeyEvent", type="keyUp", key="ArrowRight", code="ArrowRight", windowsVirtualKeyCode=39)
    t.check(ch.wait_for("state.cap.scope === 'pbi'", 5), "the right arrow key on the first radio moves to Power BI scope (a native radio group, no custom key code)")
    t.check(ch.js("document.getElementById('capz-cap').textContent").startswith(CAPTION), "and the chart changed")
    ch.cmd("Input.dispatchKeyEvent", type="keyDown", key="ArrowLeft", code="ArrowLeft", windowsVirtualKeyCode=37)
    ch.cmd("Input.dispatchKeyEvent", type="keyUp", key="ArrowLeft", code="ArrowLeft", windowsVirtualKeyCode=37)
    t.check(ch.wait_for("state.cap.scope === 'closed'", 5), "the left arrow key goes back")


@SUITE.test("pbi_switch_hash_round_trip_live_message_and_the_default_view_unchanged")
def _(t: T):
    ch = open_page()
    t.check(ch.js("state.cap.scope") == "closed" and ch.js("location.hash.includes('cps')") is False, "the default is the Closed-date view and the address has no cps")
    default_caption = ch.js("document.getElementById('capz-cap').textContent")
    t.check(default_caption.startswith("Capitalized share of Done issues by Closed date") and ch.js("document.getElementById('capz-foot').hidden") is True, f"the default view is the existing one: {default_caption!r}")
    default_table = ch.js("document.querySelector('#capz-data table').textContent")
    ch.js("document.querySelector('#f-capscope input[value=pbi]').click()")
    t.check(ch.js("state.cap.scope") == "pbi" and "cps=pbi" in ch.js("location.hash") and ch.js("document.getElementById('capz-cap').textContent").startswith(CAPTION), "choosing Power BI scope sets the state, the address (cps=pbi) and the caption")
    live = ch.wait_for("document.getElementById('f-live').textContent.includes('Power BI scope')", 3)
    t.check(live, "a polite live message names the new view")
    t.check(ch.js("document.getElementById('f-live').getAttribute('aria-live')") == "polite", "the message sits in the page's polite live region")
    t.check("cps=pbi" in ch.js("location.hash"), "in a copy opened as a file the state is kept in the address")
    fsum = ch.js("document.getElementById('fsum').textContent")
    t.check("Capitalization in Power BI scope by quarter" in fsum, f"the filter summary names it: {fsum!r}")
    ch.goto(fx()["url"] + "#cps=pbi")
    kit.wait_ready(ch)
    t.check(ch.js("state.cap.scope") == "pbi" and ch.js("document.querySelector('#f-capscope input[value=pbi]').checked") is True and ch.js("document.getElementById('capz-cap').textContent").startswith(CAPTION), "an address with cps=pbi opens the view (round trip)")
    ch.js("document.querySelector('#f-capscope input[value=closed]').click()")
    t.check(ch.js("state.cap.scope") == "closed" and "cps" not in ch.js("location.hash") and ch.js("document.querySelector('#capz-data table').textContent") == default_table, "back to Closed date: the address loses cps and the numbers are exactly the default ones")
    t.check(ch.js("document.getElementById('f-reset').disabled") is True, "with Closed date chosen nothing is marked as changed")
    ch.js("document.querySelector('#f-capscope input[value=pbi]').click()")
    t.check("Reset Filters (1)" in ch.js("document.getElementById('f-reset').textContent"), "Power BI scope counts as one applied filter")
    ch.js("document.getElementById('f-reset').click()")
    t.check(ch.js("state.cap.scope") == "closed", "Reset Filters returns to Closed date")
    t.check(not ch.console_errors(), f"no page errors: {ch.console_errors()[:2]}")


@SUITE.test("pbi_choice_is_saved_in_the_browser_storage_of_the_published_page")
def _(t: T):
    H.open_quiet()
    ch = ctx.chrome
    ch.js("document.querySelector('#f-capscope input[value=pbi]').click()")
    saved = ch.js("localStorage.getItem('delivery-pulse-filters')")
    t.check(saved and "cps=pbi" in saved, f"saved like the other Capitalization state: {saved!r}")
    t.check(ch.js("(() => { state.cap.scope = 'closed'; readParams(new URLSearchParams(localStorage.getItem('delivery-pulse-filters'))); return state.cap.scope; })()") == "pbi", "and read back from it")
    ch.js("localStorage.removeItem('delivery-pulse-filters')")                # the storage of file pages is shared: leave nothing behind for the next page


@SUITE.test("pbi_release_is_disabled_with_a_reason_and_quarter_is_the_only_grouping")
def _(t: T):
    ch = open_page("cps=pbi&cpg=release")
    info = ch.js("""(() => { const rel = document.querySelector('#f-capby input[value=release]'), q = document.querySelector('#f-capby input[value=quarter]');
      return {disabled: rel.disabled, title: rel.parentElement.title, quarter: q.checked, release: rel.checked, caption: document.getElementById('capz-cap').textContent, by: state.cap.by, head: [...document.querySelectorAll('#capz-data thead th')].slice(0, 3).map(x => x.textContent)}; })()""")
    t.check(info["disabled"] and info["title"] and "Power BI scope" in info["title"], f"Release is disabled and says why: {info['title']!r}")
    t.check(ch.js("(() => { const i = document.querySelector('#f-capby input[value=release]'); return document.getElementById(i.getAttribute('aria-describedby')).textContent; })()") == info["title"], "a screen reader gets the same reason through aria-describedby")
    t.check(info["quarter"] and not info["release"] and info["head"][1].count("-Q") == 1, f"Quarter is the grouping even when the address asked for release: {info['head']}")
    t.check(info["by"] == "release", "the Release choice itself is kept for the Closed-date view")
    ch.js("document.querySelector('#f-capscope input[value=closed]').click()")
    t.check(ch.js("document.querySelector('#f-capby input[value=release]').checked") is True and ch.js("document.querySelector('#f-capby input[value=release]').disabled") is False, "back in Closed date, Release is enabled and still chosen")


# ---------------------------------------------------------------- the numbers
@SUITE.test("pbi_table_equals_the_independent_oracle_per_quarter_and_project_both_measures")
def _(t: T):
    o = fx()["oracle"]
    for hash_, sp in (("cps=pbi", True), ("cps=pbi&cpm=count", False)):
        ch = open_page(hash_)
        compare_table(t, o, sp, "story points" if sp else "count")
        cls = ch.js(CLS_JS)
        quarters = sorted({q for q, _ in o["cells"]})
        t.check([r[0].rstrip("*") for r in cls["rows"]] == quarters and cls["head"][1:4] == ["Capitalized", "Non capitalized", "Unmapped"], f"the class table has a row per quarter and the three classes: {cls['head']}")
        bad = []
        for r in cls["rows"]:
            tot = merge([c for (qq, _), c in o["cells"].items() if qq == r[0].rstrip("*")])
            for k in range(3):
                text = r[1 + k]
                m = re.match(r"^([\d,]+) issues · ([\d.,]+) SP$", text)
                if tot["cls"][k][0] == 0:
                    if text != "–":
                        bad.append(f"{r[0]} class {k}: {text!r}")
                elif not m or int(num(m.group(1))) != tot["cls"][k][0] or abs(num(m.group(2)) - tot["cls"][k][1]) > 0.006:
                    bad.append(f"{r[0]} class {k}: {text!r} vs {tot['cls'][k]}")
        t.check(not bad, f"the Capitalized, Non capitalized and Unmapped numbers equal the oracle ({'SP' if sp else 'count'}): {bad[:3]}")
        t.check(sum(tot_n for tot_n in [int(num(re.match(r'^([\d,]+)', r[4]).group(1))) for r in cls["rows"]]) == sum(c["allN"] for c in o["cells"].values()), "the quarters add up to every Done issue that has a last sprint in 2025-Q4 or later")
        # the bars: one per quarter, n = the issues of the quarter, the share in the hover text to two decimals, as Power BI shows it
        bars = ch.js(BARS_JS)
        ns = [x[2:] for x in ch.js("[...document.querySelectorAll('#capz-svg svg text')].map(x => x.textContent).filter(x => /^n=\\d+$/.test(x))")]
        t.check(len(bars) == len(quarters), f"one bar per quarter: {len(bars)} bars, {len(quarters)} quarters")
        for b, q, n in zip(bars, quarters, ns):
            tot = merge([c for (qq, _), c in o["cells"].items() if qq == q])
            capN, allN, capSP, allSP, val = expected_cell(tot, sp)
            t.check(int(n) == allN, f"{q}: the bar says n={n}, the issues of the quarter are {allN}")
            m = re.search(r"\n(?:Story Points|Count): ([\d.]+)%", b["tip"])
            t.check(val is not None and m and abs(float(m.group(1)) - val) <= 0.006, f"{q}: the hover share {m and m.group(1)} equals the oracle {val and round(val, 2)}")
            t.check(f"{capN} of {allN} issues" in b["tip"] or f"{+round(capSP, 2):g} of {+round(allSP, 2):g} points" in b["tip"], f"{q}: the hover text carries the numbers behind the bar")
        t.check(not ch.console_errors(), f"no page errors: {ch.console_errors()[:2]}")


@SUITE.test("pbi_parity_with_the_report_the_rule_leaves_out_what_power_bi_leaves_out")
def _(t: T):
    """The universe holds issues the rule must not count: the page's totals must equal the sum over ONLY the in-scope Done Bug/Story/Task issues with a last sprint from 2025-Q4 on."""
    F = fx()
    issues = F["universe"]["issues"]
    open_page("cps=pbi")
    page_total = ctx.chrome.js("capPbiRecords().length")
    only = [i for i in issues if i["project"] in MS.PBI_SCOPE and i["status"] == "Done" and i["type"] in ("Bug", "Story", "Task") and MS.pbi_last(i)
            and MS.pbi_parse(MS.pbi_last(i)["endDate"]).astimezone(MS.UTC).date().isoformat() >= MS.PBI_START]
    t.check(page_total == len(only), f"the page holds {page_total} rows, the rule selects {len(only)}")
    left_out = [i for i in issues if i not in only]
    t.check(any(i["type"] == "Sub-task" for i in left_out) and any(i["project"] == "WFM" for i in left_out) and any(i["status"] != "Done" for i in left_out), "the fixture really holds sub-tasks, a project outside the scope and issues that are not Done")
    # the three ways of choosing a quarter that the rule rejects give different numbers on this fixture (a test that cannot tell them apart would prove nothing)
    byid = {}
    byfirst = {}
    for i in only:
        withend = [s for s in i["sprints"] if s["endDate"]]
        byid.setdefault(MS.pbi_quarter(max(withend, key=lambda s: s["id"])["endDate"]), []).append(i)
        byfirst.setdefault(MS.pbi_quarter(min(withend, key=lambda s: (MS.pbi_parse(s["endDate"]), s["id"]))["endDate"]), []).append(i)
    rule = {}
    for i in only:
        rule.setdefault(MS.pbi_quarter(MS.pbi_last(i)["endDate"]), []).append(i)
    t.check({q: len(v) for q, v in byid.items()} != {q: len(v) for q, v in rule.items()} and {q: len(v) for q, v in byfirst.items()} != {q: len(v) for q, v in rule.items()}, "the fixture tells the last sprint by end date apart from the highest sprint id and from the first sprint")
    m = ctx.chrome.js("(() => { const g = capPbiGroups().groups; return g.map(x => [x.k, x.tot.allN]); })()")
    t.check({q: n for q, n in m} == {q: len(v) for q, v in rule.items()}, f"the page groups by the rule: {m}")


@SUITE.test("pbi_projects_and_teams_filters_do_not_apply_and_the_caption_says_so")
def _(t: T):
    ch = open_page("cps=pbi")
    base = ch.js("document.querySelector('#capz-data table').textContent")
    svg = ch.js("document.getElementById('capz-svg').textContent")
    team = urllib.parse.quote(fx()["data"]["cap"]["teams"][0])
    for h in (f"cps=pbi&p=PMN&t={team}", "cps=pbi&p=CXWFM|WFM", "cps=pbi&c=Stretch&r=26.2"):
        ch2 = open_page(h)
        t.check(ch2.js("document.querySelector('#capz-data table').textContent") == base and ch2.js("document.getElementById('capz-svg').textContent") == svg, f"#{h}: the table and the bars are the same as with no filter")
        t.check(ch2.js("document.getElementById('capz-cap').textContent").startswith(CAPTION), f"#{h}: the caption says the filters do not apply")
    ch.js("document.getElementById('f-reset').click()")
    cap = ch.js("document.getElementById('capz-cap').textContent")
    t.check(cap.startswith("Capitalized share of Done issues by Closed date"), "the Closed-date view still follows the filters")


@SUITE.test("pbi_no_sprint_footnote_and_the_provisional_bar")
def _(t: T):
    o = fx()["oracle"]
    ch = open_page("cps=pbi")
    foot = ch.js("(() => { const f = document.getElementById('capz-foot'); return {hidden: f.hidden, text: f.textContent, title: f.title, links: f.querySelectorAll('a').length}; })()")
    n = o["none"]["n"]
    t.check(not foot["hidden"] and foot["text"] == f"{n} Done issues have no sprint and are not in a quarter", f"the footnote counts the Done issues with no sprint (none, or only sprints without an end date): {foot['text']!r}, oracle {n}")
    t.check(n >= 20 and foot["links"] == 0 and "Not a link" in foot["title"], "the fixture has some, and the number is plain text with the reason in its tooltip")
    t.check("1 Done issue has no sprint and is not in a quarter" == ch.js("(() => { DATA.capPbi.noSprint.n = 1; renderCapitalization(); return document.getElementById('capz-foot').textContent; })()"), "singular wording for one")
    bars = ch.js(BARS_JS)
    cur = f"{TODAY.year}-Q{(TODAY.month - 1) // 3 + 1}"
    t.check([b["dashed"] for b in bars] == [False] * (len(bars) - 1) + [True], f"only the current quarter ({cur}) is a dashed bar: {[b['dashed'] for b in bars]}")
    t.check("current quarter" in bars[-1]["tip"] and "current quarter" not in bars[0]["tip"], "and its hover text says so (not by outline alone)")
    t.check(ch.js("document.querySelector('#capz-svg svg').getAttribute('aria-label')").startswith("Capitalization % per quarter in the Power BI scope") and all(b["tip"] for b in bars), "the chart has a text alternative and every bar has a hover text")
    ch.js("(() => { const g = document.querySelector('#capz-svg a.cl'); g.focus(); })()")
    t.check(ch.js("!!document.querySelector('#capz-svg a.cl[aria-label]')") is True, "every linked bar has an aria-label (as the other tiles)")
    ch2 = open_page()
    t.check(ch2.js("document.getElementById('capz-foot').hidden") is True, "the footnote is not shown in the Closed-date view")


@SUITE.test("pbi_without_the_section_a_notice_and_the_other_view_untouched")
def _(t: T):
    data = copy.deepcopy(fx()["data"])
    del data["capPbi"]
    ch = open_page("cps=pbi", ctx.write(kit.fragment_for(data), "nopbi"))
    msg = ch.js("document.getElementById('capz-svg').textContent")
    t.check("--add-capitalization-pbi" in msg, f"a build without the section says how to add it: {msg!r}")
    ch.js("document.querySelector('#f-capscope input[value=closed]').click()")
    t.check(ch.js("document.getElementById('capz-cap').textContent").startswith("Capitalized share") and not ch.console_errors(), "the Closed-date view works and there are no page errors")
    data2 = copy.deepcopy(fx()["data"])
    data2["capPbi"]["scope"] = data2["capPbi"]["scope"][:-1]
    ch = open_page("cps=pbi", ctx.write(kit.fragment_for(data2), "otherscope"))
    t.check("another list of projects" in ch.js("document.getElementById('capz-svg').textContent"), "data read for another project list is refused with a notice, not drawn")


# ---------------------------------------------------------------- the links: every number is a query whose evaluated set has the printed count
PBI_STATES = ["cps=pbi", "cps=pbi&cpm=count", "cps=pbi&cpg=release", "cps=pbi&p=PMN", "cps=pbi&p=CXWFM|WFM&cpm=count", "cps=pbi&TEAM"]
ANCHORS_JS = """(() => [...document.querySelectorAll('#capz-host a[href], #capz-data a[href]')].map(a => ({href: a.getAttribute('href'), text: (a.textContent || '').trim(), tip: a.getAttribute('data-tip') || '',
  row: ((a.closest('tr') || {}).innerText || (a.closest('#capz-dq') ? 'capz-dq' : a.closest('#capz-svg') ? 'bar' : '')).replace(/\\s+/g, ' ').slice(0, 50)})))()"""


def pbi_anchors(url: str | None = None, hashes=PBI_STATES) -> list[dict]:
    out = []
    team = urllib.parse.quote(fx()["data"]["cap"]["teams"][0])
    for h in hashes:
        ch = open_page(h.replace("TEAM", f"t={team}"), url)
        for a in ch.js(ANCHORS_JS):
            a["state"] = h
            out.append(a)
    return out


def jql_of(href: str) -> str:
    return urllib.parse.parse_qs(urllib.parse.urlsplit(href).query, keep_blank_values=True).get("jql", [""])[0]


def judge(a: dict, universe: list[dict]):
    """('ok'|'mismatch'|'skip', detail): the printed count of a link against its query evaluated over the fictitious issues."""
    j = jql_of(a["href"])
    if a["row"] == "bar":
        m = re.search(r"the ([\d,]+) issues of this bar", a["tip"])
        n = int(m.group(1).replace(",", "")) if m else None
    else:
        n = int(a["text"].replace(",", "")) if a["text"].replace(",", "").isdigit() else None
    if n is None:
        return "skip", ""
    got = J.count(j, universe)
    return ("ok" if got == n else "mismatch"), f"printed {n}, the query matches {got}"


@SUITE.test("pbi_links_every_number_is_a_query_that_finds_exactly_the_printed_count")
def _(t: T):
    F = fx()
    anchors = pbi_anchors()
    bad, seen, kinds = [], 0, set()
    for a in anchors:
        st, d = judge(a, F["eval"])
        if st == "skip":
            continue
        seen += 1
        j = jql_of(a["href"])
        kinds.add("quarter")
        kinds.update(k for k, frag in (("class", "cf[10079] in ("), ("unmapped", "cf[10079] is EMPTY"), ("nosp", "cf[10038]"), ("project cell", ' AND project = "')) if frag in j)
        if st != "ok":
            bad.append(f"[{a['state']}] '{a['text']}' ({a['row']}): {d}")
    t.check(not bad, f"{len(bad)} links open a set that is not the printed count, e.g. {bad[:3]}")
    t.check(seen >= 250, f"{seen} links were evaluated (a blind oracle checks fewer than 250 over 6 views)")
    t.check({"class", "unmapped", "nosp", "project cell", "quarter"} <= kinds, f"the evaluated links cover the quarter, project, class, Unmapped and no-story-points queries: {sorted(kinds)}")
    # the shape of the query (the owner's rule)
    sample = next(a for a in anchors if a["row"].startswith("PMN") and "capitalized" in a["tip"])
    j = jql_of(sample["href"])
    t.check(re.match(r'^project in \("PMN", "CXSUP", "CXINT", "CXWFM", "CXCO", "INT", "EEM", "EMOB", "ESP", "DCMLT", "PVDEV"\) AND status = Done AND issuetype in \(Bug, Story, Task\) AND sprint in \(\d+(, \d+)*\)( AND sprint not in \(\d+(, \d+)*\))? AND project = "PMN" AND cf\[10079\] in \(', j) is not None, f"the shape of a project cell query: {j[:260]}")
    t.check(not [a for a in anchors if '"WFM"' in jql_of(a["href"])], "the Jira project WFM is not in the project list of any link")
    t.check(not [a for a in anchors if re.search(r"\bkey\s+in\s*\(", urllib.parse.unquote(a["href"]), re.I)], "no link is a list of issue keys")
    longest = max(len(a["href"]) for a in anchors)
    t.check(longest <= 6000, f"every link is within the 6,000 character budget (longest {longest})")
    t.note(f"{seen} links evaluated, {len(anchors)} links seen, the longest {longest} characters")


@SUITE.test("pbi_links_oracle_selftest_catches_seeded_defects")
def _(t: T):
    src = ctx.template.read_text(encoding="utf-8")
    F = fx()
    muts = [("the exclusion of later sprints dropped", '(later.length ? ` AND sprint not in (${later.join(", ")})` : "")', '""'),
            ("Unmapped without the empty value", "cf[10079] is EMPTY${cv.length", "cf[10079] is not EMPTY${cv.length"),
            ("the project clause of a cell dropped", " AND project = ${q(o.proj)}", "")]
    ran = 0
    for label, old, new in muts:
        if src.count(old) != 1:
            t.note(f"not run: {label} (the pattern is not in this template exactly once)")
            continue
        ran += 1
        tmp = Path(ctx.dir) / f"pbi_mutant_{ran}.html"
        payload = json.dumps(F["data"], ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
        tmp.write_text(src.replace(old, new, 1).replace("/*__DATA__*/null", payload), encoding="utf-8")
        found = [a for a in pbi_anchors("file://" + str(tmp), PBI_STATES[:2]) if judge(a, F["eval"])[0] == "mismatch"]
        t.check(bool(found), f"seeded defect caught: {label} ({len(found)} mismatching links)")
    if not ran:
        raise kit.Skip("none of the seeded defects applies to this template version")


@SUITE.test("pbi_links_a_query_over_the_url_budget_is_plain_text")
def _(t: T):
    ch = open_page("cps=pbi")
    before = len(ch.js(ANCHORS_JS))
    ch.js("""(() => { const P = DATA.capPbi, last = capPbiRecords()[0].q, [y, n] = last.split('-Q').map(Number), day = `${y}-${String((n - 1) * 3 + 2).padStart(2, '0')}-10`;
      for (let i = 0; i < 700; i++) P.sprints.push([900000 + i, day]); CAPPBI = null; renderCapitalization(); })()""")
    after = ch.js(ANCHORS_JS)
    t.check(after and max(len(a["href"]) for a in after) <= 6000, f"no link is over 6,000 characters (longest {max(len(a['href']) for a in after)})")
    t.check(len(after) < before, f"the quarters whose sprint list grew too long lost their links (the number stays, as text): {before} -> {len(after)} links")
    quarter_cell = ch.js("document.querySelector('#capz-data table tbody tr:last-child td').textContent.trim()")
    t.check(CELL.match(re.sub(r"\s+", " ", quarter_cell)) is not None, f"the number is still printed: {quarter_cell!r}")


# ---------------------------------------------------------------- the refresh step
def subjects():
    """The issues each delta case is about, chosen from the fictitious data, and the issues after the changes (the oracle of the outcome)."""
    F = fx()
    if "subj" in _C:
        return _C["subj"]
    u = F["universe"]
    issues = copy.deepcopy(u["issues"])
    sprints = u["sprints"]
    start = MS.PBI_START
    endday = lambda s: MS.pbi_parse(s["endDate"]).astimezone(MS.UTC).date().isoformat()
    rows = [i for i in issues if MS.pbi_in_scope(i) and MS.pbi_last(i) and endday(MS.pbi_last(i)) >= start]
    quarters = sorted({MS.pbi_quarter(MS.pbi_last(i)["endDate"]) for i in rows})
    take = lambda pred: next(i for i in rows if pred(i) and i["key"] not in used)
    used: set = set()

    def pick(pred):
        i = take(pred)
        used.add(i["key"])
        return i
    S = {}
    S["A"] = pick(lambda i: i["type"] == "Story" and MS.pbi_class(i["value"]) == 2)                      # an Unmapped one that gets a Capitalize value and new points
    S["B"] = pick(lambda i: MS.pbi_class(i["value"]) == 0)                                                # reopened
    S["F"] = pick(lambda i: MS.pbi_class(i["value"]) == 1)                                                # Removed
    S["C"] = pick(lambda i: MS.pbi_quarter(MS.pbi_last(i)["endDate"]) == quarters[1])                     # its last sprint changes to one of the latest quarter
    later = [s for s in sprints if s["endDate"] and s["id"] != 20000 and MS.pbi_quarter(s["endDate"]) == quarters[-1]]
    S["C_to"] = max(later, key=lambda s: (MS.pbi_parse(s["endDate"]), s["id"]))
    S["G"] = pick(lambda i: True)                                                                         # not returned: untouched
    none = [i for i in issues if MS.pbi_in_scope(i) and not MS.pbi_last(i) and i["resolutiondate"][:10] >= MS.PBI_FROM]
    S["E1"], S["E1b"] = none[0], none[1]                                                                  # no sprint now: E1 gets one, E1b stays (and is returned)
    ties = {}
    for s in sprints:
        if s["endDate"]:
            ties.setdefault(s["endDate"], []).append(s)
    S["tie"] = next(v for v in ties.values() if len(v) == 2)
    S["edge"] = next(s for s in sprints if s["endDate"] and s["endDate"].endswith("-0500"))
    S["edge3"] = next(s for s in sprints if s["endDate"] and s["endDate"].endswith("+0300"))
    changes = []                                                                                           # (issue after the change)
    now = dt.datetime(TODAY.year, TODAY.month, TODAY.day, 21, 0, tzinfo=MS.UTC)
    new_sprint = {"id": 29500, "name": "Sprint 29500", "state": "active", "startDate": MS.pbi_iso(now - dt.timedelta(days=7)), "endDate": MS.pbi_iso(now), "completeDate": None}
    S["new_sprint"] = new_sprint
    mk = lambda key, proj, status, typ, spr, value, sp, res=None: {"key": key, "project": proj, "num": int(key.split("-")[1]), "type": typ, "status": status, "value": value, "sp": sp, "sprints": spr,
                                                                   "resolutiondate": res or kit.stamp(TODAY, "12:00")}
    a = S["A"]
    a["value"], a["sp"] = "Capitalize - Brand new value", 21
    S["B"]["status"] = "In Progress"
    S["F"]["status"] = "Removed"
    S["C"]["sprints"] = S["C"]["sprints"] + [S["C_to"]]
    S["E1"]["sprints"] = [S["edge"]]
    new = [mk("PMN-139001", "PMN", "Done", "Story", [new_sprint], "Capitalize - Feature work", 3),                                # a new Done issue in a sprint the table does not know
           mk("CXSUP-139002", "CXSUP", "Done", "Bug", [], "Non Capitalize - Research", 2),                                         # a new Done issue with no sprint
           mk("INT-139003", "INT", "Done", "Task", S["tie"], "", 5),                                                               # two sprints ending at the same instant: the higher id
           mk("ESP-139004", "ESP", "Done", "Task", [S["edge3"], S["edge"]], "Non capitalize - Not cloud", None),                  # ends around midnight UTC: the UTC quarter decides; blank points
           mk("PVDEV-139005", "PVDEV", "Done", "Story", [next(s for s in sprints if s["id"] == 20000)], "Capitalize - Feature work", 8),   # last sprint before the start: not in a quarter
           mk("DCMLT-139006", "DCMLT", "Done", "Story", [new_sprint, next(s for s in sprints if s["id"] == 29001)], "Misc value", 1),   # an endless sprint beside a dated one
           mk("EEM-139007", "EEM", "In Progress", "Story", [new_sprint], "Capitalize - Feature work", 1),                      # not Done: not added
           mk("PMN-139008", "PMN", "Done", "Sub-task", [new_sprint], "Capitalize - Feature work", 1)]                            # a sub-task: the query would not return it; the page must not add it either
    issues += new
    S["new"] = new
    returned = [S["A"], S["B"], S["F"], S["C"], S["E1"], S["E1b"], *new]
    S["nodes"] = [MS.pbi_node(i) for i in returned]
    S["returned_keys"] = {i["key"] for i in returned}
    S["after_universe"] = {"sprints": sprints + [new_sprint], "issues": issues}
    S["rows_before"] = decode(F["data"]["capPbi"])
    _C["subj"] = S
    return S


def decode(section: dict) -> set:
    """(key, class, points, sprint id, UTC end day) of every row, from the compact text."""
    out = set()
    for x in section["rows"].split(";") if section["rows"] else []:
        n, pi, c, sp, si = x.split(",")
        out.add((f"{section['scope'][int(pi)]}-{n}", int(c), float(sp), section["sprints"][int(si)][0], section["sprints"][int(si)][1]))
    return out


def decode_none(section: dict) -> set:
    return {(f"{section['scope'][int(x.split(',')[1])]}-{x.split(',')[0]}", float(x.split(",")[2])) for x in section["noSprint"]["rows"].split(";") if x}


def refresh_once(**kw):
    S = subjects()
    kw.setdefault("pbinodes", S["nodes"])
    return H.scenario("ok", ls="recent", click=True, cache=False, **kw)


@SUITE.test("delta_inserts_replaces_deletes_and_moves_exactly_as_the_rule_says")
def _(t: T):
    F, S = fx(), subjects()
    r = refresh_once()
    a, b = r["after"], r["before"]
    t.check(not r["timed_out"] and r["status"].startswith("Refreshed ") and "Not refreshed" not in r["status"], f"the refresh finished without a failed step: {r['status'][-120:]}")
    before = decode(F["data"]["capPbi"])
    t.check(b["pbi"]["rows"] == F["data"]["capPbi"]["rows"], "the page started from the baked rows")
    P = {"scope": F["data"]["capPbi"]["scope"], "rows": a["pbi"]["rows"], "sprints": a["pbi"]["sprints"], "noSprint": a["pbi"]["none"]}
    after = decode(P)
    want = MS.pbi_payload(S["after_universe"], TODAY)
    t.check(after == decode(want), f"the rows equal the rows of the outcome computed from the changed issues ({len(after)} rows; only in page {sorted(after - decode(want))[:2]}, only in outcome {sorted(decode(want) - after)[:2]})")
    t.check(decode_none(P) == decode_none(want) and a["pbi"]["none"]["n"] == want["noSprint"]["n"] and abs(a["pbi"]["none"]["sp"] - want["noSprint"]["sp"]) < 0.006, f"the no-sprint list equals the outcome: {a['pbi']['none']['n']} vs {want['noSprint']['n']}")
    t.check(a["pbi"]["opts"] == want["opts"], f"a Capitalize value that appeared since is a link value now: {a['pbi']['opts']}")
    keys = {x[0] for x in after}
    rowof = {x[0]: x for x in after}
    t.check(rowof[S["A"]["key"]][1:3] == (0, 21.0), "A: the changed value and points replace the row")
    t.check(S["B"]["key"] not in keys and S["F"]["key"] not in keys, "B reopened and F Removed: their rows are deleted")
    qa = lambda day: f"{day[:4]}-Q{(int(day[5:7]) - 1) // 3 + 1}"
    old_c = next(x for x in before if x[0] == S["C"]["key"])
    new_c = rowof[S["C"]["key"]]
    t.check(qa(old_c[4]) != qa(new_c[4]) and new_c[3] == S["C_to"]["id"], f"C: a new last sprint moves the issue to another quarter ({qa(old_c[4])} -> {qa(new_c[4])})")
    t.check("PMN-139001" in keys and rowof["PMN-139001"][3] == 29500 and any(x[0] == 29500 for x in a["pbi"]["sprints"]), "D: a new Done issue in an unknown sprint is inserted and the sprint is added to the table")
    t.check("CXSUP-139002" not in keys and ("CXSUP-139002", 2.0) in decode_none(P), "a new Done issue with no sprint is in the no-sprint list, not in a quarter")
    t.check(S["E1"]["key"] in keys and S["E1"]["key"] not in {k for k, _ in decode_none(P)}, "E1: an issue that got its first sprint moves from the no-sprint list into a quarter")
    t.check((S["E1b"]["key"], float(S["E1b"]["sp"] or 0)) in decode_none(P), "E1b: returned again with no sprint: still in the list, once")
    t.check(rowof["INT-139003"][3] == max(s["id"] for s in S["tie"]), f"two sprints ending at the same instant: the higher id is the last one ({rowof['INT-139003'][3]})")
    t.check(rowof["ESP-139004"][4] == max((MS.pbi_parse(s["endDate"]), s["id"]) for s in (S["edge3"], S["edge"]))[0].astimezone(MS.UTC).date().isoformat() and rowof["ESP-139004"][2] == 0.0, "an end around midnight UTC gets the UTC day; blank points are 0")
    t.check("PVDEV-139005" not in keys and ("PVDEV-139005", 8.0) not in decode_none(P), "a last sprint before 2025-Q4 is in neither the chart nor the list")
    t.check("DCMLT-139006" in keys and rowof["DCMLT-139006"][3] == 29500, "a sprint without an end date beside a dated one does not count; the dated one is the last")
    t.check("EEM-139007" not in keys and "PMN-139008" not in keys, "an issue that is not Done and a sub-task are not added")
    untouched = {x for x in before if x[0] not in S["returned_keys"]}
    t.check(untouched <= after and len(untouched) > 400, f"{len(untouched)} rows the response did not return are unchanged (absence never deletes)")
    t.check(a["pbi"]["at"] and b["pbi"]["at"] is None and a["pbi"]["rows"] != b["pbi"]["rows"], "refreshedAt is set")
    ch = ctx.chrome
    ch.js("document.querySelector('#f-capscope input[value=pbi]').click()")
    oracle = MS.pbi_oracle(S["after_universe"]["issues"])
    compare_table(t, oracle, True, "after the refresh")
    cap = ch.js("document.getElementById('capz-cap').textContent")
    t.check(f"refreshed {H.il_label(a['pbi']['at'])}" in cap and cap.startswith(CAPTION), f"the caption carries the refresh time -> {cap[-70:]}")
    t.check(not r["errors"], f"no page errors: {r['errors'][:2]}")


@SUITE.test("delta_an_empty_answer_deletes_nothing")
def _(t: T):
    r = H.scenario("emptypbi", ls="recent", click=True, cache=False)
    t.check(r["after"]["pbi"]["rows"] == r["before"]["pbi"]["rows"] and r["after"]["pbi"]["at"] and "Not refreshed" not in r["status"], "an empty response changes no row and is not a failure")


@SUITE.test("delta_a_failed_step_leaves_its_data_unchanged_and_says_so")
def _(t: T):
    r = H.scenario("pbifail", ls="recent", click=True, cache=False)
    a, b = r["after"], r["before"]
    t.check(json.dumps(a["pbi"], sort_keys=True) == json.dumps(b["pbi"], sort_keys=True), "the Power BI scope data is byte-identical after a failed step")
    t.check(f"Not refreshed, data unchanged: {STEP} (power bi boom)" in r["status"] and "warn" in r["statusKind"], f"the message names the step and its reason -> {r['status'][-150:]}")
    t.check(a["capRows"] != b["capRows"] and a["pbiFail"] == "power bi boom", "the Closed-date step before it still applied; the failure is kept for the caption")
    ctx.chrome.js("document.querySelector('#f-capscope input[value=pbi]').click()")
    cap = ctx.chrome.js("document.getElementById('capz-cap').textContent")
    t.check("not refreshed: power bi boom; as of" in cap, f"the chart caption says what was not refreshed -> {cap[-90:]}")
    d = H.slow_state(ctx.chrome.js("localStorage.getItem('dp.slowData')"))
    t.check(d and "pbi" not in d and "pbiAt" not in d and d.get("capAt"), f"only the steps that succeeded were stored: {sorted(d or {})}")
    r2 = H.scenario("ok", ls="recent", click=True, cache=False, pbinodes=subjects()["nodes"], hook="""async (input, c) => { if (/project in \\("/.test(input.jql) && !input.searchResultMode) { window.__pbiCalls = (window.__pbiCalls || 0) + 1;
        if (!input.nextPageToken) return c.ok(CFG.pbinodes.slice(0, 3), "p2"); if (input.nextPageToken === "p2") throw {code: "tool_error", message: "second page boom"}; } }""")
    t.check(json.dumps(r2["after"]["pbi"], sort_keys=True) == json.dumps(r2["before"]["pbi"], sort_keys=True) and "second page boom" in r2["status"], "a second page that fails after a first one that returned changes: nothing was applied")


@SUITE.test("delta_a_lost_page_is_caught_by_jiras_count_and_nothing_is_applied")
def _(t: T):
    r = H.scenario("ok", ls="recent", click=True, cache=False, pbinodes=subjects()["nodes"], pbiCountDelta=40)
    t.check(r["after"]["pbi"]["rows"] == r["before"]["pbi"]["rows"] and "Jira counted" in r["status"] and "nothing was applied" in r["status"], f"Jira's count disagrees with the read: the step fails, data unchanged -> {r['status'][-160:]}")


@SUITE.test("delta_a_read_overtaken_by_another_is_ignored")
def _(t: T):
    """The data was replaced while this read was in flight (another refresh finished first): the older read must not be applied over it."""
    hook = """async (input, c) => { if (/project in \\("/.test(input.jql) && !input.searchResultMode && !window.__swapped) { window.__swapped = true;
        DATA.capPbi = JSON.parse(JSON.stringify(DATA.capPbi)); DATA.capPbi.refreshedAt = new Date().toISOString(); CAPPBI = null; } }"""
    r = H.scenario("ok", ls="recent", click=True, cache=False, pbinodes=subjects()["nodes"], hook=hook)
    a, b = r["after"], r["before"]
    t.check(a["pbi"]["rows"] == b["pbi"]["rows"] and "changed while it was being read" in r["status"], f"the stale read is dropped -> {r['status'][-170:]}")
    t.check(a["pbi"]["at"] is not None and a["pbiFail"] and "nothing was applied" in a["pbiFail"], "and the newer data keeps its own refresh time")


@SUITE.test("delta_runs_in_the_limited_tier_after_capitalization_and_not_on_the_third_click")
def _(t: T):
    H.open_quiet(pbinodes=subjects()["nodes"])
    pbi = lambda c: [x for x in c["calls"] if 'project in ("' in x["jql"] and x["tool"] != "getJiraIssue"]
    c1, c2 = H.click_run(H.pend_js()), H.click_run(H.pend_js())
    c3 = H.click_run(H.pend_js())
    t.check(len(pbi(c1)) >= 1 and len(pbi(c2)) >= 1, f"clicks 1 and 2 read the Power BI scope ({len(pbi(c1))}, {len(pbi(c2))} calls)")
    t.check(len(pbi(c3)) == 0 and H.skipped_limited(c3), "click 3 does not (it is counted in the same allowance)")
    cap_idx = [x["i"] for x in c1["calls"] if "project = " in x["jql"] and "issuetype in (Bug, Story, Task)" in x["jql"]]
    t.check(cap_idx and max(cap_idx) < min(x["i"] for x in pbi(c1)), "the step runs after Capitalization")
    q = pbi(c1)[0]["jql"]
    t.check(q.startswith('project in ("PMN", "CXSUP", "CXINT", "CXWFM", "CXCO", "INT", "EEM", "EMOB", "ESP", "DCMLT", "PVDEV") AND issuetype in (Bug, Story, Task) AND updated >= "'), f"the query: {q[:200]}")
    t.check(pbi(c1)[0]["fields"] == 6, "six fields are asked for")
    t.check(c1["slow"]["n"] == 1 and c2["slow"]["n"] == 2, "the allowance counted once per click, not once per step")


@SUITE.test("delta_the_stored_result_survives_a_reload_and_a_bad_value_is_ignored")
def _(t: T):
    S = subjects()
    r1 = refresh_once()
    a1 = r1["after"]
    d = H._stored()
    t.check(d["schema"] == 3 and d["pbiAt"] == a1["pbi"]["at"] and d["pbi"]["rows"] == a1["pbi"]["rows"] and d["pbi"]["refreshedAt"] == d["pbiAt"], f"stored with the data version and the refresh time: {sorted(d)}")
    r2 = H._reload()
    b2 = r2["before"]
    t.check(b2["pbi"]["rows"] == a1["pbi"]["rows"] and b2["pbi"]["at"] == a1["pbi"]["at"] and not r2["errors"], "a reload shows the refreshed Power BI scope before any refresh")
    good = d
    for label, patch in (("rows pointing outside the sprint list", {"pbi": {**good["pbi"], "rows": "1,0,0,3,9999"}}), ("a project list that is not the page's", {"pbi": {**good["pbi"], "scope": ["PMN"]}}),
                         ("a refresh time in the future", {"pbiAt": "2999-01-01T00:00:00Z", "pbi": {**good["pbi"], "refreshedAt": "2999-01-01T00:00:00Z"}}), ("a read not newer than the data's own", {"pbiAt": fx()["data"]["capPbi"]["pulledAt"], "pbi": {**good["pbi"], "refreshedAt": fx()["data"]["capPbi"]["pulledAt"]}}),
                         ("not an object", {"pbi": "x"}), ("the refresh time not matching its data", {"pbi": {**good["pbi"], "refreshedAt": "2026-01-01T00:00:00Z"}})):
        H._set_stored({**good, **patch})
        r3 = H._reload()
        t.check(r3["before"]["pbi"]["rows"] == fx()["data"]["capPbi"]["rows"] and r3["before"]["pbi"]["at"] is None and not r3["errors"], f"{label}: ignored, the baked data stays, no page errors {r3['errors'][:1]}")
    H._set_stored({**good, "build": "2000-01-01T00:00:00Z"})
    r4 = H._reload()
    t.check(r4["before"]["pbi"]["rows"] == fx()["data"]["capPbi"]["rows"], "another data version: discarded")


@SUITE.test("delta_notes_and_the_stamp_tooltip_name_the_step_in_plain_words")
def _(t: T):
    kw = dict(ls="recent", click=True, fast=True, wait="js", wait_js="window.__done === true && document.getElementById('asof').textContent.startsWith('Data as of')", cache=False)
    r = H.scenario("ok", sr="used", **kw)
    a = r["after"]
    t.check("Cycle time not refreshed yet; Capitalization not refreshed yet; Capitalization (Power BI scope) not refreshed yet." in a["stampTip"], f"the tooltip names the step: {a['stampTip']!r}")
    t.check(a["raNote"] == "Cycle time and Capitalization: not refreshed yet; Capitalization in Power BI scope: not refreshed yet; Refresh updates them up to twice a day.", f"Release Analysis says it -> {a['raNote']!r}")
    ctx.chrome.js("document.querySelector('#f-capscope input[value=pbi]').click()")
    t.check("not refreshed yet" in ctx.chrome.js("document.getElementById('capz-cap').textContent"), "and so does the chart caption")
    r2 = H.scenario("ok", sr="none", **kw)
    b = r2["after"]
    t.check(" as of " not in b["stampTip"] and "not refreshed yet" not in b["stampTip"], f"after a full refresh the limited line is absent -> {b['stampTip']!r}")
    t.check(f"Capitalization in Power BI scope: refreshed {H.il_label(b['pbi']['at'])}" in b["raNote"], f"Release Analysis carries the refresh time -> {b['raNote']!r}")
    t.check(not any("build" in x.lower() for x in (b["effNote"], b["raNote"], b["stampTip"], r2["status"], a["raNote"])), "nothing talks about a build")
    f = H.scenario("pbifail", sr="none", **kw)
    t.check("Capitalization in Power BI scope: not refreshed (power bi boom)" in f["after"]["raNote"], f"a failed step is called out in Release Analysis -> {f['after']['raNote']!r}")


if __name__ == "__main__":
    sys.exit(kit.cli(SUITE, __doc__))
