import json
import logging
import re
import unicodedata
import uuid
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from obsidian_ai_hub.utils import config, extracter, reader, llm_client, prompt
from obsidian_ai_hub.utils.topics import TOPIC_ENUM, normalize_topics

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
    "reviewed_at", "dedup_suggestions",
]

EVENT_COLUMNS = [
    "schema_version", "event_id", "occurred_at", "actor", "event_type",
    "memory_id", "previous_status", "new_status", "changes", "reason",
]


def get_db_connection() -> sqlite3.Connection:
    db_path = Path(config.MEMORY_SQLITE_PATH)
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
                dedup_suggestions TEXT
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

        conn.execute("PRAGMA user_version = 1;")
        conn.commit()

    return conn


def serialize_memory(m: dict) -> dict:
    db_row = dict(m)
    for col in ["topics", "tags", "evidence", "contradicts", "provenance", "dedup_suggestions"]:
        if col in db_row:
            if db_row[col] is not None:
                db_row[col] = json.dumps(db_row[col], ensure_ascii=False)
            else:
                db_row[col] = None
    return db_row


def deserialize_memory(row: dict) -> dict:
    m = dict(row)
    for col in ["topics", "tags", "evidence", "contradicts", "provenance", "dedup_suggestions"]:
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
            for ev in m.get("evidence", []):
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
    for field in ["kind", "valid_from", "valid_until", "review_due_at", "stability", "sensitivity", "extraction_confidence", "contradicts", "provenance"]:
        target[field] = cand.get(field)
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
    year_str = target_dt.strftime("%Y")
    month_str = target_dt.strftime("%m")
    target_date_str = target_dt.strftime("%Y-%m-%d")
    monthly_jsonl_path = Path(config.ACTIVITY_PATH) / year_str / month_str / f"{year_str}-{month_str}.jsonl"
    if not monthly_jsonl_path.exists():
        return {}

    try:
        with open(monthly_jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if data.get("date") == target_date_str:
                    return data
    except OSError as exc:
        logger.warning("Failed to read structured daily record %s: %s", monthly_jsonl_path, exc)
    return {}


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

    new_candidates = []
    conn = get_db_connection()
    try:
        with conn:
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
                    "stability": item.get("stability", "stable"),
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
                    "reviewed_at": None
                }

                cand_norm = normalize_content(cand.get("content", ""))
                cand_key = cand.get("memory_key", "")

                # Fetch up-to-date active approved memories
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM memories WHERE status = 'approved'")
                approved_rows = [deserialize_memory(dict(row)) for row in cursor.fetchall()]

                # 1. Check for complete normalized content match across ANY approved memory
                exact_content_matches = [m for m in approved_rows if normalize_content(m.get("content", "")) == cand_norm]

                if exact_content_matches:
                    # Duplicate: Auto-reject candidate, keep existing unchanged
                    cand["status"] = "rejected"
                    cand["reviewed_by"] = "system"
                    cand["reviewed_at"] = timestamp_now
                    cand["updated_at"] = timestamp_now

                    matched_ids = [m["memory_id"] for m in exact_content_matches]

                    # Insert rejected candidate
                    db_row = serialize_memory(cand)
                    columns = ", ".join(MEMORY_COLUMNS)
                    placeholders = ", ".join("?" for _ in MEMORY_COLUMNS)
                    conn.execute(
                        f"INSERT INTO memories ({columns}) VALUES ({placeholders})",
                        tuple(db_row.get(col) for col in MEMORY_COLUMNS),
                    )

                    # Create rejection event
                    log_memory_event(
                        event_type="rejected",
                        memory_id=memory_id,
                        previous_status=None,
                        new_status="rejected",
                        changes={"relation": "duplicate", "target_memory_ids": matched_ids},
                        reason="内容が既存の記憶と完全に一致するため自動却下",
                        conn=conn,
                        actor="system"
                    )
                    new_candidates.append(cand)
                    existing_memories.append(cand)
                    continue

                # 2. Check for memory_key exact match with content difference
                key_match_approved = None
                if cand_key:
                    for m in approved_rows:
                        if m.get("memory_key") == cand_key:
                            key_match_approved = m
                            break

                if key_match_approved:
                    # Content is different (since exact content match checked above didn't trigger).
                    # Auto-update the existing approved memory, auto-reject candidate
                    target_id = key_match_approved["memory_id"]

                    # Store existing values for diff logging
                    before_target = dict(key_match_approved)

                    # Update target memory
                    updated_target = update_target_with_candidate_data(key_match_approved, cand, reviewed_by="system")

                    # Persist updated target
                    db_row_target = serialize_memory(updated_target)
                    set_clause = ", ".join(f"{col} = ?" for col in MEMORY_COLUMNS if col != "memory_id")
                    values = [db_row_target.get(col) for col in MEMORY_COLUMNS if col != "memory_id"] + [target_id]
                    conn.execute(f"UPDATE memories SET {set_clause} WHERE memory_id = ?", values)

                    # Compute changes diff
                    changes_diff = {}
                    for field in MEMORY_COLUMNS:
                        if field in ["updated_at", "reviewed_at"]:
                            continue
                        before_val = before_target.get(field)
                        after_val = updated_target.get(field)
                        if before_val != after_val:
                            changes_diff[field] = {"before": before_val, "after": after_val}

                    # Log event for existing memory update
                    log_memory_event(
                        event_type="edited",
                        memory_id=target_id,
                        previous_status="approved",
                        new_status="approved",
                        changes=changes_diff,
                        reason=f"同一memory_keyの自動統合による更新（対象候補: {memory_id}）",
                        conn=conn,
                        actor="system"
                    )

                    # Reject candidate
                    cand["status"] = "rejected"
                    cand["reviewed_by"] = "system"
                    cand["reviewed_at"] = timestamp_now
                    cand["updated_at"] = timestamp_now

                    db_row_cand = serialize_memory(cand)
                    columns = ", ".join(MEMORY_COLUMNS)
                    placeholders = ", ".join("?" for _ in MEMORY_COLUMNS)
                    conn.execute(
                        f"INSERT INTO memories ({columns}) VALUES ({placeholders})",
                        tuple(db_row_cand.get(col) for col in MEMORY_COLUMNS),
                    )

                    # Log event for candidate rejection
                    log_memory_event(
                        event_type="rejected",
                        memory_id=memory_id,
                        previous_status=None,
                        new_status="rejected",
                        changes={"relation": "supersedes", "target_memory_id": target_id},
                        reason="同一memory_keyの既存記憶があるため自動置換による却下",
                        conn=conn,
                        actor="system"
                    )

                    new_candidates.append(cand)
                    existing_memories.append(cand)
                    approved_modified = True
                    continue

                # 3. Vector similarity fallback
                suggestions = run_deduplication(cand, existing_memories, embedder=embedder)
                if suggestions:
                    cand["dedup_suggestions"] = suggestions

                # Insert memory
                db_row = serialize_memory(cand)
                columns = ", ".join(MEMORY_COLUMNS)
                placeholders = ", ".join("?" for _ in MEMORY_COLUMNS)
                conn.execute(
                    f"INSERT INTO memories ({columns}) VALUES ({placeholders})",
                    tuple(db_row.get(col) for col in MEMORY_COLUMNS),
                )

                # Insert creation event
                log_memory_event(
                    event_type="created",
                    memory_id=memory_id,
                    previous_status=None,
                    new_status="candidate",
                    conn=conn
                )

                new_candidates.append(cand)
                existing_memories.append(cand)
    finally:
        conn.close()

    if approved_modified:
        project_approved_memories()

    return new_candidates


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

ALLOWED_STABILITY = {"stable", "tentative", "explicitly_settled"}


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

            for memory_id in memory_ids:
                cursor.execute("SELECT * FROM memories WHERE memory_id = ?", (memory_id,))
                row = cursor.fetchone()
                if row is None:
                    not_found.append(memory_id)
                    continue
                target = deserialize_memory(dict(row))
                prev_status = target.get("status")
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

    return {"updated": updated, "not_found": not_found, "events": event_count}


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

def resolve_memory(candidate_id: str, action: str, target_memory_id: str) -> tuple[dict, Optional[dict]]:
    """
    Resolve a candidate memory by either keeping both or replacing the existing one.
    Returns (candidate, target).
    Raises ValueError on invalid state/inputs.
    """
    if action not in ("keep_both", "replace_existing"):
        raise ValueError("action must be 'keep_both' or 'replace_existing'")

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

            # Validate target is in candidate's suggestions
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
    finally:
        conn.close()

    project_approved_memories()

    return cand, target


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
