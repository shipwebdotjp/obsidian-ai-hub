# obsidian-ai-hub

obsidian-ai-hub is an automation toolkit for Obsidian daily-note workflows.

It helps with:

- organizing inbox items into a daily note
- generating daily, weekly, and monthly summaries
- notifying you about today's schedule and tasks
- collecting and organizing research topics
- retaining reviewed long-term memories for generated output
- connecting an Obsidian vault with external services (calendar, LINE, LLMs)

## Documentation

The full user guide lives here:

**https://aihub.shipweb.jp**

- [Getting started](https://aihub.shipweb.jp/getting-started/overview) — product overview, installation, server and Web UI
- [Daily workflows](https://aihub.shipweb.jp/daily/cli-basics) — CLI basics and day-to-day commands
- [Features](https://aihub.shipweb.jp/features/memory) — memory, research, agents, jobs, healthcare, and more
- [Settings](https://aihub.shipweb.jp/settings/configuration) — `.env` and `config/config.yml`
- [Operations](https://aihub.shipweb.jp/operations) — running the server and workers
- [CLI reference](https://aihub.shipweb.jp/reference/cli) — every command and flag

Detailed usage is documented in the user guide; this README stays as a
project overview.

## Quick start

```bash
git clone <repository-url>
cd obsidian-daily-merge
uv sync
cp config/config.example.yml config/config.yml
cp .env.example .env
make build-web
uv run -m obsidian_ai_hub --serve
```

Open `http://127.0.0.1:8765` in your browser. See the
[installation guide](https://aihub.shipweb.jp/getting-started/installation)
for configuration details (`.env`, `VAULT_PATH`, API tokens, LaunchAgent
setup).

## Configuration

Configuration is split to keep secrets out of version control:

- `.env` — secrets, API keys, tokens, machine-specific paths
- `config/config.yml` — non-sensitive application settings

See [settings](https://aihub.shipweb.jp/settings/configuration).

## Project structure

- `src/obsidian_ai_hub/` — application code
- `config/` — configuration templates
- `tests/` — automated tests (`uv run pytest tests/`)
- `user-guide/` — documentation source for https://aihub.shipweb.jp
- `frontend/` — Web UI source

## License

This project is licensed under the MIT License.

See the `LICENSE` file for details.
