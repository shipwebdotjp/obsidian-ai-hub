import json
import logging
from calendar import monthrange
from datetime import datetime, timedelta

from obsidian_ai_hub.summary import store as summary_store
from obsidian_ai_hub.utils import config, llm_client, prompt, reader  # noqa: F401  (re-exported for test patching)
from obsidian_ai_hub.utils.topics import (
    TOPIC_ENUM,
    normalize_keywords,
    normalize_topics,
)

logger = logging.getLogger(__name__)

MONTH_ITEM_KINDS = [
    "highlights",
    "progress",
    "changes",
    "learnings",
    "reflections",
    "patterns",
    "gratitude",
]


def load_weekly_records(target_date: datetime) -> list[dict]:
    """Load weekly summary records overlapping the target month from SQLite."""
    year = target_date.year
    month = target_date.month

    first_day = target_date.replace(day=1)
    if month == 12:
        next_month = target_date.replace(year=year + 1, month=1, day=1)
    else:
        next_month = target_date.replace(month=month + 1, day=1)
    last_day = next_month - timedelta(days=1)

    # Load all week records and filter by overlap with the month
    records = []
    all_weeks = summary_store.list_summaries(period_type="week")

    for rec in all_weeks:
        period_start = rec.get("period_start")
        period_end = rec.get("period_end")
        if not period_start or not period_end:
            continue
        try:
            ws_dt = datetime.strptime(period_start, "%Y-%m-%d")
            we_dt = datetime.strptime(period_end, "%Y-%m-%d")
        except ValueError:
            continue
        # 週の少なくとも一部が該当月に含まれている場合
        if (
            (first_day <= ws_dt <= last_day)
            or (first_day <= we_dt <= last_day)
            or (ws_dt <= first_day and we_dt >= last_day)
        ):
            records.append(rec)

    return records


def get_monthly_structured_record(
    date: datetime, weekly_records: list[dict]
) -> dict | None:
    month_id = date.strftime("%Y-%m")
    generated_at = datetime.now().isoformat()

    _, last_day = monthrange(date.year, date.month)
    period_start = date.replace(day=1).strftime("%Y-%m-%d")
    period_end = date.replace(day=last_day).strftime("%Y-%m-%d")

    record = {
        "schema_version": 1,
        "period_type": "month",
        "period_key": month_id,
        "period_start": period_start,
        "period_end": period_end,
        "generated_at": generated_at,
        "summary": None,
        "keywords": [],
        "mood": None,
        "sleep_raw": None,
        "sleep_hours": None,
        "topics": [],
        "projects": [],
        "people": [],
        "items": [],
    }

    try:
        rendered_prompt = prompt.render_prompt(
            config.SUMMARIZE_MONTH_PROMPT_PATH,
            {
                "WEEKLY_RECORDS": json.dumps(
                    weekly_records, ensure_ascii=False, indent=2
                ),
                "TOPIC_CANDIDATES": json.dumps(TOPIC_ENUM, ensure_ascii=False),
            },
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
            "keywords",
            "topics",
            "highlights",
            "progress",
            "changes",
            "learnings",
            "reflections",
            "patterns",
            "gratitude",
        }

        for key in scalar_fields | list_fields | {"people"}:
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
                elif key in scalar_fields and isinstance(val, (str, int, float)):
                    record[key] = str(val)
                elif key in list_fields and isinstance(val, list):
                    clean_list = [str(item) for item in val if item not in (None, "")]
                    if key == "keywords":
                        record["keywords"] = normalize_keywords(val)
                    elif key == "topics":
                        record["topics"] = normalize_topics(clean_list)
                    elif key in MONTH_ITEM_KINDS:
                        record["items"].extend(
                            {"kind": key, "body": item, "display_order": idx}
                            for idx, item in enumerate(clean_list)
                        )

        # display_order を kind 単位で振り直す
        record["items"].sort(
            key=lambda x: (MONTH_ITEM_KINDS.index(x["kind"]), x["display_order"])
        )
        for kind in MONTH_ITEM_KINDS:
            kind_items = [i for i in record["items"] if i["kind"] == kind]
            for idx, item in enumerate(kind_items):
                item["display_order"] = idx

    except Exception as e:
        logger.error(
            f"Failed to generate or parse structured monthly record: {e}", exc_info=True
        )
        return None

    # Collect union of project_ids and unresolved project_candidates from weekly_records without LLM
    from obsidian_ai_hub.summary.project_utils import inherit_projects_and_candidates
    p_ids, p_candidates = inherit_projects_and_candidates(weekly_records)
    record["project_ids"] = p_ids
    record["project_candidates"] = p_candidates

    return record


