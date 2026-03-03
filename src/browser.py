"""Playwright browser setup and helper utilities."""

import asyncio
import logging
import random

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from . import config

logger = logging.getLogger(__name__)


async def create_browser():
    """Launch Playwright and return (playwright_instance, browser)."""
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=config.HEADLESS)
    logger.info("Browser launched (headless=%s)", config.HEADLESS)
    return pw, browser


async def new_context(browser: Browser, block_resources: bool = True) -> BrowserContext:
    """Create a browser context with optional resource blocking for speed."""
    ctx = await browser.new_context(
        user_agent=config.USER_AGENT,
        viewport=config.VIEWPORT,
    )
    if block_resources:
        await ctx.route(
            "**/*.{png,jpg,jpeg,gif,svg,webp,woff,woff2,ttf,eot,css}",
            lambda route: route.abort(),
        )
    return ctx


async def safe_goto(page: Page, url: str, wait_until: str = "domcontentloaded") -> bool:
    """Navigate to URL with retry + exponential backoff. Returns True on success."""
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            resp = await page.goto(url, wait_until=wait_until, timeout=config.PAGE_TIMEOUT)
            if resp and resp.status == 429:
                wait = config.RETRY_BACKOFF_BASE ** attempt
                logger.warning("Rate-limited (429) on %s, waiting %ss", url, wait)
                await asyncio.sleep(wait)
                continue
            # Best-effort networkidle wait — Next.js SPAs often never reach true idle
            try:
                await page.wait_for_load_state("networkidle", timeout=8_000)
            except Exception:
                pass  # Page content is available; background XHRs may still run
            return True
        except Exception as e:
            wait = config.RETRY_BACKOFF_BASE ** attempt
            logger.warning("Attempt %d/%d failed for %s: %s (retry in %ss)",
                           attempt, config.MAX_RETRIES, url, e, wait)
            if attempt < config.MAX_RETRIES:
                await asyncio.sleep(wait)
    logger.error("All retries exhausted for %s", url)
    return False


async def random_delay() -> None:
    await asyncio.sleep(random.uniform(config.MIN_DELAY, config.MAX_DELAY))


async def scroll_to_bottom(page: Page, pause: float = 0.5, max_scrolls: int = 20) -> None:
    """Scroll to trigger lazy-loaded content."""
    for _ in range(max_scrolls):
        prev = await page.evaluate("document.body.scrollHeight")
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(pause)
        curr = await page.evaluate("document.body.scrollHeight")
        if curr == prev:
            break
