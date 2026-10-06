import { useEffect, useState } from "react";
import type { IntervalUnit, RecurringEventSeries } from "./types";
import { listSeries } from "./recurringEventsApi";
import { formatYmdWithDow } from "../../utils/date";
import { useMediaObjectUrl } from "../media/useMediaObjectUrl";
import { EventTypesModal } from "./EventTypesModal";
import { CreateSeriesModal } from "./CreateSeriesModal";
import { SeriesDetailModal } from "./SeriesDetailModal";

function SeriesPhotoThumbnail({ mediaId, filename }: { mediaId: string; filename?: string }) {
  const { objectUrl, error } = useMediaObjectUrl(mediaId);

  if (error || !objectUrl) {
    return (
      <div className="h-14 w-14 rounded-lg border border-slate-200 bg-slate-50 flex items-center justify-center text-[10px] text-slate-400 shrink-0">
        {error ? "エラー" : "読み込み中..."}
      </div>
    );
  }

  return (
    <img
      src={objectUrl}
      alt={filename || "最新写真"}
      className="h-14 w-14 object-cover rounded-lg border border-slate-200 shrink-0"
    />
  );
}

export default function RecurringEventsPage() {
  const [seriesList, setSeriesList] = useState<RecurringEventSeries[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filter
  const [filterText, setFilterText] = useState("");

  // Modals
  const [showEventTypesModal, setShowEventTypesModal] = useState(false);
  const [showCreateSeriesModal, setShowCreateSeriesModal] = useState(false);
  const [selectedDetailSeriesId, setSelectedDetailSeriesId] = useState<string | null>(null);

  const loadSeries = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listSeries();
      setSeriesList(data);
    } catch (err: any) {
      setError(err.message || "定期記録シリーズの取得に失敗しました");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadSeries();
  }, []);

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

  const getDueDateBadge = (nextDueDateStr: string | null) => {
    if (!nextDueDateStr) {
      return (
        <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600">
          予定なし
        </span>
      );
    }

    const todayStr = new Date().toLocaleDateString("sv-SE"); // YYYY-MM-DD JST/local
    if (nextDueDateStr < todayStr) {
      return (
        <span className="rounded-full bg-red-100 px-2.5 py-1 text-xs font-semibold text-red-700 border border-red-200">
          期限超過: {formatYmdWithDow(nextDueDateStr)}
        </span>
      );
    } else if (nextDueDateStr === todayStr) {
      return (
        <span className="rounded-full bg-amber-100 px-2.5 py-1 text-xs font-semibold text-amber-800 border border-amber-200">
          本日期限: {formatYmdWithDow(nextDueDateStr)}
        </span>
      );
    } else {
      const todayDate = new Date(todayStr);
      const dueDate = new Date(nextDueDateStr);
      const diffDays = Math.ceil((dueDate.getTime() - todayDate.getTime()) / (1000 * 60 * 60 * 24));
      return (
        <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700 border border-emerald-200">
          次回予定: {formatYmdWithDow(nextDueDateStr)} (あと{diffDays}日)
        </span>
      );
    }
  };

  const filteredList = seriesList.filter((s) => {
    if (!filterText.trim()) return true;
    const q = filterText.toLowerCase();
    if (s.type_name.toLowerCase().includes(q)) return true;
    if (s.latest_note && s.latest_note.toLowerCase().includes(q)) return true;
    return s.properties.some(
      (p) =>
        p.display_name.toLowerCase().includes(q) ||
        p.value_display.toLowerCase().includes(q)
    );
  });

  return (
    <div className="h-full flex flex-col bg-slate-50 overflow-hidden">
      {/* Top Header Bar */}
      <div className="flex shrink-0 items-center justify-between border-b border-slate-200 bg-white px-6 py-4">
        <div>
          <h1 className="text-xl font-bold text-slate-900">定期記録</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            定期的な行為（散髪、清掃、オイル交換など）の実績管理・リマインダー
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setShowEventTypesModal(true)}
            className="rounded-lg border border-slate-300 bg-white px-3.5 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50 shadow-sm"
          >
            イベントタイプ管理
          </button>
          <button
            type="button"
            onClick={() => setShowCreateSeriesModal(true)}
            className="rounded-lg bg-slate-900 px-3.5 py-2 text-xs font-medium text-white hover:bg-slate-800 shadow-sm"
          >
            ＋ シリーズ作成
          </button>
        </div>
      </div>

      {/* Main Content Area */}
      <div className="flex-1 min-h-0 overflow-y-auto p-6 space-y-4">
        {/* Search / Filter Bar */}
        <div className="flex items-center justify-between gap-4">
          <input
            type="text"
            value={filterText}
            onChange={(e) => setFilterText(e.target.value)}
            placeholder="タイプ名やプロパティで検索..."
            className="w-full max-w-sm rounded-lg border border-slate-300 bg-white px-3.5 py-2 text-sm focus:border-slate-900 focus:outline-none"
          />
          <span className="text-xs text-slate-500 shrink-0">
            全 {filteredList.length} 件 / {seriesList.length} シリーズ
          </span>
        </div>

        {error && (
          <div className="rounded-lg bg-red-50 p-4 text-sm text-red-700 border border-red-200">
            {error}
          </div>
        )}

        {loading ? (
          <p className="py-12 text-center text-sm text-slate-500">定期記録シリーズを読み込み中...</p>
        ) : filteredList.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-300 bg-white p-12 text-center space-y-3">
            <p className="text-sm font-medium text-slate-600">
              {filterText ? "該当する定期記録シリーズが見つかりません。" : "定期記録シリーズがありません。"}
            </p>
            <p className="text-xs text-slate-400">
              「＋ シリーズ作成」ボタンから新しい定期記録シリーズを登録してください。
            </p>
          </div>
        ) : (
          /* Cards Grid */
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {filteredList.map((s) => (
              <div
                key={s.series_id}
                className="flex flex-col justify-between rounded-xl border border-slate-200 bg-white p-5 shadow-sm hover:border-slate-300 hover:shadow transition-all"
              >
                <div className="space-y-3">
                  {/* Title & Badge Header */}
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <h2 className="text-base font-bold text-slate-900">{s.type_name}</h2>
                      <span className="text-xs text-slate-500">
                        推奨間隔: {s.interval_value} {formatUnit(s.interval_unit)}ごと
                      </span>
                    </div>
                    <div>{getDueDateBadge(s.next_due_date)}</div>
                  </div>

                  {/* Properties */}
                  {s.properties.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {s.properties.map((p) => (
                        <span
                          key={p.property_id}
                          className="rounded bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700"
                        >
                          {p.display_name}: {p.value_display}
                        </span>
                      ))}
                    </div>
                  )}

                  {/* Metrics Summary */}
                  <div className="rounded-lg bg-slate-50 p-2.5 grid grid-cols-3 gap-2 text-center text-xs border border-slate-100">
                    <div>
                      <span className="block text-[10px] text-slate-400">最新実行日</span>
                      <span className="font-semibold text-slate-800">
                        {s.latest_executed_on ? formatYmdWithDow(s.latest_executed_on) : "-"}
                      </span>
                    </div>
                    <div>
                      <span className="block text-[10px] text-slate-400">経過日数</span>
                      <span className="font-semibold text-slate-800">
                        {s.elapsed_days !== null ? `${s.elapsed_days}日` : "-"}
                      </span>
                    </div>
                    <div>
                      <span className="block text-[10px] text-slate-400">通算回数</span>
                      <span className="font-bold text-slate-900">{s.total_count}回</span>
                    </div>
                  </div>

                  {/* Photo & Note Preview */}
                  <div className="flex items-center gap-3 pt-1">
                    {s.latest_photo_thumbnail ? (
                      <SeriesPhotoThumbnail
                        mediaId={s.latest_photo_thumbnail.media_id}
                        filename={s.latest_photo_thumbnail.filename}
                      />
                    ) : (
                      <div className="h-14 w-14 rounded-lg border border-slate-200 bg-slate-50 flex items-center justify-center text-[10px] text-slate-400 shrink-0">
                        写真なし
                      </div>
                    )}

                    <div className="min-w-0 flex-1">
                      <span className="block text-[10px] font-medium text-slate-400">最新メモ</span>
                      <p className="text-xs text-slate-700 truncate">
                        {s.latest_note || <span className="italic text-slate-400">メモなし</span>}
                      </p>
                    </div>
                  </div>
                </div>

                {/* Footer Action Button */}
                <div className="mt-4 pt-3 border-t border-slate-100 flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => setSelectedDetailSeriesId(s.series_id)}
                    className="w-full rounded-lg border border-slate-300 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 transition-colors"
                  >
                    詳細・履歴を見る
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Modals */}
      {showEventTypesModal && (
        <EventTypesModal
          onClose={() => setShowEventTypesModal(false)}
          onTypesUpdated={loadSeries}
        />
      )}

      {showCreateSeriesModal && (
        <CreateSeriesModal
          onClose={() => setShowCreateSeriesModal(false)}
          onCreated={loadSeries}
        />
      )}

      {selectedDetailSeriesId && (
        <SeriesDetailModal
          seriesId={selectedDetailSeriesId}
          onClose={() => setSelectedDetailSeriesId(null)}
          onUpdated={loadSeries}
        />
      )}
    </div>
  );
}
