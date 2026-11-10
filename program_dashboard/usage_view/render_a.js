// render_a.js: the page helpers, the charts, the key figures and the trend. Literal port of usage_report.py lines 1740-2616 (the CSS string is injected by the bundle).
// `a` is the aggregate as plain JSON (ISO date strings, string keys, arrays for tuples) plus a.model (the JS Model).

const STATUS_WORD = {"flagged": "Flagged", "within": "Within range", "not_tested": "Not tested", "unknown": "Unknown"};


function _shown_signals(sg, th) {
  // All signals, with at most max_signals_shown section or control signals (S3 and S4).
  const out = [];
  let k = 0;
  for (const f of sg["flagged"]) {
    if (f["id"] === "S3" || f["id"] === "S4") {
      k += 1;
      if (k > th["max_signals_shown"]) continue;
    }
    out.push(f);
  }
  return out;
}


function nothing_changed_text(sg) {
  const done = sg["ledger"].filter(r => r["status"] === "within" || r["status"] === "unknown");
  const todo = sg["ledger"].filter(r => r["status"] === "not_tested");
  let s = "Nothing changed beyond the usual week-to-week range. Checked: " + (done.length ? done.map(r => `${r["name"]} (${r["text"]})`).join("; ") : "nothing could be tested yet") + ".";
  if (todo.length) s += " Not tested: " + todo.map(r => `${r["name"]} (${r["text"]})`).join("; ") + ".";
  return s + " This is not a statement that usage is healthy. It covers only people with an id and write access.";
}


function export_warnings(a) {
  // Warnings shown at the top: a stale export, duplicates, unknown records.
  const out = [];
  for (const i of (a["signals"]["data_issues"] || [])) out.push(i.charAt(0).toUpperCase() + i.slice(1));
  return out;
}


// ------------------------------------------------------------------------------------------------------------ the dashboard page (graph first)
const ICON_WARN = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/></svg>';
const ICON_OK = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" d="M9 16.2 4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4z"/></svg>';
function gov() {
  return ["Pseudonymous, not anonymous: a record holds a user id (a code, no name or e-mail); the editors of the published page can read these records.",
          "Kept for 12 weeks: older weeks are removed from a person's record when they next open the page, and the owner also deletes records not seen for 12 weeks.",
          "The exported JSON file is deleted after the report is built. Screenshots of this page carry the same rules as the page.",
          ((MIN_USERS > 1 ? `A group of 0 people prints as 0; a group of ${MIN_USERS === 2 ? '1' : '1 to ' + String(MIN_USERS - 1)} prints as ${SMALL} and its neighbours are withheld when a subtraction would reveal it. ` : "No group is withheld (the minimum group size is 1), so there is no group to protect by subtraction. ")
           + "A percentage prints only when its denominator is 20 or more; below that the counts are printed with n=." + (MIN_USERS > 1 ? "" : " " + small_rule(true))),
          "Wording: say readers of a section, reach and people active. Never rank, name or evaluate people or teams, and never state a reason for a change: a change coincides with, or is associated with, something worth investigating."];
}
const HM_BUCKETS = 5;


// `num` is told by the caller (fl = true) that the figure is a Python float (round(x, 1): vpp, minutes): a JS number has no float type, and Python prints 3.0 as '3.0'.
function num(v, unit = "", fl = false) {
  // A figure for the page: the guard text when the group is small.
  if (v === SMALL) return e(SMALL);
  if (v === null || v === undefined) return "-";
  if (typeof v === "number" && Number.isInteger(v) && !fl) return e(pyfmt(v, ",") + unit);
  return e(pystr(v, fl) + unit);
}


function sh(x, d, th = THRESHOLDS) {
  return e(share_text(x, d, th));
}


function il_stamp(as_of) {
  if (!as_of) return "";
  if (!/(Z|[+-]\d\d:?\d\d)$/.test(as_of)) return as_of.slice(0, 10) + " " + as_of.slice(11, 16) + " Israel time";
  return dt_strftime(as_of, "%Y-%m-%d %H:%M") + " Israel time";
}


// ------------------------------------------------------------------------------------------------------------ chart building blocks
function nice_axis(v) {
  // (top, step) of a value axis that starts at zero: 3 to 5 round gridlines and a little head room above the largest value.
  v = Math.max(v, 1);
  for (const step of [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000, 10000]) {
    if (Math.ceil(v * 1.06 / step) <= 5) return [step * Math.ceil(v * 1.06 / step), step];
  }
  return [Math.trunc(v), Math.trunc(v)];
}


function _grid(top, step) {
  const vals = [];
  for (let v = 0; v < top + 1; v += step) vals.push(v);
  const lines = vals.filter(v => v).map(v => `<i class="gl" style="bottom:${pyfmt(100 * v / top, '.2f')}%"></i>`).join("");
  const labels = vals.map(v => `<span class="yl" style="bottom:${pyfmt(100 * v / top, '.2f')}%">${v}</span>`).join("");
  return [lines, labels];
}


function _legend(items) {
  return '<ul class="leg" aria-hidden="true">' + items.map(([cls, txt]) => `<li><span class="sw ${cls}"></span>${e(txt)}</li>`).join("") + "</ul>";
}


function show_data(inner, label = "Show data") {
  // The table equivalent of a chart, behind a disclosure (a keyboard stop). A wide table scrolls inside its own box, never the page.
  return `<details class="vd"><summary>${e(label)}</summary><div class="scroll" tabindex="0" role="region" aria-label="Data table">${inner}</div></details>`;
}


function panel(title, caption, body, data = "", hid = "", extra_cls = "") {
  // A chart with a title (the metric or the takeaway), a one-line caption (what the marks are and the period), the chart and its data.
  const i = hid ? ` id="${hid}"` : "";
  return `<div class="panel ${extra_cls}"${i}><h3>${e(title)}</h3><p class="cap">${e(caption)}</p>${body}${data}</div>`;
}


