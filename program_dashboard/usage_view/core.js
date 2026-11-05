// core.js: the browser port of usage_report.py lines 1-612 (+ cnt): constants, helpers, loading, the Model, and the Python-semantics helpers every other file uses.
// All files of usage_view/ share ONE scope (see usage_bundle.py); nothing here touches the DOM, the network or `window`.
//
// ---- THE HELPER API (Python semantics that JS gets wrong; never use Math.round, toFixed, String(float), localeCompare in the port) --------------------------------------------------
//   numbers   pyround(x, nd?)  round half to even on the exact value (no nd: an integer result); rnd(x) the report's own; pystr(x, as_float?) = str(x); pyrepr(x) = repr(x);
//             pyfmt(x, spec) = format(x, spec) for [[fill]align][sign][0][width][,][.prec][type] with type in d f F e E g G % s b o x X;  zpad(n, width) = f"{n:0{width}d}"
//             INT vs FLOAT: JS has one number type. pystr(3) is '3'; call pystr(x, true) (or pyfmt(x, '.1f')) where Python holds a float that may be whole (str(3.0) == '3.0').
//   stats     median(xs) = statistics.median (arrays or iterables), mean(xs) = statistics.mean, percentile(xs, p) (the report's own)
//   order     cmp_py(a, b) compares like Python (numbers, strings by code point, arrays/tuples element by element; null vs other throws like Python's TypeError);
//             sorted_py(iterable, key?, reverse?) = sorted(...) (stable, a key may return an array = tuple), min_by(iterable, key?) / max_by(...) = min/max (the FIRST extreme wins, like Python)
//   text      html_escape(x) / e(x) = html.escape(str(x), quote=True); pyfmt, pystr as above; dt_strftime(iso, fmt)
//   dicts     has(o, k) (k in dict, own keys only), dget(o, k, d = null) (dict.get), is_dict(x), len(x) (len of string/array/Set/Map/dict)
//   sets      set_union(...iterables), set_inter(a, b), set_diff(a, b), sorted_set(s) (sorted array)
//   dates     ISO 'YYYY-MM-DD' strings: d_add(d, days), d_diff(a, b) = (a - b).days, d_weekday(d) (Monday 0 .. Sunday 6), d_isocalendar(d) = [year, week, weekday 1..7], d_min = '0001-01-01', EPOCH = '1970-01-01'
//             datetimes (ISO strings with an offset, shown in Israel time like Python's .astimezone(IL)): dt_il_date(iso), dt_il_parts(iso) = {year, month, day, hour, minute, second, offset_minutes, weekday},
//             dt_strftime(iso, fmt) (%Y %y %m %d %e %H %I %M %S %p %b %B %a %A %j %f %z %Z %%), dt_isoformat(iso); ts_il_parts(epoch_seconds) / ts_il_date(epoch_seconds) for datetime.fromtimestamp(t, utc).astimezone(IL)
//   results   jsonable(x) (Set -> sorted array, Map -> object with String keys, undefined/NaN/Infinity -> null, a Model -> null), model_dump(m) (what fixtures.py model_dump gives)
//
// ---- DATA SHAPES of the Model (rule 3 of PORTING.md) ---------------------------------------------------------------------------------------------------------------------------
//   m.ref, m.since, m.cur, m.last, m.cutoff, m.first_day, m.last_day, m.data_start, m.first_week, m.rollover   ISO date strings or null
//   m.quiet Set of dates; m.pre_golive Set of ints; m.counts plain object; m.rows array of {u, day, week, s, v2, ws, glance}; m.people array of ints (sorted); m.weeks array of dates
//   m.by_week      Map date -> array of rows (insertion order as Python's dict); read it with .get(ws) (absent = no visits; Python's defaultdict is never filled by .get), .has(ws), iterate .entries()
//   m.first_seen, m.first_real   Map int -> date          m._memo Map (string keys)
//   m.active(ws) / m.new(ws) / m.established(ws)  Set of ints
//   m.secs(ws)     Map int person -> plain object {section: seconds}   (absent person: m.secs(ws).get(u) is undefined; Python's `.get(u, {})` is `(s.get(u) || {})`)
//   m.ctl(ws)      plain object {control: Set of people}               (absent control: undefined)
//   LV and FA are Maps with int keys (they also answer LV[0] / FA[3] for convenience); every other vocabulary is a plain object; DEVICE_ORDER, WORKDAYS, WEEKEND, V2_MARKERS, KNOWN_SCHEMAS, CONFIDENCE arrays.
//   Object keys that look like integers are reordered by JS (not by Python): the only objects of the port with such keys are in Maps, never plain objects, except in jsonable/model_dump output (string keys).

// ------------------------------------------------------------------------------------------------------------ Python-semantics helpers
function has(o, k) { return o !== null && o !== undefined && Object.prototype.hasOwnProperty.call(o, k); }
function dget(o, k, d = null) { return has(o, k) ? o[k] : d; }
function is_dict(x) { return x !== null && typeof x === "object" && !Array.isArray(x) && !(x instanceof Set) && !(x instanceof Map); }
function len(x) {
  if (typeof x === "string") return Array.from(x).length;
  if (Array.isArray(x)) return x.length;
  if (x instanceof Set || x instanceof Map) return x.size;
  return Object.keys(x).length;
}

// the exact decimal expansion of a finite non-negative double: x = N / 10^k (N a BigInt)
function _dec(x) {
  if (x === 0) return { N: 0n, k: 0 };
  const dv = new DataView(new ArrayBuffer(8));
  dv.setFloat64(0, x);
  const hi = dv.getUint32(0), lo = dv.getUint32(4), eb = (hi >>> 20) & 0x7ff;
  let mant = (BigInt(hi & 0xfffff) << 32n) | BigInt(lo), e;
  if (eb === 0) e = -1074; else { mant |= 1n << 52n; e = eb - 1075; }
  if (e >= 0) return { N: mant << BigInt(e), k: 0 };
  return { N: mant * 5n ** BigInt(-e), k: -e };
}
// round(N / 10^k * 10^nd) half to even, as a BigInt
function _round_at(N, k, nd) {
  const sh = k - nd;
  if (sh <= 0) return N * 10n ** BigInt(-sh);
  const d = 10n ** BigInt(sh);
  let q = N / d;
  const r2 = (N % d) * 2n;
  if (r2 > d || (r2 === d && (q & 1n) === 1n)) q += 1n;
  return q;
}
function _is_neg(x) { return x < 0 || Object.is(x, -0); }

function pyround(x, nd) {
  if (typeof x === "boolean") x = +x;
  const ints = nd === undefined || nd === null;
  if (!Number.isFinite(x)) {
    if (ints) throw new Error(Number.isNaN(x) ? "cannot convert float NaN to integer" : "cannot convert float infinity to integer");
    return x;
  }
  const digits = ints ? 0 : nd, neg = _is_neg(x);
  const { N, k } = _dec(Math.abs(x));
  const q = _round_at(N, k, digits);
  let v;
  if (digits > 0) {
    const s = q.toString().padStart(digits + 1, "0");
    v = Number(s.slice(0, -digits) + "." + s.slice(-digits));
  } else if (digits === 0) v = Number(q.toString());
  else v = Number(q.toString() + "0".repeat(-digits));
  if (ints) return v === 0 ? 0 : (neg ? -v : v);
  return neg ? -v : v;
}

