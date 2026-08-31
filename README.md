# obsidian-ai-hub

obsidian-ai-hub is an automation toolkit for Obsidian daily-note workflows.

It helps with:
- organizing inbox items into a daily note
- generating daily and weekly summaries
- notifying you about today’s schedule and tasks
- collecting and organizing research topics
- connecting an Obsidian vault with external services

## Highlights

- Merge inbox content into a daily note
- Create daily targets and reminders
- Notify upcoming calendar events
- Back up vault data and related artifacts
- Keep secrets and public configuration separate

## Installation

1. Clone the repository.
2. Create your local configuration files:
   - `cp config/config.example.yml config/config.yml`
   - `cp .env.example .env`
3. Edit `config/config.yml` to match your vault paths and backup settings.
4. Edit `.env` to set API keys, tokens, and machine-specific paths.
5. Run the test suite:
   - `pytest tests/`

If you want to customize prompts, do not edit the shipped prompt file directly.
Instead, copy the standard prompt file to a local path of your choice and point
`llm.make_today_target.prompt_path` in `config/config.yml` to that copy.

Example:

```bash
cp config/prompts/make_today_target.md ~/Documents/custom-make_today_target.md
```

```yaml
llm:
  make_today_target:
    provider: ollama
    model: glm-4.7:cloud
    prompt_path: /Users/you/Documents/custom-make_today_target.md
```

### install to LaunchAgent
1. chmod +x install.sh
2. make install
3. make enable

### install HITL worker to LaunchAgent (常駐 HITL ワーカー)
1. make install-hitl-worker   # または bash ./install.sh hitl-worker
2. make enable-hitl-worker
3. make status-hitl-worker     # 動作確認
4. ログ確認: make logs-hitl-worker / make errorlogs-hitl-worker

両方まとめてインストールする場合: `make install-all`（`bash ./install.sh all`）

### HITL commands

The HITL (Human-in-the-Loop) system processes queued runs that require user
input or approval. Use `--hitl-dispatch` for a one-shot scan, or `--hitl-worker`
to run the resident worker loop (used by the LaunchAgent).

```bash
python -m obsidian_ai_hub --hitl-dispatch
python -m obsidian_ai_hub --hitl-worker
```

## Configuration

Use the following split to keep the project OSS-friendly:

`.env`
- secrets
- API keys and tokens
- personal absolute paths
- environment-specific values
- `LOCAL_MODEL_DIR` is used as the base download cache for local embedder models

`config/config.yml`
- non-sensitive application settings
- relative paths and filenames inside the vault
- backup targets
- default feature values
- vault index storage paths and embedder model name
- LLM provider/model selections and optional prompt overrides via `llm.<name>`
- research behavior and deep-research (GPT Researcher) settings via `research`
- coding workspace orchestrator and CLI agent paths via `coding`

Research provider/model selection is configured only in `config/config.yml`.
Keep provider credentials such as `OPENAI_API_KEY`, `TAVILY_API_KEY`, and
`OPENCODE_API_KEY` in `.env`.

### OpenCode Go Configuration

To use the OpenCode Go provider (`opencode_go`), configure `OPENCODE_API_KEY` in your `.env` file and set the provider in `config.yml`.

OpenCode Go models are automatically routed to either OpenAI-compatible or Anthropic-compatible clients based on their model ID prefixes:
- **OpenAI-compatible** (uses `ChatOpenAI`): `glm-`, `kimi-`, `deepseek-`, `mimo-`
- **Anthropic-compatible** (uses `ChatAnthropic`): `minimax-`, `qwen3.7-`, `qwen3.6-`

Example configuration:

```yaml
llm:
  make_today_target:
    provider: opencode_go
    model: deepseek-v3
```

### Coding Workspace Configuration

The coding workspace (`/coding` in the Web UI) uses a two-layer architecture:
an LLM orchestrator that plans and an external coding CLI agent (Codex/OpenCode)
that executes file edits and tests.

Configure it in `config/config.yml` under `coding`. Environment variables override
the YAML values if set.

