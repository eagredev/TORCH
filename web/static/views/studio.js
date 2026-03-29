/**
 * TORCH Web GUI -- Studio Hub: Map Browser with collapsible inline panels.
 * Single-page accordion view — clicking a map row expands detail in-place.
 */

import { api, postApi } from "../app.js";
import { esc } from "../utils.js";

let cachedMaps = null;
let filteredMaps = [];
let renderedCount = 0;
let scrollHandler = null;
let debounceTimer = null;
let activeTab = "all";     // "all" | "custom" | "vanilla"
let activeHealthFilter = "all";  // "all" | "ok" | "stale" | "drift" | "orphan" | "new"
let searchQuery = "";
let expandedMap = null;     // currently expanded map name (accordion: only one)
const detailCache = {};     // {mapName: detailData}
const PAGE_SIZE = 48;
let statsData = null;       // cached /api/stats response
let attentionData = null;   // cached /api/maps/attention response
let assetData = null;       // cached /api/assets/custom response

// Encounter type pill colours
const ENC_COLOURS = {
  Land: "#4ade80",
  Water: "#60a5fa",
  Fishing: "#22d3ee",
  "Rock Smash": "#a3704d",
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function filterMaps(maps) {
  let result = maps;

  // Category filter: All / Custom / Vanilla
  if (activeTab === "custom") {
    // Custom = any non-vanilla map (ACTIVE, CUSTOM, or ORPHAN)
    result = result.filter(m => m.status !== "VANILLA");
  } else if (activeTab === "vanilla") {
    result = result.filter(m => m.status === "VANILLA");
  }
  // "all" shows everything

  // Health/status filter
  if (activeHealthFilter !== "all") {
    result = result.filter(m => {
      if (activeHealthFilter === "new") {
        return m.health === "never_written" || m.health === "missing_workspace";
      }
      return m.health === activeHealthFilter;
    });
  }

  if (searchQuery) {
    const q = searchQuery.toLowerCase();
    result = result.filter(m => m.name.toLowerCase().includes(q));
  }

  return result;
}

/**
 * Count maps per health status within the current category tab.
 */
function computeHealthCounts(maps) {
  let pool = maps;
  if (activeTab === "custom") {
    pool = pool.filter(m => m.status !== "VANILLA");
  } else if (activeTab === "vanilla") {
    pool = pool.filter(m => m.status === "VANILLA");
  }

  // Also apply search query so chips reflect the search
  if (searchQuery) {
    const q = searchQuery.toLowerCase();
    pool = pool.filter(m => m.name.toLowerCase().includes(q));
  }

  const counts = { all: pool.length, ok: 0, stale: 0, drift: 0, orphan: 0, new: 0 };
  for (const m of pool) {
    if (m.health === "ok") counts.ok++;
    else if (m.health === "stale") counts.stale++;
    else if (m.health === "drift") counts.drift++;
    else if (m.health === "orphan") counts.orphan++;
    else if (m.health === "never_written" || m.health === "missing_workspace") counts.new++;
  }
  return counts;
}

function renderHealthBadge(health) {
  if (!health) return "";
  const cssClass = health.replace(/_/g, "-");
  const label = health === "never_written" ? "new" : health === "missing_workspace" ? "new" : health;
  return `<span class="health-badge health-${cssClass}">${label}</span>`;
}

function renderEncPills(map) {
  if (!map.has_encounters) return "";
  return `<span class="studio-enc-pill" style="background:#2d6a2d;color:#8f8">Enc</span>`;
}

/**
 * Convert a TRAINER_CONST to a human-readable name.
 * e.g. "TRAINER_ROCKET_BUSTER" -> "Rocket Buster"
 */
function constToHumanName(c) {
  let name = c;
  if (name.startsWith("TRAINER_")) name = name.slice(8);
  return name.replace(/_/g, " ").replace(/\b\w/g, ch => ch.toUpperCase());
}

// ---------------------------------------------------------------------------
// Map row rendering
// ---------------------------------------------------------------------------

function renderMapRow(m) {
  const isVanilla = m.status === "VANILLA";
  const nameClass = isVanilla ? "studio-map-name dim" : "studio-map-name";
  const isExpanded = expandedMap === m.name;

  // Always show status badge (custom/vanilla)
  const statusBadge = isVanilla
    ? `<span class="studio-status-badge studio-status-vanilla">vanilla</span>`
    : `<span class="studio-status-badge studio-status-custom">custom</span>`;

  // Show health badge only for enrolled maps with health data
  const healthBadge = (m.enrolled && m.health) ? renderHealthBadge(m.health) : "";

  let meta = [];
  if (m.script_count > 0) meta.push(`<span class="studio-meta-item" title="Scripts">${m.script_count} scripts</span>`);
  if (m.trainer_count > 0) meta.push(`<span class="studio-meta-item" title="Trainers">${m.trainer_count} trainers</span>`);

  const encPill = renderEncPills(m);

  return `<div class="studio-map-row${isExpanded ? " expanded" : ""}" data-map="${m.name}">
    <div class="studio-map-left">
      <span class="studio-chevron">\u25B6</span>
      <span class="${nameClass}">${m.name}</span>
      <span class="studio-map-badges">${healthBadge}${statusBadge}</span>
    </div>
    <div class="studio-map-right">
      ${meta.join("")}
      ${encPill}
    </div>
  </div>`;
}

// ---------------------------------------------------------------------------
// Panel rendering (expanded detail)
// ---------------------------------------------------------------------------

function renderPanel(mapName, detail, listMeta, scripts, chains) {
  const scriptCount = listMeta ? listMeta.script_count || 0 : 0;

  // Scripts section — list individual script names
  let scriptsHtml;
  if (scripts && scripts.length > 0) {
    scriptsHtml = scripts.map(s =>
      `<a href="#/visualizer/${mapName}/${s.name}" class="studio-script-link">${s.name}</a>`
    ).join("<br>");
  } else if (scriptCount > 0) {
    scriptsHtml = `<span class="studio-panel-count">${scriptCount} script${scriptCount !== 1 ? "s" : ""}</span>`;
  } else {
    scriptsHtml = `<span class="studio-dim">None</span>`;
  }

  // Chains section
  let chainsHtml = `<span class="studio-dim">None</span>`;
  if (chains && chains.length > 0) {
    chainsHtml = chains.map(c =>
      `<a href="#/chains/${c.name}" class="studio-chain-link">${c.name}</a>
       <span class="studio-chain-meta">${c.script_count || 0} scripts</span>`
    ).join("<br>");
  }

  // Trainers section
  let trainerHtml = `<span class="studio-dim">None</span>`;
  if (detail.trainer_consts && detail.trainer_consts.length > 0) {
    trainerHtml = detail.trainer_consts.map(t => {
      const name = constToHumanName(t);
      return `<a href="#/trainers/${t}" class="studio-trainer-link" title="${t}">${name}</a>`;
    }).join("<br>");
  }

  // Encounters section
  let encHtml = `<a href="#/encounters/${mapName}" class="studio-panel-enc-link studio-dim" title="Open encounter editor">+ Add encounters</a>`;
  const hasEnc = detail.encounter_detail && Object.keys(detail.encounter_detail).length > 0;
  if (hasEnc) {
    encHtml = Object.entries(detail.encounter_detail).map(([type, count]) => {
      const colour = ENC_COLOURS[type] || "#888";
      return `<a href="#/encounters/${mapName}" class="studio-panel-enc-link" style="--enc-colour:${colour}">${type} (${count} slots)</a>`;
    }).join("<br>");
  }

  // NPCs section
  let npcHtml = `<span class="studio-dim">None</span>`;
  if (detail.npc_names && detail.npc_names.length > 0) {
    // Group duplicates
    const counts = {};
    for (const n of detail.npc_names) {
      counts[n] = (counts[n] || 0) + 1;
    }
    npcHtml = Object.entries(counts).map(([name, cnt]) => {
      return cnt > 1 ? `${name} x${cnt}` : name;
    }).join(", ");
  }

  // Connections + warps
  const dirArrows = { north: "\u2191", south: "\u2193", east: "\u2192", west: "\u2190", up: "\u2191", down: "\u2193" };
  let connItems = [];
  if (detail.connections && detail.connections.length > 0) {
    for (const c of detail.connections) {
      const arrow = dirArrows[c.direction.toLowerCase()] || "\u2192";
      connItems.push(`<div class="studio-conn-entry"><span class="studio-conn-dir">${arrow} ${c.direction}</span><a href="javascript:void(0)" class="studio-conn-link" data-navigate="${c.map}">${c.map}</a></div>`);
    }
  }
  if (detail.warps && detail.warps.length > 0) {
    const warpMap = {};
    for (const w of detail.warps) {
      if (!warpMap[w.dest_map]) {
        warpMap[w.dest_map] = { dest_map: w.dest_map, count: 1 };
      } else {
        warpMap[w.dest_map].count++;
      }
    }
    for (const w of Object.values(warpMap)) {
      const suffix = w.count > 1 ? ` x${w.count}` : "";
      connItems.push(`<div class="studio-conn-entry"><span class="studio-conn-dir">\u21B3 Warp</span><a href="javascript:void(0)" class="studio-conn-link" data-navigate="${w.dest_map}">${w.dest_map}${suffix}</a></div>`);
    }
  }
  const connHtml = connItems.length > 0
    ? connItems.join("")
    : `<span class="studio-dim">None</span>`;

  // Enroll/Unenroll button
  const enrollBtn = detail.enrolled
    ? `<button class="studio-unenroll-btn" data-map="${mapName}">Unenroll</button>`
    : `<button class="studio-enroll-btn" data-map="${mapName}">Enroll</button>`;

  // Sync button — only for stale/drift/never_written
  const needsSync = detail.enrolled && detail.health && ["stale", "drift", "never_written"].includes(detail.health);
  const syncBtn = needsSync
    ? `<button class="studio-sync-btn" data-action="sync">Sync</button>`
    : "";

  const scriptHeaderCount = scripts ? scripts.length : scriptCount;
  return `<div class="studio-panel open">
    <div class="studio-panel-grid">
      <div class="studio-panel-section">
        <h4 class="studio-panel-header-link" data-href="#/scripts/${mapName}">Scripts (${scriptHeaderCount})</h4>
        <div class="studio-panel-body">${scriptsHtml}</div>
      </div>
      <div class="studio-panel-section">
        <h4 class="studio-panel-header-link"${detail.trainer_consts && detail.trainer_consts.length > 0 ? ` data-href="#/trainers"` : ""}>Trainers (${detail.trainer_count || 0})</h4>
        <div class="studio-panel-body">${trainerHtml}</div>
      </div>
      <div class="studio-panel-section">
        <h4 class="studio-panel-header-link"${hasEnc ? ` data-href="#/encounters/${mapName}"` : ""}>Encounters</h4>
        <div class="studio-panel-body">${encHtml}</div>
      </div>
      <div class="studio-panel-section">
        <h4>Chains (${chains ? chains.length : 0})</h4>
        <div class="studio-panel-body">${chainsHtml}</div>
      </div>
      <div class="studio-panel-section">
        <h4>NPCs (${detail.npc_count || 0})</h4>
        <div class="studio-panel-body">${npcHtml}</div>
      </div>
      <div class="studio-panel-section">
        <h4>Connections</h4>
        <div class="studio-panel-body studio-conn-grid">${connHtml}</div>
      </div>
    </div>
    <div class="studio-panel-actions">
      ${enrollBtn}
      ${syncBtn}
      <button class="studio-build-btn" data-action="build">Build</button>
      <span class="studio-panel-status"></span>
    </div>
  </div>`;
}

// ---------------------------------------------------------------------------
// Expand / collapse logic
// ---------------------------------------------------------------------------

/** Reference to the main container for re-rendering */
let mainContainer = null;
let allMaps = null;  // full maps array from API

function collapseAll() {
  if (!mainContainer) return;
  const prev = mainContainer.querySelector(".studio-map-row.expanded");
  if (prev) {
    prev.classList.remove("expanded");
    const panel = prev.nextElementSibling;
    if (panel && panel.classList.contains("studio-panel")) {
      panel.remove();
    }
  }
  expandedMap = null;
}

async function toggleExpand(rowEl) {
  const mapName = rowEl.dataset.map;

  if (expandedMap === mapName) {
    // Collapse
    collapseAll();
    sessionStorage.removeItem("torch-studio-expanded");
    return;
  }

  // Collapse any previous
  collapseAll();

  // Mark expanded
  expandedMap = mapName;
  sessionStorage.setItem("torch-studio-expanded", mapName);
  rowEl.classList.add("expanded");

  // Create placeholder panel
  const placeholder = document.createElement("div");
  placeholder.className = "studio-panel open";
  placeholder.innerHTML = `<div class="studio-panel-loading">Loading...</div>`;
  rowEl.after(placeholder);

  // Fetch detail data, scripts, and chains in parallel (lazy, cached)
  if (!detailCache[mapName]) {
    try {
      const resp = await api(`/studio/maps/${mapName}`);
      if (resp.ok) {
        detailCache[mapName] = resp.data;
      } else {
        placeholder.innerHTML = `<div class="studio-panel-loading" style="color:#f44">${esc(resp.error || "Failed to load")}</div>`;
        return;
      }
    } catch (err) {
      placeholder.innerHTML = `<div class="studio-panel-loading" style="color:#f44">${esc(err.message)}</div>`;
      return;
    }
  }

  // Fetch scripts and chains in parallel (best effort, don't block on failure)
  let scripts = [];
  let chains = [];
  try {
    const [scenesResp, chainsResp] = await Promise.all([
      api(`/scenes/${mapName}`),
      api(`/chains/by-script/${mapName}/_all`),
    ]);
    if (scenesResp.ok && scenesResp.data) scripts = scenesResp.data.scripts || [];
    if (chainsResp.ok && chainsResp.data) chains = chainsResp.data.chains || [];
  } catch (_) {}

  // Find list meta for script_count
  const listMeta = allMaps ? allMaps.find(m => m.name === mapName) : null;

  // Render panel
  const panelHtml = renderPanel(mapName, detailCache[mapName], listMeta, scripts, chains);
  const temp = document.createElement("div");
  temp.innerHTML = panelHtml;
  const panelEl = temp.firstElementChild;
  placeholder.replaceWith(panelEl);

  // Wire up connection navigation links
  panelEl.querySelectorAll("[data-navigate]").forEach(link => {
    link.addEventListener("click", (e) => {
      e.preventDefault();
      navigateToMap(link.dataset.navigate);
    });
  });

  // Wire up clickable section headers
  panelEl.querySelectorAll("[data-href]").forEach(el => {
    el.addEventListener("click", () => {
      window.location.hash = el.dataset.href;
    });
  });

  // Wire up sync/build buttons
  wirePanelActions(panelEl);
}

function refreshMapList() {
  cachedMaps = null;
  // Clear detail cache so re-expand picks up new enrolled state
  for (const k of Object.keys(detailCache)) delete detailCache[k];
  if (mainContainer) {
    render(mainContainer);
  }
}

function wirePanelActions(panelEl) {
  const statusEl = panelEl.querySelector(".studio-panel-status");

  // Enroll button
  const enrollBtn = panelEl.querySelector(".studio-enroll-btn");
  if (enrollBtn) {
    enrollBtn.addEventListener("click", async () => {
      const mapName = enrollBtn.dataset.map;
      enrollBtn.disabled = true;
      enrollBtn.textContent = "Enrolling...";
      try {
        const res = await postApi(`/studio/maps/${mapName}/enroll`);
        if (res.ok) {
          enrollBtn.textContent = "Enrolled!";
          setTimeout(() => refreshMapList(), 400);
        } else {
          enrollBtn.textContent = "Enroll";
          enrollBtn.disabled = false;
          if (statusEl) statusEl.textContent = res.error || "Enroll failed";
        }
      } catch (err) {
        enrollBtn.textContent = "Enroll";
        enrollBtn.disabled = false;
        if (statusEl) statusEl.textContent = "Network error";
      }
    });
  }

  // Unenroll button
  const unenrollBtn = panelEl.querySelector(".studio-unenroll-btn");
  if (unenrollBtn) {
    unenrollBtn.addEventListener("click", async () => {
      const mapName = unenrollBtn.dataset.map;
      if (!confirm(`Unenroll ${mapName}? This removes it from the TORCH registry.`)) return;
      unenrollBtn.disabled = true;
      unenrollBtn.textContent = "Unenrolling...";
      try {
        const res = await postApi(`/studio/maps/${mapName}/unenroll`);
        if (res.ok) {
          unenrollBtn.textContent = "Unenrolled";
          setTimeout(() => refreshMapList(), 400);
        } else {
          unenrollBtn.textContent = "Unenroll";
          unenrollBtn.disabled = false;
          if (statusEl) statusEl.textContent = res.error || "Unenroll failed";
        }
      } catch (err) {
        unenrollBtn.textContent = "Unenroll";
        unenrollBtn.disabled = false;
        if (statusEl) statusEl.textContent = "Network error";
      }
    });
  }

  const syncBtn = panelEl.querySelector("[data-action='sync']");
  if (syncBtn) {
    syncBtn.addEventListener("click", async () => {
      const mapName = syncBtn.closest(".studio-panel")?.previousElementSibling?.dataset?.map;
      syncBtn.disabled = true;
      syncBtn.textContent = "Syncing...";
      try {
        // Per-map sync if we can determine the map name, otherwise fall back to full sync
        const endpoint = mapName ? `/api/sync/${encodeURIComponent(mapName)}` : "/api/sync";
        const res = await fetch(endpoint, { method: "POST" });
        const body = await res.json();
        if (body.ok) {
          syncBtn.textContent = "Synced!";
          if (statusEl) {
            statusEl.textContent = mapName
              ? `Sync started for ${mapName}`
              : `Sync started (${body.data.count} map${body.data.count !== 1 ? "s" : ""})`;
          }
          // Refresh map data after a short delay so the health badge updates
          setTimeout(() => refreshMapList(), 1500);
        } else {
          syncBtn.textContent = "Sync";
          syncBtn.disabled = false;
          if (statusEl) statusEl.textContent = body.error || "Sync failed";
        }
      } catch (err) {
        syncBtn.textContent = "Sync";
        syncBtn.disabled = false;
        if (statusEl) statusEl.textContent = "Network error";
      }
    });
  }

  const buildBtn = panelEl.querySelector("[data-action='build']");
  if (buildBtn) {
    buildBtn.addEventListener("click", async () => {
      buildBtn.disabled = true;
      buildBtn.textContent = "Building...";
      try {
        const res = await fetch("/api/build", { method: "POST" });
        const body = await res.json();
        if (body.ok) {
          buildBtn.textContent = "Build started";
          if (statusEl) statusEl.textContent = "Build started";
        } else {
          buildBtn.textContent = "Build";
          buildBtn.disabled = false;
          if (statusEl) statusEl.textContent = body.error || "Build failed";
        }
      } catch (err) {
        buildBtn.textContent = "Build";
        buildBtn.disabled = false;
        if (statusEl) statusEl.textContent = "Network error";
      }
    });
  }
}

// ---------------------------------------------------------------------------
// Connection click -> scroll + expand
// ---------------------------------------------------------------------------

function navigateToMap(mapName) {
  collapseAll();

  // Check if target is in current filtered list
  let targetInList = filteredMaps.find(m => m.name === mapName);
  if (!targetInList) {
    // Switch to "All" tab + reset health filter to find it
    activeTab = "all";
    activeHealthFilter = "all";
    if (mainContainer) {
      mainContainer.querySelectorAll(".studio-tab").forEach(b => b.classList.toggle("active", b.dataset.tab === "all"));
      renderStatusChips(mainContainer);
    }
    refilterAndRender();
    targetInList = filteredMaps.find(m => m.name === mapName);
  }

  if (!targetInList) return;  // map doesn't exist at all

  // Ensure enough rows are rendered to include the target
  const targetIdx = filteredMaps.indexOf(targetInList);
  while (renderedCount <= targetIdx) {
    renderMoreRows(mainContainer);
  }

  // Find the row and scroll to it
  const row = mainContainer.querySelector(`[data-map="${mapName}"]`);
  if (row) {
    row.scrollIntoView({ behavior: "smooth", block: "center" });
    setTimeout(() => toggleExpand(row), 300);
  }
}

// ---------------------------------------------------------------------------
// List rendering with infinite scroll
// ---------------------------------------------------------------------------

function renderMoreRows(container) {
  const end = Math.min(renderedCount + PAGE_SIZE, filteredMaps.length);
  const fragment = document.createDocumentFragment();
  for (let i = renderedCount; i < end; i++) {
    const div = document.createElement("div");
    div.innerHTML = renderMapRow(filteredMaps[i]);
    const rowEl = div.firstElementChild;
    rowEl.addEventListener("click", (e) => {
      // Don't toggle if clicking a link inside the row
      if (e.target.closest("a")) return;
      toggleExpand(rowEl);
    });
    fragment.appendChild(rowEl);
  }
  const list = container.querySelector(".studio-map-list");
  if (list) list.appendChild(fragment);
  renderedCount = end;
}

function updateResults(container) {
  const results = container.querySelector(".studio-results");
  if (results) {
    results.textContent = `${filteredMaps.length} map${filteredMaps.length !== 1 ? "s" : ""}`;
  }
}

function refilterAndRender() {
  if (!mainContainer || !allMaps) return;
  filteredMaps = filterMaps(allMaps);
  renderedCount = 0;
  expandedMap = null;
  const list = mainContainer.querySelector(".studio-map-list");
  if (list) list.innerHTML = "";
  renderMoreRows(mainContainer);
  updateResults(mainContainer);
}

function renderStatusChips(container) {
  if (!allMaps) return;
  const hc = computeHealthCounts(allMaps);
  const chipBar = container.querySelector(".studio-status-chips");
  if (!chipBar) return;

  const chips = [
    { key: "all",    label: "All",    count: hc.all },
    { key: "ok",     label: "OK",     count: hc.ok },
    { key: "stale",  label: "Stale",  count: hc.stale },
    { key: "drift",  label: "Drift",  count: hc.drift },
    { key: "orphan", label: "Orphan", count: hc.orphan },
    { key: "new",    label: "New",    count: hc.new },
  ];

  chipBar.innerHTML = chips.map(c =>
    `<button class="studio-status-chip${activeHealthFilter === c.key ? " active" : ""} studio-chip-${c.key}" data-health="${c.key}">${c.label} <span class="studio-chip-count">(${c.count})</span></button>`
  ).join("");

  chipBar.querySelectorAll(".studio-status-chip").forEach(btn => {
    btn.addEventListener("click", () => {
      activeHealthFilter = btn.dataset.health;
      chipBar.querySelectorAll(".studio-status-chip").forEach(b => b.classList.toggle("active", b.dataset.health === activeHealthFilter));
      refilterAndRender();
    });
  });
}

function renderList(container, maps, counts) {
  allMaps = maps;
  mainContainer = container;

  // Compute custom count: ACTIVE + CUSTOM + ORPHAN (all non-vanilla)
  const customCount = (counts.active || 0) + (counts.custom || 0) + (counts.orphan || 0);

  // Dashboard data
  const s = statsData || {};
  const att = attentionData || {};
  const ast = assetData || {};
  const needsSync = (att.needs_sync || []).length;
  const trainerCustom = s.trainer_count_custom || 0;
  const trainerMax = s.trainer_slots_max || 0;
  const flagFree = s.flag_free || 0;
  const flagTotal = s.flag_total || 0;
  const enrolled = s.enrolled_count || 0;
  const assetStaged = ast.total_staged || 0;
  const assetCustom = ast.total_custom || 0;

  // Tool card data
  const encounterMaps = s.encounter_map_count || 0;
  const scriptMaps = enrolled;
  const shopCount = s.shop_count || 0;
  const healCount = s.heal_count || 0;

  container.innerHTML = `
    <div class="studio-stats-strip">
      <span class="studio-strip-item" data-href="#/trainers"><strong>${trainerCustom}</strong> / ${trainerMax || "?"} Trainers</span>
      <span class="studio-strip-sep">\u2502</span>
      <span class="studio-strip-item" data-href="#/flags"><strong>${flagFree}</strong> / ${flagTotal} Flags Free</span>
      <span class="studio-strip-sep">\u2502</span>
      <span class="studio-strip-item" data-scroll="maps"><strong>${enrolled}</strong> Maps Enrolled${needsSync > 0 ? ` <span class="studio-stat-warn">(${needsSync} need sync)</span>` : ""}</span>
      <span class="studio-strip-sep">\u2502</span>
      <span class="studio-strip-item" data-href="#/assets"><strong>${assetCustom}</strong> Custom Assets${assetStaged > 0 ? ` <span class="studio-stat-warn">(${assetStaged} staged)</span>` : ""}</span>
    </div>

    <div class="studio-map-widget">
      <div class="studio-widget-header">
        <h2 class="studio-widget-title">Maps</h2>
        <div class="studio-widget-toolbar">
          <div class="studio-tabs">
            <button class="studio-tab${activeTab === "all" ? " active" : ""}" data-tab="all">All</button>
            <button class="studio-tab${activeTab === "custom" ? " active" : ""}" data-tab="custom">Custom</button>
            <button class="studio-tab${activeTab === "vanilla" ? " active" : ""}" data-tab="vanilla">Vanilla</button>
          </div>
          <input type="text" class="studio-search" placeholder="Search maps..." value="${searchQuery}">
        </div>
      </div>
      <div class="studio-map-scroll">
        <div class="studio-map-list"></div>
      </div>
      <div class="studio-widget-footer">
        <div class="studio-status-chips"></div>
        <div class="studio-results"></div>
      </div>
    </div>

    <div class="studio-tool-grid">
      <a href="#/encounters" class="studio-tool-card">
        <span class="studio-tool-card-icon">\u2666</span>
        <div class="studio-tool-card-info">
          <div class="studio-tool-card-name">Encounters</div>
          <div class="studio-tool-card-sub">${encounterMaps} map${encounterMaps !== 1 ? "s" : ""}</div>
        </div>
      </a>
      <a href="#/trainers" class="studio-tool-card">
        <span class="studio-tool-card-icon">\u2694</span>
        <div class="studio-tool-card-info">
          <div class="studio-tool-card-name">Trainers</div>
          <div class="studio-tool-card-sub">${trainerCustom} custom</div>
        </div>
      </a>
      <a href="#/scripts" class="studio-tool-card">
        <span class="studio-tool-card-icon">\u00B6</span>
        <div class="studio-tool-card-info">
          <div class="studio-tool-card-name">Scripts</div>
          <div class="studio-tool-card-sub">${scriptMaps} enrolled</div>
        </div>
      </a>
      <a href="#/flags" class="studio-tool-card">
        <span class="studio-tool-card-icon">\u2691</span>
        <div class="studio-tool-card-info">
          <div class="studio-tool-card-name">Flags</div>
          <div class="studio-tool-card-sub">${flagFree} free</div>
        </div>
      </a>
      <a href="#/shops" class="studio-tool-card">
        <span class="studio-tool-card-icon">\u229E</span>
        <div class="studio-tool-card-info">
          <div class="studio-tool-card-name">Shops</div>
        </div>
      </a>
      <a href="#/heals" class="studio-tool-card">
        <span class="studio-tool-card-icon">\u2764</span>
        <div class="studio-tool-card-info">
          <div class="studio-tool-card-name">Heals</div>
        </div>
      </a>
      <a href="#/assets" class="studio-tool-card">
        <span class="studio-tool-card-icon">\u{1F5BC}</span>
        <div class="studio-tool-card-info">
          <div class="studio-tool-card-name">Assets</div>
          ${assetStaged > 0 ? `<div class="studio-tool-card-sub studio-stat-warn">${assetStaged} staged</div>` : `<div class="studio-tool-card-sub">${assetCustom} imported</div>`}
        </div>
      </a>
      <a href="#/explorer" class="studio-tool-card">
        <span class="studio-tool-card-icon">\u{1F5FA}</span>
        <div class="studio-tool-card-info">
          <div class="studio-tool-card-name">Explorer</div>
          <div class="studio-tool-card-sub">${counts.total || 0} maps</div>
        </div>
      </a>
    </div>
  `;

  // Stats strip click handlers
  container.querySelectorAll(".studio-strip-item[data-href]").forEach(item => {
    item.addEventListener("click", () => {
      window.location.hash = item.dataset.href;
    });
  });
  container.querySelectorAll(".studio-strip-item[data-scroll]").forEach(item => {
    item.addEventListener("click", () => {
      const widget = container.querySelector(".studio-map-widget");
      if (widget) widget.scrollIntoView({ behavior: "smooth" });
    });
  });

  // Tab click handler
  container.querySelectorAll(".studio-tab").forEach(btn => {
    btn.addEventListener("click", () => {
      activeTab = btn.dataset.tab;
      container.querySelectorAll(".studio-tab").forEach(b => b.classList.toggle("active", b.dataset.tab === activeTab));
      // Re-render chips (counts change per category) and list
      renderStatusChips(container);
      refilterAndRender();
    });
  });

  // Search handler
  const searchInput = container.querySelector(".studio-search");
  if (searchInput) {
    searchInput.addEventListener("input", () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        searchQuery = searchInput.value.trim();
        renderStatusChips(container);
        refilterAndRender();
      }, 200);
    });
  }

  // Initial render
  renderStatusChips(container);
  filteredMaps = filterMaps(maps);
  renderedCount = 0;
  renderMoreRows(container);
  updateResults(container);

  // Restore previously expanded map from sessionStorage
  const savedMap = sessionStorage.getItem("torch-studio-expanded");
  if (savedMap && filteredMaps.find(m => m.name === savedMap)) {
    navigateToMap(savedMap);
  }

  // Infinite scroll — on the map scroll container, not the window
  const scrollBox = container.querySelector(".studio-map-scroll");
  if (scrollBox) {
    scrollHandler = () => {
      if (renderedCount >= filteredMaps.length) return;
      const threshold = scrollBox.scrollHeight - scrollBox.clientHeight - 200;
      if (scrollBox.scrollTop >= threshold) {
        renderMoreRows(container);
      }
    };
    scrollBox.addEventListener("scroll", scrollHandler);
  }
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