function rnd(x) { return Math.floor(x + 0.5); }                                        // int(math.floor(x + 0.5))

function _float_repr(x) {
  if (Number.isNaN(x)) return "nan";
  if (!Number.isFinite(x)) return x < 0 ? "-inf" : "inf";
  if (x === 0) return Object.is(x, -0) ? "-0.0" : "0.0";
  const neg = x < 0, parts = Math.abs(x).toExponential().split("e");
  const digits = parts[0].replace(".", ""), e10 = parseInt(parts[1], 10);
  let out;
  if (e10 < -4 || e10 >= 16) out = digits[0] + (digits.length > 1 ? "." + digits.slice(1) : "") + "e" + (e10 < 0 ? "-" : "+") + String(Math.abs(e10)).padStart(2, "0");
  else if (e10 >= 0) out = digits.length <= e10 + 1 ? digits + "0".repeat(e10 + 1 - digits.length) + ".0" : digits.slice(0, e10 + 1) + "." + digits.slice(e10 + 1);
  else out = "0." + "0".repeat(-e10 - 1) + digits;
  return (neg ? "-" : "") + out;
}
function _int_str(x) { return Math.abs(x) < 1e21 ? String(x === 0 ? 0 : x) : BigInt(x).toString(); }
function pystr(x, as_float = false) {
  if (x === null || x === undefined) return "None";
  if (x === true) return "True";
  if (x === false) return "False";
  if (typeof x === "number") return Number.isInteger(x) && !as_float ? _int_str(x) : _float_repr(x);
  if (typeof x === "string") return x;
  return pyrepr(x);
}
function _str_repr(s) {
  const q = s.includes("'") && !s.includes('"') ? '"' : "'";
  let out = q;
  for (const ch of s) {
    const c = ch.codePointAt(0);
    if (ch === "\\") out += "\\\\";
    else if (ch === q) out += "\\" + q;
    else if (ch === "\n") out += "\\n";
    else if (ch === "\r") out += "\\r";
    else if (ch === "\t") out += "\\t";
    else if (c < 32 || c === 127) out += "\\x" + c.toString(16).padStart(2, "0");
    else out += ch;
  }
  return out + q;
}
function pyrepr(x) {
  if (typeof x === "string") return _str_repr(x);
  if (Array.isArray(x)) return "[" + x.map(pyrepr).join(", ") + "]";
  if (x instanceof Set) return x.size ? "{" + Array.from(x).map(pyrepr).join(", ") + "}" : "set()";
  if (x instanceof Map) return "{" + Array.from(x, ([k, v]) => pyrepr(k) + ": " + pyrepr(v)).join(", ") + "}";
  if (x !== null && typeof x === "object") return "{" + Object.keys(x).map(k => _str_repr(k) + ": " + pyrepr(x[k])).join(", ") + "}";
  return pystr(x);
}
function zpad(n, width) { const s = String(Math.abs(n)); return (n < 0 ? "-" : "") + s.padStart(width - (n < 0 ? 1 : 0), "0"); }

