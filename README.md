# MiningCave Inventory Scraper

Scrapes `https://miningcave.com/shop-page/` product cards (`div.product-item-info`), including:
- Product name and URL
- Price text + numeric value
- Stock status text (`Out of Stock` / other action labels)
- Shipping text, description, image, product ID

The scraper follows WooCommerce pagination and processes all pages.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run Once

```bash
python3 inventory_worker.py
```

Outputs:
- `data/miningcave_inventory_latest.csv` (overwritten each run)
- `data/miningcave_inventory_history.csv` (append-only history)

Run scrape + AI pilot mode automation (marketing + SEO):

```bash
python3 inventory_worker.py --run-pilot-mode
```

## Run Daily (Built-in Scheduler)

Runs once per day at 00:05 UTC by default:

```bash
python3 inventory_worker.py --daily
```

Custom UTC time:

```bash
python3 inventory_worker.py --daily --daily-hour-utc 1 --daily-minute-utc 30
```

Daily scrape + AI pilot mode:

```bash
python3 inventory_worker.py --daily --run-pilot-mode
```

## AI Customer Agent API (Flask)

Start API:

```bash
APP_MODE=chat ./start.sh
```

Endpoints:
- `GET /health`
- `POST /chat` with JSON body: `{"message":"I need an in-stock bitcoin miner under $4000"}`
- `POST /automation/pilot-mode/run` with optional JSON body: `{"max_seo_products":50}`
- `GET /inventory` paginated frontend tables for latest/history CSV
- `GET /api/inventory/latest?page=1&per_page=25`
- `GET /api/inventory/history?page=1&per_page=25`
- `POST /automation/refresh-products-seo` (auth required)

Customer demo URL:
- Open `/inventory` to show both paginated inventory and AI chat assistant in one screen.

## Environment Variables

Copy `.env.example` and set your secrets:

```bash
cp .env.example .env
```

`.env` is auto-loaded via `python-dotenv` (optional override: `DOTENV_PATH=/path/to/.env`).

Required:
- `OPENAI_API_KEY`
- `INVENTORY_DB_URL` (shared database used by both web and worker; recommended Render Postgres)
- `AUTOMATION_API_TOKEN` (protects `/automation/pilot-mode/run`)
- `ALLOW_UI_AUTOMATION_WITHOUT_TOKEN` (`true` allows dashboard refresh buttons without manual token prompt)
- `ASSISTANT_CONTEXT_CACHE_TTL_SECONDS` (default `300`; cache refresh interval for merged CSV assistant context)

Optional:
- `FACEBOOK_PAGE_ID`
- `FACEBOOK_ACCESS_TOKEN`
- `DRY_RUN_SOCIAL` (`true` by default, recommended until validated)

## Production Deployment (Render)

This repo includes `render.yaml` for one-click Blueprint deployment:

1. Push this project to GitHub.
2. In Render: `New +` -> `Blueprint` -> select this repo.
3. Set secret env var:
- `OPENAI_API_KEY` (required for chat and AI automations)
- `INVENTORY_DB_URL` (point both services to the same DB)
- `AUTOMATION_API_TOKEN` (required to call automation trigger endpoint)
4. Deploy services:
- `miningcave-demo-web` (`APP_MODE=chat`) exposes public URL.
- `miningcave-demo-worker` (`APP_MODE=worker`) runs daily scrape + AI automations.
5. After deploy, share:
- `https://<your-web-service>.onrender.com/inventory`

Production notes:
- Chat service runs with Gunicorn (not Flask dev server).
- Health check endpoint: `/health`.
- Shared persistence uses DB tables (`inventory_latest`, `inventory_history`) populated by worker and read by web.
- Automation endpoint auth:
  `Authorization: Bearer <AUTOMATION_API_TOKEN>`
- Frontend button on `/inventory`: **Refresh Products + SEO CSV** calls `/automation/refresh-products-seo`.

## Alternative: Cron (recommended for servers)

Example: run every day at 03:00 UTC

```cron
0 3 * * * cd /home/harold-coder/Desktop/miningcave && /usr/bin/python3 inventory_worker.py >> scraper.log 2>&1
```
