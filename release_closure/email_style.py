"""Email layout for the Release Closure Summary. Outlook-safe: tables, inline styles, bgcolor
attributes, no flex/grid/CSS variables. Same visual language as the release-status emails
(Segoe UI, navy numerals, hairline rules).

Percentages and counts look different on purpose: every percentage cell carries a % sign and sits on
the navy ramp; counts are plain numbers (the bug backlog uses an amber ramp)."""
from __future__ import annotations

import html
from urllib.parse import quote

FONT = "'Segoe UI',Inter,Arial,sans-serif"
INK, NAVY, SUBTLE, LINE, PAGE, CARD, LINK = "#1A1A1A", "#1F3A5F", "#5F6368", "#E4E4E7", "#FAFAFA", "#FFFFFF", "#0B5FB3"
GOOD, WARN, BAD = "#1B6B3A", "#8A5300", "#B3261E"
NAVY_RAMP, AMBER_RAMP = (31, 58, 95), (138, 83, 0)
NUM = "font-variant-numeric:tabular-nums;"
WEEKS = 12


def _lum(c):
    f = lambda v: (v / 255 / 12.92) if v / 255 <= 0.03928 else (((v / 255) + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2])


def _contrast(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def shade(frac: float, hi=NAVY_RAMP) -> tuple[str, str]:
    """(background, text) for 0..1; text is whichever of ink/white contrasts better."""
    k = max(0.0, min(1.0, frac)) * 0.92
    bg = tuple(round(255 + (hi[i] - 255) * k) for i in range(3))
    ink, white = (26, 26, 26), (255, 255, 255)
    fg = white if _contrast(bg, white) >= _contrast(bg, ink) else ink
    h = lambda c: "#%02X%02X%02X" % c
    return h(bg), h(fg)


def tone(p, good, warn):
    return GOOD if p >= good else WARN if p >= warn else BAD


def pct(n, d):
    return int(100 * n / d + 0.5) if d else 0   # half-up, so 12.5% shows as 13% like a reader expects


def link(href, text, color=LINK):
    return f'<a href="{href}" style="color:{color};text-decoration:underline;">{text}</a>'


def jql_href(base, jql):
    return f"{base}/issues/?jql={quote(jql)}"


def spacer(h):
    return f'<div style="height:{h}px;line-height:{h}px;font-size:0;">&nbsp;</div>'


def card(inner):
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="{CARD}" '
            f'style="background:{CARD};border:1px solid {LINE};border-radius:8px;border-collapse:separate;">'
            f'<tr><td style="padding:6px 10px 10px;">{inner}</td></tr></table>')


def heading(title, sub):
    return (f'<div style="font-family:{FONT};font-size:16px;line-height:22px;font-weight:600;color:{INK};padding-bottom:2px;">{title}</div>'
            f'<div style="font-family:{FONT};font-size:13px;line-height:19px;color:{SUBTLE};padding-bottom:10px;">{sub}</div>')


TH = f"padding:8px 4px;font-family:{FONT};font-size:11px;font-weight:600;color:{SUBTLE};border-bottom:1px solid {LINE};"
TD = f"padding:9px 4px;font-family:{FONT};font-size:13px;color:{INK};border-bottom:1px solid {LINE};{NUM}"
REL = f"{TD}padding-left:6px;font-weight:600;color:{NAVY};"


def closed_by_release(r):
    return sum(v for k, v in r["buckets"].items() if k != "post")


def delivered_pct(r):
    """Cumulative % of the end-of-W1 scope delivered by the end of each week (can exceed 100)."""
    acc, out = r["buckets"]["pre"], []
    for w in range(1, r["weeks"] + 1):
        acc += r["buckets"][w]
        out.append(pct(acc, r["baseline"]))
    return out


