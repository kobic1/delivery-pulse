// views.js: the adoption views A1 to A8, the daily view and the calendar notes, and `aggregate` (usage_report.py lines 1031-1488). Literal port: the Python report is the oracle.

// ---- private helpers of this file (prefix _vw_): the Python semantics the views lean on
function _vw_has(o, k) {                       // `k in dict`
  return o instanceof Map ? o.has(k) : Object.prototype.hasOwnProperty.call(o, k);
}
function _vw_get(coll, k) {                    // coll[k] / coll.get(k) of a Map or of a plain object (undefined when absent)
  if (coll === null || coll === undefined) return undefined;
  return coll instanceof Map ? coll.get(k) : coll[k];
}
function _vw_entries(coll) {                   // dict.items()
  if (coll === null || coll === undefined) return [];
  return coll instanceof Map ? [...coll.entries()] : Object.entries(coll);
}
function _vw_values(coll) {
  return _vw_entries(coll).map((kv) => kv[1]);
}
function _vw_items_num(coll) {                 // the items of a dict with int keys (LV, FA): the keys come back as numbers
  if (coll instanceof Map) return [...coll.entries()];
  return Object.entries(coll).map(([k, v]) => [/^-?\d+$/.test(k) ? Number(k) : k, v]);
}
function _vw_sess(r, key) {                    // (r["s"].get(key) or {}) as a plain object
  const v = r.s[key];
  return v && typeof v === "object" ? v : {};
}
function _vw_getset(map, k) {                  // defaultdict(set)[k]
  let s = map.get(k);
  if (s === undefined) { s = new Set(); map.set(k, s); }
  return s;
}
function _vw_mean(xs) {                        // statistics.mean of numbers
  let t = 0;
  for (const x of xs) t += x;
  return t / xs.length;
}
function _vw_pos(v) {                          // is_num(v) and v > 0
  return is_num(v) && v > 0;
}
function _vw_range(n) {                        // range(n)
  const out = [];
  for (let i = 0; i < n; i++) out.push(i);
  return out;
}


// ------------------------------------------------------------------------------------------------------------ adoption views A1 to A8
function growth_accounting(m) {
  const rows = [];
  for (const ws of m.weeks) {
    const act = m.active(ws);
    let n = act.size;
    const prev = d_add(ws, -7);
    const row = {ws: ws, label: d_label(ws), status: m.is_prov(ws) ? "provisional" : "complete", active: gn(n), raw: n, new: null, continuing: null, reactivated: null, lapsed: null};
    if (m.first_week !== null && prev >= m.first_week) {
      const pa = m.active(prev);
      let continuing = 0, reactivated = 0;
      for (const u of act) {
        if (pa.has(u) && _vw_get(m.first_seen, u) < ws) continuing += 1;
        if (!pa.has(u) && _vw_get(m.first_seen, u) < ws) reactivated += 1;
      }
      const cells = {new: m.new(ws).size, continuing: continuing, reactivated: reactivated, lapsed: set_diff(pa, act).size};
      Object.assign(row, protect_group(cells, [[n, ["new", "continuing", "reactivated"]], [pa.size, ["continuing", "lapsed"]]]));
    }
    rows.push(row);
  }
  const n = m.active(m.cur).size;
  rows.push({ws: m.cur, label: d_label(m.cur), status: "in_progress", active: gn(n), raw: n, new: null, continuing: null, reactivated: null, lapsed: null});
  return rows;
}


function growth_verdict(m) {
  const th = m.th;
  const k = th["growth_weeks"];
  const half = Math.floor(k / 2);
  const have = m.n_full_weeks();
  const wl = [];
  for (let i = k - 1; i >= 0; i--) wl.push(d_add(m.last, -7 * i));
  if (!wl.every((w) => m.usable(w))) {
    return {state: "too_early", have: have, need: k, text: `Too early to say: ${have} of ${k} completed weeks so far.`};
  }
  const regimes = new Set(wl.map((w) => m.regime(w)));
  regimes.delete(null);
  if (regimes.size > 1 || wl.includes(m.rollover)) {
    return {state: "too_early", have: have, need: k, text: "Too early to say: the recording rules changed within the last 6 weeks (glance visits are only recorded by the newer page), so the weeks are not comparable."};
  }
  const vals = wl.map((w) => m.active(w).size);
  const a = median(vals.slice(0, half)), b = median(vals.slice(half));
  if (a === 0 && b === 0) {
    return {state: "flat", text: `No clear growth: nobody was active in the last ${k} completed weeks.`, have: have, need: k};
  }
  if ((0 < rnd(a) && rnd(a) < MIN_USERS) || (0 < rnd(b) && rnd(b) < MIN_USERS)) {
    return {state: "unknown", text: `Unknown: a weekly median is under ${MIN_USERS} people.`, have: have, need: k};
  }
  const d = b - a;
  const need = Math.max(th["growth_abs"], th["growth_rel"] * a);
  const base = `median of the last ${half} completed weeks ${rnd(b)} people, against ${rnd(a)} in the ${half} before`;
  if (d >= need) {
    return {state: "growing", text: `Growing: ${base} (+${a ? rnd(100 * d / a) : 0}%).`, have: have, need: k, a: rnd(a), b: rnd(b)};
  }
  if (-d >= need) {
    return {state: "falling", text: `Falling: ${base} (${rnd(100 * d / a)}%).`, have: have, need: k, a: rnd(a), b: rnd(b)};
  }
  return {state: "flat", text: `No clear growth: ${base}; growth needs +${rnd(100 * th["growth_rel"])}% and +${th["growth_abs"]} people.`, have: have, need: k, a: rnd(a), b: rnd(b)};
}


