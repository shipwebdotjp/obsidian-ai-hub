import json
import logging
from datetime import datetime
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

from obsidian_ai_hub.hitl.dispatcher import HitlContext, HitlResult
from obsidian_ai_hub.hitl.store import get_questions_by_set, get_run
from obsidian_ai_hub.web.services import person_properties, person_relations

logger = logging.getLogger(__name__)

JST = ZoneInfo("Asia/Tokyo")


def apply_person_candidates_handler(context: HitlContext) -> HitlResult:
    """
    HITL 承認済みの日次人物変更候補を個別の独立トランザクションで DB に適用する。
    - 候補ごとに承認時の現行状態と比較し、変更済みまたは再検証エラーの場合は該当候補のみ適用スキップし理由を記録する。
    - 承認したリレーションには source_type="manual", source_ref="summary:{summary_id}", quote=引用 で Evidence を追加する。
    """
    conn = context.conn
    run_record = get_run(context.run_id, conn=conn)
    if not run_record:
        return HitlResult.fail(f"Run {context.run_id} not found")

    active_set_id = run_record.get("active_question_set_id")
    if not active_set_id:
        return HitlResult.fail(f"Active question set missing for run {context.run_id}")

    questions = get_questions_by_set(context.run_id, active_set_id, conn=conn)

    applied_keys: List[str] = []
    skipped_keys: List[str] = []
    skip_details: Dict[str, str] = {}

    summary_id = ""

    for q in questions:
        q_key = q["question_key"]
        ans = context.answers_by_question_key.get(q_key)
        # raw answer or value
        if isinstance(ans, dict):
            ans_val = ans.get("value")
        else:
            ans_val = ans

        cand = q.get("context_json") or {}
        cand_type = cand.get("candidate_type")
        cand_summary_id = cand.get("summary_id") or ""
        if cand_summary_id:
            summary_id = cand_summary_id

        if ans_val != "apply":
            skipped_keys.append(q_key)
            skip_details[q_key] = "User selected '見送り' (skip)"
            continue

        # 適用処理 (候補ごとに独立したトランザクションで実行)
        try:
            with conn:
                cursor = conn.cursor()
                if cand_type == "property":
                    _apply_property_candidate(cursor, cand)
                elif cand_type == "relation":
                    _apply_relation_candidate(cursor, cand, summary_id)
                else:
                    raise ValueError(f"Unknown candidate type: {cand_type}")

            applied_keys.append(q_key)
            logger.info("Successfully applied candidate %s (type: %s) for run %s", q_key, cand_type, context.run_id)

        except Exception as e:
            logger.warning("Skipping candidate %s due to application failure / mismatch: %s", q_key, e)
            skipped_keys.append(q_key)
            skip_details[q_key] = f"Application skipped: {e}"

    # Checkpoint の更新
    raw_cp = context.checkpoint
    cp_data = {}
    if raw_cp:
        try:
            cp_data = json.loads(raw_cp)
        except (json.JSONDecodeError, TypeError):
            cp_data = {}

    cp_data["applied_candidate_keys"] = applied_keys
    cp_data["skipped_candidate_keys"] = skipped_keys
    cp_data["skip_details"] = skip_details
    cp_data["processed_at"] = datetime.now(JST).isoformat()

    return HitlResult.complete(checkpoint=json.dumps(cp_data, ensure_ascii=False))


def _apply_property_candidate(cursor: Any, cand: Dict[str, Any]) -> None:
    op = cand.get("operation")
    pid = cand.get("person_id")
    def_id = cand.get("property_definition_id")
    val_id = cand.get("property_value_id")
    snapshot = cand.get("snapshot")
    after = cand.get("after")

    # 人物存在確認
    cursor.execute("SELECT person_id FROM people WHERE person_id = ?", (pid,))
    if cursor.fetchone() is None:
        raise ValueError(f"Person {pid} no longer exists in DB")

    # 定義存在確認
    defn = person_properties.get_property_definition_by_id_in_tx(cursor, def_id)

    if op == "create":
        v = after.get("value") if after else None
        s_date = after.get("valid_from") if after else None
        e_date = after.get("valid_until") if after else None
        note = after.get("note") if after else None
        person_properties.create_person_property_value_in_tx(
            cursor,
            person_id=pid,
            property_definition_id=def_id,
            value=v,
            valid_from=s_date,
            valid_until=e_date,
            note=note,
            is_api_call=False,
        )

    elif op == "update":
        if not val_id:
            raise ValueError("property_value_id missing for update candidate")
        # 現行状態チェック
        cursor.execute(
            "SELECT property_value_id, person_id, property_definition_id, value_text, value_date, value_number, value_boolean, option_id, valid_from, valid_until, note FROM person_property_values WHERE property_value_id = ?",
            (val_id,),
        )
        curr_row = cursor.fetchone()
        if curr_row is None:
            raise ValueError(f"Property value {val_id} no longer exists")

        # Snapshot comparison (if present)
        if snapshot:
            if curr_row["person_id"] != snapshot.get("person_id") or curr_row["property_definition_id"] != snapshot.get("property_definition_id"):
                raise ValueError("Property value target changed")

        v = after.get("value") if after else None
        s_date = after.get("valid_from") if after else None
        e_date = after.get("valid_until") if after else None
        note = after.get("note") if after else None

        provided = ["value", "valid_from", "valid_until", "note"]
        person_properties.update_person_property_value_in_tx(
            cursor,
            property_value_id=val_id,
            value=v,
            valid_from=s_date,
            valid_until=e_date,
            note=note,
            provided=provided,
            is_api_call=False,
            expected_person_id=pid,
        )

    elif op == "delete":
        if not val_id:
            raise ValueError("property_value_id missing for delete candidate")
        person_properties.delete_person_property_value_in_tx(
            cursor,
            property_value_id=val_id,
            is_api_call=False,
            expected_person_id=pid,
        )
    else:
        raise ValueError(f"Unsupported property operation: {op}")


