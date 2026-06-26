"""
Google Flights Scraper
Uses Playwright with stealth mode to extract flight prices.
Implements human-like behavior to avoid bot detection.
"""

import asyncio
import logging
import random
import re
from datetime import datetime
from typing import Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

logger = logging.getLogger("google_flights")

# ── User Agent Pool ────────────────────────────────────────────────────────────
USER_AGENTS = [
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
      "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15",
]

# ── Viewport sizes (common resolutions) ──────────────────────────────────────
VIEWPORTS = [
      {"width": 1920, "height": 1080},
      {"width": 1440, "height": 900},
      {"width": 1366, "height": 768},
      {"width": 1536, "height": 864},
]

# ── Google Flights URL template ───────────────────────────────────────────────
# Format: /travel/flights?hl=zh-TW
GOOGLE_FLIGHTS_BASE = "https://www.google.com/travel/flights?hl=zh-TW&curr=TWD"


class GoogleFlightsScraper:
      """Scrapes Google Flights using Playwright with anti-detection measures."""

    def __init__(self):
              self._playwright = None
              self._browser: Optional[Browser] = None

    async def start(self):
              """Launch browser with stealth configuration."""
              self._playwright = await async_playwright().start()

        # Random user agent and viewport
              ua = random.choice(USER_AGENTS)
              viewport = random.choice(VIEWPORTS)

        self._browser = await self._playwright.chromium.launch(
                      headless=True,
                      args=[
                                        "--no-sandbox",
                                        "--disable-setuid-sandbox",
                                        "--disable-blink-features=AutomationControlled",
                                        "--disable-infobars",
                                        "--disable-dev-shm-usage",
                                        "--no-first-run",
                                        "--no-default-browser-check",
                                        "--disable-extensions",
                                        "--lang=zh-TW",
                      ],
        )
        logger.info(f"Browser launched (UA: {ua[:50]}...)")
        self._ua = ua
        self._viewport = viewport

    async def stop(self):
              """Close browser."""
              if self._browser:
                            await self._browser.close()
                        if self._playwright:
                                      await self._playwright.stop()
                                  logger.info("Browser closed")

    async def _create_stealth_context(self) -> BrowserContext:
              """Create a browser context with stealth settings."""
        context = await self._browser.new_context(
                      user_agent=self._ua,
                      viewport=self._viewport,
                      locale="zh-TW",
                      timezone_id="Asia/Taipei",
                      geolocation={"latitude": 25.0330, "longitude": 121.5654},
                      permissions=["geolocation"],
                      extra_http_headers={
                                        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
                                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                                        "DNT": "1",
                      },
        )

        # Inject stealth scripts to hide automation
        await context.add_init_script("""
                    // Override webdriver property
                                Object.defineProperty(navigator, 'webdriver', {
                                                get: () => undefined,
                                                            });

                                                                        // Override plugins
                                                                                    Object.defineProperty(navigator, 'plugins', {
                                                                                                    get: () => [1, 2, 3, 4, 5],
                                                                                                                });
                                                                                                                
                                                                                                                            // Override languages
                                                                                                                                        Object.defineProperty(navigator, 'languages', {
                                                                                                                                                        get: () => ['zh-TW', 'zh', 'en-US', 'en'],
                                                                                                                                                                    });
                                                                                                                                                                    
                                                                                                                                                                                // Override permissions
                                                                                                                                                                                            const originalQuery = window.navigator.permissions.query;
                                                                                                                                                                                                        window.navigator.permissions.query = (parameters) => (
                                                                                                                                                                                                                        parameters.name === 'notifications' ?
                                                                                                                                                                                                                                            Promise.resolve({ state: Notification.permission }) :
                                                                                                                                                                                                                                                                originalQuery(parameters)
                                                                                                                                                                                                                                                                            );
                                                                                                                                                                                                                                                                            
                                                                                                                                                                                                                                                                                        // Remove automation indicators
                                                                                                                                                                                                                                                                                                    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
                                                                                                                                                                                                                                                                                                                delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
                                                                                                                                                                                                                                                                                                                            delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
                                                                                                                                                                                                                                                                                                                                    """)

        return context

    async def _human_delay(self, min_ms: int = 800, max_ms: int = 2500):
              """Simulate human-like random delay."""
              delay = random.randint(min_ms, max_ms) / 1000
              await asyncio.sleep(delay)

    async def _human_scroll(self, page: Page, times: int = 3):
              """Simulate human-like scrolling."""
              for _ in range(times):
                            scroll_y = random.randint(200, 600)
                            await page.evaluate(f"window.scrollBy(0, {scroll_y})")
                            await self._human_delay(300, 800)

          async def _dismiss_overlays(self, page: Page):
                    """Dismiss cookie banners, popups, etc."""
                    overlay_selectors = [
                        # Google cookie consent
                        'button[aria-label*="Accept"]',
                        'button[aria-label*="接受"]',
                        'button:has-text("Accept all")',
                        'button:has-text("同意")',
                        'button:has-text("I agree")',
                        # Generic dismiss
                        '[data-ved] button:has-text("No thanks")',
                    ]
                    for selector in overlay_selectors:
                                  try:
                                                    btn = page.locator(selector).first
                                                    if await btn.is_visible(timeout=1000):
                                                                          await btn.click()
                                                                          logger.info(f"Dismissed overlay: {selector}")
                                                                          await self._human_delay(500, 1000)
                                                                          break
                                  except Exception:
                                                    pass

                          async def search(
                                    self,
                                    origin: str,
                                    destination: str,
                                    date: str,
                                    trip_type: str = "one_way",
                          ) -> Optional[dict]:
                                    """
                                            Search for flights on Google Flights.

                                                    Args:
                                                                origin: IATA code (e.g., 'TPE')
                                                                            destination: IATA code (e.g., 'NRT')
                                                                                        date: Date string in YYYY-MM-DD format
                                                                                                    trip_type: 'one_way' or 'round_trip'
                                                                                                    
                                                                                                            Returns:
                                                                                                                        dict with price, airline, duration, link or None if failed
                                                                                                                                """
                                    context = await self._create_stealth_context()
                                    page = await context.new_page()

        try:
                      # Build search URL
                      date_formatted = datetime.strptime(date, "%Y-%m-%d").strftime("%Y-%m-%d")
                      url = self._build_search_url(origin, destination, date_formatted, trip_type)

            logger.info(f"Navigating to Google Flights: {origin}->{destination} on {date}")
            logger.debug(f"URL: {url}")

            # Navigate with realistic timeout
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await self._human_delay(2000, 4000)

            # Dismiss any overlays
            await self._dismiss_overlays(page)
            await self._human_delay(1000, 2000)

            # Wait for flight results to load
            result = await self._wait_and_extract(page, origin, destination, date)

            return result

