const form = document.getElementById("trip-form");
const planBtn = document.getElementById("plan-btn");
const statusEl = document.getElementById("status");
const resultsTitleEl = document.getElementById("results-title");
const logisticsSectionEl = document.getElementById("logistics-section");
const logisticsStatsEl = document.getElementById("logistics-stats");
const costSectionEl = document.getElementById("cost-section");
const costStatsEl = document.getElementById("cost-stats");
const dailyPlanSectionEl = document.getElementById("daily-plan-section");
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
const emptyStateEl = document.getElementById("empty-state");
const loadingSkeletonEl = document.getElementById("loading-skeleton");
const errorBannerEl = document.getElementById("error-banner");
const errorBannerTextEl = document.getElementById("error-banner-text");
const errorBannerDismissBtn = document.getElementById("error-banner-dismiss");
const dayForm = document.getElementById("day-form");
const dayPlanBtn = document.getElementById("day-plan-btn");
const dayStatusEl = document.getElementById("day-status");
const watchForm = document.getElementById("watch-form");
const watchBtn = document.getElementById("watch-btn");
const watchStatusEl = document.getElementById("watch-status");
const watchResultEl = document.getElementById("watch-result");
const watchItemsEl = document.getElementById("watch-items");
const wishlistForm = document.getElementById("wishlist-form");
const wishlistBtn = document.getElementById("wishlist-btn");
const wishlistStatusEl = document.getElementById("wishlist-status");
const wishlistResultEl = document.getElementById("wishlist-result");
const wishlistItemsEl = document.getElementById("wishlist-items");

const NOTIFICATION_POLL_MS = 30000;
const CITY_SEARCH_DEBOUNCE_MS = 250;

// No accounts in this build — a persistent per-browser ID is enough to keep
// one visitor's saved trips/notifications from mixing with another's. The id
// itself is issued and HMAC-signed by the server (see backend/auth.py) —
// this used to just be a bare crypto.randomUUID() the browser made up on its
// own and the server trusted outright, which meant any client could set the
// header to any value and read or modify a different visitor's data. Now the
// server only accepts an id it actually issued and signed.
const CLIENT_ID_STORAGE_KEY = "trip_planner_client_id";
let CLIENT_ID = null;
let clientIdReissued = false;

async function ensureClientId() {
  const stored = localStorage.getItem(CLIENT_ID_STORAGE_KEY);
  if (stored) {
    CLIENT_ID = stored;
    return;
  }
  const res = await fetch("/api/client-id", { method: "POST" });
  const data = await res.json();
  CLIENT_ID = data.client_id;
  localStorage.setItem(CLIENT_ID_STORAGE_KEY, CLIENT_ID);
}

// fetch wrapper that attaches the signed client id and recovers once if the
// server ever rejects it (e.g. the dev db — and with it the signing secret —
// got wiped since this id was issued) by fetching a fresh one and retrying,
// instead of every scoped request failing for the rest of the session.
async function authedFetch(url, options = {}) {
  if (!CLIENT_ID) await ensureClientId();
  const opts = { ...options, headers: { ...(options.headers || {}), "X-Client-Id": CLIENT_ID } };
  const res = await fetch(url, opts);
  if (res.status === 401 && !clientIdReissued) {
    clientIdReissued = true;
    localStorage.removeItem(CLIENT_ID_STORAGE_KEY);
    await ensureClientId();
    return authedFetch(url, options);
  }
  return res;
}

const PRESETS = {
  denver: {
    origin_city: "Austin, Texas",
    destination: "Denver, Colorado",
    travelers: 2,
    budget: 1500,
    currency: "USD",
    interests: "hiking, live music, food",
    transportation: "flight",
    accommodation: "mid-range hotel",
    dietary_needs: "none",
  },
  asheville: {
    origin_city: "Charlotte, North Carolina",
    destination: "",
    travelers: 2,
    budget: 1200,
    currency: "USD",
    interests: "live music, craft food, walkable downtown",
    transportation: "flight",
    accommodation: "boutique",
    dietary_needs: "vegetarian",
  },
};

// Kept in sync conceptually with backend/src/trip_agent/currency.py's
// SUPPORTED_CURRENCIES — small enough duplication that a shared endpoint
// round-trip isn't worth it for a static list.
const CURRENCY_SYMBOLS = {
  USD: "$", EUR: "€", GBP: "£", JPY: "¥", CAD: "C$", AUD: "A$",
  CHF: "Fr", CNY: "¥", INR: "₹", MXN: "$", BRL: "R$", SGD: "S$",
};

function formatMoney(amount, currencyCode) {
  const symbol = CURRENCY_SYMBOLS[currencyCode] || currencyCode + " ";
  return `${symbol}${amount.toLocaleString()}`;
}

// Every render function below builds markup with innerHTML template
// literals, and a lot of what gets interpolated isn't ours: city/place names
// and reasoning text come from the LLM, event names/venues come from the
// Ticketmaster API, geocoding results come from Open-Meteo. None of that is
// sanitized before it reaches the browser, so anything placed into HTML
// (not set via .textContent or a DOM property like .href) needs to go
// through this first.
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
  origin: "#6b6f85",
  destination: "#4338ca",
  hotel: "#0f766e",
  activity: "#b45309",
  restaurant: "#b3261e",
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

function toLocalDateString(date) {
  const offsetMs = date.getTimezoneOffset() * 60000;
  return new Date(date.getTime() - offsetMs).toISOString().slice(0, 10);
}

