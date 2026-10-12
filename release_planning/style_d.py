"""Style D: action-led. Leads with what to do (counts of epics missing each field), not a grid of percentages."""
from __future__ import annotations

from model import *  # noqa: F401,F403
from model import html, quote, date

FONT = "'Segoe UI',Inter,Arial,sans-serif"
INK, NAVY, SUBTLE, LINE, PAGE, CARD, LINK = "#1A1A1A", "#1F3A5F", "#5F6368", "#E4E4E7", "#F5F6F8", "#FFFFFF", "#0B5FB3"
GOOD, WARN, BAD = "#1B6B3A", "#8A5300", "#B3261E"
TRACK = "#E4E4E7"
NAMES = {"commitment": "Commitment type", "points": "Story points", "pod": "Pod label", "sprint": "Target sprint"}
VERBS = {"commitment": "Set Commitment type", "points": "Add Story points", "pod": "Add a POD label", "sprint": "Set Target sprint"}


def tone(p: int) -> str:
    return GOOD if p >= 90 else WARN if p >= 60 else BAD


def bar(p: int, width: int | None = None) -> str:
    fill = max(p, 2)
    w = f' width="{width}"' if width else ' width="100%"'
    return (f'<table role="presentation"{w} cellpadding="0" cellspacing="0"><tr>'
            f'<td width="{fill}%" height="6" bgcolor="{tone(p)}" style="height:6px;line-height:6px;font-size:0;">&nbsp;</td>'
            f'<td height="6" bgcolor="{TRACK}" style="height:6px;line-height:6px;font-size:0;">&nbsp;</td></tr></table>')


def gap(px: int) -> str:
    return f'<div style="height:{px}px;line-height:{px}px;font-size:0;">&nbsp;</div>'


def card(inner: str) -> str:
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="{CARD}" '
            f'style="background:{CARD};border:1px solid {LINE};border-radius:8px;border-collapse:separate;">'
            f'<tr><td style="padding:16px 20px;font-family:{FONT};">{inner}</td></tr></table>')


def todo_lines(es: list[dict]) -> str:
    """One line per field that is missing somewhere: 'Add Story points to 21 epics'."""
    lines = []
    for k, _ in CRITERIA:
        miss = [e for e in es if not e["ok"][k]]
        if miss:
            lines.append((len(miss), k, miss))
    lines.sort(key=lambda x: -x[0])
    if not lines:
        return f'<div style="font-size:13px;color:{GOOD};font-weight:600;">Nothing to do. Every epic is fully planned.</div>'
    out = ""
    for n, k, miss in lines:
        word = "epic" if n == 1 else "epics"
        out += (f'<tr><td style="padding:3px 0;font-size:13px;color:{INK};">{VERBS[k]} on '
                f'{keys_link(miss, f"<b>{n} {word}</b>", LINK)}</td></tr>')
    return f'<table role="presentation" cellpadding="0" cellspacing="0">{out}</table>'


def team_card(epics: list[dict], team: str) -> str:
    es = [e for e in epics if team in e["teams"]]
    s = stats(es)
    pods = [r for r in team_rows(epics, team) if r["name"] != UNASSIGNED_POD]
    nopod = [e for e in es if not e["pods"]]
    head = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
            f'<td style="font-size:16px;font-weight:700;color:{NAVY};">{html.escape(team)}</td>'
            f'<td align="right" style="font-size:12px;color:{SUBTLE};">{keys_link(es, f"{len(es)} epics", LINK)}'
            f' &nbsp;&middot;&nbsp; <b style="color:{tone(s["full"])};font-size:14px;">{s["full"]}%</b> all 4 filled</td></tr></table>')
    fields = "".join(
        f'<tr><td width="30%" style="padding:3px 0;font-size:12px;color:{SUBTLE};">{NAMES[k]}</td>'
        f'<td style="padding:3px 8px;">{bar(s[k])}</td>'
        f'<td width="12%" align="right" style="padding:3px 0;font-size:12px;color:{tone(s[k])};font-weight:600;'
        f'font-variant-numeric:tabular-nums;">{s[k]}%</td></tr>' for k, _ in CRITERIA)
    pods_html = ""
    if pods:
        parts = ", ".join(f'{html.escape(r["name"])} ({r["n"]})' for r in pods)
        extra = f", and {keys_link(nopod, f'{len(nopod)} with no pod', LINK)}" if nopod else ""
        pods_html = (f'{gap(10)}<div style="font-size:12px;color:{SUBTLE};line-height:18px;">Pods: {parts}{extra}</div>')
    return card(f'{head}{gap(10)}<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{fields}</table>'
                f'{gap(12)}<div style="font-size:11px;font-weight:600;color:{SUBTLE};text-transform:uppercase;'
                f'letter-spacing:0.04em;padding-bottom:4px;">To do</div>{todo_lines(es)}{pods_html}')


