import React, { useState, useEffect } from "react";
import PersonCombobox from "./PersonCombobox";
import { Person } from "../../api/types";
import {
  PersonRelation,
  PersonRelationEvidence,
  PersonRelationType,
  PersonRelationCreateRequest,
  PersonRelationUpdateRequest,
  PersonRelationEvidenceCreateRequest,
  PersonRelationEvidenceUpdateRequest,
} from "./types";

interface RelationFormModalProps {
  currentPersonId: string;
  relationToEdit: PersonRelation | null;
  types: PersonRelationType[];
  peopleList: Person[];
  onClose: () => void;
  onCreate: (req: PersonRelationCreateRequest) => Promise<void>;
  onUpdate: (relationId: string, req: PersonRelationUpdateRequest) => Promise<void>;
  onAddEvidence: (relationId: string, req: PersonRelationEvidenceCreateRequest) => Promise<void>;
  onUpdateEvidence: (evidenceId: string, req: PersonRelationEvidenceUpdateRequest) => Promise<void>;
  onDeleteEvidence: (evidenceId: string) => Promise<void>;
}

export default function RelationFormModal({
  currentPersonId,
  relationToEdit,
  types,
  peopleList,
  onClose,
  onCreate,
  onUpdate,
  onAddEvidence,
  onUpdateEvidence,
  onDeleteEvidence,
}: RelationFormModalProps) {
  const isEditing = Boolean(relationToEdit);

  // Filter active types for dropdown, but keep the current type if editing
  const activeTypes = types.filter(
    (t) => t.is_active || (relationToEdit && t.relation_type_id === relationToEdit.relation_type_id)
  );

  // Relation Form States
  const [selectedTypeId, setSelectedTypeId] = useState(
    relationToEdit ? relationToEdit.relation_type_id : activeTypes[0]?.relation_type_id || ""
  );
  const [subjectPersonId, setSubjectPersonId] = useState(
    relationToEdit ? relationToEdit.subject_person_id : currentPersonId
  );
  const [objectPersonId, setObjectPersonId] = useState(
    relationToEdit
      ? relationToEdit.object_person_id
      : peopleList.find((p) => p.person_id !== currentPersonId)?.person_id || ""
  );
  const [startedOn, setStartedOn] = useState(relationToEdit?.started_on || "");
  const [endedOn, setEndedOn] = useState(relationToEdit?.ended_on || "");
  const [note, setNote] = useState(relationToEdit?.note || "");

  // Initial Evidence State (only during create)
  const [evQuote, setEvQuote] = useState("");
  const [evSourceRef, setEvSourceRef] = useState("");
  const [evNote, setEvNote] = useState("");
  const [evObservedAt, setEvObservedAt] = useState("");

  // New Evidence Form State (during edit mode)
  const [showAddEvidenceForm, setShowAddEvidenceForm] = useState(false);
  const [newEvQuote, setNewEvQuote] = useState("");
  const [newEvSourceRef, setNewEvSourceRef] = useState("");
  const [newEvNote, setNewEvNote] = useState("");
  const [newEvObservedAt, setNewEvObservedAt] = useState("");

  // Editing Evidence Item State
  const [editingEvidenceId, setEditingEvidenceId] = useState<string | null>(null);
  const [editEvQuote, setEditEvQuote] = useState("");
  const [editEvSourceRef, setEditEvSourceRef] = useState("");
  const [editEvNote, setEditEvNote] = useState("");
  const [editEvObservedAt, setEditEvObservedAt] = useState("");

  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [evidenceSubmitting, setEvidenceSubmitting] = useState(false);

  useEffect(() => {
    if (relationToEdit) {
      setSelectedTypeId(relationToEdit.relation_type_id);
      setSubjectPersonId(relationToEdit.subject_person_id);
      setObjectPersonId(relationToEdit.object_person_id);
      setStartedOn(relationToEdit.started_on || "");
      setEndedOn(relationToEdit.ended_on || "");
      setNote(relationToEdit.note || "");
    } else {
      // Fill defaults when types/people arrive after mount; never overwrite user input.
      if (!selectedTypeId && activeTypes.length > 0) {
        setSelectedTypeId(activeTypes[0].relation_type_id);
      }
      if (!subjectPersonId) {
        setSubjectPersonId(currentPersonId);
      }
      if (!objectPersonId) {
        const fallback = peopleList.find((p) => p.person_id !== currentPersonId)?.person_id || "";
        if (fallback) setObjectPersonId(fallback);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [relationToEdit, types, currentPersonId, peopleList]);

  const selectedType = types.find((t) => t.relation_type_id === selectedTypeId);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);

    if (!isEditing) {
      if (!selectedTypeId) {
        setFormError("関係タイプを選択してください。");
        return;
      }
      if (!subjectPersonId || !objectPersonId) {
        setFormError("両端点の人物を選択してください。");
        return;
      }
      if (subjectPersonId === objectPersonId) {
        setFormError("自分自身との関係（自己関係）を登録することはできません。");
        return;
      }
      if (subjectPersonId !== currentPersonId && objectPersonId !== currentPersonId) {
        setFormError("いずれか一方の端点に現在表示中の人物を含めてください。");
        return;
      }
    }

    if (startedOn && endedOn && startedOn > endedOn) {
      setFormError("開始日は終了日以前である必要があります。");
      return;
    }

    setSubmitting(true);
    try {
      if (isEditing && relationToEdit) {
        await onUpdate(relationToEdit.relation_id, {
          started_on: startedOn.trim() || null,
          ended_on: endedOn.trim() || null,
          note: note.trim() || null,
        });
      } else {
        const initialEvList: PersonRelationEvidenceCreateRequest[] = [];
        if (evQuote.trim() || evSourceRef.trim() || evNote.trim() || evObservedAt.trim()) {
          initialEvList.push({
            source_type: "manual",
            quote: evQuote.trim() || null,
            source_ref: evSourceRef.trim() || null,
            note: evNote.trim() || null,
            observed_at: evObservedAt.trim() || null,
          });
        }

        await onCreate({
          subject_person_id: subjectPersonId,
          object_person_id: objectPersonId,
          relation_type_id: selectedTypeId,
          started_on: startedOn.trim() || null,
          ended_on: endedOn.trim() || null,
          note: note.trim() || null,
          initial_evidence: initialEvList,
        });
      }
      onClose();
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : "関係の保存に失敗しました。");
    } finally {
      setSubmitting(false);
    }
  };

  const handleCreateNewEvidence = async () => {
    if (!relationToEdit || evidenceSubmitting) return;
    if (!newEvQuote.trim() && !newEvSourceRef.trim() && !newEvNote.trim() && !newEvObservedAt.trim()) {
      setFormError("根拠を登録するにはいずれかの項目を入力してください。");
      return;
    }
    setFormError(null);
    setEvidenceSubmitting(true);
    try {
      await onAddEvidence(relationToEdit.relation_id, {
        source_type: "manual",
        quote: newEvQuote.trim() || null,
        source_ref: newEvSourceRef.trim() || null,
        note: newEvNote.trim() || null,
        observed_at: newEvObservedAt.trim() || null,
      });
      setShowAddEvidenceForm(false);
      setNewEvQuote("");
      setNewEvSourceRef("");
      setNewEvNote("");
      setNewEvObservedAt("");
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : "根拠の追加に失敗しました。");
    } finally {
      setEvidenceSubmitting(false);
    }
  };

  const startEditEvidence = (ev: PersonRelationEvidence) => {
    setEditingEvidenceId(ev.evidence_id);
    setEditEvQuote(ev.quote || "");
    setEditEvSourceRef(ev.source_ref || "");
    setEditEvNote(ev.note || "");
    setEditEvObservedAt(ev.observed_at || "");
  };

  const handleSaveEditedEvidence = async (evidenceId: string) => {
    if (evidenceSubmitting) return;
    setFormError(null);
    setEvidenceSubmitting(true);
    try {
      await onUpdateEvidence(evidenceId, {
        quote: editEvQuote.trim() || null,
        source_ref: editEvSourceRef.trim() || null,
        note: editEvNote.trim() || null,
        observed_at: editEvObservedAt.trim() || null,
      });
      setEditingEvidenceId(null);
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : "根拠の更新に失敗しました。");
    } finally {
      setEvidenceSubmitting(false);
    }
  };

  const handleDeleteEvidenceClick = async (evidenceId: string) => {
    if (evidenceSubmitting) return;
    if (!window.confirm("この根拠を削除しますか？この操作は取り消せません。")) return;
    setFormError(null);
    setEvidenceSubmitting(true);
    try {
      await onDeleteEvidence(evidenceId);
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : "根拠の削除に失敗しました。");
    } finally {
      setEvidenceSubmitting(false);
    }
  };

  // Helper labels for subject / object display
  const subjectPerson = peopleList.find((p) => p.person_id === subjectPersonId);
  const objectPerson = peopleList.find((p) => p.person_id === objectPersonId);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-sm p-4 overflow-y-auto">
      <div className="bg-white rounded-xl border border-slate-200 shadow-xl max-w-lg w-full my-8 overflow-hidden flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="p-4 border-b border-slate-100 bg-slate-50 flex justify-between items-center shrink-0">
          <h3 className="text-sm font-bold text-slate-800">
            {isEditing ? "関係の編集" : "新規関係の作成"}
          </h3>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600 text-xs cursor-pointer"
          >
            ✕
          </button>
        </div>

        {/* Body */}
        <div className="p-5 overflow-y-auto space-y-4 text-xs">
          {formError && (
            <div className="p-3 bg-red-50 border border-red-200 text-red-700 rounded-lg">
              {formError}
            </div>
          )}

          <form id="relation-form" onSubmit={handleSubmit} className="space-y-4">
            {!isEditing ? (
              <>
                {/* Relation Type Selection */}
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">
                    関係タイプ <span className="text-red-500">*</span>
                  </label>
                  {activeTypes.length === 0 ? (
                    <p className="text-[11px] text-slate-500">
                      有効な関係タイプがありません。先に「関係タイプ」タブでタイプを作成・有効化してください。
                    </p>
                  ) : (
                    <select
                      value={selectedTypeId}
                      onChange={(e) => setSelectedTypeId(e.target.value)}
                      className="w-full rounded border border-slate-300 p-2 text-xs focus:ring-2 focus:ring-slate-800 focus:outline-none"
                      required
                    >
                      {activeTypes.map((t) => (
                        <option key={t.relation_type_id} value={t.relation_type_id}>
                          {t.forward_label} / {t.reverse_label} ({t.slug})
                        </option>
                      ))}
                    </select>
                  )}
                </div>

                {/* Endpoints Selection */}
                <div className="p-3 bg-slate-50 border border-slate-200 rounded-lg space-y-3">
                  <div className="font-semibold text-slate-800">
                    両端点の選択（
                    {selectedType?.directionality === "directed"
                      ? "有向: 発信側 → 受信側"
                      : "対称: 端点A ⇄ 端点B"}
                    ）
                  </div>

                  {selectedType?.directionality === "directed" ? (
                    <div className="space-y-3">
                      <div>
                        <label className="block text-[11px] font-semibold text-slate-600 mb-1">
                          発信側人物（主語: 「<strong>{selectedType.forward_label}</strong>」側）
                        </label>
                        <PersonCombobox
                          people={peopleList}
                          value={subjectPersonId}
                          onChange={setSubjectPersonId}
                          placeholder="発信人物を選択..."
                        />
                      </div>
                      <div>
                        <label className="block text-[11px] font-semibold text-slate-600 mb-1">
                          受信側人物（目的語: 「<strong>{selectedType.reverse_label}</strong>」側）
                        </label>
                        <PersonCombobox
                          people={peopleList}
                          value={objectPersonId}
                          onChange={setObjectPersonId}
                          placeholder="相手人物を選択..."
                        />
                      </div>
                    </div>
                  ) : (
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <label className="block text-[11px] font-semibold text-slate-600 mb-1">
                          人物 A
                        </label>
                        <PersonCombobox
                          people={peopleList}
                          value={subjectPersonId}
                          onChange={setSubjectPersonId}
                          placeholder="人物Aを選択..."
                        />
                      </div>
                      <div>
                        <label className="block text-[11px] font-semibold text-slate-600 mb-1">
                          人物 B
                        </label>
                        <PersonCombobox
                          people={peopleList}
                          value={objectPersonId}
                          onChange={setObjectPersonId}
                          placeholder="人物Bを選択..."
                        />
                      </div>
                    </div>
                  )}

                  {subjectPerson && objectPerson && (
                    <div className="text-[11px] text-slate-600 pt-1 border-t border-slate-200">
                      構造プレビュー:{" "}
                      <strong className="text-slate-900">{subjectPerson.display_name}</strong>{" "}
                      {selectedType?.directionality === "symmetric" ? "⇄" : "—"}{" "}
                      {selectedType?.forward_label}{" "}
                      {selectedType?.directionality === "symmetric" ? "⇄" : "→"}{" "}
                      <strong className="text-slate-900">{objectPerson.display_name}</strong>
                    </div>
                  )}
                </div>
              </>
            ) : (
              <div className="p-3 bg-slate-50 border border-slate-200 rounded-lg text-slate-700 space-y-1">
                <div>
                  関係タイプ:{" "}
                  <strong className="text-slate-900">
                    {relationToEdit?.relation_type?.forward_label} / {relationToEdit?.relation_type?.reverse_label}
                  </strong>{" "}
                  (<span className="font-mono text-slate-600">{relationToEdit?.relation_type?.slug}</span>)
                </div>
                <div>
                  端点構造:{" "}
                  <strong className="text-slate-900">
                    {peopleList.find((p) => p.person_id === relationToEdit?.subject_person_id)?.display_name}
                  </strong>{" "}
                  →{" "}
                  <strong className="text-slate-900">
                    {peopleList.find((p) => p.person_id === relationToEdit?.object_person_id)?.display_name}
                  </strong>
                </div>
                <p className="text-[11px] text-slate-400 mt-1">※ 両端点および関係タイプは作成後変更できません。</p>
              </div>
            )}

            {/* Dates */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block font-semibold text-slate-700 mb-1">
                  開始日 (started_on)
                </label>
                <input
                  type="date"
                  value={startedOn}
                  onChange={(e) => setStartedOn(e.target.value)}
                  className="w-full rounded border border-slate-300 p-2 text-xs focus:ring-2 focus:ring-slate-800 focus:outline-none"
                />
              </div>
              <div>
                <label className="block font-semibold text-slate-700 mb-1">
                  終了日 (ended_on)
                </label>
                <input
                  type="date"
                  value={endedOn}
                  onChange={(e) => setEndedOn(e.target.value)}
                  className="w-full rounded border border-slate-300 p-2 text-xs focus:ring-2 focus:ring-slate-800 focus:outline-none"
                />
              </div>
            </div>

            {/* Note */}
            <div>
              <label className="block font-semibold text-slate-700 mb-1">メモ (note)</label>
              <textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="関係についての補足説明メモ"
                rows={2}
                className="w-full rounded border border-slate-300 p-2 text-xs focus:ring-2 focus:ring-slate-800 focus:outline-none"
              />
            </div>

            {/* Initial Evidence input during creation */}
            {!isEditing && (
              <div className="border border-slate-200 rounded-lg p-3 bg-slate-50/50 space-y-2">
                <div className="font-semibold text-slate-800">初期根拠 (Evidence - 任意)</div>
                <div>
                  <label className="block text-[11px] text-slate-600 mb-0.5">引用文 (quote)</label>
                  <input
                    type="text"
                    value={evQuote}
                    onChange={(e) => setEvQuote(e.target.value)}
                    placeholder="根拠となる引用文"
                    className="w-full rounded border border-slate-300 p-1.5 text-xs bg-white"
                  />
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="block text-[11px] text-slate-600 mb-0.5">参照先 (source_ref)</label>
                    <input
                      type="text"
                      value={evSourceRef}
                      onChange={(e) => setEvSourceRef(e.target.value)}
                      placeholder="ノート名やURL"
                      className="w-full rounded border border-slate-300 p-1.5 text-xs bg-white"
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] text-slate-600 mb-0.5">観測日 (observed_at)</label>
                    <input
                      type="date"
                      value={evObservedAt}
                      onChange={(e) => setEvObservedAt(e.target.value)}
                      className="w-full rounded border border-slate-300 p-1.5 text-xs bg-white"
                    />
                  </div>
                </div>
                <div>
                  <label className="block text-[11px] text-slate-600 mb-0.5">補足メモ</label>
                  <input
                    type="text"
                    value={evNote}
                    onChange={(e) => setEvNote(e.target.value)}
                    placeholder="根拠に関する補足"
                    className="w-full rounded border border-slate-300 p-1.5 text-xs bg-white"
                  />
                </div>
              </div>
            )}
          </form>

          {/* Evidence Management Section during EDIT mode */}
          {isEditing && relationToEdit && (
            <div className="border-t border-slate-200 pt-4 space-y-3">
              <div className="flex items-center justify-between">
                <h4 className="font-bold text-slate-800">根拠 (Evidence) 一覧</h4>
                {!showAddEvidenceForm && (
                  <button
                    type="button"
                    onClick={() => setShowAddEvidenceForm(true)}
                    className="px-2.5 py-1 text-xs font-semibold text-slate-700 bg-slate-100 border border-slate-300 rounded hover:bg-slate-200 cursor-pointer"
                  >
                    ＋ 根拠を追加
                  </button>
                )}
              </div>

              {/* Add New Evidence Form */}
              {showAddEvidenceForm && (
                <div className="p-3 bg-blue-50/50 border border-blue-200 rounded-lg space-y-2">
                  <div className="font-bold text-blue-900 text-xs">新規根拠の追加</div>
                  <div>
                    <label className="block text-[11px] text-slate-600 mb-0.5">引用文 (quote)</label>
                    <input
                      type="text"
                      value={newEvQuote}
                      onChange={(e) => setNewEvQuote(e.target.value)}
                      placeholder="根拠となる引用"
                      className="w-full rounded border border-slate-300 p-1.5 bg-white text-xs"
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label className="block text-[11px] text-slate-600 mb-0.5">参照先 (source_ref)</label>
                      <input
                        type="text"
                        value={newEvSourceRef}
                        onChange={(e) => setNewEvSourceRef(e.target.value)}
                        placeholder="参照元"
                        className="w-full rounded border border-slate-300 p-1.5 bg-white text-xs"
                      />
                    </div>
                    <div>
                      <label className="block text-[11px] text-slate-600 mb-0.5">観測日 (observed_at)</label>
                      <input
                        type="date"
                        value={newEvObservedAt}
                        onChange={(e) => setNewEvObservedAt(e.target.value)}
                        className="w-full rounded border border-slate-300 p-1.5 bg-white text-xs"
                      />
                    </div>
                  </div>
                  <div>
                    <label className="block text-[11px] text-slate-600 mb-0.5">補足メモ</label>
                    <input
                      type="text"
                      value={newEvNote}
                      onChange={(e) => setNewEvNote(e.target.value)}
                      placeholder="補足メモ"
                      className="w-full rounded border border-slate-300 p-1.5 bg-white text-xs"
                    />
                  </div>
                  <div className="flex justify-end gap-2 pt-1">
                    <button
                      type="button"
                      onClick={() => setShowAddEvidenceForm(false)}
                      className="px-3 py-1 rounded border border-slate-300 text-slate-700 bg-white hover:bg-slate-50 cursor-pointer"
                    >
                      キャンセル
                    </button>
                    <button
                      type="button"
                      onClick={handleCreateNewEvidence}
                      disabled={evidenceSubmitting}
                      className="px-3 py-1 rounded bg-blue-700 font-semibold text-white hover:bg-blue-800 disabled:opacity-50 cursor-pointer"
                    >
                      追加保存
                    </button>
                  </div>
                </div>
              )}

              {/* Evidence Items List */}
              {(relationToEdit.evidence || []).length === 0 ? (
                <p className="text-slate-400 italic text-[11px]">根拠データはありません。</p>
              ) : (
                <div className="space-y-2">
                  {(relationToEdit.evidence || []).map((ev) =>
                    editingEvidenceId === ev.evidence_id ? (
                      /* Edit Evidence Inline Form */
                      <div
                        key={ev.evidence_id}
                        className="p-3 bg-amber-50/60 border border-amber-200 rounded-lg space-y-2"
                      >
                        <div className="font-bold text-amber-900 text-xs">根拠の編集</div>
                        <div>
                          <label className="block text-[11px] text-slate-600 mb-0.5">引用文</label>
                          <input
                            type="text"
                            value={editEvQuote}
                            onChange={(e) => setEditEvQuote(e.target.value)}
                            className="w-full rounded border border-slate-300 p-1.5 bg-white text-xs"
                          />
                        </div>
                        <div className="grid grid-cols-2 gap-2">
                          <div>
                            <label className="block text-[11px] text-slate-600 mb-0.5">参照先</label>
                            <input
                              type="text"
                              value={editEvSourceRef}
                              onChange={(e) => setEditEvSourceRef(e.target.value)}
                              className="w-full rounded border border-slate-300 p-1.5 bg-white text-xs"
                            />
                          </div>
                          <div>
                            <label className="block text-[11px] text-slate-600 mb-0.5">観測日</label>
                            <input
                              type="date"
                              value={editEvObservedAt}
                              onChange={(e) => setEditEvObservedAt(e.target.value)}
                              className="w-full rounded border border-slate-300 p-1.5 bg-white text-xs"
                            />
                          </div>
                        </div>
                        <div>
                          <label className="block text-[11px] text-slate-600 mb-0.5">補足メモ</label>
                          <input
                            type="text"
                            value={editEvNote}
                            onChange={(e) => setEditEvNote(e.target.value)}
                            className="w-full rounded border border-slate-300 p-1.5 bg-white text-xs"
                          />
                        </div>
                        <div className="flex justify-end gap-2 pt-1">
                          <button
                            type="button"
                            onClick={() => setEditingEvidenceId(null)}
                            className="px-3 py-1 rounded border border-slate-300 text-slate-700 bg-white hover:bg-slate-50 cursor-pointer"
                          >
                            キャンセル
                          </button>
                          <button
                            type="button"
                            onClick={() => handleSaveEditedEvidence(ev.evidence_id)}
                            disabled={evidenceSubmitting}
                            className="px-3 py-1 rounded bg-amber-700 font-semibold text-white hover:bg-amber-800 disabled:opacity-50 cursor-pointer"
                          >
                            更新保存
                          </button>
                        </div>
                      </div>
                    ) : (
                      /* Display Evidence Row */
                      <div
                        key={ev.evidence_id}
                        className="p-2.5 bg-slate-50 border border-slate-200 rounded-lg flex items-start justify-between gap-2"
                      >
                        <div className="space-y-0.5 text-slate-700">
                          {ev.quote && <div className="italic text-slate-900">“{ev.quote}”</div>}
                          <div className="text-[11px] text-slate-500 flex flex-wrap gap-2">
                            {ev.source_ref && <span>参照: {ev.source_ref}</span>}
                            {ev.observed_at && <span>観測: {ev.observed_at}</span>}
                          </div>
                          {ev.note && <div className="text-slate-600 text-[11px]">メモ: {ev.note}</div>}
                        </div>
                        <div className="flex gap-1 shrink-0">
                          <button
                            type="button"
                            onClick={() => startEditEvidence(ev)}
                            className="px-2 py-0.5 text-[11px] font-semibold text-slate-700 hover:text-slate-900 border border-slate-300 bg-white rounded cursor-pointer"
                          >
                            編集
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDeleteEvidenceClick(ev.evidence_id)}
                            disabled={evidenceSubmitting}
                            className="px-2 py-0.5 text-[11px] font-semibold text-rose-700 hover:text-rose-900 border border-rose-200 bg-rose-50 rounded disabled:opacity-50 cursor-pointer"
                          >
                            削除
                          </button>
                        </div>
                      </div>
                    )
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-slate-100 bg-slate-50 flex items-center justify-end gap-2 shrink-0">
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-slate-300 bg-white px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 cursor-pointer"
          >
            キャンセル
          </button>
          <button
            type="submit"
            form="relation-form"
            disabled={submitting || (!isEditing && activeTypes.length === 0)}
            className="rounded bg-slate-800 px-4 py-2 text-xs font-semibold text-white hover:bg-slate-700 disabled:opacity-50 cursor-pointer"
          >
            {submitting ? "保存中..." : isEditing ? "関係を更新" : "関係を作成"}
          </button>
        </div>
      </div>
    </div>
  );
}
