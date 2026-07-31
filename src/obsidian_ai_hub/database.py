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


def run_migration_v9(conn: sqlite3.Connection) -> None:
    """Run migration for version 9 (projects & candidates refactoring with numerical integer IDs)."""
    # 1. Drop old tables if they exist
    conn.execute("DROP TABLE IF EXISTS summary_projects;")
    conn.execute("DROP TABLE IF EXISTS projects;")

    # 2. Create rebuilt projects table with integer primary key
    conn.execute("""
        CREATE TABLE projects (
            project_id INTEGER PRIMARY KEY,
            normalized_name TEXT UNIQUE NOT NULL,
            display_name TEXT NOT NULL,
            domain TEXT NOT NULL,                -- work / personal
            status TEXT NOT NULL,                -- inquiry / active / paused / completed / cancelled
            goal TEXT,
            description TEXT,
            keywords TEXT NOT NULL DEFAULT '[]', -- JSON array
            start_date TEXT,
            target_date TEXT,
            completed_date TEXT,
            project_path TEXT,
            reference_url TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)

    # 3. Create rebuilt summary_projects table
    conn.execute("""
        CREATE TABLE summary_projects (
            summary_id TEXT NOT NULL,
            project_id INTEGER NOT NULL,
            display_order INTEGER,
            PRIMARY KEY(summary_id, project_id),
            FOREIGN KEY(summary_id) REFERENCES summaries(summary_id) ON DELETE CASCADE,
            FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
        );
    """)

    # 4. Create project_candidates table
    conn.execute("""
        CREATE TABLE project_candidates (
            candidate_id INTEGER PRIMARY KEY,
            display_name TEXT NOT NULL,
            normalized_name TEXT UNIQUE NOT NULL,
            domain TEXT NOT NULL,                -- work / personal
            status TEXT NOT NULL DEFAULT 'unresolved', -- unresolved, resolved, rejected
            goal TEXT,
            description TEXT,
            keywords TEXT NOT NULL DEFAULT '[]', -- JSON array
            start_date TEXT,
            target_date TEXT,
            completed_date TEXT,
            evidence TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)

    # 5. Create summary_project_candidates table
    conn.execute("""
        CREATE TABLE summary_project_candidates (
            summary_id TEXT NOT NULL,
            candidate_id INTEGER NOT NULL,
            display_order INTEGER,
            PRIMARY KEY(summary_id, candidate_id),
            FOREIGN KEY(summary_id) REFERENCES summaries(summary_id) ON DELETE CASCADE,
            FOREIGN KEY(candidate_id) REFERENCES project_candidates(candidate_id) ON DELETE CASCADE
        );
    """)

    # 6. Create indexes
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sp_project_id ON summary_projects(project_id);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_spc_candidate_id ON summary_project_candidates(candidate_id);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pc_normalized_name ON project_candidates(normalized_name);")

    conn.execute("PRAGMA user_version = 9;")
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

    if current_version <= 8:
        run_migration_v9(conn)

    if current_version <= 9:
        run_migration_v10(conn)

    if current_version <= 10:
        run_migration_v11(conn)

    if current_version <= 11:
        run_migration_v12(conn)

    if current_version <= 12:
        run_migration_v13(conn)

    if current_version <= 13:
        run_migration_v14(conn)

    if current_version <= 14:
        run_migration_v15(conn)

    if current_version <= 15:
        run_migration_v16(conn)

    return conn


def run_migration_v14(conn: sqlite3.Connection) -> None:
    """Run the migration schema upgrade for version 14 (research_jobs output columns)."""
    try:
        conn.execute("ALTER TABLE research_jobs ADD COLUMN output_path TEXT;")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE research_jobs ADD COLUMN is_published INTEGER NOT NULL DEFAULT 0;")
    except sqlite3.OperationalError:
        pass
    conn.execute("PRAGMA user_version = 14;")
    conn.commit()


def _ignore_duplicate_schema_object(err: sqlite3.OperationalError) -> None:
    """Raise unless the error is a duplicate-column or duplicate-index error."""
    msg = str(err)
    if "duplicate column name" in msg or "already exists" in msg:
        return
    raise err


def run_migration_v15(conn: sqlite3.Connection) -> None:
    """Run the migration schema upgrade for version 15 (generic question model + research theme origin/hitl_run_id)."""
    # hitl_runs: add title and description
    try:
        conn.execute("ALTER TABLE hitl_runs ADD COLUMN title TEXT;")
    except sqlite3.OperationalError as e:
        _ignore_duplicate_schema_object(e)
    try:
        conn.execute("ALTER TABLE hitl_runs ADD COLUMN description TEXT;")
    except sqlite3.OperationalError as e:
        _ignore_duplicate_schema_object(e)
    # hitl_questions: add sequence, title, prompt, context_json
    try:
        conn.execute("ALTER TABLE hitl_questions ADD COLUMN sequence INTEGER NOT NULL DEFAULT 0;")
    except sqlite3.OperationalError as e:
        _ignore_duplicate_schema_object(e)
    try:
        conn.execute("ALTER TABLE hitl_questions ADD COLUMN title TEXT;")
    except sqlite3.OperationalError as e:
        _ignore_duplicate_schema_object(e)
    try:
        conn.execute("ALTER TABLE hitl_questions ADD COLUMN prompt TEXT;")
    except sqlite3.OperationalError as e:
        _ignore_duplicate_schema_object(e)
    try:
        conn.execute("ALTER TABLE hitl_questions ADD COLUMN context_json TEXT;")
    except sqlite3.OperationalError as e:
        _ignore_duplicate_schema_object(e)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hitl_questions_set_seq ON hitl_questions(run_id, question_set_id, sequence);")
    # research_themes: add origin and hitl_run_id
    try:
        conn.execute("ALTER TABLE research_themes ADD COLUMN origin TEXT;")
    except sqlite3.OperationalError as e:
        _ignore_duplicate_schema_object(e)
    try:
        conn.execute("ALTER TABLE research_themes ADD COLUMN hitl_run_id TEXT;")
    except sqlite3.OperationalError as e:
        _ignore_duplicate_schema_object(e)
    conn.execute("PRAGMA user_version = 15;")
    conn.commit()


def run_migration_v16(conn: sqlite3.Connection) -> None:
    """Run migration for version 16 (hitl_runs.display_type TEXT column)."""
    try:
        conn.execute("ALTER TABLE hitl_runs ADD COLUMN display_type TEXT;")
    except sqlite3.OperationalError as e:
        _ignore_duplicate_schema_object(e)
    conn.execute("PRAGMA user_version = 16;")
    conn.commit()


def run_migration_v13(conn: sqlite3.Connection) -> None:
    """Run the migration schema upgrade for version 13 (HITL runs and questions)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS hitl_runs (
            run_id TEXT PRIMARY KEY,
            handler TEXT NOT NULL,
            status TEXT NOT NULL,
            checkpoint TEXT,
            active_question_set_id TEXT,
            lease_owner TEXT,
            lease_expires_at TEXT,
            retry_count INTEGER NOT NULL DEFAULT 0,
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS hitl_questions (
            question_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            question_set_id TEXT NOT NULL,
            question_key TEXT NOT NULL,
            status TEXT NOT NULL,
            question_type TEXT NOT NULL,
            display_text TEXT NOT NULL,
            choices TEXT, -- JSON string
            answer TEXT, -- JSON string
            is_required INTEGER NOT NULL DEFAULT 1,
            expires_at TEXT,
            answered_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(run_id) REFERENCES hitl_runs(run_id) ON DELETE CASCADE,
            UNIQUE(run_id, question_set_id, question_key)
        );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hitl_runs_status ON hitl_runs(status);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hitl_questions_run_set ON hitl_questions(run_id, question_set_id);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hitl_questions_status ON hitl_questions(status);")
    conn.execute("PRAGMA user_version = 13;")
    conn.commit()


def run_migration_v10(conn: sqlite3.Connection) -> None:
    """Run the migration schema upgrade for version 10 (command_runs and llm_call_logs tables)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS command_runs (
            run_id TEXT PRIMARY KEY,
            command TEXT NOT NULL,
            args_json TEXT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL CHECK(status IN ('running', 'succeeded', 'failed')),
            summary TEXT,
            exception_type TEXT,
            exception_message TEXT,
            traceback TEXT
        );
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS llm_call_logs (
            call_id TEXT PRIMARY KEY,
            run_id TEXT,
            provider TEXT,
            model TEXT,
            temperature REAL,
            max_tokens INTEGER,
            prompt TEXT,
            response TEXT,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            total_tokens INTEGER,
            finish_reason TEXT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL CHECK(status IN ('running', 'succeeded', 'failed')),
            exception_type TEXT,
            exception_message TEXT,
            traceback TEXT,
            FOREIGN KEY(run_id) REFERENCES command_runs(run_id) ON DELETE CASCADE
        );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_command_runs_status_started ON command_runs(status, started_at DESC);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_llm_call_logs_status_started ON llm_call_logs(status, started_at DESC);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_llm_call_logs_run_id_started ON llm_call_logs(run_id, started_at);")
    conn.execute("PRAGMA user_version = 10;")
    conn.commit()


def run_migration_v11(conn: sqlite3.Connection) -> None:
    """Run the migration schema upgrade for version 11 (activity_logs.project_id column and index)."""
    conn.execute(
        "ALTER TABLE activity_logs ADD COLUMN project_id INTEGER REFERENCES projects(project_id) ON DELETE SET NULL;"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_activity_logs_project_id ON activity_logs(project_id);"
    )
    conn.execute("PRAGMA user_version = 11;")
    conn.commit()


def run_migration_v12(conn: sqlite3.Connection) -> None:
    """Add note column to summary_projects for per-project activity notes."""
    conn.execute(
        "ALTER TABLE summary_projects ADD COLUMN note TEXT;"
    )
    conn.execute("PRAGMA user_version = 12;")
    conn.commit()
