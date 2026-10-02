import { useEffect, useRef, useState } from "react";
import type { EventType, PropertyDataType, PropertyDefinition, PropertyOption } from "./types";
import {
  createEventType,
  deleteEventType,
  listEventTypes,
  updateEventType,
} from "./recurringEventsApi";
import { useNativeDialog } from "../people/useNativeDialog";

interface EventTypesModalProps {
  onClose: () => void;
  onTypesUpdated: () => void;
}

export function EventTypesModal({ onClose, onTypesUpdated }: EventTypesModalProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  useNativeDialog(dialogRef, onClose);

  const [types, setTypes] = useState<EventType[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Form mode: null (list) or "create" or EventType (edit)
  const [editingType, setEditingType] = useState<EventType | null | "create">(null);

  // Form state
  const [name, setName] = useState("");
  const [properties, setProperties] = useState<PropertyDefinition[]>([]);

  const loadTypes = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listEventTypes();
      setTypes(data);
    } catch (e: any) {
      setError(e.message || "イベントタイプの取得に失敗しました");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadTypes();
  }, []);

  const handleStartCreate = () => {
    setName("");
    setProperties([]);
    setError(null);
    setEditingType("create");
  };

  const handleStartEdit = (t: EventType) => {
    setName(t.name);
    setProperties(
      t.properties.map((p) => ({
        ...p,
        options: p.options ? [...p.options] : [],
      }))
    );
    setError(null);
    setEditingType(t);
  };

  const handleAddProperty = () => {
    setProperties((prev) => [
      ...prev,
      {
        key: "",
        display_name: "",
        data_type: "text",
        options: [],
      },
    ]);
  };

  const handleRemoveProperty = (index: number) => {
    setProperties((prev) => prev.filter((_, i) => i !== index));
  };

  const handlePropertyChange = (
    index: number,
    field: keyof PropertyDefinition,
    value: any
  ) => {
    setProperties((prev) => {
      const next = [...prev];
      next[index] = { ...next[index], [field]: value };
      return next;
    });
  };

  const handleAddOption = (propIndex: number) => {
    setProperties((prev) => {
      const next = [...prev];
      const opts = next[propIndex].options || [];
      next[propIndex].options = [
        ...opts,
        { option_key: "", display_name: "" },
      ];
      return next;
    });
  };

  const handleRemoveOption = (propIndex: number, optIndex: number) => {
    setProperties((prev) => {
      const next = [...prev];
      const opts = [...(next[propIndex].options || [])];
      opts.splice(optIndex, 1);
      next[propIndex].options = opts;
      return next;
    });
  };

  const handleOptionChange = (
    propIndex: number,
    optIndex: number,
    field: keyof PropertyOption,
    value: string
  ) => {
    setProperties((prev) => {
      const next = [...prev];
      const opts = [...(next[propIndex].options || [])];
      opts[optIndex] = { ...opts[optIndex], [field]: value };
      next[propIndex].options = opts;
      return next;
    });
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!name.trim()) {
      setError("タイプ名を入力してください。");
      return;
    }

    try {
      if (editingType === "create") {
        await createEventType({ name: name.trim(), properties });
      } else if (editingType) {
        await updateEventType(editingType.type_id, {
          name: name.trim(),
          properties,
        });
      }
      setEditingType(null);
      await loadTypes();
      onTypesUpdated();
    } catch (err: any) {
      setError(err.message || "保存に失敗しました");
    }
  };

  const handleDelete = async (typeId: string) => {
    if (!window.confirm("このイベントタイプを削除しますか？")) return;
    setError(null);
    try {
      await deleteEventType(typeId);
      await loadTypes();
      onTypesUpdated();
    } catch (err: any) {
      setError(err.message || "削除に失敗しました");
    }
  };

  const isLocked = typeof editingType === "object" && editingType !== null && editingType.series_count > 0;

  return (
    <dialog
      ref={dialogRef}
      onClose={onClose}
      className="m-auto w-full max-w-2xl rounded-xl border border-slate-200 bg-white p-0 shadow-xl backdrop:bg-slate-900/40"
    >
      <div className="flex max-h-[85vh] flex-col">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
          <h2 className="text-lg font-bold text-slate-900">
            {editingType === "create"
              ? "イベントタイプの新規作成"
              : editingType
              ? "イベントタイプの編集"
              : "イベントタイプ管理"}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
          >
            ✕
          </button>
        </div>

        {/* Content Body */}
        <div className="flex-1 min-h-0 overflow-y-auto p-6 space-y-4">
          {error && (
            <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700 border border-red-200">
              {error}
            </div>
          )}

          {editingType === null ? (
            /* List View */
            <div className="space-y-4">
              <div className="flex justify-between items-center">
                <p className="text-sm text-slate-600">
                  定期記録の分類（例: 散髪、脱毛、オイル交換）を管理します。
                </p>
                <button
                  type="button"
                  onClick={handleStartCreate}
                  className="rounded-lg bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800"
                >
                  ＋ 新規作成
                </button>
              </div>

              {loading ? (
                <p className="py-4 text-center text-sm text-slate-500">読み込み中...</p>
              ) : types.length === 0 ? (
                <p className="py-8 text-center text-sm text-slate-500">
                  イベントタイプが登録されていません。
                </p>
              ) : (
                <div className="space-y-3">
                  {types.map((t) => (
                    <div
                      key={t.type_id}
                      className="flex items-center justify-between rounded-lg border border-slate-200 p-4 hover:border-slate-300"
                    >
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-semibold text-slate-900">{t.name}</span>
                          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
                            シリーズ: {t.series_count}件
                          </span>
                        </div>
                        {t.properties.length > 0 ? (
                          <div className="mt-1 flex flex-wrap gap-1 text-xs text-slate-500">
                            プロパティ:{" "}
                            {t.properties.map((p) => p.display_name).join(", ")}
                          </div>
                        ) : (
                          <p className="mt-1 text-xs text-slate-400">プロパティなし</p>
                        )}
                      </div>
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => handleStartEdit(t)}
                          className="rounded border border-slate-300 px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50"
                        >
                          編集
                        </button>
                        {t.series_count === 0 && (
                          <button
                            type="button"
                            onClick={() => handleDelete(t.type_id)}
                            className="rounded border border-red-200 px-2.5 py-1 text-xs font-medium text-red-600 hover:bg-red-50"
                          >
                            削除
                          </button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            /* Create / Edit Form */
            <form id="event-type-form" onSubmit={handleSave} className="space-y-5">
              {isLocked && (
                <div className="rounded-lg bg-amber-50 p-3 text-xs text-amber-800 border border-amber-200">
                  ※ このタイプには作成済みのシリーズが存在するため、プロパティの追加・削除・キー変更・型変更は制限されています。表示名の変更や選択肢の追加は可能です。
                </div>
              )}

              <div>
                <label className="block text-sm font-medium text-slate-700">タイプ名</label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="例: 散髪、オイル交換"
                  className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-slate-900 focus:outline-none"
                  required
                />
              </div>

              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <label className="block text-sm font-medium text-slate-700">
                    プロパティ定義（任意）
                  </label>
                  {!isLocked && (
                    <button
                      type="button"
                      onClick={handleAddProperty}
                      className="text-xs font-medium text-slate-900 hover:underline"
                    >
                      ＋ プロパティ追加
                    </button>
                  )}
                </div>

                {properties.length === 0 ? (
                  <p className="text-xs text-slate-400 italic">プロパティは登録されていません。</p>
                ) : (
                  properties.map((prop, pIdx) => (
                    <div
                      key={pIdx}
                      className="rounded-lg border border-slate-200 bg-slate-50 p-3 space-y-3"
                    >
                      <div className="grid grid-cols-12 gap-2 items-center">
                        <div className="col-span-4">
                          <label className="block text-[11px] text-slate-500">キー (英数)</label>
                          <input
                            type="text"
                            value={prop.key}
                            disabled={isLocked}
                            onChange={(e) => handlePropertyChange(pIdx, "key", e.target.value)}
                            placeholder="例: part, car"
                            className="mt-0.5 block w-full rounded border border-slate-300 px-2 py-1 text-xs bg-white disabled:bg-slate-100"
                            required
                          />
                        </div>
                        <div className="col-span-4">
                          <label className="block text-[11px] text-slate-500">表示名</label>
                          <input
                            type="text"
                            value={prop.display_name}
                            onChange={(e) => handlePropertyChange(pIdx, "display_name", e.target.value)}
                            placeholder="例: 部位, 車種"
                            className="mt-0.5 block w-full rounded border border-slate-300 px-2 py-1 text-xs bg-white"
                            required
                          />
                        </div>
                        <div className="col-span-3">
                          <label className="block text-[11px] text-slate-500">入力種別</label>
                          <select
                            value={prop.data_type}
                            disabled={isLocked}
                            onChange={(e) => handlePropertyChange(pIdx, "data_type", e.target.value as PropertyDataType)}
                            className="mt-0.5 block w-full rounded border border-slate-300 px-2 py-1 text-xs bg-white disabled:bg-slate-100"
                          >
                            <option value="text">テキスト</option>
                            <option value="number">数値</option>
                            <option value="select">選択肢 (select)</option>
                          </select>
                        </div>
                        <div className="col-span-1 text-right pt-4">
                          {!isLocked && (
                            <button
                              type="button"
                              onClick={() => handleRemoveProperty(pIdx)}
                              className="text-red-600 hover:text-red-800 text-xs"
                            >
                              ✕
                            </button>
                          )}
                        </div>
                      </div>

                      {/* Select Options */}
                      {prop.data_type === "select" && (
                        <div className="mt-2 border-t border-slate-200 pt-2 space-y-2">
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-medium text-slate-600">選択肢一覧</span>
                            <button
                              type="button"
                              onClick={() => handleAddOption(pIdx)}
                              className="text-[11px] text-slate-900 font-medium hover:underline"
                            >
                              ＋ 選択肢追加
                            </button>
                          </div>
                          {(prop.options || []).map((opt, oIdx) => (
                            <div key={oIdx} className="flex items-center gap-2">
                              <input
                                type="text"
                                value={opt.option_key}
                                onChange={(e) => handleOptionChange(pIdx, oIdx, "option_key", e.target.value)}
                                placeholder="キー (例: beard)"
                                className="w-1/2 rounded border border-slate-300 px-2 py-1 text-xs bg-white"
                                required
                              />
                              <input
                                type="text"
                                value={opt.display_name}
                                onChange={(e) => handleOptionChange(pIdx, oIdx, "display_name", e.target.value)}
                                placeholder="表示名 (例: ひげ)"
                                className="w-1/2 rounded border border-slate-300 px-2 py-1 text-xs bg-white"
                                required
                              />
                              {!isLocked && (
                                <button
                                  type="button"
                                  onClick={() => handleRemoveOption(pIdx, oIdx)}
                                  className="text-slate-400 hover:text-red-600 text-xs px-1"
                                >
                                  ✕
                                </button>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  ))
                )}
              </div>
            </form>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 border-t border-slate-200 px-6 py-3 bg-slate-50">
          {editingType !== null ? (
            <>
              <button
                type="button"
                onClick={() => setEditingType(null)}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100"
              >
                キャンセル
              </button>
              <button
                type="submit"
                form="event-type-form"
                className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800"
              >
                保存
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100"
            >
              閉じる
            </button>
          )}
        </div>
      </div>
    </dialog>
  );
}
