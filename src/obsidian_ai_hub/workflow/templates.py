"""Code-defined starter workflow templates.

Templates use symbolic node ids; :func:`build_graph` remaps them to fresh
UUIDs (and rewrites ``$ref`` paths / loop wiring) on every instantiation so
``workflow_nodes.node_id`` stays globally unique. Agent Node templates leave
``agent_id`` empty on purpose: the author selects the target Agent before
publishing. See ``docs/workflow/specification.md`` §15 and §20.
"""

from __future__ import annotations

from typing import Any

from obsidian_ai_hub.workflow.graph_copy import renumber_graph


def _agent_node(
    node_id: str, label: str, inputs: dict[str, Any], output_properties: dict[str, Any]
) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "node_type": "agent",
        "label": label,
        "config": {
            "agent_id": "",
            "inputs": inputs,
            "output_schema": {
                "type": "object",
                "properties": output_properties,
                "additionalProperties": False,
            },
        },
        "parent_loop_node_id": None,
        "ui_position": None,
    }


def _capability_node(
    node_id: str, label: str, capability_key: str, inputs: dict[str, Any]
) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "node_type": "capability",
        "label": label,
        "config": {"capability_key": capability_key, "inputs": inputs},
        "parent_loop_node_id": None,
        "ui_position": None,
    }


def _terminal(node_id: str) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "node_type": "terminal",
        "label": "完了",
        "config": {"outcome": "success"},
        "parent_loop_node_id": None,
        "ui_position": None,
    }


def _edge(
    edge_id: str,
    source: str,
    target: str,
    order: int = 0,
    condition: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "edge_id": edge_id,
        "source_node_id": source,
        "target_node_id": target,
        "edge_kind": "normal",
        "condition": condition,
        "order_index": order,
    }


_PLAN_REVIEW_EXECUTE: dict[str, Any] = {
    "template_key": "plan_review_execute",
    "name": "機能追加の計画→レビュー→改稿→実行",
    "description": "Plannerが計画し、Reviewerの判定で改稿ループを回し、承認後に実行する。",
    "inputs_schema": {
        "type": "object",
        "properties": {"task": {"type": "string"}},
        "required": ["task"],
        "additionalProperties": False,
    },
    "nodes": [
        _agent_node(
            "plan",
            "計画",
            {"task": {"$ref": "run.inputs.task"}},
            {"plan": {"type": "string"}},
        ),
        {
            "node_id": "loop",
            "node_type": "loop",
            "label": "改稿ループ",
            "config": {
                "state_schema": {
                    "type": "object",
                    "properties": {
                        "plan": {"type": "string"},
                        "review": {"type": "string"},
                        "done": {"type": "boolean"},
                    },
                    "required": ["plan", "done"],
                    "additionalProperties": False,
                },
                "input_mapping": {
                    "plan": {"$ref": "nodes.plan.output.plan"},
                    "review": "",
                    "done": False,
                },
                "continuation_condition": {
                    "from_path": "loop.state.done",
                    "operator": "equals",
                    "value": False,
                },
                "max_iterations": 4,
                "entry_node_id": "revise",
            },
            "parent_loop_node_id": None,
            "ui_position": None,
        },
        {
            **_agent_node(
                "revise",
                "レビューと改稿",
                {
                    "plan": {"$ref": "loop.state.plan"},
                    "review": {"$ref": "loop.state.review"},
                },
                {
                    "plan": {"type": "string"},
                    "review": {"type": "string"},
                    "done": {"type": "boolean"},
                },
            ),
            "parent_loop_node_id": "loop",
        },
        {
            "node_id": "result",
            "node_type": "loop_result",
            "label": "ループ結果",
            "config": {
                "output_mapping": {
                    "plan": {"$ref": "nodes.revise.output.plan"},
                    "review": {"$ref": "nodes.revise.output.review"},
                    "done": {"$ref": "nodes.revise.output.done"},
                }
            },
            "parent_loop_node_id": "loop",
            "ui_position": None,
        },
        _agent_node(
            "execute",
            "実行",
            {"plan": {"$ref": "nodes.loop.output.final_state.plan"}},
            {"summary": {"type": "string"}},
        ),
        _terminal("done"),
    ],
    "edges": [
        _edge("e_plan_loop", "plan", "loop"),
        _edge("e_loop_execute", "loop", "execute"),
        _edge("e_execute_done", "execute", "done"),
    ],
}

_CONTEXTUAL_RESEARCH: dict[str, Any] = {
    "template_key": "contextual_research",
    "name": "文脈付きリサーチ",
    "description": "活動・既存テーマ・Vault検索で文脈を集め、テーマを整えてリサーチを実行する。",
    "inputs_schema": {
        "type": "object",
        "properties": {"topic": {"type": "string"}},
        "required": ["topic"],
        "additionalProperties": False,
    },
    "nodes": [
        _capability_node("context", "文脈収集", "research_context_snapshot", {}),
        _agent_node(
            "theme",
            "テーマ整形",
            {
                "topic": {"$ref": "run.inputs.topic"},
                "context": {"$ref": "nodes.context.output"},
            },
            {"theme": {"type": "string"}},
        ),
        _capability_node(
            "research",
            "リサーチ実行",
            "research_agent",
            {"theme": {"$ref": "nodes.theme.output.theme"}},
        ),
        _terminal("done"),
    ],
    "edges": [
        _edge("e_context_theme", "context", "theme"),
        _edge("e_theme_research", "theme", "research"),
        _edge("e_research_done", "research", "done"),
    ],
}

TEMPLATES: tuple[dict[str, Any], ...] = (_PLAN_REVIEW_EXECUTE, _CONTEXTUAL_RESEARCH)


def list_templates() -> list[dict[str, str]]:
    return [
        {
            "template_key": template["template_key"],
            "name": template["name"],
            "description": template["description"],
        }
        for template in TEMPLATES
    ]


def get_template(template_key: str) -> dict[str, Any] | None:
    for template in TEMPLATES:
        if template["template_key"] == template_key:
            return template
    return None


def build_graph(template: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return freshly identified nodes/edges for one instantiation."""
    return renumber_graph(
        template["nodes"], template["edges"], default_positions=True
    )
