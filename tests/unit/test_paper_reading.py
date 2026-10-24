"""Ng multi-pass paper reading.

The method: several passes with different jobs, and a relevance verdict
after the first, because most papers should be parked. What this pins:

  - the ladder is monotonic and idempotent (a re-click cannot demote you)
  - later passes' questions are NOT shown early — asking "what is the
    baseline" during pass 1 trains skimming-for-an-answer
  - detection is conservative: book chapters do not get a paper ladder
  - NOTHING here computes a score. `recitation.py` states the constraint
    as product law; a completion percentage over the questions would be
    the same failure in a new place.
"""

from __future__ import annotations

from app.services import paper_reading as P


# ---------- detection --------------------------------------------------------


def test_arxiv_and_doi_are_papers():
    assert P.is_paper("https://arxiv.org/abs/1706.03762")
    assert P.is_paper("https://doi.org/10.1145/3287324")
    assert P.is_paper("https://openreview.net/forum?id=abc")
    assert P.is_paper("https://aclanthology.org/P16-1162/")


def test_book_chapters_and_blogs_are_not():
    assert not P.is_paper("https://doc.rust-lang.org/book/ch04-01.html")
    assert not P.is_paper("https://karpathy.github.io/2019/04/25/recipe/")
    assert not P.is_paper(None)


def test_non_reading_kinds_never_get_the_ladder():
    assert not P.is_paper("https://arxiv.org/abs/1", kind="exercise")
    assert not P.is_paper("https://arxiv.org/abs/1", kind="video")


# ---------- the ladder -------------------------------------------------------


def test_starts_unread():
    assert P.current_pass({}) == 0
    assert P.current_pass(None) == 0


def test_advance_is_monotonic_and_idempotent():
    s = P.advance({}, 1)
    s = P.advance(s, 3)
    s = P.advance(s, 2)          # re-reading pass 2 must not demote
    assert P.current_pass(s) == 3
    first = dict(s["passes"])
    s = P.advance(s, 3)          # re-click keeps the original timestamp
    assert s["passes"] == first


def test_advance_clamps_out_of_range():
    assert P.current_pass(P.advance({}, 99)) == P.MAX_PASS
    assert P.current_pass(P.advance({}, 0)) == 1


def test_corrupt_state_reads_as_unstarted():
    assert P.current_pass({"pass": "banana"}) == 0
    assert P.current_pass({"pass": -5}) == 0


# ---------- progressive disclosure ------------------------------------------


def test_only_the_next_pass_is_open():
    rows = P.visible_passes({})
    assert rows[0]["open"] is True
    assert rows[1]["open"] is False, "pass 2 must not open before pass 1 is done"

    rows = P.visible_passes(P.advance({}, 1))
    assert rows[1]["open"] is True
    assert rows[2]["open"] is False


def test_pass_one_asks_only_orientation_questions():
    """A methods question during pass 1 would have the reader hunting the
    paper for an answer instead of forming a prior."""
    p1 = P.pass_at(1)
    assert {q.dimension for q in p1.questions} <= {"content", "findings"}
    assert not any(q.dimension == "methods" for q in p1.questions)


def test_taste_and_methods_land_at_pass_three():
    dims = {q.dimension for q in P.pass_at(3).questions}
    assert "methods" in dims and "taste" in dims


def test_all_four_dimensions_are_covered_somewhere():
    dims = {q.dimension for p in P.PASSES for q in p.questions}
    assert dims == set(P.DIMENSIONS)


def test_question_keys_are_unique():
    keys = [q.key for p in P.PASSES for q in p.questions]
    assert len(keys) == len(set(keys))


# ---------- answers ----------------------------------------------------------


def test_answers_merge_and_blank_deletes():
    s = P.save_answers({}, {"content.aim": "They wanted X."})
    assert s["answers"]["content.aim"] == "They wanted X."
    s = P.save_answers(s, {"content.aim": "   "})
    assert "content.aim" not in s["answers"], "a blank must clear, not store empty"


def test_unknown_answer_keys_are_ignored():
    s = P.save_answers({}, {"not.a.question": "junk"})
    assert s["answers"] == {}


def test_answers_do_not_disturb_the_pass():
    s = P.advance({}, 2)
    s = P.save_answers(s, {"content.aim": "x"})
    assert P.current_pass(s) == 2


# ---------- verdict ----------------------------------------------------------


def test_verdict_roundtrip_and_validation():
    s = P.set_verdict({}, "park")
    assert s["verdict"] == "park" and s["verdict_at"]
    for bad in ("skipped", "", "PARK"):
        try:
            P.set_verdict({}, bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad!r} should have been rejected")


# ---------- the evidence bar -------------------------------------------------


def test_deep_read_needs_pass_three_and_writing():
    """A pass counter alone is not evidence of anything, so /signal is
    only offered when the reader actually left something behind."""
    assert P.is_deep_read(P.advance({}, 3)) is False
    s = P.save_answers(P.advance({}, 3), {"taste.why_now": "Compute got cheap."})
    assert P.is_deep_read(s) is True


def test_deep_read_false_below_pass_three():
    s = P.save_answers(P.advance({}, 2), {"content.aim": "x"})
    assert P.is_deep_read(s) is False


# ---------- the constraint ---------------------------------------------------


def test_nothing_exposes_a_completion_ratio():
    """BEN-135: no score, percentage, grade or 'N of M'. Enforced on the
    shapes the UI actually renders, not on a source grep — a ratio key
    appearing here is what a progress bar would be built from."""
    s = P.save_answers(P.advance({}, 3), {"content.aim": "x"})
    banned = {"score", "pct", "percent", "ratio", "grade", "completion", "total"}

    assert not (set(s) & banned), f"state keys leak a score: {set(s) & banned}"

    for row in P.visible_passes(s):
        assert not (set(row) & banned), f"pass row leaks a score: {set(row) & banned}"
        # `answered` is a raw count of prompts written on — a fact, not a
        # mark. It must never be normalised against the question total.
        assert isinstance(row["answered"], int)
        assert row["answered"] <= len(row["pass"].questions)


def test_a_blank_pass_is_not_treated_as_failure():
    """Advancing without answering anything is legitimate: the only
    consequence of a blank is that it is still blank."""
    s = P.advance({}, 2)
    rows = P.visible_passes(s)
    assert rows[1]["done"] is True
    assert rows[1]["answered"] == 0
