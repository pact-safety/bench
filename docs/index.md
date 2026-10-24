# bench

bench is a practice environment for engineers moving into AI safety research engineering. It brings the field into one daily practice: foundational papers, exercises, coding problems, curricula like ARENA and ML4Good, the week's news, and timed mock interviews. It looks at where you're weak and at the role you're aiming for, and picks what you work on next.

bench is part of [PACT](https://github.com/pact-safety), which builds open-source tools so independent researchers can evaluate AI systems for themselves. The hosted instance is invite-only alpha; the source is at [pact-safety/bench](https://github.com/pact-safety/bench).

**If you're using bench**, start with these four pages:

- **[How practice works](using/how-practice-works.md)**: the pedagogy, and how confident to be in each part of it
- **[AI in bench](using/ai-and-your-work.md)**: which models run where, what leaves your machine, and what the model is bad at
- **[Your data](using/your-data.md)**: what's stored, who can read it, and how to delete it
- **[Accessibility](using/accessibility.md)**: what's implemented, and what's still weak

## A learner's day

```
Start     →  /skills    a short assessment maps you across five skill axes
              ↓
            /aim        paste a job posting; bench reads what the role needs
              ↓
Daily     →  /          today's picks: a reading, a video, an exercise or problem
              ↓
            /problem/<slug>   work in phases, run real tests, get per-phase review
              ↓
            /tracks     follow a curriculum such as ARENA or ML4Good prework
              ↓
            /news       what the labs and safety orgs published this week
              ↓
Weekly    →  /reflect   prompts built from what you actually did
```

## Why it exists

The people who can build evals, reproduce papers, and read model internals are mostly trained inside frontier labs. The groups that check those labs need the same skills and hire from a small pool. bench makes those skills cheaper to learn outside a lab: it's free to self-host, works with your own API key, and targets what these roles actually test. The README states the assumptions this rests on and how it could be wrong.

## Map of the rest

<div class="grid cards" markdown>

- :material-target: **Using bench**

    Feature by feature: problems, mentor voices, weekly reflection, the reading library, job postings, readiness.

    [→ Start with drilling problems](using/problems.md)

- :material-source-branch: **Architecture**

    Code tour, data model, and services, for extending bench.

    [→ Code tour](architecture/code-tour.md)

- :material-tools: **Development**

    Setup, tests, and common tasks.

    [→ Setup & tests](development/setup.md)

- :material-map: **Roadmap & decisions**

    What has shipped, what's queued, and what was rejected and why.

    [→ Roadmap](roadmap.md)

</div>
