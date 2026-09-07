import React, { useRef, useState } from "react";
import {
  PersonPropertyDefinition,
  PersonPropertyDefinitionCreateRequest,
  PersonPropertyDefinitionUpdateRequest,
  PropertyCardinality,
  PropertyDataType,
  PropertySourceType,
} from "./types";
import { useNativeDialog } from "./useNativeDialog";

interface PropertyDefinitionsTabProps {
  definitions: PersonPropertyDefinition[];
  loading: boolean;
  error: string | null;
  onCreateDefinition: (req: PersonPropertyDefinitionCreateRequest) => Promise<void>;
  onUpdateDefinition: (
    propertyDefinitionId: string,
    req: PersonPropertyDefinitionUpdateRequest
  ) => Promise<void>;
  onDeleteDefinition: (propertyDefinitionId: string) => Promise<void>;
}

interface OptionFormItem {
  option_key: string;
  display_name: string;
  display_order: number;
  aliases_text: string;
}

export default function PropertyDefinitionsTab({
  definitions,
  loading,
  error,
  onCreateDefinition,
  onUpdateDefinition,
  onDeleteDefinition,
}: PropertyDefinitionsTabProps) {
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [editingDefinition, setEditingDefinition] = useState<PersonPropertyDefinition | null>(null);
  const [deletingDefinition, setDeletingDefinition] = useState<PersonPropertyDefinition | null>(null);

  // Form states for creation
  const [createKey, setCreateKey] = useState("");
  const [createDisplayName, setCreateDisplayName] = useState("");
  const [createDataType, setCreateDataType] = useState<PropertyDataType>("text");
  const [createCardinality, setCreateCardinality] = useState<PropertyCardinality>("single");
  const [createSourceType, setCreateSourceType] = useState<PropertySourceType>("database");
  const [createAliasesText, setCreateAliasesText] = useState("");
  const [createOptions, setCreateOptions] = useState<OptionFormItem[]>([]);
  const [createError, setCreateError] = useState<string | null>(null);
  const [submittingCreate, setSubmittingCreate] = useState(false);

  // Form states for editing
  const [editDisplayName, setEditDisplayName] = useState("");
  const [editAliasesText, setEditAliasesText] = useState("");
  const [editOptions, setEditOptions] = useState<OptionFormItem[]>([]);
  const [editError, setEditError] = useState<string | null>(null);
  const [submittingEdit, setSubmittingEdit] = useState(false);

  // Deletion state
  const [submittingDelete, setSubmittingDelete] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const createDialogRef = useRef<HTMLDialogElement>(null);
  const editDialogRef = useRef<HTMLDialogElement>(null);
  const deleteDialogRef = useRef<HTMLDialogElement>(null);

  const closeCreateModal = () => setShowCreateModal(false);
  const closeEditModal = () => setEditingDefinition(null);
  const closeDeleteModal = () => setDeletingDefinition(null);

  useNativeDialog(createDialogRef, closeCreateModal, showCreateModal);
  useNativeDialog(editDialogRef, closeEditModal, editingDefinition !== null);
  useNativeDialog(deleteDialogRef, closeDeleteModal, deletingDefinition !== null);

  const openCreateModal = () => {
    setCreateKey("");
    setCreateDisplayName("");
    setCreateDataType("text");
    setCreateCardinality("single");
    setCreateSourceType("database");
    setCreateAliasesText("");
    setCreateOptions([]);
    setCreateError(null);
    setShowCreateModal(true);
  };

  const openEditModal = (d: PersonPropertyDefinition) => {
    setEditingDefinition(d);
    setEditDisplayName(d.display_name);
    setEditAliasesText((d.aliases || []).join("\n"));
    setEditOptions(
      (d.options || []).map((opt) => ({
        option_key: opt.option_key,
        display_name: opt.display_name,
        display_order: opt.display_order,
        aliases_text: (opt.aliases || []).join("\n"),
      }))
    );
    setEditError(null);
  };

  const handleAddCreateOption = () => {
    setCreateOptions((prev) => [
      ...prev,
      {
        option_key: "",
        display_name: "",
        display_order: prev.length,
        aliases_text: "",
      },
    ]);
  };

  const handleRemoveCreateOption = (index: number) => {
    setCreateOptions((prev) => prev.filter((_, i) => i !== index));
  };

  const handleAddEditOption = () => {
    setEditOptions((prev) => [
      ...prev,
      {
        option_key: "",
        display_name: "",
        display_order: prev.length,
        aliases_text: "",
      },
    ]);
  };

  const handleRemoveEditOption = (index: number) => {
    setEditOptions((prev) => prev.filter((_, i) => i !== index));
  };

  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreateError(null);

    if (!createKey.trim() || !createDisplayName.trim()) {
      setCreateError("属性キーと表示名は必須です。");
      return;
    }

    if (createDataType === "select" && createOptions.length === 0) {
      setCreateError("選択肢型(select)の場合は、少なくとも1つの選択肢を設定してください。");
      return;
    }

    const aliases = createAliasesText
      .split("\n")
      .map((s) => s.trim())
      .filter((s) => s.length > 0);

    const formattedOptions = createOptions.map((opt) => ({
      option_key: opt.option_key.trim(),
      display_name: opt.display_name.trim(),
      display_order: opt.display_order,
      aliases: opt.aliases_text
        .split("\n")
        .map((s) => s.trim())
        .filter((s) => s.length > 0),
    }));

    setSubmittingCreate(true);
    try {
      await onCreateDefinition({
        key: createKey.trim(),
        display_name: createDisplayName.trim(),
        data_type: createDataType,
        cardinality: createCardinality,
        source_type: createSourceType,
        aliases,
        options: createDataType === "select" ? formattedOptions : [],
      });
      setShowCreateModal(false);
    } catch (err: unknown) {
      setCreateError(err instanceof Error ? err.message : "属性定義の作成に失敗しました。");
    } finally {
      setSubmittingCreate(false);
    }
  };

  const handleEditSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingDefinition) return;
    setEditError(null);

    if (!editDisplayName.trim()) {
      setEditError("表示名は必須です。");
      return;
    }

    const aliases = editAliasesText
      .split("\n")
      .map((s) => s.trim())
      .filter((s) => s.length > 0);

    const formattedOptions = editOptions.map((opt) => ({
      option_key: opt.option_key.trim(),
      display_name: opt.display_name.trim(),
      display_order: opt.display_order,
      aliases: opt.aliases_text
        .split("\n")
        .map((s) => s.trim())
        .filter((s) => s.length > 0),
    }));

    setSubmittingEdit(true);
    try {
      await onUpdateDefinition(editingDefinition.property_definition_id, {
        display_name: editDisplayName.trim(),
        aliases,
        options: editingDefinition.data_type === "select" ? formattedOptions : undefined,
      });
      setEditingDefinition(null);
    } catch (err: unknown) {
      setEditError(err instanceof Error ? err.message : "属性定義の更新に失敗しました。");
    } finally {
      setSubmittingEdit(false);
    }
  };

  const handleDeleteSubmit = async () => {
    if (!deletingDefinition) return;
    setDeleteError(null);
    setSubmittingDelete(true);
    try {
      await onDeleteDefinition(deletingDefinition.property_definition_id);
      setDeletingDefinition(null);
    } catch (err: unknown) {
      setDeleteError(err instanceof Error ? err.message : "属性定義の削除に失敗しました。");
    } finally {
      setSubmittingDelete(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-bold text-slate-800">属性定義管理</h2>
          <p className="text-xs text-slate-500">
            人物の属性（生年月日、スキル等）の型、保存元（DB専用/Vault正本）、選択肢を定義します。
          </p>
        </div>
        <button
          onClick={openCreateModal}
          className="rounded-lg bg-slate-800 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-700 cursor-pointer"
        >
          ＋ 新規属性定義
        </button>
      </div>

      {error && (
        <div className="p-3 bg-red-50 border border-red-200 text-red-700 text-xs rounded-lg">
          {error}
        </div>
      )}

      {loading ? (
        <div className="p-8 text-center text-xs text-slate-500">属性定義を読み込み中...</div>
      ) : (
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-sm">
          <table className="w-full text-left text-xs text-slate-700">
            <thead className="bg-slate-50 border-b border-slate-200 text-slate-500 font-semibold">
              <tr>
                <th className="p-3">キー (key)</th>
                <th className="p-3">表示名</th>
                <th className="p-3">型 (data_type)</th>
                <th className="p-3">単複 (cardinality)</th>
                <th className="p-3">保存元 (source_type)</th>
                <th className="p-3">別名 (aliases)</th>
                <th className="p-3">選択肢数</th>
                <th className="p-3 text-right">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {definitions.length === 0 ? (
                <tr>
                  <td colSpan={8} className="p-6 text-center text-slate-400">
                    登録されている属性定義はありません。
                  </td>
                </tr>
              ) : (
                definitions.map((d) => (
                  <tr key={d.property_definition_id} className="hover:bg-slate-50/80 transition-colors">
                    <td className="p-3 font-mono font-bold text-slate-900">{d.key}</td>
                    <td className="p-3 font-medium text-slate-800">{d.display_name}</td>
                    <td className="p-3">
                      <span className="inline-block px-2 py-0.5 rounded text-[11px] font-semibold bg-slate-100 text-slate-700 border border-slate-200">
                        {d.data_type}
                      </span>
                    </td>
                    <td className="p-3">
                      <span className="inline-block px-2 py-0.5 rounded text-[11px] font-semibold bg-blue-50 text-blue-700 border border-blue-200">
                        {d.cardinality === "single" ? "単数 (single)" : "複数 (multiple)"}
                      </span>
                    </td>
                    <td className="p-3">
                      {d.source_type === "vault" ? (
                        <span className="inline-block px-2 py-0.5 rounded text-[11px] font-semibold bg-amber-50 text-amber-800 border border-amber-200">
                          Vault正本
                        </span>
                      ) : (
                        <span className="inline-block px-2 py-0.5 rounded text-[11px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                          DB専用
                        </span>
                      )}
                    </td>
                    <td className="p-3 text-slate-500">
                      {d.aliases && d.aliases.length > 0 ? d.aliases.join(", ") : "—"}
                    </td>
                    <td className="p-3 text-slate-600">
                      {d.data_type === "select" ? `${d.options?.length || 0}件` : "—"}
                    </td>
                    <td className="p-3 text-right space-x-2">
                      <button
                        onClick={() => openEditModal(d)}
                        className="px-2.5 py-1 text-xs font-semibold text-slate-700 hover:text-slate-900 border border-slate-300 rounded hover:bg-slate-100 cursor-pointer"
                      >
                        編集
                      </button>
                      <button
                        onClick={() => setDeletingDefinition(d)}
                        className="px-2.5 py-1 text-xs font-semibold text-red-600 hover:text-red-800 border border-red-200 rounded hover:bg-red-50 cursor-pointer"
                      >
                        削除
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
        <dialog
          ref={createDialogRef}
          onClose={closeCreateModal}
          onKeyDown={(e) => {
            if (e.key === "Escape") closeCreateModal();
          }}
          role="dialog"
          aria-modal="true"
          className="m-auto w-full max-w-lg rounded-xl border border-slate-200 shadow-xl p-0 backdrop:bg-slate-900/60 backdrop:backdrop-blur-sm"
        >
          <div className="bg-white rounded-xl overflow-hidden">
            <div className="p-4 border-b border-slate-100 bg-slate-50 flex justify-between items-center">
              <h3 className="text-sm font-bold text-slate-800">新規属性定義の追加</h3>
              <button
                onClick={() => setShowCreateModal(false)}
                className="text-slate-400 hover:text-slate-600 text-xs cursor-pointer"
              >
                ✕
              </button>
            </div>
            <form onSubmit={handleCreateSubmit} className="p-5 space-y-4 text-xs max-h-[80vh] overflow-y-auto">
              {createError && (
                <div className="p-3 bg-red-50 border border-red-200 text-red-700 rounded-lg">
                  {createError}
                </div>
              )}
              <div>
                <label className="block font-semibold text-slate-700 mb-1">
                  属性キー (key) <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  value={createKey}
                  onChange={(e) => setCreateKey(e.target.value)}
                  placeholder="例: birth_date, gender, skills"
                  className="w-full rounded border border-slate-300 p-2 font-mono text-xs focus:ring-2 focus:ring-slate-800 focus:outline-none"
                  required
                />
                <p className="mt-1 text-[11px] text-slate-400">不変の識別子です（作成後変更不可）。</p>
              </div>

              <div>
                <label className="block font-semibold text-slate-700 mb-1">
                  表示名 <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  value={createDisplayName}
                  onChange={(e) => setCreateDisplayName(e.target.value)}
                  placeholder="例: 生年月日"
                  className="w-full rounded border border-slate-300 p-2 text-xs focus:ring-2 focus:ring-slate-800 focus:outline-none"
                  required
                />
              </div>

              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">
                    データ型 <span className="text-red-500">*</span>
                  </label>
                  <select
                    value={createDataType}
                    onChange={(e) => setCreateDataType(e.target.value as PropertyDataType)}
                    className="w-full rounded border border-slate-300 p-2 text-xs focus:ring-2 focus:ring-slate-800 focus:outline-none"
                  >
                    <option value="text">文字列 (text)</option>
                    <option value="date">日付 (date)</option>
                    <option value="number">数値 (number)</option>
                    <option value="boolean">真偽値 (boolean)</option>
                    <option value="select">選択肢 (select)</option>
                  </select>
                </div>
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">
                    単複制約 <span className="text-red-500">*</span>
                  </label>
                  <select
                    value={createCardinality}
                    onChange={(e) => setCreateCardinality(e.target.value as PropertyCardinality)}
                    className="w-full rounded border border-slate-300 p-2 text-xs focus:ring-2 focus:ring-slate-800 focus:outline-none"
                  >
                    <option value="single">単数 (single)</option>
                    <option value="multiple">複数 (multiple)</option>
                  </select>
                </div>
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">
                    保存元 <span className="text-red-500">*</span>
                  </label>
                  <select
                    value={createSourceType}
                    onChange={(e) => setCreateSourceType(e.target.value as PropertySourceType)}
                    className="w-full rounded border border-slate-300 p-2 text-xs focus:ring-2 focus:ring-slate-800 focus:outline-none"
                  >
                    <option value="database">DB専用 (database)</option>
                    <option value="vault">Vault正本 (vault)</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="block font-semibold text-slate-700 mb-1">属性名別名 (改行区切り)</label>
                <textarea
                  value={createAliasesText}
                  onChange={(e) => setCreateAliasesText(e.target.value)}
                  placeholder="例: birthday&#10;date_of_birth"
                  rows={2}
                  className="w-full rounded border border-slate-300 p-2 font-mono text-xs focus:ring-2 focus:ring-slate-800 focus:outline-none"
                />
              </div>

              {createDataType === "select" && (
                <div className="space-y-3 pt-2 border-t border-slate-200">
                  <div className="flex justify-between items-center">
                    <label className="font-semibold text-slate-800">選択肢の定義</label>
                    <button
                      type="button"
                      onClick={handleAddCreateOption}
                      className="px-2 py-1 bg-slate-100 hover:bg-slate-200 text-slate-700 font-semibold rounded text-[11px] cursor-pointer"
                    >
                      ＋ 選択肢を追加
                    </button>
                  </div>
                  {createOptions.map((opt, idx) => (
                    <div key={idx} className="p-3 bg-slate-50 border border-slate-200 rounded-lg space-y-2">
                      <div className="flex justify-between items-center">
                        <span className="font-semibold text-slate-600 text-[11px]">選択肢 #{idx + 1}</span>
                        <button
                          type="button"
                          onClick={() => handleRemoveCreateOption(idx)}
                          className="text-red-500 hover:text-red-700 text-[11px] cursor-pointer"
                        >
                          削除
                        </button>
                      </div>
                      <div className="grid grid-cols-2 gap-2">
                        <input
                          type="text"
                          value={opt.option_key}
                          onChange={(e) => {
                            const val = e.target.value;
                            setCreateOptions((prev) =>
                              prev.map((o, i) => (i === idx ? { ...o, option_key: val } : o))
                            );
                          }}
                          placeholder="キー (例: male, python)"
                          className="rounded border border-slate-300 p-1.5 font-mono text-xs"
                          required
                        />
                        <input
                          type="text"
                          value={opt.display_name}
                          onChange={(e) => {
                            const val = e.target.value;
                            setCreateOptions((prev) =>
                              prev.map((o, i) => (i === idx ? { ...o, display_name: val } : o))
                            );
                          }}
                          placeholder="表示名 (例: 男性, Python)"
                          className="rounded border border-slate-300 p-1.5 text-xs"
                          required
                        />
                      </div>
                      <input
                        type="text"
                        value={opt.aliases_text}
                        onChange={(e) => {
                          const val = e.target.value;
                          setCreateOptions((prev) =>
                            prev.map((o, i) => (i === idx ? { ...o, aliases_text: val } : o))
                          );
                        }}
                        placeholder="別名 (改行またはカンマ区切り)"
                        className="w-full rounded border border-slate-300 p-1.5 text-xs font-mono"
                      />
                    </div>
                  ))}
                </div>
              )}

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
        </dialog>
      )}

      {/* Edit Modal */}
      {editingDefinition && (
        <dialog
          ref={editDialogRef}
          onClose={closeEditModal}
          onKeyDown={(e) => {
            if (e.key === "Escape") closeEditModal();
          }}
          role="dialog"
          aria-modal="true"
          className="m-auto w-full max-w-lg rounded-xl border border-slate-200 shadow-xl p-0 backdrop:bg-slate-900/60 backdrop:backdrop-blur-sm"
        >
          <div className="bg-white rounded-xl overflow-hidden">
            <div className="p-4 border-b border-slate-100 bg-slate-50 flex justify-between items-center">
              <h3 className="text-sm font-bold text-slate-800">
                属性定義の編集: <span className="font-mono text-slate-900">{editingDefinition.key}</span>
              </h3>
              <button
                onClick={() => setEditingDefinition(null)}
                className="text-slate-400 hover:text-slate-600 text-xs cursor-pointer"
              >
                ✕
              </button>
            </div>
            <form onSubmit={handleEditSubmit} className="p-5 space-y-4 text-xs max-h-[80vh] overflow-y-auto">
              {editError && (
                <div className="p-3 bg-red-50 border border-red-200 text-red-700 rounded-lg">
                  {editError}
                </div>
              )}

              <div className="p-2.5 bg-slate-50 rounded border border-slate-200 text-slate-600 space-y-1">
                <div>キー: <strong className="font-mono text-slate-800">{editingDefinition.key}</strong> (不変)</div>
                <div>データ型: <strong className="text-slate-800">{editingDefinition.data_type}</strong> / 単複: <strong className="text-slate-800">{editingDefinition.cardinality}</strong> / 保存元: <strong className="text-slate-800">{editingDefinition.source_type}</strong> (不変)</div>
              </div>

              <div>
                <label className="block font-semibold text-slate-700 mb-1">
                  表示名 <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  value={editDisplayName}
                  onChange={(e) => setEditDisplayName(e.target.value)}
                  className="w-full rounded border border-slate-300 p-2 text-xs focus:ring-2 focus:ring-slate-800 focus:outline-none"
                  required
                />
              </div>

              <div>
                <label className="block font-semibold text-slate-700 mb-1">属性名別名 (改行区切り)</label>
                <textarea
                  value={editAliasesText}
                  onChange={(e) => setEditAliasesText(e.target.value)}
                  rows={2}
                  className="w-full rounded border border-slate-300 p-2 font-mono text-xs focus:ring-2 focus:ring-slate-800 focus:outline-none"
                />
              </div>

              {editingDefinition.data_type === "select" && (
                <div className="space-y-3 pt-2 border-t border-slate-200">
                  <div className="flex justify-between items-center">
                    <label className="font-semibold text-slate-800">選択肢の編集</label>
                    <button
                      type="button"
                      onClick={handleAddEditOption}
                      className="px-2 py-1 bg-slate-100 hover:bg-slate-200 text-slate-700 font-semibold rounded text-[11px] cursor-pointer"
                    >
                      ＋ 選択肢を追加
                    </button>
                  </div>
                  {editOptions.map((opt, idx) => (
                    <div key={idx} className="p-3 bg-slate-50 border border-slate-200 rounded-lg space-y-2">
                      <div className="flex justify-between items-center">
                        <span className="font-semibold text-slate-600 text-[11px]">選択肢 #{idx + 1}</span>
                        <button
                          type="button"
                          onClick={() => handleRemoveEditOption(idx)}
                          className="text-red-500 hover:text-red-700 text-[11px] cursor-pointer"
                        >
                          削除
                        </button>
                      </div>
                      <div className="grid grid-cols-2 gap-2">
                        <input
                          type="text"
                          value={opt.option_key}
                          onChange={(e) => {
                            const val = e.target.value;
                            setEditOptions((prev) =>
                              prev.map((o, i) => (i === idx ? { ...o, option_key: val } : o))
                            );
                          }}
                          placeholder="キー"
                          className="rounded border border-slate-300 p-1.5 font-mono text-xs"
                          required
                        />
                        <input
                          type="text"
                          value={opt.display_name}
                          onChange={(e) => {
                            const val = e.target.value;
                            setEditOptions((prev) =>
                              prev.map((o, i) => (i === idx ? { ...o, display_name: val } : o))
                            );
                          }}
                          placeholder="表示名"
                          className="rounded border border-slate-300 p-1.5 text-xs"
                          required
                        />
                      </div>
                      <input
                        type="text"
                        value={opt.aliases_text}
                        onChange={(e) => {
                          const val = e.target.value;
                          setEditOptions((prev) =>
                            prev.map((o, i) => (i === idx ? { ...o, aliases_text: val } : o))
                          );
                        }}
                        placeholder="別名 (改行区切り)"
                        className="w-full rounded border border-slate-300 p-1.5 text-xs font-mono"
                      />
                    </div>
                  ))}
                </div>
              )}

              <div className="pt-2 flex justify-end gap-2 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setEditingDefinition(null)}
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
        </dialog>
      )}

      {/* Delete Confirmation Modal */}
      {deletingDefinition && (
        <dialog
          ref={deleteDialogRef}
          onClose={closeDeleteModal}
          onKeyDown={(e) => {
            if (e.key === "Escape") closeDeleteModal();
          }}
          role="dialog"
          aria-modal="true"
          className="m-auto w-full max-w-md rounded-xl border border-slate-200 shadow-xl p-0 backdrop:bg-slate-900/60 backdrop:backdrop-blur-sm"
        >
          <div className="bg-white rounded-xl p-5 space-y-4">
            <h3 className="text-sm font-bold text-slate-900">
              属性定義の削除確認: <span className="font-mono">{deletingDefinition.key}</span>
            </h3>
            <p className="text-xs text-slate-600 leading-relaxed">
              この属性定義を削除すると、紐づくすべての人物の属性値および選択肢情報が<strong>物理削除</strong>されます。この操作は取り消せません。
            </p>
            {deleteError && (
              <div className="p-3 bg-red-50 border border-red-200 text-red-700 rounded text-xs">
                {deleteError}
              </div>
            )}
            <div className="flex justify-end gap-2 pt-2 border-t border-slate-100">
              <button
                type="button"
                onClick={() => setDeletingDefinition(null)}
                className="rounded border border-slate-300 px-4 py-2 font-semibold text-slate-700 text-xs hover:bg-slate-50 cursor-pointer"
              >
                キャンセル
              </button>
              <button
                type="button"
                onClick={handleDeleteSubmit}
                disabled={submittingDelete}
                className="rounded bg-red-600 px-4 py-2 font-semibold text-white text-xs hover:bg-red-700 disabled:opacity-50 cursor-pointer"
              >
                {submittingDelete ? "削除中..." : "安全に削除を実行"}
              </button>
            </div>
          </div>
        </dialog>
      )}
    </div>
  );
}
