# Services

Every service module under `app/services/` is single-purpose, pure-functional where possible, and includes a graceful offline fallback. Below is the contract surface for the LLM-flavored ones — what they take, what they return, what fails to.

## Pattern: LLM service + fallback

The shape that recurs across `review.py`, `hints.py`, `hamming.py`, `jds.py`, `external_capture.py`, `credentials.py`:

```python
def some_action(...) -> dict[str, Any]:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return fallback_shape  # deterministic, often process-focused
    try:
        return claude_path(...)  # the Sonnet/Haiku call
    except Exception:
        return fallback_shape    # never let an LLM error crash a route
```

Routes always call the public entry point and never branch on availability — that's the service's job.

## hints

`hints.get_hint(problem, phase, current_notes, code, count_so_far, prior_hints)`

Returns:

```python
{
  "tier": 1 | 2 | 3,
  "tier_label": "nudge" | "direction" | "scaffolding",
  "hint": "...",
  "method": "claude" | "fallback",
  "exhausted": False | True
}
```

The system prompt explicitly forbids tier-3 code expressions (the reference-solution disclosure is the escape hatch). `prior_hints` lets Claude avoid repeating itself across calls.

## review

`review.review_attempt(problem, attempt, voice_key="default")`

Returns:

```python
{
  "method": "claude" | "skipped",
  "model_used": "claude-sonnet-4-5" | None,
  "summary_md": "...",
  "per_phase": {phase: {"strength", "gap", "question"}, ...},
  "overall_score": float,
  "rubric_signals": dict | None,  # only for interview_mode
  "error_text": str | None,
  "voice_key": "default" | "hamming" | ...
}
```

The `voice_key` selects a persona from `app/services/voices.py` to prepend to the system prompt. Default voice's persona is empty so existing behavior is preserved.

## hamming (reflect)

`hamming.summarize_week(...)` → `WeekSummary`. Pure aggregation; no LLM.

`hamming.generate(week, days=7)` → dict with `summary`, `prompts[]`, `method`, `model_used`. Anti-sycophancy by design.

## readiness

Pure-functional, no LLM. `readiness.compute(user_scores, jd_axis_weights, axes)` → `Readiness` dataclass with:

- `readiness_pct` (0–100)
- `total_hours_needed`
- `gaps: list[AxisGap]` — sorted by hours descending
- `has_data: bool` — False if no scores or no JD weights
- `note: str | None` — explanation when has_data is False

`readiness.weeks_to_ready(total_hours, hours_per_week)` → float weeks.

`readiness.snapshot_for_template(readiness, axis_labels)` → dict the Jinja template consumes. Splits `gaps` into `needs_work` and `at_target`.

## voices

Registry of named-thinker personas. `voices.get(key)` always returns a `Voice` (never None — falls back to default). `voices.apply_persona(base_system_prompt, voice)` prepends the persona to a system prompt.

## jd parse

`jds.parse(source_text)` → dict matching `JD.axis_weights + signal_tags + summary + iac_profile + iac_evidence_md + method + model_used`.

`jds.fetch_from_url(url)` → optional dict `{title, org, source_text, url}` or `None` on fetch failure.

`jds.title_from_url(url)` → clean title derived from URL slug, used as fallback when fetch fails. `jds.is_url_title(s)` → bool detector for the `jd_title` Jinja filter.

`jds.interpret_iac_fit(jd_iac, user_iac)` → 1-line natural-language alignment interpretation (small Haiku call; cached on `jds.iac_fit_md`).

## external_capture

`external_capture.fetch_body(url)` → `{page_title, meta, source_text}` or `None`. Reuses the HTML-strip helper from `jds.py`.

`external_capture.parse_with_claude(url, fetched, valid_axes)` → `{title, source, axes[], summary_md}` or `None` on parse failure. Defends against code-fenced JSON; filters axes against the valid set.

## scheduler

`scheduler.pick_next(...)` — chooses problems for the day. Reads:

- User's axis scores
- Recent attempts (for recall scoring + ramp counter)
- Active JD's `axis_weights` + `signal_tags`
- `easy_first_bias` (ramp)

Returns a scored list of problems with breakdowns (the `details` field on the home Up-next card surfaces these).

## See also

- [Code tour](code-tour.md)
- [Data model](data-model.md)
