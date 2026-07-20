import json
import logging
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from obsidian_ai_hub.activity.store import get_activities_by_date
from obsidian_ai_hub.research import db as research_db
from obsidian_ai_hub.summary import store as summary_store
from obsidian_ai_hub.utils import config, reader, extracter, llm_client, prompt
from obsidian_ai_hub.utils.topics import (
    TOPIC_ENUM,
    normalize_keywords,
    normalize_topics,
)

logger = logging.getLogger(__name__)

DAY_ITEM_KINDS = ["highlights", "activities", "learnings", "reflections", "gratitude"]


def get_activity_rankings(
    activity_logs: list[dict],
) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    """アクティビティログから表示・要約用のランキングを作成する。"""
    categories = [log.get("category") for log in activity_logs if log.get("category")]
    keywords = [
        keyword
        for log in activity_logs
        for keyword in log.get("keywords", [])
        if keyword
    ]
    return Counter(categories).most_common(5), Counter(keywords).most_common(20)


def get_daily_structured_record(
    target_date: datetime,
    daily_content: str,
    logs: list[dict],
    activity_logs: list[dict],
) -> dict:
    """
    指定された日付の情報を構造化データとして生成。
    """
    date_str = target_date.strftime("%Y-%m-%d")
    generated_at = datetime.now().isoformat()

    # frontmatter から mood/sleep 取得
    mood = extracter.get_frontmatter_value(daily_content, "mood", default=None)
    sleep = extracter.get_frontmatter_value(daily_content, "sleep", default=None)

    # プロンプト用のアクティビティログを簡略化（timestampとsummaryのみ）
    simplified_activity_logs = []
    for log in activity_logs:
        ts = log.get("timestamp")
        # ミリ秒を除去 (2023-10-27T10:00:00.123456 -> 2023-10-27T10:00:00)
        if ts and "." in ts:
            ts = ts.split(".")[0]
        simplified_activity_logs.append(
            {"timestamp": ts, "summary": log.get("summary")}
        )

    top_categories, top_keywords = get_activity_rankings(activity_logs)

    # 対象日に承認されたリサーチテーマ
    approved_themes = []
    try:
        for t in research_db.list_approved_themes_by_date(date_str):
            entry = {"theme": t["theme"]}
            if t.get("direction"):
                entry["direction"] = t["direction"]
            approved_themes.append(entry)
    except Exception as e:
        logger.warning("Failed to load approved research themes: %s", e)

    # Load active, inquiry, paused projects for prompt listing
    from obsidian_ai_hub.summary.project_utils import get_active_projects_for_prompt
    existing_projects = get_active_projects_for_prompt()

    # 最小レコード（フォールバック用）
    record = {
        "schema_version": 1,
        "period_type": "day",
        "period_key": date_str,
        "period_start": date_str,
        "period_end": date_str,
        "generated_at": generated_at,
        "summary": None,
        "keywords": [],
        "mood": mood,
        "sleep_raw": sleep,
        "sleep_hours": summary_store.parse_sleep_hours(sleep),
        "topics": [],
        "projects": [],
        "project_ids": [],
        "project_candidates": [],
        "people": [],
        "items": [],
    }

    try:
        rendered_prompt = prompt.render_prompt(
            config.SUMMARIZE_DAY_PROMPT_PATH,
            {
                "SESSION_SUMMARIES": json.dumps(logs, ensure_ascii=False, indent=2),
                "ACTIVITY_LOGS": json.dumps(
                    simplified_activity_logs, ensure_ascii=False, indent=2
                ),
                "CATEGORY_RANKINGS": json.dumps(
                    top_categories, ensure_ascii=False, indent=2
                ),
                "KEYWORD_RANKINGS": json.dumps(
                    top_keywords, ensure_ascii=False, indent=2
                ),
                "DAILY_NOTE_CONTENT": daily_content,
                "TOPIC_CANDIDATES": json.dumps(TOPIC_ENUM, ensure_ascii=False),
                "APPROVED_RESEARCH_THEMES": json.dumps(
                    approved_themes, ensure_ascii=False, indent=2
                ),
                "EXISTING_PROJECTS": json.dumps(
                    existing_projects, ensure_ascii=False, indent=2
                ),
            },
        )
        response = llm_client.generate_llm_response(
            provider=config.MAKE_TODAY_TARGET_PROVIDER,
            model=config.MAKE_TODAY_TARGET_MODEL,
            prompt=rendered_prompt,
            max_tokens=8120,
        )

        # JSONパース
        cleaned_response = response.strip()
        if cleaned_response.startswith("```"):
            lines = cleaned_response.splitlines()
            if len(lines) >= 2:
                if lines[0].startswith("```json") or lines[0].startswith("```"):
                    cleaned_response = "\n".join(lines[1:-1])

        data = json.loads(cleaned_response)

        # 抽出したデータを record にマージ
        scalar_fields = {"summary"}
        list_fields = {
            "keywords",
            "topics",
            "highlights",
            "activities",
            "learnings",
            "reflections",
            "gratitude",
        }

        if "project_ids" in data and isinstance(data["project_ids"], list):
            record["project_ids"] = [
                int(p) for p in data["project_ids"]
                if isinstance(p, (int, str)) and str(p).isdigit()
            ]

        if "project_candidates" in data and isinstance(data["project_candidates"], list):
            valid_candidates = []
            for c in data["project_candidates"]:
                if isinstance(c, dict) and (c.get("display_name") or c.get("name")):
                    valid_candidates.append({
                        "display_name": c.get("display_name") or c.get("name"),
                        "domain": c.get("domain") or "personal",
                        "goal": c.get("goal"),
                        "description": c.get("description"),
                        "keywords": c.get("keywords") or [],
                        "start_date": c.get("start_date"),
                        "target_date": c.get("target_date"),
                        "completed_date": c.get("completed_date"),
                        "evidence": c.get("evidence"),
                    })
            record["project_candidates"] = valid_candidates

        for key in [
            "summary",
            "keywords",
            "topics",
            "highlights",
            "activities",
            "learnings",
            "reflections",
            "gratitude",
            "people",
        ]:
            if key in data:
                val = data[key]
                if val is None:
                    continue

                if key == "people" and isinstance(val, list):
                    normalized_people = []
                    for p in val:
                        if isinstance(p, dict) and p.get("name"):
                            normalized_people.append(
                                {
                                    "name": str(p.get("name", "")),
                                    "note": str(p.get("note", "")),
                                }
                            )
                    record["people"] = normalized_people
                elif key in scalar_fields and isinstance(val, str):
                    record[key] = val or None
                elif key in list_fields and isinstance(val, list):
                    clean_list = [str(item) for item in val if item not in (None, "")]
                    if key == "keywords":
                        record["keywords"] = normalize_keywords(val)
                    elif key == "topics":
                        record["topics"] = normalize_topics(clean_list)
                    elif key in DAY_ITEM_KINDS:
                        record["items"].extend(
                            {"kind": key, "body": item, "display_order": idx}
                            for idx, item in enumerate(clean_list)
                        )

        # display_order を kind 単位で振り直す
        record["items"].sort(
            key=lambda x: (DAY_ITEM_KINDS.index(x["kind"]), x["display_order"])
        )
        for kind in DAY_ITEM_KINDS:
            kind_items = [i for i in record["items"] if i["kind"] == kind]
            for idx, item in enumerate(kind_items):
                item["display_order"] = idx

    except Exception as e:
        logger.error(f"Failed to generate or parse structured daily record: {e}")

    return record


