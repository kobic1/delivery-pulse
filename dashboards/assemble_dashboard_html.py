#!/usr/bin/env python3
"""Assemble the 5 chart PNGs + KPI stat values into the single self-contained
dashboard HTML (charts embedded as base64, "Refined Minimal" style: light
background, colored left-border section rails matching each chart's palette,
no pull-quote callout).

Usage:
    python3 assemble_dashboard_html.py --charts-dir charts/ --meta meta.json --out dashboard.html

meta.json schema:
{
  "release": "26.4",
  "project": "PMN",
  "as_of_label": "Jul 16 2026",
  "stats": [
    {"num": "4", "lbl": "Epics delivered", "href": "https://.../issues?jql=..."},
    {"num": "99", "lbl": "Forecast epics"},
    {"num": "27", "lbl": "EDCT days", "href": "https://.../issues?jql=..."},
    {"num": "41", "lbl": "Open bugs", "href": "https://.../issues?jql=..."},
    {"num": "30.8%", "lbl": "AI field adoption", "href": "https://.../issues?jql=..."},
    {"num": "88.9%", "lbl": "Epics by AI", "href": "https://.../issues?jql=..."}
  ],
  "sections": [
    {"file": "chart_delivery.png", "rail": "#1F3A5F", "tint": "rgba(31,58,95,0.06)",
     "seclabel": "Delivery", "title": "Epic Delivery — Actual vs. Expected",
     "caption": "..."},
    ...
  ],
  "footer": "Built from PMN Jira and the R&D Efficiency Power BI dashboard. ..."
}

"href" is optional per stat -- when present the number renders as a real <a> link
(works in every mail client, since it's plain HTML text, not a raster image); when
absent (e.g. "Forecast epics", which has no underlying Jira search) it stays plain
text.
"""
import argparse
import base64
import json
import os

CSS = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><link href="https://fonts.googleapis.com/css2?family=Source+Serif+4:wght@400;600&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">
<style>* { box-sizing: border-box; }

