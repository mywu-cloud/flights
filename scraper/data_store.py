"""Data Store - supports new price_calendar format"""
import json
import logging
from datetime import datetime
from pathlib import Path
logger = logging.getLogger("data_store")


class DataStore:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._prices = self._load("prices.json", "prices", {})
        self._history = self._load("history.json", "history", {})
        self._period_fares = self._load("period_fares.json", "period_fares", {})

    def _load(self, filename, key, default):
        path = self.data_dir / filename
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    raw = json.load(f)
                # Repair legacy bug: earlier versions stored the whole
                # {"updated_at": ..., "<key>": {...}} wrapper as the in-memory
                # dict directly, causing nested wrappers to pile up on every
                # save. Unwrap until we reach the actual keyed data.
                while isinstance(raw, dict) and key in raw and "updated_at" in raw:
                    raw = raw[key]
                if isinstance(raw, dict):
                    return raw
            except Exception as e:
                logger.error("Load error {}: {}".format(filename, e))
        return default

    # ------------------------------------------------------------------
    # New calendar-based API (primary)
    # ------------------------------------------------------------------

    def update_calendar(self, sub_id: str, origin: str, destination: str,
                        date_from: str, date_to: str,
                        price_calendar: dict, scraped_at: str,
                        cheapest_airline: str = "Unknown",
                        airline_prices: dict = None):
        """
        Store a full price calendar scan result for a subscription.

        price_calendar: {date_str: price_int}  e.g. {"2026-07-15": 8500, ...}
        """
        if not price_calendar:
            logger.warning(f"[{sub_id}] update_calendar called with empty calendar")
            return

        lowest_date = min(price_calendar, key=price_calendar.get)
        lowest_price = price_calendar[lowest_date]

        entry = {
            "subscription_id": sub_id,
            "origin": origin,
            "destination": destination,
            "date_from": date_from,
            "date_to": date_to,
            "price_calendar": price_calendar,
            "cheapest_date": lowest_date,
            "cheapest_price": lowest_price,
            "cheapest_airline": cheapest_airline,
            "airline_prices": airline_prices or {},
            "scraped_at": scraped_at,
            "dates_found": len(price_calendar),
        }
        self._prices[sub_id] = entry
        logger.info(
            f"[{sub_id}] calendar stored: {len(price_calendar)} dates, "
            f"cheapest {lowest_date} @ {lowest_price} TWD"
        )

        # Append to history: track the cheapest price over time
        if sub_id not in self._history:
            self._history[sub_id] = []
        self._history[sub_id].append({
            "cheapest_price": lowest_price,
            "cheapest_date": lowest_date,
            "dates_found": len(price_calendar),
            "scraped_at": scraped_at,
        })
        # Keep last 180 history snapshots
        if len(self._history[sub_id]) > 180:
            self._history[sub_id] = self._history[sub_id][-180:]

        def update_period_fares(self, sub_id, origin, destination, periods):
            """Store per-dekad (旬) top-3 airline fare list for a subscription."""
            self._period_fares[sub_id] = {
                "subscription_id": sub_id,
                "origin": origin,
                "destination": destination,
                "periods": periods,
            }

    # ------------------------------------------------------------------
    # Legacy single-date API (kept for backward compat / fallback)
    # ------------------------------------------------------------------

    def add_price(self, entry):
        """Legacy: store a single-date price entry."""
        sid = entry["subscription_id"]
        # If there is already a calendar entry, merge this single date in
        existing = self._prices.get(sid, {})
        if "price_calendar" in existing:
            date = entry.get("date", "")
            price = entry.get("price")
            if date and price:
                cal = existing["price_calendar"]
                if date not in cal or price < cal[date]:
                    cal[date] = price
                # Recompute cheapest
                cheapest_date = min(cal, key=cal.get)
                existing["cheapest_date"] = cheapest_date
                existing["cheapest_price"] = cal[cheapest_date]
                existing["scraped_at"] = entry["scraped_at"]
        else:
            # Legacy format fallback
            self._prices[sid] = {
                "subscription_id": sid,
                "origin": entry["origin"],
                "destination": entry["destination"],
                "date": entry.get("date", ""),
                "price": entry["price"],
                "currency": entry.get("currency", "TWD"),
                "airline": entry.get("airline", "Unknown"),
                "duration": entry.get("duration", ""),
                "link": entry.get("link", ""),
                "scraped_at": entry["scraped_at"],
            }
            if sid not in self._history:
                self._history[sid] = []
            self._history[sid].append({
                "price": entry["price"],
                "airline": entry.get("airline", "Unknown"),
                "scraped_at": entry["scraped_at"],
            })
            if len(self._history[sid]) > 360:
                self._history[sid] = self._history[sid][-360:]

    # ------------------------------------------------------------------
    # Save & read helpers
    # ------------------------------------------------------------------

    def save(self):
        ts = datetime.utcnow().isoformat() + "Z"
        for fn, data in [
            ("prices.json", {"updated_at": ts, "prices": self._prices}),
            ("history.json", {"updated_at": ts, "history": self._history}),
            ("period_fares.json", {"updated_at": ts, "period_fares": self._period_fares}),
        ]:
            path = self.data_dir / fn
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved {fn}")

    def get_latest_price(self, sid):
        return self._prices.get(sid)

    def get_history(self, sid):
        return self._history.get(sid, [])

    def get_all_latest(self):
        return self._prices

    def get_cheapest_in_calendar(self, sid):
        """Return (cheapest_date, cheapest_price) or (None, None)."""
        entry = self._prices.get(sid, {})
        cal = entry.get("price_calendar", {})
        if not cal:
            return None, None
        d = min(cal, key=cal.get)
        return d, cal[d]

    def get_historical_low(self, sid):
        """Legacy helper: minimum price seen across all history."""
        h = self.get_history(sid)
        if not h:
            return None
        prices = []
        for e in h:
            p = e.get("cheapest_price") or e.get("price")
            if p:
                prices.append(p)
        return min(prices) if prices else None


    def get_last_alert(self, sid: str) -> dict | None:
        """Return the last sent alert record for a subscription, or None."""
        alerts = self._history.get("__alerts__", {})
        return alerts.get(sid)

    def set_last_alert(self, sid: str, price: int, reason: str, ts: str):
        """Persist the most recently sent alert to avoid repeat notifications."""
        if "__alerts__" not in self._history:
            self._history["__alerts__"] = {}
        self._history["__alerts__"][sid] = {
            "price": price,
            "reason": reason,
            "alerted_at": ts,
        }
