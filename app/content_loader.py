"""Load markdown-with-frontmatter problem files into the DB on startup.

File format: YAML frontmatter between `---` fences, followed by markdown
body. Body sections are split by H2 headings: `## Prompt`, `## Starter`,
`## Starter (Rust)`, `## Solution`, `## Solution (Rust)`, `## Tests`,
`## Key insight`, `## Pitfalls`. Missing sections are simply absent on
the Problem record — that is how warmups end up without `## Pitfalls`.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from .models import Problem
from .repositories import ProblemRepository


SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        raise ValueError("missing frontmatter fence")
    end = text.find("\n---", 4)
    if end == -1:
        raise ValueError("unterminated frontmatter")
    fm_raw = text[4:end]
    body = text[end + 4 :].lstrip("\n")
    return yaml.safe_load(fm_raw) or {}, body


def _split_sections(body: str) -> dict[str, str]:
    parts: dict[str, str] = {}
    matches = list(SECTION_RE.finditer(body))
    if not matches:
        return {"_": body.strip()}
    parts["_"] = body[: matches[0].start()].strip()
    for i, m in enumerate(matches):
        name = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        parts[name] = body[start:end].strip()
    return parts


def _strip_code_fence(s: str) -> str:
    if not s:
        return s
    lines = s.strip().splitlines()
    if not lines:
        return ""
    if lines[0].startswith("```") and lines[-1].startswith("```"):
        return "\n".join(lines[1:-1])
    return s


def parse_problem_file(path: Path) -> Problem:
    fm, body = _parse_frontmatter(path.read_text())
    sections = _split_sections(body)
    prompt = sections.get("Prompt", sections.get("_", "")).strip()
    starter_py = _strip_code_fence(sections.get("Starter", ""))
    starter_rs = _strip_code_fence(sections.get("Starter (Rust)", "")) or None
    sol_py = _strip_code_fence(sections.get("Solution", ""))
    sol_rs = _strip_code_fence(sections.get("Solution (Rust)", "")) or None
    tests_py = _strip_code_fence(sections.get("Tests", ""))
    key_insight = sections.get("Key insight", "").strip() or None
    pitfalls = sections.get("Pitfalls", "").strip() or None

    em_block = fm.get("em") or {}
    em_mode = str(em_block.get("mode", "full")) if isinstance(em_block, dict) else "full"
    em_prompts: dict[str, str] = {}
    if isinstance(em_block, dict):
        for phase in ("explore", "brainstorm", "plan", "implement", "verify"):
            val = em_block.get(phase)
            if isinstance(val, str) and val.strip():
                em_prompts[phase] = val.strip()

    raw_refs = fm.get("references") or []
    references: list[dict] = []
    if isinstance(raw_refs, list):
        for r in raw_refs:
            if not isinstance(r, dict) or not r.get("title"):
                continue
            entry = {"title": str(r["title"]).strip()}
            for k in ("url", "book", "why"):
                v = r.get(k)
                if isinstance(v, str) and v.strip():
                    entry[k] = v.strip()
            if "page" in r and r["page"] not in (None, ""):
                entry["page"] = str(r["page"]).strip()
            phase = r.get("phase")
            if isinstance(phase, str) and phase.strip().lower() in {"explore", "brainstorm", "plan", "implement", "verify"}:
                entry["phase"] = phase.strip().lower()
            references.append(entry)

    # Interview-mode v1 phase budgets. Optional TOML field; if absent,
    # the service supplies a proportional fallback at problem load
    # time. Authoring a per-problem budget overrides the fallback.
    # See app/services/phase_budget.py for the math.
    from .services import phase_budget as _pb_svc
    phase_budgets_raw = fm.get("phase_budgets_seconds")
    if isinstance(phase_budgets_raw, dict) and phase_budgets_raw:
        # Coerce to int + validate against time_bucket. On validation
        # failure we don't crash the loader; we log the issue and fall
        # back to the default split so a fresh prod boot survives a
        # bad TOML.
        try:
            authored_budgets = {
                k: int(v) for k, v in phase_budgets_raw.items()
                if isinstance(k, str)
            }
        except (TypeError, ValueError):
            authored_budgets = None
        if authored_budgets is not None:
            ok, reason = _pb_svc.validate_budgets(
                authored_budgets,
                time_bucket_minutes=int(fm["time_bucket"]),
            )
            if ok:
                phase_budgets = authored_budgets
            else:
                # Bad authored budgets → fallback + the loader logs
                # (print is fine here — content load happens at boot
                # and the operator reads boot logs anyway).
                print(
                    f"[content_loader] {fm['slug']}: invalid phase_budgets_seconds "
                    f"({reason}); falling back to default split",
                    flush=True,
                )
                phase_budgets = _pb_svc.default_budgets(
                    time_bucket_minutes=int(fm["time_bucket"]),
                    problem_type=fm["problem_type"],
                )
        else:
            phase_budgets = _pb_svc.default_budgets(
                time_bucket_minutes=int(fm["time_bucket"]),
                problem_type=fm["problem_type"],
            )
    else:
        phase_budgets = _pb_svc.default_budgets(
            time_bucket_minutes=int(fm["time_bucket"]),
            problem_type=fm["problem_type"],
        )

    return Problem(
        id=0,
        slug=fm["slug"],
        title=fm["title"],
        difficulty=fm["difficulty"],
        time_bucket=int(fm["time_bucket"]),
        problem_type=fm["problem_type"],
        is_warmup=bool(fm.get("is_warmup", False)),
        structural_tags=list(fm.get("structural_tags", [])),
        domain_tags=list(fm.get("domain_tags", [])),
        competency_tags=list(fm.get("competency_tags", [])),
        jd_signal_tags=list(fm.get("jd_signal_tags", [])),
        content_md=prompt,
        starter_code_python=starter_py or None,
        starter_code_rust=starter_rs,
        reference_solution_python=sol_py or None,
        reference_solution_rust=sol_rs,
        key_insight=key_insight,
        pitfalls_md=pitfalls,
        test_code_python=tests_py or None,
        rust_crate_dir=fm.get("rust_crate_dir"),
        source_provenance=fm.get("source_provenance"),
        original=bool(fm.get("original", True)),
        authored_by=fm.get("authored_by"),
        authored_date=fm.get("authored_date"),
        version=int(fm.get("version", 1)),
        em_mode=em_mode,
        em_prompts=em_prompts,
        references=references,
        phase_budgets=phase_budgets,
    )


def load_all_problems(
    content_dir: Path,
    repo: ProblemRepository,
    progress_cb=None,
) -> int:
    """Upsert all problem markdown files into the repo.

    Hash-skip optimization: each markdown file's bytes are SHA-256'd
    and compared against the row's `content_hash` in Postgres. Files
    whose hash matches are skipped (no round-trip). On a typical
    restart with no edits, the loader makes ONE query (the hashes
    SELECT) plus zero upserts, finishing in ~1 second instead of ~40."""
    import hashlib

    files: list[tuple[str, Path]] = []
    for sub in ("problems", "warmups"):
        d = content_dir / sub
        if not d.exists():
            continue
        for f in sorted(d.glob("*.md")):
            files.append((sub, f))
    total = len(files)
    # ONE round-trip to learn what's already in the DB.
    db_hashes = repo.hashes_by_slug()
    n = 0
    skipped = 0
    failed = 0
    for sub, f in files:
        raw = f.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        # Resilience: a single malformed / constraint-violating problem
        # file must NOT crash the whole startup load (which, since this
        # runs at module import, would take the entire app down and fail
        # the deploy's health check). Skip it with a loud warning and
        # keep loading the rest. autocommit=True means the failed upsert
        # doesn't poison the connection for subsequent problems.
        try:
            p = parse_problem_file(f)
            if db_hashes.get(p.slug) == digest:
                skipped += 1
                n += 1
                if progress_cb:
                    progress_cb(n, total, f"{f.stem} (skipped)")
                continue
            repo.upsert(p, content_hash=digest)
        except Exception as e:  # noqa: BLE001 — deliberately broad; one bad file can't brick boot
            failed += 1
            import sys
            sys.stdout.write(
                f"\n[startup] WARN: skipped problem {f.name}: {type(e).__name__}: {e}\n"
            )
            sys.stdout.flush()
            continue
        n += 1
        if progress_cb:
            progress_cb(n, total, f.stem)
    if failed:
        import sys
        sys.stdout.write(
            f"[startup] WARN: {failed} problem file(s) failed to load and were skipped\n"
        )
        sys.stdout.flush()
    if skipped:
        # Loader caller's "loaded N problems" print accounts for the
        # full set; surface the skip count separately so the user
        # knows the optimization is working.
        import sys
        sys.stdout.write(f"\n[startup]   ({skipped} unchanged, skipped)\n")
        sys.stdout.flush()
    return n
