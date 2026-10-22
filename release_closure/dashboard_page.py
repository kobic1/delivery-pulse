"""Release closure dashboard: one self-contained HTML page (no external assets) for presenting on a call.

Look and feel follows the Jira epic dashboard skill: lavender page, white cards with soft indigo shadows,
gradient hero with rings, sticky tabs, KPI tiles with a coloured bar, dotted-underline links into Jira.

    set -a && source .env && set +a
    python3 release_closure/build_report.py --config config_pmn.json     # refresh the data
    python3 release_closure/dashboard_page.py --config config_pmn.json   # -> build/PMN_dashboard.html
"""
from __future__ import annotations

import argparse
import html
import json
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
WEEKS = 12
COLORS = {"26.1": "#86B7FF", "26.2": "#FF6F9B", "26.3": "#C084FC", "26.4": "#7B1FF2"}   # sky, pink, lilac, purple: the brand mesh
FALLBACK = ["#86B7FF", "#FF6F9B", "#C084FC", "#7B1FF2", "#F59E0B", "#16A34A"]


def darker(hex_color, k=0.72):
    """Same hue, darker, so coloured chart labels keep enough contrast on white."""
    h = hex_color.lstrip("#")
    return "#%02X%02X%02X" % tuple(int(int(h[i:i + 2], 16) * k) for i in (0, 2, 4))
pc = lambda n, d: int(100 * n / d + 0.5) if d else 0
esc = html.escape