def format_monthly_record_as_markdown(record: dict) -> str:
    lines = []

    if record.get("summary"):
        lines.append(f"{record['summary']}\n")

    kind_labels = {
        "highlights": "ハイライト",
        "progress": "目標・プロジェクトの前進",
        "changes": "前月からの変化",
        "learnings": "学び・整理",
        "reflections": "反省・気づき",
        "patterns": "パターン・傾向",
        "gratitude": "感謝",
    }

    items_by_kind: dict[str, list[str]] = {}
    for item in record.get("items", []):
        kind = item.get("kind")
        body = item.get("body")
        if not kind or not body:
            continue
        items_by_kind.setdefault(kind, []).append(body)

    for kind, bodies in items_by_kind.items():
        label = kind_labels.get(kind, kind)
        lines.append(f"### {label}")
        for body in bodies:
            lines.append(f"- {body}")
        lines.append("")

    if record.get("people"):
        lines.append("### 人物メモ")
        for p in record["people"]:
            name = p.get("name", "Unknown")
            note = p.get("note", "")
            lines.append(f"- **{name}**: {note}")
        lines.append("")

    return "\n".join(lines).strip()


def upsert_summary_record(record: dict):
    """
    SQLite summaries テーブルにレコードをupsertする。
    """
    summary_store.upsert_summary(record)
    logger.info(f"Monthly summary upserted for {record.get('period_key')}")


def summarize_month(target_date: datetime):
    logger.info("Summarizing month for date: %s", target_date.strftime("%Y-%m"))

    # 1. データの準備 (週次レコードのロード)
    weekly_records = load_weekly_records(target_date)
    if not weekly_records:
        logger.warning(f"No weekly records found for {target_date.strftime('%Y-%m')}")

    # 2. 構造化レコードの生成
    structured_record = get_monthly_structured_record(target_date, weekly_records)
    if structured_record is None:
        logger.error(
            "Skipping persistence as monthly structured record generation failed"
        )
        return

    # 3. SQLiteへの保存
    upsert_summary_record(structured_record)

    # 4. 月次ノートへの書き込み 260719: 人間の書いたものと、AIの書いたものを混ぜないためにデイリーノートへの追記は中止
    # monthly_note = reader.get_monthly_note_content(target_date)
    # monthly_note_path = reader.get_monthly_note_path(target_date)
    # markdown_content = format_monthly_record_as_markdown(structured_record)

    # # 月次ノートのディレクトリ作成
    # monthly_note_path.parent.mkdir(parents=True, exist_ok=True)

    # if "## AIによる要約" in monthly_note:
    #     pattern = r"(## AIによる要約\n)(.*?)(?=\n## |$)"
    #     new_monthly_note = re.sub(
    #         pattern,
    #         lambda m: f"{m.group(1)}\n{markdown_content}\n\n",
    #         monthly_note,
    #         flags=re.DOTALL
    #     )
    # else:
    #     new_monthly_note = monthly_note.rstrip() + f"\n\n## AIによる要約\n\n{markdown_content}\n"

    # with open(monthly_note_path, "w", encoding="utf-8") as f:
    #     f.write(new_monthly_note)

    # logger.info(f"Monthly summary updated in: {monthly_note_path}")


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
