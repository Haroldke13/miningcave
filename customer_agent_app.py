from __future__ import annotations

import csv
import hmac
import logging
import os
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from automation.config import load_settings
from automation.customer_agent import answer_customer_question
from automation.inventory import Product, load_products, load_products_from_data_dir
from automation.marketing import create_marketing_asset, post_to_facebook_page, save_marketing_asset
from automation.openai_client import OpenAIClient
from automation.pilot_mode import run_pilot_mode
from automation.seo import generate_seo_updates
from inventory_worker import SHOP_URL, run_once
from persistence import get_inventory_page, init_db

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
_seed_lock = threading.Lock()
_seed_attempted = False
_seed_in_progress = False
_cache_lock = threading.Lock()
_products_cache: list[Product] = []
_products_cache_updated_at = 0.0
_products_cache_refreshing = False


def _build_runtime() -> tuple[OpenAIClient, list]:
    settings = load_settings()
    ai = OpenAIClient(api_key=settings.openai_api_key, model=settings.openai_model)
    products = _get_cached_products(settings)
    return ai, products


def _load_products_for_assistant(settings) -> list[Product]:
    products: list[Product] = []
    try:
        db_page = get_inventory_page(dataset="latest", page=1, per_page=200)
        if db_page["rows"]:
            for row in db_page["rows"]:
                products.append(
                    Product(
                        product_url=str(row.get("product_url", "")),
                        product_name=str(row.get("product_name", "")),
                        description=str(row.get("description", "")),
                        shipping_text=str(row.get("shipping_text", "")),
                        stock_text=str(row.get("stock_text", "")),
                        in_stock=int(row.get("in_stock", 0) or 0),
                        price_value=float(row.get("price_value") or 0),
                        price_text=str(row.get("price_text", "")),
                        currency=str(row.get("currency", "")),
                        image_url=str(row.get("image_url", "")),
                    )
                )
    except Exception:
        logging.exception("Failed to read inventory from DB; falling back to CSV")

    if not products:
        products = load_products(settings.inventory_csv)

    # Expand assistant context using all CSV rows in /data directory.
    try:
        expanded = load_products_from_data_dir(settings.inventory_csv.parent)
        if expanded:
            products = expanded
            logging.info("Assistant context expanded from data CSVs: %s products", len(products))
    except Exception:
        logging.exception("Failed to expand assistant context from data directory")
    return products


def _cache_ttl_seconds() -> int:
    raw = os.getenv("ASSISTANT_CONTEXT_CACHE_TTL_SECONDS", "300").strip()
    try:
        return max(30, int(raw))
    except ValueError:
        return 300


def _set_cached_products(products: list[Product]) -> None:
    global _products_cache, _products_cache_updated_at
    with _cache_lock:
        _products_cache = products
        _products_cache_updated_at = time.time()


def _invalidate_products_cache() -> None:
    global _products_cache_updated_at
    with _cache_lock:
        _products_cache_updated_at = 0.0


def _refresh_products_cache_async(settings) -> None:
    global _products_cache_refreshing
    with _cache_lock:
        if _products_cache_refreshing:
            return
        _products_cache_refreshing = True

    def _job() -> None:
        global _products_cache_refreshing
        try:
            products = _load_products_for_assistant(settings)
            _set_cached_products(products)
        finally:
            _products_cache_refreshing = False

    threading.Thread(target=_job, daemon=True, name="assistant-products-cache-refresh").start()


def _get_cached_products(settings) -> list[Product]:
    ttl = _cache_ttl_seconds()
    now = time.time()
    with _cache_lock:
        has_cache = bool(_products_cache)
        age = now - _products_cache_updated_at if _products_cache_updated_at else float("inf")
        cached_copy = list(_products_cache)

    # First request: load synchronously once.
    if not has_cache:
        products = _load_products_for_assistant(settings)
        _set_cached_products(products)
        return products

    # Cache exists but stale: return current cache immediately and refresh in background.
    if age > ttl:
        _refresh_products_cache_async(settings)
    return cached_copy


def _inventory_paths() -> tuple[Path, Path]:
    settings = load_settings()
    latest = settings.inventory_csv
    history = latest.parent / "miningcave_inventory_history.csv"
    return latest, history