def bar_rows(rows, head_cols, widths):
    """Generic Release | bar | label table. rows: [(release html, bar_pct, color, label html)]."""
    head = "".join(head_cols)
    body = ""
    for name, p, color, label in rows:
        bar = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
               f'<td width="{max(p, 3)}%" height="6" bgcolor="{color}" style="height:6px;line-height:6px;font-size:0;">&nbsp;</td>'
               f'<td height="6" bgcolor="{LINE}" style="height:6px;line-height:6px;font-size:0;">&nbsp;</td></tr></table>')
        body += f'<tr>{name}<td width="{widths[0]}" style="{TD}padding-left:24px;">{bar}</td>{label}</tr>'
    return card(f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">{head}{body}</table>')


def throughput(base, rel, done_key="done", buckets_key="buckets", jql_key="done_jql"):
    rows = []
    for r in rel:
        by = sum(v for k, v in r[buckets_key].items() if k != "post")
        p = pct(by, r[done_key])
        fg = tone(p, 90, 75)
        rows.append((f'<td style="{REL}">{r["name"]}</td><td align="right" style="{TD}font-weight:600;">{link(jql_href(base, r[jql_key]), str(r[done_key]))}</td>',
                     p, fg,
                     f'<td width="22%" align="right" style="{TD}padding-right:6px;white-space:nowrap;"><span style="color:{fg};font-weight:600;">{p}%</span>'
                     f'<span style="color:{SUBTLE};font-size:12px;"> &nbsp;{by} of {r[done_key]}</span></td>'))
    heads = [f'<td align="left" style="{TH}padding-left:6px;">Release</td>', f'<td align="right" style="{TH}">{"Done epics" if done_key == "done" else "Done capabilities"}</td>',
             f'<td align="left" style="{TH}padding-left:24px;" colspan="2">Done by the release date</td>']
    # bar_rows puts the bar between the first two cells and the label; reorder head accordingly
    return bar_rows(rows, heads, ["38%"])


def cycle_time(rel):
    vals = [r["cycle_avg"] or 0 for r in rel]
    mx = max(vals) or 1
    rows = []
    for r in rel:
        v = r["cycle_avg"]
        rows.append((f'<td style="{REL}">{r["name"]}</td>', pct(v or 0, mx), NAVY,
                     f'<td width="34%" align="right" style="{TD}padding-right:6px;white-space:nowrap;"><span style="font-weight:600;">{v if v is not None else "&ndash;"} days</span>'
                     f'<span style="color:{SUBTLE};font-size:12px;"> &nbsp;median {r["cycle_med"] if r["cycle_med"] is not None else "&ndash;"} &middot; {r["cycle_n"]} epics</span></td>'))
    heads = [f'<td align="left" style="{TH}padding-left:6px;">Release</td>',
             f'<td align="left" style="{TH}padding-left:24px;">Average cycle time (days)</td>', f'<td style="{TH}"></td>']
    return bar_rows(rows, heads, ["58%"])


def grid(rows, maxw, lead_head, last_head):
    """rows: [(name, lead html or None, [(text, bg, fg)], last html)]."""
    head = f'<td align="left" style="{TH}padding-left:6px;">Release</td>'
    if lead_head:
        head += f'<td align="center" style="{TH}white-space:nowrap;">{lead_head}</td>'
    head += "".join(f'<td align="center" style="{TH}">W{w}</td>' for w in range(1, maxw + 1))
    head += f'<td align="center" style="{TH}padding-left:6px;white-space:nowrap;">{last_head}</td>'
    body = ""
    for name, lead, cells, last in rows:
        tds = f'<td style="{REL}">{name}</td>'
        if lead is not None:
            tds += f'<td align="center" style="{TD}font-weight:600;">{lead}</td>'
        for text, bg, fg in cells:
            tds += (f'<td align="center" bgcolor="{bg}" style="padding:9px 0;font-family:{FONT};font-size:11px;{NUM}'
                    f'background:{bg};color:{fg};border-bottom:1px solid {CARD};border-right:1px solid {CARD};">{text}</td>')
        body += f'<tr>{tds}<td align="center" style="{TD}padding-left:6px;white-space:nowrap;">{last}</td></tr>'
    return card(f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;"><tr>{head}</tr>{body}</table>')


def pct_cells(vals):
    return [(f"{v}%", *shade(v / 100)) for v in vals]


def predictability(base, rel):
    rows = []
    for r in rel:
        vals = delivered_pct(r)
        final = pct(r["done"], r["baseline"])
        rows.append((r["name"], link(jql_href(base, r["baseline_jql"]), str(r["baseline"])) if r["baseline_jql"] else str(r["baseline"]), pct_cells(vals),
                     f'<span style="font-weight:600;color:{NAVY};">{final}%</span>'))
    return grid(rows, WEEKS, "Scope<br>(epics)", "After<br>release")


def test_coverage(base, rel):
    rows = []
    for r in rel:
        c = pct(r["auto"], r["tests"])
        rows.append((r["name"], link(jql_href(base, r["tests_jql"]), str(r["tests"])),
                     pct_cells([pct(x, r["tests"]) for x in r["auto_weekly"]]),
                     link(jql_href(base, r["auto_jql"]), f'<span style="font-weight:600;color:{tone(c, 85, 70)}">{c}%</span>', tone(c, 85, 70))))
    return grid(rows, WEEKS, "Tests<br>(count)", "Today")


def bugs_backlog(base, rel):
    mx = max(max(r["bugs_weekly"]) for r in rel) or 1
    rows = []
    for r in rel:
        wk = r["bugs_weekly"]
        d = wk[-1] - wk[0]
        col = GOOD if d < 0 else BAD if d > 0 else SUBTLE
        sign = "&minus;" if d < 0 else "+" if d > 0 else ""
        rows.append((r["name"], None, [(str(v), *shade(v / mx, AMBER_RAMP)) for v in wk],
                     f'<span style="font-weight:600;color:{col};">{sign}{abs(d)}</span>'))
    return grid(rows, WEEKS, None, "W1&rarr;W12")


def sonar_coverage(cfg):
    import calendar
    rows = cfg["sonarqube"]["monthly"]
    head = f'<td align="left" style="{TH}padding-left:6px;"></td>'
    for m in rows:
        y, mo = m["month"].split("-")
        lab = calendar.month_abbr[int(mo)] + " " + y[2:] + ("<br>to date" if m.get("partial") else "")
        head += f'<td align="center" style="{TH}white-space:nowrap;">{lab}</td>'
    lo, hi = min(m["coverage"] for m in rows), max(m["coverage"] for m in rows)
    cov = ""
    for m in rows:
        bg, fg = shade((m["coverage"] - lo) / ((hi - lo) or 1) * 0.85 + 0.1)
        cov += (f'<td align="center" bgcolor="{bg}" style="padding:9px 0;font-family:{FONT};font-size:12px;font-weight:600;{NUM}background:{bg};color:{fg};'
                f'border-bottom:1px solid {CARD};border-right:1px solid {CARD};">{m["coverage"]:.1f}%</td>')
    plain = lambda key, fmt: "".join(f'<td align="center" style="{TD}font-size:12px;">{fmt(m[key])}</td>' for m in rows)
    body = (f'<tr><td style="{REL}">Coverage</td>{cov}</tr>'
            f'<tr><td style="{TD}padding-left:6px;color:{SUBTLE};">Lines to cover</td>{plain("lines", lambda v: f"{v:,}")}</tr>'
            f'<tr><td style="{TD}padding-left:6px;color:{SUBTLE};">Projects</td>{plain("projects", str)}</tr>')
    return card(f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;"><tr>{head}</tr>{body}</table>')


def render_email(cfg, base, rel, overall) -> str:
    p = cfg["project"]
    rng = f'{rel[0]["name"]}&ndash;{rel[-1]["name"]}'
    first, last = rel[0], rel[-1]
    tests_on = cfg.get("test_coverage", True)
    deliv = delivered_pct(last)[-1]
    trend = "grew" if last["done"] > first["done"] else "fell" if last["done"] < first["done"] else "held steady"
    trend_txt = (f'from {first["done"]} to {last["done"]}' if trend != "held steady" else f'at {last["done"]}')
    cyc = f', with an average cycle time of {last["cycle_avg"]} days' if last["cycle_avg"] is not None else ""
    lede = (f'Throughput {trend} {trend_txt} epics per release. {last["name"]} delivered {deliv}% of the epics in scope '
            f'at the end of W1 by its release date{cyc}')
    sq = cfg.get("sonarqube")
    if tests_on:
        lede += f', and {pct(last["auto"], last["tests"])}% of its regression tests are automated.'
    elif sq:
        m = sq["monthly"][-1]
        lede += f'. SonarQube code coverage stands at {m["coverage"]:.1f}%.'
    else:
        lede += "."

    sections = [
        (cfg.get("throughput_title", "Throughput"), "Epics Done per release, and what share of them were already Done on the release date.", throughput(base, rel)),
    ] + ([(cfg.get("capability_throughput_title", "Throughput Capabilities"),
           "Capabilities Done per release, and what share of them were already Done on the release date.",
           throughput(base, rel, "cap_done", "cap_buckets", "cap_done_jql"))] if cfg.get("capabilities") else []) + [
        ("Cycle time", "Average calendar days a Done epic spent in In Progress or Validation, excluding flagged days and Maintenance epics. A few long-running epics lift the average above the median.", cycle_time(rel)),
        ("Predictability", "Epics delivered so far as a <b>percentage</b> of the scope at the end of W1 (the Scope column is a count). "
                           "100% means the W1 scope has been delivered; above 100% means more was delivered than planned.", predictability(base, rel)),
    ]
    if tests_on:
        ov = "%d of %d" % (overall["auto"], overall["tests"])
        sections.append(("Test coverage", "Share of each release&rsquo;s regression tests (P1 and P2) that are automated by the end of each week, as a <b>percentage</b> of that release&rsquo;s tests.",
                         test_coverage(base, rel) + f'<div style="font-family:{FONT};font-size:13px;color:{SUBTLE};padding-top:8px;">Across all {html.escape(p)} regression tests: '
                         f'{link(jql_href(base, overall["auto_jql"]), ov)} automated ({pct(overall["auto"], overall["tests"])}%).</div>'))
    if sq:
        a, z = sq["monthly"][0], sq["monthly"][-1]
        sections.append(("Code coverage", f'SonarQube coverage by month, as a <b>percentage</b> of lines to cover. It moved from {a["coverage"]:.1f}% to {z["coverage"]:.1f}% while lines to cover grew from {a["lines"]:,} to {z["lines"]:,}.',
                         sonar_coverage(cfg)))
    sections.append((cfg.get("bugs_title", "Gating bugs backlog"), "Open P1 to P3 bugs at the end of each week, excluding Accessibility bugs. These are <b>counts</b> of bugs, not percentages; "
                                             "the last column is the change from the end of W1 to the end of W12.", bugs_backlog(base, rel)))

    multi = cfg.get("projects")
    weeks_note = ", ".join(f'{r["name"]} {r["dev_start"]:%d %b}&ndash;{r["end"]:%d %b %Y}' for r in rel)
    windows = ("Each project uses its own Jira release dates, and weeks are counted from its first delivery week" if multi else f"Delivery windows: {weeks_note}")
    foot = (f'Each release has an IP (planning) week followed by 12 delivery weeks (4 sprints) up to the release date; W1 is the first delivery week. '
            f'{windows}. Epics Done during the IP week count from W1; Done date is the last move into Done; cycle time does not count the Done day itself (as in the R&D efficiency report). '
            f'Scope is the epics in the release at the end of W1 with Commitment Type Committed or empty, excluding Stretch and any that are or became Removed; Stretch epics and epics added later raise the percentage above 100. '
            f'Bugs whose summary mentions Accessibility are excluded, as on the PMN dashboard; a bug that was reopened counts as open since it was created. Throughput colour: green 90% or more of Done epics were Done by the release date, amber 75% or more.')
    if multi:
        per_rel = "; ".join(f'{r["name"]}: {", ".join(r["projects"])}' for r in rel)
        foot += f' Combined across projects on the quarterly release train ({per_rel}). ' + cfg.get("scope_note", "")
    if sq:
        foot += " Code coverage is SonarQube data supplied by month; the latest month is to date."
    if tests_on:
        foot += (f' Test coverage covers Tests labelled {", ".join(cfg["test_labels"])} with priority {" or ".join(cfg["test_priorities"])}, '
                 f'grouped by fix version; the week is the test&rsquo;s Automated Date.')

    body = "".join(spacer(28 if i else 20) + heading(t, sub) + content for i, (t, sub, content) in enumerate(sections))
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="{PAGE}" style="background:{PAGE};">'
            f'<tr><td align="center" style="padding:24px 12px;"><table role="presentation" width="720" cellpadding="0" cellspacing="0" '
            f'style="width:100%;max-width:720px;"><tr><td style="font-family:{FONT};color:{INK};">'
            f'<div style="font-size:22px;line-height:28px;font-weight:600;color:{NAVY};">{html.escape(p)} &middot; Release closure summary {rng}</div>'
            f'<div style="font-size:14px;line-height:21px;color:{SUBTLE};padding-top:6px;max-width:600px;">{lede}</div>'
            f'{body}{spacer(24)}<div style="font-size:11px;line-height:16px;color:{SUBTLE};border-top:1px solid {LINE};padding-top:12px;">{foot}</div>'
            f'</td></tr></table></td></tr></table>')
