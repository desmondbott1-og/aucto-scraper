"""Configuration constants and settings for the Aucto scraper."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "aucto_data.db"
EXPORT_PATH = DATA_DIR / "aucto_export.xlsx"
LOG_PATH = DATA_DIR / "scraper.log"

BASE_URL = "https://www.aucto.com"
MARKETPLACE_URL = f"{BASE_URL}/marketplace/lots"
BUY_NOW_FILTER = "sale-format=buy-now"
AUCTION_FILTER = "sale-format=auction"

HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
VIEWPORT = {"width": 1440, "height": 900}

CONCURRENCY = int(os.getenv("CONCURRENCY", "3"))
MIN_DELAY = float(os.getenv("MIN_DELAY", "1.0"))
MAX_DELAY = float(os.getenv("MAX_DELAY", "3.0"))
PAGE_TIMEOUT = 30_000
SELECTOR_TIMEOUT = 15_000

MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
RETRY_BACKOFF_BASE = 2

# CSS Selectors (centralised so they are easy to update if site changes)
SEL_CATEGORY_LINKS = 'a[href*="/marketplace/lots/"]'
SEL_LISTING_CARDS = 'a[href*="/marketplace/bid/"]'
SEL_NEXT_PAGE_BTN = 'button:has-text("Next"), a:has-text("Next"), [aria-label=\'Next page\']'
SEL_DETAIL_TITLE = "h1"
SEL_DETAIL_IMAGES = 'img[src*="cdn.imgeng.in"], img[src*="s3.us-east-1.amazonaws.com"]'
SEL_CORE_SPECS_HEADING = 'h2:has-text("Core Specifications")'
SEL_BREADCRUMB = "ol li"

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
