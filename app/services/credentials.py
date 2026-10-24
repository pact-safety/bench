"""Credential extraction + skill-gap analysis.

Two paths:

- Claude (preferred): sends extracted CV/transcript text to Claude
  Sonnet with the 10-axis definitions. Used when ANTHROPIC_API_KEY is
  set in the environment.
- Keyword fallback: deterministic substring matching against a
  hand-curated keyword set per axis. Always available; useful for
  testing without an API key and as a fallback if the API call fails.

Both return the same shape:
    {
      "axis_scores": {axis: 0..1},
      "rationale":   {axis: "human-readable why"},
      "summary":     "one-paragraph overall read",
      "method":      "claude" | "keyword_fallback",
      "model_used":  str | None,
    }

Privacy: extracted text is sent to Anthropic's API only for the
analysis call. We do not retain the prompt server-side beyond the
duration of the request; only the structured response and the
extracted text itself (in credential_files) persist.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from . import assessment as assess_svc


# --- Text extraction --------------------------------------------------------

def extract_text(filename: str, raw_bytes: bytes) -> str:
    """Return plain text from a file. Currently handles PDF and any text
    type. DOCX / images deferred — returns empty string for unsupported
    formats."""
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return _extract_pdf(raw_bytes)
    if lower.endswith((".txt", ".md", ".tex")):
        return raw_bytes.decode("utf-8", errors="replace")
    # Best-effort fallback: try UTF-8 decode (some "PDFs" are actually
    # plain text mislabeled).
    try:
        candidate = raw_bytes.decode("utf-8")
        if candidate.isprintable() or "\n" in candidate:
            return candidate
    except UnicodeDecodeError:
        pass
    return ""


def _extract_pdf(raw_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader
        import io
        reader = PdfReader(io.BytesIO(raw_bytes))
        return "\n\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception as e:
        return f"[pdf extraction failed: {e}]"


# --- Keyword-based fallback analyzer ---------------------------------------

# Each axis maps to a list of substring patterns. Score is proportional
# to the count of distinct matches, capped at 1.0.
_AXIS_KEYWORDS: dict[str, tuple[str, ...]] = {
    "transformer_internals": (
        "transformer", "attention", "multi-head", "self-attention", "kv cache",
        "rotary", "rope", "layernorm", "rmsnorm", "encoder-decoder",
    ),
    "training_mechanics": (
        "training loop", "gradient", "optimizer", "adamw", "sgd",
        "checkpoint", "fine-tun", "pretrain", "batch norm",
        "gradient accumulation", "mixed precision",
    ),
    "sampling_decoding": (
        "sampling", "top-k", "top-p", "nucleus", "beam search", "temperature",
        "logit", "decoding strategy",
    ),
    "eval_design": (
        "evaluation", "benchmark", "eval suite", "regression test",
        "metric", "rouge", "bleu", "calibration", "sycophancy", "robustness",
        "interpretability", "red team",
    ),
    "numerical_stability": (
        "numerical", "fp16", "bf16", "overflow", "underflow",
        "log-sum-exp", "mixed precision",
    ),
    "debugging": (
        "debug", "regression", "root cause", "production incident",
        "stack trace", "profiling", "profiler",
    ),
    "tokenization": (
        "tokeniz", "bpe", "sentencepiece", "wordpiece", "vocab",
    ),
    "data_pipeline": (
        "data pipeline", "preprocess", "etl", "spark", "airflow",
        "prefect", "ingestion", "dataloader", "shard",
    ),
    "algorithmic": (
        "algorithm", "leetcode", "competitive programming", "data structure",
        "graph", "dynamic programming", "complexity",
    ),
    "rust_fluency": (
        "rust", "borrow checker", "ownership", "cargo", "lifetimes",
        "tokio", " trait", "rust-lang",
    ),
}


def analyze_keyword(text: str) -> dict[str, Any]:
    """Deterministic substring analyzer. Used when no API key is set
    or when the LLM call fails."""
    lower = (text or "").lower()
    scores: dict[str, float] = {}
    rationale: dict[str, str] = {}
    for axis, keys in _AXIS_KEYWORDS.items():
        matched = [k for k in keys if k in lower]
        if matched:
            # Normalize: 1 keyword -> 0.25, 2 -> 0.50, 3 -> 0.75, 4+ -> 1.0
            scores[axis] = min(1.0, len(matched) * 0.25)
            rationale[axis] = "matched: " + ", ".join(matched[:5])
        else:
            scores[axis] = 0.0
            rationale[axis] = "no direct keyword evidence"
    # Pull a one-line summary derived from where the scores landed.
    strong = sorted([a for a, v in scores.items() if v >= 0.5], key=lambda a: -scores[a])
    weak = [a for a, v in scores.items() if v < 0.25]
    summary_parts = []
    if strong:
        summary_parts.append(
            "Credentials suggest strength in " +
            ", ".join(assess_svc.AXIS_LABELS.get(a, a) for a in strong[:3])
            + "."
        )
    if weak:
        summary_parts.append(
            "Less explicit evidence for " +
            ", ".join(assess_svc.AXIS_LABELS.get(a, a) for a in weak[:3])
            + " — may simply be unspoken."
        )
    return {
        "axis_scores": scores,
        "rationale": rationale,
        "summary": " ".join(summary_parts) or "No strong signals detected.",
        # Keyword fallback has no signal for iac classification — let
        # the UI suppress the block rather than show fabricated mix.
        "iac_profile": None,
        "iac_evidence_md": None,
        "method": "keyword_fallback",
        "model_used": None,
    }


# --- Claude analyzer --------------------------------------------------------

# Default to a recent Sonnet; the caller can override via env.
_DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")

_SYSTEM_PROMPT = """You are a credentials-to-competency evaluator for
AI research-engineering roles. You read CVs, transcripts, certs, and
related documents and infer the candidate's likely competency on a
fixed set of 10 axes. Score each axis on [0, 1]:
  0.00 — no evidence
  0.25 — peripheral exposure
  0.50 — direct exposure / coursework
  0.75 — applied/production experience
  1.00 — deep specialization

