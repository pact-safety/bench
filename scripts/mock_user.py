"""Mock user testing harness.

Drives the full HTTP surface (via Starlette's TestClient) so a single
invocation exercises onboarding, the adaptive assessment, scheduled
problem attempts (with EM phase notes), and the warmup flow. Use it to
verify features end-to-end against realistic data without making the
human read 30 ML problems they're still learning.

Usage:
    .venv/bin/python scripts/mock_user.py --persona grinder --reset
    .venv/bin/python scripts/mock_user.py --persona curious_beginner --no-reset

Personas:
    cold_start         — onboards only; no attempts. Tests the gate path.
    curious_beginner   — onboards, then attempts 5 problems with ~60%
                          pass rate and frequent reference-solution
                          peeks. Strong on transformer internals,
                          weak on sampling/decoding and Rust.
    grinder            — onboards, then attempts 20 problems with ~75%
                          pass rate, infrequent peeks. Strong on
                          training/debugging, weak on tokenization/eval.
                          Also burns through a few warmups.

Implementation notes:
- Server runs in-process via TestClient — no port to manage.
- DB reset is by --reset; otherwise it accumulates on prior state.
- All HTTP form bodies match the production endpoints. If a route's
  contract changes, this harness will surface it.
"""

from __future__ import annotations

import argparse
import random
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


# ---- Personas ---------------------------------------------------------------

PERSONAS: dict[str, dict] = {
    "cold_start": {
        "axes_strong": [],
        "axes_weak": ["sampling_decoding", "tokenization", "rust_fluency"],
        "num_attempts": 0,
        "num_warmups": 0,
        "success_rate": 0.0,
        "looked_at_rate": 0.0,
        "confidence_range": (3, 3),
    },
    "curious_beginner": {
        "axes_strong": ["transformer_internals"],
        "axes_weak": ["sampling_decoding", "rust_fluency"],
        "num_attempts": 5,
        "num_warmups": 1,
        "success_rate": 0.6,
        "looked_at_rate": 0.35,
        "confidence_range": (2, 4),
    },
    "grinder": {
        "axes_strong": ["training_mechanics", "debugging", "numerical_stability"],
        "axes_weak": ["tokenization", "eval_design"],
        "num_attempts": 20,
        "num_warmups": 3,
        "success_rate": 0.75,
        "looked_at_rate": 0.15,
        "confidence_range": (3, 5),
    },
}


# ---- Mock content -----------------------------------------------------------

PHASE_FILLER = {
    "explore": "Inputs: tensors of shape (B, S, D). Output: same shape. Edge: empty batch, single position, all-masked rows.",
    "brainstorm": "Two approaches: manual implementation vs. library primitive. Trade-off: clarity vs. speed.",
    "plan": "Compute projection, reshape into heads, apply attention with mask, merge heads, apply output projection. Invariant: last-dim axes preserved through reshapes; mask broadcast over batch.",
    "verify": "Hand-trace seq=2 case. Property: zeroing padded values must not affect non-pad outputs.",
}


def _broken_code() -> str:
    """A submission that will fail the test harness without crashing
    the runner. Empty stubs pass the import but fail asserts."""
    return "def __mock_broken_solution(): pass\n"


# ---- DB reset ---------------------------------------------------------------

def reset_db() -> None:
    data_dir = REPO_ROOT / "data"
    for name in ("prep.db", "prep.db-shm", "prep.db-wal"):
        p = data_dir / name
        if p.exists():
            p.unlink()


# ---- Assessment-answer picker ----------------------------------------------

def _pick_answer_index(question, axes_strong: set[str], axes_weak: set[str]) -> int:
    """Pick the option that best matches the persona. For each option, score:
        + 3 per scored axis if axis is strong
        + 1 per scored axis if axis is neutral
        - 2 per scored axis if axis is weak  (so persona scores low there)
    Returns the option index with the highest total (ties: lowest index)."""
    best_idx = 0
    best_score = -1e9
    for i, opt in enumerate(question.options):
        s = 0.0
        for axis, value in opt.scores.items():
            if axis in axes_strong:
                s += 3 * value
            elif axis in axes_weak:
                s -= 2 * value
            else:
                s += value
        if s > best_score:
            best_score = s
            best_idx = i
    return best_idx


