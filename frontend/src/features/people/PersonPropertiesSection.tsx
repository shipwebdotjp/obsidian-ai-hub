import React, { useRef, useState } from "react";
import {
  PersonPropertyDefinition,
  PersonPropertyValue,
  PersonPropertyValueCreateRequest,
  PersonPropertyValueUpdateRequest,
} from "./types";
import { useNativeDialog } from "./useNativeDialog";
import { formatYmdWithDow } from "../../utils/date";

function isValidYmd(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const [year, month, day] = value.split("-").map(Number);
  const date = new Date(`${value}T00:00:00`);
  return (
    date.getFullYear() === year && date.getMonth() + 1 === month && date.getDate() === day
  );
}

// formatYmdWithDow returns invalid input unchanged, so validate first and
// hide null/empty/invalid values per project convention.
function formatPeriodDate(value: string | null | undefined): string {
  if (!value || !isValidYmd(value)) return "";
  return formatYmdWithDow(value);
}

interface PersonPropertiesSectionProps {
  personId: string;
  properties: PersonPropertyValue[];
  definitions: PersonPropertyDefinition[];
  loading: boolean;
  onCreateProperty: (req: PersonPropertyValueCreateRequest) => Promise<void>;
  onUpdateProperty: (propertyValueId: string, req: PersonPropertyValueUpdateRequest) => Promise<void>;
  onDeleteProperty: (propertyValueId: string) => Promise<void>;
}

