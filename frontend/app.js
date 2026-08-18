const form = document.getElementById("trip-form");
const planBtn = document.getElementById("plan-btn");
const statusEl = document.getElementById("status");
const summaryEl = document.getElementById("summary");
const bookingLinksEl = document.getElementById("booking-links");
const itineraryEl = document.getElementById("itinerary");
const updatesEl = document.getElementById("updates");
const updatesListEl = document.getElementById("updates-list");
const checkUpdatesBtn = document.getElementById("check-updates-btn");
const saveTripRow = document.getElementById("save-trip-row");
const saveTripEmail = document.getElementById("save-trip-email");
const saveTripBtn = document.getElementById("save-trip-btn");
const saveTripStatus = document.getElementById("save-trip-status");
const notifBell = document.getElementById("notif-bell");
const notifBadge = document.getElementById("notif-badge");
const notifPanel = document.getElementById("notif-panel");
const notifList = document.getElementById("notif-list");

const NOTIFICATION_POLL_MS = 30000;

function escapeHtml(unsafe) {
  if (unsafe == null) return "";
  return String(unsafe)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}


const CATEGORY_COLOR = {
  origin: "#92a0c0",
  destination: "#4fa3ff",
  hotel: "#35d49a",
  activity: "#ffb454",
  restaurant: "#ff7ad9",
};

let map;
let markers = [];
let routeLine;
let currentPlan = null;
let replanTimer = null;

function initMap() {
  map = L.map("map", { scrollWheelZoom: true }).setView([39.5, -98.35], 4);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap contributors",
    maxZoom: 18,
  }).addTo(map);
}

function setDefaultDates() {
  const start = new Date();
  start.setDate(start.getDate() + 30);
  const end = new Date(start);
  end.setDate(end.getDate() + 3);
  form.start_date.value = start.toISOString().slice(0, 10);
  form.end_date.value = end.toISOString().slice(0, 10);
}

function setStatus(message, isError = false) {
  statusEl.hidden = !message;
  statusEl.textContent = message;
  statusEl.classList.toggle("error", isError);
}

function readFormData() {
  const data = Object.fromEntries(new FormData(form).entries());
  data.travelers = parseInt(data.travelers, 10);
  data.budget_usd = parseFloat(data.budget_usd);
  return data;
}

async function planTrip(payload) {
  const res = await fetch("/api/plan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Request failed (${res.status})`);
  }
  return res.json();
}

async function checkUpdates() {
  if (!currentPlan) return;
  checkUpdatesBtn.disabled = true;
  checkUpdatesBtn.textContent = "Checking...";
  try {
    const res = await fetch("/api/monitor", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan: currentPlan }),
    });
    const data = await res.json();
    renderUpdates(data);
  } catch (e) {
    renderUpdates({ has_updates: false, updates: [], error: e.message });
  } finally {
    checkUpdatesBtn.disabled = false;
    checkUpdatesBtn.textContent = "Check this plan now (manual)";
  }
}

async function saveTrip() {
  if (!currentPlan) return;
  saveTripBtn.disabled = true;
  saveTripBtn.textContent = "Saving...";
  try {
    const res = await fetch("/api/trips", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan: currentPlan, email: saveTripEmail.value || null }),
    });
    if (!res.ok) throw new Error(`Save failed (${res.status})`);
    const data = await res.json();
    saveTripStatus.textContent = `Saved (trip #${data.trip_id}) — the agent will check this automatically in the background.`;
  } catch (e) {
    saveTripStatus.textContent = `Couldn't save: ${e.message}`;
  } finally {
    saveTripBtn.disabled = false;
    saveTripBtn.textContent = "💾 Save & monitor this trip";
  }
}

async function fetchNotifications() {
  try {
    const res = await fetch("/api/notifications?unread_only=true");
    const notifications = await res.json();
    renderNotifications(notifications);
  } catch (e) {
    // silent — polling failures shouldn't interrupt the rest of the app
  }
}

