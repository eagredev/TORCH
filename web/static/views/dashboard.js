/**
 * TORCH Web GUI — Dashboard view.
 * Rich project overview: stats, health, attention, activity, build.
 */

import { api, postApi, getEventSource } from "../app.js";
import { esc } from "../utils.js";

let buildLineCount = 0;

const LAST_BUILD_LINES_KEY = "torch_last_build_lines";

const HEALTH_LABELS = {
  ok: "OK",
  stale: "Stale",
  drift: "Drift",
  orphan: "Orphan",
  never_written: "New",
  missing_workspace: "Missing",
};

const HEALTH_CLASSES = {
  ok: "ok",
  stale: "stale",
  drift: "drift",
  orphan: "orphan",
  never_written: "never",
  missing_workspace: "never",
};

function timeAgo(dateStr) {
  if (!dateStr) return "never";
  const then = new Date(dateStr);
  const now = new Date();
  const secs = Math.floor((now - then) / 1000);
  if (secs < 60) return "just now";
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.floor(days / 30);
  return `${months}mo ago`;
}

export async function render(container) {
  container.innerHTML = `
    <div class="dash-header">
      <h1>Loading...</h1>
      <p class="dash-subtitle"></p>
    </div>

    <div class="dash-lan-badge" style="display:none"></div>

    <section class="dash-section build-section">
      <h2>Build</h2>
      <div class="dash-build-buttons">
        <button class="dash-build-btn" data-mode="release" disabled>Build ROM</button>
        <button class="dash-build-btn dash-build-dev" data-mode="dev" disabled>Dev Build</button>
      </div>
      <p class="dash-build-hint">Dev Build enables debug menus (outputs pokeemerald.gba). Release Build optimizes and strips debug features (outputs pokeemerald-release.gba).</p>
      <div class="dash-download-panel">
        <h3 class="dash-download-title">Download ROM</h3>
        <div class="dash-download-list">
          <div class="dl-row dl-unavailable"><div class="dl-row-info"><span class="dl-label">Dev Build</span><span class="dl-meta">Not built yet</span></div></div>
          <div class="dl-row dl-unavailable"><div class="dl-row-info"><span class="dl-label">Release Build</span><span class="dl-meta">Not built yet</span></div></div>
        </div>
      </div>
      <div class="build-output-wrap" style="display:none">
        <pre class="build-log"></pre>
        <div class="build-progress"><div class="build-progress-fill"></div></div>
        <p class="build-status building"></p>
      </div>
    </section>

    <section class="dash-section">
      <h2>Overview</h2>
      <div class="stat-cards"></div>
    </section>

    <section class="dash-section backup-section">
      <h2>Backups <a href="#/project" class="dash-section-link">Manage</a></h2>
      <div class="backup-summary">Loading...</div>
    </section>

    <section class="dash-section attention-section">
      <h2>Needs Attention</h2>
      <div class="attention-content"></div>
    </section>

    <section class="dash-section">
      <h2>Enrolled Maps</h2>
      <div class="health-grid"></div>
      <p class="health-summary"></p>
    </section>

    <section class="dash-section chain-section">
      <h2>Script Chains</h2>
      <div class="chain-status-list"></div>
    </section>

    <section class="dash-section">
      <h2>Recent Activity</h2>
      <div class="activity-list"></div>
    </section>
  `;

  const header = container.querySelector(".dash-header h1");
  const subtitle = container.querySelector(".dash-subtitle");
  const statCards = container.querySelector(".stat-cards");
  const attentionContent = container.querySelector(".attention-content");
  const healthGrid = container.querySelector(".health-grid");
  const healthSummary = container.querySelector(".health-summary");
  const activityList = container.querySelector(".activity-list");
  const buildBtns = container.querySelectorAll(".dash-build-btn");
  const buildWrap = container.querySelector(".build-output-wrap");
  const buildLog = container.querySelector(".build-log");
  const buildStatus = container.querySelector(".build-status");
  const buildProgress = container.querySelector(".build-progress");
  const buildProgressFill = container.querySelector(".build-progress-fill");

  const lanBadge = container.querySelector(".dash-lan-badge");
  const backupSummary = container.querySelector(".backup-summary");
  const downloadPanel = container.querySelector(".dash-download-panel");
  const downloadList = container.querySelector(".dash-download-list");

  // Check if any ROMs are available for download
  api("/download/rom/info").then(res => {
    if (res.ok) renderDownloadPanel(downloadPanel, downloadList, res.data);
  }).catch(() => {});

  // Load status (header)
  const statusPromise = api("/status").then(res => {
    if (res.ok) {
      const d = res.data;
      header.textContent = d.project_name;
      subtitle.textContent =
        `TORCH ${d.torch_version} | Expansion ${d.expansion_version}`;
      buildBtns.forEach(b => b.disabled = false);

      // LAN access badge
      if (d.lan_url && lanBadge) {
        let html = `<span class="lan-badge-icon">&#x1F310;</span> `;
        html += `<span class="lan-badge-url">${esc(d.lan_url)}</span>`;
        if (d.lan_user) {
          html += `<span class="lan-badge-sep">&middot;</span>`;
          html += `<span class="lan-badge-creds">user: <strong>${esc(d.lan_user)}</strong></span>`;
        }
        lanBadge.innerHTML = html;
        lanBadge.style.display = "";
      }
    }
  }).catch(() => {
    header.textContent = "Error loading status";
    buildBtns.forEach(b => b.disabled = false);
  });

  // Load stats
  const statsPromise = api("/stats").then(res => {
    if (res.ok) renderStatCards(statCards, res.data);
  }).catch(() => {
    statCards.innerHTML = `<p style="color:#888">Could not load stats.</p>`;
  });

  // Load attention
  const attentionPromise = api("/maps/attention").then(res => {
    if (res.ok) renderAttention(attentionContent, res.data);
  }).catch(() => {
    attentionContent.innerHTML =
      `<p style="color:#888">Could not load attention data.</p>`;
  });

  // Load maps (for health grid + activity)
  const mapsPromise = api("/maps").then(res => {
    if (res.ok) {
      renderHealthGrid(healthGrid, healthSummary, res.data.enrolled);
      renderActivity(activityList, res.data.enrolled);
    }
  }).catch(() => {
    healthGrid.innerHTML = `<p style="color:#888">Could not load maps.</p>`;
  });

  // Load chain status
  const chainList = container.querySelector(".chain-status-list");
  const chainsPromise = api("/chains").then(res => {
    if (res.ok) renderChainStatus(chainList, res.data.chains || []);
  }).catch(() => {
    if (chainList) chainList.innerHTML = `<p style="color:#888">No chains found.</p>`;
  });

  // Load backups
  const backupsPromise = api("/project/backups").then(res => {
    if (res.ok) renderBackupSummary(backupSummary, res.data.backups || []);
    else backupSummary.innerHTML = `<p style="color:#888">Could not load backup info.</p>`;
  }).catch(() => {
    backupSummary.innerHTML = `<p style="color:#888">Could not load backup info.</p>`;
  });

  await Promise.all([statusPromise, statsPromise, attentionPromise, mapsPromise, chainsPromise, backupsPromise]);

  // SSE
  connectSSE(buildBtns, buildWrap, buildLog, buildStatus, buildProgress,
             buildProgressFill, attentionContent, healthGrid, healthSummary,
             activityList);

  // Build buttons (release + dev)
  buildBtns.forEach(btn => {
    btn.addEventListener("click", async () => {
      const mode = btn.dataset.mode || "release";
      buildBtns.forEach(b => b.disabled = true);
      buildLog.textContent = "";
      buildLineCount = 0;
      buildWrap.style.display = "";
      buildProgress.style.display = "";
      buildProgressFill.style.width = "0%";
      buildProgressFill.classList.remove("indeterminate", "complete", "failed");
      buildStatus.textContent = mode === "dev" ? "Dev building..." : "Building...";
      buildStatus.className = "build-status building";
      const lastLines = parseInt(localStorage.getItem(LAST_BUILD_LINES_KEY), 10);
      if (!lastLines) buildProgressFill.classList.add("indeterminate");

      try {
        const url = mode === "dev" ? "/api/build?mode=dev" : "/api/build";
        const res = await fetch(url, { method: "POST" });
        const body = await res.json();
        if (!body.ok) {
          buildStatus.textContent = body.error || "Failed to start build";
          buildStatus.className = "build-status failure";
          buildBtns.forEach(b => b.disabled = false);
        }
      } catch (err) {
        buildStatus.textContent = "Network error: " + err.message;
        buildStatus.className = "build-status failure";
        buildBtns.forEach(b => b.disabled = false);
      }
    });
  });

  // Sync button handler (delegated)
  container.addEventListener("click", async (e) => {
    if (e.target.classList.contains("sync-btn")) {
      e.target.disabled = true;
      e.target.textContent = "Syncing...";
      try {
        const res = await fetch("/api/sync", { method: "POST" });
        const body = await res.json();
        if (!body.ok) {
          e.target.textContent = body.error || "Sync failed";
        }
      } catch (err) {
        e.target.textContent = "Sync error";
      }
    }
    // Backup Now button (delegated — button is re-rendered on refresh)
    if (e.target.classList.contains("dash-backup-btn")) {
      handleBackupClick(e.target, backupSummary);
    }
  });
}

