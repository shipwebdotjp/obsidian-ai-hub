from __future__ import annotations

import calendar
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from obsidian_ai_hub.utils import config
from obsidian_ai_hub.utils.dates import get_partial_date_bounds
from obsidian_ai_hub.tasks.capabilities import get_capability_definitions


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


def run_migration_v36(db: sqlite3.Connection) -> None:
    try:
        db.execute("ALTER TABLE coding_runs ADD COLUMN slash_invocation_json TEXT")
    except sqlite3.OperationalError as e:
        _ignore_duplicate_schema_object(e)
    db.execute("PRAGMA user_version = 36")
    db.commit()


def run_migration_v37(db: sqlite3.Connection) -> None:
    try:
        db.execute("ALTER TABLE agent_runs ADD COLUMN slash_invocation_json TEXT")
    except sqlite3.OperationalError as e:
        _ignore_duplicate_schema_object(e)
    db.execute("PRAGMA user_version = 37")
    db.commit()


BUILTIN_RELATION_TYPES = [
    ("parent-child", "directed", "親である", "子である"),
    ("spouse", "symmetric", "夫婦である", "夫婦である"),
    ("partner", "symmetric", "パートナーである", "パートナーである"),
    ("sibling", "symmetric", "きょうだいである", "きょうだいである"),
    ("guardian-of", "directed", "保護者である", "被保護者である"),
    ("cohabitant", "symmetric", "同居している", "同居している"),
    ("neighbor", "symmetric", "隣人である", "隣人である"),
    ("roommate", "symmetric", "ルームメイトである", "ルームメイトである"),
    ("supervises", "directed", "監督している", "監督されている"),
    ("reports-to", "directed", "報告している", "報告を受けている"),
    ("colleague", "symmetric", "同僚である", "同僚である"),
    ("mentor-of", "directed", "メンターである", "メンティーである"),
    ("client-of", "directed", "クライアントである", "サービスを提供している"),
    ("friend", "symmetric", "友人である", "友人である"),
    ("best-friend", "symmetric", "親友である", "親友である"),
    ("acquaintance", "symmetric", "知人である", "知人である"),
    ("adversary", "symmetric", "対立している", "対立している"),
    ("estranged", "symmetric", "疎遠である", "疎遠である"),
    ("supports", "directed", "支援している", "支援を受けている"),
    ("cares-for", "directed", "世話をしている", "世話を受けている"),
    ("assists", "directed", "援助している", "援助を受けている"),
    ("respects", "directed", "尊敬している", "尊敬されている"),
    ("trusts", "directed", "信頼している", "信頼されている"),
    ("likes", "directed", "好意を抱いている", "好意を抱かれている"),
    ("dislikes", "directed", "嫌っている", "嫌われている"),
]


def run_migration_v38(db: sqlite3.Connection) -> None:
    """Run migration for version 38 (person_relation_types, person_relations, person_relation_evidence tables)."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS person_relation_types (
            relation_type_id TEXT PRIMARY KEY,
            slug TEXT NOT NULL UNIQUE,
            forward_label TEXT NOT NULL,
            reverse_label TEXT NOT NULL,
            directionality TEXT NOT NULL CHECK (directionality IN ('directed', 'symmetric')),
            description TEXT,
            is_builtin INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS person_relations (
            relation_id TEXT PRIMARY KEY,
            subject_person_id TEXT NOT NULL REFERENCES people(person_id) ON DELETE CASCADE,
            object_person_id TEXT NOT NULL REFERENCES people(person_id) ON DELETE CASCADE,
            relation_type_id TEXT NOT NULL REFERENCES person_relation_types(relation_type_id) ON DELETE RESTRICT,
            started_on TEXT,
            ended_on TEXT,
            note TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK (subject_person_id != object_person_id),
            CHECK (started_on IS NULL OR ended_on IS NULL OR started_on <= ended_on)
        );
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS person_relation_evidence (
            evidence_id TEXT PRIMARY KEY,
            relation_id TEXT NOT NULL REFERENCES person_relations(relation_id) ON DELETE CASCADE,
            source_type TEXT NOT NULL CHECK (source_type = 'manual'),
            source_ref TEXT,
            quote TEXT,
            note TEXT,
            observed_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)

    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_person_relations_unique_period "
        "ON person_relations (relation_type_id, subject_person_id, object_person_id, COALESCE(started_on, ''), COALESCE(ended_on, ''));"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_person_relations_subject ON person_relations(subject_person_id);"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_person_relations_object ON person_relations(object_person_id);"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_person_relations_type ON person_relations(relation_type_id);"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_person_relation_evidence_relation ON person_relation_evidence(relation_id);"
    )

    now = datetime.now(timezone.utc).isoformat()
    for slug, directionality, forward_label, reverse_label in BUILTIN_RELATION_TYPES:
        relation_type_id = f"rlt_builtin_{slug}"
        db.execute(
            """
            INSERT INTO person_relation_types (
                relation_type_id, slug, forward_label, reverse_label,
                directionality, is_builtin, is_active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 1, 1, ?, ?)
            ON CONFLICT(relation_type_id) DO UPDATE SET
                slug=excluded.slug,
                forward_label=excluded.forward_label,
                reverse_label=excluded.reverse_label,
                directionality=excluded.directionality,
                is_builtin=1,
                is_active=1,
                updated_at=excluded.updated_at
            """,
            (relation_type_id, slug, forward_label, reverse_label, directionality, now, now),
        )

    db.execute("PRAGMA user_version = 38")
    db.commit()


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
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sp_project_id ON summary_projects(project_id);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_spc_candidate_id ON summary_project_candidates(candidate_id);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pc_normalized_name ON project_candidates(normalized_name);"
    )

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

    if current_version <= 16:
        run_migration_v17(conn)

    if current_version <= 17:
        run_migration_v18(conn)

    if current_version <= 18:
        run_migration_v19(conn)

    if current_version <= 19:
        run_migration_v20(conn)

    if current_version <= 20:
        run_migration_v21(conn)

    if current_version <= 21:
        run_migration_v22(conn)

    if current_version <= 22:
        run_migration_v23(conn)

    if current_version <= 23:
        run_migration_v24(conn)

    if current_version <= 24:
        run_migration_v25(conn)

    if current_version <= 25:
        run_migration_v26(conn)

    if current_version <= 26:
        run_migration_v27(conn)

    if current_version <= 27:
        run_migration_v28(conn)

    if current_version <= 28:
        run_migration_v29(conn)

    if current_version <= 29:
        run_migration_v30(conn)

    if current_version <= 30:
        run_migration_v31(conn)

    if current_version <= 31:
        run_migration_v32(conn)

    if current_version <= 32:
        run_migration_v33(conn)

    if current_version <= 33:
        run_migration_v34(conn)

    if current_version <= 34:
        run_migration_v35(conn)

    if current_version <= 35:
        run_migration_v36(conn)

    if current_version <= 36:
        run_migration_v37(conn)

    if current_version <= 37:
        run_migration_v38(conn)

    if current_version <= 38:
        run_migration_v39(conn)

    if current_version <= 39:
        run_migration_v40(conn)

    if current_version <= 40:
        run_migration_v41(conn)

    if current_version <= 41:
        run_migration_v42(conn)

    if current_version <= 42:
        run_migration_v43(conn)

    if current_version <= 43:
        run_migration_v44(conn)

    if current_version <= 44:
        run_migration_v45(conn)

    if current_version <= 45:
        run_migration_v46(conn)

    if current_version <= 46:
        run_migration_v47(conn)

    if current_version <= 47:
        run_migration_v48(conn)

    if current_version <= 48:
        run_migration_v49(conn)

    if current_version <= 49:
        run_migration_v50(conn)

    if current_version <= 50:
        run_migration_v51(conn)

    if current_version <= 51:
        run_migration_v52(conn)

    if current_version <= 52:
        run_migration_v53(conn)

    if current_version <= 53:
        run_migration_v54(conn)

    if current_version <= 54:
        run_migration_v55(conn)

    if current_version <= 55:
        run_migration_v56(conn)

    return conn


def run_migration_v52(conn: sqlite3.Connection) -> None:
    """Run migration for version 52 (allow the ``incomplete`` Task status).

    Budget exhaustion with unmet required effects is recorded as
    ``incomplete`` rather than ``failed`` (see
    ``docs/task-agent/adr/effect-contract-completion.md``). The status CHECK
    constraint is inline, so SQLite requires a table rebuild while foreign
    keys from ``task_agent_plans``/``task_agent_events`` are disabled.
    """
    conn.execute("PRAGMA foreign_keys = OFF;")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS task_agent_tasks_v52 (
            task_id TEXT PRIMARY KEY,
            prompt_text TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN (
                'queued', 'planning', 'waiting_user', 'waiting_approval',
                'ready', 'running', 'waiting_reapproval', 'cancelling',
                'interrupted', 'completed', 'incomplete', 'failed', 'cancelled'
            )),
            current_plan_id TEXT,
            worker_instance_id TEXT,
            active_child_kind TEXT,
            active_child_run_id TEXT,
            result_summary TEXT,
            error_summary TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT
        );
    """)
    existing = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='task_agent_tasks';"
    ).fetchone()
    if existing is not None:
        conn.execute("""
            INSERT OR REPLACE INTO task_agent_tasks_v52 (
                task_id, prompt_text, status, current_plan_id, worker_instance_id,
                active_child_kind, active_child_run_id, result_summary,
                error_summary, created_at, updated_at, started_at, finished_at
            )
            SELECT task_id, prompt_text, status, current_plan_id,
                worker_instance_id, active_child_kind, active_child_run_id,
                result_summary, error_summary, created_at, updated_at,
                started_at, finished_at
            FROM task_agent_tasks;
        """)
        conn.execute("DROP TABLE task_agent_tasks;")
    conn.execute("ALTER TABLE task_agent_tasks_v52 RENAME TO task_agent_tasks;")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_task_agent_tasks_status "
        "ON task_agent_tasks(status);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_task_agent_tasks_worker "
        "ON task_agent_tasks(worker_instance_id);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_task_agent_tasks_finished "
        "ON task_agent_tasks(finished_at);"
    )
    conn.execute("PRAGMA user_version = 52;")
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON;")