def format_structured_record_as_markdown(
    record: dict, activity_logs: list[dict]
) -> str:
    """
    構造化レコードとアクティビティログをマークダウン形式に変換。
    """
    lines = []

    if record.get("summary"):
        lines.append(f"{record['summary']}\n")

    kind_labels = {
        "highlights": "ハイライト",
        "activities": "活動内容",
        "learnings": "学び・整理",
        "reflections": "反省・気づき",
        "gratitude": "感謝",
    }

    for item in record.get("items", []):
        kind = item.get("kind")
        body = item.get("body")
        if not kind or not body:
            continue
        label = kind_labels.get(kind, kind)
        lines.append(f"### {label}")
        lines.append(f"- {body}")
        lines.append("")

    if record.get("people"):
        lines.append("### 人物メモ")
        for p in record["people"]:
            name = p.get("name", "Unknown")
            note = p.get("note", "")
            lines.append(f"- **{name}**: {note}")
        lines.append("")

    # カテゴリとキーワードの集計 (ランキング)
    top_categories, top_keywords = get_activity_rankings(activity_logs)

    if top_categories:
        lines.append("### カテゴリ順位")
        for c, count in top_categories:
            lines.append(f"- {c}: {count}")
        lines.append("")

    if top_keywords:
        lines.append("### キーワード順位")
        for k, count in top_keywords:
            lines.append(f"- {k}: {count}")
        lines.append("")

    return "\n".join(lines).strip()