function renderNotifications(notifications) {
  notifBadge.hidden = notifications.length === 0;
  notifBadge.textContent = notifications.length;

  notifList.innerHTML = "";
  if (notifications.length === 0) {
    const div = document.createElement("div");
    div.className = "notif-empty";
    div.textContent = "No new updates. The background scheduler checks saved trips automatically.";
    notifList.appendChild(div);
    return;
  }

  for (const n of notifications) {
    const div = document.createElement("div");
    div.className = "notif-item";
    const when = new Date(n.created_at).toLocaleString();
    div.innerHTML = `
      <div class="meta">${escapeHtml(n.origin_city)} → ${escapeHtml(n.destination_city)} · ${escapeHtml(when)}</div>
      <div>${escapeHtml(n.message)}</div>
      <div class="notif-item-actions"></div>
    `;
    const actions = div.querySelector(".notif-item-actions");
    if (n.booking_link) {
      const link = document.createElement("a");
      link.href = n.booking_link;
      link.target = "_blank";
      link.rel = "noopener";
      link.className = "link-btn";
      link.textContent = "Check real prices →";
      actions.appendChild(link);
    }
    const dismiss = document.createElement("button");
    dismiss.className = "link-btn";
    dismiss.textContent = "Mark read";
    dismiss.addEventListener("click", async () => {
      await fetch(`/api/notifications/${n.id}/read`, { method: "POST" });
      fetchNotifications();
    });
    actions.appendChild(dismiss);
    notifList.appendChild(div);
  }
}

function renderUpdates(data) {
  updatesEl.hidden = false;
  updatesListEl.innerHTML = "";
  if (!data.updates || data.updates.length === 0) {
    const div = document.createElement("div");
    div.className = "update-card info";
    div.textContent = "No changes worth surfacing right now — plan still looks good.";
    updatesListEl.appendChild(div);
    return;
  }
  for (const u of data.updates) {
    const div = document.createElement("div");
    div.className = "update-card";
    div.innerHTML = `<div>${escapeHtml(u.message)}</div>`;
    if (u.booking_link) {
      const link = document.createElement("a");
      link.href = u.booking_link;
      link.target = "_blank";
      link.rel = "noopener";
      link.className = "link-btn";
      link.textContent = "Check real prices →";
      div.appendChild(link);
    }
    updatesListEl.appendChild(div);
  }
}

function clearMap() {
  markers.forEach((m) => map.removeLayer(m));
  markers = [];
  if (routeLine) {
    map.removeLayer(routeLine);
    routeLine = null;
  }
}

function renderMap(plan) {
  clearMap();
  const bounds = [];

  for (const pin of plan.map_pins) {
    const color = CATEGORY_COLOR[pin.category] || "#e8ecf5";
    const marker = L.circleMarker([pin.lat, pin.lon], {
      radius: pin.category === "destination" || pin.category === "origin" ? 9 : 7,
      color,
      fillColor: color,
      fillOpacity: 0.85,
      weight: 2,
    }).addTo(map);
    marker.bindPopup(`<b>${escapeHtml(pin.label)}</b><br/>${escapeHtml(pin.category)}`);
    markers.push(marker);
    bounds.push([pin.lat, pin.lon]);
  }

  const origin = plan.map_pins.find((p) => p.category === "origin");
  const destination = plan.map_pins.find((p) => p.category === "destination");
  if (origin && destination) {
    routeLine = L.polyline(
      [
        [origin.lat, origin.lon],
        [destination.lat, destination.lon],
      ],
      { color: "#4fa3ff", weight: 2, dashArray: "6 8", opacity: 0.7 }
    ).addTo(map);
  }

  if (bounds.length) {
    map.fitBounds(bounds, { padding: [40, 40] });
  }
}

