# ACP PoC harness (Phase 0)

PoC専用。アプリ本体・DBに接続しない。stdlib のみ。

## 配置

- `acp_harness.py` — transport層（将来の共通Clientへの切り出し候補）
- `run_poc.py` — シナリオ駆動（initialize / new-prompt / cancel / resume / permission）
- `profiles/*.json` — provider差分（argv・auth方針）。共通層に分岐を置かない
- `node_modules/` — `codex-acp` のpin導入先（`@agentclientprotocol/codex-acp@1.11.0`、save-exact）。
  production run中の暗黙download禁止に対応

## 実行

```bash
# 無料: initialize のみ
python3 run_poc.py --profile opencode --scenario initialize
python3 run_poc.py --profile codex --scenario initialize

# 有料（LLMを叩く）: 明示指定時のみ
python3 run_poc.py --profile opencode --scenario new-prompt
python3 run_poc.py --profile codex --scenario cancel --cancel-kind session
python3 run_poc.py --profile codex --scenario cancel --cancel-kind cancel_request
python3 run_poc.py --profile opencode --scenario resume
python3 run_poc.py --profile opencode --scenario permission
```

- 認証: `~/.config/obsidian-ai-hub/acp-poc.env`（600）を子プロセス環境にのみ合成。
  artifactには変数名のみ記録し、値は `***REDACTED***` 化＋書込み前リーク検査あり
- Client capabilityは最小（fs/terminal/elicitation非advertise）。
  permissionは既定deny（reject系optionを選択、なければ `-32601` 応答）
- 一時Git repo（`git init` in mkdtemp）のみ使用。前後で `git status` を記録
- artifact: `docs/acp/artifacts/<agent>-<version>-<date>/<scenario>-*.json`

## 自己テスト

```bash
uv run pytest tools/acp_poc/tests/
```

fake agent（`fake_agent.py`）相手に、initialize/new/prompt相関・deny応答・
cancel・redact・orphanなし終了を検証する。外部通信なし。
