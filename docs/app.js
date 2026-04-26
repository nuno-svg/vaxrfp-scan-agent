// VaxRFP Pipeline dashboard
// Splits opportunities into two views: RFPs (formal opportunities) and
// Signals (manufacturer news). Each view has its own KPIs and filtering.
// Persists per-opportunity status (new/reviewing/watch/applied/dismissed)
// and free-text notes in localStorage.

const STORAGE_KEY = "vaxrfp.status.v1";
const NOTES_KEY = "vaxrfp.notes.v1";
const VIEW_KEY = "vaxrfp.view.v1";
const SEEN_SIGNALS_KEY = "vaxrfp.seen_signals.v1";

const AREA_LABELS = {
  cold_chain: "Cold chain",
  manufacturing: "Manufacturing",
  regulatory: "Regulatory",
  procurement: "Procurement",
  mel: "M&E",
};

let RAW = [];      // all opportunities loaded from JSON
let META = {};     // meta.json content
let STATUS = loadStatus();
let NOTES = loadNotes();
let VIEW = loadView();           // 'rfps' | 'signals'
let SEEN_SIGNALS = loadSeenSignals();  // {id: true} — IDs marked as seen across visits

// ---------- localStorage helpers ----------

function loadStatus() {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}"); }
  catch { return {}; }
}

function saveStatus() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(STATUS));
}

function getStatus(id) { return STATUS[id] || "new"; }

function setStatus(id, value) {
  if (value === "new") delete STATUS[id];
  else STATUS[id] = value;
  saveStatus();
}

function loadNotes() {
  try { return JSON.parse(localStorage.getItem(NOTES_KEY) || "{}"); }
  catch { return {}; }
}

function saveNotes() {
  localStorage.setItem(NOTES_KEY, JSON.stringify(NOTES));
}

function getNote(id) { return NOTES[id] || ""; }

function setNote(id, value) {
  const trimmed = (value || "").trim();
  if (trimmed === "") delete NOTES[id];
  else NOTES[id] = trimmed;
  saveNotes();
}

function loadView() {
  const v = localStorage.getItem(VIEW_KEY);
  return v === "signals" ? "signals" : "rfps";
}

function saveView(v) {
  VIEW = v;
  localStorage.setItem(VIEW_KEY, v);
}

function loadSeenSignals() {
  try { return JSON.parse(localStorage.getItem(SEEN_SIGNALS_KEY) || "{}"); }
  catch { return {}; }
}

function saveSeenSignals() {
  localStorage.setItem(SEEN_SIGNALS_KEY, JSON.stringify(SEEN_SIGNALS));
}

// ---------- view splitting ----------

function isSignal(r) {
  return !!(r.source && r.source.startsWith("Signal:"));
}

function rfpRows() {
  return RAW.filter(r => !isSignal(r));
}

function signalRows() {
  return RAW.filter(r => isSignal(r));
}

// ---------- helpers ----------

let SORT = { col: "fit", desc: true };

function relativeDate(iso) {
  if (!iso) return null;
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return null;
    const now = new Date();
    const diffDays = Math.floor((now - d) / (1000 * 60 * 60 * 24));
    if (diffDays < 0) return d.toISOString().slice(0, 10);
    if (diffDays === 0) return "today";
    if (diffDays === 1) return "yesterday";
    if (diffDays < 30) return `${diffDays}d ago`;
    if (diffDays < 365) return `${Math.floor(diffDays / 30)}mo ago`;
    return d.toISOString().slice(0, 10);
  } catch { return null; }
}

function getPublishedISO(r) {
  if (r.raw && r.raw.published) return r.raw.published;
  if (r.raw && r.raw.wb_notice_type && r.noticedate) return r.noticedate;
  return r.first_seen || null;
}

