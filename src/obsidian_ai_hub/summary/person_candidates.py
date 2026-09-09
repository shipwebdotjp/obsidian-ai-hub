import json
import logging
import sqlite3
from typing import Any, Dict, List, Optional

from datetime import datetime

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.hitl.service import register_run_and_questions
from obsidian_ai_hub.hitl.store import get_run
from obsidian_ai_hub.summary import store as summary_store
from obsidian_ai_hub.utils import config, llm_client, prompt
from obsidian_ai_hub.web.services import person_properties, person_relations

logger = logging.getLogger(__name__)

PROMPT_PATH = config.BASE_DIR / "config" / "prompts" / "extract_person_candidates.md"


def run_person_candidate_extraction_for_summary(
    summary_res: Dict[str, Any],
    target_date: datetime,
    daily_content: str,
) -> Optional[str]:
    """日次要約の保存結果から確定人物と根拠テキストを取り出し、候補抽出とHITL登録を実行するオーケストレーション関数。"""
    summary_id = summary_res.get("summary_id")
    if not summary_id:
        return None

    date_str = target_date.strftime("%Y-%m-%d")
    summary_full = summary_store.get_summary_by_id(summary_id)
    resolved_people = summary_full.get("people", []) if summary_full else []
    summary_text = summary_res.get("summary", "") or ""
    ground_truth_text = f"{summary_text}\n\n{daily_content}".strip()

    return extract_and_register_person_candidates(
        summary_id=summary_id,
        date_str=date_str,
        ground_truth_text=ground_truth_text,
        resolved_people=resolved_people,
    )


def get_deterministic_run_id(summary_id: str) -> str:
    return f"hitl_run_person_candidate_{summary_id}"


