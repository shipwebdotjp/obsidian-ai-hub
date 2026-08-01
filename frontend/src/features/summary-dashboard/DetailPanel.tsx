import type {
  SummaryDetail,
  DashboardDayDetailsResponse,
  SummaryUpdatePayload,
  EditOptionsResponse,
  Person,
} from "../../api/types";
import { formatYmdWithDow } from "../../utils/date";
import { EditSummaryForm } from "./EditSummaryForm";
import { formatPeriodKey, groupSummaryItemsByKind } from "./utils";

export function DetailPanel({
  selectedSummary,
  selectedDay,
  detailLoading,
  detailError,
  mobileDetailOpen,
  onCloseMobile,
  isEditing,
  editForm,
  setEditForm,
  editOptions,
  allPeople,
  editSaving,
  editError,
  onSave,
  onCancel,
  onStartEdit,
  onRequestDelete,
  onShowDayDetail,
}: {
  selectedSummary: SummaryDetail | null;
  selectedDay: DashboardDayDetailsResponse | null;
  detailLoading: boolean;
  detailError: string | null;
  mobileDetailOpen: boolean;
  onCloseMobile: () => void;
  isEditing: boolean;
  editForm: SummaryUpdatePayload;
  setEditForm: (f: SummaryUpdatePayload) => void;
  editOptions: EditOptionsResponse | null;
  allPeople: Person[];
  editSaving: boolean;
  editError: string | null;
  onSave: () => void;
  onCancel: () => void;
  onStartEdit: () => void;
  onRequestDelete: () => void;
  onShowDayDetail: (targetDate: string) => void;
}) {
  return (
    <div
      className={`h-full w-full overflow-y-auto border-l border-slate-100 bg-white p-4 sm:p-6 lg:w-1/2 ${
        mobileDetailOpen ? "flex flex-col" : "hidden"
      } lg:flex lg:flex-col`}
    >
      <div className="flex items-center gap-2 border-b border-slate-200 pb-3 lg:hidden">
        <button
          type="button"
          onClick={onCloseMobile}
          aria-label="一覧に戻る"
          className="rounded px-2 py-1 text-sm text-slate-600 hover:bg-slate-100"
        >
          ← 一覧
        </button>
        <span className="text-sm font-semibold text-slate-700">詳細</span>
      </div>
      {detailLoading && <p className="text-sm text-slate-500">詳細をロード中…</p>}
      {detailError && <p className="text-sm text-red-600">{detailError}</p>}

      {/* 1. Summary Detail view */}
      {selectedSummary && (
        <div className="space-y-5">
          <div className="flex items-center justify-between">
            <span className="rounded bg-indigo-100 px-2 py-0.5 text-[10px] font-bold text-indigo-700 uppercase tracking-wider">
              {selectedSummary.period_type === "day"
                ? "日次サマリ"
                : selectedSummary.period_type === "week"
                ? "週次サマリ"
                : "月次サマリ"}
            </span>
            <span className="text-xs text-slate-500 font-medium">{formatPeriodKey(selectedSummary.period_key, selectedSummary.period_type)}</span>
          </div>

          {/* Edit/Delete buttons */}
          {!isEditing && (
            <div className="flex gap-2">
              <button
                onClick={onStartEdit}
                className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-50 cursor-pointer"
              >
                編集
              </button>
              <button
                onClick={onRequestDelete}
                className="rounded-md border border-red-200 bg-white px-3 py-1.5 text-xs font-semibold text-red-600 hover:bg-red-50 cursor-pointer"
              >
                削除
              </button>
            </div>
          )}

          {/* Edit Error */}
          {editError && (
            <p className="rounded bg-red-50 px-3 py-2 text-xs text-red-600">{editError}</p>
          )}

          {/* View Mode */}
          {!isEditing && (
            <>
              <h2 className="text-lg font-bold text-slate-900">{selectedSummary.summary}</h2>

              {/* Metadata */}
              <div className="flex flex-wrap gap-2 text-xs">
                {selectedSummary.mood && (
                  <span className="rounded bg-blue-50 px-2.5 py-1 text-blue-700 font-medium">
                    気分: {selectedSummary.mood}
                  </span>
                )}
                {selectedSummary.sleep_hours !== null && (
                  <span className="rounded bg-indigo-50 px-2.5 py-1 text-indigo-700 font-medium">
                    睡眠: {selectedSummary.sleep_hours}h
                  </span>
                )}
              </div>

              {selectedSummary.topics.length > 0 && (
                <div>
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">トピック</h3>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {selectedSummary.topics.map((t) => (
                      <span key={t} className="rounded bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700 font-medium">
                        {t}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {selectedSummary.project_candidates && selectedSummary.project_candidates.length > 0 && (
                <div>
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">プロジェクト候補 (未解決)</h3>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {selectedSummary.project_candidates.map((c) => (
                      <span key={c.candidate_id} className="rounded bg-red-50 border border-red-100 px-2 py-0.5 text-xs text-red-700 font-medium opacity-80">
                        {c.display_name} (候補)
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {selectedSummary.project_notes && selectedSummary.project_notes.length > 0 && (
                <div>
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">プロジェクト</h3>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {selectedSummary.project_notes.map((pn) => (
                      <span key={pn.project_id} className="rounded bg-amber-50 px-2 py-0.5 text-xs text-amber-700 font-medium">
                        {pn.note ? `${pn.display_name}: ${pn.note}` : pn.display_name}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {selectedSummary.keywords.length > 0 && (
                <div>
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">キーワード</h3>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {selectedSummary.keywords.map((k) => (
                      <span key={k} className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-600 font-medium">
                        {k}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {selectedSummary.people.length > 0 && (
                <div>
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">人物</h3>
                  <div className="mt-1 space-y-1">
                    {selectedSummary.people.filter((p) => p.resolution_status === "resolved").map((p) => (
                      <div key={p.person_id ?? p.name} className="flex items-start gap-2">
                        <span className="text-xs font-medium text-slate-700 min-w-[80px]">{p.name}</span>
                        {p.note && <span className="text-xs text-slate-500">{p.note}</span>}
                      </div>
                    ))}
                    {selectedSummary.people.filter((p) => p.resolution_status === "unresolved").map((p) => (
                      <div key={p.candidate_id ?? p.name} className="flex items-start gap-2 opacity-60">
                        <span className="inline-flex items-center justify-center w-4 h-4 rounded-full bg-amber-200 text-amber-800 text-[9px] font-bold flex-shrink-0 mt-0.5" title="未解決候補" aria-label="未解決候補">?</span>
                        <span className="text-xs text-slate-500 min-w-[80px]">{p.name}</span>
                        {p.note && <span className="text-xs text-slate-400">{p.note}</span>}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Nested item blocks */}
              <div className="mt-6 space-y-4">
                {groupSummaryItemsByKind(selectedSummary.items).map(({ kind, items }) => (
                  <section key={kind} className="border-t border-slate-100 pt-3">
                    <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400">{kind}</h4>
                    <ul className="mt-1 list-disc space-y-2 pl-5">
                      {items.map((item) => (
                        <li
                          key={item.summary_item_id}
                          className="text-xs text-slate-700 whitespace-pre-wrap leading-relaxed"
                        >
                          {item.body}
                        </li>
                      ))}
                    </ul>
                  </section>
                ))}
              </div>

              {/* If daily summary, we can also load its detailed activity logs directly below it */}
              {selectedSummary.period_type === "day" && (
                <button
                  onClick={() => onShowDayDetail(selectedSummary.period_key)}
                  className="mt-6 w-full text-center rounded-lg border border-blue-200 bg-blue-50 py-2.5 text-xs font-bold text-blue-600 hover:bg-blue-100 transition-all cursor-pointer"
                >
                  この日の詳細アクティビティログを表示する
                </button>
              )}
            </>
          )}

          {/* Edit Mode */}
          {isEditing && (
            <EditSummaryForm
              summary={selectedSummary}
              form={editForm}
              setForm={setEditForm}
              editOptions={editOptions}
              allPeople={allPeople}
              saving={editSaving}
              onSave={onSave}
              onCancel={onCancel}
            />
          )}
        </div>
      )}

      {/* 2. Log-only Day Details view */}
      {selectedDay && (
        <div className="space-y-6">
          <div className="flex items-center justify-between border-b border-slate-100 pb-3">
            <span className="rounded bg-slate-100 px-2 py-0.5 text-[10px] font-bold text-slate-600 uppercase tracking-wider">
              日別詳細ログ
            </span>
            <span className="text-xs text-slate-500 font-bold">{formatYmdWithDow(selectedDay.date)}</span>
          </div>

          {/* Times Tracker Box */}
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 space-y-3">
            <h3 className="text-xs font-bold text-slate-700">活動時間の推定値</h3>
            <div className="flex items-center gap-6 text-sm">
              <div>
                <span className="text-xs text-slate-400">推定活動カバー時間</span>
                <div className="text-base font-bold text-emerald-600">
                  {Math.floor(selectedDay.active_minutes / 60)}h {Math.round(selectedDay.active_minutes % 60)}m
                </div>
              </div>
              <div>
                <span className="text-xs text-slate-400">非活動時間</span>
                <div className="text-base font-bold text-slate-600">
                  {Math.floor(selectedDay.inactive_minutes / 60)}h {Math.round(selectedDay.inactive_minutes % 60)}m
                </div>
              </div>
            </div>
            <div className="h-2 w-full rounded-full bg-slate-200 overflow-hidden flex">
              <div
                style={{
                  width: `${(selectedDay.active_minutes / (selectedDay.active_minutes + selectedDay.inactive_minutes)) * 100}%`,
                }}
                className="bg-emerald-500 h-full"
              />
            </div>
          </div>

          {/* Detailed list */}
          <div className="space-y-4">
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">アクティビティタイムライン</h3>
            <div className="space-y-3">
              {selectedDay.logs.map((log) => (
                <div key={log.activity_id} className="rounded-xl border border-slate-100 p-4 hover:shadow-sm transition-all space-y-2">
                  <div className="flex items-center justify-between text-[10px] text-slate-400">
                    <span className="font-bold text-slate-500">{log.occurred_at.split("T")[1]?.slice(0, 5)}</span>
                    <span className="bg-slate-100 px-1.5 py-0.5 rounded text-slate-600 font-medium">{log.app_name}</span>
                  </div>
                  <h4 className="text-sm font-bold text-slate-800">{log.summary}</h4>
                  {log.window_title && (
                    <p className="text-xs text-slate-400 truncate" title={log.window_title}>
                      {log.window_title}
                    </p>
                  )}
                  <div className="flex flex-wrap gap-1">
                    {log.category && (
                      <span className="rounded bg-indigo-50 px-1.5 py-0.5 text-[10px] text-indigo-600 font-semibold">
                        {log.category}
                      </span>
                    )}
                    {log.project_name && (
                      <span className="rounded bg-sky-50 border border-sky-100 px-1.5 py-0.5 text-[10px] text-sky-700 font-semibold flex items-center gap-0.5 whitespace-nowrap">
                        📁 {log.project_name}
                      </span>
                    )}
                    {log.keywords.map((k) => (
                      <span key={k} className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-600">
                        {k}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {!selectedSummary && !selectedDay && !detailLoading && (
        <div className="flex h-full flex-col items-center justify-center text-slate-400 text-xs">
          <p>一覧から項目を選択すると、詳細がここに表示されます。</p>
        </div>
      )}
    </div>
  );
}
