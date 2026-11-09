// render_b.js: usage_report.py lines 2619-3160 (the read and use blocks, devices, when people visit, come back, recording health, how it is measured, the page).
// `a` is the aggregate as plain JSON plus `a.model` (the Model). Private helpers of this file start with `_rb_`.

// ---- small Python-semantics helpers private to this file
function _rb_t(x) {                                  // Python truthiness
    if (x === null || x === undefined || x === false || x === 0 || x === "") return false;
    if (typeof x === "number" && Number.isNaN(x)) return false;
    if (Array.isArray(x)) return x.length > 0;
    if (x instanceof Map || x instanceof Set) return x.size > 0;
    if (typeof x === "object") return Object.keys(x).length > 0;
    return true;
}
function _rb_has(c, k) {                             // `k in c` for a Set, Map, array or plain object
    if (c instanceof Set || c instanceof Map) return c.has(k);
    if (Array.isArray(c)) return c.includes(k);
    return Object.prototype.hasOwnProperty.call(c, k);
}
function _rb_get(c, k) {                             // `c[k]` for a Map or a plain object
    return c instanceof Map ? c.get(k) : c[k];
}
function _rb_fnum(v) {                               // num(v) for a value that Python made with round(x, 1): a float, so an integral value prints as '3.0' (JSON and JS numbers cannot tell 3.0 from 3)
    return typeof v === "number" ? e(pystr(v, true)) : num(v);
}
function _rb_numsort(xs) {
    return xs.slice().sort((x, y) => x - y);
}
function _rb_sum(xs) {
    let s = 0;
    for (const x of xs) s += x;
    return s;
}

// ------------------------------------------------------------------------------------------------------------ the breakdowns
function _read_block(a) {
    const th = a.model.th;
    const s = a.sections;
    if (!_rb_t(s.n)) {
        return ['<div class="panel"><h3>Section reach</h3><p class="empty-note">Too early: no completed week yet.</p></div>', ""];
    }
    const N = s.d;
    const rows = [];
    for (const r of s.rows) {
        const guard = r.under5;
        rows.push({label: r.name, guard: guard, text: !guard ? share_text(r.reach, N, th) : SMALL, frac: ((N !== SMALL && _rb_t(N)) ? r.raw / N : 0), tag: r.candidate});
    }
    let chart, summ, body;
    if (N === SMALL) {
        chart = `<p class="empty-note">Fewer than ${MIN_USERS} people were active: reach is not shown.</p>`;
        summ = "";
        body = chart;
    } else {
        [chart, summ] = hbars(rows);
        body = chart_img(chart, `Section reach, share of the ${pystr(N)} people active in the window: ${summ}.`, "");
    }
    const body_rows = [];
    for (const r of s.rows) {
        const nm = e(r.name) + (r.under5 ? ` (reach under ${MIN_USERS} people: Unknown)` : "");
        const cand = r.candidate ? ` <span class="tag">${e(r.candidate)}</span>` : "";
        body_rows.push(`<tr><th scope="row">${nm}${cand}</th><td class="n">${sh(r.reach, N, th)}</td><td class="n">${r.nav !== null ? num(r.nav) : "-"}</td><td class="n">${num(r.links)}</td><td class="n">${r.share !== null ? num(r.share, "%") : "-"}</td></tr>`);
    }
    const ol = Object.entries(s.disclosures).map(([k, v]) => `${DISCLOSURES[k]}: ${num(v)}`).join(", ");
    const table = ('<table id="reach"><thead><tr><th scope="col">Section</th><th scope="col" class="n">Reach</th><th scope="col" class="n">Section Strip</th><th scope="col" class="n">Jira links</th><th scope="col" class="n">Reading time</th></tr></thead>'
        + `<tbody>${body_rows.join("")}</tbody></table>`
        + `<p class="cap2">Reach: people with 30 seconds or more in the section in a week, of the ${num(s.n_g)} people active in ${_weeks_phrase(a.model, s.weeks)}. Section Strip and Jira links: people using the strip or the skip links to jump to the section, or following a Jira link from it (a person is counted once). `
        + `Reading time: each person's own split, averaged over the sections shown; scroll position decides which section gets the time. ${e(guard_note("A section with fewer than {n} readers shows {g} and is left out of that share."))} Simplify candidates: ${e(s.candidates.status)}. Details opened (people): ${ol}.</p>`);
    const cap = `Share of the ${num(s.n_g)} people active in ${a.window.label} with 30 seconds or more in the section. Page order, not ranked.`;
    return [panel("Section reach", cap, body, show_data(table), "p-sections"), ""];
}


function _controls_block(a) {
    const th = a.model.th;
    const c = a.controls;
    if (!_rb_t(c.n)) {
        return '<div class="panel"><h3>Control reach</h3><p class="empty-note">Too early: no completed week yet.</p></div>';
    }
    const N = c.d;
    const rows = [];
    for (const f of c.families) {
        rows.push({group: f.family});
        for (const r of f.rows) {
            const guard = r.reach === SMALL;
            rows.push({label: r.name, guard: guard, text: !guard ? share_text(r.reach, N, th) : SMALL, frac: ((N !== SMALL && _rb_t(N)) ? r.raw / N : 0)});
        }
    }
    let body;
    if (N === SMALL) {
        body = `<p class="empty-note">Fewer than ${MIN_USERS} people were active: reach is not shown.</p>`;
    } else {
        const [chart, summ] = hbars(rows);
        body = chart_img(chart, `Control reach, share of the ${pystr(N)} people active in the window that changed the control, by family: ${summ}.`);
    }
    const body_rows = [];
    for (const f of c.families) {
        body_rows.push(`<tr class="fam"><th scope="colgroup" colspan="2">${e(f.family)}</th></tr>`);
        for (const r of f.rows) {
            body_rows.push(`<tr><th scope="row">${e(r.name)}</th><td class="n">${sh(r.reach, N, th)}</td></tr>`);
        }
    }
    const rs = c.reset;
    const reset = (rs.state === "none" ? "Not recorded in v1 records." : `${sh(rs.x, rs.visits_g, th)} of visits with a control change also pressed Reset Filters in the same visit (${nlabel(rs.visits_g)}).` + (_rb_t(rs.flag) ? " Flag: 25% or more in 2 consecutive weeks." : ""));
    const [mv, pj] = c.multi_vs_projects;
    const table = (`<table id="controls"><thead><tr><th scope="col">Control</th><th scope="col" class="n">Reach</th></tr></thead><tbody>${body_rows.join("")}</tbody></table>`
        + `<p class="cap2">Reach of each control among the ${num(c.n_g)} people active in ${_weeks_phrase(a.model, c.weeks)}: people that changed it at least once. Any control: ${sh(c.any.x, N, th)}. Multi-select toggle: ${num(mv)} people; Projects: ${num(pj)} people. ${e(reset)}</p>`);
    const cap = `Share of the ${num(c.n_g)} people active in ${a.window.label} that changed the control at least once. Fixed page order, not ranked.`;
    return panel("Control reach", cap, body, show_data(table), "p-controls");
}