function spark(vals, label, part = null) {
  // A sparkline of a weekly series (None = a week that cannot be drawn: a gap). Drawn from 2 points on; autoscaled (a trend shape, not a magnitude).
  // part: per week, True for an incomplete week (the provisional first week, the week in progress). A complete week is the solid line and area with a solid dot on the last one; an incomplete week is a hatched point, joined to its neighbour by a lighter dashed line (no area under it).
  part = part || vals.map(() => false);
  const pts = [];
  vals.forEach((v, i) => { if (typeof v === "number") pts.push([i, v]); });
  if (pts.length < 2) return '<div class="skbar" aria-hidden="true"></div>';
  let lo = Math.min(...pts.map(p => p[1])), hi = Math.max(...pts.map(p => p[1]));
  const pad = (hi - lo) * 0.12 || Math.max(1.0, Math.abs(hi) * 0.1);
  lo = lo - pad; hi = hi + pad;
  const n = Math.max(vals.length - 1, 1);
  const xy = (i, v) => [100 * i / n, 28 - 26 * (v - lo) / (hi - lo) + 1];
  const f2 = (i, v) => { const p = xy(i, v); return pyfmt(p[0], ".2f") + " " + pyfmt(p[1], ".2f"); };
  const runs = [];
  let cur = [];
  vals.forEach((v, i) => {
    if (typeof v === "number") cur.push([i, v]);
    else if (cur.length) { runs.push(cur); cur = []; }
  });
  if (cur.length) runs.push(cur);
  const solid = [], dashed = [];                                                        // the runs of complete weeks, and the segments that touch an incomplete week
  for (const run of runs) {
    let sub = [];
    run.forEach(([i, v], k) => {
      if (part[i]) {
        if (sub.length) { solid.push(sub); sub = []; }
        if (k > 0) dashed.push([run[k - 1], [i, v]]);
        return;
      }
      if (k > 0 && part[run[k - 1][0]]) dashed.push([run[k - 1], [i, v]]);
      sub.push([i, v]);
    });
    if (sub.length) solid.push(sub);
  }
  const d_l = solid.flatMap(run => run.map(([i, v], k) => (k === 0 ? "M" : "L") + f2(i, v))).join(" ");
  const d_a = solid.map(run => run.map(([i, v], k) => (k === 0 ? "M" : "L") + f2(i, v)).join(" ") + ` L${pyfmt(xy(run[run.length - 1][0], 0)[0], ".2f")} 29 L${pyfmt(xy(run[0][0], 0)[0], ".2f")} 29 Z`).join(" ");
  const d_p = dashed.map(([x, y]) => `M${f2(x[0], x[1])} L${f2(y[0], y[1])}`).join(" ");
  let dots = "";
  const full = pts.filter(([i, v]) => !part[i]);
  if (full.length) {
    const [lx, ly] = xy(full[full.length - 1][0], full[full.length - 1][1]);
    dots += `<i class="ld" aria-hidden="true" style="left:${pyfmt(lx, '.1f')}%;top:${pyfmt(100 * ly / 30, '.1f')}%"></i>`;
  }
  for (const [i, v] of pts) {
    if (part[i]) {
      const [lx, ly] = xy(i, v);
      dots += `<i class="ld pt" aria-hidden="true" style="left:${pyfmt(lx, '.1f')}%;top:${pyfmt(100 * ly / 30, '.1f')}%"></i>`;
    }
  }
  const pp = d_p ? `<path class="p" d="${d_p}"/>` : "";
  return (`<div class="sparkwrap"><svg class="spark" viewBox="0 0 100 30" preserveAspectRatio="none" role="img" aria-label="${e(label)}"><path class="a" d="${d_a}"/><path class="l" d="${d_l}"/>${pp}</svg>`
          + `${dots}</div>`);
}


function hbars(rows, scale = "0 to 100% of the people shown", axis = ["0", "50%", "100%"]) {
  // A horizontal bar chart. rows: {label, text (the value as printed), frac (0..1 of the axis, or None), guard (bool), tag, group, alt}. Returns [html, summary of the numbers for the label].
  // A guarded row is a hatched stub of fixed length with the text '<5 users': its length says nothing. Bars start at zero; the axis is the same for every row.
  const out = [], summ = [];
  for (const r of rows) {
    if (r["group"]) {
      out.push(`<div class="hg">${e(r["group"])}</div>`);
      summ.push(r["group"] + ":");
      continue;
    }
    const tag = r["tag"] ? ` <span class="tag">${e(r["tag"])}</span>` : "";
    let bar, val;
    if (r["guard"]) {
      bar = '<i class="gstub"></i>'; val = `<span class="hv g">${e(SMALL)}</span>`;
    } else {
      const w = !r["frac"] ? 0 : Math.max(0.8, Math.min(100.0, 100 * r["frac"]));
      bar = w ? `<i${r["alt"] ? " class=alt" : ""} style="width:${pyfmt(w, '.1f')}%"></i>` : "";
      val = `<span class="hv">${e(r["text"])}</span>`;
    }
    out.push(`<div class="hb"><span class="hl">${e(r["label"])}${tag}</span><span class="ht">${bar}</span>${val}</div>`);
    summ.push(`${r["label"]} ${r["guard"] ? SMALL : r["text"]}`);
  }
  const ax = `<div class="hax" aria-hidden="true"><span><b>${e(axis[0])}</b><b>${e(axis[1])}</b><b>${e(axis[2])}</b></span></div>`;
  return [`<div class="hbars">${out.join("")}${ax}</div>`, summ.join("; ")];
}


function chart_img(inner, label, cls = "", style = "") {
  const s = style ? ` style="${style}"` : "";
  return `<div class="${cls}" role="img" aria-label="${e(label)}"${s}>${inner}</div>`;
}


function stack_bar(cells, names, th = THRESHOLDS, unit = "visits") {
  // A 100% stacked bar of a partition already protected by partition_cells / protect_partition (a withheld cell is SMALL).
  // Only the printed cells are drawn, as shares of the printed cells: a withheld group gets no length, so the bar can never reveal it by subtraction (a bar with a withheld group is drawn only when 2 or more groups remain).
  // Returns [html, summary, drawn]: drawn = the numbers that are on the chart (for the tests).
  const ents = cells instanceof Map ? [...cells.entries()] : Object.entries(cells);
  const shown = ents.filter(([k, v]) => v !== SMALL && v > 0);
  const hidden = ents.filter(([k, v]) => v === SMALL).map(([k, v]) => k);
  const den = shown.reduce((s, [, v]) => s + v, 0);
  const legend = shown.map(([k], i) => `<li><span class="sw c${i % 4 + 1}"></span>${e(names[k])}</li>`);
  for (const k of hidden) legend.push(`<li><span class="sw hg"></span>${e(names[k])}: ${e(SMALL)}</li>`);
  if (shown.length < (hidden.length ? 2 : 1) || !den) {
    const bar = `<div class="sb" aria-hidden="true"><span class="stubfull"><b>${e(hidden.length ? SMALL : "none")}</b></span></div>`;
    return [bar + `<ul class="sl">${legend.join("")}</ul>`, (hidden.map(k => `${names[k]} ${SMALL}`).join("; ") || "none"), []];
  }
  const use_pct = den >= th["min_den"];
  const segs = [], summ = [], drawn = [];
  shown.forEach(([k, v], i) => {
    const p = 100 * v / den;
    const txt = use_pct ? `${rnd(p)}%` : pystr(v);
    drawn.push(txt);
    segs.push(`<span class="c${i % 4 + 1}" style="flex:${pyfmt(p, '.2f')} 1 0">${p >= 9 ? e(txt) : ""}</span>`);
    summ.push(`${names[k]} ${txt}`);
  });
  for (const k of hidden) summ.push(`${names[k]} ${SMALL}`);
  const note = hidden.length ? "share of the " + String(den) + " " + unit + " shown; groups under " + String(MIN_USERS) + " people are left out" : "n=" + String(den) + " " + unit;
  const bar = `<div class="sb" aria-hidden="true">${segs.join("")}</div><ul class="sl">${legend.join("")}</ul>`;
  return [bar, summ.join("; ") + ` (${note})`, drawn];
}


function stack_note(cells, th = THRESHOLDS, unit = "visits") {
  const vals = cells instanceof Map ? [...cells.values()] : Object.values(cells);
  const shown = vals.filter(v => v !== SMALL && v > 0);
  const den = shown.reduce((s, v) => s + v, 0);
  if (!shown.length) return vals.includes(SMALL) ? `Withheld: a group under ${MIN_USERS} people, and the figures next to it would reveal it.` : "";
  if (vals.includes(SMALL)) return `Share of the ${den} ${unit} shown; groups under ${MIN_USERS} people are left out.`;
  return `n=${den} ${unit}` + (den >= th["min_den"] ? "" : " (counts: fewer than 20)");
}


// ------------------------------------------------------------------------------------------------------------ the weekly series behind the key figures
function _ra_get(coll, k) {                    // coll[k] of a Map or of a plain object
  return coll instanceof Map ? coll.get(k) : coll[k];
}


function _comparable_run(m) {
  // The completed weeks that end at the last completed week and share its recording rules (the weeks before a change of the rules, the rollover week and the provisional first week are left out).
  const L = m.last;
  const rg = m.regime(L);
  const run = [];
  let w = L;
  while (rg !== null && rg !== undefined && m.usable(w) && m.regime(w) === rg && !(w === m.rollover && rg === "v2")) {
    run.push(w);
    w = d_add(w, -7);
  }
  return run.sort();
}


