"""Style E: readiness. One stacked bar per team: ready / partly planned / not started."""
from __future__ import annotations

from _segmented import *  # noqa: F401,F403
from _segmented import html

READY, PART, NONE = "#2E8B57", "#E0A030", "#D9534F"


def bucket(es: list[dict]):
    full = [e for e in es if e["full"]]
    none = [e for e in es if not e["full"] and sum(e["ok"].values()) == 0]
    part = [e for e in es if not e["full"] and sum(e["ok"].values()) > 0]
    return full, part, none


def row(name: str, es: list[dict], team: bool, italic: bool = False) -> str:
    full, part, none = bucket(es)
    pct = round(100 * len(full) / len(es)) if es else 0
    bar = seg_bar([(len(full), READY), (len(part), PART), (len(none), NONE)])
    bg = f' bgcolor="{TEAMBG}" style="background:{TEAMBG};"' if team else ""
    cells = (name_td(name, team, italic).replace("<td ", "<td ", 1)
             + f'<td style="padding:10px 10px;">{bar}</td>'
             + count_td(full, "#1B6B3A", team) + count_td(part, "#8A5300", team) + count_td(none, "#B3261E", team)
             + f'<td align="right" style="padding:9px 8px;font-family:{FONT};font-size:13px;font-weight:{"700" if team else "400"};'
               f'color:{NAVY};font-variant-numeric:tabular-nums;">{pct}%</td>')
    return f"<tr{bg}>{cells}</tr>"


def render(cfg: dict, epics: list[dict], scope_team: str | None) -> str:
    epics, teams = scope(cfg, epics, scope_team)
    full, part, none = bucket(epics)
    head = ("<tr>" + th("Epic team / pod", "left", "37%") + th("", "center", "21%") + th("Ready", "center", "10%") + th("Partly", "center", "10%") + th("Not started", "center", "12%") + th("% ready", "right", "10%") + "</tr>")
    rows = [head]
    for t in teams:
        es = [e for e in epics if t in e["teams"]]
        rows.append(row(t, es, True))
        rt = team_rows(epics, t)
        if not all(r["name"] == UNASSIGNED_POD for r in rt):
            for r in rt:
                rows.append(row(r["name"], r["es"], False, r["name"] == UNASSIGNED_POD))
    summary = (f'<div style="font-size:14px;line-height:22px;color:{SUBTLE};">'
               f'<b style="color:{INK};">{keys_link(full, str(len(full)), "#1B6B3A")}</b> of '
               f'<b style="color:{INK};">{keys_link(epics, str(len(epics)), LINK)}</b> epics are ready &nbsp;&middot;&nbsp; '
               f'<b style="color:{INK};">{keys_link(part, str(len(part)), "#8A5300")}</b> partly planned &nbsp;&middot;&nbsp; '
               f'<b style="color:{INK};">{keys_link(none, str(len(none)), "#B3261E")}</b> not started</div>')
    key = legend([("Ready: all four fields filled", READY), ("Partly planned", PART), ("Not started: none filled", NONE)])
    body = (f'{summary}{gap(10)}{key}{gap(12)}'
            + grid(rows))
    if scope_team:
        body += todo_table(epics)
    return shell(title_for(cfg, scope_team), body)
