import json
import sqlite3
from datetime import datetime
from typing import Optional

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.web import schemas


class ProjectConflictError(ValueError):
    def __init__(self, message="Conflict: A project with this name already exists."):
        super().__init__(message)


# --- Project Management Services ---

def deserialize_project(row: dict | sqlite3.Row) -> dict:
    p = dict(row)
    kw = p.get("keywords")
    if isinstance(kw, str):
        try:
            p["keywords"] = json.loads(kw)
        except Exception:
            p["keywords"] = []
    elif not isinstance(kw, list):
        p["keywords"] = []
    return p


def deserialize_candidate(row: dict | sqlite3.Row) -> dict:
    c = dict(row)
    kw = c.get("keywords")
    if isinstance(kw, str):
        try:
            c["keywords"] = json.loads(kw)
        except Exception:
            c["keywords"] = []
    elif not isinstance(kw, list):
        c["keywords"] = []
    return c


def list_projects(
    domain: Optional[str] = None,
    status: Optional[str] = None,
) -> list[dict]:
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        sql = """
            SELECT p.*, COUNT(sp.summary_id) AS summary_count
            FROM projects p
            LEFT JOIN summary_projects sp ON p.project_id = sp.project_id
            WHERE 1=1
        """
        params = []
        if domain:
            sql += " AND p.domain = ?"
            params.append(domain)
        if status:
            sql += " AND p.status = ?"
            params.append(status)

        sql += """
            GROUP BY p.project_id
            ORDER BY summary_count DESC, p.updated_at DESC
        """
        cursor.execute(sql, params)
        return [deserialize_project(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def create_project(body: schemas.ProjectCreateRequest) -> dict:
    from obsidian_ai_hub.summary.store import normalize_entity_name

    display_name = body.display_name.strip()
    if not display_name:
        raise ValueError("Project name cannot be empty")
    norm_name = normalize_entity_name(display_name)

    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            # Conflict check
            cursor.execute("SELECT project_id FROM projects WHERE normalized_name = ?", (norm_name,))
            if cursor.fetchone() is not None:
                raise ProjectConflictError()

            now_iso = datetime.now().isoformat()
            cursor.execute("""
                INSERT INTO projects (
                    normalized_name, display_name, domain, status, goal, description,
                    keywords, start_date, target_date, completed_date, project_path,
                    reference_url, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                norm_name, display_name, body.domain, body.status, body.goal, body.description,
                json.dumps(body.keywords, ensure_ascii=False), body.start_date, body.target_date,
                body.completed_date, body.project_path, body.reference_url, now_iso, now_iso
            ))
            project_id = cursor.lastrowid

        return get_project_detail(project_id)
    finally:
        conn.close()


def get_project_detail(project_id: int) -> Optional[dict]:
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM projects WHERE project_id = ?", (project_id,))
        row = cursor.fetchone()
        if row is None:
            return None
        p = deserialize_project(row)

        cursor.execute("""
            SELECT s.summary_id, s.period_type, s.period_key, sp.note, sp.display_order
            FROM summary_projects sp
            JOIN summaries s ON sp.summary_id = s.summary_id
            WHERE sp.project_id = ?
            ORDER BY s.period_start DESC, s.period_key DESC
        """, (project_id,))
        p["summaries"] = [dict(r) for r in cursor.fetchall()]
        p["summary_count"] = len(p["summaries"])
        return p
    finally:
        conn.close()


def update_project(project_id: int, body: schemas.ProjectUpdateRequest) -> dict:
    from obsidian_ai_hub.summary.store import normalize_entity_name

    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM projects WHERE project_id = ?", (project_id,))
            row = cursor.fetchone()
            if row is None:
                raise FileNotFoundError("Project not found")

            updates = []
            params = []

            if body.display_name is not None:
                display_name = body.display_name.strip()
                if not display_name:
                    raise ValueError("Project name cannot be empty")
                norm_name = normalize_entity_name(display_name)
                # Conflict check
                cursor.execute("SELECT project_id FROM projects WHERE normalized_name = ? AND project_id != ?", (norm_name, project_id))
                if cursor.fetchone() is not None:
                    raise ProjectConflictError()
                updates.append("display_name = ?")
                params.append(display_name)
                updates.append("normalized_name = ?")
                params.append(norm_name)

            if body.domain is not None:
                updates.append("domain = ?")
                params.append(body.domain)

            if body.status is not None:
                updates.append("status = ?")
                params.append(body.status)

            if body.goal is not None:
                updates.append("goal = ?")
                params.append(body.goal)

            if body.description is not None:
                updates.append("description = ?")
                params.append(body.description)

            if body.keywords is not None:
                updates.append("keywords = ?")
                params.append(json.dumps(body.keywords, ensure_ascii=False))

            if body.start_date is not None:
                updates.append("start_date = ?")
                params.append(body.start_date)

            if body.target_date is not None:
                updates.append("target_date = ?")
                params.append(body.target_date)

            if body.completed_date is not None:
                updates.append("completed_date = ?")
                params.append(body.completed_date)

            if body.project_path is not None:
                updates.append("project_path = ?")
                params.append(body.project_path)

            if body.reference_url is not None:
                updates.append("reference_url = ?")
                params.append(body.reference_url)

            if updates:
                now_iso = datetime.now().isoformat()
                updates.append("updated_at = ?")
                params.append(now_iso)

                sql = f"UPDATE projects SET {', '.join(updates)} WHERE project_id = ?"
                params.append(project_id)
                cursor.execute(sql, tuple(params))

        return get_project_detail(project_id)
    finally:
        conn.close()


def list_project_candidates(status: Optional[str] = "unresolved") -> list[dict]:
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        sql = "SELECT * FROM project_candidates WHERE 1=1"
        params = []
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC"
        cursor.execute(sql, params)
        return [deserialize_candidate(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def get_project_candidate_detail(candidate_id: int) -> Optional[dict]:
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM project_candidates WHERE candidate_id = ?", (candidate_id,))
        row = cursor.fetchone()
        if row is None:
            return None
        c = deserialize_candidate(row)

        cursor.execute("""
            SELECT s.summary_id, s.period_type, s.period_key
            FROM summary_project_candidates spc
            JOIN summaries s ON spc.summary_id = s.summary_id
            WHERE spc.candidate_id = ?
            ORDER BY s.period_start DESC, s.period_key DESC
        """, (candidate_id,))
        c["summaries"] = [dict(r) for r in cursor.fetchall()]
        c["assigned_summaries_count"] = len(c["summaries"])
        return c
    finally:
        conn.close()


def resolve_project_candidate(
    candidate_id: int,
    body: schemas.ProjectCandidateResolveRequest,
) -> dict:
    from obsidian_ai_hub.summary.store import normalize_entity_name

    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM project_candidates WHERE candidate_id = ?", (candidate_id,))
            row = cursor.fetchone()
            if row is None:
                raise FileNotFoundError("Candidate not found")

            c = deserialize_candidate(row)

            # 1. Reject action
            if body.action == "reject":
                conn.execute("UPDATE project_candidates SET status = 'rejected', updated_at = ? WHERE candidate_id = ?", (datetime.now().isoformat(), candidate_id))
                conn.execute("DELETE FROM summary_project_candidates WHERE candidate_id = ?", (candidate_id,))

            # 2. Reopen rejected action
            elif body.action == "reopen_rejected":
                conn.execute("UPDATE project_candidates SET status = 'unresolved', updated_at = ? WHERE candidate_id = ?", (datetime.now().isoformat(), candidate_id))

            # 3. Approve new action
            elif body.action == "approve_new":
                display_name = body.display_name.strip() if body.display_name is not None else c["display_name"]
                if not display_name:
                    raise ValueError("Project name cannot be empty")
                norm_name = normalize_entity_name(display_name)

                # Conflict check
                cursor.execute("SELECT project_id FROM projects WHERE normalized_name = ?", (norm_name,))
                if cursor.fetchone() is not None:
                    raise ProjectConflictError()

                domain = body.domain if body.domain is not None else c["domain"]
                status = body.status if body.status is not None else "inquiry"
                goal = body.goal if body.goal is not None else c["goal"]
                description = body.description if body.description is not None else c["description"]
                keywords = body.keywords if body.keywords is not None else c["keywords"]
                start_date = body.start_date if body.start_date is not None else c["start_date"]
                target_date = body.target_date if body.target_date is not None else c["target_date"]
                completed_date = body.completed_date if body.completed_date is not None else c["completed_date"]
                project_path = body.project_path if body.project_path is not None else c.get("project_path")
                reference_url = body.reference_url if body.reference_url is not None else c.get("reference_url")

                now_iso = datetime.now().isoformat()
                cursor.execute("""
                    INSERT INTO projects (
                        normalized_name, display_name, domain, status, goal, description,
                        keywords, start_date, target_date, completed_date, project_path,
                        reference_url, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    norm_name, display_name, domain, status, goal, description,
                    json.dumps(keywords, ensure_ascii=False), start_date, target_date,
                    completed_date, project_path, reference_url, now_iso, now_iso
                ))
                project_id = cursor.lastrowid

                # Migrate all summary links to summary_projects
                cursor.execute("SELECT summary_id, display_order FROM summary_project_candidates WHERE candidate_id = ?", (candidate_id,))
                links = cursor.fetchall()
                for link in links:
                    conn.execute("""
                        INSERT OR IGNORE INTO summary_projects (summary_id, project_id, display_order)
                        VALUES (?, ?, ?)
                    """, (link["summary_id"], project_id, link["display_order"]))

                # Clean up candidate summary links
                conn.execute("DELETE FROM summary_project_candidates WHERE candidate_id = ?", (candidate_id,))
                # Set candidate resolved
                conn.execute("UPDATE project_candidates SET status = 'resolved', updated_at = ? WHERE candidate_id = ?", (now_iso, candidate_id))

            # 4. Link existing action
            elif body.action == "link_existing":
                project_id = body.target_project_id
                if project_id is None:
                    raise ValueError("target_project_id is required for link_existing")

                cursor.execute("SELECT project_id FROM projects WHERE project_id = ?", (project_id,))
                if cursor.fetchone() is None:
                    raise ValueError("Target project not found")

                now_iso = datetime.now().isoformat()
                # Migrate all summary links to summary_projects
                cursor.execute("SELECT summary_id, display_order FROM summary_project_candidates WHERE candidate_id = ?", (candidate_id,))
                links = cursor.fetchall()
                for link in links:
                    conn.execute("""
                        INSERT OR IGNORE INTO summary_projects (summary_id, project_id, display_order)
                        VALUES (?, ?, ?)
                    """, (link["summary_id"], project_id, link["display_order"]))

                # Clean up candidate summary links
                conn.execute("DELETE FROM summary_project_candidates WHERE candidate_id = ?", (candidate_id,))
                # Set candidate resolved
                conn.execute("UPDATE project_candidates SET status = 'resolved', updated_at = ? WHERE candidate_id = ?", (now_iso, candidate_id))

        return {"success": True}
    finally:
        conn.close()