function _group(intstr, sep) { return intstr.replace(/\B(?=(\d{3})+(?!\d))/g, sep); }
// the sig+1 digits and decimal exponent of |x| rounded to `sig` significant digits (sig >= 1): {digits: string of sig digits, exp10}
function _sig(x, sig) {
  if (x === 0) return { digits: "0".repeat(sig), exp10: 0 };
  const { N, k } = _dec(x);
  const L = N.toString().length, exp10 = L - 1 - k;
  let q = _round_at(N, k, sig - 1 - exp10), e = exp10;
  if (q.toString().length > sig) { q = q / 10n; e += 1; }
  return { digits: q.toString(), exp10: e };
}
function _fixed(x, p) {                                                                  // |x| with p decimals, half to even on the exact value
  const { N, k } = _dec(x), q = _round_at(N, k, p);
  if (p === 0) return q.toString();
  const s = q.toString().padStart(p + 1, "0");
  return s.slice(0, -p) + "." + s.slice(-p);
}
function _expo(x, p, upper) {
  const { digits, exp10 } = _sig(x, p + 1);
  return digits[0] + (p > 0 ? "." + digits.slice(1) : "") + (upper ? "E" : "e") + (exp10 < 0 ? "-" : "+") + String(Math.abs(exp10)).padStart(2, "0");
}
function pyfmt(x, spec) {
  spec = spec === undefined || spec === null ? "" : String(spec);
  const m = /^(?:(.)?([<>=^]))?([+\- ])?(#)?(0)?(\d+)?([,_])?(?:\.(\d+))?([bcdeEfFgGnosxXr%])?$/s.exec(spec);
  if (!m) throw new Error("Invalid format specifier '" + spec + "'");
  let fill = m[1], align = m[2];
  const sign = m[3] || "-", alt = !!m[4], zero = !!m[5], width = m[6] ? parseInt(m[6], 10) : 0, sep = m[7], prec = m[8] !== undefined ? parseInt(m[8], 10) : undefined;
  let type = m[9];
  if (typeof x === "boolean") x = +x;
  let body, neg = false, numeric = true;
  if (typeof x === "string") {
    if (type && type !== "s") throw new Error("Unknown format code '" + type + "' for object of type 'str'");
    body = prec !== undefined ? Array.from(x).slice(0, prec).join("") : x;
    numeric = false;
  } else if (typeof x === "number") {
    neg = _is_neg(x);
    const a = Math.abs(x);
    if (type === undefined) type = Number.isInteger(x) ? "d" : (prec === undefined ? "r" : "g");
    if (type === "n") type = Number.isInteger(x) ? "d" : "g";
    if (!Number.isFinite(x)) body = Number.isNaN(x) ? "nan" : "inf";
    else if (type === "d") {
      if (!Number.isInteger(x)) throw new Error("Unknown format code 'd' for object of type 'float'");
      body = BigInt(a).toString();
      if (sep) body = _group(body, sep);
    } else if (type === "b" || type === "o" || type === "x" || type === "X") {
      body = BigInt(a).toString({ b: 2, o: 8, x: 16, X: 16 }[type]);
      if (type === "X") body = body.toUpperCase();
      if (alt) body = "0" + type + body;
    } else if (type === "r") {
      body = _float_repr(a);
      if (sep && !/e/.test(body)) { const i = body.indexOf("."); body = _group(body.slice(0, i), sep) + body.slice(i); }
    }
    else if (type === "f" || type === "F" || type === "%") {
      body = _fixed(type === "%" ? a * 100 : a, prec === undefined ? 6 : prec);
      if (sep) { const i = body.indexOf("."); body = i < 0 ? _group(body, sep) : _group(body.slice(0, i), sep) + body.slice(i); }
      if (alt && !body.includes(".")) body += ".";
      if (type === "%") body += "%";
    } else if (type === "e" || type === "E") body = _expo(a, prec === undefined ? 6 : prec, type === "E");
    else if (type === "g" || type === "G") {
      const p = prec === undefined ? 6 : (prec === 0 ? 1 : prec), { exp10 } = _sig(a, p);
      if (exp10 >= -4 && exp10 < p) {
        body = _fixed(a, p - 1 - exp10);
        if (!alt && body.includes(".")) body = body.replace(/0+$/, "").replace(/\.$/, "");
        if (sep) { const i = body.indexOf("."); body = i < 0 ? _group(body, sep) : _group(body.slice(0, i), sep) + body.slice(i); }
      } else {
        body = _expo(a, p - 1, type === "G");
        if (!alt) body = body.replace(/\.?0+([eE])/, "$1");
      }
    } else throw new Error("Unknown format code '" + type + "' for object of type 'float'");
    if (type === "F" || type === "G" || type === "E") body = body.toUpperCase();
    if (!Number.isFinite(x) && (type === "F" || type === "E" || type === "G")) body = body.toUpperCase();
  } else {
    body = pystr(x);
    numeric = false;
  }
  const sgn = numeric ? (neg ? "-" : (sign === "+" ? "+" : (sign === " " ? " " : ""))) : "";
  if (align === undefined) { if (zero && numeric && Number.isFinite(x)) { fill = "0"; align = "="; } else align = numeric ? ">" : "<"; }
  if (fill === undefined) fill = " ";
  const pad = Math.max(0, width - Array.from(sgn + body).length);
  if (!pad) return sgn + body;
  if (align === "<") return sgn + body + fill.repeat(pad);
  if (align === ">") return fill.repeat(pad) + sgn + body;
  if (align === "=") return sgn + fill.repeat(pad) + body;
  const left = Math.floor(pad / 2);
  return fill.repeat(left) + sgn + body + fill.repeat(pad - left);
}

function html_escape(x) { return pystr(x).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#x27;"); }
function e(x) { return html_escape(x); }

// ---- ordering like Python
function _cmp_str(a, b) {                                                                // by code point, not by UTF-16 unit
  if (a === b) return 0;
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) {
    let x = a.charCodeAt(i), y = b.charCodeAt(i);
    if (x === y) continue;
    if (x >= 0xd800 && x <= 0xdfff && y >= 0xe000) x = 0xf0000 + x;                      // a surrogate (astral) sorts after the rest of the BMP
    else if (y >= 0xd800 && y <= 0xdfff && x >= 0xe000) y = 0xf0000 + y;
    return x < y ? -1 : 1;
  }
  return a.length < b.length ? -1 : (a.length > b.length ? 1 : 0);
}
function cmp_py(a, b) {
  if (typeof a === "boolean") a = +a;
  if (typeof b === "boolean") b = +b;
  if (typeof a === "number" && typeof b === "number") return a < b ? -1 : (a > b ? 1 : 0);
  if (typeof a === "string" && typeof b === "string") return _cmp_str(a, b);
  if (Array.isArray(a) && Array.isArray(b)) {
    const n = Math.min(a.length, b.length);
    for (let i = 0; i < n; i++) { const c = cmp_py(a[i], b[i]); if (c) return c; }
    return a.length < b.length ? -1 : (a.length > b.length ? 1 : 0);
  }
  if ((a === null || a === undefined) && (b === null || b === undefined)) return 0;
  throw new TypeError("'<' not supported between " + pyrepr(a) + " and " + pyrepr(b));
}
function sorted_py(it, key = null, reverse = false) {
  const items = Array.from(it).map(v => ({ v, k: key ? key(v) : v }));
  items.sort(reverse ? (x, y) => cmp_py(y.k, x.k) : (x, y) => cmp_py(x.k, y.k));         // Array.sort is stable: equal elements keep their order, also when reversed (like sorted(..., reverse=True))
  return items.map(o => o.v);
}
function min_by(it, key = null) {
  let best, bk, first = true;
  for (const v of it) { const k = key ? key(v) : v; if (first || cmp_py(k, bk) < 0) { best = v; bk = k; first = false; } }
  if (first) throw new Error("min() arg is an empty sequence");
  return best;
}
function max_by(it, key = null) {
  let best, bk, first = true;
  for (const v of it) { const k = key ? key(v) : v; if (first || cmp_py(k, bk) > 0) { best = v; bk = k; first = false; } }
  if (first) throw new Error("max() arg is an empty sequence");
  return best;
}

// ---- statistics
function median(xs) {
  const a = sorted_py(xs), n = a.length;
  if (!n) throw new Error("no median for empty data");
  return n % 2 ? a[(n - 1) / 2] : (a[n / 2 - 1] + a[n / 2]) / 2;
}
function mean(xs) {
  const a = Array.from(xs);
  if (!a.length) throw new Error("mean requires at least one data point");
  let s = 0;
  for (const v of a) s += v;
  return s / a.length;
}

// ---- sets
function set_union(...sets) { const out = new Set(); for (const s of sets) for (const v of s) out.add(v); return out; }
function set_inter(a, b) { const sb = b instanceof Set ? b : new Set(b), out = new Set(); for (const v of a) if (sb.has(v)) out.add(v); return out; }
function set_diff(a, b) { const sb = b instanceof Set ? b : new Set(b), out = new Set(); for (const v of a) if (!sb.has(v)) out.add(v); return out; }
function sorted_set(s) { return sorted_py(s); }

// ---- dates: ISO 'YYYY-MM-DD' strings (proleptic Gregorian, like datetime.date)
const d_min = "0001-01-01";
const EPOCH = "1970-01-01";
const _MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const _DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
function _days_from_civil(y, m, d) {
  y -= m <= 2 ? 1 : 0;
  const era = Math.floor(y / 400), yoe = y - era * 400, doy = Math.floor((153 * (m + (m > 2 ? -3 : 9)) + 2) / 5) + d - 1, doe = yoe * 365 + Math.floor(yoe / 4) - Math.floor(yoe / 100) + doy;
  return era * 146097 + doe - 719468;
}
function _civil_from_days(z) {
  z += 719468;
  const era = Math.floor(z / 146097), doe = z - era * 146097, yoe = Math.floor((doe - Math.floor(doe / 1460) + Math.floor(doe / 36524) - Math.floor(doe / 146096)) / 365), y = yoe + era * 400;
  const doy = doe - (365 * yoe + Math.floor(yoe / 4) - Math.floor(yoe / 100)), mp = Math.floor((5 * doy + 2) / 153), d = doy - Math.floor((153 * mp + 2) / 5) + 1, m = mp + (mp < 10 ? 3 : -9);
  return [y + (m <= 2 ? 1 : 0), m, d];
}
function _is_leap(y) { return y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0); }
function _dim(y, m) { return [31, _is_leap(y) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]; }
function _ymd(d) { const p = d.split("-"); return [parseInt(p[0], 10), parseInt(p[1], 10), parseInt(p[2], 10)]; }
function _iso(y, m, d) { return String(y).padStart(4, "0") + "-" + String(m).padStart(2, "0") + "-" + String(d).padStart(2, "0"); }
function _epoch_day(d) { const [y, m, dd] = _ymd(d); return _days_from_civil(y, m, dd); }
function d_add(d, days) {
  const [y, m, dd] = _civil_from_days(_epoch_day(d) + days);
  if (y < 1 || y > 9999) throw new RangeError("date value out of range");
  return _iso(y, m, dd);
}
function d_diff(a, b) { return _epoch_day(a) - _epoch_day(b); }
function d_weekday(d) { return (((_epoch_day(d) + 3) % 7) + 7) % 7; }                  // 1970-01-01 was a Thursday (3); Monday is 0
function d_isocalendar(d) {
  const z = _epoch_day(d), wd = d_weekday(d), th = z - wd + 3, ty = _civil_from_days(th)[0];
  const jan1 = _days_from_civil(ty, 1, 1);
  return [ty, Math.floor((th - jan1) / 7) + 1, wd + 1];
}

