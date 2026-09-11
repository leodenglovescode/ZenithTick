"use strict";

const $ = (id) => document.getElementById(id);
const SVG_NS = "http://www.w3.org/2000/svg";
const GNSS_ORIGINS = Object.freeze({
  0: { constellation: "GPS", flag: "🇺🇸", origin: "United States" },
  1: { constellation: "SBAS", flag: "🌐", origin: "Regional" },
  2: { constellation: "Galileo", flag: "🇪🇺", origin: "European Union" },
  3: { constellation: "BeiDou", flag: "🇨🇳", origin: "China" },
  4: { constellation: "IMES", flag: "🇯🇵", origin: "Japan" },
  5: { constellation: "QZSS", flag: "🇯🇵", origin: "Japan" },
  6: { constellation: "GLONASS", flag: "🇷🇺", origin: "Russia" },
  7: { constellation: "NavIC", flag: "🇮🇳", origin: "India" },
});

const dashboard = {
  satellites: [],
  sortKey: "used",
  sortDirection: "desc",
  statusTimer: null,
  statusBusy: false,
  lastStatusAt: 0,
};

const skyLabelCycle = {
  showOrigins: false,
  timer: null,
};

const clockSync = {
  anchorEpochMs: null,
  anchorPerformanceMs: null,
  uncertaintyMs: null,
  networkRttMs: null,
  lastSyncPerformanceMs: null,
  chrony: {},
  syncing: false,
};

const dateFormatter = new Intl.DateTimeFormat("en-US", {
  timeZone: "Asia/Shanghai",
  month: "long",
  day: "numeric",
  year: "numeric",
});
const weekdayFormatter = new Intl.DateTimeFormat("en-US", {
  timeZone: "Asia/Shanghai",
  weekday: "long",
});
const timeFormatter = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Shanghai",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});

function isNumber(value) {
  return typeof value === "number" && Number.isFinite(value);
}

function text(id, value) {
  $(id).textContent = value;
}

function displayNumber(value, digits = 1, suffix = "") {
  return isNumber(value) ? `${value.toFixed(digits)}${suffix}` : "—";
}

