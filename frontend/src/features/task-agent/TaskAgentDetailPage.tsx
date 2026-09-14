import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ApiError,
  approveTaskAgentTask,
  cancelHitlRun,
  cancelTaskAgentTask,
  getHitlRun,
  getTaskAgentTask,
  rejectTaskAgentTask,
  replanTaskAgentTask,
  submitHitlAnswer,
} from "../../api/client";
import type { HitlRunDetail, TaskAgentTaskDetail } from "../../api/types";
import {
  WaitingRunQuestionCard,
  toQuestionItems,
  waitForHitlSettled,
} from "../../components/InConversationQuestionCard";
import { ROUTES } from "../../constants/routes";
import { formatDateTime } from "../../utils/date";
import {
  TERMINAL_STATUSES,
  eventTypeLabel,
  taskStatusBadgeClass,
  taskStatusLabel,
} from "./taskAgentLabels";

const TERMINAL_SET = new Set<string>(TERMINAL_STATUSES);
const APPROVAL_STATUSES = ["waiting_approval", "waiting_reapproval"];
const ANSWERABLE_HITL_STATUSES = ["pending_user", "ready_to_resume"];

interface DirectionalPlanJson {
  purpose?: unknown;
  strategy?: unknown;
  capabilities?: Array<{ capability_key?: unknown; intent?: unknown }>;
  allowed_agent_ids?: unknown;
  allowed_project_ids?: unknown;
  constraints?: unknown;
  completion_criteria?: unknown;
  max_actions?: unknown;
}

function isDirectionalPlan(plan: unknown): boolean {
  if (plan == null || typeof plan !== "object") return false;
  const p = plan as Record<string, unknown>;
  return Array.isArray(p["capabilities"]) && typeof p["purpose"] === "string";
}

function DirectionalPlanView({ plan }: { plan: DirectionalPlanJson }) {
  return (
    <div className="mt-1 space-y-1 text-xs text-slate-700">
      <p className="rounded bg-blue-50 px-2 py-1 text-[11px] text-blue-800">
        承認対象は方向性とCapability範囲です（詳細引数は実行時に確定し、履歴に記録されます）。
      </p>
      {typeof plan.purpose === "string" && (
        <p>
          <span className="font-medium">目的: </span>
          {plan.purpose}
        </p>
      )}
      {typeof plan.strategy === "string" && plan.strategy && (
        <p>
          <span className="font-medium">方針: </span>
          {plan.strategy}
        </p>
      )}
      {Array.isArray(plan.capabilities) && (
        <ul className="space-y-0.5">
          {plan.capabilities.map((c, i) => (
            <li key={i} className="flex flex-wrap items-center gap-1">
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-700">
                {String(c.capability_key ?? "")}
              </span>
              {typeof c.intent === "string" && c.intent && (
                <span className="text-slate-600">{c.intent}</span>
              )}
            </li>
          ))}
        </ul>
      )}
      {typeof plan.constraints === "string" && plan.constraints && (
        <p>
          <span className="font-medium">制約: </span>
          {plan.constraints}
        </p>
      )}
      {Array.isArray(plan.allowed_agent_ids) && plan.allowed_agent_ids.length > 0 && (
        <p className="text-slate-500">
          委譲可能なAgent: {plan.allowed_agent_ids.map(String).join(", ")}
        </p>
      )}
      {Array.isArray(plan.allowed_project_ids) &&
        plan.allowed_project_ids.length > 0 && (
          <p className="text-slate-500">
            実行可能なProject: {plan.allowed_project_ids.map(String).join(", ")}
          </p>
        )}
      {typeof plan.completion_criteria === "string" && (
        <p>
          <span className="font-medium">完了条件: </span>
          {plan.completion_criteria}
        </p>
      )}
      {plan.max_actions != null && (
        <p className="text-slate-500">最大Action数: {String(plan.max_actions)}</p>
      )}
    </div>
  );
}