function _actions_block(a) {
    /* What people do with the page: four shares, each with its own base named in the row (people, or visits). */
    const th = a.model.th;
    const c = a.controls, u = a.use;
    if (!_rb_t(c.n)) return "";
    const lk = u.links, rf = u.refresh, rs = c.reset;

    function row(label, x, den, pct_txt = null) {
        // x: a count or SMALL; den: the number it is out of (an int).
        if (x === SMALL) return {label: label, guard: true, text: SMALL, frac: 0};
        const txt = _rb_t(den) ? share_text(x, den, th) : "-";
        return {label: label, guard: false, text: txt, frac: (_rb_t(den) ? x / den : 0), alt: false};
    }
    const rows = [row("Changed any control (people)", c.any.x, c.d !== SMALL ? c.d : 0),
        row("Pressed Refresh (people)", rf.x, rf.n),
        row("Visits with a Jira link click (engaged visits)", lk.x !== SMALL ? lk.visits : SMALL, lk.of),
        row("Reset Filters after a control change (visits with a change)", (rs.state === "none" ? "-" : rs.x), (rs.state !== "none" ? rs.visits : 0))];
    if (rs.state === "none") {
        rows[3] = {label: "Reset Filters after a control change (visits with a change)", guard: false, text: "not recorded", frac: 0};
    } else if (rs.x !== SMALL && rs.visits_g === SMALL) {
        rows[3] = {label: rows[3].label, guard: true, text: SMALL, frac: 0};
    }
    const [chart, summ] = hbars(rows);
    const body = chart_img(chart, `What people do: ${summ}.`);
    // the table behind it keeps every number of the use block
    const mn = u.minutes;
    const fr = u.fresh;

    function fresh_line(k) {
        const f = fr[k];
        if (!_rb_t(f)) return "not recorded in v1 records";
        const txt = Object.entries(f.cells).map(([nm, cell]) => `${nm}: ` + (cell === SMALL ? SMALL : (f.shares[nm] !== null ? `${pystr(f.shares[nm])}%` : pystr(cell)))).join(", ");
        return txt + (_rb_t(f.hidden) ? ` (share of the ${fmt_n(f.n_g)} visits shown; rows under ${MIN_USERS} people are left out)` : ` (${nlabel(f.n_g)} visits)`);
    }
    const ro = rf.outcomes;
    const refresh_out = rf.has_v2 ? ("Outcomes: " + Object.entries(ro).map(([k, v]) => `${RO[k]} ${cnt(v.people, "people")}`).join("; ") + `; automatic retries ${fmt_n(rf.retries)}`) : "Outcomes are not recorded in v1 records";
    const link_secs = lk.sections.filter(s => s.pct !== null).map(s => `${s.name}: ${pystr(s.pct)}% of engaged visits, ${s.status}`).join("; ") || `no section has ${pystr(th.link_min_clicks)} clicks from ${pystr(th.link_min_people)} people yet`;
    const trs_rows = [
        ["Median active minutes among engaged visits (30 s or more, or with input)", (mn.median !== null && mn.median !== SMALL) ? (_rb_fnum(mn.median) + " min") : (mn.median === SMALL ? num(mn.median) : "-"), `over ${num(mn.visits)} engaged visits with some active time (${num(mn.people)} people). Glance visits are reported under Recording health`],
        ["Engaged visits per active person", _rb_fnum(u.per_person.value), `in ${pystr(u.weeks)} weeks, of ${num(u.per_person.n)} active people: a count of visits, not a measure of value`],
        ["Visits with a Jira link click", lk.x !== SMALL ? (lk.pct !== null ? `${pystr(lk.pct)}%` : num(lk.visits)) : e(SMALL), `of ${fmt_n(u.engaged_g)} engaged visits had a Jira link click, by ${num(lk.x)} people. By section: ${e(link_secs)}`],
        ["Small-screen share", sh(u.phone.x, u.phone.n_g, th), `of ${fmt_n(u.phone.n_g)} engaged visits with a width recorded`],
        ["Refresh pressed by", sh(rf.x, rf.n_g, th), `of ${fmt_n(rf.n_g)} active people. ${e(refresh_out)}`],
        ["Connection at the visit", "-", e(fresh_line("lv"))],
        ["Age of the data at the start", "-", e(fresh_line("fa"))],
    ];
    const trs = trs_rows.map(([n, v, d]) => `<tr><th scope="row">${e(n)}<div class="cap2">${d}</div></th><td class="n">${v}</td></tr>`).join("");
    const table = (`<table id="usage" class="two"><thead><tr><th scope="col">Measure and basis</th><th scope="col" class="n">Result</th></tr></thead><tbody>${trs}</tbody></table>`
        + '<p class="cap2">Engaged visits = 30 seconds or more, or with input. A control or link count is a count of people, not of effect. Do not use these figures to compare teams.</p>');
    const cap = `Share of people or of visits, as named on each row; ${a.window.label}.`;
    return panel("What people do", cap, body, show_data(table), "p-actions");
}


