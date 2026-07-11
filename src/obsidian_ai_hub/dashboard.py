from __future__ import annotations

import json
import logging
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, date as date_cls, timedelta
from pathlib import Path
from typing import Iterable
from urllib.parse import quote

from obsidian_ai_hub.utils import config, reader

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
YEARS_DIRNAME = "years"


def _read_jsonl(path: Path) -> list[dict]:
    records: list[dict] = []
    if not path.exists():
        return records

    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("Skipping malformed JSONL line in %s", path)
                    continue
                if isinstance(data, dict):
                    records.append(data)
    except Exception as e:
        logger.error("Failed to read JSONL file %s: %s", path, e)
    return records


def _safe_json(obj: object) -> str:
    text = json.dumps(obj, ensure_ascii=False, indent=2)
    return text.replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def _normalize_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip()


def _coerce_text_list(value: object, limit: int | None = None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list):
        items = value
    else:
        items = [value]

    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item is None:
            continue
        text = _normalize_text(str(item))
        if not text:
            continue
        if text in seen:
            continue
        seen.add(text)
        result.append(text)
        if limit is not None and len(result) >= limit:
            break
    return result


def _keyword_bump(bucket: dict[str, dict[str, object]], keywords: object) -> None:
    for keyword in _coerce_text_list(keywords):
        key = _normalize_text(keyword).casefold()
        entry = bucket.setdefault(key, {"label": keyword, "count": 0})
        if len(keyword) > len(str(entry["label"])):
            entry["label"] = keyword
        entry["count"] = int(entry["count"]) + 1


def _top_keyword_labels(bucket: dict[str, dict[str, object]], limit: int) -> list[str]:
    items = sorted(
        bucket.values(),
        key=lambda entry: (int(entry["count"]), len(str(entry["label"]))),
        reverse=True,
    )
    return [str(entry["label"]) for entry in items[:limit]]


def _month_key_from_date(value: date_cls) -> str:
    return value.strftime("%Y-%m")


def _months_covered(start_date: date_cls, end_date: date_cls) -> list[str]:
    months: list[str] = []
    current = date_cls(start_date.year, start_date.month, 1)
    end_marker = date_cls(end_date.year, end_date.month, 1)
    while current <= end_marker:
        months.append(current.strftime("%Y-%m"))
        if current.month == 12:
            current = date_cls(current.year + 1, 1, 1)
        else:
            current = date_cls(current.year, current.month + 1, 1)
    return months


def _parse_date(value: str) -> date_cls | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        return None


def _parse_month(value: str) -> date_cls | None:
    try:
        return datetime.strptime(value, "%Y-%m").date()
    except Exception:
        return None


def _relative_to_vault(path: Path) -> str:
    try:
        return path.relative_to(config.VAULT_PATH).as_posix()
    except ValueError:
        return path.as_posix()


def _obsidian_uri(note_path: str | None) -> str | None:
    if not note_path:
        return None
    vault_name = config.VAULT_PATH.name or "Vault"
    return f"obsidian://open?vault={quote(vault_name)}&file={quote(note_path)}"


def _build_note_index() -> dict[str, str]:
    index: dict[str, str] = {}
    if not config.DAILY_PATH.exists():
        return index

    for path in config.DAILY_PATH.rglob("*.md"):
        index.setdefault(path.name, _relative_to_vault(path))
    return index


def _find_note_path(filename: str, note_index: dict[str, str], fallback: Path | None = None) -> str | None:
    if filename in note_index:
        return note_index[filename]
    if fallback is not None:
        return _relative_to_vault(fallback)
    return None


def _daily_note_fallback(date_str: str) -> Path | None:
    parsed = _parse_date(date_str)
    if parsed is None:
        return None
    return reader.get_daily_note_path(datetime.combine(parsed, datetime.min.time()))


def _weekly_note_fallback(week_start_date: str) -> Path | None:
    parsed = _parse_date(week_start_date)
    if parsed is None:
        return None
    return reader.get_weekly_note_path(datetime.combine(parsed, datetime.min.time()))


def _monthly_note_fallback(month: str) -> Path | None:
    parsed = _parse_month(month)
    if parsed is None:
        return None
    return reader.get_monthly_note_path(datetime.combine(parsed, datetime.min.time()))


def _thin_daily_record(record: dict, note_index: dict[str, str]) -> dict | None:
    date_str = str(record.get("date") or "").strip()
    parsed = _parse_date(date_str)
    if parsed is None:
        return None

    source_stats = record.get("source_stats") or {}
    note_path = _find_note_path(f"{date_str}.md", note_index, _daily_note_fallback(date_str))

    return {
        "date": date_str,
        "month": _month_key_from_date(parsed),
        "week_id": f"{parsed.isocalendar().year}-W{parsed.isocalendar().week:02d}",
        "summary": str(record.get("summary") or "").strip() or None,
        "mood": str(record.get("mood") or "").strip() or None,
        "sleep": str(record.get("sleep") or "").strip() or None,
        "topics": _coerce_text_list(record.get("topics"), limit=5),
        "keywords": _coerce_text_list(record.get("keywords"), limit=8),
        "activity_count": int(source_stats.get("activity_count") or 0),
        "llm_session_count": int(source_stats.get("llm_session_count") or 0),
        "has_daily_note": bool(source_stats.get("has_daily_note")),
        "note_path": note_path,
        "note_uri": _obsidian_uri(note_path),
    }


def _thin_weekly_record(record: dict, note_index: dict[str, str]) -> dict | None:
    week_id = str(record.get("week_id") or "").strip()
    week_start_date = str(record.get("week_start_date") or "").strip()
    week_end_date = str(record.get("week_end_date") or "").strip()
    start_parsed = _parse_date(week_start_date)
    end_parsed = _parse_date(week_end_date)
    if not week_id or start_parsed is None or end_parsed is None:
        return None

    source_stats = record.get("source_stats") or {}
    note_path = _find_note_path(
        f"{week_id}.md",
        note_index,
        _weekly_note_fallback(week_start_date),
    )

    return {
        "week_id": week_id,
        "week_start_date": week_start_date,
        "week_end_date": week_end_date,
        "summary": str(record.get("summary") or "").strip() or None,
        "mood": str(record.get("mood") or "").strip() or None,
        "sleep": str(record.get("sleep") or "").strip() or None,
        "topics": _coerce_text_list(record.get("topics"), limit=5),
        "keywords": _coerce_text_list(record.get("keywords"), limit=8),
        "daily_record_count": int(source_stats.get("daily_record_count") or 0),
        "note_path": note_path,
        "note_uri": _obsidian_uri(note_path),
    }


def _thin_monthly_record(record: dict, note_index: dict[str, str]) -> dict | None:
    month = str(record.get("month") or "").strip()
    if not month:
        return None

    source_stats = record.get("source_stats") or {}
    note_path = _find_note_path(
        f"{month}.md",
        note_index,
        _monthly_note_fallback(month),
    )

    return {
        "month": month,
        "summary": str(record.get("summary") or "").strip() or None,
        "mood": str(record.get("mood") or "").strip() or None,
        "sleep": str(record.get("sleep") or "").strip() or None,
        "topics": _coerce_text_list(record.get("topics"), limit=5),
        "keywords": _coerce_text_list(record.get("keywords"), limit=8),
        "weekly_record_count": int(source_stats.get("weekly_record_count") or 0),
        "note_path": note_path,
        "note_uri": _obsidian_uri(note_path),
    }


