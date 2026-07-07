"""Tigerair Taiwan (台灣虎航) official-site price fetcher.

Tigerair exposes a public, unauthenticated JSON endpoint that returns a
full calendar of daily fares for a given origin/destination pair. This
lets us fetch its real fares directly (no browser automation needed)
and merge them into the Google-Flights-derived calendar, keeping
whichever price is cheaper for each date.
"""
import asyncio
import logging

import requests

logger = logging.getLogger("tigerair")

DAILY_PRICES_URL = "https://api-cms.tigerairtw.com/api/app/book/daily-prices"
AIRLINE_NAME = "台灣虎航"


def fetch_daily_prices(origin: str, destination: str, date_from: str, date_to: str) -> dict:
    """
    Fetch Tigerair's own daily fare calendar for a route/date-range.

    Returns {date_str: price_int} for dates with an actual fare (amount > 0).
    Returns {} on any failure (network error, unsupported route, no service
    on that route, etc.) so callers can safely treat this as "no Tigerair
    data available" and fall back to the existing Google Flights data.
    """
    params = {
        "origin": origin,
        "destination": destination,
        "userCurrency": "TWD",
        "pricingCurrency": "TWD",
        "since": date_from,
        "until": date_to,
    }
    try:
        resp = requests.get(DAILY_PRICES_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json().get("data", [])
    except Exception as e:
        logger.warning(f"Tigerair daily-prices fetch failed for {origin}->{destination}: {e}")
        return {}

    prices = {}
    for item in data:
        date = item.get("date")
        amount = item.get("amount")
        if date and isinstance(amount, (int, float)) and amount > 0:
            prices[date] = int(amount)

    logger.info(f"Tigerair: {len(prices)} priced dates found for {origin}->{destination}")
    return prices


async def merge_into_calendar(
    price_calendar: dict,
    airline_prices: dict,
    cheapest_airline: str,
    origin: str,
    destination: str,
    date_from: str,
    date_to: str,
):
    """
    Fetch Tigerair's official fares and merge them into a price_calendar /
    airline_prices pair that was produced by the Google Flights scraper,
    keeping whichever price is lower for each date.

    Returns (price_calendar, airline_prices, cheapest_airline) - the same
    dicts passed in are mutated in place, and also returned for convenience.
    """
    tiger_prices = await asyncio.to_thread(
        fetch_daily_prices, origin, destination, date_from, date_to
    )
    if not tiger_prices:
        return price_calendar, airline_prices, cheapest_airline

    for date, price in tiger_prices.items():
        entries = airline_prices.setdefault(date, [])
        if not any(e.get("airline") == AIRLINE_NAME for e in entries):
            entries.append({"airline": AIRLINE_NAME, "price": price})
        entries.sort(key=lambda e: e.get("price", float("inf")))

        if date not in price_calendar or price < price_calendar[date]:
            price_calendar[date] = price

    if price_calendar:
        cheapest_date = min(price_calendar, key=price_calendar.get)
        cheapest_price = price_calendar[cheapest_date]
        best_entries = airline_prices.get(cheapest_date, [])
        match = next(
            (e["airline"] for e in best_entries if e.get("price") == cheapest_price),
            None,
        )
        if match:
            cheapest_airline = match

    return price_calendar, airline_prices, cheapest_airline