# ---- Driver -----------------------------------------------------------------

def run_persona(persona_name: str, *, reset: bool, seed: int) -> dict:
    if reset:
        reset_db()
    random.seed(seed)

    from fastapi.testclient import TestClient

    # Import after potential reset so the connection sees a fresh DB.
    from app.main import (
        app,
        assessment_repo,
        attempt_repo,
        problem_repo,
    )
    from app.services import assessment as assess_svc
    from app.services import skill_stats as stats_svc

    persona = PERSONAS[persona_name]
    axes_strong = set(persona["axes_strong"])
    axes_weak = set(persona["axes_weak"])

    client = TestClient(app, follow_redirects=False)

    print(f"\n=== persona: {persona_name} ===")

    # 1. Onboarding: walk to /, expect a 303 to /onboarding.
    r = client.get("/")
    assert r.status_code in (200, 303), r.status_code
    if r.status_code == 303:
        print("- home redirected to /onboarding (expected for first visit)")
    else:
        print("- home was already accessible (assessment already completed)")

    # 2. Start an assessment.
    r = client.post("/onboarding/start")
    assert r.status_code == 303, (r.status_code, r.text[:200])
    run_url = r.headers["location"]
    print(f"- assessment started: {run_url}")

    # 3. Answer until we get redirected to /result.
    qcount = 0
    while True:
        r = client.get(run_url)
        if r.status_code == 303 and "/result" in r.headers["location"]:
            break
        assert r.status_code == 200, (r.status_code, r.text[:200])
        m = re.search(r'name="question_id" value="([^"]+)"', r.text)
        if not m:
            print("- no more questions on the page; stopping")
            break
        qid = m.group(1)
        q = assess_svc.get_question(qid)
        idx = _pick_answer_index(q, axes_strong, axes_weak)
        run_id = run_url.rsplit("/", 1)[-1]
        post = client.post(
            f"/assess/{run_id}/answer",
            data={"question_id": qid, "answer_index": idx},
        )
        assert post.status_code == 303, (post.status_code, post.text[:200])
        qcount += 1
    print(f"- answered {qcount} assessment questions")

    # 4. Fetch result + verify scoring landed.
    run_id = int(run_url.rsplit("/", 1)[-1])
    latest = assessment_repo.latest_completed(1) or assessment_repo.get_run(run_id)
    scores = latest.final_scores
    print("- per-axis scores (normalized 0..1):")
    for a in sorted(scores, key=scores.get):
        marker = " (strong)" if a in axes_strong else " (weak)" if a in axes_weak else ""
        print(f"    {a:24s} {scores[a]:.2f}{marker}")
    five = stats_svc.compute_stats(scores)
    print("- consolidated 5-stat pentagon:")
    for p in five:
        print(f"    {p.label:12s} {p.score:.2f} ({p.tier})")

    # 5. Solve scheduled problems for this persona's volume.
    pass_count = 0
    fail_count = 0
    for _ in range(persona["num_attempts"]):
        # Get home → pick first scheduled problem slug.
        r = client.get("/")
        assert r.status_code == 200, r.status_code
        slugs = re.findall(r'href="/problem/([a-z0-9-]+)"', r.text)
        # First card on home is the top-scored scheduled problem.
        slug = next((s for s in slugs if not s.startswith("warmup-")), None)
        if not slug:
            print("- no scheduled problem available; stopping attempts")
            break
        problem = problem_repo.get_by_slug(slug)
        # Decide pass vs fail.
        will_pass = random.random() < persona["success_rate"]
        code = problem.reference_solution_python if (will_pass and problem.reference_solution_python) else _broken_code()
        looked = 1 if random.random() < persona["looked_at_rate"] else 0
        lo, hi = persona["confidence_range"]
        confidence = random.randint(lo, hi)
        form = {
            "code": code,
            "language": "python",
            "confidence": str(confidence),
            "looked_at_solution": str(looked),
            "looked_at_pitfalls": "0",
            # Alternate between naive (server-side default) and tz-aware
            # ("Z" suffix, browser Date.toISOString() format). Catches
            # cross-row tz-mixing bugs in the read path.
            "started_at_iso": "2026-05-12T08:00:00.000Z" if random.random() < 0.5 else "2026-05-12T08:00:00",
            "explore_notes": PHASE_FILLER["explore"] if random.random() > 0.2 else "",
            "brainstorm_notes": PHASE_FILLER["brainstorm"] if random.random() > 0.3 else "",
            "plan_notes": PHASE_FILLER["plan"],  # always present so Plan gate doesn't block submit
            "verify_notes": PHASE_FILLER["verify"] if random.random() > 0.4 else "",
            "time_per_phase_json": '{"explore":60,"brainstorm":90,"plan":180,"implement":600,"verify":40}',
        }
        sub = client.post(f"/submit/{slug}", data=form)
        # /submit returns HTML directly (200), not a redirect.
        assert sub.status_code == 200, (sub.status_code, sub.text[:200])
        if "PASS" in sub.text and "FAIL" not in sub.text.split("PASS")[0]:
            pass_count += 1
        else:
            fail_count += 1
    if persona["num_attempts"]:
        print(f"- solved {persona['num_attempts']} scheduled problems: {pass_count} PASS / {fail_count} FAIL")

    # 6. Warmups.
    warmups_done = 0
    for _ in range(persona["num_warmups"]):
        r = client.get("/warmup")
        if r.status_code != 303:
            break
        slug = r.headers["location"].split("/")[-1].split("?")[0]
        problem = problem_repo.get_by_slug(slug)
        code = problem.reference_solution_python or _broken_code()
        form = {
            "code": code,
            "language": "python",
            "confidence": "3",
            "looked_at_solution": "0",
            "looked_at_pitfalls": "0",
            # Alternate between naive (server-side default) and tz-aware
            # ("Z" suffix, browser Date.toISOString() format). Catches
            # cross-row tz-mixing bugs in the read path.
            "started_at_iso": "2026-05-12T08:00:00.000Z" if random.random() < 0.5 else "2026-05-12T08:00:00",
            "explore_notes": "",
            "brainstorm_notes": "",
            "plan_notes": "",
            "verify_notes": "",
            "time_per_phase_json": "",
        }
        sub = client.post(f"/submit/{slug}", data=form)
        if sub.status_code == 200:
            warmups_done += 1
    if persona["num_warmups"]:
        print(f"- completed {warmups_done} warmups")

    # 7. Quick state assertions.
    attempts = attempt_repo.all_for_user(1)
    states = list(__import__('json').loads('[]'))  # placeholder; not used
    print(f"- total attempts in DB: {len(attempts)}")
    print(f"- problem 1 references: {len(problem_repo.get_by_slug('scaled-dot-product-attention').references)}")

    return {
        "persona": persona_name,
        "questions_answered": qcount,
        "attempts": pass_count + fail_count,
        "passes": pass_count,
        "warmups": warmups_done,
        "skill_scores": scores,
    }


def main():
    parser = argparse.ArgumentParser(description="Drive Li's Bench with a mock user persona.")
    parser.add_argument("--persona", choices=sorted(PERSONAS.keys()), default="curious_beginner")
    parser.add_argument("--reset", action="store_true", help="wipe data/prep.db before running")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    result = run_persona(args.persona, reset=args.reset, seed=args.seed)
    print("\n=== summary ===")
    for k, v in result.items():
        if k == "skill_scores":
            continue
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
