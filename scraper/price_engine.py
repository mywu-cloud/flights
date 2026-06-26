"""Price Engine"""
import logging
from scraper.data_store import DataStore
logger = logging.getLogger("price_engine")
THRESHOLD = 0.10

class PriceEngine:
    def __init__(self, store):
        self.store = store

    def should_notify(self, sub_id, price_entry, target_price=None):
        cur = price_entry["price"]
        history = self.store.get_history(sub_id)
        if target_price and cur <= target_price:
            return True, "Target reached! {} <= {} TWD".format(cur, target_price)
        if len(history) >= 2:
            prev_low = min(e["price"] for e in history[:-1])
            if cur < prev_low:
                return True, "New historical low! {} < {} TWD".format(cur, prev_low)
        if len(history) >= 5:
            recent = history[-6:-1]
            if recent:
                avg = sum(e["price"] for e in recent) / len(recent)
                drop = (avg - cur) / avg
                if drop >= THRESHOLD:
                    return True, "Price drop {:.1f}%! {} TWD".format(drop*100, cur)
        return False, "No trigger: {} TWD".format(cur)

    def get_price_summary(self, sub_id, cur):
        history = self.store.get_history(sub_id)
        if not history:
            return {"current": cur, "historical_low": cur, "historical_high": cur, "data_points": 1}
        prices = [e["price"] for e in history]
        return {"current": cur, "historical_low": min(prices), "historical_high": max(prices), "data_points": len(prices)}