function merge_bins(counts) {
  // counts: Map (or object) {number of weeks: people}
  const keys = (counts instanceof Map ? [...counts.keys()] : Object.keys(counts).map(Number)).sort((x, y) => x - y);
  const bins = keys.map((k) => [k, k, _vw_get(counts, k)]);
  while (bins.length > 1 && Math.min(...bins.map((b) => b[2])) < MIN_USERS) {
    let i = 0;
    for (let j = 1; j < bins.length; j++) {
      if (bins[j][2] < bins[i][2]) i = j;
    }
    const nb = [i - 1, i + 1].filter((j) => 0 <= j && j < bins.length);
    let j = nb[0];
    for (const c of nb) {
      if (bins[c][2] < bins[j][2]) j = c;
    }
    const lo = Math.min(i, j), hi = Math.max(i, j);
    bins.splice(lo, hi - lo + 1, [bins[lo][0], bins[hi][1], bins[lo][2] + bins[hi][2]]);
  }
  return bins.map((b) => [b[0], b[1], b[2]]);
}


function habit_view(m) {
  const th = m.th;
  const need = th["habit_weeks"];
  const wl = [];
  for (let i = need - 1; i >= 0; i--) wl.push(d_add(m.last, -7 * i));
  if (!wl.every((w) => m.usable(w))) {
    return {state: "too_early", have: m.n_full_weeks(), need: need, text: `Too early: needs ${need} completed weeks, has ${m.n_full_weeks()}.`};
  }
  const est = m.people.filter((u) => _vw_get(m.first_seen, u) <= d_add(m.last, -th["established_days"]));
  const n = est.length;
  const per = new Map();
  for (const u of est) per.set(u, wl.filter((w) => m.active(w).has(u)).length);
  const perv = [...per.values()];
  const x = perv.filter((c) => c >= th["habit_min_weeks"]).length;
  const out = {state: "ok", n: n, weeks: need, min_weeks: th["habit_min_weeks"], window: `${d_label(wl[0])} to ${d_label(d_add(wl[wl.length - 1], 6))}`};
  if (0 < n && n < MIN_USERS) {
    Object.assign(out, {x: SMALL, pct: null, bins: [], n_print: SMALL});
    return out;
  }
  const pc = protect_partition({habit: x, rest: n - x}, n);
  out["x"] = pc["habit"];
  out["pct"] = pc["habit"] !== SMALL ? pct_of(x, n, th) : null;
  let hist = [];
  if (n) {
    const counts = new Map();
    for (const k of _vw_range(need + 1)) counts.set(k, perv.filter((c) => c === k).length);
    hist = merge_bins(counts);
  }
  out["bins"] = hist.map(([lo, hi, c]) => [lo, hi, c]);
  out["n_print"] = n;
  out["single_bin_small"] = hist.length === 1 && hist[0][2] < MIN_USERS;
  return out;
}


function retention_view(m) {
  const th = m.th;
  const last_full = d_add(m.ref, -1);
  const days = new Map();
  for (const r of m.rows) _vw_getset(days, r.u).add(r.day);
  const out = {};
  for (const [key, span, lo_off] of [["w1", th["retention_w1_days"], 1], ["w4", th["retention_w4_days"], th["retention_w4_days"] - 6]]) {
    const elig = m.people.filter((u) => !m.pre_golive.has(u) && _vw_get(m.first_real, u) >= m.cutoff && d_add(_vw_get(m.first_real, u), span) <= last_full);
    let ret = 0;
    for (const u of elig) {
      const fr = _vw_get(m.first_real, u);
      const lo = d_add(fr, lo_off), hi = d_add(fr, span);
      let any = false;
      for (const d of _vw_getset(days, u)) {
        if (lo <= d && d <= hi) { any = true; break; }
      }
      if (any) ret += 1;
    }
    const n = elig.length;
    const pc = (n >= MIN_USERS || n === 0) ? protect_partition({returned: ret, not: n - ret}, n) : {returned: SMALL, not: SMALL};
    out[key] = {n: gn(n), raw_n: n, x: pc["returned"], pct: (pc["returned"] !== SMALL && pc["not"] !== SMALL) ? pct_of(ret, n, th) : null, indicative: n < 30, span: span};
  }
  return out;
}