function setDefaultDates() {
  const todayStr = toLocalDateString(new Date());
  form.start_date.min = todayStr;
  form.end_date.min = todayStr;

  const start = new Date();
  start.setDate(start.getDate() + 30);
  const end = new Date(start);
  end.setDate(end.getDate() + 3);
  form.start_date.value = toLocalDateString(start);
  form.end_date.value = toLocalDateString(end);

  wishlistForm.wl_earliest_date.min = todayStr;
  wishlistForm.wl_latest_date.min = todayStr;
  wishlistForm.wl_earliest_date.value = todayStr;
  const wlLatest = new Date();
  wlLatest.setDate(wlLatest.getDate() + 120);
  wishlistForm.wl_latest_date.value = toLocalDateString(wlLatest);

  dayForm.day_date.min = todayStr;
  dayForm.day_date.value = todayStr;
}

// Keeps the return-date picker from allowing a date before departure, and
// the departure picker from allowing a date before today — both are enforced
// natively by the browser (past/invalid dates render greyed out and
// unselectable), this just keeps the `min` bounds in sync as the user picks.
function setupDateGuards() {
  form.start_date.addEventListener("change", () => {
    form.end_date.min = form.start_date.value || toLocalDateString(new Date());
    if (form.end_date.value && form.end_date.value < form.end_date.min) {
      form.end_date.value = form.end_date.min;
    }
  });

  wishlistForm.wl_earliest_date.addEventListener("change", () => {
    const min = wishlistForm.wl_earliest_date.value || toLocalDateString(new Date());
    wishlistForm.wl_latest_date.min = min;
    if (wishlistForm.wl_latest_date.value && wishlistForm.wl_latest_date.value < min) {
      wishlistForm.wl_latest_date.value = min;
    }
  });
}

function attachCityAutocomplete(input, dropdown) {
  let debounceTimer = null;
  let requestId = 0;
  let items = [];
  let activeIndex = -1;

  function close() {
    dropdown.hidden = true;
    dropdown.innerHTML = "";
    items = [];
    activeIndex = -1;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
  }

  function renderItems(results) {
    items = results;
    activeIndex = -1;
    if (items.length === 0) {
      dropdown.innerHTML = `<div class="autocomplete-empty">No matching cities</div>`;
      dropdown.hidden = false;
      input.setAttribute("aria-expanded", "true");
      return;
    }
    dropdown.innerHTML = items
      .map(
        (c, i) => `
      <div class="autocomplete-item" id="${dropdown.id}-option-${i}" role="option" aria-selected="false" data-index="${i}">
        <span class="city-name">${escapeHtml(c.name)}</span>
        <span class="city-region">${c.admin1 ? escapeHtml(c.admin1) + ", " : ""}${escapeHtml(c.country)}</span>
      </div>`
      )
      .join("");
    dropdown.hidden = false;
    input.setAttribute("aria-expanded", "true");
  }

  function highlight() {
    Array.from(dropdown.children).forEach((el, i) => {
      const isActive = i === activeIndex;
      el.classList.toggle("active", isActive);
      el.setAttribute("aria-selected", String(isActive));
    });
    if (activeIndex >= 0) {
      input.setAttribute("aria-activedescendant", `${dropdown.id}-option-${activeIndex}`);
    } else {
      input.removeAttribute("aria-activedescendant");
    }
  }

  function select(index) {
    const city = items[index];
    if (!city) return;
    input.value = city.label;
    close();
  }

  async function search(query) {
    const myRequestId = ++requestId;
    try {
      const res = await fetch(`/api/cities?q=${encodeURIComponent(query)}`);
      const results = await res.json();
      if (myRequestId !== requestId) return;
      renderItems(results);
    } catch (e) {
      if (myRequestId !== requestId) return;
      close();
    }
  }

  input.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    const query = input.value.trim();
    if (query.length < 2) {
      close();
      return;
    }
    debounceTimer = setTimeout(() => search(query), CITY_SEARCH_DEBOUNCE_MS);
  });

  input.addEventListener("keydown", (e) => {
    if (dropdown.hidden || items.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      activeIndex = Math.min(activeIndex + 1, items.length - 1);
      highlight();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      activeIndex = Math.max(activeIndex - 1, 0);
      highlight();
    } else if (e.key === "Enter" && activeIndex >= 0) {
      e.preventDefault();
      select(activeIndex);
    } else if (e.key === "Escape") {
      close();
    }
  });

  // mousedown (not click) fires before the input's blur, so selection
  // registers before the dropdown gets closed by the blur handler below
  dropdown.addEventListener("mousedown", (e) => {
    const item = e.target.closest(".autocomplete-item");
    if (!item) return;
    e.preventDefault();
    select(parseInt(item.dataset.index, 10));
  });

  input.addEventListener("blur", () => {
    setTimeout(close, 150);
  });
}

function setStatus(message, isError = false) {
  statusEl.hidden = !message;
  statusEl.textContent = message;
  statusEl.classList.toggle("error", isError);
}

function showError(message) {
  errorBannerEl.hidden = false;
  errorBannerTextEl.textContent = message;
}

function hideError() {
  errorBannerEl.hidden = true;
}

function applyPreset(name) {
  const preset = PRESETS[name];
  if (!preset) return;
  for (const [key, value] of Object.entries(preset)) {
    if (form.elements[key]) form.elements[key].value = value;
  }
  submitPlan();
}

function readFormData() {
  const data = Object.fromEntries(new FormData(form).entries());
  data.travelers = parseInt(data.travelers, 10);
  data.budget = parseFloat(data.budget);
  return data;
}

