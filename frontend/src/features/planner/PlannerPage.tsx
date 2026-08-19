import { useCallback, useEffect, useMemo, useState } from "react";
import {
  generatePlannerProposals,
  getPlannerTimeline,
  promotePlannerProposal,
  rejectPlannerProposal,
  updatePlannerProposal,
} from "../../api/client";
import type {
  PlannerInboxPending,
  PlannerProposal,
  PlannerProposalUpdatePayload,
  PlannerTimelineResponse,
} from "../../api/types";
import ProposalDetailPanel from "./ProposalDetailPanel";

interface Toast {
  id: number;
  text: string;
  kind: "info" | "error";
}

const WEEKDAYS = ["月", "火", "水", "木", "金", "土", "日"];

function toISODate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function startOfWeek(d: Date): Date {
  const date = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const day = date.getDay();
  date.setDate(date.getDate() + (day === 0 ? -6 : 1 - day));
  return date;
}

function addDays(d: Date, n: number): Date {
  const date = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  date.setDate(date.getDate() + n);
  return date;
}

function datePartOf(iso: string | null): string | null {
  if (!iso) return null;
  const match = iso.match(/^\d{4}-\d{2}-\d{2}/);
  return match ? match[0] : null;
}

function timePartOf(iso: string | null): string {
  if (!iso) return "";
  const match = iso.match(/T(\d{2}):(\d{2})/);
  return match ? `${match[1]}:${match[2]}` : "";
}

interface DayGroup {
  appleEvents: PlannerTimelineResponse["apple_events"];
  appleReminders: PlannerTimelineResponse["apple_reminders"];
  recurring: PlannerTimelineResponse["recurring_events"];
  inbox: PlannerInboxPending[];
  proposals: PlannerProposal[];
}

function groupByDay(timeline: PlannerTimelineResponse, dayKey: string): DayGroup {
  const appleEvents = timeline.apple_events.filter(
    (e) => !e.all_day && datePartOf(e.start_time) === dayKey,
  );
  const appleReminders = timeline.apple_reminders.filter(
    (r) => datePartOf(r.due_date) === dayKey,
  );
  const recurring = timeline.recurring_events.filter((r) => r.date === dayKey);
  const inbox = timeline.inbox_pending.filter(
    (i) =>
      datePartOf(i.kind === "calendar" ? i.start_time : i.due_date) === dayKey,
  );
  const proposals = timeline.ai_proposals.filter(
    (p) =>
      datePartOf(p.kind === "calendar" ? p.start_time : p.due_date) === dayKey,
  );
  return { appleEvents, appleReminders, recurring, inbox, proposals };
}

function errorMessage(e: unknown): string {
  if (e instanceof Error && e.message) return e.message;
  return "エラーが発生しました";
}