// datetimes: ISO strings with an offset; shown in Israel time (the report's IL), like `.astimezone(IL)`
const _IL_FMT = new Intl.DateTimeFormat("en-US", { timeZone: "Asia/Jerusalem", hourCycle: "h23", year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric", second: "numeric" });
function ts_il_parts(sec) {
  const t = Math.floor(sec), f = {};
  for (const p of _IL_FMT.formatToParts(new Date(t * 1000))) f[p.type] = parseInt(p.value, 10);
  const day = _iso(f.year, f.month, f.day), hour = f.hour % 24;
  const local_s = hour * 3600 + f.minute * 60 + f.second, utc_s = ((t % 86400) + 86400) % 86400;
  let off = (local_s - utc_s) / 60;
  if (off > 14 * 60) off -= 1440; else if (off < -14 * 60) off += 1440;                // the local and the UTC clock may be on different days
  return { year: f.year, month: f.month, day: f.day, hour, minute: f.minute, second: f.second, offset_minutes: off, weekday: d_weekday(day) };
}
function ts_il_date(sec) { const p = ts_il_parts(sec); return _iso(p.year, p.month, p.day); }

// an ISO datetime 'YYYY-MM-DDTHH:MM[:SS[.ffffff]][Z|+HH:MM]' -> its fields; `off` is null for a naive datetime
function _parse_dt(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:[.,](\d{1,6})\d*)?)?)?\s*(Z|[+-]\d{2}(?::?\d{2})?)?$/.exec(String(s));
  if (!m) throw new Error("Invalid isoformat string: " + pyrepr(s));
  let off = null;
  if (m[8]) off = m[8] === "Z" ? 0 : (m[8][0] === "-" ? -1 : 1) * (parseInt(m[8].slice(1, 3), 10) * 60 + (m[8].length > 3 ? parseInt(m[8].slice(-2), 10) : 0));
  return { y: +m[1], mo: +m[2], d: +m[3], h: m[4] ? +m[4] : 0, mi: m[5] ? +m[5] : 0, s: m[6] ? +m[6] : 0, us: m[7] ? +m[7].padEnd(6, "0") : 0, off, date_only: !m[4] };
}
function _dt_epoch(p) { return Date.UTC(p.y, p.mo - 1, p.d, p.h, p.mi, p.s) / 1000 - (p.off || 0) * 60; }
// the fields in Israel time (a naive datetime is taken as it is, a date has the time 00:00:00)
function dt_il_parts(s) {
  const p = _parse_dt(s);
  if (p.off === null) return { year: p.y, month: p.mo, day: p.d, hour: p.h, minute: p.mi, second: p.s, offset_minutes: null, weekday: d_weekday(_iso(p.y, p.mo, p.d)), microsecond: p.us };
  const q = ts_il_parts(_dt_epoch(p));
  q.microsecond = p.us;
  return q;
}
function dt_il_date(s) { const q = dt_il_parts(s); return _iso(q.year, q.month, q.day); }
function _off_str(off, colon = true) { const a = Math.abs(off), h = Math.floor(a / 60), mi = a % 60; return (off < 0 ? "-" : "+") + String(h).padStart(2, "0") + (colon ? ":" : "") + String(mi).padStart(2, "0"); }
function dt_isoformat(s) {
  const q = dt_il_parts(s);
  return _iso(q.year, q.month, q.day) + "T" + zpad(q.hour, 2) + ":" + zpad(q.minute, 2) + ":" + zpad(q.second, 2) + (q.microsecond ? "." + String(q.microsecond).padStart(6, "0") : "") + (q.offset_minutes === null ? "" : _off_str(q.offset_minutes));
}
function dt_strftime(s, fmt) {
  const q = typeof s === "object" && s !== null ? s : (/^\d{4}-\d{2}-\d{2}$/.test(s) ? Object.assign(dt_il_parts(s), { offset_minutes: null }) : dt_il_parts(s));
  const day = _iso(q.year, q.month, q.day), wd = q.weekday, doy = d_diff(day, _iso(q.year, 1, 1)) + 1;
  return fmt.replace(/%([A-Za-z%])/g, (all, c) => {
    switch (c) {
      case "Y": return String(q.year).padStart(4, "0");
      case "y": return zpad(q.year % 100, 2);
      case "m": return zpad(q.month, 2);
      case "d": return zpad(q.day, 2);
      case "e": return String(q.day).padStart(2, " ");
      case "H": return zpad(q.hour, 2);
      case "I": return zpad(q.hour % 12 || 12, 2);
      case "M": return zpad(q.minute, 2);
      case "S": return zpad(q.second, 2);
      case "p": return q.hour < 12 ? "AM" : "PM";
      case "b": return _MONTHS[q.month - 1].slice(0, 3);
      case "B": return _MONTHS[q.month - 1];
      case "a": return _DAYS[wd].slice(0, 3);
      case "A": return _DAYS[wd];
      case "j": return zpad(doy, 3);
      case "f": return String(q.microsecond || 0).padStart(6, "0");
      case "z": return q.offset_minutes === null ? "" : _off_str(q.offset_minutes, false);
      case "Z": return q.offset_minutes === null ? "" : (q.offset_minutes === 180 ? "IDT" : (q.offset_minutes === 120 ? "IST" : ""));
      case "%": return "%";
      default: return all;
    }
  });
}

// ------------------------------------------------------------------------------------------------------------ constants
let MIN_USERS = 5;                                                                         // the minimum group size (THRESHOLDS["min_group"]; set_min_group changes it for a run)
let SMALL = `<${MIN_USERS} users`;                                                         // what a withheld figure prints
const SHORT_HISTORY_DAYS = 14;
const SECTION_MIN_SECONDS = 30;                                                            // a person "reached" a section in a week with at least this many seconds in it