// Streams newline-delimited progress events from the agent while it works
// (which tool it's currently calling) instead of one long silent wait, ending
// with a "done" event carrying the finished plan. Shared by the trip planner
// and the day planner — only the endpoint and headers differ.
async function streamPlan(endpoint, payload, headers, onProgress) {
  const res = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Request failed (${res.status})`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalPlan = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop(); // last entry may be a partial line — keep for next chunk
    for (const line of lines) {
      if (!line.trim()) continue;
      const event = JSON.parse(line);
      if (event.type === "progress") {
        onProgress(event.message);
      } else if (event.type === "done") {
        finalPlan = event.plan;
      } else if (event.type === "error") {
        throw new Error(event.message);
      }
    }
  }

  if (!finalPlan) throw new Error("Stream ended without a completed plan");
  return finalPlan;
}

// Guards against the rare case of a form being submitted before the
// page-load ensureClientId() call has resolved — a no-op once it has, since
// ensureClientId short-circuits instantly when CLIENT_ID is already set.
async function planTripStream(payload, onProgress) {
  if (!CLIENT_ID) await ensureClientId();
  return streamPlan("/api/plan/stream", payload, { "X-Client-Id": CLIENT_ID }, onProgress);
}

async function planDayStream(payload, onProgress) {
  // Sent even though the day plan itself isn't scoped/saved anywhere — the
  // server uses it as the rate-limit key (see backend/ratelimit.py) instead
  // of falling back to IP, which would over-throttle everyone behind the
  // same NAT/office network.
  if (!CLIENT_ID) await ensureClientId();
  return streamPlan("/api/day-plan/stream", payload, { "X-Client-Id": CLIENT_ID }, onProgress);
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
    const res = await authedFetch("/api/trips", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan: currentPlan, email: saveTripEmail.value || null }),
    });
    if (!res.ok) throw new Error(`Save failed (${res.status})`);
    const data = await res.json();
    saveTripStatus.textContent = `Saved (trip #${data.trip_id}) — the agent will check this automatically in the background.`;
    fetchTrips();
  } catch (e) {
    saveTripStatus.textContent = `Couldn't save: ${e.message}`;
  } finally {
    saveTripBtn.disabled = false;
    saveTripBtn.textContent = "Save & monitor this trip";
  }
}

async function fetchNotifications() {
  try {
    const res = await authedFetch("/api/notifications?unread_only=true");
    const notifications = await res.json();
    renderNotifications(notifications);
  } catch (e) {
    // silent — polling failures shouldn't interrupt the rest of the app
  }
}

// Category is conveyed by the colored left border (see .notif-item--* in
// style.css) rather than an icon — text-first, no decorative glyphs.
const NOTIF_TYPE_META = {
  weather_change: { cls: "notif-item--weather" },
  flight_price_reminder: { cls: "notif-item--price" },
  hotel_price_reminder: { cls: "notif-item--price" },
  wishlist_outlook: { cls: "notif-item--price" },
  wishlist_expired: { cls: "notif-item--expired" },
  trip_feedback_request: { cls: "notif-item--feedback" },
  local_watch_new_events: { cls: "notif-item--local-watch" },
};

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
    const typeMeta = NOTIF_TYPE_META[n.type] || { cls: "" };
    div.className = `notif-item ${typeMeta.cls}`;
    const when = new Date(n.created_at).toLocaleString();

    if (n.type === "trip_feedback_request") {
      div.appendChild(renderFeedbackRequest(n, when));
      notifList.appendChild(div);
      continue;
    }

    const metaLabel = n.origin_city ? `${n.origin_city} → ${n.destination_city}` : n.destination_city;
    div.innerHTML = `
      <div class="meta">${escapeHtml(metaLabel)} · ${escapeHtml(when)}</div>
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
      link.textContent = n.type === "local_watch_new_events" ? "View tickets →" : "Check real prices →";
      actions.appendChild(link);
    }
    const dismiss = document.createElement("button");
    dismiss.className = "link-btn";
    dismiss.textContent = "Mark read";
    dismiss.addEventListener("click", async () => {
      await authedFetch(`/api/notifications/${n.id}/read`, { method: "POST" });
      fetchNotifications();
    });
    actions.appendChild(dismiss);
    notifList.appendChild(div);
  }
}

// Post-trip loop: instead of the usual message+link layout, this notification
// type collects a rating (+ optional free text) and submits real feedback
// that later gets woven into planning prompts — see agent.py.
function renderFeedbackRequest(n, when) {
  const wrap = document.createElement("div");
  wrap.innerHTML = `
    <div class="meta">${escapeHtml(n.origin_city)} → ${escapeHtml(n.destination_city)} · ${escapeHtml(when)}</div>
    <div>${escapeHtml(n.message)}</div>
    <div class="feedback-rating"></div>
    <textarea class="feedback-text" rows="2" placeholder="Optional: what stood out?"></textarea>
    <div class="feedback-hint"></div>
    <div class="notif-item-actions"></div>
  `;

  const ratingEl = wrap.querySelector(".feedback-rating");
  let selectedRating = 0;
  const stars = [];
  for (let i = 1; i <= 5; i++) {
    const star = document.createElement("button");
    star.type = "button";
    star.className = "star-btn";
    star.textContent = "★";
    star.setAttribute("aria-label", `Rate ${i} out of 5`);
    star.addEventListener("click", () => {
      selectedRating = i;
      stars.forEach((s, idx) => s.classList.toggle("selected", idx < selectedRating));
      wrap.querySelector(".feedback-hint").textContent = "";
    });
    stars.push(star);
    ratingEl.appendChild(star);
  }

  const submitBtn = document.createElement("button");
  submitBtn.className = "link-btn primary";
  submitBtn.textContent = "Submit feedback";
  submitBtn.addEventListener("click", async () => {
    if (!selectedRating) {
      wrap.querySelector(".feedback-hint").textContent = "Pick a rating first.";
      return;
    }
    submitBtn.disabled = true;
    await authedFetch(`/api/trips/${n.trip_id}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rating: selectedRating, feedback_text: wrap.querySelector(".feedback-text").value || null }),
    });
    await authedFetch(`/api/notifications/${n.id}/read`, { method: "POST" });
    fetchNotifications();
  });
  wrap.querySelector(".notif-item-actions").appendChild(submitBtn);

  return wrap;
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
    const color = CATEGORY_COLOR[pin.category] || "#14162b";
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
      { color: "#4338ca", weight: 2, dashArray: "6 8", opacity: 0.75 }
    ).addTo(map);
  }

  if (bounds.length) {
    map.fitBounds(bounds, { padding: [40, 40] });
  }
}

