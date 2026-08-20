const form = document.getElementById("trip-form");
const planBtn = document.getElementById("plan-btn");
const planStopBtn = document.getElementById("plan-stop-btn");
const statusEl = document.getElementById("status");
const resultsTitleEl = document.getElementById("results-title");
const logisticsSectionEl = document.getElementById("logistics-section");
const logisticsStatsEl = document.getElementById("logistics-stats");
const costSectionEl = document.getElementById("cost-section");
const costStatsEl = document.getElementById("cost-stats");
const hotelOptionsSectionEl = document.getElementById("hotel-options-section");
const hotelOptionsEl = document.getElementById("hotel-options");
const dailyPlanSectionEl = document.getElementById("daily-plan-section");
const bookingLinksEl = document.getElementById("booking-links");
const itineraryEl = document.getElementById("itinerary");
const updatesEl = document.getElementById("updates");
const updatesListEl = document.getElementById("updates-list");
const checkUpdatesBtn = document.getElementById("check-updates-btn");
const saveTripRow = document.getElementById("save-trip-row");
const saveTripAlerts = document.getElementById("save-trip-alerts");
const saveTripBtn = document.getElementById("save-trip-btn");
const saveWishlistBtn = document.getElementById("save-wishlist-btn");
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
const dayPlanStopBtn = document.getElementById("day-plan-stop-btn");
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
const accountBtn = document.getElementById("account-btn");
const accountPanel = document.getElementById("account-panel");
const loginForm = document.getElementById("login-form");
const loginBtn = document.getElementById("login-btn");
const signupForm = document.getElementById("signup-form");
const signupBtn = document.getElementById("signup-btn");
const accountAuthStatusEl = document.getElementById("account-auth-status");
const accountHomeCityEl = document.getElementById("account-home-city");
const useMyLocationBtn = document.getElementById("use-my-location-btn");
const accountLocationStatusEl = document.getElementById("account-location-status");
const logoutBtn = document.getElementById("logout-btn");
const landingEl = document.getElementById("landing");
const appShellEl = document.getElementById("app-shell");
const landingCtaBtn = document.getElementById("landing-cta-btn");
const profileEmailEl = document.getElementById("profile-email");
const preferencesForm = document.getElementById("preferences-form");
const savePreferencesBtn = document.getElementById("save-preferences-btn");
const preferencesStatusEl = document.getElementById("preferences-status");
const settingsForm = document.getElementById("settings-form");
const settingsStatusEl = document.getElementById("settings-status");
const inviteFriendBtn = document.getElementById("invite-friend-btn");
const inviteStatusEl = document.getElementById("invite-status");
const deleteAccountBtn = document.getElementById("delete-account-btn");
const deleteAccountConfirmEl = document.getElementById("delete-account-confirm");
const deleteAccountConfirmInput = document.getElementById("delete-account-confirm-input");
const deleteAccountConfirmBtn = document.getElementById("delete-account-confirm-btn");
const deleteAccountCancelBtn = document.getElementById("delete-account-cancel-btn");
const deleteAccountStatusEl = document.getElementById("delete-account-status");

const NOTIFICATION_POLL_MS = 30000;
const CITY_SEARCH_DEBOUNCE_MS = 250;

// An account is required to use any planning/data feature (see backend's
// require_login/require_client_id) — this is the real, server-verified login
// session, not anonymous per-browser scoping. Stateless HMAC-signed token
// (see backend/auth.py), sent as X-Session-Token on every gated request.
const SESSION_TOKEN_STORAGE_KEY = "trip_planner_session_token";
let sessionToken = localStorage.getItem(SESSION_TOKEN_STORAGE_KEY);
let currentUser = null; // { email, home_city, home_country, home_lat, home_lon } | null

// Optimistic initial render: if a token is already in localStorage, show the
// app shell immediately instead of flashing the landing page while
// restoreSession() confirms it — restoreSession() corrects back to the
// landing gate if the token turns out to be stale/invalid.
if (sessionToken) {
  landingEl.hidden = true;
  appShellEl.hidden = false;
  notifBell.hidden = false;
}

// Whatever plan is currently on screen in each planning tab, saved to
// sessionStorage so it survives a tab reload — e.g. the browser discarding a
// backgrounded tab after the traveler opens a booking link in a new tab and
// comes back, rather than forcing them to regenerate the whole plan from
// scratch. sessionStorage (not localStorage) is deliberate: cleared when the
// tab actually closes, unlike the session token above which should persist.
// Trip Planner and Day Out each get their own key — previously there was
// one shared slot, so planning a day out after a trip silently discarded the
// trip's saved view (and vice versa) the moment either was regenerated.
const LAST_TRIP_VIEW_KEY = "trip_planner_last_trip_view";
const LAST_DAY_VIEW_KEY = "trip_planner_last_day_view";
const LAST_ACTIVE_TAB_KEY = "trip_planner_last_active_tab";

function saveLastView(type, plan, meta) {
  const key = type === "trip" ? LAST_TRIP_VIEW_KEY : LAST_DAY_VIEW_KEY;
  try {
    sessionStorage.setItem(key, JSON.stringify({ plan, meta }));
  } catch {
    // Storage full/unavailable (e.g. private browsing) — non-fatal, the
    // traveler just won't get the reload-recovery, plan generation itself
    // is unaffected.
  }
}

// fetch wrapper for every endpoint that requires a logged-in account (see
// backend's require_client_id) — attaches the session token. A 401 here
// means the session really is invalid (tampered, or a dev db reset since it
// was issued), so it logs out and drops back to the landing gate rather than
// retrying — there's no anonymous fallback to recover into anymore.
async function authedFetch(url, options = {}) {
  const opts = { ...options, headers: { ...(options.headers || {}), "X-Session-Token": sessionToken } };
  const res = await fetch(url, opts);
  if (res.status === 401) {
    logout();
    setAccountAuthStatus("Your session expired — please log in again.", true);
  }
  return res;
}

// ---- Accounts (real signup/login, real browser geolocation) ----
// Required to reach any planning/data feature (see the landing gate below) —
// the only thing an account adds beyond login itself: a saved "home"
// city/coordinates so Trip Planner and Day Out can pre-fill the starting
// city automatically, on any device — never a lock-in, every field stays
// editable exactly like today.

function setAccountAuthStatus(message, isError = false) {
  accountAuthStatusEl.hidden = !message;
  accountAuthStatusEl.textContent = message;
  accountAuthStatusEl.classList.toggle("error", isError);
}

// BigDataCloud returns official ISO long-form names for some countries
// (e.g. "United States of America (the)", "Netherlands (the)") — accurate
// but jarring in a UI label, so trim the parenthetical for display/fill.
function cleanCountryName(country) {
  return country ? country.replace(/\s*\(the\)$/i, "") : country;
}

