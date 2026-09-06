import React, { useState } from "react";
import { PersonRelationType, PersonRelationTypeCreateRequest, PersonRelationTypeUpdateRequest } from "./types";

interface RelationTypesTabProps {
  types: PersonRelationType[];
  loading: boolean;
  error: string | null;
  onCreateType: (req: PersonRelationTypeCreateRequest) => Promise<void>;
  onUpdateType: (relationTypeId: string, req: PersonRelationTypeUpdateRequest) => Promise<void>;
}

export default function RelationTypesTab({
  types,
  loading,
  error,
  onCreateType,
  onUpdateType,
}: RelationTypesTabProps) {
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [editingType, setEditingType] = useState<PersonRelationType | null>(null);

  // Form states for creation
  const [createSlug, setCreateSlug] = useState("");
  const [createForward, setCreateForward] = useState("");
  const [createReverse, setCreateReverse] = useState("");
  const [createDirectionality, setCreateDirectionality] = useState<"directed" | "symmetric">("directed");
  const [createDescription, setCreateDescription] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);
  const [submittingCreate, setSubmittingCreate] = useState(false);

  // Form states for editing
  const [editForward, setEditForward] = useState("");
  const [editReverse, setEditReverse] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [editIsActive, setEditIsActive] = useState(true);
  const [editError, setEditError] = useState<string | null>(null);
  const [submittingEdit, setSubmittingEdit] = useState(false);

  const openCreateModal = () => {
    setCreateSlug("");
    setCreateForward("");
    setCreateReverse("");
    setCreateDirectionality("directed");
    setCreateDescription("");
    setCreateError(null);
    setShowCreateModal(true);
  };

  const openEditModal = (t: PersonRelationType) => {
    setEditingType(t);
    setEditForward(t.forward_label);
    setEditReverse(t.reverse_label);
    setEditDescription(t.description || "");
    setEditIsActive(t.is_active);
    setEditError(null);
  };

  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreateError(null);
    if (!createSlug.trim() || !createForward.trim() || !createReverse.trim()) {
      setCreateError("識別スラグ、正方向ラベル、逆方向ラベルは必須です。");
      return;
    }
    setSubmittingCreate(true);
    try {
      await onCreateType({
        slug: createSlug.trim(),
        forward_label: createForward.trim(),
        reverse_label: createReverse.trim(),
        directionality: createDirectionality,
        description: createDescription.trim() || null,
      });
      setShowCreateModal(false);
    } catch (err: unknown) {
      setCreateError(err instanceof Error ? err.message : "関係タイプの作成に失敗しました。");
    } finally {
      setSubmittingCreate(false);
    }
  };

  const handleEditSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingType) return;
    setEditError(null);
    if (!editForward.trim() || !editReverse.trim()) {
      setEditError("正方向ラベル、逆方向ラベルは必須です。");
      return;
    }
    setSubmittingEdit(true);
    try {
      await onUpdateType(editingType.relation_type_id, {
        forward_label: editForward.trim(),
        reverse_label: editReverse.trim(),
        description: editDescription.trim() || null,
        is_active: editIsActive,
      });
      setEditingType(null);
    } catch (err: unknown) {
      setEditError(err instanceof Error ? err.message : "関係タイプの更新に失敗しました。");
    } finally {
      setSubmittingEdit(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-bold text-slate-800">関係タイプ管理</h2>
          <p className="text-xs text-slate-500">
            人物間で定義可能な関係の種類一覧です。非活性化されたタイプは新規関係作成の選択肢から除外されます。
          </p>
        </div>
        <button
          onClick={openCreateModal}
          className="rounded-lg bg-slate-800 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-700 cursor-pointer"
        >
          ＋ 新規関係タイプ
        </button>
      </div>

      {error && (
        <div className="p-3 bg-red-50 border border-red-200 text-red-700 text-xs rounded-lg">
          {error}
        </div>
      )}

      {loading ? (
        <div className="p-8 text-center text-xs text-slate-500">関係タイプを読み込み中...</div>
      ) : (
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-sm">
          <table className="w-full text-left text-xs text-slate-700">
            <thead className="bg-slate-50 border-b border-slate-200 text-slate-500 font-semibold">
              <tr>
                <th className="p-3">スラグ (slug)</th>
                <th className="p-3">正方向ラベル</th>
                <th className="p-3">逆方向ラベル</th>
                <th className="p-3">方向性</th>
                <th className="p-3">説明</th>
                <th className="p-3">状態</th>
                <th className="p-3 text-right">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {types.length === 0 ? (
                <tr>
                  <td colSpan={7} className="p-6 text-center text-slate-400">
                    登録されている関係タイプはありません。
                  </td>
                </tr>
              ) : (
                types.map((t) => (
                  <tr
                    key={t.relation_type_id}
                    className={`hover:bg-slate-50/80 transition-colors ${
                      !t.is_active ? "bg-slate-50/50 opacity-60" : ""
                    }`}
                  >
                    <td className="p-3 font-mono font-bold text-slate-900">{t.slug}</td>
                    <td className="p-3 font-medium text-slate-800">{t.forward_label}</td>
                    <td className="p-3 font-medium text-slate-800">{t.reverse_label}</td>
                    <td className="p-3">
                      <span
                        className={`inline-block px-2 py-0.5 rounded text-[11px] font-semibold ${
                          t.directionality === "directed"
                            ? "bg-blue-50 text-blue-700 border border-blue-200"
                            : "bg-purple-50 text-purple-700 border border-purple-200"
                        }`}
                      >
                        {t.directionality === "directed" ? "有向 (directed)" : "対称 (symmetric)"}
                      </span>
                    </td>
                    <td className="p-3 text-slate-500 max-w-xs truncate">{t.description || "—"}</td>
                    <td className="p-3">
                      {t.is_active ? (
                        <span className="inline-block px-2 py-0.5 rounded text-[11px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                          有効
                        </span>
                      ) : (
                        <span className="inline-block px-2 py-0.5 rounded text-[11px] font-semibold bg-slate-100 text-slate-500 border border-slate-200">
                          非活性
                        </span>
                      )}
                    </td>
                    <td className="p-3 text-right">
                      <button
                        onClick={() => openEditModal(t)}
                        className="px-2.5 py-1 text-xs font-semibold text-slate-700 hover:text-slate-900 border border-slate-300 rounded hover:bg-slate-100 cursor-pointer"
                      >
                        編集
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Create Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-sm p-4">
          <div className="bg-white rounded-xl border border-slate-200 shadow-xl max-w-md w-full overflow-hidden">
            <div className="p-4 border-b border-slate-100 bg-slate-50 flex justify-between items-center">
              <h3 className="text-sm font-bold text-slate-800">新規関係タイプの追加</h3>
              <button
                onClick={() => setShowCreateModal(false)}
                className="text-slate-400 hover:text-slate-600 text-xs cursor-pointer"
              >
                ✕
              </button>
            </div>
            <form onSubmit={handleCreateSubmit} className="p-5 space-y-4 text-xs">
              {createError && (
                <div className="p-3 bg-red-50 border border-red-200 text-red-700 rounded-lg">
                  {createError}
                </div>
              )}
              <div>
                <label className="block font-semibold text-slate-700 mb-1">
                  識別スラグ (slug) <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  value={createSlug}
                  onChange={(e) => setCreateSlug(e.target.value)}
                  placeholder="例: parent-child, mentor-mentee"
                  className="w-full rounded border border-slate-300 p-2 font-mono text-xs focus:ring-2 focus:ring-slate-800 focus:outline-none"
                  required
                />
                <p className="mt-1 text-[11px] text-slate-400">作成後は変更できません。</p>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">
                    正方向表示名 <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="text"
                    value={createForward}
                    onChange={(e) => setCreateForward(e.target.value)}
                    placeholder="例: 親である"
                    className="w-full rounded border border-slate-300 p-2 text-xs focus:ring-2 focus:ring-slate-800 focus:outline-none"
                    required
                  />
                </div>
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">
                    逆方向表示名 <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="text"
                    value={createReverse}
                    onChange={(e) => setCreateReverse(e.target.value)}
                    placeholder="例: 子である"
                    className="w-full rounded border border-slate-300 p-2 text-xs focus:ring-2 focus:ring-slate-800 focus:outline-none"
                    required
                  />
                </div>
              </div>

              <div>
                <label className="block font-semibold text-slate-700 mb-1">
                  方向性 (directionality) <span className="text-red-500">*</span>
                </label>
                <select
                  value={createDirectionality}
                  onChange={(e) => setCreateDirectionality(e.target.value as "directed" | "symmetric")}
                  className="w-full rounded border border-slate-300 p-2 text-xs focus:ring-2 focus:ring-slate-800 focus:outline-none"
                >
                  <option value="directed">有向 (directed - 親→子、雇用者→従業員)</option>
                  <option value="symmetric">対称 (symmetric - 友人、仲が悪い)</option>
                </select>
                <p className="mt-1 text-[11px] text-slate-400">作成後は変更できません。</p>
              </div>

              <div>
                <label className="block font-semibold text-slate-700 mb-1">説明 (任意)</label>
                <textarea
                  value={createDescription}
                  onChange={(e) => setCreateDescription(e.target.value)}
                  placeholder="関係定義の補足説明"
                  rows={3}
                  className="w-full rounded border border-slate-300 p-2 text-xs focus:ring-2 focus:ring-slate-800 focus:outline-none"
                />
              </div>

              <div className="pt-2 flex justify-end gap-2 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  className="rounded border border-slate-300 px-4 py-2 font-semibold text-slate-700 hover:bg-slate-50 cursor-pointer"
                >
                  キャンセル
                </button>
                <button
                  type="submit"
                  disabled={submittingCreate}
                  className="rounded bg-slate-800 px-4 py-2 font-semibold text-white hover:bg-slate-700 disabled:opacity-50 cursor-pointer"
                >
                  {submittingCreate ? "作成中..." : "作成"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Edit Modal */}
      {editingType && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-sm p-4">
          <div className="bg-white rounded-xl border border-slate-200 shadow-xl max-w-md w-full overflow-hidden">
            <div className="p-4 border-b border-slate-100 bg-slate-50 flex justify-between items-center">
              <h3 className="text-sm font-bold text-slate-800">
                関係タイプの編集: <span className="font-mono text-slate-900">{editingType.slug}</span>
              </h3>
              <button
                onClick={() => setEditingType(null)}
                className="text-slate-400 hover:text-slate-600 text-xs cursor-pointer"
              >
                ✕
              </button>
            </div>
            <form onSubmit={handleEditSubmit} className="p-5 space-y-4 text-xs">
              {editError && (
                <div className="p-3 bg-red-50 border border-red-200 text-red-700 rounded-lg">
                  {editError}
                </div>
              )}

              <div className="p-2.5 bg-slate-50 rounded border border-slate-200 text-slate-600 space-y-1">
                <div>スラグ: <strong className="font-mono text-slate-800">{editingType.slug}</strong> (編集不可)</div>
                <div>方向性: <strong className="text-slate-800">{editingType.directionality === "directed" ? "有向" : "対称"}</strong> (編集不可)</div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">
                    正方向表示名 <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="text"
                    value={editForward}
                    onChange={(e) => setEditForward(e.target.value)}
                    className="w-full rounded border border-slate-300 p-2 text-xs focus:ring-2 focus:ring-slate-800 focus:outline-none"
                    required
                  />
                </div>
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">
                    逆方向表示名 <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="text"
                    value={editReverse}
                    onChange={(e) => setEditReverse(e.target.value)}
                    className="w-full rounded border border-slate-300 p-2 text-xs focus:ring-2 focus:ring-slate-800 focus:outline-none"
                    required
                  />
                </div>
              </div>

              <div>
                <label className="block font-semibold text-slate-700 mb-1">説明 (任意)</label>
                <textarea
                  value={editDescription}
                  onChange={(e) => setEditDescription(e.target.value)}
                  rows={3}
                  className="w-full rounded border border-slate-300 p-2 text-xs focus:ring-2 focus:ring-slate-800 focus:outline-none"
                />
              </div>

              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="editIsActive"
                  checked={editIsActive}
                  onChange={(e) => setEditIsActive(e.target.checked)}
                  className="rounded border-slate-300 text-slate-800 focus:ring-slate-800"
                />
                <label htmlFor="editIsActive" className="font-semibold text-slate-700 cursor-pointer">
                  この関係タイプを有効化する (チェックを外すと非活性化)
                </label>
              </div>

              <div className="pt-2 flex justify-end gap-2 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setEditingType(null)}
                  className="rounded border border-slate-300 px-4 py-2 font-semibold text-slate-700 hover:bg-slate-50 cursor-pointer"
                >
                  キャンセル
                </button>
                <button
                  type="submit"
                  disabled={submittingEdit}
                  className="rounded bg-slate-800 px-4 py-2 font-semibold text-white hover:bg-slate-700 disabled:opacity-50 cursor-pointer"
                >
                  {submittingEdit ? "保存中..." : "保存"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
