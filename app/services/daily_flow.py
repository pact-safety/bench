"""Daily-flow nudge.

Computes the single highest-priority "do this next" action for the
user from today's already-scheduled queue. The Today page surfaces
this as a hero card; once the action is completed (content marked
read, problem submitted, writing saved, reflection answered), the
next visit (or a /today/next redirect) advances to the next action.

Priority order is intentional and not configurable in v1:

  1. Reading        — the day usually starts with priming reading.
  2. Watch / listen — video or podcast.
  3. Practicing     — exercise first (lighter), then top-scored problem.
  4. Composing      — writing draft.
  5. Reflecting     — only if 7+ days since the last reflection (or none).
  6. Caught up      — celebrate + offer a warmup.

Each action is a self-contained dict with `verb` (active-tense),
`title`, `why` (1 sentence rationale), and `url` (where to go).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import logging
from typing import Any

from . import tracks as tracks_service


REFLECTION_NUDGE_DAYS = 7
_log = logging.getLogger(__name__)


@dataclass
class NextAction:
    kind: str               # 'reading' | 'watch' | 'exercise' | 'practice' | 'compose' | 'reflect' | 'caught_up'
    verb: str               # 'Read' / 'Watch' / 'Attempt' / ...
    title: str
    url: str
    why: str
    # Optional metadata the template renders if present.
    duration_min: int | None = None
    badge: str | None = None         # e.g. "reading", "exercise"
    difficulty: str | None = None    # 'easy' / 'medium' / 'hard' for practice
    is_warmup: bool = False          # show "warmup" tag on the card

    resume_url: str | None = None
    resume_note: str | None = None

    def asdict(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "verb": self.verb, "title": self.title,
            "url": self.url, "why": self.why,
            "duration_min": self.duration_min, "badge": self.badge,
            "difficulty": self.difficulty, "is_warmup": self.is_warmup,
            "resume_url": self.resume_url, "resume_note": self.resume_note,
        }


def _content_done_today(progress, today: date) -> bool:
    if progress is None or progress.checked_at is None:
        return False
    return progress.checked_at.date() == today and progress.status == "completed"


def _track_section_verb(kind: str) -> str:
    section_kind = (kind or "").strip().lower()
    if section_kind in {"external_reading", "external_exercise"}:
        return "Work through"
    if section_kind == "problem":
        return "Attempt"
    if section_kind.startswith("reflect"):
        return "Reflect on"
    return "Work through"


def _track_checkpoint_passed_sections(
    track: tracks_service.Track,
    active_track_state: dict[str, Any],
) -> set[int]:
    """Read checkpoint-passed sections from state with legacy fallbacks."""
    passed: set[int] = set()

    raw_passed = active_track_state.get("checkpoint_passed_sections")
    if not isinstance(raw_passed, list):
        raw_passed = active_track_state.get("completed_sections")

    if isinstance(raw_passed, list):
        for val in raw_passed:
            try:
                idx = int(val)
            except (TypeError, ValueError):
                continue
            if 0 <= idx < track.total_sections:
                passed.add(idx)

    # A preferred section can move the cursor without completing earlier
    # sections. Only cursor-only legacy payloads imply prior completion.
    if not isinstance(raw_passed, list):
        try:
            cursor = int(active_track_state.get("cursor", 0))
        except (TypeError, ValueError):
            cursor = 0
        for idx in range(max(0, cursor)):
            if idx < track.total_sections:
                passed.add(idx)

    return passed


def _cold_checkpoint_action(
    track,
    idx: int,
    passing_problem_slugs: set[str] | None,
    available_problem_slugs: set[str] | None = None,
) -> NextAction | None:
    """Surface a practical checkpoint until its runnable problem has passed."""
    slugs = tracks_service.cold_checkpoint_slugs(track, idx)
    if not slugs:
        return None
    done = passing_problem_slugs or set()
    # Match the completion gate: unavailable authored problems cannot strand
    # a learner on a dead link, and a failed attempt cannot satisfy the gate.
    pending = [slug for slug in slugs if slug not in done and (
        available_problem_slugs is None or slug in available_problem_slugs
    )]
    if not pending:
        return None

    section = tracks_service.section_at(track, idx)
    section_title = section.title if section is not None else "this section"
    return NextAction(
        kind="track_checkpoint",
        verb="Prove it cold",
        title=pending[0],
        url=f"/problem/{pending[0]}",
        why=(
            f"Cold checkpoint for {section_title} — same idea, no notebook, "
            f"no autocomplete."
        ),
        badge="checkpoint",
    )


def _next_action_for_track(
    active_track_state: dict[str, Any],
    passing_problem_slugs: set[str] | None = None,
    available_problem_slugs: set[str] | None = None,
    assessment_records: list | None = None,
    user_id: str | None = None,
) -> NextAction | None:
    slug = str(active_track_state.get("slug") or "").strip()
    if not slug:
        return None

    track = tracks_service.get_available_track(slug)
    if track is None:
        _log.warning("active track slug %r was not found or is pending audit; falling back to axis-fit picker", slug)
        return None

    from .track_exams import valid_exemptions
    checkpoint_passed = _track_checkpoint_passed_sections(track, active_track_state) | valid_exemptions(track, assessment_records or [], user_id=user_id)
    next_idx = tracks_service.next_section_index(
        track, checkpoint_passed, active_track_state.get("preferred_section")
    )
    if next_idx is None:
        return None

    section = tracks_service.section_at(track, next_idx)
    if section is None:
        return None

    sessions = active_track_state.get("session_per_section")
    saved = sessions.get(str(next_idx)) if isinstance(sessions, dict) else None
    saved = saved if isinstance(saved, dict) else {}
    next_step = str(saved.get("next_action") or "").strip()
    stopping_point = str(saved.get("stopping_point") or "").strip()

    # BEN-143 — the cold checkpoint comes BEFORE the next section, not after
    # the whole track. A learner who tabbed through an ARENA notebook with
    # Colab's autocomplete on has read the answer, not retrieved it; asking
    # for the same capability in Compose, with no completions and a real test
    # run, is the verification channel. Interleaving it here is what makes it
    # part of the daily flow rather than a page you have to remember to visit.
    cold = _cold_checkpoint_action(
        track, next_idx, passing_problem_slugs, available_problem_slugs
    )
    if cold is not None:
        # Keep the unmet gate primary without hiding the learner's saved work.
        if saved:
            cold.resume_url = f"/tracks/{slug}/sections/{next_idx}"
            cold.resume_note = next_step or stopping_point or None
        return cold

    if section.optional:
        why = f"{track.title} — optional refresher"
    else:
        required_position = track.required_section_indices.index(next_idx) + 1
        why = f"{track.title} — section {required_position} of {track.total_required_sections}"
    if next_step:
        why = f"{why}. Next: {next_step}"
    elif stopping_point:
        why = f"{why}. Last stopped: {stopping_point}"

    from .track_content import item_slug
    section_url = f"/content/{item_slug(track.slug, section.url)}"

    return NextAction(
        kind="track_section",
        verb="Resume" if saved else _track_section_verb(section.kind),
        title=section.title,
        url=section_url,
        why=why,
        duration_min=section.duration_min,
        badge=section.kind or "course",
    )


def _due_recitation_action(
    progress_by_content_id: dict, content_by_id: dict | None, today: date
) -> NextAction | None:
    """A due recitation (BEN-135) surfaces as a next-action. "Due" = a concept
    whose scheduled return is today or earlier. The framing is always what's
    *returning*, never what was missed — the card says "N concepts due to come
    back", and the picker honours the item with the most due concepts."""
    if not content_by_id:
        return None
    from .recitation_schedule import due_concepts

    # Start of tomorrow → captures anything due today or earlier.
    cutoff = datetime(today.year, today.month, today.day) + timedelta(days=1)
    best_item = None
    best_n = 0
    for cid, prog in (progress_by_content_id or {}).items():
        state = getattr(prog, "recitation_state", None)
        if not state:
            continue
        n = len(due_concepts(state, cutoff))
        item = content_by_id.get(cid)
        if n > best_n and item is not None:
            best_item, best_n = item, n
    if best_item is None:
        return None
    plural = "s" if best_n != 1 else ""
    return NextAction(
        kind="recite",
        verb="Recite",
        title=best_item.title,
        url=f"/content/{best_item.slug}#recite",
        why=f"{best_n} concept{plural} due to come back",
        badge="recite",
    )


