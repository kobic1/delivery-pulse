"""Style B: restyled to match the release-status dashboard emails."""
from __future__ import annotations

from model import *  # noqa: F401,F403
from model import html, quote, date

# ---------------------------------------------------------------- html
# Visual language matches the release-status dashboard emails: Segoe UI, #FAFAFA page,
# navy numerals, #E4E4E7 hairlines. Outlook-safe: tables, inline styles, bgcolor attributes,
# no flex/grid/CSS variables.

FONT = "'Segoe UI',Inter,Arial,sans-serif"
INK, NAVY, SUBTLE, LINE, PAGE, CARD, TEAMBG, LINK = "#1A1A1A", "#1F3A5F", "#5F6368", "#E4E4E7", "#FAFAFA", "#FFFFFF", "#F1F4F8", "#0B5FB3"
GOOD, WARN, BAD = "#1B6B3A", "#8A5300", "#B3261E"
GOOD_BG, WARN_BG, BAD_BG = "#E6F4EA", "#FDF1DC", "#FBE7E5"
TRACK = "#E4E4E7"


def tone(p: int) -> tuple[str, str]:
    return (GOOD, GOOD_BG) if p >= 90 else (WARN, WARN_BG) if p >= 60 else (BAD, BAD_BG)


def jira_link(base: str, keys: list[str], text: str, color: str) -> str:
    """Link that opens exactly these epics in Jira's issue navigator."""
    if not keys:
        return text
    jql = f'key in ({",".join(keys)}) ORDER BY key'
    return (f'<a href="{base}/issues/?jql={quote(jql)}" style="color:{color};'
            f'text-decoration:underline;">{text}</a>')


def keys_link(es: list[dict], text: str, color: str) -> str:
    return jira_link(es[0]["base"], [e["key"] for e in es], text, color) if es else text


TD = f"padding:9px 10px;font-family:{FONT};font-size:13px;"
NUM = "font-variant-numeric:tabular-nums;"


def cell(p: int | None, missing: list[dict] | None = None, bold=False) -> str:
    """A % cell; when epics are missing the criterion the % links to exactly those epics."""
    if p is None:
        return f'<td align="center" style="{TD}color:#9AA0A6;">&ndash;</td>'
    fg, _ = tone(p)
    txt = keys_link(missing or [], f"{p}%", fg)
    w = "font-weight:600;" if bold else ""
    return f'<td align="center" style="{TD}{NUM}color:{fg};{w}">{txt}</td>'


def full_cell(p: int, n_full: int, n: int, todo: list[dict] | None = None) -> str:
    fg, _ = tone(p)
    txt = keys_link(todo or [], f"{p}%", fg)
    fill = max(p, 3)          # keep a visible sliver so 0% still reads as a bar
    bar = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:5px;">'
           f'<tr><td width="{fill}%" height="4" bgcolor="{fg}" style="height:4px;line-height:4px;font-size:0;">&nbsp;</td>'
           f'<td height="4" bgcolor="{TRACK}" style="height:4px;line-height:4px;font-size:0;">&nbsp;</td></tr></table>')
    return (f'<td align="center" width="17%" style="{TD}{NUM}"><span style="color:{fg};font-weight:600;">{txt}</span>'
            f'<span style="color:{SUBTLE};font-size:11px;"> {n_full}/{n}</span>{bar}</td>')


def count_cell(es: list[dict]) -> str:
    return f'<td align="center" style="{TD}{NUM}">{keys_link(es, str(len(es)), LINK)}</td>'


def row_cells(es: list[dict], s: dict, bold: bool, pod_override=None) -> str:
    miss = lambda k: [e for e in es if not e["ok"][k]]
    out = count_cell(es)
    for k, _ in CRITERIA:
        out += pod_override if (k == "pod" and pod_override is not None) else cell(s[k], miss(k), bold)
    return out + full_cell(s["full"], s["full_n"], s["n"], [e for e in es if not e["full"]])


