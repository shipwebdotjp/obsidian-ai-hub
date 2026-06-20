import json
import logging
from collections import Counter
from datetime import datetime, timedelta
from obsidian_ai_hub.utils import config, reader, extracter, llm_client, prompt
from pathlib import Path

logger = logging.getLogger(__name__)

TOPIC_ENUM = [
    "LLM・AI活用", "AI・機械学習", "ソフトウェア開発", "開発環境・DevOps",
    "データ・分析", "クラウド・インフラ", "ツール・自動化（生産性）",
    "リサーチ手法・情報整理（PKM）", "ガジェット・デバイス", "金融・投資",
    "マーケティング・発信", "ライティング・コンテンツ制作", "コミュニケーション・対人関係",
    "思考法・判断力", "学習・教育", "自己改善（習慣・時間管理）", "メンタル・心理",
    "健康・医療", "生活・暮らし", "信仰・聖書", "その他"
]

INTENT_ENUM = [
    "理解・質問応答", "要約・整理", "調査・比較", "意思決定支援", "設計・構成検討",
    "計画・タスク化", "文章生成・編集", "コード作成・レビュー", "問題解決・トラブル対応",
    "翻訳・ローカライズ", "メタ検討", "その他"
]


def get_daily_structured_record(
    target_date: datetime,
    daily_content: str,
    logs: list[dict],
    activity_logs: list[dict]
) -> dict:
    """
    指定された日付の情報を構造化データとして生成。
    """
    date_str = target_date.strftime("%Y-%m-%d")
    generated_at = datetime.now().isoformat()

    # source_stats 計算
    daily_file = reader.get_daily_note_path(target_date)
    source_stats = {
        "activity_count": len(activity_logs),
        "llm_session_count": len(logs),
        "has_daily_note": daily_file.exists()
    }

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
        simplified_activity_logs.append({
            "timestamp": ts,
            "summary": log.get("summary")
        })

    rendered_prompt = prompt.render_prompt(
        config.SUMMARIZE_DAY_PROMPT_PATH,
        {
            "SESSION_SUMMARIES": json.dumps(logs, ensure_ascii=False, indent=2),
            "ACTIVITY_LOGS": json.dumps(simplified_activity_logs, ensure_ascii=False, indent=2),
            "DAILY_NOTE_CONTENT": daily_content,
        }
    )

    # 最小レコード（フォールバック用）
    record = {
        "schema_version": 1,
        "date": date_str,
        "generated_at": generated_at,
        "summary": None,
        "topics": [],
        "activities": [],
        "learnings": [],
        "reflections": [],
        "gratitude": [],
        "people": [],
        "questions": [],
        "keywords": [],
        "next_actions": [],
        "mood": mood,
        "sleep": sleep,
        "source_stats": source_stats
    }

    try:
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
            "topics", "activities", "learnings", "reflections",
            "gratitude", "questions", "keywords", "next_actions",
        }
        for key in [
            "summary", "topics", "activities", "learnings", "reflections",
            "gratitude", "people", "questions", "keywords", "next_actions"
        ]:
            if key in data:
                val = data[key]
                if val is None:
                    continue

                if key == "people" and isinstance(val, list):
                    normalized_people = []
                    for p in val:
                        if isinstance(p, dict) and "name" in p:
                            normalized_people.append({
                                "name": str(p.get("name", "")),
                                "note": str(p.get("note", ""))
                            })
                    record["people"] = normalized_people
                elif key in scalar_fields and isinstance(val, str):
                    record[key] = val or None
                elif key in list_fields and isinstance(val, list):
                    record[key] = [str(item) for item in val if item not in (None, "")]

    except Exception as e:
        logger.error(f"Failed to generate or parse structured daily record: {e}")

    return record


def format_structured_record_as_markdown(record: dict, activity_logs: list[dict]) -> str:
    """
    構造化レコードとアクティビティログをマークダウン形式に変換。
    """
    lines = []

    if record.get("summary"):
        lines.append(f"{record['summary']}\n")

    sections = [
        ("topics", "トピックス"),
        ("activities", "活動内容"),
        ("learnings", "学び・整理"),
        ("reflections", "反省・気づき"),
        ("gratitude", "感謝"),
        ("questions", "問い"),
        ("keywords", "キーワード"),
        ("next_actions", "ネクストアクション"),
    ]

    for key, label in sections:
        val = record.get(key)
        if val and isinstance(val, list):
            lines.append(f"### {label}")
            for item in val:
                lines.append(f"- {item}")
            lines.append("")

    if record.get("people"):
        lines.append("### 人物メモ")
        for p in record["people"]:
            name = p.get("name", "Unknown")
            note = p.get("note", "")
            lines.append(f"- **{name}**: {note}")
        lines.append("")

    # カテゴリとキーワードの集計 (ランキング)
    categories = [log.get("category") for log in activity_logs if log.get("category")]
    keywords_list = []
    for log in activity_logs:
        keywords_list.extend(log.get("keywords", []))

    top_categories = Counter(categories).most_common(5)
    top_keywords = Counter(keywords_list).most_common(20)

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