function _window_rows(m, wk) {
  const out = [];
  for (const w of wk) for (const r of m.visits(w)) out.push(r);
  return out;
}


function sections_view(m, wk) {
  const th = m.th;
  const rows = _window_rows(m, wk);
  const A = wk.length ? set_union(...wk.map((w) => m.active(w))) : new Set();
  const N = A.size;
  const reach = {};
  for (const k of Object.keys(READ_SECTIONS)) {
    const s = new Set();
    for (const w of wk) {
      const sw = m.secs(w);
      for (const u of A) {
        const d = _vw_get(sw, u);
        const v = d === undefined ? 0 : (_vw_get(d, k) === undefined ? 0 : _vw_get(d, k));
        if (v >= SECTION_MIN_SECONDS) s.add(u);
      }
    }
    reach[k] = s;
  }
  const nav = new Map(), links = new Map();
  for (const r of rows) {
    for (const [k, v] of Object.entries(_vw_sess(r, "nav"))) {
      if (_vw_has(SECTIONS, k) && _vw_pos(v)) _vw_getset(nav, k).add(r.u);
    }
    for (const [k, v] of Object.entries(_vw_sess(r, "l"))) {
      if (_vw_has(LINK_SECTIONS, k) && _vw_pos(v)) _vw_getset(links, k).add(r.u);
    }
  }
  const tot = new Map();                                      // person -> Map(section -> seconds)
  for (const w of wk) {
    for (const [u, d] of _vw_entries(m.secs(w))) {
      if (!tot.has(u)) tot.set(u, new Map());
      const t = tot.get(u);
      for (const [k, v] of _vw_entries(d)) t.set(k, (t.has(k) ? t.get(k) : 0) + v);
    }
  }
  const pw = new Map();
  for (const [u, d] of tot) {
    let s = 0;
    for (const v of d.values()) s += v;
    for (const [k, v] of d) pw.set(k, (pw.has(k) ? pw.get(k) : 0) + (s ? v / s : 0));
  }
  const pwg = (k) => (pw.has(k) ? pw.get(k) : 0);
  const shown = Object.keys(READ_SECTIONS).filter((k) => reach[k].size >= MIN_USERS);
  let pw_den = 0;
  for (const k of shown) pw_den += pwg(k);
  const cand = _simplify_candidates(m);
  const table = [];
  for (const [k, nm] of Object.entries(READ_SECTIONS)) {
    const n_r = reach[k].size;
    const share = (pw_den && shown.includes(k)) ? rnd(100 * pwg(k) / pw_den) : ((0 < n_r && n_r < MIN_USERS) ? SMALL : (n_r === 0 ? 0 : null));
    table.push({key: k, name: nm, reach: gn(n_r), raw: n_r, pct: n_r >= MIN_USERS ? pct_of(n_r, N, th) : null,
                nav: _vw_has(SECTIONS, k) ? gn(_vw_getset(nav, k).size) : null, links: gn(_vw_getset(links, k).size), share: share,
                under5: 0 < n_r && n_r < MIN_USERS, candidate: _vw_has(cand.by_key, k) ? cand.by_key[k] : null});
  }
  const ol = {};
  for (const k of Object.keys(DISCLOSURES)) {
    const us = new Set();
    for (const r of rows) {
      const v = _vw_sess(r, "o")[k];
      if (_vw_pos(v)) us.add(r.u);
    }
    ol[k] = gn(us.size);
  }
  return {n: N, n_g: gn(N), d: (N === 0 || N >= MIN_USERS) ? N : SMALL, weeks: wk.length, rows: table, candidates: cand, disclosures: ol, any_hidden: table.some((t) => t.under5)};
}


function _boundary_weeks(m) {
  const cal = m.cal || {};
  const ds = [];
  for (const r of (cal.releases || [])) ds.push(r["w6_end"], r["end"]);
  for (const s of (cal.sprints || [])) ds.push(s["end"]);
  return new Set(ds.map((d) => week_start(d)));
}