function renderStatCards(container, stats) {
  const cards = [
    {
      label: "Species",
      value: stats.species_count || 0,
    },
    {
      label: "Trainers",
      value: stats.trainer_count_total || 0,
      sub: `${stats.trainer_count_custom || 0} custom / ${stats.trainer_count_vanilla || 0} vanilla`
        + (stats.trainer_slots_max ? ` / ${stats.trainer_slots_max} max` : ""),
    },
    {
      label: "Enrolled Maps",
      value: stats.enrolled_count || 0,
      sub: `${stats.map_count_custom || 0} custom / ${stats.map_count_total || 0} total`,
    },
    {
      label: "Free Flags",
      value: stats.flag_free || 0,
      sub: `of ${stats.flag_total || 0} slots`,
    },
  ];

  container.innerHTML = cards.map(c => `
    <div class="stat-card">
      <div class="stat-card-label">${c.label}</div>
      <div class="stat-card-value">${c.value.toLocaleString()}</div>
      ${c.sub ? `<div class="stat-card-sub">${c.sub}</div>` : ""}
    </div>
  `).join("");
}

function renderAttention(container, data) {
  const { needs_sync, unenrolled } = data;
  let html = "";

  if (needs_sync.length === 0 && unenrolled.length === 0) {
    html = `<p class="attention-ok">All maps healthy</p>`;
    container.innerHTML = html;
    return;
  }

  if (needs_sync.length > 0) {
    html += needs_sync.map(m => {
      const cls = `health-badge health-${m.health.replace("_", "-")}`;
      const label = HEALTH_LABELS[m.health] || m.health;
      return `<div class="attention-item">
        <span class="map-name">${esc(m.name)}</span>
        <span class="${cls}">${label}</span>
      </div>`;
    }).join("");
    html += `<button class="sync-btn">Sync All</button>`;
  }

  if (unenrolled.length > 0) {
    html += `<div class="unenrolled-section">
      <h3>Unenrolled</h3>
      <p class="unenrolled-list">${esc(unenrolled.join(", "))}</p>
      <p class="unenrolled-hint">These workspace folders aren't enrolled. Use <code>torch enroll</code> to add them.</p>
    </div>`;
  }

  container.innerHTML = html;
}

