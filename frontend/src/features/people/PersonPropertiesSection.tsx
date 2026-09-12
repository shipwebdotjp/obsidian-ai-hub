import React, { useMemo, useRef, useState } from "react";
import {
  PersonPropertyDefinition,
  PersonPropertyValue,
  PersonPropertyValueCreateRequest,
  PersonPropertyValueUpdateRequest,
  PersonPropertyBulkSaveRequest,
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

interface BulkRow {
  key: string;
  propertyValueId?: string;
  valueInput: string;
  validFrom: string;
  validUntil: string;
  note: string;
}

let bulkRowSeq = 0;
function newBulkRow(): BulkRow {
  bulkRowSeq += 1;
  return { key: `row-${bulkRowSeq}`, valueInput: "", validFrom: "", validUntil: "", note: "" };
}

function rowValueFromProperty(pv: PersonPropertyValue): string {
  if (pv.data_type === "boolean") {
    return pv.value_boolean === true ? "true" : "false";
  }
  if (pv.data_type === "select") {
    return pv.option_id || (typeof pv.value === "string" ? pv.value : "") || "";
  }
  return pv.value === null || pv.value === undefined ? "" : String(pv.value);
}

function parseRowValue(dataType: string, raw: string): unknown {
  if (dataType === "boolean") {
    if (raw !== "true" && raw !== "false") throw new Error("値を選択してください。");
    return raw === "true";
  }
  if (dataType === "number") {
    const n = parseFloat(raw.trim());
    if (!Number.isFinite(n)) throw new Error("数値を入力してください。");
    return n;
  }
  return raw;
}

interface PersonPropertiesSectionProps {
  personId: string;
  properties: PersonPropertyValue[];
  definitions: PersonPropertyDefinition[];
  loading: boolean;
  onCreateProperty: (req: PersonPropertyValueCreateRequest) => Promise<void>;
  onUpdateProperty: (propertyValueId: string, req: PersonPropertyValueUpdateRequest) => Promise<void>;
  onDeleteProperty: (propertyValueId: string) => Promise<void>;
  onBulkSaveProperty?: (propertyDefinitionId: string, req: PersonPropertyBulkSaveRequest) => Promise<void>;
}

interface PropertyGroup {
  propertyDefinitionId: string;
  values: PersonPropertyValue[];
}

export default function PersonPropertiesSection({
  personId,
  properties,
  definitions,
  loading,
  onCreateProperty,
  onUpdateProperty,
  onDeleteProperty,
  onBulkSaveProperty = async () => {},
}: PersonPropertiesSectionProps) {
  const [showFormModal, setShowFormModal] = useState(false);
  const [editingValue, setEditingValue] = useState<PersonPropertyValue | null>(null);
  const [deletingValue, setDeletingValue] = useState<PersonPropertyValue | null>(null);

  // Single-value form states
  const [selectedDefinitionId, setSelectedDefinitionId] = useState("");
  const [valInput, setValInput] = useState<any>("");
  const [validFrom, setValidFrom] = useState("");
  const [validUntil, setValidUntil] = useState("");
  const [note, setNote] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Bulk (multiple-cardinality) form states
  const [bulkDefinitionId, setBulkDefinitionId] = useState<string | null>(null);
  const [bulkRows, setBulkRows] = useState<BulkRow[]>([]);
  const [bulkError, setBulkError] = useState<string | null>(null);
  const [bulkSubmitting, setBulkSubmitting] = useState(false);
  // Draft rows for bulk creation when a multiple definition is selected.
  const [createBulkRows, setCreateBulkRows] = useState<BulkRow[]>(() => [newBulkRow()]);

  const formDialogRef = useRef<HTMLDialogElement>(null);
  const deleteDialogRef = useRef<HTMLDialogElement>(null);
  const bulkDialogRef = useRef<HTMLDialogElement>(null);

  // Group values by property definition so multiple-cardinality attributes
  // render as several value rows with a single group-level edit affordance.
  const groups: PropertyGroup[] = useMemo(() => {
    const order: string[] = [];
    const map = new Map<string, PersonPropertyValue[]>();
    for (const pv of properties) {
      if (!map.has(pv.property_definition_id)) {
        order.push(pv.property_definition_id);
        map.set(pv.property_definition_id, []);
      }
      map.get(pv.property_definition_id)!.push(pv);
    }
    return order.map((id) => ({
      propertyDefinitionId: id,
      values: map.get(id)!,
    }));
  }, [properties]);

  const closeFormModal = () => {
    setShowFormModal(false);
    setEditingValue(null);
  };
  const closeDeleteModal = () => {
    setDeletingValue(null);
    setDeleteError(null);
  };
  const closeBulkModal = () => {
    setBulkDefinitionId(null);
    setBulkRows([]);
    setBulkError(null);
  };

  const openDeleteModal = (pv: PersonPropertyValue) => {
    setDeletingValue(pv);
    setDeleteError(null);
  };

  useNativeDialog(formDialogRef, closeFormModal, showFormModal || editingValue !== null);
  useNativeDialog(deleteDialogRef, closeDeleteModal, deletingValue !== null);
  useNativeDialog(bulkDialogRef, closeBulkModal, bulkDefinitionId !== null);

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
    setCreateBulkRows([newBulkRow()]);
    setShowFormModal(true);
  };

  const openEditModal = (pv: PersonPropertyValue) => {
    if (pv.source_type === "vault") return;
    if (pv.cardinality === "multiple") {
      openBulkEditModal(pv.property_definition_id);
      return;
    }
    setEditingValue(pv);
    setSelectedDefinitionId(pv.property_definition_id);
    setValInput(rowValueFromProperty(pv));
    setValidFrom(pv.valid_from || "");
    setValidUntil(pv.valid_until || "");
    setNote(pv.note || "");
    setFormError(null);
  };

  const openBulkEditModal = (definitionId: string) => {
    const rows = properties
      .filter((pv) => pv.property_definition_id === definitionId)
      .map((pv) => ({
        ...newBulkRow(),
        propertyValueId: pv.property_value_id,
        valueInput: rowValueFromProperty(pv),
        validFrom: pv.valid_from || "",
        validUntil: pv.valid_until || "",
        note: pv.note || "",
      }));
    setBulkDefinitionId(definitionId);
    setBulkRows(rows.length > 0 ? rows : [newBulkRow()]);
    setBulkError(null);
  };

  const currentDefinition = definitions.find((d) => d.property_definition_id === selectedDefinitionId);
  const bulkDefinition = bulkDefinitionId
    ? definitions.find((d) => d.property_definition_id === bulkDefinitionId) ?? null
    : null;

  const handleFormSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);

    let parsedVal = valInput;
    if (currentDefinition?.data_type === "boolean") {
      if (valInput !== "true" && valInput !== "false") {
        setFormError("値を選択してください。");
        return;
      }
      parsedVal = valInput === "true";
    } else if (currentDefinition?.data_type === "number") {
      parsedVal = parseFloat(String(valInput ?? "").trim());
      if (!Number.isFinite(parsedVal)) {
        setFormError("数値を入力してください。");
        return;
      }
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

  const handleBulkSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!bulkDefinitionId || !bulkDefinition) return;
    setBulkError(null);
    setBulkSubmitting(true);
    try {
      await onBulkSaveProperty(bulkDefinitionId, {
        values: bulkRows.map((row) => ({
          ...(row.propertyValueId ? { property_value_id: row.propertyValueId } : {}),
          value: parseRowValue(bulkDefinition.data_type, row.valueInput),
          valid_from: row.validFrom.trim() || null,
          valid_until: row.validUntil.trim() || null,
          note: row.note.trim() || null,
        })),
      });
      closeBulkModal();
    } catch (err: unknown) {
      // Keep the rows so user input is not lost on save errors.
      setBulkError(err instanceof Error ? err.message : "属性値の一括保存に失敗しました。");
    } finally {
      setBulkSubmitting(false);
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

  const renderValueInput = (
    definition: PersonPropertyDefinition,
    value: string,
    onChange: (v: string) => void,
    labelPrefix: string,
    required = true,
  ) => {
    if (definition.data_type === "select") {
      return (
        <select
          aria-label={`${labelPrefix} 値`}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full rounded border border-slate-300 p-2 text-xs focus:ring-2 focus:ring-slate-800 focus:outline-none"
          required={required}
        >
          <option value="">選択してください</option>
          {definition.options?.map((opt) => (
            <option key={opt.option_id} value={opt.option_id}>
              {opt.display_name} ({opt.option_key})
            </option>
          ))}
        </select>
      );
    }
    if (definition.data_type === "boolean") {
      return (
        <select
          aria-label={`${labelPrefix} 値`}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full rounded border border-slate-300 p-2 text-xs focus:ring-2 focus:ring-slate-800 focus:outline-none"
          required={required}
        >
          <option value="">選択してください</option>
          <option value="true">はい (True)</option>
          <option value="false">いいえ (False)</option>
        </select>
      );
    }
    if (definition.data_type === "date") {
      return (
        <input
          aria-label={`${labelPrefix} 値`}
          type="date"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full rounded border border-slate-300 p-2 text-xs font-mono focus:ring-2 focus:ring-slate-800 focus:outline-none"
          required={required}
        />
      );
    }
    if (definition.data_type === "number") {
      return (
        <input
          aria-label={`${labelPrefix} 値`}
          type="number"
          step="any"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full rounded border border-slate-300 p-2 text-xs font-mono focus:ring-2 focus:ring-slate-800 focus:outline-none"
          required={required}
        />
      );
    }
    return (
      <input
        aria-label={`${labelPrefix} 値`}
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="属性値を入力"
        className="w-full rounded border border-slate-300 p-2 text-xs focus:ring-2 focus:ring-slate-800 focus:outline-none"
        required={required}
      />
    );
  };

  const renderBulkRowsEditor = (
    definition: PersonPropertyDefinition,
    rows: BulkRow[],
    setRows: (rows: BulkRow[]) => void,
    allowEmpty = false,
  ) => (
    <div className="space-y-3">
      {rows.length === 0 && (
        <div className="p-3 text-center text-[11px] text-slate-500 bg-amber-50 rounded-lg border border-amber-200">
          すべての値行を削除しました。保存するとこの属性の値がすべて削除されます。
        </div>
      )}
      {rows.map((row, idx) => {
        const labelPrefix = `値 ${idx + 1}`;
        const updateRow = (patch: Partial<BulkRow>) =>
          setRows(rows.map((r) => (r.key === row.key ? { ...r, ...patch } : r)));
        return (
          <div key={row.key} className="rounded-lg border border-slate-200 bg-slate-50 p-3 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-bold text-slate-700">{labelPrefix}</span>
              <button
                type="button"
                aria-label={`${labelPrefix}の行を削除`}
                onClick={() => setRows(rows.filter((r) => r.key !== row.key))}
                disabled={!allowEmpty && rows.length <= 1}
                className="px-2 py-0.5 text-[11px] font-semibold text-red-600 border border-red-200 rounded hover:bg-red-50 disabled:opacity-50 cursor-pointer"
              >
                行を削除
              </button>
            </div>
            <div>
              <label className="block font-semibold text-slate-700 mb-1">
                値 ({definition.data_type}) <span className="text-red-500">*</span>
              </label>
              {renderValueInput(definition, row.valueInput, (v) => updateRow({ valueInput: v }), labelPrefix)}
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block font-semibold text-slate-700 mb-1">開始日 (YYYY-MM-DD)</label>
                <input
                  aria-label={`${labelPrefix} 開始日`}
                  type="date"
                  value={row.validFrom}
                  onChange={(e) => updateRow({ validFrom: e.target.value })}
                  className="w-full rounded border border-slate-300 p-2 text-xs font-mono focus:ring-2 focus:ring-slate-800 focus:outline-none"
                />
              </div>
              <div>
                <label className="block font-semibold text-slate-700 mb-1">終了日 (YYYY-MM-DD)</label>
                <input
                  aria-label={`${labelPrefix} 終了日`}
                  type="date"
                  value={row.validUntil}
                  onChange={(e) => updateRow({ validUntil: e.target.value })}
                  className="w-full rounded border border-slate-300 p-2 text-xs font-mono focus:ring-2 focus:ring-slate-800 focus:outline-none"
                />
              </div>
            </div>
            <div>
              <label className="block font-semibold text-slate-700 mb-1">メモ (任意)</label>
              <textarea
                aria-label={`${labelPrefix} メモ`}
                value={row.note}
                onChange={(e) => updateRow({ note: e.target.value })}
                rows={2}
                className="w-full rounded border border-slate-300 p-2 text-xs focus:ring-2 focus:ring-slate-800 focus:outline-none"
              />
            </div>
          </div>
        );
      })}
      <button
        type="button"
        onClick={() => setRows([...rows, newBulkRow()])}
        className="w-full rounded border border-dashed border-slate-300 px-3 py-2 text-[11px] font-semibold text-slate-600 hover:bg-slate-50 cursor-pointer"
      >
        ＋ 値行を追加
      </button>
    </div>
  );

  // Creation dialog shows a multi-row editor when a multiple-cardinality
  // definition is selected; the rows above are the bulk-create draft.
  const handleDefinitionChangeForCreate = (defId: string) => {
    setSelectedDefinitionId(defId);
    setValInput("");
    setCreateBulkRows([newBulkRow()]);
  };

  const handleCreateBulkSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!currentDefinition) return;
    setFormError(null);
    if (createBulkRows.length === 0) {
      setFormError("値行を1件以上入力してください。");
      return;
    }
    setSubmitting(true);
    try {
      await onBulkSaveProperty(selectedDefinitionId, {
        values: createBulkRows.map((row) => ({
          value: parseRowValue(currentDefinition.data_type, row.valueInput),
          valid_from: row.validFrom.trim() || null,
          valid_until: row.validUntil.trim() || null,
          note: row.note.trim() || null,
        })),
      });
      setShowFormModal(false);
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : "属性値の保存に失敗しました。");
    } finally {
      setSubmitting(false);
    }
  };

  const isCreateMultiple = !editingValue && currentDefinition?.cardinality === "multiple";

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

      {groups.length === 0 ? (
        <div className="p-4 text-center text-xs text-slate-400 bg-slate-50 rounded-lg border border-slate-200">
          登録されている属性値はありません。
        </div>
      ) : (
        <div className="divide-y divide-slate-100">
          {groups.map((group) => {
            const first = group.values[0];
            const isVault = first.source_type === "vault";
            const isMultiple = first.cardinality === "multiple";
            return (
              <div key={group.propertyDefinitionId} className="py-1.5">
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0 text-xs font-bold text-slate-900 truncate">
                    {first.property_display_name}
                  </div>
                  <div className="flex shrink-0 items-center gap-1">
                    {isVault ? (
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-amber-100 text-amber-800 border border-amber-300">
                        Vault
                      </span>
                    ) : (
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                        DB
                      </span>
                    )}
                    {!isVault && isMultiple && (
                      <button
                        onClick={() => openBulkEditModal(group.propertyDefinitionId)}
                        aria-label={`${first.property_display_name}を一括編集`}
                        className="px-2 py-0.5 text-[11px] font-semibold text-slate-700 border border-slate-300 rounded hover:bg-slate-100 cursor-pointer"
                      >
                        編集
                      </button>
                    )}
                  </div>
                </div>
                <div>
                  {group.values.map((pv) => (
                    <div key={pv.property_value_id} className="flex items-start gap-3 py-1.5 text-xs">
                      <div className="min-w-0 flex-1">
                        <div className="font-medium text-slate-900 text-sm break-words">
                          {renderValueDisplay(pv)}
                        </div>
                        {(pv.valid_from || pv.valid_until) && (
                          <div className="text-[11px] text-slate-500">
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
                        {pv.note && <div className="text-[11px] text-slate-500">{pv.note}</div>}
                      </div>
                      {!isVault && !isMultiple && (
                        <div className="flex shrink-0 items-center gap-1">
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
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Form Modal (Create single / Edit single; create multiple uses bulk rows) */}
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
            <form onSubmit={isCreateMultiple ? handleCreateBulkSubmit : handleFormSubmit} className="p-5 space-y-4 text-xs">
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
                    onChange={(e) => handleDefinitionChangeForCreate(e.target.value)}
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

              {currentDefinition && isCreateMultiple ? (
                renderBulkRowsEditor(currentDefinition, createBulkRows, setCreateBulkRows)
              ) : (
                currentDefinition && (
                  <>
                    <div>
                      <label className="block font-semibold text-slate-700 mb-1">
                        値 ({currentDefinition.data_type}) <span className="text-red-500">*</span>
                      </label>
                      {renderValueInput(currentDefinition, valInput, setValInput, "属性値")}
                    </div>

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
                  </>
                )
              )}

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

      {/* Bulk Edit Modal (multiple-cardinality) */}
      {bulkDefinitionId && bulkDefinition && (
        <dialog
          ref={bulkDialogRef}
          onClose={closeBulkModal}
          onKeyDown={(e) => {
            if (e.key === "Escape") closeBulkModal();
          }}
          role="dialog"
          aria-modal="true"
          aria-label={`${bulkDefinition.display_name}の一括編集`}
          className="m-auto w-full max-w-md rounded-xl border border-slate-200 shadow-xl p-0 backdrop:bg-slate-900/60 backdrop:backdrop-blur-sm"
        >
          <div className="bg-white rounded-xl overflow-hidden">
            <div className="p-4 border-b border-slate-100 bg-slate-50 flex justify-between items-center">
              <h3 className="text-sm font-bold text-slate-800">
                {bulkDefinition.display_name}の一括編集
              </h3>
              <button
                onClick={closeBulkModal}
                className="text-slate-400 hover:text-slate-600 text-xs cursor-pointer"
              >
                ✕
              </button>
            </div>
            <form onSubmit={handleBulkSubmit} className="p-5 space-y-4 text-xs">
              {bulkError && (
                <div className="p-3 bg-red-50 border border-red-200 text-red-700 rounded-lg">
                  {bulkError}
                </div>
              )}
              {renderBulkRowsEditor(bulkDefinition, bulkRows, setBulkRows, true)}
              <div className="pt-2 flex justify-end gap-2 border-t border-slate-100">
                <button
                  type="button"
                  onClick={closeBulkModal}
                  className="rounded border border-slate-300 px-4 py-2 font-semibold text-slate-700 hover:bg-slate-50 cursor-pointer"
                >
                  キャンセル
                </button>
                <button
                  type="submit"
                  disabled={bulkSubmitting}
                  className="rounded bg-slate-800 px-4 py-2 font-semibold text-white hover:bg-slate-700 disabled:opacity-50 cursor-pointer"
                >
                  {bulkSubmitting ? "保存中..." : "一括保存"}
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