def run_migration_v53(conn: sqlite3.Connection) -> None:
    """Run migration for version 53 (Workflow graph tables).

    Adds the Workflow Bounded Context tables (``docs/workflow/specification.md``
    §16.2). Nodes/edges belong to a revision; runs snapshot the graph; node
    invocations are keyed by persistent activation id so retries reuse the same
    activation while loop iterations get a new one.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS workflows (
            workflow_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_revisions (
            revision_id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('draft','published','superseded')),
            inputs_schema TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_nodes (
            node_id TEXT PRIMARY KEY,
            revision_id TEXT NOT NULL,
            node_type TEXT NOT NULL,
            label TEXT,
            config_json TEXT NOT NULL,
            parent_loop_node_id TEXT,
            ui_position_json TEXT
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_edges (
            edge_id TEXT PRIMARY KEY,
            revision_id TEXT NOT NULL,
            source_node_id TEXT NOT NULL,
            target_node_id TEXT NOT NULL,
            edge_kind TEXT NOT NULL DEFAULT 'normal',
            condition_json TEXT,
            order_index INTEGER NOT NULL
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_runs (
            run_id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL,
            revision_id TEXT NOT NULL,
            status TEXT NOT NULL,
            inputs_json TEXT,
            graph_snapshot_json TEXT,
            worker_instance_id TEXT,
            result_summary TEXT,
            error_summary TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_run_nodes (
            run_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            activation_id TEXT NOT NULL,
            attempt INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL,
            inputs_json TEXT,
            output_json TEXT,
            output_summary TEXT,
            error_summary TEXT,
            started_at TEXT,
            finished_at TEXT,
            PRIMARY KEY (activation_id, attempt)
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_activations (
            activation_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            iteration_context TEXT,
            created_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_events (
            event_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_revisions_workflow "
        "ON workflow_revisions(workflow_id, status);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_nodes_revision "
        "ON workflow_nodes(revision_id);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_edges_revision "
        "ON workflow_edges(revision_id, source_node_id);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_runs_status "
        "ON workflow_runs(status);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_runs_worker "
        "ON workflow_runs(worker_instance_id);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_runs_finished "
        "ON workflow_runs(finished_at);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_run_nodes_run "
        "ON workflow_run_nodes(run_id, node_id);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_events_run "
        "ON workflow_events(run_id, seq);"
    )
    conn.execute("PRAGMA user_version = 53;")
    conn.commit()


def run_migration_v54(conn: sqlite3.Connection) -> None:
    """Run migration for version 54 (Workflow run rerun lineage).

    Records which run a rerun was created from so the audit trail can link the
    copies. Adds ``workflow_runs.source_run_id``.
    """
    conn.execute(
        "ALTER TABLE workflow_runs ADD COLUMN source_run_id TEXT;"
    )
    conn.execute("PRAGMA user_version = 54;")
    conn.commit()


def run_migration_v55(conn: sqlite3.Connection) -> None:
    """Run migration for version 55 (agent Vault context references).

    Stores user-selected Vault file references (``[{"kind": "vault_file",
    "path": "<vault-relative POSIX path>"}]``) on ``agent_messages`` so the
    runtime can re-read the current note content into the LLM context on every
    turn. Only paths are persisted; note bodies always come from the Vault.
    """
    try:
        conn.execute(
            "ALTER TABLE agent_messages ADD COLUMN context_refs_json "
            "TEXT NOT NULL DEFAULT '[]';"
        )
    except sqlite3.OperationalError as e:
        _ignore_duplicate_schema_object(e)
    conn.execute("PRAGMA user_version = 55;")
    conn.commit()


def run_migration_v56(conn: sqlite3.Connection) -> None:
    """Run migration for version 56 (Task origin separation).

    Workflow capability nodes reuse the Task capability adapters, which
    require a Task row for child linkage, cancellation and events. That
    short-lived "bridge" Task must not surface as a user-facing Task in the
    Task Agent list (see ``docs/workflow/adr/workflow-graph-and-agent-node.md``).
    ``origin`` records who created the row; the list API excludes
    ``'workflow'``. Existing bridge rows are backfilled from the prompt
    marker used before this column existed.
    """
    try:
        conn.execute(
            "ALTER TABLE task_agent_tasks ADD COLUMN origin "
            "TEXT NOT NULL DEFAULT 'user';"
        )
    except sqlite3.OperationalError as e:
        _ignore_duplicate_schema_object(e)
    conn.execute(
        "UPDATE task_agent_tasks SET origin = 'workflow' "
        "WHERE prompt_text LIKE 'Workflow run % node % (%';"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_task_agent_tasks_origin "
        "ON task_agent_tasks(origin);"
    )
    conn.execute("PRAGMA user_version = 56;")
    conn.commit()


def run_migration_v51(conn: sqlite3.Connection) -> None:
    """Run migration for version 51 (planner proposal rejection feedback).

    Adds dedicated columns so a rejection reason key and an optional free-text
    comment are stored separately from ``external_result`` (which stays the
    Apple write result on promotion).
    """
    for statement in (
        "ALTER TABLE planner_proposals ADD COLUMN rejection_reason TEXT;",
        "ALTER TABLE planner_proposals ADD COLUMN rejection_comment TEXT;",
    ):
        try:
            conn.execute(statement)
        except sqlite3.OperationalError as e:
            _ignore_duplicate_schema_object(e)
    conn.execute("PRAGMA user_version = 51;")
    conn.commit()


def run_migration_v49(conn: sqlite3.Connection) -> None:
    """Run migration for version 49 (per-session OpenCode model)."""
    try:
        conn.execute("ALTER TABLE coding_sessions ADD COLUMN opencode_model TEXT;")
    except sqlite3.OperationalError as e:
        _ignore_duplicate_schema_object(e)
    conn.execute("PRAGMA user_version = 49;")
    conn.commit()


def run_migration_v50(conn: sqlite3.Connection) -> None:
    """Run migration for version 50 (project-grounded research mode)."""
    for statement in (
        "ALTER TABLE research_themes ADD COLUMN project_id INTEGER;",
        "ALTER TABLE research_jobs ADD COLUMN project_id INTEGER;",
    ):
        try:
            conn.execute(statement)
        except sqlite3.OperationalError as e:
            _ignore_duplicate_schema_object(e)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_rt_project_id ON research_themes(project_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_rj_project_id ON research_jobs(project_id)"
    )
    conn.execute("PRAGMA user_version = 50;")
    conn.commit()


def run_migration_v48(conn: sqlite3.Connection) -> None:
    """Run migration for version 48 (Scheduler Job rename + one-shot queue).

    - Recreate ``task_state`` as ``job_state`` (``task_id`` -> ``job_id``),
      copy existing rows, then drop the old table. Scheduler execution state
      is preserved; old table/SQL must not remain.
    - Create ``one_shot_jobs`` queue for run-once jobs with
      queued/running/succeeded/failed/cancelled/interrupted states,
      registration source, timing, exit code, per-segment output, and indexes
      on due-date and completion time.
    """
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    if "job_state" not in tables:
        conn.execute("""
            CREATE TABLE job_state (
                job_id TEXT PRIMARY KEY,
                last_check_at TEXT NOT NULL,
                consecutive_empty_count INTEGER NOT NULL DEFAULT 0,
                last_processed_at TEXT,
                last_error_at TEXT,
                last_error_message TEXT,
                last_error_type TEXT,
                processed_count INTEGER NOT NULL DEFAULT 0,
                skipped_count INTEGER NOT NULL DEFAULT 0,
                failed_count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );
        """)
    if "task_state" in tables:
        conn.execute("""
            INSERT OR REPLACE INTO job_state (
                job_id, last_check_at, consecutive_empty_count,
                last_processed_at, last_error_at, last_error_message, last_error_type,
                processed_count, skipped_count, failed_count, updated_at
            ) SELECT task_id, last_check_at, consecutive_empty_count,
                last_processed_at, last_error_at, last_error_message, last_error_type,
                processed_count, skipped_count, failed_count, updated_at
            FROM task_state;
        """)
        conn.execute("DROP TABLE task_state;")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS one_shot_jobs (
            job_id TEXT PRIMARY KEY,
            command TEXT NOT NULL,
            run_at_utc TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            agent_id TEXT,
            session_id TEXT,
            run_id TEXT,
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            exit_code INTEGER,
            segments_json TEXT NOT NULL DEFAULT '[]',
            output_truncated INTEGER NOT NULL DEFAULT 0,
            error_summary TEXT
        );
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_one_shot_jobs_status_run_at"
        " ON one_shot_jobs(status, run_at_utc);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_one_shot_jobs_finished_at"
        " ON one_shot_jobs(finished_at);"
    )
    conn.execute("PRAGMA user_version = 48;")
    conn.commit()


def run_migration_v47(db: sqlite3.Connection) -> None:
    """Run migration for version 47 (research_suggestion_requests table for research proposal idempotency)."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS research_suggestion_requests (
            request_key TEXT PRIMARY KEY,
            theme_id TEXT NOT NULL REFERENCES research_themes(theme_id) ON DELETE CASCADE,
            hitl_run_id TEXT NOT NULL REFERENCES hitl_runs(run_id) ON DELETE CASCADE,
            created_at TEXT NOT NULL
        );
    """)
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_research_suggestion_requests_created "
        "ON research_suggestion_requests(created_at);"
    )
    db.execute("PRAGMA user_version = 47")
    db.commit()


def run_migration_v45(db: sqlite3.Connection) -> None:
    """Run migration for version 45 (ACP transport support in coding_sessions and coding_runs)."""
    # 1. Add transport & ACP columns to coding_sessions
    try:
        db.execute("ALTER TABLE coding_sessions ADD COLUMN transport TEXT NOT NULL DEFAULT 'direct_cli';")
    except sqlite3.OperationalError as e:
        _ignore_duplicate_schema_object(e)
    try:
        db.execute("ALTER TABLE coding_sessions ADD COLUMN acp_session_id TEXT;")
    except sqlite3.OperationalError as e:
        _ignore_duplicate_schema_object(e)
    try:
        db.execute("ALTER TABLE coding_sessions ADD COLUMN acp_profile_id TEXT;")
    except sqlite3.OperationalError as e:
        _ignore_duplicate_schema_object(e)

    # Backfill existing session transport
    db.execute("UPDATE coding_sessions SET transport = 'direct_cli' WHERE transport IS NULL OR transport = '';")

    # 2. Add transport & ACP columns to coding_runs
    for col_def in (
        "transport TEXT NOT NULL DEFAULT 'direct_cli'",
        "acp_session_id TEXT",
        "acp_profile_id TEXT",
        "acp_version TEXT",
        "acp_capabilities_json TEXT",
        "acp_resume_mode TEXT",
        "acp_stop_reason TEXT",
    ):
        try:
            db.execute(f"ALTER TABLE coding_runs ADD COLUMN {col_def};")
        except sqlite3.OperationalError as e:
            _ignore_duplicate_schema_object(e)

    db.execute("UPDATE coding_runs SET transport = 'direct_cli' WHERE transport IS NULL OR transport = '';")

    db.execute("PRAGMA user_version = 45")
    db.commit()


def run_migration_v46(db: sqlite3.Connection) -> None:
    """Run migration for version 46 (ACP elicitation wait table for cross-process HITL handoff)."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS acp_elicitation_waits (
            hitl_run_id TEXT PRIMARY KEY,
            coding_run_id TEXT NOT NULL,
            elicitation_request_id TEXT NOT NULL,
            connection_token TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'waiting',
            heartbeat_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_acp_elicitation_waits_coding_run "
        "ON acp_elicitation_waits(coding_run_id);"
    )

    db.execute("PRAGMA user_version = 46")
    db.commit()


