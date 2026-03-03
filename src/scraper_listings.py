"""Phase 2: Scrape all Buy Now listings from each leaf category."""

import asyncio
import logging
import re
from urllib.parse import urljoin, urlencode, urlparse, parse_qs

from playwright.async_api import Page

from . import config
from .browser import create_browser, new_context, safe_goto, random_delay, scroll_to_bottom
from .db import (ensure_db, get_unscraped_categories, mark_category_scraped,
                 upsert_listings_batch, get_listing_count)

logger = logging.getLogger(__name__)


async def scrape_all_listings() -> int:
    """Scrape Buy Now listings from all unscraped leaf categories."""
    ensure_db()
    categories = get_unscraped_categories()
    if not categories:
        logger.info("No unscraped categories found. Run --categories first.")
        return 0

    logger.info("Scraping listings from %d categories", len(categories))
    pw, browser = await create_browser()
    total_new = 0

    try:
        # Process categories with limited concurrency
        semaphore = asyncio.Semaphore(config.CONCURRENCY)

        async def process_category(cat: dict) -> int:
            async with semaphore:
                ctx = await new_context(browser, block_resources=True)
                try:
                    page = await ctx.new_page()
                    count = await _scrape_category_listings(page, cat)
                    mark_category_scraped(cat["url"])
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

        logger.info("Listing scrape complete. %d new listings. Total in DB: %d",
                     total_new, get_listing_count())
        return total_new

    finally:
        await browser.close()
        await pw.stop()


async def _scrape_category_listings(page: Page, cat: dict) -> int:
    """Paginate through a category with buy-now filter and extract listings."""
    base_url = urljoin(config.BASE_URL, cat["url"])
    page_num = 1
    total = 0

    while True:
        # Build URL with buy-now filter and page number
        params = {config.BUY_NOW_FILTER.split("=")[0]: config.BUY_NOW_FILTER.split("=")[1]}
        if page_num > 1:
            params["page"] = str(page_num)
        url = f"{base_url}?{'&'.join(f'{k}={v}' for k, v in params.items())}"

        logger.info("  Scraping: %s (page %d)", cat["name"], page_num)
        await random_delay()

        if not await safe_goto(page, url):
            break

        await scroll_to_bottom(page)

        # Extract listing cards
        items = await _extract_listings_from_page(page, cat)

        if not items:
            logger.info("  No more listings on page %d for %s", page_num, cat["name"])
            break

        upsert_listings_batch(items)
        total += len(items)
        logger.info("  Extracted %d listings from page %d", len(items), page_num)

        # Check for next page
        has_next = await _has_next_page(page)
        if not has_next:
            break
        page_num += 1

    logger.info("  Category %s: %d total Buy Now listings", cat["name"], total)
    return total


async def _extract_listings_from_page(page: Page, cat: dict) -> list[dict]:
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

            # Extract the item title (usually the longest meaningful line)
            title = _extract_title(lines)

            # Extract price (look for $ pattern)
            price = _extract_price(lines)

            # Extract seller name (line after verified icon text or near it)
            seller = _extract_seller(lines)

            # Extract location (line with state/country pattern)
            location = _extract_location(lines)

            # Extract image URL from inside the card
            img_el = await card.query_selector("img[src*='cdn.imgeng.in']")
            img_url = await img_el.get_attribute("src") if img_el else None
            image_urls = [img_url] if img_url else []

            # Only include Buy Now items
            card_text_upper = text.upper()
            if "BUY NOW" not in card_text_upper:
                continue

            items.append({
                "item_url": full_url,
                "title": title,
                "image_urls": image_urls,
                "price": price,
                "currency": "USD",
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
            and not line.startswith("ID #")
            and "BUY NOW" not in line.upper()
            and "AUCTION" not in line.upper()
            and not re.match(r"^[\d,]+\s*bids?$", line, re.IGNORECASE)):
            return line
    return lines[0] if lines else ""


PRICE_RE = re.compile(r"\$[\d,]+(?:\.\d{2})?")

def _extract_price(lines: list[str]) -> str:
    for line in lines:
        m = PRICE_RE.search(line)
        if m:
            return m.group()
    return ""


def _extract_seller(lines: list[str]) -> str:
    """Seller name typically appears after the title, before location."""
    for i, line in enumerate(lines):
        if "," in line and any(w in line for w in ["United States", "Canada", "Mexico",
                                                     "Ontario", "California", "Texas"]):
            # The line before this is likely the seller
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
