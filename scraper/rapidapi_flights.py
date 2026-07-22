"""RapidAPI flight price fallback fetcher.

Used as a last-resort fallback when both the Google Flights scraper and
the Tigerair official-fare fetcher fail to produce any price data for a
route. Calls a RapidAPI-hosted flight-search endpoint and normalizes the
response into the same {date: price} price_calendar shape used elsewhere
in this project.

Configuration (set as GitHub Actions secrets / environment variables):
    RAPIDAPI_KEY   - your RapidAPI application key (required)
    RAPIDAPI_HOST  - the x-rapidapi-host value of the flight-search API
                     you subscribed to on RapidAPI, e.g.
                     "sky-scanner3.p.rapidapi.com" (required)
    RAPIDAPI_URL   - full endpoint URL for the calendar/price-search call
                     (required; differs per RapidAPI product)

NOTE: RapidAPI's marketplace hosts many different flight-search products,
each with its own request parameters and JSON response shape. This module
implements a best-effort generic response parser that looks for common
field name patterns (date/day + price/fare/amount). If the specific API
you subscribe to uses a different structure, adjust _parse_response()
below to match it.
"""

import asyncio
import logging
import os
from datetime import datetime

import requests

logger = logging.getLogger("rapidapi_flights")

RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
RAPIDAPI_HOST = os.getenv("RAPIDAPI_HOST")
RAPIDAPI_URL = os.getenv("RAPIDAPI_URL")

AIRLINE_NAME = "RapidAPI"


def _looks_like_date(s) -> bool:
    if not isinstance(s, str):
        return False
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _normalize_date(value) -> str:
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y"):
            try:
                return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        if len(value) >= 10 and _looks_like_date(value[:10]):
            return value[:10]
    return ""


def _extract_price(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if value > 0 else None
    if isinstance(value, dict):
        for key in ("amount", "price", "total", "value"):
            if key in value:
                extracted = _extract_price(value[key])
                if extracted:
                    return extracted
    return None


def _parse_response(payload) -> dict:
    """Best-effort extraction of {date_str: price_int} from a RapidAPI
    flight-search JSON payload. Handles a few common response shapes,
    e.g. {"data": [{"date": "...", "price": ...}, ...]} or
    {"data": {"YYYY-MM-DD": price, ...}}.
    """
    price_calendar = {}

    def _walk(node):
        if isinstance(node, dict):
            date_like_keys = [k for k in node.keys() if _looks_like_date(k)]
            if date_like_keys:
                for k in date_like_keys:
                    price = _extract_price(node[k])
                    if price:
                        price_calendar[k] = price
                return
            for key in ("data", "prices", "results", "calendar", "dates", "days"):
                if key in node:
                    _walk(node[key])
            date_val = node.get("date") or node.get("day")
            price_val = (
                node.get("price")
                if "price" in node
                else node.get("fare")
                if "fare" in node
                else node.get("amount")
                if "amount" in node
                else node.get("total")
            )
            if date_val and price_val is not None:
                price = _extract_price(price_val)
                d = _normalize_date(date_val)
                if price and d:
                    if d not in price_calendar or price < price_calendar[d]:
                        price_calendar[d] = price
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(payload)
    return price_calendar


def fetch_calendar(origin: str, destination: str, date_from: str, date_to: str) -> dict:
    """
    Fetch a fallback price calendar from RapidAPI for a route/date-range.

    Returns {date_str: price_int} for dates with a price found. Returns {}
    on any failure (missing config, network error, unsupported route,
    unparseable response) so callers can safely skip this fallback and
    keep whatever data (if any) they already have.
    """
    if not (RAPIDAPI_KEY and RAPIDAPI_HOST and RAPIDAPI_URL):
        logger.info("RapidAPI fallback skipped: RAPIDAPI_KEY/HOST/URL not configured")
        return {}

    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": RAPIDAPI_HOST,
    }
    params = {
        "origin": origin,
        "destination": destination,
        "departureDate": date_from,
        "returnDate": date_to,
        "dateFrom": date_from,
        "dateTo": date_to,
        "currency": "TWD",
    }
    try:
        resp = requests.get(RAPIDAPI_URL, headers=headers, params=params, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        logger.warning(f"RapidAPI fetch failed for {origin}->{destination}: {e}")
        return {}

    price_calendar = _parse_response(payload)

    if price_calendar:
        try:
            from_dt = datetime.strptime(date_from, "%Y-%m-%d")
            to_dt = datetime.strptime(date_to, "%Y-%m-%d")
            price_calendar = {
                d: p
                for d, p in price_calendar.items()
                if from_dt <= datetime.strptime(d, "%Y-%m-%d") <= to_dt
            }
        except ValueError:
            pass

    logger.info(
        f"RapidAPI fallback: {len(price_calendar)} priced dates found for "
        f"{origin}->{destination}"
    )
    return price_calendar


async def get_calendar_fallback(origin: str, destination: str, date_from: str, date_to: str):
    """
    Async wrapper around fetch_calendar() for use inside asyncio-based
    orchestration code (main.py). Returns (price_calendar, cheapest_airline,
    airline_prices) matching the tuple shape returned by
    GoogleFlightsScraper.search_calendar(), so it can be used as a
    drop-in fallback when the scraper (and Tigerair) find nothing.
    """
    price_calendar = await asyncio.to_thread(
        fetch_calendar, origin, destination, date_from, date_to
    )
    airline_prices = {}
    cheapest_airline = "Unknown"
    if price_calendar:
        for date, price in price_calendar.items():
            airline_prices[date] = [{"airline": AIRLINE_NAME, "price": price}]
        cheapest_airline = AIRLINE_NAME
    return price_calendar, cheapest_airline, airline_prices
