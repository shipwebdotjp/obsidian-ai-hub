import { useEffect, useRef, useState } from "react";
import type { EventType, IntervalUnit } from "./types";
import { createSeries, listEventTypes, uploadMedia } from "./recurringEventsApi";
import { useNativeDialog } from "../people/useNativeDialog";
import { PhotoPicker } from "./PhotoPicker";

interface CreateSeriesModalProps {
  onClose: () => void;
  onCreated: () => void;
}

export function CreateSeriesModal({ onClose, onCreated }: CreateSeriesModalProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  useNativeDialog(dialogRef, onClose);

  const [types, setTypes] = useState<EventType[]>([]);
  const [loadingTypes, setLoadingTypes] = useState(true);
  const [selectedTypeId, setSelectedTypeId] = useState<string>("");

  const [intervalValue, setIntervalValue] = useState<number>(1);
  const [intervalUnit, setIntervalUnit] = useState<IntervalUnit>("month");
  const [propValues, setPropValues] = useState<Record<string, any>>({});

  // Initial Record fields
  const todayStr = new Date().toLocaleDateString("sv-SE"); // YYYY-MM-DD
  const [executedOn, setExecutedOn] = useState<string>(todayStr);
  const [note, setNote] = useState<string>("");
  const [countContribution, setCountContribution] = useState<number>(1);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listEventTypes()
      .then((data) => {
        setTypes(data);
        if (data.length > 0) {
          setSelectedTypeId(data[0].type_id);
        }
      })
      .catch((err) => {
        setError(err.message || "タイプの読み込みに失敗しました");
      })
      .finally(() => setLoadingTypes(false));
  }, []);

  const selectedType = types.find((t) => t.type_id === selectedTypeId);

  // Initialize property values when selected type changes
  useEffect(() => {
    if (!selectedType) return;
    const initialValues: Record<string, any> = {};
    for (const p of selectedType.properties) {
      if (p.data_type === "select" && p.options && p.options.length > 0) {
        initialValues[p.key] = p.options[0].option_key;
      } else {
        initialValues[p.key] = "";
      }
    }
    setPropValues(initialValues);
  }, [selectedTypeId]);

  const handlePropChange = (key: string, value: any) => {
    setPropValues((prev) => ({ ...prev, [key]: value }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedType) return;
    setError(null);
    setSubmitting(true);

    try {
      let mediaId: string | null = null;
      if (selectedFile) {
        const uploaded = await uploadMedia(selectedFile);
        mediaId = uploaded.media_id;
      }

      await createSeries({
        type_id: selectedType.type_id,
        interval_value: Number(intervalValue),
        interval_unit: intervalUnit,
        property_values: propValues,
        executed_on: executedOn,
        note: note.trim() || null,
        media_id: mediaId,
        count_contribution: Number(countContribution),
      });

      onCreated();
      onClose();
    } catch (err: any) {
      setError(err.message || "シリーズの作成に失敗しました");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <dialog
      ref={dialogRef}
      onClose={onClose}
      className="m-auto w-full max-w-lg rounded-xl border border-slate-200 bg-white p-0 shadow-xl backdrop:bg-slate-900/40"
    >
      <div className="flex max-h-[85vh] flex-col">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
          <h2 className="text-lg font-bold text-slate-900">シリーズ新規作成</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
          >
            ✕
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 min-h-0 overflow-y-auto p-6 space-y-4">
          {error && (
            <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700 border border-red-200">
              {error}
            </div>
          )}

          {loadingTypes ? (
            <p className="text-center py-4 text-sm text-slate-500">タイプ情報を読み込み中...</p>
          ) : types.length === 0 ? (
            <div className="text-center py-6 space-y-2">
              <p className="text-sm text-slate-600">
                作成可能なイベントタイプが存在しません。まず「イベントタイプ管理」からタイプを作成してください。
              </p>
            </div>
          ) : (
            <form id="create-series-form" onSubmit={handleSubmit} className="space-y-4">
              {/* Event Type Select */}
              <div>
                <label className="block text-sm font-medium text-slate-700">イベントタイプ</label>
                <select
                  value={selectedTypeId}
                  onChange={(e) => setSelectedTypeId(e.target.value)}
                  className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-sm bg-white focus:border-slate-900 focus:outline-none"
                >
                  {types.map((t) => (
                    <option key={t.type_id} value={t.type_id}>
                      {t.name}
                    </option>
                  ))}
                </select>
              </div>

              {/* Dynamic Property Values */}
              {selectedType && selectedType.properties.length > 0 && (
                <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 space-y-3">
                  <span className="text-xs font-semibold text-slate-700">属性プロパティ</span>
                  {selectedType.properties.map((p) => (
                    <div key={p.key}>
                      <label className="block text-xs font-medium text-slate-600">
                        {p.display_name} ({p.key})
                      </label>
                      {p.data_type === "select" ? (
                        <select
                          value={propValues[p.key] || ""}
                          onChange={(e) => handlePropChange(p.key, e.target.value)}
                          className="mt-1 block w-full rounded border border-slate-300 px-2 py-1.5 text-xs bg-white"
                        >
                          {(p.options || []).map((opt) => (
                            <option key={opt.option_key} value={opt.option_key}>
                              {opt.display_name}
                            </option>
                          ))}
                        </select>
                      ) : p.data_type === "number" ? (
                        <input
                          type="number"
                          value={propValues[p.key] ?? ""}
                          onChange={(e) => handlePropChange(p.key, e.target.value)}
                          className="mt-1 block w-full rounded border border-slate-300 px-2 py-1.5 text-xs bg-white"
                          required
                        />
                      ) : (
                        <input
                          type="text"
                          value={propValues[p.key] ?? ""}
                          onChange={(e) => handlePropChange(p.key, e.target.value)}
                          placeholder={`例: ${p.display_name}`}
                          className="mt-1 block w-full rounded border border-slate-300 px-2 py-1.5 text-xs bg-white"
                          required
                        />
                      )}
                    </div>
                  ))}
                </div>
              )}

              {/* Recommended Interval */}
              <div>
                <label className="block text-sm font-medium text-slate-700">推奨間隔</label>
                <div className="mt-1 flex gap-2">
                  <input
                    type="number"
                    min="1"
                    value={intervalValue}
                    onChange={(e) => setIntervalValue(Math.max(1, parseInt(e.target.value) || 1))}
                    className="w-2/3 rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-slate-900 focus:outline-none"
                    required
                  />
                  <select
                    value={intervalUnit}
                    onChange={(e) => setIntervalUnit(e.target.value as IntervalUnit)}
                    className="w-1/3 rounded-lg border border-slate-300 px-3 py-2 text-sm bg-white focus:border-slate-900 focus:outline-none"
                  >
                    <option value="day">日</option>
                    <option value="week">週</option>
                    <option value="month">月</option>
                  </select>
                </div>
              </div>

              {/* Initial Record */}
              <div className="border-t border-slate-200 pt-3 space-y-3">
                <span className="text-sm font-semibold text-slate-800">開始実績（最初の記録）</span>

                <div>
                  <label className="block text-xs font-medium text-slate-600">実行日 (JST)</label>
                  <input
                    type="date"
                    value={executedOn}
                    max={todayStr}
                    onChange={(e) => setExecutedOn(e.target.value)}
                    className="mt-1 block w-full rounded border border-slate-300 px-3 py-1.5 text-xs bg-white"
                    required
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-slate-600">初期通算回数</label>
                  <input
                    type="number"
                    min="0"
                    value={countContribution}
                    onChange={(e) => setCountContribution(parseInt(e.target.value) || 0)}
                    className="mt-1 block w-full rounded border border-slate-300 px-3 py-1.5 text-xs bg-white"
                    required
                  />
                  <span className="text-[11px] text-slate-400">
                    ※ 過去からの累計回数を引き継ぐ場合は数字を変更してください（通常は1）。
                  </span>
                </div>

                <div>
                  <label className="block text-xs font-medium text-slate-600">メモ（任意）</label>
                  <textarea
                    rows={2}
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    placeholder="メモ・補足事項"
                    className="mt-1 block w-full rounded border border-slate-300 px-3 py-1.5 text-xs bg-white resize-none"
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-slate-600">写真添付（任意）</label>
                  <div className="mt-1">
                    <PhotoPicker selectedFile={selectedFile} onSelect={setSelectedFile} />
                  </div>
                </div>
              </div>
            </form>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 border-t border-slate-200 px-6 py-3 bg-slate-50">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100"
          >
            キャンセル
          </button>
          {types.length > 0 && (
            <button
              type="submit"
              form="create-series-form"
              disabled={submitting}
              className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
            >
              {submitting ? "作成中..." : "作成"}
            </button>
          )}
        </div>
      </div>
    </dialog>
  );
}
