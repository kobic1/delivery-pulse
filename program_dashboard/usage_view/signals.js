// signals.js: usage_report.py lines 610-1030 (_weeks_phrase, _confidence, _persist, _eval_count, _eval_reach, _eval_control_event, detect_signals, _s7). Literal port: same names, same order, same strings.

function _weeks_phrase(m, n) {
  // 'the last 4 completed weeks', or with --show-all 'the last 3 completed weeks and the week so far'; with no completed week 'the week so far'.
  const partial = Boolean(m.th["show_partial_week"] && m.by_week.has(m.cur));
  const done = partial ? n - 1 : n;
  if (!done) {
    return "the week so far";
  }
  return `the last ${done} completed week${done === 1 ? "" : "s"}` + (partial ? " and the week so far" : "");
}


function _confidence(weeks_seen, active, th, soft = false) {
  if (weeks_seen >= 3) {
    return "Confirmed";
  }
  if (weeks_seen === 2) {
    return "Corroborated";
  }
  return (active < th["weak_active_people"] || soft) ? "Weak signal" : "Single-source";
}


function _persist(m, ws, fn) {
  // How many consecutive completed weeks ending at ws (at most 3) show the same flagged change in the same direction.
  const r0 = fn(ws);
  if (!r0.fired) {
    return 0;
  }
  let n = 1;
  for (const i of [1, 2]) {
    const w = d_add(ws, -7 * i);
    if (!m.usable(w)) {
      break;
    }
    const r = fn(w);
    if (r.fired && r.dir === r0.dir) {
      n += 1;
    } else {
      break;
    }
  }
  return n;
}


function _eval_count(m, ws, series, up_only = false, min_cur = null) {
  // A weekly count against the normal range of the comparable weeks before it.
  const th = m.th;
  const bw = m.baseline(ws);
  if (bw.length < th["baseline_min"]) {
    return {state: "building", n: bw.length, cur: series(ws)};
  }
  const vals = bw.map((w) => series(w));
  const med = median(vals);
  const b = robust_band(vals, Math.max(th["floor_people_abs"], th["floor_people_rel"] * med), th["baseline_min"], th["band_mad"]);
  const cur = series(ws);
  const change = cur - b.median;
  const outside = cur > b.hi || (!up_only && cur < b.lo);
  const material = Math.abs(change) >= Math.max(th["change_people_abs"], th["change_people_rel"] * b.median);
  const fired = outside && material && (min_cur === null || min_cur === undefined || cur >= min_cur);
  return {state: "ok", cur: cur, band: b, change: change, fired: fired, dir: change > 0 ? 1 : -1, outside: outside, weeks: bw};
}


function _eval_reach(m, ws, kind, key) {
  // The reach (people with the section 30 s or more that week, or people who changed the control) among the established active people, against the comparable weeks before.
  const th = m.th;

  function val(w) {
    const est = m.established(w);
    return [kind === "sec" ? m.readers(w, key, est) : m.users_of_control(w, key, est), est.size];
  }
  const n_now = m.established(ws).size;
  if (n_now < th["min_den"]) {
    return {state: "few", n: n_now};
  }
  const bw = m.baseline(ws, (w) => m.established(w).size);
  if (bw.length < th["baseline_min"]) {
    return {state: "building", n: bw.length};
  }
  const ser = bw.map((w) => val(w));
  const pcts = ser.map(([x, n]) => 100 * x / n);
  if (kind === "sec" && ser.filter(([x]) => x >= MIN_USERS).length < Math.max(th["s3_baseline_weeks_with_readers"], Math.ceil(0.8 * bw.length))) {
    return {state: "sparse", n: bw.length};
  }
  const [x, n] = val(ws);
  const b = robust_band(pcts, th["floor_reach_pp"], th["baseline_min"], th["band_mad"]);
  const pct = 100 * x / n;
  const change = pct - b.median;
  if (0 < x && x < MIN_USERS) {
    return {state: "unknown", x: x, n: n, pct: pct, band: b};
  }
  const fired = (pct > b.hi || pct < b.lo) && Math.abs(change) >= th["change_reach_pp"];
  return {state: "ok", x: x, n: n, pct: pct, band: b, change: change, fired: fired, dir: change > 0 ? 1 : -1, weeks: bw};
}


