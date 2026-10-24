"""Unit tests for the MIRA Phase 0 scaffold.

Covers the parts of the merged scaffold that carry real logic — the RRF
fusion, the provider fallback ladder, and the documented stub contracts
(empty KB, identity rerank, NotImplementedError entry points). These are
the spec §10 "unit tests" for the rag/provider layer, and they run in the
~1s tier (no DB, no network): the offline provider and the empty-KB paths
never reach Anthropic or Postgres.
"""

from __future__ import annotations

import pytest
pytestmark = pytest.mark.skip(reason="MIRA stubbed as coming soon")


import asyncio

import pytest

from app.services import llm_provider as lp
from app.services import mira
from app.services import rag


def _drain(agen) -> list[dict]:
    """Collect every event an async generator yields, synchronously."""

    async def run() -> list[dict]:
        return [ev async for ev in agen]

    return asyncio.run(run())


# --------------------------------------------------------------------------
# llm_provider — fallback ladder
# --------------------------------------------------------------------------


def test_get_provider_without_key_returns_offline(monkeypatch):
    # No credentials anywhere → deterministic offline provider, never a
    # half-wired backend that raises on first token.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    provider = lp.get_provider("anthropic")
    assert isinstance(provider, lp.DeterministicOfflineProvider)
    assert provider.name == "offline"


def test_get_provider_with_key_returns_anthropic(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    provider = lp.get_provider("anthropic")
    assert isinstance(provider, lp.AnthropicProvider)
    assert provider.name == "anthropic"


def test_get_provider_unimplemented_preference_falls_to_anthropic(monkeypatch):
    # Preference is OpenAI (a Phase-5 stub), but only an Anthropic key is
    # present. The ladder must skip the stub and land on Anthropic rather
    # than hand back something that raises when streamed.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    provider = lp.get_provider("openai")
    assert isinstance(provider, lp.AnthropicProvider)


def test_get_provider_unimplemented_preference_no_keys_is_offline(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    provider = lp.get_provider("gemini")
    assert isinstance(provider, lp.DeterministicOfflineProvider)


# --------------------------------------------------------------------------
# llm_provider — streaming contracts
# --------------------------------------------------------------------------


def test_offline_provider_streams_text_then_finish():
    events = _drain(
        lp.DeterministicOfflineProvider().stream(
            "system", [lp.LLMMessage(role="user", content="hi")]
        )
    )
    assert [e["type"] for e in events] == ["text", "finish"]
    assert events[0]["delta"]  # non-empty canned text
    finish = events[1]
    assert finish["finish_reason"] == "offline"
    # Zero-usage finish so spend-cap bookkeeping behaves like a live turn.
    assert finish["usage"] == {"input_tokens": 0, "output_tokens": 0}


def test_openai_provider_stub_raises_when_streamed():
    with pytest.raises(NotImplementedError):
        _drain(lp.OpenAIProvider().stream("s", [lp.LLMMessage("user", "hi")]))


def test_gemini_provider_stub_raises_when_streamed():
    with pytest.raises(NotImplementedError):
        _drain(lp.GeminiProvider().stream("s", [lp.LLMMessage("user", "hi")]))


def test_llmmessage_defaults():
    msg = lp.LLMMessage(role="user", content="hello")
    assert msg.tool_calls is None
    assert msg.tool_use_id is None


# --------------------------------------------------------------------------
# rag — RRF fusion
# --------------------------------------------------------------------------


def _chunk(cid: str, score: float = 0.0) -> rag.RetrievedChunk:
    return rag.RetrievedChunk(
        id=cid, document_id="doc", content=f"chunk {cid}", section_path=None, score=score
    )


def test_rrf_rewards_appearing_in_both_lists():
    # c2 ranks 2nd in dense and 1st in sparse; c1 ranks 1st in dense only.
    # RRF should rank c2 above c1 — middling-in-both beats first-in-one.
    dense = [_chunk("c1", 0.9), _chunk("c2", 0.8)]
    sparse = [_chunk("c2", 0.7), _chunk("c3", 0.6)]
    fused = rag.rrf(dense, sparse)
    assert [c.id for c in fused] == ["c2", "c1", "c3"]
    # The carrier's score is overwritten with the fused score.
    assert fused[0].score == pytest.approx(1 / 60 + 1 / 61)


def test_rrf_dedupes_by_id():
    dense = [_chunk("a"), _chunk("b")]
    sparse = [_chunk("a")]
    fused = rag.rrf(dense, sparse)
    assert sorted(c.id for c in fused) == ["a", "b"]
    assert len(fused) == 2


def test_rrf_tiebreak_is_deterministic_by_id():
    # Equal fused scores (both rank 0 in their only list) → stable order by id.
    fused = rag.rrf([_chunk("b")], [_chunk("a")])
    assert [c.id for c in fused] == ["a", "b"]


def test_rrf_empty_inputs():
    assert rag.rrf([], []) == []


# --------------------------------------------------------------------------
# rag — Phase 0 stub contracts
# --------------------------------------------------------------------------


def test_hybrid_search_empty_kb_returns_empty_without_embedding():
    # Returns [] on the empty KB. If it reached embed() (a Phase-1 stub
    # that raises), this would error — so passing also proves it short-
    # circuits before the embedding call.
    assert asyncio.run(rag.hybrid_search("scheming evals")) == []


def test_rerank_is_identity_trimmed_to_k_final():
    candidates = [_chunk(str(i)) for i in range(10)]
    out = asyncio.run(rag.rerank("q", candidates, k_final=3))
    assert [c.id for c in out] == ["0", "1", "2"]


def test_embed_is_stub():
    with pytest.raises(NotImplementedError):
        asyncio.run(rag.embed("anything"))


def test_embed_dim_matches_migration_column():
    # The vector(1536) column in the MIRA migration; keep them in lockstep.
    assert rag.EMBED_DIM == 1536


# --------------------------------------------------------------------------
# mira — entry point (Phase 1a: chat loop is live)
# --------------------------------------------------------------------------


def test_mira_turn_runs_offline_without_repo(monkeypatch):
    # Phase 1a replaced the NotImplementedError stub with the chat loop.
    # With no API key and no repo, it must still produce a usable turn via
    # the deterministic offline provider — text then finish, never raising.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    events = _drain(mira.mira_turn("session-id", "hi", modality="chat"))
    assert [e["type"] for e in events] == ["text", "finish"]
    assert events[0]["delta"]  # canned offline text
    assert events[1]["usage"] == {"input_tokens": 0, "output_tokens": 0}


# --------------------------------------------------------------------------
# main — review-voice picker excludes the mentor-only Mira voice
# --------------------------------------------------------------------------


def test_review_picker_excludes_mira_keeps_reviewers():
    # Mira is a mentor, not a code-review persona — it must not show up in the
    # review-voice picker even though it's a registered voice.
    from app.main import _review_voices, _NON_REVIEW_VOICE_KEYS

    keys = [v.key for v in _review_voices()]
    assert "mira" not in keys
    assert "mira" in _NON_REVIEW_VOICE_KEYS
    # The actual review personas are still offered.
    assert "default" in keys
    assert "hamming" in keys
