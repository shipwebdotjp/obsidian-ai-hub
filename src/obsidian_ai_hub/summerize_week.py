import json
import logging
from datetime import date as date_type
from datetime import datetime, timedelta

from obsidian_ai_hub.summary import store as summary_store
from obsidian_ai_hub.utils import config, llm_client, prompt
from obsidian_ai_hub.utils.topics import (
    TOPIC_ENUM,
    normalize_keywords,
    normalize_topics,
)

logger = logging.getLogger(__name__)

WEEK_ITEM_KINDS = [
    "highlights",
    "progress",
    "learnings",
    "reflections",
    "patterns",
    "gratitude",
]


def get_week_dates(date: datetime):
    """
    指定された日付が属する週の月曜日から日曜日までの7日間のリストを返す
    """
    iso_year, iso_week, weekday = date.isocalendar()
    monday = date - timedelta(days=weekday - 1)
    return [monday + timedelta(days=i) for i in range(7)]


def load_daily_records(week_dates: list[datetime]) -> list[dict | None]:
    """Load the 7 daily summary records for the week from SQLite."""
    records = []
    for d in week_dates:
        date_str = d.strftime("%Y-%m-%d")
        try:
            record = summary_store.get_summary_by_period("day", date_str)
        except Exception as e:
            logger.error(f"Failed to load daily summary for {date_str}: {e}")
            record = None
        records.append(record)
    return records