function _eval_control_event(m, ws, key) {
  // S4: a control newly used (baseline under 5 people every week, now 5 or more and 10% or more) or no longer used (10% or more in 4 of the 5 baseline weeks, then under 5 in two consecutive weeks).
  const th = m.th;
  const prev = d_add(ws, -7);

  function val(w) {
    const est = m.established(w);
    return [m.users_of_control(w, key, est), est.size];
  }
  if (m.established(ws).size < th["min_den"]) {
    return {state: "few", n: m.established(ws).size};
  }
  const bw = m.baseline(ws, (w) => m.established(w).size);
  if (bw.length < th["baseline_min"]) {
    return {state: "building", n: bw.length};
  }
  const [x, n] = val(ws);
  const ser = new Map(bw.map((w) => [w, val(w)]));
  if ([...ser.values()].every((v) => v[0] < MIN_USERS) && x >= MIN_USERS && 100 * x / n >= th["s4_new_pct"]) {
    return {state: "ok", fired: true, dir: 1, kind: "new", x: x, n: n};
  }
  if (m.usable(prev)) {
    const [px, pn] = val(prev);
    const base = bw.filter((w) => w !== prev);
    if (pn >= th["min_den"] && base.filter((w) => 100 * ser.get(w)[0] / ser.get(w)[1] >= th["s4_stop_pct"]).length >= th["s4_stop_weeks"] && px < MIN_USERS && x < MIN_USERS) {
      return {state: "ok", fired: true, dir: -1, kind: "stopped", x: x, n: n};
    }
  }
  return {state: "ok", fired: false, x: x, n: n};
}


