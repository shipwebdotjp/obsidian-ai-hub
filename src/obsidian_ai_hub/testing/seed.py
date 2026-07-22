"""Seed demo data for E2E tests and the exploration server.

All seed functions use the application persistence APIs (not raw SQL) so the
records have the same representation as production data.
"""

from obsidian_ai_hub.testing import ensure_test_mode
from obsidian_ai_hub.testing.factories import make_memory


def seed_memory_demo_data() -> None:
    """Insert a small set of Memory Review records for browser smoke tests."""
    ensure_test_mode()

    from obsidian_ai_hub import memory as mem_mod

    candidates = [
        make_memory(
            memory_id="demo-cand-1",
            content="定例ミーティングは毎週火曜日の10時から",
            kind="fact",
            topics=["仕事"],
            tags=["会議", "定期"],
        ),
        make_memory(
            memory_id="demo-cand-2",
            content="プロジェクトXは来月までに完了させる",
            kind="commitment",
            topics=["仕事"],
            tags=["プロジェクト", "期限"],
        ),
        make_memory(
            memory_id="demo-appr-1",
            status="approved",
            content="朝のルーティン：ストレッチ→読書→日記",
            kind="pattern",
            topics=["健康"],
            tags=["習慣"],
        ),
        make_memory(
            memory_id="demo-rej-1",
            status="rejected",
            content="これは古い情報です",
            kind="fact",
            topics=["その他"],
            tags=["旧情報"],
        ),
        make_memory(
            memory_id="demo-evidence-1",
            content="Reactを採用した理由はチームの習熟度が高いため",
            kind="decision_policy",
            topics=["開発"],
            tags=["React", "技術選定"],
            evidence=[
                {
                    "path": "daily/2026-07-01.md",
                    "quote": "Reactの方が学習コストが低いという意見で一致",
                    "observed_at": "2026-07-01T12:00:00+09:00",
                }
            ],
        ),
    ]

    existing = mem_mod.load_all_memories()
    mem_mod.save_all_memories(existing + candidates)
