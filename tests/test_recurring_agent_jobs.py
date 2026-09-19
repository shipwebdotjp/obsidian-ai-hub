"""Agent recurring-job operation-scenario contract tests.

Covers the irreversible-operation contract for Agent-managed recurring jobs
(YAML write + future OS command execution by ``job_runner``):

| Stage | Source of truth / ID | Persisted | On stop | Side effect |
| --- | --- | --- | --- | --- |
| Agent register | Pydantic args, trusted Agent context, active YAML | full YAML + `agent_source` + `last_run` arm | duplicate/invalid/context-missing is not stored | YAML write, future OS command |
| Agent toggle | `job_id`, `enabled`, trusted owner | same list, single entry changed | unowned/missing is not stored | none until runner cycle |
| Human PUT | Bearer full-list PUT vs current raw YAML | unknown metadata kept, source revoked on meaningful edit | stale revision returns 409 before any write | none |
| Runner | YAML + state | existing `job_runner` | shell-free launch, existing retry rules | OS command launch |

All tests use isolated YAML/state paths and a fake runner, so no production
data or real subprocess is touched.
"""

import json
from datetime import datetime

import pytest
import yaml

from obsidian_ai_hub import job_runner
from obsidian_ai_hub.scheduler_jobs import recurring
from obsidian_ai_hub.utils import config


@pytest.fixture
def isolated_jobs(monkeypatch, tmp_path):
    """Redirect every recurring path to a temp dir (single active file)."""
    job_file = tmp_path / "jobs.test.yml"
    state_file = tmp_path / "last_run.json"
    monkeypatch.setattr(recurring, "TEST_JOB_FILE", job_file)
    monkeypatch.setattr(recurring, "LOCAL_JOB_FILE", job_file)
    monkeypatch.setattr(recurring, "DEFAULT_JOB_FILE", job_file)
    monkeypatch.setattr(recurring, "STATE_FILE", state_file)
    monkeypatch.setattr(recurring, "LOCK_FILE", tmp_path / ".job-config.lock")
    monkeypatch.setattr(recurring, "RUNNER_LOCK_FILE", tmp_path / ".job-runner.lock")
    monkeypatch.setattr(config, "JOB_RUN_STATE_PATH", state_file)
    monkeypatch.setattr(config, "IS_TEST_ENV", True)
    return job_file, state_file


def _register_tool(ctx=None):
    from obsidian_ai_hub.agents import registry

    resolved = registry.resolve_tools_with_context(
        ["register_recurring_job"],
        ctx if ctx is not None else {"agent_id": "agent-1", "session_id": "s1", "run_id": "r1"},
    )
    return resolved[0]


def _toggle_tool(ctx=None):
    from obsidian_ai_hub.agents import registry

    resolved = registry.resolve_tools_with_context(
        ["set_recurring_job_enabled"],
        ctx if ctx is not None else {"agent_id": "agent-1"},
    )
    return resolved[0]


def _load(job_file):
    with open(job_file) as f:
        return yaml.safe_load(f)


def _freeze(monkeypatch, value):
    """Patch ``recurring.datetime`` so ``datetime.now()`` returns ``value``."""

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return value if tz is None else value.astimezone(tz)

    monkeypatch.setattr(recurring, "datetime", _Frozen)


def test_agent_register_runs_next_slot_then_owner_disables(isolated_jobs, monkeypatch):
    """Agent tool register -> next matching slot only -> owner disable stops it."""
    job_file, _ = isolated_jobs
    register = _register_tool()
    toggle = _toggle_tool()

    reg_now = datetime(2026, 9, 17, 10, 0, 30)
    _freeze(monkeypatch, reg_now)
    out = json.loads(
        register.invoke(
            {
                "job_id": "minutely_agent",
                "command": "printf agent",
                "schedule": {"type": "minutely", "second": 0},
            }
        )
    )
    assert out["job_id"] == "minutely_agent"
    assert out["enabled"] is True
    assert out["next_run"] is not None

    entry = _load(job_file)[0]
    assert entry["enabled"] is True
    assert entry["agent_source"]["agent_id"] == "agent-1"
    assert entry["agent_source"]["session_id"] == "s1"
    assert entry["agent_source"]["run_id"] == "r1"
    assert entry["agent_source"]["registered_at"].endswith("+00:00")
    assert recurring.load_state()["minutely_agent"] == reg_now

    ran = []
    monkeypatch.setattr(recurring, "run_command", lambda cmd: ran.append(cmd))

    # Registered at 10:00:30; the 10:00:00 slot is in the past -> no retro run.
    job_runner.run_cycle(now=datetime(2026, 9, 17, 10, 0, 45))
    assert ran == []

    # Next matching slot runs exactly once.
    job_runner.run_cycle(now=datetime(2026, 9, 17, 10, 1, 0))
    assert ran == ["printf agent"]

    # Owner disables it; state is not re-armed and the next slot does not run.
    state_before = recurring.load_state()["minutely_agent"]
    disabled = json.loads(toggle.invoke({"job_id": "minutely_agent", "enabled": False}))
    assert disabled["enabled"] is False
    assert recurring.load_state()["minutely_agent"] == state_before
    assert _load(job_file)[0]["enabled"] is False

    job_runner.run_cycle(now=datetime(2026, 9, 17, 10, 2, 0))
    assert ran == ["printf agent"]