```yaml
coding:
  orchestrator:
    provider: openai        # openai | ollama | gemini | opencode_go | local
    model: gpt-5.6-terra    # any model supported by the provider
  cli:
    codex_path: /path/to/your/codex        # default: codex (on PATH)
    opencode_path: /path/to/your/opencode  # default: opencode (on PATH)
```

Settings:

- `coding.orchestrator.provider` (`CODING_ORCHESTRATOR_PROVIDER`): LLM provider for the orchestrator. Default `openai`.
- `coding.orchestrator.model` (`CODING_ORCHESTRATOR_MODEL`): Model ID for the orchestrator. Default `gpt-5.6-terra`.
- `coding.cli.codex_path` (`CODING_CODEX_CLI_PATH`): Absolute path or binary name for the Codex CLI. Default `codex`.
- `coding.cli.opencode_path` (`CODING_OPENCODE_CLI_PATH`): Absolute path or binary name for the OpenCode CLI. Default `opencode`.

See `config/config.example.yml` for a complete example.

## Usage

```bash
python -m obsidian_ai_hub --merge-inbox
python -m obsidian_ai_hub --make-target
python -m obsidian_ai_hub --write-today-schedule
python -m obsidian_ai_hub --summerize-week
python -m obsidian_ai_hub --summerize-week --week-date 2026-06-15
python -m obsidian_ai_hub --review-draft
python -m obsidian_ai_hub --review-draft --review-week-date 2026-07-12
python -m obsidian_ai_hub --backup
python -m obsidian_ai_hub --sync-vault
python -m obsidian_ai_hub --sync-people
python -m obsidian_ai_hub --screenshot
```

The vault sync command indexes the full `VAULT_PATH` tree into `md-hybrid-search` and stores its SQLite/Chroma data outside the vault by default.

The `--sync-people` command merges unresolved person candidates and old duplicate `people` rows into the canonical person record that corresponds to each vault person note (based on `aliases` metadata).

### Additional CLI commands

Generate a monthly review for the previous month, or select a month with
`YYYY-MM`. A daily review uses the current daily note; pass `--day-date` to
pick a specific date.

```bash
python -m obsidian_ai_hub --summerize-month
python -m obsidian_ai_hub --summerize-month --month 2026-07
python -m obsidian_ai_hub --summerize-day
python -m obsidian_ai_hub --summerize-day --day-date 2026-07-15
```

The following commands notify today's schedule, synchronize the vault with the
configured Open WebUI knowledge base, or fully rebuild the vault-search index:

```bash
python -m obsidian_ai_hub --notify-today-schedule
python -m obsidian_ai_hub --sync-knowledge
python -m obsidian_ai_hub --rebuild-vault
```

### Planner commands

Generate AI planner proposals (calendar events or reminders) from recent notes,
summaries, and schedule context. Proposals are saved to the `planner_proposals`
table and a LINE notification is sent. A human must act on them via the Planner
screen; nothing is written to Apple Calendar/Reminders automatically.

```bash
python -m obsidian_ai_hub --generate-planner-proposals
```

### Research commands

Run research immediately with a required theme. `--context` adds background or
the reason for researching it, and `--output-style` accepts `short`, `medium`,
or `long`.

```bash
python -m obsidian_ai_hub --research-agent --theme "Local-first AI tools" \
  --context "Compare options for personal knowledge management" \
  --output-style medium
```

Add a theme to the research candidates, optionally with a research direction:

```bash
python -m obsidian_ai_hub --add-research-theme --theme "Local-first AI tools" \
  --direction "Compare privacy and offline capabilities"
```

Generate three research candidates from notes created during the last 30 days:

```bash
python -m obsidian_ai_hub --suggest-research-theme
```

`--research-agent`, `--add-research-theme`, and `--suggest-research-theme`
are mutually exclusive modes.

### Capture, activity, and vault search

Capture a screenshot from the selected macOS display (display `1` by default),
scan the frontmost LINE window for unread-message candidates, or record an
activity log:

```bash
python -m obsidian_ai_hub --screenshot --display 2
python -m obsidian_ai_hub --scan-line-inbox
python -m obsidian_ai_hub --log-activity
```

Search the vault index with a required query. `--k` controls the number of
results (default: `10`), `--search-mode` accepts `similarity`, `keyword`, or
`hybrid` (default), and `--json` prints machine-readable JSON.