const THRESHOLDS = {
  min_den: 20,
  baseline_weeks: 6,
  baseline_min: 5,
  band_mad: 3.0,
  floor_people_abs: 3, floor_people_rel: 0.15,
  floor_reach_pp: 10,
  change_people_abs: 3, change_people_rel: 0.20,
  change_reach_pp: 15,
  established_days: 14,
  max_signals_shown: 3,
  weak_active_people: 30,
  s1_min_new: 5,
  s2_weeks_needed: 7, s2_regular_weeks: 3, s2_min_regulars: 10, s2_min_lapsed: 5, s2_lapsed_share: 0.20,
  s3_baseline_weeks_with_readers: 4,
  s4_stop_pct: 10, s4_stop_weeks: 4, s4_stop_consecutive: 2,
  s4_new_pct: 10,
  err_people: 5, err_visit_share: 0.02, err_visit_min: 50, err_consecutive_weeks: 2, err_quiet_days: 14,
  s6_age_days: 7, s6_min_people: 5, s6_min_share: 0.15,
  s7_export_stale_days: 3, s7_dropped_keys_share: 0.05,
  s8_share: 0.15, s8_min_people: 10, s9_share: 0.10,
  growth_weeks: 6, growth_rel: 0.20, growth_abs: 3,
  habit_weeks: 8, habit_min_weeks: 4,
  retention_w1_days: 7, retention_w4_days: 28,
  window_weeks: 4,
  simplify_reach_pct: 10, simplify_weeks: 4,
  reset_rate: 0.25, reset_weeks: 2, reset_min_people: 10, reset_min_visits: 30,
  link_min_clicks: 30, link_min_people: 10,
  event_min: 3, event_days: 3,
  workweek_min_visits: 30,
  retention_weeks: 12,
  min_group: 5,
  show_partial_week: 0,
  heatmap_min_visits: 50,
};

function set_min_group(n) {
  if (typeof n !== "number" || !Number.isInteger(n) || n < 1) throw new Error("min_group must be a whole number of 1 or more");
  MIN_USERS = n;
  SMALL = `<${n} users`;
}

function guard_note(template) {
  return MIN_USERS > 1 ? template.split("{n}").join(String(MIN_USERS)).split("{g}").join(SMALL) : "";
}

function small_rule(cap = false, ribbon = false) {
  let t;
  if (MIN_USERS <= 1) {
    t = "small groups are shown as they are: with few people these numbers describe individual visits, so keep this page private and do not share screenshots of it.";
    return cap || ribbon ? t[0].toUpperCase() + t.slice(1) : t;
  }
  t = `groups under ${MIN_USERS} people ${ribbon ? "show" : "print"} ${SMALL}.`;
  return cap || ribbon ? t[0].toUpperCase() + t.slice(1) : t;
}

// ------------------------------------------------------------------------------------------------------------ the record shape this report reads
const RECORD_SHAPE = {
  record: {
    u: "the opaque user id (read only to drop a duplicated document, never printed)",
    v: "schema version, 1 or 2; any other value is an unknown schema and the document is left out (counted)",
    first: "ISO day (Israel) of the person's first recorded visit; never pruned; anchors cohorts",
    last: "ISO day of the last recorded visit",
    pr: "(v2) 1 = the size cap dropped older weeks of this record",
    w: "{week key: {ISO day: {session id: S}}}; v1 week key = ISO week '2026-W44', v2 week key = 'S' + ISO date of the Sunday 'S2026-10-25'",
  },
  session: {
    t: "opened at: v1 minutes since the epoch (not read by this report), (v2) hours since the epoch (UTC): read only for the hour of the day (Israel time) of the day-and-hour chart",
    s: "active seconds (page visible and focused or with input within 60 s)",
    vs: "(v2) visible seconds, whether or not focused",
    g: "(v2) 1 = glance visit: visible 5 s or more, no input, under 30 s visible",
    sec: "{section key: seconds}; section keys are SECTIONS plus 'top' = the headline tiles before the first section anchor (v2)",
    nav: "{section key: clicks on the Section Strip and the skip links}",
    l: "{section key or 'other': Jira link clicks (middle click included in v2)}",
    o: "{disclosure key: opens}",
    f: "{control key: changes}",
    r: "Refresh presses", rs: "Reset Filters presses", np: "number of projects selected",
    d: "width class 's' | 'm' | 'l'", b: "page version (short commit)",
    bt: "(v2) day number (days since the epoch, Israel day) of the build time of the page version",
    lv: "(v2) 0 live, 1 snapshot only (no connector or Jira access declined), 2 live with a failed step",
    fa: "(v2) data age bucket at the start of the visit: 0 under 1 h, 1 under 24 h, 2 under 72 h, 3 older",
    ro: "(v2) {'ok': n, 'fail': n, 'declined': n} Refresh outcomes", rt: "(v2) Refresh retries",
    er: "uncaught errors (a count, never the message); in v2 real errors only", erb: "(v2) benign notifications (ResizeObserver loop and similar), never flagged",
    lf: "(v2) 1 = the visit started with a non-default filter", rr: "(v2) 1 = Reset Filters pressed after at least one control change in the same visit",
    x: "keys dropped by the 40-key cap",
  },
};
const SESSION_KEYS = new Set(Object.keys(RECORD_SHAPE.session));
const RECORD_KEYS = new Set(Object.keys(RECORD_SHAPE.record));
const V2_MARKERS = ["vs", "bt", "fa", "lv"];                                               // written by every v2 session
const KNOWN_SCHEMAS = [1, 2];

const SECTIONS = { attn: "Needs Attention", burnup: "Delivery", eff: "Efficiency", ai: "AI Adoption", bugs: "Quality", deps: "Dependencies", nfr: "NFRs", cx: "CXCROSS", capview: "Capabilities", cycles: "Cycles", analysis: "Release Analysis" };
const READ_SECTIONS = { top: "Headline tiles", ...SECTIONS };                              // `sec` also has `top` (v2); first on the page
const LINK_SECTIONS = { ...SECTIONS, other: "Outside a section" };
const CONTROLS = { release: "Release", projects: "Projects", multi: "Multi-select toggle", teams: "Teams", dc: "Delivery Cycle", ax: "Accessibility Bugs", cfb: "Customer-Found Bugs", bugpri: "Bug priority",
  gran: "Week, Month or Quarter", cfbgrp: "Customer-found bugs grouping", dp: "Dependencies view", nfrtab: "NFR tabs", cx: "CXCROSS commitment type", caplevel: "Capability commitment level",
  capby: "Capitalization grouping", capmeasure: "Capitalization measure", cycle: "Cycle choice", cytab: "Cycles detail tab", cystatus: "Cycles status filter", cypods: "Pod lists" };
const CONTROL_FAMILIES = [["Scope", ["release", "projects", "multi", "teams"]],
  ["Delivery and cycles", ["dc", "gran", "cycle", "cytab", "cystatus", "cypods"]],
  ["Quality", ["ax", "cfb", "bugpri", "cfbgrp"]],
  ["Dependencies and NFRs", ["dp", "nfrtab"]],
  ["Capabilities and CXCROSS", ["cx", "caplevel", "capby", "capmeasure"]]];
const DISCLOSURES = { how: "How this is calculated", data: "Show data", attn: "Needs Attention details", other: "Other details" };
const DEVICES = { s: "Phone (narrow window)", m: "Tablet (medium window)", l: "Desktop (wide window)" };       // the page records the browser window width: 's' up to 480 px, 'm' up to 900 px, 'l' wider
const DEVICE_ORDER = ["l", "m", "s"];
const DEVICE_CAVEAT = "By browser window width, not device type: a narrow desktop window counts as phone.";
const LV = new Map([[0, "live"], [1, "snapshot only"], [2, "live with a failed step"]]);
const FA = new Map([[0, "under 1 hour old"], [1, "1 to 24 hours old"], [2, "1 to 3 days old"], [3, "older than 3 days"]]);
for (const [k, v] of LV) LV[k] = v;                                                         // LV[0] works as well as LV.get(0)
for (const [k, v] of FA) FA[k] = v;
const RO = { ok: "succeeded", fail: "failed", declined: "declined" };

