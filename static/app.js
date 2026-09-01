const API = ""; // same origin

// ---------- State ----------
let map;
let currentTile;
let areaMarkers = {};       // name -> L.circleMarker
let areaData = {};          // name -> {lat, lon, risk_score_100, risk_band, confidence}
let routeLayers = [];
let liveOriginCoord = null; // [lat, lng] of the person's exact GPS point, when routing from live location
let lastRouteInfo = null; // { origin, destination, pathCoords, suggestedMinutes } from the last successful search
let currentTrip = null; // { trip_id, share_id, deadline_ts, countdownTimer, pollTimer, locationPushTimer }
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

function haversineKm(lat1, lon1, lat2, lon2) {
  const R = 6371;
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const a = Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

function nearestAreaTo(lat, lon) {
  let best = null, bestDist = Infinity;
  for (const [name, loc] of Object.entries(areaData)) {
    const d = haversineKm(lat, lon, loc.lat, loc.lon);
    if (d < bestDist) { bestDist = d; best = name; }
  }
  return { name: best, distanceKm: bestDist };
}

// ---------- Init ----------
document.addEventListener("DOMContentLoaded", () => {
  initMap();
  loadLocalities();
  updateClock();
  setInterval(updateClock, 30000);
  initSosHold();
  resumeTripIfActive();
  updateEmergencyContactBtnState();

  const saved = localStorage.getItem("saferoute-theme");
  if (saved === "light") setTheme("light");
});

function initMap() {
  map = L.map("map", { zoomControl: false }).setView([21.145, 79.090], 12);
  L.control.zoom({ position: "bottomleft" }).addTo(map);

  // Plain OpenStreetMap tiles: permanently free, no API key or signup ever
  // required. (CARTO's raster basemap tiles, used previously, started
  // requiring a free-but-registered API key in August 2026 - rather than
  // adding that dependency, dark mode below is done with a CSS filter on
  // these same tiles instead of a second tile provider.)
  currentTile = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap contributors",
    maxZoom: 19,
  }).addTo(map);

  applyMapTheme(document.documentElement.getAttribute("data-theme") || "dark");
}

function applyMapTheme(theme) {
  const container = document.getElementById("map");
  if (!container) return;
  container.classList.toggle("map-dark-filter", theme === "dark");
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
    sourceSel.innerHTML = '<option value="">— Select Start Area —</option>' +
      '<option value="__live__">📍 Use My Current Location</option>';
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
  document.getElementById("map")?.classList.toggle("map-dark-filter");
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

  // If routing started from the person's live location, draw the true first
  // leg from their exact GPS point to the route's first real waypoint,
  // instead of starting the line at the nearest area's centroid.
  if (liveOriginCoord) {
    latlngs = [liveOriginCoord, ...latlngs];
  }

  const line = L.polyline(latlngs, {
    color: ROUTE_COLORS[route.category] || "#9aa5c4",
    weight: 5,
    opacity: 0.85,
  }).addTo(map);
  routeLayers.push(line);
  return line;
}