function renderHealthGrid(grid, summary, enrolled) {
  if (!enrolled || enrolled.length === 0) {
    grid.innerHTML =
      `<p style="color:#888">No maps enrolled. Use <code>torch enroll</code>.</p>`;
    summary.textContent = "";
    return;
  }

  grid.innerHTML = enrolled.map(m => {
    const cls = HEALTH_CLASSES[m.health] || "never";
    const label = HEALTH_LABELS[m.health] || m.health;
    return `<div class="health-block ${cls}" title="${esc(m.name)} (${label})"></div>`;
  }).join("");

  // Summary counts
  const counts = {};
  for (const m of enrolled) {
    const h = m.health;
    counts[h] = (counts[h] || 0) + 1;
  }
  const parts = [];
  for (const [h, label] of Object.entries(HEALTH_LABELS)) {
    if (counts[h]) parts.push(`${counts[h]} ${label.toLowerCase()}`);
  }
  summary.textContent = `${parts.join(", ")} (${enrolled.length} total)`;
}

function renderActivity(container, enrolled) {
  if (!enrolled || enrolled.length === 0) {
    container.innerHTML =
      `<p style="color:#888">No sync activity yet.</p>`;
    return;
  }

  // Sort by last_written descending, filter to those with a timestamp
  const withTime = enrolled
    .filter(m => m.last_written)
    .sort((a, b) => new Date(b.last_written) - new Date(a.last_written))
    .slice(0, 5);

  if (withTime.length === 0) {
    container.innerHTML =
      `<p style="color:#888">No sync activity yet.</p>`;
    return;
  }

  container.innerHTML = withTime.map(m =>
    `<div class="activity-item">
      <span class="map-name">${esc(m.name)}</span>
      <span class="activity-time">${timeAgo(m.last_written)}</span>
    </div>`
  ).join("");
}

