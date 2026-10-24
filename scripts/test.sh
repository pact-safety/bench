#!/usr/bin/env bash
# Canonical test runner. Designed to be cheap enough to run on every
# meaningful code change.
#
# Default (no args): Tier-1 unit tests only. Fast (<1s), no DB, no
# network. This is what the agent runs to verify a change end-to-end
# without bothering you.
#
# With `--integration`: also runs Tier-2 integration tests, which
# need DATABASE_URL set and will burn one real Anthropic call per
# LLM-touching path. Slower (~10s) but exercises real wiring.
#
# Usage:
#   scripts/test.sh                # unit tests
#   scripts/test.sh --integration  # unit + integration
#   scripts/test.sh -v             # verbose
#   scripts/test.sh tests/unit/test_hints.py     # one file
set -euo pipefail

cd "$(dirname "$0")/.."

PYTEST=.venv/bin/pytest
if [[ ! -x "$PYTEST" ]]; then
    echo "ERROR: pytest not installed. Run:" >&2
    echo "  .venv/bin/pip install -e '.[dev]'" >&2
    exit 1
fi

args=()
include_integration=0
for a in "$@"; do
    if [[ "$a" == "--integration" ]]; then
        include_integration=1
    else
        args+=("$a")
    fi
done

if (( include_integration )); then
    # Run unit + integration. Integration tests are gated by the
    # `integration` pytest marker.
    "$PYTEST" tests/ ${args[@]+"${args[@]}"}
else
    # Default: unit only. Skip the integration marker so we don't try
    # to talk to Postgres / Anthropic for real.
    "$PYTEST" tests/unit/ -m "not integration" ${args[@]+"${args[@]}"}
fi