function _strip_weeks(m) {
  // The weeks the sparkline strips draw, oldest first, as [(week, partial)]: the comparable run (complete weeks), the provisional first week when it sits right before the run (or is the last completed week), and the week in progress when it has data,
  // all under the same recording rules. The strip is a picture only: the changes, the usual range and the baselines use complete comparable weeks and never these.
  const run = _comparable_run(m);
  const L = m.last;
  let out;
  if (run.length) {
    const rg0 = m.regime(L);
    out = run.map(w => [w, false]);
    if (m.provisional_first && m.first_week === d_add(run[0], -7) && m.regime(m.first_week) === rg0) out.unshift([m.first_week, true]);
  } else if (m.provisional_first && m.first_week === L && m.regime(L) !== null && m.regime(L) !== undefined) {
    out = [[L, true]];
  } else {
    return [];
  }
  const rg = m.regime(out[out.length - 1][0]);
  if (m.by_week.has(m.cur) && m.regime(m.cur) === rg && !(m.cur === m.rollover && rg === "v2")) out.push([m.cur, true]);
  return out;
}


function kpi_period(m) {
  // The period the key figures describe: the last completed week when it can be used; otherwise everything recorded so far (marked 'so far': a period in progress or a provisional first week is never compared with complete weeks).
  const L = m.last;
  if (m.usable(L)) return {"kind": "week", "rows": m.visits(L), "label": week_label(L), "so_far": false};
  if (m.rows.length) {
    let label;
    if (m.first_day >= m.cur) label = `so far, ${d_label(m.cur)} to ${d_label(m.ref)} (week in progress)`;
    else label = `all data so far, ${d_label(m.first_day)} to ${d_label(m.last_day)}`;
    return {"kind": "todate", "rows": m.rows, "label": label, "so_far": true};
  }
  return {"kind": "none", "rows": [], "label": "", "so_far": true};
}


function period_values(rows, th) {
  // The key figures (and the device split) of a set of visits, with the report's guards: engaged visits per active person needs the minimum group of people; the median active minutes needs it among the people with active time.
  const people = new Set(rows.map(r => r["u"]));
  const n = people.size;
  const eng = rows.filter(r => !r["glance"]);
  const pos = eng.filter(r => is_num(r["s"]["s"]) && r["s"]["s"] > 0);
  const mp = new Set(pos.map(r => r["u"]));
  const out = {"n": n, "people": gn(n), "eng": eng.length, "vpp": n >= MIN_USERS ? pyround(eng.length / n, 1) : (n ? SMALL : null),
               "pos": [pos.length, mp.size], "min": pos.length ? g(mp.size, pyround(median(pos.map(r => r["s"]["s"] / 60)), 1)) : null, "dev": device_counts(rows)};
  return out;
}


const DEVICE_SHORT = {"l": "Desktop", "m": "Tablet", "s": "Phone"};


function device_card(dc, th = THRESHOLDS) {
  // The Device key figure of a device_counts result: the largest window-width class with its share of the visits ('Desktop 50%'; on a tie the first of Desktop, Tablet, Phone), and in the sub line the other classes with their shares and the number of visits.
  // Percentages always add up to 100 and carry their n, however small (the owner knows the base from the sub line and the centre of the donut). A class under the minimum group size (or one a printed total would reveal) prints the guard text and the
  // denominator is the printed classes only, so a withheld class can never be rebuilt by subtraction.
  const n = dc["n"];
  if (!n) return {"state": "none"};
  const cells = dc["cells"];
  const hidden = Object.values(cells).includes(SMALL);
  const shown = DEVICE_ORDER.filter(k => cells[k] !== SMALL && cells[k] > 0).map(k => [k, cells[k]]);
  if (!shown.length) return {"state": "hidden"};
  const den = hidden ? shown.reduce((s, [, v]) => s + v, 0) : n;
  const sh_ = device_shares(dc);
  const top = Math.max(...shown.map(([, v]) => v));
  const lead = shown.find(([k, v]) => v === top)[0];
  const rest = ["s", "m", "l"].filter(k => k !== lead);
  const parts = rest.map(k => `${DEVICE_SHORT[k]} ${cells[k] === SMALL ? SMALL : String(sh_[k]) + '%'}`);
  const unit = `${den} visit${den !== 1 ? 's' : ''}` + (hidden ? " shown" : "");
  return {"state": "ok", "fig": `${DEVICE_SHORT[lead]} ${sh_[lead]}%`, "sub": parts.concat([unit]).join(" · "), "desk": ((!hidden && den >= th["min_den"]) ? sh_["l"] : null), "den": den, "hidden": hidden};
}


const DONUT_COLORS = {"l": "#3694FC", "m": "#5B6B8C", "s": "#1C7A6C"};            // NiCE blue, a grey-blue and a teal, each at least 3:1 against white
const DONUT_TEXT = {"l": "#21212B", "m": "#FFFFFF", "s": "#FFFFFF"};               // the label colour on each (4.5:1 or more)
const DONUT_GAP_DEG = 4.0;                                                          // about 2 px of white between neighbouring segments
const DONUT_HATCH_DEG = 14.0;                                                       // the fixed size of the hatched arc of a withheld class: its length says nothing about the class
const DONUT_LABEL_MIN_PCT = 12;                                                     // a segment of this share or more carries its percentage on itself


function device_donut(dc, th = THRESHOLDS) {
  // A small donut of the visits by window-width class, for the Device key figure. Returns [html, label, segments] with segments = [[class, degrees, hidden]] (for the tests).
  // (the long explanation is in usage_report.py)
  const cells = dc["cells"];
  const hidden = DEVICE_ORDER.filter(k => cells[k] === SMALL);
  const shown = DEVICE_ORDER.filter(k => cells[k] !== SMALL && cells[k] > 0).map(k => [k, cells[k]]);
  const den = hidden.length ? shown.reduce((s, [, v]) => s + v, 0) : dc["n"];
  const sh_ = device_shares(dc);
  const avail = 360.0 - DONUT_HATCH_DEG * hidden.length;
  const segs = shown.map(([k, v]) => [k, avail * v / den, false]).concat(hidden.map(k => [k, DONUT_HATCH_DEG, true]));
  const n_seg = segs.length;
  const r = 34.0;
  const circles = [], labels = [];
  let start = 0.0;
  for (const [k, deg, is_hidden] of segs) {
    const length = n_seg === 1 ? deg : Math.max(1.0, deg - DONUT_GAP_DEG);
    const off = start + (n_seg === 1 ? 0 : DONUT_GAP_DEG / 2);
    const stroke = is_hidden ? "url(#dev-hatch)" : DONUT_COLORS[k];
    circles.push(`<circle class="dseg" data-deg="${pyfmt(deg, '.2f')}" cx="50" cy="50" r="${pyfmt(r, 'g')}" fill="none" stroke="${stroke}" stroke-width="26" pathLength="360" stroke-dasharray="${pyfmt(length, '.2f')} ${pyfmt(360 - length, '.2f')}" stroke-dashoffset="${pyfmt(-off, '.2f')}" transform="rotate(-90 50 50)"/>`);
    if (!is_hidden && sh_[k] >= DONUT_LABEL_MIN_PCT) {
      const mid = (start + deg / 2) * (Math.PI / 180);
      labels.push(`<span class="dp" style="left:${pyfmt(50 + r * Math.sin(mid), '.1f')}%;top:${pyfmt(50 - r * Math.cos(mid), '.1f')}%;color:${DONUT_TEXT[k]};background:${DONUT_COLORS[k]}">${sh_[k]}%</span>`);
    }
    start += deg;
  }
  const parts = [], legend = [];
  for (const k of DEVICE_ORDER) {
    if (cells[k] === SMALL) {
      parts.push(`${DEVICE_SHORT[k]} ${SMALL}`);
      legend.push(`<li><span class="sw hg"></span><span>${e(DEVICE_SHORT[k])} ${e(SMALL)}</span></li>`);
    } else if (cells[k] > 0) {
      parts.push(`${DEVICE_SHORT[k]} ${sh_[k]}%`);
      legend.push(`<li><span class="sw" style="background:${DONUT_COLORS[k]}"></span><span>${e(DEVICE_SHORT[k])} ${sh_[k]}% (${cells[k]} of ${den})</span></li>`);
    }
  }
  const label = `Device split of ${den} visit${den !== 1 ? 's' : ''}${hidden.length ? ' shown' : ''}: ` + parts.join(", ");
  const svg = (`<svg viewBox="0 0 100 100" role="img" aria-label="${e(label)}"><defs><pattern id="dev-hatch" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="5" height="5" fill="#FFFFFF"/>`
               + `<rect width="2" height="5" fill="#767B86"/></pattern></defs>${circles.join("")}</svg>`);
  const centre = `<div class="dn" aria-hidden="true"><b>${den}</b><span>visit${den !== 1 ? "s" : ""}${hidden.length ? " shown" : ""}</span></div>`;
  return [`<div class="dwrap"><div class="donut">${svg}${centre}${labels.join("")}</div><ul class="dlg">${legend.join("")}</ul></div>`, label, segs];
}