function renderSummary(plan) {
  resultsTitleEl.textContent = "Trip Overview";
  const budgetClass = plan.within_budget ? "within-budget" : "over-budget";

  logisticsSectionEl.hidden = false;
  logisticsStatsEl.innerHTML = `
    <div class="stat">
      <div class="label">Destination</div>
      <div class="value">${escapeHtml(plan.destination_city)}, ${escapeHtml(plan.destination_country)}</div>
    </div>
    <div class="stat">
      <div class="label">Distance</div>
      <div class="value">${plan.distance_km.toLocaleString()} km</div>
    </div>
  `;

  costSectionEl.hidden = false;
  costStatsEl.innerHTML = `
    <div class="stat ${budgetClass}">
      <div class="label">Estimated cost</div>
      <div class="value">${formatMoney(plan.total_estimated_cost_low, plan.currency)}–${formatMoney(plan.total_estimated_cost_high, plan.currency)} / ${formatMoney(plan.budget, plan.currency)}</div>
    </div>
    <div class="stat">
      <div class="label">${plan.transportation === "drive" ? "Driving + hotel" : "Flight + hotel"}</div>
      <div class="value">${formatMoney(plan.flight.estimated_price_low, plan.currency)}–${formatMoney(plan.flight.estimated_price_high, plan.currency)} · ${formatMoney(plan.hotel.estimated_price_low, plan.currency)}–${formatMoney(plan.hotel.estimated_price_high, plan.currency)}/night</div>
    </div>
  `;

  bookingLinksEl.hidden = false;
  const travelLinkLabel = plan.transportation === "drive" ? "View driving directions" : "View live flights & book";
  bookingLinksEl.innerHTML = `
    <a href="${escapeHtml(plan.flight.booking_link)}" target="_blank" rel="noopener" class="link-btn primary">${travelLinkLabel}</a>
    <a href="${escapeHtml(plan.hotel.booking_link)}" target="_blank" rel="noopener" class="link-btn primary">View live hotels & book</a>
  `;
}

function renderItinerary(plan) {
  dailyPlanSectionEl.hidden = false;
  itineraryEl.innerHTML = "";

  const reasoning = document.createElement("div");
  reasoning.className = "reasoning";
  reasoning.textContent = plan.reasoning_summary;
  itineraryEl.appendChild(reasoning);

  for (const day of plan.days) {
    const card = document.createElement("div");
    card.className = "day-card";
    card.innerHTML = `
      <div class="day-stub">
        <span class="day-stub-label">DAY</span>
        <span class="day-stub-num">${day.day_number}</span>
      </div>
      <div class="day-body">
        <h3>${escapeHtml(day.date)}</h3>
        <div class="weather">${escapeHtml(day.weather_summary)}</div>
        <ul>${day.activities.map((a) => placeRecHtml(a)).join("")}</ul>
        <div class="restaurant">${placeRecHtml(day.restaurant, true)}</div>
        ${day.notes ? `<div class="notes">${escapeHtml(day.notes)}</div>` : ""}
      </div>
    `;
    itineraryEl.appendChild(card);
  }
}

function placeRecHtml(place, inline = false) {
  const link = `<a href="${escapeHtml(place.maps_link)}" target="_blank" rel="noopener" class="place-link" title="View on Google Maps">${escapeHtml(place.name)} ↗</a>`;
  return inline ? link : `<li>${link}</li>`;
}

function readWishlistFormData() {
  const data = Object.fromEntries(new FormData(wishlistForm).entries());
  return {
    origin_city: data.wl_origin_city,
    destination: data.wl_destination || "",
    earliest_date: data.wl_earliest_date,
    latest_date: data.wl_latest_date,
    trip_length_days: parseInt(data.wl_trip_length_days, 10),
    budget: parseFloat(data.wl_budget),
    currency: data.wl_currency || "USD",
    interests: data.wl_interests || "general sightseeing",
    email: data.wl_email || null,
  };
}

