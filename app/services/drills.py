"""Drill rep-trend math — pure functions over a chat transcript.

A "drill" is a timed-rep practice session run through a chat persona
(e.g. the MATS empirical-track drill partner in `voices.py`). Each rep
is delimited by markers the persona is instructed to emit:

    === REP 1 · MODE A · target 20 min ===      (rep start, in an assistant turn)
    === END REP 1 · elapsed 18 min ===          (rep end + the persona's elapsed reading)

This module walks a transcript and returns per-rep timing so a surface
can show "you're trending faster than target" across reps — the thing
the operator asked for ("report the trend across reps, not just the
last one").

Deliberately decoupled from any persistence model. The input is a list
of plain message mappings (`{"role", "content"}`), which is the lowest
common denominator across the chat surfaces — so this helper has zero
import dependency on the MIRA session/turn schema and works regardless
of how that lands. The integration layer maps its turns to this shape
in one line.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence


# Rep markers. We control both the persona prompt (which emits these)
# and this parser, so the format is strict — but the separator between
# tokens is tolerated as middot / dash / pipe / whitespace so a model
# that "helpfully" reformats the line doesn't silently break parsing.
# We only scan lines containing "===" so prose never false-matches.
_SEP = r"[·\-|:]?"
_REP_START_RE = re.compile(
    r"REP\s+(?P<rep>\d+)\b.*?MODE\s+(?P<mode>[AB])\b.*?target\s+(?P<target>\d+)\s*min",
    re.IGNORECASE,
)
_REP_END_RE = re.compile(
    r"END\s+REP\s+(?P<rep>\d+)\b.*?elapsed\s+(?P<elapsed>\d+)\s*min",
    re.IGNORECASE,
)


def _content_of(msg: Any) -> str:
    """Read message text from either a mapping (`msg["content"]`) or an
    object with a `.content` attribute. Returns '' on anything else."""
    if isinstance(msg, Mapping):
        return str(msg.get("content") or "")
    return str(getattr(msg, "content", "") or "")


def _role_of(msg: Any) -> str:
    if isinstance(msg, Mapping):
        return str(msg.get("role") or "")
    return str(getattr(msg, "role", "") or "")


def rep_trend_for_session(messages: Sequence[Any]) -> list[dict]:
    """Walk a transcript and summarize each rep's timing.

    `messages` is any sequence of message mappings/objects carrying a
    `role` ("user" | "assistant") and `content` (str). Only assistant
    turns are scanned for markers — the persona emits both the start
    and the END line.

    Returns a list of dicts, one per rep that has a START marker, in
    rep order:

        {
          "rep": int,
          "mode": "A" | "B",
          "target_min": int,
          "elapsed_min": int | None,   # None while the rep is still open
          "status": "under" | "over" | "open",
        }

    status:
        "open"   — START seen, no matching END yet (rep in progress)
        "under"  — elapsed <= target  (on or ahead of pace)
        "over"   — elapsed >  target  (over the target time)

    A START with no END leaves the rep "open". A duplicate START for an
    already-seen rep number updates that rep's mode/target (the persona
    re-announcing). An END with no matching START is ignored (defensive
    — shouldn't happen with a well-behaved persona).
    """
    # rep number -> partial record, preserving first-seen order.
    reps: dict[int, dict] = {}
    order: list[int] = []

    for msg in messages:
        if _role_of(msg) != "assistant":
            continue
        for line in _content_of(msg).splitlines():
            if "===" not in line:
                continue
            start = _REP_START_RE.search(line)
            if start:
                rep_n = int(start.group("rep"))
                if rep_n not in reps:
                    order.append(rep_n)
                rep = reps.setdefault(rep_n, {"rep": rep_n})
                rep["mode"] = start.group("mode").upper()
                rep["target_min"] = int(start.group("target"))
                rep.setdefault("elapsed_min", None)
                continue
            end = _REP_END_RE.search(line)
            if end:
                rep_n = int(end.group("rep"))
                # END with no START → ignore (defensive).
                if rep_n not in reps:
                    continue
                reps[rep_n]["elapsed_min"] = int(end.group("elapsed"))

    out: list[dict] = []
    for rep_n in order:
        rep = reps[rep_n]
        elapsed = rep.get("elapsed_min")
        target = rep.get("target_min")
        if elapsed is None:
            status = "open"
        elif target is not None and elapsed > target:
            status = "over"
        else:
            status = "under"
        out.append({
            "rep": rep_n,
            "mode": rep.get("mode"),
            "target_min": target,
            "elapsed_min": elapsed,
            "status": status,
        })
    return out


def trend_summary(trend: list[dict]) -> str:
    """One-line human summary of a rep trend, for injecting as a
    `<system_note>` so the persona can comment on the arc rather than
    just the last rep. Empty string when there's nothing closed yet.

    Example: "Rep 1: 22/20m (over). Rep 2: 18/20m (under) — trending
    faster."
    """
    closed = [r for r in trend if r["elapsed_min"] is not None]
    if not closed:
        return ""
    parts = [
        f"Rep {r['rep']}: {r['elapsed_min']}/{r['target_min']}m ({r['status']})"
        for r in closed
    ]
    line = ". ".join(parts)
    # Direction hint when there are at least two closed reps.
    if len(closed) >= 2:
        first, last = closed[0]["elapsed_min"], closed[-1]["elapsed_min"]
        if last < first:
            line += " — trending faster"
        elif last > first:
            line += " — trending slower"
        else:
            line += " — holding steady"
    return line + "."