function formatDurationSeconds(seconds) {
  if (!isNumber(seconds)) return "—";
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`;
  if (seconds < 90) return `${seconds.toFixed(seconds < 10 ? 1 : 0)} s`;
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}

function formatOffset(seconds) {
  if (!isNumber(seconds)) return "—";
  const sign = seconds >= 0 ? "+" : "−";
  const absolute = Math.abs(seconds);
  if (absolute < 1e-6) return `${sign}${(absolute * 1e9).toFixed(0)} ns`;
  if (absolute < 1e-3) return `${sign}${(absolute * 1e6).toFixed(2)} µs`;
  if (absolute < 1) return `${sign}${(absolute * 1e3).toFixed(3)} ms`;
  return `${sign}${absolute.toFixed(6)} s`;
}

function formatInterval(seconds) {
  if (!isNumber(seconds)) return "—";
  const absolute = Math.abs(seconds);
  if (absolute < 1e-6) return `${(absolute * 1e9).toFixed(0)} ns`;
  if (absolute < 1e-3) return `${(absolute * 1e6).toFixed(2)} µs`;
  if (absolute < 1) return `${(absolute * 1e3).toFixed(3)} ms`;
  return `${absolute.toFixed(6)} s`;
}

function formatEpochSeconds(seconds) {
  if (!isNumber(seconds)) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: "UTC",
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).format(new Date(seconds * 1000)) + " UTC";
}

function formatHistoryTime(seconds) {
  if (!isNumber(seconds)) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Shanghai",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(new Date(seconds * 1000));
}

function setLamp(id, state) {
  const element = $(id);
  element.className = `lamp ${state}`;
}

function satelliteOrigin(satellite) {
  if (!isNumber(satellite.gnssid) || !Number.isInteger(satellite.gnssid)) return null;
  return GNSS_ORIGINS[satellite.gnssid] || null;
}

function satelliteOriginLabel(satellite) {
  const origin = satelliteOrigin(satellite);
  return origin ? `${origin.flag} ${origin.origin} · ${origin.constellation}` : "—";
}

async function updateStatus() {
  if (dashboard.statusBusy) return;
  dashboard.statusBusy = true;
  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const state = await response.json();
    dashboard.lastStatusAt = performance.now();
    renderGps(state.gps || {});
    renderChrony(state.chrony || {});
    text("backend-state", "Backend online · status 1 Hz");
  } catch (error) {
    text("backend-state", "Backend unavailable · retrying");
    setLamp("gps-lamp", "is-bad");
    setLamp("pps-lamp", "is-bad");
  } finally {
    dashboard.statusBusy = false;
  }
}

function renderGps(gps) {
  const tpv = gps.tpv || {};
  const sky = gps.sky || {};
  const satellites = Array.isArray(gps.satellites) ? gps.satellites : [];
  const fresh = gps.connected && (!isNumber(gps.age_seconds) || gps.age_seconds < 5);
  const mode = fresh && isNumber(tpv.mode) ? tpv.mode : 0;
  const modeLabel = mode >= 3 ? "3D FIX" : mode === 2 ? "2D FIX" : "NO FIX";
  const fixElement = $("fix-mode");
  fixElement.textContent = modeLabel;
  fixElement.className = `fix-mode ${mode >= 3 ? "is-3d" : mode === 2 ? "is-2d" : ""}`;

  setLamp("gps-lamp", fresh ? (mode >= 2 ? "is-good" : "is-warn") : "is-bad");
  text("gps-header-state", fresh ? (mode >= 2 ? "FIX" : "NO FIX") : "OFFLINE");

  const visible = isNumber(sky.nSat) ? sky.nSat : satellites.length;
  const computedUsed = satellites.filter((satellite) => satellite.used === true).length;
  const used = isNumber(sky.uSat) ? sky.uSat : computedUsed;
  text("visible-count", String(visible));
  text("used-count", String(used));
  text("satellite-ratio", `${used} used / ${visible} visible`);

  text("latitude", mode >= 2 ? displayNumber(tpv.lat, 6, "°") : "—");
  text("longitude", mode >= 2 ? displayNumber(tpv.lon, 6, "°") : "—");
  const altitude = isNumber(tpv.altMSL) ? tpv.altMSL : isNumber(tpv.altHAE) ? tpv.altHAE : tpv.alt;
  text("altitude", mode >= 3 ? displayNumber(altitude, 1, " m") : "—");
  text("gps-time", typeof tpv.time === "string" ? tpv.time.replace("T", " ").replace("Z", " UTC") : "—");
  text("hdop", displayNumber(sky.hdop, 2));
  text("dop-pair", `${displayNumber(sky.pdop, 2)} / ${displayNumber(sky.vdop, 2)}`);

  const hasSpeed = mode >= 2 && isNumber(tpv.speed);
  $("speed-row").hidden = !hasSpeed;
  text("speed", hasSpeed ? `${tpv.speed.toFixed(2)} m/s` : "—");
  const hasCourse = hasSpeed && tpv.speed >= 0.5 && isNumber(tpv.track);
  $("course-row").hidden = !hasCourse;
  text("course", hasCourse ? `${tpv.track.toFixed(1)}°` : "—");
  text("receiver", gps.device || tpv.device || sky.device || "—");

  if (fresh) {
    text("gps-component-state", `gpsd connected · report age ${formatDurationSeconds(gps.age_seconds)}`);
  } else if (gps.connected) {
    text("gps-component-state", `gpsd data stale · ${formatDurationSeconds(gps.age_seconds)} old`);
  } else {
    text("gps-component-state", "gpsd unavailable · cached values retained");
  }

  dashboard.satellites = satellites;
  renderSkyPlot(satellites);
  renderSatelliteTable();
  text("satellite-update", satellites.length ? `Live SKY · ${satellites.length} records` : "No satellites visible");
}

function satelliteTooltip(satellite) {
  const origin = satelliteOrigin(satellite);
  return [
    `<b>Satellite ${escapeHtml(satellite.label || "—")}</b>`,
    ...(origin ? [`Origin   ${escapeHtml(`${origin.flag} ${origin.origin} · ${origin.constellation}`)}`] : []),
    `Azimuth  ${displayNumber(satellite.az, 1, "°")}`,
    `Elevation ${displayNumber(satellite.el, 1, "°")}`,
    `C/N0     ${displayNumber(satellite.ss, 1, " dB-Hz")}`,
    `Used     ${satellite.used === true ? "yes" : "no"}`,
  ].join("<br>");
}

function updateSkyMarkerLabels() {
  document.querySelectorAll("#satellite-layer .satellite-marker-label").forEach((label) => {
    const showFlag = skyLabelCycle.showOrigins && Boolean(label.dataset.originFlag);
    label.textContent = showFlag ? label.dataset.originFlag : label.dataset.satelliteId;
    label.classList.toggle("is-flag", showFlag);
  });
}

function setupSkyLabelCycle() {
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    skyLabelCycle.timer = setTimeout(() => {
      skyLabelCycle.showOrigins = true;
      updateSkyMarkerLabels();
    }, 3000);
    return;
  }
  skyLabelCycle.timer = setInterval(() => {
    skyLabelCycle.showOrigins = !skyLabelCycle.showOrigins;
    updateSkyMarkerLabels();
  }, 3000);
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[character]);
}

function renderSkyPlot(satellites) {
  const layer = $("satellite-layer");
  layer.replaceChildren();
  for (const satellite of satellites) {
    if (!isNumber(satellite.az) || !isNumber(satellite.el)) continue;
    const elevation = Math.max(0, Math.min(90, satellite.el));
    const azimuthRadians = satellite.az * Math.PI / 180;
    const radialDistance = 160 * (1 - elevation / 90);
    const x = 200 + radialDistance * Math.sin(azimuthRadians);
    const y = 200 - radialDistance * Math.cos(azimuthRadians);
    const signalRadius = isNumber(satellite.ss) ? Math.max(10, Math.min(17, 9 + satellite.ss / 8)) : 11;

    const node = document.createElementNS(SVG_NS, "g");
    node.setAttribute("class", `satellite-node ${satellite.used === true ? "used" : "visible"}`);
    node.setAttribute("transform", `translate(${x.toFixed(2)} ${y.toFixed(2)})`);
    node.setAttribute("tabindex", "0");
    node.setAttribute("role", "img");
    node.setAttribute("aria-label", satelliteTooltip(satellite).replace(/<[^>]+>/g, ", "));

    const circle = document.createElementNS(SVG_NS, "circle");
    circle.setAttribute("r", signalRadius.toFixed(1));
    const label = document.createElementNS(SVG_NS, "text");
    const origin = satelliteOrigin(satellite);
    label.setAttribute("class", "satellite-marker-label");
    label.setAttribute("text-anchor", "middle");
    label.setAttribute("dominant-baseline", "central");
    label.dataset.satelliteId = satellite.label || "?";
    label.dataset.originFlag = origin?.flag || "";
    const showFlag = skyLabelCycle.showOrigins && Boolean(origin);
    label.textContent = showFlag ? origin.flag : label.dataset.satelliteId;
    label.classList.toggle("is-flag", showFlag);
    node.append(circle, label);

    const show = (event) => showSatelliteTooltip(event, satellite, node);
    node.addEventListener("pointerenter", show);
    node.addEventListener("pointermove", show);
    node.addEventListener("pointerleave", hideSatelliteTooltip);
    node.addEventListener("focus", show);
    node.addEventListener("blur", hideSatelliteTooltip);
    node.addEventListener("click", show);
    layer.appendChild(node);
  }
}

function showSatelliteTooltip(event, satellite, node) {
  const tooltip = $("satellite-tooltip");
  const wrap = tooltip.parentElement;
  const wrapRect = wrap.getBoundingClientRect();
  let x;
  let y;
  if (event.clientX && event.clientY) {
    x = event.clientX - wrapRect.left + 12;
    y = event.clientY - wrapRect.top + 12;
  } else {
    const nodeRect = node.getBoundingClientRect();
    x = nodeRect.left - wrapRect.left + nodeRect.width + 8;
    y = nodeRect.top - wrapRect.top;
  }
  tooltip.innerHTML = satelliteTooltip(satellite);
  tooltip.hidden = false;
  requestAnimationFrame(() => {
    tooltip.style.left = `${Math.max(4, Math.min(x, wrapRect.width - tooltip.offsetWidth - 4))}px`;
    tooltip.style.top = `${Math.max(4, Math.min(y, wrapRect.height - tooltip.offsetHeight - 4))}px`;
  });
}

function hideSatelliteTooltip() {
  $("satellite-tooltip").hidden = true;
}

function sortValue(satellite, key) {
  if (key === "used") return satellite.used === true ? 1 : 0;
  if (key === "origin") return satelliteOriginLabel(satellite);
  const value = satellite[key];
  return value === null || value === undefined ? (typeof value === "string" ? "" : -Infinity) : value;
}

function renderSatelliteTable() {
  const body = $("satellite-table-body");
  const direction = dashboard.sortDirection === "asc" ? 1 : -1;
  const satellites = [...dashboard.satellites].sort((left, right) => {
    const a = sortValue(left, dashboard.sortKey);
    const b = sortValue(right, dashboard.sortKey);
    if (typeof a === "string" || typeof b === "string") return String(a).localeCompare(String(b), undefined, { numeric: true }) * direction;
    return (a - b) * direction;
  });
  body.replaceChildren();
  if (!satellites.length) {
    const row = body.insertRow();
    row.className = "empty-row";
    const cell = row.insertCell();
    cell.colSpan = 9;
    cell.textContent = "No satellites visible";
    return;
  }
  for (const satellite of satellites) {
    const row = body.insertRow();
    const values = [
      satellite.label || "—",
      satelliteOriginLabel(satellite),
      displayNumber(satellite.az, 1, "°"),
      displayNumber(satellite.el, 1, "°"),
      displayNumber(satellite.ss, 1),
      satellite.used === true ? "YES" : "NO",
      formatHistoryTime(satellite.first_seen),
      formatHistoryTime(satellite.last_seen),
      displayNumber(satellite.best_signal, 1),
    ];
    values.forEach((value, index) => {
      const cell = row.insertCell();
      cell.textContent = value;
      if (index === 1) cell.className = "origin-cell";
      if (index === 5) cell.classList.add(satellite.used === true ? "used-yes" : "used-no");
    });
  }
}

function setupSorting() {
  document.querySelectorAll("button[data-sort]").forEach((button) => {
    button.addEventListener("click", () => {
      const key = button.dataset.sort;
      if (dashboard.sortKey === key) {
        dashboard.sortDirection = dashboard.sortDirection === "asc" ? "desc" : "asc";
      } else {
        dashboard.sortKey = key;
        dashboard.sortDirection = ["label", "origin", "first_seen"].includes(key) ? "asc" : "desc";
      }
      document.querySelectorAll("button[data-sort]").forEach((candidate) => delete candidate.dataset.direction);
      button.dataset.direction = dashboard.sortDirection;
      renderSatelliteTable();
    });
  });
}

const sourceState = {
  "*": ["SELECTED", "source-selected"],
  "+": ["CANDIDATE", "source-candidate"],
  "-": ["EXCLUDED", ""],
  "?": ["UNREACHABLE", "source-unavailable"],
  "x": ["FALSE TICK", "source-rejected"],
  "~": ["VARIABLE", "source-rejected"],
};

function renderChrony(chrony) {
  const tracking = chrony.tracking || {};
  const sources = Array.isArray(chrony.sources) ? chrony.sources : [];
  const ppsStatus = chrony.pps_status || "unavailable";
  if (!chrony.available) {
    setLamp("pps-lamp", "is-bad");
    text("pps-header-state", "OFFLINE");
    text("chrony-state", "chronyd unavailable · cached display may be stale");
  } else if (!chrony.synchronized) {
    setLamp("pps-lamp", "is-bad");
    text("pps-header-state", "UNSYNC");
    text("chrony-state", "Chrony unsynchronized");
  } else if (ppsStatus === "selected") {
    setLamp("pps-lamp", "is-good");
    text("pps-header-state", "LOCKED");
    text("chrony-state", `PPS selected · update age ${formatDurationSeconds(chrony.age_seconds)}`);
  } else if (ppsStatus === "available") {
    setLamp("pps-lamp", "is-warn");
    text("pps-header-state", "STANDBY");
    text("chrony-state", "PPS available, not selected");
  } else {
    setLamp("pps-lamp", "is-warn");
    text("pps-header-state", "ABSENT");
    text("chrony-state", "Chrony synchronized · PPS unavailable");
  }

  text("selected-source", chrony.selected_source || "—");
  text("stratum", tracking.stratum ?? "—");
  text("system-offset", formatOffset(tracking.system_time_offset_s));
  text("last-offset", formatOffset(tracking.last_offset_s));
  text("rms-offset", formatInterval(tracking.rms_offset_s));
  text("frequency", isNumber(tracking.frequency_ppm) ? `${tracking.frequency_ppm.toFixed(3)} ppm` : "—");
  text("root-dispersion", formatInterval(tracking.root_dispersion_s));
  text("reference-time", formatEpochSeconds(tracking.reference_time_epoch));
  text("leap-status", tracking.leap_status || "—");

  const body = $("chrony-sources-body");
  body.replaceChildren();
  if (!sources.length) {
    const row = body.insertRow();
    row.className = "empty-row";
    const cell = row.insertCell();
    cell.colSpan = 8;
    cell.textContent = "No chrony sources reported";
    return;
  }
  for (const source of sources) {
    const statistics = source.statistics || {};
    const state = sourceState[source.state] || [source.state || "—", ""];
    const row = body.insertRow();
    const values = [
      state[0], source.name || "—", source.stratum ?? "—", source.reach || "—",
      formatDurationSeconds(source.last_rx_s), formatOffset(source.adjusted_offset_s),
      formatInterval(source.estimated_error_s), formatInterval(statistics.standard_deviation_s),
    ];
    values.forEach((value, index) => {
      const cell = row.insertCell();
      cell.textContent = value;
      if (index === 0) cell.className = state[1];
    });
  }
}

function nsStringToMs(value) {
  const ns = BigInt(value);
  return Number(ns / 1_000_000n) + Number(ns % 1_000_000n) / 1_000_000;
}

async function timeProbe() {
  const start = performance.now();
  const response = await fetch(`/api/time?_=${Math.random().toString(36).slice(2)}`, { cache: "no-store" });
  const end = performance.now();
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const sample = await response.json();
  const serverReceiveMs = nsStringToMs(sample.server_receive_ns);
  const serverTransmitMs = nsStringToMs(sample.server_transmit_ns);
  const serverReceiveMonoMs = nsStringToMs(sample.server_receive_monotonic_ns);
  const serverTransmitMonoMs = nsStringToMs(sample.server_transmit_monotonic_ns);
  const roundTripMs = end - start;
  const serverProcessingMs = Math.max(0, serverTransmitMonoMs - serverReceiveMonoMs);
  const networkRttMs = Math.max(0, roundTripMs - serverProcessingMs);
  return {
    anchorEpochMs: (serverReceiveMs + serverTransmitMs) / 2 + roundTripMs / 2,
    anchorPerformanceMs: end,
    networkRttMs,
    uncertaintyMs: Math.max(0.5, networkRttMs / 2),
    chrony: sample.chrony || {},
  };
}

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function synchronizeClock() {
  if (clockSync.syncing || document.hidden) return;
  clockSync.syncing = true;
  const samples = [];
  try {
    for (let index = 0; index < 6; index += 1) {
      try {
        samples.push(await timeProbe());
      } catch (_) {
        // A later probe may succeed; the clock keeps its previous anchor meanwhile.
      }
      if (index < 5) await delay(70);
    }
    if (!samples.length) throw new Error("all time probes failed");
    samples.sort((a, b) => a.networkRttMs - b.networkRttMs);
    Object.assign(clockSync, samples[0], { lastSyncPerformanceMs: performance.now() });
    renderClockQuality();
  } catch (_) {
    renderClockQuality(true);
  } finally {
    clockSync.syncing = false;
  }
}

function renderClockQuality(failed = false) {
  const quality = $("clock-quality");
  if (failed && clockSync.anchorEpochMs === null) {
    quality.textContent = "SYSTEM CLOCK · synchronization unavailable";
    quality.className = "clock-quality bad";
    return;
  }
  const chrony = clockSync.chrony || {};
  const prefix = !chrony.available || !chrony.synchronized
    ? "CHRONY UNSYNCHRONIZED"
    : chrony.pps_status === "selected"
      ? "PPS LOCKED"
      : chrony.pps_status === "available"
        ? "PPS AVAILABLE"
        : "SYSTEM CLOCK SYNCED";
  const uncertainty = isNumber(clockSync.uncertaintyMs) ? `browser sync ±${clockSync.uncertaintyMs.toFixed(1)} ms` : "browser sync unknown";
  quality.textContent = `${prefix} · ${uncertainty}`;
  quality.className = `clock-quality ${chrony.synchronized ? (chrony.pps_status === "selected" ? "good" : "warn") : "bad"}`;
}

let lastClockFrame = 0;
let lastDateKey = "";
function animateClock(frameTime) {
  if (frameTime - lastClockFrame >= 16 && clockSync.anchorEpochMs !== null) {
    lastClockFrame = frameTime;
    const epochMs = clockSync.anchorEpochMs + (frameTime - clockSync.anchorPerformanceMs);
    const date = new Date(epochMs);
    const timeParts = Object.fromEntries(timeFormatter.formatToParts(date).map((part) => [part.type, part.value]));
    text("clock-hms", `${timeParts.hour}:${timeParts.minute}:${timeParts.second}`);
    text("clock-ms", String(Math.floor(((epochMs % 1000) + 1000) % 1000)).padStart(3, "0"));
    const dateKey = dateFormatter.format(date);
    if (dateKey !== lastDateKey) {
      lastDateKey = dateKey;
      text("clock-date", dateKey);
      text("clock-weekday", `(${weekdayFormatter.format(date)})`);
    }
    if (clockSync.lastSyncPerformanceMs !== null && frameTime - clockSync.lastSyncPerformanceMs > 60_000) {
      const quality = $("clock-quality");
      quality.textContent = "SYSTEM CLOCK · browser synchronization stale";
      quality.className = "clock-quality warn";
    }
  }
  requestAnimationFrame(animateClock);
}

function start() {
  setupSorting();
  setupSkyLabelCycle();
  const defaultSort = document.querySelector('button[data-sort="used"]');
  if (defaultSort) defaultSort.dataset.direction = "desc";
  updateStatus();
  synchronizeClock();
  dashboard.statusTimer = setInterval(updateStatus, 1000);
  setInterval(synchronizeClock, 25_000);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      updateStatus();
      synchronizeClock();
    }
  });
  window.addEventListener("pageshow", synchronizeClock);
  requestAnimationFrame(animateClock);
}

start();