async function submitWishlist(e) {
  e.preventDefault();
  const payload = readWishlistFormData();
  wishlistBtn.disabled = true;
  wishlistBtn.textContent = "Adding...";
  wishlistStatusEl.hidden = false;
  wishlistStatusEl.textContent = payload.destination
    ? "Saving your wishlist item..."
    : "Saving — the agent is picking a destination for you...";
  wishlistResultEl.hidden = true;

  try {
    const res = await authedFetch("/api/wishlist", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Request failed (${res.status})`);
    }
    const data = await res.json();
    renderWishlistResult(data);
    wishlistStatusEl.hidden = true;
    wishlistForm.reset();
    fetchWishlistItems();
    fetchNotifications();
  } catch (err) {
    wishlistStatusEl.textContent = `Couldn't add to wishlist: ${err.message}`;
  } finally {
    wishlistBtn.disabled = false;
    wishlistBtn.textContent = "Add to wishlist";
  }
}

function renderWishlistResult(data) {
  wishlistResultEl.hidden = false;
  const recommendedNote = data.destination_was_recommended
    ? `<div class="reasoning">Agent picked this destination: ${escapeHtml(data.reasoning)}</div>`
    : "";
  const outlookHtml = data.outlook
    ? `<div>${escapeHtml(data.outlook.message)}</div><a href="${escapeHtml(data.outlook.booking_link)}" target="_blank" rel="noopener" class="link-btn">Check real prices →</a>`
    : `<div>Saved. The agent will check for a good window within the next few days.</div>`;
  wishlistResultEl.innerHTML = `
    <div><strong>Added to wishlist: ${escapeHtml(data.destination_city)}, ${escapeHtml(data.destination_country)}</strong></div>
    ${recommendedNote}
    ${outlookHtml}
  `;
}

async function fetchWishlistItems() {
  try {
    const res = await authedFetch("/api/wishlist");
    const items = await res.json();
    renderWishlistItems(items);
  } catch (e) {
    // silent — non-critical background refresh
  }
}

function renderWishlistItems(items) {
  wishlistItemsEl.innerHTML = "";
  if (items.length === 0) {
    wishlistItemsEl.innerHTML = `<div class="wishlist-empty">Nothing on your wishlist yet.</div>`;
    return;
  }
  for (const item of items) {
    const div = document.createElement("div");
    div.className = "wishlist-item";
    const statusNote = item.status === "expired" ? " (window passed)" : "";
    div.innerHTML = `
      <span class="item-kind-badge" title="Wishlist — not booked yet">Wishlist</span>
      <div class="dest">${escapeHtml(item.destination_city)}${item.destination_country ? ", " + escapeHtml(item.destination_country) : ""}${statusNote}</div>
      <div class="meta">From ${escapeHtml(item.origin_city)} · ${escapeHtml(item.earliest_date)} to ${escapeHtml(item.latest_date)} · ${item.trip_length_days} days · up to ${formatMoney(item.budget, item.currency)}</div>
      <div class="item-actions"></div>
    `;
    const actions = div.querySelector(".item-actions");
    const archiveBtn = document.createElement("button");
    archiveBtn.className = "link-btn";
    archiveBtn.textContent = "Remove";
    archiveBtn.addEventListener("click", async () => {
      await authedFetch(`/api/wishlist/${item.id}/archive`, { method: "POST" });
      fetchWishlistItems();
    });
    actions.appendChild(archiveBtn);
    wishlistItemsEl.appendChild(div);
  }
}

function readWatchFormData() {
  const data = Object.fromEntries(new FormData(watchForm).entries());
  return {
    city: data.watch_city,
    mood_or_interest: data.watch_mood || "general sightseeing",
    email: data.watch_email || null,
  };
}

async function submitWatch(e) {
  e.preventDefault();
  const payload = readWatchFormData();
  watchBtn.disabled = true;
  watchBtn.textContent = "Starting...";
  watchStatusEl.hidden = false;
  watchStatusEl.textContent = "Saving — checking for real events now...";
  watchResultEl.hidden = true;

  try {
    const res = await authedFetch("/api/local-watch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Request failed (${res.status})`);
    }
    const data = await res.json();
    renderWatchResult(data);
    watchStatusEl.hidden = true;
    watchForm.reset();
    fetchWatchItems();
    fetchNotifications();
  } catch (err) {
    watchStatusEl.textContent = `Couldn't start watching: ${err.message}`;
  } finally {
    watchBtn.disabled = false;
    watchBtn.textContent = "Start watching";
  }
}

function renderWatchResult(data) {
  watchResultEl.hidden = false;
  const outlookHtml = data.outlook
    ? `<div>${escapeHtml(data.outlook.message)}</div><a href="${escapeHtml(data.outlook.booking_link)}" target="_blank" rel="noopener" class="link-btn">View tickets →</a>`
    : `<div>Watching ${escapeHtml(data.city)}. Nothing new right now — the agent checks daily and will surface anything real it finds.</div>`;
  watchResultEl.innerHTML = `
    <div><strong>Now watching: ${escapeHtml(data.city)}${data.city_country ? ", " + escapeHtml(data.city_country) : ""}</strong></div>
    ${outlookHtml}
  `;
}

async function fetchWatchItems() {
  try {
    const res = await authedFetch("/api/local-watch");
    const items = await res.json();
    renderWatchItems(items);
  } catch (e) {
    // silent — non-critical background refresh
  }
}

function renderWatchItems(items) {
  watchItemsEl.innerHTML = "";
  if (items.length === 0) {
    watchItemsEl.innerHTML = `<div class="wishlist-empty">Not watching any cities yet.</div>`;
    return;
  }
  for (const item of items) {
    const div = document.createElement("div");
    div.className = "local-watch-item";
    div.innerHTML = `
      <span class="item-kind-badge" title="Watching for real local events">Watching</span>
      <div class="dest">${escapeHtml(item.city)}${item.city_country ? ", " + escapeHtml(item.city_country) : ""}</div>
      <div class="meta">${escapeHtml(item.mood_or_interest || "general sightseeing")}</div>
      <div class="item-actions"></div>
    `;
    const actions = div.querySelector(".item-actions");
    const archiveBtn = document.createElement("button");
    archiveBtn.className = "link-btn";
    archiveBtn.textContent = "Stop watching";
    archiveBtn.addEventListener("click", async () => {
      await authedFetch(`/api/local-watch/${item.id}/archive`, { method: "POST" });
      fetchWatchItems();
    });
    actions.appendChild(archiveBtn);
    watchItemsEl.appendChild(div);
  }
}

async function fetchTrips() {
  try {
    const res = await authedFetch("/api/trips");
    const trips = await res.json();
    renderTripsList(trips);
  } catch (e) {
    // silent — non-critical background refresh
  }
}

function renderTripsList(trips) {
  const tripsListEl = document.getElementById("trips-list");
  tripsListEl.innerHTML = "";
  if (trips.length === 0) {
    tripsListEl.innerHTML = `<div class="trips-empty">No saved trips yet. Plan one and hit "Save & monitor this trip".</div>`;
    return;
  }
  for (const trip of trips) {
    const div = document.createElement("div");
    div.className = "trip-item";
    const plan = trip.plan;
    div.innerHTML = `
      <span class="item-kind-badge" title="Confirmed trip">Trip</span>
      <div class="dest">${escapeHtml(plan.destination_city)}, ${escapeHtml(plan.destination_country)}</div>
      <div class="meta">From ${escapeHtml(plan.origin_city)} · ${escapeHtml(trip.start_date)} to ${escapeHtml(trip.end_date)} · ${formatMoney(plan.total_estimated_cost_low, plan.currency)}–${formatMoney(plan.total_estimated_cost_high, plan.currency)}</div>
      <div class="item-actions"></div>
    `;
    const actions = div.querySelector(".item-actions");

    const viewBtn = document.createElement("button");
    viewBtn.className = "link-btn primary";
    viewBtn.textContent = "View";
    viewBtn.addEventListener("click", () => {
      currentPlan = plan;
      renderSummary(plan);
      renderMap(plan);
      renderItinerary(plan);
      emptyStateEl.hidden = true;
      hideError();
      checkUpdatesBtn.hidden = false;
      saveTripRow.hidden = true;
      setStatus("Viewing saved trip.");
    });
    actions.appendChild(viewBtn);

    const removeBtn = document.createElement("button");
    removeBtn.className = "link-btn";
    removeBtn.textContent = "Remove";
    removeBtn.addEventListener("click", async () => {
      await authedFetch(`/api/trips/${trip.id}/archive`, { method: "POST" });
      fetchTrips();
    });
    actions.appendChild(removeBtn);

    tripsListEl.appendChild(div);
  }
}

async function submitPlan() {
  const payload = readFormData();
  planBtn.disabled = true;
  planBtn.textContent = "Planning...";
  setStatus("Starting up...");
  hideError();
  emptyStateEl.hidden = true;
  dailyPlanSectionEl.hidden = false;
  loadingSkeletonEl.hidden = false;
  itineraryEl.hidden = true;
  try {
    const plan = await planTripStream(payload, (message) => setStatus(message));
    currentPlan = plan;
    renderSummary(plan);
    renderMap(plan);
    renderItinerary(plan);
    checkUpdatesBtn.hidden = false;
    saveTripRow.hidden = false;
    saveTripStatus.textContent = "";
    setStatus("Plan ready.");
  } catch (e) {
    showError(`Couldn't plan this trip: ${e.message}`);
    setStatus("");
    if (!currentPlan) {
      emptyStateEl.hidden = false;
      dailyPlanSectionEl.hidden = true;
    }
  } finally {
    loadingSkeletonEl.hidden = true;
    itineraryEl.hidden = false;
    planBtn.disabled = false;
    planBtn.textContent = "Plan my trip";
  }
}

function setDayStatus(message, isError = false) {
  dayStatusEl.hidden = !message;
  dayStatusEl.textContent = message;
  dayStatusEl.classList.toggle("error", isError);
}

function readDayFormData() {
  const data = Object.fromEntries(new FormData(dayForm).entries());
  return {
    city: data.day_city,
    date: data.day_date,
    mood_or_interest: data.day_mood || "general sightseeing",
    dietary_needs: data.day_dietary_needs || "none",
  };
}

// Reuses the same marker colors as the trip map where the meaning lines up
// (activity, restaurant), reuses the unused-here "hotel" green for events
// (a distinct color already in the palette rather than inventing a new one),
// and treats the city center like a destination pin.
const DAY_CATEGORY_COLOR = {
  city_center: "#4338ca",
  activity: "#b45309",
  restaurant: "#b3261e",
  event: "#0f766e",
};

function renderDaySummary(plan) {
  resultsTitleEl.textContent = "Day Overview";

  logisticsSectionEl.hidden = false;
  logisticsStatsEl.innerHTML = `
    <div class="stat">
      <div class="label">City</div>
      <div class="value">${escapeHtml(plan.city)}, ${escapeHtml(plan.country)}</div>
    </div>
    <div class="stat">
      <div class="label">Date</div>
      <div class="value">${escapeHtml(plan.date)}</div>
    </div>
    <div class="stat">
      <div class="label">Mood</div>
      <div class="value">${escapeHtml(plan.mood_or_interest)}</div>
    </div>
    <div class="stat">
      <div class="label">Weather</div>
      <div class="value">${escapeHtml(plan.weather_summary)}</div>
    </div>
  `;
  bookingLinksEl.hidden = true;
  bookingLinksEl.innerHTML = "";
  // A day plan has no cost concept (no flights/hotels) — the Cost section
  // stays hidden entirely rather than showing an empty header.
  costSectionEl.hidden = true;
  costStatsEl.innerHTML = "";
}

function renderDayMap(plan) {
  clearMap();
  const bounds = [];
  for (const pin of plan.map_pins) {
    const color = DAY_CATEGORY_COLOR[pin.category] || "#14162b";
    const marker = L.circleMarker([pin.lat, pin.lon], {
      radius: pin.category === "city_center" ? 9 : 7,
      color,
      fillColor: color,
      fillOpacity: 0.85,
      weight: 2,
    }).addTo(map);
    marker.bindPopup(`<b>${escapeHtml(pin.label)}</b><br/>${escapeHtml(pin.category)}`);
    markers.push(marker);
    bounds.push([pin.lat, pin.lon]);
  }
  if (bounds.length) {
    map.fitBounds(bounds, { padding: [40, 40] });
  }
}

function pad2(n) {
  return String(n).padStart(2, "0");
}

// Builds a floating-time .ics event (no timezone conversion — Ticketmaster
// gives venue-local date/time, and that's what most calendar apps expect for
// an "add this event" action) as a real downloadable file, no server round
// trip needed since every field is already in the event data. Duration is a
// 2-hour placeholder since Ticketmaster doesn't reliably provide an end time.
function buildIcsDataUrl(ev, cityLabel) {
  const [y, m, d] = ev.date.split("-").map(Number);
  const [hh, mm] = (ev.time || "19:00:00").split(":").map(Number);
  const start = new Date(y, m - 1, d, hh || 19, mm || 0, 0);
  const end = new Date(start.getTime() + 2 * 60 * 60 * 1000);

  const fmt = (dt) =>
    `${dt.getFullYear()}${pad2(dt.getMonth() + 1)}${pad2(dt.getDate())}T${pad2(dt.getHours())}${pad2(dt.getMinutes())}00`;
  const escapeText = (s) => (s || "").replace(/[,;]/g, (c) => "\\" + c);

  const ics = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//Trip Planner Agent//EN",
    "BEGIN:VEVENT",
    `UID:${crypto.randomUUID()}@trip-planner-agent`,
    `DTSTAMP:${fmt(new Date())}`,
    `DTSTART:${fmt(start)}`,
    `DTEND:${fmt(end)}`,
    `SUMMARY:${escapeText(ev.name)}`,
    `LOCATION:${escapeText(ev.venue_name ? ev.venue_name + ", " + cityLabel : cityLabel)}`,
    `DESCRIPTION:${escapeText("Tickets: " + ev.ticket_link)}`,
    "END:VEVENT",
    "END:VCALENDAR",
  ].join("\r\n");

  return "data:text/calendar;charset=utf-8," + encodeURIComponent(ics);
}

