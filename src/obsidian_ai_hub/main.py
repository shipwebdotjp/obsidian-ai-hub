#!/usr/bin/env python3
import argparse
import logging
from datetime import datetime, timedelta, date, time

from obsidian_ai_hub import (
    do_backup,
    make_today_target,
    notify_calendar_event,
    notify_today_schedule,
    obsidian_inbox_merge,
    rebuild_valut,
    research_agent,
    suggest_research_theme,
    summerize_day,
    summerize_week,
    sync_knowledge,
    sync_valut,
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
        "--summerize-day",
        action="store_true",
        help="日次レビューを生成"
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
        run_and_log(summerize_week.main, "summerize_week")
        ran = True
    if args.summerize_day:
        run_and_log(summerize_day.main, "summerize_day")
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
    if not ran:
        parser.print_help()

if __name__ == "__main__":
    main()
