// Runs right after the page's own script: records the state before any Refresh, and offers snapshots the tests read through CDP.
// harness.py fills in /*__SUBJ__*/ (the keys of the fictitious issues each case is about).
(() => {
  const S = /*__SUBJ__*/null;
  const find = (list, k) => list.find(x => x.k === k) || null;      // null, not undefined: JSON keeps the key
  window.__snap = () => ({
    epics: DATA.epics.length, bugs: DATA.bugs.length,
    e_status: find(DATA.epics, S.eStatus), e_removed: !!find(DATA.epics, S.eRemoved), e_moved: find(DATA.epics, S.eMoved), e_new: find(DATA.epics, S.newEpic),
    b_new: find(DATA.bugs, S.newBug), b_ax: find(DATA.bugs, S.axBug), b_resolved: find(DATA.bugs, S.openBug),
    dep: find(DATA.epics, S.eDep), keep: find(DATA.epics, S.eKeep), clr: find(DATA.epics, S.eClear),
    plset: find(DATA.epics, S.plSet), plclr: find(DATA.epics, S.plClear), plkeep: find(DATA.epics, S.plKeep),
    cdone: find(DATA.bugs, S.cfbDone), copen: find(DATA.bugs, S.cfbOpen),
    depCol: (() => { const c = [...document.querySelectorAll(".bcard")].find(a => a.textContent.includes(S.eDep)); const col = c && c.closest(".bcol"); return col ? col.getAttribute("aria-label") : null; })(),
    pmn_open: DATA.bugs.filter(b => b.p === "PMN" && !b.rd && !b.ax).length,
    cfbNewBug: find(DATA.bugs, S.newCfb),
    bugC: find(DATA.bugs, S.oC), bugD: find(DATA.bugs, S.oD), bugE: find(DATA.bugs, S.oE),
    fixedKeys: DATA.bugs.filter(isCfbFixed).map(b => b.k),
    deps: DATA.deps, ext1: (DATA.ext || {})[S.farKey] || null, linksAt: DATA.linksPulledAt || null,
    hierFv: DATA.hier[S.cap].fv, listFv: DATA.capList[S.cap] ? DATA.capList[S.cap].fv : null, listS: DATA.capList[S.cap] ? DATA.capList[S.cap].s : null, listCl: DATA.capList[S.cap] ? DATA.capList[S.cap].cl : null, capNoFv: DATA.capNoFv, capPulledAt: DATA.capPulledAt,
    stampTxt: document.getElementById("asof").textContent, stampTip: document.getElementById("asof").dataset.tip || "", capFail: DATA.capRefreshFailed || null,
    capVals: DATA.cap.values.slice(), capTeams: DATA.cap.teams.slice(), capRows: DATA.cap.rows, capAt: DATA.capRefreshedAt || null, capN: DATA.capRefreshedN == null ? null : DATA.capRefreshedN, capNote: (document.getElementById("capz-cap") || {}).textContent || "",
    refreshedAt: DATA.refreshedAt || null, refreshedStats: DATA.refreshedStats || null,
    slowRaw: (() => { try { return localStorage.getItem("dp.slowRuns"); } catch (e) { return "blocked"; } })(), edctAt: DATA.edctAt || null, edctFailed: DATA.edctFailed || null,
    effNote: (document.getElementById("eff-note") || {}).textContent || "", raNote: (document.getElementById("ra-note") || {}).textContent || "",
    noEdctRow: (() => { const h = attentionModel().hyg.find(x => x.label === "Done Epics with No EDCT"); return h ? {n: h.n, note: h.note} : null; })(),
  });
  window.__before = window.__snap();
  // "done": the refresh button went busy and is usable again (latched, so a status that clears itself later does not matter)
  const btn = document.getElementById("refresh");
  window.__sawBusy = false; window.__done = false;
  new MutationObserver(recs => { if (recs.some(r => r.attributeName === "disabled")) window.__sawBusy = true; if (window.__sawBusy && !btn.disabled) window.__done = true; }).observe(btn, {attributes: true});
  window.__collect = () => ({
    before: window.__before, after: window.__snap(), meta: document.getElementById("meta").textContent, badge: document.getElementById("badge").textContent,
    status: document.getElementById("status").textContent, btn: btn.textContent, disabled: btn.disabled, calls: window.__calls, mid: window.__mid || null,
    retry: !!document.getElementById("refresh-retry"), ls: (() => { try { return localStorage.getItem("dp.lastRefresh"); } catch (e) { return "blocked"; } })(),
    stamps: [...document.body.innerText.matchAll(/Data as of/g)].length, hidden_stamps: [...document.querySelectorAll("#asof,#meta")].map(e => e.textContent),
    kpiScope: document.querySelector("#kpis .kpi .v").textContent, bugOpenKpi: document.querySelector("#bug-kpis .kpi .v").textContent,
  });
})();