function device_split(a) {
    /* Engaged visits of the window by width class (the page records small, medium or large), as a partition protected like every other partition of the report. */
    const m = a.model;
    const rows = _window_rows(m, window_weeks(m)).filter(r => !r.glance && _rb_has(DEVICES, r.s.d));
    const groups = {};
    for (const k of Object.keys(DEVICES)) {
        const us = new Set(rows.filter(r => r.s.d === k).map(r => r.u));
        groups[k] = [us, rows.filter(r => r.s.d === k).length];
    }
    let cells;
    if (rows.length) {
        cells = partition_cells(groups);
    } else {
        cells = {};
        for (const k of Object.keys(DEVICES)) cells[k] = 0;
    }
    return {cells: cells, n: rows.length, people: new Set(rows.map(r => r.u)).size};
}


function version_split(m) {
    /* S6 as a chart: the people of the last completed week by the newest build day they used: on the newest version (or under 7 days older) or more than 7 days older. Needs 20 people with a recorded build day.
       The same partition protection as S6: when the older group is under 5 people nothing about the newer group is drawn. */
    const th = m.th;
    let L = m.last;
    if (!m.usable(L) && th.show_partial_week && _rb_has(m.by_week, m.cur)) {
        L = m.cur;                                                                // no completed week to read: the week in progress, to date
    } else if (!m.usable(L)) {
        return {state: "none"};
    }
    const rows_bt = m.visits(L).filter(x => is_num(x.s.bt));
    const all_bt = m.rows.filter(x => is_num(x.s.bt)).map(x => x.s.bt);
    if (!rows_bt.length) return {state: "v1"};
    const latest = new Map();
    for (const x of rows_bt) {
        latest.set(x.u, Math.max(latest.has(x.u) ? latest.get(x.u) : x.s.bt, x.s.bt));
    }
    const n6 = latest.size;
    if (n6 < th.min_den) return {state: "few", n: n6};
    const newest = Math.max(...all_bt);
    let stale = 0;
    for (const v of latest.values()) if (newest - v > th.s6_age_days) stale += 1;
    const pc = protect_partition({old: stale, new: n6 - stale}, n6);
    return {state: "ok", n: n6, cells: pc, days: th.s6_age_days, partial: L === m.cur};
}


function _stack_panel_parts(a) {
    /* (html of the three stacked bars, the tables behind them). */
    const m = a.model, th = a.model.th;
    const parts = [], tables = [];

    function add(title, bar, summ, note, table_rows) {
        parts.push(`<div class="sub"><p class="st">${e(title)}</p>${chart_img(bar, `${title}: ${summ}`)}<p class="cap2">${e(note)}</p></div>`);
        tables.push(`<table><caption class="cap2">${e(title)}</caption><thead><tr><th scope="col">Group</th><th scope="col" class="n">Share</th></tr></thead><tbody>${table_rows}</tbody></table>`);
    }
    function rows_of(cells, names, summ_drawn) {
        return Object.entries(cells).map(([k, v]) => `<tr><th scope="row">${e(names[k])}</th><td class="n">${v === SMALL ? e(SMALL) : num(v)}</td></tr>`).join("");
    }
    const ds = device_split(a);
    if (_rb_t(ds.n)) {
        const [bar, summ] = stack_bar(ds.cells, DEVICES, th);
        add("Screen size, engaged visits", bar, summ, stack_note(ds.cells, th) + ` (${a.window.label}).`, rows_of(ds.cells, DEVICES, null));
    }
    const vs = version_split(m);
    if (vs.state === "ok") {
        const names = {new: `On the newest page version, or under ${pystr(vs.days)} days older`, old: `More than ${pystr(vs.days)} days older`};
        const cells = vs.cells;
        const [bar, summ] = stack_bar(cells, names, th, "people");
        add("Page version, people active in the " + (_rb_t(vs.partial) ? "week so far" : "last completed week"), bar, summ, (Object.values(cells).includes(SMALL) ? stack_note(cells, th, "people") : `n=${vs.n} people with a recorded build day.`), rows_of(cells, names, null));
    } else if (vs.state === "v1" || vs.state === "few") {
        const why = vs.state === "v1" ? "not recorded in v1 records" : `too few people (n=${vs.n}, needs ${pystr(th.min_den)})`;
        add("Page version, people active in the " + (_rb_t(vs.partial) ? "week so far" : "last completed week"), '<div class="sb" aria-hidden="true"><span class="stubfull"><b>Not shown</b></span></div>', "not shown: " + why, "Not shown: " + why + ".", `<tr><td colspan="2">${e(why)}</td></tr>`);
    }
    const fr = a.use.fresh;
    for (const [key, title] of [["lv", "Connection at the start of a visit"], ["fa", "Age of the data at the start of a visit"]]) {
        const f = fr[key];
        if (!_rb_t(f)) {
            add(title, '<div class="sb" aria-hidden="true"><span class="stubfull"><b>Not recorded</b></span></div>', "not recorded in v1 records", "Not recorded in v1 records.", '<tr><td colspan="2">not recorded in v1 records</td></tr>');
            continue;
        }
        const names = {};
        for (const nm of Object.keys(f.cells)) names[nm] = nm[0].toUpperCase() + nm.slice(1);
        const [bar, summ] = stack_bar(f.cells, names, th);
        add(title, bar, summ, stack_note(f.cells, th), rows_of(f.cells, names, null));
    }
    return [`<div class="sbgrid">${parts.join("")}</div>`, tables.join("")];
}


function _devices_block(a) {
    const [body, tables] = _stack_panel_parts(a);
    return panel("Where and how the page is opened", "Engaged visits by screen size and the freshness of the data; the page version of the people active in the last completed week.", body, show_data(tables), "p-devices");
}


function _breakdowns(a) {
    const [sec] = _read_block(a);
    const left = `<div class="stk">${sec}${_actions_block(a)}</div>`;
    return (`<section class="blk" id="breakdowns" aria-labelledby="h-break"><h2 id="h-break">What people read and use</h2><div class="row2e">${left}${_controls_block(a)}</div>`
        + `<div class="sub">${_devices_block(a)}</div></section>`);
}