CSS = """
.nfr{--gx:clamp(16px,4vw,56px);--ink:#1D1730;--ink2:#4D4660;--ink3:#8A839A;--line:#E7E3DC;--panel:#fff;--bg:#F1EFEA;--pur:#8B2CF5;--mag:#D23BB4;--pink:#FF5A8A;--peri:#8E9BFF;--sky:#7DB8FF;--done:#16A34A;--bad:#DC2626;
 background:transparent;color:var(--ink);font-family:'Inter','Helvetica Neue',-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;font-size:15px;line-height:1.45;max-width:none;margin:0;padding-left:env(safe-area-inset-left,0px);padding-right:max(env(safe-area-inset-right,0px),clamp(0px,9vw,190px));min-height:100vh}
.nfr *{box-sizing:border-box}.nfr button{font:inherit;color:inherit}
.hero{position:relative;min-height:170px;padding:30px var(--gx) 18px;display:flex;flex-wrap:wrap;gap:20px 48px;align-items:center;justify-content:space-between;color:var(--ink)}
.hero h1{margin:0;font-size:clamp(38px,4.8vw,68px);line-height:1;font-weight:700;letter-spacing:-.03em;text-transform:lowercase}
.gt{background:linear-gradient(100deg,#8B2CF5 0%,#C132C4 45%,#F0509A 100%);-webkit-background-clip:text;background-clip:text;color:transparent;-webkit-text-fill-color:transparent;padding-bottom:.08em;display:inline-block}
.hero .sub{margin:12px 0 0;font-size:15px;color:var(--ink2);max-width:36rem}.hero .sub b{color:var(--ink)}
.hero .chips{display:flex;gap:8px;flex-wrap:wrap;margin-top:16px}.chip{background:#fff;border:1px solid rgba(139,44,245,.2);border-radius:999px;padding:5px 14px;font-size:13px;color:var(--ink2);backdrop-filter:blur(4px)}
.smile{position:fixed;top:calc(22px + env(safe-area-inset-top,0px));right:calc(30px + env(safe-area-inset-right,0px));width:54px;height:auto;z-index:9}
.rings{display:flex;gap:30px;flex-wrap:wrap;position:relative;color:var(--ink);background:#fff;border:1px solid var(--line);border-radius:22px;padding:18px 28px 16px;box-shadow:0 4px 18px rgba(139,44,245,.16)}.ring{display:flex;flex-direction:column;align-items:center;gap:5px;min-width:7rem;text-align:center}
.ring svg{width:104px;height:104px;display:block}.ring .rl{font-size:14px;font-weight:700;color:var(--ink)}.ring .rc{font-size:12.5px;color:var(--ink2)}
.tabs{position:sticky;top:calc(env(safe-area-inset-top,0px) + 8px);z-index:5;background:rgba(255,255,255,.97);backdrop-filter:blur(8px);border:1px solid var(--line);border-radius:18px;box-shadow:0 2px 10px rgba(139,44,245,.10);display:flex;gap:2px;overflow-x:auto;padding:0 12px;margin:0 var(--gx)}
.tab{background:none;border:0;border-bottom:3px solid transparent;padding:14px 18px;font-weight:600;font-size:14px;color:var(--ink2);cursor:pointer;white-space:nowrap}
.tab:hover{color:var(--pur)}.tzoom{margin-left:auto;align-self:center;background:#fff;border:1px solid rgba(139,44,245,.3);color:var(--pur);border-radius:999px;padding:5px 14px;font-size:13px;font-weight:700;cursor:pointer;white-space:nowrap;flex:none}.tzoom[aria-pressed=true],.tzoom:hover,.tzoom:focus-visible{background:linear-gradient(100deg,#8B2CF5,#E0409F);color:#fff;border-color:transparent;outline:none}.nfr.big{zoom:1.2}
.tab[aria-selected=true]{color:var(--pur);border-image:linear-gradient(90deg,#8B2CF5,#FF5A8A) 1;border-bottom:3px solid;font-weight:700}
.main{padding:18px var(--gx) 32px;display:flex;flex-direction:column;gap:20px}.panel[hidden]{display:none}.panel{display:flex;flex-direction:column;gap:20px}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:20px;padding:16px 18px 14px;box-shadow:0 2px 10px rgba(139,44,245,.07);position:relative;overflow:hidden}
.kpi::before{content:"";position:absolute;left:0;top:0;bottom:0;width:6px;background:var(--c,var(--pur))}
.kpi .v{font-size:32px;font-weight:600;line-height:1.1;letter-spacing:-.02em;font-variant-numeric:tabular-nums}.kpi .l{font-size:14px;color:var(--ink2);margin-top:4px;font-weight:500}
.kpi .d{font-size:12.5px;margin-top:6px;color:var(--ink3)}.up{color:var(--done)}.down{color:var(--bad)}
.sec{background:var(--panel);border:1px solid var(--line);border-radius:20px;padding:18px 22px;box-shadow:0 2px 10px rgba(139,44,245,.07);min-width:0;position:relative}
.sec h2{margin:0 0 2px;font-size:18px;font-weight:700;letter-spacing:-.01em}.sec .nt{margin:0 0 14px;font-size:15px;color:var(--ink2);max-width:60rem}
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,26rem),1fr));gap:20px}
.rcards{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,15rem),1fr));gap:16px}
.rcard{background:var(--panel);border:1px solid var(--line);border-top:5px solid var(--c);border-radius:18px;padding:14px 16px;box-shadow:0 2px 10px rgba(139,44,245,.07)}
.rcard h3{margin:0 0 8px;font-size:17px;font-weight:700;display:flex;justify-content:space-between;align-items:baseline}.rcard h3 small{font-weight:400;color:var(--ink2);font-size:12px}
.rcard dl{margin:0;display:grid;grid-template-columns:1fr auto;gap:6px 10px;font-size:15px}.rcard dt{color:var(--ink2)}.rcard dd{margin:0;font-weight:700;font-variant-numeric:tabular-nums;text-align:right}
.tw{overflow-x:auto;min-width:0}.tw table{min-width:34rem}table{border-collapse:collapse;width:100%;font-size:16px;font-variant-numeric:tabular-nums}
th{font-size:12.5px;text-transform:uppercase;letter-spacing:.4px;color:var(--ink2);font-weight:700;text-align:right;padding:8px 8px;border-bottom:1px solid var(--line)}
td{padding:11px 8px;border-bottom:1px solid var(--line);text-align:right}th:first-child,td:first-child{text-align:left}td:first-child{font-weight:700}
td.h{text-align:center;padding:11px 0;font-size:14px;border-bottom:1px solid #fff;border-right:1px solid #fff}
a.fig{color:inherit;text-decoration:underline dotted;text-underline-offset:3px}a.fig:hover{color:var(--pur)}
.legend{display:flex;gap:20px;flex-wrap:wrap;font-size:14px;color:var(--ink2);margin:6px 0 0}.legend i{display:inline-block;width:20px;height:5px;border-radius:3px;margin-right:6px;vertical-align:middle}
.foot{font-size:13px;color:var(--ink2);line-height:1.6}.foot b{color:var(--ink2)}
svg text{font-family:inherit}.chart{width:100%;height:auto;display:block}.chartbox{cursor:zoom-in;overflow-x:auto;min-width:0}.chartbox .chart{min-width:520px}.panel:not(#p-overview) .chart{max-width:940px;margin-inline:auto}
.xbtn{position:absolute;top:14px;right:16px;background:#fff;border:1px solid rgba(139,44,245,.3);color:var(--pur);border-radius:999px;padding:5px 15px;font-size:12px;font-weight:700;cursor:pointer;box-shadow:0 1px 4px rgba(139,44,245,.15)}
.xbtn:hover,.xbtn:focus-visible{background:linear-gradient(100deg,#8B2CF5,#E0409F);color:#fff;border-color:transparent;outline:none}
#zoom{--ink:#1D1730;--ink2:#4D4660;--line:#E7E3DC;--pur:#8B2CF5;font-family:'Inter','Helvetica Neue',-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;position:fixed;inset:0;z-index:50;background:rgba(29,23,48,.8);display:flex;align-items:center;justify-content:center;padding:max(2vh,env(safe-area-inset-top,0px)) max(2vw,env(safe-area-inset-right,0px)) max(2vh,env(safe-area-inset-bottom,0px)) max(2vw,env(safe-area-inset-left,0px))}#zoom[hidden]{display:none}
.zbox{background:#fff;border-radius:24px;box-shadow:0 24px 70px rgba(29,23,48,.5);width:min(96vw,1800px);max-height:96vh;overflow:auto;padding:28px 36px 24px;position:relative}
.zbox h2{margin:0 0 4px;font-size:clamp(24px,2.4vw,38px);font-weight:700;letter-spacing:-.02em;color:var(--ink)}.zbox .nt{margin:0 0 14px;font-size:clamp(13px,1.2vw,18px);color:var(--ink2);max-width:75rem}
.zbox .chart{width:100%;height:auto;max-height:70vh;max-width:none;min-width:0}.zbox .legend{font-size:clamp(14px,1.3vw,20px);gap:26px;margin-top:10px}.zbox .legend i{width:32px;height:7px}
.zclose{position:absolute;top:18px;right:22px;background:linear-gradient(100deg,#8B2CF5,#E0409F);color:#fff;border:0;border-radius:999px;padding:9px 20px;font-size:14px;font-weight:700;cursor:pointer}.zclose:hover,.zclose:focus-visible{filter:brightness(1.08);outline:none}
@media(max-width:1000px){.kpis{grid-template-columns:repeat(2,1fr)}}@media(max-width:560px){.kpis{grid-template-columns:1fr}}
@media(max-width:1200px){.smile{display:none}}@media(max-width:720px){.tabs{position:static}.hero h1{font-size:38px}}
@media print{.tabs{display:none}.panel[hidden]{display:flex}}
"""


