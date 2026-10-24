"""One-shot migration: derive `domain_tags` for every content item by
title-keyword match against the existing `tag_aliases._ALIASES` map.

Run from the repo root:

    python scripts/migrate_content_domain_tags.py [--dry-run]

For each `content/{readings,videos,podcasts,exercises}/*.md` file:

  1. Parse the YAML frontmatter
  2. Reverse-lookup each axis in `axes` to find candidate sub-topics
     (e.g., axis `transformer_internals` → {attention, self-attention,
     softmax, layer_norm, kv_cache, ...})
  3. Keep only the candidates whose lowercase string appears in the
     item's title or first 200 chars of body
  4. Write the result back into the frontmatter as a new `domain_tags`
     field, inserted right after the existing `axes` line

Idempotent — re-running over a file that already has `domain_tags`
will replace it with the recomputed set. Use --dry-run to see the
proposed changes without writing.

This script will be DELETED after the migration lands and is verified
(see `docs/architecture/tag-vocabulary.md`). Kept in git history as the
audit trail for what got tagged with what.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Iterable


# Reverse-lookup table: axis ID → set of plausible sub-topic phrases
# that should appear as `domain_tags` when found in a content item's
# title or body. Derived by inverting the alias map in
# `app/services/tag_aliases.py` and adding a few obvious sub-topics
# that the alias map missed.
REVERSE_ALIAS: dict[str, set[str]] = {
    "transformer_internals": {
        "attention", "self-attention", "self attention",
        "kv-cache", "kv cache", "transformer",
        "softmax", "layer_norm", "layer norm", "layernorm",
        "normalization", "embedding", "positional", "rope",
        "multi-head", "head", "scaled dot-product",
        # Mask-related synonyms — causal-mask + attention are commonly
        # discussed together; users filtering on "attention" expect to
        # see mask-focused exercises and vice versa.
        "mask", "causal mask", "masking",
    },
    "training_mechanics": {
        "training", "optimizer", "adam", "sgd", "fine-tuning", "fine tuning",
        "loss", "gradient", "backprop", "learning rate", "schedule",
        "regularization", "dropout", "batch", "epoch",
    },
    "eval_design": {
        "eval", "evals", "evaluation", "benchmark", "metric",
        "scoring", "harness", "rubric",
    },
    "sampling_decoding": {
        "sampling", "decoding", "temperature", "top-k", "top-p",
        "nucleus", "beam", "greedy",
    },
    "numerical_stability": {
        "numerical stability", "overflow", "underflow", "stable",
        "epsilon", "logsumexp",
    },
    "tokenization": {
        "tokenization", "tokenizer", "bpe", "byte-pair",
        "subword", "tokens",
    },
    "data_pipeline": {
        "data pipeline", "dataset", "loader", "preprocessing",
        "augmentation", "pipeline",
    },
    "algorithmic": {
        "algorithm", "algorithms", "complexity", "data structure",
        "recursion", "dynamic programming",
    },
    "rust_fluency": {
        "rust", "ownership", "lifetimes", "borrow", "trait",
        "generics", "iterator", "cargo",
    },
    "ai_safety_fundamentals": {
        "alignment", "safety", "ai safety", "rlhf", "sycophancy",
        "scalable oversight", "constitutional", "harmlessness",
    },
    "mechanistic_interpretability": {
        "interpretability", "mech-interp", "mechanistic interpretability",
        "circuits", "sae", "saes", "sparse autoencoder",
        "activation patching", "induction head", "probing",
    },
    "ai_governance_strategy": {
        "governance", "policy", "agi strategy", "responsible scaling",
        "rsp", "deployment policy", "race dynamics",
    },
    "debugging": {
        "debugging", "debug", "trace", "diagnostics",
    },
}


def parse_frontmatter(text: str) -> tuple[dict, str, str, str]:
    """Return (parsed_fm, fm_raw, body, original_full_text).

    `fm_raw` is the raw YAML between the --- delimiters (preserving
    formatting); `parsed_fm` is the YAML.load result (lossy on
    formatting but accurate on values).

    Returns (None, None, None, text) if no frontmatter is found."""
    import yaml
    if not text.startswith("---\n"):
        return None, None, None, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return None, None, None, text
    fm_raw = text[4:end]
    body = text[end + 5:]
    parsed = yaml.safe_load(fm_raw) or {}
    return parsed, fm_raw, body, text


def derive_domain_tags(title: str, body: str, axes: list[str]) -> list[str]:
    """Match sub-topics from REVERSE_ALIAS against the item's title +
    first 800 chars of body. Lowercase, case-insensitive substring
    match. Result is sorted + deduplicated.

    Body window is intentionally wide (800 chars) — short content
    blurbs are common in this repo and a narrower window misses
    obvious sub-topics that appear in the second paragraph."""
    haystack = (title + " " + body[:800]).lower()
    matched: set[str] = set()
    for axis in axes:
        for subtopic in REVERSE_ALIAS.get(axis, set()):
            if subtopic.lower() in haystack:
                matched.add(subtopic)
    # Normalize a few common variants down to one canonical form.
    if "self attention" in matched:
        matched.discard("self attention")
        matched.add("self-attention")
    if "layernorm" in matched or "layer norm" in matched:
        matched.discard("layernorm")
        matched.discard("layer norm")
        matched.add("layer_norm")
    if "kv cache" in matched:
        matched.discard("kv cache")
        matched.add("kv-cache")
    if "fine tuning" in matched:
        matched.discard("fine tuning")
        matched.add("fine-tuning")
    if "byte-pair" in matched:
        matched.discard("byte-pair")
        matched.add("bpe")
    # Collapse near-duplicate verb/noun forms to the noun form.
    if "debug" in matched and "debugging" in matched:
        matched.discard("debug")
    if "eval" in matched and "evals" in matched:
        matched.discard("eval")
    if "algorithm" in matched and "algorithms" in matched:
        matched.discard("algorithm")
    if "self-attention" in matched and "attention" in matched:
        # keep both — they're meaningfully distinct sub-topics
        pass
    return sorted(matched)


def insert_domain_tags(fm_raw: str, domain_tags: list[str]) -> str:
    """Insert (or replace) a `domain_tags: [...]` line in the raw
    frontmatter. Insert position: immediately after the existing
    `axes:` line, preserving everything else verbatim."""
    # If domain_tags already present, replace it.
    domain_line = f"domain_tags: [{', '.join(domain_tags)}]"
    new_lines: list[str] = []
    seen_axes = False
    replaced = False
    for line in fm_raw.split("\n"):
        if line.startswith("domain_tags:"):
            new_lines.append(domain_line)
            replaced = True
            continue
        new_lines.append(line)
        if line.startswith("axes:") and not seen_axes and not replaced:
            new_lines.append(domain_line)
            seen_axes = True
    if not seen_axes and not replaced:
        # No `axes:` line found and no existing domain_tags. Append at
        # end. (This shouldn't happen for content items, but defensive.)
        new_lines.append(domain_line)
    return "\n".join(new_lines)


_CONTENT_KIND_DIRS = ("readings", "videos", "podcasts", "exercises")


def iter_content_files(content_root: Path) -> Iterable[Path]:
    for kind in _CONTENT_KIND_DIRS:
        d = content_root / kind
        if not d.exists():
            continue
        for f in sorted(d.glob("*.md")):
            yield f


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Print proposed changes; don't write files")
    args = ap.parse_args(argv)

    repo_root = Path(__file__).resolve().parent.parent
    content_root = repo_root / "content"

    total = 0
    written = 0
    unchanged = 0
    no_tags = 0
    for f in iter_content_files(content_root):
        total += 1
        text = f.read_text()
        parsed, fm_raw, body, _ = parse_frontmatter(text)
        if parsed is None:
            print(f"  skip (no frontmatter): {f.relative_to(repo_root)}")
            continue
        axes = parsed.get("axes") or []
        title = parsed.get("title") or ""
        domain_tags = derive_domain_tags(title, body, axes)
        existing = parsed.get("domain_tags") or []
        if sorted(existing) == domain_tags:
            unchanged += 1
            continue
        if not domain_tags:
            no_tags += 1
        new_fm = insert_domain_tags(fm_raw, domain_tags)
        new_text = f"---\n{new_fm}\n---\n{body}"
        rel = f.relative_to(repo_root)
        if args.dry_run:
            print(f"  {rel}: axes={axes} title={title!r}")
            print(f"      → domain_tags={domain_tags}")
        else:
            f.write_text(new_text)
            print(f"  wrote: {rel} → domain_tags={domain_tags}")
            written += 1

    print()
    print(f"Processed: {total}  written: {written}  unchanged: {unchanged}  empty: {no_tags}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
