import urllib.parse

from strands import tool


@tool
def search_hotels(
    destination_city: str,
    check_in: str,
    check_out: str,
    travelers: int,
    accommodation_preference: str = "any",
) -> dict:
    """Estimate nightly hotel cost and get a real live booking link.

    There is no free, self-service real-time hotel pricing API available to
    independent developers with the coverage of Booking.com/Expedia (those
    require an approved partner/affiliate agreement). Instead of inventing a
    fake hotel name and price, this returns a realistic nightly price RANGE
    (for budget planning only) plus a real Google Hotels link pre-filled with
    the destination and dates — that link shows real current hotels, ratings,
    and prices, and the traveler completes the actual booking/payment there.

    Args:
        destination_city: City to search hotels in.
        check_in: Check-in date, format YYYY-MM-DD.
        check_out: Check-out date, format YYYY-MM-DD.
        travelers: Number of travelers (used to note if multiple rooms may be needed).
        accommodation_preference: Free-text preference, e.g. "budget hostel",
            "mid-range hotel", "luxury", "boutique". Defaults to "any".
    """
    pref = accommodation_preference.lower()
    if "budget" in pref or "hostel" in pref:
        price_range = (35, 95)
    elif "luxury" in pref:
        price_range = (280, 650)
    elif "boutique" in pref:
        price_range = (150, 320)
    else:
        price_range = (90, 220)

    query = f"hotels in {destination_city}"
    booking_link = (
        "https://www.google.com/travel/search?q="
        + urllib.parse.quote(query)
        + f"&checkin={check_in}&checkout={check_out}"
    )

    return {
        "status": "success",
        "content": [
            {
                "json": {
                    "estimated_price_low_usd": price_range[0],
                    "estimated_price_high_usd": price_range[1],
                    "booking_link": booking_link,
                    "note": "Nightly estimate based on the requested accommodation tier. "
                    "Open the link for real current hotels, ratings, and prices to actually book.",
                }
            }
        ],
    }