function kpi_series(a) {
  // Weekly values of the key figures over the comparable run (the changes): the same period_values as the cards, one week at a time; the desktop share of the visits with a width needs 20 visits and no withheld class.
  // strip/sser: the same figures for the sparklines, which also draw the provisional first week and the week in progress (see _strip_weeks).
  const m = a["model"], th = a["model"].th;
  const run = _comparable_run(m);
  const grow = new Map(a["weeks"].map(w => [w["ws"], w]));
  const ser = {};
  for (const k of ["people", "new", "vpp", "min", "desk"]) ser[k] = new Map();
  const cnt_ = {"vpp": new Map(), "min": new Map()};
  for (const w of run) {
    const v = period_values(m.visits(w), th);
    ser["people"].set(w, v["people"]);
    ser["new"].set(w, grow.has(w) ? grow.get(w)["new"] : null);
    ser["vpp"].set(w, v["vpp"]);
    cnt_["vpp"].set(w, [v["eng"], v["n"]]);
    ser["min"].set(w, v["min"]);
    cnt_["min"].set(w, v["pos"]);
    const dk = device_card(v["dev"], th)["desk"];
    ser["desk"].set(w, dk === undefined ? null : dk);
  }
  const strip = _strip_weeks(m);                                                        // the same figures for the strips, with the incomplete weeks (the same guards: a group under the minimum is not a number)
  const sser = {};
  for (const k of ["people", "new", "vpp", "min"]) sser[k] = new Map();
  for (const [w, part] of strip) {
    if (!part) {
      for (const k of Object.keys(sser)) sser[k].set(w, ser[k].has(w) ? ser[k].get(w) : null);
      continue;
    }
    const v = period_values(m.visits(w), th);
    sser["people"].set(w, v["people"]);
    sser["vpp"].set(w, v["vpp"]);
    sser["min"].set(w, v["min"]);
    if (w === m.cur && v["n"]) {                                                        // in the provisional first week everyone is new by construction (as the weekly table, no figure)
      const new_n = m.new(w).size;
      sser["new"].set(w, v["n"] < MIN_USERS ? SMALL : protect_partition({"new": new_n, "other": v["n"] - new_n}, v["n"])["new"]);
    } else {
      sser["new"].set(w, null);
    }
  }
  return {"run": run, "ser": ser, "cnt": cnt_, "strip": strip, "sser": sser};
}


const STRIP_NOTE = "In the small weekly lines, a lighter hatched point is part of a week: the first week, which starts mid-week, or the week still in progress.";


function _strip_label(what, vals, part, end, fl = false) {   // fl: the series holds floats (Python tells 3.0 from 3 by type, the port by this flag)
  // The accessible name of a strip. With only complete weeks it says the weeks are comparable and ends at the card's figure; with incomplete weeks it says so (the partial first week, the week so far) and ends at the last week it draws.
  if (!part.some(Boolean)) return `${what} per week, last ${vals.length} comparable weeks, ending at ${end}.`;
  const incl = (part[0] && part[part.length - 1]) ? "the partial first week and the week so far" : part[part.length - 1] ? "the week so far" : "the partial first week";
  const tail = `, ending at ${pystr(vals[vals.length - 1], fl)}` + (part[part.length - 1] ? " (week so far)" : "");
  return `${what} per week, last ${vals.length} weeks including ${incl}${tail}.`;
}


function _delta(cur, prev, pct_ok, decimals = 0, unit = "", good_up = null) {
  // [css class, text] of the change against the previous week: an arrow and words, never colour alone. A figure that is withheld has no change.
  if (cur === null || cur === undefined || cur === SMALL || prev === null || prev === undefined || prev === SMALL) return ["nt", "Change not shown"];
  const d = decimals ? pyround(cur - prev, decimals) : pyround(cur - prev);
  const pct = (pct_ok && prev) ? ` (${rnd(100 * Math.abs(d) / prev)}%)` : "";
  const fmt = decimals ? (x => pyfmt(Math.abs(x), `.${decimals}f`)) : (x => String(Math.abs(x)));
  if (d === 0) return ["flat", '- No change<span class="sr"> vs previous week</span>'];
  const up = d > 0;
  const cls = good_up ? (up ? "up" : "down") : "flat";
  return [cls, `${up ? '&#9650; Up' : '&#9660; Down'} ${fmt(d)}${unit}${pct}<span class="sr"> vs previous week</span>`];
}


function _kpi(title, fig, delta, den, spark_html, hero = false, skel = null, hid = "", fig_cls = "") {
  const cls = "kpi" + (hero ? " hero" : "") + (skel ? " skel" : "");
  const i = hid ? ` id="${hid}"` : "";
  if (skel) return `<div class="${cls}"${i}><h3>${e(title)}</h3><p class="fig">${e(skel)}</p><p class="den">${e(den)}</p><div class="sp"><div class="skbar" aria-hidden="true"></div></div></div>`;
  const dl = delta ? `<p class="dl ${delta[0]}">${delta[1]}</p>` : "";
  return `<div class="${cls}"${i}><h3>${e(title)}</h3><p class="fig${fig_cls ? " " + fig_cls : ""}">${fig}</p>${dl}<p class="den">${den}</p><div class="sp">${spark_html}</div></div>`;
}


function device_counts(rows) {
  // Visits (engaged or glance) by the window-width class the page recorded, and the distinct people in each class. A visit without a width is not counted. The classes are a partition of the visits, protected like every other partition
  // (a class under the minimum group size is withheld, and so is a class that a printed total would reveal).
  rows = rows.filter(r => typeof r["s"]["d"] === "string" && Object.prototype.hasOwnProperty.call(DEVICES, r["s"]["d"]));
  const groups = {};
  for (const k of Object.keys(DEVICES)) {
    const mine = rows.filter(r => r["s"]["d"] === k);
    groups[k] = [new Set(mine.map(r => r["u"])), mine.length];
  }
  const people = {};
  for (const [k, v] of Object.entries(groups)) people[k] = v[0].size;
  const zero = {};
  for (const k of Object.keys(DEVICES)) zero[k] = 0;
  return {"n": rows.length, "people": people, "cells": rows.length ? partition_cells(groups) : zero};
}


