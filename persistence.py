from __future__ import annotations

import os
from dataclasses import asdict
from typing import Any

from sqlalchemy import (
    Column,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    asc,
    create_engine,
    delete,
    desc,
    func,
    insert,
    or_,
    select,
)

DEFAULT_DB_URL = "sqlite:///data/inventory.db"

metadata = MetaData()

inventory_latest = Table(
    "inventory_latest",
    metadata,
    Column("product_key", String(1024), primary_key=True),
    Column("scraped_at_utc", String(64), nullable=False),
    Column("page_number", Integer, nullable=False),
    Column("product_url", String(1024), nullable=False),
    Column("product_name", String(512), nullable=False),
    Column("image_url", String(1024), nullable=False),
    Column("shipping_text", String(1024), nullable=False),
    Column("description", String(4096), nullable=False),
    Column("stock_text", String(255), nullable=False),
    Column("in_stock", Integer, nullable=False),
    Column("price_text", String(255), nullable=False),
    Column("price_value", Float, nullable=True),
    Column("currency", String(32), nullable=False),
    Column("gtm_product_id", String(64), nullable=False),
)

inventory_history = Table(
    "inventory_history",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("product_key", String(1024), nullable=False),
    Column("scraped_at_utc", String(64), nullable=False),
    Column("page_number", Integer, nullable=False),
    Column("product_url", String(1024), nullable=False),
    Column("product_name", String(512), nullable=False),
    Column("image_url", String(1024), nullable=False),
    Column("shipping_text", String(1024), nullable=False),
    Column("description", String(4096), nullable=False),
    Column("stock_text", String(255), nullable=False),
    Column("in_stock", Integer, nullable=False),
    Column("price_text", String(255), nullable=False),
    Column("price_value", Float, nullable=True),
    Column("currency", String(32), nullable=False),
    Column("gtm_product_id", String(64), nullable=False),
)


def get_db_url() -> str:
    return (
        os.getenv("INVENTORY_DB_URL", "").strip()
        or os.getenv("DATABASE_URL", "").strip()
        or DEFAULT_DB_URL
    )


def get_engine():
    return create_engine(get_db_url(), future=True, pool_pre_ping=True)


def init_db() -> None:
    engine = get_engine()
    metadata.create_all(engine)


def _product_key(record: dict[str, Any]) -> str:
    if record.get("product_url"):
        return str(record["product_url"])
    gtm = str(record.get("gtm_product_id", "")).strip()
    if gtm:
        return f"gtm:{gtm}"
    return f"name:{record.get('product_name','')}:img:{record.get('image_url','')}"


def save_inventory_records(records: list[Any]) -> None:
    if not records:
        return
    init_db()
    engine = get_engine()
    with engine.begin() as conn:
        rows: list[dict[str, Any]] = []
        keys: list[str] = []
        for record in records:
            row = asdict(record) if hasattr(record, "__dataclass_fields__") else dict(record)
            row["product_key"] = _product_key(row)
            row["in_stock"] = int(row.get("in_stock", 0) or 0)
            rows.append(row)
            keys.append(row["product_key"])

        conn.execute(delete(inventory_latest).where(inventory_latest.c.product_key.in_(keys)))
        conn.execute(insert(inventory_latest), rows)
        conn.execute(insert(inventory_history), rows)


def get_inventory_page(
    dataset: str,
    page: int,
    per_page: int,
    search: str = "",
    sort_by: str = "product_name",
    sort_order: str = "asc",
) -> dict[str, Any]:
    init_db()
    table = inventory_history if dataset == "history" else inventory_latest
    page = max(page, 1)
    per_page = max(1, min(per_page, 200))
    offset = (page - 1) * per_page
    search = (search or "").strip()
    sort_by = (sort_by or "product_name").strip()
    sort_order = (sort_order or "asc").strip().lower()
    if sort_by not in {"product_name", "price_text", "price_value", "stock_text"}:
        sort_by = "product_name"
    if sort_order not in {"asc", "desc"}:
        sort_order = "asc"

    engine = get_engine()

    with engine.connect() as conn:
        base = select(table)
        if search:
            like_pattern = f"%{search}%"
            base = base.where(
                or_(
                    table.c.product_name.ilike(like_pattern),
                    table.c.price_text.ilike(like_pattern),
                    func.cast(table.c.price_value, String).ilike(like_pattern),
                    table.c.stock_text.ilike(like_pattern),
                )
            )

        count_query = select(func.count()).select_from(base.subquery())
        total = conn.execute(count_query).scalar_one()

        sort_col = getattr(table.c, sort_by)
        order_expr = desc(sort_col) if sort_order == "desc" else asc(sort_col)
        query = base.order_by(order_expr).limit(per_page).offset(offset)
        result = conn.execute(query).mappings().all()

    rows = []
    for item in result:
        row = dict(item)
        row.pop("product_key", None)
        row.pop("id", None)
        rows.append(row)

    total_pages = (total + per_page - 1) // per_page if total else 0
    return {
        "rows": rows,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
    }
