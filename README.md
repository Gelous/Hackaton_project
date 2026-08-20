# Trip Planner Agent

An AI agent, built with [Strands Agents SDK](https://strandsagents.com/) and Amazon Bedrock (Claude), that plans a real, bookable-shaped trip end to end — not just a list of suggestions.

## The problem

Planning a trip means juggling a dozen open browser tabs: flight prices, hotel options, weather, what's actually walkable, what's open, what fits a budget. It's a repetitive research task most people redo from scratch every time they travel, and it doesn't stop once the plan is "done" — prices and forecasts keep changing right up to departure.

**Who it's for:** budget-conscious travelers planning a trip who want a concrete, personalized itinerary without doing the research themselves — whether they already have exact dates, or just a loose "I'd like to go somewhere warm this winter" idea.

**Why it matters:** this agent does the actual research and decision-making — comparing flight/hotel options, checking real weather, matching activities to stated interests and dietary needs — and hands back one finished plan instead of a pile of tabs. Most people's actual relationship with travel isn't "I have exact dates booked," it's loose, occasional intent — which is why the agent doesn't require a firm plan to be useful (see the Wishlist below). Once there's something to watch — a locked plan or a loose wishlist — it keeps working in the background and only interrupts the traveler when something actually changes (a good window opening up, a bad-weather day) — the same "only surface for a real decision" pattern the whole app is built around.

## What it does

**Phase 1 — Interactive planning.** Give it a starting city, a destination (or leave it blank and let the agent recommend one), dates, number of travelers, total budget, interests, transportation/accommodation preferences, and dietary needs. Both city fields are a real worldwide autocomplete (type-ahead, powered by `/api/cities` → Open-Meteo's geocoding search — not a fixed list), and the date pickers block any date before today and keep the return date from landing before departure. The agent:
- Geocodes the origin/destination
- Pulls a real weather forecast for the travel dates
- Computes distance and travel time
- Estimates a flight/hotel price range and generates a **real Google Flights / Booking.com link**, pre-filled with the exact route/destination and dates, so the traveler sees real current airlines, hotels, and prices and books directly there
- Supports 12 currencies, converted with a real live exchange rate (not a guess) — see [How currency conversion works](#how-currency-conversion-works) below
- Finds restaurants and activities matching dietary needs and interests — real named places when available, each with a **real Google Maps link**; otherwise a themed recommendation (e.g. "vegetarian dinner near downtown") plus a real Maps search link, never a made-up business name
- Builds a day-by-day itinerary and flags whether the whole trip fits the budget

While it works, the UI shows real live progress ("Checking the weather...", "Comparing flight options...") streamed straight from which tool the agent is currently calling — not a fake progress bar, an actual trace of the agent's execution.

The app deliberately never invents a specific airline, hotel, or restaurant name and presents it as bookable. See [Why not just call a flight/hotel API?](#why-not-just-call-a-flighthotel-api) below.

The map and itinerary **update live** — editing any field after a plan exists automatically re-plans, no resubmit needed.

**Phase 2 — Background re-optimization, running on its own.** Click "💾 Save & monitor this trip" and the plan is persisted server-side. From that point on, a scheduler running inside the backend (no user action, no open browser tab required) wakes up on a timer, re-checks the live weather forecast and re-estimates flight/hotel pricing for every saved trip, and only writes something down when it crosses a real threshold (a meaningful estimated price move, or a day with a high chance of rain). Surfaced updates land in the in-app notification inbox (bell icon, polled automatically) and, if an email was provided, are also sent via Amazon SES — so the traveler can find out about a real decision worth making without ever having to ask. It never books anything or silently rewrites the plan.

There's also a manual "Check this plan now" button for the trip currently on screen — useful for an instant check without waiting for the schedule, but the actual autonomous behavior is the scheduler, not that button. All your saved trips are visible in the **🧳 My Trips** tab — view any of them again (re-renders the full itinerary and map) or remove one to stop monitoring it.

**Travel Wishlist — no fixed dates required.** The "Plan a Trip" flow above assumes you already know when and where. Most of the time, that's not true — real travel intent usually starts loose: "somewhere warm this winter, under $1,500." The **🌟 Wishlist** tab lets you save exactly that: an origin, an optional destination (or leave it blank and the agent picks one — the only Bedrock call this feature needs, made once at creation), a flexible date range, a trip length, and a budget ceiling. You get an outlook immediately (real weather + a price estimate for the best-looking window in your range, compared against a few candidates — not just the first available one) — and the scheduler re-checks it weekly from then on, using the same tools directly (no repeated LLM cost per check), surfacing a fresh outlook into the same notification inbox whenever there's something worth a look. This is what makes the app useful *before* you've decided to book anything, not just after — which is a much higher-frequency relationship with travel planning than "monitor my already-confirmed trip."

**Plan My Day — everyday use, not just travel.** Most days don't involve a trip at all — sometimes you just want to make the most of one evening in your own city. The **📅 Day Out** tab skips dates/budget/flights entirely: set a city, a date, and a mood or interest ("chill evening", "live music", "adventurous"), and the agent builds a same-day plan — a couple of activities, a restaurant, and any real local concerts/events actually happening that day (via the Ticketmaster Discovery API, when a free API key is configured — see [Setup](#setup)). A found event comes with a real ticket link and a genuine "📅 Add to calendar" download (a real `.ics` file built from the event's actual date/time, no server round-trip). Without a Ticketmaster key, or when nothing real turns up, it's still honest: a themed suggestion plus a real Ticketmaster search link, never an invented concert. Rate the day afterward and that feedback feeds into future Day Planner prompts the same way trip feedback does below.

**🔔 Watch a city — the proactive version of Plan My Day.** Right below the Day Out form: save a city and a mood, and the scheduler checks daily on its own for real new local events, surfacing them into the same notification inbox — no need to come back and ask, no fixed date required. Unlike the Wishlist feature, this never calls the agent at all, not even once — there's no destination to pick, just a fixed city — so it stays a real API call per check, never a Bedrock cost, no matter how many cities you watch or how long. It only ever reports events it hasn't already surfaced for that watch, so it stays a genuine "what's new" feed instead of repeating the same listing every day.

**Post-trip loop.** Once a saved trip's dates pass, the scheduler stops monitoring it (nothing left to check a flight price for) and instead asks how it went, right in the notification inbox — a real 1–5 rating plus an optional note, not a link out to somewhere else. That feedback is stored and, from then on, gets woven into the prompt for every future plan or wishlist destination recommendation for that same browser ("this traveler rated Denver 5/5 — loved the hiking and breweries; rated Miami 2/5 — too crowded and hot"), so the agent's own reasoning can lean into what actually worked and avoid what didn't. It's real stored feedback, not fabricated personalization, and if you've never left feedback the prompt simply omits the section — nothing invented to fill the gap. This is what turns repeat use into something that actually improves, instead of starting cold every time.

### Why not just call a flight/hotel API?

We looked. As of this build (August 2026), there is no free, instantly-self-serve API that returns real *live shopping* flight/hotel prices: **Amadeus Self-Service shut down in July 2026**, Duffel's free test mode only returns a fake sandbox airline ("Duffel Airways") rather than real carriers (and its real production access requires an approved commercial account), and Kiwi/Skyscanner/Booking.com/Expedia's *partner/affiliate APIs* are invite-only or require an approved commercial partnership. Hotels still work this way: the agent estimates a realistic price range (weighted by the same real seasonal-demand pattern used for flights) for budget planning and hands back a real Booking.com search deep-link — not their API, just the same public search URL any visitor would use — so the traveler sees genuine, current, bookable options for their exact dates. Google Hotels was tried first, but its `checkin`/`checkout` URL parameters turned out to be silently ignored (verified by hand — the link opened with an unrelated default date every time), so this uses Booking.com's real, documented search URL instead, which correctly applies both dates.

Flights are a partial exception: [Travelpayouts' free Data API](https://www.travelpayouts.com/) returns real prices cached from actual traveler searches (not live-quoted, and not per-carrier) for a given route, which is a genuinely real number rather than a distance-based guess. `search_flights` uses it when a free `TRAVELPAYOUTS_API_TOKEN` is configured, resolving each city to an IATA code by matching its geocoded coordinates against a bundled Travelpayouts city dataset. If no token is set, no route match is found, or Travelpayouts has nothing cached for that route, it falls back to the same honest distance/season estimate as before — the flight estimate is never a guess presented as fact, and either way a real Google Flights deep link is included so the traveler can see today's actual bookable price.

### How currency conversion works

The agent always reasons and computes in USD internally — its system prompt says so explicitly, and it never estimates or states an exchange rate itself, for the same reason it never invents a flight price: an LLM "converting currency" is just guessing at a plausible number. When a traveler picks a different currency, `server.py` converts their budget to USD *before* the agent ever sees the request, then converts every monetary field in the response back to their currency *after* the agent finishes — using a real live rate from [Frankfurter](https://frankfurter.dev) (ECB-backed, free, no API key). The displayed `budget` is always the traveler's exact original input, not a re-converted approximation, so there's no rounding drift. The one place this doesn't reach is the agent's free-text reasoning — so the system prompt tells it to talk about budget qualitatively there ("comfortably within budget") rather than quoting a dollar figure that could end up silently wrong once converted.

See [docs/architecture.md](docs/architecture.md) for the full data flow diagram.

## Tech stack

- **Agent:** [Strands Agents SDK](https://strandsagents.com/) (Python), running on Claude via **Amazon Bedrock**
- **Backend:** FastAPI
- **Frontend:** plain HTML/CSS/JS + [Leaflet](https://leafletjs.com/) (no build step, no Node.js required)
- **Data:** Open-Meteo (geocoding + weather, free/no key), OpenStreetMap Overpass API (best-effort real POI data), real Google Flights/Booking.com/Google Maps deep links for actual booking (see [docs/architecture.md](docs/architecture.md) for why we don't call a paid flight/hotel API), Ticketmaster Discovery API (optional, real local events for the Day Planner), Travelpayouts Data API (optional, real cached flight prices for Plan My Trip)
- **Background automation:** APScheduler (in-process scheduled job), SQLite (saved trips + notification inbox), Amazon SES (optional email alerts)

## Setup

### Prerequisites

- Python 3.10+
- An AWS account with:
  - Bedrock **model access** granted for a Claude model (Bedrock console → Model access)
  - An IAM user/role with `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream` permissions
  - AWS credentials available locally, either via `aws configure` (writes `~/.aws/credentials`) or environment variables (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION`)
  - (Optional) a verified sender identity in **Amazon SES** if you want email alerts from the background scheduler — without it, surfaced updates still land in the in-app notification inbox, just not by email
- (Optional) a free [Ticketmaster Discovery API](https://developer.ticketmaster.com/) key (`TICKETMASTER_API_KEY` in `backend/.env`) if you want the **Day Planner** and **🔔 Watch a city** to show/surface real concert-event names — without it, both still work: Day Planner links out to a real Ticketmaster search instead of showing specific events, and a city watch just never has anything new to report
- (Optional) a free [Travelpayouts](https://www.travelpayouts.com/) API token (`TRAVELPAYOUTS_API_TOKEN` in `backend/.env`, found under Profile → API token after signing up) if you want **Plan My Trip** to show a real cached flight price instead of a distance/season estimate — without it, flight cost estimation still works exactly as before

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

### Automated tests (no AWS/Bedrock needed)

```bash
cd backend
python -m pytest
```

Covers the pure logic — currency conversion (+ ECB fallback), the signed client_id, rate limiting, ownership-scoped db mutations, the trip monitor's threshold logic, the driving-cost estimate, and the local-watch new-event diffing — with every external call mocked out, so it runs fast, offline, and free. See [Trust & abuse protections](docs/architecture.md#trust--abuse-protections) for what the security-related ones guard against.

## Project structure

```
trip-planner-agent/
├── backend/
│   ├── src/trip_agent/
│   │   ├── agent.py               # Strands Agents (full trip plan, one-shot destination recommendation, single-day plan)
│   │   ├── schema.py              # Pydantic structured-output schemas
│   │   ├── server.py              # FastAPI app — /api/plan, /api/day-plan, /api/local-watch, /api/trips (+ /feedback), /api/wishlist, /api/notifications, /api/monitor
│   │   ├── auth.py                # Signed, server-issued client_id (HMAC) — see Trust & abuse protections
│   │   ├── ratelimit.py           # In-memory rate limit on the Bedrock/Ticketmaster-calling endpoints
│   │   ├── monitor.py             # Trip re-check logic (weather + real date-milestone reminders)
│   │   ├── wishlist_monitor.py    # Wishlist re-check logic — no LLM, reuses tools directly
│   │   ├── local_watch_monitor.py # "Watch a city" re-check logic — no LLM, diffs against already-notified events
│   │   ├── scheduler.py           # APScheduler background sweep — trips, wishlist, local watches, and post-trip feedback requests
│   │   ├── db.py                  # SQLite: trips, wishlist, local watches, shared notification inbox, settings
│   │   ├── notify.py              # Optional Amazon SES email alerts
│   │   └── tools/                 # geocode, weather, routing, flights (+ driving cost), hotels, places, events
│   └── tests/                # pytest — pure logic only, every external call mocked
├── frontend/               # static HTML/CSS/JS + Leaflet map
└── docs/architecture.md    # architecture diagram + data flow
```

## Known limitations / roadmap

- Hotel/driving pricing shown inline is an **estimate range**, not a live booking feed. Flight pricing is a real recently-cached price when a `TRAVELPAYOUTS_API_TOKEN` is configured and Travelpayouts has data for that route, otherwise the same kind of estimate range — see [Why not just call a flight/hotel API?](#why-not-just-call-a-flighthotel-api). Either way, the real, current numbers are always one click away via the Google Flights/Booking.com/driving-directions links.
- No live GPS tracking during the actual trip — intentionally out of scope for this build (see architecture doc); background monitoring covers the pre-departure window instead.
- Single-city, single-leg trips only — no multi-city itineraries yet.
- No sharing/export — a plan lives only in the browser that built it; no link to send a companion, no PDF.
- No user accounts — saved trips, wishlist items, and the notification inbox are scoped by a per-browser anonymous ID (`localStorage`), not a verified identity. The id itself is server-issued and HMAC-signed (not a bare client-generated UUID — see [docs/architecture.md](docs/architecture.md#trust--abuse-protections)), so a request can't just claim to be a different visitor, but there's still no cross-device access and no recovery if you clear browser data.
- The scheduler runs in-process, so it only checks trips while the backend process is running. Deploying via **Amazon Bedrock AgentCore** (or any always-on host) is the natural next step to make that durable in production, and would also strengthen the Technical Implementation story.
- Real event listings in the Day Planner require a (free) `TICKETMASTER_API_KEY`; without one it degrades honestly to a search link rather than showing specific events. The "Add to calendar" `.ics` file uses a 2-hour placeholder duration and floating (non-timezone-aware) start time, since Ticketmaster doesn't reliably return an end time or venue timezone.

## License

MIT — see [LICENSE](LICENSE).