// Dedup signals — group multiple news articles about the same event.
function dedupSignals(rows) {
  const groups = new Map();
  const out = [];
  for (const r of rows) {
    if (!isSignal(r)) {
      out.push(r);
      continue;
    }
    const mfr = r.source.replace("Signal:", "").trim();
    const titleNorm = (r.title || "")
      .toLowerCase()
      .replace(/[^a-z0-9 ]/g, " ")
      .split(/\s+/)
      .filter(w => w.length > 3)
      .slice(0, 4)
      .sort()
      .join(" ");
    const key = `${mfr}::${titleNorm}`;
    if (!groups.has(key)) {
      groups.set(key, { primary: r, dupes: [] });
    } else {
      const g = groups.get(key);
      if ((r.fit_total || 0) > (g.primary.fit_total || 0)) {
        g.dupes.push(g.primary);
        g.primary = r;
      } else {
        g.dupes.push(r);
      }
    }
  }
  for (const { primary, dupes } of groups.values()) {
    if (dupes.length > 0) {
      primary._dupe_count = dupes.length;
      primary._dupe_sources = dupes.map(d => d.url);
    }
    out.push(primary);
  }
  return out;
}

function sortRows(rows) {
  const col = SORT.col;
  const dir = SORT.desc ? -1 : 1;
  return rows.slice().sort((a, b) => {
    let av, bv;
    switch (col) {
      case "title":     av = (a.title || "").toLowerCase(); bv = (b.title || "").toLowerCase(); break;
      case "country":   av = (a.country || "zzz").toLowerCase(); bv = (b.country || "zzz").toLowerCase(); break;
      case "area":      av = a.fit_top_area || ""; bv = b.fit_top_area || ""; break;
      case "fit":       av = a.fit_total || 0; bv = b.fit_total || 0; break;
      case "source":    av = a.source || ""; bv = b.source || ""; break;
      case "published": av = getPublishedISO(a) || ""; bv = getPublishedISO(b) || ""; break;
      case "closes":    av = a.deadline || "9999-12-31"; bv = b.deadline || "9999-12-31"; break;
      default:          av = a.fit_total || 0; bv = b.fit_total || 0;
    }
    if (av < bv) return -1 * dir;
    if (av > bv) return  1 * dir;
    return 0;
  });
}

function exportCSV(rows) {
  const headers = ["Title", "Country", "Top area", "Fit", "Source",
                   "Published", "Deadline", "Status", "Notes", "URL"];
  const lines = [headers.join(",")];
  for (const r of rows) {
    const fields = [
      r.title || "",
      r.country || "",
      AREA_LABELS[r.fit_top_area] || r.fit_top_area || "",
      (r.fit_total || 0).toFixed(1),
      r.source || "",
      getPublishedISO(r) ? getPublishedISO(r).slice(0, 10) : "",
      r.deadline || "",
      getStatus(r.id),
      getNote(r.id),
      r.url || "",
    ];
    lines.push(fields.map(csvEscape).join(","));
  }
  const csv = lines.join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  const stamp = new Date().toISOString().slice(0, 10);
  a.href = url;
  a.download = `vaxrfp-${VIEW}-${stamp}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

function csvEscape(v) {
  const s = String(v);
  if (s.includes(",") || s.includes('"') || s.includes("\n")) {
    return `"${s.replace(/"/g, '""')}"`;
  }
  return s;
}

// ---------- data loading ----------

async function loadData() {
  try {
    const [oppsRes, metaRes] = await Promise.all([
      fetch("opportunities.json", { cache: "no-store" }),
      fetch("meta.json", { cache: "no-store" }),
    ]);
    RAW = await oppsRes.json();
    META = await metaRes.json();
  } catch (e) {
    document.getElementById("rfp-tbody").innerHTML =
      `<tr><td colspan="10" id="empty-msg">Could not load data: ${e.message}</td></tr>`;
    return;
  }

  populateSourceFilter();
  renderMeta();
  updateTabCounts();
  applyView();           // sets visibility of KPI sections + initial render
}

function populateSourceFilter() {
  // Show all sources but mark which are signals — user can filter within a view
  const sources = [...new Set(RAW.map(r => r.source))].sort();
  const sel = document.getElementById("f-source");
  for (const s of sources) {
    const opt = document.createElement("option");
    opt.value = s;
    opt.textContent = s;
    sel.appendChild(opt);
  }
}

function renderMeta() {
  const last = META.last_run
    ? new Date(META.last_run).toISOString().replace("T", " ").slice(0, 16) + " UTC"
    : "unknown";
  document.getElementById("meta-line").textContent =
    `last run ${last} · ${META.total_kept || 0} kept · ${META.total_excluded || 0} excluded`;
}

