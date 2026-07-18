import json
import logging
import os
import re
import unicodedata
import uuid
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from obsidian_ai_hub.utils import config, extracter, reader, llm_client, prompt
from obsidian_ai_hub.utils.topics import TOPIC_ENUM, normalize_topics

ALLOWED_STABILITY = frozenset({"stable", "tentative", "explicitly_settled"})
STABILITY_DEFAULT = "tentative"


def normalize_stability(raw: object, default: str = STABILITY_DEFAULT) -> str:
    if not isinstance(raw, str) or raw not in ALLOWED_STABILITY:
        logger.warning(
            "Invalid or missing stability value %r; coercing to %r",
            raw, default,
        )
        return default
    return raw

logger = logging.getLogger(__name__)

_embedder = None

def get_embedder():
    global _embedder
    if _embedder is not None:
        return _embedder
    try:
        from obsidian_ai_hub.utils.simple_sbert_embeddings import SimpleSbertEmbeddings
        _embedder = SimpleSbertEmbeddings(
            model_name=config.VAULT_INDEX_EMBEDDER_MODEL,
            allow_network_fallback=config.VAULT_INDEX_ALLOW_NETWORK_FALLBACK
        )
        return _embedder
    except Exception as e:
        logger.warning(f"SBERT Embeddings are not available: {e}. Vector search is disabled.")
        return None


def get_current_timestamp() -> str:
    # Use JST timezone for standard +09:00 formatting
    jst = timezone(timedelta(hours=9))
    return datetime.now(jst).isoformat(timespec="seconds")


def generate_memory_id(date_str: str) -> str:
    clean_date = date_str.replace("-", "")
    rand_part = uuid.uuid4().hex[:6]
    return f"mem_{clean_date}_{rand_part}"


def generate_event_id() -> str:
    return f"evt_{uuid.uuid4().hex[:12]}"