function _simplify_candidates(m) {
  const th = m.th;
  const k = th["simplify_weeks"];
  const wl = [];
  for (let i = k - 1; i >= 0; i--) wl.push(d_add(m.last, -7 * i));
  if (!wl.every((w) => m.usable(w))) {
    return {status: `not tested: needs ${k} completed weeks, has ${m.n_full_weeks()}`, by_key: {}};
  }
  if (wl.some((w) => m.active(w).size < th["min_den"])) {
    return {status: `not tested: needs ${th["min_den"]} or more active people in each of the last ${k} weeks`, by_key: {}};
  }
  if (!m.cal || !((m.cal.releases && m.cal.releases.length) || (m.cal.sprints && m.cal.sprints.length))) {
    return {status: "not tested: no calendar supplied, so use around a cycle boundary cannot be checked", by_key: {}};
  }
  const bwk = _boundary_weeks(m);
  const bw = wl.filter((w) => bwk.has(w));
  if (!bw.length) {
    return {status: `not tested: no cycle boundary in the last ${k} weeks, so use around one cannot be checked`, by_key: {}};
  }
  const out = {};
  for (const key of Object.keys(READ_SECTIONS)) {
    if (key === "top") continue;
    const low = wl.every((w) => 100 * m.readers(w, key, m.active(w)) / m.active(w).size <= th["simplify_reach_pct"]);
    if (low) out[key] = "Simplify candidate";
  }
  return {status: `tested: ${Object.keys(out).length} candidate(s) (reach ${th["simplify_reach_pct"]}% or less in each of the last ${k} weeks and at a cycle boundary)`, by_key: out};
}


function controls_view(m, wk) {
  const th = m.th;
  const A = wk.length ? set_union(...wk.map((w) => m.active(w))) : new Set();
  const N = A.size;
  const users = new Map();
  let any_f = new Set();
  for (const w of wk) {
    for (const [k, us] of _vw_entries(m.ctl(w))) {
      const cur = _vw_getset(users, k);
      for (const u of us) { cur.add(u); any_f.add(u); }
    }
  }
  const fams = [];
  for (const [fam, keys] of CONTROL_FAMILIES) {
    const rows = [];
    for (const k of keys) {
      const n = _vw_getset(users, k).size;
      rows.push({key: k, name: CONTROLS[k], reach: gn(n), raw: n, pct: n >= MIN_USERS ? pct_of(n, N, th) : null});
    }
    fams.push({family: fam, rows: rows});
  }
  // reset in the same visit (v2): visits with a reset after at least one control change / visits with at least one control change
  function changed(r) {
    return _vw_values(_vw_sess(r, "f")).some((v) => _vw_pos(v));
  }
  function wk_reset(ws) {
    const rs = m.visits(ws).filter((r) => r.v2 && changed(r));
    const rr = rs.filter((r) => r.s["rr"] === 1);
    return [rs, rr];
  }
  const rs_all = [];
  for (const w of wk) for (const r of m.visits(w)) if (r.v2 && changed(r)) rs_all.push(r);
  const rr_all = rs_all.filter((r) => r.s["rr"] === 1);
  const reset = {state: "ok", visits: rs_all.length, n_users: new Set(rs_all.map((r) => r.u)).size};
  reset["visits_g"] = g(reset["n_users"], rs_all.length);
  if (!rs_all.length) {
    reset["state"] = "none";
  } else {
    const rp = new Set(rr_all.map((r) => r.u));
    const rr_set = new Set(rr_all);
    const pc = partition_cells({rr: [rp, rr_all.length], rest: [new Set(rs_all.filter((r) => !rr_set.has(r)).map((r) => r.u)), rs_all.length - rr_all.length]});
    reset["x"] = pc["rest"] !== SMALL ? pc["rr"] : SMALL;
    reset["pct"] = reset["x"] !== SMALL ? pct_of(rr_all.length, rs_all.length, th) : null;
    let flagged = false;
    const wl = [];
    for (let i = th["reset_weeks"] - 1; i >= 0; i--) wl.push(d_add(m.last, -7 * i));
    if (wl.every((w) => m.usable(w))) {
      flagged = true;
      for (const w of wl) {
        const [a, b] = wk_reset(w);
        if (!(new Set(a.map((r) => r.u)).size >= th["reset_min_people"] && a.length >= th["reset_min_visits"] && b.length >= th["reset_rate"] * a.length)) {
          flagged = false;
        }
      }
    }
    reset["flag"] = flagged;
  }
  return {n: N, n_g: gn(N), d: (N === 0 || N >= MIN_USERS) ? N : SMALL, weeks: wk.length, families: fams, any: {x: gn(any_f.size), pct: any_f.size >= MIN_USERS ? pct_of(any_f.size, N, th) : null, raw: any_f.size}, reset: reset,
          multi_vs_projects: [gn(_vw_getset(users, "multi").size), gn(_vw_getset(users, "projects").size)]};
}


