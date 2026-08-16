const API = ""; // same origin

// ---------- State ----------
let map;
let tileDark, tileLight, currentTile;
let areaMarkers = {};       // name -> L.circleMarker
let areaData = {};          // name -> {lat, lon, risk_score_100, risk_band, confidence}
let routeLayers = [];
let userMarker = null;
let watchId = null;
let riskOverlayOn = true;
let charts = {};
let analyticsLoaded = false;

const TIME_SLOT_HOUR = { Morning: 9, Afternoon: 15, Evening: 19, Night: 23 };

function riskColor(band) {
  if (!band) return "#9aa5c4";
  if (band.startsWith("Green")) return "#34d399";
  if (band.startsWith("Yellow")) return "#fbbf24";
  if (band.startsWith("Red")) return "#f87171";
  return "#9aa5c4";
}

// ---------- Init ----------
document.addEventListener("DOMContentLoaded", () => {
  initMap();
  loadLocalities();
  updateClock();
  setInterval(updateClock, 30000);
  initSosHold();

  const saved = localStorage.getItem("saferoute-theme");
  if (saved === "light") setTheme("light");
});

function initMap() {
  map = L.map("map", { zoomControl: false }).setView([21.145, 79.090], 12);
  L.control.zoom({ position: "bottomleft" }).addTo(map);

  tileDark = L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
    attribution: "&copy; OpenStreetMap &copy; CARTO",
    subdomains: "abcd",
    maxZoom: 20,
  });
  tileLight = L.tileLayer("https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png", {
    attribution: "&copy; OpenStreetMap &copy; CARTO",
    subdomains: "abcd",
    maxZoom: 20,
  });
  currentTile = tileDark.addTo(map);
}

// ---------- Localities / risk-colored markers ----------
async function loadLocalities(hour) {
  const url = hour !== undefined ? `${API}/api/localities?hour=${hour}` : `${API}/api/localities`;
  const res = await fetch(url);
  const data = await res.json();

  const sourceSel = document.getElementById("sourceArea");
  const destSel = document.getElementById("destArea");
  const firstLoad = Object.keys(areaData).length === 0;

  if (firstLoad) {
    sourceSel.innerHTML = '<option value="">— Select Start Area —</option>';
    destSel.innerHTML = '<option value="">— Select Destination —</option>';
  }

  data.localities.forEach((loc) => {
    areaData[loc.name] = loc;

    if (areaMarkers[loc.name]) {
      areaMarkers[loc.name].setStyle({
        color: riskColor(loc.risk_band),
        fillColor: riskColor(loc.risk_band),
      });
    } else {
      const marker = L.circleMarker([loc.lat, loc.lon], {
        radius: 8,
        color: riskColor(loc.risk_band),
        fillColor: riskColor(loc.risk_band),
        fillOpacity: riskOverlayOn ? 0.75 : 0.35,
        weight: 2,
      }).addTo(map);
      marker.on("click", () => showAreaInfo(loc.name));
      areaMarkers[loc.name] = marker;

      if (firstLoad) {
        [sourceSel, destSel].forEach((sel) => {
          const opt = document.createElement("option");
          opt.value = loc.name;
          opt.textContent = loc.name;
          sel.appendChild(opt);
        });
      }
    }
  });
}

function showAreaInfo(name) {
  const loc = areaData[name];
  if (!loc) return;
  const card = document.getElementById("areaInfoCard");
  const content = document.getElementById("areaInfoContent");
  content.innerHTML = `
    <div class="area-info-name">${name}</div>
    <div class="area-info-band" style="background:${riskColor(loc.risk_band)}">${loc.risk_band}</div>
    <div class="area-info-row"><span>Risk score</span><b>${loc.risk_score_100}/100</b></div>
    <div class="area-info-row"><span>Confidence</span><b>${loc.confidence}</b></div>
  `;
  card.classList.remove("hidden");
}
function closeAreaInfo() {
  document.getElementById("areaInfoCard").classList.add("hidden");
}

// ---------- Map controls ----------
function toggleMapLayer() {
  map.removeLayer(currentTile);
  currentTile = currentTile === tileDark ? tileLight.addTo(map) : tileDark.addTo(map);
}

function toggleRiskOverlay() {
  riskOverlayOn = !riskOverlayOn;
  document.getElementById("riskOverlayBtn").classList.toggle("active-overlay", riskOverlayOn);
  Object.values(areaMarkers).forEach((m) => m.setStyle({ fillOpacity: riskOverlayOn ? 0.75 : 0.35 }));
}

function resetView() {
  map.setView([21.145, 79.090], 12);
}

