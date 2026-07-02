"""
Google Flights Scraper
Uses Playwright with stealth mode to extract flight prices.
Implements human-like behavior to avoid bot detection.
Supports calendar scan mode: scan a date range and return price_calendar dict.
"""

import asyncio
import logging
import random
import re
from datetime import datetime, timedelta
from typing import Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

logger = logging.getLogger("google_flights")

# User Agent Pool
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15",
]

# Viewport sizes (common resolutions)
VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
]

GOOGLE_FLIGHTS_BASE = "https://www.google.com/travel/flights?hl=zh-TW&curr=TWD"


class GoogleFlightsScraper:
    """Scrapes Google Flights using Playwright with anti-detection measures."""

    def __init__(self):
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._ua = None
        self._viewport = None

    async def start(self):
        """Launch browser with stealth configuration."""
        self._playwright = await async_playwright().start()
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
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['zh-TW', 'zh', 'en-US', 'en'] });
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
            );
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
            'button[aria-label*="Accept"]',
            'button[aria-label*="Accept all"]',
            'button[aria-label*="Reject all"]',
            'button[aria-label*="\u63a5\u53d7"]',
            'button:has-text("Accept all")',
            'button:has-text("Reject all")',
            'button:has-text("\u540c\u610f")',
            'button:has-text("I agree")',
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

    async def search_calendar(
        self,
        origin: str,
        destination: str,
        date_from: str,
        date_to: str,
    ) -> dict:
        """
        Scan Google Flights date grid for an entire date range.
        Returns price_calendar: {date_str: price_int} for all found dates.

        Strategy: open the date-flexible search (price calendar view) then
        read date+price pairs from aria-labels. Falls back to weekly scan
        if the calendar view yields fewer than 5 dates.

        Args:
            origin: IATA code (e.g., 'TPE')
            destination: IATA code (e.g., 'NRT')
            date_from: start date 'YYYY-MM-DD'
            date_to: end date 'YYYY-MM-DD'

        Returns:
            dict  {date_str: lowest_price_int}  -- may be empty on failure
        """
        context = await self._create_stealth_context()
        page = await context.new_page()
        price_calendar = {}
        cheapest_airline = "Unknown"
        try:
            # Use flexible dates URL with view=2 to encourage calendar display
            url = (
                f"https://www.google.com/travel/flights?"
                f"hl=zh-TW&curr=TWD"
                f"&q={origin}+to+{destination}"
                f"&departure_date={date_from}"
                f"&trip_type=1"
            )
            logger.info(
                f"Calendar scan: {origin}->{destination} {date_from} to {date_to}"
            )
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await self._human_delay(2000, 4000)
            await self._dismiss_overlays(page)
            await self._human_delay(1000, 2000)

            # Try calendar grid extraction
            price_calendar = await self._extract_calendar_prices(
                page, origin, destination, date_from, date_to
            )

            # Fallback to weekly scan if insufficient
            if len(price_calendar) < 5:
                logger.info(
                    "Calendar grid extraction insufficient (%d dates), "
                    "falling back to weekly scan", len(price_calendar)
                )
                await context.close()
                context = None
                price_calendar, cheapest_airline = await self._scan_weekly(
                    origin, destination, date_from, date_to
                )

        except Exception as e:
            logger.error(
                f"Calendar search failed for {origin}->{destination}: {e}",
                exc_info=True,
            )
            try:
                await page.screenshot(
                    path=f"logs/error_cal_{origin}_{destination}.png"
                )
            except Exception:
                pass
        finally:
            if context:
                await context.close()

        logger.info(
            f"Calendar result: {len(price_calendar)} dates found for "
            f"{origin}->{destination}"
        )
        return price_calendar, cheapest_airline

    async def _extract_calendar_prices(
        self,
        page: Page,
        origin: str,
        destination: str,
        date_from: str,
        date_to: str,
    ) -> dict:
        """
        Try to read a price-per-date grid from the current Google Flights page.
        Looks for aria-label patterns like '2026\u5e747\u670815\u65e5 NT$8,500'
        and data-date attributes.
        """
        price_calendar = {}
        try:
            await self._human_scroll(page, times=2)
            await self._human_delay(1500, 2500)

            raw = await page.evaluate("""
                () => {
                    const results = [];
                    // Strategy 1: scan aria-labels for date + price patterns
                const seen = {};
                const allEls = document.querySelectorAll('[aria-label]');
                for (const el of allEls) {
                    const lbl = el.getAttribute('aria-label') || '';
                    const dateMatch = lbl.match(/(\d{4})\u5e74(\d{1,2})\u6708(\d{1,2})\u65e5/);
                    const priceMatch = lbl.match(/NT\$\s*([\d,]+)|TWD\s*([\d,]+)|([\d,]+)\s*TWD/);
                    if (dateMatch && priceMatch) {
                        const yr = dateMatch[1];
                        const mo = String(dateMatch[2]).padStart(2, '0');
                        const dy = String(dateMatch[3]).padStart(2, '0');
                        const dateStr = yr + '-' + mo + '-' + dy;
                        const priceRaw = (priceMatch[1] || priceMatch[2] || priceMatch[3] || '').replace(/,/g, '');
                        const price = parseInt(priceRaw, 10);
                        if (price >= 3000 && price <= 200000) {
                            if (!seen[dateStr] || price < seen[dateStr]) {
                                seen[dateStr] = price;
                                results.push({ date: dateStr, price: price });
                            }
                        }
                    }
                }
                // Strategy 2: data-date cells
                const dateCells = document.querySelectorAll('[data-date]');
                for (const cell of dateCells) {
                    const d = cell.getAttribute('data-date');
                    if (!d) continue;
                    const priceEl = cell.querySelector('.YMlIz, .FpEdX, [class*="price"]');
                    const txt = priceEl ? priceEl.textContent : cell.textContent;
                    const pm = txt.match(/NT\$\s*([\d,]+)/);
                    if (pm) {
                        const price = parseInt(pm[1].replace(/,/g, ''), 10);
                        if (price >= 3000 && price <= 200000 && (!seen[d] || price < seen[d])) {
                            seen[d] = price;
                            results.push({ date: d, price: price });
                        }
                    }
                }
                return results;
                }
            """)

            from_dt = datetime.strptime(date_from, "%Y-%m-%d")
            to_dt = datetime.strptime(date_to, "%Y-%m-%d")

            for item in raw:
                d = item.get("date", "")
                p = item.get("price", 0)
                if not d or not p:
                    continue
                try:
                    dt = datetime.strptime(d, "%Y-%m-%d")
                    if from_dt <= dt <= to_dt:
                        if d not in price_calendar or p < price_calendar[d]:
                            price_calendar[d] = p
                except ValueError:
                    pass

        except Exception as e:
            logger.error(f"Calendar grid extraction error: {e}")

        return price_calendar

    async def _scan_weekly(
        self,
        origin: str,
        destination: str,
        date_from: str,
        date_to: str,
    ) -> dict:
        """
        Fallback: iterate dates sampling every 7 days across the range,
        scraping each individual date. Slower but reliable.
        """
        price_calendar = {}
        airline_by_date = {}  # track airline for each date
        from_dt = datetime.strptime(date_from, "%Y-%m-%d")
        to_dt = datetime.strptime(date_to, "%Y-%m-%d")

        current = from_dt
        while current <= to_dt:
            date_str = current.strftime("%Y-%m-%d")
            try:
                result = await asyncio.wait_for(
                    self.search(
                        origin=origin,
                        destination=destination,
                        date=date_str,
                    ),
                    timeout=60,  # 60s per date
                )
            except asyncio.TimeoutError:
                logger.warning(
                    f"Weekly scan [{origin}->{destination}] {date_str}: timeout"
                )
                result = None
            if result and result.get("price"):
                price_calendar[date_str] = result["price"]
                airline_by_date[date_str] = result.get("airline", "Unknown")
                logger.info(
                    f"Weekly scan [{origin}->{destination}] {date_str}: "
                    f"{result['price']} TWD (airline: {result.get('airline', 'Unknown')})"
                )
            else:
                logger.warning(
                    f"Weekly scan [{origin}->{destination}] {date_str}: no price"
                )
            current += timedelta(days=14)
            await self._human_delay(5000, 10000)

        # Find airline for cheapest date
        cheapest_airline = "Unknown"
        if price_calendar:
            cheapest_date = min(price_calendar, key=price_calendar.get)
            cheapest_airline = airline_by_date.get(cheapest_date, "Unknown")
        return price_calendar, cheapest_airline

    async def search(
        self,
        origin: str,
        destination: str,
        date: str,
        trip_type: str = "one_way",
    ) -> Optional[dict]:
        """
        Search for flights on Google Flights for a single specific date.

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
            date_formatted = datetime.strptime(date, "%Y-%m-%d").strftime("%Y-%m-%d")
            url = self._build_search_url(origin, destination, date_formatted, trip_type)
            logger.info(f"Navigating to Google Flights: {origin}->{destination} on {date}")
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await self._human_delay(2000, 4000)
            await self._dismiss_overlays(page)
            await self._human_delay(1000, 2000)
            result = await self._wait_and_extract(page, origin, destination, date)
            return result
        except Exception as e:
            logger.error(f"Search failed for {origin}->{destination}: {e}", exc_info=True)
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
        # Wait for page to settle with known-safe selectors only
        loaded = False
        for selector in ['.YMlIz', '.FpEdX']:
            try:
                await page.wait_for_selector(selector, timeout=8000)
                logger.info(f"Results loaded (selector: {selector})")
                loaded = True
                break
            except Exception:
                continue
        if not loaded:
            # Fallback: just wait a fixed time for page to render
            await asyncio.sleep(5)
            logger.info("Results loaded (fixed wait)")
        await self._human_scroll(page, times=2)
        result = (
            await self._extract_from_dom(page, origin, destination, date)
            or await self._extract_from_text(page, origin, destination, date)
        )
        return result

    async def _extract_from_dom(
        self, page: Page, origin: str, destination: str, date: str
    ) -> Optional[dict]:
        """Extract price from DOM elements using known Google Flights selectors."""
        try:
            flight_data = await page.evaluate("""
                () => {
                    const results = [];
                    const airlineNames = [
                        'China Airlines', 'EVA Air', 'Japan Airlines', 'ANA',
                        'Peach', 'Jetstar', 'Starlux', 'Tiger Air', 'Scoot',
                        'Zipair', 'Air Japan', 'Vanilla Air', 'Spring Airlines',
                        'HK Express', 'Cebu Pacific', 'VietJet', 'AirAsia',
                        '中華航空', '長榮航空',
                        '星宇航空', '台灣虎航',
                        '櫻樂櫻', '全日空',
                        '櫻樂櫻航空', '酒井安航空',
                        '春秋航空', '天馬航空',
                    ];
                    function findAirlineInCard(el) {
                        let card = el;
                        for (let i = 0; i < 10; i++) {
                            if (!card || !card.parentElement) break;
                            card = card.parentElement;
                            if (card.tagName === 'LI' || card.getAttribute('role') === 'listitem' ||
                                card.classList.contains('pIav2d') || card.classList.contains('yR1myc')) break;
                        }
                        const airlineSelectors = ['.Ir0Voe', '.sSHqwe', '.h1fkLb', '.VY3BNb', '[data-iata]'];
                        for (const sel of airlineSelectors) {
                            const airEl = card.querySelector(sel);
                            if (airEl) {
                                const txt = airEl.textContent.trim();
                                if (txt.length > 1 && txt.length < 60) return txt;
                            }
                        }
                        const cardText = card.textContent || '';
                        for (const name of airlineNames) {
                            if (cardText.includes(name)) return name;
                        }
                        return 'Unknown';
                    }
                    const knownEls = document.querySelectorAll('.YMlIz, .FpEdX');
                    for (const el of knownEls) {
                        const text = (el.textContent || '').trim();
                        const match = text.match(/NT\$\s*([\d,]+)|([\d,]+)\s*TWD/);
                        if (match) {
                            const raw = (match[1] || match[2] || '').replace(/,/g, '');
                            const price = parseInt(raw, 10);
                            if (price >= 3000 && price <= 200000) {
                                const airline = findAirlineInCard(el);
                                results.push({ price_raw: price, element_text: text, airline: airline });
                            }
                        }
                    }
                    if (results.length === 0) {
                        const ariaEls = document.querySelectorAll('[aria-label*="NT$"]');
                        for (const el of ariaEls) {
                            const lbl = el.getAttribute('aria-label') || '';
                            const match = lbl.match(/NT\$\s*([\d,]+)/);
                            if (match) {
                                const price = parseInt(match[1].replace(/,/g, ''), 10);
                                if (price >= 3000 && price <= 200000) {
                                    const airline = findAirlineInCard(el);
                                    results.push({ price_raw: price, element_text: lbl.substring(0, 100), airline: airline });
                                }
                            }
                        }
                    }
                    return results.slice(0, 20);
                }
            """)
            logger.info(f"DOM JS returned {len(flight_data) if flight_data else 0} results")
            if flight_data:
                logger.info(f"DOM first result: {flight_data[0]}")
            if not flight_data:
                return None
            valid = [f for f in flight_data if f.get("price_raw") and 3000 <= f["price_raw"] <= 200000]
            if not valid:
                return None
            valid.sort(key=lambda x: x["price_raw"])
            best = valid[0]
            logger.info(f"DOM extraction: found {len(valid)} prices, lowest: {best['price_raw']}")
            return {
                "price": best["price_raw"],
                "airline": best.get("airline", "Unknown"),
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
                        if 3000 <= price <= 200000:
                            all_prices.append(price)
                    except ValueError:
                        pass
            if not all_prices:
                logger.warning("Text extraction: no valid prices found")
                return None
            all_prices.sort()
            logger.info(
                f"Text extraction: found {len(all_prices)} prices, lowest: {all_prices[0]}"
            )
            # Try to find airline from page text
            detected_airline = "Unknown"
            airline_list = [
                "China Airlines", "EVA Air", "Japan Airlines", "ANA",
                "Peach", "Jetstar", "Starlux", "Tiger Air", "Scoot",
                "Zipair", "Air Japan", "Vanilla Air", "Spring Airlines",
                "HK Express", "Cebu Pacific", "VietJet", "AirAsia",
                "中華航空", "長榮航空",
                "星宇航空", "台灣虎航",
                "櫻樂櫻", "全日空", "泰皇航空",
                "丸井空輸", "櫻樂櫻航空",
                "天馬航空", "亞亞航空",
                "酒井安航空", "春秋航空",
            ]
            for name in airline_list:
                if name.lower() in text.lower():
                    detected_airline = name
                    break
            logger.info(f"Text extraction airline detected: {detected_airline}")
            return {
                "price": all_prices[0],
                "airline": detected_airline,
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
            "Zipair", "Air Japan", "Vanilla Air", "Spring Airlines",
            "HK Express", "Cebu Pacific", "VietJet", "AirAsia",
            "中華航空", "長榮航空",
            "星宇航空", "台灣虎航",
            "櫻樂櫻", "全日空", "泰皇航空",
            "丸井空輸", "櫻樂櫻航空",
            "天馬航空", "亞亞航空",
            "酒井安航空", "春秋航空",
        ]
        for airline in airlines:
            if airline.lower() in text.lower():
                return airline
        return "Unknown"
