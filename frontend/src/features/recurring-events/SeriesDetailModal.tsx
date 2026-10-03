import { useEffect, useRef, useState } from "react";
import type { ExecutionRecord, IntervalUnit, RecurringEventSeries } from "./types";
import {
  addExecutionRecord,
  deleteExecutionRecord,
  getSeries,
  updateExecutionRecord,
  updateSeriesInterval,
  uploadMedia,
} from "./recurringEventsApi";
import { useMediaObjectUrl } from "../media/useMediaObjectUrl";
import { useNativeDialog } from "../people/useNativeDialog";

function RecordPhotoView({ mediaId, filename }: { mediaId: string; filename?: string }) {
  const { objectUrl, error } = useMediaObjectUrl(mediaId);

  if (error || !objectUrl) {
    return (
      <div className="h-20 w-20 rounded-lg border border-slate-200 bg-slate-50 flex items-center justify-center text-[10px] text-slate-400">
        {error ? "エラー" : "読み込み中..."}
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={() => {
        const a = document.createElement("a");
        a.href = objectUrl;
        a.download = filename || mediaId;
        document.body.appendChild(a);
        a.click();
        a.remove();
      }}
      title="クリックで保存/ダウンロード"
      className="inline-block cursor-pointer focus:outline-none"
    >
      <img
        src={objectUrl}
        alt={filename || "実行写真"}
        className="h-20 w-20 object-cover rounded-lg border border-slate-200 hover:opacity-90"
      />
    </button>
  );
}

function RecordPhotoEditThumb({ mediaId, filename }: { mediaId: string; filename?: string }) {
  const { objectUrl, error } = useMediaObjectUrl(mediaId);

  if (error || !objectUrl) {
    return (
      <div className="h-10 w-10 rounded border border-slate-200 bg-slate-50 flex items-center justify-center text-[10px] text-slate-400">
        ...
      </div>
    );
  }

  return (
    <img
      src={objectUrl}
      alt={filename || "既存の写真"}
      className="h-10 w-10 object-cover rounded border border-slate-200"
    />
  );
}

interface SeriesDetailModalProps {
  seriesId: string;
  onClose: () => void;
  onUpdated: () => void;
}

export function SeriesDetailModal({ seriesId, onClose, onUpdated }: SeriesDetailModalProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  useNativeDialog(dialogRef, onClose);

  const [series, setSeries] = useState<RecurringEventSeries | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Interval editing state
  const [editingInterval, setEditingInterval] = useState(false);
  const [intervalVal, setIntervalVal] = useState<number>(1);
  const [intervalUnit, setIntervalUnit] = useState<IntervalUnit>("month");

  // New Record state
  const todayStr = new Date().toLocaleDateString("sv-SE"); // YYYY-MM-DD
  const [newExecutedOn, setNewExecutedOn] = useState<string>(todayStr);
  const [newNote, setNewNote] = useState<string>("");
  const [newFile, setNewFile] = useState<File | null>(null);
  const [addingRecord, setAddingRecord] = useState(false);

  // Record Editing state
  const [editingRecord, setEditingRecord] = useState<ExecutionRecord | null>(null);
  const [editExecutedOn, setEditExecutedOn] = useState<string>("");
  const [editNote, setEditNote] = useState<string>("");
  const [editCountContribution, setEditCountContribution] = useState<number>(1);
  const [editFile, setEditFile] = useState<File | null>(null);
  const [clearMediaFlag, setClearMediaFlag] = useState<boolean>(false);
  const [savingRecord, setSavingRecord] = useState(false);

  const loadDetail = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getSeries(seriesId);
      setSeries(data);
      setIntervalVal(data.interval_value);
      setIntervalUnit(data.interval_unit);
    } catch (err: any) {
      setError(err.message || "詳細の取得に失敗しました");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadDetail();
  }, [seriesId]);

  const handleSaveInterval = async () => {
    if (!series) return;
    setError(null);
    try {
      const updated = await updateSeriesInterval(series.series_id, {
        interval_value: Number(intervalVal),
        interval_unit: intervalUnit,
      });
      setSeries(updated);
      setEditingInterval(false);
      onUpdated();
    } catch (err: any) {
      setError(err.message || "推奨間隔の変更に失敗しました");
    }
  };

  const handleAddRecordSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!series) return;
    setError(null);
    setAddingRecord(true);

    try {
      let mediaId: string | null = null;
      if (newFile) {
        const uploaded = await uploadMedia(newFile);
        mediaId = uploaded.media_id;
      }

      const updated = await addExecutionRecord(series.series_id, {
        executed_on: newExecutedOn,
        note: newNote.trim() || null,
        media_id: mediaId,
      });

      setSeries(updated);
      setNewNote("");
      setNewFile(null);
      setNewExecutedOn(todayStr);
      onUpdated();
    } catch (err: any) {
      setError(err.message || "記録の追加に失敗しました");
    } finally {
      setAddingRecord(false);
    }
  };

  const handleStartEditRecord = (rec: ExecutionRecord) => {
    setEditingRecord(rec);
    setEditExecutedOn(rec.executed_on);
    setEditNote(rec.note || "");
    setEditCountContribution(rec.count_contribution);
    setEditFile(null);
    setClearMediaFlag(false);
  };

  const handleSaveEditRecord = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingRecord) return;
    setError(null);
    setSavingRecord(true);

    try {
      let mediaId: string | undefined = undefined;
      if (editFile) {
        const uploaded = await uploadMedia(editFile);
        mediaId = uploaded.media_id;
      }

      const updated = await updateExecutionRecord(editingRecord.record_id, {
        executed_on: editExecutedOn,
        note: editNote.trim() || null,
        media_id: mediaId,
        clear_media: clearMediaFlag,
        count_contribution: editingRecord.is_start_record ? Number(editCountContribution) : undefined,
      });

      setSeries(updated);
      setEditingRecord(null);
      onUpdated();
    } catch (err: any) {
      setError(err.message || "記録の更新に失敗しました");
    } finally {
      setSavingRecord(false);
    }
  };

  const handleDeleteRecord = async (rec: ExecutionRecord) => {
    const isLast = series?.records.length === 1;
    const msg = isLast
      ? "この記録を削除すると、シリーズ自体も削除されます。よろしいですか？"
      : "この実行記録を削除しますか？";

    if (!window.confirm(msg)) return;

    setError(null);
    try {
      const res = await deleteExecutionRecord(rec.record_id);
      if (res.series_deleted) {
        onUpdated();
        onClose();
      } else {
        await loadDetail();
        onUpdated();
      }
    } catch (err: any) {
      setError(err.message || "記録の削除に失敗しました");
    }
  };

  const formatUnit = (unit: IntervalUnit) => {
    switch (unit) {
      case "day":
        return "日";
      case "week":
        return "週";
      case "month":
        return "月";
    }
  };

  return (
    <dialog
      ref={dialogRef}
      onClose={onClose}
      className="m-auto w-full max-w-2xl rounded-xl border border-slate-200 bg-white p-0 shadow-xl backdrop:bg-slate-900/40"
    >
      <div className="flex max-h-[85vh] flex-col">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
          <div>
            <h2 className="text-lg font-bold text-slate-900">
              {series ? `${series.type_name} 詳細` : "シリーズ詳細"}
            </h2>
            {series && series.properties.length > 0 && (
              <div className="mt-1 flex flex-wrap gap-1 text-xs text-slate-500">
                {series.properties.map((p) => (
                  <span
                    key={p.property_id}
                    className="rounded bg-slate-100 px-1.5 py-0.5 font-medium text-slate-700"
                  >
                    {p.display_name}: {p.value_display}
                  </span>
                ))}
              </div>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
          >
            ✕
          </button>
        </div>

        {/* Content Body */}
        <div className="flex-1 min-h-0 overflow-y-auto p-6 space-y-6">
          {error && (
            <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700 border border-red-200">
              {error}
            </div>
          )}

          {loading || !series ? (
            <p className="text-center py-8 text-sm text-slate-500">詳細を読み込み中...</p>
          ) : (
            <>
              {/* Metrics & Interval Banner */}
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 grid grid-cols-2 md:grid-cols-4 gap-4 text-center">
                <div>
                  <span className="block text-[11px] text-slate-500">通算回数</span>
                  <span className="text-base font-bold text-slate-900">
                    {series.total_count} 回
                  </span>
                </div>
                <div>
                  <span className="block text-[11px] text-slate-500">最新実行日</span>
                  <span className="text-base font-semibold text-slate-800">
                    {series.latest_executed_on || "未実行"}
                  </span>
                </div>
                <div>
                  <span className="block text-[11px] text-slate-500">経過日数</span>
                  <span className="text-base font-semibold text-slate-800">
                    {series.elapsed_days !== null ? `${series.elapsed_days} 日` : "-"}
                  </span>
                </div>
                <div>
                  <span className="block text-[11px] text-slate-500">次回予定日</span>
                  <span className="text-base font-bold text-emerald-700">
                    {series.next_due_date || "-"}
                  </span>
                </div>
              </div>

              {/* Interval Setting */}
              <div className="flex items-center justify-between border-b border-slate-200 pb-4">
                <div className="text-xs text-slate-600">
                  推奨間隔:{" "}
                  {editingInterval ? (
                    <span className="inline-flex items-center gap-1 ml-1">
                      <input
                        type="number"
                        min="1"
                        value={intervalVal}
                        onChange={(e) => setIntervalVal(Math.max(1, parseInt(e.target.value) || 1))}
                        className="w-16 rounded border border-slate-300 px-2 py-0.5 text-xs bg-white"
                      />
                      <select
                        value={intervalUnit}
                        onChange={(e) => setIntervalUnit(e.target.value as IntervalUnit)}
                        className="rounded border border-slate-300 px-2 py-0.5 text-xs bg-white"
                      >
                        <option value="day">日</option>
                        <option value="week">週</option>
                        <option value="month">月</option>
                      </select>
                    </span>
                  ) : (
                    <span className="font-semibold text-slate-800">
                      {series.interval_value} {formatUnit(series.interval_unit)}ごと
                    </span>
                  )}
                </div>

                {editingInterval ? (
                  <div className="flex gap-1">
                    <button
                      type="button"
                      onClick={() => setEditingInterval(false)}
                      className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-100"
                    >
                      キャンセル
                    </button>
                    <button
                      type="button"
                      onClick={handleSaveInterval}
                      className="rounded bg-slate-900 px-2.5 py-1 text-xs text-white hover:bg-slate-800"
                    >
                      保存
                    </button>
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => setEditingInterval(true)}
                    className="text-xs font-medium text-slate-700 hover:underline"
                  >
                    間隔を変更
                  </button>
                )}
              </div>

              {/* Add New Record Form */}
              <div className="rounded-xl border border-slate-200 bg-white p-4 space-y-3">
                <h3 className="text-sm font-bold text-slate-900">新しい記録を追加</h3>
                <form onSubmit={handleAddRecordSubmit} className="space-y-3">
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div>
                      <label className="block text-xs font-medium text-slate-600">実行日 (JST)</label>
                      <input
                        type="date"
                        value={newExecutedOn}
                        max={todayStr}
                        onChange={(e) => setNewExecutedOn(e.target.value)}
                        className="mt-1 block w-full rounded border border-slate-300 px-2.5 py-1.5 text-xs bg-white"
                        required
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-slate-600">写真添付 (任意)</label>
                      <input
                        type="file"
                        accept="image/*"
                        onChange={(e) => setNewFile(e.target.files?.[0] || null)}
                        className="mt-1 block w-full text-xs text-slate-500 file:mr-2 file:py-1 file:px-2.5 file:rounded file:border-0 file:text-xs file:font-semibold file:bg-slate-100 file:text-slate-700 hover:file:bg-slate-200"
                      />
                    </div>
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-slate-600">メモ (任意)</label>
                    <input
                      type="text"
                      value={newNote}
                      onChange={(e) => setNewNote(e.target.value)}
                      placeholder="例: シャンプー付き、オイルフィルター交換含む"
                      className="mt-1 block w-full rounded border border-slate-300 px-2.5 py-1.5 text-xs bg-white"
                    />
                  </div>

                  <div className="flex justify-end">
                    <button
                      type="submit"
                      disabled={addingRecord}
                      className="rounded-lg bg-slate-900 px-3.5 py-1.5 text-xs font-medium text-white hover:bg-slate-800 disabled:opacity-50"
                    >
                      {addingRecord ? "追加中..." : "記録を追加"}
                    </button>
                  </div>
                </form>
              </div>

              {/* History / Records List */}
              <div className="space-y-3">
                <h3 className="text-sm font-bold text-slate-900">実行記録 履歴</h3>
                {series.records.length === 0 ? (
                  <p className="text-center py-6 text-xs text-slate-400">記録がありません。</p>
                ) : (
                  <div className="space-y-3">
                    {series.records.map((rec) => (
                      <div
                        key={rec.record_id}
                        className="rounded-xl border border-slate-200 p-4 bg-white hover:border-slate-300 transition-colors"
                      >
                        {editingRecord?.record_id === rec.record_id ? (
                          /* Edit Record Form */
                          <form onSubmit={handleSaveEditRecord} className="space-y-3">
                            <div className="flex items-center justify-between border-b border-slate-200 pb-2">
                              <span className="text-xs font-bold text-slate-800">記録の編集</span>
                              {rec.is_start_record && (
                                <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-800">
                                  開始記録
                                </span>
                              )}
                            </div>

                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                              <div>
                                <label className="block text-xs font-medium text-slate-600">実行日 (JST)</label>
                                <input
                                  type="date"
                                  value={editExecutedOn}
                                  max={todayStr}
                                  onChange={(e) => setEditExecutedOn(e.target.value)}
                                  className="mt-1 block w-full rounded border border-slate-300 px-2.5 py-1.5 text-xs bg-white"
                                  required
                                />
                              </div>

                              {rec.is_start_record && (
                                <div>
                                  <label className="block text-xs font-medium text-slate-600">回数寄与</label>
                                  <input
                                    type="number"
                                    min="0"
                                    value={editCountContribution}
                                    onChange={(e) => setEditCountContribution(parseInt(e.target.value) || 0)}
                                    className="mt-1 block w-full rounded border border-slate-300 px-2.5 py-1.5 text-xs bg-white"
                                    required
                                  />
                                </div>
                              )}
                            </div>

                            <div>
                              <label className="block text-xs font-medium text-slate-600">メモ</label>
                              <input
                                type="text"
                                value={editNote}
                                onChange={(e) => setEditNote(e.target.value)}
                                className="mt-1 block w-full rounded border border-slate-300 px-2.5 py-1.5 text-xs bg-white"
                              />
                            </div>

                            <div>
                              <label className="block text-xs font-medium text-slate-600">写真変更 / 解除</label>
                              {rec.media && !clearMediaFlag && (
                                <div className="mt-1 flex items-center gap-2">
                                  <RecordPhotoEditThumb
                                    mediaId={rec.media.media_id}
                                    filename={rec.media.filename}
                                  />
                                  <button
                                    type="button"
                                    onClick={() => setClearMediaFlag(true)}
                                    className="text-xs text-red-600 hover:underline"
                                  >
                                    写真を解除する
                                  </button>
                                </div>
                              )}

                              {(clearMediaFlag || !rec.media) && (
                                <div className="mt-1">
                                  <input
                                    type="file"
                                    accept="image/*"
                                    onChange={(e) => {
                                      setEditFile(e.target.files?.[0] || null);
                                      setClearMediaFlag(false);
                                    }}
                                    className="block w-full text-xs text-slate-500 file:mr-2 file:py-1 file:px-2.5 file:rounded file:border-0 file:text-xs file:font-semibold file:bg-slate-100 file:text-slate-700 hover:file:bg-slate-200"
                                  />
                                </div>
                              )}
                            </div>

                            <div className="flex justify-end gap-2 pt-2">
                              <button
                                type="button"
                                onClick={() => setEditingRecord(null)}
                                className="rounded border border-slate-300 px-3 py-1 text-xs text-slate-600 hover:bg-slate-100"
                              >
                                キャンセル
                              </button>
                              <button
                                type="submit"
                                disabled={savingRecord}
                                className="rounded bg-slate-900 px-3 py-1 text-xs font-medium text-white hover:bg-slate-800 disabled:opacity-50"
                              >
                                {savingRecord ? "保存中..." : "保存"}
                              </button>
                            </div>
                          </form>
                        ) : (
                          /* View Record Item */
                          <div className="flex items-start justify-between gap-4">
                            <div className="space-y-1">
                              <div className="flex items-center gap-2">
                                <span className="text-sm font-bold text-slate-900">
                                  {rec.executed_on}
                                </span>
                                {rec.is_start_record && (
                                  <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-800">
                                    開始記録
                                  </span>
                                )}
                                <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-600">
                                  回数寄与: +{rec.count_contribution}
                                </span>
                              </div>

                              {rec.note ? (
                                <p className="text-xs text-slate-700">{rec.note}</p>
                              ) : (
                                <p className="text-xs text-slate-400 italic">メモなし</p>
                              )}

                              {rec.media && (
                                <div className="pt-2">
                                  <RecordPhotoView
                                    mediaId={rec.media.media_id}
                                    filename={rec.media.filename}
                                  />
                                </div>
                              )}
                            </div>

                            <div className="flex items-center gap-2 shrink-0">
                              <button
                                type="button"
                                onClick={() => handleStartEditRecord(rec)}
                                className="rounded border border-slate-300 px-2 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50"
                              >
                                編集
                              </button>
                              <button
                                type="button"
                                onClick={() => handleDeleteRecord(rec)}
                                className="rounded border border-red-200 px-2 py-1 text-xs font-medium text-red-600 hover:bg-red-50"
                              >
                                削除
                              </button>
                            </div>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end border-t border-slate-200 px-6 py-3 bg-slate-50">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100"
          >
            閉じる
          </button>
        </div>
      </div>
    </dialog>
  );
}