function eventCardEl(ev, cityLabel) {
  const div = document.createElement("div");
  div.className = "event-card";
  const metaParts = [ev.category];
  if (ev.date) metaParts.push(ev.date + (ev.time ? " " + ev.time.slice(0, 5) : ""));
  if (ev.venue_name) metaParts.push(ev.venue_name);
  div.innerHTML = `
    <div class="event-name">${escapeHtml(ev.name)}</div>
    <div class="event-meta">${escapeHtml(metaParts.join(" · "))}</div>
    <div class="event-actions"></div>
  `;
  const actions = div.querySelector(".event-actions");

  const ticketLink = document.createElement("a");
  ticketLink.href = ev.ticket_link;
  ticketLink.target = "_blank";
  ticketLink.rel = "noopener";
  ticketLink.className = "link-btn";
  ticketLink.textContent = ev.date ? "View tickets →" : "Search events →";
  actions.appendChild(ticketLink);

  if (ev.date) {
    const calBtn = document.createElement("a");
    calBtn.href = buildIcsDataUrl(ev, cityLabel);
    calBtn.download = `${ev.name.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}.ics`;
    calBtn.className = "link-btn";
    calBtn.textContent = "Add to calendar";
    actions.appendChild(calBtn);
  }

  return div;
}

function renderDayItinerary(plan) {
  dailyPlanSectionEl.hidden = false;
  itineraryEl.innerHTML = "";

  const reasoning = document.createElement("div");
  reasoning.className = "reasoning";
  reasoning.textContent = plan.reasoning_summary;
  itineraryEl.appendChild(reasoning);

  const dayOfMonth = new Date(plan.date + "T00:00:00").getDate();
  const card = document.createElement("div");
  card.className = "day-card";
  card.innerHTML = `
    <div class="day-stub">
      <span class="day-stub-label">DAY OUT</span>
      <span class="day-stub-num">${dayOfMonth}</span>
    </div>
    <div class="day-body">
      <h3>${escapeHtml(plan.city)}, ${escapeHtml(plan.date)}</h3>
      <div class="weather">${escapeHtml(plan.weather_summary)}</div>
      <ul>${plan.activities.map((a) => placeRecHtml(a)).join("")}</ul>
      <div class="restaurant">${placeRecHtml(plan.restaurant, true)}</div>
    </div>
  `;
  itineraryEl.appendChild(card);

  const eventsHeading = document.createElement("h2");
  eventsHeading.className = "section-heading";
  eventsHeading.textContent = "Local events today";
  itineraryEl.appendChild(eventsHeading);

  if (plan.events.length === 0) {
    const empty = document.createElement("div");
    empty.className = "events-empty";
    empty.textContent = "No specific events found for this date — try a broader mood, or search directly.";
    itineraryEl.appendChild(empty);
  } else {
    for (const ev of plan.events) {
      itineraryEl.appendChild(eventCardEl(ev, plan.city));
    }
  }

  itineraryEl.appendChild(dayFeedbackCardEl(plan.city, plan.mood_or_interest));
}

