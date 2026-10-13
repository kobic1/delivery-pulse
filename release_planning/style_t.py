"""Style T: paste into a Teams chat or channel. Uses only what Teams' sanitizer keeps:
bold/colored text, native tables, links. No backgrounds, borders, pills or fonts."""
from __future__ import annotations

from model import *  # noqa: F401,F403
from model import html

GOOD, WARN, BAD, LINK = "#1B6B3A", "#B25E00", "#C4262E", "#0B5FB3"
VERBS = {"commitment": "Set Commitment type on", "points": "Add Story points on",
         "pod": "Add a POD label on", "sprint": "Set Target sprint on"}


def tone(p: int) -> str:
    return GOOD if p >= 90 else WARN if p >= 60 else BAD


def pct(p: int | None, missing: list[dict] | None = None) -> str:
    if p is None:
        return "&ndash;"
    txt = '<b><span style="color:' + tone(p) + '">' + str(p) + "%</span></b>"
    return keys_link(missing or [], txt, tone(p), underline=False)


def bold(n) -> str:
    return "<b>" + str(n) + "</b>"


def row(name: str, es: list[dict], s: dict, team: bool, pod_cell: str | None = None) -> str:
    miss = lambda k: [e for e in es if not e["ok"][k]]
    nm = "<b>" + html.escape(name) + "</b>" if team else "&nbsp;&nbsp;&nbsp;&nbsp;" + html.escape(name)
    cells = ""
    for k, _ in CRITERIA:
        cells += "<td>" + (pod_cell if (k == "pod" and pod_cell is not None) else pct(s[k], miss(k))) + "</td>"
    not_full = [e for e in es if not e["full"]]
    return ("<tr><td>" + nm + "</td><td>" + keys_link(es, str(len(es)), LINK) + "</td>" + cells
            + "<td>" + pct(s["full"], not_full) + "</td></tr>")


def render(cfg: dict, epics: list[dict], scope_team: str | None) -> str:
    teams = sorted({t for e in epics for t in e["teams"]}, key=lambda t: (t == NO_TEAM, t.lower()))
    if scope_team:
        epics = [e for e in epics if scope_team in e["teams"]]
        teams = [scope_team]
    s = stats(epics)
    m1, m2 = cfg["milestones"]
    in_ms = lambda m: [e for e in epics if e["milestone"] == m]
    title = cfg["project"] + " &middot; Release " + cfg["release"] + " planning status"
    if scope_team:
        title += " &middot; " + html.escape(scope_team)
    summary = (keys_link(epics, bold(s["n"]), LINK) + " epics &nbsp;|&nbsp; "
               + pct(s["full"], [e for e in epics if not e["full"]]) + " have all four fields filled &nbsp;|&nbsp; "
               + keys_link(in_ms(m1), bold(len(in_ms(m1))), LINK) + " in the " + m1 + " &nbsp;|&nbsp; "
               + keys_link(in_ms(m2), bold(len(in_ms(m2))), LINK) + " in the " + m2)
    head = "".join("<th>" + h + "</th>" for h in ["Epic team / pod", "Epics", *[c[1] for c in CRITERIA], "All 4 filled"])
    rows = ["<tr>" + head + "</tr>"]
    for t in teams:
        es = [e for e in epics if t in e["teams"]]
        rows.append(row(t, es, stats(es), True))
        rt = team_rows(epics, t)
        if not all(r["name"] == UNASSIGNED_POD for r in rt):
            for r in rt:
                un = r["name"] == UNASSIGNED_POD
                pc = pct(r["pod"], [e for e in r["es"] if not e["ok"]["pod"]]) if un else "&ndash;"
                rows.append(row(r["name"], r["es"], r, False, pc))
    lines = []
    for k, _ in CRITERIA:
        miss = [e for e in epics if not e["ok"][k]]
        if miss:
            lines.append((len(miss), k, miss))
    lines.sort(key=lambda x: -x[0])
    items = ""
    for n, k, miss in lines:
        label = bold(str(n) + (" epic" if n == 1 else " epics"))
        items += "<li>" + VERBS[k] + " " + keys_link(miss, label, LINK) + "</li>"
    if items:
        todo_html = "<p><b>To do</b></p><ul>" + items + "</ul>"
    else:
        todo_html = '<p><b><span style="color:' + GOOD + '">Every epic is fully planned.</span></b></p>'
    return "<p><b>" + title + "</b></p><p>" + summary + "</p><table>" + "".join(rows) + "</table>" + todo_html
