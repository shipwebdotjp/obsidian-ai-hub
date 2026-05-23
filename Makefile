# obsidian-ai-hub LaunchAgent 管理 Makefile

PLIST=~/Library/LaunchAgents/jp.shipweb.obsidian-ai-hub.plist
LABEL=jp.shipweb.obsidian-ai-hub
DOMAIN=gui/$(shell id -u)

.PHONY: install start stop restart reload enable disable status logs errorlogs

# インストール（初回のみ）
install:
	bash ./install.sh

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
