"""Healthcare (Apple Health) package — separate DB from memory.sqlite3."""

from obsidian_ai_hub.healthcare.store import get_healthcare_db_connection

__all__ = ["get_healthcare_db_connection"]
