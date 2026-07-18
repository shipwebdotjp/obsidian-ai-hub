import sqlite3
import os

db_path = "memory.sqlite3"
if os.path.exists(db_path):
    os.remove(db_path)

conn = sqlite3.connect(db_path)
try:
    # Run setup schema by creating connection through obsidian_ai_hub.memory which triggers migrations
    os.environ["MEMORY_SQLITE_PATH"] = db_path
    os.environ["VAULT_PATH"] = "."
    from obsidian_ai_hub import memory
    memory.get_db_connection().close()
finally:
    conn.close()

# Reconnect to populate data
conn = sqlite3.connect(db_path)
cursor = conn.cursor()
try:
    # Populate people
    cursor.execute(
        "INSERT INTO people (person_id, display_name, normalized_name, vault_id) VALUES (?, ?, ?, ?)",
        ("peo_suzuki", "鈴木健", "鈴木健", "suzuki-ken")
    )
    cursor.execute(
        "INSERT INTO people (person_id, display_name, normalized_name, vault_id) VALUES (?, ?, ?, ?)",
        ("peo_sato", "佐藤太郎", "佐藤太郎", None)
    )

    # Populate candidates
    cursor.execute(
        "INSERT INTO person_candidates (candidate_id, display_name, normalized_name, status) VALUES (?, ?, ?, ?)",
        ("cand_yamada", "山田さん", "山田さん", "unresolved")
    )

    # Populate summaries
    cursor.execute(
        "INSERT INTO summaries (summary_id, period_type, period_key, period_start, period_end, summary) VALUES (?, ?, ?, ?, ?, ?)",
        ("sum_1", "day", "2026-08-01", "2026-08-01", "2026-08-01", "昨日の山田さんとの面談について")
    )
    cursor.execute(
        "INSERT INTO summaries (summary_id, period_type, period_key, period_start, period_end, summary) VALUES (?, ?, ?, ?, ?, ?)",
        ("sum_2", "day", "2026-08-02", "2026-08-02", "2026-08-02", "先週の山田さんの振り返りについて")
    )

    # Populate candidate summary links
    cursor.execute(
        "INSERT INTO summary_person_candidates (summary_id, candidate_id, note, display_order) VALUES (?, ?, ?, ?)",
        ("sum_1", "cand_yamada", "開発チームの山田さんから進捗共有を受けた。", 1)
    )
    cursor.execute(
        "INSERT INTO summary_person_candidates (summary_id, candidate_id, note, display_order) VALUES (?, ?, ?, ?)",
        ("sum_2", "cand_yamada", "こちらの山田さんは営業部の方。新規商談について。", 2)
    )

    conn.commit()
    print("Verification DB set up successfully!")
finally:
    conn.close()