function renderSummary(plan) {
  summaryEl.hidden = false;
  const budgetClass = plan.within_budget ? "within-budget" : "over-budget";
  summaryEl.innerHTML = `
    <div class="stat">
      <div class="label">Destination</div>
      <div class="value">${escapeHtml(plan.destination_city)}, ${escapeHtml(plan.destination_country)}</div>
    </div>
    <div class="stat">
      <div class="label">Distance</div>
      <div class="value">${plan.distance_km.toLocaleString()} km</div>
    </div>
    <div class="stat ${budgetClass}">
      <div class="label">Estimated cost</div>
      <div class="value">$${plan.total_estimated_cost_low_usd.toLocaleString()}–$${plan.total_estimated_cost_high_usd.toLocaleString()} / $${plan.budget_usd.toLocaleString()}</div>
    </div>
    <div class="stat">
      <div class="label">Flight + hotel</div>
      <div class="value">$${plan.flight.estimated_price_low_usd.toFixed(0)}–$${plan.flight.estimated_price_high_usd.toFixed(0)} · $${plan.hotel.estimated_price_low_usd.toFixed(0)}–$${plan.hotel.estimated_price_high_usd.toFixed(0)}/night</div>
    </div>
  `;

  bookingLinksEl.hidden = false;
  bookingLinksEl.innerHTML = `
    <a href="${escapeHtml(plan.flight.booking_link)}" target="_blank" rel="noopener" class="link-btn primary">✈️ View live flights & book</a>
    <a href="${escapeHtml(plan.hotel.booking_link)}" target="_blank" rel="noopener" class="link-btn primary">🏨 View live hotels & book</a>
  `;
}

function renderItinerary(plan) {
  itineraryEl.innerHTML = "";

  const reasoning = document.createElement("div");
  reasoning.className = "reasoning";
  reasoning.textContent = plan.reasoning_summary;
  itineraryEl.appendChild(reasoning);

  for (const day of plan.days) {
    const card = document.createElement("div");
    card.className = "day-card";
    card.innerHTML = `
      <h3>Day ${day.day_number} · ${escapeHtml(day.date)}</h3>
      <div class="weather">${escapeHtml(day.weather_summary)}</div>
      <ul>${day.activities.map((a) => placeRecHtml(a)).join("")}</ul>
      <div class="restaurant">🍽️ ${placeRecHtml(day.restaurant, true)}</div>
      ${day.notes ? `<div class="notes">${escapeHtml(day.notes)}</div>` : ""}
    `;
    itineraryEl.appendChild(card);
  }
}

function placeRecHtml(place, inline = false) {
  const link = `<a href="${escapeHtml(place.maps_link)}" target="_blank" rel="noopener" class="place-link" title="View on Google Maps">${escapeHtml(place.name)} ↗</a>`;
  return inline ? link : `<li>${link}</li>`;
}

async function submitPlan() {
  const payload = readFormData();
  planBtn.disabled = true;
  planBtn.textContent = "Planning...";
  setStatus("Agent is researching flights, hotels, weather, and activities...");
  try {
    const plan = await planTrip(payload);
    currentPlan = plan;
    renderSummary(plan);
    renderMap(plan);
    renderItinerary(plan);
    checkUpdatesBtn.hidden = false;
    saveTripRow.hidden = false;
    saveTripStatus.textContent = "";
    setStatus("Plan ready.");
  } catch (e) {
    setStatus(e.message, true);
  } finally {
    planBtn.disabled = false;
    planBtn.textContent = "Plan my trip";
  }
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  submitPlan();
});

// "Live" updates: once a plan exists, changing any field auto-replans after a
// short debounce, so edits reflect without needing to resubmit manually.
form.addEventListener("change", () => {
  if (!currentPlan) return;
  clearTimeout(replanTimer);
  setStatus("Inputs changed — updating plan...");
  replanTimer = setTimeout(submitPlan, 900);
});

checkUpdatesBtn.addEventListener("click", checkUpdates);
saveTripBtn.addEventListener("click", saveTrip);
notifBell.addEventListener("click", () => {
  notifPanel.hidden = !notifPanel.hidden;
});

initMap();
setDefaultDates();
fetchNotifications();
setInterval(fetchNotifications, NOTIFICATION_POLL_MS);