```bash
python -m obsidian_ai_hub --vault-search --query "project planning" \
  --k 5 --search-mode hybrid --json
```

### Cleanup commands

Delete old records to keep the database compact. Both commands remove entries
older than 30 days.

```bash
python -m obsidian_ai_hub --cleanup-line-webhooks
python -m obsidian_ai_hub --cleanup-execution-logs
```

## Long-Term Memory

Long-term memory lets the assistant retain useful, reviewed information from
your notes, such as writing preferences, decision policies, commitments, and
recurring patterns. It is designed to keep AI-generated suggestions under your
control: new memories are always created as candidates and require review
before they can be used.

```mermaid
flowchart LR
    A[Weekly daily notes and structured data] --> B[AI memory candidates]
    B --> C[Review in the CLI or Web UI]
    C --> D[Approved long-term memories]
    D --> E[Context for daily target generation]
```

### Create memory candidates

Extract candidates from the most recently completed Monday--Sunday week:

```bash
uv run -m obsidian_ai_hub --memory-extract
```

To select a particular week, pass any date in that week:

```bash
uv run -m obsidian_ai_hub --memory-extract --week 2026-07-13
```

The extraction model considers the seven daily notes and their daily structured
records. Each note is included only up to `## AIによる要約`; activity logs are
not separately supplied. It produces candidates in these categories:
`preference`, `decision_policy`, `fact`, `commitment`, `pattern`, and
`episode`.

Each candidate includes supporting evidence, an extraction-confidence score,
and possible duplicate or replacement suggestions. Review the evidence rather
than treating the confidence score as an approval recommendation. The model is
instructed not to invent facts, to treat note contents as data rather than
instructions, and not to turn a one-off event into a permanent preference or
habit. A `pattern` requires evidence from at least two distinct days.

### Generate interview questions

Generate personalized interview questions from the selected week's daily notes.
Answers are collected via LINE or the Web UI and converted into memory
candidates automatically.

```bash
uv run -m obsidian_ai_hub --memory-interview
uv run -m obsidian_ai_hub --memory-interview --memory-interview-week 2026-07-13
```

### Review candidates with the CLI

Use the candidate ID to approve or reject it:

```bash
uv run -m obsidian_ai_hub --memory-review --id mem_20260713_51609b --approve
uv run -m obsidian_ai_hub --memory-review --id mem_20260713_3907c3 --reject
```

To correct the candidate text before accepting it, edit and approve in one
step:

```bash
uv run -m obsidian_ai_hub --memory-review \
  --id mem_20260713_f2ec1b \
  --edit \
  --content "Prefer concise Japanese responses."
```

Delete a memory permanently with its ID. The command asks for confirmation;
pass `--yes` to skip that prompt.

```bash
uv run -m obsidian_ai_hub --memory-delete --id mem_20260713_f2ec1b
uv run -m obsidian_ai_hub --memory-delete --id mem_20260713_f2ec1b --yes
```

### Review candidates in the Web UI

Build the Web UI once after installing the project dependencies:

```bash
make build-web
```

Start the local server:

```bash
uv run -m obsidian_ai_hub --serve
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). The **Memory** page lets
you inspect a candidate and its evidence, approve or reject individual
candidates, edit candidate text and review fields, and apply approval or
rejection to multiple selected candidates at once. The **Dashboard** page shows
daily, weekly, and monthly summaries with filters and a detail panel.

The server is local-only by default. If you intentionally make it available on
your network with `--serve-host`, set `OBSIDIAN_AI_HUB_API_TOKEN` first.
Use `--serve-port` to override the default port (`8765`):

```bash
uv run -m obsidian_ai_hub --serve --serve-host 127.0.0.1 --serve-port 9000
```

### Development mode

For development, start the API server with auto-reload and debug logging:

```bash
uv run -m obsidian_ai_hub --serve --debug
```

In a separate terminal, start the Vite dev server:

```bash
cd frontend && npm run dev
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173) in your browser. The Vite dev server proxies API requests to `http://127.0.0.1:8765`.

