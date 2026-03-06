from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv


@dataclass
class Settings:
    openai_api_key: str
    openai_model: str
    inventory_csv: Path
    latest_marketing_dir: Path
    latest_seo_csv: Path
    facebook_page_id: str
    facebook_access_token: str
    dry_run_social: bool


def _as_bool(value: str, default: bool) -> bool:
    if not value:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_settings() -> Settings:
    dotenv_path = os.getenv("DOTENV_PATH", ".env")
    load_dotenv(dotenv_path=dotenv_path, override=False)

    return Settings(
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip(),
        inventory_csv=Path(os.getenv("INVENTORY_CSV", "data/miningcave_inventory_latest.csv")),
        latest_marketing_dir=Path(os.getenv("MARKETING_OUTPUT_DIR", "data/marketing")),
        latest_seo_csv=Path(os.getenv("SEO_OUTPUT_CSV", "data/seo_product_updates.csv")),
        facebook_page_id=os.getenv("FACEBOOK_PAGE_ID", "").strip(),
        facebook_access_token=os.getenv("FACEBOOK_ACCESS_TOKEN", "").strip(),
        dry_run_social=_as_bool(os.getenv("DRY_RUN_SOCIAL", "true"), default=True),
    )