const WEEK_KEY_RX = /^(\d{4}-W\d{2}|S\d{4}-\d{2}-\d{2})\n?$/;                               // Python's `$` also matches before a final newline
const WORKDAYS = [6, 0, 1, 2, 3];                                                           // Sunday to Thursday (date.weekday(): Monday 0 ... Sunday 6)
const WEEKEND = [4, 5];                                                                     // Friday, Saturday

// ------------------------------------------------------------------------------------------------------------ time
function iso_week_key(d) {
  const [y, w] = d_isocalendar(d);
  return `${y}-W${zpad(w, 2)}`;
}

function week_start(d) {
  return d_add(d, -((d_weekday(d) + 1) % 7));
}

function sunday_key(d) {
  return "S" + week_start(d);
}

function is_complete(ws, ref) {
  return d_add(ws, 6) < ref;
}

function d_label(d) {
  return `${_ymd(d)[2]} ${dt_strftime(d, "%b")}`;
}

function week_label(ws) {
  return `${d_label(ws)} to ${d_label(d_add(ws, 6))}`;
}

// date.fromisoformat (Python 3.9: 'YYYY-MM-DD' only) -> the ISO string, or null
function parse_day(v) {
  if (typeof v !== "string") return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(v);
  if (!m) return null;
  const y = +m[1], mo = +m[2], d = +m[3];
  if (y < 1 || mo < 1 || mo > 12 || d < 1 || d > _dim(y, mo)) return null;
  return v;
}

// ------------------------------------------------------------------------------------------------------------ small numbers and the guards
function is_num(v) {
  return typeof v === "number";
}

function g(users, value) {
  return users === 0 || users >= MIN_USERS ? value : SMALL;
}

function gn(n) {
  return g(n, n);
}

function percentile(xs, p) {
  xs = sorted_py(xs);
  if (xs.length === 1) return xs[0];
  if (!xs.length) throw new Error("list index out of range");
  const k = (xs.length - 1) * p, lo = Math.floor(k), hi = Math.ceil(k);
  return xs[lo] + (xs[hi] - xs[lo]) * (k - lo);
}

// cells: a plain object {name: count} or a Map; the result has the same kind. relations: [[total, [names]]]; hidden: an iterable of names or null
function protect_group(cells, relations, hidden = null) {
  const isMap = cells instanceof Map;
  const keys = isMap ? Array.from(cells.keys()) : Object.keys(cells), val = k => (isMap ? cells.get(k) : cells[k]), inCells = k => (isMap ? cells.has(k) : has(cells, k));
  const out_hidden = new Set(hidden || []);
  for (const k of keys) { const v = val(k); if (0 < v && v < MIN_USERS) out_hidden.add(k); }
  let changed = true;
  while (changed) {
    changed = false;
    for (const [total, names] of relations) {
      if (!(total === 0 || total >= MIN_USERS)) continue;
      const mine = names.filter(inCells);
      if (!mine.some(n => out_hidden.has(n))) continue;
      let rem = total;
      for (const n of mine) if (!out_hidden.has(n)) rem -= val(n);
      if (rem < MIN_USERS) {
        const vis = mine.filter(n => !out_hidden.has(n) && val(n) > 0);
        if (vis.length) {
          out_hidden.add(min_by(vis, n => val(n)));
          changed = true;
        }
      }
    }
  }
  if (isMap) return new Map(keys.map(k => [k, out_hidden.has(k) ? SMALL : val(k)]));
  const out = {};
  for (const k of keys) out[k] = out_hidden.has(k) ? SMALL : val(k);
  return out;
}

function protect_partition(cells, total, hidden = null) {
  return protect_group(cells, [[total, cells instanceof Map ? Array.from(cells.keys()) : Object.keys(cells)]], hidden);
}

function robust_band(values, floor, min_n = 5, mult = 3.0) {
  values = Array.from(values);
  if (values.length < min_n) return null;
  const m = median(values);
  const mad = median(values.map(v => Math.abs(v - m)));
  const half = Math.max(mult * 1.4826 * mad, floor);
  return { median: m, lo: m - half, hi: m + half, half: half, mad: mad, n: values.length, min: Math.min(...values), max: Math.max(...values) };
}

function pct_of(x, d, th = THRESHOLDS) {
  return d >= th["min_den"] && d > 0 ? rnd(100 * x / d) : null;
}

// ------------------------------------------------------------------------------------------------------------ loading
function _unwrap(raw) {
  if (is_dict(raw)) {
    for (const k of ["documents", "docs", "items", "rows", "results"]) {
      if (Array.isArray(raw[k])) return raw[k];
    }
    throw new Error("expected a list of documents (or an object with a list under documents, docs, items, rows or results)");
  }
  if (!Array.isArray(raw)) throw new Error("expected a list of documents");
  return raw;
}

function _doc_id(row, body) {
  for (const src of [body, row]) {
    for (const k of ["u", "id", "doc_id"]) {
      const v = dget(src, k);
      if (typeof v === "string" && v) return v;
    }
  }
  return null;
}

function _n_sessions(body) {
  let n = 0;
  for (const days of Object.values(body["w"] || {})) {
    if (!is_dict(days)) continue;
    for (const s of Object.values(days)) if (is_dict(s)) n += Object.keys(s).length;
  }
  return n;
}

// (bodies, stats) as a two-element array. The id of a document is kept in memory only to drop a duplicated document (the Python report hashes it; nothing here prints it).
function load_export(raw) {
  const rows = _unwrap(raw);
  const stats = { read: rows.length, skipped: 0, duplicates: 0, unknown_schema: 0, no_id: 0, round_page: [100, 500, 1000].includes(rows.length) };
  const out = [], seen = new Map();
  for (const row of rows) {
    if (!is_dict(row)) {
      stats["skipped"] += 1;
      continue;
    }
    const body = is_dict(row["data"]) && (!has(row, "w") || has(row, "id") || has(row, "doc_id")) ? row["data"] : row;
    if (!is_dict(body["w"])) {
      stats["skipped"] += 1;
      continue;
    }
    const v = body["v"];
    if (typeof v === "boolean" || !KNOWN_SCHEMAS.includes(v)) {
      stats["unknown_schema"] += 1;
      continue;
    }
    const did = _doc_id(row, body);
    if (did === null) stats["no_id"] += 1;
    else {
      if (seen.has(did)) {
        stats["duplicates"] += 1;
        const i = seen.get(did);
        if (cmp_py([pystr(body["last"] || ""), _n_sessions(body)], [pystr(out[i]["last"] || ""), _n_sessions(out[i])]) > 0) out[i] = body;      // keep the fuller copy
        continue;
      }
      seen.set(did, out.length);
    }
    out.push(body);
  }
  return [out, stats];
}

function load_bodies(raw) {
  return load_export(raw)[0];
}

