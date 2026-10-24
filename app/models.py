from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ProblemType(str, Enum):
    CODE_COMPOSE = "code_compose"
    CODE_DEBUG = "code_debug"
    CODE_READ = "code_read"
    # Reserved for v1.5 — accepted by the schema, not surfaced in UI.
    PAPER_RESPONSE = "paper_response"
    PAPER_SUMMARY = "paper_summary"
    FORUM_DRAFT = "forum_draft"


class Difficulty(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


EM_PHASES: tuple[str, ...] = ("explore", "brainstorm", "plan", "implement", "verify")


@dataclass
class Problem:
    id: int
    slug: str
    title: str
    difficulty: str
    time_bucket: int
    problem_type: str
    is_warmup: bool
    structural_tags: list[str] = field(default_factory=list)
    domain_tags: list[str] = field(default_factory=list)
    competency_tags: list[str] = field(default_factory=list)
    jd_signal_tags: list[str] = field(default_factory=list)
    content_md: str = ""
    starter_code_python: str | None = None
    starter_code_rust: str | None = None
    reference_solution_python: str | None = None
    reference_solution_rust: str | None = None
    key_insight: str | None = None
    pitfalls_md: str | None = None
    test_code_python: str | None = None
    rust_crate_dir: str | None = None
    source_provenance: str | None = None
    original: bool = True
    authored_by: str | None = None
    authored_date: str | None = None
    version: int = 1
    # Engineering Method customization.
    # em_mode: "full" runs all five phases; "lite" hides Brainstorm + Plan;
    # "bypass" hides the whole EM scaffolding (default for warmups).
    em_mode: str = "full"
    em_prompts: dict[str, str] = field(default_factory=dict)
    # Per-problem references (docs, paper sections, book chapters/pages).
    # Each entry has at least `title`. Optional: `url`, `book`, `page`,
    # `why`, `phase` (one of EM_PHASES; if absent, the ref is shown as
    # "general").
    references: list[dict] = field(default_factory=list)
    # Interview-mode v1 per-phase budgets (seconds). Optional TOML
    # field `phase_budgets_seconds`; loader validates against
    # time_bucket and falls back to a proportional split if absent.
    # The five phases sum to time_bucket * 60 (with ±10s tolerance).
    # See app/services/phase_budget.py for the math + fallback.
    phase_budgets: dict[str, int] = field(default_factory=dict)


@dataclass
class Attempt:
    id: int | None
    user_id: str   # UUID (was int in the SQLite era)
    problem_id: int
    problem_version: int
    started_at: datetime
    ended_at: datetime | None
    language_used: str
    final_code: str | None
    solved_without_lookup: bool | None
    confidence_1_to_5: int | None
    time_to_first_edit_seconds: int | None
    edit_count: int
    looked_at_solution: bool
    looked_at_pitfalls: bool
    test_passed: bool | None
    test_output: str | None
    notes_md: str | None
    # Engineering Method per-phase capture.
    explore_notes: str | None = None
    brainstorm_notes: str | None = None
    plan_notes: str | None = None
    verify_notes: str | None = None
    time_per_phase: dict[str, int] | None = None
    # Interview mode: aux panels hidden, timer prominent, stricter LLM rubric.
    interview_mode: bool = False
    # Phase-aware hint ladder: {"plan": 2, "implement": 1, ...} counts how
    # many hints the user requested per phase during the attempt. None
    # for legacy rows. Feeds the scheduler (similar to looked_at_solution).
    hints_used: dict[str, int] | None = None
    # Optional user-authored tests from the problem page.
    user_tests_code: str | None = None
    # Initiative tag (migration 011). NULL = pre-tagging legacy or
    # operator-unassigned. /focus attributes per-initiative activity via
    # exact slug match on this column once the read-path PR lands.
    initiative_slug: str | None = None
    # Interview-mode v1 per-attempt snapshot of the problem's phase
    # budgets in effect at submit time (seconds per phase). Stored
    # per-row so historical review pages stay accurate when the
    # problem's budgets are retuned later. None for legacy rows;
    # the post-session review falls back to default_budgets() then.
    phase_budgets: dict[str, int] | None = None
    # True when the session ended via hard cutoff (operator hit the
    # session-total time limit and the form auto-submitted). False
    # for normal early submissions. Helps the scheduler distinguish
    # "ran out of time" from "wrapped up cleanly."
    cutoff: bool = False
    # v3 forward-compat: which coach style was active for this
    # session ('silent' | 'nudges' | 'live_coach'). NULL in v1.
    interview_mode_preference: str | None = None


@dataclass
class Reflection:
    """Weekly Hamming-mode reflection: a prompt set + the user's reply."""
    id: int | None
    user_id: str   # UUID (was int in the SQLite era)
    period_start: datetime
    period_end: datetime
    generated_at: datetime
    prompts: list[dict]           # [{label: str, prompt: str}, ...]
    response_md: str | None
    response_updated_at: datetime | None
    summary_md: str | None
    method: str
    model_used: str | None
    calibration_json: dict[str, Any] | None = None
    # True when the row was inserted by the Saturday pre-generation cron
    # (GH #229) rather than by an operator-triggered `/reflect/generate`.
    # Distinguishes "the bench made this for you while you slept" from
    # "you asked for this just now" in the UI.
    pregenerated: bool = False
    # Initiative tag (migration 011). NULL = pre-tagging legacy or
    # operator-unassigned. /focus attributes reflections via exact-slug
    # match once the read-path PR lands.
    initiative_slug: str | None = None


@dataclass
class ReviewState:
    user_id: str   # UUID (was int in the SQLite era)
    problem_id: int
    last_attempt_id: int | None
    last_due_score: float
    next_due_at: datetime | None
    lapses: int
    ease_factor: float | None


@dataclass
class Session:
    id: int | None
    user_id: str   # UUID (was int in the SQLite era)
    started_at: datetime
    ended_at: datetime | None
    strategy_name: str
    time_limit_seconds: int | None
    problems: list[int]


@dataclass
class AssessmentRun:
    id: int | None
    user_id: str   # UUID (was int in the SQLite era)
    started_at: datetime
    completed_at: datetime | None
    final_scores: dict[str, float]


@dataclass
class CredentialRun:
    id: int | None
    user_id: str   # UUID (was int in the SQLite era)
    started_at: datetime
    completed_at: datetime | None
    status_text: str | None


@dataclass
class CredentialFile:
    id: int | None
    run_id: int
    filename: str
    content_type: str | None
    byte_size: int
    sha256: str | None
    extracted_text: str | None
    uploaded_at: datetime


@dataclass
class CredentialAssessment:
    id: int | None
    run_id: int
    inferred_axis_scores: dict[str, float]
    summary_md: str | None
    rationale: dict[str, str]
    method: str             # 'claude' | 'keyword_fallback'
    model_used: str | None
    created_at: datetime


@dataclass
class ChatOutcome:
    """One chat-outcome entry from the MCP log_chat_outcome tool.

    Persisted via ChatOutcomesRepository (migration 009, table
    chat_outcomes). Read surfaces: /decisions and /focus "last decided".
    Append-only by design — no edit/delete in the v1 UI.
    """
    id: str                  # UUID; generated server-side
    user_id: str             # UUID
    initiative_slug: str     # validated against loaded initiatives at write time
    decisions: str
    next_actions: str
    chat_url: str | None
    created_at: datetime
    source: str = "mcp"      # 'mcp' | 'manual' | 'backfill'


@dataclass
class MiraSession:
    """One MIRA mentor conversation (migration 014_mira, mira_sessions).

    A session groups a sequence of `MiraTurn`s across one modality. Phase 1a
    only creates chat sessions; the `modality` CHECK already allows 'voice'
    for the Phase-3 voice surface. `title` is null until a future summariser
    backfills it — the UI falls back to a timestamp.
    """
    id: str                  # UUID; generated server-side
    user_id: str             # UUID
    modality: str            # 'chat' | 'voice'
    started_at: datetime
    ended_at: datetime | None = None
    title: str | None = None
    # Session-level knobs. Phase 1a stores nothing; the MATS drill
    # launcher stores {"persona_key": "..."} so a session keeps its
    # persona across turns and resumes.
    meta: dict = field(default_factory=dict)


@dataclass
class MiraTurn:
    """One turn in a MIRA conversation (migration 014_mira, mira_turns).

    `role` is the Anthropic vocabulary ('user'|'assistant'|'tool'). The JSONB
    columns (`tool_calls`, `citations`, `latency_ms`) stay None in Phase 1a —
    no tools, no RAG citations yet — but the fields are carried so the row
    shape is stable when Phase 2 turns them on. Append-only.
    """
    id: str                  # UUID; generated server-side
    session_id: str          # UUID
    role: str
    content: str
    created_at: datetime
    tool_calls: Any | None = None
    citations: Any | None = None
    provider_used: str | None = None
    latency_ms: Any | None = None
    interrupted: bool = False


@dataclass
class Writing:
    id: int | None
    user_id: str   # UUID (was int in the SQLite era)
    title: str
    body_md: str
    source_refs: list[dict]      # [{kind, id, title}]
    status: str                  # 'draft' | 'published' | 'archived'
    word_count: int
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None
    # Initiative tag (migration 011). Writings are the most likely place
    # to want cross-initiative tagging (essays for fellows, blog posts
    # for content, etc.); accepts ANY active initiative slug, including
    # ones whose bench.surface is null. NULL = pre-tagging legacy or
    # operator-unassigned.
    initiative_slug: str | None = None


@dataclass
class Feedback:
    id: int | None
    user_id: str   # UUID (was int in the SQLite era)
    url: str
    page_title: str | None
    theme: str | None
    viewport_width: int | None
    body: str
    status: str                  # 'open' | 'backlog' | 'archived' | 'dismissed'
    created_at: datetime
    processed_at: datetime | None
    processing_notes: str | None
    # A timestamp without a GH URL is a durable promotion claim whose
    # outcome may be uncertain; never automatically retry creating its issue.
    # `promoted_by` is a soft reference to auth.users(id) — no FK so a
    # user deletion doesn't cascade-orphan the audit trail.
    gh_issue_url: str | None = None
    gh_issue_number: int | None = None
    promoted_at: datetime | None = None
    promoted_by: str | None = None


@dataclass
class JD:
    id: int | None
    user_id: str   # UUID (was int in the SQLite era)
    title: str
    org: str | None
    source_text: str
    axis_weights: dict[str, float]   # {axis: 0..1}
    signal_tags: list[str]
    summary: str | None
    method: str                       # 'claude' | 'keyword_fallback'
    model_used: str | None
    parsed_at: datetime | None
    created_at: datetime
    archived_at: datetime | None
    # Iterator / Amplifier / Connector role profile (LessWrong taxonomy).
    # None when the keyword fallback was used — the heuristic has no
    # signal here, so we'd rather hide the UI block than fabricate one.
    iac_profile: dict[str, float] | None = None
    iac_evidence_md: str | None = None
    # Cached one-line "fit" interpretation. Populated lazily on the
    # detail page after a user's CV profile is available, so we don't
    # re-fire a Claude call on every render.
    iac_fit_md: str | None = None


@dataclass
class AttemptReview:
    id: int | None
    attempt_id: int
    method: str                # 'claude' | 'skipped'
    model_used: str | None
    summary_md: str | None
    per_phase: dict[str, dict[str, str]]   # phase -> {strength, gap, question}
    overall_score: float | None
    error_text: str | None
    created_at: datetime
    # Populated only for interview-mode attempts. Maps each rubric
    # signal to a categorical level (see services/review.py).
    rubric_signals: dict[str, str] | None = None


@dataclass
class ContentItem:
    id: int
    slug: str
    kind: str            # 'reading' | 'video' | 'podcast' | 'exercise'
    title: str
    source: str | None = None
    url: str | None = None
    duration_min: int | None = None
    axes: list[str] = field(default_factory=list)
    # Sub-topic tags within an axis. E.g. a `transformer_internals`-axed
    # reading about layer normalization carries `domain_tags=[layer_norm,
    # normalization]`. Mirrors `Problem.domain_tags` to unify the two
    # vocabularies (LIS-284 / GH #2). The library filter now matches
    # directly on `domain_tags ∪ axes` instead of using the alias bridge
    # in the now-deleted `app/services/tag_aliases.py`.
    domain_tags: list[str] = field(default_factory=list)
    prerequisites: list[str] = field(default_factory=list)
    content_md: str | None = None
    authored_by: str | None = None
    authored_date: str | None = None
    version: int = 1
    # Exercise-only frontmatter: when `colab_url` is present we render
    # an "Open in Colab" affordance; otherwise `gpu_required` can still
    # signal that local CUDA / external GPU is recommended.
    gpu_required: bool = False
    colab_url: str | None = None
    # 'authored' = comes from a markdown file in content/, syncs at startup.
    # 'user'     = pasted by the user via /content/new, immune to startup sync.
    source_kind: str = "authored"
    created_by_user_id: str | None = None   # UUID


@dataclass
class ContentProgress:
    user_id: str   # UUID (was int in the SQLite era)
    content_id: int
    status: str            # 'unread' | 'in_progress' | 'completed'
    checked_at: datetime | None
    notes_md: str | None
    favorited: bool = False
    rating_1_to_5: int | None = None
    # Initiative tag (migration 011). NULL = pre-tagging legacy or
    # operator-unassigned.
    initiative_slug: str | None = None
    # Recitation loop (migration 017, BEN-135): per-concept successive-
    # relearning schedule, {concept: {interval_days, due_at, misses,
    # last_recited}}. Empty on pre-migration rows.
    recitation_state: dict = field(default_factory=dict)
    last_recited_at: datetime | None = None
    # Ng multi-pass reading (migration 027): furthest pass, per-pass
    # timestamps, guiding-question answers, relevance verdict. Never a
    # score — see app/services/paper_reading.py. Empty = not started.
    paper_state: dict = field(default_factory=dict)


@dataclass
class AssessmentResponse:
    id: int | None
    run_id: int
    question_id: str
    answer_index: int
    axis_scores: dict[str, float]
    answered_at: datetime


@dataclass
class NewsItem:
    """One ingested RSS item (rss-news-feed Phase 1, migration 012).

    Tier-N feeds in content/news_feeds.toml get polled hourly; each
    entry's URL is the dedup key. `axes_json` stays empty in Phase 1;
    Phase 2 fills it via an LLM classifier pass against the bench's
    13 axes.
    """
    id: int | None
    source: str               # feed slug from news_feeds.toml
    title: str
    url: str                  # UNIQUE; dedup key
    summary: str | None
    published_at: datetime    # from RSS <pubDate>
    fetched_at: datetime      # when the poller saw it
    axes_json: list[str] = field(default_factory=list)
    is_pinned: bool = False
    is_dismissed: bool = False


@dataclass
class NewsFeedHealth:
    """Per-feed observability — surfaced on a future /admin/feed_health
    or via a quick SQL spot-check. The poller upserts one row per feed
    slug on every tick."""
    feed_slug: str
    last_success_at: datetime | None
    last_failure_at: datetime | None
    last_error_message: str | None
    consecutive_failures: int = 0
    last_items_seen: int = 0
    last_items_inserted: int = 0


@dataclass
class Contact:
    """One row in the /connecting tracker (WS6, migration 013).

    A person the operator is maintaining a relationship with. Warmth
    is NOT a column on this row — it's computed at read time in the
    connecting service from the latest interaction's occurred_at
    relative to the contact's cadence_days. Storing warmth would be
    duplicate state that drifts; cadence + last-interaction is the
    minimal source of truth.
    """
    id: int | None
    user_id: str
    name: str
    email: str | None
    handle: str | None
    context: str | None
    cadence_days: int
    archived: bool
    created_at: datetime
    updated_at: datetime


@dataclass
class ContactInteraction:
    """One logged touchpoint with a Contact.

    `direction` is None for kinds that don't have one (a meeting / call
    is mutual by definition). The list view's "their move" highlight
    keys off `direction == 'inbound'` on the most-recent interaction.
    """
    id: int | None
    contact_id: int
    user_id: str
    occurred_at: datetime
    kind: str            # 'sent' | 'received' | 'meeting' | 'call' | 'message' | 'note'
    direction: str | None  # 'outbound' | 'inbound' | None
    notes: str | None
    created_at: datetime


def jd_default_user_id() -> str:
    """DEPRECATED. Kept temporarily because old code paths still call it
    during the SQLite→Postgres migration. Routes should read
    `request.state.user_session.user_id` instead. Will be removed in
    Phase 5 after every callsite migrates."""
    raise RuntimeError(
        "jd_default_user_id() is no longer valid — user_id is per-request "
        "now. Read request.state.user_session.user_id (or use Depends "
        "with the auth gate)."
    )