def _discover_source_years() -> list[int]:
    years: list[int] = []
    if not config.ACTIVITY_PATH.exists():
        return years

    for path in config.ACTIVITY_PATH.iterdir():
        if path.is_dir() and path.name.isdigit() and len(path.name) == 4:
            years.append(int(path.name))
    return sorted(set(years))


def _build_year_payload(year: int, note_index: dict[str, str]) -> dict:
    year_dir = config.ACTIVITY_PATH / str(year)

    daily_by_date: dict[str, dict] = {}
    daily_topic_counter: Counter[str] = Counter()
    daily_keyword_stats: dict[str, dict[str, object]] = {}
    month_daily_counts: Counter[str] = Counter()
    month_weekly_counts: Counter[str] = Counter()
    month_topic_counters: defaultdict[str, Counter[str]] = defaultdict(Counter)
    month_keyword_stats: defaultdict[str, dict[str, dict[str, object]]] = defaultdict(dict)

    for month in range(1, 13):
        monthly_daily_file = year_dir / f"{month:02d}" / f"{year}-{month:02d}.jsonl"
        for record in _read_jsonl(monthly_daily_file):
            thin = _thin_daily_record(record, note_index)
            if thin is None:
                continue
            daily_by_date[thin["date"]] = thin
            month_daily_counts[thin["month"]] += 1
            daily_topic_counter.update(thin["topics"])
            month_topic_counters[thin["month"]].update(thin["topics"])
            _keyword_bump(daily_keyword_stats, thin["keywords"])
            _keyword_bump(month_keyword_stats[thin["month"]], thin["keywords"])

    weekly_by_id: dict[str, dict] = {}
    weekly_file = year_dir / f"{year}-week.jsonl"
    for record in _read_jsonl(weekly_file):
        thin = _thin_weekly_record(record, note_index)
        if thin is None:
            continue
        weekly_by_id[thin["week_id"]] = thin
        start_parsed = _parse_date(thin["week_start_date"])
        end_parsed = _parse_date(thin["week_end_date"])
        if start_parsed is None or end_parsed is None:
            continue
        for month in _months_covered(start_parsed, end_parsed):
            month_weekly_counts[month] += 1

    monthly_by_month: dict[str, dict] = {}
    monthly_file = year_dir / f"{year}.jsonl"
    for record in _read_jsonl(monthly_file):
        thin = _thin_monthly_record(record, note_index)
        if thin is None:
            continue
        monthly_by_month[thin["month"]] = thin

    month_keys = sorted(set(month_daily_counts) | set(month_weekly_counts) | set(monthly_by_month))
    months: list[dict] = []
    for month in month_keys:
        monthly_record = monthly_by_month.get(month) or {}
        topics = monthly_record.get("topics") or month_topic_counters[month].most_common(5)
        if topics and not isinstance(topics[0], str):
            topics = [topic for topic, _count in topics]
        keywords = monthly_record.get("keywords") or _top_keyword_labels(month_keyword_stats[month], 8)
        note_path = monthly_record.get("note_path")
        note_uri = monthly_record.get("note_uri")
        months.append(
            {
                "month": month,
                "daily_count": int(month_daily_counts[month]),
                "weekly_count": int(month_weekly_counts[month]),
                "summary": monthly_record.get("summary"),
                "mood": monthly_record.get("mood"),
                "sleep": monthly_record.get("sleep"),
                "topics": topics if isinstance(topics, list) else list(topics),
                "keywords": keywords if isinstance(keywords, list) else list(keywords),
                "has_monthly_note": bool(note_path),
                "note_path": note_path,
                "note_uri": note_uri,
            }
        )

    daily_records = sorted(daily_by_date.values(), key=lambda item: item["date"], reverse=True)
    weekly_records = sorted(weekly_by_id.values(), key=lambda item: item["week_id"], reverse=True)
    monthly_records = sorted(monthly_by_month.values(), key=lambda item: item["month"], reverse=True)
    months = sorted(months, key=lambda item: item["month"], reverse=True)

    return {
        "schema_version": SCHEMA_VERSION,
        "year": year,
        "generated_at": datetime.now().isoformat(),
        "daily": daily_records,
        "weekly": weekly_records,
        "monthly": monthly_records,
        "months": months,
        "aggregates": {
            "daily_count": len(daily_records),
            "weekly_count": len(weekly_records),
            "monthly_count": len(monthly_records),
            "activity_count": sum(record["activity_count"] for record in daily_records),
            "llm_session_count": sum(record["llm_session_count"] for record in daily_records),
            "top_topics": [topic for topic, _count in daily_topic_counter.most_common(8)],
            "top_keywords": _top_keyword_labels(daily_keyword_stats, 12),
        },
    }


def _load_year_payload(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error("Failed to load dashboard year payload %s: %s", path, e)
        return None
    if isinstance(data, dict) and data.get("schema_version") == SCHEMA_VERSION:
        return data
    return None


def _discover_output_years(output_dir: Path) -> list[int]:
    years_dir = output_dir / YEARS_DIRNAME
    if not years_dir.exists():
        return []

    years: list[int] = []
    for path in years_dir.glob("*.json"):
        if path.stem.isdigit():
            years.append(int(path.stem))
    return sorted(set(years))


def _build_manifest(year_payloads: dict[int, dict]) -> dict:
    available_years = sorted(year_payloads)
    totals = {
        "daily_count": 0,
        "weekly_count": 0,
        "monthly_count": 0,
        "activity_count": 0,
        "llm_session_count": 0,
    }
    top_topics: Counter[str] = Counter()
    keyword_stats: dict[str, dict[str, object]] = {}
    latest_daily: str | None = None
    latest_weekly: str | None = None
    latest_monthly: str | None = None

    for year in available_years:
        payload = year_payloads[year]
        aggregates = payload.get("aggregates") or {}
        totals["daily_count"] += int(aggregates.get("daily_count") or 0)
        totals["weekly_count"] += int(aggregates.get("weekly_count") or 0)
        totals["monthly_count"] += int(aggregates.get("monthly_count") or 0)
        totals["activity_count"] += int(aggregates.get("activity_count") or 0)
        totals["llm_session_count"] += int(aggregates.get("llm_session_count") or 0)
        top_topics.update(aggregates.get("top_topics") or [])
        _keyword_bump(keyword_stats, aggregates.get("top_keywords") or [])

        daily = payload.get("daily") or []
        weekly = payload.get("weekly") or []
        monthly = payload.get("monthly") or []
        if daily:
            candidate = daily[0].get("date")
            if candidate and (latest_daily is None or candidate > latest_daily):
                latest_daily = candidate
        if weekly:
            candidate = weekly[0].get("week_id")
            if candidate and (latest_weekly is None or candidate > latest_weekly):
                latest_weekly = candidate
        if monthly:
            candidate = monthly[0].get("month")
            if candidate and (latest_monthly is None or candidate > latest_monthly):
                latest_monthly = candidate

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(),
        "vault_name": config.VAULT_PATH.name or "Vault",
        "available_years": available_years,
        "count": len(available_years),
        "totals": totals,
        "top_topics": [topic for topic, _count in top_topics.most_common(8)],
        "top_keywords": _top_keyword_labels(keyword_stats, 12),
        "latest": {
            "daily": latest_daily,
            "weekly": latest_weekly,
            "monthly": latest_monthly,
        },
        "year_files": {str(year): f"{YEARS_DIRNAME}/{year}.json" for year in available_years},
    }


