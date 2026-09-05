import { useEffect, useState, useCallback, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import {
  ApiError,
  listHitlRuns,
  getHitlRun,
  submitHitlAnswer,
  cancelHitlRun,
} from "../../api/client";
import type { HitlRun, HitlRunDetail, HitlQuestion } from "../../api/types";
import { WaitingRunQuestionCard, toQuestionItems } from "../../components/InConversationQuestionCard";
import { formatDateTime, formatYmdWithDow } from "../../utils/date";

interface MaintEvidence {
  path: string;
  quote?: string;
  observed_at?: string;
}

interface MaintMemory {
  memory_id: string;
  status: string;
  content: string;
  evidence?: MaintEvidence[];
}

interface MemoryMaintenanceContext {
  type: "memory_maintenance";
  proposal_id: string;
  action: "merge" | "correct" | "expire" | "no_action";
  main_id: string;
  absorbed_ids: string[];
  reason: string;
  integrated_content?: string | null;
  target_memories?: MaintMemory[];
}

interface ResearchSuggestionContext {
  type: "research_suggestion";
  theme?: string | null;
  direction?: string | null;
  why_now?: string | null;
}

interface CalendarEventContext {
  type: "calendar_event";
  event?: {
    title?: string | null;
    start_time?: string | null;
    end_time?: string | null;
    location?: string | null;
  } | null;
  content?: string | null;
}

interface ReminderContext {
  type: "reminder";
  reminder?: {
    title?: string | null;
    due_date?: string | null;
  } | null;
  content?: string | null;
}

function asMemoryMaintenanceContext(context: unknown): MemoryMaintenanceContext | null {
  if (context && typeof context === "object" && (context as any).type === "memory_maintenance") {
    return context as MemoryMaintenanceContext;
  }
  return null;
}

function asResearchSuggestionContext(context: unknown): ResearchSuggestionContext | null {
  if (context && typeof context === "object" && (context as any).type === "research_suggestion") {
    return context as ResearchSuggestionContext;
  }
  return null;
}

function asCalendarEventContext(context: unknown): CalendarEventContext | null {
  if (context && typeof context === "object" && (context as any).type === "calendar_event") {
    return context as CalendarEventContext;
  }
  return null;
}

function asReminderContext(context: unknown): ReminderContext | null {
  if (context && typeof context === "object" && (context as any).type === "reminder") {
    return context as ReminderContext;
  }
  return null;
}

function displayTypeLabel(dt: string | null | undefined): string {
  if (!dt) return "";
  if (dt === "in_conversation_question") return "ASK";
  return dt;
}

function getFormattedObserved(observedAt: string | undefined): string {
  if (!observedAt) return "";
  const cleanYmd = observedAt.substring(0, 10);
  const formatted = formatYmdWithDow(cleanYmd);
  if (formatted && formatted !== cleanYmd) {
    return formatted;
  }
  const dt = formatDateTime(observedAt);
  return dt || "";
}

function LabeledDateField({
  label,
  value,
  allowYmdOnly = false,
}: {
  label: string;
  value?: string | null;
  allowYmdOnly?: boolean;
}) {
  if (!value) return null;
  const formatted =
    allowYmdOnly && /^\d{4}-\d{2}-\d{2}$/.test(value)
      ? formatYmdWithDow(value)
      : formatDateTime(value);
  if (!formatted) return null;
  return (
    <div>
      <span className="font-bold text-slate-600">{label}: </span>
      <span className="text-slate-800">{formatted}</span>
    </div>
  );
}

export default function HitlPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const runIdParam = searchParams.get("run_id");
  const [runs, setRuns] = useState<HitlRun[]>([]);
  const [total, setTotal] = useState(0);
  const [selectedRun, setSelectedRun] = useState<HitlRunDetail | null>(null);
  const [mobileDetailOpen, setMobileDetailOpen] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string>("pending_user");
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState<string | null>(null); // question_id or runId if cancelling
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [answers, setAnswers] = useState<Record<string, any>>({});
  const [comments, setComments] = useState<Record<string, string>>({});

  const abortRef = useRef<AbortController | null>(null);

  const reloadRuns = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    setError(null);
    try {
      const res = await listHitlRuns({
        status: statusFilter === "all" ? undefined : statusFilter,
        limit: 100,
      });
      if (controller.signal.aborted) return;
      setRuns(res.items);
      setTotal(res.total);
    } catch (e) {
      if (controller.signal.aborted) return;
      setError(e instanceof ApiError ? e.message : "確認待ちタスクの取得に失敗しました");
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    void reloadRuns();
    return () => {
      abortRef.current?.abort();
    };
  }, [reloadRuns]);

  const loadDetail = useCallback(async (runId: string, preserveDrafts = false) => {
    setDetailLoading(true);
    setDetailError(null);
    setSuccessMessage(null);
    try {
      const detail = await getHitlRun(runId);
      setSelectedRun(detail);

      if (preserveDrafts) {
        // Keep in-progress drafts for questions that are still pending so a
        // single answer submission does not wipe other typed answers.
        const pendingKeys = new Set(
          detail.questions
            .filter((q) => q.status === "pending")
            .map((q) => q.question_key)
        );
        setAnswers((prev) => {
          const next: Record<string, any> = {};
          detail.questions.forEach((q) => {
            if (!pendingKeys.has(q.question_key)) return;
            next[q.question_key] =
              q.question_key in prev
                ? prev[q.question_key]
                : q.question_type === "boolean"
                ? true
                : "";
          });
          return next;
        });
        setComments((prev) => {
          const next: Record<string, string> = {};
          for (const key of pendingKeys) {
            const val = prev[key];
            if (val) next[key] = val;
          }
          return next;
        });
        return;
      }

      // Initialize answer states for pending questions
      const initialAnswers: Record<string, any> = {};
      detail.questions.forEach((q) => {
        if (q.status === "pending") {
          initialAnswers[q.question_key] = q.question_type === "boolean" ? true : "";
        }
      });
      setAnswers(initialAnswers);
      setComments({});
    } catch (e) {
      setDetailError(e instanceof ApiError ? e.message : "詳細情報の取得に失敗しました");
      setSelectedRun(null);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  // When arriving via a deep link (e.g. ?run_id=... from the research detail)
  // or selecting a row, load the detail for the flagged run.
  const loadDetailForParam = useCallback(() => {
    if (runIdParam) {
      setMobileDetailOpen(true);
      void loadDetail(runIdParam);
    }
  }, [runIdParam, loadDetail]);

  useEffect(() => {
    loadDetailForParam();
  }, [loadDetailForParam]);

  const handleBackToList = () => {
    setMobileDetailOpen(false);
    setSelectedRun(null);
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete("run_id");
      return next;
    }, { replace: true });
  };

  const handleSelectRun = (run: HitlRun) => {
    if (run.run_id === selectedRun?.run_id) {
      void loadDetail(run.run_id);
      return;
    }
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.set("run_id", run.run_id);
      return next;
    }, { replace: true });
  };

  const handleSubmitAnswer = async (q: HitlQuestion) => {
    if (!selectedRun) return;
    const ansValue = answers[q.question_key];
    const commentVal = comments[q.question_key] || null;

    // Simple validation
    if (q.is_required && (ansValue === undefined || ansValue === "")) {
      setDetailError(`${q.display_text} の回答は必須です。`);
      return;
    }

    // Custom validation for memory maintenance feedback
    const maintCtx = asMemoryMaintenanceContext(q.context);
    if (maintCtx && ansValue === "feedback" && (!commentVal || !commentVal.trim())) {
      setDetailError("フィードバックして再提案を選択した場合は、コメントを入力してください。");
      return;
    }

    setSubmitting(q.question_id);
    setDetailError(null);
    setSuccessMessage(null);
    try {
      await submitHitlAnswer(selectedRun.run_id, q.question_key, ansValue, commentVal);
      setSuccessMessage("回答を正常に送信しました。");
      // Reload run detail to reflect updated questions and run status,
      // preserving in-progress drafts for the other pending questions.
      await loadDetail(selectedRun.run_id, true);
      await reloadRuns();
    } catch (e) {
      setDetailError(e instanceof ApiError ? e.message : "回答の送信に失敗しました");
    } finally {
      setSubmitting(null);
    }
  };

  const handleCancelRun = async () => {
    if (!selectedRun) return;
    if (!window.confirm("この確認タスクの実行全体をキャンセルしますか？")) return;

    setSubmitting(selectedRun.run_id);
    setDetailError(null);
    setSuccessMessage(null);
    try {
      await cancelHitlRun(selectedRun.run_id);
      setSuccessMessage("タスク全体を正常にキャンセルしました。");
      await loadDetail(selectedRun.run_id);
      await reloadRuns();
    } catch (e) {
      setDetailError(e instanceof ApiError ? e.message : "キャンセルの実行に失敗しました");
    } finally {
      setSubmitting(null);
    }
  };

  const statusLabel = (s: string) => {
    switch (s) {
      case "pending_user": return "回答待ち";
      case "ready_to_resume": return "再開可能";
      case "running": return "実行中";
      case "completed": return "完了";
      case "failed": return "失敗";
      case "cancelled": return "キャンセル済み";
      default: return s;
    }
  };

  const statusBadgeColor = (s: string) => {
    switch (s) {
      case "pending_user": return "bg-yellow-100 text-yellow-800";
      case "ready_to_resume": return "bg-emerald-100 text-emerald-800";
      case "running": return "bg-blue-100 text-blue-800";
      case "completed": return "bg-slate-100 text-slate-800";
      case "failed": return "bg-rose-100 text-rose-800";
      case "cancelled": return "bg-rose-100 text-rose-800";
      default: return "bg-slate-100 text-slate-800";
    }
  };

  const isStructuredChoice = (choice: any): choice is { value: any; label: string; description?: string } => {
    return choice && typeof choice === 'object' && 'value' in choice && 'label' in choice;
  };

  const getAnswerLabel = (q: HitlQuestion): string => {
    if (q.answer === null || q.answer === undefined) {
      return "(回答なし/スキップ)";
    }

    let val: any = q.answer;
    if (q.answer && typeof q.answer === "object" && "value" in q.answer) {
      val = q.answer.value;
    }

    if (q.choices && Array.isArray(q.choices)) {
      for (const choice of q.choices) {
        if (isStructuredChoice(choice) && choice.value === val) {
          return choice.label;
        }
      }
    }
    return String(val);
  };

  const getAnswerComment = (q: HitlQuestion): string | null => {
    if (q.answer && typeof q.answer === "object" && "comment" in q.answer) {
      return q.answer.comment || null;
    }
    return null;
  };

  return (
    <div className="flex h-full flex-col overflow-hidden bg-slate-50 lg:flex-row">
      {/* Runs Side Panel */}
      <div className={`h-full w-full min-h-0 border-r border-slate-200 bg-white lg:w-80 shrink-0 ${mobileDetailOpen ? "hidden" : "flex flex-col"} lg:flex lg:flex-col`}>
        <div className="border-b border-slate-200 p-4">
          <div className="flex items-center justify-between">
            <h1 className="text-base font-semibold text-slate-800">確認待ちタスク</h1>
            <span className="text-xs text-slate-500">({total} 件)</span>
          </div>
          <div className="mt-3">
            <label htmlFor="status-filter" className="sr-only">
              ステータス
            </label>
            <select
              id="status-filter"
              aria-label="ステータスフィルター"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="w-full cursor-pointer rounded border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-700 outline-none"
            >
              <option value="all">すべて</option>
              <option value="pending_user">回答待ち</option>
              <option value="ready_to_resume">再開可能</option>
              <option value="running">実行中</option>
              <option value="completed">完了</option>
              <option value="failed">失敗</option>
              <option value="cancelled">キャンセル済み</option>
            </select>
          </div>
        </div>

        {loading && <p className="p-4 text-xs text-slate-500">読み込み中…</p>}
        {error && <p className="p-4 text-xs text-red-600">{error}</p>}

        <ul className="flex-1 overflow-y-auto divide-y divide-slate-100">
          {runs.map((r) => {
            const isSelected = selectedRun?.run_id === r.run_id;
            return (
              <li
                key={r.run_id}
                data-testid="hitl-run-row"
                data-selected={isSelected ? "true" : "false"}
                role="button"
                tabIndex={0}
                onClick={() => handleSelectRun(r)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    handleSelectRun(r);
                  }
                }}
                className={`cursor-pointer p-4 transition-colors ${
                  isSelected
                    ? "bg-slate-200 border-l-4 border-slate-800"
                    : "hover:bg-slate-50"
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5 truncate mr-2">
                    {r.display_type && (
                      <span className="rounded bg-indigo-50 text-indigo-700 border border-indigo-100 px-1.5 py-0.5 text-[10px] font-medium shrink-0">
                        {displayTypeLabel(r.display_type)}
                      </span>
                    )}
                    <span className="text-xs font-semibold text-slate-800 truncate" title={r.display_title || r.title || "確認待ちタスク"}>
                      {r.display_title || r.title || "確認待ちタスク"}
                    </span>
                  </div>
                  <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium shrink-0 ${statusBadgeColor(r.status)}`}>
                    {statusLabel(r.status)}
                  </span>
                </div>
                <div className="mt-1 text-[10px] text-slate-400">
                  {formatDateTime(r.created_at)}
                </div>
              </li>
            );
          })}
          {!loading && runs.length === 0 && (
            <li className="p-6 text-center text-xs text-slate-400">
              該当するタスクはありません。
            </li>
          )}
        </ul>
      </div>

      {/* Run Details Panel */}
      <div className={`min-w-0 min-h-0 flex-1 overflow-hidden bg-slate-50 ${mobileDetailOpen ? "flex flex-col" : "hidden"} lg:flex lg:flex-col`}>
        <div className="flex items-center gap-2 border-b border-slate-200 bg-white p-3 lg:hidden">
          <button
            type="button"
            onClick={handleBackToList}
            aria-label="一覧に戻る"
            className="cursor-pointer rounded px-2 py-1 text-sm text-slate-600 hover:bg-slate-100"
          >
            ← 一覧
          </button>
          <span className="truncate text-sm font-semibold text-slate-700">
            確認待ちタスク詳細
          </span>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-6">
        {detailLoading && (
          <p className="text-sm text-slate-500">詳細情報を読み込み中…</p>
        )}

        {detailError && (
          <div className="mb-4 rounded border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
            {detailError}
          </div>
        )}

        {successMessage && (
          <div className="mb-4 rounded border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-700">
            {successMessage}
          </div>
        )}

        {selectedRun ? (
          <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-200 pb-4">
              <div>
                <div className="flex items-center gap-2 flex-wrap">
                  {selectedRun.display_type && (
                    <span className="rounded bg-indigo-50 text-indigo-700 border border-indigo-100 px-2 py-0.5 text-[10px] font-bold">
                      {displayTypeLabel(selectedRun.display_type)}
                    </span>
                  )}
                  <h2 className="text-lg font-semibold text-slate-800">{selectedRun.display_title || selectedRun.title || "確認待ちタスク"}</h2>
                </div>
                {selectedRun.description && (
                  <p className="mt-2 text-xs text-slate-600 leading-relaxed max-w-2xl">{selectedRun.description}</p>
                )}

                <details className="mt-4 text-xs text-slate-500 bg-slate-50 border border-slate-100 rounded-lg p-3 max-w-sm">
                  <summary className="font-semibold cursor-pointer outline-none select-none text-slate-600 hover:text-slate-800">
                    技術情報
                  </summary>
                  <div className="mt-2 space-y-1.5">
                    <p>Run ID: <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono">{selectedRun.run_id}</code></p>
                    <p>Handler: <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono">{selectedRun.handler}</code></p>
                  </div>
                </details>
              </div>
              <div className="flex flex-col items-end gap-2 shrink-0">
                <span className={`rounded px-2.5 py-1 text-xs font-semibold ${statusBadgeColor(selectedRun.status)}`}>
                  {statusLabel(selectedRun.status)}
                </span>
                <span className="text-[10px] text-slate-400">
                  登録: {formatDateTime(selectedRun.created_at)}
                </span>
              </div>
            </div>

            {selectedRun.error_message && (
              <div className="mt-4 rounded border border-rose-100 bg-rose-50/50 p-4">
                <h3 className="text-xs font-semibold text-rose-800">エラーメッセージ</h3>
                <p className="mt-1 text-xs text-rose-700">{selectedRun.error_message}</p>
              </div>
            )}

            {/* Run-level Action (Cancellation) */}
            {["pending_user", "ready_to_resume"].includes(selectedRun.status) && (
              <div className="mt-6 flex justify-end">
                <button
                  type="button"
                  onClick={handleCancelRun}
                  disabled={!!submitting}
                  className="rounded bg-rose-600 px-4 py-2 text-xs font-semibold text-white hover:bg-rose-700 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
                >
                  {submitting === selectedRun.run_id ? "キャンセル中…" : "実行全体をキャンセル"}
                </button>
              </div>
            )}

            {/* Dedicated Question Card rendering for in-conversation questions */}
            {selectedRun.display_type === "in_conversation_question" && (() => {
              const answeredQuestions = selectedRun.questions.filter((q) => q.status === "answered");
              const pendingQuestions = selectedRun.questions.filter((q) => !q.status || q.status === "pending");

              return (
                <div className="mt-6 space-y-4">
                  {answeredQuestions.length > 0 && (
                    <div
                      data-testid="answered-in-conversation-card"
                      className="my-3 p-4 border border-emerald-300 bg-emerald-50/50 rounded shadow-sm"
                    >
                      <div className="flex items-center justify-between mb-3 border-b border-emerald-200 pb-2">
                        <span className="font-semibold text-emerald-900 text-sm flex items-center gap-2">
                          <span>✅ 回答済み要件確認</span>
                        </span>
                        <span className="text-xs text-emerald-700 font-mono">ID: {selectedRun.run_id}</span>
                      </div>

                      <div className="space-y-3">
                        {answeredQuestions.map((q, idx) => {
                          const label = getAnswerLabel(q);
                          const comment = getAnswerComment(q);
                          const qText = q.display_text || q.prompt || q.title || q.question_key;
                          let val: any = q.answer;
                          if (q.answer && typeof q.answer === "object" && "value" in q.answer) {
                            val = q.answer.value;
                          }

                          return (
                            <div key={q.question_id || q.question_key} className="bg-white p-3 rounded border border-emerald-200">
                              <p className="text-sm font-medium text-slate-800 mb-1.5">
                                {answeredQuestions.length > 1 ? `${idx + 1}. ` : ''}{qText}
                              </p>
                              <div className="text-sm text-slate-700 flex items-start gap-1.5 pl-1">
                                <span className="font-semibold text-emerald-700 shrink-0">選択:</span>
                                <span className="font-medium text-slate-900">{label}</span>
                              </div>
                              {val === "other" && comment && (
                                <div className="mt-2 pl-3 border-l-2 border-emerald-400 bg-emerald-50/30 py-1 pr-2 rounded-r">
                                  <p className="text-xs text-emerald-800 font-semibold mb-0.5">自由入力本文:</p>
                                  <p className="text-sm text-slate-800 whitespace-pre-wrap">{comment}</p>
                                </div>
                              )}
                              {val !== "other" && comment && (
                                <div className="mt-2 pl-3 border-l-2 border-emerald-400 bg-emerald-50/30 py-1 pr-2 rounded-r">
                                  <p className="text-xs text-emerald-800 font-semibold mb-0.5">コメント:</p>
                                  <p className="text-sm text-slate-800 whitespace-pre-wrap">{comment}</p>
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  {pendingQuestions.length > 0 && (
                    <WaitingRunQuestionCard
                      key={selectedRun.run_id}
                      hitlRunId={selectedRun.run_id}
                      questions={toQuestionItems(pendingQuestions)}
                      disabled={!["pending_user", "ready_to_resume"].includes(selectedRun.status)}
                      onSubmit={async (answers) => {
                        const entries = Object.entries(answers);
                        const results = await Promise.allSettled(
                          entries.map(([qKey, ans]) =>
                            submitHitlAnswer(selectedRun.run_id, qKey, ans.value, ans.comment)
                          )
                        );
                        await loadDetail(selectedRun.run_id, true);
                        await reloadRuns();

                        const rejections = results.filter((r): r is PromiseRejectedResult => r.status === "rejected");
                        if (rejections.length > 0) {
                          const firstErr = rejections[0].reason;
                          const msg = firstErr instanceof Error ? firstErr.message : "一部の回答の送信に失敗しました";
                          setDetailError(msg);
                          throw new Error(msg);
                        }
                      }}
                      onCancel={async () => {
                        await cancelHitlRun(selectedRun.run_id);
                        await loadDetail(selectedRun.run_id);
                        await reloadRuns();
                      }}
                    />
                  )}
                </div>
              );
            })()}

            {/* Standard Question Set List */}
            {selectedRun.display_type !== "in_conversation_question" && (
              <div className="mt-8 space-y-6">
              <h3 className="text-sm font-bold text-slate-700 border-l-4 border-slate-700 pl-2">
                質問
              </h3>

              <div className="space-y-4">
                {selectedRun.questions.map((q) => {
                  const isPending = q.status === "pending";
                  const answerVal = answers[q.question_key];

                  return (
                    <div
                      key={q.question_id}
                      className="rounded-lg border border-slate-100 bg-slate-50/50 p-5"
                    >
                      <div className="flex items-start justify-between gap-4">
                        <div className="flex-1">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-bold text-slate-500">{q.title || q.question_key}</span>
                            {q.is_required === 1 && (
                              <span className="rounded bg-red-100 px-1 py-0.5 text-[10px] font-medium text-red-800">
                                必須
                              </span>
                            )}
                          </div>
                          <p className="mt-2 text-sm font-semibold text-slate-800">{q.prompt || q.display_text}</p>

                          {/* Dedicated rendering for memory maintenance proposal details */}
                          {(() => {
                            const currentMaintCtx = asMemoryMaintenanceContext(q.context);
                            if (currentMaintCtx) {
                              return (
                                <div className="mt-3 space-y-3 bg-white border border-slate-200 rounded-lg p-4 text-xs text-slate-700">
                                  <div>
                                    <span className="font-bold text-slate-600">提案アクション: </span>
                                    <span className="rounded bg-indigo-50 border border-indigo-100 px-1.5 py-0.5 text-[10px] font-bold text-indigo-700 uppercase ml-1">
                                      {currentMaintCtx.action}
                                    </span>
                                  </div>
                                  <div>
                                    <span className="font-bold text-slate-600">根拠・理由: </span>
                                    <p className="mt-0.5 text-slate-800 leading-relaxed font-medium">{currentMaintCtx.reason}</p>
                                  </div>
                                  {["merge", "correct"].includes(currentMaintCtx.action) && currentMaintCtx.integrated_content && (
                                    <div>
                                      <span className="font-bold text-slate-600">変更・適用後の本文: </span>
                                      <div className="mt-1 bg-emerald-50 border border-emerald-100 rounded p-2 text-emerald-900 font-medium whitespace-pre-wrap">
                                        {currentMaintCtx.integrated_content}
                                      </div>
                                    </div>
                                  )}
                                  <div>
                                    <span className="font-bold text-slate-600">対象メモリ群:</span>
                                    <div className="mt-1.5 space-y-2">
                                      {(currentMaintCtx.target_memories || []).map((m) => {
                                        const isMain = m.memory_id === currentMaintCtx.main_id;
                                        const isAbsorbed = (currentMaintCtx.absorbed_ids || []).includes(m.memory_id);
                                        let labelClass = "bg-slate-100 text-slate-700 border-slate-200";
                                        let labelText = "対象";
                                        if (isMain) {
                                          if (currentMaintCtx.action === "expire") {
                                            labelClass = "bg-rose-50 text-rose-700 border-rose-200";
                                            labelText = "失効対象";
                                          } else {
                                            labelClass = "bg-emerald-50 text-emerald-700 border-emerald-200";
                                            labelText = "正本 (残す)";
                                          }
                                        } else if (isAbsorbed) {
                                          labelClass = "bg-rose-50 text-rose-700 border-rose-200";
                                          labelText = "吸収 (superseded)";
                                        }

                                        return (
                                          <div key={m.memory_id} className="rounded border border-slate-100 bg-slate-50 p-2.5">
                                            <div className="flex items-center gap-1.5 mb-1">
                                              <span className="font-mono font-bold text-slate-500 text-[10px]">{m.memory_id}</span>
                                              <span className={`rounded border px-1 py-0.2 text-[9px] font-bold ${labelClass}`}>
                                                {labelText}
                                              </span>
                                            </div>
                                            <p className="font-medium text-slate-800">{m.content}</p>
                                            {m.evidence && m.evidence.length > 0 && (
                                              <div className="mt-1.5 pt-1.5 border-t border-slate-200/50">
                                                <span className="text-[10px] text-slate-400 font-bold block mb-0.5">エビデンス（証拠）:</span>
                                                <ul className="space-y-1 list-disc pl-3 text-[10px] text-slate-500">
                                                  {m.evidence.map((ev, evIdx) => {
                                                    const formattedDate = getFormattedObserved(ev.observed_at);
                                                    return (
                                                      <li key={evIdx}>
                                                        {formattedDate && <span className="font-semibold text-slate-600 mr-1">[{formattedDate}]</span>}
                                                        {ev.quote && <span>&ldquo;{ev.quote}&rdquo;</span>}
                                                        <span className="text-[9px] text-slate-400 block mt-0.5">({ev.path})</span>
                                                      </li>
                                                    );
                                                  })}
                                                </ul>
                                              </div>
                                            )}
                                          </div>
                                        );
                                      })}
                                    </div>
                                  </div>
                                </div>
                              );
                            }

                            const currentResearchCtx = asResearchSuggestionContext(q.context);
                            if (currentResearchCtx) {
                              return (
                                <div
                                  data-testid="research-suggestion-context"
                                  className="mt-3 space-y-3 rounded-lg border border-slate-200 bg-white p-4 text-xs text-slate-700"
                                >
                                  <h4 className="font-bold text-slate-700">提案内容</h4>
                                  {currentResearchCtx.theme && (
                                    <div>
                                      <span className="font-bold text-slate-600">テーマ: </span>
                                      <span className="text-slate-800">{currentResearchCtx.theme}</span>
                                    </div>
                                  )}
                                  {currentResearchCtx.direction && (
                                    <div>
                                      <span className="font-bold text-slate-600">調査の方向: </span>
                                      <span className="text-slate-800">{currentResearchCtx.direction}</span>
                                    </div>
                                  )}
                                  {currentResearchCtx.why_now && (
                                    <div>
                                      <span className="font-bold text-slate-600">今調べる理由: </span>
                                      <span className="text-slate-800 whitespace-pre-wrap">{currentResearchCtx.why_now}</span>
                                    </div>
                                  )}
                                </div>
                              );
                            }

                            const currentCalendarCtx = asCalendarEventContext(q.context);
                            if (currentCalendarCtx) {
                              return (
                                <div
                                  data-testid="calendar-event-context"
                                  className="mt-3 space-y-3 rounded-lg border border-slate-200 bg-white p-4 text-xs text-slate-700"
                                >
                                  <h4 className="font-bold text-slate-700">カレンダー登録内容</h4>
                                  {currentCalendarCtx.event?.title && (
                                    <div>
                                      <span className="font-bold text-slate-600">タイトル: </span>
                                      <span className="text-slate-800">{currentCalendarCtx.event.title}</span>
                                    </div>
                                  )}
                                  <LabeledDateField label="開始" value={currentCalendarCtx.event?.start_time} />
                                  <LabeledDateField label="終了" value={currentCalendarCtx.event?.end_time} />
                                  {currentCalendarCtx.event?.location && (
                                    <div>
                                      <span className="font-bold text-slate-600">場所: </span>
                                      <span className="text-slate-800">{currentCalendarCtx.event.location}</span>
                                    </div>
                                  )}
                                  {currentCalendarCtx.content && (
                                    <div>
                                      <span className="font-bold text-slate-600">元の内容: </span>
                                      <p className="mt-0.5 text-slate-800 leading-relaxed font-medium whitespace-pre-wrap">{currentCalendarCtx.content}</p>
                                    </div>
                                  )}
                                </div>
                              );
                            }

                            const currentReminderCtx = asReminderContext(q.context);
                            if (currentReminderCtx) {
                              return (
                                <div
                                  data-testid="reminder-context"
                                  className="mt-3 space-y-3 rounded-lg border border-slate-200 bg-white p-4 text-xs text-slate-700"
                                >
                                  <h4 className="font-bold text-slate-700">リマインダー登録内容</h4>
                                  {currentReminderCtx.reminder?.title && (
                                    <div>
                                      <span className="font-bold text-slate-600">タイトル: </span>
                                      <span className="text-slate-800">{currentReminderCtx.reminder.title}</span>
                                    </div>
                                  )}
                                  <LabeledDateField
                                    label="期限"
                                    value={currentReminderCtx.reminder?.due_date}
                                    allowYmdOnly
                                  />
                                  {currentReminderCtx.content && (
                                    <div>
                                      <span className="font-bold text-slate-600">元の内容: </span>
                                      <p className="mt-0.5 text-slate-800 leading-relaxed font-medium whitespace-pre-wrap">{currentReminderCtx.content}</p>
                                    </div>
                                  )}
                                </div>
                              );
                            } else if (q.context != null) {
                              return <p className="mt-1 text-xs text-slate-400">{JSON.stringify(q.context)}</p>;
                            }
                            return null;
                          })()}
                        </div>
                        <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                          q.status === "pending"
                            ? "bg-yellow-100 text-yellow-800"
                            : q.status === "answered"
                            ? "bg-emerald-100 text-emerald-800"
                            : "bg-slate-200 text-slate-600"
                        }`}>
                          {q.status === "pending"
                            ? "回答待ち"
                            : q.status === "answered"
                            ? "回答済み"
                            : q.status === "skipped"
                            ? "スキップ"
                            : "キャンセル"}
                        </span>
                      </div>

                      {/* Answering fields */}
                      <div className="mt-4 border-t border-slate-100 pt-4">
                        {isPending ? (
                          <div className="space-y-4">
                            {/* Boolean type Rendering */}
                            {q.question_type === "boolean" && (
                              <div className="flex items-center gap-4">
                                <label className="flex items-center gap-2 cursor-pointer text-sm text-slate-700">
                                  <input
                                    type="radio"
                                    name={q.question_id}
                                    checked={answerVal === true}
                                    onChange={() => setAnswers({ ...answers, [q.question_key]: true })}
                                    className="cursor-pointer"
                                  />
                                  <span>はい (True)</span>
                                </label>
                                <label className="flex items-center gap-2 cursor-pointer text-sm text-slate-700">
                                  <input
                                    type="radio"
                                    name={q.question_id}
                                    checked={answerVal === false}
                                    onChange={() => setAnswers({ ...answers, [q.question_key]: false })}
                                    className="cursor-pointer"
                                  />
                                  <span>いいえ (False)</span>
                                </label>
                              </div>
                            )}

                            {/* Select type Rendering */}
                            {q.question_type === "select" && q.choices && (
                              <div>
                                {q.choices.some((c: any) => isStructuredChoice(c)) ? (
                                  <div className="space-y-2 max-w-md">
                                    {q.choices.map((choice: any) => {
                                      const val = isStructuredChoice(choice) ? choice.value : choice;
                                      const label = isStructuredChoice(choice) ? choice.label : String(choice);
                                      const desc = isStructuredChoice(choice) ? choice.description : undefined;
                                      const isSelected = answerVal === val;
                                      return (
                                        <button
                                          key={String(val)}
                                          type="button"
                                          aria-pressed={isSelected}
                                          onClick={() => setAnswers({ ...answers, [q.question_key]: val })}
                                          className={`w-full text-left rounded-lg p-3 border transition-all cursor-pointer ${
                                            isSelected
                                              ? "border-blue-600 bg-blue-50 text-blue-900 ring-1 ring-blue-600"
                                              : "border-slate-200 bg-white hover:bg-slate-50 text-slate-700"
                                          }`}
                                        >
                                          <span className="text-xs font-bold block">{label}</span>
                                          {desc && <span className="mt-1 block text-[10px] text-slate-500 leading-normal">{desc}</span>}
                                        </button>
                                      );
                                    })}
                                  </div>
                                ) : (
                                  <div className="flex flex-wrap gap-2">
                                    {q.choices.map((choice: any) => {
                                      const choiceStr = String(choice);
                                      const isSelected = answerVal === choice;
                                      return (
                                        <button
                                          key={choiceStr}
                                          type="button"
                                          aria-pressed={isSelected}
                                          onClick={() => setAnswers({ ...answers, [q.question_key]: choice })}
                                          className={`rounded px-3 py-1.5 text-xs font-medium cursor-pointer transition-colors ${
                                            isSelected
                                              ? "bg-blue-600 text-white"
                                              : "bg-slate-200 text-slate-700 hover:bg-slate-300"
                                          }`}
                                        >
                                          {choiceStr}
                                        </button>
                                      );
                                    })}
                                  </div>
                                )}
                              </div>
                            )}

                            {/* Text / Comment type Rendering */}
                            {q.question_type === "text" && (
                              <textarea
                                value={answerVal || ""}
                                onChange={(e) => setAnswers({ ...answers, [q.question_key]: e.target.value })}
                                placeholder="回答を入力してください…"
                                className="w-full rounded border border-slate-200 bg-white p-3 text-sm text-slate-800 outline-none focus:border-slate-400"
                                rows={3}
                              />
                            )}

                            {/* Comment input */}
                            <div>
                              <textarea
                                value={comments[q.question_key] || ""}
                                onChange={(e) => setComments({ ...comments, [q.question_key]: e.target.value })}
                                placeholder="コメント（任意）"
                                className="w-full rounded border border-slate-200 bg-white p-2 text-xs text-slate-600 outline-none focus:border-slate-400"
                                rows={2}
                              />
                            </div>

                            <div className="flex justify-end mt-2">
                              <button
                                type="button"
                                onClick={() => handleSubmitAnswer(q)}
                                disabled={submitting === q.question_id}
                                className="rounded bg-blue-600 px-4 py-2 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
                              >
                                {submitting === q.question_id ? "送信中…" : "回答を送信"}
                              </button>
                            </div>
                          </div>
                        ) : (
                          // Answered or Cancelled state display
                          <div className="text-sm">
                            <span className="text-xs text-slate-500 font-semibold block">
                              回答内容:
                            </span>
                            <div className="mt-1 rounded border border-slate-100 bg-white p-3 font-medium text-slate-800 whitespace-pre-wrap">
                              {getAnswerLabel(q)}
                            </div>
                            {getAnswerComment(q) && (
                              <div className="mt-2">
                                <span className="text-xs text-slate-500 font-semibold block">
                                  コメント:
                                </span>
                                <div className="mt-1 rounded border border-slate-100 bg-slate-50 p-2 text-xs text-slate-600 whitespace-pre-wrap">
                                  {getAnswerComment(q)}
                                </div>
                              </div>
                            )}
                            {q.answered_at && (
                              <span className="mt-1 block text-[10px] text-slate-400 text-right">
                                回答日時: {formatDateTime(q.answered_at)}
                              </span>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
            )}
          </div>
        ) : (
          !detailLoading && (
            <div className="flex h-64 flex-col items-center justify-center rounded-xl border border-dashed border-slate-300 bg-white text-slate-400 shadow-sm">
              <span className="text-sm">一覧から確認待ちタスクを選択してください。</span>
            </div>
          )
        )}
        </div>
      </div>
    </div>
  );
}
