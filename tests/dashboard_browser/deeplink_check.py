#!/usr/bin/env python3
"""Deep links: a link to the dashboard that ends in a plain #token opens the page on that section.

Asserted (file mode, headless Chrome; the Artifact passes only such a plain #token to the page):
  * #quality, #cycles and #ai-adoption open with that section's heading in view (the strip's current entry is the section, or Efficiency for AI Adoption when the strip has no entry for it) and focus on the heading;
  * a token is not a filter state: the reader's filters are the defaults (or the saved ones), and the page does not start at a filter view;
  * a product token opens the product view (#prd1) and #prd1~quality opens a section of it; a section that view does not have (#prd1~cycles), an unknown token and a token that only looks like a section open the page as usual;
  * the reader taking over (a wheel event) stops the corrections;
  * in the published page (a mocked claude runtime here) a click on a strip entry puts that section's token in the address at once (#dependencies, #prd1~quality in a product view), the address follows the
    keyboard moves of the strip too, and there is no copy-link button.

    python3 deeplink_check.py [--live] [--only NAME]
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kit                                                                          # noqa: E402
import make_synthetic as MS                                                         # noqa: E402
from kit import ctx, T                                                              # noqa: E402

SUITE = kit.Suite("Delivery Pulse deep links")


def load(token, vp=(1400, 900), products=True, runtime=False, prelude=None):
    ch = ctx.chrome
    data = MS.make(MS.il_today())
    data["build"] = {"sha": "abc1234", "dirty": False, "at": "2026-01-01T00:00+02:00"}
    if products:
        data["productList"], data["products"] = ["PRD1", "PRD2"], MS.product_sample(data)
    url = ctx.write(kit.wrap(MS.render_page(data), prelude=prelude or ("<script>window.claude = {use: () => Promise.resolve(null)};</script>" if runtime else "")), "deep")
    ch.cmd("Emulation.setTimezoneOverride", timezoneId="Asia/Jerusalem")
    ch.viewport(*vp, mobile=vp[0] < 500)
    ch.goto(url + ("#" + token if token else ""))
    assert kit.wait_ready(ch), "the page did not draw: " + str(ch.console_errors()[:2])
    time.sleep(1.4)
    return ch


def js(ch, code):
    return ch.js(f"(() => {{ {code} }})()")


def top(ch, hid):
    return js(ch, f"const h = document.getElementById({hid!r}); return h ? Math.round(h.getBoundingClientRect().top) : null")


def current(ch):
    return js(ch, "const a = document.querySelector('#seclist a[aria-current]'); return a ? a.textContent.replace(/ \\(\\d+\\)$/, '') : null")


def in_view(y):
    return y is not None and 0 <= y < 420


@SUITE.test("a_section_token_opens_on_that_section_with_focus_on_its_heading")
def _(t: T):
    for token, hid, strip in (("quality", "h-bugs", "Quality"), ("cycles", "h-cycles", "Cycles"), ("ai-adoption", "h-ai", "Efficiency"), ("needs-attention", "h-attn", "Needs Attention")):
        ch = load(token)
        y = top(ch, hid)
        t.check(in_view(y) or token == "needs-attention", f"#{token}: the heading is at {y}, not in view")
        t.check(js(ch, f"return document.activeElement && document.activeElement.id") == hid, f"#{token}: focus is on {js(ch, 'return document.activeElement && document.activeElement.id')!r}")
        t.check(current(ch) in (strip, "AI Adoption") if token == "ai-adoption" else current(ch) == strip, f"#{token}: the strip's current entry is {current(ch)!r}, expected {strip!r}")      # with the strip branch merged Efficiency stands for AI Adoption; before it the strip has its own entry
        t.check(js(ch, "return PRODUCT") == "cxone" and not ch.console_errors(), f"#{token}: product {js(ch, 'return PRODUCT')}, errors {ch.console_errors()[:2]}")


@SUITE.test("a_token_is_not_a_filter_state")
def _(t: T):
    ch = load("quality")
    t.check(js(ch, "return state.release === DATA.current && state.projects.size === projectsAll.length && state.teams.size === 0"), "a token changed the filters")
    ch = load("")
    t.check(in_view(top(ch, "h-bugs")) is False and js(ch, "return window.scrollY") < 5, "a link with no token did not open at the top")


@SUITE.test("a_product_token_opens_the_product_view_and_its_section")
def _(t: T):
    ch = load("prd1")
    t.check(js(ch, "return PRODUCT") == "PRD1" and js(ch, "return window.scrollY") < 5, f"#prd1 opened {js(ch, 'return PRODUCT')} at {js(ch, 'return window.scrollY')}")
    ch = load("prd1~quality")
    t.check(js(ch, "return PRODUCT") == "PRD1" and in_view(top(ch, "h-bugs")), f"#prd1~quality: product {js(ch, 'return PRODUCT')}, heading at {top(ch, 'h-bugs')}")
    ch = load("prd1~cycles")
    t.check(js(ch, "return PRODUCT") == "PRD1" and js(ch, "return window.scrollY") < 5, "a section the product view does not have moved the page")
    ch = load("cxone~quality")
    t.check(js(ch, "return PRODUCT") == "cxone" and in_view(top(ch, "h-bugs")), "#cxone~quality did not open CXone on Quality")
    for token in ("nope", "prd9~quality", "quality~prd1"):
        ch = load(token)
        t.check(js(ch, "return PRODUCT") == "cxone" and js(ch, "return window.scrollY") < 5 and not ch.console_errors(), f"#{token}: the page did not open as usual")


@SUITE.test("the_reader_taking_over_stops_the_corrections")
def _(t: T):
    ch = load("quality")
    ch.js("window.dispatchEvent(new Event('wheel')); window.scrollTo(0, 3000)")
    time.sleep(3.0)
    t.check(abs(js(ch, "return window.scrollY") - 3000) < 40, "the page pulled the reader back to the section after they scrolled")


@SUITE.test("the_heading_a_link_lands_on_has_no_focus_ring_until_the_reader_uses_the_keyboard")
def _(t: T):
    ch = load("quality")
    ring = lambda: js(ch, "const e = document.activeElement; const c = getComputedStyle(e); return {id: e.id, style: c.outlineStyle, width: c.outlineWidth}")
    r = ring()
    t.check(r["id"] == "h-bugs" and (r["style"] == "none" or r["width"] == "0px"), f"the landed heading shows a ring: {r}")
    ch.js("window.dispatchEvent(new KeyboardEvent('keydown', {key: 'Tab', bubbles: true}))")
    time.sleep(0.2)
    t.check(js(ch, "return document.documentElement.classList.contains('deeplanding')") is False, "the ring suppression stays after the reader pressed a key")


STUB_IO = """<script>window.claude = {use: () => Promise.resolve(null)};
/* the published page runs in a cross-origin frame, where the browser ignores rootMargin: a target counts as intersecting whenever any part of it is in the window */
window.IntersectionObserver = class { constructor(cb) { this.cb = cb; this.t = new Set(); window.addEventListener('scroll', () => this.fire(), {passive: true}); }
  observe(el) { this.t.add(el); setTimeout(() => this.fire(), 0); } disconnect() { this.t.clear(); } unobserve(el) { this.t.delete(el); }
  fire() { const vh = window.innerHeight; this.cb([...this.t].map(el => { const r = el.getBoundingClientRect(); return {target: el, isIntersecting: r.bottom > 0 && r.top < vh, boundingClientRect: r}; })); } };</script>"""


@SUITE.test("the_strip_marks_the_section_being_read_in_a_cross_origin_frame_too")
def _(t: T):
    ch = load("efficiency", runtime=True, prelude=STUB_IO)                # a link pins its section; the first key press releases the pin and the strip is read from the page
    ch.js("window.dispatchEvent(new KeyboardEvent('keydown', {key: 'a', bubbles: true}))"); time.sleep(0.6)
    t.check(js(ch, "return SEC.current()") == "h-eff" and js(ch, "const r = document.getElementById('h-eff').getBoundingClientRect(); return r.top >= 0 && r.top < window.innerHeight * 0.6"), f"after the key press the strip marks {js(ch, 'return SEC.current()')} while Efficiency is on screen")
    sections = ["h-attn", "h-burnup", "h-eff", "h-bugs", "h-deps"]
    for hid in sections[1:]:
        ch.js(f"window.scrollTo(0, landingY('{hid}') + 12)"); time.sleep(0.5)
        t.check(js(ch, "return SEC.current()") == hid, f"reading {hid}: the strip marks {js(ch, 'return SEC.current()')}")
    ch.js("window.scrollTo(0, 0)"); time.sleep(0.5)
    t.check(js(ch, "return SEC.top()") is True, f"at the top of the page the strip marks {js(ch, 'return SEC.current()')} instead of nothing")


@SUITE.test("a_click_on_the_strip_puts_the_section_in_the_address_at_once_and_there_is_no_copy_button")
def _(t: T):
    for token, clicks in (("", [("h-deps", "#dependencies"), ("h-bugs", "#quality"), ("h-attn", "#needs-attention")]),
                          ("prd1", [("h-bugs", "#prd1~quality"), ("h-deps", "#prd1~dependencies")])):
        ch = load(token, runtime=True)
        t.check(js(ch, "return !document.getElementById('sec-copy') && !document.querySelector('.seclink')"), f"#{token}: the copy-link button is still on the strip")
        for hid, want in clicks:
            ch.js(f"document.querySelector('#seclist a[data-jump=\"{hid}\"]').click()")
            time.sleep(0.15)                                                         # no waiting for the scroll to settle
            t.check(js(ch, "return location.hash") == want, f"#{token}: after clicking {hid} the address is {js(ch, 'return location.hash')!r}, expected {want!r}")
    ch = load("", runtime=True)
    ch.js("document.querySelector('#seclist a[data-jump=\"h-eff\"]').focus(); document.activeElement.dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowDown', altKey: true, bubbles: true}))")
    time.sleep(0.15)
    t.check(js(ch, "return location.hash") not in ("", "#"), f"Alt + Down left the address as it was: {js(ch, 'return location.hash')!r}")


if __name__ == "__main__":
    sys.exit(kit.cli(SUITE, __doc__))