// ------------------------------------------------------------------------------------------------------------ day and hour
function hour_grid(m) {
    /* Engaged visits by weekday (Israel day of the visit) and hour of the day (Israel time, from the opening time the v2 page records in hours) over the completed weeks. A cell counts its visits and its distinct people; a cell of 1 to 4 people is
       withheld (hatched, no number). No total is printed next to the cells, so no cell can be reconstructed by subtraction. A visit whose opening time does not fall on its own day is not used (counted). */
    const done = new Set(m.weeks);
    if (m.th.show_partial_week) done.add(m.cur);
    const cells = new Map();                                                       // key "weekday,hour" (0 = Sunday) -> [visits, Set of people]
    let used = 0, skipped = 0;
    for (const r of m.rows) {
        if (r.glance || !r.v2 || !done.has(r.ws) || !is_num(r.s.t)) continue;
        let il = null;
        try {
            const ms = r.s.t * 3600 * 1000;
            const d = new Date(ms);
            if (Number.isFinite(ms) && !Number.isNaN(d.getTime())) {
                const y = d.getUTCFullYear();
                if (y >= 1 && y <= 9999) {
                    const p = dt_il_parts(d.toISOString());
                    il = {date: `${String(p.year).padStart(4, "0")}-${String(p.month).padStart(2, "0")}-${String(p.day).padStart(2, "0")}`, hour: p.hour};
                }
            }
        } catch (err) {
            il = null;
        }
        if (il === null) {
            skipped += 1;
            continue;
        }
        if (il.date !== r.day) {
            skipped += 1;
            continue;
        }
        const k = ((d_weekday(r.day) + 1) % 7) + "," + il.hour;                    // 0 = Sunday
        if (!cells.has(k)) cells.set(k, [0, new Set()]);
        const cell = cells.get(k);
        cell[0] += 1;
        cell[1].add(r.u);
        used += 1;
    }
    const allp = new Set();
    for (const c of cells.values()) for (const u of c[1]) allp.add(u);
    if (used < m.th.heatmap_min_visits || used < 1 || allp.size < MIN_USERS) {
        return {state: "few", used: used};
    }
    const out = new Map();
    for (const [k, v] of cells) {
        out.set(k, v[0] === 0 ? {state: "none"} : v[1].size < MIN_USERS ? {state: "small"} : {state: "ok", visits: v[0], people: v[1].size});
    }
    const hours = _rb_numsort([...new Set([...out.keys()].map(k => Number(k.split(",")[1])))]);
    const lo = Math.min(...hours), hi = Math.max(...hours);
    const vals = _rb_numsort([...out.values()].filter(c => c.state === "ok").map(c => c.visits));
    const hrs = [];
    for (let h = lo; h <= hi; h++) hrs.push(h);
    return {state: "ok", cells: out, hours: hrs, vals: vals, used: used, skipped: skipped};
}


function _bucket(v, vals) {
    /* 1..HM_BUCKETS: the rank of a cell among the printed cells (quantile buckets), so one busy hour does not turn every other cell to the palest tint. */
    if (vals.length < 2) return HM_BUCKETS;
    const rank = vals.filter(x => x <= v).length / vals.length;
    return Math.max(1, Math.min(HM_BUCKETS, Math.ceil(rank * HM_BUCKETS)));
}


function _heatmap_block(a) {
    const m = a.model;
    const hg = hour_grid(m);
    const head = '<section class="blk" id="when" aria-labelledby="h-when"><h2 id="h-when">When people visit</h2>';
    const title = "Engaged visits by weekday and hour";
    if (!m.rows.some(r => r.v2)) {
        return head + panel(title, "Israel time.", '<p class="empty-note">Not recorded in v1 records: the earlier page did not record the hour of a visit.</p>') + "</section>";
    }
    if (hg.state !== "ok") {
        return head + panel(title, "Israel time.", `<p class="empty-note">Too early: needs ${Math.max(1, Math.trunc(m.th.heatmap_min_visits))} engaged visit${m.th.heatmap_min_visits <= 1 ? "" : "s"} with a recorded time${MIN_USERS <= 1 ? "" : `, and ${MIN_USERS} people`}.</p>`) + "</section>";
    }
    const days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
    const hours = hg.hours;
    const cells_html = [], summ = [], trs = [];
    for (let d = 0; d < 7; d++) {
        cells_html.push(`<span class="d">${days[d]}</span>`);
        const cs = [];
        for (const h of hours) {
            const c = hg.cells.get(d + "," + h) || {state: "none"};
            const name = `${days[d]} ${String(h).padStart(2, "0")}:00`;
            if (c.state === "ok") {
                const b = _bucket(c.visits, hg.vals);
                cells_html.push(`<i class="c v${b}" title="${e(name)}: ${c.visits} visits"></i>`);
                cs.push(`<td class="n">${c.visits}</td>`);
                summ.push(`${name} ${c.visits}`);
            } else if (c.state === "small") {
                cells_html.push(`<i class="c h" title="${e(name)}: ${e(SMALL)}"></i>`);
                cs.push(`<td class="n">${e(SMALL)}</td>`);
                summ.push(`${name} ${SMALL}`);
            } else {
                cells_html.push(`<i class="c" title="${e(name)}: none"></i>`);
                cs.push('<td class="n">0</td>');
            }
        }
        trs.push(`<tr><th scope="row">${days[d]}</th>${cs.join("")}</tr>`);
    }
    const xh = '<span class="x"></span>' + hours.map(h => `<span class="x">${h}</span>`).join("");
    const busy = Math.max(...hg.vals);
    const inner = `<div class="hm" style="--cols:${hours.length}" aria-hidden="true">${xh}${cells_html.join("")}</div>`;
    const ramp_i = [];
    for (let b = 1; b <= HM_BUCKETS; b++) ramp_i.push(`<i class="v${b}"></i>`);
    const ramp = ('<div class="ramp" aria-hidden="true"><span>Fewer visits</span>' + ramp_i.join("") + `<span>more (up to ${busy} in one hour)</span>`
        + '<span class="sep"></span>' + (MIN_USERS > 1 ? '<i class="h"></i><span>' + e(SMALL) + '</span>' : '') + '<i></i><span>none</span></div>');
    const label = `Engaged visits by weekday and hour of the day, Israel time, all completed weeks. Cells with fewer than ${MIN_USERS} people are withheld. ` + summ.slice(0, 400).join("; ") + ".";
    const table = ('<table id="hours"><thead><tr><th scope="col">Weekday</th>' + hours.map(h => `<th scope="col" class="n">${h}:00</th>`).join("") + `</tr></thead><tbody>${trs.join("")}</tbody></table>`
        + `<p class="cap2">Engaged visits per weekday and hour (Israel time) over the completed weeks; ${hours.length} hours from the first to the last hour with a visit. ${e(guard_note("A cell of fewer than {n} people shows {g}. No total is shown: it would reveal a withheld cell."))}`
        + (_rb_t(hg.skipped) ? ` ${hg.skipped} visit(s) with an opening time outside their own day were left out.` : "") + "</p>");
    const cap = "Engaged visits per weekday (rows) and hour of the day (columns, Israel time), all completed weeks. Darker = more visits.";
    return head + panel(title, cap, chart_img(inner, label) + ramp, show_data(table), "p-hours") + "</section>";
}