function pct_split(values) {
  // Whole percentages of the values that add up to exactly 100 (largest remainder: 1/3 each is 34, 33, 33); all zeros stay 0.
  const tot = values.reduce((s, v) => s + v, 0);
  if (!tot) return values.map(() => 0);
  const raw = values.map(v => 100 * v / tot);
  const base = raw.map(x => Math.floor(x));
  const order = values.map((_, i) => i).sort((i, j) => (-(raw[i] - base[i]) - -(raw[j] - base[j])) || (i - j));
  for (const i of order.slice(0, 100 - base.reduce((s, v) => s + v, 0))) base[i] += 1;
  return base;
}


function device_shares(dc) {
  // {class: whole percentage} over the printed classes of a device_counts result (a withheld class has none and the others share 100 between them), adding up to 100.
  const ks = DEVICE_ORDER.filter(k => dc["cells"][k] !== SMALL);
  const sp = pct_split(ks.map(k => dc["cells"][k]));
  const out = {};
  ks.forEach((k, i) => { out[k] = sp[i]; });
  return out;
}


function device_texts(dc, th = THRESHOLDS) {
  // {class: [share, full text]} for a device_counts result: always a percentage of the visits (a small base is shown by its n, here and in the card), adding up to 100, with the counts behind it. The denominator is the printed classes only when a class
  // is withheld, so the total of a withheld class is never printed. A withheld class prints the guard text and nothing else.
  const cells = dc["cells"];
  const hidden = Object.values(cells).includes(SMALL);
  const den = hidden ? Object.values(cells).filter(v => v !== SMALL).reduce((s, v) => s + v, 0) : dc["n"];
  const sh_ = device_shares(dc);
  const out = {};
  for (const k of DEVICE_ORDER) {
    const c = cells[k];
    if (c === SMALL) { out[k] = [SMALL, SMALL]; continue; }
    const ppl = dc["people"][k];
    const who = `${ppl} ${ppl === 1 ? 'person' : 'people'}`;
    out[k] = [`${sh_[k]}%`, `${sh_[k]}% (${c} of ${den} visits, ${who})`];
  }
  return out;
}


function device_line(dc, th = THRESHOLDS) {
  // 'Desktop (wide window) 80% | Tablet (medium window) 5% | Phone (narrow window) 15%' (the short form of device_texts).
  const tx = device_texts(dc, th);
  return DEVICE_ORDER.map(k => `${DEVICES[k]} ${tx[k][0]}`).join(" | ");
}


function _pl(n, one, many) {
  return `${n} ${n === 1 ? one : many}`;
}


function _first_comparison_note(m) {
  // Why there is nothing to compare yet and when there will be: a week of data that starts mid-week is never compared, and a change needs two complete weeks.
  const first_usable = m.provisional_first ? d_add(m.first_week, 7) : m.first_week;
  const sat = d_add(first_usable, 13);
  const start = m.provisional_first ? `Data starts ${d_label(m.data_start)}, mid-week: that week is not compared. ` : `Data starts ${d_label(m.data_start)}. `;
  return start + `Comparisons appear after two complete weeks (from Sat ${d_label(sat)}).`;
}


function device_period_lines(a) {
  // [[label, device_counts]] for the period of the key figures and, when it differs, all the recorded visits.
  const m = a["model"];
  const P = kpi_period(m);
  const out = [];
  if (P["kind"] !== "none") {
    out.push([P["label"], device_counts(P["rows"])]);
    if (P["kind"] === "week" && m.rows.length) out.push([`all recorded visits, ${d_label(m.first_day)} to ${d_label(m.last_day)}`, device_counts(m.rows)]);
  }
  return out;
}