function renderChainStatus(container, chains) {
  if (!container) return;
  if (!chains || chains.length === 0) {
    container.innerHTML = `<p style="color:#888">No script chains. <a href="#/chains" style="color:var(--accent,#d4a017)">Create one</a> to link scripts into sequences.</p>`;
    return;
  }

  container.innerHTML = chains.map(c => {
    const syncDot = c.synced_at
      ? `<span class="chain-sync-dot chain-sync-ok" title="Synced: ${esc(c.synced_at)}"></span>`
      : `<span class="chain-sync-dot chain-sync-stale" title="Not synced"></span>`;
    const maps = esc((c.maps || []).join(", "));
    return `<div class="dash-chain-item">
      ${syncDot}
      <a href="#/chains/${esc(c.name)}" class="dash-chain-name">${esc(c.name)}</a>
      <span class="dash-chain-meta">${c.script_count} scripts &middot; ${maps}</span>
    </div>`;
  }).join("");
}

function parseBackupDate(dateStr) {
  if (!dateStr || dateStr.length !== 8) return null;
  const y = dateStr.slice(0, 4);
  const m = dateStr.slice(4, 6);
  const d = dateStr.slice(6, 8);
  const iso = `${y}-${m}-${d}T00:00:00`;
  const parsed = new Date(iso);
  if (isNaN(parsed.getTime())) return null;
  return parsed.toISOString();
}

function renderBackupSummary(container, backups) {
  if (!backups || backups.length === 0) {
    container.innerHTML = `<span class="backup-info">No backups yet.</span>
      <button class="dash-backup-btn">Backup Now</button>`;
    return;
  }

  const latest = backups[0];
  const ago = timeAgo(parseBackupDate(latest.date));
  const size = latest.size_mb != null ? ` ${latest.size_mb.toFixed(1)} MB` : "";
  const ver = latest.version ? `v${esc(latest.version)}` : esc(latest.filename);

  container.innerHTML = `<span class="backup-info">${backups.length} backup${backups.length !== 1 ? "s" : ""} &mdash; latest: ${ver} (${esc(ago)}${size ? "," + size : ""})</span>
    <button class="dash-backup-btn">Backup Now</button>`;
}

function renderDownloadPanel(panel, listEl, data) {
  const builds = data.builds || [];
  panel.style.display = "";
  listEl.innerHTML = builds.map(b => {
    if (!b.available) {
      return `<div class="dl-row dl-unavailable">
        <div class="dl-row-info">
          <span class="dl-label">${esc(b.label)}</span>
          <span class="dl-meta">Not built yet</span>
        </div>
      </div>`;
    }
    const modified = new Date(b.modified);
    const ts = modified.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })
             + " " + modified.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
    return `<div class="dl-row">
      <div class="dl-row-info">
        <span class="dl-label">${esc(b.label)}</span>
        <span class="dl-meta">${esc(b.filename)} &middot; ${b.size_mb} MB &middot; ${esc(ts)}</span>
      </div>
      <a class="dl-btn" href="/api/download/rom?variant=${esc(b.variant)}" title="Download ${esc(b.filename)}">Download</a>
    </div>`;
  }).join("");
}

async function handleBackupClick(btn, summaryEl) {
  btn.disabled = true;
  const origLabel = btn.textContent;
  btn.textContent = "Creating...";
  try {
    const res = await postApi("/project/backups/create", {});
    if (res.ok) {
      // Re-fetch backup list
      const listRes = await api("/project/backups");
      if (listRes.ok) renderBackupSummary(summaryEl, listRes.data.backups || []);
      // Flash success on the new button
      const newBtn = summaryEl.querySelector(".dash-backup-btn");
      if (newBtn) {
        newBtn.textContent = "Created!";
        newBtn.disabled = true;
        setTimeout(() => { newBtn.textContent = origLabel; newBtn.disabled = false; }, 2000);
      }
    } else {
      btn.textContent = res.error || "Failed";
      setTimeout(() => { btn.textContent = origLabel; btn.disabled = false; }, 2000);
    }
  } catch (_) {
    btn.textContent = "Error";
    setTimeout(() => { btn.textContent = origLabel; btn.disabled = false; }, 2000);
  }
}

// Track listeners added to the global SSE so cleanup can remove them
let _sseListeners = [];

