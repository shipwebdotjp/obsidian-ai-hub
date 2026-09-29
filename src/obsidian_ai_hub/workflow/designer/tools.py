"""LangChain tools for Workflow Designer catalog and graph manipulation.

Bound to a GraphBuilder instance per request.
Predictable tool errors return { "ok": false, "code": "...", "issues": [...] }
instead of raising exceptions.
"""

from __future__ import annotations

from typing import Any, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from obsidian_ai_hub.workflow.designer import catalog
from obsidian_ai_hub.workflow.designer.builder import GraphBuilder

# --- Input Schemas ---


class CatalogSearchInput(BaseModel):
    query: str = Field(default="", description="検索キーワード（名称・パスなど）")
    target: str = Field(
        default="capability",
        description="検索対象: 'capability', 'agent', 'project', 'person', 'vault'",
    )


class CatalogGetDetailsInput(BaseModel):
    target: str = Field(description="対象種別: 'capability', 'agent', 'project', 'person', 'vault'")
    item_id: str = Field(description="対象の識別子（capability_key, agent_id, project_id, person_id, relative_path）")


class SetMetadataInput(BaseModel):
    name: str = Field(description="Workflow の名前（空でない文字列）")
    description: str = Field(default="", description="Workflow の説明文")


class SetInputsSchemaInput(BaseModel):
    inputs_schema: dict[str, Any] = Field(
        description="Workflow 全体の JSON Schema（properties, required を含む object スキーマ）"
    )


class AddNodeInput(BaseModel):
    node_type: str = Field(
        description="ノード種別: 'capability', 'agent', 'llm', 'loop', 'loop_result', 'terminal', 'text_template'"
    )
    label: str = Field(description="ノードの表示名")
    node_config: Optional[dict[str, Any]] = Field(default=None, description="ノードの初期設定オブジェクト")
    parent_loop_node_id: Optional[str] = Field(
        default=None, description="Loop ノード内の子グラフとして配置する場合は親 Loop Node ID"
    )


class RemoveNodeInput(BaseModel):
    node_id: str = Field(description="削除対象の Node ID")


class SetNodeConfigInput(BaseModel):
    node_id: str = Field(description="対象の Node ID")
    node_config: dict[str, Any] = Field(description="設定する config オブジェクト")


class BindFieldInput(BaseModel):
    node_id: str = Field(description="対象の Node ID")
    field_path: str = Field(
        description="設定対象フィールドのドット指定パス（例: 'inputs.vault_path', 'inputs.prompt', 'template'）"
    )
    value: Any = Field(
        description="設定する値（リテラル、型付き参照 {'$ref': 'nodes.<id>.output.<field>'}、式 {'$expr': {...}}、pipe 付き参照 {'$ref': '...', 'pipe': [...]}）"
    )


class AddEdgeInput(BaseModel):
    source_node_id: str = Field(description="接続元 Node ID")
    target_node_id: str = Field(description="接続先 Node ID")
    edge_kind: str = Field(
        default="normal", description="Edge 種別: 'normal' または 'error'。条件分岐は condition に {'from_path': '...', 'operator': 'equals'|'exists'|'in', 'value': ...} を指定する"
    )
    condition: Optional[dict[str, Any]] = Field(
        default=None, description="条件 Edge の場合: {'from_path': '...', 'operator': 'equals'|'exists'|'in', 'value': ...}"
    )
    order_index: int = Field(default=0, description="評価順序インデックス")


class RemoveEdgeInput(BaseModel):
    edge_id: str = Field(description="削除対象の Edge ID")


class ConfigureLoopInput(BaseModel):
    loop_node_id: str = Field(description="対象の Loop Node ID")
    entry_node_id: str = Field(description="Loop 子グラフの入口 Node ID")
    state_schema: dict[str, Any] = Field(description="Loop 状態オブジェクトの JSON Schema")
    continuation_condition: dict[str, Any] = Field(
        description="Loop 継続条件: {'from_path': '...', 'operator': '...', 'value': '...'}"
    )
    max_iterations: int = Field(default=10, description="最大反復回数 (1..50)")
    input_mapping: Optional[dict[str, Any]] = Field(
        default=None, description="Loop 開始時の初期状態マッピング"
    )


class FinalizeInput(BaseModel):
    summary: str = Field(description="作成した Workflow グラフの概要")
    assumptions: list[str] = Field(default_factory=list, description="生成にあたって置いた前提事項のリスト")


# --- Tool Factory ---


