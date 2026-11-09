#!/usr/bin/env python3
"""The CXCROSS section counts the Capabilities of other projects that sit under a CXCROSS Initiative, not only the Capabilities owned by CXCROSS.

Worked out here from the payload (fictitious data), never from the page's code: a Capability belongs to the section when its key is a CXCROSS key, or when its parent is a CXCROSS Initiative that is not Removed.
The fixture is extended with Capabilities of PMN, CXWFM and CXSUP so that every case is there:
  * a PMN Capability under a live CXCROSS Initiative            -> in the section, with its epics;
  * a CXWFM Capability under a Removed CXCROSS Initiative       -> not in it;
  * a PMN Capability under an Initiative of another project     -> not in it;
  * a CXSUP Capability the hierarchy does not know              -> not in it;
  * a CXCO Capability under a live CXCROSS Initiative with no epic -> not a row, but listed under "Capabilities with No Epics".
Rows, the 'Epics Under Them' tile, the link of each row and the none list are compared, for all projects and for PMN alone.

    python3 cx_check.py [--live] [--only NAME]
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kit                                                                          # noqa: E402
import make_synthetic as MS                                                         # noqa: E402
from kit import ctx, T                                                              # noqa: E402

SUITE = kit.Suite("Delivery Pulse CXCROSS section")
REL = "27.1"
NO_EPIC = "CXCO-98001"


def build():
    data = MS.make(MS.il_today())
    data["build"] = {"sha": "abc1234", "dirty": False, "at": "2026-01-01T00:00+02:00"}
    H = data["hier"]
    inis = sorted(k for k, r in H.items() if r["ty"] == "Initiative")
    live = next(k for k in inis if H[k]["s"] != "Removed")
    gone = next(k for k in inis if H[k]["s"] == "Removed")
    H["ZZINI-1"] = {"ty": "Initiative", "t": "another project initiative", "s": "In Progress", "fv": [REL], "p": "ZZINI"}
    pick = {}
    for proj in ("PMN", "CXWFM", "CXSUP"):                                          # a Capability of the project that holds epics of the release
        seen = {}
        for e in data["epics"]:
            c = e.get("cp")
            if c and not c.startswith("CXCROSS") and e["p"] == proj and REL in e["fv"]:
                seen.setdefault(c, 0)
                seen[c] += 1
        pick[proj] = sorted(seen, key=lambda c: (-seen[c], c))[:2]
    assert len(pick["PMN"]) == 2 and pick["CXWFM"] and pick["CXSUP"], pick
    rec = lambda c, par: {"ty": "Capability", "t": f"capability {c}", "s": "In Progress", "fv": [REL], "p": c.split("-")[0], **({"par": par} if par else {})}
    H[pick["PMN"][0]] = rec(pick["PMN"][0], live)                                  # under a live CXCROSS Initiative
    H[pick["CXWFM"][0]] = rec(pick["CXWFM"][0], gone)                              # under a Removed one
    H[pick["PMN"][1]] = rec(pick["PMN"][1], "ZZINI-1")                             # under an Initiative of another project
    H[NO_EPIC] = rec(NO_EPIC, live)                                                # ours, under a live Initiative, no epic anywhere
    data["_in"], data["_out"] = pick["PMN"][0], [pick["CXWFM"][0], pick["PMN"][1], pick["CXSUP"][0]]
    return data


def expected(data, projects):
    H = data["hier"]
    def ini_ok(c):
        p = (H.get(c) or {}).get("par")
        return bool(p and p in H and H[p]["s"] != "Removed" and p.startswith("CXCROSS"))
    is_cx = lambda c: bool(c) and (c.startswith("CXCROSS") or ini_ok(c))
    scope = [e for e in data["epics"] if e["p"] in projects and REL in e["fv"]]
    eps = [e for e in scope if is_cx(e.get("cp")) and (H.get(e["cp"]) or {}).get("s") != "Removed"]
    return {e["cp"] for e in eps}, len(eps)


READ = """(() => { const tx = e => e.textContent.replace(/\\s+/g, ' ').trim();
  const rows = [...document.querySelectorAll('#cx-body tbody tr > th > a')].map(a => a.getAttribute('href').split('/browse/')[1]).filter(Boolean);
  const tiles = {}; document.querySelectorAll('#cx-kpis .kpi').forEach(c => { const l = c.querySelector('.l'); tiles[tx(l)] = tx(c.querySelector('.v')); });
  return {rows: [...new Set(rows)], tiles, none: tx(document.getElementById('cx-none')), errors: 0}; })()"""


def load_page(data, hash_):
    ch = ctx.chrome
    ch.cmd("Emulation.setTimezoneOverride", timezoneId="Asia/Jerusalem")
    ch.viewport(1400, 900)
    url = ctx.write(kit.wrap(MS.render_page(data)), "cx")
    ch.goto(url + "#" + hash_)
    assert kit.wait_ready(ch), "the page did not draw: " + str(ch.console_errors()[:2])
    time.sleep(0.5)
    return ch


@SUITE.test("capabilities_of_other_projects_under_a_cxcross_initiative_are_counted_and_the_others_are_not")
def _(t: T):
    data = build()
    for hash_, projects in ((f"r={REL}", set(data["projects"])), (f"r={REL}&p=PMN", {"PMN"})):
        ch = load_page(data, hash_)
        r = ch.js(READ)
        want_rows, want_epics = expected(data, projects)
        rows = set(r["rows"])
        t.check(rows == want_rows, f"[{hash_}] the rows are {sorted(rows ^ want_rows)} different from the recount ({len(rows)} rows, expected {len(want_rows)})")
        t.check(r["tiles"].get("Epics Under Them") == f"{want_epics:,}", f"[{hash_}] Epics Under Them is {r['tiles'].get('Epics Under Them')}, the recount is {want_epics}")
        if "PMN" in projects:
            t.check(data["_in"] in rows, f"[{hash_}] the PMN Capability under a live CXCROSS Initiative is not a row")
        t.check(not any(c in rows for c in data["_out"]), f"[{hash_}] a Capability that is not under a live CXCROSS Initiative is a row: {[c for c in data['_out'] if c in rows]}")
        t.check(not ch.console_errors(), f"[{hash_}] console error: {ch.console_errors()[:2]}")
    ch = load_page(data, f"r={REL}")
    r = ch.js(READ)
    t.check(NO_EPIC in r["none"], f"our Capability under a CXCROSS Initiative with no epic is not in the none list: {r['none'][:200]!r}")


@SUITE.test("every_row_opens_the_epics_it_counts_in_jira")
def _(t: T):
    data = build()
    ch = load_page(data, f"r={REL}")
    cells = ch.js("""(() => [...document.querySelectorAll('#cx-body tbody tr')].map(tr => ({cap: (tr.querySelector('th a') || {}).getAttribute && tr.querySelector('th a').getAttribute('href').split('/browse/')[1],
      cells: [...tr.querySelectorAll('td a')].map(a => ({text: a.textContent.trim(), href: a.getAttribute('href') || ''}))})))()""")
    mine = next(r for r in cells if r["cap"] == data["_in"])
    got = sum(int(c["text"].split("/")[1]) for c in mine["cells"] if re.fullmatch(r"\d+/\d+", c["text"]))
    want = sum(1 for e in data["epics"] if e.get("cp") == data["_in"] and REL in e["fv"])
    t.check(got == want, f"the row of {data['_in']} counts {got} epics, the recount is {want}")
    t.check(all(f"parent%20%3D%20{data['_in']}" in c["href"] or f"parent = {data['_in']}" in c["href"] for c in mine["cells"] if re.fullmatch(r"\d+/\d+", c["text"])), "a cell of the row does not ask for the epics under the Capability")


@SUITE.test("selftest_the_check_fails_when_only_cxcross_owned_capabilities_count")
def _(t: T):
    import tempfile
    src = ctx.template.read_text(encoding="utf-8")
    old = "const all = scope.filter(e => isCxCap(H, e.cp)), removedCap"
    if src.count(old) != 1:
        raise kit.Skip("the seeding anchor is not in this template exactly once")
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(src.replace(old, 'const all = scope.filter(e => e.cp && e.cp.startsWith("CXCROSS")), removedCap'))
    data = build()
    ch = ctx.chrome
    ch.cmd("Emulation.setTimezoneOverride", timezoneId="Asia/Jerusalem")
    ch.viewport(1400, 900)
    url = ctx.write(kit.wrap(MS.render_page(data, Path(f.name))), "cxseed")
    Path(f.name).unlink()
    ch.goto(url + f"#r={REL}")
    kit.wait_ready(ch)
    time.sleep(0.5)
    r = ch.js(READ)
    t.check(data["_in"] not in r["rows"], "the seeded old rule still lists the Capability under a CXCROSS Initiative: the check is blind")


if __name__ == "__main__":
    sys.exit(kit.cli(SUITE, __doc__))