def get_weekly_structured_record(
    date: datetime, daily_records: list[dict | None]
) -> dict:
    iso_year, iso_week, _ = date.isocalendar()
    week_id = f"{iso_year}-W{iso_week:02d}"
    week_dates = get_week_dates(date)
    week_start = week_dates[0].strftime("%Y-%m-%d")
    week_end = week_dates[-1].strftime("%Y-%m-%d")
    generated_at = datetime.now().isoformat()

    # プロンプト用のデータを準備（Noneはプレースホルダに）
    simplified_daily_records = []
    for i, r in enumerate(daily_records):
        d_str = week_dates[i].strftime("%Y-%m-%d")
        if r:
            simplified_daily_records.append(r)
        else:
            simplified_daily_records.append({"date": d_str, "status": "no data"})

    record = {
        "schema_version": 1,
        "period_type": "week",
        "period_key": week_id,
        "period_start": week_start,
        "period_end": week_end,
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
            config.SUMMARIZE_WEEK_PROMPT_PATH,
            {
                "DAILY_RECORDS": json.dumps(
                    simplified_daily_records, ensure_ascii=False, indent=2
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
                    elif key in WEEK_ITEM_KINDS:
                        record["items"].extend(
                            {"kind": key, "body": item, "display_order": idx}
                            for idx, item in enumerate(clean_list)
                        )

        # display_order を kind 単位で振り直す
        record["items"].sort(
            key=lambda x: (WEEK_ITEM_KINDS.index(x["kind"]), x["display_order"])
        )
        for kind in WEEK_ITEM_KINDS:
            kind_items = [i for i in record["items"] if i["kind"] == kind]
            for idx, item in enumerate(kind_items):
                item["display_order"] = idx

    except Exception as e:
        logger.error(f"Failed to generate or parse structured weekly record: {e}")

    # Collect union of project_ids and unresolved project_candidates from daily_records without LLM
    union_project_ids = set()
    union_candidates = []
    seen_candidate_norms = set()

    for r in daily_records:
        if not r:
            continue
        p_ids = r.get("project_ids") or []
        for pid in p_ids:
            if isinstance(pid, int):
                union_project_ids.add(pid)

        pcands = r.get("project_candidates") or []
        for c in pcands:
            if not isinstance(c, dict):
                continue
            status = c.get("status") or "unresolved"
            if status != "unresolved":
                continue
            norm_name = c.get("normalized_name")
            if not norm_name:
                from obsidian_ai_hub.summary.store import normalize_entity_name
                norm_name = normalize_entity_name(c.get("display_name") or c.get("name") or "")
            if norm_name and norm_name not in seen_candidate_norms:
                seen_candidate_norms.add(norm_name)
                union_candidates.append({
                    "display_name": c.get("display_name") or c.get("name"),
                    "domain": c.get("domain") or "personal",
                    "goal": c.get("goal"),
                    "description": c.get("description"),
                    "keywords": c.get("keywords") or [],
                    "start_date": c.get("start_date"),
                    "target_date": c.get("target_date"),
                    "completed_date": c.get("completed_date"),
                    "evidence": c.get("evidence")
                })

    record["project_ids"] = list(union_project_ids)

    # Double check database candidate status to ensure no resolved/rejected ones are inherited as candidates
    from obsidian_ai_hub.database import get_db_connection
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        filtered_candidates = []
        for c in union_candidates:
            from obsidian_ai_hub.summary.store import normalize_entity_name
            norm_name = normalize_entity_name(c["display_name"])
            cursor.execute("SELECT status, candidate_id FROM project_candidates WHERE normalized_name = ?", (norm_name,))
            row = cursor.fetchone()
            if row is not None:
                status = row["status"]
                if status == "resolved":
                    cursor.execute("SELECT project_id FROM projects WHERE normalized_name = ?", (norm_name,))
                    p_row = cursor.fetchone()
                    if p_row is not None:
                        record["project_ids"].append(p_row[0])
                    continue
                elif status == "rejected":
                    continue
            filtered_candidates.append(c)
        record["project_candidates"] = filtered_candidates
        record["project_ids"] = list(set(record["project_ids"]))
    except Exception as e:
        logger.warning("Failed to verify candidate database status during week project inheritance: %s", e)
        record["project_candidates"] = union_candidates
    finally:
        conn.close()

    return record


def format_weekly_record_as_markdown(record: dict) -> str:
    lines = []

    if record.get("summary"):
        lines.append(f"{record['summary']}\n")

    kind_labels = {
        "highlights": "ハイライト",
        "progress": "目標・プロジェクトの前進",
        "learnings": "学び・整理",
        "reflections": "反省・気づき",
        "patterns": "パターン・傾向",
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

    return "\n".join(lines).strip()


def upsert_summary_record(record: dict):
    """
    SQLite summaries テーブルにレコードをupsertする。
    """
    try:
        summary_store.upsert_summary(record)
        logger.info(f"Weekly summary upserted for {record.get('period_key')}")
    except Exception as e:
        logger.error(f"Failed to upsert weekly summary: {e}")


def _coerce_target_date(target_date: datetime | date_type | str | None) -> datetime:
    if target_date is None:
        return datetime.now()
    if isinstance(target_date, datetime):
        return target_date
    if isinstance(target_date, date_type):
        return datetime.combine(target_date, datetime.min.time())
    if isinstance(target_date, str):
        return datetime.strptime(target_date, "%Y-%m-%d")
    raise TypeError(f"Unsupported target_date type: {type(target_date)!r}")


def summarize_week(target_date: datetime | date_type | str | None = None):
    target_date = _coerce_target_date(target_date)
    logger.info("Summarizing week for date: %s", target_date.date())

    # 1. データの準備
    week_dates = get_week_dates(target_date)
    daily_records = load_daily_records(week_dates)

    # 2. 構造化レコードの生成
    structured_record = get_weekly_structured_record(target_date, daily_records)

    if not structured_record.get("summary"):
        logger.error(
            "Failed to generate structured record; skipping persistence and weekly note update"
        )
        return

    # 3. SQLiteへの保存
    upsert_summary_record(structured_record)

    # 4. ウィークリーノートへの書き込み 260719: 人間の書いたものと、AIの書いたものを混ぜないためにデイリーノートへの追記は中止
    # weekly_note = reader.get_weekly_note_content(target_date)
    # weekly_note_path = reader.get_weekly_note_path(target_date)
    # markdown_content = format_weekly_record_as_markdown(structured_record)

    # if "## AIによる要約" in weekly_note:
    #     pattern = r"(## AIによる要約\n)(.*?)(?=\n## |$)"
    #     new_weekly_note = re.sub(
    #         pattern,
    #         lambda m: f"{m.group(1)}\n{markdown_content}\n\n",
    #         weekly_note,
    #         flags=re.DOTALL
    #     )
    # else:
    #     new_weekly_note = weekly_note.rstrip() + f"\n\n## AIによる要約\n\n{markdown_content}\n"

    # weekly_note_path.parent.mkdir(parents=True, exist_ok=True)
    # with open(weekly_note_path, "w", encoding="utf-8") as f:
    #     f.write(new_weekly_note)

    # logger.info(f"Weekly summary updated in: {weekly_note_path}")


def main(target_date: datetime | date_type | str | None = None):
    # デフォルトでは実行日の属する週を対象とする
    summarize_week(target_date)


if __name__ == "__main__":
    main()