function is_v2(s) {
  return V2_MARKERS.some(k => has(s, k));
}

function sessions_of(bodies) {
  const rows = [];
  bodies.forEach((b, u) => {
    for (const [wk, days] of Object.entries(b["w"] || {})) {
      if (!is_dict(days)) continue;
      for (const [day, sess] of Object.entries(days)) {
        const d = parse_day(day);
        if (d === null) continue;
        for (const s of Object.values(sess || {})) {
          if (is_dict(s)) rows.push({ u: u, day: d, week: wk, s: s, v2: is_v2(s) });
        }
      }
    }
  });
  return rows;
}

// ------------------------------------------------------------------------------------------------------------ the calendar (optional)
function parse_calendar(raw) {
  const cal = { releases: [], sprints: [], events: [], quiet_weeks: [], warnings: [] };
  if (!is_dict(raw)) throw new Error("the calendar must be a JSON object");
  for (const r of raw["releases"] || []) {
    const [w1, w6, end] = ["w1", "w6_end", "end"].map(k => (is_dict(r) ? parse_day(dget(r, k)) : null));
    if (!(w1 && w6 && end)) {
      cal["warnings"].push("a release entry of the calendar was skipped (dates missing)");
      continue;
    }
    if (w6 !== d_add(w1, 41)) cal["warnings"].push(`the calendar says the end of W6 is ${w6}, but W1 + 41 days is ${d_add(w1, 41)}: the calendar is not the dashboard's own definition`);
    cal["releases"].push({ release: Array.from(pystr(has(r, "release") ? r["release"] : "")).slice(0, 12).join(""), w1: w1, w6_end: w6, end: end });
  }
  for (const s of raw["sprints"] || []) {
    const [a, b] = ["start", "end"].map(k => (is_dict(s) ? parse_day(dget(s, k)) : null));
    if (a && b) cal["sprints"].push({ no: dget(s, "no"), start: a, end: b });
  }
  for (const k of ["events", "quiet_weeks"]) {
    for (const x of raw[k] || []) {
      const d = parse_day(is_dict(x) ? dget(x, "date") : x);
      if (d) cal[k].push(d);
    }
  }
  return cal;
}

// ------------------------------------------------------------------------------------------------------------ the model: every row of the data window, organised by Sunday-start week
class Model {
  constructor(bodies, ref, since = null, calendar = null, th = null) {
    this.th = th || THRESHOLDS;
    this.ref = ref; this.since = since; this.cal = calendar;
    this.cur = week_start(ref);                                                           // the week in progress
    this.last = d_add(this.cur, -7);                                                      // the last completed week
    this.cutoff = d_add(this.cur, -7 * (this.th["retention_weeks"] - 1));
    this.quiet = new Set(((calendar || {})["quiet_weeks"] || []).map(week_start));
    this.counts = { stale_sessions: 0, future_sessions: 0, before_since: 0, bad_week_key: 0 };
    const rows = [];
    for (const r of sessions_of(bodies)) {
      if (!WEEK_KEY_RX.test(pystr(r["week"]))) this.counts["bad_week_key"] += 1;
      else if (r["day"] > ref) this.counts["future_sessions"] += 1;
      else if (r["day"] < this.cutoff) this.counts["stale_sessions"] += 1;
      else if (since && r["day"] < since) this.counts["before_since"] += 1;
      else {
        r["ws"] = week_start(r["day"]);
        r["glance"] = r["s"]["g"] === 1 || r["s"]["g"] === true;
        rows.push(r);
      }
    }
    this.rows = rows;
    this.by_week = new Map();
    for (const r of rows) {
      if (!this.by_week.has(r["ws"])) this.by_week.set(r["ws"], []);
      this.by_week.get(r["ws"]).push(r);
    }
    this.people = sorted_py(new Set(rows.map(r => r["u"])));
    const earliest = new Map();
    for (const r of rows) {
      if (!earliest.has(r["u"]) || r["day"] < earliest.get(r["u"])) earliest.set(r["u"], r["day"]);
    }
    this.first_seen = new Map(); this.pre_golive = new Set();
    for (const u of this.people) {
      const real = _dmin(parse_day(bodies[u]["first"]) || earliest.get(u), earliest.get(u));
      if (since && real < since) this.pre_golive.add(u);
      this.first_seen.set(u, _dmin(since ? _dmax(real, since) : real, earliest.get(u)));
    }
    this.first_real = new Map();
    for (const u of this.people) this.first_real.set(u, _dmin(parse_day(bodies[u]["first"]) || earliest.get(u), earliest.get(u)));
    this.first_day = rows.length ? rows.reduce((a, r) => (r["day"] < a ? r["day"] : a), rows[0]["day"]) : null;
    this.last_day = rows.length ? rows.reduce((a, r) => (r["day"] > a ? r["day"] : a), rows[0]["day"]) : null;
    const start = since ? _dmax(since, this.cutoff) : this.first_day;
    this.data_start = start;
    this.first_week = start ? week_start(start) : null;
    this.provisional_first = !!(start && start > this.first_week);
    this.weeks = [];                                                                      // the completed weeks from the first week of data
    if (this.first_week) {
      let w = this.first_week;
      while (w <= this.last) {
        this.weeks.push(w);
        w = d_add(w, 7);
      }
    }
    this.n_bodies = bodies.length;
    const cut = d_add(ref, -7 * this.th["retention_weeks"]);
    this.stale_records = bodies.filter(b => (parse_day(b["last"]) || d_min) < cut).length;
    this.pruned_records = bodies.filter(b => b["pr"] === 1 || b["pr"] === true).length;
    this._memo = new Map();
    const v2_weeks = sorted_py(Array.from(this.by_week).filter(([w, rs]) => rs.some(r => r["v2"])).map(([w]) => w));
    const v1_before = v2_weeks.length > 0 && Array.from(this.by_week).some(([w, rs]) => w < v2_weeks[0] && rs.some(r => !r["v2"]));
    this.rollover = v1_before ? v2_weeks[0] : null;                                       // the first week of the new recording rules: it mixes both
  }

  // -- weeks
  is_prov(ws) {
    return this.provisional_first && ws === this.first_week;
  }

  usable(ws) {
    return this.first_week !== null && this.first_week <= ws && ws <= this.last && !this.is_prov(ws);
  }

  n_full_weeks() {
    return this.weeks.filter(w => !this.is_prov(w)).length;
  }

  regime(ws) {
    const rs = this.by_week.get(ws);
    return !rs || !rs.length ? null : (rs.some(r => r["v2"]) ? "v2" : "v1");
  }

  baseline(ws, den_fn = null) {
    const out = [];
    const mine = this.regime(ws) || "v2";
    for (let i = 1; i <= this.th["baseline_weeks"]; i++) {
      const w = d_add(ws, -7 * i);
      if (this.first_week === null || w < this.first_week) break;
      const rg = this.regime(w);
      if (this.is_prov(w) || this.quiet.has(w) || (rg !== null && rg !== mine) || (w === this.rollover && mine === "v2")) continue;
      if (den_fn && den_fn(w) < this.th["min_den"]) continue;
      out.push(w);
    }
    return sorted_py(out);
  }

