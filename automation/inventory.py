from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass
class Product:
    product_url: str
    product_name: str
    description: str
    shipping_text: str
    stock_text: str
    in_stock: int
    price_value: float
    price_text: str
    currency: str
    image_url: str


def _to_int(value: str) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        lowered = str(value).strip().lower()
        if lowered == "true":
            return 1
        return 0


def _to_float(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def load_products(csv_path: Path) -> list[Product]:
    if not csv_path.exists():
        raise FileNotFoundError(f"Inventory CSV not found: {csv_path}")

    rows: list[Product] = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(
                Product(
                    product_url=row.get("product_url", "").strip(),
                    product_name=row.get("product_name", "").strip(),
                    description=row.get("description", "").strip(),
                    shipping_text=row.get("shipping_text", "").strip(),
                    stock_text=row.get("stock_text", "").strip(),
                    in_stock=_to_int(row.get("in_stock", "")),
                    price_value=_to_float(row.get("price_value", "")),
                    price_text=row.get("price_text", "").strip(),
                    currency=row.get("currency", "").strip(),
                    image_url=row.get("image_url", "").strip(),
                )
            )
    return rows


def load_products_from_data_dir(data_dir: Path) -> list[Product]:
    """Load products from all CSV files in a directory and deduplicate rows.

    Uses all rows across files to improve retrieval context for the assistant.
    Dedup key preference:
    1) product_url
    2) product_name + image_url
    """
    if not data_dir.exists():
        return []

    csv_files = sorted(data_dir.glob("*.csv"))
    if not csv_files:
        return []

    deduped: dict[str, Product] = {}
    for csv_file in csv_files:
        try:
            products = load_products(csv_file)
        except Exception:
            continue
        for p in products:
            key = p.product_url.strip() or f"{p.product_name.strip()}|{p.image_url.strip()}"
            if not key.strip("|"):
                continue
            # Keep row with better stock signal and richer description if collisions happen.
            existing = deduped.get(key)
            if not existing:
                deduped[key] = p
                continue
            if p.in_stock > existing.in_stock:
                deduped[key] = p
                continue
            if len(p.description) > len(existing.description):
                deduped[key] = p

    return list(deduped.values())


def top_in_stock(products: Iterable[Product], limit: int = 12) -> list[Product]:
    return sorted((p for p in products if p.in_stock > 0), key=lambda p: p.price_value, reverse=True)[:limit]
