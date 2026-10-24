"""Tests for app.env — the .env loader.

Covers the shell-export-wins precedence and the empty-value handling
that bit us earlier in the migration."""

from __future__ import annotations

import os
from pathlib import Path

from app import env


def test_load_dotenv_sets_keys_when_absent(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("FOO=bar\nBAZ=qux\n")
    monkeypatch.delenv("FOO", raising=False)
    monkeypatch.delenv("BAZ", raising=False)
    loaded = env.load_dotenv(path=f)
    assert loaded == {"FOO": "bar", "BAZ": "qux"}
    assert os.environ["FOO"] == "bar"
    assert os.environ["BAZ"] == "qux"


def test_load_dotenv_respects_existing_env(tmp_path, monkeypatch):
    """Shell-exported value wins over the file. This is the bug that
    bit us with the leaked Anthropic key in ~/.bashrc."""
    f = tmp_path / ".env"
    f.write_text("FOO=from-file\n")
    monkeypatch.setenv("FOO", "from-shell")
    loaded = env.load_dotenv(path=f)
    assert "FOO" not in loaded
    assert os.environ["FOO"] == "from-shell"


def test_load_dotenv_treats_empty_as_unset(tmp_path, monkeypatch):
    """Blank `KEY=` lines must NOT clobber a shell-set value to empty.
    The hint ladder broke earlier because empty .env line was masking
    the real key — this regression check makes sure it stays fixed."""
    f = tmp_path / ".env"
    f.write_text("FOO=\n")
    monkeypatch.delenv("FOO", raising=False)
    loaded = env.load_dotenv(path=f)
    assert "FOO" not in loaded
    assert "FOO" not in os.environ


def test_load_dotenv_strips_quotes(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text('FOO="quoted value"\nBAR=\'single\'\n')
    monkeypatch.delenv("FOO", raising=False)
    monkeypatch.delenv("BAR", raising=False)
    env.load_dotenv(path=f)
    assert os.environ["FOO"] == "quoted value"
    assert os.environ["BAR"] == "single"


def test_load_dotenv_skips_comments_and_blank_lines(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("# top comment\n\nFOO=bar\n# another\n\n")
    monkeypatch.delenv("FOO", raising=False)
    loaded = env.load_dotenv(path=f)
    assert loaded == {"FOO": "bar"}


def test_load_dotenv_returns_empty_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("FOO", raising=False)
    loaded = env.load_dotenv(path=tmp_path / "does-not-exist.env")
    assert loaded == {}