// ------------------------------------------------------------------------------------------------------------ the signals S0 to S9
function detect_signals(m, ctx = null) {
  // What changed in the last completed week against the comparable weeks before it (see the Python docstring).
  const th = m.th;
  const L = m.last;
  const out = {compared: null, flagged: [], ledger: [], tested: [], not_tested: [], cap_hidden: 0};
  const led = (i, name, status, text) => { out.ledger.push({id: i, name: name, status: status, text: text}); };
  const SIG = (i, name, headline, obs, base, thr, conf, nshow, nxt) => {
    out.flagged.push({id: i, name: name, headline: headline, observation: obs, baseline: base, threshold: thr, confidence: conf, not_show: nshow, next: nxt});
  };

  function untested(i, name, reason) {
    led(i, name, "not_tested", reason);
    out.not_tested.push([name, reason]);
  }

  if (!m.usable(L)) {
    const why = !m.weeks.length ? "no completed week of data yet" : "the only completed week is the first week of data, which starts mid-week and is provisional";
    for (const [i, name] of [["S0", "Weekly active people"], ["S1", "New active people"], ["S2", "Lapsed regular people"], ["S3", "Section reach"], ["S4", "Controls newly used or no longer used"],
                             ["S5", "Page errors"], ["S6", "Published-version split"], ["S8", "Snapshot-only visits"], ["S9", "Stale data seen"]]) {
      untested(i, name, why);
    }
    _s7(m, ctx, out, led, SIG, untested);
    return out;
  }
  const act = m.active(L);
  const n_act = act.size;
  const est = m.established(L);
  out.compared = {ws: L, label: week_label(L), active: gn(n_act), raw_active: n_act, established: est.size};
  const nb_all = m.baseline(L).length;
  out.compared.baseline_weeks = nb_all;
  const wk = week_label(L);
  let ev, name, b, seen;

  // ---- S0 weekly active people
  ev = _eval_count(m, L, (w) => m.active(w).size);
  name = "Weekly active people";
  if (ev.state === "building") {
    untested("S0", name, `baseline building (${ev.n} of ${th["baseline_min"]} comparable weeks)`);
  } else if (0 < ev.cur && ev.cur < MIN_USERS) {
    led("S0", name, "unknown", `${SMALL} active in the compared week: Unknown`);
    out.tested.push(name);
  } else {
    out.tested.push(name);
    b = ev.band;
    const txt = `${ev.cur} people active; usual ${gm(b.median)} (normal range ${gm(Math.max(0, b.lo))} to ${gm(b.hi)}, ${b.n} weeks)`;
    if (ev.fired) {
      seen = _persist(m, L, (w) => _eval_count(m, w, (x) => m.active(x).size));
      const more = ev.dir > 0;
      led("S0", name, "flagged", txt);
      SIG("S0", name, `${more ? "More" : "Fewer"} people were active than usual`, `${ev.cur} people were active in ${wk}, against a usual ${gm(b.median)}.`,
          `Median of the ${b.n} comparable completed weeks before: ${gm(b.median)}; normal range ${gm(Math.max(0, b.lo))} to ${gm(b.hi)}.`,
          `Outside the range and at least ${Math.max(th["change_people_abs"], rnd(th["change_people_rel"] * b.median))} people (${rnd(100 * th["change_people_rel"])}%) from the median.`,
          _confidence(seen, n_act, th), "The reason for the change: the count says nothing about any person or about what lies behind it. Visits are not counted here.",
          "Worth investigating: whether a message, a review meeting or a release milestone coincides with the change (see the calendar notes), and whether the change is in new or in established people (S1).");
    } else {
      led("S0", name, "within", txt);
    }
  }

  // ---- S1 new active people
  ev = _eval_count(m, L, (w) => m.new(w).size, true, th["s1_min_new"]);
  name = "New active people";
  if (ev.state === "building") {
    untested("S1", name, `baseline building (${ev.n} of ${th["baseline_min"]} comparable weeks)`);
  } else {
    out.tested.push(name);
    b = ev.band;
    const usual = (rnd(b.hi) >= MIN_USERS && rnd(b.median) !== 0 && rnd(b.median) >= MIN_USERS) ? `usual ${gm(b.median)} (normal range up to ${gm(b.hi)}, ${b.n} weeks)` : `usually under ${MIN_USERS} a week (${b.n} weeks)`;
    const txt = `${gn(ev.cur)} new; ${usual}`;
    if (ev.fired) {
      seen = _persist(m, L, (w) => _eval_count(m, w, (x) => m.new(x).size, true, th["s1_min_new"]));
      led("S1", name, "flagged", txt);
      SIG("S1", name, "More new people than usual", `${ev.cur} people were seen for the first time in ${wk}, against a usual ${rnd(b.median) >= MIN_USERS ? gm(b.median) : "under " + pystr(MIN_USERS)}.`,
          `Median of the ${b.n} comparable completed weeks before: ${rnd(b.median) >= MIN_USERS ? gm(b.median) : "under " + pystr(MIN_USERS)}; upper end of the range ${rnd(b.hi) >= MIN_USERS ? gm(b.hi) : "under " + pystr(MIN_USERS)}.`, `At least ${th["s1_min_new"]} new people and above the range (increases only).`,
          _confidence(seen, n_act, th), "Whether they come back: new people are reported separately from established people and are not in the reach or control signals.",
          "Worth investigating: whether an announcement or a change of the audience coincides with the new people; the cohort retention view shows whether they return.");
    } else {
      led("S1", name, "within", txt);
    }
  }

  // ---- S2 lapsed regular people (aggregate only)
  name = "Lapsed regular people";
  const k_full = m.weeks.filter((w) => !m.is_prov(w)).length;
  if (k_full < th["s2_weeks_needed"]) {
    untested("S2", name, `needs ${th["s2_weeks_needed"]} completed weeks, has ${k_full}`);
  } else {
    out.tested.push(name);

    const eval_s2 = (ws) => {
      for (let i = 0; i < 7; i++) {
        if (!m.usable(d_add(ws, -7 * i))) {
          return {fired: false};
        }
      }
      const base = [6, 5, 4, 3].map((i) => d_add(ws, -7 * i));
      const regs = new Set(m.people.filter((u) => base.filter((w) => m.active(w).has(u)).length >= th["s2_regular_weeks"]));
      const recent = [2, 1, 0].map((i) => d_add(ws, -7 * i));
      const lapsed = new Set([...regs].filter((u) => !recent.some((w) => m.active(w).has(u))));
      const fired = regs.size >= th["s2_min_regulars"] && lapsed.size >= th["s2_min_lapsed"] && lapsed.size >= th["s2_lapsed_share"] * regs.size;
      return {fired: fired, dir: -1, regs: regs.size, lapsed: lapsed.size};
    };
    const r = eval_s2(L);
    const txt = r.regs >= th["s2_min_regulars"] ? `${gn(r.regs)} regular people, ${gn(r.lapsed)} of them lapsed` : `fewer than ${th["s2_min_regulars"]} regular people: not enough to judge`;
    if (r.fired) {
      seen = _persist(m, L, eval_s2);
      const pc = protect_partition({lapsed: r.lapsed, still: r.regs - r.lapsed}, r.regs);
      led("S2", name, "flagged", txt);
      let obs;
      if (pc.lapsed === SMALL) {
        obs = `A group of the ${r.regs} regular people has stopped visiting; its size is withheld because the remaining count would reveal a group under ${MIN_USERS} people.`;
      } else {
        obs = `${r.lapsed} of ${r.regs} regular people (${share_text(r.lapsed, r.regs, th)}) have not visited in the last 3 completed weeks.`;
      }
      SIG("S2", name, "Regular people have stopped visiting", obs,
          `Regular = active in ${th["s2_regular_weeks"]} of the 4 completed weeks from ${d_label(d_add(L, -42))} to ${d_label(d_add(d_add(L, -21), 6))}; lapsed = regular with no visit in the 3 weeks since.`,
          `At least ${th["s2_min_regulars"]} regulars, ${th["s2_min_lapsed"]} lapsed and ${rnd(100 * th["s2_lapsed_share"])}% of the regulars.`, _confidence(seen, n_act, th),
          "Whether they stopped for good, use another source or were away; the count is an aggregate and says nothing about any person.",
          "Worth investigating: whether a change of the audience, of the page or of a review routine coincides with the drop.");
    } else {
      led("S2", name, "within", txt);
    }
  }

  // ---- S3 section reach, S4 controls
  const th_min = th["min_den"];
  const s3_flag = [], s4_flag = [];
  let s3_n = 0, s4_n = 0;
  const s3_skip = {}, s4_skip = {};
  for (const [key, nm] of Object.entries(READ_SECTIONS)) {
    ev = _eval_reach(m, L, "sec", key);
    if (ev.state === "few" || ev.state === "building" || ev.state === "sparse") {
      s3_skip[ev.state] = (s3_skip[ev.state] || 0) + 1;
      continue;
    }
    s3_n += 1;
    if (ev.state === "ok" && ev.fired) {
      seen = _persist(m, L, (w) => _eval_reach(m, w, "sec", key));
      s3_flag.push([Math.abs(ev.change), key, nm, ev, seen]);
    }
  }
  for (const [key, nm] of Object.entries(CONTROLS)) {
    ev = _eval_control_event(m, L, key);
    if (ev.state === "few" || ev.state === "building") {
      s4_skip[ev.state] = (s4_skip[ev.state] || 0) + 1;
      continue;
    }
    s4_n += 1;
    if (ev.fired) {
      seen = _persist(m, L, (w) => _eval_control_event(m, w, key));
      s4_flag.push([ev.n, key, nm, ev, seen]);
    }
  }
  for (const [i, name_, n_t, skip, flagged_n] of [["S3", "Section reach", s3_n, s3_skip, s3_flag.length], ["S4", "Controls newly used or no longer used", s4_n, s4_skip, s4_flag.length]]) {
    const unit = i === "S3" ? "sections" : "controls";
    if (n_t === 0) {
      const reason = skip["few"] ? `too few active people (n=${est.size}, needs ${th_min})` : (skip["building"] ? `baseline building (fewer than ${th["baseline_min"]} comparable weeks)` : "baseline weeks had too few readers");
      untested(i, name_, reason);
    } else {
      out.tested.push(name_);
      let extra = "";
      if (Object.keys(skip).length) {
        extra = "; not tested: " + Object.entries(skip).map(([k, v]) => `${v} (${k === "sparse" ? "too few readers in the baseline" : k})`).join(", ");
      }
      led(i, name_, flagged_n ? "flagged" : "within", `${n_t} ${unit} tested, ${flagged_n} flagged${extra}`);
    }
  }
  const items = s3_flag.slice().sort((p, q) => cmp_py(-p[0], -q[0]));
  for (const [, key, nm, ev3, seen3] of items) {
    b = ev3.band;
    const up = ev3.dir > 0;
    SIG("S3", `Reach of ${nm}`, up ? `More people read ${nm}` : `Fewer people read ${nm}`,
        `Reach ${share_text(ev3.x, ev3.n, th)} of established active people in ${wk} (${ev3.x} of n=${ev3.n}), against a usual ${rnd(b.median)}%.`,
        `Median reach of the ${b.n} comparable completed weeks before: ${rnd(b.median)}% (normal range ${rnd(Math.max(0, b.lo))}% to ${rnd(Math.min(100, b.hi))}%).`,
        `Outside the range and at least ${th["change_reach_pp"]} percentage points from the median; reach = people with ${SECTION_MIN_SECONDS} s or more in the section that week, among established people.`,
        _confidence(seen3, ev3.n, th),
        "Whether the section was useful: reach counts the people with time in it. A section can be read by few people on purpose. Scroll position decides which section gets the time.",
        "Worth investigating: whether a change of the page, a release milestone or a review routine coincides with the change in reach.");
  }
  for (const [, key, nm, ev4, seen4] of s4_flag.slice().sort((p, q) => cmp_py([-p[0], p[1]], [-q[0], q[1]]))) {
    const isnew = ev4.kind === "new";
    SIG("S4", `Control: ${nm}`, isnew ? `${nm} is newly used` : `${nm} is no longer used`,
        (isnew
          ? `${ev4.x} established people (${share_text(ev4.x, ev4.n, th)}) changed this control in ${wk}; in the ${m.baseline(L).length} weeks before, fewer than ${MIN_USERS} people did.`
          : `Fewer than ${MIN_USERS} established people changed this control in each of the last 2 completed weeks.`),
        isnew ? `Newly used: under ${MIN_USERS} people in every comparable week before.` : `Stopped: ${th["s4_stop_pct"]}% or more of established people in ${th["s4_stop_weeks"]} of the baseline weeks.`,
        `Newly used: ${MIN_USERS} or more people and ${th["s4_new_pct"]}% or more. Stopped: under ${MIN_USERS} people in ${th["s4_stop_consecutive"]} consecutive weeks.`, _confidence(seen4, ev4.n, th),
        "Whether the control works or is wanted: a change counts the people that touched it, not the effect.",
        "Worth investigating: whether a change of the page or a new routine coincides with the change in use; the control may have moved or been renamed.");
  }

  // ---- S5 page errors
  name = "Page errors";
  out.tested.push(name);

  const eval_err = (ws) => {
    const rs = m.visits(ws);
    const er = rs.filter((r) => is_num(r.s["er"]) && r.s["er"] > 0);
    const people = new Set(er.map((r) => r.u)).size;
    const prev_b = m.usable(d_add(ws, -7))
      ? new Set(m.visits(d_add(ws, -7)).filter((r) => is_num(r.s["er"]) && r.s["er"] > 0 && typeof r.s["b"] === "string").map((r) => r.s["b"]))
      : new Set();
    const now_b = new Set(er.filter((r) => typeof r.s["b"] === "string").map((r) => r.s["b"]));
    const a = people >= th["err_people"];
    const b2 = er.length > 0 && rs.length >= th["err_visit_min"] && er.length >= th["err_visit_share"] * rs.length;
    const c = [...now_b].some((x) => prev_b.has(x));
    return {fired: a || b2 || c, dir: 1, people: people, visits: er.length, n: rs.length, rules: [["people", a], ["share", b2], ["build", c]].filter(([, ok]) => ok).map(([x]) => x), all_v1: er.length > 0 && !er.some((r) => r.v2)};
  };
  const r = eval_err(L);
  const err_from = d_add(m.ref, -(th["err_quiet_days"] - 1));
  const recent = m.rows.filter((x) => x.day >= err_from && is_num(x.s["er"]) && x.s["er"] > 0);
  const older = m.rows.filter((x) => x.day < err_from && is_num(x.s["er"]) && x.s["er"] > 0);
  let hist = "";
  if (older.length) {
    const ou = new Set(older.map((x) => x.u)).size;
    hist = ` Earlier in the data: errors were recorded for ${cnt(gn(ou), "users")}.`;
  }
  if (r.fired) {
    seen = _persist(m, L, eval_err);
    led("S5", name, "flagged", `${cnt(g(r.people, r.visits), "visits")} with an error by ${cnt(gn(r.people), "users")} in the compared week`);
    const why = {people: `${th["err_people"]} or more people had an error`, share: `${rnd(100 * th["err_visit_share"])}% or more of the visits had an error`, build: "the same page version had an error in two consecutive weeks"};
    SIG("S5", name, "Page errors need a look", `${cnt(g(r.people, r.visits), "visits")} ended with an uncaught error in ${wk} (${cnt(gn(r.people), "users")}); ` + r.rules.map((k) => why[k]).join("; ") + ".",
        `Last completed week; errors in the last ${th["err_quiet_days"]} days: ${cnt(g(new Set(recent.map((x) => x.u)).size, recent.length), "visits")}.`,
        `${th["err_people"]} or more people, or ${rnd(100 * th["err_visit_share"])}% or more of the visits (at least ${th["err_visit_min"]} visits), or the same page version in ${th["err_consecutive_weeks"]} consecutive weeks.`,
        _confidence(seen, n_act, th, r.all_v1),
        "What the error was: the page records a count, never the message. In v1 records the count may include harmless browser notifications.",
        "Worth investigating: open the published page with the browser's developer console and compare with the page version that coincides with the errors.");
  } else {
    if (recent.length) {
      const ru = new Set(recent.map((x) => x.u)).size;
      led("S5", name, "within", `${cnt(g(ru, recent.length), "visits")} with an error in the last ${th["err_quiet_days"]} days (${cnt(gn(ru), "users")}): below the flag threshold.` + hist);
    } else {
      led("S5", name, "within", `none in the last ${th["err_quiet_days"]} days.` + hist);
    }
  }

  // ---- S6 published-version split
  name = "Published-version split";
  const rows_bt = m.visits(L).filter((x) => is_num(x.s["bt"]));
  const all_bt = m.rows.filter((x) => is_num(x.s["bt"])).map((x) => x.s["bt"]);
  if (!rows_bt.length) {
    untested("S6", name, "field not recorded in v1: version order unknown; counts only");
  } else {
    const latest = new Map();
    for (const x of rows_bt) {
      latest.set(x.u, Math.max(latest.has(x.u) ? latest.get(x.u) : x.s["bt"], x.s["bt"]));
    }
    const newest = all_bt.reduce((p, q) => (q > p ? q : p));
    const n6 = latest.size;
    if (n6 < th["min_den"]) {
      untested("S6", name, `too few active people (n=${n6}, needs ${th["min_den"]})`);
    } else {
      out.tested.push(name);
      const stale = [...latest.values()].filter((v) => newest - v > th["s6_age_days"]).length;
      const pc = protect_partition({old: stale, new: n6 - stale}, n6);
      if (pc.old === SMALL) {
        led("S6", name, stale ? "unknown" : "within", stale ? `${SMALL} on an older published version` : "no one on a version more than 7 days older than the newest");
      } else {
        const txt = `${stale} of ${n6} people on a version more than ${th["s6_age_days"]} days older than the newest (${share_text(stale, n6, th)})`;
        if (stale >= th["s6_min_people"] && stale >= th["s6_min_share"] * n6) {
          led("S6", name, "flagged", txt);
          SIG("S6", name, "Some people are on an older published version", txt + ".", `Compared with the newest page version seen in the data (build day ${pystr(newest)}).`,
              `${th["s6_min_people"]} or more people and ${rnd(100 * th["s6_min_share"])}% or more of the people active in the week.`, _confidence(1, n_act, th),
              "Why they are on it: a tab left open for days or an old link is associated with it, but the data cannot tell.", "Worth investigating: whether the page is republished while people keep an old tab open, and whether that coincides with other signals.");
        } else {
          led("S6", name, "within", txt);
        }
      }
    }
  }

  // ---- S7 data coverage
  _s7(m, ctx, out, led, SIG, untested);

  // ---- S8 snapshot-only visits, S9 stale data seen
  const v2 = m.visits(L).filter((x) => x.v2);
  for (const [i, name_, key, vals, share_min, people_min, txtname] of [["S8", "Snapshot-only visits", "lv", [1], th["s8_share"], th["s8_min_people"], "snapshot only (no live connection)"],
                                                                      ["S9", "Stale data seen", "fa", [2, 3], th["s9_share"], 0, "data older than 24 hours at the start"]]) {
    const have = v2.filter((x) => is_num(x.s[key]));
    if (!have.length) {
      untested(i, name_, "field not recorded in v1");
      continue;
    }
    if (have.length < th["min_den"]) {
      untested(i, name_, `too few visits (n=${have.length}, needs ${th["min_den"]})`);
      continue;
    }
    out.tested.push(name_);
    const hit = have.filter((x) => vals.includes(x.s[key]));
    const hp = new Set(hit.map((x) => x.u));
    const rest = have.filter((x) => !vals.includes(x.s[key]));
    const pc = partition_cells({hit: [hp, hit.length], rest: [new Set(rest.map((x) => x.u)), rest.length]});
    if (pc.hit === SMALL || pc.rest === SMALL) {
      led(i, name_, "unknown", `a group under ${MIN_USERS} people: not shown (Unknown)`);
      continue;
    }
    const sh = hit.length / have.length;
    const txt = `${share_text(hit.length, have.length, th)} of ${fmt_n(g(n_act, have.length))} visits were ${txtname} (${gn(hp.size)} people)`;
    if (sh >= share_min && hp.size >= Math.max(people_min, MIN_USERS)) {
      led(i, name_, "flagged", txt);
      SIG(i, name_, i === "S9" ? "Many visits saw old or snapshot data" : "Many visits were snapshot only", txt + ".", "Visits of the compared week that recorded the field (v2 pages only).",
          `${rnd(100 * share_min)}% or more of the visits` + (people_min ? ` and ${people_min} or more people` : "") + ".", _confidence(1, n_act, th),
          "Whether anyone acted on old data. The visit starts from the data it finds.", "Worth investigating: whether the data refresh or the connector access coincides with these visits.");
    } else {
      led(i, name_, "within", txt);
    }
  }
  out.ledger.sort((p, q) => cmp_py(p.id, q.id));
  return out;
}