export default function PlannerPage() {
  const [weekStart, setWeekStart] = useState(() => startOfWeek(new Date()));
  const [timeline, setTimeline] = useState<PlannerTimelineResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [toasts, setToasts] = useState<Toast[]>([]);

  const notify = useCallback((text: string, kind: "info" | "error" = "info") => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { id, text, kind }]);
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 3500);
  }, []);

  const weekEnd = useMemo(() => addDays(weekStart, 6), [weekStart]);
  const days = useMemo(
    () => Array.from({ length: 7 }, (_, i) => addDays(weekStart, i)),
    [weekStart],
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getPlannerTimeline(toISODate(weekStart), toISODate(weekEnd))
      .then((data) => {
        if (!cancelled) setTimeline(data);
      })
      .catch((e) => {
        if (!cancelled) setError(errorMessage(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [weekStart, weekEnd, refreshKey]);

  const selectedProposal = useMemo(
    () => timeline?.ai_proposals.find((p) => p.proposal_id === selectedId) ?? null,
    [timeline, selectedId],
  );

  const allDayEvents = timeline?.apple_events.filter((e) => e.all_day) ?? [];
  const unscheduledProposals =
    timeline?.ai_proposals.filter(
      (p) => !datePartOf(p.kind === "calendar" ? p.start_time : p.due_date),
    ) ?? [];

  const handleSave = async (payload: PlannerProposalUpdatePayload) => {
    if (!selectedProposal) return;
    setBusy(true);
    try {
      await updatePlannerProposal(selectedProposal.proposal_id, payload);
      notify("保存しました");
      setRefreshKey((v) => v + 1);
    } catch (e) {
      notify(errorMessage(e), "error");
    } finally {
      setBusy(false);
    }
  };

  const handlePromote = async () => {
    if (!selectedProposal) return;
    setBusy(true);
    try {
      await promotePlannerProposal(selectedProposal.proposal_id);
      notify("Appleに登録しました");
      setSelectedId(null);
      setRefreshKey((v) => v + 1);
    } catch (e) {
      notify(errorMessage(e), "error");
    } finally {
      setBusy(false);
    }
  };

  const handleReject = async () => {
    if (!selectedProposal) return;
    setBusy(true);
    try {
      await rejectPlannerProposal(selectedProposal.proposal_id);
      notify("却下しました");
      setSelectedId(null);
      setRefreshKey((v) => v + 1);
    } catch (e) {
      notify(errorMessage(e), "error");
    } finally {
      setBusy(false);
    }
  };

  const handleGenerate = async () => {
    setBusy(true);
    try {
      const res = await generatePlannerProposals();
      notify(`AI提案を${res.generated}件生成しました`);
      setRefreshKey((v) => v + 1);
    } catch (e) {
      notify(errorMessage(e), "error");
    } finally {
      setBusy(false);
    }
  };

  const isToday = (d: Date) => toISODate(d) === toISODate(new Date());

  return (
    <div className="flex h-full flex-col bg-slate-50">
      <header className="flex flex-wrap items-center gap-2 border-b border-slate-200 bg-white p-3 sm:gap-3 sm:p-4">
        <h1 className="text-base font-semibold">プランナー</h1>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => setWeekStart(addDays(weekStart, -7))}
            aria-label="前の週"
            className="cursor-pointer rounded border border-slate-300 px-3 py-1 text-sm"
          >
            ‹
          </button>
          <button
            type="button"
            onClick={() => setWeekStart(startOfWeek(new Date()))}
            className="cursor-pointer rounded border border-slate-300 px-3 py-1 text-sm"
          >
            今週
          </button>
          <button
            type="button"
            onClick={() => setWeekStart(addDays(weekStart, 7))}
            aria-label="次の週"
            className="cursor-pointer rounded border border-slate-300 px-3 py-1 text-sm"
          >
            ›
          </button>
        </div>
        <span className="text-sm text-slate-600">
          {toISODate(weekStart).replace(/-/g, "/")} 〜{" "}
          {toISODate(weekEnd).replace(/-/g, "/")}
        </span>
        <div className="ml-auto flex gap-2">
          <button
            type="button"
            onClick={() => setRefreshKey((v) => v + 1)}
            className="cursor-pointer rounded border border-slate-300 px-3 py-1 text-sm"
          >
            再読み込み
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={handleGenerate}
            className="cursor-pointer rounded bg-blue-600 px-3 py-1 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
          >
            AI提案を生成
          </button>
        </div>
      </header>

      {timeline?.apple_error && (
        <div className="border-b border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-800">
          Apple連携でエラーが発生しました: {timeline.apple_error}
        </div>
      )}

      {error && (
        <div className="border-b border-rose-200 bg-rose-50 px-4 py-2 text-sm text-rose-700">
          {error}
        </div>
      )}

      <div className="flex min-h-0 flex-1 overflow-hidden">
        <div className="min-h-0 min-w-0 flex-1 overflow-auto">
          {loading && timeline === null ? (
            <div className="flex h-full items-center justify-center text-sm text-slate-500">
              読み込み中…
            </div>
          ) : timeline ? (
            <div className="min-w-[720px] p-3">
              {allDayEvents.length > 0 && (
                <div className="mb-2 rounded border border-slate-200 bg-white p-2">
                  <div className="mb-1 text-xs font-semibold text-slate-500">終日</div>
                  <div className="flex flex-wrap gap-1">
                    {allDayEvents.map((e, i) => (
                      <span
                        key={i}
                        className="rounded bg-blue-100 px-2 py-0.5 text-xs text-blue-800"
                      >
                        {e.title}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              <div className="grid grid-cols-7 gap-2">
                {days.map((day, idx) => {
                  const key = toISODate(day);
                  const group = groupByDay(timeline, key);
                  const today = isToday(day);
                  return (
                    <div
                      key={key}
                      className={`flex min-h-[420px] flex-col rounded border bg-white ${
                        today ? "border-blue-400" : "border-slate-200"
                      }`}
                    >
                      <div
                        className={`border-b border-slate-100 p-2 text-center text-xs font-semibold ${
                          today ? "bg-blue-50 text-blue-700" : "text-slate-600"
                        }`}
                      >
                        <div>{WEEKDAYS[idx]}</div>
                        <div>{day.getDate()}</div>
                      </div>
                      <div className="flex flex-1 flex-col gap-1 overflow-y-auto p-1.5">
                        {group.appleEvents.map((e, i) => (
                          <div
                            key={`ae-${i}`}
                            className="rounded bg-blue-100 px-2 py-1 text-xs text-blue-900"
                          >
                            <span className="font-medium">{timePartOf(e.start_time)}</span>{" "}
                            {e.title}
                          </div>
                        ))}
                        {group.appleReminders.map((r, i) => (
                          <div
                            key={`ar-${i}`}
                            className="rounded bg-blue-50 px-2 py-1 text-xs text-blue-800"
                          >
                            ⏰ {r.title}
                          </div>
                        ))}
                        {group.recurring.map((r, i) => (
                          <div
                            key={`rc-${i}`}
                            className="rounded bg-slate-100 px-2 py-1 text-xs text-slate-700"
                          >
                            🔁 {r.title}
                          </div>
                        ))}
                        {group.inbox.map((i) => (
                          <div
                            key={`in-${i.run_id}`}
                            className="rounded bg-amber-100 px-2 py-1 text-xs text-amber-900"
                          >
                            ⏳ {i.title}
                          </div>
                        ))}
                        {group.proposals.map((p) => (
                          <button
                            type="button"
                            key={p.proposal_id}
                            onClick={() => setSelectedId(p.proposal_id)}
                            data-testid="planner-proposal-chip"
                            className={`cursor-pointer rounded px-2 py-1 text-left text-xs text-purple-900 ${
                              selectedId === p.proposal_id
                                ? "bg-purple-700 text-white"
                                : "bg-purple-100 hover:bg-purple-200"
                            }`}
                          >
                            ✨ {p.title}
                          </button>
                        ))}
                        {group.appleEvents.length === 0 &&
                          group.appleReminders.length === 0 &&
                          group.recurring.length === 0 &&
                          group.inbox.length === 0 &&
                          group.proposals.length === 0 && (
                            <div className="text-center text-xs text-slate-300">-</div>
                          )}
                      </div>
                    </div>
                  );
                })}
              </div>

              {unscheduledProposals.length > 0 && (
                <div className="mt-2 rounded border border-slate-200 bg-white p-2">
                  <div className="mb-1 text-xs font-semibold text-slate-500">
                    日付未定のAI提案
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {unscheduledProposals.map((p) => (
                      <button
                        type="button"
                        key={p.proposal_id}
                        onClick={() => setSelectedId(p.proposal_id)}
                        className={`cursor-pointer rounded px-2 py-0.5 text-xs ${
                          selectedId === p.proposal_id
                            ? "bg-purple-700 text-white"
                            : "bg-purple-100 text-purple-900 hover:bg-purple-200"
                        }`}
                      >
                        ✨ {p.title}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : null}
        </div>

        {selectedProposal && (
          <div className="hidden w-80 shrink-0 lg:block">
            <ProposalDetailPanel
              proposal={selectedProposal}
              busy={busy}
              onSave={handleSave}
              onPromote={handlePromote}
              onReject={handleReject}
              onClose={() => setSelectedId(null)}
            />
          </div>
        )}
      </div>

      <div className="pointer-events-none fixed bottom-4 right-4 flex flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`pointer-events-auto rounded px-4 py-2 text-sm text-white shadow ${
              t.kind === "error" ? "bg-rose-600" : "bg-slate-900"
            }`}
          >
            {t.text}
          </div>
        ))}
      </div>
    </div>
  );
}