"""Style C: heat map. Cells are filled by completeness so gaps jump out; very compact."""
from __future__ import annotations

from model import *  # noqa: F401,F403
from model import html, quote, date

FONT = "'Segoe UI',Inter,Arial,sans-serif"
INK, SUBTLE, LINE, LINK = "#1A1A1A", "#5F6368", "#E4E4E7", "#0B5FB3"
# completeness steps: (upper bound inclusive, fill, text)
STEPS = [(24, "#F4B8B0", "#6B1A12"), (49, "#F8D3AE", "#6A3A00"), (74, "#FBE9A8", "#5A4700"),
         (99, "#D3E8C4", "#1F4D12"), (100, "#B5DDBF", "#0F4A22")]


def shade(p: int) -> tuple[str, str]:
    return next((f, t) for ub, f, t in STEPS if p <= ub)


def heat(p: int | None, missing: list[dict] | None = None, bold=False, w: str = "") -> str:
    if p is None:
        return f'<td align="center" bgcolor="#F4F4F5" style="background:#F4F4F5;border:2px solid #fff;font-family:{FONT};font-size:12px;color:#9AA0A6;{w}">&ndash;</td>'
    fill, txt = shade(p)
    label = keys_link(missing or [], f"{p}%", txt)
    wt = "700" if bold else "500"
    return (f'<td align="center" bgcolor="{fill}" style="background:{fill};border:2px solid #fff;padding:7px 4px;'
            f'font-family:{FONT};font-size:13px;font-weight:{wt};color:{txt};font-variant-numeric:tabular-nums;{w}">{label}</td>')


def row(name_html: str, es: list[dict], s: dict, pod_cell: str | None, team: bool) -> str:
    miss = lambda k: [e for e in es if not e["ok"][k]]
    ns = f"padding:7px 8px;font-family:{FONT};font-size:13px;"
    name = (f'<td style="{ns}font-weight:700;color:{INK};border-top:{"10px solid #fff" if team else "0"};">{name_html}</td>'
            if team else f'<td style="{ns}padding-left:22px;color:{SUBTLE};">{name_html}</td>')
    cnt = f'<td align="center" style="{ns}font-variant-numeric:tabular-nums;">{keys_link(es, str(len(es)), LINK)}</td>'
    cells = "".join(pod_cell if (k == "pod" and pod_cell is not None) else heat(s[k], miss(k), team)
                    for k, _ in CRITERIA)
    full = heat(s["full"], [e for e in es if not e["full"]], True)
    return f"<tr>{name}{cnt}{cells}{full}</tr>"


def legend() -> str:
    labels = ["0&ndash;24%", "25&ndash;49%", "50&ndash;74%", "75&ndash;99%", "100%"]
    cells = "".join(f'<td bgcolor="{f}" align="center" style="background:{f};border:2px solid #fff;padding:3px 8px;'
                    f'font-family:{FONT};font-size:11px;color:{t};">{l}</td>' for (_, f, t), l in zip(STEPS, labels))
    return (f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin-top:12px;"><tr>'
            f'<td style="font-family:{FONT};font-size:11px;color:{SUBTLE};padding-right:8px;">Share of epics filled in</td>{cells}</tr></table>')


def render(cfg: dict, epics: list[dict], scope_team: str | None) -> str:
    teams = sorted({t for e in epics for t in e["teams"]})
    if scope_team:
        epics = [e for e in epics if scope_team in e["teams"]]
        teams = [scope_team]
    s = stats(epics)
    m1, m2 = cfg["milestones"]
    in_ms = lambda m: [e for e in epics if e["milestone"] == m]
    head_cell = (f"padding:6px 4px;font-family:{FONT};font-size:11px;font-weight:600;color:{SUBTLE};"
                 f"text-transform:uppercase;letter-spacing:0.04em;")
    heads = "".join(f'<td align="center" style="{head_cell}">{h}</td>'
                    for h in ["Epics", *[c[1] for c in CRITERIA], "All 4 filled"])
    rows = [f'<tr><td style="{head_cell}" align="left">Epic team / pod</td>{heads}</tr>']
    for t in sorted(teams, key=lambda t: (t == NO_TEAM, t.lower())):
        es = [e for e in epics if t in e["teams"]]
        rows.append(row(html.escape(t), es, stats(es), None, True))
        rows_t = team_rows(epics, t)
        if not all(r["name"] == UNASSIGNED_POD for r in rows_t):
            for r in rows_t:
                un = r["name"] == UNASSIGNED_POD
                pc = heat(r["pod"], [e for e in r["es"] if not e["ok"]["pod"]]) if un else heat(None)
                nm = f"<i>{html.escape(r['name'])}</i>" if un else html.escape(r["name"])
                rows.append(row(nm, r["es"], r, pc, False))
    sub = f' &middot; {html.escape(scope_team)}' if scope_team else ""
    line = (f'{keys_link(epics, str(s["n"]), INK)} epics &nbsp;&middot;&nbsp; '
            f'{keys_link([e for e in epics if not e["full"]], str(s["full"]) + "%", INK)} have all four filled &nbsp;&middot;&nbsp; '
            f'{keys_link(in_ms(m1), str(len(in_ms(m1))), INK)} in the {m1} &nbsp;&middot;&nbsp; '
            f'{keys_link(in_ms(m2), str(len(in_ms(m2))), INK)} in the {m2}')
    body = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="#FFFFFF" style="background:#FFFFFF;">'
            f'<tr><td align="center" style="padding:20px 12px;"><table role="presentation" width="720" cellpadding="0" '
            f'cellspacing="0" style="width:100%;max-width:720px;"><tr><td style="font-family:{FONT};color:{INK};">'
            f'<div style="font-size:22px;line-height:28px;font-weight:700;">{cfg["project"]} &middot; Release {cfg["release"]} planning{sub}</div>'
            f'<div style="font-size:14px;line-height:22px;color:{SUBTLE};padding:6px 0 16px;">{line}</div>'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:separate;">{"".join(rows)}</table>'
            f'{legend()}')
    if scope_team:
        todo = [e for e in epics if not e["full"]]
        names = {"commitment": "Commitment type", "points": "Story points", "pod": "Pod label", "sprint": "Target sprint"}
        if todo:
            items = ""
            for e in sorted(todo, key=lambda e: (sum(e["ok"].values()), e["key"])):
                miss = ", ".join(("Stale sprint" if (k == "sprint" and e["stale_sprint"]) else names[k])
                                 for k, _ in CRITERIA if not e["ok"][k])
                items += (f'<tr><td style="padding:6px 8px;font-family:{FONT};font-size:13px;white-space:nowrap;'
                          f'border-bottom:1px solid {LINE};"><a href="{e["url"]}" style="color:{LINK};">{e["key"]}</a></td>'
                          f'<td style="padding:6px 8px;font-family:{FONT};font-size:13px;border-bottom:1px solid {LINE};">'
                          f'{html.escape(e["summary"][:80])}</td><td style="padding:6px 8px;font-family:{FONT};font-size:12px;'
                          f'color:#8C2A1F;border-bottom:1px solid {LINE};">{miss}</td></tr>')
            body += (f'<div style="font-family:{FONT};font-size:15px;font-weight:700;padding:28px 0 8px;">'
                     f'{len(todo)} epic(s) to complete</div><table role="presentation" width="100%" cellpadding="0" '
                     f'cellspacing="0" style="border-collapse:collapse;">{items}</table>')
        else:
            body += f'<p style="font-family:{FONT};font-size:14px;font-weight:700;color:#0F4A22;">Every epic is fully planned.</p>'
    return body + "</td></tr></table></td></tr></table>"
