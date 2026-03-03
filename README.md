# Aucto.com Industrial Equipment Scraper

Scrapes industrial equipment listings from **aucto.com** — both Buy Now and Auction formats. Uses Playwright (async) for browser automation and exports all data to Excel.

---

## Requirements

- Python 3.11+
- Google Chrome / Chromium (installed via Playwright)

---

## Installation

```bash
# Clone the repo
git clone https://github.com/desmondbott1-og/aucto-scraper.git
cd aucto-scraper

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate        # Linux/macOS
# venv\Scripts\activate         # Windows

# Install dependencies
pip install -r requirements.txt

# Install Playwright browser
playwright install chromium
```

---

## Running the Scraper

### Full Pipeline (recommended)

Runs all phases in sequence: categories → buy-now listings → auction listings → details → export.

```bash
python -m src.main --all
```

### Run Individual Phases

```bash
# Phase 1 — Discover all category URLs
python -m src.main --categories

# Phase 2a — Scrape Buy Now listings
python -m src.main --listings

# Phase 2b — Scrape Auction listings
python -m src.main --auctions

# Phase 3 — Scrape detail pages (core specs + images + bid info)
python -m src.main --details

# Export — Write all data to Excel
python -m src.main --export
```

### Options

| Flag | Description |
|------|-------------|
| `--all` | Run full pipeline (phases 1→2a→2b→3→export) |
| `--categories` | Phase 1: discover categories |
| `--listings` | Phase 2a: scrape buy-now listings |
| `--auctions` | Phase 2b: scrape auction listings |
| `--details` | Phase 3: scrape detail pages |
| `--export` | Export to Excel |
| `--limit N` | Stop after N listings per phase (useful for testing) |
| `--concurrency N` | Number of parallel browser contexts (default: 3) |
| `--headless` | Force headless browser mode |
| `--no-headless` | Show browser window (useful for debugging) |

### Examples

```bash
# Test run — scrape only 30 auction listings then export
python -m src.main --auctions --limit 30
python -m src.main --details --limit 30
python -m src.main --export

# Run with more concurrency for faster scraping
python -m src.main --all --concurrency 5

# Debug a specific phase with visible browser
python -m src.main --details --no-headless
```

---

## Output

| File | Description |
|------|-------------|
| `data/aucto_data.db` | SQLite database with all scraped data |
| `data/aucto_export.xlsx` | Final Excel export with all listings |
| `data/category_summary.xlsx` | Item counts per category/subcategory |
| `data/scraper.log` | Full log of all scraping activity |

### Excel Columns

| Column | Description |
|--------|-------------|
| Title | Listing title |
| URL | Direct link to the listing |
| Listing Type | `buy-now` or `auction` |
| Price | Listed price (buy-now) or starting bid (auction) |
| Currency | `USD` or `CAD` |
| Current Bid | Current highest bid (auctions only) |
| Bid History | Bid count or `Ended` status |
| Seller Name | Verified seller name |
| Location | City, State/Province, Country |
| Primary Category | Top-level category (e.g., "Machining Equipment") |
| Subcategory | Sub-level category (e.g., "CNC Lathes") |
| Image URLs | Thumbnail image URLs from listing card |
| Item Details (Core Specs) | Key-value specs from detail page |
| All Detail Images | Full-resolution images from detail page |

---

## Resume / Checkpoint

The scraper tracks progress in the database. If a run is interrupted, simply re-run the same command — it will skip already-scraped categories and listings automatically.

```bash
# Safe to re-run at any time — picks up where it left off
python -m src.main --details
```

---

## Pipeline Architecture

```
Phase 1: Category Discovery
  └─ Crawls /marketplace/lots → saves all category URLs to DB

Phase 2a: Buy-Now Listings
  └─ For each category, fetches ?sale-format=buy-now pages
  └─ Extracts title, price, seller, location, images per listing

Phase 2b: Auction Listings
  └─ Same as 2a but with ?sale-format=auction filter
  └─ Also extracts bid count from listing cards

Phase 3: Detail Pages
  └─ Visits each listing's detail URL
  └─ Extracts Core Specifications, full image gallery
  └─ For auctions: extracts current bid, bid count, ended status

Export
  └─ Joins all tables → writes to aucto_export.xlsx
```
