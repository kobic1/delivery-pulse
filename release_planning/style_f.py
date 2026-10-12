"""Style F: milestones. Where each team's epics sit: 1st milestone, 2nd milestone, or not scheduled yet."""
from __future__ import annotations

from _segmented import *  # noqa: F401,F403
from _segmented import html

M1C, M2C, UNC = "#1F3A5F", "#5B9BD5", "#C9CDD3"


def split(es: list[dict], m1: str, m2: str):
    a = [e for e in es if e["milestone"] == m1]
    b = [e for e in es if e["milestone"] == m2]
    c = [e for e in es if e["milestone"] not in (m1, m2)]
    return a, b, c


def row(name: str, es: list[dict], team: bool, m1: str, m2: str, italic: bool = False) -> str:
    a, b, c = split(es, m1, m2)
    s = stats(es)
    bar = seg_bar([(len(a), M1C), (len(b), M2C), (len(c), UNC)])
    bg = f' bgcolor="{TEAMBG}" style="background:{TEAMBG};"' if team else ""
    full = keys_link([e for e in es if not e["full"]], f'{s["full"]}%', NAVY)
    cells = (name_td(name, team, italic)
             + f'<td style="padding:10px 10px;">{bar}</td>'
             + count_td(a, NAVY, team) + count_td(b, "#2F6FA8", team) + count_td(c, "#5F6368", team)
             + f'<td align="right" style="padding:9px 8px;font-family:{FONT};font-size:13px;font-weight:{"700" if team else "400"};'
               f'color:{NAVY};font-variant-numeric:tabular-nums;">{full}</td>')
    return f"<tr{bg}>{cells}</tr>"


def render(cfg: dict, epics: list[dict], scope_team: str | None) -> str:
    epics, teams = scope(cfg, epics, scope_team)
    m1, m2 = cfg["milestones"]
    a, b, c = split(epics, m1, m2)
    head = ("<tr>" + th("Epic team / pod", "left", "37%") + th("", "center", "25%") + th("1st", "center", "9%") + th("2nd", "center", "9%")
            + th("Not set", "center", "10%") + th("All 4 filled", "right", "10%") + "</tr>")
    rows = [head]
    for t in teams:
        es = [e for e in epics if t in e["teams"]]
        rows.append(row(t, es, True, m1, m2))
        rt = team_rows(epics, t)
        if not all(r["name"] == UNASSIGNED_POD for r in rt):
            for r in rt:
                rows.append(row(r["name"], r["es"], False, m1, m2, r["name"] == UNASSIGNED_POD))
    summary = (f'<div style="font-size:14px;line-height:22px;color:{SUBTLE};">'
               f'<b style="color:{INK};">{keys_link(a, str(len(a)), NAVY)}</b> epics in the {m1} &nbsp;&middot;&nbsp; '
               f'<b style="color:{INK};">{keys_link(b, str(len(b)), "#2F6FA8")}</b> in the {m2} &nbsp;&middot;&nbsp; '
               f'<b style="color:{INK};">{keys_link(c, str(len(c)), "#5F6368")}</b> not scheduled yet, of '
               f'<b style="color:{INK};">{keys_link(epics, str(len(epics)), LINK)}</b></div>')
    key = legend([(m1.capitalize(), M1C), (m2.capitalize(), M2C), ("Not scheduled: no Target sprint or an old one", UNC)])
    body = (f'{summary}{gap(10)}{key}{gap(12)}'
            + grid(rows))
    if scope_team:
        body += todo_table(epics)
    return shell(title_for(cfg, scope_team), body)