// ------------------------------------------------------------------------------------------------------------ do people come back
function cohort_grid(m) {
    /* Cohort retention: rows = the week people were first seen (a Sunday-start week), columns = weeks since, a cell = the people of the cohort that were active that week. Only people with a known first day (not before the go-live day,
       not before the 12 weeks kept) are in a cohort, and only completed weeks are columns. A cohort of fewer than 5 people is withheld; a cell is protected as the partition 'returned / not returned' of its cohort, like the week-1 and week-4 figures;
       a percentage is printed from a cohort of 20 people, below that the count. */
    const th = m.th;
    const by_week = new Map();
    for (const u of m.people) {
        if (_rb_has(m.pre_golive, u) || _rb_get(m.first_real, u) < m.cutoff) continue;
        const ws = week_start(_rb_get(m.first_real, u));
        if (!by_week.has(ws)) by_week.set(ws, []);
        by_week.get(ws).push(u);
    }
    const rows = [];
    for (const ws of [...by_week.keys()].sort()) {
        const k_max = Math.floor(d_diff(m.last, ws) / 7);
        if (k_max < 1) continue;
        const people = by_week.get(ws);
        const n = people.length;
        const row = {ws: ws, n: n, n_g: gn(n), cells: []};
        for (let k = 1; k <= k_max; k++) {
            if (n < MIN_USERS) {
                row.cells.push({k: k, state: "small"});
                continue;
            }
            const w = d_add(ws, 7 * k);
            const act = m.active(w);
            const x = people.filter(u => _rb_has(act, u)).length;
            const pc = protect_partition({ret: x, not: n - x}, n);
            if (pc.ret === SMALL) {
                row.cells.push({k: k, state: "small"});
            } else if (n >= th.min_den) {
                row.cells.push({k: k, state: "pct", x: x, pct: rnd(100 * x / n)});
            } else {
                row.cells.push({k: k, state: "count", x: x});
            }
        }
        rows.push(row);
    }
    const eligible = rows.filter(r => r.n >= MIN_USERS);
    return {rows: rows, eligible: eligible.length, kmax: rows.length ? Math.max(...rows.map(r => r.cells.length)) : 0};
}


function _cohort_block(a) {
    const m = a.model;
    const th = m.th;
    const cg = cohort_grid(m);
    const r_ = a.retention;
    let body, table, summ;
    if (!cg.eligible) {
        body = `<p class="empty-note">Too early: needs a first-seen week with ${MIN_USERS > 1 ? MIN_USERS : 1} ${MIN_USERS > 1 ? "or more people" : "person"} and one completed week after it.</p>`;
        table = "";
        summ = "";
    } else {
        const kmax = cg.kmax;
        const ks = [];
        for (let k = 1; k <= kmax; k++) ks.push(k);
        const head = '<span class="x"></span>' + ks.map(k => `<span class="x">+${k}</span>`).join("");
        const cells = [], trs = [], summ_l = [];
        for (const r of cg.rows) {
            const small_row = r.n < MIN_USERS;
            const lbl = `${d_label(r.ws)}, ` + (small_row ? e(SMALL) : `n=${r.n}`);
            cells.push(`<span class="rl">${lbl}</span>`);
            const tds = [];
            r.cells.forEach((c, ci) => {
                const nm = `${week_label(r.ws)} cohort, week +${c.k}`;
                if (c.state === "small") {
                    if (small_row) {                                                // a cohort under 5 people: one hatched bar for the whole row
                        if (ci === 0) {
                            cells.push(`<i class="cc h" style="grid-column:span ${r.cells.length}" title="${e(week_label(r.ws))} cohort: ${e(SMALL)}"></i>`);
                        }
                    } else {
                        cells.push(`<i class="cc h" title="${e(nm)}: ${e(SMALL)}"></i>`);
                    }
                    tds.push(`<td class="n">${e(SMALL)}</td>`);
                    summ_l.push(`${nm} ${SMALL}`);
                } else if (c.state === "pct") {
                    const b = _bucket_pct(c.pct);
                    cells.push(`<i class="cc v${b}${b >= 5 ? " dk" : ""}" title="${e(nm)}: ${c.pct}%">${c.pct}%</i>`);
                    tds.push(`<td class="n">${c.pct}%</td>`);
                    summ_l.push(`${nm} ${c.pct}%`);
                } else {
                    cells.push(`<i class="cc n" title="${e(nm)}: ${c.x} of ${r.n}">${c.x}</i>`);
                    tds.push(`<td class="n">${c.x} of ${r.n}</td>`);
                    summ_l.push(`${nm} ${c.x} of ${r.n}`);
                }
            });
            for (let i = 0; i < kmax - r.cells.length; i++) {
                cells.push('<i></i>');
            }
            trs.push(`<tr><th scope="row">${e(week_label(r.ws))}</th><td class="n">${small_row ? e(SMALL) : r.n}</td>${tds.join("")}</tr>`);
        }
        const grid = `<div class="ch" style="--cols:${kmax}" aria-hidden="true">${head}${cells.join("")}</div>`;
        const ramp_i = [];
        for (let b = 1; b < 6; b++) ramp_i.push(`<i class="v${b}"></i>`);
        const ramp = ('<div class="ramp" aria-hidden="true"><span>0%</span>' + ramp_i.join("") + '<span>100% back</span><span class="sep"></span><i class="cc n"></i><span>count (cohort under 20)</span>' + (MIN_USERS > 1 ? '<i class="h"></i><span>' + e(SMALL) + '</span>' : '') + '</div>');
        const label = "Cohort retention: for each week people were first seen, the people active again N weeks later. " + summ_l.slice(0, 300).join("; ") + ".";
        body = chart_img(grid, label) + ramp;
        table = ('<table id="cohorts"><thead><tr><th scope="col">First seen in the week of</th><th scope="col" class="n">People</th>' + ks.map(k => `<th scope="col" class="n">+${k} wk</th>`).join("")
            + `</tr></thead><tbody>${trs.join("")}</tbody></table><p class="cap2">Rows are the people first seen in a Sunday-to-Saturday week; people first seen before the go-live day or before the 12 weeks kept are not in a cohort. A cell is the people active again that many weeks later; `
            + `a percentage needs a cohort of 20 people, a smaller cohort prints counts, ${e(guard_note("a cohort or a cell of fewer than {n} people prints {g}."))} Use it to see whether newcomers stay; never to judge a person or a team.</p>`);
    }
    const cap = "People active again N weeks after the week they were first seen (completed weeks only).";
    return panel("Do newcomers come back?", cap, body, table ? show_data(table) : "", "p-cohorts");
}