async function findRoutes() {
  const sourceSelValue = document.getElementById("sourceArea").value;
  const destination = document.getElementById("destArea").value;
  const timeSlot = document.getElementById("timeSlot").value;
  const hour = TIME_SLOT_HOUR[timeSlot] ?? 19;

  const resultsEl = document.getElementById("routeResults");
  const cardsEl = document.getElementById("routeCards");
  resultsEl.classList.remove("hidden");
  clearRoutes();

  let origin = sourceSelValue;
  let liveOriginNote = "";
  liveOriginCoord = null;

  if (sourceSelValue === "__live__") {
    cardsEl.innerHTML = '<div class="route-error" style="color:var(--text-dim)">Getting your location…</div>';
    const pos = await getCurrentLocationOnce();
    if (!pos.ok) {
      cardsEl.innerHTML = '<div class="route-error">Could not get your location — check location permission and try again, or pick a start area manually.</div>';
      return;
    }
    updateUserMarker(pos.lat, pos.lng);
    document.getElementById("liveCoords").textContent = `${pos.lat.toFixed(4)}, ${pos.lng.toFixed(4)}`;
    liveOriginCoord = [pos.lat, pos.lng];

    const nearest = nearestAreaTo(pos.lat, pos.lng);
    if (!nearest.name) {
      cardsEl.innerHTML = '<div class="route-error">Could not match your location to a known area.</div>';
      liveOriginCoord = null;
      return;
    }
    origin = nearest.name;
    liveOriginNote = `<div class="route-live-note"><i class="fa-solid fa-location-crosshairs"></i> Using your location — nearest area: <b>${nearest.name}</b> (~${nearest.distanceKm.toFixed(2)} km away)</div>`;
  }

  cardsEl.innerHTML = '<div class="route-error" style="color:var(--text-dim)">Calculating…</div>';
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

    cardsEl.innerHTML = liveOriginNote;
    const bounds = [];
    data.routes.forEach((route) => {
      const card = document.createElement("div");
      card.className = "route-card" + (route.duplicate_of ? " route-card-duplicate" : "");
      card.innerHTML = `
        <span class="route-badge ${route.category}">${route.category}</span>
        ${route.duplicate_of ? '<span class="route-dup-tag">same path</span>' : ""}
        <div class="route-metrics">
          <b>${route.total_time_min} min</b> · ${route.total_distance_km} km<br>
          Mean risk: <b>${route.mean_risk}</b>/10 · Peak risk: <b>${route.peak_risk}</b>/10<br>
          Detour: ${route.detour_percent}%${route.feasible ? "" : " (exceeds limit)"}
        </div>
        <div class="route-explain">${route.explanation}</div>`;
      cardsEl.appendChild(card);
      // Skip drawing a second identical polyline on top of one already drawn.
      if (!route.duplicate_of) {
        const line = drawRoute(route);
        if (line) bounds.push(...line.getLatLngs());
      }
    });
    if (bounds.length) map.fitBounds(bounds, { padding: [40, 40] });

    // Offer trip check-in using the recommended route's timing and path.
    const recommended = data.routes.find((r) => r.category === "recommended") || data.routes[0];
    lastRouteInfo = {
      origin, destination,
      pathCoords: recommended?.path_coords || [],
      suggestedMinutes: Math.ceil((recommended?.total_time_min || 20) + 10),
    };
    document.getElementById("tripDuration").value = lastRouteInfo.suggestedMinutes;
    document.getElementById("tripStartCard").classList.remove("hidden");
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

  // Keep the map's look in sync with the UI theme.
  if (map) {
    applyMapTheme(theme);
    document.getElementById("layerToggleBtn")?.classList.toggle("active-layer", theme === "dark");
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
      const ll = userMarker.getLatLng();
      resolve({ lat: ll.lat, lng: ll.lng, ok: true });
      return;
    }
    if (!navigator.geolocation) {
      resolve({ lat: 21.145, lng: 79.090, ok: false }); // Nagpur center fallback
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({ lat: pos.coords.latitude, lng: pos.coords.longitude, ok: true }),
      () => resolve({ lat: 21.145, lng: 79.090, ok: false }),
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

  const contact = getEmergencyContact();

  try {
    const res = await fetch(`${API}/api/sos`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        lat, lng,
        timestamp: new Date().toISOString(),
        message: "I need help. This is an automatic SOS alert.",
        contact_name: contact?.name || null,
        contact_phone: contact?.phone || null,
      }),
    });
    const data = await res.json();
    const rec = data.sos_record || {};

    if (rec.sms?.sent) {
      overlayText.textContent = contact?.phone
        ? `${contact.name || "Your contact"} was notified by SMS with your location (id ${rec.sos_id}).`
        : `Your emergency contact was notified by SMS with your location (id ${rec.sos_id}).`;
    } else {
      overlayText.textContent = `SOS logged (id ${rec.sos_id || "n/a"}). Real SMS isn't configured on this server, so tap a call button below to reach help directly.`;
    }

    let extraLines = "";
    if (contact?.phone) {
      extraLines += `<div class="area-info-row"><span>Emergency contact</span><a href="tel:${contact.phone}" class="sos-station-call">Call ${contact.name || contact.phone}</a></div>`;
    }
    if (rec.tracking_url) {
      extraLines += `<div class="area-info-row"><span>Live tracking link</span><a href="${rec.tracking_url}" target="_blank" class="sos-station-call">Open</a></div>`;
    }

    const jurisdiction = rec.nearest_police_jurisdiction;
    if (jurisdiction?.area_name) {
      const phoneLine = jurisdiction.phone
        ? jurisdiction.is_hq_fallback
          ? `<a href="tel:${jurisdiction.phone}" class="sos-station-call">Call Nagpur Police HQ: ${jurisdiction.phone}</a><br><span class="sos-station-note">(No verified direct line for ${jurisdiction.area_name} specifically)</span>`
          : `<a href="tel:${jurisdiction.phone}" class="sos-station-call">Call ${jurisdiction.area_name} Station: ${jurisdiction.phone}</a>`
        : `<span class="sos-station-note">No verified direct line for this station — use the numbers below.</span>`;
      stationInfo.innerHTML = extraLines + `</br>` + `</br>` +
        `<i class="fa-solid fa-building-shield"></i> Nearest police jurisdiction: <b>${jurisdiction.area_name}</b> (~${jurisdiction.approx_distance_km} km away).<br>${phoneLine}`;
    } else {
      stationInfo.innerHTML = extraLines;
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

// ---------- Trip check-in ----------
const TRIP_STORAGE_KEY = "saferoute-active-trip";

function saveTripToStorage() {
  if (!currentTrip) {
    localStorage.removeItem(TRIP_STORAGE_KEY);
    return;
  }
  localStorage.setItem(TRIP_STORAGE_KEY, JSON.stringify({
    trip_id: currentTrip.trip_id,
    share_id: currentTrip.share_id,
    deadline_ts: currentTrip.deadline_ts,
  }));
}

function resumeTripIfActive() {
  const saved = localStorage.getItem(TRIP_STORAGE_KEY);
  if (!saved) return;
  try {
    const parsed = JSON.parse(saved);
    currentTrip = { trip_id: parsed.trip_id, share_id: parsed.share_id, deadline_ts: parsed.deadline_ts };
    const shareUrl = `${window.location.origin}/track/${currentTrip.share_id}`;
    document.getElementById("tripShareUrl").value = shareUrl;
    document.getElementById("tripStartCard").classList.add("hidden");
    document.getElementById("tripActiveCard").classList.remove("hidden");
    startTripCountdown();
    startTripLocationPush();
  } catch (e) {
    localStorage.removeItem(TRIP_STORAGE_KEY);
  }
}

async function startTrip() {
  if (!lastRouteInfo) return;
  const duration = parseFloat(document.getElementById("tripDuration").value);
  if (!duration || duration <= 0) {
    alert("Enter a valid number of minutes.");
    return;
  }

  const pos = await getCurrentLocationOnce();
  const lat = pos.ok ? pos.lat : (areaData[lastRouteInfo.origin]?.lat || 21.145);
  const lng = pos.ok ? pos.lng : (areaData[lastRouteInfo.origin]?.lon || 79.090);

  try {
    const contact = getEmergencyContact();
    const res = await fetch(`${API}/api/trip/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        origin: lastRouteInfo.origin,
        destination: lastRouteInfo.destination,
        duration_min: duration,
        lat, lng,
        path_coords: lastRouteInfo.pathCoords,
        contact_name: contact?.name || null,
        contact_phone: contact?.phone || null,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Could not start trip");

    const shareUrl = `${window.location.origin}${data.share_path}`;
    document.getElementById("tripShareUrl").value = shareUrl;
    document.getElementById("tripStartCard").classList.add("hidden");
    document.getElementById("tripActiveCard").classList.remove("hidden");

    currentTrip = { trip_id: data.trip_id, share_id: data.share_id, deadline_ts: data.deadline_ts };
    saveTripToStorage();
    startTripCountdown();
    startTripLocationPush();
  } catch (err) {
    alert("Could not start trip check-in: " + err.message);
  }
}

function startTripCountdown() {
  const el = document.getElementById("tripCountdown");
  const sub = document.getElementById("tripCardSub");
  let alertShown = false;

  const tick = () => {
    if (!currentTrip) return;
    const remainingMs = currentTrip.deadline_ts * 1000 - Date.now();
    if (remainingMs > 0) {
      const mins = Math.floor(remainingMs / 60000);
      const secs = Math.floor((remainingMs % 60000) / 1000);
      el.textContent = `${mins}:${secs.toString().padStart(2, "0")}`;
      el.classList.remove("overdue");
    } else {
      el.textContent = "0:00";
      el.classList.add("overdue");
      sub.textContent = "Time's up — checking whether an alert has gone out…";
    }
  };
  tick();
  currentTrip.countdownTimer = setInterval(tick, 1000);

  // Poll the trip's real status so the UI reflects it once the
  // server-side auto-alert has actually fired - this is what actually
  // confirms the alert went out, not just the local countdown hitting 0.
  currentTrip.pollTimer = setInterval(async () => {
    if (!currentTrip) return;
    try {
      const res = await fetch(`${API}/api/trip/share/${currentTrip.share_id}`);
      const data = await res.json();
      if (data.status === "auto_alerted") {
        sub.textContent = "Automatic alert sent — your last location and nearest station were shared.";
        if (!alertShown) {
          alertShown = true;
          showTripAlertOverlay(data.nearest_police_jurisdiction);
        }
      } else if (data.status === "arrived_safe") {
        // Checked in from another tab/device - stop tracking here too.
        stopTripTracking();
      }
    } catch (e) { /* ignore transient poll errors */ }
  }, 5000);
}

function showTripAlertOverlay(jurisdiction) {
  const info = document.getElementById("tripAlertStationInfo");
  if (jurisdiction?.area_name) {
    info.innerHTML = `<i class="fa-solid fa-building-shield"></i> Nearest jurisdiction: <b>${jurisdiction.area_name}</b>` +
      (jurisdiction.phone ? `<br><a href="tel:${jurisdiction.phone}" class="sos-station-call">Call: ${jurisdiction.phone}</a>` : "");
  } else {
    info.innerHTML = "";
  }
  document.getElementById("tripAlertOverlay").classList.remove("hidden");
}
function closeTripAlertOverlay() {
  document.getElementById("tripAlertOverlay").classList.add("hidden");
}

function startTripLocationPush() {
  currentTrip.locationPushTimer = setInterval(async () => {
    if (!currentTrip) return;
    const pos = await getCurrentLocationOnce();
    if (!pos.ok) return;
    fetch(`${API}/api/trip/${currentTrip.trip_id}/location`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lat: pos.lat, lng: pos.lng }),
    }).catch(() => {});
  }, 20000);
}

function stopTripTracking() {
  if (currentTrip) {
    clearInterval(currentTrip.countdownTimer);
    clearInterval(currentTrip.pollTimer);
    clearInterval(currentTrip.locationPushTimer);
  }
  currentTrip = null;
  saveTripToStorage();
  document.getElementById("tripActiveCard").classList.add("hidden");
  document.getElementById("tripStartCard").classList.remove("hidden");
}

async function checkInTrip() {
  if (!currentTrip) return;
  const btn = document.querySelector(".trip-safe-btn");
  btn?.classList.add("confirmed");

  try {
    await fetch(`${API}/api/trip/${currentTrip.trip_id}/checkin`, { method: "POST" });
  } catch (e) { /* best effort */ }

  showToast("✅ Done — you arrived safely!");
  setTimeout(() => {
    btn?.classList.remove("confirmed");
    stopTripTracking();
  }, 1400);
}

function showToast(message) {
  let toast = document.getElementById("appToast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "appToast";
    toast.className = "app-toast";
    document.body.appendChild(toast);
  }
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(toast._hideTimer);
  toast._hideTimer = setTimeout(() => toast.classList.remove("show"), 2800);
}

function copyTripShareLink() {
  const input = document.getElementById("tripShareUrl");
  input.select();
  navigator.clipboard?.writeText(input.value).catch(() => {
    document.execCommand("copy");
  });
}

// ---------- Emergency contact (stored client-side only) ----------
const CONTACT_STORAGE_KEY = "saferoute-emergency-contact";

function getEmergencyContact() {
  const raw = localStorage.getItem(CONTACT_STORAGE_KEY);
  if (!raw) return null;
  try { return JSON.parse(raw); } catch (e) { return null; }
}

function openEmergencyContactModal() {
  const contact = getEmergencyContact();
  document.getElementById("contactNameInput").value = contact?.name || "";
  // Show just the 10-digit local number; the +91 prefix is fixed in the UI.
  const localDigits = (contact?.phone || "").replace(/^\+91/, "");
  document.getElementById("contactPhoneInput").value = localDigits;
  document.getElementById("contactModal").classList.remove("hidden");
}
function closeEmergencyContactModal() {
  document.getElementById("contactModal").classList.add("hidden");
}

function saveEmergencyContact() {
  const name = document.getElementById("contactNameInput").value.trim();
  let digits = document.getElementById("contactPhoneInput").value.trim().replace(/\D/g, "");
  // Be forgiving if someone types the country code again out of habit
  // (the +91 prefix is already fixed outside the input).
  if (digits.length === 12 && digits.startsWith("91")) digits = digits.slice(2);
  else if (digits.length === 11 && digits.startsWith("0")) digits = digits.slice(1);

  if (digits.length !== 10) {
    alert("Enter a valid 10-digit phone number (without the country code).");
    return;
  }
  const phone = `+91${digits}`;
  localStorage.setItem(CONTACT_STORAGE_KEY, JSON.stringify({ name, phone }));
  updateEmergencyContactBtnState();
  closeEmergencyContactModal();
}

function clearEmergencyContact() {
  localStorage.removeItem(CONTACT_STORAGE_KEY);
  document.getElementById("contactNameInput").value = "";
  document.getElementById("contactPhoneInput").value = "";
  updateEmergencyContactBtnState();
}

function updateEmergencyContactBtnState() {
  const btn = document.getElementById("emergencyContactBtn");
  const contact = getEmergencyContact();
  if (btn) {
    btn.classList.toggle("contact-set", !!contact?.phone);
    btn.title = contact?.phone ? `Emergency contact: ${contact.name || contact.phone}` : "Emergency Contact (not set)";
  }
}
