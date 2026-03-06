#!/usr/bin/env python3
"""MiningCave inventory scraper.

Scrapes product cards from https://miningcave.com/shop-page/, iterates paginated
shop pages, and stores:
1) latest snapshot CSV (overwritten each run)
2) append-only history CSV (timestamped rows)
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from persistence import save_inventory_records

BASE_URL = "https://miningcave.com"
SHOP_URL = "https://miningcave.com/shop-page/"
DEFAULT_TIMEOUT = 30
DEFAULT_DELAY_SECONDS = 0.3


@dataclass
class ProductRecord:
    scraped_at_utc: str
    page_number: int
    product_url: str
    product_name: str
    image_url: str
    shipping_text: str
    description: str
    stock_text: str
    in_stock: int
    price_text: str
    price_value: Optional[float]
    currency: str
    gtm_product_id: str


def clean_text(value: str) -> str:
    return " ".join(value.split()).strip()


def parse_price(value: str) -> tuple[Optional[float], str]:
    cleaned = clean_text(value)
    if not cleaned:
        return None, ""

    currency = ""
    if "$" in cleaned:
        currency = "USD"
    elif "€" in cleaned:
        currency = "EUR"
    elif "£" in cleaned:
        currency = "GBP"

    match = re.search(r"([0-9][0-9,]*(?:\.[0-9]+)?)", cleaned)
    if not match:
        return None, currency

    number = match.group(1).replace(",", "")
    try:
        return float(number), currency
    except ValueError:
        return None, currency


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            )
        }
    )
    return session


def fetch_soup(session: requests.Session, url: str, timeout: int = DEFAULT_TIMEOUT) -> BeautifulSoup:
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def get_max_page(first_page_soup: BeautifulSoup) -> int:
    max_page = 1
    nav = first_page_soup.select_one("nav.woocommerce-pagination")
    if not nav:
        return max_page

    for node in nav.select(".page-numbers"):
        label = clean_text(node.get_text())
        if label.isdigit():
            max_page = max(max_page, int(label))
            continue
        aria_label = clean_text(node.get("aria-label", ""))
        match = re.search(r"Page\s+(\d+)", aria_label, flags=re.IGNORECASE)
        if match:
            max_page = max(max_page, int(match.group(1)))
    return max_page


def build_page_url(start_url: str, page_number: int) -> str:
    if page_number <= 1:
        return start_url
    parsed = urlparse(start_url)
    path = parsed.path.rstrip("/")
    new_path = f"{path}/page/{page_number}/"
    return parsed._replace(path=new_path, params="", query="", fragment="").geturl()


def _extract_quantity_from_text(text: str) -> Optional[int]:
    match = re.search(r"\b(\d{1,5})\b", text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def extract_stock_info(product_card: BeautifulSoup) -> tuple[str, int]:
    parent_li = product_card.find_parent("li")
    roots = [product_card]
    if parent_li:
        roots.append(parent_li)

    for root in roots:
        outstock = root.select_one("a.outstock_button")
        if outstock:
            text = clean_text(outstock.get_text()) or "Out of Stock"
            return text, 0

    for root in roots:
        action_links = root.select(".product-item-actions a")
        for link in action_links:
            classes = " ".join(link.get("class", []))
            if "outstock" in classes.lower():
                return "Out of Stock", 0
            if "instock" in classes.lower():
                text = clean_text(link.get_text()) or "In Stock"
                qty = _extract_quantity_from_text(text)
                qty = qty if qty is not None else 1
                return f"In Stock ({qty})", qty
            text = clean_text(link.get_text())
            if not text:
                continue
            lower = text.lower()
            if "out of stock" in lower:
                return text, 0
            if "add to cart" in lower or "in stock" in lower:
                qty = _extract_quantity_from_text(text)
                qty = qty if qty is not None else 1
                return f"In Stock ({qty})", qty

    # On this theme, many in-stock items have an empty actions container and no
    # explicit in-stock label; absence of out-of-stock signals implies available.
    return "In Stock (1)", 1


def extract_product_records(soup: BeautifulSoup, page_number: int, scraped_at_utc: str) -> list[ProductRecord]:
    records: list[ProductRecord] = []
    for product_card in soup.select("div.product-item-info"):
        name = clean_text(
            (
                product_card.select_one("h2.woocommerce-loop-product__title")
                or product_card.select_one(".product-item-name")
            ).get_text()
            if (product_card.select_one("h2.woocommerce-loop-product__title") or product_card.select_one(".product-item-name"))
            else ""
        )
        product_link = (
            product_card.select_one("a.woocommerce-LoopProduct-link")
            or product_card.select_one('a[href*="/product/"]')
            or product_card.select_one("a[href]")
        )
        if not product_link:
            parent_li = product_card.find_parent("li")
            if parent_li:
                product_link = parent_li.select_one("a.woocommerce-LoopProduct-link")
        product_url = product_link.get("href", "").strip() if product_link else ""
        if product_url:
            product_url = urljoin(BASE_URL, product_url)

        image = product_card.select_one(".product-item-photo img")
        image_url = image.get("src", "").strip() if image else ""
        if image_url:
            image_url = urljoin(BASE_URL, image_url)

        shipping = clean_text(
            product_card.select_one(".estimated-shipping-dates").get_text()
            if product_card.select_one(".estimated-shipping-dates")
            else ""
        )
        description = clean_text(
            product_card.select_one(".despr").get_text() if product_card.select_one(".despr") else ""
        )

        price_text = clean_text(product_card.select_one(".price").get_text() if product_card.select_one(".price") else "")
        price_value, currency = parse_price(price_text)

        stock_text, in_stock = extract_stock_info(product_card)

        gtm_span = product_card.select_one(".gtm4wp_productdata")
        if not gtm_span:
            parent_li = product_card.find_parent("li")
            if parent_li:
                gtm_span = parent_li.select_one(".gtm4wp_productdata")
        gtm_product_id = clean_text(gtm_span.get("data-gtm4wp_product_id", "")) if gtm_span else ""

        if not name and not product_url:
            continue

        records.append(
            ProductRecord(
                scraped_at_utc=scraped_at_utc,
                page_number=page_number,
                product_url=product_url,
                product_name=name,
                image_url=image_url,
                shipping_text=shipping,
                description=description,
                stock_text=stock_text,
                in_stock=in_stock,
                price_text=price_text,
                price_value=price_value,
                currency=currency,
                gtm_product_id=gtm_product_id,
            )
        )
    return records


def write_csv(path: Path, rows: Iterable[ProductRecord], append: bool) -> None:
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = list(ProductRecord.__dataclass_fields__.keys())
    write_header = not path.exists() or not append
    mode = "a" if append else "w"

    with path.open(mode, newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=headers)
        if write_header:
            writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def scrape_inventory(start_url: str, delay_seconds: float = DEFAULT_DELAY_SECONDS) -> list[ProductRecord]:
    session = build_session()
    scraped_at_utc = datetime.now(timezone.utc).isoformat()

    first_page = fetch_soup(session, start_url)
    max_page = get_max_page(first_page)
    logging.info("Detected %s shop pages", max_page)

    all_records = extract_product_records(first_page, page_number=1, scraped_at_utc=scraped_at_utc)
    logging.info("Page 1: %s products", len(all_records))

    for page_number in range(2, max_page + 1):
        page_url = build_page_url(start_url, page_number)
        soup = fetch_soup(session, page_url)
        page_records = extract_product_records(soup, page_number=page_number, scraped_at_utc=scraped_at_utc)
        all_records.extend(page_records)
        logging.info("Page %s: %s products", page_number, len(page_records))
        if delay_seconds > 0:
            time.sleep(delay_seconds)

    deduped: dict[str, ProductRecord] = {}
    unnamed_counter = 0
    for record in all_records:
        key = record.product_url or f"unnamed-{unnamed_counter}"
        deduped[key] = record
        if not record.product_url:
            unnamed_counter += 1

    records = list(deduped.values())
    logging.info("Collected %s unique products (%s raw rows)", len(records), len(all_records))
    return records


def run_once(
    start_url: str,
    latest_csv: Path,
    history_csv: Path,
    delay_seconds: float,
    run_pilot_mode_automation: bool = False,
) -> None:
    rows = scrape_inventory(start_url=start_url, delay_seconds=delay_seconds)
    write_csv(latest_csv, rows, append=False)
    write_csv(history_csv, rows, append=True)
    save_inventory_records(rows)
    logging.info("Wrote latest snapshot to %s", latest_csv)
    logging.info("Appended history to %s", history_csv)
    logging.info("Synced inventory rows to shared database")
    if run_pilot_mode_automation:
        from automation.pilot_mode import run_pilot_mode

        summary = run_pilot_mode()
        logging.info("Pilot mode automation summary: %s", summary)


def seconds_until_next_run(hour_utc: int, minute_utc: int) -> int:
    now = datetime.now(timezone.utc)
    target = now.replace(hour=hour_utc, minute=minute_utc, second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)
    return int((target - now).total_seconds())


def run_daily(
    start_url: str,
    latest_csv: Path,
    history_csv: Path,
    delay_seconds: float,
    hour_utc: int,
    minute_utc: int,
    run_pilot_mode_automation: bool = False,
) -> None:
    while True:
        wait_seconds = seconds_until_next_run(hour_utc=hour_utc, minute_utc=minute_utc)
        logging.info(
            "Next scheduled run in %s seconds at %02d:%02d UTC",
            wait_seconds,
            hour_utc,
            minute_utc,
        )
        time.sleep(wait_seconds)
        try:
            run_once(
                start_url=start_url,
                latest_csv=latest_csv,
                history_csv=history_csv,
                delay_seconds=delay_seconds,
                run_pilot_mode_automation=run_pilot_mode_automation,
            )
        except Exception:
            logging.exception("Scheduled run failed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape MiningCave shop-page products (price + stock) into CSV files."
    )
    parser.add_argument("--start-url", default=SHOP_URL, help="Shop page URL (default: %(default)s)")
    parser.add_argument(
        "--latest-csv",
        default="data/miningcave_inventory_latest.csv",
        help="Path for latest inventory snapshot CSV (default: %(default)s)",
    )
    parser.add_argument(
        "--history-csv",
        default="data/miningcave_inventory_history.csv",
        help="Path for append-only historical CSV (default: %(default)s)",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=DEFAULT_DELAY_SECONDS,
        help="Delay between paginated requests (default: %(default)s)",
    )
    parser.add_argument(
        "--daily",
        action="store_true",
        help="Run forever and scrape once per day at --daily-hour-utc:--daily-minute-utc",
    )
    parser.add_argument("--daily-hour-utc", type=int, default=0, help="UTC hour for daily runs (0-23)")
    parser.add_argument("--daily-minute-utc", type=int, default=5, help="UTC minute for daily runs (0-59)")
    parser.add_argument(
        "--run-pilot-mode",
        action="store_true",
        help="After each scrape, run AI automations for marketing + SEO outputs",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    args = parse_args()

    latest_csv = Path(args.latest_csv)
    history_csv = Path(args.history_csv)

    if args.daily:
        run_daily(
            start_url=args.start_url,
            latest_csv=latest_csv,
            history_csv=history_csv,
            delay_seconds=args.delay_seconds,
            hour_utc=args.daily_hour_utc,
            minute_utc=args.daily_minute_utc,
            run_pilot_mode_automation=args.run_pilot_mode,
        )
        return

    run_once(
        start_url=args.start_url,
        latest_csv=latest_csv,
        history_csv=history_csv,
        delay_seconds=args.delay_seconds,
        run_pilot_mode_automation=args.run_pilot_mode,
    )


if __name__ == "__main__":
    main()