export default function PersonPropertiesSection({
  personId,
  properties,
  definitions,
  loading,
  onCreateProperty,
  onUpdateProperty,
  onDeleteProperty,
}: PersonPropertiesSectionProps) {
  const [showFormModal, setShowFormModal] = useState(false);
  const [editingValue, setEditingValue] = useState<PersonPropertyValue | null>(null);
  const [deletingValue, setDeletingValue] = useState<PersonPropertyValue | null>(null);

  // Form states
  const [selectedDefinitionId, setSelectedDefinitionId] = useState("");
  const [valInput, setValInput] = useState<any>("");
  const [validFrom, setValidFrom] = useState("");
  const [validUntil, setValidUntil] = useState("");
  const [note, setNote] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const formDialogRef = useRef<HTMLDialogElement>(null);
  const deleteDialogRef = useRef<HTMLDialogElement>(null);

  const closeFormModal = () => {
    setShowFormModal(false);
    setEditingValue(null);
  };
  const closeDeleteModal = () => {
    setDeletingValue(null);
    setDeleteError(null);
  };

  const openDeleteModal = (pv: PersonPropertyValue) => {
    setDeletingValue(pv);
    setDeleteError(null);
  };

  useNativeDialog(formDialogRef, closeFormModal, showFormModal || editingValue !== null);
  useNativeDialog(deleteDialogRef, closeDeleteModal, deletingValue !== null);

  // Available DB-exclusive definitions for creation
  const dbDefinitions = definitions.filter((d) => d.source_type === "database");

  const openCreateModal = () => {
    const firstDef = dbDefinitions[0];
    setSelectedDefinitionId(firstDef ? firstDef.property_definition_id : "");
    setValInput("");
    setValidFrom("");
    setValidUntil("");
    setNote("");
    setFormError(null);
    setShowFormModal(true);
  };

  const openEditModal = (pv: PersonPropertyValue) => {
    if (pv.source_type === "vault") return;
    setEditingValue(pv);
    setSelectedDefinitionId(pv.property_definition_id);

    if (pv.data_type === "boolean") {
      setValInput(pv.value_boolean === true ? "true" : "false");
    } else if (pv.data_type === "select") {
      setValInput(pv.option_id || pv.value || "");
    } else {
      setValInput(pv.value ?? "");
    }

    setValidFrom(pv.valid_from || "");
    setValidUntil(pv.valid_until || "");
    setNote(pv.note || "");
    setFormError(null);
  };

  const currentDefinition = definitions.find((d) => d.property_definition_id === selectedDefinitionId);

  const handleFormSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);

    let parsedVal = valInput;
    if (currentDefinition?.data_type === "boolean") {
      parsedVal = valInput === "true";
    } else if (currentDefinition?.data_type === "number") {
      parsedVal = parseFloat(valInput);
    }

    setSubmitting(true);
    try {
      if (editingValue) {
        await onUpdateProperty(editingValue.property_value_id, {
          value: parsedVal,
          valid_from: validFrom.trim() || null,
          valid_until: validUntil.trim() || null,
          note: note.trim() || null,
        });
        setEditingValue(null);
      } else {
        await onCreateProperty({
          property_definition_id: selectedDefinitionId,
          value: parsedVal,
          valid_from: validFrom.trim() || null,
          valid_until: validUntil.trim() || null,
          note: note.trim() || null,
        });
        setShowFormModal(false);
      }
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : "属性値の保存に失敗しました。");
    } finally {
      setSubmitting(false);
    }
  };

  const handleDeleteSubmit = async () => {
    if (!deletingValue) return;
    setDeleteError(null);
    setSubmitting(true);
    try {
      await onDeleteProperty(deletingValue.property_value_id);
      setDeletingValue(null);
    } catch (err: unknown) {
      setDeleteError(err instanceof Error ? err.message : "属性値の削除に失敗しました。");
    } finally {
      setSubmitting(false);
    }
  };

  const renderValueDisplay = (pv: PersonPropertyValue) => {
    if (pv.data_type === "date") {
      const raw = pv.value_date ?? (typeof pv.value === "string" ? pv.value : null);
      return formatPeriodDate(raw) || "—";
    }
    if (pv.data_type === "boolean") {
      return pv.value_boolean ? "はい (True)" : "いいえ (False)";
    }
    if (pv.data_type === "select") {
      return pv.option_display_name || pv.option_key || pv.value || "—";
    }
    return pv.value !== null && pv.value !== undefined ? String(pv.value) : "—";
  };

  return (
    <div className="space-y-3 pt-3 border-t border-slate-200">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-xs font-bold text-slate-800">人物属性</h3>
          <p className="text-[11px] text-slate-500">
            登録されている属性履歴一覧です。
          </p>
        </div>
        <button
          onClick={openCreateModal}
          disabled={dbDefinitions.length === 0}
          className="rounded bg-slate-800 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-slate-700 disabled:opacity-50 cursor-pointer"
        >
          ＋ 属性を追加
        </button>
      </div>

      {properties.length === 0 ? (
        <div className="p-4 text-center text-xs text-slate-400 bg-slate-50 rounded-lg border border-slate-200">
          登録されている属性値はありません。
        </div>
      ) : (
        <div className="space-y-2">
          {properties.map((pv) => {
            const isVault = pv.source_type === "vault";
            return (
              <div
                key={pv.property_value_id}
                className={`p-3 rounded-lg border text-xs space-y-1 transition-colors ${
                  isVault
                    ? "bg-amber-50/40 border-amber-200 text-slate-800"
                    : "bg-white border-slate-200 text-slate-800"
                }`}
              >
                <div className="flex justify-between items-start">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-slate-900">{pv.property_display_name}</span>
                    <span className="font-mono text-[10px] text-slate-400">({pv.property_key})</span>
                  </div>
                  <div className="flex items-center gap-1">
                    {isVault ? (
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-amber-100 text-amber-800 border border-amber-300">
                        Vault
                      </span>
                    ) : (
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                        DB
                      </span>
                    )}
                    {!isVault && (
                      <>
                        <button
                          onClick={() => openEditModal(pv)}
                          className="px-2 py-0.5 text-[11px] font-semibold text-slate-700 border border-slate-300 rounded hover:bg-slate-100 cursor-pointer"
                        >
                          編集
                        </button>
                        <button
                          onClick={() => openDeleteModal(pv)}
                          className="px-2 py-0.5 text-[11px] font-semibold text-red-600 border border-red-200 rounded hover:bg-red-50 cursor-pointer"
                        >
                          削除
                        </button>
                      </>
                    )}
                  </div>
                </div>

                <div className="font-medium text-slate-900 text-sm pt-0.5">
                  {renderValueDisplay(pv)}
                </div>

                {(pv.valid_from || pv.valid_until) && (
                  <div className="text-[11px] text-slate-500 font-mono">
                    有効期間:{" "}
                    {pv.valid_from
                      ? formatPeriodDate(pv.valid_from) || ""
                      : "開始指定なし"}{" "}
                    ～{" "}
                    {pv.valid_until
                      ? formatPeriodDate(pv.valid_until) || ""
                      : "終了指定なし"}
                  </div>
                )}

                {pv.note && (
                  <div className="text-[11px] text-slate-600 bg-slate-50/80 p-1.5 rounded border border-slate-100 mt-1">
                    {pv.note}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Form Modal (Create / Edit) */}
      {(showFormModal || editingValue) && (
        <dialog
          ref={formDialogRef}
          onClose={closeFormModal}
          onKeyDown={(e) => {
            if (e.key === "Escape") closeFormModal();
          }}
          role="dialog"
          aria-modal="true"
          className="m-auto w-full max-w-md rounded-xl border border-slate-200 shadow-xl p-0 backdrop:bg-slate-900/60 backdrop:backdrop-blur-sm"
        >
          <div className="bg-white rounded-xl overflow-hidden">
            <div className="p-4 border-b border-slate-100 bg-slate-50 flex justify-between items-center">
              <h3 className="text-sm font-bold text-slate-800">
                {editingValue ? "属性値の編集" : "新規属性値の追加"}
              </h3>
              <button
                onClick={closeFormModal}
                className="text-slate-400 hover:text-slate-600 text-xs cursor-pointer"
              >
                ✕
              </button>
            </div>
            <form onSubmit={handleFormSubmit} className="p-5 space-y-4 text-xs">
              {formError && (
                <div className="p-3 bg-red-50 border border-red-200 text-red-700 rounded-lg">
                  {formError}
                </div>
              )}

              {!editingValue ? (
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">
                    属性定義 <span className="text-red-500">*</span>
                  </label>
                  <select
                    value={selectedDefinitionId}
                    onChange={(e) => {
                      setSelectedDefinitionId(e.target.value);
                      setValInput("");
                    }}
                    className="w-full rounded border border-slate-300 p-2 text-xs focus:ring-2 focus:ring-slate-800 focus:outline-none"
                    required
                  >
                    {dbDefinitions.map((d) => (
                      <option key={d.property_definition_id} value={d.property_definition_id}>
                        {d.display_name} ({d.key}) [{d.data_type}]
                      </option>
                    ))}
                  </select>
                </div>
              ) : (
                <div className="p-2.5 bg-slate-50 rounded border border-slate-200 text-slate-700 font-semibold">
                  {editingValue.property_display_name} ({editingValue.property_key})
                </div>
              )}

              {currentDefinition && (
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">
                    値 ({currentDefinition.data_type}) <span className="text-red-500">*</span>
                  </label>

                  {currentDefinition.data_type === "select" ? (
                    <select
                      value={valInput}
                      onChange={(e) => setValInput(e.target.value)}
                      className="w-full rounded border border-slate-300 p-2 text-xs focus:ring-2 focus:ring-slate-800 focus:outline-none"
                      required
                    >
                      <option value="">選択してください</option>
                      {currentDefinition.options?.map((opt) => (
                        <option key={opt.option_id} value={opt.option_id}>
                          {opt.display_name} ({opt.option_key})
                        </option>
                      ))}
                    </select>
                  ) : currentDefinition.data_type === "boolean" ? (
                    <select
                      value={valInput}
                      onChange={(e) => setValInput(e.target.value)}
                      className="w-full rounded border border-slate-300 p-2 text-xs focus:ring-2 focus:ring-slate-800 focus:outline-none"
                    >
                      <option value="true">はい (True)</option>
                      <option value="false">いいえ (False)</option>
                    </select>
                  ) : currentDefinition.data_type === "date" ? (
                    <input
                      type="date"
                      value={valInput}
                      onChange={(e) => setValInput(e.target.value)}
                      className="w-full rounded border border-slate-300 p-2 text-xs font-mono focus:ring-2 focus:ring-slate-800 focus:outline-none"
                      required
                    />
                  ) : currentDefinition.data_type === "number" ? (
                    <input
                      type="number"
                      step="any"
                      value={valInput}
                      onChange={(e) => setValInput(e.target.value)}
                      className="w-full rounded border border-slate-300 p-2 text-xs font-mono focus:ring-2 focus:ring-slate-800 focus:outline-none"
                      required
                    />
                  ) : (
                    <input
                      type="text"
                      value={valInput}
                      onChange={(e) => setValInput(e.target.value)}
                      placeholder="属性値を入力"
                      className="w-full rounded border border-slate-300 p-2 text-xs focus:ring-2 focus:ring-slate-800 focus:outline-none"
                      required
                    />
                  )}
                </div>
              )}

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">開始日 (YYYY-MM-DD)</label>
                  <input
                    type="date"
                    value={validFrom}
                    onChange={(e) => setValidFrom(e.target.value)}
                    className="w-full rounded border border-slate-300 p-2 text-xs font-mono focus:ring-2 focus:ring-slate-800 focus:outline-none"
                  />
                </div>
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">終了日 (YYYY-MM-DD)</label>
                  <input
                    type="date"
                    value={validUntil}
                    onChange={(e) => setValidUntil(e.target.value)}
                    className="w-full rounded border border-slate-300 p-2 text-xs font-mono focus:ring-2 focus:ring-slate-800 focus:outline-none"
                  />
                </div>
              </div>

              <div>
                <label className="block font-semibold text-slate-700 mb-1">メモ (任意)</label>
                <textarea
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  rows={2}
                  className="w-full rounded border border-slate-300 p-2 text-xs focus:ring-2 focus:ring-slate-800 focus:outline-none"
                />
              </div>

              <div className="pt-2 flex justify-end gap-2 border-t border-slate-100">
                <button
                  type="button"
                  onClick={closeFormModal}
                  className="rounded border border-slate-300 px-4 py-2 font-semibold text-slate-700 hover:bg-slate-50 cursor-pointer"
                >
                  キャンセル
                </button>
                <button
                  type="submit"
                  disabled={submitting}
                  className="rounded bg-slate-800 px-4 py-2 font-semibold text-white hover:bg-slate-700 disabled:opacity-50 cursor-pointer"
                >
                  {submitting ? "保存中..." : "保存"}
                </button>
              </div>
            </form>
          </div>
        </dialog>
      )}

      {/* Delete Confirmation Modal */}
      {deletingValue && (
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
              属性値の削除確認: <span className="font-bold">{deletingValue.property_display_name}</span>
            </h3>
            <p className="text-xs text-slate-600 leading-relaxed">
              この属性値を削除します。よろしいですか？
            </p>
            {deleteError && (
              <div className="p-3 bg-red-50 border border-red-200 text-red-700 rounded-lg text-xs">
                {deleteError}
              </div>
            )}
            <div className="flex justify-end gap-2 pt-2 border-t border-slate-100">
              <button
                type="button"
                onClick={closeDeleteModal}
                className="rounded border border-slate-300 px-4 py-2 font-semibold text-slate-700 text-xs hover:bg-slate-50 cursor-pointer"
              >
                キャンセル
              </button>
              <button
                type="button"
                onClick={handleDeleteSubmit}
                disabled={submitting}
                className="rounded bg-red-600 px-4 py-2 font-semibold text-white text-xs hover:bg-red-700 disabled:opacity-50 cursor-pointer"
              >
                {submitting ? "削除中..." : "削除"}
              </button>
            </div>
          </div>
        </dialog>
      )}
    </div>
  );
}
