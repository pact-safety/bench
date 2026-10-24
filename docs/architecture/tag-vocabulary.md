# Tag vocabulary

How problems and content items are tagged, how the library filter matches across both, and what changed when we unified the vocabularies (LIS-284 / GH #2 / migration 005).

## The schema

Every problem and every content item carries some combination of these tag fields:

### Problems (`content/problems/*.md` frontmatter → `problems` table)

| Field | Vocabulary | Purpose |
|---|---|---|
| `domain_tags` | Sub-topic phrases (free-form within an axis) — `attention`, `softmax`, `layer_norm`, `ownership` | What's the topic? Used by library filter. |
| `competency_tags` | Assessment axis IDs — `transformer_internals`, `training_mechanics`, `rust_fluency` | What skill axis does this build? Drives the skill-rating pentagon and JD matching. |
| `structural_tags` | Code-shape descriptors — `tensor_manipulation`, `numerical_stability`, `recursion` | What kind of code is this? Used for surface filtering ("show me the numerical-stability problems"). |
| `jd_signal_tags` | JD-matching tags — `interpretability`, `mechanistic_interp`, `transformer` | What JD signals does this match? Used by the readiness scoring against an active JD. |

### Content items (`content/{readings,videos,podcasts,exercises}/*.md` frontmatter → `content_items` table)

| Field | Vocabulary | Purpose |
|---|---|---|
| `axes` | Assessment axis IDs — same controlled vocabulary as `competency_tags` on problems | What skill axis does this build? Drives the daily-content picker and the JD-axis match. |
| `domain_tags` | Sub-topic phrases (free-form within an axis) — same vocabulary as problem `domain_tags` | What's the topic? Used by library filter. **Added in migration 005**, populated by `scripts/migrate_content_domain_tags.py`. |

## The library filter, in one sentence

`?tag=X` matches any item where `X` (case-insensitive) appears in:
- for problems: `domain_tags ∪ competency_tags ∪ structural_tags`
- for content items: `domain_tags ∪ axes`

Direct equality. No alias bridge.

## What changed (LIS-284 unification)

### Before (PR #30 era)

- Content items carried only `axes` — coarse, axis-only vocabulary.
- Problems carried four tag fields including fine-grained `domain_tags`.
- A click on `?tag=attention` (a problem domain_tag) wouldn't match the Vaswani reading (which was only tagged `axes: [transformer_internals]`) without help.
- `app/services/tag_aliases.py` provided that help — a curated synonym map. `expand("attention")` returned `{"attention", "transformer_internals"}`, and the filter matched on the expanded set.

### Problem with the bridge

The bridge worked but it broadened matches too aggressively. `expand("transformer_internals")` returned every sub-topic of that axis. So `?tag=transformer_internals` matched any item carrying *any* of: `attention`, `self-attention`, `softmax`, `layer_norm`, `kv-cache`, `transformer`. Reversed, `?tag=attention` matched any content axed `transformer_internals` — even readings purely about layer normalization, which the user didn't ask for.

The bridge traded precision for recall. For a small library that was fine; for a growing one it's noise.

### After (migration 005)

- Content items now carry their own `domain_tags`, populated by title-keyword matching against the old alias map (see `scripts/migrate_content_domain_tags.py` for the audit trail of what got tagged with what).
- `app/services/tag_aliases.py` is deleted; the library filter matches `domain_tags ∪ axes` directly.
- Precision improves: `?tag=attention` only returns items that actually carry `attention` as a sub-topic tag.
- Recall stays acceptable: items with axis-only tagging still match axis-tag clicks (e.g., a generically-axed `transformer_internals` reading still appears for `?tag=transformer_internals`).

## The canonical vocabulary

There's no formal closed set; the vocabulary is the union of what's actually in use across the corpus. Two intended scopes:

### Top-level axes (closed set, defined by `app/services/assessment.py:AXES`)

These are the 13 canonical skill axes used everywhere — assessment, JDs, content axes, problem competency tags. New axes go through a deliberate design pass (recent example: PR #28 added `ai_safety_fundamentals`, `mechanistic_interpretability`, `ai_governance_strategy`).

Adding an axis is a moderate change — it touches:
- `app/services/assessment.py` (the `AXES` tuple)
- `app/services/jds.py` (`_AXIS_KEYWORDS` keyword fallback)
- The Claude JD-parsing system prompt's axis-disambiguation guidance
- Existing user `users.settings_json` rows (axis ratings; new axes default to 0)

### Sub-topic `domain_tags` (open set, free-form within an axis)

Authors pick sub-tags that name the concrete topic. Examples in current use:

| Axis | Sub-topics in current corpus |
|---|---|
| `transformer_internals` | `attention`, `self-attention`, `kv-cache`, `softmax`, `layer_norm`, `normalization`, `transformer`, `embedding`, `mask`, `causal mask`, `multi-head`, `head`, `scaled dot-product` |
| `training_mechanics` | `training`, `optimizer`, `loss`, `gradient`, `batch`, `learning rate`, `fine-tuning` |
| `eval_design` | `eval`, `evals`, `evaluation`, `benchmark`, `scoring` |
| `numerical_stability` | `overflow`, `stable` |
| `tokenization` | `tokenization`, `tokenizer`, `bpe`, `subword`, `tokens` |
| `data_pipeline` | `dataset`, `pipeline`, `data pipeline` |
| `algorithmic` | `algorithm`, `algorithms` |
| `rust_fluency` | `rust`, `ownership`, `lifetimes`, `borrow`, `iterator`, `trait`, `generics` |
| `mechanistic_interpretability` | `interpretability`, `circuits`, `sae`, `saes`, `sparse autoencoder` |
| `ai_safety_fundamentals` | `alignment`, `safety`, `ai safety`, `rlhf`, `sycophancy` |
| `ai_governance_strategy` | `governance`, `policy`, `agi strategy`, `responsible scaling` |
| `debugging` | `debug`, `debugging`, `trace`, `diagnostics` |

The list is what's in the corpus today, not a closed taxonomy. Adding a new sub-topic is just adding it to a frontmatter `domain_tags` field on the relevant content item or problem — no schema or code change needed.

## Adding a new content item

When you author a new reading / video / podcast / exercise in `content/`:

1. Pick the right `axes` from the canonical assessment AXES list. Usually one, occasionally two for cross-axis content.
2. Pick `domain_tags` — concrete sub-topics that describe what the item is *about*. Use existing sub-topics where applicable (look at the table above + the corpus); coin new ones only when none fit.
3. Save. The next app boot loads the file via `app/services/content.py:parse_content_file`. The library filter picks it up automatically.

You can verify the tagging surfaces correctly by visiting `/library?tag=<your-new-tag>` and seeing the item appear.

## Migration audit trail

The one-shot migration that populated `domain_tags` for the existing 32 content items is at `scripts/migrate_content_domain_tags.py`. It uses title + first-800-char body keyword match against a reverse-lookup of the old alias map. The script is kept in git history (not deleted) as the audit trail — if anyone questions why a specific content item got specific tags, they can re-run the script and see.

## See also

- [Infrastructure & platforms](../development/infrastructure.md)
- [Services architecture](services.md)
- [`app/services/assessment.py:AXES`](https://github.com/pact-safety/bench/blob/main/app/services/assessment.py) — canonical axis list
- `scripts/migrate_content_domain_tags.py` — one-shot migration that ran on 2026-05-16
