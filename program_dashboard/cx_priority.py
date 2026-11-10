"""The CXCROSS priority order: read at build time from a Confluence page that lists the cross-product projects in priority bands, and match each CXCROSS Initiative to one row of it.

The page is read through the same Jira basic auth the collector already uses (GET {JIRA_BASE_URL}/wiki/rest/api/content/{id}?expand=body.storage). What goes into the payload is small
and internal: `cxPrio` = {"groups": [band labels, in page order], "map": {InitiativeKey: {"g": band index, "r": row position in the page order, "n": the clean page row name}}}.
Nothing else from the page is kept. Any failure (variable unset, no access, HTTP error, timeout, too few rows) returns None with one warning line: the build never fails because of this step.

Parsing (standard library only):
  * Every top-level table is read. A table whose header row has a "Global Priority" column puts each row in the band named by that column ("Global Priority - 2"; text such as "Watch List" is used as it is).
    Any other table is read in band-row mode: a band row sits between the project rows and names the band of the rows below it.
  * A band row is a row with a single cell, or a row whose only filled cell is the first one AND whose text is a known band label (Global Priority - N, Ending, Watch List, On Hold).
    (A project row that has a name and nothing else is therefore still a project row.)
  * A project row's name is the text of the first link or bold text of its first cell, never the owner name or the "Individual Report" link; without either, the first line of the cell.
Matching: see match_initiatives (an explicit Jira key in the row wins; otherwise normalised names).
Overrides: the optional environment variable CXCROSS_PRIORITY_OVERRIDES, a JSON object {"<Initiative key>": "<page row name>"}, pins an Initiative to a row by name and wins over every automatic rule (see apply_overrides).
"""
from __future__ import annotations

import html as _html
import json
import re
import sys
from html.parser import HTMLParser

MIN_ROWS = 3                      # fewer parsed rows than this means the page was not understood: no field
KEY_RX = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
BAND_RX = re.compile(r"^(global priority\s*[-–—:]?\s*\d+|ending|watch\s*list|on hold)$", re.I)
GP_HEAD_RX = re.compile(r"global\s+priority", re.I)
STOP = frozenset("the a an of for and to in on with by from at or as is are be into via vs".split())
BLOCKS = {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "tr", "table"}
EMPH = {"a", "ac:link-body", "strong", "b", "u"}
OWNER_LINK_RX = re.compile(r"^individual report$", re.I)


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace(" ", " ")).strip()


class _Cell:
    __slots__ = ("header", "colspan", "blocks", "text_parts", "hrefs")

    def __init__(self, header: bool, colspan: int):
        self.header, self.colspan, self.blocks, self.text_parts, self.hrefs = header, colspan, [], [], []

    @property
    def text(self) -> str:
        return clean(" ".join(self.text_parts))

    @property
    def name(self) -> str:
        """The clean project name: the first emphasised text (link or bold) of the first non-empty line that is not the 'Individual Report' link, else that line."""
        for text, emph in self.blocks:
            if not text:
                continue
            for e in emph:
                if e and not OWNER_LINK_RX.match(e):
                    return e
            return text
        return ""


