# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project Overview

This is an Obsidian Daily Note Automation Tool (`obsidian-ai-hub`) that automates daily note management for Obsidian vaults on macOS. It handles inbox merging, daily target generation, weekly reviews, and calendar event notifications.

## Key Commands

```bash
# Install dependencies
uv sync

# Run tests
uv run pytest tests/

# Run CLI commands
uv run python -m obsidian_ai_hub --merge-inbox
uv run python -m obsidian_ai_hub --make-target
uv run python -m obsidian_ai_hub --notify-calendar-event
uv run python -m obsidian_ai_hub --summerize-week
uv run python -m obsidian_ai_hub --backup

# Memory Review Web UI (FastAPI + React)
make build-web                                # フロントエンドをビルド (cd frontend && npm ci && npm run build)
uv run python -m obsidian_ai_hub --serve      # 起動 (frontend/dist が必要)
make dev-web                                  # 開発: Vite dev server (proxy -> :8765)
# 環境変数で上書き:
#   MEMORY_REVIEW_HOST  (default 127.0.0.1; 非ループバック時 MEMORY_REVIEW_API_TOKEN 必須)
#   MEMORY_REVIEW_PORT  (default 8765)
#   MEMORY_REVIEW_API_TOKEN

# Run scheduled tasks
./batch/scheduler.sh
```

## Architecture

### Core Modules

| File | Purpose |
|------|---------|
| `main.py` | CLI entry point with argparse - orchestrates all operations |
| `task_runner.py` | Cron-like scheduler that reads `tasks/tasks.yml` and tracks execution in `tasks/last_run.json` |
| `memory.py` | Long-term memory store (SQLite) + extraction/review/compile pipeline |

### Utility Package (`src/obsidian_ai_hub/utils/`)

| File | Purpose |
|------|---------|
| `config.py` | Centralized path and API key configuration |
| `llm_client.py` | Multi-provider LLM client (OpenAI, Gemini, Ollama, llama-cpp-python) |
| `reader.py` | Helper functions for reading daily/weekly notes |
| `extracter.py` | Extract content from notes (YAML frontmatter, subheaders) |

### Research Package (`src/obsidian_ai_hub/research/`)

| File | Purpose |
|------|---------|
| `db.py` | Research theme / job CRUD (SQLite) + activity JSONL reader |
| `dedup.py` | 3-stage dedup: exact match → SBERT → LLM |
| `runner.py` | Research execution engine (run_research, run_theme_research, save_research_to_vault) |
| `pipeline.py` | `create_theme_and_research`: candidate creation → dedup → immediate research |
| `suggest.py` | LLM-based theme suggestion from activity JSONL |
| `research_agent.py` | CLI shim (re-exports from `runner.py`) |
| `suggest_research_theme.py` | CLI shim (re-exports from `suggest.py`) |

### Web UI (`src/obsidian_ai_hub/web/`, `frontend/`)

| File | Purpose |
|------|---------|
| `web/app.py` | FastAPI factory, security (loopback vs token), static SPA delivery |
| `web/api.py` | `/api/v1/memories` ルート (list / detail / review / edit / batch-review) |
| `web/schemas.py` | Pydantic 入出力モデル |
| `web/service.py` | memory.py を呼ぶユースケース層 + threading.Lock |
| `frontend/` | Vite + React + TS + Tailwind CSS v4 |

### Configuration

- **Environment variables** (`.env`): `OPENAI_API_KEY`, `VAULT_PATH`, `MEMORY_SQLITE_PATH`, `MEMORY_REVIEW_API_TOKEN`, ...
- **YAML Config** `config/config.yml`
- **Task scheduling**: `tasks/tasks.local.yml` defines cron-like tasks (hourly, daily, weekly, monthly)

### macOS Native Integration

- Calendar access via **EventKit** (PyObjC)
- Reminders via **osascript**
- Audio transcription via **Whisper**

## Implementation Guidelines

- Modules directly under `src/obsidian_ai_hub/` should remain thin wrappers around `main` functions that are invoked by the CLI. Put concrete application logic in appropriate subpackages instead.
- Prefer straightforward failure over defensive error suppression. Do not add unnecessary robustness or catch exceptions merely to hide them; let unexpected errors surface naturally.

## Testing Guidelines
- This is a personal project; avoid writing detailed test codes for implementation details.
- Tests for frequently changing parts, such as string matching or the structure of output markdown, are not required.
- Write only the minimum necessary test code to check for critical errors or crashes.
- Tests must use isolated temporary databases (or explicitly injected test database paths) and must never modify the production database.
