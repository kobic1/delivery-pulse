"""A small JQL evaluator: the subset the Delivery Pulse links use for bugs, customer-found bugs and capitalization, run over the baked records.

Supported: AND, OR, NOT, parentheses; =, !=, >, >=, <, <=, ~, !~; IN / NOT IN (...); IS [NOT] EMPTY (or NULL); quoted strings with \\" escapes; cf[NNNNN] fields.
Anything else (WAS, functions, unknown fields) raises Unsupported, so a test can tell "the oracle cannot judge this" from Malformed ("this query is broken").
Dates are day strings (YYYY-MM-DD); a comparison with a date-only operand compares days, which is the granularity the baked data has.
"""
from __future__ import annotations

import re


class Malformed(Exception):
    pass


class Unsupported(Exception):
    pass


TOKEN = re.compile(r'\s*(?:(?P<str>"(?:[^"\\]|\\.)*")|(?P<cf>cf\[\d+\])|(?P<op>>=|<=|!=|!~|=|<|>|~)|(?P<punct>[(),])|(?P<word>[A-Za-z0-9_][\w.\-]*))')
KEYWORDS = {"AND", "OR", "NOT", "IN", "IS", "EMPTY", "NULL", "WAS", "ON", "CHANGED"}


def tokenize(jql: str):
    out, pos = [], 0
    jql = jql.rstrip()
    while pos < len(jql):
        m = TOKEN.match(jql, pos)
        if not m or m.end() == pos:
            raise Malformed(f"cannot read the query at position {pos}: {jql[pos:pos + 30]!r}")
        pos = m.end()
        kind = m.lastgroup
        val = m.group(kind)
        if kind == "str":
            out.append(("str", re.sub(r'\\(.)', r'\1', val[1:-1])))
        elif kind == "word" and val.upper() in KEYWORDS:
            out.append(("kw", val.upper()))
        else:
            out.append((kind, val))
    return out


class Parser:
    def __init__(self, jql: str):
        self.t = tokenize(jql)
        self.i = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self, kind=None, val=None):
        tok = self.peek()
        if tok[0] is None or (kind and tok[0] != kind) or (val is not None and tok[1] != val):
            raise Malformed(f"expected {val or kind} but found {tok[1]!r} (token {self.i})")
        self.i += 1
        return tok

    def parse(self):
        if not self.t:
            raise Malformed("empty query")
        e = self.or_()
        if self.i != len(self.t):
            raise Malformed(f"unexpected {self.peek()[1]!r} after the query")
        return e

    def or_(self):
        parts = [self.and_()]
        while self.peek() == ("kw", "OR"):
            self.i += 1
            parts.append(self.and_())
        return ("or", parts) if len(parts) > 1 else parts[0]

    def and_(self):
        parts = [self.not_()]
        while self.peek() == ("kw", "AND"):
            self.i += 1
            parts.append(self.not_())
        return ("and", parts) if len(parts) > 1 else parts[0]

    def not_(self):
        if self.peek() == ("kw", "NOT"):
            self.i += 1
            return ("not", self.not_())
        return self.atom()

    def atom(self):
        if self.peek() == ("punct", "("):
            self.i += 1
            e = self.or_()
            self.take("punct", ")")
            return e
        kind, field = self.peek()
        if kind not in ("word", "cf"):
            raise Malformed(f"expected a field but found {field!r}")
        self.i += 1
        k, v = self.peek()
        if k == "op":
            self.i += 1
            return ("cmp", field, v, self.value())
        if (k, v) == ("kw", "IN"):
            self.i += 1
            return ("in", field, False, self.values())
        if (k, v) == ("kw", "NOT"):
            self.i += 1
            self.take("kw", "IN")
            return ("in", field, True, self.values())
        if (k, v) == ("kw", "IS"):
            self.i += 1
            neg = self.peek() == ("kw", "NOT")
            if neg:
                self.i += 1
            if self.peek() not in (("kw", "EMPTY"), ("kw", "NULL")):
                raise Malformed("IS must be followed by EMPTY or NULL")
            self.i += 1
            return ("empty", field, neg)
        if (k, v) in (("kw", "WAS"), ("kw", "CHANGED")):
            raise Unsupported("WAS / CHANGED")
        raise Malformed(f"expected an operator after {field} but found {v!r}")

    def value(self):
        kind, v = self.peek()
        if kind in ("str", "word"):
            self.i += 1
            return v
        raise Malformed(f"expected a value but found {v!r}")

    def values(self):
        self.take("punct", "(")
        out = []
        if self.peek() == ("punct", ")"):
            raise Malformed("an empty list: in ()")
        while True:
            out.append(self.value())
            if self.peek() == ("punct", ","):
                self.i += 1
                continue
            break
        self.take("punct", ")")
        return out