def run_migration_v14(conn: sqlite3.Connection) -> None:
    """Run the migration schema upgrade for version 14 (research_jobs output columns)."""
    try:
        conn.execute("ALTER TABLE research_jobs ADD COLUMN output_path TEXT;")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute(
            "ALTER TABLE research_jobs ADD COLUMN is_published INTEGER NOT NULL DEFAULT 0;"
        )
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
        conn.execute(
            "ALTER TABLE hitl_questions ADD COLUMN sequence INTEGER NOT NULL DEFAULT 0;"
        )
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
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_hitl_questions_set_seq ON hitl_questions(run_id, question_set_id, sequence);"
    )
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


def run_migration_v17(conn: sqlite3.Connection) -> None:
    """Run migration for version 17 (research_themes HITL feedback columns).

    Feedback is only populated for auto_suggestion themes that flow through the
    HITL confirmation (research.run_approved_suggestion).
    """
    for column in (
        "feedback_decision",
        "feedback_reason",
        "feedback_comment",
        "feedback_at",
    ):
        try:
            conn.execute(f"ALTER TABLE research_themes ADD COLUMN {column} TEXT;")
        except sqlite3.OperationalError as e:
            _ignore_duplicate_schema_object(e)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_rt_feedback_decision_at "
        "ON research_themes(feedback_decision, feedback_at);"
    )
    conn.execute("PRAGMA user_version = 17;")
    conn.commit()