def fig(base, jql, text):
    if not jql:
        return str(text)
    return f'<a class="fig" target="_blank" rel="noopener" href="{esc(base)}/issues/?jql={quote(jql)}">{text}</a>'


def cumulative(r):
    acc, out = r["buckets"]["0pre"], []
    for w in range(1, WEEKS + 1):
        acc += r["buckets"][str(w)]
        out.append(pc(acc, r["baseline"]))
    return out


def ring(pct_val, color, label, caption):
    c = 2 * 3.14159 * 36
    off = c * (1 - min(pct_val, 100) / 100)
    gid = "rg" + str(abs(hash(label)) % 100000)
    return (f'<div class="ring"><svg viewBox="0 0 88 88" role="img" aria-label="{esc(label)} {pct_val}%"><defs><linearGradient id="{gid}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#8B2CF5"/><stop offset="1" stop-color="#FF5A8A"/></linearGradient></defs>'
            f'<circle cx="44" cy="44" r="36" fill="none" stroke="rgba(139,44,245,.13)" stroke-width="9"/>'
            f'<circle cx="44" cy="44" r="36" fill="none" stroke="url(#{gid})" stroke-width="9" stroke-linecap="round" stroke-dasharray="{c:.1f}" stroke-dashoffset="{off:.1f}" transform="rotate(-90 44 44)"/>'
            f'<text x="44" y="51" text-anchor="middle" fill="#1D1730" font-size="21" font-weight="700">{pct_val}%</text></svg>'
            f'<div class="rl">{esc(label)}</div><div class="rc">{esc(caption)}</div></div>')


