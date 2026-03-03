"""Phase 3: Scrape detail pages for core specifications and extra images."""

import asyncio
import logging
from urllib.parse import urljoin

from playwright.async_api import Page

from . import config
from .browser import create_browser, new_context, safe_goto, random_delay
from .db import (ensure_db, get_unscraped_listings, mark_listing_scraped,
                 upsert_item_details)

logger = logging.getLogger(__name__)


async def scrape_all_details() -> int:
    """Scrape detail pages for all listings not yet detailed."""
    ensure_db()
    listings = get_unscraped_listings()
    if not listings:
        logger.info("No unscraped listings. Run --listings first.")
        return 0

    logger.info("Scraping details for %d listings", len(listings))
    pw, browser = await create_browser()
    success = 0

    try:
        semaphore = asyncio.Semaphore(config.CONCURRENCY)

        async def process_listing(listing: dict) -> bool:
            async with semaphore:
                # Don't block images on detail pages - we need image URLs
                ctx = await new_context(browser, block_resources=False)
                try:
                    page = await ctx.new_page()
                    ok = await _scrape_detail_page(page, listing["item_url"])
                    if ok:
                        mark_listing_scraped(listing["item_url"])
                    return ok
                except Exception as e:
                    logger.error("Error on detail %s: %s", listing["item_url"], e)
                    return False
                finally:
                    await ctx.close()

        tasks = [process_listing(lst) for lst in listings]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        success = sum(1 for r in results if r is True)

        logger.info("Detail scrape complete. %d/%d succeeded", success, len(listings))
        return success

    finally:
        await browser.close()
        await pw.stop()


async def _scrape_detail_page(page: Page, url: str) -> bool:
    """Visit a single detail page and extract core specs + images."""
    await random_delay()
    if not await safe_goto(page, url, wait_until="domcontentloaded"):
        return False

    # Wait for core specs section to appear
    try:
        await page.wait_for_selector(config.SEL_CORE_SPECS_HEADING, timeout=config.SELECTOR_TIMEOUT)
    except Exception:
        logger.debug("Core specs heading not found on %s, trying to extract anyway", url)

    # Extract core specifications
    core_specs = await _extract_core_specs(page)

    # Extract all image URLs from detail page
    all_images = await _extract_detail_images(page)

    upsert_item_details(url, core_specs, all_images)
    logger.info("  Scraped detail: %s (%d specs, %d images)", url, len(core_specs), len(all_images))
    return True


async def _extract_core_specs(page: Page) -> dict:
    """Extract key-value pairs from the Core Specifications section."""
    specs = {}
    try:
        specs = await page.evaluate("""() => {
            const result = {};
            // Find the h2 with "Core Specifications"
            let specsH2 = null;
            for (const h of document.querySelectorAll('h2')) {
                if (h.textContent.includes('Core Specifications')) { specsH2 = h; break; }
            }
            if (!specsH2) return result;

            // Specs live inside the next sibling div of the h2
            const specsDiv = specsH2.nextElementSibling;
            if (!specsDiv) return result;

            // Each spec is an h3 with text "Key: Value"
            // Value may spill into one or more following siblings (span, a) until the next h3
            const h3s = specsDiv.querySelectorAll('h3');
            for (const h3 of h3s) {
                const text = h3.textContent.trim();
                const colonIdx = text.indexOf(':');
                if (colonIdx < 0) continue;
                const key = text.substring(0, colonIdx).trim();
                let val = text.substring(colonIdx + 1).trim();

                // Collect ALL following siblings until the next h3
                let sib = h3.nextElementSibling;
                const sibParts = [];
                while (sib && sib.tagName !== 'H3') {
                    const sibText = sib.textContent.trim();
                    // Strip trailing ">" breadcrumb separators
                    const clean = sibText.replace(/\s*>\s*$/, '').trim();
                    if (clean) sibParts.push(clean);
                    sib = sib.nextElementSibling;
                }
                if (sibParts.length > 0) {
                    const joined = sibParts.join(' > ');
                    val = val ? val + ' ' + joined : joined;
                }

                // Skip Category — already stored in listings table from Phase 2
                if (key && key !== 'Category') result[key] = val;
            }
            return result;
        }""")
    except Exception as e:
        logger.debug("Error extracting core specs: %s", e)

    return specs or {}


async def _extract_detail_images(page: Page) -> list[str]:
    """Extract all product image URLs from the detail page."""
    images = set()
    try:
        img_elements = await page.query_selector_all(config.SEL_DETAIL_IMAGES)
        for img in img_elements:
            src = await img.get_attribute("src")
            if not src:
                continue
            # Skip logos and UI chrome
            if "company-logo" in src or "aucto_logo" in src:
                continue
            images.add(src)
    except Exception as e:
        logger.debug("Error extracting images: %s", e)
    return list(images)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(scrape_all_details())
