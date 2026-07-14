#!/usr/bin/env python3
import argparse
import logging
from datetime import datetime

from obsidian_ai_hub import (
    do_backup,
    make_today_target,
    notify_calendar_event,
    notify_today_schedule,
    obsidian_inbox_merge,
    rebuild_valut,
    research_agent,
    dashboard,
    suggest_research_theme,
    summerize_day,
    summerize_week,
    summerize_month,
    sync_knowledge,
    sync_valut,
    take_screenshot,
    scan_line_inbox,
    search_obsidian_vault,
    review_draft,
)
from obsidian_ai_hub.handler import add_research_theme

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


def main():
    parser = argparse.ArgumentParser(description="Obsidian Daily Merge Tool")
    parser.add_argument(
        "--merge-inbox",
        action="store_true",
        help="Obsidian の Inbox を DailyNote にマージ"
    )
    parser.add_argument(
        "--make-target",
        action="store_true",
        help="過去のDailyNoteから今日の目標を作成し書き込み"
    )
    parser.add_argument(
        "--notify-calendar-event",
        action="store_true",
        help="今日のカレンダーイベントと定期リマインダをLINEに通知"
    )
    parser.add_argument(
        "--summerize-week",
        action="store_true",
        help="週次レビューを生成"
    )
    parser.add_argument(
        "--review-draft",
        action="store_true",
        help="空の result:: を持つ週次ノートにレビュー下書きを保存しLINEへ通知"
    )
    def validate_date(value):
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            raise argparse.ArgumentTypeError(
                f"Invalid date format: {value}. Expected YYYY-MM-DD"
            )
        return value

    parser.add_argument(
        "--week-date",
        type=validate_date,
        help="--summerize-week で対象とする週の日付 (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--review-week-date",
        type=validate_date,
        help="--review-draft で対象とする週の日付 (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--summerize-month",
        action="store_true",
        help="月次レビューを生成"
    )
    parser.add_argument(
        "--summerize-day",
        action="store_true",
        help="日次レビューを生成"
    )
    parser.add_argument(
        "--build-dashboard",
        action="store_true",
        help="静的ダッシュボード用のJSON/HTMLを生成"
    )
    parser.add_argument(
        "--dashboard-year",
        type=int,
        action="append",
        help="--build-dashboard で再生成する対象年。省略時は利用可能な全年度を対象にする"
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help="指定されたフォルダをバックアップ（rsync）"
    )
    parser.add_argument(
        "--notify-today-schedule",
        action="store_true",
        help="今日の予定をLINEに通知"
    )
    parser.add_argument(
        "--sync-knowledge",
        action="store_true",
        help="Obsidian VaultをOpen Web UIの知識ベースと同期"
    )
    parser.add_argument(
        "--sync-vault",
        action="store_true",
        help="Obsidian Vaultをmd-hybrid-searchのインデックスと同期"
    )
    parser.add_argument(
        "--rebuld-vault",
        action="store_true",
        help="Obsidian Vaultのmd-hybrid-searchインデックスを再構築"
    )
    parser.add_argument(
        "--research-agent",
        action="store_true",
        help="リサーチ候補テーマリストの未調査テーマを調査して保存"
    )
    parser.add_argument(
        "--add-research-theme",
        action="store_true",
        help="リサーチ候補テーマリストにテーマを追記"
    )
    parser.add_argument(
        "--suggest-research-theme",
        action="store_true",
        help="最近30日のノートから研究候補3件を生成して追記"
    )
    parser.add_argument(
        "--screenshot",
        action="store_true",
        help="macOSのスクリーンショットを撮影してInboxに保存"
    )
    parser.add_argument(
        "--scan-line-inbox",
        action="store_true",
        help="LINE の前面ウィンドウをスキャンして未読候補を抽出"
    )
    parser.add_argument(
        "--log-activity",
        action="store_true",
        help="アクティビティログを記録（ウィンドウ情報、スクリーンショット、OCR、要約）"
    )
    parser.add_argument(
        "--vault-search",
        action="store_true",
        help="Obsidian Vault を検索"
    )
    parser.add_argument(
        "--query",
        type=str,
        help="--vault-search で使用する検索クエリ"
    )
    parser.add_argument(
        "--k",
        type=int,
        default=10,
        help="--vault-search の検索結果件数 (デフォルト: 10)"
    )
    parser.add_argument(
        "--search-mode",
        choices=("similarity", "keyword", "hybrid"),
        default="hybrid",
        help="--vault-search の検索モード (デフォルト: hybrid)"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="結果を JSON 形式で出力"
    )
    parser.add_argument(
        "--display",
        type=int,
        default=1,
        help="--screenshot で使用するディスプレイ番号（デフォルト: 1）"
    )
    parser.add_argument(
        "--theme",
        type=str,
        help="--research-agent で即時調査するテーマ名、または --add-research-theme に付けるテーマ名"
    )
    parser.add_argument(
        "--context",
        type=str,
        help="--research-agent に渡す補足文脈。自分の前提知識や調べたい理由を入れる"
    )
    parser.add_argument(
        "--output-style",
        choices=("short", "medium", "long"),
        help="--research-agent の出力長を切り替える"
    )
    def validate_month(value):
        import re
        if not re.match(r'^\d{4}-\d{2}$', value):
            raise argparse.ArgumentTypeError(f"Invalid month format: {value}. Expected YYYY-MM")
        return value

    parser.add_argument(
        "--month",
        type=validate_month,
        help="--summerize-month で指定する対象月 (YYYY-MM)"
    )
    # Memory commands
    parser.add_argument(
        "--memory-extract",
        action="store_true",
        help="週次ノートから長期記憶候補を抽出"
    )
    parser.add_argument(
        "--week",
        type=validate_date,
        help="--memory-extract の対象週に含まれる日付 (YYYY-MM-DD)。省略時は直近の完了週"
    )
    parser.add_argument(
        "--memory-review",
        action="store_true",
        help="長期記憶候補をレビュー"
    )
    parser.add_argument(
        "--id",
        type=str,
        help="レビュー対象の記憶ID (e.g. mem_...)"
    )
    parser.add_argument(
        "--approve",
        action="store_true",
        help="記憶候補を承認"
    )
    parser.add_argument(
        "--reject",
        action="store_true",
        help="記憶候補を却下"
    )
    parser.add_argument(
        "--edit",
        action="store_true",
        help="記憶候補を編集して承認"
    )
    parser.add_argument(
        "--content",
        type=str,
        help="編集時の新しい記憶の本文"
    )
    parser.add_argument(
        "--memory-compile",
        action="store_true",
        help="長期記憶コンテキストをコンパイル（診断用）"
    )
    parser.add_argument(
        "--render-copilot-profile",
        action="store_true",
        help="承認済み長期記憶からCopilot説明書（7ファイル）を生成・更新"
    )
    parser.add_argument(
        "--for",
        dest="for_purpose",
        type=str,
        help="長期記憶コンパイルの目的 (e.g. make-target)"
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Memory Review Web UI (FastAPI + React) を起動"
    )
    parser.add_argument(
        "--serve-host",
        type=str,
        default=None,
        help="Web UI のバインドアドレス (既定: 127.0.0.1; 非ループバック時は MEMORY_REVIEW_API_TOKEN 必須)"
    )
    parser.add_argument(
        "--serve-port",
        type=int,
        default=None,
        help="Web UI の待ち受けポート (既定: 8765)"
    )
    args = parser.parse_args()
    ran = False

    def run_and_log(fn, name: str):
        print(f"[START] {name} at {datetime.now().isoformat()}")
        try:
            fn()
        except Exception as e:
            # surface the error but continue to ensure we always print END for debugging
            print(f"[ERROR] {name}: {type(e).__name__}")
            raise
        finally:
            print(f"[END] {name} at {datetime.now().isoformat()}")

    if args.research_agent and args.add_research_theme:
        parser.error("--research-agent and --add-research-theme cannot be combined")
    if args.suggest_research_theme and (args.research_agent or args.add_research_theme):
        parser.error("--suggest-research-theme cannot be combined with other research modes")
    if args.theme and not (args.research_agent or args.add_research_theme):
        parser.error("--theme requires --research-agent or --add-research-theme")
    if args.context and not args.research_agent:
        parser.error("--context requires --research-agent")
    if args.output_style and not args.research_agent:
        parser.error("--output-style requires --research-agent")
    if args.vault_search and not args.query:
        parser.error("--vault-search requires --query")
    if args.query and not args.vault_search:
        parser.error("--query requires --vault-search")

    # Memory validations
    if args.week and not args.memory_extract:
        parser.error("--week requires --memory-extract")
    if args.memory_review:
        if not args.id:
            parser.error("--memory-review requires --id ID")
        actions_count = sum([args.approve, args.reject, args.edit])
        if actions_count != 1:
            parser.error("--memory-review requires exactly one action: --approve, --reject, or --edit")
        if args.edit and not args.content:
            parser.error("--edit action requires --content")
    if args.memory_compile and not args.for_purpose:
        parser.error("--memory-compile requires --for PURPOSE")
    if args.for_purpose and not args.memory_compile:
        parser.error("--for requires --memory-compile")

    research_kwargs = {}
    if args.context is not None:
        research_kwargs["context"] = args.context
    if args.output_style is not None:
        research_kwargs["output_style"] = args.output_style

    if args.merge_inbox:
        run_and_log(obsidian_inbox_merge.main, "merge_inbox")
        ran = True
    if args.notify_calendar_event:
        run_and_log(notify_calendar_event.main, "notify_calendar_event")
        ran = True
    if args.make_target:
        run_and_log(make_today_target.main, "make_target")
        ran = True
    if args.summerize_week:
        run_and_log(lambda: summerize_week.main(args.week_date), "summerize_week")
        ran = True
    if args.review_draft:
        run_and_log(lambda: review_draft.main(args.review_week_date), "review_draft")
        ran = True
    if args.summerize_month:
        run_and_log(lambda: summerize_month.main(args.month), "summerize_month")
        ran = True
    if args.summerize_day:
        run_and_log(summerize_day.main, "summerize_day")
        ran = True
    if args.build_dashboard:
        run_and_log(lambda: dashboard.build_dashboard(args.dashboard_year), "build_dashboard")
        ran = True
    if args.backup:
        run_and_log(do_backup.main, "backup")
        ran = True
    if args.notify_today_schedule:
        run_and_log(notify_today_schedule.main, "notify_today_schedule")
        ran = True
    if args.sync_knowledge:
        run_and_log(sync_knowledge.main, "sync_knowledge")
        ran = True
    if args.sync_vault:
        run_and_log(sync_valut.main, "sync_vault")
        ran = True
    if getattr(args, "rebuld_vault"):
        run_and_log(rebuild_valut.main, "rebuild_vault")
        ran = True
    if args.research_agent:
        if args.theme:
            run_and_log(
                lambda: research_agent.main(args.theme, **research_kwargs),
                "research_agent",
            )
        else:
            run_and_log(lambda: research_agent.main(**research_kwargs), "research_agent")
        ran = True
    if args.add_research_theme:
        if not args.theme:
            raise ValueError("--add-research-theme requires --theme")
        run_and_log(lambda: add_research_theme.main(args.theme), "add_research_theme")
        ran = True
    if args.suggest_research_theme:
        run_and_log(suggest_research_theme.main, "suggest_research_theme")
        ran = True
    if args.screenshot:
        run_and_log(lambda: take_screenshot.main(args.display), "take_screenshot")
        ran = True
    if args.scan_line_inbox:
        run_and_log(scan_line_inbox.main, "scan_line_inbox")
        ran = True
    if args.log_activity:
        from obsidian_ai_hub import logging_activity
        run_and_log(logging_activity.main, "log_activity")
        ran = True
    if args.vault_search:
        search_obsidian_vault.main(
            query=args.query,
            k=args.k,
            search_mode=args.search_mode,
            json_output=args.json
        )
        ran = True
    if args.memory_extract:
        from obsidian_ai_hub import memory
        run_and_log(lambda: memory.extract_memories(args.week), "memory_extract")
        ran = True
    if args.memory_review:
        from obsidian_ai_hub import memory
        action = None
        if args.approve:
            action = "approve"
        elif args.reject:
            action = "reject"
        elif args.edit:
            action = "edit"
        run_and_log(lambda: memory.review_memory(args.id, action, args.content), "memory_review")
        ran = True
    if args.memory_compile:
        from obsidian_ai_hub import memory
        import json
        pack = memory.compile_context(args.for_purpose)
        print(json.dumps(pack, ensure_ascii=False, indent=2))
        ran = True
    if getattr(args, "render_copilot_profile", False):
        from obsidian_ai_hub import memory
        run_and_log(
            lambda: print("\n".join(f"- {p}" for p in memory.render_copilot_profile())),
            "render_copilot_profile"
        )
        ran = True
    if args.serve:
        from obsidian_ai_hub.web import app as web_app
        import os as _os
        host = args.serve_host or _os.getenv("MEMORY_REVIEW_HOST", "127.0.0.1")
        port = args.serve_port or int(_os.getenv("MEMORY_REVIEW_PORT", "8765"))
        token = _os.getenv("MEMORY_REVIEW_API_TOKEN", "")
        web_app.HOST = host
        web_app.PORT = port
        web_app.TOKEN = token
        web_app.TOKEN_REQUIRED = host not in ("127.0.0.1", "::1", "localhost")
        if web_app.TOKEN_REQUIRED and not token:
            raise RuntimeError(
                "MEMORY_REVIEW_API_TOKEN is required when binding to a non-loopback host."
            )
        import uvicorn
        uvicorn.run(
            web_app.create_app(host=host, port=port, token=token),
            host=host,
            port=port,
            log_level="info",
        )
        ran = True
    if not ran:
        parser.print_help()

if __name__ == "__main__":
    main()