def run_migration_v39(db: sqlite3.Connection) -> None:
    """Run migration for version 39 (person property definitions, options, aliases, and values)."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS person_property_definitions (
            property_definition_id TEXT PRIMARY KEY,
            key TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            data_type TEXT NOT NULL CHECK (data_type IN ('text', 'date', 'number', 'boolean', 'select')),
            cardinality TEXT NOT NULL CHECK (cardinality IN ('single', 'multiple')),
            source_type TEXT NOT NULL CHECK (source_type IN ('database', 'vault')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS person_property_definition_aliases (
            alias_id TEXT PRIMARY KEY,
            property_definition_id TEXT NOT NULL REFERENCES person_property_definitions(property_definition_id) ON DELETE CASCADE,
            alias_key TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        );
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS person_property_options (
            option_id TEXT PRIMARY KEY,
            property_definition_id TEXT NOT NULL REFERENCES person_property_definitions(property_definition_id) ON DELETE CASCADE,
            option_key TEXT NOT NULL,
            display_name TEXT NOT NULL,
            display_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (property_definition_id, option_key)
        );
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS person_property_option_aliases (
            alias_id TEXT PRIMARY KEY,
            option_id TEXT NOT NULL REFERENCES person_property_options(option_id) ON DELETE CASCADE,
            alias_value TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (option_id, alias_value)
        );
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS person_property_values (
            property_value_id TEXT PRIMARY KEY,
            person_id TEXT NOT NULL REFERENCES people(person_id) ON DELETE CASCADE,
            property_definition_id TEXT NOT NULL REFERENCES person_property_definitions(property_definition_id) ON DELETE CASCADE,
            source_type TEXT NOT NULL CHECK (source_type IN ('database', 'vault')),
            value_text TEXT,
            value_date TEXT,
            value_number REAL,
            value_boolean INTEGER CHECK (value_boolean IS NULL OR value_boolean IN (0, 1)),
            option_id TEXT REFERENCES person_property_options(option_id) ON DELETE RESTRICT,
            valid_from TEXT,
            valid_until TEXT,
            note TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK (valid_from IS NULL OR valid_until IS NULL OR valid_from <= valid_until)
        );
    """)

    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_ppv_person ON person_property_values(person_id);"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_ppv_definition ON person_property_values(property_definition_id);"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_ppv_def_text_period ON person_property_values(property_definition_id, value_text, valid_from, valid_until);"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_ppv_def_date_period ON person_property_values(property_definition_id, value_date, valid_from, valid_until);"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_ppv_def_number_period ON person_property_values(property_definition_id, value_number, valid_from, valid_until);"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_ppv_def_bool_period ON person_property_values(property_definition_id, value_boolean, valid_from, valid_until);"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_ppv_def_option_period ON person_property_values(property_definition_id, option_id, valid_from, valid_until);"
    )

    db.execute("PRAGMA user_version = 39")
    db.commit()


