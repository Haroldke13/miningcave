from __future__ import annotations

import re

from automation.inventory import Product
from automation.openai_client import OpenAIClient

STOP_WORDS = {
    "i",
    "me",
    "my",
    "need",
    "want",
    "show",
    "give",
    "find",
    "for",
    "with",
    "that",
    "this",
    "under",
    "over",
    "below",
    "above",
    "than",
    "and",
    "the",
    "a",
    "an",
    "to",
    "of",
    "in",
    "stock",
    "miner",
    "miners",
    "bitcoin",
    "is",
    "are",
    "be",
    "been",
    "being",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "will",
    "would",
    "could",
    "should",
    "may",
    "might",
    "must",
    "can",
    "on",
    "at",
    "by",
    "from",
    "up",
    "about",
    "out",
    "as",
    "or",
    "if",
    "because",
    "as",
    "until",
    "while",
    "it",
    "its",
    "not",
    "no",
    "nor",
    "so",
    "such",
    "only",
    "own",
    "same",
    "than",
    "too",
    "very",
    "just",
    "where",
    "when",
    "why",
    "how",
    "all",
    "each",
    "every",
    "both",
    "few",
    "more",
    "most",
    "other",
    "some",
    "any",
}

MINER_KEYWORDS = (
    "antminer",
    "whatsminer",
    "avalon",
    "miner",
    "th/s",
    "gh/s",
    "kh/s",
    "mh/s",
    "bitcoin miner",
    "asic miner",
    "mining rig",
    "crypto miner",
    "hash rate",
    "hashrate",
    "mining hardware",
    "mining device",
)
ACCESSORY_KEYWORDS = (
    "fan",
    "cable",
    "splitter",
    "adapter",
    "control board",
    "psu for",
    "kit",
    "dummy",
    "power supply",
    "psu",
    "power supply for",
    "cooling fan",
    "replacement fan",
    "power cord",
    "extension cable",
    "mining cable",
    "power splitter",
    "pcie splitter",
    "breakout board",
    "control module",
    "management board",
    "firmware",
    "software",
    "cooling solution",
    "thermal pad",
)


def _product_line(product: Product) -> str:
    return (
        f"- {product.product_name} | price={product.price_text or product.price_value} | "
        f"price_value={product.price_value} | in_stock={product.in_stock} | "
        f"stock={product.stock_text} | shipping={product.shipping_text} | "
        f"url={product.product_url}"
    )


def _parse_amount(value: str) -> float:
    return float(value.replace(",", "").strip())


def _extract_price_limits(query: str) -> tuple[float | None, float | None, bool]:
    q = query.lower()
    # Common typo normalization
    q = q.replace("undfer", "under").replace("ovre", "over")
    min_price: float | None = None
    max_price: float | None = None

    between_match = re.search(
        r"between\s+\$?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s+(?:and|to)\s+\$?\s*([0-9][0-9,]*(?:\.[0-9]+)?)",
        q,
    )
    if between_match:
        a = _parse_amount(between_match.group(1))
        b = _parse_amount(between_match.group(2))
        lo, hi = sorted([a, b])
        min_price, max_price = lo, hi

    min_match = re.search(
        r"(?:over|above|more than|at least|minimum|min)\s+\$?\s*([0-9][0-9,]*(?:\.[0-9]+)?)",
        q,
    )
    if min_match:
        min_price = _parse_amount(min_match.group(1))

    max_match = re.search(
        r"(?:under|below|less than|at most|maximum|max)\s+\$?\s*([0-9][0-9,]*(?:\.[0-9]+)?)",
        q,
    )
    if max_match:
        max_price = _parse_amount(max_match.group(1))

    contradictory = min_price is not None and max_price is not None and min_price >= max_price
    return min_price, max_price, contradictory


def _query_terms(query: str) -> list[str]:
    words = re.findall(r"[a-z0-9\+\-]{2,}", query.lower())
    return [w for w in words if w not in STOP_WORDS]


def _score_product(product: Product, terms: list[str]) -> int:
    if not terms:
        return 0
    name = product.product_name.lower()
    desc = product.description.lower()
    score = 0
    for term in terms:
        if term in name:
            score += 4
        elif term in desc:
            score += 2
    return score