export async function render(container) {
  container.innerHTML = `<p style="color:#888">Loading Studio Hub...</p>`;
  try {
    // Fetch all data in parallel
    const [mapsResp, statsResp, attResp, assetResp] = await Promise.all([
      cachedMaps ? Promise.resolve({ ok: true, data: cachedMaps }) : api("/studio/maps"),
      api("/stats"),
      api("/maps/attention"),
      api("/assets/custom"),
    ]);

    if (!mapsResp.ok) {
      container.innerHTML = `<article><p style="color:#f44">${esc(mapsResp.error)}</p></article>`;
      return;
    }
    cachedMaps = mapsResp.data;
    statsData = statsResp.ok ? statsResp.data : null;
    attentionData = attResp.ok ? attResp.data : null;
    assetData = assetResp.ok ? assetResp.data : null;

    renderList(container, cachedMaps.maps, cachedMaps.counts);
  } catch (err) {
    container.innerHTML = `<article><p style="color:#f44">${esc(err.message)}</p></article>`;
  }
}

export function cleanup() {
  if (scrollHandler) {
    // Scroll handler is on the map scroll container, not window
    const scrollBox = mainContainer && mainContainer.querySelector(".studio-map-scroll");
    if (scrollBox) scrollBox.removeEventListener("scroll", scrollHandler);
    scrollHandler = null;
  }
  clearTimeout(debounceTimer);
  cachedMaps = null;
  renderedCount = 0;
  filteredMaps = [];
  expandedMap = null;
  mainContainer = null;
  allMaps = null;
  // Clear detail cache (const object — delete keys, can't reassign)
  for (const k of Object.keys(detailCache)) delete detailCache[k];
  // Reset filter/search state
  activeTab = "all";
  activeHealthFilter = "all";
  searchQuery = "";
  statsData = null;
  attentionData = null;
  assetData = null;
}