def extract_and_register_person_candidates(
    summary_id: str,
    date_str: str,
    ground_truth_text: str,
    resolved_people: List[Dict[str, Any]],
    conn: Optional[sqlite3.Connection] = None,
) -> Optional[str]:
    """
    確定人物から人物属性・リレーションの変更候補を抽出し、HITL Runを登録する。

    - 既に同一 summary_id の Run が存在する場合は既存 Run を保持し処理をスキップする。
    - 候補が 0 件の場合は Run を登録しない。
    """
    run_id = get_deterministic_run_id(summary_id)

    # 既存 Run チェック (状態を問わず再利用して変更しない)
    existing_run = get_run(run_id, conn=conn)
    if existing_run is not None:
        logger.info("HITL Run %s already exists for summary %s. Skipping extraction.", run_id, summary_id)
        return run_id

    # 確定人物が存在しない場合はスキップ
    confirmed_people = [p for p in resolved_people if p.get("person_id") and p.get("resolution_status") == "resolved"]
    if not confirmed_people:
        logger.info("No resolved confirmed people for summary %s. Skipping candidate extraction.", summary_id)
        return None

    # DB専用属性定義を取得
    all_defs = person_properties.list_property_definitions()
    db_defs = [d for d in all_defs if d.get("source_type") == "database"]

    # 有効なリレーションタイプを取得
    all_rel_types = person_relations.list_person_relation_types()
    active_rel_types = [t for t in all_rel_types if t.get("is_active")]

    if not db_defs and not active_rel_types:
        logger.info("No active DB property definitions or relation types available. Skipping extraction.")
        return None

    confirmed_person_ids = {p["person_id"] for p in confirmed_people}
    people_map = {p["person_id"]: p.get("name") or p.get("display_name") for p in confirmed_people}

    # 対象人物の既存属性値を取得
    existing_properties: List[Dict[str, Any]] = []
    for pid in confirmed_person_ids:
        try:
            props = person_properties.list_person_properties(pid)
            # DB専用のみ抽出
            existing_properties.extend([p for p in props if p.get("source_type") == "database"])
        except Exception as e:
            logger.warning("Failed to list properties for person %s: %s", pid, e)

    # 対象人物の既存直接リレーションを取得
    existing_relations_raw: List[Dict[str, Any]] = []
    for pid in confirmed_person_ids:
        try:
            rels = person_relations.list_person_relations_for_person(pid)
            existing_relations_raw.extend(rels)
        except Exception as e:
            logger.warning("Failed to list relations for person %s: %s", pid, e)

    # 重複除去 (relation_id 単位)
    seen_rel_ids = set()
    existing_relations: List[Dict[str, Any]] = []
    for rel in existing_relations_raw:
        rid = rel.get("relation_id")
        if rid and rid not in seen_rel_ids:
            seen_rel_ids.add(rid)
            existing_relations.append(rel)

    # プロンプトレンダリング
    rendered_prompt = prompt.render_prompt(
        PROMPT_PATH,
        {
            "GROUND_TRUTH_TEXT": ground_truth_text or "",
            "CONFIRMED_PEOPLE": json.dumps(confirmed_people, ensure_ascii=False, indent=2),
            "DB_PROPERTY_DEFINITIONS": json.dumps(db_defs, ensure_ascii=False, indent=2),
            "EXISTING_PERSON_PROPERTIES": json.dumps(existing_properties, ensure_ascii=False, indent=2),
            "ACTIVE_RELATION_TYPES": json.dumps(active_rel_types, ensure_ascii=False, indent=2),
            "EXISTING_PERSON_RELATIONS": json.dumps(existing_relations, ensure_ascii=False, indent=2),
        },
    )

    response = llm_client.generate_llm_response(
        provider=config.MAKE_TODAY_TARGET_PROVIDER,
        model=config.MAKE_TODAY_TARGET_MODEL,
        prompt=rendered_prompt,
        temperature=0.1,
        max_tokens=16384,
    )

    cleaned_response = response.strip()
    if cleaned_response.startswith("```"):
        lines = cleaned_response.splitlines()
        if len(lines) >= 2 and lines[-1].strip().startswith("```"):
            cleaned_response = "\n".join(lines[1:-1])

    try:
        data = json.loads(cleaned_response)
    except json.JSONDecodeError as e:
        logger.error("Failed to decode JSON from candidate extraction response: %s", e)
        raise ValueError(f"Invalid JSON response from candidate extraction LLM: {e}") from e

    raw_prop_cands = data.get("property_candidates") or []
    raw_rel_cands = data.get("relation_candidates") or []

    # 検証と構築
    valid_prop_cands = _validate_and_build_property_candidates(
        raw_prop_cands, summary_id, confirmed_person_ids, people_map, db_defs, existing_properties
    )
    valid_rel_cands = _validate_and_build_relation_candidates(
        raw_rel_cands, summary_id, confirmed_person_ids, people_map, active_rel_types, existing_relations
    )

    # 最大5件制限
    valid_prop_cands = valid_prop_cands[:5]
    valid_rel_cands = valid_rel_cands[:5]

    total_candidates = len(valid_prop_cands) + len(valid_rel_cands)
    if total_candidates == 0:
        logger.info("No valid candidates extracted for summary %s. No HITL Run created.", summary_id)
        return None

    # HITL 質問の構築
    questions_data = []
    seq = 0

    for cand in valid_prop_cands:
        q_key = cand["candidate_key"]
        p_name = cand["person_name"]
        def_name = cand["property_display_name"]
        op = cand["operation"]
        op_label = {"create": "新規作成", "update": "更新", "delete": "削除"}.get(op, op)

        questions_data.append({
            "question_key": q_key,
            "question_type": "select",
            "display_text": f"【属性{op_label}】{p_name} の「{def_name}」",
            "title": f"属性{op_label}: {p_name}（{def_name}）",
            "prompt": f"{p_name} の属性「{def_name}」を{op_label}しますか？",
            "choices": [
                {"value": "apply", "label": "適用"},
                {"value": "skip", "label": "見送り"},
            ],
            "is_required": 1,
            "sequence": seq,
            "context_json": cand,
        })
        seq += 1

    for cand in valid_rel_cands:
        q_key = cand["candidate_key"]
        s_name = cand["subject_person_name"]
        o_name = cand["object_person_name"]
        rel_label = cand["relation_type_forward_label"]
        op = cand["operation"]
        op_label = {"create": "新規作成", "update": "更新", "delete": "削除"}.get(op, op)

        questions_data.append({
            "question_key": q_key,
            "question_type": "select",
            "display_text": f"【関係{op_label}】{s_name} → {o_name}（{rel_label}）",
            "title": f"関係{op_label}: {s_name} → {o_name}",
            "prompt": f"{s_name} と {o_name} の関係「{rel_label}」を{op_label}しますか？",
            "choices": [
                {"value": "apply", "label": "適用"},
                {"value": "skip", "label": "見送り"},
            ],
            "is_required": 1,
            "sequence": seq,
            "context_json": cand,
        })
        seq += 1

    checkpoint_data = {
        "summary_id": summary_id,
        "date_str": date_str,
        "applied_candidate_keys": [],
        "skipped_candidate_keys": [],
    }

    title_str = f"{date_str} 日次人物変更候補"

    register_run_and_questions(
        run_id=run_id,
        handler="summary.apply_person_candidates",
        checkpoint=json.dumps(checkpoint_data, ensure_ascii=False),
        question_set_id="set_1",
        questions_data=questions_data,
        conn=conn,
        title=title_str,
        description=f"{date_str} の日次要約から抽出された人物属性・関係の変更候補です。",
        display_type="daily_person_changes",
    )

    logger.info("Successfully registered HITL Run %s with %d candidates for summary %s", run_id, total_candidates, summary_id)
    return run_id