function _bucket_pct(p) {
    return p < 20 ? 1 : p < 40 ? 2 : p < 60 ? 3 : p < 80 ? 4 : 5;
}


function _return_habit_block(a) {
    const th = a.model.th;
    const h = a.habit, r = a.retention;
    const rows = [];
    for (const [key, label] of [["w1", "Back within a week of the first visit"], ["w4", "Back in week 4 after the first visit"]]) {
        const x = r[key];
        if (!_rb_t(x.raw_n)) {
            rows.push({label: label + " (no eligible people yet)", guard: false, text: "none yet", frac: 0});
        } else if (x.x === SMALL) {
            rows.push({label: `${label} (eligible: ${fmt_n(x.n)})`, guard: true, text: SMALL, frac: 0});
        } else {
            rows.push({label: `${label} (eligible: ${pystr(x.raw_n)})`, guard: false, text: share_text(x.x, x.raw_n, th), frac: x.x / x.raw_n});
        }
    }
    let hab_t = "";
    if (h.state !== "ok") {
        hab_t = `<p class="empty-note" id="habit">Habit: ${e(h.text)}</p>`;
    } else {
        const nprint = h.n_print;
        if (nprint === SMALL || h.x === SMALL) {
            rows.push({label: `Active in ${pystr(h.min_weeks)} or more of the last ${pystr(h.weeks)} weeks`, guard: true, text: SMALL, frac: 0});
        } else {
            rows.push({label: `Active in ${pystr(h.min_weeks)} or more of the last ${pystr(h.weeks)} weeks (established: ${pystr(nprint)})`, guard: false, text: share_text(h.x, h.n, th), frac: h.x / h.n});
        }
    }
    const [chart, summ] = hbars(rows);
    const body = chart_img(chart, `Return and habit: ${summ}.`);
    // the histogram of weeks active
    let hist = "";
    let data = "";
    if (h.state === "ok" && h.n_print !== SMALL && _rb_t(h.bins)) {
        const bins = h.bins;
        const mx = Math.max(...bins.map(b => b[2])) || 1;
        const lab = (lo, hi) => lo === hi ? `${lo} week${lo !== 1 ? "s" : ""}` : `${lo} to ${hi} weeks`;
        const hrows = bins.map(([lo, hi, c]) => ({label: lab(lo, hi), guard: false, text: String(c), frac: c / mx, alt: true}));
        const [hchart, hsumm] = hbars(hrows, undefined, ["0", "", `${mx} people`]);
        const hlabel = `Weeks active out of the last ${h.weeks} among ${pystr(h.n_print)} established people: ${hsumm}.`;
        hist = `<div class="sub"><p class="st">Weeks active out of the last ${pystr(h.weeks)}, established people</p>${chart_img(hchart, hlabel)}<p class="cap2">${e(guard_note("Neighbouring groups are merged until each has at least {n} people.") || "Every group is shown as it is.")}</p></div>`;
        const brow = bins.map(([lo, hi, c]) => `<tr><th scope="row">${e(lab(lo, hi))}</th><td class="n">${num(c)}</td></tr>`).join("");
        data = `<table id="habit-table"><thead><tr><th scope="col">Weeks active</th><th scope="col" class="n">People</th></tr></thead><tbody>${brow}</tbody></table>`;
    }
    const rrows = [];
    for (const [key, label, when] of [["w1", "Week 1", "a visit on a later day within 7 days of the first visit"], ["w4", "Week 4", "a visit in days 22 to 28 after the first visit"]]) {
        const x = r[key];
        const res = !_rb_t(x.raw_n) ? "no eligible people yet" : sh(x.x, x.raw_n, th) + (_rb_t(x.indicative) ? " (indicative)" : "");
        rrows.push(`<tr><th scope="row">${label}: ${e(when)}</th><td class="n">${num(x.n)}</td><td class="n">${res}</td></tr>`);
    }
    const table = (`<table id="retention"><thead><tr><th scope="col">Retention</th><th scope="col" class="n">Eligible people</th><th scope="col" class="n">Came back</th></tr></thead><tbody>${rrows.join("")}</tbody></table>`
        + (h.state === "ok" ? `<p class="cap2" id="habit">Habit: ${(h.n_print !== SMALL && h.x !== SMALL) ? sh(h.x, h.n, th) : e(SMALL)} of ${num(h.n_print)} established people were active in ${pystr(h.min_weeks)} or more of the last ${pystr(h.weeks)} completed weeks (${e(h.window)}). Established = first seen at least 14 days before the compared week.</p>` : "")
        + data + '<p class="cap2">Retention follows people first seen at least 7 (or 28) days ago; people that arrived later are not in the figure yet. Indicative under 30 people.</p>');
    return panel("Return and habit", "Share of eligible people that came back, and of established people active in 4 or more of the last 8 weeks.", body + hist + hab_t, show_data(table), "p-habit");
}