def upsert_monthly_record(target_date: datetime, record: dict):
    """
    月次JSONLにレコードをupsertする。
    """
    monthly_log_dir = Path(config.ACTIVITY_PATH) / target_date.strftime("%Y/%m")
    monthly_log_dir.mkdir(parents=True, exist_ok=True)
    log_file = monthly_log_dir / target_date.strftime("%Y-%m.jsonl")

    records = {}
    parse_failed = False
    if log_file.exists():
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    data = json.loads(line)
                    if "date" in data:
                        records[data["date"]] = data
                except json.JSONDecodeError:
                    parse_failed = True
                    logger.error("Failed to parse existing monthly JSONL; aborting upsert to avoid data loss")
                    break

    if parse_failed:
        return

    # upsert
    records[record["date"]] = record

    # 保存（date昇順）
    sorted_dates = sorted(records.keys())
    try:
        with open(log_file, "w", encoding="utf-8") as f:
            for d in sorted_dates:
                f.write(json.dumps(records[d], ensure_ascii=False) + "\n")
        logger.info(f"Monthly record upserted to {log_file}")
    except Exception as e:
        logger.error(f"Failed to write monthly record: {e}")


def load_activity_logs(target_date: datetime) -> list[dict]:
    activity_log_file = Path(config.ACTIVITY_PATH) / target_date.strftime("%Y/%m") / target_date.strftime("%Y-%m-%d.jsonl")
    logs = []
    if not activity_log_file.exists():
        return logs

    with open(activity_log_file, "r", encoding="utf-8") as f:
        for line in f:
            try:
                data = json.loads(line)
                # Coalesce None to defaults
                category = data.get("category")
                if category is None:
                    category = "その他"

                keywords = data.get("keywords")
                if keywords is None:
                    keywords = []

                logs.append({
                    "timestamp": data.get("timestamp"),
                    "app_name": data.get("app_name"),
                    "window_title": data.get("window_title"),
                    "summary": data.get("summary"),
                    "category": category,
                    "keywords": keywords
                })
            except json.JSONDecodeError:
                logger.error("Error decoding JSON from activity log file")
    return logs


def load_conversation_logs(log_file_dir: str, target_date: datetime) -> list[dict]:
    logs = []
    date_str = target_date.strftime('%Y%m%d')
    log_dir = Path(log_file_dir)
    for file in log_dir.glob(f'*@{date_str}*.json'):
        with open(file, "r", encoding="utf-8") as f:
            try:
                log = json.load(f)
                logs.append(log)
            except json.JSONDecodeError:
                logger.error("Error decoding JSON from log file")

    return logs


def summarize_day(target_date: datetime):
    """
    指定日のログをまとめ、構造化レコードの生成、月次保存、デイリーノートへの追記を行う。
    """
    logger.info("Summarizing day: %s", target_date.date())

    daily_file = reader.get_daily_note_path(target_date)
    daily_content = reader.get_daily_note_content(target_date)

    # 1. ログのロード
    logs = load_conversation_logs(config.AI_LOG_PATH, target_date)
    activity_logs = load_activity_logs(target_date)

    # 2. 構造化レコードの生成
    structured_record = get_daily_structured_record(target_date, daily_content, logs, activity_logs)

    # 3. 月次JSONLへの保存 (永続化)
    upsert_monthly_record(target_date, structured_record)

    # 4. デイリーノートへの追記 (人間用表示)
    if structured_record.get("summary"):
        if structured_record.get("source_stats", {}).get("has_daily_note"):
            markdown_content = format_structured_record_as_markdown(structured_record, activity_logs)
            extracter.append_to_subheader_file(daily_file.as_posix(), "## AIによる要約", [markdown_content])
    else:
        logger.error("Failed to generate structured record; skipping daily note update")


def main():
    today = datetime.now()
    yesterday = today - timedelta(days=1)
    summarize_day(yesterday)


if __name__ == "__main__":
    main()
