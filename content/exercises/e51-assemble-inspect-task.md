---
slug: e51-assemble-inspect-task
kind: exercise
title: "Assemble an Inspect Task in the right order"
source: "prep for ARENA 3.3 Running Evals with Inspect"
duration_min: 9
axes: [eval_design, ai_safety_fundamentals]
domain_tags: [inspect, task, solver, scorer]
arena_section: "3.3"
pedagogy: parsons
authored_by: claude_code_arena_prep
authored_date: 2026-08-21
version: 1
---

**Setup.** In Inspect, an eval is a `Task` built from three parts: a **dataset**
(the items — each `Sample` holds the input, the target, and any metadata), a
**solver** (what happens to a sample on its way to a model response — system
message, chain of thought, the generate call), and a **scorer** (what turns the
finished model state into a `Score`). Below are the pieces of one task file,
scrambled. One of them does not belong.

```
A.  return Task(
        dataset=dataset,
        solver=[system_message(SYSTEM), multiple_choice(shuffle=True)],
        scorer=choice(),
    )

B.  @task

C.  dataset = json_dataset("power_seeking.jsonl")

D.  def power_seeking() -> Task:

E.  from inspect_ai import Task, task
    from inspect_ai.dataset import json_dataset
    from inspect_ai.scorer import choice
    from inspect_ai.solver import multiple_choice, system_message

F.  SYSTEM = "Answer with a single letter."

G.  score = choice()(state, target)
```

**Question.** Give the correct order of the blocks you keep, name the one you
drop, and state the constraint that forces each adjacency. Commit before
revealing.

<details>
<summary>reveal</summary>

**Order: E, F, B, D, C, A.** Drop **G**.

The constraints, in order:

- **E first** — names must exist before they are referenced. Nothing else can
  be parsed without `Task`, `task`, the dataset loader, the solver, the scorer.
- **F before A** — `SYSTEM` is read at the moment `system_message(SYSTEM)` is
  constructed, which happens inside the return.
- **B immediately above D** — a decorator binds to the function definition on
  the next line. Any block between them is a syntax error, not a style issue.
- **C before A** — `dataset` must be bound before it is passed. It sits in the
  function body, so it runs per-call, not at import.
- **A last** — the `Task` is the assembly step. It cannot be built until its
  three arguments exist.

**Why G is a distractor.** Scoring is not something you call. You *declare* the
scorer on the `Task` and the framework applies it to each sample's final state
after the solver runs, collecting the `Score` values into metrics. A scorer
returns a `Score` — a value plus, optionally, the extracted answer and an
explanation — never a bare number you compute inline. Calling it by hand
bypasses the eval loop, produces no log, and leaves `state`/`target` undefined
at that point in the file.

Note also that `solver` is a **list**: solvers compose in sequence, each
handing the updated state to the next. `multiple_choice()` is the one that
presents options and generates; `choice()` is its matching scorer.

</details>

**Key insight.** `Task = dataset + solver + scorer` is a declaration, not a
script — you name the three parts and the framework owns the loop, which is
exactly why you never call the scorer yourself.
