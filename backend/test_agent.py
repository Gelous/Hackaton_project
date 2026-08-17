import sys
sys.path.insert(0, "src")
sys.stdout.reconfigure(encoding="utf-8")

from trip_agent.agent import plan_trip

plan = plan_trip(
    {
        "origin_city": "Austin, Texas",
        "destination": "",
        "start_date": "2026-09-10",
        "end_date": "2026-09-13",
        "travelers": 2,
        "budget_usd": 1800,
        "interests": "hiking, local food, live music",
        "transportation": "flight",
        "accommodation": "mid-range hotel",
        "dietary_needs": "vegetarian",
    }
)

print(plan.model_dump_json(indent=2))
