"""Style A: the original release planning layout (first version sent)."""
from __future__ import annotations

from model import *  # noqa: F401,F403
from model import html, quote, date

GREEN, AMBER, RED = "#1e7a3c", "#b25e00", "#c0392b"
GREEN_BG, AMBER_BG, RED_BG = "#e3f4e8", "#fdf0d9", "#fbe4e1"
MUTED, BORDER, ROWBG = "#6b6b6b", "#e2e2e2", "#f4f4f2"

# ---------------------------------------------------------------- html

def tone(p: int) -> tuple[str, str]:
    return (GREEN, GREEN_BG) if p >= 90 else (AMBER, AMBER_BG) if p >= 60 else (RED, RED_BG)


def jira_link(base: str, keys: list[str], text: str, color: str) -> str:
    """Link that opens exactly these epics in Jira's issue navigator."""
    if not keys:
        return text
    jql = f'key in ({",".join(keys)}) ORDER BY key'
    return (f'<a href="{base}/issues/?jql={quote(jql)}" style="color:{color};'
            f'text-decoration:underline;">{text}</a>')


def cell(p: int | None, missing: list[dict] | None = None, bold=False) -> str:
    """A % cell; when epics are missing the criterion the % links to exactly those epics."""
    if p is None:
        return f'<td style="padding:6px 8px;color:{MUTED};text-align:center;">&mdash;</td>'
    fg, _ = tone(p)
    w = "font-weight:bold;" if bold else ""
    txt = f"{p}%"
    if missing:
        txt = jira_link(missing[0]["base"], [e["key"] for e in missing], txt, fg)
    return f'<td style="padding:6px 8px;color:{fg};text-align:center;{w}">{txt}</td>'


def full_cell(p: int, n_full: int, n: int, todo: list[dict] | None = None) -> str:
    fg, bg = tone(p)
    txt = f"{p}%"
    if todo:
        txt = jira_link(todo[0]["base"], [e["key"] for e in todo], txt, fg)
    return (f'<td bgcolor="{bg}" style="padding:6px 8px;text-align:center;font-weight:bold;'
            f'color:{fg};background:{bg};">{txt}<span style="font-weight:normal;font-size:11px;">'
            f' ({n_full}/{n})</span></td>')


def count_cell(es: list[dict]) -> str:
    n = len(es)
    return (f'<td style="padding:6px 8px;text-align:center;">'
            f'{jira_link(es[0]["base"], [e["key"] for e in es], str(n), "#0b5fb3")}</td>')


def row_cells(es: list[dict], s: dict, bold: bool, pod_override=None) -> str:
    miss = lambda k: [e for e in es if not e["ok"][k]]
    out = count_cell(es)
    for k, _ in CRITERIA:
        out += pod_override if (k == "pod" and pod_override is not None) else cell(s[k], miss(k), bold)
    return out + full_cell(s["full"], s["full_n"], s["n"], [e for e in es if not e["full"]])


def kpi(label: str, value: str, es: list[dict] | None = None, color: str = "#222") -> str:
    """Summary tile; the number links to the epics it counts."""
    if es:
        value = jira_link(es[0]["base"], [e["key"] for e in es], value, color)
    return (f'<td style="padding:10px 14px;background:{ROWBG};border-right:6px solid #fff;" width="25%">'
            f'<div style="font-size:12px;color:{MUTED};">{label}</div>'
            f'<div style="font-size:24px;font-weight:bold;color:{color};">{value}</div></td>')