def test_register_context_missing_is_rejected_without_write(isolated_jobs):
    job_file, _ = isolated_jobs
    recurring.atomic_write_yaml(job_file, [])

    tool = _register_tool(ctx={})
    out = json.loads(
        tool.invoke(
            {
                "job_id": "no_ctx",
                "command": "printf x",
                "schedule": {"type": "minutely"},
            }
        )
    )
    assert "error" in out
    assert _load(job_file) == []
    assert recurring.load_state() == {}


def test_register_duplicate_and_invalid_leave_yaml_unchanged(isolated_jobs):
    job_file, _ = isolated_jobs
    recurring.atomic_write_yaml(
        job_file,
        [
            {
                "id": "existing",
                "enabled": True,
                "schedule": {"type": "minutely"},
                "command": "printf existing",
                "note": "keep me",
            }
        ],
    )
    tool = _register_tool()

    dup = json.loads(
        tool.invoke(
            {
                "job_id": "existing",
                "command": "printf dup",
                "schedule": {"type": "minutely"},
            }
        )
    )
    assert "error" in dup

    bad_schedule = json.loads(
        tool.invoke(
            {
                "job_id": "bad_sched",
                "command": "printf x",
                "schedule": {"type": "minutely", "day": 5},
            }
        )
    )
    assert "error" in bad_schedule

    bad_command = json.loads(
        tool.invoke(
            {
                "job_id": "bad_cmd",
                "command": "echo 'unclosed",
                "schedule": {"type": "minutely"},
            }
        )
    )
    assert "error" in bad_command

    jobs = _load(job_file)
    assert [j["id"] for j in jobs] == ["existing"]
    assert jobs[0]["note"] == "keep me"


def test_tool_inputs_cannot_spoof_agent_source(isolated_jobs):
    tool = _register_tool(ctx={"agent_id": "agent-1"})
    with pytest.raises(Exception):
        tool.invoke(
            {
                "job_id": "spoof",
                "command": "printf x",
                "schedule": {"type": "minutely"},
                "agent_id": "evil",
            }
        )


def test_cron_spellings_pass_pydantic(isolated_jobs):
    job_file, _ = isolated_jobs
    tool = _register_tool()
    out = json.loads(
        tool.invoke(
            {
                "job_id": "cron",
                "command": "printf x",
                "schedule": {
                    "type": "daily",
                    "hour": "8-18/2",
                    "minute": [0, 30],
                    "second": "0",
                },
            }
        )
    )
    assert "error" not in out
    saved = _load(job_file)[0]
    assert saved["schedule"]["hour"] == "8-18/2"
    assert saved["schedule"]["minute"] == [0, 30]