// Closes every floating dropdown (notifications, the login/signup account
// panel) so at most one is ever on screen at once — Settings itself lives
// in the sidenav now (see the tab-switch handler), not a dropdown, so
// switching to it doesn't need this at all.
function closeAllPanels() {
  notifPanel.hidden = true;
  accountPanel.hidden = true;
}

// Resets the Settings tab's transient UI state (status messages, an open
// delete-confirmation) — called whenever it's opened, so switching away and
// back never shows a stale "Saved!" from three tab-visits ago.
function resetSettingsTabState() {
  preferencesStatusEl.hidden = true;
  settingsStatusEl.hidden = true;
  inviteStatusEl.hidden = true;
  closeDeleteAccountConfirm();
}

// Saved account defaults (see /api/auth/preferences) prefill the matching
// form fields — currency/transportation/accommodation only when a plan
// hasn't been generated yet (unconditional overwrite is fine that early),
// alert emails only into fields still empty, same "never a lock-in" rule as
// the home-location prefill below.
function applyPreferences() {
  if (!currentUser) return;
  if (currentUser.default_currency && !currentPlan) {
    form.currency.value = currentUser.default_currency;
    wishlistForm.wl_currency.value = currentUser.default_currency;
  }
  if (currentUser.default_transportation && !currentPlan) {
    form.transportation.value = currentUser.default_transportation;
  }
  if (currentUser.default_accommodation && !currentPlan) {
    form.accommodation.value = currentUser.default_accommodation;
  }
  // No email field to prefill anymore (see the "Email me at my account
  // address" checkboxes) — the backend derives the actual alert address
  // from the logged-in account itself (default_currency etc. above still
  // need prefilling since those are real per-plan choices, not identity).
}

async function submitPreferences(e) {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(preferencesForm).entries());
  savePreferencesBtn.disabled = true;
  preferencesStatusEl.hidden = false;
  preferencesStatusEl.classList.remove("error");
  preferencesStatusEl.textContent = "Saving...";
  try {
    const res = await fetch("/api/auth/preferences", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Session-Token": sessionToken },
      body: JSON.stringify({
        default_currency: data.pref_currency || null,
        default_transportation: data.pref_transportation || null,
        default_accommodation: data.pref_accommodation || null,
        notify_email: data.pref_notify_email || null,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Couldn't save preferences");
    }
    currentUser = await res.json();
    applyPreferences();
    preferencesStatusEl.textContent = "Preferences saved.";
  } catch (err) {
    preferencesStatusEl.classList.add("error");
    preferencesStatusEl.textContent = err.message;
  } finally {
    savePreferencesBtn.disabled = false;
  }
}

const FONT_SCALES = { small: 0.9, medium: 1, large: 1.15 };

// Pure display preferences (see Settings) applied as CSS — every rem-based
// font-size in style.css scales off --font-scale, and the dark palette is a
// straight data-theme swap (see style.css's html[data-theme="dark"] block).
// Reset to the light/medium defaults on logout so a shared browser never
// keeps a previous account's look on the landing page or the next login.
function applyDisplaySettings() {
  const theme = currentUser && currentUser.theme === "dark" ? "dark" : "light";
  const scale = FONT_SCALES[currentUser && currentUser.font_scale] || 1;
  document.documentElement.setAttribute("data-theme", theme);
  document.documentElement.style.setProperty("--font-scale", scale);
}

async function submitSettings(e) {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(settingsForm).entries());
  const settingsBtn = document.getElementById("save-settings-btn");
  settingsBtn.disabled = true;
  settingsStatusEl.hidden = false;
  settingsStatusEl.classList.remove("error");
  settingsStatusEl.textContent = "Saving...";
  try {
    const res = await fetch("/api/auth/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Session-Token": sessionToken },
      body: JSON.stringify({
        email_notifications_enabled: data.settings_email_notifications === "on",
        in_app_notifications_enabled: data.settings_in_app_notifications === "on",
        font_scale: data.settings_font_scale,
        theme: data.settings_theme,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Couldn't save settings");
    }
    currentUser = await res.json();
    applyDisplaySettings();
    settingsStatusEl.textContent = "Settings saved.";
    if (!currentUser.in_app_notifications_enabled) {
      renderNotifications([]);
      clearInterval(notificationPollTimer);
      notificationPollTimer = null;
    } else if (!notificationPollTimer) {
      fetchNotifications();
      notificationPollTimer = setInterval(fetchNotifications, NOTIFICATION_POLL_MS);
    }
  } catch (err) {
    settingsStatusEl.classList.add("error");
    settingsStatusEl.textContent = err.message;
  } finally {
    settingsBtn.disabled = false;
  }
}

async function inviteFriend() {
  inviteStatusEl.hidden = false;
  inviteStatusEl.classList.remove("error");
  try {
    await navigator.clipboard.writeText(window.location.origin);
    inviteStatusEl.textContent = "Link copied — share it with a friend.";
  } catch {
    inviteStatusEl.classList.add("error");
    inviteStatusEl.textContent = `Couldn't copy automatically — here's the link: ${window.location.origin}`;
  }
}

function openDeleteAccountConfirm() {
  deleteAccountConfirmEl.hidden = false;
  deleteAccountConfirmInput.value = "";
  deleteAccountConfirmBtn.disabled = true;
  deleteAccountStatusEl.hidden = true;
}

function closeDeleteAccountConfirm() {
  deleteAccountConfirmEl.hidden = true;
}

async function confirmDeleteAccount() {
  deleteAccountConfirmBtn.disabled = true;
  deleteAccountStatusEl.hidden = false;
  deleteAccountStatusEl.classList.remove("error");
  deleteAccountStatusEl.textContent = "Deleting your account...";
  try {
    const res = await fetch("/api/auth/account", {
      method: "DELETE",
      headers: { "X-Session-Token": sessionToken },
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Couldn't delete account");
    }
    logout();
  } catch (err) {
    deleteAccountStatusEl.classList.add("error");
    deleteAccountStatusEl.textContent = err.message;
    deleteAccountConfirmBtn.disabled = false;
  }
}

// The single source of truth for the logged-in/logged-out gate — called
// from every place currentUser changes (restoreSession, onAuthSuccess,
// logout), so the landing page vs. the real app is always in sync with
// whether there's an actual verified session, never just an optimistic guess.
function updateAccountUI() {
  const loggedIn = !!currentUser;
  accountPanel.hidden = true; // login/signup dropdown never applies once logged in — see accountBtn's handler
  landingEl.hidden = loggedIn;
  appShellEl.hidden = !loggedIn;
  notifBell.hidden = !loggedIn;
  if (loggedIn) {
    profileEmailEl.textContent = `Signed in as ${currentUser.email}`;
    accountHomeCityEl.textContent = currentUser.home_city
      ? `${currentUser.home_city}, ${cleanCountryName(currentUser.home_country)}`
      : "Not set";
    preferencesForm.pref_currency.value = currentUser.default_currency || "";
    preferencesForm.pref_transportation.value = currentUser.default_transportation || "";
    preferencesForm.pref_accommodation.value = currentUser.default_accommodation || "";
    preferencesForm.pref_notify_email.value = currentUser.notify_email || "";
    settingsForm.settings_email_notifications.checked = currentUser.email_notifications_enabled !== false;
    settingsForm.settings_in_app_notifications.checked = currentUser.in_app_notifications_enabled !== false;
    settingsForm.settings_font_scale.value = currentUser.font_scale || "medium";
    settingsForm.settings_theme.value = currentUser.theme || "light";
  }
  applyDisplaySettings();
}

// Runs once at boot: if a session token is already in localStorage (a
// returning visitor who's logged in before), verify it's still valid and
// load the real profile — never trusts the locally-cached shape of a user
// object across visits, only what the server confirms right now.
async function restoreSession() {
  if (!sessionToken) return;
  try {
    const res = await fetch("/api/auth/me", { headers: { "X-Session-Token": sessionToken } });
    if (!res.ok) {
      // Corrects the optimistic app-shell render above (see the top of this
      // file) back to the landing gate — the stored token turned out to be
      // stale/invalid (e.g. a dev db reset since it was issued).
      sessionToken = null;
      currentUser = null;
      localStorage.removeItem(SESSION_TOKEN_STORAGE_KEY);
      updateAccountUI();
      return;
    }
    currentUser = await res.json();
    updateAccountUI();
    loadAccountData();
  } catch {
    // Network hiccup — leave the stored token alone and just try again next
    // load, rather than logging the traveler out over a transient failure.
  }
}

let notificationPollTimer = null;

// Every account-scoped list (notifications/wishlist/watches/trips) is only
// ever fetched once a real session exists — called after a successful
// login/signup and after restoreSession confirms a stored token is still
// valid, never speculatively before either resolves.
function loadAccountData() {
  fetchNotifications();
  fetchWishlistItems();
  fetchTrips();
  fetchWatchItems();
  if (!notificationPollTimer) {
    notificationPollTimer = setInterval(fetchNotifications, NOTIFICATION_POLL_MS);
  }
}

function onAuthSuccess(data) {
  sessionToken = data.session_token;
  localStorage.setItem(SESSION_TOKEN_STORAGE_KEY, sessionToken);
  const { session_token, ...profile } = data;
  currentUser = profile;
  updateAccountUI();
  setAccountAuthStatus("");
  prefillFromHomeLocation();
  applyPreferences();
  loadAccountData();
}

async function submitSignup(e) {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(signupForm).entries());
  signupBtn.disabled = true;
  setAccountAuthStatus("Creating account...");
  try {
    const res = await fetch("/api/auth/signup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: data.signup_email, password: data.signup_password }),
    });
    const result = await res.json();
    if (!res.ok) throw new Error(result.detail || `Request failed (${res.status})`);
    signupForm.reset();
    onAuthSuccess(result);
  } catch (err) {
    setAccountAuthStatus(err.message, true);
  } finally {
    signupBtn.disabled = false;
  }
}

