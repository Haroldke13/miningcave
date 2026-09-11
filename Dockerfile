# syntax=docker/dockerfile:1
###############################################################################
# miningcave — Flask customer-agent front end over an OpenAI-backed product
# assistant, plus an inventory/marketing/SEO automation worker
#
# Build:  docker build -t miningcave:latest .
# Run:    see DEPLOY.md
#
# This REPLACES the 14-line Dockerfile that was here before: that one ran as
# root, pinned no patch version, had no EXPOSE and no HEALTHCHECK, and its
# `COPY . .` happily copied the committed `.env` into the image because
# .dockerignore did not exclude it.
#
# BEFORE YOU PUBLISH: the automation endpoints are UNAUTHENTICATED by default.
# ALLOW_UI_AUTOMATION_WITHOUT_TOKEN defaults to "true" in
# customer_agent_app.py. DEPLOY.md section 1.
###############################################################################

FROM python:3.11.9-slim-bookworm AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt ./
# psycopg[binary] ships wheels, so no libpq-dev and no compiler is needed here.
# If you ever swap it for plain `psycopg`, this stage starts needing both.
RUN python -m pip install --upgrade pip setuptools wheel \
 && python -m pip install -r requirements.txt

FROM python:3.11.9-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PORT=5765 \
    APP_MODE=chat \
    DRY_RUN_SOCIAL=true

COPY --from=builder /opt/venv /opt/venv

RUN useradd --system --create-home --uid 10009 --shell /usr/sbin/nologin appuser

WORKDIR /app
COPY --chown=root:root . /app

# persistence.py defaults to sqlite:///data/inventory.db, resolved relative to
# the working directory, and automation/config.py puts the marketing and SEO
# outputs under data/ too. The directory does not exist in git — create it and
# make it the one writable place in the tree.
RUN mkdir -p /app/data && chown appuser:appuser /app/data
VOLUME ["/app/data"]

USER appuser

EXPOSE 5765

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import http.client,sys; c=http.client.HTTPConnection('127.0.0.1',5765,timeout=4); c.request('GET','/'); sys.exit(0 if c.getresponse().status<500 else 1)"

# start.sh honours APP_MODE: "chat" execs gunicorn on $PORT, anything else runs
# the batch worker. APP_MODE=chat is set above so the web container always
# serves HTTP; override it to run the worker from the same image.
# The product cache is per-process, so extra workers just multiply the memory
# and the cache misses. Two, with threads for the OpenAI round trips.
ENV WEB_CONCURRENCY=2
CMD ["/app/start.sh"]