  // -- people per week
  visits(ws) {
    return this.by_week.get(ws) || [];
  }

  active(ws) {
    const k = "act|" + ws;
    if (!this._memo.has(k)) this._memo.set(k, new Set((this.by_week.get(ws) || []).map(r => r["u"])));
    return this._memo.get(k);
  }

  new(ws) {
    return new Set(Array.from(this.active(ws)).filter(u => this.first_seen.get(u) >= ws));
  }

  established(ws) {
    const cut = d_add(ws, -this.th["established_days"]);
    return new Set(Array.from(this.active(ws)).filter(u => this.first_seen.get(u) <= cut));
  }

  secs(ws) {
    const k = "secs|" + ws;
    if (!this._memo.has(k)) {
      const out = new Map();
      for (const r of this.by_week.get(ws) || []) {
        for (const [key, v] of Object.entries(r["s"]["sec"] || {})) {
          if (has(READ_SECTIONS, key) && is_num(v) && v > 0) {
            if (!out.has(r["u"])) out.set(r["u"], {});
            const o = out.get(r["u"]);
            o[key] = (has(o, key) ? o[key] : 0) + v;
          }
        }
      }
      this._memo.set(k, out);
    }
    return this._memo.get(k);
  }

  ctl(ws) {
    const k = "ctl|" + ws;
    if (!this._memo.has(k)) {
      const out = {};
      for (const r of this.by_week.get(ws) || []) {
        for (const [key, v] of Object.entries(r["s"]["f"] || {})) {
          if (has(CONTROLS, key) && is_num(v) && v > 0) {
            if (!has(out, key)) out[key] = new Set();
            out[key].add(r["u"]);
          }
        }
      }
      this._memo.set(k, out);
    }
    return this._memo.get(k);
  }

  readers(ws, key, among) {
    const s = this.secs(ws);
    let n = 0;
    for (const u of among) if ((s.has(u) && has(s.get(u), key) ? s.get(u)[key] : 0) >= SECTION_MIN_SECONDS) n += 1;
    return n;
  }

  users_of_control(ws, key, among) {
    const c = this.ctl(ws);
    return set_inter(has(c, key) ? c[key] : new Set(), among).size;
  }

  // -- visits
  static engaged(r) {
    return !r["glance"];
  }

  engaged(r) {
    return Model.engaged(r);
  }
}

function _dmin(a, b) { return b < a ? b : a; }                                              // min() of two ISO dates (the first wins a tie)
function _dmax(a, b) { return b > a ? b : a; }

// ------------------------------------------------------------------------------------------------------------ small helpers for the views and the signals
const CONFIDENCE = ["Confirmed", "Corroborated", "Single-source", "Weak signal", "Unknown"];

function gm(x) {
  const v = rnd(x);
  return 0 < v && v < MIN_USERS ? SMALL : pystr(v);
}

function nlabel(v) {
  return v !== SMALL ? `n=${pystr(v)}` : `count withheld: fewer than ${MIN_USERS} people`;
}

function fmt_n(v) {
  return v === SMALL ? v : (v === null || v === undefined ? "-" : (Number.isInteger(v) ? pyfmt(v, ",") : pystr(v)));
}

function share_text(x, d, th = THRESHOLDS) {
  if (x === SMALL) return SMALL;
  if (d === SMALL) return pystr(x);
  const p = pct_of(x, d, th);
  return p !== null ? `${p}%` : `${pystr(x)} (n=${pystr(d)})`;
}

// groups: {name: [set of people, count of visits]} (a plain object or a Map)
function partition_cells(groups) {
  const isMap = groups instanceof Map;
  const entries = isMap ? Array.from(groups.entries()) : Object.entries(groups);
  const cells = isMap ? new Map() : {}, hidden = new Set();
  let total = 0;
  for (const [k, [p, c]] of entries) {
    if (isMap) cells.set(k, c); else cells[k] = c;
    total += c;
    if (0 < len(p) && len(p) < MIN_USERS) hidden.add(k);
  }
  return protect_partition(cells, total, hidden);
}

function window_weeks(m) {
  const k = m.th["window_weeks"];
  let wk = m.weeks.length ? (k === 0 ? m.weeks.slice() : m.weeks.slice(-k)) : [];
  if (m.th["show_partial_week"] && m.by_week.has(m.cur) && !wk.includes(m.cur)) wk = wk.concat([m.cur]);          // the week in progress, to date
  return wk;
}

function cnt(v, noun) {
  return v === SMALL ? SMALL : `${pystr(v)} ${noun}`;
}

// ------------------------------------------------------------------------------------------------------------ results as plain JSON, and the Model dump of the tests
function _jkey(k) {
  if (typeof k === "string") return k;
  if (Array.isArray(k)) return "(" + k.map(pyrepr).join(", ") + (k.length === 1 ? "," : "") + ")";
  return pystr(k);
}
function jsonable(x) {
  if (x === undefined || x === null) return null;
  if (x instanceof Model) return null;
  if (typeof x === "number") return Number.isFinite(x) ? x : null;
  if (typeof x !== "object") return x;
  if (x instanceof Set) return sorted_py(Array.from(x, jsonable));
  if (x instanceof Map) { const o = {}; for (const [k, v] of x) o[_jkey(k)] = jsonable(v); return o; }
  if (Array.isArray(x)) return x.map(jsonable);
  const o = {};
  for (const k of Object.keys(x)) o[k] = jsonable(x[k]);
  return o;
}

function model_dump(m) {
  const weeks_all = sorted_py(m.by_week.keys()), by_week = {};
  for (const w of weeks_all) {
    const secs = {}, ctl = {};
    for (const [u, d] of sorted_py(m.secs(w).entries(), kv => kv[0])) secs[String(u)] = Object.assign({}, d);
    for (const [k, us] of sorted_py(Object.entries(m.ctl(w)), kv => kv[0])) ctl[k] = sorted_py(us);
    by_week[w] = { rows: m.by_week.get(w).length, active: sorted_py(m.active(w)), new: sorted_py(m.new(w)), established: sorted_py(m.established(w)),
      engaged: m.visits(w).filter(r => m.engaged(r)).length, regime: m.regime(w), usable: m.usable(w), prov: m.is_prov(w),
      baseline: m.baseline(w), secs: secs, ctl: ctl };
  }
  const fs = {}, fr = {};
  for (const [u, d] of m.first_seen) fs[String(u)] = d;
  for (const [u, d] of m.first_real) fr[String(u)] = d;
  return jsonable({
    ref: m.ref, since: m.since, cur: m.cur, last: m.last, cutoff: m.cutoff, quiet: sorted_py(m.quiet), counts: m.counts, rows: m.rows.length, people: m.people.slice(),
    first_seen: fs, first_real: fr, pre_golive: sorted_py(m.pre_golive),
    first_day: m.first_day, last_day: m.last_day, data_start: m.data_start, first_week: m.first_week, provisional_first: m.provisional_first, weeks: m.weeks.slice(),
    n_bodies: m.n_bodies, stale_records: m.stale_records, pruned_records: m.pruned_records, rollover: m.rollover, n_full_weeks: m.n_full_weeks(),
    by_week: by_week,
  });
}