def table(epics: list[dict], teams: list[str], with_pods: bool) -> str:
    head = "".join(f'<th style="padding:6px 8px;text-align:center;font-weight:normal;color:{MUTED};">{h}</th>'
                   for h in ["Epics", *[c[1] for c in CRITERIA], "All 4 filled"])
    band = (f'<tr><td></td><td></td><td colspan="4" align="center" style="padding:4px 8px;font-size:12px;'
            f'color:{MUTED};border-bottom:2px solid {BORDER};">% of epics with a value filled in</td>'
            f'<td align="center" style="padding:4px 8px;font-size:12px;color:{MUTED};'
            f'border-bottom:2px solid {BORDER};">% with all four</td></tr>')
    rows = [band, f'<tr style="border-bottom:1px solid {BORDER};"><th style="padding:6px 8px;text-align:left;'
            f'font-weight:normal;color:{MUTED};">Epic team / pod</th>{head}</tr>']
    ts = sorted(teams, key=lambda t: (t == NO_TEAM, t.lower()))
    for t in ts:
        es = [e for e in epics if t in e["teams"]]
        rows.append(f'<tr bgcolor="{ROWBG}" style="background:{ROWBG};font-weight:bold;">'
                    f'<td style="padding:8px;">{html.escape(t)}</td>' + row_cells(es, stats(es), True) + "</tr>")
        if with_pods:
            rows_t = team_rows(epics, t)
            if all(r["name"] == UNASSIGNED_POD for r in rows_t):
                rows_t = []   # no real pods yet: the team row already says so
            for r in rows_t:
                unassigned = r["name"] == UNASSIGNED_POD
                pod_cell = cell(r["pod"], [e for e in r["es"] if not e["ok"]["pod"]]) if unassigned else cell(None)
                rows.append(f'<tr style="border-bottom:1px solid {BORDER};">'
                            f'<td style="padding:5px 8px 5px 22px;color:{MUTED};">{html.escape(r["name"])}</td>'
                            + row_cells(r["es"], r, False, pod_cell) + "</tr>")
    return ('<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;'
            f'font-size:13px;">{"".join(rows)}</table>')


def missing_chips(e: dict) -> str:
    labels = {"commitment": "no commitment type", "points": "no story points", "pod": "no pod",
              "sprint": "stale sprint" if e["stale_sprint"] else "no target sprint"}
    return " &middot; ".join(f'<span style="color:{RED};">{labels[k]}</span>'
                             for k, _ in CRITERIA if not e["ok"][k])


def action_list(epics: list[dict], team: str) -> str:
    todo = [e for e in epics if team in e["teams"] and not e["full"]]
    if not todo:
        return f'<p style="color:{GREEN};font-weight:bold;">Every epic is fully planned.</p>'
    todo.sort(key=lambda e: (sum(e["ok"].values()), e["key"]))
    rows = "".join(
        f'<tr style="border-bottom:1px solid {BORDER};"><td style="padding:5px 8px;white-space:nowrap;">'
        f'<a href="{e["url"]}" style="color:#0b5fb3;">{e["key"]}</a></td>'
        f'<td style="padding:5px 8px;">{html.escape(e["summary"][:90])}</td>'
        f'<td style="padding:5px 8px;font-size:12px;">{missing_chips(e)}</td></tr>' for e in todo)
    return (f'<p style="margin:18px 0 6px;font-weight:bold;">{len(todo)} epic(s) still to plan</p>'
            f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;font-size:13px;">{rows}</table>')


def render(cfg: dict, epics: list[dict], scope_team: str | None) -> str:
    teams = sorted({t for e in epics for t in e["teams"]})
    if scope_team:
        epics = [e for e in epics if scope_team in e["teams"]]
        teams = [scope_team]
    s = stats(epics)
    ms = {m: sum(1 for e in epics if e["milestone"] == m) for m in cfg["milestones"]}
    fg, _ = tone(s["full"])
    title = f'{cfg["project"]} &middot; Release {cfg["release"]} planning status'
    if scope_team:
        title += f' &middot; {html.escape(scope_team)}'
    m1, m2 = cfg["milestones"]
    in_ms = lambda m: [e for e in epics if e["milestone"] == m]
    kp = (kpi("Epics", str(s["n"]), epics) +
          kpi("All 4 filled", f'{s["full"]}%', [e for e in epics if not e["full"]], fg) +
          kpi(m1.capitalize(), str(ms[m1]), in_ms(m1)) + kpi(m2.capitalize(), str(ms[m2]), in_ms(m2)))
    body = (f'<div style="font-family:Segoe UI,Arial,sans-serif;color:#222;max-width:760px;">'
            f'<div style="font-size:20px;font-weight:bold;">{title}</div>'
            f'<div style="margin:0 0 14px;"></div>'
            f'<table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:16px;"><tr>{kp}</tr></table>'
            f'{table(epics, teams, True)}')
    if scope_team:
        body += action_list(epics, scope_team)
    return body + "</div>"
