"""
Flight Price Tracker - Main Orchestrator
Runs scraping for all subscriptions and triggers notifications.
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import pytz

from scraper.google_flights import GoogleFlightsScraper
from scraper.notifier import Notifier
from scraper.price_engine import PriceEngine
from scraper.data_store import DataStore

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

# Constants
SUBSCRIPTIONS_FILE = Path("config/subscriptions.json")
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


async def process_subscription(scraper, store, engine, notifier, sub):
    """Process a single subscription: scrape, store, compare, notify."""
    sub_id = sub["id"]
    origin = sub["origin"]
    destination = sub["destination"]
    date = sub["date"]
    target_price = sub.get("target_price")
    currency = sub.get("currency", "TWD")

    logger.info(f"[{sub_id}] Scraping {origin} -> {destination} on {date}")

    try:
        result = await scraper.search(origin=origin, destination=destination, date=date)
        if result is None:
            logger.warning(f"[{sub_id}] No result returned from scraper")
            return

        now_taipei = datetime.now(TZ_TAIPEI)
        price_entry = {
            "subscription_id": sub_id,
            "origin": origin,
            "destination": destination,
            "date": date,
            "price": result["price"],
            "currency": currency,
            "airline": result.get("airline", "Unknown"),
            "duration": result.get("duration", ""),
            "scraped_at": now_taipei.isoformat(),
            "link": result.get("link", ""),
        }

        store.add_price(price_entry)
        logger.info(f"[{sub_id}] Current price: {result['price']} {currency}")

        should_notify, reason = engine.should_notify(sub_id, price_entry, target_price)
        if should_notify:
            logger.info(f"[{sub_id}] ALERT triggered: {reason}")
            await notifier.send_alert(sub, price_entry, reason)
        else:
            logger.info(f"[{sub_id}] No alert (reason: {reason})")

    except Exception as e:
        logger.error(f"[{sub_id}] Error: {e}", exc_info=True)


async def main():
    """Main entry point."""
    logger.info("=" * 60)
    logger.info("Flight Price Tracker started")
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
    if not subscriptions:
        logger.info("No active subscriptions. Exiting.")
        return

    scraper = GoogleFlightsScraper()
    try:
        await scraper.start()
        for sub in subscriptions:
            await process_subscription(scraper, store, engine, notifier, sub)
            await asyncio.sleep(5)
    finally:
        await scraper.stop()

    store.save()
    logger.info("Data saved successfully")
    logger.info("Flight Price Tracker finished")


if __name__ == "__main__":
    if "--test" in sys.argv:
        logger.info("Running in TEST mode")
    asyncio.run(main())