def create_designer_tools(builder: GraphBuilder) -> list[StructuredTool]:
    """Create designer tools bound to the provided GraphBuilder instance."""

    def _catalog_search(query: str = "", target: str = "capability") -> Any:
        return catalog.catalog_search(query=query, target=target)

    def _catalog_get_details(target: str, item_id: str) -> Any:
        return catalog.catalog_get_details(target=target, item_id=item_id)

    def _set_metadata(name: str, description: str = "") -> Any:
        return builder.set_metadata(name=name, description=description)

    def _set_inputs_schema(inputs_schema: dict[str, Any]) -> Any:
        return builder.set_inputs_schema(inputs_schema=inputs_schema)

    def _add_node(
        node_type: str,
        label: str,
        node_config: Optional[dict[str, Any]] = None,
        parent_loop_node_id: Optional[str] = None,
    ) -> Any:
        return builder.add_node(
            node_type=node_type,
            label=label,
            config=node_config,
            parent_loop_node_id=parent_loop_node_id,
        )

    def _remove_node(node_id: str) -> Any:
        return builder.remove_node(node_id=node_id)

    def _set_node_config(node_id: str, node_config: dict[str, Any]) -> Any:
        return builder.set_node_config(node_id=node_id, config=node_config)

    def _bind_field(node_id: str, field_path: str, value: Any) -> Any:
        return builder.bind_field(node_id=node_id, field_path=field_path, value=value)

    def _add_edge(
        source_node_id: str,
        target_node_id: str,
        edge_kind: str = "normal",
        condition: Optional[dict[str, Any]] = None,
        order_index: int = 0,
    ) -> Any:
        return builder.add_edge(
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            edge_kind=edge_kind,
            condition=condition,
            order_index=order_index,
        )

    def _remove_edge(edge_id: str) -> Any:
        return builder.remove_edge(edge_id=edge_id)

    def _configure_loop(
        loop_node_id: str,
        entry_node_id: str,
        state_schema: dict[str, Any],
        continuation_condition: dict[str, Any],
        max_iterations: int = 10,
        input_mapping: Optional[dict[str, Any]] = None,
    ) -> Any:
        return builder.configure_loop(
            loop_node_id=loop_node_id,
            entry_node_id=entry_node_id,
            state_schema=state_schema,
            continuation_condition=continuation_condition,
            max_iterations=max_iterations,
            input_mapping=input_mapping,
        )

    def _validate() -> Any:
        return builder.validate()

    def _finalize(summary: str, assumptions: Optional[list[str]] = None) -> Any:
        return builder.finalize(summary=summary, assumptions=assumptions or [])

    return [
        StructuredTool.from_function(
            func=_catalog_search,
            name="catalog_search",
            description="Capability, Agent, Project, Person, Vault ファイルを検索し、最大10件の候補を返します。",
            args_schema=CatalogSearchInput,
        ),
        StructuredTool.from_function(
            func=_catalog_get_details,
            name="catalog_get_details",
            description="指定したアイテムの入力/出力 Schema や詳細メタデータを取得します。",
            args_schema=CatalogGetDetailsInput,
        ),
        StructuredTool.from_function(
            func=_set_metadata,
            name="graph_set_metadata",
            description="Workflow の名前と説明を設定します。",
            args_schema=SetMetadataInput,
        ),
        StructuredTool.from_function(
            func=_set_inputs_schema,
            name="graph_set_inputs_schema",
            description="Workflow 全体の inputs_schema (JSON Schema) を設定します。",
            args_schema=SetInputsSchemaInput,
        ),
        StructuredTool.from_function(
            func=_add_node,
            name="graph_add_node",
            description="新しい Node シェルを追加します。",
            args_schema=AddNodeInput,
        ),
        StructuredTool.from_function(
            func=_remove_node,
            name="graph_remove_node",
            description="指定した Node（および関連 Edge/子ノード）を削除します。",
            args_schema=RemoveNodeInput,
        ),
        StructuredTool.from_function(
            func=_set_node_config,
            name="graph_set_node_config",
            description="Node の node_config 全体を設定します。参照がある場合、対応する Capability の strict 設定が自動更新されます。",
            args_schema=SetNodeConfigInput,
        ),
        StructuredTool.from_function(
            func=_bind_field,
            name="graph_bind_field",
            description="Node 内の特定フィールドにリテラル値・型付き参照・$expr 式・pipe 付き参照をバインドします。",
            args_schema=BindFieldInput,
        ),
        StructuredTool.from_function(
            func=_add_edge,
            name="graph_add_edge",
            description="2つの Node 間に Edge を追加します。",
            args_schema=AddEdgeInput,
        ),
        StructuredTool.from_function(
            func=_remove_edge,
            name="graph_remove_edge",
            description="指定した Edge を削除します。",
            args_schema=RemoveEdgeInput,
        ),
        StructuredTool.from_function(
            func=_configure_loop,
            name="graph_configure_loop",
            description="Loop Node の入口ノード、state_schema、継続条件、最大反復回数を設定します。",
            args_schema=ConfigureLoopInput,
        ),
        StructuredTool.from_function(
            func=_validate,
            name="graph_validate",
            description="現在のグラフの構造および静的検証を実行し、エラーや検証 issue の一覧を返します。",
        ),
        StructuredTool.from_function(
            func=_finalize,
            name="graph_finalize",
            description="グラフのレイアウトを整え、完成パッケージを作成して最終報告を行います。",
            args_schema=FinalizeInput,
        ),
    ]
