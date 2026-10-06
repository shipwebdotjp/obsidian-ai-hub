from pathlib import Path
import pytest

from obsidian_ai_hub.utils import config as app_config
from obsidian_ai_hub.utils.config import (
    VaultRegistry,
    VaultValidationError,
    read_web_status,
    update_web_status,
    validate_vault_registry,
)


def test_vault_registry_validation_success(tmp_path: Path):
    main_dir = tmp_path / "main"
    blog_dir = tmp_path / "blog"
    ai_dir = tmp_path / "ai"
    main_dir.mkdir()
    blog_dir.mkdir()
    ai_dir.mkdir()

    raw_config = {
        "vaults": {
            "main": {
                "path": str(main_dir),
                "display_name": "Personal Main",
                "role": "primary",
                "ai_access": "read",
            },
            "blog": {
                "path": str(blog_dir),
                "display_name": "Hugo Blog",
                "ai_access": "write",
            },
            "ai": {
                "path": str(ai_dir),
                "display_name": "AI Workspace",
                "ai_access": "write",
            },
        },
        "primary_vault": {
            "inbox": "inbox",
            "daily": "daily",
        },
    }

    registry = validate_vault_registry(raw_config)
    assert isinstance(registry, VaultRegistry)
    assert len(registry.list_vaults()) == 3
    assert registry.get("main").path == main_dir.resolve()
    assert registry.get("main").role == "primary"
    assert registry.get("main").ai_access == "read"
    assert registry.get("blog").ai_access == "write"
    assert registry.get_primary().vault_id == "main"
    assert registry.primary_config.inbox == "inbox"


def test_vault_registry_validation_missing_vaults():
    with pytest.raises(VaultValidationError, match="Missing required 'vaults'"):
        validate_vault_registry({"some_other_key": 123})


def test_vault_registry_validation_missing_main(tmp_path: Path):
    blog_dir = tmp_path / "blog"
    blog_dir.mkdir()
    raw_config = {
        "vaults": {
            "blog": {
                "path": str(blog_dir),
                "display_name": "Blog",
                "role": "primary",
                "ai_access": "write",
            }
        }
    }
    with pytest.raises(VaultValidationError, match="Required vault 'main' is missing"):
        validate_vault_registry(raw_config)


def test_vault_registry_validation_main_not_primary(tmp_path: Path):
    main_dir = tmp_path / "main"
    main_dir.mkdir()
    raw_config = {
        "vaults": {
            "main": {
                "path": str(main_dir),
                "display_name": "Personal Main",
                "ai_access": "read",
            }
        }
    }
    with pytest.raises(VaultValidationError, match="Vault 'main' must have role: 'primary'"):
        validate_vault_registry(raw_config)


def test_vault_registry_validation_multiple_primaries(tmp_path: Path):
    main_dir = tmp_path / "main"
    blog_dir = tmp_path / "blog"
    main_dir.mkdir()
    blog_dir.mkdir()
    raw_config = {
        "vaults": {
            "main": {
                "path": str(main_dir),
                "display_name": "Personal Main",
                "role": "primary",
                "ai_access": "read",
            },
            "blog": {
                "path": str(blog_dir),
                "display_name": "Hugo Blog",
                "role": "primary",
                "ai_access": "write",
            },
        }
    }
    with pytest.raises(VaultValidationError, match="Exactly one vault must have role: 'primary'"):
        validate_vault_registry(raw_config)


def test_vault_registry_validation_nonexistent_path(tmp_path: Path):
    raw_config = {
        "vaults": {
            "main": {
                "path": str(tmp_path / "does_not_exist"),
                "display_name": "Personal Main",
                "role": "primary",
                "ai_access": "read",
            }
        }
    }
    with pytest.raises(VaultValidationError, match="path does not exist"):
        validate_vault_registry(raw_config)


def test_vault_registry_validation_invalid_ai_access(tmp_path: Path):
    main_dir = tmp_path / "main"
    main_dir.mkdir()
    raw_config = {
        "vaults": {
            "main": {
                "path": str(main_dir),
                "display_name": "Personal Main",
                "role": "primary",
                "ai_access": "admin",
            }
        }
    }
    with pytest.raises(VaultValidationError, match="invalid ai_access 'admin'"):
        validate_vault_registry(raw_config)


def test_vault_registry_validation_duplicate_paths(tmp_path: Path):
    main_dir = tmp_path / "main"
    main_dir.mkdir()
    raw_config = {
        "vaults": {
            "main": {
                "path": str(main_dir),
                "display_name": "Personal Main",
                "role": "primary",
                "ai_access": "read",
            },
            "blog": {
                "path": str(main_dir),
                "display_name": "Hugo Blog",
                "ai_access": "write",
            },
        }
    }
    with pytest.raises(VaultValidationError, match="share identical path"):
        validate_vault_registry(raw_config)


def test_vault_registry_validation_nested_paths(tmp_path: Path):
    main_dir = tmp_path / "main"
    nested_dir = main_dir / "subfolder"
    main_dir.mkdir()
    nested_dir.mkdir()
    raw_config = {
        "vaults": {
            "main": {
                "path": str(main_dir),
                "display_name": "Personal Main",
                "role": "primary",
                "ai_access": "read",
            },
            "blog": {
                "path": str(nested_dir),
                "display_name": "Nested Blog",
                "ai_access": "write",
            },
        }
    }
    with pytest.raises(VaultValidationError, match="are nested"):
        validate_vault_registry(raw_config)


def test_web_status_tracking():
    update_web_status("starting")
    status = read_web_status()
    assert status["status"] == "starting"
    assert status["error"] is None

    update_web_status("ready")
    status = read_web_status()
    assert status["status"] == "ready"
    assert status["error"] is None

    update_web_status("failed", error="Invalid config: main missing")
    status = read_web_status()
    assert status["status"] == "failed"
    assert status["error"] == "Invalid config: main missing"


def test_create_app_startup_validation(monkeypatch, tmp_path: Path):
    from obsidian_ai_hub.web.app import create_app

    # Test failure when config is invalid
    invalid_cfg = {
        "vaults": {
            "main": {
                "path": str(tmp_path / "nonexistent_vault_dir"),
                "display_name": "Main",
                "role": "primary",
                "ai_access": "read",
            }
        }
    }
    monkeypatch.setattr(app_config, "_load_yaml_config", lambda: invalid_cfg)
    with pytest.raises(RuntimeError, match="Vault Registry validation failed"):
        create_app(token="test-token")

    status = read_web_status()
    assert status["status"] == "failed"
    assert status["error"] is not None

    # Test success when config is valid
    main_dir = tmp_path / "main"
    main_dir.mkdir(parents=True, exist_ok=True)
    valid_cfg = {
        "vaults": {
            "main": {
                "path": str(main_dir),
                "display_name": "Personal Main",
                "role": "primary",
                "ai_access": "read",
            }
        }
    }
    monkeypatch.setattr(app_config, "_load_yaml_config", lambda: valid_cfg)
    app = create_app(token="test-token")
    assert app is not None
    status = read_web_status()
    assert status["status"] == "ready"
    assert status["error"] is None
