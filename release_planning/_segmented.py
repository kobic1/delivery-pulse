"""Shared pieces for the segmented-bar styles (E, F). Outlook-safe: tables, inline styles, bgcolor."""
from __future__ import annotations

from model import *  # noqa: F401,F403
from model import html

FONT = "'Segoe UI',Inter,Arial,sans-serif"
INK, NAVY, SUBTLE, LINE, PAGE, CARD, LINK = "#1A1A1A", "#1F3A5F", "#5F6368", "#E4E4E7", "#FAFAFA", "#FFFFFF", "#0B5FB3"
TEAMBG = "#F1F4F8"
NAMES = {"commitment": "Commitment type", "points": "Story points", "pod": "Pod label", "sprint": "Target sprint"}


def gap(px: int) -> str:
    return f'<div style="height:{px}px;line-height:{px}px;font-size:0;">&nbsp;</div>'


def seg_bar(parts: list[tuple[int, str]], height: int = 14) -> str:
    """Horizontal stacked bar. parts = [(count, color)]; zero parts are skipped, tiny ones get a sliver."""
    total = sum(n for n, _ in parts) or 1
    live = [(n, c) for n, c in parts if n]
    if not live:
        live = [(1, "#E4E4E7")]
    pct = [max(round(100 * n / total), 3) for n, _ in live]
    cells = "".join(f'<td width="{p}%" height="{height}" bgcolor="{c}" style="height:{height}px;line-height:{height}px;'
                    f'font-size:0;border-right:1px solid #fff;">&nbsp;</td>' for p, (n, c) in zip(pct, live))
    return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>{cells}</tr></table>'


def legend(items: list[tuple[str, str]]) -> str:
    cells = "".join(f'<td width="10" height="10" bgcolor="{c}" style="font-size:0;line-height:10px;">&nbsp;</td>'
                    f'<td style="padding:0 16px 0 6px;font-family:{FONT};font-size:12px;color:{SUBTLE};">{l}</td>'
                    for l, c in items)
    return f'<table role="presentation" cellpadding="0" cellspacing="0"><tr>{cells}</tr></table>'


def count_td(es: list[dict], color: str = LINK, bold: bool = False) -> str:
    w = "700" if bold else "400"
    txt = keys_link(es, str(len(es)), color) if es else f'<span style="color:#B0B5BA;">0</span>'
    return (f'<td align="center" style="padding:9px 6px;font-family:{FONT};font-size:13px;font-weight:{w};'
            f'font-variant-numeric:tabular-nums;">{txt}</td>')


def shell(title_html: str, inner: str, bg: str = PAGE) -> str:
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="{bg}" style="background:{bg};">'
            f'<tr><td align="center" style="padding:24px 12px;"><table role="presentation" width="720" cellpadding="0" '
            f'cellspacing="0" style="width:100%;max-width:720px;"><tr><td style="font-family:{FONT};color:{INK};">'
            f'<div style="font-size:22px;line-height:28px;font-weight:700;color:{NAVY};">{title_html}</div>{gap(16)}{inner}'
            f'</td></tr></table></td></tr></table>')


def card(inner: str) -> str:
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="{CARD}" '
            f'style="background:{CARD};border:1px solid {LINE};border-radius:8px;border-collapse:separate;">'
            f'<tr><td style="padding:12px 16px;">{inner}</td></tr></table>')


def th(label: str, align: str = "center", width: str = "") -> str:
    w = f' width="{width}"' if width else ""
    return (f'<td align="{align}"{w} style="padding:8px 6px;font-family:{FONT};font-size:10px;font-weight:600;color:{SUBTLE};'
            f'text-transform:uppercase;letter-spacing:0.02em;border-bottom:1px solid {LINE};">{label}</td>')


def name_td(name: str, team: bool, italic: bool = False) -> str:
    if team:
        return (f'<td style="padding:10px 6px;font-family:{FONT};font-size:13px;font-weight:700;color:{NAVY};'
                f'background:{TEAMBG};">{html.escape(name)}</td>')
    nm = f"<i>{html.escape(name)}</i>" if italic else html.escape(name)
    return (f'<td style="padding:8px 6px 8px 22px;font-family:{FONT};font-size:13px;color:{SUBTLE};">{nm}</td>')


def grid(rows: list[str]) -> str:
    """Fixed-layout grid inside a card so the bar column keeps its width in every mail client."""
    return card('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
                f'style="border-collapse:collapse;table-layout:fixed;">{"".join(rows)}</table>')


def title_for(cfg: dict, scope_team: str | None) -> str:
    return (f'{cfg["project"]} &middot; Release {cfg["release"]} planning status'
            + (f' &middot; {html.escape(scope_team)}' if scope_team else ""))


def scope(cfg: dict, epics: list[dict], scope_team: str | None):
    teams = sorted({t for e in epics for t in e["teams"]}, key=lambda t: (t == NO_TEAM, t.lower()))
    if scope_team:
        return [e for e in epics if scope_team in e["teams"]], [scope_team]
    return epics, teams


def todo_table(epics: list[dict]) -> str:
    todo = [e for e in epics if not e["full"]]
    if not todo:
        return f'<p style="font-family:{FONT};font-size:14px;font-weight:700;color:#1B6B3A;">Every epic is fully planned.</p>'
    rows = ""
    for e in sorted(todo, key=lambda e: (sum(e["ok"].values()), e["key"])):
        miss = ", ".join(("Stale sprint" if (k == "sprint" and e["stale_sprint"]) else NAMES[k])
                         for k, _ in CRITERIA if not e["ok"][k])
        cs = f'padding:7px 8px;font-family:{FONT};font-size:13px;border-bottom:1px solid {LINE};'
        rows += (f'<tr><td style="{cs}white-space:nowrap;"><a href="{e["url"]}" style="color:{LINK};">{e["key"]}</a></td>'
                 f'<td style="{cs}">{html.escape(e["summary"][:80])}</td>'
                 f'<td style="{cs}font-size:12px;color:#B3261E;">Missing: {miss}</td></tr>')
    return (f'<div style="font-family:{FONT};font-size:15px;font-weight:700;padding:28px 0 8px;">{len(todo)} epic(s) to complete</div>'
            + card(f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">{rows}</table>'))