function _back_block(a) {
    return (`<section class="blk" id="back" aria-labelledby="h-back"><h2 id="h-back">Do people come back?</h2><div class="row2">${_cohort_block(a)}${_return_habit_block(a)}</div></section>`);
}


// ------------------------------------------------------------------------------------------------------------ recording health
function _health_block(a) {
    const th = a.model.th;
    const m = a.model;
    const h = a.health;
    const rows = [["Visits in the data", `${fmt_n(h.visits_g)}`, `${fmt_n(h.v2_g)} from the newer page, ${num(h.v1_visits)} from the earlier page (${num(h.v1_people)} people)`]];
    const bars = [];
    let stacks = "";
    if (h.has_v2) {
        const gl = h.glance;
        rows.push(["Glance visits", sh(gl.x, gl.n_g, th), `of ${fmt_n(gl.n_g)} visits; engaged visits ${num(gl.engaged)}. A glance is 5 seconds or more with no input and under 30 seconds. Engaged = 30 seconds or more, or with input.`],
            ["Visible, no active seconds", sh(h.focus.x, h.focus.n_g, th), "visits with visible time but no active seconds: a high share points at a focus problem in the page frame, not at idle readers"],
            ["Real page errors", sh(h.errors_real.x, h.errors_real.n_g, th), "of visits (v2 pages)"],
            ["Benign notifications", sh(h.errors_benign.x, h.errors_benign.n_g, th), "counted apart and never flagged"]);
        const cells = {glance: gl.x, engaged: gl.engaged};
        const [sbar, ssum] = stack_bar(cells, {glance: "Glance visits", engaged: "Engaged visits"}, th);
        stacks = `<div class="sub"><p class="st">Glance and engaged visits (newer page)</p>${chart_img(sbar, "Glance and engaged visits: " + ssum)}<p class="cap2">${e(stack_note(cells, th))}</p></div>`;

        const share_row = (label, d) => {
            if (d.x === SMALL) return {label: label, guard: true, text: SMALL, frac: 0};
            return {label: label, guard: false, text: share_text(d.x, d.n, th), frac: _rb_t(d.n) ? d.x / d.n : 0};
        };
        bars.push(share_row("Real page errors (of visits)", h.errors_real), share_row("Benign notifications (of visits)", h.errors_benign), share_row("Visible but no active seconds (of visits)", h.focus), share_row("Visits that dropped keys (of visits)", h.dropped));
    } else {
        rows.push(["Glance visits, focus, benign errors", "-", "not recorded in v1 records: the data holds only the earlier page's visits, so adoption is probably under-counted"]);
        bars.push({label: "Visits that dropped keys (of visits)", guard: h.dropped.x === SMALL, text: h.dropped.x !== SMALL ? share_text(h.dropped.x, h.dropped.n, th) : SMALL, frac: (h.dropped.x !== SMALL && _rb_t(h.dropped.n)) ? h.dropped.x / h.dropped.n : 0});
    }
    if (h.attributed !== null) {
        bars.push({label: "Active time attributed to a section", guard: false, text: `${pystr(h.attributed)}%`, frac: h.attributed / 100, alt: true});
    }
    rows.push(["Visits that dropped keys", sh(h.dropped.x, h.dropped.n_g, th), "at the 40-key cap"],
        ["Active time attributed to a section", h.attributed !== null ? num(h.attributed, "%") : "-", "of active seconds"],
        ["Records not opened for over 12 weeks", num(h.stale_records), `their weeks are left out; delete them. ${pystr(h.stale_sessions)} sessions older than 12 weeks were ignored`],
        ["Records cut by the size cap", num(h.pruned_records), "older weeks dropped to keep a record small"]);
    const [chart, summ] = hbars(bars);
    const left = stacks || '<p class="empty-note">Glance and engaged visits: not recorded in v1 records.</p>';
    const body = `<div class="row2e"><div>${left}</div><div>${chart_img(chart, "Recording health: " + summ + ".")}</div></div>`;
    const trs = rows.map(([n, v, d]) => `<tr><th scope="row">${e(n)}<div class="cap2">${e(d)}</div></th><td class="n">${v}</td></tr>`).join("");
    const table = `<table id="health" class="two"><thead><tr><th scope="col">Check and reading</th><th scope="col" class="n">Result</th></tr></thead><tbody>${trs}</tbody></table>`;
    return ('<section class="blk" id="recording" aria-labelledby="h-health"><h2 id="h-health">Recording health</h2>'
        + panel("Can the measurement be trusted?", "How the page recorded visits, not how people use it; shares of visits unless named.", body, show_data(table), "p-health") + "</section>");
}