def compute_due_review(
    *,
    today: date,
    user_settings: dict[str, Any] | None = None,
    user_id: str | None = None,
    progress_by_content_id: dict | None = None,
    content_by_id: dict | None = None,
    problems_by_id: dict | None = None,
) -> NextAction | None:
    """Return the next spaced review independently of the active track hero."""
    # BEN-135: a due recitation is a time-sensitive spaced-repetition
    # obligation — honour it before rotating in new material.
    recite_action = _due_recitation_action(progress_by_content_id or {}, content_by_id, today)
    if recite_action is not None:
        return recite_action

    # Returned problems share the recitation priority, after active tracks.
    # The complete catalogue is separate from the truncated fresh-pick pool.
    from .problem_schedule import due_problem_ids

    for pid in due_problem_ids((user_settings or {}).get("problem_schedule"), today):
        problem = (problems_by_id or {}).get(int(pid)) if pid.isdecimal() else None
        if problem is None:
            continue
        return NextAction(
            kind="practice", verb="Attempt", title=problem.title,
            url=f"/problem/{problem.slug}",
            why="This problem is due again — retrieve it after a gap.",
            duration_min=problem.time_bucket, badge="due again",
            difficulty=(getattr(problem, "difficulty", "") or "").lower() or None,
            is_warmup=bool(getattr(problem, "is_warmup", False)),
        )

    return None