def run_migration_v40(db: sqlite3.Connection) -> None:
    """Run migration for version 40 (principal_person_settings table for Principal Person context)."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS principal_person_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            person_id TEXT NOT NULL REFERENCES people(person_id) ON DELETE RESTRICT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)

    db.execute("PRAGMA user_version = 40")
    db.commit()


def run_migration_v41(db: sqlite3.Connection) -> None:
    """Run migration for version 41 (memories.scope, memory_people table, and person_summary_extraction_logs table)."""
    try:
        db.execute(
            "ALTER TABLE memories ADD COLUMN scope TEXT DEFAULT 'user' CHECK (scope IS NULL OR scope IN ('user', 'person'));"
        )
    except sqlite3.OperationalError as e:
        _ignore_duplicate_schema_object(e)

    # Fill existing rows with scope='user' if null
    db.execute("UPDATE memories SET scope = 'user' WHERE scope IS NULL;")

    db.execute("""
        CREATE TABLE IF NOT EXISTS memory_people (
            memory_id TEXT NOT NULL REFERENCES memories(memory_id) ON DELETE CASCADE,
            person_id TEXT NOT NULL REFERENCES people(person_id) ON DELETE CASCADE,
            created_at TEXT NOT NULL,
            PRIMARY KEY (memory_id, person_id)
        );
    """)

    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_people_person ON memory_people(person_id);"
    )

    db.execute("""
        CREATE TABLE IF NOT EXISTS person_summary_extraction_logs (
            summary_id TEXT NOT NULL REFERENCES summaries(summary_id) ON DELETE CASCADE,
            person_id TEXT NOT NULL REFERENCES people(person_id) ON DELETE CASCADE,
            content_hash TEXT NOT NULL,
            processed_at TEXT NOT NULL,
            PRIMARY KEY (summary_id, person_id)
        );
    """)

    db.execute("PRAGMA user_version = 41")
    db.commit()


def get_date_bounds(d_str: str | None) -> tuple[str | None, str | None]:
    if not d_str or not str(d_str).strip():
        return None, None
    s = str(d_str).strip().replace("/", "-")
    parts = s.split("-")
    if len(parts) == 1 and re.match(r"^\d{4}$", parts[0]):
        y = int(parts[0])
        return f"{y:04d}-01-01", f"{y:04d}-12-31"
    elif len(parts) == 2 and re.match(r"^\d{4}$", parts[0]) and re.match(r"^\d{1,2}$", parts[1]):
        y, m = int(parts[0]), int(parts[1])
        if 1 <= m <= 12:
            last_day = calendar.monthrange(y, m)[1]
            return f"{y:04d}-{m:02d}-01", f"{y:04d}-{m:02d}-{last_day:02d}"
    elif len(parts) == 3 and re.match(r"^\d{4}$", parts[0]) and re.match(r"^\d{1,2}$", parts[1]) and re.match(r"^\d{1,2}$", parts[2]):
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        if 1 <= m <= 12:
            last_day = calendar.monthrange(y, m)[1]
            if 1 <= d <= last_day:
                formatted = f"{y:04d}-{m:02d}-{d:02d}"
                return formatted, formatted
    return None, None


def run_migration_v42(db: sqlite3.Connection) -> None:
    """Run migration for version 42 (person_property_values rebuild with partial date boundary columns & new CHECK constraint)."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS person_property_values_v42 (
            property_value_id TEXT PRIMARY KEY,
            person_id TEXT NOT NULL REFERENCES people(person_id) ON DELETE CASCADE,
            property_definition_id TEXT NOT NULL REFERENCES person_property_definitions(property_definition_id) ON DELETE CASCADE,
            source_type TEXT NOT NULL CHECK (source_type IN ('database', 'vault')),
            value_text TEXT,
            value_date TEXT,
            value_date_min TEXT,
            value_date_max TEXT,
            value_number REAL,
            value_boolean INTEGER CHECK (value_boolean IS NULL OR value_boolean IN (0, 1)),
            option_id TEXT REFERENCES person_property_options(option_id) ON DELETE RESTRICT,
            valid_from TEXT,
            valid_from_min TEXT,
            valid_until TEXT,
            valid_until_max TEXT,
            note TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK (valid_from_min IS NULL OR valid_until_max IS NULL OR valid_from_min <= valid_until_max)
        );
    """)

    cursor = db.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='person_property_values';"
    )
    if cursor.fetchone() is not None:
        cursor.execute("""
            SELECT property_value_id, person_id, property_definition_id, source_type,
                   value_text, value_date, value_number, value_boolean, option_id,
                   valid_from, valid_until, note, created_at, updated_at
            FROM person_property_values
        """)
        rows = cursor.fetchall()
        for r in rows:
            v_date_min, v_date_max = get_date_bounds(r["value_date"])
            v_from_min, _ = get_date_bounds(r["valid_from"])
            _, v_until_max = get_date_bounds(r["valid_until"])

            db.execute(
                """
                INSERT INTO person_property_values_v42 (
                    property_value_id, person_id, property_definition_id, source_type,
                    value_text, value_date, value_date_min, value_date_max,
                    value_number, value_boolean, option_id,
                    valid_from, valid_from_min, valid_until, valid_until_max,
                    note, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    r["property_value_id"],
                    r["person_id"],
                    r["property_definition_id"],
                    r["source_type"],
                    r["value_text"],
                    r["value_date"],
                    v_date_min,
                    v_date_max,
                    r["value_number"],
                    r["value_boolean"],
                    r["option_id"],
                    r["valid_from"],
                    v_from_min,
                    r["valid_until"],
                    v_until_max,
                    r["note"],
                    r["created_at"],
                    r["updated_at"],
                ),
            )

        db.execute("DROP TABLE person_property_values;")

    db.execute("ALTER TABLE person_property_values_v42 RENAME TO person_property_values;")

    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_ppv_person ON person_property_values(person_id);"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_ppv_definition ON person_property_values(property_definition_id);"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_ppv_def_text_period ON person_property_values(property_definition_id, value_text, valid_from_min, valid_until_max);"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_ppv_def_date_period ON person_property_values(property_definition_id, value_date_min, value_date_max, valid_from_min, valid_until_max);"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_ppv_def_number_period ON person_property_values(property_definition_id, value_number, valid_from_min, valid_until_max);"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_ppv_def_bool_period ON person_property_values(property_definition_id, value_boolean, valid_from_min, valid_until_max);"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_ppv_def_option_period ON person_property_values(property_definition_id, option_id, valid_from_min, valid_until_max);"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_ppv_def_bounds ON person_property_values(property_definition_id, valid_from_min, valid_until_max);"
    )

    db.execute("PRAGMA user_version = 42")
    db.commit()


def run_migration_v43(db: sqlite3.Connection) -> None:
    """Run migration for version 43 (person_relations rebuild with partial date boundary columns & new CHECK constraint)."""
    # Rebuilding drops person_relations while person_relation_evidence holds a
    # foreign key to it; disable FK enforcement for the rebuild (restored below).
    db.execute("PRAGMA foreign_keys = OFF;")
    db.execute("""
        CREATE TABLE IF NOT EXISTS person_relations_v43 (
            relation_id TEXT PRIMARY KEY,
            subject_person_id TEXT NOT NULL REFERENCES people(person_id) ON DELETE CASCADE,
            object_person_id TEXT NOT NULL REFERENCES people(person_id) ON DELETE CASCADE,
            relation_type_id TEXT NOT NULL REFERENCES person_relation_types(relation_type_id) ON DELETE RESTRICT,
            started_on TEXT,
            started_on_min TEXT,
            ended_on TEXT,
            ended_on_max TEXT,
            note TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK (subject_person_id != object_person_id),
            CHECK (started_on_min IS NULL OR ended_on_max IS NULL OR started_on_min <= ended_on_max)
        );
    """)

    cursor = db.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='person_relations';"
    )
    if cursor.fetchone() is not None:
        cursor.execute("""
            SELECT relation_id, subject_person_id, object_person_id, relation_type_id,
                   started_on, ended_on, note, created_at, updated_at
            FROM person_relations
        """)
        rows = cursor.fetchall()
        for r in rows:
            s_min, _ = get_partial_date_bounds(r["started_on"])
            _, e_max = get_partial_date_bounds(r["ended_on"])

            db.execute(
                """
                INSERT INTO person_relations_v43 (
                    relation_id, subject_person_id, object_person_id, relation_type_id,
                    started_on, started_on_min, ended_on, ended_on_max,
                    note, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    r["relation_id"],
                    r["subject_person_id"],
                    r["object_person_id"],
                    r["relation_type_id"],
                    r["started_on"],
                    s_min,
                    r["ended_on"],
                    e_max,
                    r["note"],
                    r["created_at"],
                    r["updated_at"],
                ),
            )

        db.execute("DROP TABLE person_relations;")

    db.execute("ALTER TABLE person_relations_v43 RENAME TO person_relations;")

    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_person_relations_unique_period "
        "ON person_relations (relation_type_id, subject_person_id, object_person_id, COALESCE(started_on, ''), COALESCE(ended_on, ''));"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_person_relations_subject ON person_relations(subject_person_id);"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_person_relations_object ON person_relations(object_person_id);"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_person_relations_type ON person_relations(relation_type_id);"
    )

    db.execute("PRAGMA user_version = 43")
    db.commit()
    db.execute("PRAGMA foreign_keys = ON;")


def run_migration_v44(db: sqlite3.Connection) -> None:
    """Run migration for version 44 (Task Agent MVP tables + capability seed)."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS task_agent_tasks (
            task_id TEXT PRIMARY KEY,
            prompt_text TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN (
                'queued', 'planning', 'waiting_user', 'waiting_approval',
                'ready', 'running', 'waiting_reapproval', 'cancelling',
                'interrupted', 'completed', 'failed', 'cancelled'
            )),
            current_plan_id TEXT,
            worker_instance_id TEXT,
            active_child_kind TEXT,
            active_child_run_id TEXT,
            result_summary TEXT,
            error_summary TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT
        );
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS task_agent_plans (
            plan_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES task_agent_tasks(task_id) ON DELETE CASCADE,
            version INTEGER NOT NULL,
            plan_json TEXT NOT NULL,
            approval_policy_snapshot TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN (
                'pending', 'approved', 'rejected', 'superseded'
            )),
            rejection_reason TEXT,
            created_at TEXT NOT NULL,
            decided_at TEXT,
            UNIQUE (task_id, version)
        );
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS task_agent_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL REFERENCES task_agent_tasks(task_id) ON DELETE CASCADE,
            seq INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (task_id, seq)
        );
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS task_agent_capabilities (
            capability_key TEXT PRIMARY KEY,
            adapter_kind TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            approval_policy TEXT NOT NULL CHECK (approval_policy IN ('auto', 'plan_required')),
            updated_at TEXT NOT NULL
        );
    """)
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_task_agent_tasks_status "
        "ON task_agent_tasks(status);"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_task_agent_tasks_worker "
        "ON task_agent_tasks(worker_instance_id);"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_task_agent_tasks_finished "
        "ON task_agent_tasks(finished_at);"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_task_agent_plans_task "
        "ON task_agent_plans(task_id, version);"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_task_agent_events_task "
        "ON task_agent_events(task_id, seq);"
    )

    # Idempotent seed of the code-defined catalog. The DB owns only `enabled`
    # and `approval_policy`, so the seed never overwrites those two columns.
    now = datetime.now(timezone.utc).isoformat()
    for definition in get_capability_definitions():
        db.execute(
            """
            INSERT INTO task_agent_capabilities (
                capability_key, adapter_kind, enabled, approval_policy, updated_at
            ) VALUES (?, ?, 1, ?, ?)
            ON CONFLICT(capability_key) DO UPDATE SET
                adapter_kind=excluded.adapter_kind,
                updated_at=excluded.updated_at
            """,
            (
                definition.key,
                definition.adapter_kind,
                definition.default_approval_policy,
                now,
            ),
        )

    db.execute("PRAGMA user_version = 44")
    db.commit()


def run_migration_v18(conn: sqlite3.Connection) -> None:
    """Run migration for version 18 (line_webhook_events table for LINE Webhook foundation)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS line_webhook_events (
            event_id TEXT PRIMARY KEY,
            dedup_key TEXT UNIQUE NOT NULL,
            webhook_event_id TEXT,
            event_type TEXT,
            status TEXT NOT NULL,
            payload_json TEXT,
            delivery_count INTEGER NOT NULL DEFAULT 1,
            received_at TEXT NOT NULL,
            last_received_at TEXT NOT NULL
        );
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_line_webhook_received_at ON line_webhook_events(received_at);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_line_webhook_dedup_key ON line_webhook_events(dedup_key);"
    )
    conn.execute("PRAGMA user_version = 18;")
    conn.commit()