function _measure_block(a = null) {
    return ('<section class="blk" aria-labelledby="h-how"><h2 id="h-how">How this is measured</h2>'
        + `<ul class="gov" id="governance">${gov().map(x => `<li>${e(x)}</li>`).join("")}</ul>`
        + '<details class="vd" id="how"><summary>What is counted and what is not</summary>'
        + `<p class="cap">${e(coverage_not_counted())}</p>`
        + '<p class="cap">The published Delivery Pulse page counts, for each person with an id, which sections they read, which filters and buttons they use, which Jira links they follow (by section only), how long the page is open in front of them and in use, '
        + 'their screen size, the page version, how fresh the data was, the hour a visit opened and page errors. It records no names, e-mail addresses, issue keys, project, team or pod names or search text. People that are signed out or hold view-only access, that open an offline copy, '
        + 'or whose browser blocks the page&#39;s storage are not counted, so these are counts of people with an id, not of all visitors. A visit that is only looked at for 5 seconds or more is recorded as a glance; a visit with input or 30 seconds or more is an engaged visit. '
        + `Weeks run Sunday to Saturday and count as complete once Saturday has passed; the block under the weekly chart compares this week to date with the same weekdays of the week before. ${e(guard_note("Any figure that rests on fewer than {n} people shows {g}."))} Weeks before the first record show "before the data starts", not zero. `
        + 'This page is a snapshot of an export, not a live view.</p></details></section>');
}


// usage_report.py lines 1620-1632 fall between views.js (to 1488) and render_a.js (from 1740): ported here because ribbon_text and _measure_block need them.
function coverage_not_counted() {
    return ("Not counted: people signed out, with view-only access, using an offline copy or whose browser blocks storage. Includes the owner's and testers' visits. Aggregate counts only; " + small_rule() + " Never used to rank or assess people or teams.");
}


function fmt_date(d) {
    return `${d_label(d)} ${d.slice(0, 4)}`;                                      // f"{d.day} {d:%b %Y}"
}


function _who(a) {
    const n = a.n_people.n;
    return n === SMALL ? `fewer than ${MIN_USERS} people` : (n === 1 ? `${n} person` : `${n} people`);
}


function ribbon_text(a) {
    /* The coverage ribbon: two lines at most on a desktop. The longer list of what is not counted is under 'How this is measured'. It says the small-group setting in force. */
    const who = _who(a);
    const span = _rb_t(a.first_day) ? `, ${d_label(a.first_day)} to ${fmt_date(a.last_day)} (Israel time)` : "";
    const aud = _rb_t(a.audience) ? `, of an audience of ${pystr(a.audience.size)} (a lower bound)` : "";
    return (`Based on ${who} with an id${span}${aud}. Pseudonymous, not anonymous. Not counted: signed-out, view-only, offline-copy and storage-blocked visitors. `
        + small_rule(false, true) + " Never used to rank or assess people or teams.");
}


function _period(a) {
    const m = a.model;
    if (!_rb_t(m.weeks)) return "";
    return `Period: ${m.weeks.length} completed week${m.weeks.length !== 1 ? "s" : ""}, ${d_label(m.weeks[0])} to ${d_label(d_add(m.weeks[m.weeks.length - 1], 6))} (Sunday to Saturday), and the week in progress.`;
}


function html_report(a, standalone = false) {
    /* The page: an Artifact fragment (own title, inline style, no script). Order, as in an analytics report: coverage ribbon, key figures with sparklines, the trend (people per week, per day),
       the breakdowns (sections, controls, actions, devices), when people visit, whether they come back, recording health, how this is measured. */
    set_min_group(("min_group" in a.model.th) ? a.model.th.min_group : 5);
    const stamp = il_stamp(a.as_of) || `${a.ref} (no export time given)`;
    const out = [];
    const add = (x) => { out.push(x); };
    add('<title>Delivery Pulse Usage</title>\n<meta name="claude:viewport-fit-sides" content="cover">\n<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600&display=swap">');
    add(`<style>${CSS}</style>`);
    const per = _rb_t(a.n_sessions) ? _period(a) : "";
    add(`<header class="top gutter"><h1>Delivery Pulse Usage</h1><span class="stamp" id="asof">Data as of ${e(stamp)}</span>` + (per ? `<span class="period" id="period">${e(per)}</span>` : "") + '</header>');
    add('<main class="gutter">');
    if (a.demo) {
        add('<p class="demo" id="demo-banner" role="note">Demo data: this page shows fictitious people and numbers so the layout can be reviewed. It says nothing about real use.</p>');
    }
    for (const w of export_warnings(a)) {
        add(`<p class="warn" role="status">${ICON_WARN}<span>${e(w)}</span></p>`);
    }
    add(`<p class="ribbon" id="coverage"><b>Coverage.</b> ${e(ribbon_text(a))}</p>`);
    if (!_rb_t(a.n_sessions)) {
        add('<section class="empty" id="empty" aria-labelledby="h-empty"><h2 id="h-empty">No usage recorded yet</h2>'
            + '<p>The export holds no visit that this report can use, so there is nothing to show. Nothing on this page is an estimate.</p>'
            + '<ol><li>Open the published Delivery Pulse page as a person with edit access and use it for 30 seconds.</li>'
            + '<li>Export the documents of the collection <code>usage</code> with the ArtifactData tool.</li>'
            + '<li>Run this report on that file with <code>--as-of</code> set to the export time (and <code>--since</code> to the go-live day).</li></ol></section>');
        if (_rb_t(a.stats.unknown_schema) || _rb_t(a.stats.skipped) || _rb_t(a.counts.stale_sessions)) {
            add('<p class="cap">Some documents were skipped or are older than 12 weeks: see the warning above or the text report.</p>');
        }
    } else {
        if (a.history_days < SHORT_HISTORY_DAYS) {
            add(`<p class="note" id="caveat">Only ${pystr(a.history_days)} day${a.history_days === 1 ? "" : "s"} of data so far: trends are not meaningful yet.</p>`);
        }
        if (_rb_t(a.audience) && _rb_t(a.audience.stale)) {
            add('<p class="note" id="audience-note">The audience size looks out of date: more people are in the data than in the audience.</p>');
        }
        add(_kpis(a));
        add(_trend(a));
        add(_breakdowns(a));
        add(_heatmap_block(a));
        add(_back_block(a));
        add(_health_block(a));
    }
    add(_measure_block(a));
    add("</main>");
    add('<footer class="gutter">Delivery Pulse Usage. Counts only: this page never contains a user id.</footer>');
    const frag = out.join("\n");
    if (standalone) {
        return '<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1"></head><body>' + frag + "</body></html>";
    }
    return frag;
}