async function submitLogin(e) {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(loginForm).entries());
  loginBtn.disabled = true;
  setAccountAuthStatus("Logging in...");
  try {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: data.login_email, password: data.login_password }),
    });
    const result = await res.json();
    if (!res.ok) throw new Error(result.detail || `Request failed (${res.status})`);
    loginForm.reset();
    onAuthSuccess(result);
  } catch (err) {
    setAccountAuthStatus(err.message, true);
  } finally {
    loginBtn.disabled = false;
  }
}

function logout() {
  // Stateless signed tokens (see backend/auth.py) — nothing to invalidate
  // server-side, just forget it locally.
  sessionToken = null;
  currentUser = null;
  localStorage.removeItem(SESSION_TOKEN_STORAGE_KEY);
  updateAccountUI();
  closeAllPanels();
  clearInterval(notificationPollTimer);
  notificationPollTimer = null;
  // Every list below is this account's private data (see db.py's module
  // docstring on why login is mandatory) — cleared immediately so it can
  // never linger on screen for the next person to use this browser.
  renderNotifications([]);
  renderWishlistItems([]);
  renderWatchItems([]);
  renderTripsList([]);
}

// Shared by the account panel's "Use my current location" (saves to the
// account) and the inline versions next to Starting City / Day Out's city
// field (one-off convenience, no account required) — real browser
// geolocation -> real reverse geocoding, never a guessed city.
async function detectCurrentCity() {
  if (!("geolocation" in navigator)) {
    throw new Error("This browser doesn't support location detection");
  }
  const position = await new Promise((resolve, reject) => {
    navigator.geolocation.getCurrentPosition(resolve, reject, { timeout: 10000 });
  }).catch((err) => {
    throw new Error(err.code === err.PERMISSION_DENIED ? "Location permission denied" : "Couldn't get your location");
  });
  const { latitude, longitude } = position.coords;
  const res = await fetch(`/api/reverse-geocode?lat=${latitude}&lon=${longitude}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Couldn't determine a city for your location");
  }
  const place = await res.json();
  return { ...place, lat: latitude, lon: longitude };
}

async function useMyLocationForAccount() {
  useMyLocationBtn.disabled = true;
  accountLocationStatusEl.hidden = false;
  accountLocationStatusEl.classList.remove("error");
  accountLocationStatusEl.textContent = "Detecting your location...";
  try {
    const place = await detectCurrentCity();
    const res = await fetch("/api/auth/home-location", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Session-Token": sessionToken },
      body: JSON.stringify({ city: place.city, country: place.country, lat: place.lat, lon: place.lon }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Couldn't save your location");
    }
    currentUser = await res.json();
    updateAccountUI();
    accountLocationStatusEl.textContent = `Saved: ${place.city}, ${cleanCountryName(place.country)}`;
    prefillFromHomeLocation();
  } catch (err) {
    accountLocationStatusEl.classList.add("error");
    accountLocationStatusEl.textContent = err.message;
  } finally {
    useMyLocationBtn.disabled = false;
  }
}

// Day Out's exact search anchor, when known — real device coordinates (or
// the account's saved home coordinates), which are more precise than
// whatever a city name re-geocodes to, so activities/restaurants/events end
// up anchored to the traveler's actual point instead of the city center.
// null means "use the typed city name as-is" (see readDayFormData below).
// Cleared the moment the traveler types over the city field by hand (see the
// day-city-input listener below) — editing it manually means the precise
// point no longer applies.
let dayOutLocation = null;

// The inline "📍 Use my location" next to a specific city field — a one-off
// fill, works with or without an account, never saved anywhere unless the
// traveler separately uses the account panel's version.
async function useMyLocationForField(btn) {
  const input = document.getElementById(btn.dataset.cityInput);
  const originalText = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Detecting...";
  try {
    const place = await detectCurrentCity();
    input.value = `${place.city}, ${cleanCountryName(place.country)}`;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    if (input.id === "day-city-input") {
      dayOutLocation = { lat: place.lat, lon: place.lon, country: place.country, country_code: place.country_code };
    }
  } catch (err) {
    showError(err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = originalText;
  }
}

// Only a real, trusted keystroke/paste/autofill should drop back to
// city-name-only search — the programmatic fills above dispatch a synthetic
// (untrusted) "input" event of their own right after setting dayOutLocation,
// which must not immediately undo it.
document.getElementById("day-city-input").addEventListener("input", (e) => {
  if (e.isTrusted) dayOutLocation = null;
});

// Auto-fills Starting City (Trip Planner) and City (Day Out) from a logged-
// in account's saved home location — only into a field that's still empty,
// so it never overwrites something the traveler already typed.
function prefillFromHomeLocation() {
  if (!currentUser || !currentUser.home_city) return;
  const label = `${currentUser.home_city}, ${cleanCountryName(currentUser.home_country)}`;
  const originInput = document.getElementById("origin-input");
  const dayCityInput = document.getElementById("day-city-input");
  if (originInput && !originInput.value) {
    originInput.value = label;
    originInput.dispatchEvent(new Event("input", { bubbles: true }));
  }
  if (dayCityInput && !dayCityInput.value) {
    dayCityInput.value = label;
    dayCityInput.dispatchEvent(new Event("input", { bubbles: true }));
    if (currentUser.home_lat != null && currentUser.home_lon != null) {
      dayOutLocation = { lat: currentUser.home_lat, lon: currentUser.home_lon, country: currentUser.home_country, country_code: null };
    }
  }
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
  // Fixed 2 decimals so amounts never render inconsistently (e.g. "$809.21"
  // next to "$1,646.3" for the same list of numbers).
  return `${symbol}${amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

// Flight prices collapse low === high when a real observed price was found
// (see tools/flights.py's Travelpayouts integration) instead of an estimated
// range — show that as a single value rather than an odd "$540-$540".
function formatMoneyRange(low, high, currencyCode) {
  if (low === high) return formatMoney(low, currencyCode);
  return `${formatMoney(low, currencyCode)}–${formatMoney(high, currencyCode)}`;
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
  event: "#7c3aed",
};

let map;
let markers = [];
let routeLine;
let currentPlan = null;
let currentTripMeta = null; // { travelers, nights, tripId } — tripId is set once the plan is actually
// saved (see saveTrip/the Saved Trips card click) — null means "not confirmed yet", which is what
// gates the Google Calendar link (see updateCalendarLink): only a real, locked-in trip gets one.
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

// Only sets the `min` boundary (today) on every date field — never a
// pre-filled value. A date is real data the traveler has to actually choose,
// not something with a sensible generic example the way "hiking, museums..."
// is for interests; pre-filling one risks looking like a real, deliberate
// choice already made rather than a placeholder-shaped guess.
function setDefaultDates() {
  const todayStr = toLocalDateString(new Date());
  form.start_date.min = todayStr;
  form.end_date.min = todayStr;

  wishlistForm.wl_earliest_date.min = todayStr;
  wishlistForm.wl_latest_date.min = todayStr;

  dayForm.day_date.min = todayStr;
  // Day Out is meant to answer "what can I do today" by default — an
  // everyday, low-friction tool, not one more date picker to fill in every
  // time (still fully editable for planning a different day).
  if (!dayForm.day_date.value) dayForm.day_date.value = todayStr;
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

// Trip Planner and Day Out share one results panel (map/itinerary/etc. in
// <main>) rather than each having its own — cheaper than duplicating that
// markup twice, but it means switching tabs must fully reset every section
// before showing the newly-active tab's own plan. Without this, a leftover
// section from the other planner stayed on screen — most visibly "Choose a
// hotel", which a day plan never has at all.
function clearResultsPanel() {
  emptyStateEl.hidden = true;
  dailyPlanSectionEl.hidden = true;
  logisticsSectionEl.hidden = true;
  costSectionEl.hidden = true;
  hotelOptionsSectionEl.hidden = true;
  hotelOptionsEl.innerHTML = "";
  bookingLinksEl.hidden = true;
  bookingLinksEl.innerHTML = "";
  checkUpdatesBtn.hidden = true;
  saveTripRow.hidden = true;
  document.getElementById("calendar-link-row").hidden = true;
  updatesEl.hidden = true;
  clearMap();
}

const EMPTY_STATE_COPY = {
  trip: {
    heading: "Your trip will show up here",
    body: "Fill in the form and select <strong>Plan my trip</strong> — real flights, hotels, weather, and activities researched and turned into one day-by-day plan.",
    steps: [
      "Set preferences &amp; budget",
      "Agent researches &amp; builds the plan",
      "Save it — the agent keeps watching for better deals in the background, even after you close this tab",
    ],
  },
  day: {
    heading: "Your day out will show up here",
    body: "Fill in a city (or use your location) and select <strong>Plan my day</strong> — real activities, a restaurant, and any local events happening that day, no hotel or booking involved.",
    steps: [
      "Set a city — or use your location for suggestions right around you",
      "Agent researches real activities, food, and events nearby",
      "Come back anytime — this stays here until you plan a new day",
    ],
  },
};

function setEmptyStateForTab(tab) {
  const copy = EMPTY_STATE_COPY[tab];
  emptyStateEl.querySelector("h2").textContent = copy.heading;
  emptyStateEl.querySelector("p").innerHTML = copy.body;
  emptyStateEl.querySelector(".empty-state-steps").innerHTML = copy.steps
    .map((s, i) => `<div><span class="step-num">${i + 1}</span> ${s}</div>`)
    .join("");
}

// A real Google Calendar deep link (calendar.google.com's own URL-based
// event creation — no API key, no OAuth, just a pre-filled compose screen
// the traveler still has to hit "Save" on themselves) for a trip that's
// actually confirmed. Google's all-day end date is exclusive, so the last
// day needs +1 to actually include it on the calendar.
function googleCalendarUrl(plan) {
  const start = plan.days[0].date;
  const endDate = new Date(plan.days[plan.days.length - 1].date + "T00:00:00");
  endDate.setDate(endDate.getDate() + 1);
  const fmt = (s) => s.replace(/-/g, "");
  const params = new URLSearchParams({
    action: "TEMPLATE",
    text: `Trip to ${plan.destination_city}`,
    dates: `${fmt(start)}/${fmt(toLocalDateString(endDate))}`,
    details: plan.reasoning_summary || `Trip from ${plan.origin_city} to ${plan.destination_city}`,
    location: `${plan.destination_city}, ${plan.destination_country}`,
  });
  return `https://calendar.google.com/calendar/render?${params.toString()}`;
}

// Only a confirmed trip (currentTripMeta.tripId set — see saveTrip and the
// Saved Trips card click) gets a calendar link; a plan that's merely been
// generated isn't a real commitment yet.
function updateCalendarLink() {
  const row = document.getElementById("calendar-link-row");
  const link = document.getElementById("calendar-link");
  if (currentPlan && currentTripMeta && currentTripMeta.tripId) {
    link.href = googleCalendarUrl(currentPlan);
    row.hidden = false;
  } else {
    row.hidden = true;
  }
}

// Renders Trip Planner's own last-known state into the shared results panel
// — called both right after a new plan finishes and when switching back to
// this tab, so either way the traveler sees exactly what they left behind.
function showTripResults(plan, meta) {
  clearResultsPanel();
  resultsTitleEl.textContent = "Trip Overview";
  if (!plan) {
    setEmptyStateForTab("trip");
    emptyStateEl.hidden = false;
    return;
  }
  dailyPlanSectionEl.hidden = false;
  renderSummary(plan, meta);
  renderMap(plan);
  renderItinerary(plan);
  renderHotelOptions(plan);
  checkUpdatesBtn.hidden = false;
  // A confirmed trip (already saved — see saveTrip/the Saved Trips card
  // click) shows the calendar link instead of "save me" controls it no
  // longer needs.
  const confirmed = !!(meta && meta.tripId);
  saveTripRow.hidden = confirmed;
  updateCalendarLink();
}

// Day Out's counterpart to showTripResults — deliberately never touches
// hotelOptionsSectionEl/checkUpdatesBtn/saveTripRow (clearResultsPanel
// already hid them): a day out has no hotel, no booking, and nothing for
// the background monitor to watch.
function showDayResults(plan) {
  clearResultsPanel();
  resultsTitleEl.textContent = "Day Overview";
  if (!plan) {
    setEmptyStateForTab("day");
    emptyStateEl.hidden = false;
    return;
  }
  dailyPlanSectionEl.hidden = false;
  renderDaySummary(plan);
  renderDayMap(plan);
  renderDayItinerary(plan);
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
async function streamPlan(endpoint, payload, headers, onProgress, signal) {
  const res = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify(payload),
    signal,
  });
  if (!res.ok) {
    if (res.status === 401) logout();
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

async function planTripStream(payload, onProgress, signal) {
  return streamPlan("/api/plan/stream", payload, { "X-Session-Token": sessionToken }, onProgress, signal);
}

async function planDayStream(payload, onProgress, signal) {
  // Also used as the rate-limit key (see backend/ratelimit.py) and to
  // attribute day-plan feedback back to this account.
  return streamPlan("/api/day-plan/stream", payload, { "X-Session-Token": sessionToken }, onProgress, signal);
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
      body: JSON.stringify({ plan: currentPlan, alerts: saveTripAlerts.checked }),
    });
    if (!res.ok) throw new Error(`Save failed (${res.status})`);
    const data = await res.json();
    currentTripMeta = { ...currentTripMeta, tripId: data.trip_id };
    saveTripRow.hidden = true;
    updateCalendarLink();
    saveTripStatus.textContent = `Saved (trip #${data.trip_id}) — the agent will check this automatically in the background.`;
    saveLastView("trip", currentPlan, currentTripMeta);
    fetchTrips();
  } catch (e) {
    saveTripStatus.textContent = `Couldn't save: ${e.message}`;
  } finally {
    saveTripBtn.disabled = false;
    saveTripBtn.textContent = "Save & monitor this trip";
  }
}

// The wishlist counterpart to "Save & monitor" — for a plan that's real and
// good, but not locked in yet. Reuses /api/wishlist's real geocode + immediate
// outlook rather than a separate endpoint, just pre-filled from the plan
// that's already on screen instead of asking the traveler to re-enter it.
async function saveTripToWishlist() {
  if (!currentPlan) return;
  saveWishlistBtn.disabled = true;
  saveTripStatus.textContent = "";
  try {
    const days = currentPlan.days;
    const res = await authedFetch("/api/wishlist", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        origin_city: currentPlan.origin_city,
        destination: currentPlan.destination_city,
        earliest_date: days[0].date,
        latest_date: days[days.length - 1].date,
        trip_length_days: days.length,
        budget: currentPlan.budget,
        currency: currentPlan.currency,
        interests: form.interests.value || "general sightseeing",
        alerts: saveTripAlerts.checked,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Save failed (${res.status})`);
    }
    saveTripStatus.textContent = "Saved to your wishlist.";
    fetchWishlistItems();
  } catch (e) {
    saveTripStatus.textContent = `Couldn't save: ${e.message}`;
  } finally {
    saveWishlistBtn.disabled = false;
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

function renderSummary(plan, tripMeta) {
  resultsTitleEl.textContent = "Trip Overview";
  const budgetClass = plan.within_budget ? "within-budget" : "over-budget";
  const { travelers, nights } = tripMeta;

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

  // Three real cases, not just within/over: safely under budget even in the
  // worst case, under budget only if things go cheap, or over budget even in
  // the best case — each needs different wording to stay honest about risk.
  const bestCaseMargin = plan.budget - plan.total_estimated_cost_low;
  const worstCaseMargin = plan.budget - plan.total_estimated_cost_high;
  let budgetHint;
  if (worstCaseMargin >= 0) {
    budgetHint = `${formatMoney(worstCaseMargin, plan.currency)} under your ${formatMoney(plan.budget, plan.currency)} budget, even in the worst case`;
  } else if (bestCaseMargin >= 0) {
    budgetHint = `could run up to ${formatMoney(-worstCaseMargin, plan.currency)} over your ${formatMoney(plan.budget, plan.currency)} budget in the worst case`;
  } else {
    budgetHint = `at least ${formatMoney(-bestCaseMargin, plan.currency)} over your ${formatMoney(plan.budget, plan.currency)} budget`;
  }

  const isDriving = plan.transportation === "drive";
  const travelLabel = isDriving ? "Driving" : "Flight";
  const travelHint = isDriving
    ? "round trip, one vehicle for the whole group"
    : travelers
      ? `round trip, for all ${travelers} traveler${travelers === 1 ? "" : "s"} combined`
      : "round trip, for all travelers combined";

  const hotelLowTotal = plan.hotel.estimated_price_low * nights;
  const hotelHighTotal = plan.hotel.estimated_price_high * nights;

  costSectionEl.hidden = false;
  costStatsEl.innerHTML = `
    <div class="stat ${budgetClass}">
      <div class="label">Total estimated cost</div>
      <div class="value">${formatMoney(plan.total_estimated_cost_low, plan.currency)}–${formatMoney(plan.total_estimated_cost_high, plan.currency)}</div>
      <div class="hint">${budgetHint}</div>
    </div>
    <div class="stat">
      <div class="label">${travelLabel}</div>
      <div class="value">${formatMoneyRange(plan.flight.estimated_price_low, plan.flight.estimated_price_high, plan.currency)}</div>
      <div class="hint">${travelHint}</div>
      ${plan.flight.note ? `<div class="hint">${escapeHtml(plan.flight.note)}</div>` : ""}
    </div>
    <div class="stat">
      <div class="label">Hotel</div>
      <div class="value">${formatMoney(plan.hotel.estimated_price_low, plan.currency)}–${formatMoney(plan.hotel.estimated_price_high, plan.currency)} / night</div>
      <div class="hint">× ${nights} night${nights === 1 ? "" : "s"} = ${formatMoney(hotelLowTotal, plan.currency)}–${formatMoney(hotelHighTotal, plan.currency)}</div>
    </div>
  `;

  bookingLinksEl.hidden = false;
  const travelLinkLabel = plan.transportation === "drive" ? "View driving directions" : "View live flights & book";
  bookingLinksEl.innerHTML = `
    <a href="${escapeHtml(plan.flight.booking_link)}" target="_blank" rel="noopener" class="link-btn primary">${travelLinkLabel}</a>
    <a href="${escapeHtml(plan.hotel.booking_link)}" target="_blank" rel="noopener" class="link-btn primary">View live hotels & book</a>
  `;
}

// Real hotels near the destination (see tools/hotels.py's OpenStreetMap
// search) the traveler can actually pick between — picking one calls
// /api/plan/choose-hotel to re-anchor every activity's travel time to that
// specific hotel (pure recompute, no agent call). "Chosen" is inferred from
// hotel.suggested_neighborhood exactly matching a name here, which is only
// true after a real choice — see server.py's choose_hotel.
let hotelChoiceInFlight = false;

function renderHotelOptions(plan) {
  const options = (plan.hotel && plan.hotel.named_options) || [];
  if (!options.length) {
    hotelOptionsSectionEl.hidden = true;
    hotelOptionsEl.innerHTML = "";
    return;
  }

  hotelOptionsSectionEl.hidden = false;
  hotelOptionsEl.innerHTML = "";
  const chosenName = plan.hotel.suggested_neighborhood;

  for (const hotel of options) {
    const isChosen = hotel.name === chosenName;
    const card = document.createElement("div");
    card.className = "event-card" + (isChosen ? " chosen" : "");
    card.innerHTML = `
      <div class="event-name">${escapeHtml(hotel.name)}</div>
      <div class="event-meta">${escapeHtml(hotel.category)}${isChosen ? " · chosen" : ""}</div>
      <div class="event-actions"></div>
    `;
    const actions = card.querySelector(".event-actions");

    const mapsLink = document.createElement("a");
    mapsLink.href = hotel.maps_link;
    mapsLink.target = "_blank";
    mapsLink.rel = "noopener";
    mapsLink.className = "link-btn";
    mapsLink.textContent = "View on Maps ↗";
    actions.appendChild(mapsLink);

    if (!isChosen) {
      const chooseBtn = document.createElement("button");
      chooseBtn.type = "button";
      chooseBtn.className = "link-btn primary";
      chooseBtn.textContent = "Choose this hotel";
      chooseBtn.addEventListener("click", () => chooseHotel(hotel, chooseBtn));
      actions.appendChild(chooseBtn);
    }

    hotelOptionsEl.appendChild(card);
  }
}

async function chooseHotel(hotel, btn) {
  if (hotelChoiceInFlight || !currentPlan) return;
  hotelChoiceInFlight = true;
  const originalText = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Updating...";
  hideError();
  try {
    const res = await fetch("/api/plan/choose-hotel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan: currentPlan, hotel_name: hotel.name, hotel_lat: hotel.lat, hotel_lon: hotel.lon }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Request failed (${res.status})`);
    }
    const updatedPlan = await res.json();
    currentPlan = updatedPlan;
    renderSummary(updatedPlan, currentTripMeta);
    renderMap(updatedPlan);
    renderItinerary(updatedPlan);
    renderHotelOptions(updatedPlan);
    saveLastView("trip", updatedPlan, currentTripMeta);
  } catch (e) {
    showError(`Couldn't switch hotels: ${e.message}`);
  } finally {
    hotelChoiceInFlight = false;
    btn.disabled = false;
    btn.textContent = originalText;
  }
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
        ${day.events.length ? `<div class="day-events-label">🎟 Tickets</div><div class="day-events"></div>` : ""}
      </div>
    `;
    if (day.events.length) {
      const eventsWrap = card.querySelector(".day-events");
      for (const ev of day.events) {
        eventsWrap.appendChild(eventCardEl(ev, plan.destination_city, "hotel"));
      }
    }
    itineraryEl.appendChild(card);
  }
}

const COMMUTE_ICONS = { walk: "🚶", drive: "🚗", bus: "🚌" };

// Real straight-line distance/time (server-computed — see
// backend/src/trip_agent/travel_estimates.py) from a real anchor point —
// Trip Planner's hotel area, or Day Out's chosen location/city center — to
// this place, with any real alternative commute mode (e.g. bus for a
// farther trip) alongside the primary one. Never present for a themed/
// generic suggestion with no real coordinates to measure from.
function travelInfoHtml(place, anchorLabel = "hotel") {
  if (place.travel_mode == null || place.distance_km == null) return "";
  const options = place.commute_options && place.commute_options.length
    ? place.commute_options
    : [{ mode: place.travel_mode, minutes: place.travel_minutes }];
  const parts = options.map((o) => `${COMMUTE_ICONS[o.mode] || ""} ~${o.minutes} min by ${o.mode}`);
  return ` <span class="hint">${parts.join(" · or ")} (${place.distance_km} km) each way from ${anchorLabel}</span>`;
}

function placeRecHtml(place, inline = false, anchorLabel = "hotel") {
  const link = `<a href="${escapeHtml(place.maps_link)}" target="_blank" rel="noopener" class="place-link" title="View on Google Maps">${escapeHtml(place.name)} ↗</a>`;
  const travel = travelInfoHtml(place, anchorLabel);
  return inline ? link + travel : `<li>${link}${travel}</li>`;
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
    alerts: data.wl_alerts === "on",
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
    event_type: data.watch_event_type || "",
    alerts: data.watch_alerts === "on",
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
      <div class="meta">${escapeHtml([item.event_type, item.mood_or_interest].filter(Boolean).join(" · ") || "general sightseeing")}</div>
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

// Saved trips render as closed book covers — destination front and center,
// the real details (map, day-by-day itinerary, hotel options, calendar
// link) only appear once the traveler actually opens one, same as a real
// book on a shelf rather than a dense list row.
function renderTripsList(trips) {
  const tripsListEl = document.getElementById("trips-list");
  tripsListEl.innerHTML = "";
  if (trips.length === 0) {
    tripsListEl.innerHTML = `<div class="trips-empty">No saved trips yet. Plan one and hit "Save & monitor this trip".</div>`;
    return;
  }
  for (const trip of trips) {
    const plan = trip.plan;
    const nights = Math.max(1, Math.round((new Date(trip.end_date) - new Date(trip.start_date)) / 86400000));

    const wrap = document.createElement("div");
    wrap.className = "trip-book-wrap";

    const book = document.createElement("button");
    book.type = "button";
    book.className = "trip-book";
    book.setAttribute("aria-label", `Open saved trip to ${plan.destination_city}`);
    book.innerHTML = `
      <div class="trip-book-spine"></div>
      <div class="trip-book-cover">
        <span class="item-kind-badge" title="Confirmed trip">Trip</span>
        <div class="trip-book-title">${escapeHtml(plan.destination_city)}</div>
        <div class="trip-book-sub">${escapeHtml(plan.destination_country)}</div>
        <div class="trip-book-dates">${escapeHtml(trip.start_date)} → ${escapeHtml(trip.end_date)}</div>
        <div class="trip-book-cost">${formatMoney(plan.total_estimated_cost_low, plan.currency)}–${formatMoney(plan.total_estimated_cost_high, plan.currency)}</div>
        <div class="trip-book-open">Open →</div>
      </div>
    `;
    book.addEventListener("click", () => {
      currentPlan = plan;
      currentTripMeta = { travelers: null, nights, tripId: trip.id };
      showTripResults(plan, currentTripMeta);
      hideError();
      setStatus("Viewing saved trip.");
      saveLastView("trip", plan, currentTripMeta);
    });

    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "trip-book-remove";
    removeBtn.title = "Remove this saved trip";
    removeBtn.setAttribute("aria-label", "Remove this saved trip");
    removeBtn.textContent = "✕";
    removeBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      await authedFetch(`/api/trips/${trip.id}/archive`, { method: "POST" });
      fetchTrips();
    });

    wrap.appendChild(book);
    wrap.appendChild(removeBtn);
    tripsListEl.appendChild(wrap);
  }
}

let planAbortController = null;

async function submitPlan() {
  const payload = readFormData();
  planAbortController = new AbortController();
  planBtn.disabled = true;
  planBtn.textContent = "Planning...";
  planStopBtn.hidden = false;
  setStatus("Starting up...");
  hideError();
  emptyStateEl.hidden = true;
  dailyPlanSectionEl.hidden = false;
  loadingSkeletonEl.hidden = false;
  itineraryEl.hidden = true;
  try {
    const plan = await planTripStream(payload, (message) => setStatus(message), planAbortController.signal);
    currentPlan = plan;
    const nights = Math.max(1, Math.round((new Date(payload.end_date) - new Date(payload.start_date)) / 86400000));
    const tripMeta = { travelers: payload.travelers, nights };
    currentTripMeta = tripMeta;
    showTripResults(plan, tripMeta);
    saveTripStatus.textContent = "";
    setStatus("Plan ready.");
    saveLastView("trip", plan, tripMeta);
  } catch (e) {
    if (e.name === "AbortError") {
      setStatus("Stopped.");
    } else {
      showError(`Couldn't plan this trip: ${e.message}`);
      setStatus("");
    }
    if (!currentPlan) {
      showTripResults(null, null);
    }
  } finally {
    loadingSkeletonEl.hidden = true;
    itineraryEl.hidden = false;
    planBtn.disabled = false;
    planBtn.textContent = "Plan my trip";
    planStopBtn.hidden = true;
    planAbortController = null;
  }
}

function setDayStatus(message, isError = false) {
  dayStatusEl.hidden = !message;
  dayStatusEl.textContent = message;
  dayStatusEl.classList.toggle("error", isError);
}

function readDayFormData() {
  const data = Object.fromEntries(new FormData(dayForm).entries());
  const payload = {
    city: data.day_city,
    date: data.day_date,
    mood_or_interest: data.day_mood || "general sightseeing",
    event_type: data.day_event_type || "",
    max_events: Number(data.day_max_events) || 5,
    dietary_needs: data.day_dietary_needs || "none",
  };
  // Real device/account coordinates (see dayOutLocation above) — anchors
  // every nearby search to this exact point instead of the city's center
  // (see agent.py's DAY_SYSTEM_PROMPT). Omitted entirely when the traveler
  // just typed a city name, so the backend falls back to geocoding it.
  if (dayOutLocation) {
    payload.lat = dayOutLocation.lat;
    payload.lon = dayOutLocation.lon;
    payload.country = dayOutLocation.country;
    payload.country_code = dayOutLocation.country_code;
  }
  return payload;
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

function eventCardEl(ev, cityLabel, anchorLabel = "hotel") {
  const div = document.createElement("div");
  div.className = "event-card";
  const metaParts = [ev.category];
  if (ev.date) metaParts.push(ev.date + (ev.time ? " " + ev.time.slice(0, 5) : ""));
  if (ev.venue_name) metaParts.push(ev.venue_name);
  div.innerHTML = `
    <div class="event-name">${escapeHtml(ev.name)}</div>
    <span class="ticket-required-badge">🎫 Ticket required</span>
    <div class="event-meta">${escapeHtml(metaParts.join(" · "))}${travelInfoHtml(ev, anchorLabel)}</div>
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
      <ul>${plan.activities.map((a) => placeRecHtml(a, false, "your location")).join("")}</ul>
      <div class="restaurant">${placeRecHtml(plan.restaurant, true, "your location")}</div>
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
      itineraryEl.appendChild(eventCardEl(ev, plan.city, "your location"));
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
let dayPlanAbortController = null;

async function submitDayPlan() {
  const payload = readDayFormData();
  dayPlanAbortController = new AbortController();
  dayPlanBtn.disabled = true;
  dayPlanBtn.textContent = "Planning...";
  dayPlanStopBtn.hidden = false;
  setDayStatus("Starting up...");
  hideError();
  emptyStateEl.hidden = true;
  dailyPlanSectionEl.hidden = false;
  loadingSkeletonEl.hidden = false;
  itineraryEl.hidden = true;
  checkUpdatesBtn.hidden = true;
  saveTripRow.hidden = true;
  hotelOptionsSectionEl.hidden = true;
  try {
    const plan = await planDayStream(payload, (message) => setDayStatus(message), dayPlanAbortController.signal);
    currentDayPlan = plan;
    showDayResults(plan);
    setDayStatus("Day plan ready.");
    saveLastView("day", plan, null);
  } catch (e) {
    if (e.name === "AbortError") {
      setDayStatus("Stopped.");
    } else {
      showError(`Couldn't plan this day: ${e.message}`);
      setDayStatus("");
    }
    if (!currentDayPlan) {
      showDayResults(null);
    }
  } finally {
    loadingSkeletonEl.hidden = true;
    itineraryEl.hidden = false;
    dayPlanBtn.disabled = false;
    dayPlanBtn.textContent = "Plan my day";
    dayPlanStopBtn.hidden = true;
    dayPlanAbortController = null;
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

planStopBtn.addEventListener("click", () => planAbortController?.abort());
dayPlanStopBtn.addEventListener("click", () => dayPlanAbortController?.abort());

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
saveWishlistBtn.addEventListener("click", saveTripToWishlist);
notifBell.addEventListener("click", () => {
  const opening = notifPanel.hidden;
  closeAllPanels();
  notifPanel.hidden = !opening;
  notifBell.setAttribute("aria-expanded", String(!notifPanel.hidden));
});
// Logged in: the account icon is just a shortcut into the Settings tab
// (real account info lives there now, not a second dropdown surface).
// Logged out: it's the only way to reach login/signup, so it still opens
// that dropdown.
accountBtn.addEventListener("click", () => {
  if (currentUser) {
    document.querySelector('[data-tab="settings-tab"]').click();
    return;
  }
  const opening = accountPanel.hidden;
  closeAllPanels();
  accountPanel.hidden = !opening;
  accountBtn.setAttribute("aria-expanded", String(!accountPanel.hidden));
});
errorBannerDismissBtn.addEventListener("click", hideError);

document.querySelectorAll(".account-tab-btn").forEach((tabBtn) => {
  tabBtn.addEventListener("click", () => {
    document.querySelectorAll(".account-tab-btn").forEach((b) => b.classList.toggle("active", b === tabBtn));
    const isLogin = tabBtn.dataset.accountTab === "login";
    loginForm.hidden = !isLogin;
    signupForm.hidden = isLogin;
    setAccountAuthStatus("");
  });
});
loginForm.addEventListener("submit", submitLogin);
signupForm.addEventListener("submit", submitSignup);
logoutBtn.addEventListener("click", logout);
preferencesForm.addEventListener("submit", submitPreferences);
settingsForm.addEventListener("submit", submitSettings);
inviteFriendBtn.addEventListener("click", inviteFriend);
deleteAccountBtn.addEventListener("click", openDeleteAccountConfirm);
deleteAccountCancelBtn.addEventListener("click", closeDeleteAccountConfirm);
deleteAccountConfirmBtn.addEventListener("click", confirmDeleteAccount);
deleteAccountConfirmInput.addEventListener("input", () => {
  deleteAccountConfirmBtn.disabled = deleteAccountConfirmInput.value !== "DELETE";
});
useMyLocationBtn.addEventListener("click", useMyLocationForAccount);
document.querySelectorAll(".use-location-inline").forEach((btn) => {
  btn.addEventListener("click", () => useMyLocationForField(btn));
});
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
// Each tab keeps its own results state (currentPlan/currentDayPlan) and its
// own last-generated-plan storage (see saveLastView) — switching tabs
// re-renders whichever plan belongs to the tab just opened (or that tab's
// own empty state, if it has no plan yet) instead of leaving the previously
// active tab's results on screen. The active tab itself is remembered too,
// so a reload comes back to wherever the traveler actually left off.
document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => {
      b.classList.toggle("active", b === btn);
      b.setAttribute("aria-selected", String(b === btn));
    });
    document.querySelectorAll(".tab-panel").forEach((panel) => {
      panel.hidden = panel.id !== btn.dataset.tab;
    });
    try {
      sessionStorage.setItem(LAST_ACTIVE_TAB_KEY, btn.dataset.tab);
    } catch {
      // Storage full/unavailable — non-fatal, just no tab-restore on reload.
    }
    if (currentUser) {
      if (btn.dataset.tab === "trips-tab") {
        fetchTrips();
        fetchWishlistItems();
      }
      if (btn.dataset.tab === "day-tab") fetchWatchItems();
    }
    if (btn.dataset.tab === "trip-tab") {
      showTripResults(currentPlan, currentTripMeta);
    } else if (btn.dataset.tab === "day-tab") {
      showDayResults(currentDayPlan);
    } else if (btn.dataset.tab === "settings-tab") {
      resetSettingsTabState();
    }
  });
});

