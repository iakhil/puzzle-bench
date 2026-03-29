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
python3 -m app.cli run-live-wordle-openai
```

## Commands

```bash
python3 -m app.cli seed-demo
python3 -m app.cli run-daily-benchmark
python3 -m app.cli run-live-wordle
python3 -m app.cli run-live-wordle-openai
python3 -m app.cli fetch-daily-puzzles
python3 -m app.cli recompute-leaderboard
```

## Environment

- `GAME_BENCH_DB_PATH`: SQLite database path. Defaults to `data/game_bench.db`
- `GAME_BENCH_TIMEZONE`: Canonical benchmark timezone. Defaults to `UTC`
- `BROWSERBASE_API_KEY`: Optional Browserbase API key
- `BROWSERBASE_PROJECT_ID`: Optional Browserbase project id