def _render_index_html(payload: dict) -> str:
    template = """<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Obsidian Dashboard</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4efe6;
      --bg-2: #e6dcc9;
      --panel: rgba(255, 252, 247, 0.86);
      --panel-border: rgba(89, 60, 26, 0.12);
      --text: #1f1913;
      --muted: #705d49;
      --accent: #a8551f;
      --accent-2: #567c73;
      --shadow: 0 18px 40px rgba(71, 46, 19, 0.12);
      --radius: 20px;
      --radius-sm: 14px;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Hiragino Sans", "Noto Sans JP", sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at top left, rgba(168, 85, 31, 0.14), transparent 36%),
        radial-gradient(circle at right top, rgba(86, 124, 115, 0.16), transparent 30%),
        linear-gradient(180deg, var(--bg), var(--bg-2));
      min-height: 100vh;
    }
    .shell {
      max-width: 1440px;
      margin: 0 auto;
      padding: 28px;
    }
    .hero {
      display: grid;
      gap: 18px;
      grid-template-columns: 1.3fr 0.9fr;
      align-items: end;
      margin-bottom: 20px;
    }
    .title-block {
      padding: 28px;
      border: 1px solid var(--panel-border);
      border-radius: 28px;
      background: linear-gradient(180deg, rgba(255,255,255,0.76), rgba(255,255,255,0.52));
      backdrop-filter: blur(10px);
      box-shadow: var(--shadow);
    }
    h1 {
      margin: 0 0 10px;
      font-size: clamp(2rem, 4vw, 3.8rem);
      letter-spacing: 0.02em;
    }
    .subtitle {
      margin: 0;
      color: var(--muted);
      line-height: 1.6;
    }
    .toolbar, .stats, .month-rail, .panel-grid { display: grid; gap: 12px; }
    .toolbar {
      grid-template-columns: 180px 220px 1fr auto auto;
      margin-top: 18px;
      align-items: center;
    }
    .control {
      width: 100%;
      padding: 14px 16px;
      border: 1px solid rgba(112, 93, 73, 0.18);
      border-radius: 14px;
      background: rgba(255,255,255,0.72);
      color: var(--text);
      font: inherit;
    }
    .button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 14px 18px;
      border-radius: 14px;
      border: 1px solid rgba(168, 85, 31, 0.18);
      background: linear-gradient(180deg, rgba(168,85,31,0.16), rgba(168,85,31,0.08));
      color: var(--accent);
      font-weight: 700;
      cursor: pointer;
      text-decoration: none;
    }
    .stats {
      grid-template-columns: repeat(5, minmax(0, 1fr));
      margin: 18px 0 14px;
    }
    .stat {
      padding: 18px;
      border-radius: var(--radius);
      border: 1px solid var(--panel-border);
      background: var(--panel);
      box-shadow: var(--shadow);
    }
    .stat-label {
      font-size: 0.82rem;
      color: var(--muted);
      margin-bottom: 10px;
    }
    .stat-value {
      font-size: 1.8rem;
      font-weight: 800;
      letter-spacing: 0.01em;
    }
    .chips { display: flex; flex-wrap: wrap; gap: 8px; }
    .chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 8px 12px;
      border-radius: 999px;
      background: rgba(255,255,255,0.72);
      border: 1px solid rgba(112, 93, 73, 0.14);
      color: var(--text);
      font-size: 0.88rem;
    }
    .section {
      margin-top: 18px;
      padding: 18px;
      border: 1px solid var(--panel-border);
      border-radius: 24px;
      background: var(--panel);
      box-shadow: var(--shadow);
    }
    .section-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin-bottom: 12px;
    }
    .section h2 {
      margin: 0;
      font-size: 1.2rem;
    }
    .month-rail {
      grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    }
    .month-btn {
      text-align: left;
      padding: 14px;
      border-radius: 16px;
      border: 1px solid rgba(112, 93, 73, 0.16);
      background: rgba(255,255,255,0.72);
      color: var(--text);
      cursor: pointer;
    }
    .month-btn.active {
      border-color: rgba(168, 85, 31, 0.42);
      box-shadow: 0 0 0 2px rgba(168, 85, 31, 0.1) inset;
    }
    .month-title {
      font-weight: 800;
      margin-bottom: 6px;
    }
    .month-meta, .meta {
      color: var(--muted);
      font-size: 0.88rem;
      line-height: 1.5;
    }
    .record-list {
      display: grid;
      gap: 12px;
      margin-top: 12px;
    }
    .record {
      padding: 16px;
      border-radius: 18px;
      background: rgba(255,255,255,0.76);
      border: 1px solid rgba(112, 93, 73, 0.14);
      display: grid;
      gap: 10px;
    }
    .record-top {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: start;
    }
    .record-title {
      font-size: 1rem;
      font-weight: 800;
      margin: 0;
    }
    .record-body {
      color: var(--text);
      line-height: 1.65;
    }
    .record-footer {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
    }
    .empty {
      padding: 18px;
      color: var(--muted);
      border: 1px dashed rgba(112, 93, 73, 0.22);
      border-radius: 16px;
      background: rgba(255,255,255,0.42);
    }
    .note-link {
      color: var(--accent-2);
      font-weight: 700;
      text-decoration: none;
    }
    .muted {
      color: var(--muted);
    }
    .two-col {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 18px;
    }
    @media (max-width: 1100px) {
      .hero, .toolbar, .stats, .two-col { grid-template-columns: 1fr; }
      .shell { padding: 16px; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <section class="hero">
      <div class="title-block">
        <h1>Obsidian Dashboard</h1>
        <p class="subtitle">
          日次・週次・月次の要約を、静的 JSON からまとめて読むためのダッシュボードです。
          ノート本体へのリンクは Obsidian URI を使います。
        </p>
        <div class="toolbar">
          <select id="yearSelect" class="control" aria-label="Year selector"></select>
          <select id="monthSelect" class="control" aria-label="Month selector"></select>
          <input id="searchInput" class="control" type="search" placeholder="検索: summary / keyword / topic / date">
          <a id="resetButton" class="button" href="#">Reset</a>
          <a class="button" href="stats.html" style="background: linear-gradient(180deg, rgba(86,124,115,0.16), rgba(86,124,115,0.08)); border-color: rgba(86,124,115,0.18); color: var(--accent-2);">統計</a>
        </div>
      </div>
      <div class="title-block">
        <div class="chips" id="manifestChips"></div>
      </div>
    </section>

    <section class="stats" id="stats"></section>

    <section class="section">
      <div class="section-head">
        <h2>Month Overview</h2>
        <div class="meta" id="monthSummaryMeta"></div>
      </div>
      <div class="month-rail" id="monthRail"></div>
    </section>

    <section class="two-col">
      <section class="section">
        <div class="section-head">
          <h2>Top Topics</h2>
          <div class="meta" id="topicSectionMeta">selected year</div>
        </div>
        <div class="chips" id="topicChips"></div>
      </section>
      <section class="section">
        <div class="section-head">
          <h2>Top Keywords</h2>
          <div class="meta" id="keywordSectionMeta">selected year</div>
        </div>
        <div class="chips" id="keywordChips"></div>
      </section>
    </section>

    <section class="section">
      <div class="section-head">
        <h2>Monthly Records</h2>
        <div class="meta" id="monthlyMeta"></div>
      </div>
      <div class="record-list" id="monthlyList"></div>
    </section>

    <section class="section">
      <div class="section-head">
        <h2>Weekly Records</h2>
        <div class="meta" id="weeklyMeta"></div>
      </div>
      <div class="record-list" id="weeklyList"></div>
    </section>

    <section class="section">
      <div class="section-head">
        <h2>Daily Records</h2>
        <div class="meta" id="dailyMeta"></div>
      </div>
      <div class="record-list" id="dailyList"></div>
    </section>
  </main>

  <script>
    window.__DASHBOARD_BOOTSTRAP__ = __BOOTSTRAP_JSON__;
  </script>
  <script>
    const bootstrap = window.__DASHBOARD_BOOTSTRAP__;
    const manifest = bootstrap.manifest || {};
    const years = bootstrap.years || {};

    const yearSelect = document.getElementById('yearSelect');
    const searchInput = document.getElementById('searchInput');
    const monthSelect = document.getElementById('monthSelect');
    const resetButton = document.getElementById('resetButton');
    const statsEl = document.getElementById('stats');
    const monthRailEl = document.getElementById('monthRail');
    const manifestChips = document.getElementById('manifestChips');
    const topicChips = document.getElementById('topicChips');
    const keywordChips = document.getElementById('keywordChips');
    const dailyList = document.getElementById('dailyList');
    const weeklyList = document.getElementById('weeklyList');
    const monthlyList = document.getElementById('monthlyList');
    const dailyMeta = document.getElementById('dailyMeta');
    const weeklyMeta = document.getElementById('weeklyMeta');
    const monthlyMeta = document.getElementById('monthlyMeta');
    const monthSummaryMeta = document.getElementById('monthSummaryMeta');

    const defaultYear = String(
      (manifest.latest && manifest.latest.daily && manifest.latest.daily.slice(0, 4)) ||
      (manifest.available_years && manifest.available_years[manifest.available_years.length - 1]) ||
      new Date().getFullYear()
    );

    const state = {
      year: defaultYear,
      query: '',
      month: 'all',
    };

    function escapeHtml(value) {
      return String(value || '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
    }

    function formatDate(dateStr) {
      if (!dateStr) return '';
      const d = new Date(dateStr + 'T00:00:00');
      const weekdays = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
      return d.getFullYear() + '/' + String(d.getMonth() + 1).padStart(2, '0')
        + '/' + String(d.getDate()).padStart(2, '0')
        + '(' + weekdays[d.getDay()] + ')';
    }

    function obsidianUri(notePath) {
      if (!notePath) {
        return '';
      }
      return 'obsidian://open?vault=' + encodeURIComponent(manifest.vault_name || 'Vault')
        + '&file=' + encodeURIComponent(notePath);
    }

    function yearData() {
      return years[state.year] || {daily: [], weekly: [], monthly: [], months: [], aggregates: {}};
    }

    function makeHaystack(item) {
      return JSON.stringify(item).toLowerCase();
    }

    function matchesQuery(item) {
      if (!state.query) {
        return true;
      }
      return makeHaystack(item).includes(state.query);
    }

    function matchesMonth(item, kind) {
      if (state.month === 'all') {
        return true;
      }
      if (kind === 'daily') {
        return item.month === state.month || String(item.date || '').startsWith(state.month);
      }
      if (kind === 'weekly') {
        const startMonth = String(item.week_start_date || '').slice(0, 7);
        const endMonth = String(item.week_end_date || '').slice(0, 7);
        return state.month >= startMonth && state.month <= endMonth;
      }
      if (kind === 'monthly') {
        return item.month === state.month;
      }
      return true;
    }

    function sortDaily(items) {
      return [...items].sort((a, b) => String(a.date || '').localeCompare(String(b.date || '')));
    }

    function sortWeekly(items) {
      return [...items].sort((a, b) => String(a.week_id || '').localeCompare(String(b.week_id || '')));
    }

    function sortMonthly(items) {
      return [...items].sort((a, b) => String(a.month || '').localeCompare(String(b.month || '')));
    }

    function renderStats(data) {
      const a = data.aggregates || {};
      const cards = [
        ['Daily', a.daily_count || 0],
        ['Weekly', a.weekly_count || 0],
        ['Monthly', a.monthly_count || 0],
        ['Activity', a.activity_count || 0],
        ['Sessions', a.llm_session_count || 0],
      ];
      statsEl.innerHTML = cards.map(([label, value]) => `
        <article class="stat">
          <div class="stat-label">${escapeHtml(label)}</div>
          <div class="stat-value">${escapeHtml(value)}</div>
        </article>
      `).join('');

      const chips = [];
      if (manifest.generated_at) {
        chips.push(['Generated', manifest.generated_at]);
      }
      if (manifest.available_years && manifest.available_years.length) {
        chips.push(['Years', manifest.available_years.join(', ')]);
      }
      chips.push(['Vault', manifest.vault_name || 'Vault']);
      manifestChips.innerHTML = chips.map(([label, value]) => `<span class="chip"><strong>${escapeHtml(label)}:</strong> ${escapeHtml(value)}</span>`).join('');
    }

    function renderYearSelect() {
      const options = (manifest.available_years || []).slice().reverse().map(String);
      yearSelect.innerHTML = options.map((year) => `<option value="${escapeHtml(year)}">${escapeHtml(year)}</option>`).join('');
      if (options.includes(state.year)) {
        yearSelect.value = state.year;
      } else if (options.length) {
        state.year = options[0];
        yearSelect.value = state.year;
      }
    }

    function renderMonthSelect(data) {
      const months = ['all', ...(data.months || []).map((month) => month.month)];
      monthSelect.innerHTML = months.map((month) => {
        const label = month === 'all' ? 'All months' : month;
        return `<option value="${escapeHtml(month)}">${escapeHtml(label)}</option>`;
      }).join('');
      monthSelect.value = state.month;
      if (!months.includes(state.month)) {
        state.month = 'all';
        monthSelect.value = 'all';
      }
    }

    function monthTopics(data) {
      if (state.month === 'all') return (data.aggregates && data.aggregates.top_topics) || [];
      const monthly = (data.monthly || []).find(m => m.month === state.month);
      if (monthly && monthly.topics && monthly.topics.length) return monthly.topics;
      const weekly = (data.weekly || []).filter(w => {
        const sm = (w.week_start_date || '').slice(0, 7);
        const em = (w.week_end_date || '').slice(0, 7);
        return state.month >= sm && state.month <= em;
      });
      const counter = {};
      weekly.forEach(w => (w.topics || []).forEach(t => { counter[t] = (counter[t] || 0) + 1; }));
      return Object.entries(counter).sort((a, b) => b[1] - a[1]).slice(0, 8).map(e => e[0]);
    }

    function monthKeywords(data) {
      if (state.month === 'all') return (data.aggregates && data.aggregates.top_keywords) || [];
      const monthly = (data.monthly || []).find(m => m.month === state.month);
      if (monthly && monthly.keywords && monthly.keywords.length) return monthly.keywords;
      const weekly = (data.weekly || []).filter(w => {
        const sm = (w.week_start_date || '').slice(0, 7);
        const em = (w.week_end_date || '').slice(0, 7);
        return state.month >= sm && state.month <= em;
      });
      const stats = {};
      weekly.forEach(w => (w.keywords || []).forEach(k => {
        const key = k.toLowerCase();
        const entry = stats[key] || (stats[key] = {label: k, count: 0});
        if (k.length > entry.label.length) entry.label = k;
        entry.count++;
      }));
      return Object.values(stats).sort((a, b) => b.count - a.count).slice(0, 12).map(e => e.label);
    }

    function renderTopicChips(data) {
      const topics = monthTopics(data);
      topicChips.innerHTML = topics.length
        ? topics.map((topic) => `<span class="chip">${escapeHtml(topic)}</span>`).join('')
        : '<div class="empty">No topic data.</div>';
    }

    function renderKeywordChips(data) {
      const keywords = monthKeywords(data);
      keywordChips.innerHTML = keywords.length
        ? keywords.map((keyword) => `<span class="chip">${escapeHtml(keyword)}</span>`).join('')
        : '<div class="empty">No keyword data.</div>';
    }

    function renderTopicKeywordMeta() {
      const ctx = state.month === 'all' ? state.year : state.month;
      document.getElementById('topicSectionMeta').textContent = ctx;
      document.getElementById('keywordSectionMeta').textContent = ctx;
    }

    function renderMonthRail(data) {
      const months = [...(data.months || [])].sort((a, b) => String(b.month || '').localeCompare(String(a.month || '')));
      if (!months.length) {
        monthRailEl.innerHTML = '<div class="empty">No month summaries yet.</div>';
        monthSummaryMeta.textContent = '';
        return;
      }

      monthRailEl.innerHTML = months.map((month) => {
        const active = month.month === state.month ? ' active' : '';
        const title = month.month;
        const summary = month.summary || 'No summary';
        return `
          <button class="month-btn${active}" data-month="${escapeHtml(month.month)}" type="button">
            <div class="month-title">${escapeHtml(title)}</div>
            <div class="month-meta">${escapeHtml(summary)}</div>
            <div class="month-meta">${escapeHtml(month.daily_count || 0)} daily / ${escapeHtml(month.weekly_count || 0)} weekly</div>
          </button>
        `;
      }).join('');

      monthRailEl.querySelectorAll('[data-month]').forEach((button) => {
        button.addEventListener('click', () => {
          state.month = button.getAttribute('data-month') || 'all';
          monthSelect.value = state.month;
          render();
        });
      });

      const selected = months.find((month) => month.month === state.month);
      monthSummaryMeta.textContent = selected
        ? `${selected.daily_count || 0} daily, ${selected.weekly_count || 0} weekly`
        : `${months.length} months available`;
    }

    function renderRecordList(target, items, kind) {
      const filtered = sortByKind(items, kind).filter((item) => matchesQuery(item) && matchesMonth(item, kind));
      target.innerHTML = filtered.length ? filtered.map((item) => renderRecord(item, kind)).join('') : '<div class="empty">No records match the current filter.</div>';
      return filtered.length;
    }

    function sortByKind(items, kind) {
      if (kind === 'daily') return sortDaily(items);
      if (kind === 'weekly') return sortWeekly(items);
      return sortMonthly(items);
    }

    function renderRecord(item, kind) {
      const title = kind === 'daily'
        ? formatDate(item.date)
        : kind === 'weekly'
          ? item.week_id
          : item.month;
      const subtitle = kind === 'daily'
        ? `${item.activity_count || 0} activity / ${item.llm_session_count || 0} sessions`
        : kind === 'weekly'
          ? `${formatDate(item.week_start_date)} → ${formatDate(item.week_end_date)} / ${item.daily_record_count || 0} daily`
          : `${item.weekly_record_count || 0} weekly summaries`;
      const topics = (item.topics || []).map((topic) => `<span class="chip">${escapeHtml(topic)}</span>`).join('');
      const keywords = (item.keywords || []).map((keyword) => `<span class="chip">${escapeHtml(keyword)}</span>`).join('');
      const summary = item.summary || 'No summary';
      const noteUri = item.note_uri || obsidianUri(item.note_path);
      const noteLink = noteUri ? `<a class="note-link" href="${escapeHtml(noteUri)}" target="_blank" rel="noreferrer">Open note</a>` : '<span class="muted">No note found</span>';

      return `
        <article class="record">
          <div class="record-top">
            <div>
              <h3 class="record-title">${escapeHtml(title)}</h3>
              <div class="meta">${escapeHtml(subtitle)}</div>
            </div>
            <div class="meta">${escapeHtml(item.note_path || '')}</div>
          </div>
          <div class="record-body">${escapeHtml(summary)}</div>
          <div class="chips">${topics}</div>
          <div class="chips">${keywords}</div>
          <div class="record-footer">
            <div class="meta">${item.mood ? `Mood: ${escapeHtml(item.mood)}` : ''}${item.sleep ? ` ${item.mood ? '· ' : ''}Sleep: ${escapeHtml(item.sleep)}` : ''}</div>
            <div>${noteLink}</div>
          </div>
        </article>
      `;
    }

    function renderCounts(data) {
      const dailyCount = renderRecordList(dailyList, data.daily || [], 'daily');
      const weeklyCount = renderRecordList(weeklyList, data.weekly || [], 'weekly');
      const monthlyCount = renderRecordList(monthlyList, data.monthly || [], 'monthly');
      dailyMeta.textContent = `${dailyCount} records shown`;
      weeklyMeta.textContent = `${weeklyCount} records shown`;
      monthlyMeta.textContent = `${monthlyCount} records shown`;
    }

    function render() {
      const data = yearData();
      renderMonthSelect(data);
      renderStats(data);
      renderTopicChips(data);
      renderKeywordChips(data);
      renderTopicKeywordMeta();
      renderMonthRail(data);
      renderCounts(data);
    }

    yearSelect.addEventListener('change', () => {
      state.year = yearSelect.value;
      state.month = 'all';
      monthSelect.value = 'all';
      render();
    });
    monthSelect.addEventListener('change', () => {
      state.month = monthSelect.value;
      render();
    });
    searchInput.addEventListener('input', () => {
      state.query = searchInput.value.trim().toLowerCase();
      render();
    });
    resetButton.addEventListener('click', (event) => {
      event.preventDefault();
      state.query = '';
      state.month = 'all';
      searchInput.value = '';
      monthSelect.value = 'all';
      render();
    });

    renderYearSelect();
    render();
  </script>
</body>
</html>
"""
    return template.replace("__BOOTSTRAP_JSON__", _safe_json(payload))