except Exception as e:
            logger.error(f"Search failed for {origin}->{destination}: {e}", exc_info=True)
            # Save screenshot for debugging
            try:
                              await page.screenshot(path=f"logs/error_{origin}_{destination}_{date}.png")
except Exception:
                pass
            return None

finally:
            await context.close()

    def _build_search_url(
              self, origin: str, destination: str, date: str, trip_type: str
    ) -> str:
              """Build Google Flights search URL."""
        # Google Flights URL with parameters
        trip_param = "1" if trip_type == "one_way" else "2"
        return (
                      f"https://www.google.com/travel/flights?"
                      f"hl=zh-TW&curr=TWD"
                      f"&q={origin}+to+{destination}"
                      f"&departure_date={date}"
                      f"&trip_type={trip_param}"
        )

    async def _wait_and_extract(
              self, page: Page, origin: str, destination: str, date: str
    ) -> Optional[dict]:
              """Wait for results and extract the best price."""

        # Simulate human scrolling while waiting
        await self._human_scroll(page, times=2)

        # Wait for price elements with multiple fallback selectors
        price_selectors = [
                      # Google Flights price cards
            '[data-gs*="price"]',
                      '.YMlIz',
                      '.FpEdX',
                      'div[class*="price"]',
                      # Price text patterns
                      'span:has-text("TWD")',
                      'span:has-text("NT$")',
                      'span:has-text("$")',
        ]

        results_loaded = False
        for selector in price_selectors:
                      try:
                                        await page.wait_for_selector(selector, timeout=15000)
                                        results_loaded = True
                                        logger.info(f"Results loaded (selector: {selector})")
                                        break
