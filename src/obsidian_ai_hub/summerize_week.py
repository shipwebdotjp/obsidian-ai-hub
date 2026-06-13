import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from obsidian_ai_hub.utils import config, reader, extracter, llm_client

logger = logging.getLogger(__name__)

STRUCTURED_PROMPT = """
あなたは週次アナリスト兼コーチです。今週の7日間分の日次構造化データを元に、週次レビューを構造化されたJSON形式で出力してください。
目的は「この1週間の小さな積み重ねが、どのように成長に寄与したか」を将来の月次・四半期・年次要約に再利用できる形で保存することです。

# 項目定義
- summary: 週の一言（20〜40字程度）
- topics: 今週の主なトピックス
- activities: 主な活動内容
- learnings: 学び・整理できたこと
- reflections: 反省・気づき
- gratitude: 感謝したこと
- people: 人物メモ。 `{"name": "...", "note": "..."}` の配列
- questions: 問い
- keywords: キーワード
- next_actions: 来週の観測ポイントやネクストアクション
- mood: 気分・エネルギーの流れ
- sleep: 睡眠・疲労の状況

# 出力形式
必ず以下のJSON形式のみを出力してください。余計な解説は不要です。
{
  "summary": "...",
  "topics": [],
  "activities": [],
  "learnings": [],
  "reflections": [],
  "gratitude": [],
  "people": [{"name": "...", "note": "..."}],
  "questions": [],
  "keywords": [],
  "next_actions": [],
  "mood": "...",
  "sleep": "..."
}

今週の日次データ:
{DAILY_RECORDS}
"""

def get_week_dates(date: datetime):
    """
    指定された日付が属する週の月曜日から日曜日までの7日間のリストを返す
    """
    iso_year, iso_week, weekday = date.isocalendar()
    monday = date - timedelta(days=weekday - 1)
    return [monday + timedelta(days=i) for i in range(7)]

