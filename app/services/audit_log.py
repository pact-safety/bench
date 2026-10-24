"""Custody ledger for LLM calls — the shared `audit_log.py` that
`mira._audit_turn` has been waiting on (see the Brain<->MIRA boundary
doc referenced there).

One JSON line per call, appended to `DEFAULT_PATH` (overridable via
`LIS_AUDIT_LOG_PATH`, e.g. for tests or for pointing at a mounted
volume). The disk file is ephemeral on Fly, so every record is also
emitted as a single structured `logging` line (logger name
`audit_log`) so the platform's log drain captures it regardless.

`payload` must already be a summary (e.g. `{"assistant_chars": N)`) —
callers never pass raw message content here; this module doesn't
inspect or enforce that, it just writes what it's given.

Like `spend_cap.py`, this is best-effort: a custody line must never
break a user turn, so any failure logs a warning and returns rather
than raising.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

_log = logging.getLogger("audit_log")

DEFAULT_PATH = Path(os.environ.get("LIS_AUDIT_LOG_PATH", "data/audit_log.jsonl"))


def record(
    *,
    capability: str,
    model: str,
    payload: dict,
    redaction_applied: list,
    dropped: list,
    usage: dict | None,
    path: Path | None = None,
) -> None:
    """Append one custody line for an LLM call. Never raises."""
    target = path or DEFAULT_PATH
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "capability": capability,
        "model": model,
        "payload": payload,
        "redaction_applied": redaction_applied,
        "dropped": dropped,
        "usage": _usage_summary(usage),
    }

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:  # never let a disk issue break a user turn
        _log.warning("audit_log write failed: %s", e)

    try:
        _log.info(
            "ts=%s capability=%s model=%s payload=%s redaction_applied=%s dropped=%s usage=%s",
            entry["ts"],
            capability,
            model,
            entry["payload"],
            redaction_applied,
            dropped,
            entry["usage"],
        )
    except Exception as e:
        _log.warning("audit_log structured log failed: %s", e)


def _usage_summary(usage: dict | None) -> dict | None:
    if not usage:
        return None
    return {
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
    }