except Exception:
                continue

        if not results_loaded:
                      logger.warning("Could not confirm results loaded, attempting extraction anyway")

        await self._human_delay(1500, 3000)
        await self._human_scroll(page, times=2)

        # Extract page content
        content = await page.content()

        # Try multiple extraction strategies
        result = (
                      await self._extract_from_dom(page, origin, destination, date)
                      or await self._extract_from_text(page, origin, destination, date)
        )

        return result

    async def _extract_from_dom(
              self, page: Page, origin: str, destination: str, date: str
    ) -> Optional[dict]:
              """Extract price from DOM elements."""
        try:
                      # Try to get flight list items
                      flight_data = await page.evaluate("""
                                      () => {
                                                          const results = [];

                                                                              // Strategy 1: Look for structured flight data
                                                                                                  const priceElements = document.querySelectorAll(
                                                                                                                          '[aria-label*="TWD"], [aria-label*="NT$"]'
                                                                                                                                              );
                                                                                                                                              
                                                                                                                                                                  for (const el of priceElements) {
                                                                                                                                                                                          const text = el.getAttribute('aria-label') || el.textContent;
                                                                                                                                                                                                                  const match = text.match(/([\\d,]+)\\s*(TWD|NT\\$)?/);
                                                                                                                                                                                                                                          if (match) {
                                                                                                                                                                                                                                                                      results.push({
                                                                                                                                                                                                                                                                                                      price_text: match[0],
                                                                                                                                                                                                                                                                                                                                      price_raw: parseInt(match[1].replace(/,/g, '')),
                                                                                                                                                                                                                                                                                                                                                                      element_text: el.textContent.trim().substring(0, 200),
                                                                                                                                                                                                                                                                                                                                                                                                  });
                                                                                                                                                                                                                                                                                                                                                                                                                          }
                                                                                                                                                                                                                                                                                                                                                                                                                                              }
                                                                                                                                                                                                                                                                                                                                                                                                                                              
                                                                                                                                                                                                                                                                                                                                                                                                                                                                  // Strategy 2: Look for price spans
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      if (results.length === 0) {
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              const spans = document.querySelectorAll('span, div');
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      for (const span of spans) {
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  const text = span.textContent.trim();
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              // Match TWD prices like "NT$12,345" or "12,345 TWD"
                                                                                    if (/^(NT\\$|TWD\\s*)?[1-9][\\d,]{3,}(\\s*TWD)?$/.test(text)) {
                                                                                                                    const num = parseInt(text.replace(/[^\\d]/g, ''));
                                                                                                                                                    if (num >= 1000 && num <= 500000) {
                                                                                                                                                                                        results.push({
                                                                                                                                                                                                                                price_text: text,
                                                                                                                                                                                                                                                                        price_raw: num,
                                                                                                                                                                                                                                                                                                                element_text: span.parentElement?.textContent?.trim().substring(0, 200) || text,
                                                                                                                                                                                                                                                                                                                                                    });
                                                                                                                                                                                                                                                                                                                                                                                    }
                                                                                                                                                                                                                                                                                                                                                                                                                }
                                                                                                                                                                                                                                                                                                                                                                                                                                        }
                                                                                                                                                                                                                                                                                                                                                                                                                                                            }
                                                                                                                                                                                                                                                                                                                                                                                                                                                            
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                return results.slice(0, 20);
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                }
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            """)

            if not flight_data:
                              return None

            # Filter and find the lowest valid price
            valid_prices = [
                              f for f in flight_data
                              if f.get("price_raw") and 1000 <= f["price_raw"] <= 500000
            ]

            if not valid_prices:
                              return None

            # Sort by price and take the lowest
            valid_prices.sort(key=lambda x: x["price_raw"])
            best = valid_prices[0]

            logger.info(f"DOM extraction: found {len(valid_prices)} prices, lowest: {best['price_raw']}")

            return {
                              "price": best["price_raw"],
                              "airline": self._extract_airline(best.get("element_text", "")),
                              "duration": "",
                              "link": page.url,
                              "extraction_method": "dom",
            }

except Exception as e:
            logger.error(f"DOM extraction failed: {e}")
            return None

    async def _extract_from_text(
              self, page: Page, origin: str, destination: str, date: str
    ) -> Optional[dict]:
              """Fallback: extract price from page text content."""
        try:
                      text = await page.inner_text("body")

            # Match TWD price patterns
                      patterns = [
                                        r'NT\$\s*([\d,]+)',
                                        r'TWD\s*([\d,]+)',
                                        r'([\d,]+)\s*TWD',
                                        r'\$\s*([\d,]+)',
                      ]

            all_prices = []
            for pattern in patterns:
                              matches = re.findall(pattern, text)
                              for match in matches:
                                                    try:
                                                                              price = int(match.replace(",", ""))
                                                                              if 1000 <= price <= 500000:
                                                                                                            all_prices.append(price)
                                                      except ValueError:
                                                        pass

            if not all_prices:
                              logger.warning("Text extraction: no valid prices found")
                              return None

            all_prices.sort()
            logger.info(f"Text extraction: found {len(all_prices)} prices, lowest: {all_prices[0]}")

            return {
                              "price": all_prices[0],
                              "airline": "Unknown",
                              "duration": "",
                              "link": page.url,
                              "extraction_method": "text",
            }

except Exception as e:
            logger.error(f"Text extraction failed: {e}")
            return None

    @staticmethod
    def _extract_airline(text: str) -> str:
              """Try to extract airline name from surrounding text."""
        airlines = [
                      "China Airlines", "EVA Air", "Japan Airlines", "ANA",
                      "Peach", "Jetstar", "Starlux", "Tiger Air", "Scoot",
                      "中華航空", "長榮航空", "星宇航空", "台灣虎航",
        ]
        for airline in airlines:
                      if airline.lower() in text.lower():
                                        return airline
                                return "Unknown"
