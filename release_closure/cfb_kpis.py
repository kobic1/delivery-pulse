"""Customer-found bugs (CFB), Regressions and PQCR per release, as a section for the release closure emails.

CFB: Bug, status Done, reported by the CFB account, resolution Fixed or Fixed - Config, bucketed by resolution date
inside the release window (IP week start to release date). Regressions: the same bugs with Regression = Yes.
PQCR: the sum of Number of Incidents over the CFB bugs."""
from __future__ import annotations

from datetime import date, timedelta

import build_report as B

INC, REG = "customfield_10068", "customfield_10055"   # Number of Incidents, Regression
TITLE = "Customer-Found Bugs (CFB)"
SUB = ("Bugs found by customers and fixed (Fixed or Fixed - Config) in each release window. "
       "PQCR is the sum of &ldquo;Number of Incidents&rdquo; across those bugs. Counts, not percentages.")
NOTE = ("CFB: Bug, Done, reported by the CFB account, resolution Fixed or Fixed - Config, bucketed by resolution date within the release window; "
        "Regressions have Regression = Yes; PQCR is the sum of Number of Incidents over those bugs.")


def _iso(d):
    return d.isoformat() if hasattr(d, "isoformat") else str(d)


def cfb_jql(cfg, extra=""):
    return (f'project = {cfg["project"]} AND issuetype = Bug AND status = Done AND reporter = "{cfg["cfb_reporter"]}" '
            f'AND resolution in (Fixed, "Fixed - Config"){extra}')


def window_jql(cfg, r):
    end = date.fromisoformat(_iso(r["end"])) + timedelta(days=1)   # the release date itself is inside the window
    return cfb_jql(cfg, f' AND resolutiondate >= "{_iso(r["start"])}" AND resolutiondate < "{end.isoformat()}"')


def stats(base, s, jql):
    bugs = B.search(base, s, jql, [INC, REG])
    reg = sum(1 for i in bugs if (i["fields"].get(REG) or {}).get("value") == "Yes")
    return {"cfb": len(bugs), "reg": reg, "pqcr": int(sum(i["fields"].get(INC) or 0 for i in bugs)), "jql": jql}


def attach(cfg, base, s, rel):
    """Add r['cfb'] to each release and return the all-time totals."""
    for r in rel:
        r["cfb"] = stats(base, s, window_jql(cfg, r))
    return stats(base, s, cfb_jql(cfg))


def table(m, base, rel, total):
    """m is the email style module (card, link, jql_href, TH, TD, REL, ...), so the table follows each template's look."""
    head = (f'<th scope="col" align="left" style="{m.TH}padding-left:6px;text-align:left;">Release</th>'
            + "".join(f'<th scope="col" align="center" style="{m.TH}text-align:center;">{h}</th>' for h in ("CFB bugs", "Regressions", "PQCR (incidents)")))
    big = f"{m.TD}font-size:15px;font-weight:600;text-align:center;"

    def cell(n, href, last=False):
        inner = f'<span style="color:{m.INK if n == 0 else m.NAVY}">{n}</span>'
        return f'<td align="center" style="{big}{"border-bottom:0;" if last else ""}">{m.link(href, inner)}</td>'

    def row(label, c, last=False, style=None):
        h = m.jql_href(base, c["jql"])
        hr = m.jql_href(base, c["jql"] + " AND regression = Yes")
        return (f'<tr><th scope="row" align="left" style="{style or m.REL}text-align:left;">{label}</th>'
                f'{cell(c["cfb"], h, last)}{cell(c["reg"], hr, last)}{cell(c["pqcr"], h, last)}</tr>')
    body = "".join(row(r["name"], r["cfb"]) for r in rel)
    body += row("All time", total, True, f'padding:9px 4px 9px 6px;font-family:{m.FONT};font-size:13px;font-weight:400;color:{m.SUBTLE};')
    return m.card(f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;"><tr>{head}</tr>{body}</table>')