def normalize_content(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    text = re.sub(r'\s+', '', text)
    return text


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    dot_product = sum(a * b for a, b in zip(v1, v2))
    norm_a = sum(a * a for a in v1) ** 0.5
    norm_b = sum(b * b for b in v2) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot_product / (norm_a * norm_b)


# SQLite Store Layer
MEMORY_COLUMNS = [
    "schema_version", "memory_id", "status", "kind", "memory_key", "content",
    "topics", "tags", "evidence", "valid_from", "valid_until", "review_due_at",
    "stability", "sensitivity", "extraction_confidence", "supersedes",
    "contradicts", "provenance", "created_at", "updated_at", "reviewed_by",
    "reviewed_at", "dedup_suggestions", "dedup_assessment",
]

EVENT_COLUMNS = [
    "schema_version", "event_id", "occurred_at", "actor", "event_type",
    "memory_id", "previous_status", "new_status", "changes", "reason",
]


def _assert_test_db_is_not_production(db_path: Path) -> None:
    """Reject the configured production DB while pytest isolation is active."""
    if os.getenv("OBSIDIAN_AI_HUB_TESTING") != "1":
        return

    production_path = os.getenv("OBSIDIAN_AI_HUB_TEST_PRODUCTION_DB_PATH")
    if not production_path:
        raise RuntimeError("OBSIDIAN_AI_HUB_TEST_PRODUCTION_DB_PATH is required in test mode")
    if db_path.expanduser().resolve() == Path(production_path).expanduser().resolve():
        raise RuntimeError("Refusing to open the production memory database while tests are running")


def get_db_connection() -> sqlite3.Connection:
    db_path = Path(config.MEMORY_SQLITE_PATH)
    _assert_test_db_is_not_production(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 30000;")

    # Run migrations/initialization
    cursor = conn.cursor()
    cursor.execute("PRAGMA user_version;")
    current_version = cursor.fetchone()[0]

    if current_version == 0:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                schema_version INTEGER DEFAULT 1,
                memory_id TEXT PRIMARY KEY,
                status TEXT,
                kind TEXT,
                memory_key TEXT,
                content TEXT,
                topics TEXT,
                tags TEXT,
                evidence TEXT,
                valid_from TEXT,
                valid_until TEXT,
                review_due_at TEXT,
                stability TEXT,
                sensitivity TEXT,
                extraction_confidence REAL,
                supersedes TEXT,
                contradicts TEXT,
                provenance TEXT,
                created_at TEXT,
                updated_at TEXT,
                reviewed_by TEXT,
                reviewed_at TEXT,
                dedup_suggestions TEXT,
                dedup_assessment TEXT
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_events (
                schema_version INTEGER DEFAULT 1,
                event_id TEXT PRIMARY KEY,
                occurred_at TEXT,
                actor TEXT,
                event_type TEXT,
                memory_id TEXT,
                previous_status TEXT,
                new_status TEXT,
                changes TEXT,
                reason TEXT,
                FOREIGN KEY(memory_id) REFERENCES memories(memory_id)
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_memory_key ON memories(memory_key);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_events_memory_id_occurred_at ON memory_events(memory_id, occurred_at);")

        conn.execute("PRAGMA user_version = 2;")
        conn.commit()
    elif current_version == 1:
        conn.execute("ALTER TABLE memories ADD COLUMN dedup_assessment TEXT;")
        conn.execute("PRAGMA user_version = 2;")
        conn.commit()

    if current_version <= 2:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS research_themes (
                schema_version INTEGER DEFAULT 3,
                theme_id TEXT PRIMARY KEY,
                theme TEXT NOT NULL,
                direction TEXT,
                kind TEXT,
                why_now TEXT,
                confidence REAL,
                normalized_key TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'candidate',
                duplicate_of_theme_id TEXT,
                duplicate_reason TEXT,
                related_theme_ids TEXT,
                created_at TEXT,
                updated_at TEXT,
                reviewed_at TEXT,
                reviewed_by TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS research_jobs (
                schema_version INTEGER DEFAULT 1,
                job_id TEXT PRIMARY KEY,
                theme_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                generated_title TEXT,
                mode TEXT,
                markdown TEXT,
                error TEXT,
                started_at TEXT,
                finished_at TEXT,
                FOREIGN KEY(theme_id) REFERENCES research_themes(theme_id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_rt_status ON research_themes(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_rt_normalized_key ON research_themes(normalized_key)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_rj_theme_id ON research_jobs(theme_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_rj_status ON research_jobs(status)")
        conn.execute("PRAGMA user_version = 3;")
        conn.commit()

    if current_version <= 3:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS activity_logs (
                schema_version INTEGER DEFAULT 1,
                activity_id TEXT PRIMARY KEY,
                activity_date TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                app_name TEXT,
                window_title TEXT,
                summary TEXT,
                category TEXT,
                keywords TEXT,
                screenshots TEXT,
                source_path TEXT,
                source_line INTEGER,
                UNIQUE(source_path, source_line)
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_logs_date_occurred ON activity_logs(activity_date, occurred_at);")
        conn.execute("PRAGMA user_version = 4;")
        conn.commit()

    if current_version <= 4:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS summaries (
                schema_version INTEGER DEFAULT 1,
                summary_id TEXT PRIMARY KEY,
                period_type TEXT NOT NULL,
                period_key TEXT NOT NULL,
                period_start TEXT,
                period_end TEXT,
                generated_at TEXT,
                summary TEXT,
                keywords TEXT,
                mood TEXT,
                sleep_raw TEXT,
                sleep_hours REAL,
                UNIQUE(period_type, period_key)
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS summary_items (
                summary_item_id TEXT PRIMARY KEY,
                summary_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                body TEXT,
                display_order INTEGER,
                FOREIGN KEY(summary_id) REFERENCES summaries(summary_id) ON DELETE CASCADE
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS topics (
                topic_id TEXT PRIMARY KEY,
                normalized_name TEXT UNIQUE NOT NULL,
                display_name TEXT NOT NULL
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                project_id TEXT PRIMARY KEY,
                normalized_name TEXT UNIQUE NOT NULL,
                display_name TEXT NOT NULL
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS people (
                person_id TEXT PRIMARY KEY,
                normalized_name TEXT UNIQUE NOT NULL,
                display_name TEXT NOT NULL
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS summary_topics (
                summary_id TEXT NOT NULL,
                topic_id TEXT NOT NULL,
                display_order INTEGER,
                PRIMARY KEY(summary_id, topic_id),
                FOREIGN KEY(summary_id) REFERENCES summaries(summary_id) ON DELETE CASCADE,
                FOREIGN KEY(topic_id) REFERENCES topics(topic_id) ON DELETE CASCADE
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS summary_projects (
                summary_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                display_order INTEGER,
                PRIMARY KEY(summary_id, project_id),
                FOREIGN KEY(summary_id) REFERENCES summaries(summary_id) ON DELETE CASCADE,
                FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS summary_people (
                summary_id TEXT NOT NULL,
                person_id TEXT NOT NULL,
                note TEXT,
                display_order INTEGER,
                PRIMARY KEY(summary_id, person_id),
                FOREIGN KEY(summary_id) REFERENCES summaries(summary_id) ON DELETE CASCADE,
                FOREIGN KEY(person_id) REFERENCES people(person_id) ON DELETE CASCADE
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_summaries_period ON summaries(period_type, period_key);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_summaries_period_start ON summaries(period_start);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_summary_items_summary_id ON summary_items(summary_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_summary_items_kind ON summary_items(summary_id, kind);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_summary_topics_summary_id ON summary_topics(summary_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_summary_projects_summary_id ON summary_projects(summary_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_summary_people_summary_id ON summary_people(summary_id);")
        conn.execute("PRAGMA user_version = 5;")
        conn.commit()

    if current_version <= 5:
        # Add vault_id to people table
        conn.execute("ALTER TABLE people ADD COLUMN vault_id TEXT;")

        # Create person_candidates table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS person_candidates (
                candidate_id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                normalized_name TEXT UNIQUE NOT NULL,
                status TEXT NOT NULL DEFAULT 'unresolved'
            );
        """)

        # Create summary_person_candidates table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS summary_person_candidates (
                summary_id TEXT NOT NULL,
                candidate_id TEXT NOT NULL,
                note TEXT,
                display_order INTEGER,
                PRIMARY KEY(summary_id, candidate_id),
                FOREIGN KEY(summary_id) REFERENCES summaries(summary_id) ON DELETE CASCADE,
                FOREIGN KEY(candidate_id) REFERENCES person_candidates(candidate_id) ON DELETE CASCADE
            );
        """)

        # Create indexes
        conn.execute("CREATE INDEX IF NOT EXISTS idx_spc_summary_id ON summary_person_candidates(summary_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pc_normalized_name ON person_candidates(normalized_name);")

        conn.execute("PRAGMA user_version = 6;")
        conn.commit()

    if current_version <= 6:
        run_migration_v7(conn)

    return conn


def run_migration_v7(conn: sqlite3.Connection) -> None:
    """Run the migration schema upgrade for version 7 (person_aliases table)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS person_aliases (
            normalized_name TEXT PRIMARY KEY,
            person_id TEXT NOT NULL,
            display_name TEXT NOT NULL,
            FOREIGN KEY(person_id) REFERENCES people(person_id) ON DELETE CASCADE
        );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_person_aliases_person_id ON person_aliases(person_id);")
    conn.execute("PRAGMA user_version = 7;")
    conn.commit()


def serialize_memory(m: dict) -> dict:
    db_row = dict(m)
    for col in ["topics", "tags", "evidence", "contradicts", "provenance", "dedup_suggestions", "dedup_assessment"]:
        if col in db_row:
            if db_row[col] is not None:
                db_row[col] = json.dumps(db_row[col], ensure_ascii=False)
            else:
                db_row[col] = None
    return db_row


def deserialize_memory(row: dict) -> dict:
    m = dict(row)
    for col in ["topics", "tags", "evidence", "contradicts", "provenance", "dedup_suggestions", "dedup_assessment"]:
        if col in m and m[col] is not None:
            try:
                m[col] = json.loads(m[col])
            except Exception:
                logger.warning("Failed to deserialize %s for memory %s: %r", col, m.get("memory_id"), m[col])
                m[col] = None
    return m


def serialize_event(e: dict) -> dict:
    db_row = dict(e)
    if "changes" in db_row and db_row["changes"] is not None:
        db_row["changes"] = json.dumps(db_row["changes"], ensure_ascii=False)
    return db_row


def deserialize_event(row: dict) -> dict:
    e = dict(row)
    if "changes" in e and e["changes"] is not None:
        try:
            e["changes"] = json.loads(e["changes"])
        except Exception:
            e["changes"] = {}
    return e


def get_approved_memories_path() -> Path:
    vault_copilot = Path(config.VAULT_PATH) / "copilot"
    return vault_copilot / "memory" / "approved.md"


def load_all_memories() -> list[dict]:
    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM memories")
            rows = cursor.fetchall()
            return [deserialize_memory(dict(row)) for row in rows]
    finally:
        conn.close()


def save_all_memories(memories: list[dict]):
    """Replace the memories table with the provided list using upsert semantics.

    The full-table delete-and-insert approach causes FOREIGN KEY constraint
    failures once `memory_events` rows exist for the memories being kept. We
    instead insert/update the new rows and remove the surplus rows after
    detaching their event log so the cascade is safe.
    """
    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            for m in memories:
                db_row = serialize_memory(m)
                columns = ", ".join(MEMORY_COLUMNS)
                placeholders = ", ".join("?" for _ in MEMORY_COLUMNS)
                update_clause = ", ".join(
                    f"{col}=excluded.{col}" for col in MEMORY_COLUMNS if col != "memory_id"
                )
                cursor.execute(
                    f"INSERT INTO memories ({columns}) VALUES ({placeholders}) "
                    f"ON CONFLICT(memory_id) DO UPDATE SET {update_clause}",
                    tuple(db_row.get(col) for col in MEMORY_COLUMNS),
                )

            keep_ids = [m.get("memory_id") for m in memories if m.get("memory_id")]
            cursor.execute("SELECT memory_id FROM memories")
            existing_ids = [row["memory_id"] for row in cursor.fetchall()]
            surplus_ids = [eid for eid in existing_ids if eid not in set(keep_ids)]
            if surplus_ids:
                placeholders = ", ".join("?" for _ in surplus_ids)
                # Drop event log for the surplus IDs first so that
                # `DELETE FROM memories` does not violate the FK.
                cursor.execute(
                    f"DELETE FROM memory_events WHERE memory_id IN ({placeholders})",
                    surplus_ids,
                )
                cursor.execute(
                    f"DELETE FROM memories WHERE memory_id IN ({placeholders})",
                    surplus_ids,
                )
    finally:
        conn.close()


def log_memory_event(
    event_type: str,
    memory_id: str,
    previous_status: Optional[str],
    new_status: str,
    changes: Optional[dict] = None,
    reason: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
    actor: str = "user"
):
    event_record = {
        "schema_version": 1,
        "event_id": generate_event_id(),
        "occurred_at": get_current_timestamp(),
        "actor": actor,
        "event_type": event_type,
        "memory_id": memory_id,
        "previous_status": previous_status,
        "new_status": new_status,
        "changes": changes or {},
        "reason": reason
    }
    db_row = serialize_event(event_record)
    columns = ", ".join(EVENT_COLUMNS)
    placeholders = ", ".join("?" for _ in EVENT_COLUMNS)

    sql = f"INSERT INTO memory_events ({columns}) VALUES ({placeholders})"
    values = tuple(db_row.get(col) for col in EVENT_COLUMNS)

    if conn is not None:
        conn.execute(sql, values)
    else:
        c = get_db_connection()
        try:
            with c:
                c.execute(sql, values)
        finally:
            c.close()


def project_approved_memories():
    approved_md_file = get_approved_memories_path()
    approved_md_file.parent.mkdir(parents=True, exist_ok=True)

    memories = load_all_memories()
    active_approved = [
        m for m in memories
        if m.get("status") == "approved"
    ]

    # Keep a fixed order of kinds
    kinds_order = ["preference", "decision_policy", "fact", "commitment", "pattern", "episode"]
    grouped_memories = {k: [] for k in kinds_order}
    for m in active_approved:
        kind = m.get("kind", "preference")
        if kind not in grouped_memories:
            grouped_memories[kind] = []
        grouped_memories[kind].append(m)

    lines = [
        "# Approved Memories",
        "",
        "> Generated from the SQLite memory database. Do not edit manually.",
        ""
    ]

    for kind in kinds_order:
        m_list = grouped_memories[kind]
        if not m_list:
            continue
        lines.append(f"## {kind}")
        lines.append("")
        for m in m_list:
            lines.append(f"### {m['memory_id']}")
            lines.append("")
            lines.append(m.get("content", ""))
            lines.append("")
            lines.append(f"- Key: `{m.get('memory_key', '')}`")
            lines.append(f"- Stability: `{m.get('stability', 'stable')}`")
            evidence_lines = []
            for ev in (m.get("evidence") or []):
                path = ev.get("path", "")
                if path.endswith(".md"):
                    path = path[:-3]
                quote = ev.get("quote", "")
                evidence_lines.append(f"[[{path}]] — 「{quote}」")
            if evidence_lines:
                lines.append(f"- Evidence: {', '.join(evidence_lines)}")
            lines.append("")

    with open(approved_md_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).strip() + "\n")



def merge_topics_and_tags(existing: list[str], new_vals: list[str]) -> list[str]:
    merged = list(existing)
    for val in new_vals:
        if val not in merged:
            merged.append(val)
    return merged


def merge_evidence(existing: list[dict], new_vals: list[dict]) -> list[dict]:
    merged = list(existing)
    for item in new_vals:
        path = item.get("path", "")
        quote = item.get("quote", "")
        observed_at = item.get("observed_at")

        duplicate = False
        for ex in merged:
            if ex.get("path", "") == path and ex.get("quote", "") == quote and ex.get("observed_at") == observed_at:
                duplicate = True
                break
        if not duplicate:
            merged.append(item)
    return merged


def update_target_with_candidate_data(target: dict, cand: dict, reviewed_by: str) -> dict:
    timestamp_now = get_current_timestamp()
    target["content"] = cand.get("content", "")
    for field in ["kind", "valid_from", "valid_until", "review_due_at", "sensitivity", "extraction_confidence", "contradicts", "provenance"]:
        target[field] = cand.get(field)
    target["stability"] = normalize_stability(cand.get("stability"), default="tentative")
    target["topics"] = merge_topics_and_tags(target.get("topics") or [], cand.get("topics") or [])
    target["tags"] = merge_topics_and_tags(target.get("tags") or [], cand.get("tags") or [])
    target["evidence"] = merge_evidence(target.get("evidence") or [], cand.get("evidence") or [])
    target["updated_at"] = timestamp_now
    target["reviewed_by"] = reviewed_by
    target["reviewed_at"] = timestamp_now
    return target


def run_deduplication(candidate: dict, existing_memories: list[dict], embedder=None) -> list[dict]:
    suggestions = []
    cand_norm = normalize_content(candidate.get("content", ""))
    cand_key = candidate.get("memory_key", "")

    # We only dedup against currently active approved memories
    approved_mems = [m for m in existing_memories if m.get("status") == "approved"]
    if not approved_mems:
        return suggestions

    candidate_vector = None
    if embedder is not None and cand_norm:
        try:
            candidate_vector = embedder.embed_query(cand_norm)
        except Exception as e:
            logger.warning(f"Failed to generate embedding for candidate: {e}")

    for existing in approved_mems:
        ex_norm = normalize_content(existing.get("content", ""))
        ex_key = existing.get("memory_key", "")
        ex_id = existing.get("memory_id", "")

        # 1. memory_key exact match
        if cand_key and cand_key == ex_key:
            if cand_norm == ex_norm:
                suggestions.append({
                    "target_memory_id": ex_id,
                    "relation": "duplicate",
                    "reason": "同じmemory_keyで内容が実質的に一致する",
                    "score": 1.0
                })
            else:
                suggestions.append({
                    "target_memory_id": ex_id,
                    "relation": "supersedes",
                    "reason": "同じmemory_keyで内容が更新されているため置換を提案",
                    "score": 1.0
                })
            continue

        # 2. Normalized content match
        if cand_norm and cand_norm == ex_norm:
            suggestions.append({
                "target_memory_id": ex_id,
                "relation": "duplicate",
                "reason": "内容が既存の記憶と完全に一致する",
                "score": 1.0
            })
            continue

        # 3. Vector similarity
        if candidate_vector is not None and ex_norm:
            try:
                ex_vector = embedder.embed_query(ex_norm)
                sim = cosine_similarity(candidate_vector, ex_vector)
                if sim >= 0.85:
                    suggestions.append({
                        "target_memory_id": ex_id,
                        "relation": "duplicate",
                        "reason": "既存の記憶と非常に内容が類似している",
                        "score": round(sim, 2)
                    })
            except Exception as e:
                logger.warning(f"Failed to compute similarity with {ex_id}: {e}")

    return suggestions


def _week_bounds(
    week_date_str: Optional[str] = None,
    now: Optional[datetime] = None,
) -> tuple[datetime, datetime]:
    """Return the Monday--Sunday ISO week for an explicit date or last completed week."""
    if week_date_str:
        reference_date = datetime.strptime(week_date_str, "%Y-%m-%d")
        week_start = reference_date - timedelta(days=reference_date.weekday())
    else:
        today = now or datetime.now()
        current_week_start = today - timedelta(days=today.weekday())
        week_start = current_week_start - timedelta(days=7)
    return week_start, week_start + timedelta(days=6)


MEMORY_SOURCE_HEADERS = (
    "## 💡 今日の気づき・振り返り",
    "## 📝メモ",
)


def _extract_memory_source_content(note_content: str) -> str:
    """Return only the daily-note sections relevant to memory extraction."""
    sections = []
    for header in MEMORY_SOURCE_HEADERS:
        content = extracter.get_subheader_view(note_content, header)
        if content:
            sections.append(f"{header}\n{content}")
    return "\n\n".join(sections)


def _vault_relative_path(path: Path) -> str:
    try:
        return path.relative_to(config.VAULT_PATH).as_posix()
    except ValueError:
        return path.as_posix()


def _load_daily_structured_record(target_dt: datetime) -> dict:
    target_date_str = target_dt.strftime("%Y-%m-%d")
    try:
        from obsidian_ai_hub.summary import store as summary_store
        record = summary_store.get_summary_by_period("day", target_date_str)
    except Exception as exc:
        logger.warning("Failed to load structured daily record for %s: %s", target_date_str, exc)
        return {}

    if not record:
        return {}

    items = record.get("items", [])
    kind_map = {
        "highlights": "highlights",
        "activities": "activities",
        "learnings": "learnings",
        "reflections": "reflections",
        "gratitude": "gratitude",
    }
    structured = {
        "date": target_date_str,
        "summary": record.get("summary"),
        "topics": record.get("topics", []),
        "people": [{"name": p.get("name", ""), "note": p.get("note", "")} for p in record.get("people", [])],
        "mood": record.get("mood"),
        "sleep": record.get("sleep_raw"),
        "keywords": record.get("keywords", []),
    }
    for item in items:
        kind = item.get("kind")
        body = item.get("body")
        if kind in kind_map and body:
            structured.setdefault(kind, []).append(body)
    return structured


def _load_weekly_memory_sources(week_start: datetime, week_end: datetime) -> tuple[list[dict], list[dict]]:
    daily_notes = []
    structured_records = []
    for offset in range(7):
        target_dt = week_start + timedelta(days=offset)
        note_path = reader.get_daily_note_path(target_dt)
        if note_path.exists():
            try:
                note_content = note_path.read_text(encoding="utf-8")
                daily_notes.append({
                    "date": target_dt.strftime("%Y-%m-%d"),
                    "path": _vault_relative_path(note_path),
                    "content": _extract_memory_source_content(note_content),
                })
            except OSError as exc:
                logger.warning("Failed to read daily note %s: %s", note_path, exc)

        structured_record = _load_daily_structured_record(target_dt)
        if structured_record:
            structured_records.append(structured_record)

    logger.info(
        "Loaded %s daily notes and %s structured records for %s to %s",
        len(daily_notes), len(structured_records), week_start.date(), week_end.date(),
    )
    return daily_notes, structured_records


DEDUP_INPUT_BATCH_TOKEN_LIMIT = 24000
DEDUP_LLM_OUTPUT_TOKEN_LIMIT = 24000


def perform_dedup_assessment_llm(candidates_to_assess: list[dict], existing_memories: list[dict]) -> None:
    if not candidates_to_assess:
        return

    # Find approved memories mapped by memory_id for quick lookup
    approved_map = {m["memory_id"]: m for m in existing_memories if m.get("status") == "approved"}

    # Build comparison groups
    comparison_groups = []
    for cand in candidates_to_assess:
        targets_info = []
        target_ids = []
        for sug in cand.get("dedup_suggestions", []):
            tid = sug.get("target_memory_id")
            target_mem = approved_map.get(tid)
            if target_mem:
                targets_info.append({
                    "memory_id": tid,
                    "memory_key": target_mem.get("memory_key") or "",
                    "content": target_mem.get("content") or "",
                    "relation": sug.get("relation") or "",
                    "score": sug.get("score")
                })
                target_ids.append(tid)

        if targets_info:
            comparison_groups.append({
                "candidate": cand,
                "targets": targets_info,
                "target_ids": target_ids
            })

    if not comparison_groups:
        return

    # Batching based on token estimation
    batches = []
    current_batch = []
    current_tokens = 0

    # Let's estimate tokens of a simple empty template
    try:
        empty_prompt = prompt.render_prompt(
            config.BASE_DIR / "config" / "prompts" / "memory_dedup_review.md",
            {"comparison_list": ""}
        )
    except Exception:
        # Fallback if config files are not in expected places during tests
        empty_prompt = "Compare candidate memories"
    base_tokens = estimate_tokens(empty_prompt)

    def format_group_text(grp, idx):
        c = grp["candidate"]
        text = f"=== 比較グループ {idx} ===\n"
        text += "【新しく抽出された候補（Candidate）】\n"
        text += f"- 候補ID: {c['memory_id']}\n"
        text += f"- 判定キー(memory_key): {c.get('memory_key') or ''}\n"
        text += f"- 本文: {c.get('content') or ''}\n\n"
        text += "【既存の承認済み記憶（Target）】\n"
        for t in grp["targets"]:
            text += f"- 既存記憶ID: {t['memory_id']}\n"
            text += f"  判定キー(memory_key): {t['memory_key']}\n"
            text += f"  本文: {t['content']}\n"
            text += f"  類似関係: {t['relation']} (類似度: {t['score'] or '1.0'})\n"
        text += "\n"
        return text

    for i, grp in enumerate(comparison_groups, 1):
        grp_text = format_group_text(grp, i)
        grp_tokens = estimate_tokens(grp_text)
        if base_tokens + current_tokens + grp_tokens > DEDUP_INPUT_BATCH_TOKEN_LIMIT:
            if current_batch:
                batches.append(current_batch)
                current_batch = [grp]
                current_tokens = grp_tokens
            else:
                batches.append([grp])
                current_batch = []
                current_tokens = 0
        else:
            current_batch.append(grp)
            current_tokens += grp_tokens

    if current_batch:
        batches.append(current_batch)

    # Process each batch
    for batch in batches:
        comp_text = ""
        for idx, grp in enumerate(batch, 1):
            comp_text += format_group_text(grp, idx)

        prompt_path = config.BASE_DIR / "config" / "prompts" / "memory_dedup_review.md"
        try:
            rendered_prompt = prompt.render_prompt(
                prompt_path,
                {"comparison_list": comp_text}
            )
        except Exception:
            rendered_prompt = f"Please review these and return JSON:\n{comp_text}"

        try:
            response = llm_client.generate_llm_response(
                provider=config.MEMORY_EXTRACTOR_PROVIDER,
                model=config.MEMORY_EXTRACTOR_MODEL,
                prompt=rendered_prompt,
                max_tokens=DEDUP_LLM_OUTPUT_TOKEN_LIMIT,
                temperature=0.2
            ).strip()

            if response.startswith("```"):
                lines = response.splitlines()
                if len(lines) >= 2:
                    if lines[0].startswith("```json") or lines[0].startswith("```"):
                        response = "\n".join(lines[1:-1]).strip()

            try:
                results = json.loads(response)
                if not isinstance(results, list):
                    results = [results]
            except json.JSONDecodeError as je:
                logger.error(f"Failed to parse LLM response as JSON. Error: {je}. Response: {response}")
                raise ValueError("response_invalid")

            results_by_cand = {}
            for r in results:
                if isinstance(r, dict) and "candidate_id" in r:
                    results_by_cand[r["candidate_id"]] = r

            for grp in batch:
                c = grp["candidate"]
                cid = c["memory_id"]
                res_item = results_by_cand.get(cid)

                valid = False
                if res_item:
                    decision = res_item.get("decision")
                    target_id = res_item.get("target_memory_id")
                    integrated_content = res_item.get("integrated_content")
                    reason = res_item.get("reason") or "LLM判定"

                    if decision in ("merge", "supersede", "new"):
                        if decision in ("merge", "supersede"):
                            if target_id in grp["target_ids"]:
                                if decision == "merge":
                                    if isinstance(integrated_content, str) and integrated_content.strip():
                                        valid = True
                                else:
                                    valid = True
                        else:
                            valid = True

                if valid:
                    score = 1.0
                    for t in grp["targets"]:
                        if t["memory_id"] == target_id:
                            score = t["score"] if t["score"] is not None else 1.0
                            break

                    assessment = {
                        "decision": decision,
                        "target_memory_id": target_id if decision in ("merge", "supersede") else None,
                        "similarity_score": score,
                        "reason": reason,
                    }
                    if decision == "merge":
                        assessment["integrated_content"] = integrated_content

                    c["dedup_assessment"] = assessment
                else:
                    logger.warning(f"Invalid or missing LLM response item for candidate {cid}: {res_item}")
                    scores = [t["score"] for t in grp["targets"] if t["score"] is not None]
                    best_score = max(scores) if scores else 1.0
                    c["dedup_assessment"] = {
                        "decision": "failed",
                        "similarity_score": best_score,
                        "reason": "LLM response was invalid or failed validation checks",
                        "failure_kind": "response_invalid"
                    }

        except Exception as exc:
            logger.exception(f"LLM request or parsing failed for batch: {exc}")
            failure_kind = "response_invalid" if str(exc) == "response_invalid" else "request_failed"
            for grp in batch:
                c = grp["candidate"]
                scores = [t["score"] for t in grp["targets"] if t["score"] is not None]
                best_score = max(scores) if scores else 1.0
                c["dedup_assessment"] = {
                    "decision": "failed",
                    "similarity_score": best_score,
                    "reason": f"Failed to get or parse LLM response: {str(exc)}",
                    "failure_kind": failure_kind
                }


def extract_memories(week_date_str: Optional[str] = None) -> list[dict]:
    """Extract memory candidates from a completed or explicitly selected week."""
    approved_modified = False
    week_start, week_end = _week_bounds(week_date_str)
    week_start_str = week_start.strftime("%Y-%m-%d")
    week_end_str = week_end.strftime("%Y-%m-%d")
    logger.info("Extracting memories for week: %s to %s", week_start_str, week_end_str)

    daily_notes, structured_records = _load_weekly_memory_sources(week_start, week_end)
    if not daily_notes:
        logger.info("No daily notes found for week %s to %s; skipping memory extraction", week_start_str, week_end_str)
        return []

    # Build and render prompt
    rendered_prompt = prompt.render_prompt(
        config.MEMORY_EXTRACTOR_PROMPT_PATH,
        {
            "week_start": week_start_str,
            "week_end": week_end_str,
            "daily_notes": json.dumps(daily_notes, ensure_ascii=False, indent=2),
            "structured_records": json.dumps(structured_records, ensure_ascii=False, indent=2) if structured_records else "(なし)",
            "topic_candidates": json.dumps(TOPIC_ENUM, ensure_ascii=False)
        }
    )

    # Call LLM
    response = llm_client.generate_llm_response(
        provider=config.MEMORY_EXTRACTOR_PROVIDER,
        model=config.MEMORY_EXTRACTOR_MODEL,
        prompt=rendered_prompt,
        max_tokens=32000,
        temperature=0.2
    ).strip()

    # Clean code blocks
    if response.startswith("```"):
        lines = response.splitlines()
        if len(lines) >= 2:
            if lines[0].startswith("```json") or lines[0].startswith("```"):
                response = "\n".join(lines[1:-1]).strip()

    try:
        extracted = json.loads(response)
        if not isinstance(extracted, list):
            extracted = [extracted]
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM memory extraction response as JSON. Response: {response}. Error: {e}")
        return []

    existing_memories = load_all_memories()
    embedder = get_embedder()

    timestamp_now = get_current_timestamp()

    class CachedEmbedder:
        def __init__(self, actual_embedder):
            self.actual_embedder = actual_embedder
            self.cache = {}

        def embed_query(self, text):
            if text not in self.cache:
                self.cache[text] = self.actual_embedder.embed_query(text)
            return self.cache[text]

    cached_embedder = CachedEmbedder(embedder) if embedder is not None else None

    # Load active approved memories
    approved_mems = [m for m in existing_memories if m.get("status") == "approved"]

    final_candidates_to_save = []
    candidates_to_assess = []
    exact_content_rejections = []

    for item in extracted:
        if not isinstance(item, dict):
            logger.warning(f"Skipping non-dict extracted candidate item: {item}")
            continue

        # Generate new ID
        memory_id = generate_memory_id(week_end_str)

        # Build complete schema structure
        cand = {
            "schema_version": 1,
            "memory_id": memory_id,
            "status": "candidate",
            "kind": item.get("kind", "preference"),
            "memory_key": item.get("memory_key", ""),
            "content": item.get("content", ""),
            "topics": normalize_topics(item.get("topics", [])),
            "tags": item.get("tags", []),
            "evidence": item.get("evidence", []),
            "valid_from": item.get("valid_from") or week_start_str,
            "valid_until": item.get("valid_until"),
            "review_due_at": item.get("review_due_at"),
            "stability": normalize_stability(item.get("stability"), default="tentative"),
            "sensitivity": item.get("sensitivity", "personal"),
            "extraction_confidence": float(item.get("extraction_confidence", 0.90)),
            "supersedes": item.get("supersedes"),
            "contradicts": item.get("contradicts") or [],
            "provenance": {
                "extraction_method": "weekly_llm",
                "prompt_version": "mem-extract-week-v2",
                "model": f"{config.MEMORY_EXTRACTOR_PROVIDER}:{config.MEMORY_EXTRACTOR_MODEL}",
                "week_start": week_start_str,
                "week_end": week_end_str,
            },
            "created_at": timestamp_now,
            "updated_at": timestamp_now,
            "reviewed_by": None,
            "reviewed_at": None,
            "dedup_suggestions": None,
            "dedup_assessment": None
        }

        cand_norm = normalize_content(cand.get("content", ""))

        # 1. Check for complete normalized content match across ANY approved memory
        exact_content_matches = [m for m in approved_mems if normalize_content(m.get("content", "")) == cand_norm]

        if exact_content_matches:
            # Duplicate: Auto-reject candidate, keep existing unchanged
            cand["status"] = "rejected"
            cand["reviewed_by"] = "system"
            cand["reviewed_at"] = timestamp_now
            cand["updated_at"] = timestamp_now

            matched_ids = [m["memory_id"] for m in exact_content_matches]
            exact_content_rejections.append((cand, matched_ids))
            final_candidates_to_save.append(cand)
            continue

        # 2. Get standard dedup suggestions using CachedEmbedder
        suggestions = run_deduplication(cand, existing_memories, embedder=cached_embedder)
        if suggestions:
            cand["dedup_suggestions"] = suggestions
            candidates_to_assess.append(cand)
        else:
            final_candidates_to_save.append(cand)

    # Perform LLM assessment on matching candidates
    perform_dedup_assessment_llm(candidates_to_assess, existing_memories)
    final_candidates_to_save.extend(candidates_to_assess)

    # Open DB connection and persist all candidates
    conn = get_db_connection()
    try:
        with conn:
            for cand in final_candidates_to_save:
                db_row = serialize_memory(cand)
                columns = ", ".join(MEMORY_COLUMNS)
                placeholders = ", ".join("?" for _ in MEMORY_COLUMNS)
                conn.execute(
                    f"INSERT INTO memories ({columns}) VALUES ({placeholders})",
                    tuple(db_row.get(col) for col in MEMORY_COLUMNS),
                )

                if cand["status"] == "rejected":
                    # Find matched IDs for exact content rejection
                    matched_ids = []
                    for c_ref, m_ids in exact_content_rejections:
                        if c_ref["memory_id"] == cand["memory_id"]:
                            matched_ids = m_ids
                            break
                    log_memory_event(
                        event_type="rejected",
                        memory_id=cand["memory_id"],
                        previous_status=None,
                        new_status="rejected",
                        changes={"relation": "duplicate", "target_memory_ids": matched_ids},
                        reason="内容が既存の記憶と完全に一致するため自動却下",
                        conn=conn,
                        actor="system"
                    )
                else:
                    log_memory_event(
                        event_type="created",
                        memory_id=cand["memory_id"],
                        previous_status=None,
                        new_status="candidate",
                        conn=conn
                    )
    finally:
        conn.close()

    return final_candidates_to_save


def review_memory(memory_id: str, action: str, new_content: Optional[str] = None) -> bool:
    """
    Review candidate memory with specified action (approve, reject, edit).
    """
    logger.info(f"Reviewing memory {memory_id} with action {action}")

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM memories WHERE memory_id = ?", (memory_id,))
        row = cursor.fetchone()
        if row is None:
            logger.error(f"Memory with ID {memory_id} not found")
            return False

        if action == "edit" and not new_content:
            logger.error("Content is required for edit action")
            return False

        target = deserialize_memory(dict(row))
        prev_status = target.get("status")
        if prev_status == "superseded":
            logger.error(f"Cannot review a superseded memory: {memory_id}")
            return False
        timestamp_now = get_current_timestamp()

        if action == "approve":
            target["status"] = "approved"
            target["reviewed_by"] = "user"
            target["reviewed_at"] = timestamp_now
            target["updated_at"] = timestamp_now

            db_row = serialize_memory(target)
            set_clause = ", ".join(f"{col} = ?" for col in MEMORY_COLUMNS if col != "memory_id")
            values = [db_row.get(col) for col in MEMORY_COLUMNS if col != "memory_id"] + [memory_id]
            conn.execute(f"UPDATE memories SET {set_clause} WHERE memory_id = ?", values)

            log_memory_event(
                event_type="approved",
                memory_id=memory_id,
                previous_status=prev_status,
                new_status="approved",
                conn=conn
            )
            conn.commit()
        elif action == "reject":
            target["status"] = "rejected"
            target["reviewed_by"] = "user"
            target["reviewed_at"] = timestamp_now
            target["updated_at"] = timestamp_now

            db_row = serialize_memory(target)
            set_clause = ", ".join(f"{col} = ?" for col in MEMORY_COLUMNS if col != "memory_id")
            values = [db_row.get(col) for col in MEMORY_COLUMNS if col != "memory_id"] + [memory_id]
            conn.execute(f"UPDATE memories SET {set_clause} WHERE memory_id = ?", values)

            log_memory_event(
                event_type="rejected",
                memory_id=memory_id,
                previous_status=prev_status,
                new_status="rejected",
                conn=conn
            )
            conn.commit()
        elif action == "edit":
            before_content = target.get("content", "")
            target["content"] = new_content
            target["status"] = "approved"
            target["reviewed_by"] = "user"
            target["reviewed_at"] = timestamp_now
            target["updated_at"] = timestamp_now

            changes = {
                "content": {
                    "before": before_content,
                    "after": new_content
                }
            }

            db_row = serialize_memory(target)
            set_clause = ", ".join(f"{col} = ?" for col in db_row if col != "memory_id")
            values = [db_row[col] for col in db_row if col != "memory_id"] + [memory_id]
            conn.execute(f"UPDATE memories SET {set_clause} WHERE memory_id = ?", values)

            log_memory_event(
                event_type="edited",
                memory_id=memory_id,
                previous_status=prev_status,
                new_status="approved",
                changes=changes,
                conn=conn
            )
            conn.commit()
        else:
            logger.error(f"Unknown action: {action}")
            return False
    finally:
        conn.close()

    # Re-project approved memories markdown
    project_approved_memories()
    return True


def estimate_tokens(text: str) -> int:
    try:
        import tiktoken
        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))
    except Exception:
        # Fallback approximation for mixed Japanese and English text
        return int(len(text) * 1.2)


def get_currently_valid_approved_memories() -> tuple[list[dict], list[dict]]:
    """
    Check and update expiration status for all approved memories.
    Returns:
        (active_approved, excluded) where:
            active_approved: list of currently valid, approved memory dicts
            excluded: list of dicts with {"memory_id": str, "reason": str} for items excluded due to being expired or not yet valid
    """
    logger.info("Checking and loading currently valid approved memories")
    memories = load_all_memories()

    now_dt = datetime.now(timezone.utc)
    active_approved = []
    excluded = []
    has_changes = False

    conn = get_db_connection()
    try:
        with conn:
            for m in memories:
                m_id = m.get("memory_id")
                status = m.get("status")

                if status != "approved":
                    continue

                # Check expiration logic
                is_expired = False

                valid_until = m.get("valid_until")
                if valid_until:
                    try:
                        # Assuming valid_until is YYYY-MM-DD
                        val_dt = datetime.strptime(valid_until, "%Y-%m-%d")
                        if now_dt.date() > val_dt.date():
                            is_expired = True
                    except Exception:
                        pass

                review_due_at = m.get("review_due_at")
                if review_due_at:
                    try:
                        # Try parsing as ISO datetime or YYYY-MM-DD
                        if "T" in review_due_at:
                            rd_dt = datetime.fromisoformat(review_due_at)
                            if rd_dt.tzinfo is None:
                                rd_dt = rd_dt.replace(tzinfo=timezone.utc)
                            if now_dt > rd_dt:
                                is_expired = True
                        else:
                            rd_dt = datetime.strptime(review_due_at, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                            if now_dt.date() > rd_dt.date():
                                is_expired = True
                    except Exception:
                        pass

                if is_expired:
                    m["status"] = "expired"
                    m["updated_at"] = get_current_timestamp()
                    has_changes = True

                    # Update target in DB
                    db_row = serialize_memory(m)
                    set_clause = ", ".join(f"{col} = ?" for col in MEMORY_COLUMNS if col != "memory_id")
                    values = [db_row.get(col) for col in MEMORY_COLUMNS if col != "memory_id"] + [m_id]
                    conn.execute(f"UPDATE memories SET {set_clause} WHERE memory_id = ?", values)

                    log_memory_event(
                        event_type="expired",
                        memory_id=m_id,
                        previous_status="approved",
                        new_status="expired",
                        reason="Automatic expiration during validity check",
                        conn=conn
                    )
                    excluded.append({"memory_id": m_id, "reason": "expired"})
                    continue

                # Check valid_from (not yet valid)
                valid_from = m.get("valid_from")
                if valid_from:
                    try:
                        vf_dt = datetime.strptime(valid_from, "%Y-%m-%d")
                        if now_dt.date() < vf_dt.date():
                            excluded.append({"memory_id": m_id, "reason": "not_yet_valid"})
                            continue
                    except Exception:
                        pass

                active_approved.append(m)
    finally:
        conn.close()

    if has_changes:
        try:
            project_approved_memories()
        except Exception as e:
            logger.error(f"Failed to update memories database on validity check: {e}")

    return active_approved, excluded


def compile_context(for_purpose: str = "make-target") -> dict:
    """
    Compile approved memories to be injected as ContextPack.
    - Resolves automatic expiration of valid_until / review_due_at.
    - Excludes non-active items.
    - Prioritizes based on confidence, stability, and creation timestamp.
    - Selects items within the token budget.
    """
    logger.info(f"Compiling context for purpose: {for_purpose}")
    excluded = []
    try:
        active_approved, initial_excluded = get_currently_valid_approved_memories()
        excluded.extend(initial_excluded)
    except Exception as e:
        logger.error(f"Failed to load memories for compilation fallback: {e}")
        return {
            "context": "",
            "used_memory_ids": [],
            "estimated_tokens": 0,
            "excluded": []
        }

    # Prioritization sorting
    # 1. extraction_confidence (descending)
    # 2. stability (stable=1, other=0) (descending)
    # 3. created_at (descending)
    def priority_key(item):
        raw_conf = item.get("extraction_confidence")
        confidence = float(raw_conf) if raw_conf is not None else 0.0
        stability_score = 1 if item.get("stability") == "stable" else 0
        created_at_str = item.get("created_at") or ""
        return (confidence, stability_score, created_at_str)

    sorted_active = sorted(active_approved, key=priority_key, reverse=True)

    used_memory_ids = []
    budget = config.MEMORY_CONTEXT_MAX_TOKENS
    context_lines = []
    total_tokens = 0

    # Format long term memories section title
    section_title = "## 根拠付き参考情報（長期記憶）\n"
    total_tokens += estimate_tokens(section_title)

    for m in sorted_active:
        m_id = m.get("memory_id")
        kind = m.get("kind", "preference")
        key = m.get("memory_key", "")
        content = m.get("content", "")

        # Format item
        item_text = f"- [{kind}] (Key: {key}): {content}\n"
        tokens = estimate_tokens(item_text)

        if total_tokens + tokens > budget:
            excluded.append({"memory_id": m_id, "reason": "token_limit_exceeded"})
            continue

        context_lines.append(item_text)
        total_tokens += tokens
        used_memory_ids.append(m_id)

    context_str = ""
    if context_lines:
        context_str = section_title + "".join(context_lines)

    return {
        "context": context_str,
        "used_memory_ids": used_memory_ids,
        "estimated_tokens": total_tokens,
        "excluded": excluded
    }


# Fields that the Web UI can edit. Other fields (kind, memory_key, evidence,
# dedup_suggestions, contradicts, supersedes, provenance, sensitivity,
# extraction_confidence) are intentionally not editable from the review UI to
# keep dedup fingerprints stable.
EDITABLE_FIELDS = (
    "content",
    "topics",
    "tags",
    "valid_from",
    "valid_until",
    "review_due_at",
    "stability",
)

def _validate_date_str(value, field_name: str):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string in YYYY-MM-DD format")
    datetime.strptime(value, "%Y-%m-%d")
    return value


def _validate_edit_payload(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dict")

    unknown = set(payload.keys()) - set(EDITABLE_FIELDS)
    if unknown:
        raise ValueError(
            f"editable fields are {sorted(EDITABLE_FIELDS)}; got unknown: {sorted(unknown)}"
        )

    if "content" in payload and (not isinstance(payload["content"], str) or not payload["content"].strip()):
        raise ValueError("content must be a non-empty string")

    if "topics" in payload:
        if not isinstance(payload["topics"], list):
            raise ValueError("topics must be a list of strings")
        payload["topics"] = normalize_topics(payload["topics"])

    if "tags" in payload:
        if not isinstance(payload["tags"], list) or not all(isinstance(t, str) for t in payload["tags"]):
            raise ValueError("tags must be a list of strings")

    if "stability" in payload:
        if payload["stability"] not in ALLOWED_STABILITY:
            raise ValueError(
                f"stability must be one of {sorted(ALLOWED_STABILITY)}; got {payload['stability']!r}"
            )

    for date_field in ("valid_from", "valid_until", "review_due_at"):
        if date_field in payload:
            _validate_date_str(payload[date_field], date_field)

    if "valid_from" in payload and "valid_until" in payload:
        vf = payload.get("valid_from")
        vu = payload.get("valid_until")
        if vf and vu and vf > vu:
            raise ValueError("valid_from must be on or before valid_until")

    return payload


def update_memory_fields(memory_id: str, fields: dict) -> dict:
    """
    Web/API specific: edit EDITABLE_FIELDS and auto-approve.
    Returns {"found": bool, "updated": bool, "changes": dict, "memory": dict|None}.
    Raises ValueError on validation errors.
    """
    logger.info(f"Updating memory {memory_id} with fields {list(fields.keys())}")
    validated = _validate_edit_payload(dict(fields))

    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM memories WHERE memory_id = ?", (memory_id,))
            row = cursor.fetchone()
            if row is None:
                return {"found": False, "updated": False, "changes": {}, "memory": None}

            target = deserialize_memory(dict(row))
            prev_status = target.get("status")
            if prev_status == "superseded":
                raise ValueError("Cannot edit a superseded memory")
            timestamp_now = get_current_timestamp()

            changes = {}
            for k, v in validated.items():
                before = target.get(k)
                if before != v:
                    changes[k] = {"before": before, "after": v}
                    target[k] = v

            if not changes:
                return {"found": True, "updated": False, "changes": {}, "memory": target}

            target["status"] = "approved"
            target["reviewed_by"] = "user"
            target["reviewed_at"] = timestamp_now
            target["updated_at"] = timestamp_now

            db_row = serialize_memory(target)
            set_clause = ", ".join(f"{col} = ?" for col in db_row if col != "memory_id")
            values = [db_row[col] for col in db_row if col != "memory_id"] + [memory_id]
            conn.execute(f"UPDATE memories SET {set_clause} WHERE memory_id = ?", values)

            log_memory_event(
                event_type="edited",
                memory_id=memory_id,
                previous_status=prev_status,
                new_status="approved",
                changes=changes,
                conn=conn,
            )
    finally:
        conn.close()

    project_approved_memories()
    return {"found": True, "updated": True, "changes": changes, "memory": target}


def batch_review_memories(memory_ids: list, action: str) -> dict:
    """
    Web/API specific: approve or reject multiple memories in one go.
    Returns {"updated": [ids...], "not_found": [ids...], "events": int}.
    action must be 'approve' or 'reject'.
    """
    if action not in ("approve", "reject"):
        raise ValueError("action must be 'approve' or 'reject'")
    if not isinstance(memory_ids, list) or not memory_ids:
        raise ValueError("memory_ids must be a non-empty list")
    if not all(isinstance(mid, str) for mid in memory_ids):
        raise ValueError("memory_ids must be strings")

    seen = set()
    deduped_ids = []
    for mid in memory_ids:
        if mid not in seen:
            seen.add(mid)
            deduped_ids.append(mid)
    memory_ids = deduped_ids

    new_status = "approved" if action == "approve" else "rejected"
    event_type = {"approve": "approved", "reject": "rejected"}[action]
    updated = []
    not_found = []
    event_count = 0

    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            timestamp_now = get_current_timestamp()

            skipped = []
            for memory_id in memory_ids:
                cursor.execute("SELECT * FROM memories WHERE memory_id = ?", (memory_id,))
                row = cursor.fetchone()
                if row is None:
                    not_found.append(memory_id)
                    continue
                target = deserialize_memory(dict(row))
                prev_status = target.get("status")
                if prev_status == "superseded":
                    skipped.append(memory_id)
                    continue
                target["status"] = new_status
                target["reviewed_by"] = "user"
                target["reviewed_at"] = timestamp_now
                target["updated_at"] = timestamp_now

                db_row = serialize_memory(target)
                set_clause = ", ".join(f"{col} = ?" for col in MEMORY_COLUMNS if col != "memory_id")
                values = [db_row.get(col) for col in MEMORY_COLUMNS if col != "memory_id"] + [memory_id]
                conn.execute(f"UPDATE memories SET {set_clause} WHERE memory_id = ?", values)

                log_memory_event(
                    event_type=event_type,
                    memory_id=memory_id,
                    previous_status=prev_status,
                    new_status=new_status,
                    conn=conn,
                )
                event_count += 1
                updated.append(memory_id)
    finally:
        conn.close()

    if updated:
        project_approved_memories()

    return {"updated": updated, "not_found": not_found, "skipped": skipped, "events": event_count}


def get_memory_events(memory_id: str) -> list:
    """Return event history for a memory_id in chronological order."""
    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM memory_events WHERE memory_id = ? ORDER BY occurred_at ASC",
                (memory_id,),
            )
            rows = cursor.fetchall()
            return [deserialize_event(dict(row)) for row in rows]
    finally:
        conn.close()

def resolve_memory(
    candidate_id: str,
    action: str,
    target_memory_id: str,
    integrated_content: Optional[str] = None,
    switch_date: Optional[str] = None
) -> tuple[dict, Optional[dict]]:
    """
    Resolve a candidate memory by keeping both, replacing, merging, or superseding the existing one.
    Returns (candidate, target).
    Raises ValueError on invalid state/inputs.
    """
    allowed_actions = ("keep_both", "replace_existing", "merge_existing", "supersede_existing")
    if action not in allowed_actions:
        raise ValueError(f"action must be one of {allowed_actions}")

    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()

            # Fetch candidate
            cursor.execute("SELECT * FROM memories WHERE memory_id = ?", (candidate_id,))
            cand_row = cursor.fetchone()
            if cand_row is None:
                raise ValueError(f"Candidate memory not found: {candidate_id}")
            cand = deserialize_memory(dict(cand_row))

            if cand.get("status") != "candidate":
                raise ValueError(f"Memory {candidate_id} is not in candidate status (current: {cand.get('status')})")

            # Fetch target
            cursor.execute("SELECT * FROM memories WHERE memory_id = ?", (target_memory_id,))
            target_row = cursor.fetchone()
            if target_row is None:
                raise ValueError(f"Target memory not found: {target_memory_id}")
            target = deserialize_memory(dict(target_row))

            if target.get("status") != "approved":
                raise ValueError(f"Target memory {target_memory_id} is not in approved status")

            # Validate target_memory_id matches dedup_assessment.target_memory_id
            assessment = cand.get("dedup_assessment")
            ass_target = assessment.get("target_memory_id") if (assessment and isinstance(assessment, dict)) else None

            if ass_target:
                if ass_target != target_memory_id:
                    raise ValueError(f"Target {target_memory_id} does not match LLM assessed target: {ass_target}")
            else:
                # Fallback to dedup_suggestions for backward compatibility/old data
                suggestions = cand.get("dedup_suggestions") or []
                target_ids = [s.get("target_memory_id") for s in suggestions if s.get("target_memory_id")]
                if target_memory_id not in target_ids:
                    raise ValueError(f"Target {target_memory_id} is not in candidate's suggestions: {target_ids}")

            timestamp_now = get_current_timestamp()

            if action == "keep_both":
                cand["status"] = "approved"
                cand["reviewed_by"] = "user"
                cand["reviewed_at"] = timestamp_now
                cand["updated_at"] = timestamp_now

                db_row_cand = serialize_memory(cand)
                set_clause = ", ".join(f"{col} = ?" for col in MEMORY_COLUMNS if col != "memory_id")
                values = [db_row_cand.get(col) for col in MEMORY_COLUMNS if col != "memory_id"] + [candidate_id]
                conn.execute(f"UPDATE memories SET {set_clause} WHERE memory_id = ?", values)

                log_memory_event(
                    event_type="approved",
                    memory_id=candidate_id,
                    previous_status="candidate",
                    new_status="approved",
                    reason="手動操作: 両方保持を選択して承認",
                    conn=conn
                )

            elif action == "replace_existing":
                # Save target state before update
                before_target = dict(target)

                # Update target with candidate data
                target = update_target_with_candidate_data(target, cand, reviewed_by="user")

                # Save updated target
                db_row_target = serialize_memory(target)
                set_clause = ", ".join(f"{col} = ?" for col in MEMORY_COLUMNS if col != "memory_id")
                values = [db_row_target.get(col) for col in MEMORY_COLUMNS if col != "memory_id"] + [target_memory_id]
                conn.execute(f"UPDATE memories SET {set_clause} WHERE memory_id = ?", values)

                # Compute differences
                changes_diff = {}
                for field in MEMORY_COLUMNS:
                    if field in ["updated_at", "reviewed_at"]:
                        continue
                    before_val = before_target.get(field)
                    after_val = target.get(field)
                    if before_val != after_val:
                        changes_diff[field] = {"before": before_val, "after": after_val}

                # Log event for target
                log_memory_event(
                    event_type="edited",
                    memory_id=target_memory_id,
                    previous_status="approved",
                    new_status="approved",
                    changes=changes_diff,
                    reason=f"手動操作: 置換による更新（対象候補: {candidate_id}）",
                    conn=conn
                )

                # Reject candidate
                cand["status"] = "rejected"
                cand["reviewed_by"] = "user"
                cand["reviewed_at"] = timestamp_now
                cand["updated_at"] = timestamp_now

                db_row_cand = serialize_memory(cand)
                set_clause = ", ".join(f"{col} = ?" for col in MEMORY_COLUMNS if col != "memory_id")
                values = [db_row_cand.get(col) for col in MEMORY_COLUMNS if col != "memory_id"] + [candidate_id]
                conn.execute(f"UPDATE memories SET {set_clause} WHERE memory_id = ?", values)

                # Log event for candidate
                log_memory_event(
                    event_type="rejected",
                    memory_id=candidate_id,
                    previous_status="candidate",
                    new_status="rejected",
                    changes={"relation": "supersedes", "target_memory_id": target_memory_id},
                    reason="手動操作: 既存記憶の置換を選択して却下",
                    conn=conn
                )

            elif action == "merge_existing":
                if not integrated_content or not isinstance(integrated_content, str) or not integrated_content.strip():
                    raise ValueError("integrated_content is required for merge_existing action")

                # Save target state before update
                before_target = dict(target)

                # Update target with candidate/integrated data
                target["content"] = integrated_content
                for field in ["kind", "valid_until", "review_due_at", "stability", "sensitivity", "extraction_confidence", "contradicts"]:
                    target[field] = cand.get(field)
                target["stability"] = normalize_stability(cand.get("stability"), default="tentative")
                target["topics"] = merge_topics_and_tags(target.get("topics") or [], cand.get("topics") or [])
                target["tags"] = merge_topics_and_tags(target.get("tags") or [], cand.get("tags") or [])
                target["evidence"] = merge_evidence(target.get("evidence") or [], cand.get("evidence") or [])
                target["updated_at"] = timestamp_now
                target["reviewed_by"] = "user"
                target["reviewed_at"] = timestamp_now

                # Save updated target
                db_row_target = serialize_memory(target)
                set_clause = ", ".join(f"{col} = ?" for col in MEMORY_COLUMNS if col != "memory_id")
                values = [db_row_target.get(col) for col in MEMORY_COLUMNS if col != "memory_id"] + [target_memory_id]
                conn.execute(f"UPDATE memories SET {set_clause} WHERE memory_id = ?", values)

                # Compute differences
                changes_diff = {}
                for field in MEMORY_COLUMNS:
                    if field in ["updated_at", "reviewed_at"]:
                        continue
                    before_val = before_target.get(field)
                    after_val = target.get(field)
                    if before_val != after_val:
                        changes_diff[field] = {"before": before_val, "after": after_val}

                # Log event for target
                log_memory_event(
                    event_type="edited",
                    memory_id=target_memory_id,
                    previous_status="approved",
                    new_status="approved",
                    changes=changes_diff,
                    reason=f"手動操作: マージによる更新（対象候補: {candidate_id}）",
                    conn=conn
                )

                # Reject candidate
                cand["status"] = "rejected"
                cand["reviewed_by"] = "user"
                cand["reviewed_at"] = timestamp_now
                cand["updated_at"] = timestamp_now

                db_row_cand = serialize_memory(cand)
                set_clause = ", ".join(f"{col} = ?" for col in MEMORY_COLUMNS if col != "memory_id")
                values = [db_row_cand.get(col) for col in MEMORY_COLUMNS if col != "memory_id"] + [candidate_id]
                conn.execute(f"UPDATE memories SET {set_clause} WHERE memory_id = ?", values)

                # Log event for candidate
                log_memory_event(
                    event_type="rejected",
                    memory_id=candidate_id,
                    previous_status="candidate",
                    new_status="rejected",
                    changes={"relation": "duplicate", "target_memory_id": target_memory_id},
                    reason="手動操作: 既存記憶へのマージを選択して却下",
                    conn=conn
                )

            elif action == "supersede_existing":
                if not switch_date or not isinstance(switch_date, str):
                    raise ValueError("switch_date is required for supersede_existing action")
                try:
                    switch_dt = datetime.strptime(switch_date, "%Y-%m-%d")
                except ValueError:
                    raise ValueError("switch_date must be in YYYY-MM-DD format")

                # Validate switch_date > target valid_from
                old_valid_from = target.get("valid_from")
                if old_valid_from:
                    old_vf_dt = None
                    try:
                        old_vf_dt = datetime.strptime(old_valid_from, "%Y-%m-%d")
                    except ValueError:
                        pass
                    if old_vf_dt and switch_dt <= old_vf_dt:
                        raise ValueError(f"switch_date ({switch_date}) must be strictly after existing valid_from ({old_valid_from})")

                predecessor_until_dt = switch_dt - timedelta(days=1)
                predecessor_until_str = predecessor_until_dt.strftime("%Y-%m-%d")

                # Save target and candidate states before update
                before_target = dict(target)
                before_cand = dict(cand)

                # Update old memory
                target["status"] = "superseded"
                target["valid_until"] = predecessor_until_str
                target["updated_at"] = timestamp_now

                db_row_target = serialize_memory(target)
                set_clause = ", ".join(f"{col} = ?" for col in MEMORY_COLUMNS if col != "memory_id")
                values = [db_row_target.get(col) for col in MEMORY_COLUMNS if col != "memory_id"] + [target_memory_id]
                conn.execute(f"UPDATE memories SET {set_clause} WHERE memory_id = ?", values)

                # Log event for target
                log_memory_event(
                    event_type="superseded",
                    memory_id=target_memory_id,
                    previous_status="approved",
                    new_status="superseded",
                    changes={
                        "valid_until": {"before": before_target.get("valid_until"), "after": predecessor_until_str},
                        "superseded_by": candidate_id
                    },
                    reason=f"手動操作: 置換による終了（後継候補: {candidate_id}）",
                    conn=conn
                )

                # Update new memory
                cand["status"] = "approved"
                cand["valid_from"] = switch_date
                cand["supersedes"] = target_memory_id
                cand["memory_key"] = target.get("memory_key")
                cand["reviewed_by"] = "user"
                cand["reviewed_at"] = timestamp_now
                cand["updated_at"] = timestamp_now

                db_row_cand = serialize_memory(cand)
                set_clause = ", ".join(f"{col} = ?" for col in MEMORY_COLUMNS if col != "memory_id")
                values = [db_row_cand.get(col) for col in MEMORY_COLUMNS if col != "memory_id"] + [candidate_id]
                conn.execute(f"UPDATE memories SET {set_clause} WHERE memory_id = ?", values)

                # Compute differences for candidate approved event
                cand_changes = {
                    "status": {"before": "candidate", "after": "approved"},
                    "valid_from": {"before": before_cand.get("valid_from"), "after": switch_date},
                    "supersedes": {"before": before_cand.get("supersedes"), "after": target_memory_id}
                }
                if before_cand.get("memory_key") != target.get("memory_key"):
                    cand_changes["memory_key"] = {"before": before_cand.get("memory_key"), "after": target.get("memory_key")}

                log_memory_event(
                    event_type="approved",
                    memory_id=candidate_id,
                    previous_status="candidate",
                    new_status="approved",
                    changes=cand_changes,
                    reason=f"手動操作: 既存記憶 {target_memory_id} の後継として承認",
                    conn=conn
                )
    finally:
        conn.close()

    project_approved_memories()

    return cand, target


def _prune_dedup_suggestions(cursor, memory_id: str) -> None:
    cursor.execute("SELECT memory_id, dedup_suggestions FROM memories WHERE dedup_suggestions IS NOT NULL")
    rows = cursor.fetchall()
    for row in rows:
        mid = row["memory_id"]
        raw = row["dedup_suggestions"]
        if raw is None:
            continue
        try:
            suggestions = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(suggestions, list):
            continue
        filtered = [s for s in suggestions if s.get("target_memory_id") != memory_id]
        if len(filtered) != len(suggestions):
            new_val = json.dumps(filtered, ensure_ascii=False) if filtered else None
            cursor.execute("UPDATE memories SET dedup_suggestions = ? WHERE memory_id = ?", (new_val, mid))


def delete_memory(memory_id: str) -> dict:
    conn = get_db_connection()
    was_approved = False
    events_deleted = 0
    target = None
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM memories WHERE memory_id = ?", (memory_id,))
            row = cursor.fetchone()
            if row is None:
                return {"found": False, "deleted": False, "events_deleted": 0, "memory": None}

            target = deserialize_memory(dict(row))
            was_approved = target.get("status") == "approved"

            cursor.execute("DELETE FROM memory_events WHERE memory_id = ?", (memory_id,))
            events_deleted = cursor.rowcount

            _prune_dedup_suggestions(cursor, memory_id)
            cursor.execute("DELETE FROM memories WHERE memory_id = ?", (memory_id,))
    finally:
        conn.close()

    if was_approved:
        project_approved_memories()

    return {"found": True, "deleted": True, "events_deleted": events_deleted, "memory": target}


def batch_delete_memories(memory_ids: list[str]) -> dict:
    if not memory_ids:
        return {"deleted": [], "not_found": [], "events_deleted": 0}

    memory_ids = list(dict.fromkeys(memory_ids))
    conn = get_db_connection()
    deleted = []
    not_found = []
    total_events = 0
    had_approved = False

    try:
        with conn:
            cursor = conn.cursor()
            for mid in memory_ids:
                cursor.execute("SELECT * FROM memories WHERE memory_id = ?", (mid,))
                row = cursor.fetchone()
                if row is None:
                    not_found.append(mid)
                    continue

                target = deserialize_memory(dict(row))
                if target.get("status") == "approved":
                    had_approved = True

                cursor.execute("DELETE FROM memory_events WHERE memory_id = ?", (mid,))
                total_events += cursor.rowcount
                cursor.execute("DELETE FROM memories WHERE memory_id = ?", (mid,))
                deleted.append(mid)

            for mid in deleted:
                _prune_dedup_suggestions(cursor, mid)
    finally:
        conn.close()

    if had_approved:
        project_approved_memories()

    return {"deleted": deleted, "not_found": not_found, "events_deleted": total_events}


EXPECTED_FILES = {
    "AI_README.md": "AI全体プロフィールと横断的指針 (AI Profile & Guidelines)",
    "values.md": "明示された価値観・優先順位 (Values)",
    "response_style.md": "応答・対話スタイルの好み (Response Style)",
    "decision_policy.md": "判断方針・優先順位 (Decision Policy)",
    "risk_tolerance.md": "リスク許容度・慎重さの方針 (Risk Tolerance)",
    "memory_rules.md": "明示された記憶管理ルール (Memory Rules)",
    "current_projects.md": "現在進行中のプロジェクト・コミットメント (Current Projects)"
}


def render_copilot_profile() -> list[str]:
    """
    Summarize approved and valid memories and render the copilot profile markdown files.
    Returns:
        List of updated relative file paths.
    """
    logger.info("Starting copilot profile rendering")

    # Get active/valid approved memories
    active_approved, _ = get_currently_valid_approved_memories()

    # Build file mapping and absolute paths
    copilot_dir = Path(config.VAULT_PATH) / "copilot"
    core_dir = copilot_dir / "core"

    copilot_dir.mkdir(parents=True, exist_ok=True)
    core_dir.mkdir(parents=True, exist_ok=True)

    file_paths = {}
    for filename in EXPECTED_FILES:
        if filename == "AI_README.md":
            file_paths[filename] = copilot_dir / filename
        else:
            file_paths[filename] = core_dir / filename

    timestamp = get_current_timestamp()

    # 7 expected keys
    expected_keys = set(EXPECTED_FILES.keys())

    contents = {}
    if not active_approved:
        logger.info("No active approved memories found. Generating fallback notice for all files.")
        for filename in expected_keys:
            contents[filename] = "現時点で承認済みメモリなし"
    else:
        # Prepare filtered memories for LLM input
        filtered_memories = []
        for m in active_approved:
            filtered_m = {
                "kind": m.get("kind"),
                "memory_key": m.get("memory_key"),
                "content": m.get("content"),
                "topics": m.get("topics"),
                "tags": m.get("tags"),
                "valid_from": m.get("valid_from"),
                "valid_until": m.get("valid_until"),
                "stability": m.get("stability"),
                "sensitivity": m.get("sensitivity"),
                "extraction_confidence": m.get("extraction_confidence")
            }
            filtered_memories.append(filtered_m)

        json_memories = json.dumps(filtered_memories, ensure_ascii=False, indent=2)

        # Render prompt
        rendered_prompt = prompt.render_prompt(
            config.MEMORY_RENDERER_PROMPT_PATH,
            {"memories": json_memories}
        )

        # Call LLM
        response = llm_client.generate_llm_response(
            provider=config.MEMORY_RENDERER_PROVIDER,
            model=config.MEMORY_RENDERER_MODEL,
            prompt=rendered_prompt,
            max_tokens=32000,
            temperature=0.2
        ).strip()

        # Clean response
        if response.startswith("```"):
            lines = response.splitlines()
            if len(lines) >= 2:
                if lines[0].startswith("```json") or lines[0].startswith("```"):
                    response = "\n".join(lines[1:-1]).strip()

        try:
            data = json.loads(response)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}. Response was: {response}")
            raise ValueError(f"LLM response is not a valid JSON string: {e}")

        if not isinstance(data, dict):
            logger.error(f"LLM response is not a JSON object: {data}")
            raise ValueError("LLM output is not a JSON object/dictionary")

        # Validation checks
        actual_keys = set(data.keys())
        if actual_keys != expected_keys:
            logger.error(f"JSON key mismatch. Expected keys: {expected_keys}. Got: {actual_keys}")
            raise ValueError(f"JSON key mismatch. Expected exactly: {expected_keys}")

        for key, val in data.items():
            if not isinstance(val, str) or not val.strip():
                logger.error(f"Key {key} has an invalid or empty value: {val!r}")
                raise ValueError(f"Key '{key}' must have a non-empty string value")
            contents[key] = val.strip()

    # Write files if validation succeeds
    updated_paths = []
    for filename, body in contents.items():
        title = EXPECTED_FILES[filename]
        dest_path = file_paths[filename]

        # Generate full markdown
        markdown_content = f"""---
type: copilot-profile
generated_at: {timestamp}
---

# {title}

> [!NOTE]
> このファイルは承認済み長期記憶から自動生成されました。手書きでの変更は保持されません。

{body}
"""
        with open(dest_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)

        # relative to VAULT_PATH
        relative_p = _vault_relative_path(dest_path)
        updated_paths.append(relative_p)

    logger.info("Copilot profile rendering completed successfully.")
    return sorted(updated_paths)