def _to_stock_count(value: str) -> int:
    text = str(value).strip().lower()
    if not text:
        return 0
    if text == "true":
        return 1
    if text == "false":
        return 0
    try:
        return int(float(text))
    except ValueError:
        return 0


def _normalize_inventory_row(row: dict) -> dict:
    in_stock_count = _to_stock_count(row.get("in_stock", "0"))
    stock_text = str(row.get("stock_text", "")).strip()
    if in_stock_count <= 0:
        stock_text = "Out of Stock"
    elif "in stock" in stock_text.lower():
        stock_text = f"In Stock ({in_stock_count})"
    elif not stock_text:
        stock_text = f"In Stock ({in_stock_count})"

    row["in_stock"] = str(in_stock_count)
    row["stock_text"] = stock_text
    return row


def _paginate_csv(
    csv_path: Path,
    page: int,
    per_page: int,
    search: str = "",
    sort_by: str = "product_name",
    sort_order: str = "asc",
) -> dict:
    if not csv_path.exists():
        return {"rows": [], "total": 0, "page": page, "per_page": per_page, "total_pages": 0}

    page = max(page, 1)
    per_page = max(min(per_page, 200), 1)
    search = (search or "").strip().lower()
    sort_by = (sort_by or "product_name").strip()
    sort_order = (sort_order or "asc").strip().lower()
    if sort_by not in {"product_name", "price_text", "price_value", "stock_text"}:
        sort_by = "product_name"
    if sort_order not in {"asc", "desc"}:
        sort_order = "asc"

    all_rows = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            norm = _normalize_inventory_row(row)
            if search:
                joined = " ".join(
                    [
                        str(norm.get("product_name", "")),
                        str(norm.get("price_text", "")),
                        str(norm.get("price_value", "")),
                        str(norm.get("stock_text", "")),
                    ]
                ).lower()
                if search not in joined:
                    continue
            all_rows.append(norm)

    if sort_by == "price_value":
        all_rows.sort(
            key=lambda r: float(r.get("price_value") or 0),
            reverse=(sort_order == "desc"),
        )
    else:
        all_rows.sort(
            key=lambda r: str(r.get(sort_by, "")).lower(),
            reverse=(sort_order == "desc"),
        )
    total = len(all_rows)
    start_index = (page - 1) * per_page
    end_index = start_index + per_page
    rows = all_rows[start_index:end_index]

    total_pages = (total + per_page - 1) // per_page if total else 0
    return {
        "rows": rows,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
    }


def _parse_int_query(name: str, default: int, minimum: int = 1, maximum: int = 200) -> tuple[int | None, str | None]:
    raw = request.args.get(name, str(default))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None, f"Invalid '{name}' value: must be an integer."
    if value < minimum or value > maximum:
        return None, f"Invalid '{name}' value: must be between {minimum} and {maximum}."
    return value, None


