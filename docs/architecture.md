# Architecture

```mermaid
flowchart TB
    subgraph Browser
        UI["Web UI (HTML/CSS/JS + Leaflet map)\nnotification bell polls every 30s"]
    end

    subgraph Backend["FastAPI backend (Python)"]
        API["/api/plan, /api/trips,\n/api/notifications, /api/monitor"]
        Agent["Strands Agent\n(Claude via Amazon Bedrock)"]
        Monitor["monitor.py\nweather + price-drift heuristics"]
        Scheduler["scheduler.py\nAPScheduler background job\n(runs on a timer, no user action)"]
        DB[("SQLite\ntrips + notifications")]
    end

    subgraph Tools["Agent tools"]
        Geo["geocode_city"]
        Weather["get_weather_forecast"]
        Route["estimate_distance"]
        Flights["search_flights"]
        Hotels["search_hotels"]
        Rest["search_restaurants"]
        Act["search_activities"]
    end

    subgraph External["External data sources"]
        Bedrock[("Amazon Bedrock\nClaude Sonnet")]
        OpenMeteo[("Open-Meteo\ngeocoding + weather APIs")]
        Overpass[("OpenStreetMap Overpass API\n(best-effort, unreliable)")]
        GoogleLinks[("Google Flights / Hotels / Maps\nreal deep links, opened by the traveler")]
        Estimator[("Price-range estimator\n(budget planning only)")]
        SES[("Amazon SES\noptional email alerts")]
    end

    UI -- "1. POST preferences" --> API
    API --> Agent
    Agent -- "reasons + calls tools" --> Tools
    Agent <-- "inference" --> Bedrock

    Geo --> OpenMeteo
    Weather --> OpenMeteo
    Rest --> Overpass
    Act --> Overpass
    Rest --> GoogleLinks
    Act --> GoogleLinks
    Flights --> Estimator
    Flights --> GoogleLinks
    Hotels --> Estimator
    Hotels --> GoogleLinks

    Agent -- "2. structured TripPlan JSON" --> API
    API -- "3. itinerary + map pins" --> UI

    UI -- "4. Save & monitor this trip" --> API
    API -- "persist" --> DB

    Scheduler -- "5. wakes on a timer, reads every active trip" --> DB
    Scheduler --> Monitor
    Monitor --> Weather
    Scheduler -- "6. writes only real decisions" --> DB
    Scheduler -. "optional" .-> SES

    UI -- "7. polls" --> API
    API -- "unread notifications" --> DB
    DB -- "8. surfaced to the bell icon" --> UI
```

## Flow

1. **Phase 1 — Interactive planning.** The traveler fills in origin, destination (optional), dates, budget, interests, transportation, accommodation, and dietary needs in the web UI. Editing any field after a plan exists triggers a debounced re-plan, so the itinerary and map stay live-updated without a manual resubmit.
2. **Agent reasoning.** The FastAPI backend hands the request to a Strands `Agent` running on Claude (via Amazon Bedrock). The agent decides which tools to call and in what order — geocoding, weather, distance, flights, hotels, restaurants, activities — and reasons over the results to build one concrete itinerary that fits the stated budget and preferences. If no destination was given, the agent picks one itself and says so.
3. **Structured output.** The agent's final answer is constrained to a Pydantic schema (`TripPlan`), so the backend gets clean JSON — flight/hotel estimate + real booking link, day-by-day plan, and map pins — with no text-parsing required.
4. **Locking in a trip.** `POST /api/trips` persists the finished plan to SQLite. This is the moment a disposable plan becomes something the system is responsible for watching.
5. **Autonomous background sweep — the actual "agent," not a button.** `scheduler.py` runs an APScheduler job on a timer (default every 4 hours, configurable) entirely inside the backend process. On each wake-up it reads every active trip from SQLite and calls the same `monitor.check_for_updates()` logic used for on-demand checks — re-checking the live weather forecast and re-estimating flight/hotel pricing. No browser tab needs to be open and no user needs to click anything for this to run.
6. **Surfacing only real decisions.** An update is written to the `notifications` table only when it crosses a real threshold (a meaningful estimated price move, or a day with a high rain chance) — never on every fluctuation, and it never rewrites the plan itself. Every surfaced update carries the same real Google Flights/Hotels booking link, so the traveler can act immediately.
7. **Delivery.** The frontend polls `GET /api/notifications` every 30 seconds and shows a badge/inbox on the bell icon. If the trip was saved with an email address, the same update is also sent via Amazon SES — so a real decision can reach the traveler even if they never reopen the app.

## Data sources

| Tool | Source | Notes |
|---|---|---|
| `geocode_city` | Open-Meteo Geocoding API | Free, no key |
| `get_weather_forecast` | Open-Meteo Forecast API | Free, no key; falls back to a seasonal estimate outside the ~16-day forecast horizon |
| `estimate_distance` | Computed (haversine) | No external dependency, always available |
| `search_restaurants` / `search_activities` | OpenStreetMap Overpass API (best effort) + Google Maps search link (always) | Overpass is unreliable in practice (the public instance returned HTTP 406 during development) so it's treated as bonus enrichment only. Every recommendation — named or themed — always carries a real, official Google Maps deep link (`google.com/maps/search/?api=1&query=...`), so the traveler can always see genuine current options |
| `search_flights` / `search_hotels` | Price-range estimate (for budget math) + Google Flights/Hotels link (for real prices) | No free self-service API returns real live flight/hotel prices as of Aug 2026 — Amadeus Self-Service shut down July 2026, and every remaining option (Duffel live mode, Kiwi, Skyscanner, Booking.com/Expedia) requires an approved business/commercial account. Rather than fabricate a specific airline or hotel name, these tools return an honest estimate range plus a real, pre-filled Google Flights/Hotels deep link showing real current options to book |

**Design principle:** the agent never presents a specific airline, hotel, restaurant, or attraction name as a real bookable option unless a tool actually returned that exact name. Where only an estimate is possible, it's labeled as an estimate and paired with a real link to verify and act on.

## Why a scheduler thread instead of the user triggering checks?

The hackathon brief's whole premise is an agent that "runs autonomously and only surfaces when there's a real decision to make," not another app the user has to open and poll themselves. An on-demand "Check for updates" button (still available for instant checks) doesn't satisfy that — it's the user doing the work of remembering to ask. `scheduler.py` is what actually makes the background monitoring real: it runs on its own schedule, checks every saved trip whether or not anyone is looking, and only writes something down when there's something worth a human decision. Deploying to Amazon Bedrock AgentCore (or any always-on host) would make this durable beyond a single dev-server process — noted as a next step in the README.
