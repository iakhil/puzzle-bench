# game-bench

Daily browser-agent benchmark for logical puzzles.

## What is included

- A benchmark engine with pluggable model, puzzle, and sandbox adapters
- Local SQLite persistence for puzzle instances, runs, steps, artifacts, and daily leaderboard rows
- A FastAPI web app that shows the current leaderboard and run detail pages
- A local development path with fixture-based puzzle adapters and a deterministic mock model
- A production-oriented `BrowserbaseSandboxProvider` scaffold for remote browser sessions

## Quick start

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Health check:

```bash
curl -s http://127.0.0.1:8000/health
```

Seed fixture/demo data:

```bash
python3 -m app.cli seed-demo
```

Then open `http://127.0.0.1:8000`.

Run the live NYT Wordle benchmark in a real browser:

```bash
python3 -m app.cli run-live-wordle
```

Run Wordle with a real OpenAI model decision loop:

```bash
export OPENAI_API_KEY=...
export GAME_BENCH_HEADLESS=0
python3 -m app.cli run-live-wordle-openai
```

Run Wordle with a separate fully agentic browser-use loop where the model chooses low-level UI actions:

```bash
export OPENAI_API_KEY=...
export GAME_BENCH_AGENTIC_HEADLESS=0
export GAME_BENCH_AGENTIC_KEEP_OPEN_SECONDS=20
python3 -m app.cli run-live-wordle-openai-agentic
```

Trigger the agentic run through the internal admin endpoint:

```bash
export GAME_BENCH_ADMIN_TOKEN=...
curl -X POST http://127.0.0.1:8000/internal/runs/wordle-agentic \
  -H "Authorization: Bearer $GAME_BENCH_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"target_date":"2026-03-29"}'
```

## Commands

```bash
python3 -m app.cli seed-demo
python3 -m app.cli run-daily-benchmark
python3 -m app.cli run-live-wordle
python3 -m app.cli run-live-wordle-openai
python3 -m app.cli run-live-wordle-openai-agentic
python3 -m app.cli fetch-daily-puzzles
python3 -m app.cli recompute-leaderboard
```

## Environment

- `GAME_BENCH_DB_PATH`: SQLite database path. Defaults to `data/game_bench.db`
- `GAME_BENCH_DATA_ROOT`: Root for persistent app data. Defaults to `data`
- `GAME_BENCH_ARTIFACTS_ROOT`: Artifact and replay directory. Defaults to `<data-root>/artifacts`
- `GAME_BENCH_TIMEZONE`: Canonical benchmark timezone. Defaults to `UTC`
- `GAME_BENCH_ADMIN_TOKEN`: Bearer token for internal run-trigger endpoints
- `GAME_BENCH_HEADLESS`: Set to `0` to show the Playwright browser window. Defaults to `1`
- `GAME_BENCH_KEEP_OPEN_SECONDS`: How long a headed browser stays open after the run ends. Defaults to `10` when headed, `0` when headless
- `GAME_BENCH_BROWSER_PROVIDER`: Browser backend for live runs. Use `browserbase` in production, `local` in development. Defaults to `local`
- `GAME_BENCH_AGENTIC_HEADLESS`: Set to `0` to show the browser window for the separate computer-use agent. Defaults to `0`
- `GAME_BENCH_AGENTIC_KEEP_OPEN_SECONDS`: How long the separate agentic browser stays open after the run ends. Defaults to `15` when headed
- `GAME_BENCH_AGENTIC_MAX_TURNS`: Max computer-use turns before the separate agentic run aborts. Defaults to `30`
- `OPENAI_COMPUTER_MODEL`: OpenAI model for the separate agentic browser-use path. Defaults to `gpt-5.4`
- `BROWSERBASE_API_KEY`: Optional Browserbase API key
- `BROWSERBASE_PROJECT_ID`: Optional Browserbase project id
- `BROWSERBASE_REGION`: Browserbase region for remote sessions. Defaults to `us-west-2`

## Render deployment

This repo includes [render.yaml](/Users/akhilivaturi/dev/game-bench/render.yaml) for a single persistent-disk web service plus a daily cron trigger.

Production defaults:

- FastAPI app runs as a single Render web service
- SQLite and artifacts live under `/var/data`
- Browser automation uses Browserbase via `GAME_BENCH_BROWSER_PROVIDER=browserbase`
- The cron job calls the protected `/internal/runs/wordle-agentic` endpoint

Before enabling the cron service, set:

- `GAME_BENCH_BASE_URL`
- `GAME_BENCH_ADMIN_TOKEN`
- `OPENAI_API_KEY`
- `BROWSERBASE_API_KEY`
- `BROWSERBASE_PROJECT_ID`
