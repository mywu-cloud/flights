"""
Flight Price Tracker - Main Orchestrator
Scans price calendars for all subscriptions and triggers notifications.
New model: subscriptions have date_from/date_to ranges, not fixed dates.
"""

import asyncio
import json
import logging
import os
import sys
import calendar
from datetime import datetime
from pathlib import Path

import pytz

from scraper.google_flights import GoogleFlightsScraper
from scraper.notifier import Notifier
from scraper.price_engine import PriceEngine
from scraper.data_store import DataStore
from scraper import tigerair

# Logging setup
Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(
            f"logs/scraper_{datetime.now().strftime('%Y%m%d_%H%M')}.log"
        ),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("main")

SUBSCRIPTIONS_FILE = Path("config/subscriptions.json")
PERIOD_SUBS_FILE = Path("config/period_subscriptions.json")
DATA_DIR = Path("data")
TZ_TAIPEI = pytz.timezone("Asia/Taipei")


def load_subscriptions() -> list:
    """Load flight subscriptions from config file."""
    if not SUBSCRIPTIONS_FILE.exists():
        logger.warning(f"Subscriptions file not found: {SUBSCRIPTIONS_FILE}")
        return []
    with open(SUBSCRIPTIONS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    subscriptions = [s for s in data.get("subscriptions", []) if s.get("active", True)]
    logger.info(f"Loaded {len(subscriptions)} active subscription(s)")
    return subscriptions


def load_period_subscriptions() -> list:
    """Load user-defined period comparison entries from config file."""
    if not PERIOD_SUBS_FILE.exists():
        logger.warning(f"Period subscriptions file not found: {PERIOD_SUBS_FILE}")
        return []
    with open(PERIOD_SUBS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    period_subs = [p for p in data.get("period_subscriptions", []) if p.get("active", True)]
    logger.info(f"Loaded {len(period_subs)} active period subscription(s)")
    return period_subs


def cheapest_date_in_dekad(price_calendar, year, month, dekad):
    """Find the cheapest (date, price) within a given year/month/dekad."""
    if dekad == "上旬":
        start_day, end_day = 1, 10
    elif dekad == "中旬":
        start_day, end_day = 11, 20
    else:
        end_day = calendar.monthrange(year, month)[1]
        start_day = 21
    candidates = {}
    for date_str, price in price_calendar.items():
        d = datetime.strptime(date_str, "%Y-%m-%d")
        if d.year == year and d.month == month and start_day <= d.day <= end_day:
            candidates[date_str] = price
    if not candidates:
        return None, None
    best_date = min(candidates, key=candidates.get)
    return best_date, candidates[best_date]


async def process_period_subscriptions(scraper, store, period_subs, calendars_by_route):
    """Fetch top-2 airline choices for each user-defined period comparison entry."""
    for ps in period_subs:
        period_id = ps["id"]
        origin = ps["origin"]
        destination = ps["destination"]
        year = ps["year"]
        month = ps["month"]
        dekad = ps["dekad"]
        label = f"{month}月{dekad}"
        calendar_data = calendars_by_route.get((origin, destination))
        if not calendar_data:
            logger.warning(f"[{period_id}] No calendar data for {origin}->{destination}, skipping")
            continue
        best_date, best_price = cheapest_date_in_dekad(calendar_data, year, month, dekad)
        if not best_date:
            logger.warning(f"[{period_id}] No dates found in {label} for {origin}->{destination}")
            continue
        choices = []
        try:
            detail = await scraper.search(origin=origin, destination=destination, date=best_date)
            if detail:
                choices = detail.get("all_airlines", [])[:2]
        except Exception as e:
            logger.warning(f"[{period_id}] Period detail scan failed: {e}")
        if not choices:
            choices = [{"airline": "Unknown", "price": best_price}]
        store.update_period_fare(
            period_id=period_id,
            origin=origin,
            destination=destination,
            label=label,
            best_date=best_date,
            choices=choices,
        )
        await asyncio.sleep(2)
    logger.info(f"Updated {len(period_subs)} period comparison result(s)")


async def process_subscription(scraper, store, engine, notifier, sub):
    """
    Process a single subscription using the new calendar scan model.
    Reads date_from/date_to from subscription, scans price calendar,
    stores results, and triggers notifications.
    """
    sub_id = sub["id"]
    origin = sub["origin"]
    destination = sub["destination"]
    target_price = sub.get("target_price")
    currency = sub.get("currency", "TWD")

    # Support both new (date_from/date_to) and legacy (date) format
    date_from = sub.get("date_from")
    date_to = sub.get("date_to")
    if not date_from or not date_to:
        # Legacy fallback: use fixed date as a single-day range
        fixed_date = sub.get("date", "")
        if fixed_date:
            date_from = fixed_date
            date_to = fixed_date
            logger.warning(
                f"[{sub_id}] Using legacy fixed date {fixed_date}. "
                f"Please update subscription to use date_from/date_to."
            )
        else:
            logger.error(f"[{sub_id}] No date_from/date_to or date. Skipping.")
            return

    now_taipei = datetime.now(TZ_TAIPEI)
    scraped_at = now_taipei.isoformat()

    logger.info(
        f"[{sub_id}] Calendar scan {origin} -> {destination} "
        f"from {date_from} to {date_to}"
    )

    try:
        price_calendar, cheapest_airline, airline_prices = await scraper.search_calendar(
            origin=origin,
            destination=destination,
            date_from=date_from,
            date_to=date_to,
        )

        # Compare against Tigerair Taiwan's own official fares (if any) and
        # keep whichever price is cheaper for each date.
        price_calendar, airline_prices, cheapest_airline = await tigerair.merge_into_calendar(
            price_calendar=price_calendar,
            airline_prices=airline_prices,
            cheapest_airline=cheapest_airline,
            origin=origin,
            destination=destination,
            date_from=date_from,
            date_to=date_to,
        )

        if not price_calendar:
            logger.warning(f"[{sub_id}] No prices found in calendar scan")
            return

        # Store the calendar result
        store.update_calendar(
            sub_id=sub_id,
            origin=origin,
            destination=destination,
            date_from=date_from,
            date_to=date_to,
            price_calendar=price_calendar,
            scraped_at=scraped_at,
            cheapest_airline=cheapest_airline,
            airline_prices=airline_prices,
        )

        cheapest_date, cheapest_price = store.get_cheapest_in_calendar(sub_id)
        logger.info(
            f"[{sub_id}] Cheapest: {cheapest_date} @ {cheapest_price} {currency} "
            f"(target: {target_price})"
        )

        # Check notification triggers
        should_notify, reason = engine.should_notify_calendar(
            sub_id=sub_id,
            price_calendar=price_calendar,
            target_price=target_price,
        )
        if should_notify:
            logger.info(f"[{sub_id}] ALERT triggered: {reason}")
            # Build a simplified price_entry for notifier compatibility
            price_entry = {
                "subscription_id": sub_id,
                "origin": origin,
                "destination": destination,
                "date": cheapest_date,
                "price": cheapest_price,
                "currency": currency,
                "airline": "See link",
                "scraped_at": scraped_at,
                "link": (
                    f"https://www.google.com/travel/flights?"
                    f"hl=zh-TW&curr=TWD"
                    f"&q={origin}+to+{destination}"
                    f"&departure_date={cheapest_date}"
                    f"&trip_type=1"
                ),
            }
            await notifier.send_alert(sub, price_entry, reason)
            # Record this alert so we don't spam the same price repeatedly
            store.set_last_alert(
                sid=sub_id,
                price=cheapest_price,
                reason=reason,
                ts=scraped_at,
            )
        else:
            logger.info(f"[{sub_id}] No alert (reason: {reason})")
        return price_calendar

    except Exception as e:
        logger.error(f"[{sub_id}] Error: {e}", exc_info=True)
        return None


async def main():
    """Main entry point."""
    logger.info("=" * 60)
    logger.info("Flight Price Tracker started (calendar scan mode)")
    logger.info(f"Time (Taipei): {datetime.now(TZ_TAIPEI).strftime('%Y-%m-%d %H:%M:%S %Z')}")
    logger.info("=" * 60)

    DATA_DIR.mkdir(exist_ok=True)

    store = DataStore(data_dir=DATA_DIR)
    engine = PriceEngine(store=store)
    notifier = Notifier(
        telegram_token=os.getenv("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID"),
        email_sender=os.getenv("EMAIL_SENDER"),
        email_password=os.getenv("EMAIL_PASSWORD"),
        email_receiver=os.getenv("EMAIL_RECEIVER"),
    )

    subscriptions = load_subscriptions()
    period_subs = load_period_subscriptions()
    if not subscriptions:
        logger.info("No active subscriptions. Exiting.")
        return

        calendars_by_route = {}
        scraper = GoogleFlightsScraper()
    try:
        await scraper.start()
        for sub in subscriptions:
            price_calendar = await process_subscription(scraper, store, engine, notifier, sub)
            if price_calendar:
                calendars_by_route[(sub["origin"], sub["destination"])] = price_calendar
            # Save after each subscription so data is persisted even if later ones fail
            store.save()
            # Polite delay between subscriptions
            await asyncio.sleep(3)
        if period_subs:
            try:
                await process_period_subscriptions(scraper, store, period_subs, calendars_by_route)
            except Exception as e:
                logger.error(f"Period subscriptions processing error: {e}", exc_info=True)
    finally:
        await scraper.stop()

    store.save()
    logger.info("Data saved successfully")
    logger.info("Flight Price Tracker finished")


if __name__ == "__main__":
    if "--test" in sys.argv:
        logger.info("Running in TEST mode")
    asyncio.run(main())
