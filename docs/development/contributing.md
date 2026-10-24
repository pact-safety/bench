# Adding a voice, a problem, or a content item

Quick patterns for the three additions you'll do most often.

## Adding a voice

Open `app/services/voices.py`. Append to `_VOICES`:

```python
Voice(
    key="bell_hooks",
    name="bell hooks",
    era="cultural critique · 1980s–2010s",
    works="Teaching to Transgress; All About Love.",
    persona=(
        "You write in the spirit of bell hooks: pedagogy is liberation "
        "work. When reviewing this attempt, ask who the candidate is "
        "doing this for — who benefits from this code working, and who "
        "is rendered invisible by the assumptions baked in? Critique "
        "with care; the goal of feedback is the candidate's growth, "
        "not the platform's self-protection. Compassionate, specific."
    ),
    review_lens=(
        "Who benefits from this code working, and what assumptions does "
        "it bake in? Whose use cases would this fail to serve?"
    ),
    provocation="\"To be loving is to be radical — to choose to see "
                "another person clearly.\"",
),
```

Tests:

```python
# tests/unit/test_voices.py
def test_registry_includes_bell_hooks():
    assert "bell_hooks" in voices.valid_keys()
```

That's it. The voice appears in the `/voices` page, the per-submission dropdown, and the settings preference picker automatically.

## Adding a problem

Author a TOML file in `content/`. Convention: `r<axis_prefix>-<short_name>.toml` for Rust problems, `<short_name>.toml` for Python.

```toml
slug = "tiny-attention-from-scratch"
title = "Attention from scratch — single head, no batching"
problem_type = "code_compose"
difficulty = "medium"
time_bucket = 25
domain_tags = ["transformer_internals", "attention"]
structural_tags = ["compose"]
competency_tags = ["pytorch", "linalg"]
jd_signal_tags = ["transformer", "interpretability"]
is_warmup = false
em_mode = "full"

content_md = """
Implement single-head scaled dot-product attention from scratch over
(L, D) queries, keys, values. No batching, no mask. Output: (L, D)
context vector.

…
"""

starter_code_python = "def attention(q, k, v):\n    pass\n"
reference_solution_python = "..."
key_insight = "softmax over the last axis of QK^T / sqrt(d)"
pitfalls_md = "Don't forget the d^0.5 normalization."
test_code_python = "..."
```

On the next startup (or `LIS_FORCE_RELOAD=1`), the loader picks it up. The `content_hash` column means unchanged files are skipped, so adding is fast.

## Adding a content item

Same TOML convention, with `kind` set to one of `reading`, `video`, `podcast`, `exercise`:

```toml
slug = "r01-vaswani-attention-is-all-you-need"
title = "Attention Is All You Need — §3.2.1"
kind = "reading"
duration_min = 22
source = "Vaswani et al., 2017"
axes = ["transformer_internals"]
prerequisites = []

content_md = """
This is the section that defines scaled dot-product attention…
"""
```

## Adding an axis

This is rarer. Edit `app/services/assessment.py`:

```python
AXES = (
    "transformer_internals",
    ...
    "your_new_axis",
)
AXIS_LABELS = {
    ...
    "your_new_axis": "Your New Axis Label",
}
```

Then update:

- The 12-question quiz in the same file (add questions that score against the new axis)
- Any problems' `domain_tags` that should include it
- JD parse — the curated `_AXIS_KEYWORDS` table in `app/services/jds.py` if you want keyword-fallback scoring

The scheduler and readiness math work off `AXES` directly — they'll pick up the new axis automatically.

## Adding a route

In `app/main.py`, in the appropriate thematic section:

```python
@app.get("/your-route", response_class=HTMLResponse)
def your_route(request: Request):
    uid = request.state.user_session.user_id
    # ... assemble context ...
    return templates.TemplateResponse(
        request, "your_template.html",
        {"config": config, "nav_section": "today", ...}
    )
```

Then create `templates/your_template.html` extending `base.html`. Add a nav-link if it deserves one (in `templates/base.html`).

## See also

- [Setup](setup.md)
- [Common tasks](common-tasks.md)
- [Code tour](../architecture/code-tour.md)
