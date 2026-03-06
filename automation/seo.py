from __future__ import annotations

import csv
import json
from dataclasses import dataclass, asdict
from pathlib import Path

from automation.inventory import Product
from automation.openai_client import OpenAIClient


@dataclass
class SEORecord:
    product_url: str
    product_name: str
    seo_title: str
    seo_description: str
    seo_keywords: str
    optimized_description: str


def _optimize_product(ai: OpenAIClient, product: Product) -> SEORecord:
    result = ai.text(
        system_prompt=(
            "You are an ecommerce SEO specialist for crypto mining hardware. "
            "Write high-converting product SEO fields."
        ),
        user_prompt=(
            "Return strict JSON with keys: seo_title, seo_description, seo_keywords, optimized_description.\n"
            f"Product name: {product.product_name}\n"
            f"Current description: {product.description}\n"
            f"Price: {product.price_text}\n"
            f"Shipping: {product.shipping_text}\n"
            f"Stock: {product.stock_text}\n"
        ),
        max_output_tokens=420,
    )
    try:
        data = json.loads(result)
    except json.JSONDecodeError:
        data = {
            "seo_title": product.product_name[:60],
            "seo_description": product.description[:155],
            "seo_keywords": "ASIC miner, bitcoin miner, mining hardware",
            "optimized_description": product.description,
        }

    return SEORecord(
        product_url=product.product_url,
        product_name=product.product_name,
        seo_title=str(data.get("seo_title", product.product_name))[:70],
        seo_description=str(data.get("seo_description", product.description))[:170],
        seo_keywords=str(data.get("seo_keywords", "ASIC miner, bitcoin miner")),
        optimized_description=str(data.get("optimized_description", product.description)),
    )


def generate_seo_updates(
    ai: OpenAIClient,
    products: list[Product],
    output_csv: Path,
    max_products: int = 50,
) -> list[SEORecord]:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    selected = [p for p in products if p.product_name][:max_products]
    rows = [_optimize_product(ai, p) for p in selected]

    with output_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(SEORecord.__dataclass_fields__.keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))
    return rows