function use_view(m, wk) {
  const th = m.th;
  const rows = _window_rows(m, wk);
  const eng = rows.filter((r) => !r.glance);
  const A = wk.length ? set_union(...wk.map((w) => m.active(w))) : new Set();
  const out = {engaged: eng.length, engaged_g: g(A.size, eng.length), weeks: wk.length, people: gn(A.size), n_people: A.size};
  // A5
  function clicks(r, key = null) {
    let t = 0;
    for (const [k, v] of Object.entries(_vw_sess(r, "l"))) {
      if (_vw_has(LINK_SECTIONS, k) && _vw_pos(v) && (key === null || k === key)) t += v;
    }
    return t;
  }
  const link_vis = eng.filter((r) => clicks(r) > 0);
  const lp = new Set(link_vis.map((r) => r.u));
  out["links"] = {x: gn(lp.size), visits: g(lp.size, link_vis.length), pct: lp.size >= MIN_USERS ? pct_of(link_vis.length, eng.length, th) : null, of: eng.length, sections: []};
  for (const [key, nm] of Object.entries(LINK_SECTIONS)) {
    let n_c = 0;
    for (const r of eng) n_c += clicks(r, key);
    const ppl = new Set(eng.filter((r) => clicks(r, key) > 0).map((r) => r.u));
    if (n_c >= th["link_min_clicks"] && ppl.size >= th["link_min_people"]) {
      const vis = eng.filter((r) => clicks(r, key) > 0);
      const rate = (w) => {
        const e_w = m.visits(w).filter((r) => !r.glance);
        return e_w.length ? 100 * e_w.filter((r) => clicks(r, key) > 0).length / e_w.length : 0;
      };
      const bw = m.baseline(m.last);
      let status = `baseline building (${bw.length} of ${th["baseline_min"]} weeks)`;
      if (bw.length >= th["baseline_min"] && m.usable(m.last)) {
        const b = robust_band(bw.map((w) => rate(w)), th["floor_reach_pp"], th["baseline_min"], th["band_mad"]);
        const cur = rate(m.last);
        status = cur > b["hi"] ? "above its usual range" : cur < b["lo"] ? "below its usual range" : "within its usual range";
      }
      out["links"]["sections"].push({name: nm, pct: pct_of(vis.length, eng.length, th), x: gn(ppl.size), status: status});
    }
  }
  const mins = eng.filter((r) => _vw_pos(r.s["s"])).map((r) => r.s["s"] / 60);
  const mp = new Set(eng.filter((r) => _vw_pos(r.s["s"])).map((r) => r.u));
  out["minutes"] = {median: mins.length ? g(mp.size, pyround(median(mins), 1)) : null, visits: g(mp.size, mins.length), people: gn(mp.size)};
  out["per_person"] = {value: A.size >= MIN_USERS ? pyround(eng.length / A.size, 1) : (A.size ? SMALL : null), n: gn(A.size)};
  // A6
  const dev = eng.filter((r) => _vw_has(DEVICES, r.s["d"]));
  const small = dev.filter((r) => r.s["d"] === "s");
  const sp = new Set(small.map((r) => r.u));
  const rest = dev.filter((r) => r.s["d"] !== "s");
  const pc6 = dev.length ? partition_cells({small: [sp, small.length], rest: [new Set(rest.map((r) => r.u)), rest.length]}) : {small: 0, rest: 0};
  out["phone"] = {n: dev.length, n_g: g(A.size, dev.length), x: pc6["rest"] !== SMALL ? pc6["small"] : SMALL, pct: !Object.values(pc6).includes(SMALL) ? pct_of(small.length, dev.length, th) : null};
  // A7
  const rp = new Set(rows.filter((r) => _vw_pos(r.s["r"])).map((r) => r.u));
  out["refresh"] = {x: gn(rp.size), pct: rp.size >= MIN_USERS ? pct_of(rp.size, A.size, th) : null, n: A.size, n_g: gn(A.size)};
  const v2 = rows.filter((r) => r.v2);
  const ro = {};
  for (const k of Object.keys(RO)) {
    const us = new Set(v2.filter((r) => _vw_pos(_vw_sess(r, "ro")[k])).map((r) => r.u));
    let tot = 0;
    for (const r of v2) {
      const v = _vw_sess(r, "ro")[k];
      if (_vw_pos(v)) tot += Math.trunc(v);
    }
    ro[k] = {people: gn(us.size), n: g(us.size, tot)};
  }
  const rt_users = new Set(v2.filter((r) => _vw_pos(r.s["rt"])).map((r) => r.u));
  let rt_tot = 0;
  for (const r of v2) if (_vw_pos(r.s["rt"])) rt_tot += Math.trunc(r.s["rt"]);
  Object.assign(out["refresh"], {outcomes: ro, retries: g(rt_users.size, rt_tot), has_v2: v2.length > 0});
  // A8
  const fresh = {};
  for (const [key, names, label] of [["lv", LV, "Connection"], ["fa", FA, "Age of the data at the start of the visit"]]) {
    const have = v2.filter((r) => is_num(r.s[key]));
    if (!have.length) {
      fresh[key] = null;
      continue;
    }
    const groups = {};
    for (const [code, nm] of _vw_items_num(names)) {
      const sel = have.filter((r) => r.s[key] === code);
      groups[nm] = [new Set(sel.map((r) => r.u)), sel.length];
    }
    const pc = partition_cells(groups);
    let vis_sum = 0;
    for (const c of Object.values(pc)) if (c !== SMALL) vis_sum += c;
    const shares = {};
    for (const [nm, c] of Object.entries(pc)) shares[nm] = (c !== SMALL && vis_sum) ? rnd(100 * c / vis_sum) : null;
    fresh[key] = {label: label, n: have.length, n_g: g(A.size, have.length), cells: pc, shares: shares, hidden: Object.values(pc).includes(SMALL)};
  }
  out["fresh"] = fresh;
  return out;
}


