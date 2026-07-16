import pytest
from obsidian_ai_hub.utils import config


@pytest.fixture(autouse=True)
def _isolate_research_vault_dir(tmp_path, monkeypatch):
    vault_path = tmp_path / "vault"
    vault_path.mkdir()
    monkeypatch.setattr(config, "VAULT_PATH", vault_path)
    monkeypatch.setattr(config, "RESEARCH_OUTPUT_DIR", vault_path / "research")
