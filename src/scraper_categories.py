"""Phase 1: Discover all category and subcategory URLs from aucto.com."""

import asyncio
import logging
import re
from urllib.parse import urljoin

from playwright.async_api import Page

from . import config
from .browser import create_browser, new_context, safe_goto, random_delay, scroll_to_bottom
from .db import ensure_db, upsert_category, get_all_categories

logger = logging.getLogger(__name__)

# Pattern matching category URLs (exclude /marketplace/lots?... query-only URLs)
CATEGORY_URL_RE = re.compile(r"^/marketplace/lots/[a-z0-9-]+(?:/[a-z0-9-]+)*$", re.IGNORECASE)


async def discover_categories() -> int:
    """Crawl the marketplace to find all categories. Returns count found."""
    ensure_db()
    pw, browser = await create_browser()

    try:
        ctx = await new_context(browser, block_resources=True)
        page = await ctx.new_page()

        # Step 1: Get top-level categories from /marketplace/lots
        logger.info("Fetching top-level categories from %s", config.MARKETPLACE_URL)
        if not await safe_goto(page, config.MARKETPLACE_URL):
            logger.error("Failed to load marketplace page")
            return 0

        await scroll_to_bottom(page)
        top_cats = await _extract_category_links(page)
        logger.info("Found %d top-level category links", len(top_cats))

        for cat_url, cat_name in top_cats:
            upsert_category(cat_url, cat_name, parent_category=cat_name)

        # Step 2: Visit each top-level category to find subcategories
        all_leaf_urls = set()
        for cat_url, cat_name in top_cats:
            full_url = urljoin(config.BASE_URL, cat_url)
            logger.info("Exploring category: %s -> %s", cat_name, full_url)
            await random_delay()

            if not await safe_goto(page, full_url):
                continue

            await scroll_to_bottom(page)
            sub_cats = await _extract_category_links(page)
            sub_cats = [(u, n) for u, n in sub_cats if u != cat_url and u.startswith(cat_url)]

            if sub_cats:
                logger.info("  Found %d subcategories in %s", len(sub_cats), cat_name)
                for sub_url, sub_name in sub_cats:
                    upsert_category(sub_url, sub_name, parent_category=cat_name,
                                    subcategory=sub_name, is_leaf=True)
                    all_leaf_urls.add(sub_url)

                    # Check for deeper subcategories
                    deep_full = urljoin(config.BASE_URL, sub_url)
                    await random_delay()
                    if not await safe_goto(page, deep_full):
                        continue
                    await scroll_to_bottom(page)
                    deep_cats = await _extract_category_links(page)
                    deep_cats = [(u, n) for u, n in deep_cats
                                 if u != sub_url and u.startswith(sub_url)]
                    if deep_cats:
                        # Mark parent as non-leaf, children as leaf
                        upsert_category(sub_url, sub_name, parent_category=cat_name,
                                        subcategory=sub_name, is_leaf=False)
                        for deep_url, deep_name in deep_cats:
                            upsert_category(deep_url, deep_name, parent_category=cat_name,
                                            subcategory=f"{sub_name} > {deep_name}", is_leaf=True)
                            all_leaf_urls.add(deep_url)
            else:
                # No subcategories -> this is a leaf category
                upsert_category(cat_url, cat_name, parent_category=cat_name, is_leaf=True)
                all_leaf_urls.add(cat_url)

        categories = get_all_categories()
        logger.info("Category discovery complete: %d total, %d leaf categories",
                     len(categories), len(all_leaf_urls))
        return len(categories)

    finally:
        await browser.close()
        await pw.stop()


async def _extract_category_links(page: Page) -> list[tuple[str, str]]:
    """Extract (href, text) pairs for category links on the current page."""
    links = await page.query_selector_all(config.SEL_CATEGORY_LINKS)
    results = []
    seen = set()
    for link in links:
        href = await link.get_attribute("href")
        text = (await link.inner_text()).strip()
        if href and CATEGORY_URL_RE.match(href) and href not in seen:
            seen.add(href)
            # Clean up the name
            name = text.split("\n")[0].strip()
            if name:
                results.append((href, name))
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(discover_categories())