Output JSON ONLY, with this shape exactly:
{
  "axis_scores": {axis_key: float, ...},
  "rationale": {axis_key: "one sentence why", ...},
  "summary": "two to three sentence overall read",
  "iac_profile": {
    "iterator": 0.0..1.0,
    "amplifier": 0.0..1.0,
    "connector": 0.0..1.0
  },
  "iac_evidence_md": "short markdown citing CV evidence for each iac score"
}

iac_profile taxonomy (from "Talent Needs of Technical AI Safety
Teams"). Score what the candidate has demonstrably *done*, not what
they could in principle do. The three roles are not mutually
exclusive; most candidates have some mix:
- iterator: pushes existing research agendas forward. Strong at
  executing experiments, debugging models, shipping incremental
  wins. CV signals: PhD/research projects iterating on a paper line,
  "ran N experiments," "improved baseline by X."
- amplifier: multiplies others' research output. Strong at tooling,
  infra, evals, internal codebases. CV signals: SWE/infra roles,
  open-source maintainer, eval framework authorship, internal
  platform work.
- connector: synthesizes across disciplines or people. Strong at
  setting new agendas, bridging fields, distillation. CV signals:
  cross-domain background (e.g. physics→ML), workshop/review work,
  writing (blog/distill/LessWrong posts), founding/leading projects.

The three iac_profile scores should sum to roughly 1.0 — they
represent strength mix, not independent traits. If the document is
silent, default to {0.4, 0.4, 0.2} (slight iterator/amplifier lean
for typical engineer CVs).

iac_evidence_md: 2-4 short bullets pointing to specific CV lines
that justify each non-trivial score. Keep under 300 characters.

Axes (use these exact keys):
- transformer_internals: attention, MHA, KV cache, layer normalization, the math of how transformers compute
- training_mechanics: training loops, optimizers, gradient accumulation, mixed precision, checkpointing
- sampling_decoding: top-k, top-p, beam search, temperature, length normalization
- eval_design: benchmark design, paired comparisons, robustness, sycophancy, interpretability evals
- numerical_stability: log-sum-exp, mixed precision pitfalls, biased vs. unbiased variance
- debugging: silent ML bugs, root-cause analysis under uncertainty
- tokenization: BPE, sentencepiece, wordpiece, vocab design
- data_pipeline: preprocessing, ETL, dataloader robustness, sharding
- algorithmic: classical CS algorithms and data structures, complexity reasoning
- rust_fluency: Rust ownership, borrow checker, idiomatic Rust patterns

Be calibrated. Most candidates score 0.0 on most axes; that is not a
failure of the candidate, it's the document not mentioning it. Score
only what the document evidences."""


def analyze_with_claude(text: str, user_id: str | None = None) -> dict[str, Any]:
    """Call Claude. Raises on API/JSON failure; caller falls back.

    `user_id` feeds the spend-cap shim. Cap-hit raises `RuntimeError`,
    handled the same as any other failure → keyword fallback."""
    from . import llm_keys, spend_cap

    if spend_cap.over_cap_for(user_id, "credentials_analyze"):
        raise RuntimeError("daily Anthropic cap reached — falling back to keyword analysis")
    client = llm_keys.client_for(user_id)
    truncated = text[:30000]  # cap input
    resp = client.messages.create(
        model=_DEFAULT_MODEL,
        max_tokens=2000,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": "Document text:\n\n" + truncated}],
    )
    spend_cap.record_usage_for(user_id, resp, service="credentials_analyze")
    body = "".join(b.text for b in resp.content if hasattr(b, "text"))
    # Extract JSON from the response (the model sometimes wraps in code fences).
    m = re.search(r"\{.*\}", body, re.DOTALL)
    if not m:
        raise ValueError("no JSON in Claude response")
    parsed = json.loads(m.group(0))
    scores = parsed.get("axis_scores", {})
    iac_profile = _coerce_iac_profile(parsed.get("iac_profile"))
    iac_evidence_md = str(parsed.get("iac_evidence_md", "")).strip() or None
    return {
        "axis_scores": {a: float(scores.get(a, 0.0)) for a in assess_svc.AXES},
        "rationale": parsed.get("rationale", {}),
        "summary": parsed.get("summary", ""),
        "iac_profile": iac_profile,
        "iac_evidence_md": iac_evidence_md,
        "method": "claude",
        "model_used": _DEFAULT_MODEL,
    }


# Iterator / Amplifier / Connector — mirrors the keys in services.jds.
# Kept inline rather than imported to keep these two parse pipelines
# from accidentally sharing state.
_IAC_KEYS: tuple[str, ...] = ("iterator", "amplifier", "connector")


def _coerce_iac_profile(raw: Any) -> dict[str, float] | None:
    """Same shape coercion as in services.jds — returns None when the
    raw payload has no recognizable iac keys, so callers can default."""
    if not isinstance(raw, dict):
        return None
    out: dict[str, float] = {}
    saw_any = False
    for k in _IAC_KEYS:
        try:
            v = float(raw.get(k, 0.0))
            saw_any = saw_any or (k in raw)
        except (TypeError, ValueError):
            v = 0.0
        out[k] = max(0.0, min(1.0, v))
    return out if saw_any else None


def analyze(text: str, user_id: str | None = None) -> dict[str, Any]:
    """Public entrypoint. Prefer Claude when API key is set; otherwise
    fall back to keyword matching. If the Claude call errors (including
    a spend-cap hit), also fall back."""
    if not (text or "").strip():
        return {
            "axis_scores": {a: 0.0 for a in assess_svc.AXES},
            "rationale": {a: "empty document" for a in assess_svc.AXES},
            "summary": "No extractable text in the uploaded document.",
            "iac_profile": None,
            "iac_evidence_md": None,
            "method": "keyword_fallback",
            "model_used": None,
        }
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return analyze_with_claude(text, user_id=user_id)
        except Exception as e:
            return {
                **analyze_keyword(text),
                "summary": f"Claude analysis failed ({e}); falling back to keyword matching. " + analyze_keyword(text)["summary"],
            }
    return analyze_keyword(text)


# --- Gap calculation --------------------------------------------------------

def compute_gap(credential_scores: dict[str, float], assessment_scores: dict[str, float]) -> dict[str, float]:
    """Per-axis gap = credentials - assessment. Positive means the
    credential suggests more capability than the user reported."""
    gap = {}
    for a in assess_svc.AXES:
        gap[a] = float(credential_scores.get(a, 0.0)) - float(assessment_scores.get(a, 0.0))
    return gap


def top_gaps(gap: dict[str, float], n: int = 3) -> list[str]:
    """Axes where the credential exceeds the assessment by the most —
    'you have the credential but rated yourself low; worth drilling.'"""
    items = [(a, v) for a, v in gap.items() if v > 0.05]
    items.sort(key=lambda x: -x[1])
    return [a for a, _ in items[:n]]
