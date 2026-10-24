"""Minimal .env loader — no python-dotenv dependency.

Parses `KEY=VALUE` lines from the repo-root `.env.local` (preferred)
and `.env` (fallback) and merges them into `os.environ`. Existing
environment variables take precedence (so an `export` in `~/.bashrc`
still wins over the file).

Convention mirrors Next.js / Vite:
    .env.example  — template, committed, never has real values
    .env.local    — real values for this machine, gitignored
    .env          — optional shared values, also gitignored

Called once at app import time from `app/main.py`. Safe to call again;
re-reading the files is cheap.

Format:
    # comments allowed
    KEY=value        # trailing comments not parsed — keep them on their own line
    KEY="quoted"     # outer quotes stripped
    KEY=             # empty value treated as "not set" — won't mask shell defaults

The point isn't to replace dotenv — it's to make `uvicorn app.main:app`,
`pytest`, and `scripts/mock_user.py` pick up a local secret without
anyone having to `source` anything, while keeping the real key out
of the repo's tracked surface.
"""

from __future__ import annotations

import os
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent


def _parse_one(path: Path, loaded: dict[str, str]) -> None:
    """Merge KEY=VALUE pairs from `path` into os.environ. Updates
    `loaded` with the keys we actually wrote — handy for debugging
    which file a given var came from."""
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if not key or value == "":
            continue
        # Don't clobber an already-set env var. Order:
        #   shell `export` > .env.local > .env
        if key in os.environ:
            continue
        os.environ[key] = value
        loaded[key] = value


def load_dotenv(path: Path | None = None) -> dict[str, str]:
    """Load env files into os.environ. By default reads `.env.local`
    then `.env` from the repo root. Pass `path` to load a single file
    (useful for tests).

    Returns the dict of keys that *were* loaded (i.e. weren't already
    in the environment).
    """
    loaded: dict[str, str] = {}
    if path is not None:
        _parse_one(path, loaded)
        return loaded
    # .env.local first so a real local secret beats a shared placeholder
    # that might live in .env. shell-`export` still wins over both
    # because _parse_one checks os.environ before writing.
    _parse_one(_REPO_ROOT / ".env.local", loaded)
    _parse_one(_REPO_ROOT / ".env", loaded)
    return loaded
