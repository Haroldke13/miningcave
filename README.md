# MiningCave Inventory Scraper and AI Agent

Scrapes product stock and pricing from the MiningCave WooCommerce storefront, stores snapshots and history, and serves an inventory dashboard plus an LLM-backed sales chat over that data.

## What it does

Three pieces share one codebase, selected at runtime by `APP_MODE` in `start.sh`.

**Scraper (`inventory_worker.py`).** Fetches `https://miningcave.com/shop-page/`, reads the page count from `nav.woocommerce-pagination`, then walks every page extracting each `div.product-item-info`: product name, product URL, price text and a normalised numeric price, stock status text (with an explicit out-of-stock check and a quantity parse), shipping text, description, image URL and a GTM product id. Results are written to `data/miningcave_inventory_latest.csv` (overwritten each run) and appended to `data/miningcave_inventory_history.csv`. Flags: `--start-url`, `--daily`, `--daily-hour-utc`, `--daily-minute-utc`, `--run-pilot-mode`. The `--daily` scheduler is a built-in sleep loop, not cron.

**Web app (`customer_agent_app.py`, Flask).** Routes actually defined in the file:

- `GET /` and `GET /inventory` — the dashboard page (`templates/inventory.html`)
- `GET /health`
- `GET /api/inventory/latest` and `GET /api/inventory/history` — paginated JSON with `page`, `per_page`, search and sort
- `POST /chat` and `POST /api/chat` — customer question answering
- `POST /automation/pilot-mode/run`
- `POST /automation/refresh-products-seo`
- `POST /automation/post-social-update`

**Automation package (`automation/`).**

- `customer_agent.py` — filters and ranks products by keyword and by price limits parsed out of the question, then asks the model to answer grounded in those rows. It has a `_local_response` fallback path that answers from the CSV without calling the model.
- `seo.py` — generates per-product SEO title/description rows into a CSV.
- `marketing.py` — generates marketing copy and an image, and posts to a Facebook Page via `https://graph.facebook.com/v21.0/<page_id>/photos`. Gated by `DRY_RUN_SOCIAL`, which defaults to true.
- `openai_client.py` — a hand-rolled HTTP client against `https://api.openai.com/v1/responses` (text) and `/v1/images/generations` with `gpt-image-1`. The official `openai` SDK is not used.
- `pilot_mode.py` — runs marketing + SEO in one pass and writes `data/pilot_mode_last_run.json`.

**Persistence (`persistence.py`).** SQLAlchemy Core tables `inventory_latest` (keyed on product) and `inventory_history` (append-only), so the worker and web service can share a database instead of a local CSV.

## Tech stack

From `requirements.txt`, all pinned:

- `Flask==3.0.3`, `gunicorn==23.0.0`
- `beautifulsoup4==4.12.3`, `requests==2.32.3`
- `SQLAlchemy==2.0.38`, `psycopg[binary]==3.2.6`
- `python-dotenv==1.0.1`

Plus: Python 3.11-slim base image (`Dockerfile`), Render Blueprint deploy (`render.yaml`, two Docker services — a web service and a worker), vanilla HTML/CSS/JS frontend (`templates/inventory.html`, `static/inventory.css`, `static/inventory.js`), OpenAI Responses and Images APIs over raw HTTP, Facebook Graph API v21.0.

## Setup and running

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill it in
```

One-off scrape:

```bash
python3 inventory_worker.py
```

Daily scrape (default 00:05 UTC), optionally with the AI automations:

```bash
python3 inventory_worker.py --daily
python3 inventory_worker.py --daily --run-pilot-mode
```

Web API and dashboard:

```bash
APP_MODE=chat ./start.sh            # gunicorn customer_agent_app:app
python3 customer_agent_app.py       # Flask dev server, PORT defaults to 10000
```

Pilot-mode automations once:

```bash
APP_MODE=pilot_once ./start.sh      # or: python3 -m automation.pilot_mode
```

Environment variables. `.env` is loaded by `python-dotenv` (override the path with `DOTENV_PATH`).

| Variable | Required | Notes |
| --- | --- | --- |
| `OPENAI_API_KEY` | Yes for any AI path | `OpenAIClient` raises `ValueError` if empty |
| `OPENAI_MODEL` | No | defaults to `gpt-4.1-mini` |
| `INVENTORY_DB_URL` | No, but needed for shared state | falls back to `DATABASE_URL`, then to `sqlite:///data/inventory.db` |
| `AUTOMATION_API_TOKEN` | Yes to protect the automation endpoints | sent as `Authorization: Bearer <token>` |
| `ALLOW_UI_AUTOMATION_WITHOUT_TOKEN` | — | **defaults to `true`**, which disables that auth check |
| `ASSISTANT_CONTEXT_CACHE_TTL_SECONDS` | No | default 300 |
| `INVENTORY_CSV`, `MARKETING_OUTPUT_DIR`, `SEO_OUTPUT_CSV` | No | output paths |
| `DRY_RUN_SOCIAL` | No | defaults to `true`; set false to actually post |
| `FACEBOOK_PAGE_ID`, `FACEBOOK_ACCESS_TOKEN` | Only for real posting | |
| `APP_MODE`, `PORT`, `WEB_CONCURRENCY` | No | read by `start.sh` |

Render deploy: create a Blueprint from `render.yaml`, then set `OPENAI_API_KEY`, `INVENTORY_DB_URL` and `AUTOMATION_API_TOKEN` as secrets on both services (they are declared `sync: false`). The web service health check is `/health`.

No migrations are needed — `persistence.init_db()` calls `metadata.create_all()`.

## Status

Working prototype, built as a job-application demo. One commit, dated 2026-03-06. The repository still contains the application cover letter (`cover lettter`) and a working-notes file (`how to go about it`).

What is implemented and looks complete: the scraper and its CSV/DB persistence, the paginated inventory API and dashboard, the chat endpoint with a non-AI fallback, the SEO and marketing generators, the Facebook posting path, the Docker/Render deployment wiring, and the daily scheduler.

Caveats:

- `ALLOW_UI_AUTOMATION_WITHOUT_TOKEN` defaults to `true`, so on a default deployment `/automation/*` is reachable without a token. Those endpoints spend OpenAI credits and, with `DRY_RUN_SOCIAL=false`, post publicly to Facebook.
- The scraper depends on MiningCave's current WooCommerce markup (`div.product-item-info`, `nav.woocommerce-pagination`). Any layout change breaks extraction silently apart from log noise.
- `miningcave.com` is a third-party site; check its terms before running this against it at scale.
- No tests, no CI, no linting.
- TODO: verify — nothing here was executed. The scrape counts quoted in the cover letter (685 products, 25 pages, 630 out of stock) are the author's claim from a run whose CSV is not in the repository, and were not reproduced.

## Licence

**Proprietary software — all rights reserved.** Copyright © 2026 Joel Harold Onyango.

This repository is not open source. The full terms are in [LICENSE](LICENSE); in
summary, you may not copy, redistribute, modify, sublicense, publish, re-host or
commercially exploit this software, in whole or in part, without the prior
written permission of the copyright holder. Access to this repository does not
grant any licence beyond reading it.

Previous versions of this repository were published under an open-source licence.
That change is not retroactive: copies obtained under the earlier licence remain
governed by its terms. Everything from this commit onward is covered by
[LICENSE](LICENSE).
