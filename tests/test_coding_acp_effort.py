"""ACP thought_level (reasoning effort) selection from advertised configOptions.

The Worker pins the model with ``session/set_config_option`` (configId
``model``) and then selects the best effort the agent advertises for it
(``max -> xhigh -> high -> medium -> low``). No advertised preferred value
keeps the agent default; a rejected set fails the turn before prompting.
"""

from unittest.mock import patch

import pytest

from obsidian_ai_hub.coding import acp


def _effort_option(values, option_id="effort", category="thought_level"):
    option = {
        "id": option_id,
        "name": "Effort",
        "type": "select",
        "currentValue": values[0] if values else "",
        "options": [{"value": v, "name": v} for v in values],
    }
    if category is not None:
        option["category"] = category
    return option


@pytest.mark.parametrize(
    "advertised,expected",
    [
        (["default", "low", "medium", "high", "xhigh", "max"], "max"),
        (["default", "low", "medium", "high", "xhigh"], "xhigh"),
        (["default", "low", "medium", "high"], "high"),
        (["default", "low", "medium"], "medium"),
        (["default", "low"], "low"),
    ],
)
def test_effort_priority_picks_first_advertised(advertised, expected):
    selection = acp._select_effort([_effort_option(advertised)])

    assert selection.applied is True
    assert selection.value == expected
    assert selection.config_id == "effort"
    assert selection.advertised == advertised
    assert selection.unsupported_reason is None


def test_effort_uses_advertised_option_id_and_values_verbatim():
    selection = acp._select_effort(
        [_effort_option(["low", "high"], option_id="reasoning_effort")]
    )

    assert selection.config_id == "reasoning_effort"
    assert selection.value == "high"


def test_effort_flattens_grouped_select_options():
    option = {
        "id": "effort",
        "category": "thought_level",
        "type": "select",
        "currentValue": "low",
        "options": [
            {"group": "fast", "name": "Fast", "options": [{"value": "low", "name": "Low"}]},
            {"group": "deep", "name": "Deep", "options": [{"value": "max", "name": "Max"}]},
        ],
    }

    selection = acp._select_effort([option])

    assert selection.value == "max"
    assert selection.advertised == ["low", "max"]


def test_effort_locates_option_without_category_by_known_id():
    selection = acp._select_effort([_effort_option(["medium"], category=None)])

    assert selection.value == "medium"


def test_effort_without_preferred_value_keeps_agent_default():
    selection = acp._select_effort([_effort_option(["default", "ultra"])])

    assert selection.applied is False
    assert selection.value is None
    assert selection.advertised == ["default", "ultra"]
    assert selection.unsupported_reason


def test_effort_not_advertised_keeps_agent_default():
    selection = acp._select_effort(
        [{"id": "model", "category": "model", "type": "select", "currentValue": "m", "options": []}]
    )

    assert selection.applied is False
    assert selection.value is None
    assert selection.advertised == []
    assert selection.unsupported_reason


def _run_turn(config_options, effort_error=None):
    profile = acp.AcpLaunchProfile.get_profile("opencode")
    client = acp.AcpClientBackend(profile)
    calls = []
    config_params = []

    def fake_request(method, params, timeout=60.0):
        calls.append(method)
        if method == "session/new":
            return {"sessionId": "sess_effort"}
        if method == "session/set_config_option":
            config_params.append(dict(params))
            if params["configId"] == "model":
                return {"configOptions": config_options}
            if effort_error is not None:
                raise acp.AcpError(effort_error)
            return {"configOptions": config_options}
        return {}

    def fake_send_async(method, params):
        calls.append(method)
        return 5

    with patch.object(acp.AcpConnection, "start"), \
         patch.object(acp.AcpConnection, "is_alive", return_value=True), \
         patch.object(acp.AcpConnection, "terminate", return_value=0), \
         patch.object(acp.AcpConnection, "notify"), \
         patch.object(acp.AcpClientBackend, "initialize", return_value={"protocol_version": 1, "capabilities": {}}), \
         patch.object(acp.AcpConnection, "request", side_effect=fake_request), \
         patch.object(acp.AcpConnection, "send_request_async", side_effect=fake_send_async), \
         patch.object(acp.AcpConnection, "wait_for_response", return_value={"result": {"stopReason": "end_turn"}}), \
         patch.object(acp.AcpConnection, "pop_notifications", return_value=[]), \
         patch.object(acp.AcpConnection, "pop_client_requests", return_value=[]):

        res = client.execute_turn(repo_path="/tmp", prompt="hi")

    return res, calls, config_params


def test_execute_turn_sets_model_then_effort_then_prompt():
    res, calls, config_params = _run_turn(
        [_effort_option(["low", "medium", "high", "max"])]
    )

    assert calls == [
        "session/new",
        "session/set_config_option",
        "session/set_config_option",
        "session/prompt",
    ]
    assert config_params[0]["configId"] == "model"
    assert config_params[1] == {
        "sessionId": "sess_effort",
        "configId": "effort",
        "value": "max",
    }
    assert res.exit_code == 0
    assert res.diagnostics["acp_effort"] == "max"
    assert res.diagnostics["acp_effort_advertised"] == ["low", "medium", "high", "max"]
    assert res.diagnostics["acp_effort_unsupported_reason"] is None


def test_execute_turn_without_effort_option_prompts_with_agent_default():
    res, calls, config_params = _run_turn(
        [{"id": "model", "category": "model", "type": "select", "currentValue": "m", "options": []}]
    )

    assert "session/prompt" in calls
    assert [p["configId"] for p in config_params] == ["model"]
    assert res.exit_code == 0
    assert res.diagnostics["acp_effort"] is None
    assert res.diagnostics["acp_effort_advertised"] is None
    assert res.diagnostics["acp_effort_unsupported_reason"]


def test_execute_turn_unadvertised_priority_value_prompts_with_agent_default():
    res, calls, config_params = _run_turn([_effort_option(["default", "ultra"])])

    assert "session/prompt" in calls
    assert [p["configId"] for p in config_params] == ["model"]
    assert res.diagnostics["acp_effort"] is None
    assert res.diagnostics["acp_effort_advertised"] == ["default", "ultra"]
    assert res.diagnostics["acp_effort_unsupported_reason"]


def test_execute_turn_effort_rejection_fails_without_prompt():
    res, calls, config_params = _run_turn(
        [_effort_option(["high", "max"])],
        effort_error="RPC error on session/set_config_option: Effort not found",
    )

    assert res.exit_code == -1
    assert "max" in (res.error_message or "")
    assert "session/prompt" not in calls
    assert config_params[1]["configId"] == "effort"
    assert res.diagnostics["acp_effort"] == "max"