def run_migration_v19(conn: sqlite3.Connection) -> None:
    """Run migration for version 19 (task_state table for aggregated task status).

    Task state aggregates per-task status for high-frequency scheduled commands
    (e.g. minutely merge_inbox). Empty runs do not create command_runs rows;
    instead their outcome is folded into a single task_state row so the
    individual execution history is not flooded with no-op runs.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS task_state (
            task_id TEXT PRIMARY KEY,
            last_check_at TEXT NOT NULL,
            consecutive_empty_count INTEGER NOT NULL DEFAULT 0,
            last_processed_at TEXT,
            last_error_at TEXT,
            last_error_message TEXT,
            last_error_type TEXT,
            processed_count INTEGER NOT NULL DEFAULT 0,
            skipped_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        );
    """)
    conn.execute("PRAGMA user_version = 19;")
    conn.commit()


def run_migration_v21(conn: sqlite3.Connection) -> None:
    """Run migration for version 21 (AI agent tables: agents, agent_sessions, agent_messages, agent_runs)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agents (
            agent_id TEXT PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            system_prompt TEXT NOT NULL,
            provider TEXT,
            model TEXT,
            tool_ids_json TEXT NOT NULL DEFAULT '[]',
            advanced_params_json TEXT NOT NULL DEFAULT '{}',
            delegate_agent_ids_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_sessions (
            session_id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(agent_id) REFERENCES agents(agent_id) ON DELETE CASCADE
        );
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_messages (
            message_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES agent_sessions(session_id) ON DELETE CASCADE,
            UNIQUE(session_id, sequence)
        );
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_runs (
            run_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            user_message_id TEXT NOT NULL,
            assistant_message_id TEXT,
            status TEXT NOT NULL,
            used_tools_json TEXT NOT NULL DEFAULT '[]',
            created_hitl_run_ids_json TEXT NOT NULL DEFAULT '[]',
            error_message TEXT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            FOREIGN KEY(session_id) REFERENCES agent_sessions(session_id) ON DELETE CASCADE,
            FOREIGN KEY(user_message_id) REFERENCES agent_messages(message_id) ON DELETE CASCADE,
            FOREIGN KEY(assistant_message_id) REFERENCES agent_messages(message_id) ON DELETE CASCADE
        );
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_sessions_agent_id ON agent_sessions(agent_id);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_messages_session_seq ON agent_messages(session_id, sequence);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_runs_session_id ON agent_runs(session_id);"
    )

    conn.execute("PRAGMA user_version = 21;")
    conn.commit()


def run_migration_v22(conn: sqlite3.Connection) -> None:
    """Run migration for version 22 (agent_runs.tool_calls_json for detailed tool call history)."""
    try:
        conn.execute(
            "ALTER TABLE agent_runs ADD COLUMN tool_calls_json TEXT NOT NULL DEFAULT '[]';"
        )
    except sqlite3.OperationalError as e:
        _ignore_duplicate_schema_object(e)
    conn.execute("PRAGMA user_version = 22;")
    conn.commit()


def run_migration_v23(conn: sqlite3.Connection) -> None:
    """Run migration for version 23 (agent advanced params + prompt templates).

    - agents.advanced_params_json: JSON for max_tokens and reasoning.effort.
      Stored as {"max_tokens": int, "reasoning": {"effort": str}}.
      Single `max_tokens` value is mapped by LangChain to max_completion_tokens
      or max_output_tokens (Responses API) and to num_predict (Ollama).
    - agent_prompt_templates: per-agent named prompt snippets, inserted by
      replacing the chat input when selected. Phase 1 is plain text only;
      variable expansion is deferred to phase 2.
    """
    try:
        conn.execute(
            "ALTER TABLE agents ADD COLUMN advanced_params_json TEXT NOT NULL DEFAULT '{}';"
        )
    except sqlite3.OperationalError as e:
        _ignore_duplicate_schema_object(e)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_prompt_templates (
            template_id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            name TEXT NOT NULL,
            content TEXT NOT NULL,
            display_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(agent_id) REFERENCES agents(agent_id) ON DELETE CASCADE
        );
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_apt_agent_order ON agent_prompt_templates(agent_id, display_order);"
    )
    conn.execute("PRAGMA user_version = 23;")
    conn.commit()


def run_migration_v24(conn: sqlite3.Connection) -> None:
    """Run migration for version 24 (agent_messages.attachments_json for multimodal chat).

    Stores user-uploaded image attachments as a JSON array of
    ``{"name": str, "mime_type": str, "data": str (base64 data URL body)}``
    records so they can be replayed to the LLM in subsequent turns and shown
    back to the user in the chat history. Empty list ``'[]'`` means no images.
    Mirrors the additive patterns used for ``agent_runs.tool_calls_json``
    (v22) and ``agents.advanced_params_json`` (v23).
    """
    try:
        conn.execute(
            "ALTER TABLE agent_messages ADD COLUMN attachments_json TEXT NOT NULL DEFAULT '[]';"
        )
    except sqlite3.OperationalError as e:
        _ignore_duplicate_schema_object(e)
    conn.execute("PRAGMA user_version = 24;")
    conn.commit()


def run_migration_v25(conn: sqlite3.Connection) -> None:
    """Run migration for version 25 (agents/agents_sessions pinned_at).

    Adds ``pinned_at TEXT`` (ISO-8601, nullable) to both tables. Null means
    unpinned; a timestamp means pinned. Used to sort pinned items first
    (pinned_at DESC) in list queries.
    """
    try:
        conn.execute("ALTER TABLE agents ADD COLUMN pinned_at TEXT;")
    except sqlite3.OperationalError as e:
        _ignore_duplicate_schema_object(e)
    try:
        conn.execute("ALTER TABLE agent_sessions ADD COLUMN pinned_at TEXT;")
    except sqlite3.OperationalError as e:
        _ignore_duplicate_schema_object(e)
    conn.execute("PRAGMA user_version = 25;")
    conn.commit()


def run_migration_v26(conn: sqlite3.Connection) -> None:
    """Run migration for version 26 (agent_sessions title_is_edited flag).

    Adds ``title_is_edited INTEGER NOT NULL DEFAULT 0`` to ``agent_sessions``.
    Flag is set to 1 when a user explicitly edits the title, preventing subsequent
    auto-title generations from overwriting the user-chosen title.
    """
    try:
        conn.execute(
            "ALTER TABLE agent_sessions ADD COLUMN title_is_edited INTEGER NOT NULL DEFAULT 0;"
        )
    except sqlite3.OperationalError as e:
        _ignore_duplicate_schema_object(e)
    conn.execute("PRAGMA user_version = 26;")
    conn.commit()


def run_migration_v27(conn: sqlite3.Connection) -> None:
    """Run migration for version 27 (Dedicated coding workspace: coding_sessions, coding_messages, coding_runs)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS coding_sessions (
            session_id TEXT PRIMARY KEY,
            project_id INTEGER NOT NULL,
            backend TEXT NOT NULL,
            repo_path TEXT NOT NULL,
            external_session_id TEXT,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(project_id) ON DELETE CASCADE
        );
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS coding_messages (
            message_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES coding_sessions(session_id) ON DELETE CASCADE,
            UNIQUE(session_id, sequence)
        );
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS coding_runs (
            run_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            user_message_id TEXT NOT NULL,
            orchestrator_message_id TEXT,
            worker_message_id TEXT,
            status TEXT NOT NULL,
            dirty_tree_at_start TEXT,
            error_message TEXT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            FOREIGN KEY(session_id) REFERENCES coding_sessions(session_id) ON DELETE CASCADE,
            FOREIGN KEY(user_message_id) REFERENCES coding_messages(message_id) ON DELETE CASCADE,
            FOREIGN KEY(orchestrator_message_id) REFERENCES coding_messages(message_id) ON DELETE CASCADE,
            FOREIGN KEY(worker_message_id) REFERENCES coding_messages(message_id) ON DELETE CASCADE
        );
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_coding_sessions_project_id ON coding_sessions(project_id);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_coding_messages_session_seq ON coding_messages(session_id, sequence);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_coding_runs_session_id ON coding_runs(session_id);"
    )

    conn.execute("PRAGMA user_version = 27;")
    conn.commit()


