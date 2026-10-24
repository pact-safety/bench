"""Unit tests for app.services.audit_log — the custody ledger that
lights up mira's dormant `_audit_turn` hook (BEN-144).

Covers: valid JSONL on write, usage=None handling, never-raises on an
unwritable path, the structured logging line, and that
`mira._audit_turn` actually produces a record now that this module
exists."""

from __future__ import annotations

import json
import logging
import os

from app.services import audit_log


def test_record_writes_valid_jsonl(tmp_path):
    target = tmp_path / "audit_log.jsonl"
    audit_log.record(
        capability="mira",
        model="claude-x",
        payload={"assistant_chars": 42},
        redaction_applied=[],
        dropped=[],
        usage={"input_tokens": 10, "output_tokens": 20},
        path=target,
    )
    lines = target.read_text().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["capability"] == "mira"
    assert entry["model"] == "claude-x"
    assert entry["payload"] == {"assistant_chars": 42}
    assert entry["usage"] == {"input_tokens": 10, "output_tokens": 20}
    assert "ts" in entry


def test_record_handles_usage_none(tmp_path):
    target = tmp_path / "audit_log.jsonl"
    audit_log.record(
        capability="mira",
        model="claude-x",
        payload={"assistant_chars": 1},
        redaction_applied=[],
        dropped=[],
        usage=None,
        path=target,
    )
    entry = json.loads(target.read_text().splitlines()[0])
    assert entry["usage"] is None


def test_record_appends(tmp_path):
    target = tmp_path / "audit_log.jsonl"
    for _ in range(3):
        audit_log.record(
            capability="mira",
            model="m",
            payload={},
            redaction_applied=[],
            dropped=[],
            usage=None,
            path=target,
        )
    assert len(target.read_text().splitlines()) == 3


def test_record_never_raises_on_unwritable_path(tmp_path):
    # Point at a path whose parent is actually a file, so mkdir/open fail.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    bad_target = blocker / "audit_log.jsonl"
    audit_log.record(
        capability="mira",
        model="m",
        payload={},
        redaction_applied=[],
        dropped=[],
        usage=None,
        path=bad_target,
    )  # must not raise


def test_record_emits_structured_log_line(tmp_path, caplog):
    target = tmp_path / "audit_log.jsonl"
    with caplog.at_level(logging.INFO, logger="audit_log"):
        audit_log.record(
            capability="mira",
            model="claude-x",
            payload={"assistant_chars": 7},
            redaction_applied=[],
            dropped=[],
            usage={"input_tokens": 1, "output_tokens": 2},
            path=target,
        )
    records = [r for r in caplog.records if r.name == "audit_log"]
    assert len(records) == 1
    message = records[0].getMessage()
    assert "capability=mira" in message
    assert "model=claude-x" in message


def test_mira_audit_turn_now_produces_a_record(tmp_path, monkeypatch):
    """Integration-ish: import mira with the audit hook's import guard
    now satisfied, and confirm _audit_turn writes through to
    audit_log.record given the mira call-site contract."""
    monkeypatch.setenv("LIS_NO_DB", "1")
    monkeypatch.setenv("LIS_SKIP_STARTUP_LOAD", "1")
    target = tmp_path / "audit_log.jsonl"
    monkeypatch.setenv("LIS_AUDIT_LOG_PATH", str(target))

    # audit_log.DEFAULT_PATH is read at import time from the env var, so
    # reload it under the patched env before importing mira.
    import importlib

    importlib.reload(audit_log)
    assert audit_log.DEFAULT_PATH == target

    from app.services import mira

    mira._audit_turn(model="m", usage={"input_tokens": 1, "output_tokens": 2}, content_len=5)

    lines = target.read_text().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["capability"] == "mira"
    assert entry["model"] == "m"
    assert entry["payload"] == {"assistant_chars": 5}
    assert entry["usage"] == {"input_tokens": 1, "output_tokens": 2}
