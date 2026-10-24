from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore


REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class AppConfig:
    db_path: Path
    content_dir: Path
    host: str
    port: int


@dataclass(frozen=True)
class UIConfig:
    use_codemirror: bool
    session_size: int


@dataclass(frozen=True)
class SchedulerWeights:
    days_since: float
    low_confidence: float
    over_time: float
    used_reference: float
    topic_gap: float
    never_attempted: float
    content_aligned: float
    content_aligned_recency_days: int
    jd_aligned: float
    used_hints: float
    max_60min_per_session: int
    require_category_span: bool


@dataclass(frozen=True)
class WarmupConfig:
    recency_floor_days: int


@dataclass(frozen=True)
class RunnerConfig:
    python_timeout_seconds: int
    rust_timeout_seconds: int


@dataclass(frozen=True)
class EmConfig:
    plan_gate_chars: int
    default_enabled: bool


@dataclass(frozen=True)
class MiraConfig:
    model: str
    history_max_turns: int
    history_token_budget: int


@dataclass(frozen=True)
class Config:
    app: AppConfig
    ui: UIConfig
    scheduler: SchedulerWeights
    warmup: WarmupConfig
    runner: RunnerConfig
    em: EmConfig
    mira: MiraConfig


def load_config(path: Path | None = None) -> Config:
    cfg_path = path or REPO_ROOT / "config.toml"
    with cfg_path.open("rb") as f:
        raw = tomllib.load(f)
    app = raw["app"]
    ui = raw["ui"]
    sched = raw["scheduler"]
    warmup = raw["warmup"]
    runner = raw["runner"]
    em = raw.get("em", {"plan_gate_chars": 80, "default_enabled": True})
    mira = raw.get("mira", {})
    return Config(
        app=AppConfig(
            db_path=REPO_ROOT / app["db_path"],
            content_dir=REPO_ROOT / app["content_dir"],
            host=app["host"],
            port=int(app["port"]),
        ),
        ui=UIConfig(use_codemirror=bool(ui["use_codemirror"]), session_size=int(ui["session_size"])),
        scheduler=SchedulerWeights(
            days_since=float(sched["weight_days_since"]),
            low_confidence=float(sched["weight_low_confidence"]),
            over_time=float(sched["weight_over_time"]),
            used_reference=float(sched["weight_used_reference"]),
            topic_gap=float(sched["weight_topic_gap"]),
            never_attempted=float(sched["weight_never_attempted"]),
            content_aligned=float(sched.get("weight_content_aligned", 1.5)),
            content_aligned_recency_days=int(sched.get("content_aligned_recency_days", 3)),
            jd_aligned=float(sched.get("weight_jd_aligned", 1.5)),
            used_hints=float(sched.get("weight_used_hints", 0.6)),
            max_60min_per_session=int(sched["max_60min_per_session"]),
            require_category_span=bool(sched["require_category_span"]),
        ),
        warmup=WarmupConfig(recency_floor_days=int(warmup["recency_floor_days"])),
        runner=RunnerConfig(
            python_timeout_seconds=int(runner["python_timeout_seconds"]),
            rust_timeout_seconds=int(runner["rust_timeout_seconds"]),
        ),
        em=EmConfig(
            plan_gate_chars=int(em.get("plan_gate_chars", 80)),
            default_enabled=bool(em.get("default_enabled", True)),
        ),
        mira=MiraConfig(
            # Sonnet default — MIRA is the expansive surface (spec §5; the
            # Brain⟷MIRA boundary doc puts MIRA on the strongest model).
            model=str(mira.get("model", "claude-sonnet-4-5")),
            history_max_turns=int(mira.get("history_max_turns", 20)),
            history_token_budget=int(mira.get("history_token_budget", 6000)),
        ),
    )