def upsert_summary_record(record: dict):
    """
    SQLite summaries テーブルにレコードをupsertする。
    """
    try:
        summary_store.upsert_summary(record)
        logger.info(f"Daily summary upserted for {record.get('period_key')}")
    except Exception as e:
        logger.error(f"Failed to upsert daily summary: {e}")


def load_activity_logs(target_date: datetime) -> list[dict]:
    activity_date_str = target_date.strftime("%Y-%m-%d")
    try:
        db_activities = get_activities_by_date(activity_date_str)
    except Exception as e:
        logger.error(f"Failed to fetch activity logs from SQLite: {e}")
        return []

    logs = []
    for data in db_activities:
        # Coalesce None to defaults
        category = data.get("category")
        if category is None:
            category = "その他"

        keywords = data.get("keywords")
        if keywords is None:
            keywords = []

        logs.append(
            {
                "timestamp": data.get("occurred_at"),
                "app_name": data.get("app_name"),
                "window_title": data.get("window_title"),
                "summary": data.get("summary"),
                "category": category,
                "keywords": keywords,
            }
        )
    return logs


def load_conversation_logs(log_file_dir: str, target_date: datetime) -> list[dict]:
    logs = []
    date_str = target_date.strftime("%Y%m%d")
    log_dir = Path(log_file_dir)
    for file in log_dir.glob(f"*@{date_str}*.json"):
        with open(file, "r", encoding="utf-8") as f:
            try:
                log = json.load(f)
                logs.append(log)
            except json.JSONDecodeError:
                logger.error("Error decoding JSON from log file")

    return logs


def summarize_day(target_date: datetime):
    """
    指定日のログをまとめ、構造化レコードの生成、SQLite保存、デイリーノートへの追記を行う。
    """
    logger.info("Summarizing day: %s", target_date.date())

    daily_content = reader.get_daily_note_content(target_date)

    # 1. ログのロード
    logs = load_conversation_logs(config.AI_LOG_PATH, target_date)
    activity_logs = load_activity_logs(target_date)

    # 2. 構造化レコードの生成
    structured_record = get_daily_structured_record(
        target_date, daily_content, logs, activity_logs
    )

    if not structured_record.get("summary"):
        logger.error(
            "Failed to generate structured record; skipping persistence and daily note update"
        )
        return

    # 3. SQLiteへの保存 (永続化)
    upsert_summary_record(structured_record)

    # 4. デイリーノートへの追記 (人間用表示) 260719: 人間の書いたものと、AIの書いたものを混ぜないためにデイリーノートへの追記は中止
    # if daily_file.exists():
    #     markdown_content = format_structured_record_as_markdown(structured_record, activity_logs)
    #     extracter.append_to_subheader_file(daily_file.as_posix(), "## AIによる要約", [markdown_content])


def main():
    today = datetime.now()
    yesterday = today - timedelta(days=1)
    summarize_day(yesterday)


if __name__ == "__main__":
    main()
