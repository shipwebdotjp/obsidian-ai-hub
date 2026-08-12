# obsidian-ai-hub LaunchAgent 管理 Makefile

PLIST=~/Library/LaunchAgents/jp.shipweb.obsidian-ai-hub.plist
LABEL=jp.shipweb.obsidian-ai-hub
DOMAIN=gui/$(shell id -u)

.PHONY: install start stop restart reload enable disable status logs errorlogs build-web dev-web jules-setup

# インストール（初回のみ）
install:
	bash ./install.sh

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

# 有効化（自動起動ON）
enable:
	launchctl bootstrap $(DOMAIN) $(PLIST)

# 無効化（自動起動OFF）
disable:
	launchctl bootout $(DOMAIN) $(PLIST)

# 状態確認
status:
	launchctl list | grep $(LABEL) || true

# 標準ログ表示
logs:
	tail -f /tmp/obsidian_merge.log

# エラーログ表示
errorlogs:
	tail -f /tmp/obsidian_merge.err

# Memory Review Web UI のフロントエンドをビルド（dist を生成、CI 用は npm ci）
build-web:
	cd frontend && npm ci && npm run build

npm-build:
	cd frontend && npm install && npm run build

# Memory Review Web UI の開発サーバ（Vite + FastAPI を別portで起動する想定）
npm-dev:
	cd frontend && npm run dev

serve:
	OBSIDIAN_AI_HUB_ALLOW_TAILNET_TASKS=1 uv run -m obsidian_ai_hub --serve --debug

# E2E 探索サーバー（Ctrl-C で停止）
e2e-serve: build-web
	uv run python -m obsidian_ai_hub.testing.e2e_server

# E2E テストを実行（フロントエンドをビルドしてからブラウザテスト）
test-e2e: build-web
	uv run pytest -m e2e