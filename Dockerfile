# Multi-stage Dockerfile for Li's Bench.
#
# Stage 1 (builder): install all deps including the `ml` extra
# (torch + numpy). The reference solutions need torch at import time
# to run problem test cases at submission. Keep this stage fat; we'll
# discard everything but the venv when we copy into the runtime stage.
#
# Stage 2 (runtime): slim Python with the prebuilt venv. No build
# tools, no pip cache, no test files. ~200MB image with torch.
#
# Why not a single stage: torch pulls in ~600MB of build deps that
# never ship to runtime. Multi-stage cuts the prod image by half.

# ---------- Islands builder (FRONTEND-1a) -----------------------------------
# Node exists ONLY in this stage: `npm run build` emits the hashed
# island assets (static/dist/) that the runtime stage copies in. No
# Node in the runtime image — the Jinja asset() helper just reads the
# build manifest.

FROM node:22-slim AS islands

WORKDIR /islands
COPY package.json package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY vite.config.ts tsconfig.json ./
COPY static/src/ ./static/src/
RUN npm run build

# ---------- Builder ---------------------------------------------------------

FROM python:3.11-slim AS builder

# Build deps for psycopg + pyjwt cryptography. Trim aggressively;
# only what the wheels can't bring themselves.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy just the dep manifest first so a code-only change doesn't
# invalidate the layer cache for the dependency install.
COPY pyproject.toml README.md ./
COPY app/__init__.py app/__init__.py
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -e ".[ml]"

# ---------- Runtime --------------------------------------------------------

FROM python:3.11-slim AS runtime

# psycopg's pure-Python path needs libpq.so.5 at runtime. The
# `psycopg[binary]` wheel ships its own libpq but a system one is a
# safe fallback for any C extension we add later.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Bring in the prebuilt venv from the builder stage.
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Source code last so the layer cache is warm during dev iterations.
COPY app/ ./app/
COPY templates/ ./templates/
COPY static/ ./static/
# Built island assets (hashed filenames + .vite/manifest.json). Comes
# after the static/ COPY so the local static/dist (gitignored, usually
# absent in CI checkouts anyway) can never shadow the stage's output.
COPY --from=islands /islands/static/dist/ ./static/dist/
COPY content/ ./content/
COPY migrations_pg/ ./migrations_pg/
# scripts/ ships operator-runs-on-Fly maintenance tools (backfill, etc.).
# These aren't imported by the app at runtime, but they need to be on
# disk for `fly ssh console -C "python /app/scripts/..."` to work.
# Without this COPY, the operator hits ENOENT when trying to e.g. run
# the chat_outcomes backfill that the cutover PR shipped (issue
# surfaced post-PR #253).
COPY scripts/ ./scripts/
# config.toml is read at import time by app/config.py (load_config()
# opens REPO_ROOT / "config.toml"). Without it the app crashes on boot
# with FileNotFoundError before uvicorn finishes binding.
COPY config.toml pyproject.toml README.md ./

# Non-root user. App listens on 8765 inside the container; Fly's
# proxy maps 443 → 8765.
RUN useradd --create-home --shell /bin/bash app \
    && chown -R app:app /app
USER app

EXPOSE 8765

# Uvicorn directly; no gunicorn or nginx wrapper. Single worker
# matches the in-process cache assumption (cache lives per process).
# `--proxy-headers` so Fly's load balancer X-Forwarded-* headers get
# respected for `request.url` reconstruction.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8765", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*"]
