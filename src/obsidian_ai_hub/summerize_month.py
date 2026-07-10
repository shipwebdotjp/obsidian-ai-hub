import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from obsidian_ai_hub.utils import config, reader, llm_client, prompt
from obsidian_ai_hub.utils.summary_aggregation import (
    calculate_average_numeric_value,
    calculate_most_common_value,
)

logger = logging.getLogger(__name__)

def load_weekly_records(target_date: datetime) -> list[dict]:
    year = target_date.strftime("%Y")
    log_file = Path(config.ACTIVITY_PATH) / year / f"{year}-week.jsonl"

    records = []
    if not log_file.exists():
        return records

    # 月の開始日と終了日
    first_day = target_date.replace(day=1)
    if target_date.month == 12:
        next_month = target_date.replace(year=target_date.year + 1, month=1, day=1)
    else:
        next_month = target_date.replace(month=target_date.month + 1, day=1)
    last_day = next_month - timedelta(days=1)

    try:
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    data = json.loads(line)
                    ws = data.get("week_start_date")
                    we = data.get("week_end_date")
                    if ws and we:
                        ws_dt = datetime.strptime(ws, "%Y-%m-%d")
                        we_dt = datetime.strptime(we, "%Y-%m-%d")
                        # 週の少なくとも一部が該当月に含まれている場合
                        if (first_day <= ws_dt <= last_day) or (first_day <= we_dt <= last_day) or (ws_dt <= first_day and we_dt >= last_day):
                            records.append(data)
                except (json.JSONDecodeError, ValueError):
                    continue
    except Exception as e:
        logger.error(f"Failed to read weekly log file {log_file}: {e}")

    return records

def get_monthly_structured_record(
    date: datetime,
    weekly_records: list[dict]
) -> dict | None:
    month_id = date.strftime("%Y-%m")
    generated_at = datetime.now().isoformat()

    source_stats = {
        "weekly_record_count": len(weekly_records),
    }

    record = {
        "schema_version": 1,
        "month": month_id,
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
        "mood": calculate_most_common_value(weekly_records, "mood"),
        "sleep": calculate_average_numeric_value(weekly_records, "sleep"),
        "source_stats": source_stats
    }

    try:
        rendered_prompt = prompt.render_prompt(
            config.SUMMARIZE_MONTH_PROMPT_PATH,
            {"WEEKLY_RECORDS": json.dumps(weekly_records, ensure_ascii=False, indent=2)}
        )
        response = llm_client.generate_llm_response(
            provider=config.MAKE_TODAY_TARGET_PROVIDER,
            model=config.MAKE_TODAY_TARGET_MODEL,
            prompt=rendered_prompt,
            max_tokens=8192,
        )

        cleaned_response = response.strip()
        if cleaned_response.startswith("```"):
            lines = cleaned_response.splitlines()
            if len(lines) >= 2:
                if lines[0].startswith("```json") or lines[0].startswith("```"):
                    cleaned_response = "\n".join(lines[1:-1])

        data = json.loads(cleaned_response)

        scalar_fields = {"summary"}
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
        logger.error(f"Failed to generate or parse structured monthly record: {e}", exc_info=True)
        return None

    return record

def format_monthly_record_as_markdown(record: dict) -> str:
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
        ("next_actions", "来月の展望"),
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
        lines.append(f"### 睡眠・健康\n{record['sleep']}\n")

    return "\n".join(lines).strip()

def upsert_monthly_record(year: int, record: dict):
    monthly_log_dir = Path(config.ACTIVITY_PATH) / str(year)
    monthly_log_dir.mkdir(parents=True, exist_ok=True)
    log_file = monthly_log_dir / f"{year}.jsonl"

    records = {}
    parse_failed = False
    if log_file.exists():
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    data = json.loads(line)
                    if "month" in data:
                        records[data["month"]] = data
                except json.JSONDecodeError:
                    parse_failed = True
                    logger.error("Failed to parse existing monthly JSONL; aborting upsert to avoid data loss")
                    break

    if parse_failed:
        return

    records[record["month"]] = record

    sorted_months = sorted(records.keys())
    try:
        with open(log_file, "w", encoding="utf-8") as f:
            for m in sorted_months:
                f.write(json.dumps(records[m], ensure_ascii=False) + "\n")
        logger.info(f"Monthly record upserted to {log_file}")
    except Exception as e:
        logger.error(f"Failed to write monthly record: {e}")

def summarize_month(target_date: datetime):
    logger.info("Summarizing month for date: %s", target_date.strftime("%Y-%m"))

    # 1. データの準備 (週次レコードのロード)
    weekly_records = load_weekly_records(target_date)
    if not weekly_records:
        logger.warning(f"No weekly records found for {target_date.strftime('%Y-%m')}")

    # 2. 構造化レコードの生成
    structured_record = get_monthly_structured_record(target_date, weekly_records)
    if structured_record is None:
        logger.error("Skipping persistence as monthly structured record generation failed")
        return

    # 3. 月次JSONLへの保存
    upsert_monthly_record(target_date.year, structured_record)

    # 4. 月次ノートへの書き込み
    monthly_note = reader.get_monthly_note_content(target_date)
    monthly_note_path = reader.get_monthly_note_path(target_date)
    markdown_content = format_monthly_record_as_markdown(structured_record)

    # 月次ノートのディレクトリ作成
    monthly_note_path.parent.mkdir(parents=True, exist_ok=True)

    if "## AIによる要約" in monthly_note:
        pattern = r"(## AIによる要約\n)(.*?)(?=\n## |$)"
        new_monthly_note = re.sub(
            pattern,
            lambda m: f"{m.group(1)}\n{markdown_content}\n\n",
            monthly_note,
            flags=re.DOTALL
        )
    else:
        new_monthly_note = monthly_note.rstrip() + f"\n\n## AIによる要約\n\n{markdown_content}\n"

    with open(monthly_note_path, "w", encoding="utf-8") as f:
        f.write(new_monthly_note)

    logger.info(f"Monthly summary updated in: {monthly_note_path}")

def main(target_month_str: str = None):
    if target_month_str:
        try:
            target_date = datetime.strptime(target_month_str, "%Y-%m")
        except ValueError:
            logger.error(f"Invalid month format: {target_month_str}. Expected YYYY-MM")
            return
    else:
        # デフォルトは先月
        today = datetime.now()
        first_day_of_this_month = today.replace(day=1)
        target_date = first_day_of_this_month - timedelta(days=1)

    summarize_month(target_date)

if __name__ == "__main__":
    main()