function _kpis(a) {
  // The five key figures: people active (the hero), new people, engaged visits per person, median visit length and the device (twice as wide; the glance share is under Recording health). Each shows its value for the period (the last completed week, or the data so far while there is none)
  // with the number behind it; only the comparison (the change against the week before, the usual range, the sparkline) falls back to a short muted note when there is nothing comparable.
  const m = a["model"], th = a["model"].th;
  const c = a["compared"], au = a["audience"];
  const P = kpi_period(m);
  const ks = kpi_series(a);
  const run = ks["run"], ser = ks["ser"], cn = ks["cnt"];
  const strip = ks["strip"], sser = ks["sser"];
  const part = strip.map(x => x[1]);
  const vals = period_values(P["rows"], th);
  const L = m.last;
  const prev = d_add(L, -7);
  const week_mode = P["kind"] === "week";
  const has_prev = week_mode && run.includes(prev) && run.includes(L);
  let why;
  if (!week_mode) why = "No comparison yet: first week of data";
  else if (!run.includes(L)) why = (m.regime(L) !== null && m.regime(L) !== undefined) ? "No comparison: recording rules changed" : "No comparison: no visits that week";
  else if (!has_prev) why = "No comparison yet: first complete week";
  else why = "";
  const note = ["nt", why];
  const so = P["so_far"] ? ", so far" : "";
  const get = (key, w) => { const x = ser[key].get(w); return x === undefined ? null : x; };
  const get2 = (key, w) => { const x = sser[key].get(w); return x === undefined ? null : x; };
  const strip_of = key => {
    // (values, incomplete flags) of a strip: an incomplete week at either end that cannot be drawn (no figure, or a group under the minimum) takes no room.
    const vs = strip.map(([w]) => (is_num(get2(key, w)) ? get2(key, w) : null));
    const ps = part.slice();
    while (vs.length && ps[0] && vs[0] === null) { vs.shift(); ps.shift(); }
    while (vs.length && ps[ps.length - 1] && vs[vs.length - 1] === null) { vs.pop(); ps.pop(); }
    return [vs, ps];
  };
  const sp = (key, what, end, fl = false) => {
    const [vs, ps] = strip_of(key);
    return spark(vs, _strip_label(what, vs, ps, end, fl), ps);
  };
  const cells = [];
  let dl, den, v, pv;
  // 1 people active (hero)
  if (vals["people"] === SMALL) {
    cells.push(_kpi("People active", "", null, `A group under ${MIN_USERS} people is not shown`, "", true, SMALL, "kpi-people"));
  } else {
    const cur = vals["n"];
    const pp = get("people", prev);
    dl = has_prev ? _delta(cur, pp, pp !== null && pp !== SMALL && pp >= th["min_den"], 0, "", true) : note;
    if (week_mode && c && c["state"] === "ok") {
      const where = c["above"] ? "above" : c["below"] ? "below" : "inside";
      den = `Usual ${e(c['median'])} (range ${e(c['lo'])} to ${e(c['hi'])}): ${where} the usual range`;
    } else if (week_mode && c) {
      den = `Usual range building: ${c['n_baseline']} of ${th['baseline_min']} comparable weeks`;
    } else {
      den = e(P["label"].charAt(0).toUpperCase() + P["label"].slice(1)) + "<br>No usual range yet: it needs 5 complete weeks";
    }
    if (au) {
      den += (au["x"] !== null && au["x"] !== undefined && week_mode)
        ? (`<br>${num(au['x'])} of an audience of ${au['size']}` + (au["pct"] !== null && au["pct"] !== undefined ? ` (${au['pct']}%)` : "") + ", a lower bound")
        : `<br>Audience of ${au['size']} supplied`;
    } else {
      den += "<br>No audience size supplied";
    }
    cells.push(_kpi("People active", num(vals["people"]), dl, den, sp("people", "People active", cur), true, null, "kpi-people"));
  }
  // 2 new people
  let nw;
  if (week_mode) {
    const row = a["weeks"].find(w => w["ws"] === L);
    nw = row ? row["new"] : null;
  } else if (vals["n"]) {
    const new_n = m.people.filter(u => _ra_get(m.first_seen, u) >= m.first_day).length;
    nw = (0 < vals["n"] && vals["n"] < MIN_USERS) ? SMALL : protect_partition({"new": new_n, "other": vals["n"] - new_n}, vals["n"])["new"];
  } else {
    nw = null;
  }
  if (nw === null || nw === undefined) {
    cells.push(_kpi("New people", "", null, "First week of data", "", false, "No data", "kpi-new"));
  } else if (nw === SMALL) {
    cells.push(_kpi("New people", "", null, `A group under ${MIN_USERS} people is not shown`, "", false, SMALL, "kpi-new"));
  } else {
    pv = get("new", prev);
    dl = has_prev ? _delta(nw, pv, false, 0, "", true) : note;
    cells.push(_kpi("New people", num(nw), dl, e(`of ${vals['people'] === SMALL ? vals['people'] : _pl(vals['n'], 'person', 'people')} active${so}`), sp("new", "New people", nw), false, null, "kpi-new"));
  }
  // 3 engaged visits per active person
  v = vals["vpp"];
  if (v === null) {
    cells.push(_kpi("Engaged visits per person", "", null, "No visits in the period", "", false, "No visits", "kpi-vpp"));
  } else if (v === SMALL) {
    cells.push(_kpi("Engaged visits per person", "", null, `Fewer than ${MIN_USERS} people`, "", false, SMALL, "kpi-vpp"));
  } else {
    pv = get("vpp", prev);
    dl = has_prev ? _delta(v, pv, pv !== null && pv !== SMALL && cn["vpp"].get(prev)[1] >= th["min_den"], 1, "", null) : note;
    cells.push(_kpi("Engaged visits per person", num(v, "", true), dl, e(`${_pl(vals['eng'], 'engaged visit', 'engaged visits')}, ${_pl(vals['n'], 'person', 'people')}${so}`), sp("vpp", "Engaged visits per active person", pystr(v, true), true), false, null, "kpi-vpp"));
  }
  // 4 median active minutes
  v = vals["min"];
  if (v === null) {
    cells.push(_kpi("Median visit length", "", null, "No active seconds recorded in the period", "", false, "No active time", "kpi-min"));
  } else if (v === SMALL) {
    cells.push(_kpi("Median visit length", "", null, `Fewer than ${MIN_USERS} people`, "", false, SMALL, "kpi-min"));
  } else {
    pv = get("min", prev);
    dl = has_prev ? _delta(v, pv, false, 1, " min", null) : note;
    cells.push(_kpi("Median visit length", `${num(v, "", true)}<span class="small"> min</span>`, dl, e(`active minutes, ${_pl(vals['pos'][0], 'engaged visit', 'engaged visits')}${so}`), sp("min", "Median active minutes per engaged visit", pystr(v, true), true), false, null, "kpi-min"));
  }
  // 5 device (twice as wide as the others: the donut and its legend sit side by side)
  const dev = device_card(vals["dev"], th);
  if (dev["state"] === "none") {
    cells.push(_kpi("Device", "", null, "No browser window width recorded", "", false, "No width", "kpi-device"));
  } else if (dev["state"] === "hidden") {
    cells.push(_kpi("Device", "", null, `A group under ${MIN_USERS} people is not shown`, "", false, SMALL, "kpi-device"));
  } else {
    const dk = get("desk", L), pk = get("desk", prev);
    dl = (has_prev && dk !== null && pk !== null) ? _delta(dk, pk, false, 0, " points", null) : (!has_prev ? note : ["nt", "Change not shown: under 20 visits"]);
    cells.push(_kpi("Device", e(dev["fig"]), dl, e(dev["sub"]), device_donut(vals["dev"], th)[0], false, null, "kpi-device", "sm"));
  }
  // the table behind the sparklines and the cards
  const body = [];
  const trow = (label, v_people, v_new, v_vpp, v_min) =>
    `<tr><th scope="row">${e(label)}</th><td class="n">${num(v_people)}</td><td class="n">${num(v_new)}</td><td class="n">${num(v_vpp, "", true)}</td><td class="n">${num(v_min, "", true)}</td></tr>`;
  if (!week_mode) body.push(trow(P["label"].charAt(0).toUpperCase() + P["label"].slice(1), vals["people"], nw, vals["vpp"], vals["min"]));
  for (const w of run.slice().reverse()) body.push(trow(week_label(w), get("people", w), get("new", w), get("vpp", w), get("min", w)));
  const usable_n = m.weeks.filter(w => !m.is_prov(w)).length;
  let table = ('<table id="kpi-table"><thead><tr><th scope="col">Period</th><th scope="col" class="n">People active</th><th scope="col" class="n">New people</th><th scope="col" class="n">Engaged visits per person</th><th scope="col" class="n">Median visit length (min)</th>'
               + `</tr></thead><tbody>${body.join("")}</tbody></table>`
               + (usable_n > run.length ? `<p class="cap2">${usable_n - run.length} earlier completed week(s) are left out: the page recorded visits under other rules, so the figures are not comparable.</p>` : ""));
  const drows = [];
  for (const [label, dc] of device_period_lines(a)) {
    if (!dc["n"]) {
      drows.push(`<tr><th scope="row">${e(label)}</th><td class="n">no browser window width recorded</td></tr>`);
      continue;
    }
    const tx = device_texts(dc, th);
    for (const k of DEVICE_ORDER) drows.push(`<tr><th scope="row">${e(label)}: ${e(DEVICES[k])}</th><td class="n">${e(tx[k][1])}</td></tr>`);
  }
  table += (`<table id="device-table"><thead><tr><th scope="col">Window width class</th><th scope="col" class="n">Share of visits</th></tr></thead><tbody>${drows.join("")}</tbody></table>`
            + `<p class="cap2">${e(DEVICE_CAVEAT)} Every visit counts, glance or engaged; a visit without a width is not counted.</p>`);
  let sub;
  if (week_mode) {
    sub = `Last completed week: ${week_label(L)}. Each figure is compared with the week before; the line shows the weeks since the last change of the recording rules.`;
    if (!has_prev) sub = `Last completed week: ${week_label(L)}. ` + _first_comparison_note(m);
  } else if (P["kind"] === "todate") {
    sub = P["label"].charAt(0).toUpperCase() + P["label"].slice(1) + ". " + _first_comparison_note(m);
  } else {
    sub = "No data yet.";
  }
  const strip_note = cells.some(c => c.includes('class="ld pt"')) ? `<p class="cap" id="strip-note">${e(STRIP_NOTE)}</p>` : "";
  return (`<section class="blk" id="kpis" aria-labelledby="h-kpi"><h2 id="h-kpi">Key figures</h2><p class="cap" id="kpi-note">${e(sub)}</p><p class="cap" id="device-caveat">Device is by browser window width, not device type: a narrow desktop window counts as phone.</p>${strip_note}`
          + `<div class="kpis">${cells.join("")}</div>${show_data(table)}</section>`);
}


// ------------------------------------------------------------------------------------------------------------ the trend
function _tick_label(label) {
  return (label.startsWith("W1 starts") ? "W1 starts" : label.startsWith("End of W6") ? "Delivery Cycle 1 ends" : label.startsWith("Release end") ? "Release ends" : label);
}


