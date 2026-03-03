# Aucto.com Industrial Equipment Scraper

## Project Overview
A fast, robust Python scraper for **aucto.com** that extracts industrial equipment listings filtered by "Buy Now" sale format. Uses **Playwright** (async) for browser automation since the site is a Next.js SPA requiring JS rendering.

## Architecture

### 3-Phase Scraping Pipeline
1. **Phase 1 – Category Discovery** (`src/scraper_categories.py`): Crawl `/marketplace/lots` to extract all category and subcategory URLs. Run once, save to DB.
2. **Phase 2 – Listing Scraping** (`src/scraper_listings.py`): For each category URL (with `?sale-format=buy-now` filter), paginate through all listings. Extract: title, URL, image URLs, price, currency, seller name, location, category info.
3. **Phase 3 – Detail Scraping** (`src/scraper_details.py`): For each listing URL, visit the detail page and extract "Core Specifications" as `item_details`.

### Data Storage
- **SQLite** database (`aucto_data.db`) for intermediate/persistent storage
- **Excel export** (`src/export.py`) for final output

### Key Technical Details

#### Site Structure (aucto.com)
- **Base URL**: `https://www.aucto.com`
- **Categories page**: `/marketplace/lots` — contains top-level category cards with links like `/marketplace/lots/plant-and-facility-equipment`
- **Subcategory pages**: e.g., `/marketplace/lots/industrial-parts-electrical-components` — contain further subcategory links and listing cards
- **Buy Now filter**: Append `?sale-format=buy-now` to any category URL
- **Pagination**: Pages use `?page=2`, `?page=3` etc. Combined with filter: `?sale-format=buy-now&page=2`
- **Detail pages**: `/marketplace/bid/{slug}/{id}` — contain title, images, price, seller, location, and "Core Specifications" section
- **Breadcrumb** on category pages shows hierarchy: Home > Assets > {Primary Category} > {Subcategory}

#### Listing Card Structure (on category pages)
Each listing card contains:
- **Title**: Item name in the card heading
- **URL**: Link wrapping the card → `/marketplace/bid/{slug}/{id}`
- **Image**: `img` tag with CDN URL (`cls5k0ry.cdn.imgeng.in` or `hpp1qri6.cdn.imgeng.in`)
- **Price**: Dollar amount displayed (e.g., `$3,068`)
- **Currency**: Always USD on this site
- **Seller name**: Text near the verified icon
- **Location**: Text near the location pin icon
- **Sale format badge**: "BUY NOW" / "AUCTION" label

#### Detail Page Structure
- **Core Specifications**: Section with `h2` "Core Specifications" containing key-value pairs (Category, Manufacturer, Model, Year, Condition, etc.)
- **Images**: Multiple images in a gallery/carousel
- **Product Description**: Free text description

#### CSS Selectors (guide, verify with Playwright inspector)
- Category cards on `/marketplace/lots`: `a[href^="/marketplace/lots/"]`
- Listing cards: Cards containing links to `/marketplace/bid/`
- Price element: Look for dollar amounts in card text
- Seller name: Near `.verified-icon` or "Verified" text
- Location: Near location pin icon
- Core Specifications: `h2` containing "Core Specifications", then sibling/child elements for key-value pairs

## File Structure
```
aucto-scraper/
├── CLAUDE.md              # This file — project context for Claude Code
├── requirements.txt       # Python dependencies
├── .env.example           # Environment config template
├── src/
│   ├── __init__.py
│   ├── config.py          # Settings, constants, timeouts
│   ├── db.py              # SQLite schema + CRUD operations
│   ├── browser.py         # Playwright browser setup + helpers
│   ├── scraper_categories.py  # Phase 1: category URL discovery
│   ├── scraper_listings.py    # Phase 2: listing extraction per category
│   ├── scraper_details.py     # Phase 3: detail page scraping
│   ├── export.py          # Export DB → Excel
│   └── main.py            # CLI entry point orchestrating all phases
└── data/                  # Output directory (gitignored)
    ├── aucto_data.db
    └── aucto_export.xlsx
```

## Running the Scraper
```bash
# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Run full pipeline
python -m src.main --all

# Run individual phases
python -m src.main --categories    # Phase 1 only
python -m src.main --listings      # Phase 2 only
python -m src.main --details       # Phase 3 only
python -m src.main --export        # Export to Excel
```

## Performance & Robustness Requirements
- Use **async Playwright** with configurable concurrency (default: 3 browser contexts)
- Implement **retry logic** with exponential backoff (3 retries, 2/4/8s delays)
- Use **request interception** to block images/fonts/CSS for speed (except on detail pages where we need image URLs)
- Handle pagination automatically (detect "no more results" condition)
- Implement **checkpoint/resume**: track which categories and listings have been scraped in DB so interrupted runs can resume
- Use **random delays** between requests (1-3s) to avoid rate limiting
- Set realistic **User-Agent** and viewport
- Log progress with Python `logging` module (INFO level to console, DEBUG to file)
- Graceful shutdown on Ctrl+C — commit any pending data

## Database Schema
```sql
-- Categories discovered in Phase 1
CREATE TABLE categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    parent_category TEXT,          -- e.g., "Industrial Parts"
    subcategory TEXT,              -- e.g., "Electrical Components"
    scraped_listings BOOLEAN DEFAULT 0,  -- checkpoint flag
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Listings discovered in Phase 2
CREATE TABLE listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_url TEXT UNIQUE NOT NULL,
    title TEXT,
    image_urls TEXT,               -- JSON array of image URLs
    price TEXT,
    currency TEXT DEFAULT 'USD',
    seller_name TEXT,
    location TEXT,
    primary_category TEXT,
    subcategory TEXT,
    category_url TEXT,             -- FK reference
    scraped_details BOOLEAN DEFAULT 0,  -- checkpoint flag
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Detail data from Phase 3
CREATE TABLE item_details (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_url TEXT UNIQUE NOT NULL,  -- FK to listings.item_url
    core_specifications TEXT,          -- JSON dict of spec key-value pairs
    all_image_urls TEXT,               -- JSON array (detail page may have more images)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## Coding Conventions
- Python 3.11+, type hints everywhere
- `async`/`await` throughout — no sync Playwright
- Use `dataclasses` or `TypedDict` for structured data
- All selectors in `config.py` so they're easy to update if site changes
- Comprehensive error handling — never let one failed page crash the whole run
- Use context managers for browser/DB connections

## Important Gotchas
- The site is a **Next.js SPA** — must wait for JS rendering, not just page load. Use `wait_for_selector` or `wait_for_load_state("networkidle")`.
- Some pages may have **lazy-loaded content** — scroll down or wait for specific elements.
- The "Buy Now" filter is a **URL parameter**, not a JS toggle, so we can construct filtered URLs directly.
- **Pagination**: Check if a "next page" button exists or if item count drops to 0 to detect last page.
- **Rate limiting**: The site may throttle aggressive scraping. Implement delays and retry on 429 status.
- Category pages show **subcategory cards at the top** and **listing cards below** — need to distinguish between the two when parsing.
- Some categories may have **0 Buy Now listings** — handle gracefully and mark as scraped.
