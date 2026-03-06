from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

from automation.inventory import Product, top_in_stock
from automation.openai_client import OpenAIClient


@dataclass
class MarketingAsset:
    created_at_utc: str
    caption: str
    hashtags: str
    image_path: str
    channel: str
    posted: bool
    remote_id: str


def _build_marketing_prompt(products: list[Product]) -> str:
    lines = []
    for p in top_in_stock(products, limit=8):
        lines.append(f"- {p.product_name} | {p.price_text} | {p.shipping_text} | {p.product_url}")
    return "\n".join(lines)


def create_marketing_asset(
    ai: OpenAIClient,
    products: list[Product],
    output_dir: Path,
) -> MarketingAsset:
    output_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    context = _build_marketing_prompt(products)
    caption = ai.text(
        system_prompt=(
            "You are MiningCave's social media growth marketer. "
            "Write performance-focused crypto mining product social copy."
        ),
        user_prompt=(
            f"Use this in-stock catalog context:\n{context}\n\n"
            "Return exactly:\n"
            "Line 1: Caption (<= 100 words)\n"
            "Line 2: Hashtags (8-15 relevant tags)"
        ),
        max_output_tokens=260,
    )
    lines = [line.strip() for line in caption.splitlines() if line.strip()]
    caption_line = lines[0] if lines else "Top mining machines now available at MiningCave."
    hashtags_line = lines[1] if len(lines) > 1 else "#bitcoin #asicminer #cryptomining #miningcave"

    image_prompt = (
        "Create a premium product-marketing style image for ASIC crypto miners, "
        "clean studio lighting, no text overlay, modern ecommerce visual."
    )
    image_b64 = ai.generate_image_b64(prompt=image_prompt, size="1024x1024")
    image_path = output_dir / f"social_{now}.png"
    ai.save_b64_image(image_b64, str(image_path))

    return MarketingAsset(
        created_at_utc=datetime.now(timezone.utc).isoformat(),
        caption=caption_line,
        hashtags=hashtags_line,
        image_path=str(image_path),
        channel="facebook",
        posted=False,
        remote_id="",
    )


def post_to_facebook_page(
    asset: MarketingAsset,
    page_id: str,
    access_token: str,
    dry_run: bool = True,
) -> MarketingAsset:
    if dry_run:
        return asset
    if not page_id or not access_token:
        raise ValueError("FACEBOOK_PAGE_ID and FACEBOOK_ACCESS_TOKEN are required for live posting")

    url = f"https://graph.facebook.com/v21.0/{page_id}/photos"
    caption = f"{asset.caption}\n\n{asset.hashtags}"
    with open(asset.image_path, "rb") as image_file:
        files = {"source": image_file}
        data = {
            "caption": caption,
            "access_token": access_token,
        }
        response = requests.post(url, files=files, data=data, timeout=60)
    response.raise_for_status()
    payload = response.json()
    asset.posted = True
    asset.remote_id = str(payload.get("id", ""))
    return asset


def save_marketing_asset(asset: MarketingAsset, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "latest_marketing_asset.json"
    with output_file.open("w", encoding="utf-8") as f:
        json.dump(asset.__dict__, f, indent=2)
    return output_file