def test_toggle_ownership_restrictions(isolated_jobs):
    job_file, _ = isolated_jobs
    recurring.atomic_write_yaml(
        job_file,
        [
            {
                "id": "manual",
                "enabled": True,
                "schedule": {"type": "minutely"},
                "command": "printf manual",
            },
            {
                "id": "owned",
                "enabled": True,
                "schedule": {"type": "minutely"},
                "command": "printf owned",
                "agent_source": {"agent_id": "agent-1"},
            },
            {
                "id": "corrupt",
                "enabled": True,
                "schedule": {"type": "minutely"},
                "command": "printf corrupt",
                "agent_source": "not-a-dict",
            },
            {
                "id": "other",
                "enabled": True,
                "schedule": {"type": "minutely"},
                "command": "printf other",
                "agent_source": {"agent_id": "agent-2"},
            },
        ],
    )

    # Another agent cannot toggle jobs it does not own.
    other = _toggle_tool(ctx={"agent_id": "agent-2"})
    assert "error" in json.loads(other.invoke({"job_id": "owned", "enabled": False}))
    assert "error" in json.loads(other.invoke({"job_id": "manual", "enabled": False}))
    assert "error" in json.loads(other.invoke({"job_id": "corrupt", "enabled": False}))
    assert "error" in json.loads(other.invoke({"job_id": "missing", "enabled": False}))

    # The owner can toggle its own job, including a currently corrupt-source job
    # is not owned by anyone.
    owner = _toggle_tool(ctx={"agent_id": "agent-1"})
    ok = json.loads(owner.invoke({"job_id": "owned", "enabled": False}))
    assert ok["enabled"] is False

    # No unauthorized entry was mutated.
    by_id = {j["id"]: j for j in _load(job_file)}
    assert by_id["manual"]["enabled"] is True
    assert by_id["corrupt"]["enabled"] is True
    assert by_id["other"]["enabled"] is True


def test_corrupt_source_treated_as_unowned_by_service(isolated_jobs):
    job_file, _ = isolated_jobs
    recurring.atomic_write_yaml(
        job_file,
        [
            {
                "id": "corrupt",
                "enabled": True,
                "schedule": {"type": "minutely"},
                "command": "printf x",
                "agent_source": {"session_id": "no-agent"},
            }
        ],
    )
    assert recurring.get_agent_source({"agent_source": {"session_id": "x"}}) is None
    assert not recurring.is_agent_owned_by({"agent_source": "x"}, "a")
    with pytest.raises(ValueError):
        recurring.set_recurring_job_enabled("corrupt", False, agent_id="a")
    assert _load(job_file)[0]["enabled"] is True


def test_agent_source_sanitizes_optional_types():
    # Wrong-typed optional fields would fail the API response schema and turn
    # the /jobs list into a 500, so they are rejected as "unowned" instead.
    assert recurring.get_agent_source(
        {"agent_source": {"agent_id": "a", "session_id": 123}}
    ) is None
    assert recurring.get_agent_source(
        {"agent_source": {"agent_id": "a", "registered_at": ["x"]}}
    ) is None
    assert recurring.get_agent_source(
        {"agent_source": {"agent_id": "a", "session_id": "s"}}
    ) == {
        "agent_id": "a",
        "session_id": "s",
        "run_id": None,
        "registered_at": None,
    }


def test_reenable_arms_only_on_transition(isolated_jobs):
    job_file, _ = isolated_jobs
    recurring.atomic_write_yaml(
        job_file,
        [
            {
                "id": "owned",
                "enabled": False,
                "schedule": {"type": "hourly", "minute": 0},
                "command": "printf x",
                "agent_source": {"agent_id": "a"},
            }
        ],
    )
    old_now = datetime(2026, 1, 1, 0, 0, 0)
    recurring.save_state({"owned": old_now})

    reenable_now = datetime(2026, 6, 1, 12, 0, 0)
    recurring.set_recurring_job_enabled("owned", True, agent_id="a", now=reenable_now)
    assert recurring.load_state()["owned"] == reenable_now

    again_now = datetime(2026, 6, 2, 12, 0, 0)
    recurring.set_recurring_job_enabled("owned", True, agent_id="a", now=again_now)
    # enabled -> enabled is a no-op for arming.
    assert recurring.load_state()["owned"] == reenable_now


