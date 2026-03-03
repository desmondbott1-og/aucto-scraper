"""SQLite database layer with schema, CRUD, and checkpoint support."""

import json
import sqlite3
from contextlib import contextmanager
from typing import Any

from . import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    parent_category TEXT,
    subcategory TEXT,
    is_leaf BOOLEAN DEFAULT 0,
    scraped_listings BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_url TEXT UNIQUE NOT NULL,
    title TEXT,
    image_urls TEXT,
    price TEXT,
    currency TEXT DEFAULT 'USD',
    seller_name TEXT,
    location TEXT,
    primary_category TEXT,
    subcategory TEXT,
    category_url TEXT,
    scraped_details BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS item_details (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_url TEXT UNIQUE NOT NULL,
    core_specifications TEXT,
    all_image_urls TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def ensure_db() -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(_SCHEMA)


@contextmanager
def get_conn():
    conn = sqlite3.connect(str(config.DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def upsert_category(url: str, name: str, parent_category: str | None = None,
                    subcategory: str | None = None, is_leaf: bool = False) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO categories (url, name, parent_category, subcategory, is_leaf)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(url) DO UPDATE SET
                 name=excluded.name, parent_category=excluded.parent_category,
                 subcategory=excluded.subcategory, is_leaf=excluded.is_leaf""",
            (url, name, parent_category, subcategory, int(is_leaf)),
        )


def get_unscraped_categories() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM categories WHERE scraped_listings = 0 AND is_leaf = 1"
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_categories() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM categories ORDER BY parent_category, subcategory").fetchall()
    return [dict(r) for r in rows]


def mark_category_scraped(url: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE categories SET scraped_listings = 1 WHERE url = ?", (url,))


def upsert_listing(data: dict[str, Any]) -> None:
    image_urls = data.get("image_urls")
    if isinstance(image_urls, list):
        image_urls = json.dumps(image_urls)
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO listings (item_url, title, image_urls, price, currency,
                                     seller_name, location, primary_category, subcategory, category_url)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(item_url) DO UPDATE SET
                 title=excluded.title, image_urls=excluded.image_urls,
                 price=excluded.price, currency=excluded.currency,
                 seller_name=excluded.seller_name, location=excluded.location,
                 primary_category=excluded.primary_category,
                 subcategory=excluded.subcategory, category_url=excluded.category_url""",
            (data["item_url"], data.get("title"), image_urls,
             data.get("price"), data.get("currency", "USD"),
             data.get("seller_name"), data.get("location"),
             data.get("primary_category"), data.get("subcategory"),
             data.get("category_url")),
        )


def upsert_listings_batch(items: list[dict[str, Any]]) -> None:
    with get_conn() as conn:
        for data in items:
            image_urls = data.get("image_urls")
            if isinstance(image_urls, list):
                image_urls = json.dumps(image_urls)
            conn.execute(
                """INSERT INTO listings (item_url, title, image_urls, price, currency,
                                         seller_name, location, primary_category, subcategory, category_url)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(item_url) DO UPDATE SET
                     title=excluded.title, image_urls=excluded.image_urls,
                     price=excluded.price, currency=excluded.currency,
                     seller_name=excluded.seller_name, location=excluded.location,
                     primary_category=excluded.primary_category,
                     subcategory=excluded.subcategory, category_url=excluded.category_url""",
                (data["item_url"], data.get("title"), image_urls,
                 data.get("price"), data.get("currency", "USD"),
                 data.get("seller_name"), data.get("location"),
                 data.get("primary_category"), data.get("subcategory"),
                 data.get("category_url")),
            )


def get_unscraped_listings() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM listings WHERE scraped_details = 0").fetchall()
    return [dict(r) for r in rows]


def mark_listing_scraped(item_url: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE listings SET scraped_details = 1 WHERE item_url = ?", (item_url,))


def get_listing_count() -> int:
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]


def upsert_item_details(listing_url: str, core_specs: dict, all_image_urls: list[str]) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO item_details (listing_url, core_specifications, all_image_urls)
               VALUES (?, ?, ?)
               ON CONFLICT(listing_url) DO UPDATE SET
                 core_specifications=excluded.core_specifications,
                 all_image_urls=excluded.all_image_urls""",
            (listing_url, json.dumps(core_specs), json.dumps(all_image_urls)),
        )


def get_full_export_data() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT l.title, l.item_url, l.image_urls, l.price, l.currency,
                   l.seller_name, l.location, l.primary_category, l.subcategory,
                   d.core_specifications, d.all_image_urls
            FROM listings l
            LEFT JOIN item_details d ON l.item_url = d.listing_url
            ORDER BY l.primary_category, l.subcategory, l.title
        """).fetchall()
    return [dict(r) for r in rows]