def summary_strip(items: list[tuple[str, str, str]]) -> str:
    """One quiet strip of figures divided by hairlines: (label, value html, color)."""
    n = len(items)
    cells = ""
    for i, (label, value, color) in enumerate(items):
        div = f"border-left:1px solid {LINE};" if i else ""
        cells += (f'<td width="{100 // n}%" valign="top" style="padding:14px 18px;{div}font-family:{FONT};">'
                  f'<div style="font-size:24px;line-height:28px;font-weight:600;color:{color};{NUM}">{value}</div>'
                  f'<div style="font-size:12px;line-height:16px;color:{SUBTLE};padding-top:2px;">{label}</div></td>')
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="{CARD}" '
            f'style="background:{CARD};border:1px solid {LINE};border-radius:8px;border-collapse:separate;"><tr>{cells}</tr></table>')


def table(epics: list[dict], teams: list[str], with_pods: bool) -> str:
    th = f"padding:8px 10px;font-family:{FONT};font-size:11px;font-weight:600;color:{SUBTLE};text-transform:uppercase;letter-spacing:0.04em;"
    band = (f'<tr><td></td><td></td><td colspan="4" align="center" style="padding:10px 10px 2px;font-family:{FONT};'
            f'font-size:12px;color:{SUBTLE};">% of epics with a value filled in</td>'
            f'<td align="center" style="padding:10px 10px 2px;font-family:{FONT};font-size:12px;color:{SUBTLE};">% with all four</td></tr>')
    head = (f'<tr><td style="{th}border-bottom:1px solid {LINE};" align="left">Epic team / pod</td>'
            + "".join(f'<td align="center" style="{th}border-bottom:1px solid {LINE};">{h}</td>'
                      for h in ["Epics", *[c[1] for c in CRITERIA], "All 4 filled"]) + '</tr>')
    rows = [band, head]
    for t in sorted(teams, key=lambda t: (t == NO_TEAM, t.lower())):
        es = [e for e in epics if t in e["teams"]]
        rows.append(f'<tr bgcolor="{TEAMBG}" style="background:{TEAMBG};"><td style="{TD}font-weight:600;color:{NAVY};">'
                    f'{html.escape(t)}</td>' + row_cells(es, stats(es), True) + "</tr>")
        if with_pods:
            rows_t = team_rows(epics, t)
            if all(r["name"] == UNASSIGNED_POD for r in rows_t):
                rows_t = []   # no real pods yet: the team row already says so
            for r in rows_t:
                unassigned = r["name"] == UNASSIGNED_POD
                pod_cell = cell(r["pod"], [e for e in r["es"] if not e["ok"]["pod"]]) if unassigned else cell(None)
                name_style = f"color:{SUBTLE};font-style:italic;" if unassigned else f"color:{INK};"
                rows.append(f'<tr><td style="{TD}padding-left:26px;{name_style}border-bottom:1px solid {LINE};">'
                            f'{html.escape(r["name"])}</td>'
                            + row_cells(r["es"], r, False, pod_cell).replace(
                                f'style="{TD}', f'style="{TD}border-bottom:1px solid {LINE};') + "</tr>")
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="{CARD}" '
            f'style="background:{CARD};border:1px solid {LINE};border-radius:8px;border-collapse:separate;">'
            f'<tr><td style="padding:6px 8px 10px;"><table role="presentation" width="100%" cellpadding="0" '
            f'cellspacing="0" style="border-collapse:collapse;">{"".join(rows)}</table></td></tr></table>')


