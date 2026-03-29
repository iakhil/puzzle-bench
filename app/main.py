from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

try:
    from .config import get_settings
    from .db import init_db
    from .repository import fetch_leaderboard_rows, fetch_recent_runs, fetch_run_detail
except ImportError:  # pragma: no cover - direct script execution fallback
    import sys

    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from app.config import get_settings
    from app.db import init_db
    from app.repository import fetch_leaderboard_rows, fetch_recent_runs, fetch_run_detail


settings = get_settings()
app = FastAPI(title="game-bench", version="0.1.0")
template_dir = Path(__file__).resolve().parent.parent / "templates"
static_dir = Path(__file__).resolve().parent.parent / "static"
templates = Jinja2Templates(directory=str(template_dir))
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/", response_class=HTMLResponse)
def homepage(request: Request) -> HTMLResponse:
    target_date = datetime.now(timezone.utc).date()
    leaderboard_rows = fetch_leaderboard_rows(target_date)
    recent_runs = fetch_recent_runs()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
            "target_date": target_date.isoformat(),
            "leaderboard_rows": leaderboard_rows,
            "recent_runs": recent_runs,
        },
    )


@app.get("/runs/{run_id}", response_class=HTMLResponse)
def run_detail_page(request: Request, run_id: str) -> HTMLResponse:
    detail = fetch_run_detail(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return templates.TemplateResponse(
        request,
        "run_detail.html",
        {
            "request": request,
            "detail": detail,
            "json": json,
        },
    )


@app.get("/leaderboard", response_class=JSONResponse)
def leaderboard_api(date: str | None = None) -> JSONResponse:
    target_date = datetime.fromisoformat(date).date() if date else datetime.now(timezone.utc).date()
    rows = fetch_leaderboard_rows(target_date)
    return JSONResponse(
        [
            {
                "leaderboard_date": row["leaderboard_date"],
                "provider": row["provider"],
                "model_id": row["model_id"],
                "average_score": row["average_score"],
                "solve_rate": row["solve_rate"],
                "puzzle_count": row["puzzle_count"],
                "average_latency_ms": row["average_latency_ms"],
                "average_cost_usd": row["average_cost_usd"],
            }
            for row in rows
        ]
    )


@app.get("/runs/{run_id}.json", response_class=JSONResponse)
def run_detail_api(run_id: str) -> JSONResponse:
    detail = fetch_run_detail(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Run not found")
    payload = {
        "run": dict(detail["run"]),
        "steps": [dict(row) for row in detail["steps"]],
        "artifacts": [dict(row) for row in detail["artifacts"]],
    }
    return JSONResponse(payload)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
