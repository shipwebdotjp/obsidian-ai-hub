from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from obsidian_ai_hub.utils import config


def _assert_test_db_is_not_production(db_path: Path) -> None:
    """Reject the configured production DB while pytest isolation is active."""
    if os.getenv("OBSIDIAN_AI_HUB_TESTING") != "1":
        return

    production_path = os.getenv("OBSIDIAN_AI_HUB_TEST_PRODUCTION_DB_PATH")
    if not production_path:
        raise RuntimeError(
            "OBSIDIAN_AI_HUB_TEST_PRODUCTION_DB_PATH is required in test mode"
        )
    if db_path.expanduser().resolve() == Path(production_path).expanduser().resolve():
        raise RuntimeError(
            "Refusing to open the production memory database while tests are running"
        )


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
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_person_aliases_person_id ON person_aliases(person_id);"
    )
    conn.execute("PRAGMA user_version = 7;")
    conn.commit()


def run_migration_v8(conn: sqlite3.Connection) -> None:
    """Run the migration schema upgrade for version 8 (summary_person_assignments table)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS summary_person_assignments (
            summary_id TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            person_id TEXT NOT NULL,
            PRIMARY KEY (summary_id, normalized_name),
            FOREIGN KEY(summary_id) REFERENCES summaries(summary_id) ON DELETE CASCADE,
            FOREIGN KEY(person_id) REFERENCES people(person_id) ON DELETE CASCADE
        );
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_spa_normalized_name ON summary_person_assignments(normalized_name);"
    )
    conn.execute("PRAGMA user_version = 8;")
    conn.commit()


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
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memories_memory_key ON memories(memory_key);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_events_memory_id_occurred_at ON memory_events(memory_id, occurred_at);"
        )

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
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_rt_status ON research_themes(status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_rt_normalized_key ON research_themes(normalized_key)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_rj_theme_id ON research_jobs(theme_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_rj_status ON research_jobs(status)"
        )
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
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_activity_logs_date_occurred ON activity_logs(activity_date, occurred_at);"
        )
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
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_summaries_period ON summaries(period_type, period_key);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_summaries_period_start ON summaries(period_start);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_summary_items_summary_id ON summary_items(summary_id);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_summary_items_kind ON summary_items(summary_id, kind);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_summary_topics_summary_id ON summary_topics(summary_id);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_summary_projects_summary_id ON summary_projects(summary_id);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_summary_people_summary_id ON summary_people(summary_id);"
        )
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
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_spc_summary_id ON summary_person_candidates(summary_id);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_pc_normalized_name ON person_candidates(normalized_name);"
        )

        conn.execute("PRAGMA user_version = 6;")
        conn.commit()

    if current_version <= 6:
        run_migration_v7(conn)

    if current_version <= 7:
        run_migration_v8(conn)

    return conn