def compute_next(
    *,
    today: date,
    user_settings: dict[str, Any] | None = None,
    user_id: str | None = None,
    daily_reading=None,
    daily_watch=None,
    daily_exercise=None,
    progress_by_content_id: dict | None = None,
    content_by_id: dict | None = None,
    scored_problems: list | None = None,
    problems_by_id: dict | None = None,
    attempts_today_problem_ids: set[int] | None = None,
    # Keep the old input callable, but only a lifetime passing run satisfies
    # the practical gate; failed attempts must continue to surface.
    attempted_problem_slugs: set[str] | None = None,
    passing_problem_slugs: set[str] | None = None,
    available_problem_slugs: set[str] | None = None,
    active_writing=None,
    last_reflection_at: datetime | None = None,
    kinds_done_today: set[str] | None = None,
) -> NextAction:
    """Pure function: takes the day's queue + completion state, returns
    the single next action. No DB / HTTP — easy to unit-test.

    `kinds_done_today` is the set of content kinds (reading / video /
    podcast / exercise) the user has completed at least one of today.
    Once a kind is in the set, the slot is considered done — we don't
    rotate them through another unread item of the same kind. Without
    this, the next-action loop got stuck on readings: pick_daily picks
    the *best unread* reading, so completing one immediately surfaced
    a different reading and the user never advanced to the watch slot."""
    progress_by_content_id = progress_by_content_id or {}
    attempts_today_problem_ids = attempts_today_problem_ids or set()
    scored_problems = scored_problems or []
    kinds_done = kinds_done_today or set()

    active_track_state = (user_settings or {}).get("active_track")
    if isinstance(active_track_state, dict) and active_track_state.get("slug"):
        track_action = _next_action_for_track(
            active_track_state, passing_problem_slugs, available_problem_slugs,
            (user_settings or {}).get("track_assessments", []), user_id=user_id,
        )
        if track_action is not None:
            return track_action

    due_review = compute_due_review(
        today=today, user_settings=user_settings,
        progress_by_content_id=progress_by_content_id, content_by_id=content_by_id,
        problems_by_id=problems_by_id,
    )
    if due_review is not None:
        return due_review

    def _slot_done(slot_kinds: set[str], picked) -> bool:
        """A slot is done if (a) any item of its kind was completed
        today (so the next call doesn't ask for ANOTHER reading), OR
        (b) the specific picked item is itself marked done today."""
        if slot_kinds & kinds_done:
            return True
        if picked is None:
            # No item to suggest at all — slot is effectively done.
            return True
        return _content_done_today(progress_by_content_id.get(picked.id), today)

    # 1) Reading
    if not _slot_done({"reading"}, daily_reading):
        return NextAction(
            kind="reading", verb="Read", title=daily_reading.title,
            url=f"/content/{daily_reading.slug}",
            why="Primes today's practice on overlapping skill axes.",
            duration_min=daily_reading.duration_min,
            badge="reading",
        )

    # 2) Watch / listen — video OR podcast counts. If the user did
    #    either kind today, both slots are done.
    if (
        daily_watch is None
        and not ({"video", "podcast"} & kinds_done)
        and daily_exercise is not None
    ):
        # If there's still downstream work queued today, don't mark
        # watch/listen as done just because the picker returned no
        # item. Keep the slot open and send the user to choose one.
        return NextAction(
            kind="watch", verb="Pick", title="a video or podcast for today",
            url="/library",
            why="No watch/listen item is queued yet — choose one to complete today's listening slot.",
            badge="watch",
        )

    if not _slot_done({"video", "podcast"}, daily_watch):
        verb = "Watch" if daily_watch.kind == "video" else "Listen to"
        return NextAction(
            kind="watch", verb=verb, title=daily_watch.title,
            url=f"/content/{daily_watch.slug}",
            why="Background-format reinforcement — 1.5x is fine for what you already know.",
            duration_min=daily_watch.duration_min,
            badge=daily_watch.kind,
        )

    # 3) Exercise (the lighter "practice")
    if not _slot_done({"exercise"}, daily_exercise):
        return NextAction(
            kind="exercise", verb="Work through", title=daily_exercise.title,
            url=f"/content/{daily_exercise.slug}",
            why="Quick exercise to bridge from reading into practice.",
            duration_min=daily_exercise.duration_min,
            badge="exercise",
        )

    # 4) Practice — one attempt satisfies the slot for today.
    #    After that, advance to writing / reflection.
    if not attempts_today_problem_ids:
        for s in scored_problems:
            if s.problem.id in attempts_today_problem_ids:
                continue
            is_warmup = bool(getattr(s.problem, "is_warmup", False))
            # Badge surface order: warmup tag > problem type. Warmups are
            # short (5-10 min) and explicitly a barrier-lowering ramp;
            # surfacing the label makes it obvious this is a "starter" pick.
            badge = "warmup" if is_warmup else s.problem.problem_type.replace('_', ' ')
            why = (
                f"Warmup ({s.problem.time_bucket} min) — quick rep to ease in."
                if is_warmup else
                f"Top-scored compose problem for today ({s.problem.time_bucket} min)."
            )
            return NextAction(
                kind="practice", verb="Attempt", title=s.problem.title,
                url=f"/problem/{s.problem.slug}",
                why=why,
                duration_min=s.problem.time_bucket,
                badge=badge,
                difficulty=(getattr(s.problem, "difficulty", "") or "").lower() or None,
                is_warmup=is_warmup,
            )

    # 5) Writing — surface if there's an active draft updated today, OR
    #    if no draft exists yet and the user has done enough reading/practice
    #    that drafting a synthesis is the natural next step.
    if active_writing is not None:
        return NextAction(
            kind="compose", verb="Keep drafting", title=active_writing.title or "(untitled draft)",
            url=f"/writings/{active_writing.id}",
            why="In-progress writing draft from today's reading + practice.",
            duration_min=None,
            badge="writing",
        )

    # 6) Reflection — nudge weekly
    if last_reflection_at is None or (
        datetime.utcnow() - last_reflection_at
    ).days >= REFLECTION_NUDGE_DAYS:
        return NextAction(
            kind="reflect", verb="Reflect on", title="this week",
            url="/reflect",
            why=(
                "It's been a week — Hamming-style review pulls the last 7 "
                "days of activity and asks what you're avoiding."
                if last_reflection_at is not None
                else "Set up your first weekly reflection. The prompts are "
                     "specific to the data, not generic."
            ),
            badge="reflect",
        )

    # 7) Caught up.
    return NextAction(
        kind="caught_up", verb="Take a walk", title="You're caught up for today",
        url="/library",
        why="Nothing scheduled. Browse the library if you want extra reps, or rest.",
        badge="done",
    )
