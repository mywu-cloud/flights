"""Price Engine - calendar-aware notification logic"""
import logging
from scraper.data_store import DataStore

logger = logging.getLogger("price_engine")

# Price drop threshold (10%) for "new low" alerts
THRESHOLD = 0.10


class PriceEngine:
    def __init__(self, store: DataStore):
        self.store = store

    # ------------------------------------------------------------------
    # New calendar-based notification check (primary)
    # ------------------------------------------------------------------

    def should_notify_calendar(
        self, sub_id: str, price_calendar: dict, target_price: int | None
    ) -> tuple[bool, str]:
        """
        Check whether any date in price_calendar warrants a notification.

        Rules (checked in order):
        1. ANY date's price <= target_price  → notify (target reached)
        2. Cheapest price is a new historical low → notify
        3. Cheapest price dropped >= THRESHOLD vs recent average → notify

        Returns (should_notify: bool, reason: str)
        """
        if not price_calendar:
            return False, "Empty calendar"

        cheapest_price = min(price_calendar.values())
        cheapest_date = min(price_calendar, key=price_calendar.get)

        # Rule 1: target reached
        if target_price and cheapest_price <= target_price:
            last = self.store.get_last_alert(sub_id)
            if last is not None:
                last_price = last.get("price", 0)
                # Only re-notify if price dropped at least 5% further than last alert
                if cheapest_price >= last_price * 0.95:
                    return False, (
                        f"Target already alerted at {last_price} TWD "
                        f"(current {cheapest_price}, not 5% lower)"
                    )
            return True, (
                f"Target reached! {cheapest_date} @ {cheapest_price} TWD "
                f"<= {target_price} TWD"
            )

        # Rule 2: new historical low
        history = self.store.get_history(sub_id)
        if len(history) >= 2:
            # history entries have 'cheapest_price' (new format) or 'price' (legacy)
            prev_prices = []
            for e in history[:-1]:
                p = e.get("cheapest_price") or e.get("price")
                if p:
                    prev_prices.append(p)
            if prev_prices:
                prev_low = min(prev_prices)
                if cheapest_price < prev_low:
                    return True, (
                        f"New historical low! {cheapest_date} @ {cheapest_price} TWD "
                        f"< prev low {prev_low} TWD"
                    )

        # Rule 3: significant price drop vs recent average
        if len(history) >= 5:
            recent = history[-6:-1]
            recent_prices = []
            for e in recent:
                p = e.get("cheapest_price") or e.get("price")
                if p:
                    recent_prices.append(p)
            if recent_prices:
                avg = sum(recent_prices) / len(recent_prices)
                drop = (avg - cheapest_price) / avg
                if drop >= THRESHOLD:
                    return True, (
                        f"Price drop {drop*100:.1f}%! "
                        f"{cheapest_date} @ {cheapest_price} TWD "
                        f"(avg was {avg:.0f} TWD)"
                    )

        return False, f"No trigger: cheapest {cheapest_date} @ {cheapest_price} TWD"

    # ------------------------------------------------------------------
    # Legacy single-date notification check (backward compat)
    # ------------------------------------------------------------------

    def should_notify(
        self, sub_id: str, price_entry: dict, target_price: int | None = None
    ) -> tuple[bool, str]:
        """Legacy check for a single-date price entry."""
        cur = price_entry["price"]
        history = self.store.get_history(sub_id)

        if target_price and cur <= target_price:
            return True, f"Target reached! {cur} <= {target_price} TWD"

        if len(history) >= 2:
            prev_low = min(
                (e.get("price") or e.get("cheapest_price") or 9999999)
                for e in history[:-1]
            )
            if cur < prev_low:
                return True, f"New historical low! {cur} < {prev_low} TWD"

        if len(history) >= 5:
            recent = history[-6:-1]
            if recent:
                recent_prices = [
                    e.get("price") or e.get("cheapest_price") or 0
                    for e in recent
                ]
                avg = sum(p for p in recent_prices if p) / max(
                    1, sum(1 for p in recent_prices if p)
                )
                drop = (avg - cur) / avg if avg else 0
                if drop >= THRESHOLD:
                    return True, (
                        f"Price drop {drop*100:.1f}%! {cur} TWD"
                    )

        return False, f"No trigger: {cur} TWD"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def get_price_summary(self, sub_id: str, cur: int) -> dict:
        """Return a summary dict for display purposes."""
        history = self.store.get_history(sub_id)
        if not history:
            return {
                "current": cur,
                "historical_low": cur,
                "historical_high": cur,
                "data_points": 1,
            }
        prices = []
        for e in history:
            p = e.get("price") or e.get("cheapest_price")
            if p:
                prices.append(p)
        if not prices:
            return {
                "current": cur,
                "historical_low": cur,
                "historical_high": cur,
                "data_points": len(history),
            }
        return {
            "current": cur,
            "historical_low": min(prices),
            "historical_high": max(prices),
            "data_points": len(prices),
        }