def _render_stats_html(payload: dict) -> str:
    template = """<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Topic Trends - Obsidian Dashboard</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4efe6;
      --bg-2: #e6dcc9;
      --panel: rgba(255, 252, 247, 0.86);
      --panel-border: rgba(89, 60, 26, 0.12);
      --text: #1f1913;
      --muted: #705d49;
      --accent: #a8551f;
      --accent-2: #567c73;
      --shadow: 0 18px 40px rgba(71, 46, 19, 0.12);
      --radius: 20px;
      --radius-sm: 14px;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Hiragino Sans", "Noto Sans JP", sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at top left, rgba(168, 85, 31, 0.14), transparent 36%),
        radial-gradient(circle at right top, rgba(86, 124, 115, 0.16), transparent 30%),
        linear-gradient(180deg, var(--bg), var(--bg-2));
      min-height: 100vh;
    }
    .shell {
      max-width: 1440px;
      margin: 0 auto;
      padding: 28px;
    }
    .hero {
      display: grid;
      gap: 18px;
      grid-template-columns: 1fr;
      align-items: end;
      margin-bottom: 20px;
    }
    .title-block {
      padding: 28px;
      border: 1px solid var(--panel-border);
      border-radius: 28px;
      background: linear-gradient(180deg, rgba(255,255,255,0.76), rgba(255,255,255,0.52));
      backdrop-filter: blur(10px);
      box-shadow: var(--shadow);
    }
    h1 {
      margin: 0 0 10px;
      font-size: clamp(2rem, 4vw, 3.8rem);
      letter-spacing: 0.02em;
    }
    .subtitle {
      margin: 0;
      color: var(--muted);
      line-height: 1.6;
    }
    .toolbar {
      display: flex;
      gap: 12px;
      margin-top: 18px;
      align-items: center;
      flex-wrap: wrap;
    }
    .control {
      padding: 14px 16px;
      border: 1px solid rgba(112, 93, 73, 0.18);
      border-radius: 14px;
      background: rgba(255,255,255,0.72);
      color: var(--text);
      font: inherit;
    }
    .button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 14px 18px;
      border-radius: 14px;
      border: 1px solid rgba(168, 85, 31, 0.18);
      background: linear-gradient(180deg, rgba(168,85,31,0.16), rgba(168,85,31,0.08));
      color: var(--accent);
      font-weight: 700;
      cursor: pointer;
      text-decoration: none;
    }
    .granularity-selector {
      display: flex;
      gap: 8px;
    }
    .granularity-btn {
      padding: 14px 18px;
      border-radius: 14px;
      border: 1px solid rgba(112, 93, 73, 0.18);
      background: rgba(255,255,255,0.72);
      color: var(--text);
      cursor: pointer;
      font-weight: 700;
      font-family: inherit;
    }
    .granularity-btn.active {
      background: var(--accent);
      color: #fff;
      border-color: var(--accent);
    }
    .chart-container {
      background: var(--panel);
      border: 1px solid var(--panel-border);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      padding: 24px;
      margin-top: 20px;
      position: relative;
    }
    .chart-container h2 {
      margin: 0 0 10px;
      font-size: 1.4rem;
    }
    .chart-scroll-wrapper {
      overflow-x: auto;
      margin-top: 15px;
      border: 1px solid rgba(112, 93, 73, 0.12);
      border-radius: var(--radius-sm);
      background: rgba(255, 255, 255, 0.4);
    }
    .chart-tooltip {
      position: absolute;
      background: rgba(31, 25, 19, 0.95);
      color: #fff;
      padding: 10px 14px;
      border-radius: 8px;
      font-size: 0.85rem;
      pointer-events: none;
      display: none;
      z-index: 100;
      box-shadow: 0 4px 12px rgba(0,0,0,0.15);
      line-height: 1.4;
    }
    .legend {
      display: flex;
      flex-wrap: wrap;
      gap: 15px;
      margin-top: 20px;
      padding: 14px;
      border-radius: var(--radius-sm);
      background: rgba(255, 255, 255, 0.5);
      border: 1px solid rgba(112, 93, 73, 0.12);
    }
    .legend-item {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 0.9rem;
    }
    .legend-color {
      width: 16px;
      height: 16px;
      border-radius: 4px;
    }
    .empty {
      padding: 40px;
      text-align: center;
      color: var(--muted);
      border: 1px dashed rgba(112, 93, 73, 0.22);
      border-radius: 16px;
      background: rgba(255,255,255,0.42);
      font-size: 1.1rem;
    }
    .spacer {
      flex-grow: 1;
    }
    @media (max-width: 1100px) {
      .toolbar { flex-direction: column; align-items: stretch; }
      .spacer { display: none; }
      .shell { padding: 16px; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <section class="hero">
      <div class="title-block">
        <h1>Topic Trends</h1>
        <p class="subtitle">
          日次の topics を元にした時系列の積み上げ棒グラフです。興味関心の移り変わりを視覚的に追うことができます。
        </p>
        <div class="toolbar">
          <select id="yearSelect" class="control" aria-label="Year selector"></select>
          <div class="granularity-selector">
            <button class="granularity-btn" data-g="day" type="button">日次</button>
            <button class="granularity-btn" data-g="week" type="button">週次</button>
            <button class="granularity-btn" data-g="month" type="button">月次</button>
          </div>
          <div class="spacer"></div>
          <a class="button" href="index.html">ダッシュボードに戻る</a>
        </div>
      </div>
    </section>

    <section class="chart-container">
      <h2 id="chartTitle">Topic Distribution</h2>
      <div class="chart-scroll-wrapper">
        <svg id="trendsSvg"></svg>
      </div>
      <div class="chart-tooltip" id="tooltip"></div>
      <div class="legend" id="legend"></div>
    </section>
  </main>

  <script>
    window.__DASHBOARD_BOOTSTRAP__ = __BOOTSTRAP_JSON__;
  </script>
  <script>
    const bootstrap = window.__DASHBOARD_BOOTSTRAP__;
    const manifest = bootstrap.manifest || {};
    const years = bootstrap.years || {};

    const yearSelect = document.getElementById('yearSelect');
    const trendsSvg = document.getElementById('trendsSvg');
    const tooltip = document.getElementById('tooltip');
    const legendEl = document.getElementById('legend');
    const chartTitle = document.getElementById('chartTitle');

    const defaultYear = String(
      (manifest.latest && manifest.latest.daily && manifest.latest.daily.slice(0, 4)) ||
      (manifest.available_years && manifest.available_years[manifest.available_years.length - 1]) ||
      new Date().getFullYear()
    );

    const state = {
      year: defaultYear,
      granularity: 'week', // Default to week
    };

    const colors = ['#a8551f', '#567c73', '#2d6a4f', '#1d3557', '#e07a5f', '#81b29a'];
    const otherColor = '#b0b0b0';

    function escapeHtml(value) {
      return String(value || '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
    }

    function normalizeText(value) {
      if (typeof value !== 'string') return '';
      return value.normalize('NFKC').trim();
    }

    function coerceTextList(value) {
      if (value === null || value === undefined) return [];
      let items = [];
      if (typeof value === 'string') {
        items = [value];
      } else if (Array.isArray(value)) {
        items = value;
      } else {
        items = [value];
      }

      const result = [];
      const seen = new Set();
      items.forEach(item => {
        if (item === null || item === undefined) return;
        const text = normalizeText(String(item));
        if (!text) return;
        if (seen.has(text)) return;
        seen.add(text);
        result.push(text);
      });
      return result;
    }

    function generateDays(year) {
      const dates = [];
      let curr = new Date(Date.UTC(year, 0, 1));
      while (curr.getUTCFullYear() === year) {
        dates.push(curr.toISOString().slice(0, 10));
        curr.setUTCDate(curr.getUTCDate() + 1);
      }
      return dates;
    }

    function getISOWeekString(date) {
      const d = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
      const dayNum = d.getUTCDay() || 7;
      d.setUTCDate(d.getUTCDate() + 4 - dayNum);
      const yearStart = new Date(Date.UTC(d.getUTCFullYear(),0,1));
      const weekNo = Math.ceil((((d - yearStart) / 86400000) + 1)/7);
      return d.getUTCFullYear() + '-W' + String(weekNo).padStart(2, '0');
    }

    function generateWeeks(year) {
      const weeks = new Set();
      let curr = new Date(Date.UTC(year, 0, 1));
      while (curr.getUTCFullYear() === year) {
        weeks.add(getISOWeekString(curr));
        curr.setUTCDate(curr.getUTCDate() + 1);
      }
      return Array.from(weeks).sort();
    }

    function generateMonths(year) {
      const months = [];
      for (let m = 1; m <= 12; m++) {
        months.push(year + '-' + String(m).padStart(2, '0'));
      }
      return months;
    }

    function renderYearSelect() {
      const options = (manifest.available_years || []).slice().reverse().map(String);
      yearSelect.innerHTML = options.map((year) => `<option value="${escapeHtml(year)}">${escapeHtml(year)}年</option>`).join('');
      if (options.includes(state.year)) {
        yearSelect.value = state.year;
      } else if (options.length) {
        state.year = options[0];
        yearSelect.value = state.year;
      }
    }

    function renderLegend(topTopics) {
      legendEl.innerHTML = '';
      if (!topTopics.length) return;

      topTopics.forEach((t, i) => {
        const item = document.createElement('div');
        item.className = 'legend-item';
        item.innerHTML = `
          <span class="legend-color" style="background: ${colors[i % colors.length]}"></span>
          <span class="legend-label">${escapeHtml(t)}</span>
        `;
        legendEl.appendChild(item);
      });

      const item = document.createElement('div');
      item.className = 'legend-item';
      item.innerHTML = `
        <span class="legend-color" style="background: ${otherColor}"></span>
        <span class="legend-label">Other</span>
      `;
      legendEl.appendChild(item);
    }

    function renderChart() {
      trendsSvg.innerHTML = ''; // Clear SVG
      tooltip.style.display = 'none';

      const yearStr = state.year;
      const yearInt = parseInt(yearStr);
      const data = years[yearStr] || {daily: []};
      const daily = data.daily || [];

      // Compute top 6 topics
      const topicCounts = {};
      daily.forEach(r => {
        const rTopics = Array.from(new Set(coerceTextList(r.topics)));
        rTopics.forEach(t => {
          topicCounts[t] = (topicCounts[t] || 0) + 1;
        });
      });
      const topTopics = Object.entries(topicCounts)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 6)
        .map(entry => entry[0]);

      if (daily.length === 0) {
        trendsSvg.setAttribute('width', '100%');
        trendsSvg.setAttribute('height', '150');
        trendsSvg.innerHTML = `
          <foreignObject x="0" y="0" width="100%" height="150">
            <div class="empty">データが存在しません。</div>
          </foreignObject>
        `;
        renderLegend([]);
        chartTitle.textContent = `${yearStr}年 トピック推移 (データなし)`;
        return;
      }

      const labelMap = { 'day': '日次', 'week': '週次', 'month': '月次' };
      chartTitle.textContent = `${yearStr}年 トピック推移 (${labelMap[state.granularity]})`;

      // Generate continuous timeline keys
      let keys = [];
      if (state.granularity === 'day') {
        keys = generateDays(yearInt);
      } else if (state.granularity === 'week') {
        keys = generateWeeks(yearInt);
      } else {
        keys = generateMonths(yearInt);
      }

      // Group daily records by granularity key
      const bucketMap = {};
      keys.forEach(k => { bucketMap[k] = []; });

      daily.forEach(r => {
        const dateStr = String(r.date || '').trim();
        if (!dateStr.startsWith(yearStr)) return;
        const parts = dateStr.split('-');
        if (parts.length < 3) return;
        const parsed = new Date(Date.UTC(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2])));
        if (isNaN(parsed)) return;

        let k = '';
        if (state.granularity === 'day') {
          k = dateStr;
        } else if (state.granularity === 'week') {
          k = getISOWeekString(parsed);
        } else {
          k = dateStr.slice(0, 7);
        }

        if (bucketMap[k]) {
          bucketMap[k].push(r);
        }
      });

      // Plot configurations
      let barWidth = 12;
      let barGap = 6;
      if (state.granularity === 'week') {
        barWidth = 24;
        barGap = 10;
      } else if (state.granularity === 'month') {
        barWidth = 48;
        barGap = 20;
      }

      const margin = { left: 60, right: 40, top: 30, bottom: 60 };
      const plotHeight = 350;
      const totalHeight = plotHeight + margin.top + margin.bottom;
      const totalWidth = margin.left + margin.right + keys.length * (barWidth + barGap);

      trendsSvg.setAttribute('width', totalWidth);
      trendsSvg.setAttribute('height', totalHeight);
      trendsSvg.setAttribute('viewBox', `0 0 ${totalWidth} ${totalHeight}`);

      // Draw dashed horizontal lines at percentages
      const percentages = [0, 25, 50, 75, 100];
      percentages.forEach(p => {
        const y = margin.top + plotHeight - (p / 100) * plotHeight;

        // dashed grid line
        const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        line.setAttribute('x1', margin.left);
        line.setAttribute('y1', y);
        line.setAttribute('x2', totalWidth - margin.right);
        line.setAttribute('y2', y);
        line.setAttribute('stroke', 'rgba(112, 93, 73, 0.15)');
        line.setAttribute('stroke-dasharray', '4,4');
        trendsSvg.appendChild(line);

        // Y label
        const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        text.setAttribute('x', margin.left - 10);
        text.setAttribute('y', y + 4);
        text.setAttribute('text-anchor', 'end');
        text.setAttribute('fill', 'var(--muted)');
        text.setAttribute('font-size', '0.75rem');
        text.textContent = p + '%';
        trendsSvg.appendChild(text);
      });

      // Draw Y axis line
      const yAxis = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      yAxis.setAttribute('x1', margin.left);
      yAxis.setAttribute('y1', margin.top);
      yAxis.setAttribute('x2', margin.left);
      yAxis.setAttribute('y2', margin.top + plotHeight);
      yAxis.setAttribute('stroke', 'rgba(112, 93, 73, 0.3)');
      trendsSvg.appendChild(yAxis);

      // Draw bars and X labels
      keys.forEach((key, index) => {
        const x = margin.left + index * (barWidth + barGap);
        const records = bucketMap[key] || [];

        // Check if empty
        if (records.length === 0) {
          drawXLabel(key, x, index);
          return;
        }

        // Count topics in this bucket
        const counts = {};
        topTopics.forEach(t => { counts[t] = 0; });
        counts['Other'] = 0;
        let total = 0;

        records.forEach(r => {
          const rTopics = Array.from(new Set(coerceTextList(r.topics)));
          rTopics.forEach(t => {
            if (topTopics.includes(t)) {
              counts[t] = (counts[t] || 0) + 1;
            } else {
              counts['Other'] = (counts['Other'] || 0) + 1;
            }
            total++;
          });
        });

        if (total > 0) {
          let currentY = margin.top + plotHeight;
          const order = [...topTopics, 'Other'];

          order.forEach(t => {
            const count = counts[t] || 0;
            if (count === 0) return;
            const prop = count / total;
            const segmentHeight = prop * plotHeight;

            const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
            rect.setAttribute('x', x);
            rect.setAttribute('y', currentY - segmentHeight);
            rect.setAttribute('width', barWidth);
            rect.setAttribute('height', segmentHeight);
            rect.setAttribute('fill', t === 'Other' ? otherColor : colors[topTopics.indexOf(t) % colors.length]);
            rect.setAttribute('rx', 2);
            rect.setAttribute('ry', 2);

            // Tooltip attributes
            rect.setAttribute('data-key', key);
            rect.setAttribute('data-topic', t);
            rect.setAttribute('data-count', count);
            rect.setAttribute('data-total', total);
            rect.setAttribute('data-pct', (prop * 100).toFixed(1) + '%');

            trendsSvg.appendChild(rect);
            currentY -= segmentHeight;
          });
        }

        drawXLabel(key, x, index);
      });

      renderLegend(topTopics);

      function drawXLabel(key, x, index) {
        let showLabel = false;
        let labelText = '';

        if (state.granularity === 'day') {
          if (key.endsWith('-01')) {
            showLabel = true;
            const parts = key.split('-');
            labelText = parseInt(parts[1]) + '/1';
          }
        } else if (state.granularity === 'week') {
          const parts = key.split('-W');
          const wkNum = parseInt(parts[1]);
          if (wkNum === 1 || wkNum % 4 === 1) {
            showLabel = true;
            labelText = 'W' + parts[1];
          }
        } else {
          showLabel = true;
          const parts = key.split('-');
          labelText = parseInt(parts[1]) + '月';
        }

        if (showLabel) {
          // tick
          const tick = document.createElementNS('http://www.w3.org/2000/svg', 'line');
          tick.setAttribute('x1', x + barWidth / 2);
          tick.setAttribute('y1', margin.top + plotHeight);
          tick.setAttribute('x2', x + barWidth / 2);
          tick.setAttribute('y2', margin.top + plotHeight + 5);
          tick.setAttribute('stroke', 'rgba(112, 93, 73, 0.5)');
          trendsSvg.appendChild(tick);

          // text
          const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
          text.setAttribute('x', x + barWidth / 2);
          text.setAttribute('y', margin.top + plotHeight + 18);
          text.setAttribute('text-anchor', 'middle');
          text.setAttribute('fill', 'var(--muted)');
          text.setAttribute('font-size', '0.75rem');
          text.textContent = labelText;
          trendsSvg.appendChild(text);
        }
      }
    }

    // Tooltip event listener
    trendsSvg.addEventListener('mousemove', (e) => {
      const target = e.target;
      if (target.tagName === 'rect' && target.hasAttribute('data-topic')) {
        const key = target.getAttribute('data-key');
        const topic = target.getAttribute('data-topic');
        const count = target.getAttribute('data-count');
        const pct = target.getAttribute('data-pct');

        tooltip.style.display = 'block';
        tooltip.innerHTML = `
          <strong>${escapeHtml(key)}</strong><br/>
          トピック: <strong>${escapeHtml(topic)}</strong><br/>
          件数: ${escapeHtml(count)}<br/>
          割合: ${escapeHtml(pct)}
        `;

        const containerRect = document.querySelector('.chart-container').getBoundingClientRect();
        const x = e.clientX - containerRect.left + 15;
        const y = e.clientY - containerRect.top + 15;

        tooltip.style.left = x + 'px';
        tooltip.style.top = y + 'px';
      } else {
        tooltip.style.display = 'none';
      }
    });

    trendsSvg.addEventListener('mouseleave', () => {
      tooltip.style.display = 'none';
    });

    // Toolbar event listeners
    yearSelect.addEventListener('change', () => {
      state.year = yearSelect.value;
      renderChart();
    });

    document.querySelectorAll('.granularity-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.granularity-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        state.granularity = btn.getAttribute('data-g');
        renderChart();
      });
    });

    // Initialize granularity active state
    document.querySelector(`.granularity-btn[data-g="${state.granularity}"]`).classList.add('active');

    renderYearSelect();
    renderChart();
  </script>
</body>
</html>
"""
    return template.replace("__BOOTSTRAP_JSON__", _safe_json(payload))