The `--debug` flag is a global development flag. When combined with `--serve`, it enables:
- **Auto-reload**: Uvicorn watches Python source files and restarts the server on changes.
- **Debug logging**: Both Uvicorn and the application use `debug` log level.

When used alone, `--debug` is accepted but does not change behavior (reserved for future use with other subcommands).

### Use approved memories in daily targets

Approved memories are compiled into a small reference section for daily target
generation. Only approved memories that are currently valid are included; old
or not-yet-active memories are excluded, and the most relevant entries are kept
within the configured context limit.

Inspect the context that would be used with:

```bash
uv run -m obsidian_ai_hub --memory-compile --for make-target
```

When you run `--make-target`, the compiled memory context is automatically
added to the LLM prompt. Other commands do not automatically use long-term
memory yet.

### Maintain approved memories

Run a diagnostic maintenance pass on all approved long-term memories. The
command groups memories by key, exact content, or vector similarity, then uses
an LLM to propose merge, correct, or expire actions. Proposals are registered
as a HITL run for review.

```bash
uv run -m obsidian_ai_hub --memory-maintain
```

### Generate Copilot instructions (Explanation document)

You can summarize all currently valid, approved memories using an LLM to generate or completely replace the profile instruction files for Copilot.

To render the profile, run:

```bash
uv run -m obsidian_ai_hub --render-copilot-profile
```

On successful execution, this command completely overwrites the following 7 files under your vault (any existing manual/handwritten content in these files will be lost and replaced):
- `copilot/AI_README.md`: General profile and cross-cutting guidelines for AI.
- `copilot/core/values.md`: Explicitly stated values/priorities.
- `copilot/core/response_style.md`: Preference for response/dialog style.
- `copilot/core/decision_policy.md`: Decision policy/priorities.
- `copilot/core/risk_tolerance.md`: Risk tolerance/prudence policy.
- `copilot/core/memory_rules.md`: Explicitly stated memory management rules.
- `copilot/core/current_projects.md`: Current ongoing projects/commitments.

If there are no valid approved memories in the database, the command will still generate all 7 files with the fallback content "現時点で承認済みメモリなし" (No approved memory at this moment).

To customize the LLM provider, model, or prompt path for rendering, add the `renderer` settings under the `memory` section in your `config/config.yml`. Note that only the provider and model inherit from the memory extractor configuration if left unconfigured, while `prompt_path` instead defaults to `config/prompts/memory_render.md`.

```yaml
memory:
  renderer:
    provider: openai
    model: gpt-4o
    prompt_path: /Users/you/Documents/custom-memory-render.md
```

If provider or model is not configured, it will inherit your memory extractor configuration.

### Memory settings

Add optional settings to `config/config.yml` to change the context size or the
model used for extraction:

```yaml
memory:
  context_max_tokens: 800
  extractor:
    provider: ollama
    model: glm-4.7:cloud
    # prompt_path: /Users/you/Documents/custom-memory-extract.md
```

When the extractor settings are omitted, the daily-target LLM provider and
model are used.

## Healthcare Data

Apple Health (HealthKit) data is stored in a dedicated SQLite database,
separate from the main memory database. This keeps the main database compact
and avoids impacting VACUUM/backup operations.

### Data location

The healthcare database is stored at:

```
~/.config/obsidian-ai-hub/healthcare.sqlite3
```

Override with `HEALTHCARE_SQLITE_PATH` environment variable or
`healthcare.sqlite_path` in `config/config.yml`.

### Import Apple Health data

1. On your iPhone, open the Health app → tap your profile → **Export All Health
   Data**.
2. Unzip the exported file to a directory (e.g.,
   `~/.config/obsidian-ai-hub/healthcare/apple_health_export`).
3. Run the import command:

```bash
python -m obsidian_ai_hub --import-apple-health
```

Specify a custom export directory or batch size:

```bash
python -m obsidian_ai_hub --import-apple-health \
  --healthcare-export-dir /path/to/apple_health_export \
  --healthcare-batch-size 10000
```

Preview the import without writing to the database:

```bash
python -m obsidian_ai_hub --import-apple-health --healthcare-dry-run
```

### Configuration

Add to `config/config.yml`:

```yaml
healthcare:
  sqlite_path: /Users/you/.config/obsidian-ai-hub/healthcare.sqlite3
  export_dir: /Users/you/.config/obsidian-ai-hub/healthcare/apple_health_export
```

Or use environment variables: `HEALTHCARE_SQLITE_PATH`, `HEALTHCARE_EXPORT_DIR`.

The import is idempotent; re-running it will not duplicate records.

## Task Runner

The task runner reads scheduled jobs from `tasks/tasks.local.yml` when it exists, and falls back to `tasks/tasks.yml` otherwise. It also persists the last execution time in `tasks/last_run.json` so each task is only run once per matching schedule window.

Use `tasks/tasks.local.sample.yml` as the starting point for your own `tasks/tasks.local.yml`.

To create and send a weekly review draft on Sunday night, enable the
`review_draft_sunday_evening` example after replacing its project path. The
weekly note must contain an empty `result::` line; the generated draft is saved
immediately below it before the LINE Push notification is sent.

For near-real-time Inbox processing, schedule `merge_inbox` with
`type: minutely` and `second: 0`. The task runner LaunchAgent already fires
every 60 seconds, so inbox files are usually merged within about a minute of
save. Files whose `mtime` is within the last 5 seconds are deferred to the
next run (a single stat check, no wait), which avoids racing with an
in-progress write. iCloud-offloaded files are still downloaded and awaited up
to 60 seconds, and Whisper is loaded only inside that CLI process and released
when it exits.

Each task entry uses this shape:

```yaml
- id: example
  enabled: true
  schedule:
    type: hourly
    minute: 0
  command: echo "hello"
```

Supported `schedule.type` values are `minutely`, `hourly`, `daily`, `weekly`, and `monthly`.

`schedule` fields can be written as:
- a single number, for example `minute: 0`
- a list, for example `minute: [0, 30]`
- a comma-separated string, for example `minute: "0,30"`
- a range, for example `hour: "8-18"`
- a stepped range, for example `minute: "*/15"` or `hour: "8-18/2"`
- `*` where allowed, such as `weekday: "*"`

The runner understands `second`, `minute`, `hour`, `day`, and `weekday`. Missing fields fall back to sensible defaults, such as `minute: 0` and `weekday: "*"`.

Commands are executed without a shell. Plain argv-style commands are supported, and you can chain a directory change with `cd /path && ...`. Shell operators like pipes, redirects, and environment expansion are not interpreted.

### Task Runner Web UI (Token)

The Web UI provides a dedicated **Task Management** page where you can manage, add, edit, and disable tasks visually:
- **Access Control:** All Web API endpoints — including the task configuration APIs (`GET`/`PUT` `/api/v1/task-config`) — require a valid `Authorization: Bearer <token>` header matching the `OBSIDIAN_AI_HUB_API_TOKEN` environment variable. Authentication is unconditional regardless of the connecting client (loopback, LAN, or public), and the app is bound to localhost with TLS terminated at a reverse proxy or tunnel.
- **Structure Validation:** ID uniqueness, valid cron ranges/values, relevant fields per schedule type, and command execution structures are validated prior to saving. Syntax/meaning errors return `422 Unprocessable Entity`.
- **Atomic Operations & Optimistic Locking:** Settings are written atomically using temporary files and `os.replace` to prevent corruption. If multiple sessions try to modify configuration concurrently, the server throws `409 Conflict`, prompting you to refresh.
- **No Retrospective Execution (Arming):** When you add a task, re-enable it, or modify its schedule/command, the task is "armed" with the current save time, preventing retrospective execution of past run frames.
- **Detailed Mode parsing:** When editing custom commands in detailed mode, the UI displays the backend parsed representation (shlex argv list) to prevent misinterpretation of command execution paths. Note that comments in `tasks.local.yml` are not preserved during structured saves.

## Project Structure

- `src/obsidian_ai_hub/` — application code
- `config/` — configuration templates
- `tests/` — automated tests

## License

This project is licensed under the MIT License.

See the `LICENSE` file for details.

## Test mode

Run CLI commands safely in an isolated environment:

```bash
ENV=test uv run python -m obsidian_ai_hub --merge-inbox
```

See `docs/testing.md` for full details.