function _addSSE(event, fn) {
  const es = getEventSource();
  es.addEventListener(event, fn);
  _sseListeners.push([event, fn]);
}

function connectSSE(buildBtns, buildWrap, buildLog, buildStatus, buildProgress,
                    buildProgressFill, attentionContent, healthGrid,
                    healthSummary, activityList) {
  _addSSE("build_start", (e) => {
    buildWrap.style.display = "";
    buildLog.textContent = "";
    buildLineCount = 0;
    buildProgress.style.display = "";
    buildProgressFill.style.width = "0%";
    buildProgressFill.classList.remove("indeterminate", "complete", "failed");
    let devMode = false;
    try { devMode = JSON.parse(e.data).dev_mode; } catch (_) {}
    buildStatus.textContent = devMode ? "Dev building..." : "Building...";
    buildStatus.className = "build-status building";
    buildBtns.forEach(b => b.disabled = true);
    const lastLines = parseInt(localStorage.getItem(LAST_BUILD_LINES_KEY), 10);
    if (!lastLines) buildProgressFill.classList.add("indeterminate");
  });

  _addSSE("build_output", (e) => {
    try {
      const d = JSON.parse(e.data);
      buildLog.textContent += d.line + "\n";
      buildLog.scrollTop = buildLog.scrollHeight;
      buildLineCount++;
      const lastLines = parseInt(localStorage.getItem(LAST_BUILD_LINES_KEY), 10);
      if (lastLines > 0) {
        const pct = Math.min(98, (buildLineCount / lastLines) * 100);
        buildProgressFill.style.width = pct + "%";
        buildProgressFill.classList.remove("indeterminate");
      }
    } catch (_) {}
  });

  _addSSE("build_complete", (e) => {
    try {
      const d = JSON.parse(e.data);
      localStorage.setItem(LAST_BUILD_LINES_KEY, String(buildLineCount));
      buildProgressFill.style.width = "100%";
      buildProgressFill.classList.remove("indeterminate");
      if (d.success) {
        buildStatus.textContent = "Build successful";
        buildStatus.className = "build-status success";
        buildProgressFill.classList.add("complete");
      } else {
        buildStatus.textContent = `Build failed (exit code ${d.exit_code})`;
        buildStatus.className = "build-status failure";
        buildProgressFill.classList.add("failed");
      }
    } catch (_) {
      buildStatus.textContent = "Build finished";
      buildStatus.className = "build-status";
    }
    buildBtns.forEach(b => b.disabled = false);
    // Refresh download panel after build
    const dlPanel = document.querySelector(".dash-download-panel");
    const dlList = document.querySelector(".dash-download-list");
    if (dlPanel && dlList) {
      api("/download/rom/info").then(res => {
        if (res.ok) renderDownloadPanel(dlPanel, dlList, res.data);
      }).catch(() => {});
    }
  });

  // Sync SSE events
  _addSSE("sync_start", (e) => {
    try {
      const d = JSON.parse(e.data);
      const syncBtn = document.querySelector(".sync-btn");
      if (syncBtn) syncBtn.textContent = `Syncing ${d.map}...`;
    } catch (_) {}
  });

  _addSSE("sync_complete", (e) => {
    try {
      const d = JSON.parse(e.data);
      // Update sync button with per-map progress
      const syncBtn = document.querySelector(".sync-btn");
      if (syncBtn) {
        syncBtn.textContent = d.success
          ? `Synced ${d.map}`
          : `Failed: ${d.map}`;
      }
    } catch (_) {}
  });

  _addSSE("sync_all_done", () => {
    // Refresh attention section, health grid, and activity after all syncs
    setTimeout(async () => {
      try {
        const [attRes, mapsRes] = await Promise.all([
          api("/maps/attention"),
          api("/maps"),
        ]);
        if (attRes.ok && attentionContent) {
          renderAttention(attentionContent, attRes.data);
        }
        if (mapsRes.ok) {
          if (healthGrid && healthSummary) {
            renderHealthGrid(healthGrid, healthSummary, mapsRes.data.enrolled);
          }
          if (activityList) {
            renderActivity(activityList, mapsRes.data.enrolled);
          }
        }
      } catch (_) {}
    }, 500);
  });
}

export function cleanup() {
  // Remove this view's SSE listeners without closing the shared connection
  const es = getEventSource();
  for (const [event, fn] of _sseListeners) {
    es.removeEventListener(event, fn);
  }
  _sseListeners = [];
  buildLineCount = 0;
}
