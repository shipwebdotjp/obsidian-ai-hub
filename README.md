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

## Usage

```bash
python -m obsidian_ai_hub --merge-inbox
python -m obsidian_ai_hub --make-target
python -m obsidian_ai_hub --notify-calendar-event
python -m obsidian_ai_hub --summerize-week
python -m obsidian_ai_hub --summerize-week --week-date 2026-06-15
python -m obsidian_ai_hub --review-draft
python -m obsidian_ai_hub --review-draft --review-week-date 2026-07-12
python -m obsidian_ai_hub --backup
python -m obsidian_ai_hub --sync-vault
python -m obsidian_ai_hub --screenshot
python -m obsidian_ai_hub --build-dashboard
```

The vault sync command indexes the full `VAULT_PATH` tree into `md-hybrid-search` and stores its SQLite/Chroma data outside the vault by default.

## Task Runner

The task runner reads scheduled jobs from `tasks/tasks.local.yml` when it exists, and falls back to `tasks/tasks.yml` otherwise. It also persists the last execution time in `tasks/last_run.json` so each task is only run once per matching schedule window.

Use `tasks/tasks.local.sample.yml` as the starting point for your own `tasks/tasks.local.yml`.

To create and send a weekly review draft on Sunday night, enable the
`review_draft_sunday_evening` example after replacing its project path. The
weekly note must contain an empty `result::` line; the generated draft is saved
immediately below it before the LINE Push notification is sent.

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

## Project Structure

- `src/obsidian_ai_hub/` — application code
- `config/` — configuration templates
- `tests/` — automated tests

## License

This project is licensed under the MIT License.

See the `LICENSE` file for details.