// ---------- Live location ----------
function locateMe() {
  if (!navigator.geolocation) {
    document.getElementById("locationStatus").textContent = "Geolocation not supported by this browser.";
    return;
  }
  document.getElementById("locationStatus").textContent = "Locating…";
  document.getElementById("liveBar").classList.remove("hidden");

  watchId = navigator.geolocation.watchPosition(
    (pos) => {
      const { latitude, longitude } = pos.coords;
      updateUserMarker(latitude, longitude);
      document.getElementById("locationStatus").textContent = "Live location active.";
      document.getElementById("liveBarText").textContent = `Tracking: ${latitude.toFixed(4)}, ${longitude.toFixed(4)}`;
      document.getElementById("liveCoords").textContent = `${latitude.toFixed(4)}, ${longitude.toFixed(4)}`;
    },
    (err) => {
      document.getElementById("locationStatus").textContent = "Location permission denied.";
      document.getElementById("liveBar").classList.add("hidden");
    },
    { enableHighAccuracy: true }
  );
}

function updateUserMarker(lat, lon) {
  if (userMarker) {
    userMarker.setLatLng([lat, lon]);
  } else {
    userMarker = L.circleMarker([lat, lon], {
      radius: 9,
      color: "#60a5fa",
      fillColor: "#60a5fa",
      fillOpacity: 0.9,
      weight: 3,
    }).addTo(map).bindTooltip("You are here");
  }
}

function centerOnLocation() {
  if (userMarker) {
    map.setView(userMarker.getLatLng(), 15);
  } else {
    locateMe();
  }
}

function stopTracking() {
  if (watchId !== null) navigator.geolocation.clearWatch(watchId);
  watchId = null;
  document.getElementById("liveBar").classList.add("hidden");
  document.getElementById("locationStatus").textContent = "";
}

// ---------- Route panel ----------
function togglePanel() {
  document.getElementById("routePanel").classList.toggle("collapsed");
}

function onSelectionChange() {
  const source = document.getElementById("sourceArea").value;
  const dest = document.getElementById("destArea").value;
  document.getElementById("findBtn").disabled = !(source && dest && source !== dest);
}

function clearRoutes() {
  routeLayers.forEach((l) => map.removeLayer(l));
  routeLayers = [];
}

const ROUTE_COLORS = { recommended: "#34d399", fastest: "#60a5fa", safest: "#fbbf24" };

function drawRoute(route) {
  let latlngs = route.path_coords;
  if (!latlngs || latlngs.length < 2) {
    // Fallback for older responses without path_coords: straight lines between area centroids.
    latlngs = route.path.map((name) => {
      const loc = areaData[name];
      return loc ? [loc.lat, loc.lon] : null;
    }).filter(Boolean);
  }
  if (latlngs.length < 2) return null;
  const line = L.polyline(latlngs, {
    color: ROUTE_COLORS[route.category] || "#9aa5c4",
    weight: 5,
    opacity: 0.85,
  }).addTo(map);
  routeLayers.push(line);
  return line;
}

async function findRoutes() {
  const origin = document.getElementById("sourceArea").value;
  const destination = document.getElementById("destArea").value;
  const timeSlot = document.getElementById("timeSlot").value;
  const hour = TIME_SLOT_HOUR[timeSlot] ?? 19;

  const resultsEl = document.getElementById("routeResults");
  const cardsEl = document.getElementById("routeCards");
  resultsEl.classList.remove("hidden");
  cardsEl.innerHTML = '<div class="route-error" style="color:var(--text-dim)">Calculating…</div>';
  clearRoutes();

  await loadLocalities(hour); // refresh risk colors for the selected time

  const now = new Date();
  now.setHours(hour, 0, 0, 0);

  try {
    const res = await fetch(`${API}/api/optimize_route`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ origin, destination, departure_time: now.toISOString() }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Request failed");

    cardsEl.innerHTML = "";
    const bounds = [];
    data.routes.forEach((route) => {
      const card = document.createElement("div");
      card.className = "route-card";
      card.innerHTML = `
        <span class="route-badge ${route.category}">${route.category}</span>
        <div class="route-metrics">
          <b>${route.total_time_min} min</b> · ${route.total_distance_km} km<br>
          Mean risk: <b>${route.mean_risk}</b>/10 · Peak risk: <b>${route.peak_risk}</b>/10<br>
          Detour: ${route.detour_percent}%${route.feasible ? "" : " (exceeds limit)"}
        </div>
        <div class="route-explain">${route.explanation}</div>`;
      cardsEl.appendChild(card);
      const line = drawRoute(route);
      if (line) bounds.push(...line.getLatLngs());
    });
    if (bounds.length) map.fitBounds(bounds, { padding: [40, 40] });
  } catch (err) {
    cardsEl.innerHTML = `<div class="route-error">${err.message}</div>`;
  }
}

