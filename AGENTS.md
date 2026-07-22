# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project Overview

This is an Obsidian Daily Note Automation Tool (`obsidian-ai-hub`) that automates daily note management for Obsidian vaults on macOS. It handles inbox merging, daily target generation, weekly reviews, and calendar event notifications.

## Project Knowledge (`ai_wiki`)

- For work involving prior product or architecture decisions, first check [ai_wiki/00-Index.md](ai_wiki/00-Index.md).
- Record durable decisions, their context, and rationale in `ai_wiki/10-Decisions.md` when they affect future implementation choices. Use `ai_wiki/20-Worklog.md` only for temporary progress notes and handoffs.

## Key Commands

```bash
# Install dependencies
uv sync

# Run tests
uv run pytest tests/

# Run CLI commands
uv run python -m obsidian_ai_hub --merge-inbox
uv run python -m obsidian_ai_hub --make-target
uv run python -m obsidian_ai_hub --write-today-schedule
uv run python -m obsidian_ai_hub --summerize-week
uv run python -m obsidian_ai_hub --backup

# Memory Review Web UI (FastAPI + React)
make build-web                                # フロントエンドをビルド (cd frontend && npm ci && npm run build)
uv run python -m obsidian_ai_hub --serve      # 起動 (frontend/dist が必要)
# 環境変数で上書き:
#   MEMORY_REVIEW_HOST  (default 127.0.0.1; 非ループバック時 MEMORY_REVIEW_API_TOKEN 必須)
#   MEMORY_REVIEW_PORT  (default 8765)
#   MEMORY_REVIEW_API_TOKEN

# E2E / 探索
make e2e-serve                                # シード済み探索サーバーを起動 (http://127.0.0.1:8766)
make test-e2e                                 # フロントエンドビルド + ブラウザ E2E テスト実行

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
- Run database-writing tests only with `uv run pytest tests/`; never call test functions or seed `memory` / `research.db` from `uv run python -` or another ad-hoc Python command.
- Database-writing tests must use the `test_memory_db_path` fixture (the suite also applies it automatically). Do not patch a production path into `config.MEMORY_SQLITE_PATH`.
- For a one-off database check, inject a newly created temporary SQLite path before importing or calling application DB code. Do not use the configured database as a convenient test target.
- Do not delete or alter production data discovered during testing without explicit user authorization. See `docs/testing.md` for the test-environment contract and failure handling.

## E2E テスト / フロントエンド検証

- フロントエンド機能を変更したら、playwright-cli を使い `make e2e-serve` 環境で変更導線を実際に操作して確認してください。
- 重要な導線は `tests/e2e/` に自動テストとして追加してください。
- フロントエンドの作業完了時には必ず `make test-e2e` を実行し、回帰が起きていないことを確認してください。
- E2E テスト失敗時の診断情報（trace、スクリーンショット、console error、サーバーログ）は `test-results/e2e/` に出力されます。