function health_view(m) {
  const th = m.th;
  const rows = m.rows;
  const v2 = rows.filter((r) => r.v2);
  const v1 = rows.filter((r) => !r.v2);
  const npp = m.people.length;
  const usersOf = (rs) => new Set(rs.map((r) => r.u));
  const out = {visits: rows.length, visits_g: g(npp, rows.length), v2: v2.length, v2_g: g(usersOf(v2).size, v2.length), v1: v1.length, has_v2: v2.length > 0};
  out["v1_people"] = gn(usersOf(v1).size);
  out["v1_visits"] = g(usersOf(v1).size, v1.length);
  const gl = v2.filter((r) => r.glance);
  const en = v2.filter((r) => !r.glance);
  const pc = partition_cells({glance: [usersOf(gl), gl.length], engaged: [usersOf(en), en.length]});
  out["glance"] = {x: pc["glance"], engaged: pc["engaged"], pct: !Object.values(pc).includes(SMALL) ? pct_of(gl.length, v2.length, th) : null, n: v2.length, n_g: out["v2_g"]};

  function share_of(sel, den) {
    const p = usersOf(sel);
    const x = g(p.size, sel.length);
    return {x: x, n: den.length, n_g: g(usersOf(den).size, den.length), pct: x !== SMALL ? pct_of(sel.length, den.length, th) : null, people: gn(p.size)};
  }
  const focus = v2.filter((r) => _vw_pos(r.s["vs"]) && !_vw_pos(r.s["s"]));
  out["focus"] = share_of(focus, v2);
  out["errors_real"] = share_of(v2.filter((r) => _vw_pos(r.s["er"])), v2);
  out["errors_benign"] = share_of(v2.filter((r) => _vw_pos(r.s["erb"])), v2);
  out["errors_v1"] = share_of(v1.filter((r) => _vw_pos(r.s["er"])), v1);
  out["dropped"] = share_of(rows.filter((r) => _vw_pos(r.s["x"])), rows);
  let s_tot = 0;
  for (const r of rows) if (_vw_pos(r.s["s"])) s_tot += r.s["s"];
  let sec_tot = 0;
  for (const r of rows) {
    for (const [k, v] of Object.entries(_vw_sess(r, "sec"))) {
      if (_vw_has(READ_SECTIONS, k) && _vw_pos(v)) sec_tot += v;
    }
  }
  out["attributed"] = (s_tot && m.people.length >= MIN_USERS) ? rnd(100 * Math.min(1, sec_tot / s_tot)) : null;
  out["stale_records"] = (m.stale_records === 0 || m.stale_records >= MIN_USERS) ? m.stale_records : SMALL;
  out["pruned_records"] = (m.pruned_records === 0 || m.pruned_records >= MIN_USERS) ? m.pruned_records : SMALL;
  out["stale_sessions"] = m.counts["stale_sessions"];
  return out;
}


// ------------------------------------------------------------------------------------------------------------ the daily view and the calendar notes
function calendar_marks(m, lo, hi) {
  const marks = [];
  const cal = m.cal || {};
  for (const r of (cal.releases || [])) {
    for (const [d, label] of [[r["w1"], `W1 starts (${r["release"]})`], [r["w6_end"], `End of W6, Delivery Cycle 1 ends (${r["release"]})`], [r["end"], `Release end, end of W12 (${r["release"]})`]]) {
      if (lo <= d && d <= hi) marks.push([d, label, "ms"]);
    }
  }
  for (const s of (cal.sprints || [])) {
    if (lo <= s["start"] && s["start"] <= hi) marks.push([s["start"], "Sprint starts", "sp"]);
  }
  for (const d of (cal.events || [])) {
    if (lo <= d && d <= hi) marks.push([d, "Owner review day", "ev"]);
  }
  return marks.sort((a, b) => {                              // sorted(tuples): element by element, stable
    for (let i = 0; i < 3; i++) {
      if (a[i] < b[i]) return -1;
      if (a[i] > b[i]) return 1;
    }
    return 0;
  });
}


