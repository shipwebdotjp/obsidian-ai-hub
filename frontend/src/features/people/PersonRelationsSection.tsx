import React, { useEffect, useMemo, useState } from "react";
import { Person } from "../../api/types";
import { PersonDetail, PersonRelation, RelationStatus } from "./types";
import RelationEvidenceSection from "./RelationEvidenceSection";

interface PersonRelationsSectionProps {
  currentPerson: PersonDetail;
  relations: PersonRelation[];
  peopleList: Person[];
  statusFilter: RelationStatus | "all";
  onStatusFilterChange: (status: RelationStatus | "all") => void;
  onOpenCreateModal: () => void;
  onOpenEditModal: (relation: PersonRelation) => void;
  onDeleteRelation: (relationId: string) => Promise<void>;
}

const STATUS_GROUPS: { key: RelationStatus; label: string; badgeColor: string }[] = [
  { key: "active", label: "継続中 (Active)", badgeColor: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  { key: "upcoming", label: "開始前 (Upcoming)", badgeColor: "bg-blue-50 text-blue-700 border-blue-200" },
  { key: "undated", label: "期間不明 (Undated)", badgeColor: "bg-purple-50 text-purple-700 border-purple-200" },
  { key: "ended", label: "終了 (Ended)", badgeColor: "bg-slate-100 text-slate-600 border-slate-200" },
];

export default function PersonRelationsSection({
  currentPerson,
  relations,
  peopleList,
  statusFilter,
  onStatusFilterChange,
  onOpenCreateModal,
  onOpenEditModal,
  onDeleteRelation,
}: PersonRelationsSectionProps) {
  const [expandedRelationIds, setExpandedRelationIds] = useState<Set<string>>(new Set());
  const [deletingIds, setDeletingIds] = useState<Set<string>>(new Set());

  // Drop expanded/deleting state from previously viewed persons.
  useEffect(() => {
    setExpandedRelationIds(new Set());
    setDeletingIds(new Set());
  }, [currentPerson.person_id]);

  const handleDeleteClick = (relationId: string) => {
    if (deletingIds.has(relationId)) return;
    // Confirm before acquiring the lock so a cancelled delete never
    // flickers the button into the disabled state.
    if (!window.confirm("この人物間関係を削除しますか？この操作は取り消せません。")) return;
    setDeletingIds((prev) => new Set(prev).add(relationId));
    void onDeleteRelation(relationId).finally(() =>
      setDeletingIds((prev) => {
        const next = new Set(prev);
        next.delete(relationId);
        return next;
      })
    );
  };

  const toggleExpand = (relationId: string) => {
    setExpandedRelationIds((prev) => {
      const next = new Set(prev);
      if (next.has(relationId)) {
        next.delete(relationId);
      } else {
        next.add(relationId);
      }
      return next;
    });
  };

  const peopleMap = useMemo(() => {
    const map = new Map<string, Person>();
    peopleList.forEach((p) => map.set(p.person_id, p));
    return map;
  }, [peopleList]);

  // Filtered relations
  const displayedRelations =
    statusFilter === "all"
      ? relations
      : relations.filter((r) => r.status === statusFilter);

  return (
    <div className="space-y-4 border-t border-slate-100 pt-6 mt-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-bold text-slate-800">人物間関係 (Relations)</h3>
          <p className="text-xs text-slate-500">
            「{currentPerson.display_name}」に関連する人物間リレーションの一覧です。
          </p>
        </div>
        <div className="flex items-center gap-2">
          {/* Status Filter Dropdown */}
          <select
            value={statusFilter}
            onChange={(e) => onStatusFilterChange(e.target.value as RelationStatus | "all")}
            className="rounded border border-slate-300 p-1.5 text-xs text-slate-700 focus:ring-2 focus:ring-slate-800 focus:outline-none"
            aria-label="状態フィルター"
          >
            <option value="all">すべての状態 ({relations.length})</option>
            <option value="active">継続中 (Active)</option>
            <option value="upcoming">開始前 (Upcoming)</option>
            <option value="undated">期間不明 (Undated)</option>
            <option value="ended">終了 (Ended)</option>
          </select>

          <button
            onClick={onOpenCreateModal}
            className="rounded bg-slate-800 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-700 cursor-pointer"
          >
            ＋ 関係を追加
          </button>
        </div>
      </div>

      {displayedRelations.length === 0 ? (
        <div className="p-6 text-center text-xs text-slate-400 border border-slate-200 rounded-xl bg-slate-50/50">
          該当する人物間関係はありません。
        </div>
      ) : (
        <div className="space-y-6">
          {STATUS_GROUPS.map((group) => {
            const groupRelations = displayedRelations.filter((r) => r.status === group.key);
            if (groupRelations.length === 0) return null;

            return (
              <div key={group.key} className="space-y-2">
                <div className="flex items-center gap-2">
                  <span className={`px-2 py-0.5 text-[11px] font-bold rounded border ${group.badgeColor}`}>
                    {group.label}
                  </span>
                  <span className="text-xs font-bold text-slate-500">({groupRelations.length}件)</span>
                </div>

                <div className="bg-white border border-slate-200 rounded-xl divide-y divide-slate-100 shadow-sm overflow-hidden">
                  {groupRelations.map((rel) => {
                    const isSubject = rel.subject_person_id === currentPerson.person_id;
                    const otherPersonId = isSubject ? rel.object_person_id : rel.subject_person_id;
                    const otherPerson = peopleMap.get(otherPersonId);
                    const otherPersonName = otherPerson ? otherPerson.display_name : "不明な人物";

                    const labelText = isSubject
                      ? rel.relation_type?.forward_label || "関係あり"
                      : rel.relation_type?.reverse_label || "関係あり";

                    const isExpanded = expandedRelationIds.has(rel.relation_id);

                    return (
                      <div key={rel.relation_id} className="p-3 hover:bg-slate-50/50 transition-colors">
                        <div className="flex flex-wrap items-start justify-between gap-2">
                          <div className="space-y-1">
                            <div className="flex items-center gap-1.5 text-xs font-bold text-slate-900">
                              <span className="text-slate-600 font-semibold">{labelText}</span>
                              <span className="text-slate-400">—</span>
                              <span className="text-slate-900 font-bold underline decoration-slate-300" title={otherPerson ? undefined : otherPersonId}>
                                {otherPersonName}
                              </span>
                            </div>

                            <div className="flex flex-wrap items-center gap-3 text-[11px] text-slate-500">
                              {(rel.started_on || rel.ended_on) ? (
                                <div>
                                  期間: {rel.started_on || "未指定"} ～ {rel.ended_on || "現在"}
                                </div>
                              ) : (
                                <div>期間: 未設定</div>
                              )}
                              {rel.note && <div>メモ: {rel.note}</div>}
                            </div>
                          </div>

                          <div className="flex items-center gap-2 shrink-0">
                            <button
                              onClick={() => toggleExpand(rel.relation_id)}
                              className="px-2.5 py-1 text-xs font-medium text-slate-600 bg-slate-100 hover:bg-slate-200 rounded cursor-pointer border border-slate-200"
                            >
                              根拠 ({rel.evidence ? rel.evidence.length : 0}) {isExpanded ? "▲" : "▼"}
                            </button>
                            <button
                              onClick={() => onOpenEditModal(rel)}
                              className="px-2.5 py-1 text-xs font-semibold text-slate-700 border border-slate-300 bg-white hover:bg-slate-100 rounded cursor-pointer"
                            >
                              編集
                            </button>
                            <button
                              onClick={() => handleDeleteClick(rel.relation_id)}
                              disabled={deletingIds.has(rel.relation_id)}
                              className="px-2.5 py-1 text-xs font-semibold text-rose-700 border border-rose-200 bg-rose-50 hover:bg-rose-100 disabled:opacity-50 rounded cursor-pointer"
                            >
                              削除
                            </button>
                          </div>
                        </div>

                        {/* Expanded Evidence Section */}
                        {isExpanded && (
                          <div className="mt-3 pt-3 border-t border-slate-100">
                            <RelationEvidenceSection evidence={rel.evidence || []} />
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