function _chart_weeks(a) {
  // People active per Sunday-to-Saturday week: a line and area for the complete weeks, hatched columns for the incomplete ones (the provisional first week and the week in progress), the usual range, the calendar events.
  const rows = a["weeks"], comp = a["compared"], m = a["model"];
  const n = rows.length;
  const vis = rows.filter(w => w["active"] !== SMALL).map(w => w["raw"]);
  const hi_band = comp && comp["raw_hi"] !== null && comp["raw_hi"] !== undefined ? comp["raw_hi"] : 0;
  const [top, step] = nice_axis(Math.max(...vis, hi_band, 1));
  const [lines, labels] = _grid(top, step);
  const slots = [], parts = [], runs = [], ticks = [];
  let cur = [];
  let last_c = null;
  rows.forEach((w, i) => { if (w["status"] === "complete" && w["active"] !== SMALL) last_c = i; });
  const vmax = Math.max(...vis, 0);
  rows.forEach((w, i) => {
    const tag = w["status"] === "provisional" ? "provisional, data starts mid-week" : w["status"] === "in_progress" ? "so far this week, not comparable" : "";
    const val = w["active"] === SMALL ? SMALL : String(w["active"]);
    parts.push(`${w['label']}: ${val} people` + (tag ? ` (${tag})` : ""));
    const tip = e(`${w['label']}: ${val} people` + (tag ? ` (${tag})` : ""));
    const y = 100 * w["raw"] / top;
    const keep = (i === 0 || i === n - 1 || i === last_c || w["raw"] === vmax) ? "" : " nk";
    if (w["status"] !== "complete") {
      if (w["active"] === SMALL) slots.push(`<div class="slot" title="${tip}"><i class="stub"></i></div>`);
      else if (w["raw"] === 0) slots.push(`<div class="slot" title="${tip}"><i class="zero"></i></div>`);
      else slots.push(`<div class="slot" title="${tip}"><i class="hbar" style="height:${pyfmt(Math.max(1.5, y), '.1f')}%"></i><span class="vl${keep}" style="bottom:calc(${pyfmt(y, '.1f')}% + 5px)">${w["raw"]}</span></div>`);
      if (cur.length) { runs.push(cur); cur = []; }
    } else if (w["active"] === SMALL) {
      slots.push(`<div class="slot" title="${tip}"><i class="stub"></i></div>`);
      if (cur.length) { runs.push(cur); cur = []; }
    } else {
      cur.push([i, y]);
      const big = i === last_c ? " big" : "";
      slots.push(`<div class="slot" title="${tip}"><i class="dot${big}" style="bottom:${pyfmt(y, '.1f')}%"></i><span class="vl${keep}" style="bottom:calc(${pyfmt(y, '.1f')}% + ${i === last_c ? 13 : 10}px)">${w["raw"]}</span></div>`);
    }
  });
  if (cur.length) runs.push(cur);
  const xy = (i, y) => [100 * (i + 0.5) / n, 100 - y];
  const f2 = (i, y) => { const p = xy(i, y); return pyfmt(p[0], ".2f") + " " + pyfmt(p[1], ".2f"); };
  const d_l = runs.flatMap(run => run.map(([i, y], k) => (k === 0 ? "M" : "L") + f2(i, y))).join(" ");
  const d_a = runs.filter(run => run.length > 1).map(run => run.map(([i, y], k) => (k === 0 ? "M" : "L") + f2(i, y)).join(" ") + ` L${pyfmt(xy(run[run.length - 1][0], 0)[0], ".2f")} 100 L${pyfmt(xy(run[0][0], 0)[0], ".2f")} 100 Z`).join(" ");
  const svg = runs.length ? `<svg class="ln2" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true" focusable="false"><path class="a" d="${d_a}"/><path class="l" d="${d_l}"/></svg>` : "";
  let band = "", band_txt = "";
  if (comp && comp["raw_hi"] !== null && comp["raw_hi"] !== undefined) {
    const lo = Math.max(0, comp["raw_lo"]), hi = Math.min(top, comp["raw_hi"]);
    band = `<div class="band" style="bottom:${pyfmt(100 * lo / top, '.1f')}%;height:${pyfmt(Math.max(1.0, 100 * (hi - lo) / top), '.1f')}%"></div>`;
    band_txt = ` Usual range of the last completed week: ${comp['lo']} to ${comp['hi']}.`;
  }
  // calendar events and the change of recording rules
  const first_ws = rows[0]["ws"], last_day = d_add(rows[rows.length - 1]["ws"], 6);
  const evs = calendar_marks(m, first_ws, last_day).filter(([d, lb, kind]) => kind === "ms").map(([d, lb, kind]) => [d, _tick_label(lb), ""]);
  if (m.rollover && first_ws <= m.rollover && m.rollover <= last_day) evs.push([m.rollover, "New recording rules", " rc"]);
  const tk = [], cal_txt = [];
  evs.slice().sort(cmp_py).forEach(([d, lb, cls], j) => {
    const idx = Math.floor(d_diff(week_start(d), first_ws) / 7);
    const x = 100 * (idx + (d_diff(d, week_start(d)) + 0.5) / 7) / n;
    const r = j % 3;                                                                          // neighbouring labels sit on different rows, so they never overlap
    const fl = x > 62 ? " fl" : "";
    tk.push(`<div class="tk${cls}${fl}" style="left:${pyfmt(x, '.2f')}%;--r:${r}"><span class="tl">${e(lb)}</span></div>`);
    cal_txt.push(`${d_label(d)}: ${lb}`);
  });
  const xl = rows.map((w, i) => `<span class="${(n - 1 - i) % 3 === 0 ? "" : "nk"}">${e(w["label"])}</span>`).join("");
  const summary = (`People active per Sunday-to-Saturday week, ${rows[0]['label']} to ${rows[rows.length - 1]['label']}. ` + parts.join("; ") + "." + band_txt
                   + (cal_txt.length ? " Calendar: " + cal_txt.join("; ") + "." : ""));
  const inner = (`<div class="ya" aria-hidden="true">${labels}</div><div class="pa" style="--n:${n}">${lines}${band}<div class="slots" style="--n:${n}">${slots.join("")}</div>${svg}${tk.join("")}</div>`
                 + `<div class="xa" style="--n:${n}" aria-hidden="true">${xl}</div>`);
  return chart_img(inner, summary, "plot");
}


function _week_table(a) {
  const body = [];
  for (const w of a["weeks"]) {
    const tag = w["status"] === "provisional" ? "provisional: data starts mid-week" : w["status"] === "in_progress" ? "so far, not comparable" : "";
    const cells = ["new", "continuing", "reactivated", "lapsed"].map(k => `<td class="n">${w[k] !== null && w[k] !== undefined ? num(w[k]) : "-"}</td>`).join("");
    body.push(`<tr><th scope="row">${e(w["label"])}` + (tag ? `<div class="cap2">${e(tag)}</div>` : "") + `</th><td class="n">${num(w["active"])}</td>${cells}</tr>`);
  }
  return ('<table class="wk-table" id="weeks"><thead><tr><th scope="col">Week starting (Sunday)</th><th scope="col" class="n">People</th><th scope="col" class="n">New</th><th scope="col" class="n">Continuing</th><th scope="col" class="n">Back after a gap</th>'
          + `<th scope="col" class="n">Lapsed</th></tr></thead><tbody>${body.join("")}</tbody></table>`);
}


const _RA_WD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const _RA_MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];


