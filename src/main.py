"""CLI entry point for the Aucto scraper pipeline."""

import argparse
import asyncio
import logging
import signal
import sys

from . import config
from .db import ensure_db
from .scraper_categories import discover_categories
from .scraper_listings import scrape_all_listings
from .scraper_details import scrape_all_details
from .export import export_to_excel


def setup_logging():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(str(config.LOG_PATH), mode="a"),
        ],
    )


def parse_args():
    parser = argparse.ArgumentParser(description="Aucto.com scraper — Buy Now & Auctions")
    parser.add_argument("--all", action="store_true", help="Run full pipeline")
    parser.add_argument("--categories", action="store_true", help="Phase 1: discover categories")
    parser.add_argument("--listings", action="store_true", help="Phase 2: scrape buy-now listings")
    parser.add_argument("--auctions", action="store_true", help="Phase 2b: scrape auction listings")
    parser.add_argument("--details", action="store_true", help="Phase 3: scrape detail pages")
    parser.add_argument("--export", action="store_true", help="Export to Excel")
    parser.add_argument("--headless", action="store_true", default=None, help="Force headless mode")
    parser.add_argument("--no-headless", action="store_true", help="Force visible browser")
    parser.add_argument("--concurrency", type=int, help="Override concurrency level")
    parser.add_argument("--limit", type=int, default=0,
                        help="Stop after N listings (for testing)")
    return parser.parse_args()


async def run_pipeline(args):
    logger = logging.getLogger("main")
    ensure_db()

    if args.headless:
        config.HEADLESS = True
    elif args.no_headless:
        config.HEADLESS = False
    if args.concurrency:
        config.CONCURRENCY = args.concurrency

    run_all = args.all or not any([args.categories, args.listings, args.auctions,
                                   args.details, args.export])

    if run_all or args.categories:
        logger.info("=== Phase 1: Category Discovery ===")
        count = await discover_categories()
        logger.info("Found %d categories", count)

    if run_all or args.listings:
        logger.info("=== Phase 2: Buy-Now Listing Scraping ===")
        count = await scrape_all_listings(sale_format="buy-now", limit=args.limit)
        logger.info("Scraped %d new buy-now listings", count)

    if run_all or args.auctions:
        logger.info("=== Phase 2b: Auction Listing Scraping ===")
        count = await scrape_all_listings(sale_format="auction", limit=args.limit)
        logger.info("Scraped %d new auction listings", count)

    if run_all or args.details:
        logger.info("=== Phase 3: Detail Scraping ===")
        count = await scrape_all_details()
        logger.info("Scraped %d item details", count)

    if run_all or args.export:
        logger.info("=== Exporting to Excel ===")
        path = export_to_excel()
        logger.info("Export saved to %s", path)


def main():
    setup_logging()
    args = parse_args()

    # Graceful shutdown on Ctrl+C
    loop = asyncio.new_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: loop.stop())
        except NotImplementedError:
            pass  # Windows

    try:
        loop.run_until_complete(run_pipeline(args))
    except KeyboardInterrupt:
        logging.getLogger("main").info("Interrupted - shutting down gracefully")
    finally:
        loop.close()


if __name__ == "__main__":
    main()