def nice_max(v):
    import math
    if v <= 0:
        return 10
    mag = 10 ** math.floor(math.log10(v))
    for m in (1, 2, 2.5, 5, 10):
        if m * mag >= v:
            return m * mag
    return 10 * mag


def line_chart(series, ymax, ytitle, ref=None, fmt="{:.0f}", ticks=5):
    """series: [(name, color, [values], bold)]"""
    W, H, L, R, T, B = 640, 290, 46, 66, 14, 34
    pw, ph = W - L - R, H - T - B
    x = lambda i: L + pw * i / (WEEKS - 1)
    y = lambda v: T + ph * (1 - min(v, ymax) / ymax)
    step = ymax / ticks
    o = [f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="{esc(ytitle)}">']
    for k in range(ticks + 1):
        v = step * k
        o.append(f'<line x1="{L}" x2="{W - R}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="#E7E3DC"/><text x="{L - 8}" y="{y(v) + 4:.1f}" text-anchor="end" font-size="12" fill="#6B6480">{fmt.format(v)}</text>')
    if ref is not None:
        o.append(f'<line x1="{L}" x2="{W - R}" y1="{y(ref):.1f}" y2="{y(ref):.1f}" stroke="#16A34A" stroke-dasharray="5 4"/><text x="{W - R + 6}" y="{y(ref) + 4:.1f}" font-size="12.5" font-weight="700" fill="#15803D">plan</text>')
    for i in range(WEEKS):
        o.append(f'<text x="{x(i):.1f}" y="{H - 12}" text-anchor="middle" font-size="12" fill="#6B6480">W{i + 1}</text>')
    ends = sorted(((y(vals[-1]), name, color) for name, color, vals, _ in series), key=lambda e: e[0])
    placed, last_y = {}, -99
    for yy, name, color in ends:
        yy = max(yy, last_y + 13)
        placed[name] = (yy, color)
        last_y = yy
    for name, color, vals, bold in series:
        pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(vals))
        o.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="{3.4 if bold else 2}" stroke-linejoin="round" stroke-linecap="round" opacity="{1 if bold else .8}"/>')
        for i, v in enumerate(vals):
            o.append(f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="{4 if bold else 2.6}" fill="{color}"><title>{esc(name)} · W{i + 1}: {fmt.format(v)}</title></circle>')
        o.append(f'<text x="{x(WEEKS - 1) + 8:.1f}" y="{placed[name][0] + 4:.1f}" font-size="12.5" font-weight="700" fill="{darker(color)}">{esc(name)}</text>')
    o.append("</svg>")
    return '<div class="chartbox" data-legend="1">' + "".join(o) + "</div>"


def stacked_bars(rows):
    """rows: [(name, color, by_date, after)]"""
    W, rowh, L, R = 640, 50, 52, 56
    mx = max(a + b for _, _, a, b in rows) or 1
    pw = W - L - R
    H = rowh * len(rows) + 28
    o = [f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="Done epics per release, split by release date">']
    for i, (name, color, a, b) in enumerate(rows):
        y0 = 10 + i * rowh
        wa, wb = pw * a / mx, pw * b / mx
        o.append(f'<text x="{L - 10}" y="{y0 + 24}" text-anchor="end" font-size="14" font-weight="700" fill="#1D1730">{esc(name)}</text>')
        o.append(f'<rect x="{L}" y="{y0 + 6}" width="{wa:.1f}" height="28" rx="5" fill="{color}"><title>{a} Done by the release date</title></rect>')
        if b:
            o.append(f'<rect x="{L + wa:.1f}" y="{y0 + 6}" width="{wb:.1f}" height="28" rx="5" fill="{color}" opacity=".35"><title>{b} Done after the release date</title></rect>')
        o.append(f'<text x="{L + wa + wb + 8:.1f}" y="{y0 + 25}" font-size="15" font-weight="700" fill="#1D1730">{a + b}</text>')
    o.append("</svg>")
    return '<div class="chartbox" data-legend="0">' + "".join(o) + "</div>"


def heat(v, hi=(88, 28, 170)):
    k = max(0, min(100, v)) / 100 * 0.92
    bg = tuple(round(255 + (hi[i] - 255) * k) for i in range(3))
    fg = "#fff" if (0.299 * bg[0] + 0.587 * bg[1] + 0.114 * bg[2]) < 140 else "#1D1730"
    return "#%02X%02X%02X" % bg, fg


def build(cfg, data, base, fragment=False):
    rel = data["releases"]
    for r in rel:
        r["buckets"] = {("0pre" if k == "pre" else k): v for k, v in r["buckets"].items()}
        r["cum"] = cumulative(r)
        r["by_date"] = sum(v for k, v in r["buckets"].items() if k != "post")
        r["after_n"] = r["buckets"]["post"]
    first, last, prev = rel[0], rel[-1], rel[-2] if len(rel) > 1 else rel[-1]
    col = lambda r: COLORS.get(r["name"], FALLBACK[rel.index(r) % len(FALLBACK)])
    title = f'{cfg["project"]} · Release closure {first["name"]}–{last["name"]}'
    asof = datetime.now().strftime("%d %b %Y, %H:%M")
    delta = lambda a, b, unit="", good_up=True: (f'<span class="{"up" if (a >= b) == good_up else "down"}">{"▲" if a > b else "▼" if a < b else "="} {abs(a - b)}{unit}</span> vs {prev["name"]}')

    rings = (ring(pc(last["by_date"], last["done"]), "#FFFFFF", "Done by release date", f'{last["by_date"]} of {last["done"]} Done epics')
             + ring(min(pc(last["done"], last["baseline"]), 100), "#FFFFFF", "Delivered after release date", f'{pc(last["done"], last["baseline"])}% of the W1 scope'))
    smile = ('<svg class="smile" viewBox="0 0 60 48" aria-hidden="true"><circle cx="10" cy="9" r="4.6" fill="#fff"/><circle cx="29" cy="9" r="4.6" fill="#fff"/>'
             '<path d="M47 5v8a22 22 0 0 1-22 22v0" fill="none" stroke="#fff" stroke-width="8"/></svg>')
    hero = (f'<header class="hero">{smile}<div><h1><span class="gt">release closure</span></h1>'
            f'<p class="sub"><b>{esc(cfg.get("project_label", cfg["project"]))}</b> · releases {esc(first["name"])}–{esc(last["name"])}. Epics delivered per release, how long they take, how steadily they close, and the open P1 to P3 bug backlog. The rings show {esc(last["name"])}.</p>'
            f'<div class="chips"><span class="chip">12 delivery weeks per release</span><span class="chip">Figures link to Jira</span></div></div>'
            f'<div class="rings" aria-label="Latest release at a glance">{rings}</div></header>')

    kp = [("Done epics", fig(base, last["done_jql"], last["done"]), delta(last["done"], prev["done"]), "#8B2CF5"),
          ("Done by release date", f'{pc(last["by_date"], last["done"])}%', f'{last["by_date"]} of {last["done"]} Done epics', "#FF5A8A"),
          ("Average cycle time", f'{last["cycle_avg"]} days', f'median {last["cycle_med"]} · {delta(last["cycle_avg"], prev["cycle_avg"], "d", False)}', "#7DB8FF"),
          ("Scope at end of W1", fig(base, last.get("baseline_jql", ""), last["baseline"]), f'{prev["name"]}: {prev["baseline"]}', "#C084FC"),
          ("Delivered after release date", f'{pc(last["done"], last["baseline"])}%', f'of the W1 scope · {delta(pc(last["done"], last["baseline"]), pc(prev["done"], prev["baseline"]), "pts")}', "#D23BB4"),
          ("Closed after release date", f'{last["after_n"]}', f'epics Done after {esc(last["end"])} · {prev["name"]}: {prev["after_n"]}', "#8E9BFF"),
          ("Open P1–P3 bugs", f'{last["bugs_weekly"][-1]}', f'end of W12 · {delta(last["bugs_weekly"][-1], prev["bugs_weekly"][-1], "", False)}', "#FF7A59"),
          ("Bugs W1 → W12", f'{last["bugs_weekly"][-1] - last["bugs_weekly"][0]:+d}', f'from {last["bugs_weekly"][0]} to {last["bugs_weekly"][-1]}', "#6B6480")]
    kpis = "".join(f'<div class="kpi" style="--c:{c}"><div class="v">{v}</div><div class="l">{l}</div><div class="d">{d}</div></div>' for l, v, d, c in kp)
    cards = "".join(
        f'<div class="rcard" style="--c:{col(r)}"><h3>{esc(r["name"])}<small>{esc(r["dev_start"])} → {esc(r["end"])}</small></h3><dl>'
        f'<dt>Done epics</dt><dd>{fig(base, r["done_jql"], r["done"])}</dd><dt>Done by release date</dt><dd>{pc(r["by_date"], r["done"])}%</dd>'
        f'<dt>Avg cycle time</dt><dd>{r["cycle_avg"]} d</dd><dt>Scope at W1</dt><dd>{fig(base, r.get("baseline_jql", ""), r["baseline"])}</dd>'
        f'<dt>Delivered after release date</dt><dd>{pc(r["done"], r["baseline"])}%</dd><dt>Open bugs at W12</dt><dd>{r["bugs_weekly"][-1]}</dd></dl></div>' for r in rel)
    overview = (f'<div class="kpis">{kpis}</div><div class="sec"><h2>Release by release</h2><p class="nt">Each card is one release, from its first delivery week to its release date.</p><div class="rcards">{cards}</div></div>'
                f'<div class="cols"><div class="sec"><h2>Predictability</h2><p class="nt">Cumulative epics delivered as a percentage of the scope at the end of W1.</p>'
                f'{line_chart([(r["name"], col(r), r["cum"], r is last) for r in rel], 150, "Cumulative delivery", 100, "{:.0f}%", ticks=3)}</div>'
                f'<div class="sec"><h2>Open P1–P3 bugs</h2><p class="nt">Count at the end of each week.</p>'
                f'{line_chart([(r["name"], col(r), r["bugs_weekly"], r is last) for r in rel], nice_max(max(max(r["bugs_weekly"]) for r in rel)), "Open bugs", ticks=4)}</div></div>')

    trows = "".join(f'<tr><td>{esc(r["name"])}</td><td>{fig(base, r["done_jql"], r["done"])}</td><td>{r["by_date"]}</td><td>{pc(r["by_date"], r["done"])}%</td><td>{r["after_n"]}</td></tr>' for r in rel)
    throughput = (f'<div class="sec"><h2>Throughput</h2><p class="nt">Epics Done per release. The solid part was Done by the release date, the lighter part after it.</p>'
                  f'{stacked_bars([(r["name"], col(r), r["by_date"], r["after_n"]) for r in rel])}</div>'
                  f'<div class="sec"><table><thead><tr><th>Release</th><th>Done epics</th><th>By release date</th><th>% of Done</th><th>After release</th></tr></thead><tbody>{trows}</tbody></table></div>')

    mx = max(r["cycle_avg"] for r in rel) or 1
    crow = "".join(f'<tr><td>{esc(r["name"])}</td><td>{r["cycle_avg"]}</td><td>{r["cycle_med"]}</td><td>{r["cycle_n"]}</td>'
                   f'<td style="width:38%"><div style="background:#F3EEFB;border-radius:6px;height:12px"><div style="width:{pc(r["cycle_avg"], mx)}%;background:{col(r)};height:12px;border-radius:6px"></div></div></td></tr>' for r in rel)
    cycle = (f'<div class="sec"><h2>Cycle time</h2><p class="nt">Average calendar days a Done epic spent in In Progress or Validation, excluding flagged days and Maintenance epics. A few long-running epics lift the average above the median.</p>'
             f'<table><thead><tr><th>Release</th><th>Average (days)</th><th>Median (days)</th><th>Epics</th><th></th></tr></thead><tbody>{crow}</tbody></table></div>')

    head = "".join(f"<th style='text-align:center'>W{w}</th>" for w in range(1, WEEKS + 1))
    prow = ""
    for r in rel:
        cells = "".join(f'<td class="h" style="background:{heat(v)[0]};color:{heat(v)[1]}">{v}%</td>' for v in r["cum"])
        prow += (f'<tr><td>{esc(r["name"])}</td><td>{fig(base, r.get("baseline_jql", ""), r["baseline"])}</td>{cells}<td><b>{pc(r["done"], r["baseline"])}%</b></td></tr>')
    pred = (f'<div class="sec"><h2>Predictability</h2><p class="nt">Epics delivered so far as a percentage of the scope at the end of W1 (epics in the release then, Committed or empty, excluding Stretch and Removed). 100% means the W1 scope is delivered; above 100% means more was delivered than planned.</p>'
            f'{line_chart([(r["name"], col(r), r["cum"], r is last) for r in rel], 150, "Cumulative delivery", 100, "{:.0f}%", ticks=3)}</div>'
            f'<div class="sec"><table><thead><tr><th>Release</th><th>Scope (epics)</th>{head}<th>After release</th></tr></thead><tbody>{prow}</tbody></table></div>')

    bhead = "".join(f"<th style='text-align:center'>W{w}</th>" for w in range(1, WEEKS + 1))
    bmx = max(max(r["bugs_weekly"]) for r in rel) or 1
    brow = ""
    for r in rel:
        cells = "".join(f'<td class="h" style="background:{heat(v / bmx * 100, (190, 40, 92))[0]};color:{heat(v / bmx * 100, (190, 40, 92))[1]}">{v}</td>' for v in r["bugs_weekly"])
        dd = r["bugs_weekly"][-1] - r["bugs_weekly"][0]
        brow += f'<tr><td>{esc(r["name"])}</td>{cells}<td class="{"up" if dd < 0 else "down" if dd > 0 else ""}"><b>{dd:+d}</b></td></tr>'
    bugs = (f'<div class="sec"><h2>Open P1–P3 bugs</h2><p class="nt">Bugs open at the end of each week, excluding Accessibility bugs (summary mentions Accessibility). A bug counts as closed from its resolution date. These are counts, not percentages.</p>'
            f'{line_chart([(r["name"], col(r), r["bugs_weekly"], r is last) for r in rel], nice_max(bmx), "Open bugs", ticks=4)}</div>'
            f'<div class="sec"><table><thead><tr><th>Release</th>{bhead}<th>W1 → W12</th></tr></thead><tbody>{brow}</tbody></table></div>')

    legend = '<div class="legend">' + "".join(f'<span><i style="background:{col(r)}"></i>{esc(r["name"])}</span>' for r in rel) + "</div>"
    foot = (f'<div class="foot"><b>How to read it.</b> Each release has an IP (planning) week, then 12 delivery weeks (4 sprints) ending on the release date; W1 is the first delivery week. '
            f'Epics Done during the IP week count from W1. Done date is the last move into Done. Cycle time does not count the Done day. Colours: lighter shades are lower values. '
            f'Source: Jira ({esc(base.replace("https://", ""))}), refreshed {asof}. Figures with a dotted underline open the matching issues in Jira.</div>')
    tabs = [("overview", "Overview", overview), ("throughput", "Throughput", throughput), ("cycle", "Cycle time", cycle), ("pred", "Predictability", pred), ("bugs", "Bugs backlog", bugs)]
    bar_extra = '<button type="button" class="tzoom" id="tzoom" aria-pressed="false">Larger text</button>'
    bar = "".join(f'<button class="tab" role="tab" id="t-{k}" aria-selected="{"true" if i == 0 else "false"}" aria-controls="p-{k}" data-t="{k}">{n}</button>' for i, (k, n, _) in enumerate(tabs)) + bar_extra
    tabs = [(k, n, c.replace("<table>", '<div class="tw"><table>').replace("</table>", "</table></div>")) for k, n, c in tabs]
    panels = "".join(f'<section class="panel" role="tabpanel" id="p-{k}" aria-labelledby="t-{k}"{"" if i == 0 else " hidden"}>{c}{legend if k != "overview" else ""}</section>' for i, (k, _, c) in enumerate(tabs))
    zjs = ("(function(){var z=document.getElementById('zoom'),body=z.querySelector('.zbody'),last=null;"
           "function open(sec,btn){var cb=sec.querySelector('.chartbox');last=btn;var h=sec.querySelector('h2'),n=sec.querySelector('.nt');"
           "var lg=cb.dataset.legend==='1'?document.getElementById('lg').innerHTML:'';"
           "body.innerHTML='<h2>'+h.textContent+'</h2>'+(n?'<p class=\"nt\">'+n.textContent+'</p>':'')+cb.innerHTML+lg;"
           "z.hidden=false;document.body.style.overflow='hidden';z.querySelector('.zclose').focus()}"
           "function close(){z.hidden=true;body.innerHTML='';document.body.style.overflow='';if(last)last.focus()}"
           "document.querySelectorAll('.chartbox').forEach(function(cb){var sec=cb.closest('.sec');var b=document.createElement('button');b.type='button';b.className='xbtn';b.textContent='Expand';"
           "b.setAttribute('aria-label','Expand chart: '+sec.querySelector('h2').textContent);b.addEventListener('click',function(e){e.stopPropagation();open(sec,b)});sec.appendChild(b);"
           "cb.addEventListener('click',function(){open(sec,b)})});"
           "z.addEventListener('click',function(e){if(e.target===z)close()});z.querySelector('.zclose').addEventListener('click',close);"
           "document.addEventListener('keydown',function(e){if(e.key==='Escape'&&!z.hidden)close()});window.__zoomOpen=function(){return !z.hidden}})();")
    js = ("document.getElementById('tzoom').addEventListener('click',function(e){var on=document.querySelector('.nfr').classList.toggle('big');e.currentTarget.setAttribute('aria-pressed',on?'true':'false');e.currentTarget.textContent=on?'Normal text':'Larger text'});"
          "document.querySelectorAll('.tab').forEach(function(b){b.addEventListener('click',function(){var k=b.dataset.t;"
          "document.querySelectorAll('.tab').forEach(function(x){x.setAttribute('aria-selected',x===b?'true':'false')});"
          "document.querySelectorAll('.panel').forEach(function(p){p.hidden=p.id!=='p-'+k});window.scrollTo({top:0,behavior:'smooth'})})});"
          "document.addEventListener('keydown',function(e){var t=Array.from(document.querySelectorAll('.tab'));var i=t.findIndex(function(x){return x.getAttribute('aria-selected')==='true'});"
          "if(window.__zoomOpen&&window.__zoomOpen())return;if(e.key==='ArrowRight'&&i<t.length-1)t[i+1].click();if(e.key==='ArrowLeft'&&i>0)t[i-1].click()});")
    mesh = ("body{margin:0;background:radial-gradient(36vw 78vh at 100% 0%,rgba(154,44,242,.95),rgba(154,44,242,0) 70%),radial-gradient(30vw 62vh at 97% 34%,rgba(255,90,135,.95),rgba(255,90,135,0) 72%),"
            "radial-gradient(36vw 78vh at 100% 100%,rgba(125,184,255,.98),rgba(125,184,255,0) 70%),radial-gradient(28vw 52vh at 90% 64%,rgba(201,166,250,.7),rgba(201,166,250,0) 72%),#F1EFEA;background-attachment:fixed}")
    page = (f'<div class="nfr">{hero}<nav class="tabs" role="tablist">{bar}</nav><main class="main">{panels}{foot}</main></div><template id="lg">{legend}</template>'
            f'<div id="zoom" role="dialog" aria-modal="true" aria-label="Expanded chart" hidden><div class="zbox"><button type="button" class="zclose">Close (Esc)</button><div class="zbody"></div></div></div>'
            f'<script>{js}{zjs}</script>')
    if fragment:   # for publishing: the platform adds doctype, head and body
        return (f'<title>{esc(cfg["project"])} Release Closure</title><meta name="claude:viewport-fit-sides" content="cover">'
                '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
                '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap">'
                f'<style>{mesh}{CSS}</style>{page}')
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)}</title>'
            f'<style>{mesh}{CSS}</style></head><body>{page}</body></html>')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--artifact", action="store_true", help="write the publishable fragment (no doctype/head/body)")
    a = ap.parse_args()
    cfg = json.loads((HERE / a.config).read_text())
    data = json.loads((HERE / "build" / f'{cfg.get("slug", cfg["project"])}_release_closure.json').read_text())
    base = os.environ.get("JIRA_BASE_URL", "https://nice-ce-cxone-prod.atlassian.net").rstrip("/")
    out = HERE / "build" / f'{cfg.get("slug", cfg["project"])}_dashboard{"_artifact" if a.artifact else ""}.html'
    out.write_text(build(cfg, data, base, fragment=a.artifact), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