// ---------- Tabs ----------
function showTab(name) {
  document.querySelectorAll(".tab-content").forEach((el) => el.classList.remove("active"));
  document.querySelectorAll(".nav-btn").forEach((el) => el.classList.remove("active"));

  document.getElementById(`tab${name.charAt(0).toUpperCase() + name.slice(1)}`).classList.add("active");
  document.getElementById(`nav${name.charAt(0).toUpperCase() + name.slice(1)}`).classList.add("active");

  if (name === "dashboard" && !analyticsLoaded) loadAnalytics();
  if (name === "map") setTimeout(() => map.invalidateSize(), 100);
}

// ---------- Theme ----------
function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme");
  setTheme(current === "dark" ? "light" : "dark");
}
function setTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  document.getElementById("themeIcon").className = theme === "dark" ? "fa-solid fa-moon" : "fa-solid fa-sun";
  localStorage.setItem("saferoute-theme", theme);

  // Keep the map tile style in sync with the UI theme.
  if (map && tileDark && tileLight) {
    const wanted = theme === "dark" ? tileDark : tileLight;
    if (currentTile !== wanted) {
      map.removeLayer(currentTile);
      currentTile = wanted.addTo(map);
      document.getElementById("layerToggleBtn")?.classList.toggle("active-layer", theme === "dark");
    }
  }
}

function updateClock() {
  const el = document.getElementById("headerTime");
  if (el) el.textContent = new Date().toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

// ---------- SOS: 3-second press-and-hold ----------
const HOLD_DURATION_MS = 3000;
let holdTimer = null;
let holdStartTime = null;

function initSosHold() {
  const btn = document.getElementById("sosButton");
  const fill = document.getElementById("sosProgressFill");
  if (!btn) return;

  const start = (e) => {
    e.preventDefault();
    if (holdTimer) return;
    holdStartTime = Date.now();
    btn.classList.add("holding");
    fill.style.transition = "none";
    fill.style.strokeDashoffset = "125.6";
    // Force reflow so the transition below actually animates from the reset state.
    fill.getBoundingClientRect();
    fill.style.transition = `stroke-dashoffset ${HOLD_DURATION_MS}ms linear`;
    fill.style.strokeDashoffset = "0";

    holdTimer = setTimeout(() => {
      holdTimer = null;
      btn.classList.remove("holding");
      triggerSOS();
    }, HOLD_DURATION_MS);
  };

  const cancel = () => {
    if (!holdTimer) return;
    clearTimeout(holdTimer);
    holdTimer = null;
    btn.classList.remove("holding");
    fill.style.transition = "none";
    fill.style.strokeDashoffset = "125.6";
  };

  btn.addEventListener("mousedown", start);
  btn.addEventListener("touchstart", start, { passive: false });
  ["mouseup", "mouseleave", "touchend", "touchcancel"].forEach((evt) => btn.addEventListener(evt, cancel));
}

function getCurrentLocationOnce() {
  return new Promise((resolve) => {
    if (userMarker) {
      resolve(userMarker.getLatLng());
      return;
    }
    if (!navigator.geolocation) {
      resolve({ lat: 21.145, lng: 79.090 }); // Nagpur center fallback
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({ lat: pos.coords.latitude, lng: pos.coords.longitude }),
      () => resolve({ lat: 21.145, lng: 79.090 }),
      { enableHighAccuracy: true, timeout: 8000 }
    );
  });
}

async function triggerSOS() {
  const pos = await getCurrentLocationOnce();
  const lat = pos.lat, lng = pos.lng;
  updateUserMarker(lat, lng);
  document.getElementById("liveCoords").textContent = `${lat.toFixed(4)}, ${lng.toFixed(4)}`;

  const overlayText = document.getElementById("sosOverlayText");
  const stationInfo = document.getElementById("sosStationInfo");
  overlayText.textContent = "Sending…";
  stationInfo.innerHTML = "";
  document.getElementById("sosOverlay").classList.remove("hidden");

  try {
    const res = await fetch(`${API}/api/sos`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        lat, lng,
        timestamp: new Date().toISOString(),
        message: "I need help. This is an automatic SOS alert.",
      }),
    });
    const data = await res.json();
    const rec = data.sos_record || {};

    overlayText.textContent = rec.sms?.sent
      ? `Your emergency contact was notified by SMS with your location (id ${rec.sos_id}).`
      : `SOS logged (id ${rec.sos_id || "n/a"}). Real SMS isn't configured on this server, so tap a call button below to reach help directly.`;

    const jurisdiction = rec.nearest_police_jurisdiction;
    if (jurisdiction?.area_name) {
      const phoneLine = jurisdiction.phone
        ? `<a href="tel:${jurisdiction.phone}" class="sos-station-call">Call ${jurisdiction.area_name} Station: ${jurisdiction.phone}</a>`
        : `<span class="sos-station-note">No verified direct line for this station — use the numbers below.</span>`;
      stationInfo.innerHTML = `
        <i class="fa-solid fa-building-shield"></i>
        Nearest police jurisdiction: <b>${jurisdiction.area_name}</b>
        (~${jurisdiction.approx_distance_km} km away).<br>
        ${phoneLine}`;
    }
  } catch (e) {
    overlayText.textContent = "Could not reach the server — call the numbers below directly.";
  }
}

