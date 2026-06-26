"""
Price Engine
Compares scraped prices against user targets and historical lows.
Decides whether to trigger a notification.
"""

import logging
from typing import Optional, Tuple

from scraper.data_store import DataStore

logger = logging.getLogger("price_engine")

# Notify if price drops by this percentage from historical avg
SIGNIFICANT_DROP_THRESHOLD = 0.10  # 10%


class PriceEngine:
      """
          Evaluates whether a new price should trigger a notification.

              Notification is triggered when ANY of these conditions are met:
                  1. Price <= user's target price
                      2. Price is a new historical low
                          3. Price dropped >= 10% compared to the recent average
                              """

    def __init__(self, store: DataStore):
              self.store = store

    def should_notify(
              self,
              sub_id: str,
              price_entry: dict,
              target_price: Optional[int] = None,
    ) -> Tuple[bool, str]:
              """
                      Evaluate whether a notification should be sent.

                              Returns:
                                          (should_notify: bool, reason: str)
                                                  """
              current_price = price_entry["price"]
              history = self.store.get_history(sub_id)

        # ── Rule 1: Target price reached ─────────────────────────────────────
              if target_price and current_price <= target_price:
                            reason = (
                                              f"Target price reached! "
                                              f"{current_price:,} <= target {target_price:,} TWD"
                            )
                            logger.info(f"[{sub_id}] {reason}")
                            return True, reason

              # ── Rule 2: Historical low ────────────────────────────────────────────
              if len(history) >= 2:
                            # Exclude the very last entry (just added) to get previous low
                            previous_entries = history[:-1]
                            previous_low = min(e["price"] for e in previous_entries)

                  if current_price < previous_low:
                                    reason = (
                                                          f"New historical low! "
                                                          f"{current_price:,} < previous low {previous_low:,} TWD"
                                    )
                                    logger.info(f"[{sub_id}] {reason}")
                                    return True, reason

        # ── Rule 3: Significant price drop from recent average ────────────────
        if len(history) >= 5:
                      # Use last 5 data points for recent average (excluding current)
                      recent = history[-6:-1]
                      if recent:
                                        avg_price = sum(e["price"] for e in recent) / len(recent)
                                        drop_ratio = (avg_price - current_price) / avg_price

                          if drop_ratio >= SIGNIFICANT_DROP_THRESHOLD:
                                                reason = (
                                                                          f"Significant price drop! "
                                                                          f"{current_price:,} TWD "
                                                                          f"({drop_ratio * 100:.1f}% below recent avg {avg_price:,.0f} TWD)"
                                                )
                                                logger.info(f"[{sub_id}] {reason}")
                                                return True, reason

        # ── No alert ──────────────────────────────────────────────────────────
        reason = (
                      f"Price {current_price:,} TWD - "
                      f"no trigger conditions met"
        )
        return False, reason

    def get_price_summary(self, sub_id: str, current_price: int) -> dict:
              """Generate a summary dict for notification messages."""
        history = self.store.get_history(sub_id)

        if not history:
                      return {
                          "current": current_price,
                          "historical_low": current_price,
                          "historical_high": current_price,
                          "data_points": 1,
        }

        prices = [e["price"] for e in history]
        return {
                      "current": current_price,
                      "historical_low": min(prices),
                      "historical_high": max(prices),
                      "avg_30d": int(sum(prices[-60:]) / len(prices[-60:])),
                      "data_points": len(prices),
        }