def action_list(epics: list[dict], team: str) -> str:
    todo = [e for e in epics if team in e["teams"] and not e["full"]]
    if not todo:
        return f'<p style="font-family:{FONT};font-size:14px;color:{GOOD};font-weight:600;">Every epic is fully planned.</p>'
    todo.sort(key=lambda e: (sum(e["ok"].values()), e["key"]))
    th = f"padding:8px 8px;font-family:{FONT};font-size:11px;font-weight:600;color:{SUBTLE};text-transform:uppercase;letter-spacing:0.04em;border-bottom:1px solid {LINE};"
    names = {"commitment": "Commitment type", "points": "Story points", "pod": "Pod label", "sprint": "Target sprint"}
    head = (f'<tr><td style="{th}" align="left">Epic</td><td style="{th}" align="left">Title</td>'
            + "".join(f'<td align="center" style="{th}">{names[k]}</td>' for k, _ in CRITERIA) + "</tr>")
    body = ""
    for e in todo:
        marks = ""
        for k, _ in CRITERIA:
            if e["ok"][k]:
                marks += f'<td align="center" style="{TD}color:#B0B5BA;border-bottom:1px solid {LINE};">&ndash;</td>'
            else:
                word = "Stale" if (k == "sprint" and e["stale_sprint"]) else "Missing"
                marks += (f'<td align="center" style="{TD}font-size:12px;font-weight:500;color:{BAD};'
                          f'border-bottom:1px solid {LINE};">{word}</td>')
        body += (f'<tr><td style="{TD}white-space:nowrap;border-bottom:1px solid {LINE};">'
                 f'<a href="{e["url"]}" style="color:{LINK};text-decoration:underline;">{e["key"]}</a></td>'
                 f'<td style="{TD}color:{INK};border-bottom:1px solid {LINE};">{html.escape(e["summary"][:90])}</td>{marks}</tr>')
    return (f'<div style="font-family:{FONT};font-size:15px;font-weight:600;color:{INK};padding:28px 0 10px;">'
            f'{len(todo)} epic(s) still to plan</div>'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="{CARD}" '
            f'style="background:{CARD};border:1px solid {LINE};border-radius:8px;border-collapse:separate;">'
            f'<tr><td style="padding:4px 8px 8px;"><table role="presentation" width="100%" cellpadding="0" '
            f'cellspacing="0" style="border-collapse:collapse;">{head}{body}</table></td></tr></table>')


def render(cfg: dict, epics: list[dict], scope_team: str | None) -> str:
    teams = sorted({t for e in epics for t in e["teams"]})
    if scope_team:
        epics = [e for e in epics if scope_team in e["teams"]]
        teams = [scope_team]
    s = stats(epics)
    m1, m2 = cfg["milestones"]
    in_ms = lambda m: [e for e in epics if e["milestone"] == m]
    fg, _ = tone(s["full"])
    title = f'{cfg["project"]} &middot; Release {cfg["release"]} planning status'
    sub = f'<div style="font-size:16px;color:{SUBTLE};padding-top:4px;">{html.escape(scope_team)}</div>' if scope_team else ""
    strip = summary_strip([
        ("Epics", keys_link(epics, str(s["n"]), NAVY), NAVY),
        ("All 4 filled", keys_link([e for e in epics if not e["full"]], f'{s["full"]}%', fg), fg),
        (m1.capitalize(), keys_link(in_ms(m1), str(len(in_ms(m1))), NAVY), NAVY),
        (m2.capitalize(), keys_link(in_ms(m2), str(len(in_ms(m2))), NAVY), NAVY),
    ])
    body = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="{PAGE}" style="background:{PAGE};">'
            f'<tr><td align="center" style="padding:24px 12px;"><table role="presentation" width="720" cellpadding="0" '
            f'cellspacing="0" style="width:100%;max-width:720px;"><tr><td style="font-family:{FONT};color:{INK};">'
            f'<div style="font-size:22px;line-height:28px;font-weight:600;color:{NAVY};">{title}</div>{sub}'
            f'<div style="height:16px;line-height:16px;font-size:0;">&nbsp;</div>{strip}'
            f'<div style="height:16px;line-height:16px;font-size:0;">&nbsp;</div>{table(epics, teams, True)}')
    if scope_team:
        body += action_list(epics, scope_team)
    return body + "</td></tr></table></td></tr></table>"