class _PageParser(HTMLParser):
    """Collects the top-level tables as lists of rows of _Cell. Nested tables flow into the text of the cell that holds them."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[_Cell]]] = []
        self._depth = 0
        self._row: list[_Cell] | None = None
        self._cell: _Cell | None = None
        self._buf: list[str] = []            # text of the current line
        self._emph_depth = 0
        self._emph_buf: list[str] = []
        self._emph: list[str] = []           # emphasised texts of the current line

    def _end_line(self):
        if self._cell is None:
            return
        self._flush_emph()
        text = clean("".join(self._buf))
        if text or self._emph:
            self._cell.blocks.append((text, [clean(e) for e in self._emph]))
        self._buf, self._emph = [], []

    def _flush_emph(self):
        if self._emph_buf:
            t = clean("".join(self._emph_buf))
            if t:
                self._emph.append(t)
            self._emph_buf = []

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._depth += 1
            if self._depth == 1:
                self.tables.append([])
                return
        if self._depth == 1:
            if tag == "tr":
                self._row = []
                self.tables[-1].append(self._row)
                return
            if tag in ("td", "th") and self._row is not None:
                try:
                    span = int(dict(attrs).get("colspan") or 1)
                except ValueError:
                    span = 1
                self._cell = _Cell(tag == "th", span)
                self._row.append(self._cell)
                self._buf, self._emph, self._emph_buf, self._emph_depth = [], [], [], 0
                return
        if self._cell is not None:
            if tag in BLOCKS:
                self._end_line()
            if tag in EMPH:
                self._emph_depth += 1
            if tag == "a":
                href = dict(attrs).get("href")
                if href:
                    self._cell.hrefs.append(href)

    def handle_endtag(self, tag):
        if tag == "table" and self._depth:
            self._depth -= 1
            return
        if self._depth != 1:
            return
        if tag in ("td", "th") and self._cell is not None:
            self._end_line()
            self._cell = None
            return
        if tag == "tr":
            self._row = None
            return
        if self._cell is not None:
            if tag in EMPH and self._emph_depth:
                self._emph_depth -= 1
                if not self._emph_depth:
                    self._flush_emph()
            if tag in BLOCKS:
                self._end_line()

    def handle_data(self, data):
        if self._cell is None:
            return
        self._cell.text_parts.append(data)
        self._buf.append(data)
        if self._emph_depth:
            self._emph_buf.append(data)


def _column_of_priority(row: list[_Cell]) -> int | None:
    col = 0
    for c in row:
        if GP_HEAD_RX.search(c.text):
            return col
        col += max(1, c.colspan)
    return None


def _band_from_value(text: str) -> str | None:
    """The band named by a Global Priority column value: a number N is 'Global Priority - N'; Watch List, Ending, On Hold are used as written; anything else is no band."""
    t = clean(text)
    m = re.match(r"^(\d+)\b", t)
    if m:
        return f"Global Priority - {int(m.group(1))}"
    return t if BAND_RX.match(t) else None


def parse_page(storage_html: str) -> dict:
    """{'groups': [labels in page order], 'rows': [{'g': band index, 'r': position, 'n': name, 'keys': [Jira keys in the row's text and links]}]}."""
    p = _PageParser()
    p.feed(storage_html or "")
    p.close()
    groups: list[str] = []
    rows: list[dict] = []

    def group_index(label: str) -> int:
        if label not in groups:
            groups.append(label)
        return groups.index(label)

    for table in p.tables:
        header = next((r for r in table if r and all(c.header for c in r)), None)
        gp_col = _column_of_priority(header) if header else None
        band = None
        for row in table:
            if not row or all(c.header for c in row):
                continue
            first = row[0]
            rest_filled = any(c.text for c in row[1:])
            if gp_col is None and first.text and (len(row) == 1 or (not rest_filled and BAND_RX.match(first.text))):
                band = first.text
                continue
            name = first.name
            if not name:
                continue
            if gp_col is not None:
                cells, col = {}, 0
                for c in row:
                    cells[col] = c
                    col += max(1, c.colspan)
                label = _band_from_value(cells[gp_col].text) if gp_col in cells else None
            else:
                label = band
            if not label:
                continue
            keys = set()
            for c in row:
                keys.update(KEY_RX.findall(c.text))
                for h in c.hrefs:
                    keys.update(KEY_RX.findall(h))
            rows.append({"g": group_index(label), "r": len(rows), "n": name, "keys": sorted(keys)})
    return {"groups": groups, "rows": rows}


def tokens(text: str) -> list[str]:
    """Lowercase, bracket tags such as [R&D] removed, & and apostrophes joined into the word (R&D = rd), other punctuation a separator, trivial words dropped."""
    t = re.sub(r"\[[^\]]*\]", " ", _html.unescape(text or "")).lower()
    t = re.sub(r"[&'’]", "", t)
    return [w for w in re.split(r"[^\w]+", t) if w and w not in STOP]


def score(page_name: str, title: str):
    """None when the two names do not match, else a tuple that orders matches: (tier, token Jaccard, tokens in common). Tier 2: one name's tokens are all in the other's with at least 2 in common. Tier 1: Jaccard >= 0.6."""
    a, b = set(tokens(page_name)), set(tokens(title))
    if not a or not b:
        return None
    common, union = len(a & b), len(a | b)
    jac = common / union
    if (a <= b or b <= a) and common >= 2:
        return (2, jac, common)
    if jac >= 0.6:
        return (1, jac, common)
    return None


def match_initiatives(rows: list[dict], initiatives: dict[str, str]) -> dict[str, dict]:
    """{Initiative key: the page row it matches}, at most one row each. (a) An explicit Jira key of the Initiative in a row's text or links wins (the earliest such row);
    (b) otherwise the best-scoring row by name (see score); equal scores go to the earliest row; no row that fails both rules, no entry."""
    out = {}
    by_key: dict[str, dict] = {}
    for r in rows:
        for k in r.get("keys") or []:
            by_key.setdefault(k, r)
    for key, title in initiatives.items():
        if key in by_key:
            out[key] = by_key[key]
            continue
        best, best_s = None, None
        for r in rows:
            s = score(r["n"], title)
            if s is not None and (best_s is None or s > best_s):
                best, best_s = r, s
        if best is not None:
            out[key] = best
    return out


def norm_name(text: str) -> str:
    """A name as the matcher reads it (tokens joined): two names are the same row name when this is equal."""
    return " ".join(tokens(text))


def parse_overrides(raw: str | None) -> tuple[dict[str, str], str | None]:
    """({Initiative key: row name}, problem). The variable holds a JSON object of strings; anything else (not JSON, not an object, a value that is not a non-empty string) is ignored whole or entry by entry,
    and `problem` says so in one short phrase (None when all is well or the variable is empty)."""
    if not (raw or "").strip():
        return {}, None
    try:
        obj = json.loads(raw)
    except ValueError:
        return {}, "is not valid JSON"
    if not isinstance(obj, dict):
        return {}, "is not a JSON object"
    good = {str(k).strip(): v.strip() for k, v in obj.items() if isinstance(v, str) and v.strip() and str(k).strip()}
    return good, None if len(good) == len(obj) else "has entries that are not key: row name"


def apply_overrides(rows: list[dict], hier: dict, overrides: dict[str, str]) -> tuple[dict[str, dict], list[str]]:
    """({Initiative key: row}, keys ignored). An override pins the Initiative to the first page row whose name equals the given one after the matcher's normalisation (exact equality of the token strings).
    It is ignored when the key is not an Initiative of the hierarchy (or is Removed) or when no row has that name."""
    out, ignored = {}, []
    for key, name in overrides.items():
        rec = hier.get(key)
        want = norm_name(name)
        row = next((r for r in rows if want and norm_name(r["n"]) == want), None) if rec and rec.get("ty") == "Initiative" and rec.get("s") != "Removed" else None
        if row is None:
            ignored.append(key)
        else:
            out[key] = row
    return out, ignored


def candidate_initiatives(hier: dict) -> dict[str, str]:
    """The Initiatives the CXCROSS table can show: not Removed, and either a CXCROSS issue or the parent of an in-scope Capability (a Capability that is a CXCROSS issue, or sits under a CXCROSS Initiative; not Removed)."""
    def alive_ini(k):
        r = hier.get(k)
        return r if r and r.get("ty") == "Initiative" and r.get("s") != "Removed" else None
    out = {k: r.get("t") or "" for k, r in hier.items() if alive_ini(k) and k.startswith("CXCROSS")}
    for c, r in hier.items():
        if r.get("ty") != "Capability" or r.get("s") == "Removed":
            continue
        par = r.get("par")
        if not alive_ini(par):
            continue
        if c.startswith("CXCROSS") or par.startswith("CXCROSS"):
            out[par] = hier[par].get("t") or ""
    return out


def build_with_notes(hier: dict, storage_html: str, overrides: dict[str, str] | None = None) -> tuple[dict | None, list[str]]:
    """(the payload field, the override keys that were ignored). The field is None when fewer than MIN_ROWS rows parse. An override wins over the automatic match of the same Initiative."""
    page = parse_page(storage_html)
    if len(page["rows"]) < MIN_ROWS:
        return None, []
    matched = match_initiatives(page["rows"], candidate_initiatives(hier))
    pinned, ignored = apply_overrides(page["rows"], hier, overrides or {})
    matched.update(pinned)
    return {"groups": page["groups"], "map": {k: {"g": r["g"], "r": r["r"], "n": r["n"]} for k, r in sorted(matched.items())}}, ignored


def build(hier: dict, storage_html: str, overrides: dict[str, str] | None = None) -> dict | None:
    """The payload field from the page's storage HTML and the hierarchy, or None when fewer than MIN_ROWS rows parse."""
    return build_with_notes(hier, storage_html, overrides)[0]


def fetch_page(session, base: str, page_id: str, timeout: int = 60) -> str:
    """The page's storage-format HTML (raises on any HTTP or network error; compute() catches it)."""
    r = session.get(f"{base.rstrip('/')}/wiki/rest/api/content/{page_id}", params={"expand": "body.storage"}, timeout=timeout)
    r.raise_for_status()
    return r.json()["body"]["storage"]["value"]


def compute(session, base: str, hier: dict, env: dict | None = None) -> dict | None:
    """cxPrio for the payload, or None (with one warning line) when it cannot be built. Never raises."""
    import os
    page_id = ((env if env is not None else os.environ).get("CXCROSS_PRIORITY_PAGE_ID") or "").strip()
    if not page_id:
        print("warning: CXCROSS_PRIORITY_PAGE_ID is not set; the CXCROSS table keeps its title order", flush=True)
        return None
    overrides, problem = parse_overrides((env if env is not None else os.environ).get("CXCROSS_PRIORITY_OVERRIDES"))
    if problem:
        print(f"warning: CXCROSS_PRIORITY_OVERRIDES {problem}; it is ignored (or the bad entries are)", flush=True)
    try:
        res, ignored = build_with_notes(hier, fetch_page(session, base, page_id), overrides)
    except Exception as exc:                                   # HTTP error, timeout, no access, an unexpected page: never fail the build
        print(f"warning: the CXCROSS priority page could not be read ({type(exc).__name__}); the CXCROSS table keeps its title order", flush=True)
        return None
    if res is None:
        print(f"warning: fewer than {MIN_ROWS} rows could be read from the CXCROSS priority page; the CXCROSS table keeps its title order", flush=True)
        return None
    if ignored:
        print(f"warning: CXCROSS priority overrides ignored (no such Initiative, or no page row of that name): {', '.join(ignored)}", flush=True)
    print(f"CXCROSS priority: {len(res['groups'])} bands, {len(res['map'])} Initiatives matched ({len(overrides) - len(ignored)} by override)", flush=True)
    return res


if __name__ == "__main__":                                        # python3 cx_priority.py PAGE.json HIER-PAYLOAD.json : a local check against a saved page and payload (prints counts only)
    import json
    pg = json.load(open(sys.argv[1]))
    d = json.load(open(sys.argv[2]))
    r = build(d["hier"], pg["body"]["storage"]["value"])
    print(None if r is None else {"groups": len(r["groups"]), "matched": len(r["map"])})
