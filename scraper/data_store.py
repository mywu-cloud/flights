"""Data Store"""
import json
import logging
from datetime import datetime
from pathlib import Path
logger = logging.getLogger("data_store")

class DataStore:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._prices = self._load("prices.json", {})
        self._history = self._load("history.json", {})

    def _load(self, filename, default):
        path = self.data_dir / filename
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error("Load error {}: {}".format(filename, e))
        return default

    def add_price(self, entry):
        sid = entry["subscription_id"]
        self._prices[sid] = {
            "subscription_id": sid,
            "origin": entry["origin"],
            "destination": entry["destination"],
            "date": entry["date"],
            "price": entry["price"],
            "currency": entry.get("currency", "TWD"),
            "airline": entry.get("airline", "Unknown"),
            "duration": entry.get("duration", ""),
            "link": entry.get("link", ""),
            "scraped_at": entry["scraped_at"],
        }
        if sid not in self._history:
            self._history[sid] = []
        self._history[sid].append({"price": entry["price"], "airline": entry.get("airline", "Unknown"), "scraped_at": entry["scraped_at"]})
        if len(self._history[sid]) > 360:
            self._history[sid] = self._history[sid][-360:]

    def save(self):
        ts = datetime.utcnow().isoformat() + "Z"
        for fn, data in [("prices.json", {"updated_at": ts, "prices": self._prices}), ("history.json", {"updated_at": ts, "history": self._history})]:
            with open(self.data_dir / fn, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    def get_latest_price(self, sid): return self._prices.get(sid)
    def get_history(self, sid): return self._history.get(sid, [])
    def get_all_latest(self): return self._prices
    def get_historical_low(self, sid):
        h = self.get_history(sid)
        return min(e["price"] for e in h) if h else None
