"""GraphBuilder: State management and generic operations for building workflow graphs.

All user/LLM actions modify this in-memory GraphBuilder instance.
Predictable input/schema/reference errors do NOT raise Python exceptions;
they return {"ok": false, "code": "...", "issues": [...]} without mutating state.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from obsidian_ai_hub.tasks import store as task_store
from obsidian_ai_hub.tasks.capabilities import get_capability_definitions
from obsidian_ai_hub.workflow.capabilities import (
    is_strict_allowed,
    output_contract_class,
    workflow_output_schema,
)
from obsidian_ai_hub.workflow.definition_package import (
    DefinitionPackageError,
    build_package,
    validate_package,
)
from obsidian_ai_hub.workflow.models import (
    EDGE_KINDS,
    MAX_EDGES,
    MAX_ITERATIONS,
    MAX_NODES,
    NODE_TYPES,
    TERMINAL_OUTCOMES,
    iter_references,
)
from obsidian_ai_hub.workflow.validation import validate_graph


def derive_node_analysis(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Derive deterministic node analysis (effects & approval requirements) from nodes."""
    cap_defs = {c.key: c for c in get_capability_definitions()}
    try:
        policies = {
            str(c["capability_key"]): str(c.get("approval_policy") or "plan_required")
            for c in task_store.list_capabilities()
        }
    except Exception:
        policies = {}

    analysis: list[dict[str, Any]] = []
    for node in nodes or []:
        nid = str(node.get("node_id") or "")
        ntype = str(node.get("node_type") or "")
        label = str(node.get("label") or nid)
        config = node.get("config") or {}
        if not isinstance(config, dict):
            config = {}

        if ntype == "agent":
            analysis.append({
                "node_id": nid,
                "node_type": ntype,
                "label": label,
                "effects": "会話型Agentの実行（検索・思考・ツール呼び出しの可能性を含む）",
                "requires_approval": True,
                "requires_approval_reason": "会話型Agentノードを含むため承認が必要です",
            })
        elif ntype == "capability":
            key = str(config.get("capability_key") or "")
            cap = cap_defs.get(key)
            is_read_only = cap.read_only if cap else False
            policy = policies.get(key, cap.default_approval_policy if cap else "plan_required")
            req_approval = (policy == "plan_required")

            if cap:
                effects_desc = "読み取り専用操作" if is_read_only else f"外部書き込み・変更操作 ({cap.description or cap.label})"
            else:
                effects_desc = f"Capability '{key}' の実行"

            if req_approval:
                reason = f"承認が必要なCapability '{key}' を含むため"
            else:
                reason = "読み取り専用または自動承認Capabilityのため承認不要"

            analysis.append({
                "node_id": nid,
                "node_type": ntype,
                "label": label,
                "effects": effects_desc,
                "requires_approval": req_approval,
                "requires_approval_reason": reason,
            })
        elif ntype == "llm":
            analysis.append({
                "node_id": nid,
                "node_type": ntype,
                "label": label,
                "effects": "単発LLM呼び出し（会話コンテキスト非保存）",
                "requires_approval": False,
                "requires_approval_reason": "単発LLMノードのため承認不要",
            })
        elif ntype == "text_template":
            analysis.append({
                "node_id": nid,
                "node_type": ntype,
                "label": label,
                "effects": "テキストテンプレート描画",
                "requires_approval": False,
                "requires_approval_reason": "テキストテンプレートノードのため承認不要",
            })
        elif ntype == "terminal":
            outcome = config.get("outcome", "completed")
            analysis.append({
                "node_id": nid,
                "node_type": ntype,
                "label": label,
                "effects": f"ワークフロー実行終端 ({outcome})",
                "requires_approval": False,
                "requires_approval_reason": "終端ノードのため承認不要",
            })
        elif ntype in ("loop", "loop_result"):
            analysis.append({
                "node_id": nid,
                "node_type": ntype,
                "label": label,
                "effects": "反復・集約制御",
                "requires_approval": False,
                "requires_approval_reason": "制御ノードのため承認不要",
            })
        else:
            analysis.append({
                "node_id": nid,
                "node_type": ntype,
                "label": label,
                "effects": "不明なノード処理",
                "requires_approval": False,
                "requires_approval_reason": "承認不要",
            })

    return analysis