// A day plan is never saved/monitored server-side — it's shown once,
// immediately — so unlike trip feedback (asked later, via the notification
// inbox, after the trip happens) this asks right here, right after the plan
// renders. Feeds into agent.py's DAY_SYSTEM_PROMPT the same way trip
// feedback feeds into trip planning — real stored ratings, never fabricated.
function dayFeedbackCardEl(city, moodOrInterest) {
  const wrap = document.createElement("div");
  wrap.className = "day-feedback-card";
  wrap.innerHTML = `
    <div class="day-feedback-heading">How was this day?</div>
    <div class="feedback-rating"></div>
    <textarea class="feedback-text" rows="2" placeholder="Optional: what stood out?"></textarea>
    <div class="feedback-hint"></div>
    <div class="notif-item-actions"></div>
  `;

  const ratingEl = wrap.querySelector(".feedback-rating");
  let selectedRating = 0;
  const stars = [];
  for (let i = 1; i <= 5; i++) {
    const star = document.createElement("button");
    star.type = "button";
    star.className = "star-btn";
    star.textContent = "★";
    star.setAttribute("aria-label", `Rate ${i} out of 5`);
    star.addEventListener("click", () => {
      selectedRating = i;
      stars.forEach((s, idx) => s.classList.toggle("selected", idx < selectedRating));
      wrap.querySelector(".feedback-hint").textContent = "";
    });
    stars.push(star);
    ratingEl.appendChild(star);
  }

  const submitBtn = document.createElement("button");
  submitBtn.className = "link-btn primary";
  submitBtn.textContent = "Submit feedback";
  submitBtn.addEventListener("click", async () => {
    if (!selectedRating) {
      wrap.querySelector(".feedback-hint").textContent = "Pick a rating first.";
      return;
    }
    submitBtn.disabled = true;
    await authedFetch("/api/day-plan/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        city,
        mood_or_interest: moodOrInterest,
        rating: selectedRating,
        feedback_text: wrap.querySelector(".feedback-text").value || null,
      }),
    });
    wrap.innerHTML = `<div class="day-feedback-heading">Thanks — noted for next time.</div>`;
  });
  wrap.querySelector(".notif-item-actions").appendChild(submitBtn);

  return wrap;
}