def render(cfg: dict, epics: list[dict], scope_team: str | None) -> str:
    teams = sorted({t for e in epics for t in e["teams"]}, key=lambda t: (t == NO_TEAM, t.lower()))
    if scope_team:
        epics = [e for e in epics if scope_team in e["teams"]]
        teams = [scope_team]
    s = stats(epics)
    m1, m2 = cfg["milestones"]
    in_ms = lambda m: [e for e in epics if e["milestone"] == m]
    title = f'{cfg["project"]} &middot; Release {cfg["release"]} planning status' + (f' &middot; {html.escape(scope_team)}' if scope_team else "")
    overall = card(
        f'<div style="font-size:28px;line-height:32px;font-weight:700;color:{tone(s["full"])};'
        f'font-variant-numeric:tabular-nums;">{keys_link([e for e in epics if not e["full"]], str(s["full"]) + "%", tone(s["full"]))}'
        f'<span style="font-size:14px;font-weight:400;color:{SUBTLE};"> of {keys_link(epics, str(s["n"]), LINK)} epics have all four fields filled</span></div>'
        f'{gap(10)}{bar(s["full"])}{gap(10)}<div style="font-size:12px;color:{SUBTLE};">'
        f'{keys_link(in_ms(m1), str(len(in_ms(m1))), LINK)} epics in the {m1} &nbsp;&middot;&nbsp; '
        f'{keys_link(in_ms(m2), str(len(in_ms(m2))), LINK)} in the {m2}</div>')
    cards = "".join(team_card(epics, t) + gap(12) for t in teams)
    body = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="{PAGE}" style="background:{PAGE};">'
            f'<tr><td align="center" style="padding:24px 12px;"><table role="presentation" width="720" cellpadding="0" '
            f'cellspacing="0" style="width:100%;max-width:720px;"><tr><td style="font-family:{FONT};color:{INK};">'
            f'<div style="font-size:22px;line-height:28px;font-weight:700;color:{NAVY};">{title}</div>{gap(14)}{overall}{gap(16)}')
    if not scope_team:
        body += (f'<div style="font-size:15px;font-weight:700;padding-bottom:10px;">Teams</div>{cards}')
    else:
        body += cards
        todo = [e for e in epics if not e["full"]]
        if todo:
            groups = ""
            for k, _ in CRITERIA:
                miss = sorted([e for e in todo if not e["ok"][k]], key=lambda e: e["key"])
                if not miss:
                    continue
                label = "Stale target sprint" if k == "sprint" and all(e["stale_sprint"] for e in miss) else NAMES[k]
                links = " &nbsp; ".join(f'<a href="{e["url"]}" title="{html.escape(e["summary"][:80])}" style="color:{LINK};">{e["key"]}</a>' for e in miss)
                groups += (f'<div style="padding:10px 0;border-bottom:1px solid {LINE};"><div style="font-size:13px;font-weight:700;'
                           f'color:{INK};padding-bottom:4px;">{label} missing on {len(miss)}</div>'
                           f'<div style="font-size:12px;line-height:20px;">{links}</div></div>')
            body += card(f'<div style="font-size:15px;font-weight:700;padding-bottom:2px;">Epics to update</div>{groups}')
    return body + "</td></tr></table></td></tr></table>"
