# Deploying miningcave

A Flask customer-agent page (`customer_agent_app:app`) over an OpenAI-backed
product assistant, plus an inventory/marketing/SEO batch worker in the same
codebase. `start.sh` picks which one runs, from `APP_MODE`.

Public hostname: **mining.harolditdata.uk** → `127.0.0.1:5765`
Overall verdict: **NEEDS WORK** — section 1 is not optional.

---

## 1. Blocker: the automation endpoints are open by default

`customer_agent_app.py`:

```python
configured = os.getenv("AUTOMATION_API_TOKEN", "").strip()
allow_without_token = os.getenv("ALLOW_UI_AUTOMATION_WITHOUT_TOKEN", "true")...
```

The default is **true**. With no `AUTOMATION_API_TOKEN` set, the automation
routes answer to anyone who can reach the port. On a public hostname that means
anyone on the internet can drive the pilot-mode runs, the marketing generation
and the SEO writes — every one of which spends your OpenAI quota, and some of
which post to a Facebook page.

Set both, always:

```bash
AUTOMATION_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
ALLOW_UI_AUTOMATION_WITHOUT_TOKEN=false
```

Setting only the token is not enough — leaving the allow flag at its default
keeps the bypass alive.

## 2. Environment variables

Nothing here is baked into the image; `.dockerignore` now excludes `.env`.

| Variable | Required | Notes |
|---|---|---|
| `OPENAI_API_KEY` | yes | the chat page is useless without it |
| `OPENAI_MODEL` | no | defaults to `gpt-4.1-mini` |
| `AUTOMATION_API_TOKEN` | yes | see section 1 |
| `ALLOW_UI_AUTOMATION_WITHOUT_TOKEN` | yes | set to `false` |
| `FACEBOOK_PAGE_ID` / `FACEBOOK_ACCESS_TOKEN` | only for social posting | leave unset to keep it inert |
| `DRY_RUN_SOCIAL` | no | defaults to `true` in the image. Leave it there until you have watched a dry run's output. |
| `INVENTORY_DB_URL` or `DATABASE_URL` | no | defaults to `sqlite:///data/inventory.db` |
| `APP_MODE` | no | `chat` in the image; set `worker` to run the batch job instead |

There is a committed `.env.example` — use it as the key list, not as values.

> Not build-verified. Docker is not installed on this machine, so this image has
> never been built here.

## 3. Build and run

```bash
docker build -t miningcave:latest .

docker volume create miningcave-data

docker run -d --name miningcave \
  --restart unless-stopped \
  -p 127.0.0.1:5765:5765 \
  -e OPENAI_API_KEY="$OPENAI_API_KEY" \
  -e AUTOMATION_API_TOKEN="$AUTOMATION_API_TOKEN" \
  -e ALLOW_UI_AUTOMATION_WITHOUT_TOKEN=false \
  -e DRY_RUN_SOCIAL=true \
  -v miningcave-data:/app/data \
  --memory 512m --cpus 0.5 \
  miningcave:latest
```

The worker is the same image with a different mode, and it should NOT be
published on a port:

```bash
docker run --rm \
  -e APP_MODE=pilot_once \
  -e OPENAI_API_KEY="$OPENAI_API_KEY" \
  -v miningcave-data:/app/data \
  miningcave:latest
```

## 4. Persistence

`/app/data` holds `inventory.db`, the generated marketing assets and
`seo_product_updates.csv`. Without the volume, every batch run starts from
nothing and the web page's product cache is empty on each restart.

## 5. Cloudflare tunnel

```yaml
  - hostname: mining.harolditdata.uk
    service: http://127.0.0.1:5765
```

Because of section 1, put Cloudflare Access in front of this hostname even after
you set the token — an OpenAI-spending endpoint is a bill, not just a bug.

## 6. Health

`GET /` under HTTP 500 counts as alive. The probe deliberately does not touch
the OpenAI client: a provider outage should not restart the container.