function updateTabCounts() {
  document.getElementById("tab-count-rfps").textContent = rfpRows().length;
  // Dedup signals for accurate count
  document.getElementById("tab-count-signals").textContent =
    dedupSignals(signalRows()).length;
}

// ---------- view switching ----------

function switchView(newView) {
  if (newView === VIEW) return;

  // Mark all currently-visible signals as seen when leaving signals view
  if (VIEW === "signals") {
    for (const r of dedupSignals(signalRows())) {
      SEEN_SIGNALS[r.id] = true;
    }
    saveSeenSignals();
  }

  saveView(newView);
  applyView();
}

function applyView() {
  // Update tab UI
  const tRfps = document.getElementById("tab-rfps");
  const tSigs = document.getElementById("tab-signals");
  tRfps.classList.toggle("active", VIEW === "rfps");
  tSigs.classList.toggle("active", VIEW === "signals");
  tRfps.setAttribute("aria-selected", VIEW === "rfps");
  tSigs.setAttribute("aria-selected", VIEW === "signals");

  // Swap KPI panels
  document.getElementById("kpis-rfps").classList.toggle("hidden", VIEW !== "rfps");
  document.getElementById("kpis-signals").classList.toggle("hidden", VIEW !== "signals");

  // Update help text & filter visibility
  const help = document.getElementById("tab-help");
  if (VIEW === "rfps") {
    help.textContent = "Formal RFPs, EOIs, and CFPs scored against 5 expertise areas.";
  } else {
    help.textContent = "Manufacturer news (Google News RSS) — early-warning indicators of upstream procurement, not formal RFPs.";
  }

  // Hide deadline-related controls in Signals view (signals have no deadlines)
  document.querySelectorAll(".filter-hide-expired").forEach(el =>
    el.classList.toggle("hidden", VIEW === "signals"));
  document.querySelectorAll(".col-closes").forEach(el =>
    el.classList.toggle("hidden", VIEW === "signals"));

  applyAndRender();
}

// ---------- filtering ----------

function getFilters() {
  return {
    area: document.getElementById("f-area").value,
    status: document.getElementById("f-status").value,
    minScore: parseInt(document.getElementById("f-min").value, 10) || 0,
    source: document.getElementById("f-source").value,
    hideExpired: document.getElementById("f-hide-expired").checked,
    search: document.getElementById("f-search").value.trim().toLowerCase(),
  };
}

function applyFilters(rows) {
  const f = getFilters();
  return rows.filter(r => {
    const status = getStatus(r.id);
    if (f.status && status !== f.status) return false;
    if (!f.status && status === "dismissed") return false;
    if (f.source && r.source !== f.source) return false;
    if (f.hideExpired && r.flags && r.flags.expired && VIEW === "rfps") return false;

    let score = r.fit_total || 0;
    if (f.area) {
      score = (r.fit_per_area && r.fit_per_area[f.area]) || 0;
    }
    if (score < f.minScore) return false;

    if (f.search) {
      const hay = `${r.title} ${r.country || ""} ${r.source}`.toLowerCase();
      if (!hay.includes(f.search)) return false;
    }
    return true;
  });
}

// ---------- rendering ----------

function applyAndRender() {
  const baseRows = VIEW === "rfps" ? rfpRows() : signalRows();
  let filtered = applyFilters(baseRows);
  if (VIEW === "signals") {
    filtered = dedupSignals(filtered);
  }
  filtered = sortRows(filtered);
  renderKPIs(filtered);
  renderTable(filtered);
  updateTabCounts();
  const ec = document.getElementById("export-count");
  if (ec) ec.textContent = `(${filtered.length} rows)`;
}

function renderKPIs(filtered) {
  if (VIEW === "rfps") {
    document.getElementById("kpi-rfps-total").textContent = filtered.length;
    const newCount = filtered.filter(r => getStatus(r.id) === "new").length;
    document.getElementById("kpi-rfps-new").textContent = newCount;
    const appliedCount = rfpRows().filter(r => getStatus(r.id) === "applied").length;
    document.getElementById("kpi-rfps-applied").textContent = appliedCount;
    const top = filtered.reduce((m, r) => Math.max(m, r.fit_total || 0), 0);
    document.getElementById("kpi-rfps-top").textContent = filtered.length ? top.toFixed(1) : "—";
  } else {
    document.getElementById("kpi-signals-total").textContent = filtered.length;
    const newSinceLast = filtered.filter(r => !SEEN_SIGNALS[r.id]).length;
    document.getElementById("kpi-signals-new").textContent = newSinceLast;
    const watchCount = signalRows().filter(r => getStatus(r.id) === "watch").length;
    document.getElementById("kpi-signals-watch").textContent = watchCount;
    const mfrs = new Set(filtered.map(r => (r.source || "").replace("Signal:", "")));
    document.getElementById("kpi-signals-mfrs").textContent = mfrs.size;
  }
}