function calendar_note(m) {
  const cal = m.cal || {};
  const rels = (cal.releases || []).filter((r) => r["w1"] <= m.ref);
  if (!rels.length || !m.data_start) return null;
  let r = rels[0];
  for (const x of rels) if (x["w1"] > r["w1"]) r = x;
  const wk = (d) => Math.floor(d_diff(d, r["w1"]) / 7) + 1;
  const a = Math.max(1, wk(m.data_start)), b = Math.min(12, wk(m.ref));
  const bounds = [r["w6_end"], r["end"]].filter((d) => m.data_start <= d && d < m.ref);
  const start = m.data_start >= r["w1"] ? "" : " (the data starts before W1)";
  if (bounds.length) {
    return `Data covers W${a} to W${b} of release ${r["release"]}${start} and includes ${bounds.includes(r["w6_end"]) ? "the end of Delivery Cycle 1 (W6)" : "the release end"}.`;
  }
  return `Data covers W${a} to W${b} of release ${r["release"]}${start} so far; no cycle boundary has been observed yet.`;
}


function event_windows(m, per_day) {
  // per_day: Map {day: people}
  const th = m.th;
  const ev = [...((m.cal || {}).events || [])].sort();
  if (!ev.length) return null;
  const work = [...per_day.keys()].filter((d) => WORKDAYS.includes(d_weekday(d)) && d < m.ref && (m.data_start && d >= m.data_start)).sort();
  const idx = new Map(work.map((d, i) => [d, i]));
  const wins = [];
  for (const d of ev) {
    let e = null;
    for (const x of work) if (x <= d) e = x;                 // work is sorted: the last day on or before d
    if (e === null || idx.get(e) < th["event_days"] - 1) continue;
    wins.push(idx.get(e));
  }
  const n_ev = ev.length;
  if (wins.length < th["event_min"]) {
    return {state: "few", events: n_ev, usable: wins.length, text: `${n_ev} review day${n_ev !== 1 ? "s" : ""} marked, ${wins.length} with a complete window: ${wins.length === 1 ? "one observation" : "too few observations"}, not a pattern (needs ${th["event_min"]}).`};
  }
  const k = th["event_days"];
  const win_mean = (i) => _vw_mean(_vw_range(k).map((j) => per_day.get(work[i - j])));
  const ev_vals = wins.map((i) => win_mean(i));
  const used = new Set();
  for (const i of wins) for (let x = i - k + 1; x <= i; x++) used.add(x);
  const others = [];
  for (let i = k - 1; i < work.length; i++) {
    let hit = false;
    for (let x = i - k + 1; x <= i; x++) if (used.has(x)) { hit = true; break; }
    if (!hit) others.push(win_mean(i));
  }
  if (!others.length) {
    return {state: "few", events: n_ev, usable: wins.length, text: "No other window to compare with."};
  }
  const a = median(ev_vals), b = median(others);
  return {state: "ok", events: n_ev, usable: wins.length, text: `Average people per working day in the ${k} days ending on a review day: ${gm(a)} (median of ${wins.length} windows); in other ${k}-day windows: ${gm(b)} (median of ${others.length}). This is an association, not a measured effect.`};
}


function daily_view(m) {
  const ref = m.ref;
  const by_day = new Map();
  for (const r of m.rows) _vw_getset(by_day, r.day).add(r.u);
  const days = [];
  for (let i = 27; i >= 0; i--) {
    const d = d_add(ref, -i);
    const n = by_day.has(d) ? by_day.get(d).size : 0;
    days.push({day: d, users: gn(n), raw: n, has_data: !!(m.data_start && d >= m.data_start), weekend: WEEKEND.includes(d_weekday(d)), partial: d === ref});
  }
  const marks = calendar_marks(m, days[0]["day"], days[days.length - 1]["day"]);
  const per = new Map(days.map((d) => [d["day"], d["raw"]]));
  const lo28 = d_add(ref, -27);
  const rows28 = m.rows.filter((r) => lo28 <= r.day && r.day < ref);
  let ww = null;
  if (rows28.length >= m.th["workweek_min_visits"] && new Set(rows28.map((r) => r.u)).size >= MIN_USERS) {
    ww = {pct: rnd(100 * rows28.filter((r) => WORKDAYS.includes(d_weekday(r.day))).length / rows28.length), n: rows28.length};
  }
  return {days: days, marks: marks, workweek: ww, events: event_windows(m, per), note: calendar_note(m)};
}


