"""Phase 2: Scrape Buy Now and Auction listings from each leaf category."""

import asyncio
import logging
import re
from urllib.parse import urljoin

from playwright.async_api import Page

from . import config
from .browser import create_browser, new_context, safe_goto, random_delay, scroll_to_bottom
from .db import (ensure_db, get_unscraped_categories, mark_category_scraped,
                 upsert_listings_batch, get_listing_count)

logger = logging.getLogger(__name__)

BID_COUNT_RE = re.compile(r"(\d+)\s*bids?", re.IGNORECASE)
PRICE_RE = re.compile(r"\$[\d,]+(?:\.\d{2})?")
PRICE_CAD_RE = re.compile(r"CAD\s*[\d,]+(?:\.\d{2})?")


async def scrape_all_listings(sale_format: str = "buy-now", limit: int = 0) -> int:
    """Scrape listings from all unscraped leaf categories.

    Args:
        sale_format: 'buy-now' or 'auction'
        limit: stop after this many total listings (0 = no limit, for testing)
    """
    ensure_db()
    categories = get_unscraped_categories(sale_format)
    if not categories:
        logger.info("No unscraped categories found for %s.", sale_format)
        return 0

    logger.info("Scraping %s listings from %d categories (limit=%s)",
                sale_format, len(categories), limit or "none")
    pw, browser = await create_browser()
    total_new = 0

    try:
        semaphore = asyncio.Semaphore(config.CONCURRENCY)

        async def process_category(cat: dict) -> int:
            async with semaphore:
                if limit and total_new >= limit:
                    return 0
                ctx = await new_context(browser, block_resources=True)
                try:
                    page = await ctx.new_page()
                    remaining = max(0, limit - total_new) if limit else 0
                    count = await _scrape_category_listings(page, cat, sale_format, remaining)
                    mark_category_scraped(cat["url"], sale_format)
                    return count
                except Exception as e:
                    logger.error("Error scraping category %s: %s", cat["url"], e)
                    return 0
                finally:
                    await ctx.close()

        tasks = [process_category(cat) for cat in categories]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for r in results:
            if isinstance(r, int):
                total_new += r

        logger.info("Listing scrape complete. %d new %s listings. Total in DB: %d",
                    total_new, sale_format, get_listing_count())
        return total_new

    finally:
        await browser.close()
        await pw.stop()


async def _scrape_category_listings(page: Page, cat: dict,
                                    sale_format: str, limit: int) -> int:
    """Paginate through a category with the given sale-format filter."""
    sale_filter = config.AUCTION_FILTER if sale_format == "auction" else config.BUY_NOW_FILTER
    base_url = urljoin(config.BASE_URL, cat["url"])
    page_num = 1
    total = 0

    while True:
        params = {sale_filter.split("=")[0]: sale_filter.split("=")[1]}
        if page_num > 1:
            params["page"] = str(page_num)
        url = f"{base_url}?{'&'.join(f'{k}={v}' for k, v in params.items())}"

        logger.info("  Scraping [%s]: %s (page %d)", sale_format, cat["name"], page_num)
        await random_delay()

        if not await safe_goto(page, url):
            break

        await scroll_to_bottom(page)

        items = await _extract_listings_from_page(page, cat, sale_format)

        if not items:
            logger.info("  No more listings on page %d for %s", page_num, cat["name"])
            break

        # Respect limit
        if limit:
            items = items[:limit - total]

        upsert_listings_batch(items)
        total += len(items)
        logger.info("  Extracted %d listings from page %d", len(items), page_num)

        if limit and total >= limit:
            break

        has_next = await _has_next_page(page)
        if not has_next:
            break
        page_num += 1

    logger.info("  Category %s: %d total %s listings", cat["name"], total, sale_format)
    return total


