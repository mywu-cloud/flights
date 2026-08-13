"""
scraper/news_scraper.py

Scans Taiwanese airlines' official news / press-release pages for new-route
announcements (開航 / 直飛 / 首航 / 新航線 ...) and writes the
results to an announcements.json file, following the same general shape as
prices.json / history.json described in the project README.

IMPORTANT: this script was written by inspecting each airline site's HTML
structure manually on 2026-08-11 via a browser. It has NOT been executed in
a real Python environment as part of this change (it was added through the
GitHub web editor only). Please run it locally / in CI before relying on it,
and expect to tweak selectors if a site's markup changes.

Usage:
    python -m scraper.news_scraper --output data/announcements.json
"""

import argparse
import hashlib
import json
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "news_sources.json"

# Where the currently-published announcements.json lives, so we can diff
# against it and flag brand-new items. Mirrors the gh-pages data path used
# for prices.json / history.json (see README "資料存放").
EXISTING_ANNOUNCEMENTS_URL = "https://mywu-cloud.github.io/flights/data/announcements.json"


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_existing_announcements():
    """Best-effort fetch of the currently-published announcements.json."""
    try:
        with urllib.request.urlopen(EXISTING_ANNOUNCEMENTS_URL, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {item["id"]: item for item in data.get("announcements", [])}
    except Exception:
        return {}


def make_id(code, url, title):
    h = hashlib.sha1(f"{code}|{url}|{title}".encode("utf-8")).hexdigest()[:10]
    return f"{code.lower()}-{h}"


def parse_date(raw, date_format):
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        if date_format:
            return datetime.strptime(raw, date_format).date().isoformat()
        # Fallback for e.g. "2026-08-05T12:00:00" (China Airlines datefilter attr)
        return raw[:10]
    except ValueError:
        nums = re.findall(r"\d+", raw)
        if len(nums) >= 3:
            y, m, d = nums[0], nums[1], nums[2]
            try:
                return datetime(int(y), int(m), int(d)).date().isoformat()
            except ValueError:
                return None
        return None


def matches_keywords(title, keywords, exclude_keywords=None):
    if exclude_keywords and any(kw in title for kw in exclude_keywords):
        return False
    return any(kw in title for kw in keywords)


def scrape_source(page, source, keywords, exclude_keywords=None):
    results = []
    page.goto(source["page_url"], wait_until="domcontentloaded", timeout=30000)

    if source.get("click_tab_text"):
        try:
            page.get_by_text(source["click_tab_text"], exact=True).first.click(timeout=15000)
            page.wait_for_timeout(2500)
        except Exception as e:
            print(f"  [warn] could not click tab '{source['click_tab_text']}': {e}")

    try:
        page.wait_for_selector(source["item_selector"], timeout=20000)
    except Exception as e:
        print(f"  [warn] no items found for {source['airline']}: {e}")
        return results

    items = page.query_selector_all(source["item_selector"])
    for item in items:
        try:
            title_el = item.query_selector(source["title_selector"]) if source.get("title_selector") else None
            title = (title_el.inner_text() if title_el else item.inner_text()).strip()
            if not title or not matches_keywords(title, keywords, exclude_keywords):
                continue

            href = item.get_attribute("href")
            if not href:
                a = item.query_selector("a")
                href = a.get_attribute("href") if a else None
            if href and href.startswith("http"):
                url = href
            elif href:
                url = source["base_url"].rstrip("/") + "/" + href.lstrip("/")
            else:
                url = source["page_url"]

            if source.get("date_attr"):
                raw_date = item.get_attribute(source["date_attr"])
            elif source.get("date_selector"):
                date_el = item.query_selector(source["date_selector"])
                raw_date = date_el.inner_text() if date_el else None
            else:
                raw_date = None

            date_iso = parse_date(raw_date, source.get("date_format"))

            results.append(
                {
                    "id": make_id(source["code"], url, title),
                    "airline": source["airline"],
                    "airline_code": source["code"],
                    "title": title,
                    "url": url,
                    "date": date_iso,
                    "scraped_at": datetime.utcnow().isoformat() + "Z",
                }
            )
        except Exception as e:
            print(f"  [warn] failed to parse an item for {source['airline']}: {e}")
            continue

    return results


def run(output_path):
    config = load_config()
    keywords = config.get("keywords", [])
    exclude_keywords = config.get("exclude_keywords", [])
    existing = load_existing_announcements()

    all_results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="zh-TW")
        for source in config.get("sources", []):
            print(f"Scanning {source['airline']} ...")
            try:
                found = scrape_source(page, source, keywords, exclude_keywords)
                print(f"  -> {len(found)} matching announcement(s)")
                all_results.extend(found)
            except Exception as e:
                print(f"  [error] {source['airline']} failed: {e}")
        browser.close()

    # Drop previously-stored items that no longer pass the keyword filter
    # (e.g. exclude_keywords added later), so stale unrelated news doesn't
    # linger forever.
    existing = {
        item_id: item
        for item_id, item in existing.items()
        if matches_keywords(item.get("title", ""), keywords, exclude_keywords)
    }

    # Merge with existing data, keep the latest version of each id, and flag
    # ids that were not present before as "is_new" for the frontend to badge.
    merged = dict(existing)
    new_ids = []
    for item in all_results:
        if item["id"] not in existing:
            new_ids.append(item["id"])
        merged[item["id"]] = item

    for item in merged.values():
        item["is_new"] = item["id"] in new_ids

    announcements = sorted(merged.values(), key=lambda x: x.get("date") or "", reverse=True)

    output = {
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "announcements": announcements,
    }

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"Wrote {len(announcements)} announcements ({len(new_ids)} new) -> {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="data/announcements.json",
        help="Path to write the announcements JSON file",
    )
    args = parser.parse_args()
    try:
        run(args.output)
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        sys.exit(1)
