#!/usr/bin/env bash
set -euo pipefail

# First-run setup for self-hosting Li's Bench.
# Run from the repo root: ./scripts/setup.sh

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# ── 1. Check Python 3.11+ ────────────────────────────────────────────────────

PYTHON=""
for cmd in python3.11 python3.12 python3.13 python3; do
  if command -v "$cmd" &>/dev/null; then
    ver=$("$cmd" -c 'import sys; print(sys.version_info[:2] >= (3,11))')
    if [ "$ver" = "True" ]; then
      PYTHON="$cmd"
      break
    fi
  fi
done

if [ -z "$PYTHON" ]; then
  echo "ERROR: Python 3.11+ is required. Install it and re-run."
  exit 1
fi

echo "✓ Python: $($PYTHON --version)"

# ── 2. Check DATABASE_URL (or that postgres is reachable) ────────────────────

if [ -z "${DATABASE_URL:-}" ] && ! command -v psql &>/dev/null; then
  echo ""
  echo "WARNING: DATABASE_URL is not set and psql is not on PATH."
  echo "  Set DATABASE_URL in your .env (see .env.example) before running the app."
  echo "  A Supabase project or local Postgres both work."
  echo ""
fi

# ── 3. Copy .env.example → .env if missing ──────────────────────────────────

if [ ! -f .env ]; then
  cp .env.example .env
  echo "✓ Created .env from .env.example — fill in DATABASE_URL and any API keys you need."
else
  echo "✓ .env already exists, skipping copy."
fi

# ── 4. Install dependencies (uv preferred, pip fallback) ────────────────────

if command -v uv &>/dev/null; then
  echo "✓ Using uv"
  uv sync
else
  echo "uv not found — falling back to pip"
  if [ ! -d .venv ]; then
    "$PYTHON" -m venv .venv
  fi
  # shellcheck disable=SC1091
  source .venv/bin/activate
  pip install -e ".[ml]" --quiet
fi

# ── 5. Run database migrations ───────────────────────────────────────────────

if [ -n "${DATABASE_URL:-}" ]; then
  echo "Running migrations..."
  if command -v uv &>/dev/null; then
    uv run python scripts/apply_migrations.py
  else
    source .venv/bin/activate
    python scripts/apply_migrations.py
  fi
  echo "✓ Migrations applied."
else
  echo "Skipping migrations (DATABASE_URL not set)."
  echo "  Run 'python scripts/apply_migrations.py' after setting DATABASE_URL."
fi

# ── Done ─────────────────────────────────────────────────────────────────────

echo ""
echo "Setup complete."
echo ""
echo "To start the app:"
if command -v uv &>/dev/null; then
  echo "  DATABASE_URL=<your-url> LIS_LOCAL_MODE=1 uv run uvicorn app.main:app --port 8765"
else
  echo "  source .venv/bin/activate"
  echo "  DATABASE_URL=<your-url> LIS_LOCAL_MODE=1 uvicorn app.main:app --port 8765"
fi
echo ""
echo "  → http://127.0.0.1:8765/"
echo ""
echo "LIS_LOCAL_MODE=1 bypasses GitHub OAuth — any local Postgres works."
echo "See SETUP.md for full environment setup (Supabase, auth, LLM keys)."
