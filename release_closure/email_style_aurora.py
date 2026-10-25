"""Email layout for the Release Closure Summary. Outlook-safe: tables, inline styles, bgcolor
attributes, no flex/grid/CSS variables. Same visual language as the release-status emails
(Segoe UI, navy numerals, hairline rules).

Percentages and counts look different on purpose: every percentage cell carries a % sign and sits on
the navy ramp; counts are plain numbers (the bug backlog uses an amber ramp)."""
from __future__ import annotations

import html
import sys
from urllib.parse import quote

FONT = "'Segoe UI',Inter,Arial,sans-serif"
INK, NAVY, SUBTLE, LINE, PAGE, CARD, LINK = "#14123A", "#2B2D9E", "#5A6078", "#DEE7F5", "#F2F8FF", "#FFFFFF", "#1F6FEB"
BLUE, VIOLET, MINT = "#2F7BFF", "#6A32EE", "#E4FBF4"
GOOD, WARN, BAD = "#1B6B3A", "#8A5300", "#B3261E"
NAVY_RAMP, AMBER_RAMP = (48, 52, 190), (0, 96, 128)   # % series: white to indigo; counts: white to teal
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
    ink, white = (26, 26, 26), (255, 255, 255)
    base_k = max(0.0, min(1.0, frac)) * 0.85
    for step in range(0, 40):                     # nudge the shade lighter or darker until the text reaches 4.5:1
        for k in (base_k - step * 0.005, base_k + step * 0.005):
            k = max(0.0, min(0.95, k))
            bg = tuple(round(255 + (hi[i] - 255) * k) for i in range(3))
            fg = white if _contrast(bg, white) >= _contrast(bg, ink) else ink
            if max(_contrast(bg, white), _contrast(bg, ink)) >= 4.5:
                h = lambda c: "#%02X%02X%02X" % c
                return h(bg), h(fg)
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
            f'style="background:{CARD};border:1px solid {LINE};border-radius:8px;border-collapse:separate;table-layout:fixed;">'
            f'<tr><td style="padding:6px 10px 10px;">{inner}</td></tr></table>')


def heading(title, sub):
    return (f'<h2 style="margin:0;font-family:{FONT};font-size:16px;line-height:22px;font-weight:600;color:{INK};padding-bottom:2px;">{title}</h2>'
            f'<div style="font-family:{FONT};font-size:13px;line-height:19px;color:{SUBTLE};padding-bottom:10px;">{sub}</div>')