def run_migration_v28(conn: sqlite3.Connection) -> None:
    """Run migration for version 28 (coding_sessions.tool_ids_json and coding_settings table)."""
    try:
        conn.execute("ALTER TABLE coding_sessions ADD COLUMN tool_ids_json TEXT;")
    except sqlite3.OperationalError as e:
        _ignore_duplicate_schema_object(e)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS coding_settings (
            setting_key TEXT PRIMARY KEY,
            setting_value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)

    conn.execute("PRAGMA user_version = 28;")
    conn.commit()


def run_migration_v29(conn: sqlite3.Connection) -> None:
    """Run migration for version 29 (coding_runs.diagnostics_json TEXT column)."""
    try:
        conn.execute("ALTER TABLE coding_runs ADD COLUMN diagnostics_json TEXT;")
    except sqlite3.OperationalError as e:
        _ignore_duplicate_schema_object(e)

    conn.execute("PRAGMA user_version = 29;")
    conn.commit()


def run_migration_v31(conn: sqlite3.Connection) -> None:
    """Run migration for version 31 (agents.delegate_agent_ids_json for subagent delegation)."""
    try:
        conn.execute(
            "ALTER TABLE agents ADD COLUMN delegate_agent_ids_json TEXT NOT NULL DEFAULT '[]';"
        )
    except sqlite3.OperationalError as e:
        _ignore_duplicate_schema_object(e)
    conn.execute("PRAGMA user_version = 31;")
    conn.commit()