def load_daily_record(date: datetime) -> dict | None:
    monthly_log_file = Path(config.ACTIVITY_PATH) / date.strftime("%Y/%m") / date.strftime("%Y-%m.jsonl")
    if not monthly_log_file.exists():
        return None
    date_str = date.strftime("%Y-%m-%d")
    try:
        with open(monthly_log_file, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    data = json.loads(line)
                    if data.get("date") == date_str:
                        return data
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        logger.error(f"Failed to read monthly log file {monthly_log_file}: {e}")
    return None

def get_weekly_structured_record(
    date: datetime,
    daily_records: list[dict | None]
) -> dict:
    iso_year, iso_week, _ = date.isocalendar()
    week_id = f"{iso_year}-W{iso_week:02d}"
    week_dates = get_week_dates(date)
    week_start = week_dates[0].strftime("%Y-%m-%d")
    week_end = week_dates[-1].strftime("%Y-%m-%d")
    generated_at = datetime.now().isoformat()

    source_stats = {
        "daily_record_count": len([r for r in daily_records if r is not None]),
    }

    # プロンプト用のデータを準備（Noneはプレースホルダに）
    simplified_daily_records = []
    for i, r in enumerate(daily_records):
        d_str = week_dates[i].strftime("%Y-%m-%d")
        if r:
            simplified_daily_records.append(r)
        else:
            simplified_daily_records.append({"date": d_str, "status": "no data"})

    prompt = STRUCTURED_PROMPT.replace("{DAILY_RECORDS}", json.dumps(simplified_daily_records, ensure_ascii=False, indent=2))

    record = {
        "schema_version": 1,
        "week_id": week_id,
        "week_start_date": week_start,
        "week_end_date": week_end,
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
        "mood": None,
        "sleep": None,
        "source_stats": source_stats
    }

    try:
        response = llm_client.generate_llm_response(
            provider=config.MAKE_TODAY_TARGET_PROVIDER,
            model=config.MAKE_TODAY_TARGET_MODEL,
            prompt=prompt,
            max_tokens=8192,
        )

        cleaned_response = response.strip()
        if cleaned_response.startswith("```"):
            lines = cleaned_response.splitlines()
            if len(lines) >= 2:
                if lines[0].startswith("```json") or lines[0].startswith("```"):
                    cleaned_response = "\n".join(lines[1:-1])

        data = json.loads(cleaned_response)

        scalar_fields = {"summary", "mood", "sleep"}
        list_fields = {
            "topics", "activities", "learnings", "reflections",
            "gratitude", "questions", "keywords", "next_actions",
        }

        for key in scalar_fields | list_fields | {"people"}:
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
                elif key in scalar_fields and isinstance(val, (str, int, float)):
                    record[key] = str(val)
                elif key in list_fields and isinstance(val, list):
                    record[key] = [str(item) for item in val if item not in (None, "")]

    except Exception as e:
        logger.error(f"Failed to generate or parse structured weekly record: {e}")

    return record

def format_weekly_record_as_markdown(record: dict) -> str:
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
        ("next_actions", "来週の観測ポイント"),
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

    if record.get("mood"):
        lines.append(f"### 気分・エネルギー\n{record['mood']}\n")

    if record.get("sleep"):
        lines.append(f"### 睡眠・疲労\n{record['sleep']}\n")

    return "\n".join(lines).strip()

def upsert_weekly_record(iso_year: int, record: dict) -> bool:
    weekly_log_dir = Path(config.ACTIVITY_PATH) / str(iso_year)
    weekly_log_dir.mkdir(parents=True, exist_ok=True)
    log_file = weekly_log_dir / f"{iso_year}-week.jsonl"

    records = {}
    parse_failed = False
    if log_file.exists():
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    data = json.loads(line)
                    if "week_id" in data:
                        records[data["week_id"]] = data
                except json.JSONDecodeError:
                    parse_failed = True
                    logger.error("Failed to parse existing weekly JSONL; aborting upsert to avoid data loss")
                    break

    if parse_failed:
        return False

    records[record["week_id"]] = record

    sorted_week_ids = sorted(records.keys())
    try:
        with open(log_file, "w", encoding="utf-8") as f:
            for wid in sorted_week_ids:
                f.write(json.dumps(records[wid], ensure_ascii=False) + "\n")
        logger.info(f"Weekly record upserted to {log_file}")
        return True
    except Exception as e:
        logger.error(f"Failed to write weekly record: {e}")
        return False

def summarize_week(target_date: datetime):
    logger.info("Summarizing week for date: %s", target_date.date())

    # 1. データの準備
    week_dates = get_week_dates(target_date)
    daily_records = [load_daily_record(d) for d in week_dates]

    # 2. 構造化レコードの生成
    structured_record = get_weekly_structured_record(target_date, daily_records)

    # 3. 週次JSONLへの保存
    iso_year, _, _ = target_date.isocalendar()
    if not upsert_weekly_record(iso_year, structured_record):
        logger.error("Skipping weekly note update as JSONL upsert failed")
        return

    # 4. ウィークリーノートへの書き込み
    weekly_note = reader.get_weekly_note_content(target_date)
    weekly_note_path = reader.get_weekly_note_path(target_date)
    markdown_content = format_weekly_record_as_markdown(structured_record)

    if "## AIによる要約" in weekly_note:
        pattern = r"(## AIによる要約\n)(.*?)(?=\n## |$)"
        new_weekly_note = re.sub(
            pattern,
            lambda m: f"{m.group(1)}\n{markdown_content}\n\n",
            weekly_note,
            flags=re.DOTALL
        )
    else:
        new_weekly_note = weekly_note.rstrip() + f"\n\n## AIによる要約\n\n{markdown_content}\n"

    weekly_note_path.parent.mkdir(parents=True, exist_ok=True)
    with open(weekly_note_path, "w", encoding="utf-8") as f:
        f.write(new_weekly_note)

    logger.info(f"Weekly summary updated in: {weekly_note_path}")

def main():
    today = datetime.now()
    # デフォルトでは先週を要約する（日曜日に実行されることが多いが、月曜日に先週分をやることもある）
    # ここではシンプルに引数の日の属する週を対象とする
    summarize_week(today)

if __name__ == "__main__":
    main()