TH = f"padding:8px 4px;font-family:{FONT};font-size:12px;font-weight:600;color:{SUBTLE};border-bottom:1px solid {LINE};"
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
    return card(f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;"><tr>{head}</tr>{body}</table>')


def throughput(base, rel, done_key="done", buckets_key="buckets", jql_key="done_jql"):
    rows = []
    for r in rel:
        by = sum(v for k, v in r[buckets_key].items() if k != "post")
        p = pct(by, r[done_key])
        fg = tone(p, 90, 75)
        rows.append((f'<th scope="row" align="left" style="{REL}text-align:left;">{r["name"]}</th><td align="right" style="{TD}font-weight:600;">{link(jql_href(base, r[jql_key]), str(r[done_key]))}</td>',
                     p, fg,
                     f'<td width="22%" align="right" style="{TD}padding-right:6px;"><span style="color:{fg};font-weight:600;">{p}%</span>'
                     f'<span style="color:{SUBTLE};font-size:12px;"> &nbsp;{by} of {r[done_key]}</span></td>'))
    heads = [f'<th scope="col" align="left" style="{TH}padding-left:6px;text-align:left;">Release</th>', f'<th scope="col" align="right" style="{TH}text-align:right;">{"Done capabilities" if done_key == "cap_done" else "Done epics"}</th>',
             f'<th scope="col" align="left" style="{TH}padding-left:24px;text-align:left;" colspan="2">Done by release date</th>']
    # bar_rows puts the bar between the first two cells and the label; reorder head accordingly
    return bar_rows(rows, heads, ["38%"])


def cycle_time(rel):
    solid = [r["cycle_avg"] or 0 for r in rel if r["cycle_n"] >= 5] or [r["cycle_avg"] or 0 for r in rel]
    mx = max(solid) or 1
    rows = []
    for r in rel:
        v = r["cycle_avg"]
        small = r["cycle_n"] < 5
        rows.append((f'<th scope="row" align="left" style="{REL}text-align:left;">{r["name"]}</th>', 0 if small else min(100, pct(v or 0, mx)), LINE if small else BLUE,
                     f'<td width="34%" align="right" style="{TD}padding-right:6px;"><span style="font-weight:600;white-space:nowrap;">{v if v is not None else "&ndash;"} days</span>'
                     f'<span style="color:{SUBTLE};font-size:12px;"> &nbsp;median {r["cycle_med"] if r["cycle_med"] is not None else "&ndash;"} &middot; {"n=" if small else ""}{r["cycle_n"]}{"" if small else " epics"}</span></td>'))
    heads = [f'<th scope="col" align="left" style="{TH}padding-left:6px;text-align:left;">Release</th>',
             f'<th scope="col" align="left" style="{TH}padding-left:24px;text-align:left;">Average cycle time</th>', f'<td style="{TH}"></td>']
    return bar_rows(rows, heads, ["58%"])


def grid(rows, maxw, lead_head, last_head):
    """rows: [(name, lead html or None, [(text, bg, fg)], last html)]."""
    head = f'<th scope="col" align="left" style="{TH}padding-left:6px;text-align:left;">Release</th>'
    if lead_head:
        head += f'<th scope="col" align="center" style="{TH}white-space:nowrap;text-align:center;">{lead_head}</th>'
    head += "".join(f'<th scope="col" align="center" style="{TH}text-align:center;">W{w}</th>' for w in range(1, maxw + 1))
    head += f'<th scope="col" align="center" style="{TH}padding-left:6px;white-space:nowrap;text-align:center;">{last_head}</th>'
    body = ""
    for name, lead, cells, last in rows:
        tds = f'<th scope="row" align="left" style="{REL}text-align:left;">{name}</th>'
        if lead is not None:
            tds += f'<td align="center" style="{TD}font-weight:600;">{lead}</td>'
        for text, bg, fg in cells:
            tds += (f'<td align="center" bgcolor="{bg}" style="padding:9px 0;font-family:{FONT};font-size:12px;{NUM}'
                    f'background:{bg};color:{fg};border-bottom:1px solid {CARD};border-right:1px solid {CARD};">{text}</td>')
        body += f'<tr>{tds}<td align="center" style="{TD}padding-left:6px;white-space:nowrap;">{last}</td></tr>'
    return card(f'<div style="overflow-x:auto;"><table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;min-width:560px;"><tr>{head}</tr>{body}</table></div>')


def pct_cells(vals):
    return [(f"{v}%", *shade(v / 100)) for v in vals]


def predictability(base, rel):
    rows = []
    for r in rel:
        vals = delivered_pct(r)
        final = pct(r["done"], r["baseline"])
        rows.append((r["name"], link(jql_href(base, r["baseline_jql"]), str(r["baseline"])) if r["baseline_jql"] else str(r["baseline"]), pct_cells(vals),
                     f'<span style="font-weight:600;color:{NAVY};">{final}%</span>'))
    return grid(rows, WEEKS, "Scope<br>(epics)", "Final<br>(today)")


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
        col = SUBTLE if abs(d) <= 1 else GOOD if d < 0 else BAD
        sign = "&minus;" if d < 0 else "+" if d > 0 else ""
        rows.append((r["name"], None, [(str(v), *shade(v / mx, AMBER_RAMP)) for v in wk],
                     f'<span style="font-weight:600;color:{col};">{sign}{abs(d)}</span>'))
    return grid(rows, WEEKS, None, "W1&rarr;W12")


def sonar_coverage(cfg):
    import calendar
    rows = cfg["sonarqube"]["monthly"]
    head = f'<th scope="col" align="left" style="{TH}padding-left:6px;text-align:left;">Metric</th>'
    for m in rows:
        y, mo = m["month"].split("-")
        lab = calendar.month_abbr[int(mo)] + " " + y + ("<br>to date" if m.get("partial") else "")
        head += f'<th scope="col" align="center" style="{TH}white-space:nowrap;text-align:center;">{lab}</th>'
    lo, hi = min(m["coverage"] for m in rows), max(m["coverage"] for m in rows)
    cov = ""
    for m in rows:
        bg, fg = "#E4F4F8", INK
        cov += (f'<td align="center" bgcolor="{bg}" style="padding:9px 0;font-family:{FONT};font-size:12px;font-weight:600;{NUM}background:{bg};color:{fg};'
                f'border-bottom:1px solid {CARD};border-right:1px solid {CARD};">{m["coverage"]:.1f}%</td>')
    plain = lambda key, fmt: "".join(f'<td align="center" style="{TD}font-size:12px;">{fmt(m[key])}</td>' for m in rows)
    body = (f'<tr><th scope="row" align="left" style="{REL}text-align:left;">Coverage</th>{cov}</tr>'
            f'<tr><th scope="row" align="left" style="{TD}padding-left:6px;color:{SUBTLE};font-weight:400;text-align:left;">Lines to cover</th>{plain("lines", lambda v: f"{v:,}")}</tr>'
            f'<tr><th scope="row" align="left" style="{TD}padding-left:6px;color:{SUBTLE};font-weight:400;text-align:left;">Projects</th>{plain("projects", str)}</tr>')
    return card(f'<div style="overflow-x:auto;"><table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;"><tr>{head}</tr>{body}</table></div>')


def _logo_src(cfg):
    """Logo image source: a hosted URL if configured (works in every mail client), else an inline copy (works in some)."""
    import base64
    from pathlib import Path
    if cfg.get("logo_url"):
        return cfg["logo_url"]
    if cfg.get("logo_inline"):
        p = Path(__file__).resolve().parent / "assets" / "nice_smile_white.png"
        return "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode() if p.exists() else ""
    return ""


_BANNER_CACHE = {}


def _banner_png_uri(title_plain, brand=""):
    """The banner as one picture (gradient, title and smile drawn in). Gradients drawn by CSS are dropped by some mail
    clients, a picture is not. Returns "" if the picture cannot be made (no Pillow or no bold font)."""
    key = (title_plain, brand)
    if key in _BANNER_CACHE:
        return _BANNER_CACHE[key]
    uri = ""
    try:
        import base64
        import io
        from pathlib import Path
        import numpy as np
        from PIL import Image, ImageDraw, ImageFont
        W, H, S = 720, 64, 2
        stops = [((106, 50, 238), 0.0), ((47, 123, 255), 0.55), ((43, 136, 238), 1.0)]

        def grad(x):
            for (c1, p1), (c2, p2) in zip(stops, stops[1:]):
                if x <= p2:
                    return [c1[i] + (c2[i] - c1[i]) * (x - p1) / (p2 - p1) for i in range(3)]
            return list(stops[-1][0])
        arr = np.zeros((H * S, W * S, 3), dtype=np.uint8)
        for x in range(W * S):
            arr[:, x] = [round(v) for v in grad(x / (W * S - 1))]
        img = Image.fromarray(arr).convert("RGBA")
        pairs = (("/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf"),
                 ("/Library/Fonts/Arial Bold.ttf", "/Library/Fonts/Arial.ttf"),
                 ("C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/segoeui.ttf"),
                 ("C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf"),
                 ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
        bold_path = reg_path = None
        for bp, rp in pairs:
            try:
                ImageFont.truetype(bp, 20)
                ImageFont.truetype(rp, 20)
                bold_path, reg_path = bp, rp
                break
            except Exception:
                continue
        if bold_path is None:
            return ""
        head = brand if brand and title_plain.startswith(brand) else ""
        tail = title_plain[len(head):]
        size = 26
        while True:
            fb = ImageFont.truetype(bold_path, size * S)      # one typeface and weight for the whole title
            width = fb.getlength(head + tail) / S
            if width <= W - 26 - 24 - 30 - 28 or size <= 17:
                break
            size -= 1
        d = ImageDraw.Draw(img)
        d.text((26 * S, H * S // 2), head, font=fb, fill="white", anchor="lm")
        d.text((26 * S + fb.getlength(head), H * S // 2), tail, font=fb, fill=(226, 236, 255), anchor="lm")   # same weight, softer white: the name stands out by tone
        smile = Path(__file__).resolve().parent / "assets" / "nice_smile_white.png"
        if smile.exists():
            sm = Image.open(smile).convert("RGBA").resize((30 * S, 30 * S), Image.LANCZOS)
            img.alpha_composite(sm, ((W - 24 - 30) * S, (H * S - 30 * S) // 2))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "PNG", optimize=True)
        uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        uri = ""
    _BANNER_CACHE[key] = uri
    return uri


def banner(title, logo_src="", title_plain="", brand=""):
    uri = _banner_png_uri(title_plain, brand) if title_plain else ""
    if uri:   # one picture: works where CSS gradients are stripped; the title is the alt text
        return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="#3D5AF1" style="background:#3D5AF1;border-radius:16px;border-collapse:separate;">'
                f'<tr><td style="padding:0;"><img src="{uri}" width="720" alt="{html.escape(title_plain)}" '
                f'style="display:block;border:0;width:100%;max-width:720px;height:auto;border-radius:16px;color:#FFFFFF;font-family:{FONT};font-size:20px;font-weight:700;"></td></tr></table>')
    brand_html = html.escape(brand)
    logo = (f'<td align="right" valign="middle" style="padding:0 22px 0 0;"><img src="{logo_src}" width="28" height="28" alt="NiCE" '
            f'style="display:block;border:0;width:28px;height:28px;"></td>') if logo_src else ""
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="#3D5AF1" '
            f'style="background:#3D5AF1;background-image:linear-gradient(115deg,{VIOLET} 0%,{BLUE} 55%,#2B88EE 100%);border-radius:16px;border-collapse:separate;">'
            f'<tr><td valign="middle" style="padding:16px 24px;font-family:{FONT};">'
            f'<div style="font-size:20px;line-height:26px;font-weight:400;color:#FFFFFF;"><b>{brand_html}</b>{title}</div></td>{logo}</tr></table>')


def _verdict(cfg, rel):
    """One factual line: the latest release's key figures, and what it is compared with."""
    tp = bool(cfg.get("throughput_exclude_categories"))
    dk, bk = ("tp_done", "tp_buckets") if tp else ("done", "buckets")
    last = rel[-1]
    by = sum(v for k, v in last[bk].items() if k != "post")
    parts = [f'{last[dk]} epics done', f'{pct(by, last[dk])}% done by release date', f'{pct(last["done"], last["baseline"])}% of the W1 scope']
    if last["cycle_avg"] is not None:
        parts.append(f'average cycle time {last["cycle_avg"]} days')
    parts.append(f'{last["bugs_weekly"][-1]} bugs in the P1-P3 backlog (W12)')
    lead = f'{last["name"]} vs {rel[-2]["name"]}: ' if len(rel) > 1 else f'{last["name"]}: '
    return lead + ", ".join(parts)


def executive_summary(base, rel, cfg):
    tp = bool(cfg.get("throughput_exclude_categories"))
    dk, bk, jk = ("tp_done", "tp_buckets", "tp_jql") if tp else ("done", "buckets", "done_jql")

    def figs(r):
        by = sum(v for k, v in r[bk].items() if k != "post")
        return (r[dk], pct(by, r[dk]), r["cycle_avg"], pct(r["done"], r["baseline"]), r["bugs_weekly"][-1])

    last, prev = rel[-1], (rel[-2] if len(rel) > 1 else None)
    a, b = figs(last), (figs(prev) if prev else None)
    labels = ["Done epics", "Done by release date", "Cycle time (days)", "vs W1 scope", "Bugs Backlog: P1-P3"]
    head = "".join(f'<td align="center" style="padding:8px 6px 2px;font-family:{FONT};font-size:12px;color:{SUBTLE};">{l}</td>' for l in labels)
    big = f"padding:2px 6px 4px;font-family:{FONT};font-size:24px;line-height:30px;font-weight:700;color:{INK};{NUM}"
    vals = [f'<a href="{jql_href(base, last[jk])}" style="color:{LINK};text-decoration:none;">{a[0]}</a>', f'<span style="color:{tone(a[1], 90, 75)};">{a[1]}%</span>',
            str(a[2]) if a[2] is not None else "&ndash;", f"{a[3]}%", str(a[4])]
    row1 = "".join(f'<td align="center" style="{big}">{v}</td>' for v in vals)
    row2 = ""
    if b:
        def d(x, y, lower_better=False, unit="", neutral=False):
            if x is None or y is None:
                return "&ndash;"
            dv = x - y
            good = (dv < 0) if lower_better else (dv > 0)
            col = SUBTLE if (dv == 0 or neutral) else GOOD if good else BAD
            sign = "&minus;" if dv < 0 else "+" if dv > 0 else "&plusmn;"
            return f'<span style="color:{col};">{sign}{abs(dv)}{unit}</span>'
        cells = [d(a[0], b[0]), d(a[1], b[1], unit=" pts"), d(a[2], b[2], True), d(a[3], b[3], unit=" pts", neutral=True), d(a[4], b[4], True)]
        row2 = "".join(f'<td align="center" style="padding:0 6px 10px;font-family:{FONT};font-size:13px;font-weight:600;{NUM}">{x}</td>' for x in cells)
        row2 = f"<tr>{row2}</tr>"
    return card(f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;"><tr>{head}</tr><tr>{row1}</tr>{row2}</table>')


def render_email(cfg, base, rel, overall) -> str:
    p = cfg.get("display_name", cfg["project"])
    rng = f'{rel[0]["name"]}&ndash;{rel[-1]["name"]}'
    first, last = rel[0], rel[-1]
    tests_on = cfg.get("test_coverage", True)
    deliv = delivered_pct(last)[-1]
    dk = "tp_done" if cfg.get("throughput_exclude_categories") else "done"
    trend = "grew" if last[dk] > first[dk] else "fell" if last[dk] < first[dk] else "held steady"
    trend_txt = (f'from {first[dk]} to {last[dk]}' if trend != "held steady" else f'at {last[dk]}')
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
        (cfg.get("throughput_title", "Throughput"),
         "Epics done per release" + (f", excluding {' and '.join(cfg['throughput_exclude_categories'])} epics" if cfg.get("throughput_exclude_categories") else "")
         + ", and what share of them were already done on the release date.",
         throughput(base, rel, *(("tp_done", "tp_buckets", "tp_jql") if cfg.get("throughput_exclude_categories") else ()))),
    ] + ([(cfg.get("capability_throughput_title", "Throughput Capabilities"),
           "Capabilities Done per release" + (", including Done capabilities from other projects that have Done CXWFM epics" if cfg.get("capabilities_from_other_projects") else "")
           + ", and what share of them were already Done on the release date.",
           throughput(base, rel, "cap_done", "cap_buckets", "cap_done_jql"))] if cfg.get("capabilities") else []) + [
        ("Cycle Time", "Average calendar days a done epic spent in In Progress or Validation, excluding flagged days. Maintenance epics are excluded, so the epic count can be lower than done epics. The median is shown for comparison; releases with fewer than 5 epics show no bar.", cycle_time(rel)),
        ("Predictability", "Epics delivered so far as a <b>percentage</b> of the scope at the end of W1 (the Scope column is a count). W1 is the first delivery week, after the planning (IP) week. "
                           "100% means the W1 scope has been delivered; above 100% means more was delivered than planned.", predictability(base, rel)),
    ]
    if tests_on:
        ov = "%d of %d" % (overall["auto"], overall["tests"])
        sections.append(("Test coverage", "Share of each release&rsquo;s regression tests (P1 and P2) that are automated by the end of each week, as a <b>percentage</b> of that release&rsquo;s tests.",
                         test_coverage(base, rel) + f'<div style="font-family:{FONT};font-size:13px;color:{SUBTLE};padding-top:8px;">Across all {html.escape(p)} regression tests: '
                         f'{link(jql_href(base, overall["auto_jql"]), ov)} automated ({pct(overall["auto"], overall["tests"])}%).</div>'))
    if sq:
        a, z = sq["monthly"][0], sq["monthly"][-1]
        sections.append(("Code Coverage", f'SonarQube coverage by month, as a <b>percentage</b> of lines to cover. It moved from {a["coverage"]:.1f}% to {z["coverage"]:.1f}% while lines to cover grew from {a["lines"]:,} to {z["lines"]:,}.'
                         + (f' The set of projects grew from {a["projects"]} to {z["projects"]}, so months are not strictly like for like.' if a["projects"] != z["projects"] else ""),
                         sonar_coverage(cfg)))
    sections.append((cfg.get("bugs_title", "Gating bugs backlog"), "Bugs in the P1-P3 backlog at the end of each week, excluding Accessibility bugs. These are <b>counts</b> of bugs, not percentages; "
                                             "the last column is the change from the end of W1 to the end of W12.", bugs_backlog(base, rel)))

    cfb_on = bool(rel and rel[0].get("cfb"))
    if cfb_on:   # customer-found bugs sit directly below the bugs backlog
        import cfb_kpis
        sections.append((cfb_kpis.TITLE, cfb_kpis.SUB, cfb_kpis.table(sys.modules[__name__], base, rel, overall["cfb"])))

    multi = cfg.get("projects")
    weeks_note = ", ".join(f'{r["name"]} {r["dev_start"].day} {r["dev_start"]:%b %Y}&ndash;{r["end"].day} {r["end"]:%b %Y}' for r in rel)
    windows = ("Each project uses its own Jira release dates, and weeks are counted from its first delivery week" if multi else f"Delivery windows: {weeks_note}")
    foot = (f'Each release has an IP (planning) week followed by 12 delivery weeks (4 sprints) up to the release date; W1 is the first delivery week. '
            f'{windows}. Epics done during the IP week count from W1; the done date is the last move into Done; cycle time does not count the Done day itself (as in the R&D efficiency report). '
            f'Scope is the epics in the release at the end of W1 with Commitment Type Committed or empty, excluding Stretch and any that are or became Removed; Stretch epics and epics added later raise the percentage above 100. '
            f'{cfg.get("bug_exclusion_note", "Bugs whose summary mentions Accessibility are excluded, as on the PMN dashboard")}; a bug that was reopened counts as open since it was created. Throughput colour: green 90% or more of done epics were done by the release date, amber 75% or more.')
    foot += " Final (today) in Predictability is the share delivered as of the send date, including epics done after the release date."
    if cfb_on:
        foot += "<br>" + __import__("cfb_kpis").NOTE
    if cfg.get("footnote_extra"):
        foot += " " + cfg["footnote_extra"]
    if multi:
        per_rel = "; ".join(f'{r["name"]}: {", ".join(r["projects"])}' for r in rel)
        foot += f' Combined across projects on the quarterly release train ({per_rel}). ' + cfg.get("scope_note", "")
    if sq:
        foot += " Code coverage is SonarQube data supplied by month; the latest month is to date."
    if tests_on:
        foot += (f' Test coverage covers Tests labelled {", ".join(cfg["test_labels"])} with priority {" or ".join(cfg["test_priorities"])}, '
                 f'grouped by fix version; the week is the test&rsquo;s Automated Date.')

    exec_sub = cfg.get("summary_note") or _verdict(cfg, rel)   # a written note, when one is configured, replaces the generated figures line
    plain_title = p + " Release Closure Summary " + rel[0]["name"] + "\u2013" + rel[-1]["name"]
    exec_note = (f'<div style="font-family:{FONT};font-size:12px;line-height:17px;color:{SUBTLE};padding-top:6px;">'
                 f'Changes compare {rel[-1]["name"]} with {rel[-2]["name"]}; bugs are compared at the end of W12. '
                 f'For &ldquo;vs W1 scope&rdquo;, 100% means the scope at the end of W1 was fully delivered.</div>') if len(rel) > 1 else ""
    if cfg.get("lean_copy"):
        exec_note = ""
    preheader = (f'<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;font-size:1px;line-height:1px;color:{PAGE};">{exec_sub}</div>')
    for start in (" Delivery windows:", " Throughput colour:", " Final (today) in Predictability", " Epics done during the IP week", " Scope is the epics", " Bugs whose summary", " Bugs are excluded", " Accessibility bugs are excluded", " Code coverage is SonarQube", " Test coverage covers", " Throughput Epics excludes", " Throughput Capabilities counts"):
        foot = foot.replace(start, "<br>" + start.lstrip(), 1)
    if cfg.get("lean_copy"):
        lean = {"Throughput": "Epics done per release, and the share done by the release date.",
                "Cycle Time": "Average days in In Progress or Validation. Median shown for comparison; releases with fewer than 5 epics show no bar.",
                "Predictability": "Cumulative % of the end-of-W1 scope delivered, by week. 100% is the plan.",
                "Code Coverage": "SonarQube coverage by month.",
                cfg.get("bugs_title", "Gating bugs backlog"): "Open bugs at the end of each week (counts). Last column: change from W1 to W12."}
        sections = [(ti, lean.get(ti, su), co) for ti, su, co in sections]
        foot = (f'Each release has a planning (IP) week, then 12 delivery weeks; W1 is the first. Windows: {weeks_note}.<br>'
                'Scope is the epics in the release at the end of W1 (Committed or empty, excluding Stretch and Removed). '
                'Final (today) includes epics done after the release date. Cycle time excludes Maintenance epics and flagged days.<br>'
                + cfg.get("bug_exclusion_note", "Accessibility bugs are excluded") + '.'
                + ('<br>' + __import__("cfb_kpis").NOTE if cfb_on else "")
                + ('<br>Code coverage: SonarQube, latest month to date.' if cfg.get("sonarqube") else ""))
    body = "".join(spacer(28 if i else 20) + heading(t, sub) + content for i, (t, sub, content) in enumerate(sections))
    return (f'<table role="presentation" lang="en" width="100%" cellpadding="0" cellspacing="0" bgcolor="{PAGE}" style="background:{PAGE};">'
            f'<tr><td align="center" style="padding:24px 12px;"><table role="presentation" width="720" cellpadding="0" cellspacing="0" '
            f'style="width:100%;max-width:720px;table-layout:fixed;"><tr><td style="font-family:{FONT};color:{INK};">'
            f'{preheader}{banner(" Release Closure Summary " + rng, _logo_src(cfg), plain_title, p)}'
            f'{spacer(18)}{heading("Executive Summary", exec_sub)}{executive_summary(base, rel, cfg)}{exec_note}'
            f'{body}{spacer(24)}<div style="font-size:12px;line-height:17px;color:{SUBTLE};border-top:1px solid {LINE};padding-top:12px;">{foot}</div>'
            f'</td></tr></table></td></tr></table>')