def _looks_like_core_miner(product: Product) -> bool:
    text = f"{product.product_name} {product.description}".lower()
    if any(k in text for k in ACCESSORY_KEYWORDS):
        return False
    return any(k in text for k in MINER_KEYWORDS)


def find_relevant_products(products: list[Product], query: str, limit: int = 12) -> list[Product]:
    q = query.lower().strip()
    if not q:
        return products[:limit]

    min_price, max_price, contradictory = _extract_price_limits(q)
    if contradictory:
        return []
    require_in_stock = any(k in q for k in ["in stock", "in-stock", "available", "ready to ship"])
    miner_intent = any(k in q for k in ["bitcoin miner", "asic miner", "miner", "antminer", "whatsminer", "avalon"])
    terms = _query_terms(q)

    candidate_products = []
    for p in products:
        if require_in_stock:
            stock_text = p.stock_text.lower()
            # Explicitly honor stock_text signal when user asks for in-stock items.
            if "in stock" not in stock_text and p.in_stock <= 0:
                continue
        if miner_intent and not _looks_like_core_miner(p):
            continue
        if min_price is not None and p.price_value < min_price:
            continue
        if max_price is not None and p.price_value > max_price:
            continue
        candidate_products.append(p)
    strict_filtering = require_in_stock or miner_intent or min_price is not None or max_price is not None
    if not candidate_products and not strict_filtering:
        candidate_products = products
    if not candidate_products:
        return []

    ranked: list[tuple[int, Product]] = []
    for p in candidate_products:
        score = _score_product(p, terms)
        if p.in_stock > 0:
            score += 1
        ranked.append((score, p))

    # Prefer higher semantic match on product_name/description, then available stock.
    ranked.sort(key=lambda x: (x[0], x[1].in_stock, -x[1].price_value), reverse=True)
    top = [p for score, p in ranked if score > 0][:limit]
    if top:
        return top

    # If user only gave budget/availability with no strong name terms, return by best stock/price fit.
    candidate_products.sort(key=lambda p: (p.in_stock <= 0, p.price_value))
    return candidate_products[:limit]


def _local_response(
    user_message: str,
    relevant: list[Product],
    min_price: float | None,
    max_price: float | None,
    contradictory: bool,
) -> str:
    if contradictory:
        return "Your price filter is contradictory (minimum is higher than maximum). Please adjust and retry."
    if not relevant:
        return (
            "I could not find an exact product match for that price/stock filter in the current catalog snapshot. "
            "Please adjust the budget range or stock constraint."
        )

    lines = ["Here are matching products from the current inventory data:"]
    for p in relevant:
        lines.append(
            f"- {p.product_name} | ${p.price_value:.2f} | stock={p.in_stock} | {p.product_url}"
        )
    if min_price is not None or max_price is not None:
        lines.append(
            f"Applied price filter: min={min_price if min_price is not None else 'none'}, "
            f"max={max_price if max_price is not None else 'none'}."
        )
    return "\n".join(lines)


def answer_customer_question(
    ai: OpenAIClient,
    products: list[Product],
    user_message: str,
) -> str:
    q = user_message.lower().strip()
    min_price, max_price, contradictory = _extract_price_limits(q)
    # Use a wider retrieval set so fallback can list all available matching options.
    relevant = find_relevant_products(products, user_message, limit=500)
    if not relevant:
        return _local_response(user_message, relevant, min_price, max_price, contradictory)
    # Keep model context bounded for reliability; fallback still contains all.
    catalog_context = "\n".join(_product_line(p) for p in relevant[:30])
    system_prompt = (
        "You are MiningCave's 24/7 AI sales and support agent. "
        "Be concise, trustworthy, and conversion-focused. "
        "Only claim stock/pricing from provided catalog context. "
        "If uncertain, say you will verify and suggest contacting support."
    )
    user_prompt = (
        f"Customer message:\n{user_message}\n\n"
        f"Relevant catalog context:\n{catalog_context}\n\n"
        "Respond with:\n"
        "1) Direct answer\n"
        "2) 2-4 recommended products if relevant\n"
        "3) Clear next step (buy now link or support handoff)\n"
        "When customer asks by budget, respect numeric price_value limits."
    )
    model_answer = ai.text(system_prompt=system_prompt, user_prompt=user_prompt, max_output_tokens=500)
    if model_answer and model_answer.strip():
        return model_answer.strip()
    return _local_response(user_message, relevant, min_price, max_price, contradictory)