async def _extract_listings_from_page(page: Page, cat: dict,
                                      sale_format: str) -> list[dict]:
    """Parse all listing cards on the current page."""
    cards = await page.query_selector_all(config.SEL_LISTING_CARDS)
    items = []
    seen_urls = set()

    for card in cards:
        try:
            href = await card.get_attribute("href")
            if not href or "/marketplace/bid/" not in href:
                continue
            full_url = urljoin(config.BASE_URL, href)
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)

            text = await card.inner_text()
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            card_text_upper = text.upper()

            # Detect listing type from badge in card text
            if "BUY NOW" in card_text_upper:
                listing_type = "buy-now"
            elif "AUCTION" in card_text_upper:
                listing_type = "auction"
            else:
                listing_type = sale_format  # fallback to the filter we used

            title = _extract_title(lines)
            price, currency = _extract_price(lines)
            seller = _extract_seller(lines)
            location = _extract_location(lines)
            bid_count = _extract_bid_count(lines)

            img_el = await card.query_selector("img[src*='cdn.imgeng.in']")
            img_url = await img_el.get_attribute("src") if img_el else None
            image_urls = [img_url] if img_url else []

            # current_bid only meaningful for auctions
            current_bid = price if listing_type == "auction" else None
            # price field: use for buy-now, leave for auctions too (it's the starting/current bid)
            bid_history = f'{{"bid_count": {bid_count}}}' if bid_count is not None else None

            items.append({
                "item_url": full_url,
                "title": title,
                "image_urls": image_urls,
                "price": price,
                "currency": currency,
                "listing_type": listing_type,
                "current_bid": current_bid,
                "bid_history": bid_history,
                "seller_name": seller,
                "location": location,
                "primary_category": cat.get("parent_category", ""),
                "subcategory": cat.get("subcategory", cat.get("name", "")),
                "category_url": cat["url"],
            })
        except Exception as e:
            logger.debug("Error parsing card: %s", e)
            continue

    return items


def _extract_title(lines: list[str]) -> str:
    """Pick the title from parsed card text lines."""
    for line in lines:
        if (len(line) > 10
            and not line.startswith("$")
            and not line.startswith("CAD")
            and not line.startswith("ID #")
            and "BUY NOW" not in line.upper()
            and "AUCTION" not in line.upper()
            and "ENDED" not in line.upper()
            and not re.match(r"^[\d,]+\s*bids?$", line, re.IGNORECASE)
            and not re.match(r"^\d+[DdHhMmSs]", line)):  # skip countdown timers
            return line
    return lines[0] if lines else ""


def _extract_price(lines: list[str]) -> tuple[str, str]:
    """Return (price_string, currency). Handles both USD ($) and CAD formats."""
    for line in lines:
        m = PRICE_RE.search(line)
        if m:
            return m.group(), "USD"
        m = PRICE_CAD_RE.search(line)
        if m:
            return m.group(), "CAD"
    return "", "USD"


def _extract_bid_count(lines: list[str]) -> int | None:
    """Extract bid count from card text e.g. '7 bids' -> 7."""
    for line in lines:
        m = BID_COUNT_RE.search(line)
        if m:
            return int(m.group(1))
    return None


def _extract_seller(lines: list[str]) -> str:
    """Seller name typically appears after the title, before location."""
    for i, line in enumerate(lines):
        if "," in line and any(w in line for w in ["United States", "Canada", "Mexico",
                                                     "Ontario", "California", "Texas"]):
            if i > 0 and not lines[i-1].startswith("$") and not lines[i-1].startswith("ID"):
                return lines[i-1]
    return ""


def _extract_location(lines: list[str]) -> str:
    for line in lines:
        if "," in line and any(w in line for w in ["United States", "Canada", "Mexico",
                                                     "Ontario", "California", "Texas",
                                                     "Georgia", "Michigan", "Missouri"]):
            return line
    return ""


async def _has_next_page(page: Page) -> bool:
    """Check if there is a next page button that is not disabled."""
    try:
        next_btn = await page.query_selector(config.SEL_NEXT_PAGE_BTN)
        if next_btn:
            is_disabled = await next_btn.get_attribute("disabled")
            classes = await next_btn.get_attribute("class") or ""
            return is_disabled is None and "disabled" not in classes
    except Exception:
        pass
    return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(scrape_all_listings())
