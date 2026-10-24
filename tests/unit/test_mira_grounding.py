"""v2.1 slice 2 — Mira turns grounded in KB retrieval.

Pins the citation contract: chunks present → the system prompt carries
the RETRIEVED CONTEXT blocks with [cite:<doc_id>] handles and the
don't-invent instruction; no chunks (or retrieval blowing up) → the
original honest no-substrate footer, verbatim enough that the model
still refuses to fabricate citations.
"""

from __future__ import annotations

import pytest
pytestmark = pytest.mark.skip(reason="MIRA stubbed as coming soon")


import asyncio
from unittest.mock import MagicMock

import pytest

from app.services import mira as mira_service
from app.services import rag


async def _collect(gen):
    return [ev async for ev in gen]


@pytest.fixture()
def captured_system(monkeypatch):
    captured = {}

    class FakeProvider:
        name = "fake"

        async def stream(self, system, messages, max_tokens):
            captured["system"] = system
            yield {"type": "finish", "usage": None}

    monkeypatch.setattr(
        mira_service.llm_provider, "get_provider", lambda name: FakeProvider()
    )
    monkeypatch.setattr(mira_service.spend_cap, "over_cap_for", lambda *a: False)
    return captured


def _chunk(doc_id="d-42", title="KV caches", content="the cache grows linearly"):
    return rag.RetrievedChunk(
        id="c1", document_id=doc_id, content=content,
        section_path="Memory", score=1.0, title=title,
    )


def test_turn_with_chunks_carries_citation_contract(captured_system, monkeypatch):
    async def _fake_search(query, k_candidates=50, k_final=5, *, user_id=None):
        assert user_id == "uid-9"
        assert query == "why does my kv cache blow up"
        return [_chunk()]

    monkeypatch.setattr(mira_service.rag, "hybrid_search", _fake_search)
    asyncio.run(_collect(mira_service.mira_turn(
        "sess", "why does my kv cache blow up", user_id="uid-9", repo=None,
    )))
    system = captured_system["system"]
    assert "RETRIEVED CONTEXT" in system
    assert "[cite:d-42] KV caches › Memory" in system
    assert "the cache grows linearly" in system
    assert "never invent" in system
    assert "No knowledge-base retrieval" not in system


def test_turn_without_chunks_keeps_honest_footer(captured_system, monkeypatch):
    async def _empty(query, k_candidates=50, k_final=5, *, user_id=None):
        return []

    monkeypatch.setattr(mira_service.rag, "hybrid_search", _empty)
    asyncio.run(_collect(mira_service.mira_turn("sess", "hi", user_id="u", repo=None)))
    system = captured_system["system"]
    assert "No knowledge-base retrieval" in system
    assert "RETRIEVED CONTEXT" not in system


def test_retrieval_failure_degrades_to_honest_footer(captured_system, monkeypatch):
    async def _boom(query, k_candidates=50, k_final=5, *, user_id=None):
        raise RuntimeError("kb down")

    monkeypatch.setattr(mira_service.rag, "hybrid_search", _boom)
    asyncio.run(_collect(mira_service.mira_turn("sess", "hi", user_id="u", repo=None)))
    assert "No knowledge-base retrieval" in captured_system["system"]


def test_chunk_content_is_capped_in_prompt(captured_system, monkeypatch):
    async def _big(query, k_candidates=50, k_final=5, *, user_id=None):
        return [_chunk(content="x" * 5000)]

    monkeypatch.setattr(mira_service.rag, "hybrid_search", _big)
    asyncio.run(_collect(mira_service.mira_turn("sess", "hi", user_id="u", repo=None)))
    # 1200-char cap per block keeps five chunks bounded in the budget.
    assert "x" * 1200 in captured_system["system"]
    assert "x" * 1301 not in captured_system["system"]
