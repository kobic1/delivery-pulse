// The page's only outside dependency, claude.use("mcp").callTool(...), answered locally in the real shape of the Atlassian
// searchJiraIssuesUsingJql tool: {payload: {issues: {nodes: [{key, fields}], pageInfo: {hasNextPage, endCursor}}}}.
// harness.py fills in /*__CFG__*/ (the answers) and /*__HOOK__*/ (an optional per-test override); nothing here touches the network.
(() => {
  const CFG = /*__CFG__*/null;
  const RD = Date, off = CFG.shift;
  if (off) { class D extends RD { constructor(...a) { if (a.length) super(...a); else super(RD.now() + off); } static now() { return RD.now() + off; } } window.Date = D; }
  if (CFG.fastTimers) { const st = window.setTimeout; window.setTimeout = (f, ms, ...a) => st(f, ms >= 4000 ? ms / 20 : ms, ...a); }
  // ls "recent" means "this case is about a click, not about the automatic refresh on open": the page's one 600 ms timer that starts it is dropped (ls "recentauto" keeps dp.lastRefresh recent and lets it run)
  if (CFG.ls === "recent") { const st = window.setTimeout; window.setTimeout = (f, ms, ...a) => (ms === 600 && /auto: true/.test(String(f))) ? 0 : st(f, ms, ...a); }   // the page's multi-second timers (settle, deadlines) run 20 times faster
  if (CFG.deadlineMs) window.__dpCallDeadlineMs = CFG.deadlineMs;      // a template with a per-call deadline reads its length from here (a no-op for one without)
  window.__CFG = CFG; window.__calls = []; window.__countCalls = [];
  try { localStorage.removeItem("delivery-pulse-filters"); } catch (e) {}
  try { if (!CFG.keep) { localStorage.removeItem("dp.slowRuns"); localStorage.removeItem("dp.slowData"); }      // CFG.keep: this page is a reload of the previous one, its stored allowance and limited-tier data stay
    // dp.slowRuns is the daily allowance of the limited refresh tier (cycle time, Capitalization); CFG.sr seeds it, the Israel day is computed here so CFG.shift is honoured
    if (CFG.sr) {
      const ilDay = t => new Intl.DateTimeFormat("en-CA", {timeZone: "Asia/Jerusalem", year: "numeric", month: "2-digit", day: "2-digit"}).format(t);
      const today = ilDay(new Date()), plus = n => ilDay(new Date(RD.parse(today + "T12:00:00Z") + n * 86400000));
      const seeds = {none: null, auto: {day: today, n: 0, auto: 1}, one: {day: today, n: 1, auto: 1}, used: {day: today, n: 2, auto: 1}, yesterday: {day: plus(-1), n: 2, auto: 1}, future: {day: plus(400), n: 2, auto: 1}, corrupt: "{not json"};
      const v = typeof CFG.sr === "string" ? (CFG.sr in seeds ? seeds[CFG.sr] : CFG.sr) : {day: today, ...CFG.sr};       // a name, a raw string stored as it is, or an object (the day defaults to today)
      if (v) localStorage.setItem("dp.slowRuns", typeof v === "string" ? v : JSON.stringify(v));
    }
  } catch (e) {}
  try { if (CFG.ls === "recent" || CFG.ls === "recentauto") localStorage.setItem("dp.lastRefresh", String(RD.now())); else if (CFG.ls === "old") localStorage.setItem("dp.lastRefresh", String(RD.now() - 3600000)); else if (CFG.ls === "none") localStorage.removeItem("dp.lastRefresh");
    if (CFG.ls === "blocked") Object.defineProperty(window, "localStorage", {get() { throw new Error("blocked"); }}); } catch (e) {}
  window.__hook = /*__HOOK__*/null;
  const ok = (nodes, more) => ({payload: {issues: {nodes, pageInfo: more ? {hasNextPage: true, endCursor: more} : {hasNextPage: false, endCursor: null}}}});
  window.__ok = ok;
  const self = {
    callTool: async (server, tool, input, opts) => {
      if (input && input.searchResultMode === "count") {          // Jira's own count of a query: the sum over the pages the same query returns (not logged as an ordinary call), plus CFG.countDelta to imitate a lost page
        window.__countCalls.push({jql: input.jql});
        if (CFG.mode === "nocount") return {payload: {issues: {nodes: []}}};
        let n = 0, tok;
        for (let i = 0; i < 50; i++) { const r = await self.callTool(server, tool, {...input, searchResultMode: undefined, nextPageToken: tok}, {...opts, __silent: true}); n += r.payload.issues.nodes.length; tok = r.payload.issues.pageInfo && r.payload.issues.pageInfo.endCursor; if (!tok) break; }
        return {payload: {issues: {totalCount: n + (CFG.countDelta || 0), nodes: []}}};
      }
      const idx = window.__calls.length;
      if (tool === "getJiraIssue") {          // an issue with its change history: In Progress 6 days before the resolution day, Validation 3 days before, Done on it (so EDCT = 6)
        window.__calls.push({i: idx, server, tool, jql: "issue " + input.issueIdOrKey, token: null, fields: (input.fields || []).length, opts});
        if (CFG.mode === "edctfail") throw {code: "tool_error", message: "history boom"};
        const all = [...(CFG.page1 || []), ...(CFG.page2 || [])], n = all.find(x => x.key === input.issueIdOrKey), rd = n && n.fields && n.fields.resolutiondate ? n.fields.resolutiondate.slice(0, 10) : "2026-01-01";
        const at = (d, k, h) => { const x = new RD(Date.UTC(+rd.slice(0, 4), +rd.slice(5, 7) - 1, +rd.slice(8, 10) - k, h)); return x.toISOString().slice(0, 19) + ".000+0000"; };
        const hist = [{created: at(rd, 0, 8), items: [{field: "status", fromString: "Validation", toString: "Done"}]}, {created: at(rd, 3, 8), items: [{field: "status", fromString: "In Progress", toString: "Validation"}]},
                      {created: at(rd, 6, 8), items: [{field: "status", fromString: "Ready for Dev", toString: "In Progress"}]}];
        return {payload: {issues: {nodes: [{key: input.issueIdOrKey, changelog: {startAt: 0, maxResults: 3, total: 3, histories: hist}, fields: {status: {name: "Done"}}}]}}};
      }
      if (!(opts && opts.__silent)) window.__calls.push({i: idx, server, tool, jql: input.jql, token: input.nextPageToken || null, fields: (input.fields || []).length, opts});
      if (CFG.slow) await new Promise(r => setTimeout(r, CFG.slow));
      const jql = input.jql, MODE = CFG.mode, farHasProject = (input.fields || []).includes("project");
      if (/(?<![\w-])INT(?![\w-])/i.test(String(jql).replace(/"(?:[^"\\]|\\.)*"/g, '""'))) throw {code: "tool_error", message: "Error in the JQL Query: 'INT' is a reserved JQL word. You must surround it in quotation marks."};      // as Jira answers a project key that is a reserved word
      if (window.__hook) { const h = await window.__hook(input, {idx, calls: window.__calls, CFG, ok}); if (h !== undefined) return h; }
      if (MODE === "denied") throw {code: "approval_required", message: "declined"};
      if (jql.includes("issuetype = Capability AND status != Removed AND fixVersion is EMPTY")) return ok([{key: "CXCROSS-90001", fields: {status: {name: "Done"}}}, {key: "CXCROSS-90002", fields: {status: {name: "New"}}}]);
      if (jql.includes("issuetype = Capability AND (updated")) { if (MODE === "capsfail") throw {code: "tool_error", message: "capabilities boom"}; return ok(CFG.capsnodes); }
      if (jql.includes("cf[10329] is not EMPTY") && jql.includes("status not in")) { if (MODE === "cfbfail") throw {code: "tool_error", message: "cfb boom"}; return ok(CFG.opencfb); }
      if (jql.includes("issuetype = Epic AND status != Removed AND fixVersion in (")) { if (MODE === "linksfail") throw {code: "tool_error", message: "links boom"}; return ok(CFG.linknodes); }
      if (/^key in \(/.test(jql) && farHasProject) return ok(CFG.farnodes);
      if (/^key in \(/.test(jql)) return ok(CFG.leftcfb);
      if (jql.includes("issuetype in (Bug, Story, Task)")) {
        if (MODE === "capfail") throw {code: "tool_error", message: "capitalization boom"};
        const proj = jql.match(/project = "?(\w+)"?/)[1];
        return ok(MODE === "emptycap" ? [] : CFG.capnodes.filter(n => n.key.startsWith(proj + "-")));
      }
      if (jql.includes("[Accessibility]")) return ok([{key: CFG.axkey, fields: {}}]);
      if (!input.nextPageToken) return ok(CFG.page1, "cursor-1");
      if (input.nextPageToken === "cursor-1") return ok(CFG.page2);
      throw {code: "tool_error", message: "unexpected cursor"};
    }
  };
  // ---- the `db` and `user` capabilities, only when a case sets CFG.usage (every other suite keeps getting null for both): an in-memory fake store with the real semantics of the documented db contract.
  // Switches in CFG.usage: db:null / user:null / uid:null (a viewer with no id) / uid:"..."; fault: "invalid" (every set and update rejects invalid_argument, also what a view-only viewer gets), "exhausted", "quota", "unavailable_once" (the first
  // write rejects `unavailable`, then all succeed), "unavailable_always"; getFault: the same codes for get; latency (ms per call); share:true keeps the store in localStorage (a reload or a second page of the same person sees it, keep:true does not clear it);
  // seed: {path: body} documents present at start; t: the page's usage timers (window.__dpUsageT); focus/vis: window.__focus and window.__vis, read by document.hasFocus() and document.visibilityState.
  const U = CFG.usage;
  let dbNs = null, userNs = null;
  if (U) {
    const KEY = "__mockdb", clone = x => JSON.parse(JSON.stringify(x));
    try { if (U.share && !CFG.keep) localStorage.removeItem(KEY); } catch (e) {}
    window.__dbDocs = {}; window.__dbLog = []; window.__dbOverlap = 0; window.__focus = true; window.__vis = "visible"; window.__dpUsageT = U.t || undefined;
    document.hasFocus = () => window.__focus !== false;
    for (const prop of ["visibilityState", "hidden"]) Object.defineProperty(document, prop, {configurable: true, get: () => prop === "hidden" ? window.__vis === "hidden" : window.__vis});
    const read = () => { if (!U.share) return window.__dbDocs; try { return JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) { return {}; } };
    const save = d => { if (U.share) localStorage.setItem(KEY, JSON.stringify(d)); };
    { const d = read(); for (const [k, v] of Object.entries(U.seed || {})) if (!(k in d)) d[k] = clone(v); save(d); window.__dbDocs = d; }
    window.__dbRead = read;
    const SEG = /^[A-Za-z0-9_\-.~:@+]+$/;
    const grammar = (path, even) => {
      const segs = String(path).split("/");
      if (typeof path !== "string" || segs.length > 16 || path.length > 1000) throw new TypeError("path too long or too deep: " + path);
      for (const s of segs) if (!SEG.test(s) || s === "." || s === ".." || s.length > 200) throw new TypeError("bad segment in " + path);
      if ((segs.length % 2 === 0) !== even) throw new TypeError(`a ${even ? "document" : "collection"} path has an ${even ? "even" : "odd"} number of segments: ${path}`);
    };
    const err = (code, message) => ({code, message});
    const depth = (x, d = 1) => x && typeof x === "object" ? Math.max(d, ...Object.values(x).map(v => depth(v, d + 1))) : d;
    const merge = (a, b) => { for (const [k, v] of Object.entries(b)) a[k] = (v && typeof v === "object" && !Array.isArray(v) && a[k] && typeof a[k] === "object" && !Array.isArray(a[k])) ? merge(a[k], v) : clone(v); return a; };
    const busy = {}; let writes = 0;
    const snap = (path, d) => Object.freeze({id: path.split("/").pop(), exists: d !== undefined, data: () => d === undefined ? undefined : clone(d), metadata: {fromCache: false, hasPendingWrites: false}});
    const run = async (op, path, data, fn) => {
      const entry = {op, path, data: data === undefined ? undefined : clone(data), at: Date.now(), result: "pending"}; window.__dbLog.push(entry);
      if (busy[path]) window.__dbOverlap++;
      busy[path] = (busy[path] || 0) + 1;
      try {
        if (U.latency) await new Promise(r => setTimeout(r, U.latency)); else await Promise.resolve();
        const out = fn(); entry.result = "ok"; return out;
      } catch (e) { entry.result = e.code || "error"; throw e; } finally { busy[path]--; }
    };
    const writeFault = () => {
      const f = U.fault; if (!f) return;
      if (f === "invalid") throw err("invalid_argument", "refused");
      if (f === "exhausted") throw err("resource_exhausted", "slow down");
      if (f === "quota") throw err("quota_exceeded", "full");
      if (f === "unavailable_always") throw err("unavailable", "later");
      if (f === "unavailable_once" && writes++ === 0) throw err("unavailable", "later");
    };
    const check = body => {
      if (!body || typeof body !== "object" || Array.isArray(body)) throw err("invalid_argument", "body must be an object");
      if (JSON.stringify(body).length > 256 * 1024) throw err("invalid_argument", "over 256 KiB");
      if (depth(body) > 32) throw err("invalid_argument", "over 32 levels");
    };
    const docRef = path => {
      grammar(path, true);
      return {id: path.split("/").pop(), path,
        get: () => run("get", path, undefined, () => { if (U.getFault) throw err(U.getFault, "get refused"); const d = read(); return snap(path, d[path] === undefined ? undefined : clone(d[path])); }),
        set: data => run("set", path, data, () => { writeFault(); check(data); const d = read(); d[path] = clone(data); save(d); window.__dbDocs = d; }),
        update: data => run("update", path, data, () => { writeFault(); check(data); const d = read(); if (d[path] === undefined) throw err("invalid_argument", "update needs an existing document"); d[path] = merge(d[path], clone(data)); save(d); window.__dbDocs = d; }),
        delete: () => run("delete", path, undefined, () => { const d = read(); delete d[path]; save(d); window.__dbDocs = d; }),
        collection: p => colRef(path + "/" + p)};
    };
    const colRef = path => { grammar(path, false); return {path, doc: id => docRef(path + "/" + (id || Math.random().toString(36).slice(2))), onSnapshot: () => () => {}}; };
    dbNs = Object.freeze({doc: docRef, collection: colRef});
    const uid = U.uid === undefined ? "u_synthetic_001" : U.uid;
    userNs = Object.freeze({id: async () => uid, name: async () => "Synthetic Person", email: async () => "synthetic.person@example.invalid", isOwner: async () => false, canEdit: async () => false, can: async () => null,
      me: async () => ({id: uid, name: "Synthetic Person", email: "synthetic.person@example.invalid", avatarUrl: "", color: "#000", isOwner: false, canEdit: false}), profiles: async ids => ({})});
  }
  window.claude = {use: async (name) => name === "mcp" ? self : (U && name === "db") ? (U.db === null ? null : dbNs) : (U && name === "user") ? (U.user === null ? null : userNs) : null};
})();
