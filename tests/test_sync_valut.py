from __future__ import annotations

import pytest

from obsidian_ai_hub import sync_valut


def test_main_exits_on_config_mismatch(monkeypatch):
    class FakeConfigMismatchError(Exception):
        pass

    class FakeIndex:
        def sync(self):
            raise FakeConfigMismatchError("configuration mismatch")

    monkeypatch.setattr(sync_valut, "build_vault_search_index", lambda: FakeIndex())
    monkeypatch.setattr(
        sync_valut, "ConfigMismatchError", FakeConfigMismatchError, raising=False
    )

    with pytest.raises(SystemExit) as excinfo:
        sync_valut.main()

    assert excinfo.value.code == 1