function _s7(m, ctx, out, led, SIG, untested) {
  // S7 data coverage: the age of the export, duplicated or unknown records, records kept past 12 weeks, the share of visits that dropped keys, the size cap.
  const th = m.th;
  const name = "Data coverage";
  if (ctx === null || ctx === undefined) {
    untested("S7", name, "no export information supplied");
    return;
  }
  out.tested.push(name);
  const stats = ctx.stats || {};
  const issues = [], facts = [];
  const age = ctx.export_age_days, lv_age = ctx.latest_visit_age;
  if (age === null || age === undefined) {
    facts.push("export time not supplied (read as taken today)");
  } else {
    facts.push(`export is ${pystr(age)} days old`);
    if (age > th["s7_export_stale_days"]) {
      issues.push(`the export is ${pystr(age)} days old (older than ${th["s7_export_stale_days"]} days): take a new one before reading a trend`);
    }
  }
  if (lv_age !== null && lv_age !== undefined && lv_age > th["s7_export_stale_days"]) {
    issues.push(`the latest visit in the data is ${pystr(lv_age)} days before the report day: the export may be stale`);
  }
  for (const [k, label] of [["duplicates", "duplicated documents dropped"], ["skipped", "rows skipped (not a record)"], ["unknown_schema", "documents with an unknown schema left out"]]) {
    if (stats[k]) {
      issues.push(`${pystr(stats[k])} ${label}`);
    }
  }
  if (stats["round_page"]) {
    issues.push(`the export holds exactly ${pystr(stats["read"])} records, a round page size: confirm the tool's own total`);
  }
  const st = m.stale_records;
  if (st) {
    issues.push(`${st < MIN_USERS ? SMALL.split("users").join("records") : pystr(st) + " records"} not opened for over ${th["retention_weeks"]} weeks: delete them`);
  }
  const pr = m.pruned_records;
  if (pr) {
    issues.push(`${pr < MIN_USERS ? SMALL.split("users").join("records") : pystr(pr) + " records"} where the size cap dropped older weeks`);
  }
  const xr = m.rows.filter((r) => is_num(r.s["x"]) && r.s["x"] > 0);
  if (m.rows.length && xr.length >= th["s7_dropped_keys_share"] * m.rows.length && xr.length >= 1) {
    issues.push(`${rnd(100 * xr.length / m.rows.length)}% of the visits dropped keys at the size cap`);
  }
  for (const w of ctx.calendar_warnings || []) {
    issues.push(w);
  }
  out["data_issues"] = issues;
  if (issues.length) {
    led("S7", name, "flagged", issues.join("; "));
    SIG("S7", name, "The data itself needs a check", issues.join("; ") + ".", "Facts about the export, not a comparison with earlier weeks.", "Any item listed.", "Confirmed",
        "Whether usage changed: these items concern how complete and how current the export is.", "Worth investigating: take a fresh export, then run the report again.");
  } else {
    led("S7", name, "within", facts.concat(["no duplicated, skipped or unknown records"]).join("; "));
  }
}