function _chart_days(a) {
  const dv = a["daily"];
  const days = dv["days"];
  const n = days.length;
  const vis = days.filter(d => d["users"] !== SMALL).map(d => d["raw"]);
  const [top, step] = nice_axis(Math.max(...vis, 1));
  const [lines, labels] = _grid(top, step);
  const mark_by_day = new Map();
  for (const [d, label, kind] of dv["marks"]) {
    if (!mark_by_day.has(d)) mark_by_day.set(d, []);
    mark_by_day.get(d).push([label, kind]);
  }
  const slots = [], mrow = [], parts = [];
  for (const d of days) {
    const we = d["weekend"] ? " we" : "";
    const state = (!d["has_data"] ? "before the data starts" : d["users"] === SMALL ? SMALL : String(d["raw"])) + (d["partial"] ? " (so far today, not comparable)" : "") + (d["weekend"] ? " (Friday or Saturday)" : "");
    const dd = d["day"];
    const tip = `${_RA_WD[d_weekday(dd)]} ${dd.slice(8, 10)} ${_RA_MON[Number(dd.slice(5, 7)) - 1]}: ${state}`;
    parts.push(tip);
    if (!d["has_data"]) slots.push(`<div class="slot" title="${e(tip)}"></div>`);
    else if (d["users"] === SMALL) slots.push(`<div class="slot" title="${e(tip)}"><i class="stub"></i></div>`);
    else if (d["raw"] === 0) slots.push(`<div class="slot" title="${e(tip)}"><i class="zero"></i></div>`);
    else slots.push(`<div class="slot" title="${e(tip)}"><i class="col${we}${d["partial"] ? " part" : ""}" style="height:${pyfmt(Math.max(1.5, 100 * d["raw"] / top), '.1f')}%"></i></div>`);
    const mk = mark_by_day.get(d["day"]);
    mrow.push(mk ? "<span>&#9650;</span>" : "<span></span>");
  }
  const half = Math.floor(n / 2);
  const xl = days.map((d, i) => `<span>${(i === 0 || i === half || i === n - 1) ? d_label(days[i]["day"]) : ""}</span>`).join("");
  const cal = dv["marks"].map(([d, lb]) => `${d_label(d)}: ${lb}`).join("; ");
  const summary = `People active per day, last 28 days, ${d_label(days[0]['day'])} to ${d_label(days[days.length - 1]['day'])}. ` + parts.join("; ") + "." + (cal ? ` Calendar marks: ${cal}.` : "");
  const inner = (`<div class="ya" aria-hidden="true">${labels}</div><div class="pa">${lines}<div class="slots" style="--n:${n}">${slots.join("")}</div></div>`
                 + `<div class="mk" style="--n:${n}" aria-hidden="true">${mrow.join("")}</div><div class="xa day" style="--n:${n}" aria-hidden="true">${xl}</div>`);
  return chart_img(inner, summary, "plot", "--ph:200px");
}


function _day_label(d) {
  return `${dt_strftime(d, "%a")} ${d_label(d)}`;
}


function _day_range(lo, hi) {
  return lo === hi ? _day_label(lo) : `${_day_label(lo)} to ${_day_label(hi)}`;
}


const WTD_RULES_NOTE = "Visits are not comparable: the page's recording rules changed between these two periods (glance visits are only recorded by the newer page).";


function wtd_title(w) {
  // The sentence above the week-so-far figures (text and page).
  if (w["state"] === "no_current") return `This week so far (${_day_range(w['cur_lo'], w['cur_hi'])}, today still in progress): no visit recorded yet.`;
  const note = w["data_from"] ? `; data starts ${d_label(w['data_from'])}` : (w["state"] === "no_baseline" ? "; no visit recorded in those days" : "");
  return `This week so far (${_day_range(w['cur_lo'], w['cur_hi'])}, today still in progress) against the same days last week (${_day_range(w['prev_lo'], w['prev_hi'])}${note})`;
}


function wtd_delta(r, state) {
  // '+3, +12%': the difference with its sign (and a percentage when the previous figure allows one); empty when there is no baseline, 'change not shown' when a figure is withheld.
  const d = r["diff"];
  if (d === null) return (state === "no_baseline" || state === "no_current") ? "" : "change not shown";
  if (d === 0) return "0";
  const sg = d > 0 ? "+" : "-";
  return `${sg}${pyfmt(Math.abs(d), ",")}` + (r["pct"] !== null ? `, ${sg}${r['pct']}%` : "");
}


function wtd_rows(w) {
  // [(measure, this week so far, same days last week, difference)] as printed.
  return [["people", "Active people"], ["visits", "Visits"]].map(([key, name]) => [name, fmt_n(w[key]["cur"]), w["state"] === "no_baseline" ? "not enough data" : fmt_n(w[key]["prev"]), wtd_delta(w[key], w["state"])]);
}


function _wtd_block(w) {
  // This week so far against the same days last week: under the weekly people chart.
  if (w["state"] === "no_current") return `<div class="wtd" id="wtd"><p class="cap2">${e(wtd_title(w))}</p></div>`;
  const trs = wtd_rows(w).map(([n_, c_, p_, dl]) => `<tr><th scope="row">${e(n_)}</th><td class="n">${e(c_)}</td><td class="n">${e(p_)}</td><td class="n">${dl ? e(dl) : "-"}</td></tr>`).join("");
  const note = w["rules_changed"] ? `<p class="cap2">${e(WTD_RULES_NOTE)}</p>` : "";
  return (`<div class="wtd" id="wtd"><p class="cap">${e(wtd_title(w))}</p><table id="wtd-table" class="two"><thead><tr><th scope="col">Measure</th><th scope="col" class="n">This week so far</th>`
          + `<th scope="col" class="n">Same days last week</th><th scope="col" class="n">Difference</th></tr></thead><tbody>${trs}</tbody></table>${note}</div>`);
}


function _trend(a) {
  const gv = a["growth"], dv = a["daily"];
  const rows = a["weeks"];
  const cap_w = `Distinct people with a visit in each Sunday-to-Saturday week, ${rows[0]['label']} to ${rows[rows.length - 1]['label']}.`;
  const has_band = a["compared"] && a["compared"]["raw_hi"] !== null && a["compared"]["raw_hi"] !== undefined;
  const leg = _legend([["ln", "Complete week"], ["hb", "Incomplete week"]].concat(MIN_USERS > 1 ? [["hg", SMALL]] : []).concat(has_band ? [["bd", "Usual range"]] : []).concat([["tk", "Calendar event"]]));
  const week = panel("People active per week", cap_w, _chart_weeks(a) + leg + `<p class="verdict" id="growth"><b>Is adoption growing?</b> ${e(gv["text"])}</p>` + _wtd_block(a["wtd"]), show_data(_week_table(a)), "p-weeks");
  const cap_d = `Distinct people per day, ${d_label(dv['days'][0]['day'])} to ${d_label(dv['days'][dv['days'].length - 1]['day'])}.`;
  const leg_d = _legend([["hb", "Today so far"], ["we", "Friday, Saturday"]].concat(MIN_USERS > 1 ? [["hg", SMALL]] : []));
  const mk = dv["marks"].map(([d, label]) => `<li>${d_label(d)}: ${e(label)}</li>`).join("");
  const ww = dv["workweek"] ? `<p class="cap2">Sunday to Thursday had ${dv["workweek"]["pct"]}% of the ${dv["workweek"]["n"]} visits in the last 28 days.</p>` : "";
  const extra = [dv["note"], (dv["events"] || {})["text"]].filter(x => x).map(x => `<p class="cap2">${e(x)}</p>`).join("");
  const tbl = ('<table id="days"><thead><tr><th scope="col">Day</th><th scope="col" class="n">People</th></tr></thead><tbody>'
               + dv["days"].slice().reverse().map(d => `<tr><td>${d["day"]}${d["partial"] ? " (so far today, not comparable)" : ""}</td><td class="n">${!d["has_data"] ? "before the data starts" : num(d["users"])}</td></tr>`).join("") + "</tbody></table>"
               + (mk ? `<ul class="gov" aria-label="Calendar marks">${mk}</ul>` : "") + extra);
  const day = panel("People active per day", cap_d, _chart_days(a) + leg_d + ww, show_data(tbl), "p-days");
  return `<section class="blk" id="trend" aria-labelledby="h-trend"><h2 id="h-trend">Trend</h2><div class="row2">${week}${day}</div></section>`;
}