function week_to_date(m) {
  const th = m.th;
  const cur = m.cur, ref = m.ref;
  const n = d_diff(ref, cur);
  const prev_lo = d_add(cur, -7);
  const prev_hi = d_add(prev_lo, n);
  const cur_rows = m.visits(cur);
  const prev_rows = m.visits(prev_lo).filter((r) => r.day <= prev_hi);
  const cur_p = m.active(cur), prev_p = new Set(prev_rows.map((r) => r.u));
  let state;
  if (!cur_rows.length && n === 0) state = "no_current";
  else if (!prev_rows.length) state = "no_baseline";
  else if (m.data_start && m.data_start > prev_lo) state = "partial";
  else state = "ok";

  function metric(cur_val, prev_val) {
    const sc = g(cur_p.size, cur_val), sp = g(prev_p.size, prev_val);
    const d = (state === "ok" || state === "partial") && sc !== SMALL && sp !== SMALL ? cur_val - prev_val : null;
    return {cur: sc, prev: sp, raw_cur: cur_val, raw_prev: prev_val, diff: d, pct: d ? pct_of(Math.abs(d), prev_val, th) : null};
  }

  const mix = (rows) => new Set(rows.map((r) => r.v2 ? "v2" : "v1"));
  const same_mix = (x, y) => x.size === y.size && [...x].every((k) => y.has(k));
  return {state: state, ref: ref, n: n, cur_lo: cur, cur_hi: ref, prev_lo: prev_lo, prev_hi: prev_hi,
          data_from: m.data_start && m.data_start > prev_lo ? m.data_start : null,
          people: metric(cur_p.size, prev_p.size), visits: metric(cur_rows.length, prev_rows.length),
          rules_changed: cur_rows.length > 0 && prev_rows.length > 0 && !same_mix(mix(cur_rows), mix(prev_rows))};
}


// ------------------------------------------------------------------------------------------------------------ the aggregate
function aggregate(bodies, opts) {
  // opts: {today, as_of, now, demo, since, audience, calendar (the RAW calendar JSON or null), th, stats}; dates are ISO strings, as_of and now ISO datetimes with offset
  opts = opts || {};
  const th = opts.th || THRESHOLDS;
  set_min_group(th["min_group"] !== undefined ? th["min_group"] : 5);
  const demo = !!opts.demo;
  const since = opts.since || null;
  const audience = opts.audience || null;
  const as_of = opts.as_of || null;
  const stats = opts.stats || null;
  const calendar = opts.calendar ? parse_calendar(opts.calendar) : null;
  const now = opts.now || new Date().toISOString();
  const now_date = opts.today || dt_il_date(now);
  let ref, age;
  if (as_of) {
    ref = dt_il_date(as_of);
    age = d_diff(now_date, ref);
  } else {
    ref = now_date;
    age = null;
  }
  const m = new Model(bodies, ref, since, calendar, th);
  const latest_age = m.last_day ? d_diff(ref, m.last_day) : null;
  const ctx = {export_age_days: age, latest_visit_age: latest_age, stats: stats || {}, calendar_warnings: (calendar || {}).warnings || []};
  const sig = detect_signals(m, ctx);
  const wk = window_weeks(m);
  const n_people = m.people.length;
  let comp = null;
  if (m.usable(m.last)) {
    const ev = _eval_count(m, m.last, (w) => m.active(w).size);
    comp = {ws: m.last, label: week_label(m.last), active: gn(m.active(m.last).size), raw: m.active(m.last).size, state: ev["state"], n_baseline: _vw_has(ev, "n") ? ev["n"] : (ev["weeks"] || []).length, established: m.established(m.last).size};
    if (ev["state"] === "ok") {
      const b = ev["band"];
      Object.assign(comp, {median: gm(b["median"]), lo: gm(Math.max(0, b["lo"])), hi: gm(b["hi"]), raw_lo: Math.max(0, b["lo"]), raw_hi: b["hi"], n_weeks: b["n"], inside: !ev["outside"], above: ev["cur"] > b["hi"], below: ev["cur"] < b["lo"]});
    }
  }
  let aud = null;
  if (audience) {
    const x = comp ? m.active(m.last).size : null;
    aud = {size: audience, people: gn(n_people), x: x !== null ? gn(x) : null, stale: n_people > audience,
           pct: (x !== null && x >= MIN_USERS && audience >= th["min_den"] && n_people <= audience) ? rnd(100 * x / audience) : null};
  }
  const wk_hi = wk.length ? (d_add(wk[wk.length - 1], 6) < ref ? d_add(wk[wk.length - 1], 6) : ref) : null;
  return {
    demo: demo, today: now_date, ref: ref, as_of: as_of, export_age_days: age, latest_visit_age: latest_age, since: since,
    n_docs: bodies.length, n_sessions: m.rows.length, n_people: {raw: n_people, n: gn(n_people)}, first_day: m.first_day, last_day: m.last_day,
    history_days: m.first_day ? d_diff(ref, m.first_day) + 1 : 0, data_start: m.data_start, provisional_first: m.provisional_first, first_week: m.first_week,
    compared: comp, signals: sig, weeks: growth_accounting(m), growth: growth_verdict(m), habit: habit_view(m), retention: retention_view(m),
    window: {weeks: wk.length, lo: wk.length ? wk[0] : null, hi: wk_hi, label: wk.length ? `${d_label(wk[0])} to ${d_label(wk_hi)}` : ""},
    sections: sections_view(m, wk), controls: controls_view(m, wk), use: use_view(m, wk), health: health_view(m), daily: daily_view(m), wtd: week_to_date(m), audience: aud,
    stats: stats || {}, counts: m.counts, model: m,
  };
}