DATE_FIELDS = {"created", "resolutiondate", "updated", "cf[10099]", "cf[10051]", "duedate"}


def _get(issue: dict, field: str):
    f = field.lower()
    if f in issue:
        return issue[f]
    raise Unsupported(f"field {field}")


def _text_match(summary: str, pattern: str) -> bool:
    p = pattern.strip()
    if p.startswith('"') and p.endswith('"') and len(p) > 1:
        p = p[1:-1]
    rx = ".*".join(re.escape(x) for x in p.split("*"))
    return re.search(rx, summary or "", re.I) is not None


def evaluate(node, issue: dict) -> bool:
    kind = node[0]
    if kind == "and":
        return all(evaluate(n, issue) for n in node[1])
    if kind == "or":
        return any(evaluate(n, issue) for n in node[1])
    if kind == "not":
        return not evaluate(node[1], issue)
    if kind == "empty":
        v = _get(issue, node[1])
        empty = v is None or v == "" or v == []
        return (not empty) if node[2] else empty
    if kind == "in":
        v = _get(issue, node[1])
        hit = (v is not None) and (str(v) in node[3] if not isinstance(v, list) else any(str(x) in node[3] for x in v))
        return (not hit) if node[2] else hit
    if kind == "cmp":
        _, field, op, val = node
        v = _get(issue, field)
        if field.lower() == "summary" and op in ("~", "!~"):
            hit = _text_match(v, val)
            return hit if op == "~" else not hit
        if isinstance(v, list):                                          # labels: != matches an issue that lacks the value
            has = val in v
            if op == "=":
                return has
            if op == "!=":
                return not has
            raise Unsupported(f"{field} {op}")
        if op in ("~", "!~"):
            raise Unsupported(f"{field} {op}")
        if v is None:
            return op == "!="
        if field.lower() in DATE_FIELDS:
            a, b = str(v)[:10], str(val)[:10]
        elif isinstance(v, (int, float)):
            try:
                a, b = float(v), float(val)
            except ValueError:
                return False
        else:
            a, b = str(v), str(val)
        return {"=": a == b, "!=": a != b, ">": a > b, ">=": a >= b, "<": a < b, "<=": a <= b}[op]
    raise Malformed(f"internal: {kind}")


def parse(jql: str):
    return Parser(jql).parse()


def count(jql: str, issues: list[dict]) -> int:
    tree = parse(jql)
    return sum(1 for i in issues if evaluate(tree, i))


# ---- the baked records as Jira fields -------------------------------------------------------------------------------------------------------------------------------------------
def bug_issue(b: dict, cfb_account: str) -> dict:
    return {"key": b["k"], "project": b["p"], "issuetype": "Bug", "status": b["s"], "resolution": b.get("rs"), "priority": b.get("pr"),
            "reporter": cfb_account if b.get("rb") else "acct:someone-else", "created": b["cr"], "resolutiondate": b.get("rd"), "cf[10329]": "SF-1" if b.get("sf") else None,
            "cf[10099]": b.get("cl"), "cf[10051]": b.get("rtd"), "cf[10098]": b.get("tm"), "cf[10055]": "Yes" if b.get("rg") else None, "regression": "Yes" if b.get("rg") else None,
            "cf[10068]": b.get("inc"), "summary": ("[Accessibility] " if b.get("ax") else "") + "synthetic bug", "labels": []}


def cap_issues(cap: dict) -> list[dict]:
    import datetime as dt
    epoch = dt.date.fromisoformat(cap["epoch"])
    out = []
    for row in cap["rows"].split(";"):
        n, p, v, sp, cd, t, fb = row.split(",")
        day = (epoch + dt.timedelta(days=int(cd))).isoformat()
        out.append({"key": f"{cap['projects'][int(p)]}-{n}", "project": cap["projects"][int(p)], "issuetype": "Story", "status": "Done", "resolution": "Done",
                    "cf[10099]": None if fb == "1" else day, "resolutiondate": day, "cf[10079]": cap["values"][int(v)] if int(v) >= 0 else None, "cf[10038]": float(sp),
                    "cf[10098]": cap["teams"][int(t)] if int(t) >= 0 else None, "created": day, "summary": "synthetic", "labels": []})
    return out


def pbi_issues(universe_issues: list[dict]) -> list[dict]:
    """The fictitious Power BI scope issues (make_synthetic.pbi_universe) as Jira fields, with ALL their sprints (a link names sprints, so the evaluator needs the whole list, not only the last one)."""
    return [{"key": i["key"], "project": i["project"], "issuetype": i["type"], "status": i["status"], "sprint": [str(s["id"]) for s in i["sprints"]],
             "cf[10079]": i["value"] or None, "cf[10038]": i["sp"], "resolutiondate": i["resolutiondate"], "summary": "synthetic", "labels": []} for i in universe_issues]
