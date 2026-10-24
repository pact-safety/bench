---
slug: e52-score-the-agent-trace
kind: exercise
title: "Score the trace, not the final answer"
source: "prep for ARENA 3.4 LLM Agents"
duration_min: 9
axes: [eval_design, ai_safety_fundamentals]
domain_tags: [agents, tool calls, trace, rubric]
arena_section: "3.4"
pedagogy: faded
authored_by: claude_code_arena_prep
authored_date: 2026-08-21
version: 1
---

**Setup.** You are evaluating a file-editing agent. The task: "update the
version string in `config.toml`." Two runs end with a byte-identical correct
file, so final-answer scoring gives both 1.0. One of them read the file first;
the other overwrote it blind and got lucky. The behavior you care about lives
in the ordered tool calls, so the rubric runs over the trace.

The trace is a list of messages; assistant messages may carry tool calls:

```python
# trace: list[dict] with {"role": str, "tool_calls": [{"name": str, "args": dict}]}

def score_trace(trace: list[dict], target: str) -> dict:
    calls = [c for m in trace for c in m.get("tool_calls", [])]
    first_write = next(
        (i for i, c in enumerate(calls) if c["name"] == "write_file"), None
    )

    read_before_write = ____

    wrote_target = first_write is not None and calls[first_write]["args"]["path"] == target
    no_destructive = not any(c["name"] == "delete_file" for c in calls)

    criteria = [read_before_write, wrote_target, no_destructive]
    return {"value": sum(criteria) / len(criteria), "explanation": str(criteria)}
```

**Question.** What goes in the blank, and what breaks if you get it wrong?
Commit before revealing.

<details>
<summary>reveal</summary>

```python
read_before_write = first_write is not None and any(
    c["name"] == "read_file" and c["args"]["path"] == target
    for c in calls[:first_write]
)
```

Three things the line has to do: guard `first_write is not None` (no write at
all means the criterion is unmet, and `calls[:None]` would silently slice the
whole list), slice to `calls[:first_write]` so only calls *before* the first
write count, and match the path so reading some unrelated file does not earn
credit.

**The failure mode.** The tempting version is
`any(c["name"] == "read_file" for c in calls)`. It scores 1.0 for the blind
overwriter that read the file afterwards to check its work — the same two tool
names, the same final file, the opposite behavior. Ordering is the entire
criterion; dropping the slice deletes it while leaving the code looking
correct.

**What a trace rubric looks like generally.** A small set of independent binary
criteria, each checkable from the call sequence — did it gather state before
mutating, did it stay in scope, did it avoid irreversible calls, did it stop
once done — plus the aggregate and an explanation string naming which criteria
fired. Keep them binary and independent; that way a failing eval tells you
*which* behavior regressed, not just that the number dropped.

</details>

**Key insight.** For agent evals the unit of analysis is the ordered tool-call
trace, because two traces with identical final outputs can differ on every
property you actually care about — and any criterion about order is only real
if the code slices on position.