function closeSOS() {
  document.getElementById("sosOverlay").classList.add("hidden");
}

// ---------- Analytics dashboard ----------
async function loadAnalytics() {
  const subtitle = document.getElementById("dashSubtitle");
  try {
    const res = await fetch(`${API}/api/analytics`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Failed to load analytics");
    analyticsLoaded = true;

    subtitle.textContent = `Based on ${data.total_records.toLocaleString()} crime records across ${data.num_areas} Nagpur areas`;
    document.getElementById("statTotal").textContent = data.total_records.toLocaleString();
    document.getElementById("statHighRisk").textContent = data.high_risk_areas;
    document.getElementById("statNightPct").textContent = `${data.night_crime_pct}%`;
    document.getElementById("statSafest").textContent = data.safest_area;
    document.getElementById("aboutDatasetText").textContent =
      `${data.total_records.toLocaleString()} real crime records across ${data.num_areas} Nagpur areas (2025). Features include crime type, time slot, lighting score, crowd density, and proximity data.`;

    renderAreaTable(data.area_summary);
    renderCharts(data);
  } catch (e) {
    subtitle.textContent = "Could not load analytics: " + e.message;
  }
}

function renderAreaTable(rows) {
  const tbody = document.getElementById("areaTableBody");
  tbody.innerHTML = "";
  const pillColor = { High: "#f87171", Medium: "#fbbf24", Low: "#34d399" };
  rows.forEach((r) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${r.area}</td>
      <td>${r.total}</td>
      <td>${r.avg_risk}</td>
      <td>${r.safety_score}</td>
      <td>${r.avg_lighting}</td>
      <td>${r.avg_police_km}</td>
      <td><span class="risk-pill" style="background:${pillColor[r.risk_level] || '#9aa5c4'}">${r.risk_level}</span></td>`;
    tbody.appendChild(tr);
  });
}

function renderCharts(data) {
  Chart.defaults.color = "#9aa5c4";
  Chart.defaults.borderColor = "rgba(154,165,196,0.15)";

  const safetyEntries = Object.entries(data.safety_score_by_area);
  charts.safety?.destroy();
  charts.safety = new Chart(document.getElementById("chartSafety"), {
    type: "bar",
    data: {
      labels: safetyEntries.map((e) => e[0]),
      datasets: [{ label: "Safety Score", data: safetyEntries.map((e) => e[1]), backgroundColor: "#34d399" }],
    },
    options: { responsive: true, plugins: { legend: { display: false } } },
  });

  const typeEntries = Object.entries(data.crime_type_distribution);
  charts.type?.destroy();
  charts.type = new Chart(document.getElementById("chartCrimeType"), {
    type: "doughnut",
    data: {
      labels: typeEntries.map((e) => e[0]),
      datasets: [{
        data: typeEntries.map((e) => e[1]),
        backgroundColor: ["#f87171", "#fb923c", "#fbbf24", "#a78bfa", "#818cf8", "#34d399", "#f472b6"],
      }],
    },
    options: { responsive: true },
  });

  const slotEntries = Object.entries(data.time_slot_distribution);
  charts.slot?.destroy();
  charts.slot = new Chart(document.getElementById("chartTimeSlot"), {
    type: "bar",
    data: {
      labels: slotEntries.map((e) => e[0]),
      datasets: [{ label: "Crimes", data: slotEntries.map((e) => e[1]), backgroundColor: "#a78bfa" }],
    },
    options: { responsive: true, plugins: { legend: { display: false } } },
  });

  const areaEntries = Object.entries(data.crime_count_by_area);
  charts.area?.destroy();
  charts.area = new Chart(document.getElementById("chartCrimeArea"), {
    type: "bar",
    data: {
      labels: areaEntries.map((e) => e[0]),
      datasets: [{ label: "Crimes", data: areaEntries.map((e) => e[1]), backgroundColor: "#f87171" }],
    },
    options: { responsive: true, plugins: { legend: { display: false } } },
  });
}
