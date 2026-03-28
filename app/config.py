from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class Settings:
    db_path: Path
    timezone: str
    default_budget_steps: int
    default_budget_seconds: int
    base_dir: Path


def get_settings() -> Settings:
    base_dir = Path(__file__).resolve().parent.parent
    db_path = Path(os.getenv("GAME_BENCH_DB_PATH", base_dir / "data" / "game_bench.db"))
    return Settings(
        db_path=db_path,
        timezone=os.getenv("GAME_BENCH_TIMEZONE", "UTC"),
        default_budget_steps=int(os.getenv("GAME_BENCH_DEFAULT_STEPS", "20")),
        default_budget_seconds=int(os.getenv("GAME_BENCH_DEFAULT_SECONDS", "120")),
        base_dir=base_dir,
    )