body { font-family:'Inter','Segoe UI',-apple-system,Arial,sans-serif; margin:0; background:#FAFAFA; color:#1A1A1A; }
.wrap { max-width:880px; margin:0 auto; padding:36px; }
.eyebrow { font-size:10.5px; font-weight:700; letter-spacing:0.1em; text-transform:uppercase; color:#1F3A5F; margin-bottom:4px; }
h1 { font-size:22px; margin:0 0 20px; }
/* Stat cards are a table, not flexbox: Outlook's Word engine has no flex support and
   would stack six cards in one column. A 3x2 grid also stops the labels wrapping to
   three lines the way they did when six cards shared one row. */
table.stats { width:100%; table-layout:fixed; border-collapse:separate; border-spacing:0; margin-bottom:30px; }
td.stat { width:32%; background:#ffffff; border:1px solid #E4E4E7; border-radius:8px; padding:14px 16px; vertical-align:top; }
td.gap { width:2%; }
td.rowgap { height:12px; line-height:12px; font-size:0; }
.stat .num { font-size:24px; font-weight:700; color:#1F3A5F; line-height:1.2; font-variant-numeric:tabular-nums; }
.stat a.num { text-decoration:none; border-bottom:1px dotted #1F3A5F; }
.stat .lbl { font-size:12px; color:#5F6368; margin-top:3px; line-height:1.35; }
.section { padding-left:18px; margin-bottom:34px; border-radius:0 8px 8px 0; padding-top:4px; padding-bottom:4px; }
.section .seclabel { font-size:10.5px; font-weight:700; text-transform:uppercase; letter-spacing:0.06em; margin-bottom:4px; }
.section .stitle { font-size:16px; font-weight:600; margin-bottom:12px; }
.section img { width:100%; height:auto; border-radius:4px; }
.section .cap { font-size:12.5px; color:#5F6368; margin-top:9px; line-height:1.55; }
footer { font-size:11.5px; color:#6B6B6B; border-top:1px solid #E4E4E7; padding-top:14px; margin-top:6px; line-height:1.5; }

.aimetrics-card { background:white; border-radius:10px; overflow:hidden; margin-bottom:14px; border:1px solid #eee; }
.aimetrics-h { background-color:#6B21D9; background-image:linear-gradient(135deg,#6B21D9,#6D28D9); color:white; font-size:11px; font-weight:700; letter-spacing:0.04em; text-transform:uppercase; padding:8px 14px; }
table.aimetrics { width:100%; border-collapse:collapse; font-variant-numeric:tabular-nums; font-size:12.5px; }
table.aimetrics th, table.aimetrics td { padding:7px 10px; text-align:right; border-bottom:1px solid #f2f2f2; }
table.aimetrics th:first-child, table.aimetrics td.rowlbl { text-align:left; color:#555; font-weight:500; }
table.aimetrics thead th { color:#666; font-weight:600; font-size:11px; text-transform:uppercase; }
table.aimetrics tr.pctrow td { background:#EEE6FC; font-weight:700; color:#6B21D9; }
table.aimetrics tr.pctrow td.rowlbl { color:#6B21D9; }

</style></head><body><div class="wrap">
"""


def b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--charts-dir", required=True)
    ap.add_argument("--meta", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    meta = json.load(open(args.meta))

    html = [CSS]
    html.append(f'<div class="eyebrow">Release {meta["release"]} · {meta["project"]} · {meta["as_of_label"]}</div>\n')
    html.append(f'<h1>{meta.get("h1", "Delivery, Efficiency, Quality &amp; AI Adoption")}</h1>\n')

    # Charts are plain raster images -- confirmed by Kobi's own test that HTML image
    # maps (per-value clickable regions over a PNG) don't survive his mail client, so
    # that approach (tried and reverted) isn't used here. These stat cards are real
    # HTML text, so a plain <a href> works everywhere a link ever does: wrap the
    # number in one whenever build_and_send.py supplied an "href" for it.
    def stat_cell(s):
        number = (f'<a class="num" href="{s["href"]}" target="_blank">{s["num"]}</a>'
                  if s.get("href") else f'<div class="num">{s["num"]}</div>')
        return f'<td class="stat">{number}<div class="lbl">{s["lbl"]}</div></td>'

    stats = meta["stats"]
    stat_rows = []
    for i in range(0, len(stats), 3):
        chunk = [stat_cell(s) for s in stats[i:i + 3]]
        chunk += ['<td class="stat-empty"></td>'] * (3 - len(chunk))
        stat_rows.append("<tr>" + '<td class="gap"></td>'.join(chunk) + "</tr>")
    html.append('<table class="stats" role="presentation" cellpadding="0" cellspacing="0">'
                + '<tr><td class="rowgap" colspan="5">&nbsp;</td></tr>'.join(stat_rows)
                + "</table>\n")

    for sec in meta["sections"]:
        img_path = os.path.join(args.charts_dir, sec["file"])
        img_b64 = b64(img_path)
        # Colors are inlined, not CSS variables: Outlook and Gmail drop var(), which would
        # silently remove the colored rail and label.
        html.append(
            f'<div class="section" style="border-left:3px solid {sec["rail"]}; '
            f'background-image:linear-gradient(90deg,{sec["tint"]},transparent 55%)">\n'
            f'<div class="seclabel" style="color:{sec["rail"]}">{sec["seclabel"]}</div>'
            f'<div class="stitle">{sec["title"]}</div>\n'
            f'<img src="data:image/png;base64,{img_b64}">'
            f'<div class="cap">{sec["caption"]}</div></div>\n'
        )

    amt = meta.get("ai_metrics_table")
    if amt:
        def render_table(label, rows, months):
            head = "".join(f"<th>{mo}</th>" for mo in months)
            row_class = ' class="pctrow"'
            body = "".join(
                f'<tr{row_class if rowlbl == "%" else ""}>'
                f'<td class="rowlbl">{rowlbl}</td>'
                + "".join(f"<td>{v}</td>" for v in vals) + "</tr>"
                for rowlbl, vals in rows.items()
            )
            return (f'<div class="aimetrics-card"><div class="aimetrics-h">{label}</div>'
                    f'<table class="aimetrics"><thead><tr><th></th>{head}</tr></thead>'
                    f'<tbody>{body}</tbody></table></div>')

        html.append(
            '<div class="section" style="border-left:3px solid #7B4FC7; '
            'background-image:linear-gradient(90deg,rgba(123,79,199,0.06),transparent 55%)">\n'
            '<div class="seclabel" style="color:#7B4FC7">AI Adoption</div>'
            '<div class="stitle">AI Implementer Metrics</div>\n'
            + render_table("EPICS", amt["epics_rows"], amt["months"])
            + render_table("BUG + STORY", amt["bug_story_rows"], amt["months"])
            + f'<div class="cap">Pulled live from {meta["project"]} Jira, bucketed by the Closed '
              f'date field; % is of AI-marked issues that also have an AI Model Used value. As of '
              f'{amt["as_of"]}.</div></div>\n'
        )

    html.append(f'<footer>{meta["footer"]}</footer>\n</div></body></html>')

    with open(args.out, "w") as f:
        f.write("".join(html))
    print(f"wrote {args.out} ({os.path.getsize(args.out)} bytes)")


if __name__ == "__main__":
    main()