def test_default_file_shadowed_to_local_preserving_all_jobs(isolated_jobs, monkeypatch, tmp_path):
    """Reading jobs.yml then registering must write the full list to local."""
    _, state_file = isolated_jobs
    local = tmp_path / "jobs.local.yml"
    default = tmp_path / "jobs.yml"
    monkeypatch.setattr(recurring, "LOCAL_JOB_FILE", local)
    monkeypatch.setattr(recurring, "DEFAULT_JOB_FILE", default)
    monkeypatch.setattr(recurring, "TEST_JOB_FILE", local)
    monkeypatch.setattr(config, "IS_TEST_ENV", False)

    recurring.atomic_write_yaml(
        default,
        [
            {
                "id": "d1",
                "enabled": True,
                "schedule": {"type": "minutely"},
                "command": "printf d1",
                "custom": {"keep": True},
            },
            {
                "id": "d2",
                "enabled": False,
                "schedule": {"type": "hourly", "minute": 0},
                "command": "printf d2",
            },
        ],
    )
    old_now = datetime(2026, 1, 1, 0, 0, 0)
    recurring.save_state({"d1": old_now, "d2": old_now})

    recurring.register_recurring_job(
        "new",
        "printf new",
        {"type": "minutely"},
        agent_id="a",
    )

    saved = _load(local)
    assert [j["id"] for j in saved] == ["d1", "d2", "new"]
    assert saved[0]["custom"] == {"keep": True}
    state = recurring.load_state()
    assert state["d1"] == old_now
    assert state["d2"] == old_now
    assert "new" in state


def test_merge_preserves_unknown_and_revokes_on_meaning_change():
    current = [
        {
            "id": "agent_job",
            "enabled": True,
            "schedule": {"type": "minutely", "second": 0},
            "command": "printf old",
            "note": "hand written",
            "agent_source": {"agent_id": "a", "session_id": "s"},
        },
        {
            "id": "manual",
            "enabled": True,
            "schedule": {"type": "minutely"},
            "command": "printf manual",
            "note": "keep",
        },
    ]

    # Reorder + same values: metadata and ownership survive.
    reordered = [
        {
            "id": "manual",
            "enabled": True,
            "schedule": {"type": "minutely"},
            "command": "printf manual",
        },
        {
            "id": "agent_job",
            "enabled": True,
            "schedule": {"type": "minutely", "second": 0},
            "command": "printf old",
        },
    ]
    merged = recurring.merge_recurring_jobs(current, reordered)
    by_id = {j["id"]: j for j in merged}
    assert by_id["agent_job"]["agent_source"]["agent_id"] == "a"
    assert by_id["agent_job"]["note"] == "hand written"
    assert by_id["manual"]["note"] == "keep"

    # Meaningful edit (command) revokes ownership but keeps other metadata.
    edited = [dict(reordered[0]), dict(reordered[1], command="printf new")]
    merged = recurring.merge_recurring_jobs(current, edited)
    agent_job = next(j for j in merged if j["id"] == "agent_job")
    assert "agent_source" not in agent_job
    assert agent_job["note"] == "hand written"

    # Client-supplied agent_source is never trusted.
    injected = [
        {
            "id": "manual",
            "enabled": True,
            "schedule": {"type": "minutely"},
            "command": "printf manual",
            "agent_source": {"agent_id": "evil"},
        }
    ]
    merged = recurring.merge_recurring_jobs(current, injected)
    assert "agent_source" not in merged[0]

    # New entries cannot self-assign an owner.
    new_entry = [
        {
            "id": "brand_new",
            "enabled": True,
            "schedule": {"type": "minutely"},
            "command": "printf n",
            "agent_source": {"agent_id": "evil"},
        }
    ]
    merged = recurring.merge_recurring_jobs(current, new_entry)
    assert "agent_source" not in merged[0]


def test_task_capability_boundary():
    from obsidian_ai_hub.tasks.capabilities import (
        EXCLUDED_TOOL_IDS,
        get_capability_definitions,
    )
    from obsidian_ai_hub.tasks.adapters.registry_tools import TASK_CONTEXT_TOOL_IDS

    caps = {d.key: d for d in get_capability_definitions()}
    assert caps["register_recurring_job"].default_approval_policy == "plan_required"
    assert "set_recurring_job_enabled" not in caps
    assert "set_recurring_job_enabled" in EXCLUDED_TOOL_IDS
    assert "register_recurring_job" in TASK_CONTEXT_TOOL_IDS
    assert "set_recurring_job_enabled" not in TASK_CONTEXT_TOOL_IDS


def test_capability_schema_derives_cron_fields():
    from obsidian_ai_hub.tasks.capability_schemas import (
        resolve_json_schema,
        validate_capability_inputs,
    )

    schema = resolve_json_schema("register_recurring_job")
    assert "job_id" in schema["properties"]
    assert "schedule" in schema["properties"]
    validated = validate_capability_inputs(
        "register_recurring_job",
        {
            "job_id": "j",
            "command": "printf x",
            "schedule": {"type": "daily", "hour": "*/2"},
        },
    )
    assert validated["schedule"]["hour"] == "*/2"
