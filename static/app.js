(function () {
  "use strict";

  const socket = io();

  const $ = (id) => document.getElementById(id);
  const statusDevice = $("status-device");
  const statusMode = $("status-mode");
  const statusBands = $("status-bands");
  const statusCenter = $("status-center");
  const statusFloorPeak = $("status-floor-peak");
  const statusMinFloor = $("status-min-floor");
  const statusSlice = $("status-slice");
  const statusError = $("status-error");
  const rtlDevice = $("rtl-device");
  const rtlCount = $("rtl-count");
  const rtlError = $("rtl-error");
  const hackrfSpectrumCanvas = $("hackrf-spectrum-canvas");
  const panelHackrf = $("panel-hackrf");
  const detectionsList = $("detections-list");
  const planesList = $("planes-list");
  const mapContainer = $("map-container");
  const adsbInput = $("adsb-input");
  const adsbSubmit = $("adsb-submit");
  const adsbList = $("adsb-list");
  const wsStatus = $("ws-status");

  let adsbLines = [];
  let planeDetections = [];  // current plane state by ICAO (for map)
  let firstSeenPlanes = {};  // ICAO -> plane (first-seen log for list; one row per ICAO)
  let map = null;
  let planeMarkers = {};
  let planePolylines = {};
  let planePaths = {};       // key -> [[lat,lon], ...] persistent, max TRACK_POINTS
  const TRACK_POINTS = 50;
  const MAX_FIRST_SEEN = 100;

  function normIcao(icao) {
    const s = (icao != null && icao !== "") ? String(icao).trim() : "";
    return s ? s.toUpperCase() : "";
  }

  function planeKey(p) {
    const icao = normIcao(p.icao);
    return icao || (p.lat != null && p.lon != null ? "pos_" + p.lat.toFixed(5) + "_" + p.lon.toFixed(5) : null);
  }

  function bearingDegrees(lat0, lon0, lat1, lon1) {
    const dLon = (lon1 - lon0) * Math.PI / 180;
    const lat0r = lat0 * Math.PI / 180, lat1r = lat1 * Math.PI / 180;
    const y = Math.sin(dLon) * Math.cos(lat1r);
    const x = Math.cos(lat0r) * Math.sin(lat1r) - Math.sin(lat0r) * Math.cos(lat1r) * Math.cos(dLon);
    let br = Math.atan2(y, x) * 180 / Math.PI;
    return (br + 360) % 360;
  }

  function haversineMeters(lat1, lon1, lat2, lon2) {
    const R = 6371000;
    const dLat = (lat2 - lat1) * Math.PI / 180;
    const dLon = (lon2 - lon1) * Math.PI / 180;
    const a = Math.sin(dLat/2)*Math.sin(dLat/2) +
              Math.cos(lat1*Math.PI/180)*Math.cos(lat2*Math.PI/180)*Math.sin(dLon/2)*Math.sin(dLon/2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
    return R * c;
  }

  function computeGroundSpeedKnots(path, windowSec) {
    if (!path || path.length < 2) return null;
    windowSec = windowSec != null ? windowSec : 10;
    const now = path[path.length - 1].ts;
    const cutoff = now - windowSec;
    const window = path.filter((pt) => pt.ts >= cutoff);
    if (window.length < 2) return null;
    let distanceM = 0;
    for (let i = 1; i < window.length; i++) {
      distanceM += haversineMeters(window[i-1].lat, window[i-1].lon, window[i].lat, window[i].lon);
    }
    const elapsed = window[window.length - 1].ts - window[0].ts;
    if (elapsed < 0.5) return null;
    const speedMs = distanceM / elapsed;
    return speedMs * 1.94384;
  }

  // Saves panel (collapsible)
  const savesToggle = $("saves-toggle");
  const savesPanel = $("saves-panel");
  const savesClose = $("saves-close");
  const saveNameInput = $("save-name");
  const saveBtn = $("save-btn");
  const savesListEl = $("saves-list");
  const savesMessageEl = $("saves-message");
  const savesLoadMergeBtn = $("saves-load-merge");
  const savesLoadReplaceBtn = $("saves-load-replace");
  const savesDeleteBtn = $("saves-delete");
  const settingsBtn = $("settings-btn");
  const settingsOverlay = $("settings-overlay");
  const settingsBackdrop = $("settings-backdrop");
  const settingsCloseBtn = $("settings-close");
  const settingsSaveBtn = $("settings-save");
  const settingsResetBtn = $("settings-reset");
  const settingDarkTheme = $("setting-dark-theme");

  const SETTINGS_KEY = "skyhunter_settings";
  const DEFAULT_SETTINGS = { darkTheme: true };

  let selectedSaveName = null;

  function getStoredSettings() {
    try {
      const raw = localStorage.getItem(SETTINGS_KEY);
      if (!raw) return Object.assign({}, DEFAULT_SETTINGS);
      const parsed = JSON.parse(raw);
      return Object.assign({}, DEFAULT_SETTINGS, parsed);
    } catch (_) {
      return Object.assign({}, DEFAULT_SETTINGS);
    }
  }

  function applyTheme(settings) {
    const dark = settings.darkTheme !== false;
    document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
  }

  function openSettingsModal() {
    if (!settingsOverlay) return;
    loadSettingsIntoForm(getStoredSettings());
    settingsOverlay.classList.add("open");
    settingsOverlay.setAttribute("aria-hidden", "false");
  }

  function closeSettingsModal() {
    if (!settingsOverlay) return;
    settingsOverlay.classList.remove("open");
    settingsOverlay.setAttribute("aria-hidden", "true");
  }

  function loadSettingsIntoForm(settings) {
    if (settingDarkTheme) settingDarkTheme.checked = settings.darkTheme !== false;
  }

  function getSettingsFromForm() {
    return {
      darkTheme: settingDarkTheme ? settingDarkTheme.checked : DEFAULT_SETTINGS.darkTheme,
    };
  }

  function saveSettings() {
    const settings = getSettingsFromForm();
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
      applyTheme(settings);
      closeSettingsModal();
    } catch (e) {
      alert("Could not save settings.");
    }
  }

  function resetSettingsToDefaults() {
    loadSettingsIntoForm(DEFAULT_SETTINGS);
  }

  function openSavesPanel() {
    if (savesPanel) {
      savesPanel.classList.add("open");
      savesPanel.setAttribute("aria-hidden", "false");
      document.body.classList.add("saves-panel-open");
      selectedSaveName = null;
      refreshSavesList();
      updateSavesButtons();
      showSavesMessage("", false);
    }
  }

  function closeSavesPanel() {
    if (savesPanel) {
      savesPanel.classList.remove("open");
      savesPanel.setAttribute("aria-hidden", "true");
      document.body.classList.remove("saves-panel-open");
    }
  }

  function showSavesMessage(text, isError) {
    if (!savesMessageEl) return;
    savesMessageEl.textContent = text;
    savesMessageEl.className = "saves-message" + (isError ? " saves-message-error" : text ? " saves-message-ok" : "");
    if (text) {
      clearTimeout(showSavesMessage._tid);
      showSavesMessage._tid = setTimeout(() => showSavesMessage("", false), 4000);
    }
  }

  function updateSavesButtons() {
    const hasSelection = !!selectedSaveName;
    if (savesLoadMergeBtn) savesLoadMergeBtn.disabled = !hasSelection;
    if (savesLoadReplaceBtn) savesLoadReplaceBtn.disabled = !hasSelection;
    if (savesDeleteBtn) savesDeleteBtn.disabled = !hasSelection;
  }

  if (savesToggle) savesToggle.addEventListener("click", openSavesPanel);
  if (savesClose) savesClose.addEventListener("click", closeSavesPanel);

  function refreshSavesList() {
    if (!savesListEl) return;
    fetch("/api/saves")
      .then((r) => r.json())
      .then((arr) => {
        savesListEl.innerHTML = "";
        (arr || []).forEach((s) => {
          const div = document.createElement("div");
          div.className = "saves-list-item" + (selectedSaveName === s.name ? " selected" : "");
          div.setAttribute("role", "option");
          div.setAttribute("data-name", s.name || "");
          const dateStr = s.saved_at ? new Date(s.saved_at * 1000).toLocaleString() : "";
          div.innerHTML = "<span class=\"saves-list-item-name\">" + (s.name || "unnamed") + "</span><br><span class=\"saves-list-date\">" + dateStr + "</span>";
          div.addEventListener("click", () => {
            selectedSaveName = s.name || null;
            savesListEl.querySelectorAll(".saves-list-item").forEach((el) => el.classList.remove("selected"));
            div.classList.add("selected");
            updateSavesButtons();
          });
          savesListEl.appendChild(div);
        });
        if ((arr || []).length === 0) {
          const empty = document.createElement("div");
          empty.className = "saves-list-empty";
          empty.textContent = "No saved sessions yet. Save a session above.";
          savesListEl.appendChild(empty);
        }
      })
      .catch(() => showSavesMessage("Failed to load saves list.", true));
  }

  if (saveBtn && saveNameInput) {
    saveBtn.addEventListener("click", () => {
      const name = saveNameInput.value.trim() || "scan_" + new Date().toISOString().slice(0, 10);
      fetch("/api/saves", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name }),
      })
        .then((r) => r.json())
        .then((data) => {
          if (data.ok) {
            saveNameInput.value = name;
            selectedSaveName = name;
            refreshSavesList();
            updateSavesButtons();
            showSavesMessage("Saved as \"" + name + "\".", false);
          } else {
            showSavesMessage(data.error || "Save failed.", true);
          }
        })
        .catch(() => showSavesMessage("Save failed.", true));
    });
  }

  function doLoad(merge) {
    if (!selectedSaveName) return;
    fetch("/api/saves/load", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: selectedSaveName, merge: merge }),
    })
      .then((r) => r.json())
      .then((data) => {
        if (data.ok) {
          showSavesMessage(merge ? "Merged \"" + selectedSaveName + "\" into current session." : "Replaced session with \"" + selectedSaveName + "\".", false);
          refreshSavesList();
        } else {
          showSavesMessage(data.error || "Load failed.", true);
        }
      })
      .catch(() => showSavesMessage("Load failed.", true));
  }

  if (savesLoadMergeBtn) savesLoadMergeBtn.addEventListener("click", () => doLoad(true));
  if (savesLoadReplaceBtn) savesLoadReplaceBtn.addEventListener("click", () => doLoad(false));

  if (savesDeleteBtn) {
    savesDeleteBtn.addEventListener("click", () => {
      if (!selectedSaveName) return;
      if (!confirm("Delete save \"" + selectedSaveName + "\"?")) return;
      fetch("/api/saves/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: selectedSaveName }),
      })
        .then((r) => r.json())
        .then((data) => {
          if (data.ok) {
            selectedSaveName = null;
            refreshSavesList();
            updateSavesButtons();
            showSavesMessage("Deleted \"" + data.name + "\".", false);
          } else {
            showSavesMessage(data.error || "Delete failed.", true);
          }
        })
        .catch(() => showSavesMessage("Delete failed.", true));
    });
  }

  if (settingsBtn) settingsBtn.addEventListener("click", openSettingsModal);
  if (settingsCloseBtn) settingsCloseBtn.addEventListener("click", closeSettingsModal);
  if (settingsBackdrop) settingsBackdrop.addEventListener("click", closeSettingsModal);
  if (settingsSaveBtn) settingsSaveBtn.addEventListener("click", saveSettings);
  if (settingsResetBtn) settingsResetBtn.addEventListener("click", resetSettingsToDefaults);

  if (settingDarkTheme) {
    settingDarkTheme.addEventListener("change", () => {
      applyTheme(getSettingsFromForm());
    });
  }

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && settingsOverlay && settingsOverlay.classList.contains("open")) {
      closeSettingsModal();
    }
  });

  applyTheme(getStoredSettings());

  // HackRF tab: fast poll for spectrum + device stats
  let hackrfPollId = null;

  function updateHackrfPanel(data) {
    if (!data) return;
    const set = (id, text, className) => {
      const el = document.getElementById(id);
      if (!el) return;
      el.textContent = text;
      if (className !== undefined) el.className = className;
    };
    set("hackrf-status-device", data.device === "ok" ? "OK" : data.device === "error" ? "Error" : "—", "value status-badge " + (data.device === "ok" ? "ok" : data.device === "error" ? "error" : "pending"));
    set("hackrf-status-mode", data.mode || "—");
    set("hackrf-status-bands", Array.isArray(data.bands) ? data.bands.map((b) => b[0] + "–" + b[1]).join(", ") : "—");
    set("hackrf-status-center", data.center_mhz != null ? data.center_mhz.toFixed(3) + " MHz" : "—");
    set("hackrf-status-floor-peak", data.floor_db != null && data.peak_db != null ? data.floor_db.toFixed(1) + " / " + data.peak_db.toFixed(1) : "—");
    set("hackrf-status-min-floor", data.min_floor_db != null ? data.min_floor_db.toFixed(1) : "—");
    set("hackrf-status-slice", Array.isArray(data.slice_mhz) ? data.slice_mhz[0].toFixed(3) + " .. " + data.slice_mhz[1].toFixed(3) : "—");
    set("hackrf-status-error", data.error || "—");
    if (Array.isArray(data.spectrum_freq_mhz) && Array.isArray(data.spectrum_db) && hackrfSpectrumCanvas) {
      drawSpectrum(hackrfSpectrumCanvas, data.spectrum_freq_mhz, data.spectrum_db);
    }
  }

  function drawSpectrum(canvas, freqMhz, db) {
    if (!canvas || !freqMhz || !freqMhz.length || !db || db.length !== freqMhz.length) return;
    const ctx = canvas.getContext("2d");
    const w = canvas.width;
    const h = canvas.height;
    const padding = { top: 20, right: 20, bottom: 32, left: 52 };
    const plotW = w - padding.left - padding.right;
    const plotH = h - padding.top - padding.bottom;
    const minF = Math.min.apply(null, freqMhz);
    const maxF = Math.max.apply(null, freqMhz);
    const minDb = Math.min.apply(null, db);
    const maxDb = Math.max.apply(null, db);
    const rangeDb = maxDb - minDb || 1;
    const padDb = rangeDb * 0.05;
    const dbLo = minDb - padDb;
    const dbHi = maxDb + padDb;
    ctx.fillStyle = "#0f1117";
    ctx.fillRect(0, 0, w, h);
    ctx.strokeStyle = "#1e2330";
    ctx.lineWidth = 1;
    ctx.strokeRect(padding.left, padding.top, plotW, plotH);
    ctx.fillStyle = "#7a8194";
    ctx.font = "11px JetBrains Mono, monospace";
    ctx.textAlign = "right";
    ctx.fillText(minF.toFixed(2) + " MHz", padding.left - 6, h - 8);
    ctx.textAlign = "left";
    ctx.fillText(maxF.toFixed(2) + " MHz", padding.left + plotW + 6, h - 8);
    ctx.textAlign = "right";
    ctx.fillText(dbHi.toFixed(0) + " dB", padding.left - 6, padding.top + 12);
    ctx.fillText(dbLo.toFixed(0) + " dB", padding.left - 6, padding.top + plotH - 2);
    const x = (f) => padding.left + ((f - minF) / (maxF - minF || 1)) * plotW;
    const y = (d) => padding.top + plotH - ((d - dbLo) / (dbHi - dbLo)) * plotH;
    ctx.beginPath();
    ctx.moveTo(x(freqMhz[0]), y(db[0]));
    for (let i = 1; i < freqMhz.length; i++) {
      ctx.lineTo(x(freqMhz[i]), y(db[i]));
    }
    ctx.strokeStyle = "#4a7fc7";
    ctx.lineWidth = 1.5;
    ctx.stroke();
    const grad = ctx.createLinearGradient(0, padding.top, 0, padding.top + plotH);
    grad.addColorStop(0, "rgba(74, 127, 199, 0.35)");
    grad.addColorStop(1, "rgba(74, 127, 199, 0)");
    ctx.lineTo(x(freqMhz[freqMhz.length - 1]), padding.top + plotH);
    ctx.lineTo(x(freqMhz[0]), padding.top + plotH);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();
  }

  // Tabs
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
      document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
      tab.classList.add("active");
      const panel = document.getElementById("panel-" + tab.dataset.tab);
      if (panel) panel.classList.add("active");
      if (tab.dataset.tab === "detections" && mapContainer) {
        setTimeout(function () {
          initMap();
          if (map) {
            map.invalidateSize();
            updateMapMarkers(planeDetections);
          }
        }, 150);
      }
      if (tab.dataset.tab === "hackrf") {
        if (hackrfPollId) clearInterval(hackrfPollId);
        hackrfPollId = setInterval(() => {
          if (!panelHackrf || !panelHackrf.classList.contains("active")) return;
          fetch("/api/status")
            .then((r) => r.json())
            .then(updateHackrfPanel)
            .catch(() => {});
        }, 200);
        fetch("/api/status").then((r) => r.json()).then(updateHackrfPanel).catch(() => {});
      } else {
        if (hackrfPollId) {
          clearInterval(hackrfPollId);
          hackrfPollId = null;
        }
      }
    });
  });

  function formatTime(ts) {
    if (ts == null) return "—";
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString("en-GB", { hour12: false });
  }

  function detectionClass(label) {
    if (!label) return "unknown";
    const s = (label + "").toLowerCase();
    if (s.includes("fpv")) return "fpv";
    if (s.includes("dji")) return "dji";
    if (s.includes("signal")) return "signal";
    return "unknown";
  }

  function detectionIcon(label) {
    const c = detectionClass(label);
    if (c === "fpv") return "⌂";  // antenna / analog
    if (c === "dji") return "◆";  // drone / digital
    return "◇";
  }

  function displayLabel(label) {
    if (!label) return "UNKNOWN";
    const s = (label + "").toLowerCase();
    if (s.includes("fpv")) return "FPV";
    if (s.includes("dji")) return "DJI";
    if (s.includes("signal")) return "UNKNOWN";
    return label;
  }

  function renderDetection(d) {
    const cls = detectionClass(d.label);
    const icon = detectionIcon(d.label);
    const labelText = displayLabel(d.label);
    const freq = d.center_mhz != null ? d.center_mhz.toFixed(3) + " MHz" : "—";
    const width = d.width_mhz != null ? "~" + d.width_mhz.toFixed(1) + " MHz" : "";
    const detail = [freq, width].filter(Boolean).join(" · ");
    const timeStr = formatTime(d.ts);
    const div = document.createElement("div");
    div.className = "detection-item " + cls;
    div.innerHTML =
      '<div class="detection-icon">' + icon + "</div>" +
      '<div class="detection-body">' +
      '<div class="detection-label">' + labelText + "</div>" +
      '<div class="detection-detail">' + detail + "</div>" +
      "</div>" +
      '<div class="detection-time">' + timeStr + "</div>";
    return div;
  }

  function addDetection(data) {
    const el = renderDetection(data);
    detectionsList.insertBefore(el, detectionsList.firstChild);
    // Keep last N in DOM
    while (detectionsList.children.length > 200) detectionsList.removeChild(detectionsList.lastChild);
  }

  socket.on("connect", () => {
    wsStatus.textContent = "Connected";
    wsStatus.classList.add("connected");
    wsStatus.classList.remove("disconnected");
  });

  socket.on("disconnect", () => {
    wsStatus.textContent = "Disconnected";
    wsStatus.classList.remove("connected");
    wsStatus.classList.add("disconnected");
  });

  function updateRtlStatus(rtl) {
    if (!rtl) return;
    const dev = rtl.device || "—";
    const labels = {
      receiving_data: "Receiving data",
      connected_no_data: "Connected / No data yet",
      starting: "Starting",
      not_running: "Not running",
      port_closed: "Port closed",
      running_waiting_for_port: "Running / Waiting for port",
      process_exited: "Process exited",
      error: "Error",
      ok: "Connected",
      no_data: "No data",
      not_detected: "Not detected"
    };
    const devText = labels[dev] || dev;
    const okStates = ["ok", "receiving_data"];
    const pendingStates = ["no_data", "connected_no_data", "starting", "running_waiting_for_port"];
    const errorStates = ["error", "port_closed", "process_exited"];
    let badgeClass = "value status-badge not_detected";
    if (okStates.includes(dev)) badgeClass = "value status-badge ok";
    else if (pendingStates.includes(dev)) badgeClass = "value status-badge pending";
    else if (errorStates.includes(dev)) badgeClass = "value status-badge error";
    if (rtlDevice) {
      rtlDevice.textContent = devText;
      rtlDevice.className = badgeClass;
    }
    if (rtlCount) rtlCount.textContent = rtl.count != null ? String(rtl.count) : "—";
    if (rtlError) rtlError.textContent = rtl.error || "—";
    const adsbSdrDevice = $("adsb-sdr-device");
    const adsbSdrCount = $("adsb-sdr-count");
    const adsbSdrError = $("adsb-sdr-error");
    if (adsbSdrDevice) {
      adsbSdrDevice.textContent = devText;
      adsbSdrDevice.className = badgeClass;
    }
    if (adsbSdrCount) adsbSdrCount.textContent = rtl.count != null ? String(rtl.count) : "—";
    if (adsbSdrError) adsbSdrError.textContent = rtl.error || "—";
  }

  socket.on("status", (data) => {
    if (!data) return;
    statusDevice.textContent = data.device === "ok" ? "OK" : data.device === "error" ? "Error" : "—";
    statusDevice.className = "value status-badge " + (data.device === "ok" ? "ok" : data.device === "error" ? "error" : "pending");
    statusMode.textContent = data.mode || "—";
    statusBands.textContent = Array.isArray(data.bands)
      ? data.bands.map((b) => b[0] + "–" + b[1]).join(", ")
      : "—";
    statusCenter.textContent = data.center_mhz != null ? data.center_mhz.toFixed(3) + " MHz" : "—";
    statusFloorPeak.textContent =
      data.floor_db != null && data.peak_db != null
        ? data.floor_db.toFixed(1) + " / " + data.peak_db.toFixed(1)
        : "—";
    statusMinFloor.textContent = data.min_floor_db != null ? data.min_floor_db.toFixed(1) : "—";
    statusSlice.textContent = Array.isArray(data.slice_mhz)
      ? data.slice_mhz[0].toFixed(3) + " .. " + data.slice_mhz[1].toFixed(3)
      : "—";
    statusError.textContent = data.error || "—";
    if (data.rtl_status) updateRtlStatus(data.rtl_status);
    if (panelHackrf && panelHackrf.classList.contains("active")) updateHackrfPanel(data);
  });

  socket.on("alert", (data) => {
    addDetection(data);
  });

  socket.on("detections_snapshot", (arr) => {
    if (!Array.isArray(arr)) return;
    detectionsList.innerHTML = "";
    [...arr].reverse().forEach((d) => detectionsList.appendChild(renderDetection(d)));
  });

  function initMap() {
    if (map || !mapContainer) return;
    map = L.map(mapContainer, { scrollWheelZoom: true }).setView([39.5, -98.5], 4);
    // Tiles: server serves cache under static/map-tiles; fetches OSM on miss and saves for offline.
    L.tileLayer("/api/map-tile/{z}/{x}/{y}.png", {
      attribution: "&copy; <a href=\"https://www.openstreetmap.org/copyright\">OpenStreetMap</a>",
      maxZoom: 19,
      minZoom: 0,
    }).addTo(map);
  }

  function planeIcon(bearingDeg) {
    // bearingDeg = 0 north, 90 east (degrees from north). Default ✈ points right (east) so rotation = bearing - 90.
    const deg = bearingDeg != null && !isNaN(bearingDeg) ? bearingDeg - 90 : -90;
    return L.divIcon({
      className: "plane-marker-icon",
      html: "<div class=\"plane-marker\" style=\"transform: rotate(" + deg + "deg)\" aria-hidden=\"true\">✈</div>",
      iconSize: [28, 28],
      iconAnchor: [14, 14],
    });
  }

  function popupContent(p) {
    const icao = (p.icao || "—").toString();
    const flight = (p.flight || "—").toString();
    const manufacturer = (p.manufacturer || "—").toString();
    const model = (p.model || "—").toString();
    const operator = (p.operator || "—").toString();
    const alt = p.altitude != null ? p.altitude + " ft" : "—";
    const headingStr = (p.computedHeading != null && !isNaN(p.computedHeading))
      ? (p.computedHeading.toFixed(0) + "°") : "—";
    const groundSpeedStr = (p.computedGroundSpeedKnots != null && !isNaN(p.computedGroundSpeedKnots))
      ? (p.computedGroundSpeedKnots.toFixed(0) + " kt") : "—";
    const lat = p.lat != null ? p.lat.toFixed(5) : "—";
    const lon = p.lon != null ? p.lon.toFixed(5) : "—";
    const ts = p.ts != null ? (function () {
      const s = Math.max(0, Math.floor(Date.now() / 1000 - p.ts));
      return s < 60 ? s + " s ago" : Math.floor(s / 60) + " min ago";
    })() : "—";
    return "<div class=\"plane-popup\">" +
      "<div class=\"plane-popup-row\"><span class=\"plane-popup-label\">ICAO</span> " + icao + "</div>" +
      "<div class=\"plane-popup-row\"><span class=\"plane-popup-label\">Callsign</span> " + flight + "</div>" +
      "<div class=\"plane-popup-row\"><span class=\"plane-popup-label\">Manufacturer</span> " + manufacturer + "</div>" +
      "<div class=\"plane-popup-row\"><span class=\"plane-popup-label\">Model</span> " + model + "</div>" +
      "<div class=\"plane-popup-row\"><span class=\"plane-popup-label\">Operator</span> " + operator + "</div>" +
      "<div class=\"plane-popup-row\"><span class=\"plane-popup-label\">Altitude</span> " + alt + "</div>" +
      "<div class=\"plane-popup-row\"><span class=\"plane-popup-label\">Heading</span> " + headingStr + "</div>" +
      "<div class=\"plane-popup-row\"><span class=\"plane-popup-label\">Ground speed</span> " + groundSpeedStr + "</div>" +
      "<div class=\"plane-popup-row\"><span class=\"plane-popup-label\">Lat / Lon</span> " + lat + ", " + lon + "</div>" +
      "<div class=\"plane-popup-row\"><span class=\"plane-popup-label\">Last seen</span> " + ts + "</div>" +
      "</div>";
  }

  function updateMapMarkers(planes) {
    if (!map) initMap();
    if (!map) return;
    const seen = new Set();
    (planes || []).forEach((p) => {
      const lat = p.lat;
      const lon = p.lon;
      if (lat == null || lon == null) return;
      const key = planeKey(p);
      if (!key) return;
      seen.add(key);
      // Persistent path: [{ lat, lon, ts }, ...], ts in seconds. Append only if different from last point.
      if (!planePaths[key]) planePaths[key] = [];
      const path = planePaths[key];
      const ts = p.ts != null ? p.ts : Date.now() / 1000;
      const last = path.length ? path[path.length - 1] : null;
      if (!last || last.lat !== lat || last.lon !== lon) {
        path.push({ lat: lat, lon: lon, ts: ts });
        if (path.length > TRACK_POINTS) path.shift();
      }
      const pathLatLngs = path.map(function (pt) { return [pt.lat, pt.lon]; });
      if (!planePolylines[key]) {
        planePolylines[key] = L.polyline(pathLatLngs, { color: "#4a7fc7", weight: 2, opacity: 0.7 }).addTo(map);
      } else {
        planePolylines[key].setLatLngs(pathLatLngs);
      }
      // Heading: from trail (last segment) if >= 2 points, else SBS track, else 0 (north). 0/360=north, 90=east.
      let bearing = null;
      if (path.length >= 2) {
        const a = path[path.length - 2];
        const b = path[path.length - 1];
        bearing = bearingDegrees(a.lat, a.lon, b.lat, b.lon);
      }
      if (bearing == null && p.track != null && !isNaN(p.track)) bearing = p.track;
      if (bearing == null) bearing = 0;
      const computedGroundSpeedKnots = computeGroundSpeedKnots(path, 10);
      const pDisplay = Object.assign({}, p, { computedHeading: bearing, computedGroundSpeedKnots: computedGroundSpeedKnots });
      if (!planeMarkers[key]) {
        const m = L.marker([lat, lon], { icon: planeIcon(bearing) }).addTo(map);
        m.bindPopup(popupContent(pDisplay), { maxWidth: 280 });
        m._planeData = pDisplay;
        planeMarkers[key] = m;
      } else {
        const m = planeMarkers[key];
        m.setLatLng([lat, lon]);
        m.setIcon(planeIcon(bearing));
        m.setPopupContent(popupContent(pDisplay));
        m._planeData = pDisplay;
      }
    });
    Object.keys(planeMarkers).forEach((k) => {
      if (!seen.has(k)) {
        map.removeLayer(planeMarkers[k]);
        delete planeMarkers[k];
        if (planePolylines[k]) {
          map.removeLayer(planePolylines[k]);
          delete planePolylines[k];
        }
        delete planePaths[k];
      }
    });
  }

  function updateFirstSeen(plane) {
    const icao = normIcao(plane.icao);
    if (!icao) return;
    if (!firstSeenPlanes[icao]) {
      firstSeenPlanes[icao] = Object.assign({}, plane, { firstSeenTs: Date.now() / 1000 });
    } else {
      firstSeenPlanes[icao] = Object.assign({}, firstSeenPlanes[icao], plane);
    }
    const keys = Object.keys(firstSeenPlanes);
    if (keys.length > MAX_FIRST_SEEN) {
      const byFirst = keys.sort((a, b) => (firstSeenPlanes[a].firstSeenTs || 0) - (firstSeenPlanes[b].firstSeenTs || 0));
      byFirst.slice(0, keys.length - MAX_FIRST_SEEN).forEach((k) => delete firstSeenPlanes[k]);
    }
  }

  function renderPlanesList() {
    planesList.innerHTML = "";
    const list = Object.values(firstSeenPlanes)
      .sort((a, b) => (b.firstSeenTs || 0) - (a.firstSeenTs || 0))
      .slice(0, MAX_FIRST_SEEN);
    list.forEach((p) => {
      const div = document.createElement("div");
      div.className = "plane-item";
      const icao = p.icao || "—";
      const flight = p.flight ? " " + p.flight : "";
      const alt = p.altitude != null ? " · " + p.altitude + " ft" : "";
      const pos = p.lat != null && p.lon != null ? " " + p.lat.toFixed(4) + ", " + p.lon.toFixed(4) : "";
      div.innerHTML = "<span class=\"icao\">" + icao + "</span>" + flight + alt + pos;
      planesList.appendChild(div);
    });
  }

  function mergePlaneByIcao(p) {
    const icao = normIcao(p.icao);
    if (!icao) {
      planeDetections.push(p);
      if (planeDetections.length > 200) planeDetections.shift();
      return;
    }
    const idx = planeDetections.findIndex((x) => normIcao(x.icao) === icao);
    if (idx >= 0) {
      planeDetections[idx] = Object.assign({}, planeDetections[idx], p);
    } else {
      planeDetections.push(p);
      if (planeDetections.length > 200) planeDetections.shift();
    }
  }

  socket.on("plane", (p) => {
    mergePlaneByIcao(p);
    updateFirstSeen(p);
    updateMapMarkers(planeDetections);
    renderPlanesList();
  });

  socket.on("planes_snapshot", (arr) => {
    if (!Array.isArray(arr)) return;
    planeDetections = arr;
    arr.forEach(updateFirstSeen);
    updateMapMarkers(planeDetections);
    renderPlanesList();
  });

  socket.on("adsb_update", (data) => {
    if (data && Array.isArray(data.lines)) {
      adsbLines = data.lines;
      renderAdsbList();
    }
  });

  function renderAdsbList() {
    adsbList.innerHTML = "";
    adsbLines.forEach((line) => {
      const div = document.createElement("div");
      div.className = "adsb-line";
      div.textContent = line;
      adsbList.appendChild(div);
    });
  }

  // Poll status when on dashboard or ADS-B tab (in case socket misses updates)
  setInterval(() => {
    const onDashboard = document.getElementById("panel-dashboard").classList.contains("active");
    const onAdsb = document.getElementById("panel-adsb").classList.contains("active");
    if (!onDashboard && !onAdsb) return;
    fetch("/api/status")
      .then((r) => r.json())
      .then((data) => {
        statusDevice.textContent = data.device === "ok" ? "OK" : data.device === "error" ? "Error" : "—";
        statusDevice.className = "value status-badge " + (data.device === "ok" ? "ok" : data.device === "error" ? "error" : "pending");
        statusMode.textContent = data.mode || "—";
        statusBands.textContent = Array.isArray(data.bands)
          ? data.bands.map((b) => b[0] + "–" + b[1]).join(", ")
          : "—";
        statusCenter.textContent = data.center_mhz != null ? data.center_mhz.toFixed(3) + " MHz" : "—";
        statusFloorPeak.textContent =
          data.floor_db != null && data.peak_db != null
            ? data.floor_db.toFixed(1) + " / " + data.peak_db.toFixed(1)
            : "—";
        statusMinFloor.textContent = data.min_floor_db != null ? data.min_floor_db.toFixed(1) : "—";
        statusSlice.textContent = Array.isArray(data.slice_mhz)
          ? data.slice_mhz[0].toFixed(3) + " .. " + data.slice_mhz[1].toFixed(3)
          : "—";
        statusError.textContent = data.error || "—";
        if (data.rtl_status) updateRtlStatus(data.rtl_status);
      })
      .catch(() => {});
  }, 1500);

  // ADS-B submit
  adsbSubmit.addEventListener("click", () => {
    const text = adsbInput.value.trim();
    if (!text) return;
    fetch("/api/adsb", {
      method: "POST",
      headers: { "Content-Type": "text/plain" },
      body: text,
    })
      .then((r) => r.json())
      .then((data) => {
        if (data.lines !== undefined) adsbLines = data.lines;
        renderAdsbList();
        adsbInput.value = "";
      });
  });

  // Load initial ADS-B list and planes
  fetch("/api/adsb")
    .then((r) => r.json())
    .then((data) => {
      if (Array.isArray(data.lines)) {
        adsbLines = data.lines;
        renderAdsbList();
      }
    })
    .catch(() => {});

  fetch("/api/planes")
    .then((r) => r.json())
    .then((arr) => {
      if (Array.isArray(arr)) {
        planeDetections = arr;
        renderPlanesList(planeDetections);
      }
    })
    .catch(() => {});

  // Load Speer Cyber Defense logo from base64 file (static/logo.txt)
  const speerLogo = $("speer-logo");
  if (speerLogo) {
    fetch("/static/logo.txt")
      .then((r) => r.text())
      .then((dataUrl) => {
        const s = (dataUrl || "").trim();
        if (s) speerLogo.src = s;
      })
      .catch(() => {});
  }
})();
