# obsidian-ai-hub LaunchAgent 管理 Makefile

PLIST=~/Library/LaunchAgents/jp.shipweb.obsidian-ai-hub.plist
LABEL=jp.shipweb.obsidian-ai-hub
HITL_PLIST=~/Library/LaunchAgents/jp.shipweb.obsidian-ai-hub.hitl-worker.plist
HITL_LABEL=jp.shipweb.obsidian-ai-hub.hitl-worker
WEB_PLIST=~/Library/LaunchAgents/jp.shipweb.obsidian-ai-hub.web.plist
WEB_LABEL=jp.shipweb.obsidian-ai-hub.web
DOMAIN=gui/$(shell id -u)

.PHONY: install install-all install-hitl-worker install-web start stop restart restart-base restart-hitl-worker restart-web reload reload-hitl-worker reload-web enable enable-hitl-worker enable-web disable disable-hitl-worker disable-web status status-hitl-worker status-web logs logs-hitl-worker logs-web errorlogs errorlogs-hitl-worker errorlogs-web build-web dev-web jules-setup serve serve-debug opcheck-serve

# インストール（初回のみ）
install:
	bash ./install.sh

# 全サービスインストール
install-all:
	bash ./install.sh all

# hitl-worker のみインストール
install-hitl-worker:
	bash ./install.sh hitl-worker

# Web サーバーのみインストール
install-web:
	bash ./install.sh web

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

# 再起動（通常はこれ）: job_runner + hitl-worker + Web サーバー
# Web を最後に置く: 未インストールでも job_runner / hitl-worker の再起動は完了させる。
restart: restart-base restart-hitl-worker restart-web

# job_runner 再起動
restart-base:
	launchctl kickstart -k $(DOMAIN)/$(LABEL)

# Web サーバー再起動（コード変更時）
restart-web:
	launchctl kickstart -k $(DOMAIN)/$(WEB_LABEL)

# hitl-worker 再起動（コード変更時）
restart-hitl-worker:
	launchctl kickstart -k $(DOMAIN)/$(HITL_LABEL)

# plist再読み込み（設定変更時）
reload:
	launchctl bootout $(DOMAIN) $(PLIST) || true
	launchctl bootstrap $(DOMAIN) $(PLIST)

# hitl-worker plist再読み込み
reload-hitl-worker:
	launchctl bootout $(DOMAIN) $(HITL_PLIST) || true
	launchctl bootstrap $(DOMAIN) $(HITL_PLIST)

# Web サーバー plist再読み込み
reload-web:
	launchctl bootout $(DOMAIN) $(WEB_PLIST) || true
	launchctl bootstrap $(DOMAIN) $(WEB_PLIST)

# 有効化（自動起動ON）
enable:
	launchctl bootstrap $(DOMAIN) $(PLIST)

# hitl-worker 有効化
enable-hitl-worker:
	launchctl bootstrap $(DOMAIN) $(HITL_PLIST)

# Web サーバー有効化
enable-web:
	launchctl bootstrap $(DOMAIN) $(WEB_PLIST)

# 無効化（自動起動OFF）
disable:
	launchctl bootout $(DOMAIN) $(PLIST)

# hitl-worker 無効化
disable-hitl-worker:
	launchctl bootout $(DOMAIN) $(HITL_PLIST)

# Web サーバー無効化
disable-web:
	launchctl bootout $(DOMAIN) $(WEB_PLIST)

# 状態確認
status:
	launchctl list | grep $(LABEL) || true

# hitl-worker 状態確認
status-hitl-worker:
	launchctl list | grep $(HITL_LABEL) || true

# Web サーバー状態確認
status-web:
	launchctl list | grep $(WEB_LABEL) || true

# 標準ログ表示
logs:
	tail -f /tmp/obsidian_merge.log

# hitl-worker 標準ログ表示
logs-hitl-worker:
	tail -f /tmp/obsidian_hitl_worker.log

# Web サーバー標準ログ表示
logs-web:
	tail -f /tmp/obsidian_web.log

# エラーログ表示
errorlogs:
	tail -f /tmp/obsidian_merge.err

# hitl-worker エラーログ表示
errorlogs-hitl-worker:
	tail -f /tmp/obsidian_hitl_worker.err

# Web サーバーエラーログ表示
errorlogs-web:
	tail -f /tmp/obsidian_web.err

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
	uv run -m obsidian_ai_hub --serve

serve-restart:
	lsof -ti :8765 | xargs kill
	uv run -m obsidian_ai_hub --serve

serve-debug:
	uv run -m obsidian_ai_hub --serve --debug

# 隔離サンドボックス（別DB・別Vault・別ポート、worker 有効。実データを変更しない）
opcheck-serve:
	bash ./scripts/opcheck_serve.sh