def _require_automation_auth() -> tuple[bool, tuple[dict, int] | None]:
    configured = os.getenv("AUTOMATION_API_TOKEN", "").strip()
    allow_without_token = os.getenv("ALLOW_UI_AUTOMATION_WITHOUT_TOKEN", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if allow_without_token:
        return True, None
    if not configured:
        return False, ({"error": "Automation endpoint is disabled: missing AUTOMATION_API_TOKEN."}, 503)
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return False, ({"error": "Unauthorized"}, 401)
    token = auth.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(token, configured):
        return False, ({"error": "Forbidden"}, 403)
    return True, None


def _ensure_inventory_seeded() -> None:
    global _seed_attempted, _seed_in_progress
    try:
        db_data = get_inventory_page("latest", page=1, per_page=1)
        if db_data.get("total", 0) > 0:
            return
    except Exception:
        logging.exception("DB check failed while seeding inventory")

    latest, _ = _inventory_paths()
    if latest.exists() and latest.stat().st_size > 64:
        return

    def _seed_job() -> None:
        global _seed_in_progress
        settings = load_settings()
        try:
            logging.info("No inventory found; starting async initial scrape seed")
            run_once(
                start_url=SHOP_URL,
                latest_csv=settings.inventory_csv,
                history_csv=settings.inventory_csv.parent / "miningcave_inventory_history.csv",
                delay_seconds=0.2,
                run_pilot_mode_automation=False,
            )
            logging.info("Initial inventory seed completed")
        except Exception:
            logging.exception("Initial inventory seed failed")
        finally:
            _seed_in_progress = False

    with _seed_lock:
        if _seed_in_progress or _seed_attempted:
            return
        _seed_attempted = True
        _seed_in_progress = True
        thread = threading.Thread(target=_seed_job, daemon=True, name="inventory-seed")
        thread.start()


@app.get("/")
def index():
    return render_template("inventory.html")


@app.get("/inventory")
def inventory_page():
    return render_template("inventory.html")


@app.get("/health")
def health() -> tuple[dict, int]:
    try:
        init_db()
        return {"ok": True}, 200
    except Exception:
        return {"ok": False, "error": "Database unavailable"}, 503


@app.get("/api/inventory/latest")
def api_inventory_latest() -> tuple[dict, int]:
    _ensure_inventory_seeded()
    page, err = _parse_int_query("page", 1, 1, 500000)
    if err:
        return {"error": err}, 400
    per_page, err = _parse_int_query("per_page", 25, 1, 200)
    if err:
        return {"error": err}, 400
    search = request.args.get("search", "")
    sort_by = request.args.get("sort_by", "product_name")
    sort_order = request.args.get("sort_order", "asc")
    try:
        db_data = get_inventory_page(
            "latest",
            page=page or 1,
            per_page=per_page or 25,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        if db_data.get("total", 0) > 0:
            db_data["seeding"] = False
            return db_data, 200
        latest, _ = _inventory_paths()
        csv_data = _paginate_csv(
            latest,
            page or 1,
            per_page or 25,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        csv_data["seeding"] = _seed_in_progress
        return csv_data, 200
    except Exception:
        logging.exception("DB inventory read failed; falling back to CSV")
        latest, _ = _inventory_paths()
        csv_data = _paginate_csv(
            latest,
            page or 1,
            per_page or 25,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        csv_data["seeding"] = _seed_in_progress
        return csv_data, 200


@app.get("/api/inventory/history")
def api_inventory_history() -> tuple[dict, int]:
    _ensure_inventory_seeded()
    page, err = _parse_int_query("page", 1, 1, 500000)
    if err:
        return {"error": err}, 400
    per_page, err = _parse_int_query("per_page", 25, 1, 200)
    if err:
        return {"error": err}, 400
    search = request.args.get("search", "")
    sort_by = request.args.get("sort_by", "product_name")
    sort_order = request.args.get("sort_order", "asc")
    try:
        db_data = get_inventory_page(
            "history",
            page=page or 1,
            per_page=per_page or 25,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        if db_data.get("total", 0) > 0:
            db_data["seeding"] = False
            return db_data, 200
        _, history = _inventory_paths()
        csv_data = _paginate_csv(
            history,
            page or 1,
            per_page or 25,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        csv_data["seeding"] = _seed_in_progress
        return csv_data, 200
    except Exception:
        logging.exception("DB history read failed; falling back to CSV")
        _, history = _inventory_paths()
        csv_data = _paginate_csv(
            history,
            page or 1,
            per_page or 25,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        csv_data["seeding"] = _seed_in_progress
        return csv_data, 200


@app.post("/chat")
def chat() -> tuple[dict, int]:
    payload = request.get_json(silent=True) or {}
    user_message = str(payload.get("message", "")).strip()
    if not user_message:
        return {"error": "message is required"}, 400
    try:
        ai, products = _build_runtime()
        if not products:
            return {"error": "Inventory is not ready yet. Please retry shortly."}, 503
        answer = answer_customer_question(ai=ai, products=products, user_message=user_message)
        return {"answer": answer}, 200
    except ValueError as exc:
        if "OPENAI_API_KEY" in str(exc):
            return {"error": "AI assistant is temporarily unavailable (missing API key)."}, 503
        return {"error": "Invalid chat configuration."}, 500
    except Exception as exc:  # pragma: no cover
        logging.exception("Chat request failed")
        return {"error": "Chat service is temporarily unavailable."}, 500


@app.post("/api/chat")
def api_chat() -> tuple[dict, int]:
    return chat()


@app.post("/automation/pilot-mode/run")
def run_automation() -> tuple[dict, int]:
    ok, err_response = _require_automation_auth()
    if not ok:
        return err_response  # type: ignore[return-value]

    payload = request.get_json(silent=True) or {}
    try:
        max_seo_products = int(payload.get("max_seo_products", 50))
    except (TypeError, ValueError):
        return {"error": "max_seo_products must be an integer."}, 400
    if max_seo_products < 1 or max_seo_products > 500:
        return {"error": "max_seo_products must be between 1 and 500."}, 400
    try:
        result = run_pilot_mode(max_seo_products=max_seo_products)
        return jsonify(result), 200
    except ValueError as exc:
        if "OPENAI_API_KEY" in str(exc):
            return {"error": "Automation unavailable: missing OPENAI_API_KEY."}, 503
        return {"error": "Automation configuration error."}, 500
    except Exception:  # pragma: no cover
        logging.exception("Automation run failed")
        return {"error": "Automation run failed."}, 500


@app.post("/automation/refresh-products-seo")
def refresh_products_and_seo() -> tuple[dict, int]:
    ok, err_response = _require_automation_auth()
    if not ok:
        return err_response  # type: ignore[return-value]

    payload = request.get_json(silent=True) or {}
    try:
        max_seo_products = int(payload.get("max_seo_products", 50))
    except (TypeError, ValueError):
        return {"error": "max_seo_products must be an integer."}, 400
    if max_seo_products < 1 or max_seo_products > 500:
        return {"error": "max_seo_products must be between 1 and 500."}, 400

    settings = load_settings()
    try:
        # 1) Refresh product inventory from source and sync CSV + DB
        run_once(
            start_url=SHOP_URL,
            latest_csv=settings.inventory_csv,
            history_csv=settings.inventory_csv.parent / "miningcave_inventory_history.csv",
            delay_seconds=0.2,
            run_pilot_mode_automation=False,
        )
        _invalidate_products_cache()

        # 2) Regenerate SEO CSV output
        ai = OpenAIClient(api_key=settings.openai_api_key, model=settings.openai_model)
        products = load_products(settings.inventory_csv)
        seo_rows = generate_seo_updates(
            ai=ai,
            products=products,
            output_csv=settings.latest_seo_csv,
            max_products=max_seo_products,
        )
        return {
            "ok": True,
            "inventory_csv": str(settings.inventory_csv),
            "seo_output_csv": str(settings.latest_seo_csv),
            "seo_rows_written": len(seo_rows),
        }, 200
    except ValueError as exc:
        if "OPENAI_API_KEY" in str(exc):
            return {"error": "SEO refresh unavailable: missing OPENAI_API_KEY."}, 503
        return {"error": "Refresh configuration error."}, 500
    except Exception:
        logging.exception("Refresh products + SEO failed")
        return {"error": "Refresh failed."}, 500


@app.post("/automation/post-social-update")
def post_social_update() -> tuple[dict, int]:
    ok, err_response = _require_automation_auth()
    if not ok:
        return err_response  # type: ignore[return-value]

    settings = load_settings()
    try:
        # Refresh latest inventory before creating social content.
        run_once(
            start_url=SHOP_URL,
            latest_csv=settings.inventory_csv,
            history_csv=settings.inventory_csv.parent / "miningcave_inventory_history.csv",
            delay_seconds=0.2,
            run_pilot_mode_automation=False,
        )
        _invalidate_products_cache()
        ai = OpenAIClient(api_key=settings.openai_api_key, model=settings.openai_model)
        products = load_products(settings.inventory_csv)
        asset = create_marketing_asset(
            ai=ai,
            products=products,
            output_dir=settings.latest_marketing_dir,
        )
        asset = post_to_facebook_page(
            asset=asset,
            page_id=settings.facebook_page_id,
            access_token=settings.facebook_access_token,
            dry_run=settings.dry_run_social,
        )
        output_file = save_marketing_asset(asset, settings.latest_marketing_dir)
        return {
            "ok": True,
            "posted": asset.posted,
            "channel": asset.channel,
            "asset_file": str(output_file),
            "message": "Social update complete.",
        }, 200
    except ValueError as exc:
        if "OPENAI_API_KEY" in str(exc):
            return {"error": "Social update unavailable: missing OPENAI_API_KEY."}, 503
        return {"error": "Social update configuration error."}, 500
    except Exception:
        logging.exception("Social update failed")
        return {"error": "Social update failed."}, 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
