from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from automation.config import load_settings
from automation.inventory import load_products
from automation.marketing import create_marketing_asset, post_to_facebook_page, save_marketing_asset
from automation.openai_client import OpenAIClient
from automation.seo import generate_seo_updates


def run_pilot_mode(max_seo_products: int = 50) -> dict:
    settings = load_settings()
    products = load_products(settings.inventory_csv)
    ai = OpenAIClient(api_key=settings.openai_api_key, model=settings.openai_model)

    marketing_asset = create_marketing_asset(
        ai=ai,
        products=products,
        output_dir=settings.latest_marketing_dir,
    )
    marketing_asset = post_to_facebook_page(
        asset=marketing_asset,
        page_id=settings.facebook_page_id,
        access_token=settings.facebook_access_token,
        dry_run=settings.dry_run_social,
    )
    marketing_json = save_marketing_asset(marketing_asset, settings.latest_marketing_dir)

    seo_rows = generate_seo_updates(
        ai=ai,
        products=products,
        output_csv=settings.latest_seo_csv,
        max_products=max_seo_products,
    )

    result = {
        "ran_at_utc": datetime.now(timezone.utc).isoformat(),
        "inventory_rows": len(products),
        "marketing_asset": asdict(marketing_asset),
        "marketing_asset_file": str(marketing_json),
        "seo_rows_written": len(seo_rows),
        "seo_file": str(settings.latest_seo_csv),
        "dry_run_social": settings.dry_run_social,
    }
    summary_path = Path("data/pilot_mode_last_run.json")
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run MiningCave pilot mode automations.")
    parser.add_argument("--max-seo-products", type=int, default=50)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_pilot_mode(max_seo_products=args.max_seo_products)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