def _validate_and_build_property_candidates(
    raw_cands: List[Dict[str, Any]],
    summary_id: str,
    confirmed_person_ids: set[str],
    people_map: Dict[str, str],
    db_defs: List[Dict[str, Any]],
    existing_properties: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    defs_map = {d["property_definition_id"]: d for d in db_defs}
    props_map = {p["property_value_id"]: p for p in existing_properties}

    valid_cands = []
    for idx, c in enumerate(raw_cands):
        if not isinstance(c, dict):
            continue

        op = c.get("operation")
        if op not in ("create", "update", "delete"):
            continue

        pid = c.get("person_id")
        def_id = c.get("property_definition_id")
        val_id = c.get("property_value_id")

        if pid not in confirmed_person_ids or def_id not in defs_map:
            continue

        defn = defs_map[def_id]

        if op in ("update", "delete"):
            if not val_id or val_id not in props_map:
                continue
            curr_prop = props_map[val_id]
            if curr_prop["person_id"] != pid or curr_prop["property_definition_id"] != def_id:
                continue
            snapshot = curr_prop
        else:
            snapshot = None

        after_val = c.get("after")
        if op == "delete":
            after_state = None
        else:
            if not isinstance(after_val, dict):
                continue
            v = after_val.get("value")
            if v is None or (isinstance(v, str) and not v.strip()):
                continue
            # Select option validation if select type
            if defn["data_type"] == "select":
                opt_keys = {opt["option_key"] for opt in defn.get("options") or []}
                if v not in opt_keys:
                    continue
            after_state = {
                "value": v,
                "valid_from": after_val.get("valid_from"),
                "valid_until": after_val.get("valid_until"),
                "note": after_val.get("note"),
            }

        quote = c.get("quote") or ""
        reason = c.get("reason") or ""

        cand_obj = {
            "candidate_type": "property",
            "candidate_key": f"cand_attr_{idx}",
            "operation": op,
            "summary_id": summary_id,
            "person_id": pid,
            "person_name": people_map.get(pid, pid),
            "property_definition_id": def_id,
            "property_key": defn["key"],
            "property_display_name": defn["display_name"],
            "property_value_id": val_id,
            "before": c.get("before") if op in ("update", "delete") else None,
            "after": after_state,
            "quote": str(quote),
            "reason": str(reason),
            "snapshot": snapshot,
        }
        valid_cands.append(cand_obj)

    return valid_cands


def _validate_and_build_relation_candidates(
    raw_cands: List[Dict[str, Any]],
    summary_id: str,
    confirmed_person_ids: set[str],
    people_map: Dict[str, str],
    active_rel_types: List[Dict[str, Any]],
    existing_relations: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    types_map = {t["relation_type_id"]: t for t in active_rel_types}
    rels_map = {r["relation_id"]: r for r in existing_relations}

    valid_cands = []
    for idx, c in enumerate(raw_cands):
        if not isinstance(c, dict):
            continue

        op = c.get("operation")
        if op not in ("create", "update", "delete"):
            continue

        subj_id = c.get("subject_person_id")
        obj_id = c.get("object_person_id")
        rel_type_id = c.get("relation_type_id")
        rel_id = c.get("relation_id")

        if subj_id not in confirmed_person_ids or obj_id not in confirmed_person_ids:
            continue
        if subj_id == obj_id:
            # Self-relation forbidden
            continue
        if rel_type_id not in types_map:
            continue

        rel_type = types_map[rel_type_id]

        if op in ("update", "delete"):
            if not rel_id or rel_id not in rels_map:
                continue
            curr_rel = rels_map[rel_id]
            if curr_rel["relation_type_id"] != rel_type_id:
                continue

            if rel_type.get("directionality") == "symmetric":
                endpoints_match = (
                    (curr_rel["subject_person_id"] == subj_id and curr_rel["object_person_id"] == obj_id) or
                    (curr_rel["subject_person_id"] == obj_id and curr_rel["object_person_id"] == subj_id)
                )
            else:
                endpoints_match = (
                    curr_rel["subject_person_id"] == subj_id and curr_rel["object_person_id"] == obj_id
                )

            if not endpoints_match:
                continue
            snapshot = curr_rel
        else:
            snapshot = None

        after_val = c.get("after")
        if op == "delete":
            after_state = None
        else:
            if not isinstance(after_val, dict):
                continue
            after_state = {
                "started_on": after_val.get("started_on"),
                "ended_on": after_val.get("ended_on"),
                "note": after_val.get("note"),
            }

        quote = c.get("quote") or ""
        reason = c.get("reason") or ""

        cand_obj = {
            "candidate_type": "relation",
            "candidate_key": f"cand_rel_{idx}",
            "operation": op,
            "summary_id": summary_id,
            "subject_person_id": subj_id,
            "subject_person_name": people_map.get(subj_id, subj_id),
            "object_person_id": obj_id,
            "object_person_name": people_map.get(obj_id, obj_id),
            "relation_type_id": rel_type_id,
            "relation_type_slug": rel_type["slug"],
            "relation_type_forward_label": rel_type["forward_label"],
            "relation_type_reverse_label": rel_type["reverse_label"],
            "relation_id": rel_id,
            "before": c.get("before") if op in ("update", "delete") else None,
            "after": after_state,
            "quote": str(quote),
            "reason": str(reason),
            "snapshot": snapshot,
        }
        valid_cands.append(cand_obj)

    return valid_cands
