# Trip Planner Agent

An AI agent, built with [Strands Agents SDK](https://strandsagents.com/) and Amazon Bedrock (Claude), that plans a real, bookable-shaped trip end to end — not just a list of suggestions.

## The problem

Planning a trip means juggling a dozen open browser tabs: flight prices, hotel options, weather, what's actually walkable, what's open, what fits a budget. It's a repetitive research task most people redo from scratch every time they travel, and it doesn't stop once the plan is "done" — prices and forecasts keep changing right up to departure.

**Who it's for:** budget-conscious travelers planning a short domestic trip who want a concrete, personalized itinerary without doing the research themselves.

**Why it matters:** this agent does the actual research and decision-making — comparing flight/hotel options, checking real weather, matching activities to stated interests and dietary needs — and hands back one finished plan instead of a pile of tabs. After the plan is locked, it keeps watching in the background and only interrupts the traveler when something actually changes (a price drop, a bad-weather day) — the same "only surface for a real decision" pattern the plan is built around.

## What it does

**Phase 1 — Interactive planning.** Give it a starting city, a destination (or leave it blank and let the agent recommend one), dates, number of travelers, total budget, interests, transportation/accommodation preferences, and dietary needs. The agent:
- Geocodes the origin/destination
- Pulls a real weather forecast for the travel dates
- Computes distance and travel time
- Estimates a flight/hotel price range and generates a **real Google Flights / Google Hotels link**, pre-filled with the exact route and dates, so the traveler sees real current airlines, hotels, and prices and books directly there
- Finds restaurants and activities matching dietary needs and interests — real named places when available, each with a **real Google Maps link**; otherwise a themed recommendation (e.g. "vegetarian dinner near downtown") plus a real Maps search link, never a made-up business name
- Builds a day-by-day itinerary and flags whether the whole trip fits the budget

The app deliberately never invents a specific airline, hotel, or restaurant name and presents it as bookable. See [Why not just call a flight/hotel API?](#why-not-just-call-a-flighthotel-api) below.

The map and itinerary **update live** — editing any field after a plan exists automatically re-plans, no resubmit needed.

**Phase 2 — Background re-optimization, running on its own.** Click "💾 Save & monitor this trip" and the plan is persisted server-side. From that point on, a scheduler running inside the backend (no user action, no open browser tab required) wakes up on a timer, re-checks the live weather forecast and re-estimates flight/hotel pricing for every saved trip, and only writes something down when it crosses a real threshold (a meaningful estimated price move, or a day with a high chance of rain). Surfaced updates land in the in-app notification inbox (bell icon, polled automatically) and, if an email was provided, are also sent via Amazon SES — so the traveler can find out about a real decision worth making without ever having to ask. It never books anything or silently rewrites the plan.

There's also a manual "Check this plan now" button for the trip currently on screen — useful for an instant check without waiting for the schedule, but the actual autonomous behavior is the scheduler, not that button.

### Why not just call a flight/hotel API?

We looked. As of this build (August 2026), there is no free, instantly-self-serve API that returns real live flight/hotel prices: **Amadeus Self-Service shut down in July 2026**, Duffel's free test mode only returns a fake sandbox airline ("Duffel Airways") rather than real carriers, and Kiwi/Skyscanner/Booking.com/Expedia are invite-only or require an approved commercial partnership. Rather than fabricate a plausible-sounding airline or hotel name — which is worse than useless, since a traveler could act on it — the agent estimates a realistic price range for budget planning and hands back a real Google Flights/Hotels/Maps deep link (Google's own documented URL scheme, not scraping) so the traveler always sees genuine, current, bookable options.

See [docs/architecture.md](docs/architecture.md) for the full data flow diagram.

## Tech stack

- **Agent:** [Strands Agents SDK](https://strandsagents.com/) (Python), running on Claude via **Amazon Bedrock**
- **Backend:** FastAPI
- **Frontend:** plain HTML/CSS/JS + [Leaflet](https://leafletjs.com/) (no build step, no Node.js required)
- **Data:** Open-Meteo (geocoding + weather, free/no key), OpenStreetMap Overpass API (best-effort real POI data), real Google Flights/Hotels/Maps deep links for actual booking (see [docs/architecture.md](docs/architecture.md) for why we don't call a paid flight/hotel API)
- **Background automation:** APScheduler (in-process scheduled job), SQLite (saved trips + notification inbox), Amazon SES (optional email alerts)

## Setup

### Prerequisites

- Python 3.10+
- An AWS account with:
  - Bedrock **model access** granted for a Claude model (Bedrock console → Model access)
  - An IAM user/role with `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream` permissions
  - AWS credentials available locally, either via `aws configure` (writes `~/.aws/credentials`) or environment variables (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION`)
  - (Optional) a verified sender identity in **Amazon SES** if you want email alerts from the background scheduler — without it, surfaced updates still land in the in-app notification inbox, just not by email

### Install & run

```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt

# optional: copy backend/.env.example to backend/.env and adjust the model id/region
cp .env.example .env

uvicorn trip_agent.server:app --app-dir src --reload
```

Then open **http://localhost:8000** — the backend serves the frontend directly, so there's nothing else to start. The background scheduler starts automatically with the server (default: checks every 4 hours — set `MONITOR_INTERVAL_MINUTES=1` in `backend/.env` for a fast demo loop). Set `SES_SENDER_EMAIL` in `backend/.env` to enable email alerts.

### Quick smoke test (no server needed)

```bash
cd backend
python test_agent.py
```

Runs the agent once against a sample trip and prints the resulting JSON plan — useful to confirm your AWS/Bedrock setup works before touching the UI.

## Project structure

```
trip-planner-agent/
├── backend/
│   └── src/trip_agent/
│       ├── agent.py       # Strands Agent definition + system prompt
│       ├── schema.py      # Pydantic TripPlan structured-output schema
│       ├── server.py      # FastAPI app (/api/plan, /api/trips, /api/notifications, /api/monitor)
│       ├── monitor.py     # Re-check logic (weather + price-drift heuristics)
│       ├── scheduler.py   # APScheduler background sweep — the actual autonomy
│       ├── db.py          # SQLite: saved trips + notification inbox
│       ├── notify.py      # Optional Amazon SES email alerts
│       └── tools/         # geocode, weather, routing, flights, hotels, places
├── frontend/               # static HTML/CSS/JS + Leaflet map
└── docs/architecture.md    # architecture diagram + data flow
```

## Known limitations / roadmap

- Flight and hotel pricing shown inline is an **estimate range**, not a live booking feed — see [Why not just call a flight/hotel API?](#why-not-just-call-a-flighthotel-api). The real, current numbers are always one click away via the Google Flights/Hotels links.
- No live GPS tracking during the actual trip — intentionally out of scope for this build (see architecture doc); background monitoring covers the pre-departure window instead.
- Currently assumes flight as the primary transportation mode in the itinerary math even when "drive" is selected.
- No user accounts — saved trips and the notification inbox are global rather than scoped per traveler. Fine for a demo/single-user setup; a real multi-user product would need auth.
- The scheduler runs in-process, so it only checks trips while the backend process is running. Deploying via **Amazon Bedrock AgentCore** (or any always-on host) is the natural next step to make that durable in production, and would also strengthen the Technical Implementation story.

## License

MIT — see [LICENSE](LICENSE).
