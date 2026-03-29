from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class Settings:
    db_path: Path
    artifacts_root: Path
    timezone: str
    default_budget_steps: int
    default_budget_seconds: int
    base_dir: Path
    admin_token: str | None
    browser_provider: str
    browserbase_api_key: str | None
    browserbase_project_id: str | None
    browserbase_region: str


def get_settings() -> Settings:
    base_dir = Path(__file__).resolve().parent.parent
    writable_root = Path(os.getenv("GAME_BENCH_DATA_ROOT", base_dir / "data"))
    db_path = Path(os.getenv("GAME_BENCH_DB_PATH", writable_root / "game_bench.db"))
    artifacts_root = Path(os.getenv("GAME_BENCH_ARTIFACTS_ROOT", writable_root / "artifacts"))
    return Settings(
        db_path=db_path,
        artifacts_root=artifacts_root,
        timezone=os.getenv("GAME_BENCH_TIMEZONE", "UTC"),
        default_budget_steps=int(os.getenv("GAME_BENCH_DEFAULT_STEPS", "20")),
        default_budget_seconds=int(os.getenv("GAME_BENCH_DEFAULT_SECONDS", "120")),
        base_dir=base_dir,
        admin_token=os.getenv("GAME_BENCH_ADMIN_TOKEN"),
        browser_provider=os.getenv("GAME_BENCH_BROWSER_PROVIDER", "local"),
        browserbase_api_key=os.getenv("BROWSERBASE_API_KEY"),
        browserbase_project_id=os.getenv("BROWSERBASE_PROJECT_ID"),
        browserbase_region=os.getenv("BROWSERBASE_REGION", "us-west-2"),
    )