class GraphBuilder:
    """GraphBuilder manages graph construction, tool operations, and validation."""

    def __init__(self, name: str = "", description: str = "") -> None:
        self.name: str = name
        self.description: str = description
        self.inputs_schema: dict[str, Any] = {"type": "object", "properties": {}, "required": []}
        self.nodes: list[dict[str, Any]] = []
        self.edges: list[dict[str, Any]] = []

    def set_metadata(self, name: str, description: str = "") -> dict[str, Any]:
        """Update workflow package name and description."""
        name_clean = (name or "").strip()
        if not name_clean:
            return {"ok": False, "code": "invalid_name", "issues": ["name は空でない文字列が必要です"]}
        self.name = name_clean
        self.description = description or ""
        return {"ok": True, "name": self.name, "description": self.description}

    def set_inputs_schema(self, inputs_schema: dict[str, Any]) -> dict[str, Any]:
        """Update top-level inputs_schema."""
        if not isinstance(inputs_schema, dict):
            return {"ok": False, "code": "invalid_inputs_schema", "issues": ["inputs_schema は object が必要です"]}
        self.inputs_schema = inputs_schema
        return {"ok": True, "inputs_schema": self.inputs_schema}

    def add_node(
        self,
        node_type: str,
        label: str,
        config: Optional[dict[str, Any]] = None,
        parent_loop_node_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Add a new node shell to the graph."""
        if len(self.nodes) >= MAX_NODES:
            return {"ok": False, "code": "max_nodes_exceeded", "issues": [f"Node 数が上限 {MAX_NODES} を超えています"]}

        ntype = (node_type or "").strip().lower()
        if ntype not in NODE_TYPES:
            return {
                "ok": False,
                "code": "invalid_node_type",
                "issues": [f"node_type '{node_type}' は無効です。{sorted(NODE_TYPES)} のいずれかを指定してください"],
            }

        label_clean = (label or "").strip() or ntype
        parent_clean = str(parent_loop_node_id).strip() if parent_loop_node_id else None

        if parent_clean:
            parent_node = next((n for n in self.nodes if str(n["node_id"]) == parent_clean), None)
            if not parent_node:
                return {
                    "ok": False,
                    "code": "parent_loop_not_found",
                    "issues": [f"親 Loop Node '{parent_clean}' が存在しません"],
                }
            if parent_node.get("node_type") != "loop":
                return {
                    "ok": False,
                    "code": "parent_not_a_loop",
                    "issues": [f"親 Node '{parent_clean}' は Loop Node ではありません"],
                }

        node_id = f"node_{uuid.uuid4().hex[:8]}"
        cfg = config if isinstance(config, dict) else {}

        # Default configs
        if ntype == "terminal" and "outcome" not in cfg:
            cfg["outcome"] = "completed"

        node = {
            "node_id": node_id,
            "node_type": ntype,
            "label": label_clean,
            "config": cfg,
            "parent_loop_node_id": parent_clean,
            "ui_position": None,
        }
        self.nodes.append(node)
        return {"ok": True, "node_id": node_id, "node": node}

    def remove_node(self, node_id: str) -> dict[str, Any]:
        """Remove a node and its associated edges / children."""
        target_id = str(node_id or "").strip()
        existing = next((n for n in self.nodes if str(n["node_id"]) == target_id), None)
        if not existing:
            return {"ok": False, "code": "node_not_found", "issues": [f"Node '{target_id}' が存在しません"]}

        # Remove child nodes if loop
        child_ids = {str(n["node_id"]) for n in self.nodes if n.get("parent_loop_node_id") == target_id}
        to_remove = {target_id} | child_ids

        self.nodes = [n for n in self.nodes if str(n["node_id"]) not in to_remove]
        self.edges = [
            e for e in self.edges
            if str(e["source_node_id"]) not in to_remove and str(e["target_node_id"]) not in to_remove
        ]
        return {"ok": True, "removed_node_ids": list(to_remove)}

    def _check_and_apply_strict_references(self, value: Any) -> list[str]:
        """Inspect value for capability references.

        If referencing a structured capability, enforces strict policy and automatically
        sets fail_on_output_mismatch: true on the source capability node.
        Returns a list of error issue strings if invalid.
        """
        by_id = {str(n["node_id"]): n for n in self.nodes}
        errors: list[str] = []

        for ref in iter_references(value):
            segments = ref.split(".")
            if len(segments) >= 3 and segments[0] == "nodes" and segments[2] == "output":
                source_id = segments[1]
                source_node = by_id.get(source_id)
                if not source_node or source_node.get("node_type") != "capability":
                    continue

                cfg = source_node.get("config") or {}
                key = str(cfg.get("capability_key") or "")
                if not key:
                    continue

                contract = output_contract_class(key)
                strict_ok = is_strict_allowed(key)

                tail = segments[3:]
                if not tail:
                    errors.append(
                        f"output_contract: Capability '{key}' の出力全体 (nodes.{source_id}.output) は参照できません。"
                        "宣言済みの個別フィールドを参照してください"
                    )
                    continue

                if contract != "structured":
                    errors.append(
                        f"output_contract: Capability '{key}' (contract={contract}) の出力は参照できません"
                    )
                    continue

                if not strict_ok:
                    errors.append(
                        f"strict_policy: Capability '{key}' (nodes.{source_id}) は strict 参照が許可されていません"
                    )
                    continue

                schema = workflow_output_schema(key)
                if not isinstance(schema, dict):
                    errors.append(f"output_contract: Capability '{key}' に宣言済み出力がありません")
                    continue

                props = schema.get("properties") or {}
                field = tail[0]
                if field not in props:
                    errors.append(f"output_contract: フィールド '{field}' は Capability '{key}' の宣言済み出力にありません")
                    continue

                req = schema.get("required") or []
                if field not in req:
                    errors.append(f"output_contract: フィールド '{field}' は Capability '{key}' の必須出力ではありません")
                    continue

                # Automatically set fail_on_output_mismatch = True on the source node
                cfg["fail_on_output_mismatch"] = True

        return errors

    def _reapply_all_strict_references(self) -> None:
        """Re-scan all nodes' configs and edges' conditions to re-apply strict flags."""
        for n in self.nodes:
            cfg = n.get("config")
            if isinstance(cfg, dict):
                self._check_and_apply_strict_references(cfg)
        for e in self.edges:
            cond = e.get("condition")
            if isinstance(cond, dict):
                self._check_and_apply_strict_references(cond)

    def set_node_config(self, node_id: str, config: dict[str, Any]) -> dict[str, Any]:
        """Set config object for a node."""
        target_id = str(node_id or "").strip()
        node = next((n for n in self.nodes if str(n["node_id"]) == target_id), None)
        if not node:
            return {"ok": False, "code": "node_not_found", "issues": [f"Node '{target_id}' が存在しません"]}

        if not isinstance(config, dict):
            return {"ok": False, "code": "invalid_config", "issues": ["config は object が必要です"]}

        strict_errors = self._check_and_apply_strict_references(config)
        if strict_errors:
            return {"ok": False, "code": "invalid_strict_reference", "issues": strict_errors}

        node["config"] = config
        self._reapply_all_strict_references()
        return {"ok": True, "node_id": target_id, "config": node["config"]}

    def bind_field(self, node_id: str, field_path: str, value: Any) -> dict[str, Any]:
        """Bind a value/reference/expression/pipe to a field within a node's config."""
        target_id = str(node_id or "").strip()
        node = next((n for n in self.nodes if str(n["node_id"]) == target_id), None)
        if not node:
            return {"ok": False, "code": "node_not_found", "issues": [f"Node '{target_id}' が存在しません"]}

        path_clean = (field_path or "").strip()
        if not path_clean:
            return {"ok": False, "code": "invalid_field_path", "issues": ["field_path は空でない文字列が必要です"]}

        strict_errors = self._check_and_apply_strict_references(value)
        if strict_errors:
            return {"ok": False, "code": "invalid_strict_reference", "issues": strict_errors}

        config = node.get("config")
        if not isinstance(config, dict):
            config = {}
            node["config"] = config

        parts = path_clean.split(".")
        current = config
        for part in parts[:-1]:
            if part not in current or not isinstance(current[part], dict):
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value

        return {"ok": True, "node_id": target_id, "config": node["config"]}

    def add_edge(
        self,
        source_node_id: str,
        target_node_id: str,
        edge_kind: str = "normal",
        condition: Optional[dict[str, Any]] = None,
        order_index: int = 0,
    ) -> dict[str, Any]:
        """Add an edge between two nodes in the same scope."""
        if len(self.edges) >= MAX_EDGES:
            return {"ok": False, "code": "max_edges_exceeded", "issues": [f"Edge 数が上限 {MAX_EDGES} を超えています"]}

        src_id = str(source_node_id or "").strip()
        tgt_id = str(target_node_id or "").strip()

        by_id = {str(n["node_id"]): n for n in self.nodes}
        if src_id not in by_id:
            return {"ok": False, "code": "source_node_not_found", "issues": [f"Source Node '{src_id}' が存在しません"]}
        if tgt_id not in by_id:
            return {"ok": False, "code": "target_node_not_found", "issues": [f"Target Node '{tgt_id}' が存在しません"]}

        src_node = by_id[src_id]
        tgt_node = by_id[tgt_id]

        if src_node.get("parent_loop_node_id") != tgt_node.get("parent_loop_node_id"):
            return {
                "ok": False,
                "code": "scope_mismatch",
                "issues": [f"Source '{src_id}' と Target '{tgt_id}' のスコープが一致しません"],
            }

        if src_node.get("node_type") == "terminal":
            return {"ok": False, "code": "terminal_outgoing_edge", "issues": [f"terminal Node '{src_id}' に outgoing Edge は追加できません"]}

        kind = (edge_kind or "normal").strip().lower()
        if kind not in EDGE_KINDS:
            return {"ok": False, "code": "invalid_edge_kind", "issues": [f"edge_kind '{edge_kind}' は無効です"]}

        if condition is not None:
            strict_errors = self._check_and_apply_strict_references(condition)
            if strict_errors:
                return {"ok": False, "code": "invalid_strict_reference", "issues": strict_errors}

        edge_id = f"edge_{uuid.uuid4().hex[:8]}"
        edge = {
            "edge_id": edge_id,
            "source_node_id": src_id,
            "target_node_id": tgt_id,
            "edge_kind": kind,
            "condition": condition,
            "order_index": int(order_index or 0),
        }
        self.edges.append(edge)
        return {"ok": True, "edge_id": edge_id, "edge": edge}

    def remove_edge(self, edge_id: str) -> dict[str, Any]:
        """Remove an edge by ID."""
        target_id = str(edge_id or "").strip()
        existing = next((e for e in self.edges if str(e["edge_id"]) == target_id), None)
        if not existing:
            return {"ok": False, "code": "edge_not_found", "issues": [f"Edge '{target_id}' が存在しません"]}

        self.edges = [e for e in self.edges if str(e["edge_id"]) != target_id]
        return {"ok": True, "removed_edge_id": target_id}

    def configure_loop(
        self,
        loop_node_id: str,
        entry_node_id: str,
        state_schema: dict[str, Any],
        continuation_condition: dict[str, Any],
        max_iterations: int = 10,
        input_mapping: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Configure a loop node's execution parameters."""
        lid = str(loop_node_id or "").strip()
        loop_node = next((n for n in self.nodes if str(n["node_id"]) == lid), None)
        if not loop_node or loop_node.get("node_type") != "loop":
            return {"ok": False, "code": "loop_node_not_found", "issues": [f"Loop Node '{lid}' が存在しません"]}

        eid = str(entry_node_id or "").strip()
        child_nodes = [n for n in self.nodes if n.get("parent_loop_node_id") == lid]
        child_ids = {str(n["node_id"]) for n in child_nodes}
        if eid not in child_ids:
            return {"ok": False, "code": "entry_node_not_in_loop", "issues": [f"Entry Node '{eid}' は Loop '{lid}' の子グラフに含まれていません"]}

        if not isinstance(state_schema, dict):
            return {"ok": False, "code": "invalid_state_schema", "issues": ["state_schema は object が必要です"]}

        if not isinstance(continuation_condition, dict):
            return {"ok": False, "code": "invalid_continuation_condition", "issues": ["continuation_condition は object が必要です"]}

        strict_errors = self._check_and_apply_strict_references(continuation_condition)
        if input_mapping:
            strict_errors.extend(self._check_and_apply_strict_references(input_mapping))
        if strict_errors:
            return {"ok": False, "code": "invalid_strict_reference", "issues": strict_errors}

        max_iter = int(max_iterations or 10)
        if max_iter < 1 or max_iter > MAX_ITERATIONS:
            return {"ok": False, "code": "invalid_max_iterations", "issues": [f"max_iterations は 1..{MAX_ITERATIONS} の範囲で指定してください"]}

        config = loop_node.get("config") or {}
        config["entry_node_id"] = eid
        config["state_schema"] = state_schema
        config["continuation_condition"] = continuation_condition
        config["max_iterations"] = max_iter
        config["input_mapping"] = input_mapping or {}
        loop_node["config"] = config

        return {"ok": True, "loop_node_id": lid, "config": config}

    def validate(self) -> dict[str, Any]:
        """Run structural package validation and static graph validation."""
        pkg_data = {
            "format": "obsidian-ai-hub.workflow-definition",
            "version": 1,
            "name": self.name or "Untitled Workflow",
            "description": self.description or "",
            "inputs_schema": self.inputs_schema,
            "nodes": self.nodes,
            "edges": self.edges,
        }

        structural_errors: list[dict[str, Any]] = []
        try:
            validate_package(pkg_data)
        except DefinitionPackageError as exc:
            for msg in str(exc).split("; "):
                structural_errors.append({"code": "structural_error", "message": msg})

        static_issues: list[dict[str, Any]] = []
        if not structural_errors:
            raw_issues = validate_graph(
                nodes=self.nodes,
                edges=self.edges,
                inputs_schema=self.inputs_schema,
            )
            for issue_str in raw_issues:
                static_issues.append({"code": "graph_validation_issue", "message": issue_str})

        return {
            "ok": len(structural_errors) == 0,
            "structural_errors": structural_errors,
            "validation_issues": static_issues,
        }

    def apply_layout(self) -> None:
        """Apply deterministic coordinates (ui_position) for all nodes in the graph."""
        scopes: dict[Optional[str], list[dict[str, Any]]] = {}
        for n in self.nodes:
            parent = n.get("parent_loop_node_id")
            scopes.setdefault(parent, []).append(n)

        by_id = {str(n["node_id"]): n for n in self.nodes}

        for scope_id, scope_nodes in scopes.items():
            scope_ids = {str(n["node_id"]) for n in scope_nodes}
            in_degree = {nid: 0 for nid in scope_ids}
            out_edges: dict[str, list[str]] = {nid: [] for nid in scope_ids}

            for e in self.edges:
                src = str(e["source_node_id"])
                tgt = str(e["target_node_id"])
                if src in scope_ids and tgt in scope_ids:
                    out_edges[src].append(tgt)
                    in_degree[tgt] += 1

            # Topological depth assignment
            depth: dict[str, int] = {}
            roots = [nid for nid in scope_ids if in_degree[nid] == 0]
            if not roots and scope_nodes:
                roots = [str(scope_nodes[0]["node_id"])]

            for r in roots:
                depth[r] = 0

            queue = list(roots)
            while queue:
                curr = queue.pop(0)
                curr_d = depth.get(curr, 0)
                for nxt in out_edges.get(curr, []):
                    if depth.get(nxt, -1) < curr_d + 1:
                        depth[nxt] = curr_d + 1
                        queue.append(nxt)

            # Assign coordinates per column (depth)
            cols: dict[int, list[str]] = {}
            for nid in scope_ids:
                d = depth.get(nid, 0)
                cols.setdefault(d, []).append(nid)

            for col_idx in sorted(cols.keys()):
                col_nodes = sorted(cols[col_idx], key=lambda x: str(by_id[x].get("label")))
                for row_idx, nid in enumerate(col_nodes):
                    x_pos = 100 + col_idx * 280
                    y_pos = 100 + row_idx * 160
                    by_id[nid]["ui_position"] = {"x": x_pos, "y": y_pos}

    def finalize(self, summary: str = "", assumptions: Optional[list[str]] = None) -> dict[str, Any]:
        """Apply layout and build definition package."""
        self.apply_layout()

        pkg = build_package(
            name=self.name or "Untitled Workflow",
            description=self.description or "",
            inputs_schema=self.inputs_schema,
            nodes=self.nodes,
            edges=self.edges,
        )

        val_res = self.validate()
        structural_errors = val_res["structural_errors"]
        validation_issues = val_res["validation_issues"]

        if structural_errors:
            return {
                "ok": False,
                "package": None,
                "summary": None,
                "assumptions": assumptions or [],
                "node_analysis": [],
                "structural_errors": structural_errors,
                "validation_issues": validation_issues,
            }

        node_analysis = derive_node_analysis(self.nodes)

        return {
            "ok": True,
            "package": pkg,
            "summary": summary or f"Workflow '{self.name}' を作成しました",
            "assumptions": assumptions or [],
            "node_analysis": node_analysis,
            "structural_errors": [],
            "validation_issues": validation_issues,
        }
