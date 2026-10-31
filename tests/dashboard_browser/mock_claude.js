// The page's only outside dependency, claude.use("mcp").callTool(...), answered locally in the real shape of the Atlassian
// searchJiraIssuesUsingJql tool: {payload: {issues: {nodes: [{key, fields}], pageInfo: {hasNextPage, endCursor}}}}.
// harness.py fills in /*__CFG__*/ (the answers) and /*__HOOK__*/ (an optional per-test override); nothing here touches the network.
(() => {
  const CFG = /*__CFG__*/null;
  const RD = Date, off = CFG.shift;
  if (off) { class D extends RD { constructor(...a) { if (a.length) super(...a); else super(RD.now() + off); } static now() { return RD.now() + off; } } window.Date = D; }
  if (CFG.fastTimers) { const st = window.setTimeout; window.setTimeout = (f, ms, ...a) => st(f, ms >= 4000 ? ms / 20 : ms, ...a); }   // the page's multi-second timers (settle, deadlines) run 20 times faster
  if (CFG.deadlineMs) window.__dpCallDeadlineMs = CFG.deadlineMs;      // a template with a per-call deadline reads its length from here (a no-op for one without)
  window.__CFG = CFG; window.__calls = []; window.__countCalls = [];
  try { localStorage.removeItem("delivery-pulse-filters"); } catch (e) {}
  try { if (CFG.ls === "recent") localStorage.setItem("dp.lastRefresh", String(RD.now())); else if (CFG.ls === "old") localStorage.setItem("dp.lastRefresh", String(RD.now() - 3600000)); else if (CFG.ls === "none") localStorage.removeItem("dp.lastRefresh");
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
        const proj = jql.match(/project = (\w+)/)[1];
        return ok(MODE === "emptycap" ? [] : CFG.capnodes.filter(n => n.key.startsWith(proj + "-")));
      }
      if (jql.includes("[Accessibility]")) return ok([{key: CFG.axkey, fields: {}}]);
      if (!input.nextPageToken) return ok(CFG.page1, "cursor-1");
      if (input.nextPageToken === "cursor-1") return ok(CFG.page2);
      throw {code: "tool_error", message: "unexpected cursor"};
    }
  };
  window.claude = {use: async (name) => name !== "mcp" ? null : self};
})();