// Restores whatever plan was on screen in each tab before a reload (see
// saveLastView) — no network call, just re-rendering already-real data that
// was already fetched once. Loads both tabs' saved plans into memory
// regardless of which was active, then re-opens whichever tab was actually
// active — clicking it triggers the handler above, which renders that tab's
// plan (or its empty state, if only the other tab had one saved).
function restoreLastView() {
  try {
    const raw = sessionStorage.getItem(LAST_TRIP_VIEW_KEY);
    const saved = raw && JSON.parse(raw);
    if (saved && saved.plan) {
      currentPlan = saved.plan;
      currentTripMeta = saved.meta;
    }
  } catch {
    sessionStorage.removeItem(LAST_TRIP_VIEW_KEY);
  }

  try {
    const raw = sessionStorage.getItem(LAST_DAY_VIEW_KEY);
    const saved = raw && JSON.parse(raw);
    if (saved && saved.plan) {
      currentDayPlan = saved.plan;
    }
  } catch {
    sessionStorage.removeItem(LAST_DAY_VIEW_KEY);
  }

  const lastTab = sessionStorage.getItem(LAST_ACTIVE_TAB_KEY);
  const tabBtn = lastTab && document.querySelector(`[data-tab="${lastTab}"]`);
  if (tabBtn) {
    tabBtn.click();
  } else {
    // First-ever visit, or nothing to restore — trip-tab is already the
    // active tab in the markup, just needs its (empty) results rendered.
    showTripResults(currentPlan, currentTripMeta);
  }
}

initMap();
setDefaultDates();
restoreLastView();

// Map/date setup above doesn't depend on login state, so it runs
// immediately; restoreSession() (which loads account data itself once a
// valid session is confirmed — see loadAccountData) resolves independently.
restoreSession().then(() => {
  prefillFromHomeLocation();
  applyPreferences();
});

landingCtaBtn.addEventListener("click", () => {
  accountPanel.hidden = false;
  accountBtn.setAttribute("aria-expanded", "true");
});
