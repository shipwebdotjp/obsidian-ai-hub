import os
import sys
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = str(PROJECT_ROOT / "src")


def _run(
    script: str, extra_env: dict[str, str] | None = None, expect_error: bool = False
):
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
        "PYTHONPATH": SRC_DIR,
    }
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        text=True,
    )
    if expect_error:
        assert result.returncode != 0, (
            f"Expected non-zero return, got {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    else:
        assert result.returncode == 0, (
            f"Expected zero return, got {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result.stdout.strip(), result.stderr.strip()


class TestIsolation:
    def test_is_test_env_and_config_yml_path(self):
        """ENV=test → IS_TEST_ENV==True, CONFIG_YML_PATH ends with config.test.yml"""
        out, _ = _run(
            "from obsidian_ai_hub.utils import config; "
            "print(config.IS_TEST_ENV, config.CONFIG_YML_PATH)",
            extra_env={"ENV": "test", "OAIHUB_SKIP_DOTENV": "1"},
        )
        assert "True" in out
        assert out.endswith("config.test.yml")

    def test_vault_path_ignores_parent_env(self):
        """ENV=test VAULT_PATH=/prod → VAULT_PATH is under TEST_WORKSPACE"""
        out, _ = _run(
            "from obsidian_ai_hub.utils import config; print(config.VAULT_PATH)",
            extra_env={"ENV": "test", "VAULT_PATH": "/prod", "OAIHUB_SKIP_DOTENV": "1"},
        )
        assert out.startswith("/") or out.startswith("/private/")
        assert "/prod" not in out
        assert "obsidian-ai-hub-test-" in out
        assert out.endswith("/vault")

    def test_all_paths_under_test_workspace(self):
        """ENV=test → all paths share the same TEST_WORKSPACE"""
        out, _ = _run(
            "from obsidian_ai_hub.utils import config; "
            "print(config.VAULT_PATH, config.MEMORY_SQLITE_PATH, "
            "config.AI_LOG_PATH, config.VAULT_INDEX_SQLITE_PATH, "
            "config.VAULT_INDEX_CHROMA_PATH, config.ACTIVITY_PATH, "
            "config.TASK_RUN_STATE_PATH, config.KNOWLEDGE_SYNC_STATE_PATH)",
            extra_env={"ENV": "test", "OAIHUB_SKIP_DOTENV": "1"},
        )
        parts = out.split()
        assert len(parts) == 8
        ws = str(Path(parts[0]).parent)  # VAULT_PATH parent == TEST_WORKSPACE
        for p in parts:
            assert str(p).startswith(ws), f"{p} not under {ws}"

    def test_env_vars_deleted(self):
        """ENV=test → OPENAI_APIKEY, LINE_TOKEN, APPLE_CALENDAR_NAME are deleted"""
        out, _ = _run(
            "from obsidian_ai_hub.utils import config; "
            "import os; "
            "print(os.environ.get('OPENAI_API_KEY', 'DELETED'), "
            "os.environ.get('LINE_TOKEN', 'DELETED'), "
            "os.environ.get('APPLE_CALENDAR_NAME', 'DELETED'))",
            extra_env={
                "ENV": "test",
                "OAIHUB_SKIP_DOTENV": "1",
                "OPENAI_API_KEY": "should_be_deleted",
            },
        )
        assert out == "DELETED DELETED DELETED"

    def test_allow_external_default_false(self):
        """ENV=test → ALLOW_EXTERNAL_IN_TEST == False"""
        out, _ = _run(
            "from obsidian_ai_hub.utils import config; print(config.ALLOW_EXTERNAL_IN_TEST)",
            extra_env={"ENV": "test", "OAIHUB_SKIP_DOTENV": "1"},
        )
        assert "False" in out

    def test_allow_external_in_test_deleted(self):
        """ENV=test ALLOW_EXTERNAL_IN_TEST=1 (from parent) → still False"""
        out, _ = _run(
            "from obsidian_ai_hub.utils import config; print(config.ALLOW_EXTERNAL_IN_TEST)",
            extra_env={
                "ENV": "test",
                "ALLOW_EXTERNAL_IN_TEST": "1",
                "OAIHUB_SKIP_DOTENV": "1",
            },
        )
        assert "False" in out

    def test_load_tasks_empty(self):
        """ENV=test → load_tasks() returns empty list"""
        out, _ = _run(
            "from obsidian_ai_hub.utils import config; "
            "from obsidian_ai_hub import task_runner; "
            "print(task_runner.load_tasks())",
            extra_env={"ENV": "test", "OAIHUB_SKIP_DOTENV": "1"},
        )
        assert out == "[]"

    def test_no_env(self):
        """No ENV set → IS_TEST_ENV==False, CONFIG_YML_PATH is config.yml"""
        out, _ = _run(
            "from obsidian_ai_hub.utils import config; "
            "print(config.IS_TEST_ENV, config.CONFIG_YML_PATH)",
        )
        assert "False" in out
        assert out.endswith("config.yml")

    def test_send_line_push_blocked(self):
        """ENV=test → send_line_push() raises RuntimeError"""
        _, err = _run(
            "from obsidian_ai_hub.utils.line_messaging import send_line_push; "
            "send_line_push('t', 't', 't')",
            extra_env={"ENV": "test", "OAIHUB_SKIP_DOTENV": "1"},
            expect_error=True,
        )
        assert "RuntimeError" in err
        assert "External access blocked in test mode" in err