let currentDayPlan = null;

async function submitDayPlan() {
  const payload = readDayFormData();
  dayPlanBtn.disabled = true;
  dayPlanBtn.textContent = "Planning...";
  setDayStatus("Starting up...");
  hideError();
  emptyStateEl.hidden = true;
  dailyPlanSectionEl.hidden = false;
  loadingSkeletonEl.hidden = false;
  itineraryEl.hidden = true;
  checkUpdatesBtn.hidden = true;
  saveTripRow.hidden = true;
  try {
    const plan = await planDayStream(payload, (message) => setDayStatus(message));
    currentDayPlan = plan;
    renderDaySummary(plan);
    renderDayMap(plan);
    renderDayItinerary(plan);
    setDayStatus("Day plan ready.");
  } catch (e) {
    showError(`Couldn't plan this day: ${e.message}`);
    setDayStatus("");
    if (!currentPlan && !currentDayPlan) {
      emptyStateEl.hidden = false;
      dailyPlanSectionEl.hidden = true;
    }
  } finally {
    loadingSkeletonEl.hidden = true;
    itineraryEl.hidden = false;
    dayPlanBtn.disabled = false;
    dayPlanBtn.textContent = "Plan my day";
  }
}

dayForm.addEventListener("submit", (e) => {
  e.preventDefault();
  submitDayPlan();
});

form.addEventListener("submit", (e) => {
  e.preventDefault();
  submitPlan();
});

// "Live" updates: once a plan exists, changing any field auto-replans after a
// short debounce, so edits reflect without needing to resubmit manually.
// Free-text descriptive fields are excluded — correcting a typo in
// "interests" shouldn't cost a 20-40s Bedrock call. Dates, budget, travelers,
// destination, and the two selects all meaningfully change the plan, so
// those still auto-replan.
const NO_AUTO_REPLAN_FIELDS = new Set(["interests", "dietary_needs"]);

form.addEventListener("change", (e) => {
  if (!currentPlan) return;
  if (NO_AUTO_REPLAN_FIELDS.has(e.target.name)) return;
  clearTimeout(replanTimer);
  setStatus("Inputs changed — updating plan...");
  replanTimer = setTimeout(submitPlan, 900);
});

checkUpdatesBtn.addEventListener("click", checkUpdates);
saveTripBtn.addEventListener("click", saveTrip);
notifBell.addEventListener("click", () => {
  notifPanel.hidden = !notifPanel.hidden;
  notifBell.setAttribute("aria-expanded", String(!notifPanel.hidden));
});
errorBannerDismissBtn.addEventListener("click", hideError);
document.querySelectorAll(".preset-chip").forEach((chip) => {
  chip.addEventListener("click", () => applyPreset(chip.dataset.preset));
});

attachCityAutocomplete(document.getElementById("origin-input"), document.getElementById("origin-dropdown"));
attachCityAutocomplete(document.getElementById("destination-input"), document.getElementById("destination-dropdown"));
attachCityAutocomplete(document.getElementById("wl-origin-input"), document.getElementById("wl-origin-dropdown"));
attachCityAutocomplete(document.getElementById("wl-destination-input"), document.getElementById("wl-destination-dropdown"));
attachCityAutocomplete(document.getElementById("day-city-input"), document.getElementById("day-city-dropdown"));
attachCityAutocomplete(document.getElementById("watch-city-input"), document.getElementById("watch-city-dropdown"));
setupDateGuards();

wishlistForm.addEventListener("submit", submitWishlist);
watchForm.addEventListener("submit", submitWatch);

// Tab switching between "Plan a Trip", "Day Out", "Wishlist", and "My Trips"
document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => {
      b.classList.toggle("active", b === btn);
      b.setAttribute("aria-selected", String(b === btn));
    });
    document.querySelectorAll(".tab-panel").forEach((panel) => {
      panel.hidden = panel.id !== btn.dataset.tab;
    });
    if (btn.dataset.tab === "wishlist-tab") fetchWishlistItems();
    if (btn.dataset.tab === "trips-tab") fetchTrips();
    if (btn.dataset.tab === "day-tab") fetchWatchItems();
  });
});

initMap();
setDefaultDates();

// Everything below needs a signed client id first (see ensureClientId above)
// — map/date setup doesn't depend on it, so those run immediately above
// while this resolves.
(async () => {
  await ensureClientId();
  fetchNotifications();
  fetchWishlistItems();
  fetchTrips();
  fetchWatchItems();
  setInterval(fetchNotifications, NOTIFICATION_POLL_MS);
})();
