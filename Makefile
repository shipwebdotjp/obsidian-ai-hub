# obsidian-ai-hub LaunchAgent 管理 Makefile

PLIST=~/Library/LaunchAgents/jp.shipweb.obsidian-ai-hub.plist
LABEL=jp.shipweb.obsidian-ai-hub
HITL_PLIST=~/Library/LaunchAgents/jp.shipweb.obsidian-ai-hub.hitl-worker.plist
HITL_LABEL=jp.shipweb.obsidian-ai-hub.hitl-worker
DOMAIN=gui/$(shell id -u)

.PHONY: install install-all install-hitl-worker start stop restart reload reload-hitl-worker enable enable-hitl-worker disable disable-hitl-worker status status-hitl-worker logs logs-hitl-worker errorlogs errorlogs-hitl-worker build-web dev-web jules-setup serve

# インストール（初回のみ）
install:
	bash ./install.sh

# 全サービスインストール
install-all:
	bash ./install.sh all

# hitl-worker のみインストール
install-hitl-worker:
	bash ./install.sh hitl-worker

# Jules VM用環境構築セットアップ
jules-setup:
	uv sync --frozen --all-extras
	npm --prefix frontend ci
	uv run playwright install --with-deps chromium

# 起動（登録済み前提）
start:
	launchctl start $(LABEL)

# 停止
stop:
	launchctl stop $(LABEL)

# 再起動（通常はこれ）
restart:
	launchctl kickstart -k $(DOMAIN)/$(LABEL)

# plist再読み込み（設定変更時）
reload:
	launchctl bootout $(DOMAIN) $(PLIST) || true
	launchctl bootstrap $(DOMAIN) $(PLIST)

# hitl-worker plist再読み込み
reload-hitl-worker:
	launchctl bootout $(DOMAIN) $(HITL_PLIST) || true
	launchctl bootstrap $(DOMAIN) $(HITL_PLIST)

# 有効化（自動起動ON）
enable:
	launchctl bootstrap $(DOMAIN) $(PLIST)

# hitl-worker 有効化
enable-hitl-worker:
	launchctl bootstrap $(DOMAIN) $(HITL_PLIST)

# 無効化（自動起動OFF）
disable:
	launchctl bootout $(DOMAIN) $(PLIST)

# hitl-worker 無効化
disable-hitl-worker:
	launchctl bootout $(DOMAIN) $(HITL_PLIST)

# 状態確認
status:
	launchctl list | grep $(LABEL) || true

# hitl-worker 状態確認
status-hitl-worker:
	launchctl list | grep $(HITL_LABEL) || true

# 標準ログ表示
logs:
	tail -f /tmp/obsidian_merge.log

# hitl-worker 標準ログ表示
logs-hitl-worker:
	tail -f /tmp/obsidian_hitl_worker.log

# エラーログ表示
errorlogs:
	tail -f /tmp/obsidian_merge.err

# hitl-worker エラーログ表示
errorlogs-hitl-worker:
	tail -f /tmp/obsidian_hitl_worker.err

# Memory Review Web UI のフロントエンドをビルド（dist を生成、CI 用は npm ci）
build-web:
	cd frontend && npm ci && npm run build

npm-build:
	cd frontend && npm run build

# Memory Review Web UI の開発サーバ（Vite + FastAPI を別portで起動する想定）
npm-dev:
	cd frontend && npm run dev

# Web UI の開発サーバ（OBSIDIAN_AI_HUB_API_TOKEN が必須。localhost bind 固定）
serve:
	uv run -m obsidian_ai_hub --serve --debug

# E2E 探索サーバー（Ctrl-C で停止）
e2e-serve: build-web
	uv run python -m obsidian_ai_hub.testing.e2e_server

# E2E テストを実行（フロントエンドをビルドしてからブラウザテスト）
test-e2e: build-web
	uv run pytest -m e2e