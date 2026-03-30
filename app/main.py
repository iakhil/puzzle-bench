from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import threading
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request as UrlRequest, urlopen

from fastapi import Body, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

try:
    from .agentic_browser import run_agentic_wordle_openai
    from .config import get_settings
    from .db import init_db
    from .repository import fetch_leaderboard_rows, fetch_recent_runs, fetch_run_detail
except ImportError:  # pragma: no cover - direct script execution fallback
    import sys

    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from app.agentic_browser import run_agentic_wordle_openai
    from app.config import get_settings
    from app.db import init_db
    from app.repository import fetch_leaderboard_rows, fetch_recent_runs, fetch_run_detail


settings = get_settings()
app = FastAPI(title="game-bench", version="0.1.0")
template_dir = Path(__file__).resolve().parent.parent / "templates"
static_dir = Path(__file__).resolve().parent.parent / "static"
templates = Jinja2Templates(directory=str(template_dir))
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
artifact_root = settings.artifacts_root
agentic_run_lock = threading.Lock()


def artifact_url(path: str | None) -> str | None:
    if not path:
        return None
    if path.startswith("https://") or path.startswith("http://"):
        session_id = _browserbase_session_id(path)
        return f"/replays/browserbase/{session_id}" if session_id else path
    try:
        relative = Path(path).resolve().relative_to(artifact_root.resolve())
    except ValueError:
        return None
    return f"/artifacts/{relative.as_posix()}"


def _browserbase_session_id(path: str) -> str | None:
    parsed = urlparse(path)
    if parsed.netloc not in {"browserbase.com", "www.browserbase.com"}:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[0] == "sessions":
        return parts[1]
    return None


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    app.state.agentic_active_run = None


@app.get("/health", response_class=JSONResponse)
def healthcheck() -> JSONResponse:
    return JSONResponse({"ok": True, "active_run": app.state.agentic_active_run})


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
            "artifact_url": artifact_url,
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
            "artifact_url": artifact_url,
        },
    )


@app.get("/artifacts/{artifact_path:path}")
def artifact_file(artifact_path: str) -> FileResponse:
    target = (artifact_root / artifact_path).resolve()
    if artifact_root.resolve() not in target.parents and target != artifact_root.resolve():
        raise HTTPException(status_code=404, detail="Artifact not found")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    return FileResponse(target)


@app.get("/replays/browserbase/{session_id}", response_class=HTMLResponse)
def browserbase_replay_page(request: Request, session_id: str) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "browserbase_replay.html",
        {
            "request": request,
            "session_id": session_id,
        },
    )


@app.get("/replays/browserbase/{session_id}.json", response_class=JSONResponse)
def browserbase_replay_json(session_id: str) -> JSONResponse:
    if not settings.browserbase_api_key:
        raise HTTPException(status_code=503, detail="Browserbase API key is not configured")
    request = UrlRequest(
        f"https://api.browserbase.com/v1/sessions/{session_id}/recording",
        headers={"X-BB-API-Key": settings.browserbase_api_key},
        method="GET",
    )
    try:
        with urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=502, detail=f"Browserbase recording fetch failed: {detail}") from exc
    except URLError as exc:
        raise HTTPException(status_code=502, detail=f"Browserbase recording fetch failed: {exc.reason}") from exc
    return JSONResponse(payload)


@app.post("/internal/runs/wordle-agentic", response_class=JSONResponse)
def trigger_wordle_agentic_run(
    payload: dict[str, Any] | None = Body(default=None),
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    if not settings.admin_token:
        raise HTTPException(status_code=503, detail="Admin token is not configured")
    expected = f"Bearer {settings.admin_token}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Invalid admin token")
    if not agentic_run_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="An agentic run is already in progress")

    requested_date = None
    if payload and payload.get("target_date"):
        requested_date = datetime.fromisoformat(str(payload["target_date"])).date()
    else:
        requested_date = datetime.now(timezone.utc).date()

    def _run() -> None:
        try:
            result = run_agentic_wordle_openai(target_date=requested_date)
            app.state.agentic_active_run = {"run_id": result.run_id, "status": result.solve_status, "completed": True}
        except Exception as exc:
            app.state.agentic_active_run = {
                "run_id": run_preview_id,
                "status": "failed",
                "error": str(exc),
                "target_date": requested_date.isoformat(),
            }
        finally:
            agentic_run_lock.release()

    run_preview_id = f"queued-{requested_date.isoformat()}"
    app.state.agentic_active_run = {"run_id": run_preview_id, "status": "running", "target_date": requested_date.isoformat()}
    threading.Thread(target=_run, daemon=True).start()
    return JSONResponse({"queued": True, "target_date": requested_date.isoformat(), "run": app.state.agentic_active_run})


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
                "representative_run_id": row["representative_run_id"],
                "representative_video_path": row["representative_video_path"] or None,
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