def build_dashboard(years: Iterable[int] | None = None, output_dir: Path | None = None) -> Path:
    output_dir = output_dir or config.DASHBOARD_PATH
    output_dir.mkdir(parents=True, exist_ok=True)
    years_dir = output_dir / YEARS_DIRNAME
    years_dir.mkdir(parents=True, exist_ok=True)

    note_index = _build_note_index()

    selected_years = sorted({int(year) for year in years}) if years is not None else _discover_source_years()
    for year in selected_years:
        payload = _build_year_payload(year, note_index)
        year_path = years_dir / f"{year}.json"
        year_path.write_text(_safe_json(payload), encoding="utf-8")
        logger.info("Wrote dashboard year payload: %s", year_path)

    existing_years = _discover_output_years(output_dir)
    year_payloads: dict[int, dict] = {}
    for year in existing_years:
        payload = _load_year_payload(years_dir / f"{year}.json")
        if payload is not None:
            year_payloads[year] = payload

    manifest = _build_manifest(year_payloads)
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(_safe_json(manifest), encoding="utf-8")
    logger.info("Wrote dashboard manifest: %s", manifest_path)

    html_path = output_dir / "index.html"
    stats_path = output_dir / "stats.html"
    html_payload = {
        "manifest": manifest,
        "years": {str(year): year_payloads[year] for year in sorted(year_payloads)},
    }
    html_path.write_text(_render_index_html(html_payload), encoding="utf-8")
    logger.info("Wrote dashboard HTML: %s", html_path)

    stats_path.write_text(_render_stats_html(html_payload), encoding="utf-8")
    logger.info("Wrote dashboard stats HTML: %s", stats_path)
    return html_path