def run_migration_v32(conn: sqlite3.Connection) -> None:
    """Run migration for version 32 (coding_orchestrator_tool_calls table for Coding Orchestrator tool history)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS coding_orchestrator_tool_calls (
            call_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            phase TEXT NOT NULL,
            phase_turn INTEGER NOT NULL,
            iteration INTEGER NOT NULL,
            call_index INTEGER NOT NULL,
            call_key TEXT NOT NULL,
            orchestrator_message_id TEXT,
            tool_name TEXT NOT NULL,
            args_json TEXT NOT NULL,
            result TEXT,
            status TEXT NOT NULL,
            error TEXT,
            provider_call_id TEXT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            FOREIGN KEY(run_id) REFERENCES coding_runs(run_id) ON DELETE CASCADE,
            FOREIGN KEY(orchestrator_message_id) REFERENCES coding_messages(message_id) ON DELETE SET NULL
        );
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_cotc_run_id ON coding_orchestrator_tool_calls(run_id);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_cotc_message_id ON coding_orchestrator_tool_calls(orchestrator_message_id);"
    )
    conn.execute("PRAGMA user_version = 32;")
    conn.commit()


def run_migration_v33(conn: sqlite3.Connection) -> None:
    """Run migration for version 33 (hitl_run_id column in agent_runs and coding_runs)."""
    try:
        conn.execute("ALTER TABLE agent_runs ADD COLUMN hitl_run_id TEXT REFERENCES hitl_runs(run_id) ON DELETE SET NULL;")
    except sqlite3.OperationalError as e:
        _ignore_duplicate_schema_object(e)

    try:
        conn.execute("ALTER TABLE coding_runs ADD COLUMN hitl_run_id TEXT REFERENCES hitl_runs(run_id) ON DELETE SET NULL;")
    except sqlite3.OperationalError as e:
        _ignore_duplicate_schema_object(e)

    conn.execute("PRAGMA user_version = 33;")
    conn.commit()


def run_migration_v34(conn: sqlite3.Connection) -> None:
    """Run migration for version 34 (reconnectable run execution + SSE event log).

    - Adds ownership/idempotency columns to agent_runs and coding_runs:
      idempotency_key, idempotency_hash, created_instance_id, worker_instance_id.
    - Adds agent_run_events / coding_run_events tables with AUTOINCREMENT
      event_id cursor, run_id FK, event_type, payload_json, created_at.
    - Adds run-scoped cursor index and session-scoped idempotency partial
      unique index.
    """
    for table in ("agent_runs", "coding_runs"):
        for column in (
            "idempotency_key TEXT",
            "idempotency_hash TEXT",
            "created_instance_id TEXT",
            "worker_instance_id TEXT",
        ):
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column};")
            except sqlite3.OperationalError as e:
                _ignore_duplicate_schema_object(e)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_run_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(run_id) REFERENCES agent_runs(run_id) ON DELETE CASCADE
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS coding_run_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(run_id) REFERENCES coding_runs(run_id) ON DELETE CASCADE
        );
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_run_events_run "
        "ON agent_run_events(run_id, event_id);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_coding_run_events_run "
        "ON coding_run_events(run_id, event_id);"
    )
    # Session-scoped idempotency: same key resend returns first run.
    # Partial unique index keeps legacy NULL rows unrestricted.
    try:
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_runs_session_idem "
            "ON agent_runs(session_id, idempotency_key) "
            "WHERE idempotency_key IS NOT NULL;"
        )
    except sqlite3.OperationalError as e:
        _ignore_duplicate_schema_object(e)
    try:
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_coding_runs_session_idem "
            "ON coding_runs(session_id, idempotency_key) "
            "WHERE idempotency_key IS NOT NULL;"
        )
    except sqlite3.OperationalError as e:
        _ignore_duplicate_schema_object(e)
    conn.execute("PRAGMA user_version = 34;")
    conn.commit()


def _quote_list(values: tuple[str, ...]) -> str:
    return ",".join(f"'{v}'" for v in values)


def run_migration_v35(conn: sqlite3.Connection) -> None:
    """Run migration for version 35 (single active run per session).

    Enforces the plan's session active-run invariant atomically with partial
    unique indexes, closing the SELECT-then-INSERT race for concurrent
    POST /runs with different idempotency keys. Pre-existing duplicates are
    interrupted (newest non-terminal kept) before the index is created.
    Partial-index predicates inline literals (SQLite forbids bound params).
    """
    for table, terminal in (
        ("agent_runs", ("succeeded", "failed", "cancelled", "interrupted")),
        ("coding_runs", ("completed", "failed", "cancelled", "interrupted")),
    ):
        quoted = _quote_list(terminal)
        try:
            # Keep newest non-terminal per session; interrupt the rest.
            conn.execute(
                f"""
                UPDATE {table} SET status = 'interrupted',
                    error_message = COALESCE(error_message, 'Interrupted (duplicate active run)'),
                    finished_at = COALESCE(finished_at, datetime('now'))
                WHERE rowid IN (
                    SELECT rowid FROM (
                        SELECT rowid,
                            ROW_NUMBER() OVER (
                                PARTITION BY session_id ORDER BY started_at DESC, rowid DESC
                            ) AS rn
                        FROM {table}
                        WHERE status NOT IN ({quoted})
                    ) WHERE rn > 1
                );
                """
            )
        except sqlite3.OperationalError as e:
            # Older SQLite without window functions: fall back to index attempt;
            # app-level guard still applies for personal single-process use.
            if "no such function" not in str(e).lower() and "near" not in str(e):
                raise
        try:
            conn.execute(
                f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{table}_single_active "
                f"ON {table}(session_id) "
                f"WHERE status NOT IN ({quoted});"
            )
        except sqlite3.OperationalError as e:
            _ignore_duplicate_schema_object(e)
    conn.execute("PRAGMA user_version = 35;")
    conn.commit()


def run_migration_v30(conn: sqlite3.Connection) -> None:
    """Run migration for version 30 (P1-2 worker message orphan fix).

    - Adds coding_messages.run_id (nullable FK) to link each message to its run.
    - Creates junction table coding_run_worker_messages for ordered history
      when multiple worker messages belong to one run (previously only last was kept
      via coding_runs.worker_message_id). Dual-write ensures backward compatibility:
      existing code reading worker_message_id still sees last message, while
      new code can list all via run_id.
    """
    try:
        conn.execute(
            "ALTER TABLE coding_messages ADD COLUMN run_id TEXT REFERENCES coding_runs(run_id) ON DELETE SET NULL;"
        )
    except sqlite3.OperationalError as e:
        _ignore_duplicate_schema_object(e)
    try:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_coding_messages_run_id ON coding_messages(run_id);"
        )
    except sqlite3.OperationalError as e:
        _ignore_duplicate_schema_object(e)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS coding_run_worker_messages (
            run_id TEXT NOT NULL,
            message_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
            PRIMARY KEY (run_id, message_id),
            FOREIGN KEY(run_id) REFERENCES coding_runs(run_id) ON DELETE CASCADE,
            FOREIGN KEY(message_id) REFERENCES coding_messages(message_id) ON DELETE CASCADE
        );
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_crw_run_seq ON coding_run_worker_messages(run_id, seq);"
    )
    conn.execute("PRAGMA user_version = 30;")
    conn.commit()


def run_migration_v20(conn: sqlite3.Connection) -> None:
    """Run migration for version 20 (planner_proposals table for AI planner proposals).

    AI proposals are low-to-medium confidence candidates ("you might want to
    schedule/remind this") generated from the app's full context. They are the
    source of truth for the Planner screen's AI proposal layer and never touch
    the existing Inbox -> HITL -> Apple registration flow.

    State machine: proposed -> promoted | rejected | expired.
    The fingerprint partial unique index prevents duplicate active candidates
    (proposed/promoted) while allowing a fresh proposal once a previous one is
    rejected or expired.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS planner_proposals (
            proposal_id       TEXT PRIMARY KEY,
            kind              TEXT NOT NULL,   -- 'calendar' | 'reminder'
            title             TEXT NOT NULL,
            start_time        TEXT,            -- ISO datetime (calendar)
            end_time          TEXT,            -- ISO datetime (calendar)
            location          TEXT,            -- (calendar)
            due_date          TEXT,            -- ISO datetime or YYYY-MM-DD (reminder)
            rationale         TEXT NOT NULL,   -- required generation rationale
            generation_source TEXT NOT NULL,   -- e.g. 'daily_06:00'
            status            TEXT NOT NULL,   -- proposed | promoted | rejected | expired
            fingerprint       TEXT NOT NULL,
            external_result   TEXT,            -- Apple write result on promotion
            created_at        TEXT NOT NULL,
            updated_at        TEXT NOT NULL,
            expired_at        TEXT,
            promoted_at       TEXT,
            rejected_at       TEXT
        );
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pp_status ON planner_proposals(status);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pp_created_at ON planner_proposals(created_at);"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_pp_active_fingerprint "
        "ON planner_proposals(fingerprint) WHERE status IN ('proposed', 'promoted');"
    )
    conn.execute("PRAGMA user_version = 20;")
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
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_hitl_runs_status ON hitl_runs(status);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_hitl_questions_run_set ON hitl_questions(run_id, question_set_id);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_hitl_questions_status ON hitl_questions(status);"
    )
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
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_command_runs_status_started ON command_runs(status, started_at DESC);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_llm_call_logs_status_started ON llm_call_logs(status, started_at DESC);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_llm_call_logs_run_id_started ON llm_call_logs(run_id, started_at);"
    )
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
    conn.execute("ALTER TABLE summary_projects ADD COLUMN note TEXT;")
    conn.execute("PRAGMA user_version = 12;")
    conn.commit()
