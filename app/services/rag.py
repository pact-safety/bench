"""Postgres-native RAG for MIRA's knowledge base (Phase 0 scaffold).

Why this exists
---------------
MIRA's value is research taste, not retrieval — but the taste has to be
grounded in the safety-eval canon (MIRA spec §8), so it needs a retrieval
layer. Per the spec we keep everything in the existing Supabase Postgres
with `pgvector` rather than bolting on a separate vector store: hybrid
search (dense cosine + sparse `ts_rank`/BM25) fused with Reciprocal Rank
Fusion, then a cross-encoder rerank to the final top-k.

What's real in Phase 0 vs. later
---------------------------------
This is the scaffold (spec §9 Phase 0): the *shapes* and the pure logic
are here; the parts that need a live KB, an embedding vendor, or a GPU are
honest stubs that land in Phase 1–2.

  - `hybrid_search()` — present with its real signature, but short-circuits
    to `[]` while the `kb_chunks` table is empty. The dense + sparse + RRF
    pipeline (commented inline) wires up in Phase 1 once `scripts/seed_kb.py`
    has loaded the 13 P1 papers.
  - `rerank()` — returns its input unchanged (trimmed to `k_final`), exactly
    as the spec specifies for Phase 0. The `bge-reranker-v2-m3` cross-encoder
    (self-hosted on Modal) lands in Phase 2.
  - `embed()` — stub; Voyage `voyage-3-large` (1536-dim, fits the
    `vector(1536)` column in migration `004_mira.sql`) lands in Phase 1.
  - `rrf()` — implemented for real. It's pure and deterministic, so there's
    no reason to defer it, and having it tested early de-risks Phase 1.

Async to match `llm_provider.py` and the eventual streaming agent loop; see
that module's docstring for why this subsystem diverges from the otherwise-
synchronous services. Note the data layer (`app/db.py`) is synchronous
psycopg — the Phase 1 implementation of `hybrid_search` will bridge the sync
query into this async surface (e.g. via a thread executor), not pretend the
driver is async.
"""

from __future__ import annotations

from dataclasses import dataclass


# Dimensionality of the `kb_chunks.embedding` column in migration
# `004_mira.sql`. voyage-3-large and text-embedding-3-large both emit 1536.
EMBED_DIM = 1536


@dataclass
class RetrievedChunk:
    """One retrieved KB chunk, the unit `mira.py` embeds as a `[cite:doc_id]`
    block. `score` carries whichever score produced this row (cosine,
    ts_rank, fused, or rerank) depending on the pipeline stage."""

    id: str
    document_id: str
    content: str
    section_path: str | None
    score: float
    # Human-readable document title; None on pipelines that never
    # joined kb_documents. Prompts prefer it over the bare doc id.
    title: str | None = None


async def embed(text: str) -> list[float]:
    """Embed text to a 1536-dim vector. Stub until Phase 1 (spec §9).

    Phase 1 wires Voyage `voyage-3-large` here (primary); a self-hosted
    `bge-large-en-v1.5` is the vendor-free alternative (spec §11). Kept
    behind one function so the embedding backend is hot-swappable without
    touching `hybrid_search`.
    """
    raise NotImplementedError("embed() lands in MIRA Phase 1 (spec §9).")


def rrf(
    dense: list[RetrievedChunk],
    sparse: list[RetrievedChunk],
    k: int = 60,
) -> list[RetrievedChunk]:
    """Reciprocal Rank Fusion of two ranked candidate lists.

    Each input list is assumed already ordered best-first. An item's fused
    score is the sum over the lists it appears in of `1 / (k + rank)`, with
    `rank` 0-indexed. `k=60` is the conventional RRF constant — large enough
    that the gap between rank 1 and rank 2 doesn't dominate, so a chunk that
    ranks middling in *both* lists can beat one that ranks first in only one.

    Returns a single list sorted by fused score, descending. Dedupe is by
    `id`; the first-seen `RetrievedChunk` object is kept as the carrier (its
    `.score` field is overwritten with the fused score so downstream stages
    read one consistent number).
    """
    fused: dict[str, float] = {}
    carrier: dict[str, RetrievedChunk] = {}
    for ranked in (dense, sparse):
        for rank, chunk in enumerate(ranked):
            fused[chunk.id] = fused.get(chunk.id, 0.0) + 1.0 / (k + rank)
            carrier.setdefault(chunk.id, chunk)

    out: list[RetrievedChunk] = []
    # Sort by fused score desc; tie-break on id so the order is deterministic
    # (matters for the `hybrid_search` determinism unit test in spec §10).
    for cid in sorted(fused, key=lambda c: (-fused[c], c)):
        chunk = carrier[cid]
        chunk.score = fused[cid]
        out.append(chunk)
    return out


async def rerank(
    query: str,
    candidates: list[RetrievedChunk],
    k_final: int = 5,
) -> list[RetrievedChunk]:
    """Cross-encoder rerank of fused candidates down to `k_final`.

    Phase 0: identity — returns the candidates unchanged, trimmed to
    `k_final` (spec §9). Phase 2 swaps in `bge-reranker-v2-m3` (self-hosted;
    Cohere Rerank as paid fallback) which re-scores `(query, chunk)` pairs.
    Keeping the trim here means callers already get a top-k contract that
    won't change shape when the real reranker lands.
    """
    return candidates[:k_final]


_kb_repo = None  # KbRepository, injected by app.main (same pattern as llm_keys)


def set_kb_repo(repo) -> None:
    global _kb_repo
    _kb_repo = repo


async def hybrid_search(
    query: str,
    k_candidates: int = 50,
    k_final: int = 5,
    *,
    user_id: str | None = None,
) -> list[RetrievedChunk]:
    """Retrieve the top `k_final` KB chunks for a query.

    Phase 1a (v2.1 KB slice): the SPARSE side is live — `ts_rank` over
    the user's vault + the shared canon, via KbRepository. The dense
    side stays off until `embed()` gets its vendor (`VOYAGE_API_KEY`);
    when it lands, its ranked list joins the existing `rrf()` fusion —
    the plumbing below already goes through rrf so that arrival is a
    diff to ONE block, not a rewrite.

    `user_id` scopes retrieval: None (background/canon contexts) sees
    only shared-canon rows; a real uid sees canon + their own vault.
    A caller that gets no chunks should reason first-principles and
    skip the `[cite:...]` blocks — correct behavior on an empty KB.

    The repository query is synchronous psycopg; bridged off the event
    loop per the module docstring.
    """
    if _kb_repo is None or not (query or "").strip():
        return []
    import anyio

    def _sparse() -> list[RetrievedChunk]:
        hits = _kb_repo.sparse_search(user_id, query, k=k_candidates)
        return [
            RetrievedChunk(
                id=h.chunk_id,
                document_id=h.document_id,
                content=h.content,
                section_path=h.section_path,
                score=h.score,
                title=h.document_title,
            )
            for h in hits
        ]

    try:
        sparse = await anyio.to_thread.run_sync(_sparse)
    except Exception:  # noqa: BLE001 — retrieval must never kill a turn
        return []
    fused = rrf([], sparse)[:k_candidates]
    return await rerank(query, fused, k_final)