function renderTable(rows) {
  const tbody = document.getElementById("rfp-tbody");
  if (!rows.length) {
    const msg = VIEW === "rfps"
      ? "No RFPs match the current filters."
      : "No signals match the current filters.";
    tbody.innerHTML = `<tr><td colspan="10" id="empty-msg">${msg}</td></tr>`;
    return;
  }

  tbody.innerHTML = "";
  for (const r of rows) {
    tbody.appendChild(renderRow(r));
  }
}

function renderRow(r) {
  const tr = document.createElement("tr");

  // Mark unseen signals visually
  if (VIEW === "signals" && !SEEN_SIGNALS[r.id]) {
    tr.classList.add("row-unseen");
  }

  // Title cell
  const tdTitle = document.createElement("td");
  tdTitle.className = "title-cell";
  const a = document.createElement("a");
  a.href = r.url;
  a.target = "_blank";
  a.rel = "noopener";
  a.textContent = r.title;
  tdTitle.appendChild(a);
  if (r.description) {
    const desc = document.createElement("span");
    desc.className = "desc";
    desc.textContent = (r.description || "").slice(0, 180) + (r.description.length > 180 ? "…" : "");
    tdTitle.appendChild(desc);
  }
  if (r.flags) {
    if (r.flags.requires_review_sanctions) {
      const f = document.createElement("span"); f.className = "flag flag-review"; f.textContent = "review (sanctions)";
      f.title = (r.flag_notes && r.flag_notes.sanctions) || "";
      tdTitle.appendChild(f);
    }
    if (r.flags.requires_review_eligibility) {
      const f = document.createElement("span"); f.className = "flag flag-elig"; f.textContent = "review (eligibility)";
      f.title = (r.flag_notes && r.flag_notes.eligibility) || "";
      tdTitle.appendChild(f);
    }
    if (r.flags.urgent_deadline) {
      const f = document.createElement("span"); f.className = "flag flag-urgent"; f.textContent = "urgent";
      tdTitle.appendChild(f);
    }
  }
  tr.appendChild(tdTitle);

  const tdCountry = document.createElement("td");
  tdCountry.className = "country-cell";
  tdCountry.textContent = r.country || "—";
  tr.appendChild(tdCountry);

  const tdArea = document.createElement("td");
  if (r.fit_top_area) {
    const tag = document.createElement("span");
    tag.className = "area-tag";
    tag.textContent = AREA_LABELS[r.fit_top_area] || r.fit_top_area;
    tdArea.appendChild(tag);
  } else {
    tdArea.textContent = "—";
  }
  tr.appendChild(tdArea);

  const tdFit = document.createElement("td");
  const fit = r.fit_total || 0;
  const pill = document.createElement("span");
  pill.className = `fit-pill fit-${Math.round(fit)}`;
  pill.textContent = fit.toFixed(1);
  pill.title = r.fit_per_area
    ? Object.entries(r.fit_per_area).map(([k, v]) => `${AREA_LABELS[k] || k}: ${v}`).join("\n")
    : "";
  tdFit.appendChild(pill);
  tr.appendChild(tdFit);

  const tdSource = document.createElement("td");
  tdSource.textContent = r.source;
  if (r._dupe_count) {
    const badge = document.createElement("span");
    badge.className = "dupe-badge";
    badge.textContent = `+${r._dupe_count}`;
    badge.title = `Also covered by ${r._dupe_count} other source${r._dupe_count > 1 ? "s" : ""}`;
    tdSource.appendChild(document.createTextNode(" "));
    tdSource.appendChild(badge);
  }
  tr.appendChild(tdSource);

  const tdPub = document.createElement("td");
  tdPub.className = "published-cell";
  const pubISO = getPublishedISO(r);
  if (pubISO) {
    const rel = relativeDate(pubISO);
    tdPub.textContent = rel || "—";
    tdPub.title = pubISO;
  } else {
    tdPub.textContent = "—";
  }
  tr.appendChild(tdPub);

  const tdClose = document.createElement("td");
  tdClose.classList.add("col-closes");
  if (VIEW === "signals") tdClose.classList.add("hidden");
  if (r.deadline) {
    const days = r.deadline_days;
    let cls = "deadline-normal";
    let text = r.deadline;
    if (days !== null && days !== undefined) {
      if (days < 0) { cls = "deadline-expired"; text = `${r.deadline} (expired)`; }
      else if (days <= 7) { cls = "deadline-urgent"; text = `${days}d`; }
      else if (days <= 21) { cls = "deadline-soon"; text = `${days}d`; }
      else { text = `${days}d`; }
    }
    tdClose.classList.add(cls);
    tdClose.textContent = text;
    tdClose.title = r.deadline;
  } else {
    tdClose.textContent = "—";
  }
  tr.appendChild(tdClose);

  const tdStatus = document.createElement("td");
  const sel = document.createElement("select");
  sel.className = `status-select status-${getStatus(r.id)}`;
  for (const opt of ["new", "reviewing", "watch", "applied", "dismissed"]) {
    const o = document.createElement("option");
    o.value = opt;
    o.textContent = opt;
    if (getStatus(r.id) === opt) o.selected = true;
    sel.appendChild(o);
  }
  sel.addEventListener("change", () => {
    setStatus(r.id, sel.value);
    sel.className = `status-select status-${sel.value}`;
    applyAndRender();
  });
  tdStatus.appendChild(sel);
  tr.appendChild(tdStatus);

  const tdNotes = document.createElement("td");
  const noteInput = document.createElement("textarea");
  noteInput.className = "note-input";
  noteInput.rows = 1;
  noteInput.placeholder = "add note…";
  noteInput.value = getNote(r.id);
  noteInput.addEventListener("blur", () => {
    setNote(r.id, noteInput.value);
  });
  tdNotes.appendChild(noteInput);
  tr.appendChild(tdNotes);

  const tdAction = document.createElement("td");
  const open = document.createElement("a");
  open.href = r.url;
  open.target = "_blank";
  open.rel = "noopener";
  open.textContent = "Open ↗";
  tdAction.appendChild(open);
  tr.appendChild(tdAction);

  return tr;
}

