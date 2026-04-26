// VaxRFP Pipeline dashboard
// Fetches opportunities.json + meta.json, renders filterable table,
// persists per-opportunity status (new/reviewing/applied/dismissed) in localStorage.

const STORAGE_KEY = "vaxrfp.status.v1";
const AREA_LABELS = {
  cold_chain: "Cold chain",
  manufacturing: "Manufacturing",
  regulatory: "Regulatory",
  procurement: "Procurement",
  mel: "M&E",
};

let RAW = [];      // all opportunities loaded from JSON
let META = {};     // meta.json content
let STATUS = loadStatus();  // {id: 'new'|'reviewing'|'applied'|'dismissed'}

// ---------- localStorage helpers ----------

function loadStatus() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
  } catch {
    return {};
  }
}

function saveStatus() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(STATUS));
}

function getStatus(id) {
  return STATUS[id] || "new";
}

function setStatus(id, value) {
  if (value === "new") delete STATUS[id];
  else STATUS[id] = value;
  saveStatus();
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
      `<tr><td colspan="8" id="empty-msg">Could not load data: ${e.message}</td></tr>`;
    return;
  }

  populateSourceFilter();
  renderMeta();
  applyAndRender();
}

function populateSourceFilter() {
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
    if (!f.status && status === "dismissed") return false;  // hide dismissed by default
    if (f.source && r.source !== f.source) return false;
    if (f.hideExpired && r.flags && r.flags.expired) return false;

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
  const filtered = applyFilters(RAW);
  renderKPIs(filtered);
  renderTable(filtered);
}

function renderKPIs(filtered) {
  document.getElementById("kpi-total").textContent = filtered.length;

  const newCount = filtered.filter(r => getStatus(r.id) === "new").length;
  document.getElementById("kpi-new").textContent = newCount;

  const appliedCount = RAW.filter(r => getStatus(r.id) === "applied").length;
  document.getElementById("kpi-applied").textContent = appliedCount;

  const top = filtered.reduce((m, r) => Math.max(m, r.fit_total || 0), 0);
  document.getElementById("kpi-top").textContent = filtered.length ? top.toFixed(1) : "—";
}

function renderTable(rows) {
  const tbody = document.getElementById("rfp-tbody");
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="8" id="empty-msg">No opportunities match the current filters.</td></tr>`;
    return;
  }

  tbody.innerHTML = "";
  for (const r of rows) {
    tbody.appendChild(renderRow(r));
  }
}

function renderRow(r) {
  const tr = document.createElement("tr");

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
  // Inline flags
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

  // Country
  const tdCountry = document.createElement("td");
  tdCountry.className = "country-cell";
  tdCountry.textContent = r.country || "—";
  tr.appendChild(tdCountry);

  // Top area
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

  // Fit score
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

  // Source
  const tdSource = document.createElement("td");
  tdSource.textContent = r.source;
  tr.appendChild(tdSource);

  // Closes (deadline)
  const tdClose = document.createElement("td");
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
    tdClose.className = cls;
    tdClose.textContent = text;
    tdClose.title = r.deadline;
  } else {
    tdClose.textContent = "—";
  }
  tr.appendChild(tdClose);

  // Status select
  const tdStatus = document.createElement("td");
  const sel = document.createElement("select");
  sel.className = `status-select status-${getStatus(r.id)}`;
  for (const opt of ["new", "reviewing", "applied", "dismissed"]) {
    const o = document.createElement("option");
    o.value = opt;
    o.textContent = opt;
    if (getStatus(r.id) === opt) o.selected = true;
    sel.appendChild(o);
  }
  sel.addEventListener("change", () => {
    setStatus(r.id, sel.value);
    sel.className = `status-select status-${sel.value}`;
    applyAndRender();   // re-filter (e.g. dismissed disappears)
  });
  tdStatus.appendChild(sel);
  tr.appendChild(tdStatus);

  // Action: open link
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

// ---------- wire up filters ----------

function wireFilters() {
  for (const id of ["f-area", "f-status", "f-min", "f-source", "f-hide-expired"]) {
    document.getElementById(id).addEventListener("change", applyAndRender);
  }
  document.getElementById("f-search").addEventListener("input", applyAndRender);
}

// ---------- init ----------

wireFilters();
loadData();