def _apply_relation_candidate(cursor: Any, cand: Dict[str, Any], summary_id: str) -> None:
    op = cand.get("operation")
    subj_id = cand.get("subject_person_id")
    obj_id = cand.get("object_person_id")
    rel_type_id = cand.get("relation_type_id")
    rel_id = cand.get("relation_id")
    snapshot = cand.get("snapshot")
    after = cand.get("after")
    quote = cand.get("quote") or ""

    # 端点存在確認
    cursor.execute("SELECT person_id FROM people WHERE person_id = ?", (subj_id,))
    if cursor.fetchone() is None:
        raise ValueError(f"Subject person {subj_id} no longer exists")
    cursor.execute("SELECT person_id FROM people WHERE person_id = ?", (obj_id,))
    if cursor.fetchone() is None:
        raise ValueError(f"Object person {obj_id} no longer exists")

    # Evidence データ準備
    ev_item = {
        "source_type": "manual",
        "source_ref": f"summary:{summary_id}" if summary_id else "summary",
        "quote": quote,
        "note": cand.get("reason") or None,
        "observed_at": None,
    }

    if op == "create":
        s_date = after.get("started_on") if after else None
        e_date = after.get("ended_on") if after else None
        note = after.get("note") if after else None

        res_rel, action = person_relations.create_person_relation_in_tx(
            cursor,
            subject_person_id=subj_id,
            object_person_id=obj_id,
            relation_type_id=rel_type_id,
            started_on=s_date,
            ended_on=e_date,
            note=note,
            initial_evidence=[ev_item],
        )

    elif op == "update":
        if not rel_id:
            raise ValueError("relation_id missing for update candidate")

        # 現行確認
        curr_rel = person_relations.get_person_relation_by_id_in_tx(cursor, rel_id)
        if snapshot:
            snapshot_type = snapshot.get("relation_type_id")
            snapshot_subj = snapshot.get("subject_person_id")
            snapshot_obj = snapshot.get("object_person_id")
            snapshot_s_date = snapshot.get("started_on")
            snapshot_e_date = snapshot.get("ended_on")
            snapshot_note = snapshot.get("note")

            curr_type = curr_rel.get("relation_type_id")
            curr_subj = curr_rel.get("subject_person_id")
            curr_obj = curr_rel.get("object_person_id")
            curr_s_date = curr_rel.get("started_on")
            curr_e_date = curr_rel.get("ended_on")
            curr_note = curr_rel.get("note")

            if (
                curr_type != snapshot_type or
                curr_subj != snapshot_subj or
                curr_obj != snapshot_obj or
                curr_s_date != snapshot_s_date or
                curr_e_date != snapshot_e_date or
                curr_note != snapshot_note
            ):
                raise ValueError("Relation target snapshot mismatch")

        s_date = after.get("started_on") if after else None
        e_date = after.get("ended_on") if after else None
        note = after.get("note") if after else None

        provided = ["started_on", "ended_on", "note"]
        res_rel, action = person_relations.update_person_relation_in_tx(
            cursor,
            relation_id=rel_id,
            started_on=s_date,
            ended_on=e_date,
            note=note,
            provided=provided,
        )

        # Evidence 追加
        now_iso = datetime.now(JST).isoformat()
        person_relations.deduplicate_and_add_evidence(
            cursor, res_rel["relation_id"], [ev_item], now_iso
        )

    elif op == "delete":
        if not rel_id:
            raise ValueError("relation_id missing for delete candidate")
        person_relations.delete_person_relation_in_tx(cursor, rel_id)

    else:
        raise ValueError(f"Unsupported relation operation: {op}")