// ---------- wiring ----------

function wireFilters() {
  for (const id of ["f-area", "f-status", "f-min", "f-source", "f-hide-expired"]) {
    document.getElementById(id).addEventListener("change", applyAndRender);
  }
  document.getElementById("f-search").addEventListener("input", applyAndRender);
}

function wireExport() {
  const btn = document.getElementById("btn-export-csv");
  if (!btn) return;
  btn.addEventListener("click", () => {
    const baseRows = VIEW === "rfps" ? rfpRows() : signalRows();
    let filtered = applyFilters(baseRows);
    if (VIEW === "signals") filtered = dedupSignals(filtered);
    filtered = sortRows(filtered);
    if (filtered.length === 0) {
      alert("Nothing to export — adjust filters first.");
      return;
    }
    exportCSV(filtered);
  });
}

function wireSorting() {
  const headers = document.querySelectorAll("#rfp-table th[data-sort]");
  for (const th of headers) {
    th.style.cursor = "pointer";
    th.addEventListener("click", () => {
      const col = th.dataset.sort;
      if (SORT.col === col) {
        SORT.desc = !SORT.desc;
      } else {
        SORT.col = col;
        SORT.desc = ["fit", "published", "closes"].includes(col);
      }
      for (const h of headers) {
        h.classList.remove("sort-asc", "sort-desc");
      }
      th.classList.add(SORT.desc ? "sort-desc" : "sort-asc");
      applyAndRender();
    });
  }
}

function wireTabs() {
  document.getElementById("tab-rfps").addEventListener("click", () => switchView("rfps"));
  document.getElementById("tab-signals").addEventListener("click", () => switchView("signals"));
}

// ---------- init ----------

wireFilters();
wireExport();
wireSorting();
wireTabs();
loadData();