function LegacyPlanView({ plan }: { plan: unknown }) {
  const p = (plan ?? {}) as Record<string, unknown>;
  const steps = Array.isArray(p["steps"]) ? p["steps"] : [];
  return (
    <div className="mt-1 space-y-1 text-xs text-slate-700">
      <p className="rounded bg-slate-100 px-2 py-1 text-[11px] text-slate-600">
        旧形式の静的Plan（保存済み入力で実行されます）。
      </p>
      {typeof p["purpose"] === "string" && (
        <p>
          <span className="font-medium">目的: </span>
          {p["purpose"]}
        </p>
      )}
      <p className="text-slate-500">Step数: {steps.length}</p>
    </div>
  );
}

export default function TaskAgentDetailPage() {
  const { taskId } = useParams<{ taskId: string }>();
  const [detail, setDetail] = useState<TaskAgentTaskDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [hitlRun, setHitlRun] = useState<HitlRunDetail | null>(null);
  const [hitlBusy, setHitlBusy] = useState(false);

  const loadDetail = useCallback(
    async (showLoading = true) => {
      if (!taskId) {
        setError("Taskが見つかりません");
        setLoading(false);
        return;
      }
      if (showLoading) setLoading(true);
      setError(null);
      try {
        const res = await getTaskAgentTask(taskId);
        setDetail(res);
        const asked = res.events
          .filter((e) => e.event_type === "hitl_question_asked")
          .sort((a, b) => (a.seq ?? 0) - (b.seq ?? 0))
          .at(-1);
        const hitlRunId = asked?.payload?.hitl_run_id;
        if (typeof hitlRunId === "string" && hitlRunId) {
          try {
            setHitlRun(await getHitlRun(hitlRunId));
          } catch {
            setHitlRun(null);
          }
        } else {
          setHitlRun(null);
        }
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "読み込みに失敗しました");
      } finally {
        if (showLoading) setLoading(false);
      }
    },
    [taskId],
  );

  useEffect(() => {
    void loadDetail();
  }, [loadDetail]);

  useEffect(() => {
    const status = detail?.task.status;
    if (!status || TERMINAL_SET.has(status)) return;
    const id = setInterval(() => void loadDetail(false), 3000);
    return () => clearInterval(id);
  }, [loadDetail, detail?.task.status]);

  const runAction = useCallback(
    async (fn: (id: string) => Promise<unknown>) => {
      if (!taskId) return;
      setBusy(true);
      setActionError(null);
      try {
        await fn(taskId);
        await loadDetail(false);
      } catch (e) {
        setActionError(e instanceof ApiError ? e.message : "操作に失敗しました");
      } finally {
        setBusy(false);
      }
    },
    [taskId, loadDetail],
  );

  if (loading) return <p className="p-4 text-sm text-slate-500">読み込み中…</p>;
  if (error || !detail)
    return (
      <div className="bg-slate-50 p-4">
        <p className="rounded border border-rose-300 bg-rose-50 p-2 text-sm text-rose-700">
          {error ?? "Taskが見つかりません"}
        </p>
        <Link to={ROUTES.TASK_AGENT} className="mt-2 inline-block text-sm text-blue-600">
          ← 一覧
        </Link>
      </div>
    );

  const task = detail.task;
  const isTerminal = TERMINAL_SET.has(task.status);
  const needsApproval = APPROVAL_STATUSES.includes(task.status);
  const canReplan = task.status === "interrupted";
  const childRefs = detail.events.filter(
    (e) => e.event_type === "child_run_started",
  );
  const actionHistory = detail.events.filter(
    (e) => e.event_type === "capability_completed",
  );
  const pendingQuestions = hitlRun
    ? toQuestionItems(hitlRun.questions ?? [])
    : [];
  const showQuestionCard =
    hitlRun != null &&
    ANSWERABLE_HITL_STATUSES.includes(hitlRun.status) &&
    pendingQuestions.length > 0;
  const rejectDisabled = busy || !rejectReason.trim();

  return (
    <div className="flex h-full flex-col bg-slate-50">
      <header className="border-b border-slate-200 bg-white px-4 py-3">
        <Link to={ROUTES.TASK_AGENT} className="text-sm text-blue-600">
          ← 一覧
        </Link>
        <h1 className="mt-1 text-lg font-semibold">Task詳細</h1>
      </header>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
        {actionError && (
          <p className="rounded border border-rose-300 bg-rose-50 p-2 text-sm text-rose-700">
            {actionError}
          </p>
        )}

        <section className="rounded border border-slate-200 bg-white p-4">
          <div className="flex flex-wrap items-center gap-2">
            <span className={taskStatusBadgeClass(task.status)}>
              {taskStatusLabel(task.status)}
            </span>
            <span className="text-xs text-slate-400">
              作成 {formatDateTime(task.created_at)}
              {task.started_at && ` / 開始 ${formatDateTime(task.started_at)}`}
              {task.finished_at && ` / 終了 ${formatDateTime(task.finished_at)}`}
            </span>
          </div>
          <p className="mt-2 whitespace-pre-wrap text-sm">{task.prompt_text}</p>
          {task.result_summary && (
            <p className="mt-2 whitespace-pre-wrap text-sm text-slate-700">
              結果: {task.result_summary}
            </p>
          )}
          {task.error_summary && (
            <p className="mt-2 whitespace-pre-wrap text-sm text-rose-700">
              エラー: {task.error_summary}
            </p>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            {needsApproval && (
              <>
                <button
                  type="button"
                  data-testid="task-approve"
                  disabled={busy}
                  onClick={() => void runAction(approveTaskAgentTask)}
                  className="cursor-pointer rounded bg-emerald-600 px-3 py-1.5 text-xs text-white disabled:cursor-not-allowed disabled:opacity-50"
                >
                  承認
                </button>
                <button
                  type="button"
                  data-testid="task-reject"
                  disabled={rejectDisabled}
                  onClick={() =>
                    void runAction((id) => rejectTaskAgentTask(id, rejectReason.trim()))
                  }
                  className="cursor-pointer rounded bg-rose-600 px-3 py-1.5 text-xs text-white disabled:cursor-not-allowed disabled:opacity-50"
                >
                  差戻し
                </button>
              </>
            )}
            {!isTerminal && (
              <button
                type="button"
                data-testid="task-cancel"
                disabled={busy}
                onClick={() => void runAction(cancelTaskAgentTask)}
                className="cursor-pointer rounded bg-slate-900 px-3 py-1.5 text-xs text-white disabled:cursor-not-allowed disabled:opacity-50"
              >
                {task.status === "running" ? "実行中の子runを停止して取消" : "取消"}
              </button>
            )}
            {canReplan && (
              <button
                type="button"
                data-testid="task-replan"
                disabled={busy}
                onClick={() => void runAction(replanTaskAgentTask)}
                className="cursor-pointer rounded bg-blue-600 px-3 py-1.5 text-xs text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                再計画
              </button>
            )}
          </div>
          {needsApproval && (
            <textarea
              aria-label="差戻し理由"
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              placeholder="差戻し理由(必須)"
              rows={2}
              className="mt-2 w-full rounded border border-slate-300 px-2 py-1 text-sm"
            />
          )}
        </section>

        {showQuestionCard && hitlRun && (
          <WaitingRunQuestionCard
            hitlRunId={hitlRun.run_id}
            questions={pendingQuestions}
            disabled={hitlBusy}
            onSubmit={async (answers) => {
              setHitlBusy(true);
              try {
                await Promise.all(
                  Object.entries(answers).map(([key, a]) =>
                    submitHitlAnswer(hitlRun.run_id, key, a.value, a.comment),
                  ),
                );
                await waitForHitlSettled(hitlRun.run_id).catch(() => undefined);
                await loadDetail(false);
              } finally {
                setHitlBusy(false);
              }
            }}
            onCancel={async () => {
              setHitlBusy(true);
              try {
                await cancelHitlRun(hitlRun.run_id);
                await loadDetail(false);
              } finally {
                setHitlBusy(false);
              }
            }}
          />
        )}

        <section className="rounded border border-slate-200 bg-white p-4">
          <h2 className="text-sm font-semibold">Plan履歴</h2>
          {detail.plans.length === 0 && (
            <p className="mt-1 text-sm text-slate-500">Planはまだありません</p>
          )}
          <ul className="mt-2 space-y-3">
            {detail.plans.map((p) => (
              <li key={p.plan_id} className="rounded border border-slate-200 p-2">
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <span className="font-medium">v{p.version}</span>
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-600">
                    {p.status}
                  </span>
                  {p.plan_id === task.current_plan_id && (
                    <span className="rounded-full bg-blue-100 px-2 py-0.5 text-[10px] font-medium text-blue-800">
                      現行
                    </span>
                  )}
                  <span className="text-slate-400">{formatDateTime(p.created_at)}</span>
                </div>
                {p.rejection_reason && (
                  <p className="mt-1 text-xs text-rose-700">
                    差戻し理由: {p.rejection_reason}
                  </p>
                )}
                {isDirectionalPlan(p.plan) ? (
                  <DirectionalPlanView plan={p.plan as DirectionalPlanJson} />
                ) : (
                  <LegacyPlanView plan={p.plan} />
                )}
                <pre className="mt-1 overflow-x-auto whitespace-pre-wrap text-xs text-slate-700">
                  {JSON.stringify(p.plan, null, 1)}
                </pre>
              </li>
            ))}
          </ul>
        </section>

        {actionHistory.length > 0 && (
          <section className="rounded border border-slate-200 bg-white p-4">
            <h2 className="text-sm font-semibold">実行Action履歴</h2>
            <ul className="mt-1 space-y-2 text-xs text-slate-700">
              {actionHistory.map((e) => (
                <li key={e.event_id} className="rounded border border-slate-100 p-2">
                  <div className="font-medium">
                    Action {String(e.payload?.action_index ?? e.payload?.step_index ?? "?")}:{" "}
                    {String(e.payload?.capability_key ?? "")}
                  </div>
                  {e.payload?.inputs != null && (
                    <pre className="mt-1 overflow-x-auto whitespace-pre-wrap text-slate-600">
                      入力: {JSON.stringify(e.payload.inputs)}
                    </pre>
                  )}
                  {(e.payload?.observation ?? e.payload?.summary) != null && (
                    <p className="mt-1 whitespace-pre-wrap text-slate-600">
                      結果: {String(e.payload?.observation ?? e.payload?.summary)}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          </section>
        )}

        {childRefs.length > 0 && (
          <section className="rounded border border-slate-200 bg-white p-4">
            <h2 className="text-sm font-semibold">子run参照</h2>
            <ul className="mt-1 space-y-1 text-xs text-slate-700">
              {childRefs.map((e) => (
                <li key={e.event_id}>
                  {String(e.payload?.child_kind ?? "")}:{" "}
                  {String(e.payload?.child_run_id ?? "")}
                  {e.payload?.agent_id && ` (agent: ${String(e.payload.agent_id)})`}
                  {e.payload?.project_id != null &&
                    ` (project: ${String(e.payload.project_id)}${e.payload?.backend ? `/${String(e.payload.backend)}` : ""})`}
                </li>
              ))}
            </ul>
          </section>
        )}

        <section className="rounded border border-slate-200 bg-white p-4">
          <h2 className="text-sm font-semibold">実行Event</h2>
          {detail.events.length === 0 && (
            <p className="mt-1 text-sm text-slate-500">Eventはまだありません</p>
          )}
          <ul className="mt-1 divide-y divide-slate-100 text-xs">
            {detail.events.map((e) => (
              <li key={e.event_id} className="py-1">
                <span className="font-medium">{eventTypeLabel(e.event_type)}</span>
                <span className="ml-2 text-slate-400">{formatDateTime(e.created_at)}</span>
                <pre className="overflow-x-auto whitespace-pre-wrap text-slate-600">
                  {JSON.stringify(e.payload)}
                </pre>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}
