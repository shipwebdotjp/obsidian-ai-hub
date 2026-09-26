import { useCallback, useEffect, useRef, useState } from "react";
import { getApiErrorMessage } from "../../utils/error";
import { Link } from "react-router-dom";
import {
  ApiError,
  approveTaskAgentTask,
  cancelHitlRun,
  cancelTaskAgentTask,
  getHitlRun,
  getTaskAgentTask,
  listTaskAgentTargetOptions,
  rejectTaskAgentTask,
  replanTaskAgentTask,
  setTaskAgentProjectResolution,
  submitHitlAnswer,
} from "../../api/client";
import type {
  HitlRunDetail,
  TaskAgentEvent,
  TaskAgentProjectResolution,
  TaskAgentTargetOption,
  TaskAgentTaskDetail,
} from "../../api/types";
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
import { SmartText, StructuredValue } from "./StructuredValue";
import { GeneratedMediaList } from "../media/GeneratedMediaList";
import {
  ChildRunLink,
  HitlRunLink,
  childRunRefFromPayload,
  hitlRunIdFromPayload,
} from "./ChildRunLink";

const TERMINAL_SET = new Set<string>(TERMINAL_STATUSES);
const APPROVAL_STATUSES = ["waiting_approval", "waiting_reapproval"];
const ANSWERABLE_HITL_STATUSES = ["pending_user", "ready_to_resume"];

interface DirectionalPlanJson {
  purpose?: unknown;
  strategy?: unknown;
  capabilities?: Array<{ capability_key?: unknown; intent?: unknown }>;
  allowed_agent_ids?: unknown;
  allowed_project_ids?: unknown;
  project_resolution?: TaskAgentProjectResolution | null;
  constraints?: unknown;
  completion_criteria?: unknown;
  max_actions?: unknown;
}

function resolutionSummaryText(
  resolution: TaskAgentProjectResolution,
): string {
  if (resolution.kind === "project") {
    const name =
      resolution.display_name && resolution.display_name.trim()
        ? resolution.display_name
        : `Project ${String(resolution.project_id ?? "")}`;
    return name;
  }
  return "一般Task";
}

function resolutionSourceLabel(source: string): string {
  return source === "user" ? "人間選択" : "推定";
}

function ProjectResolutionView({
  resolution,
}: {
  resolution: TaskAgentProjectResolution;
}) {
  return (
    <div className="mt-1 rounded border border-slate-200 bg-slate-50 px-2 py-1">
      <p className="min-w-0 break-words">
        <span className="font-medium">対象: </span>
        {resolutionSummaryText(resolution)}
        {resolution.kind === "project" &&
          resolution.project_id !== null &&
          resolution.project_id !== undefined && (
            <span className="text-slate-500">
              {" "}
              (project:{String(resolution.project_id)})
            </span>
          )}
      </p>
      <p className="mt-0.5 min-w-0 break-words text-slate-500">
        選定元: {resolutionSourceLabel(resolution.source)}
        {resolution.source === "inferred" &&
        resolution.confidence !== null &&
        resolution.confidence !== undefined ? (
          <> / スコア: {String(resolution.confidence)}</>
        ) : null}
        {resolution.rationale ? (
          <>
            {" "}
            / 根拠:{" "}
            <span className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
              {resolution.rationale}
            </span>
          </>
        ) : null}
      </p>
    </div>
  );
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
      {plan.project_resolution !== null &&
      plan.project_resolution !== undefined &&
      typeof plan.project_resolution === "object" &&
      (plan.project_resolution.kind === "project" ||
        plan.project_resolution.kind === "general") ? (
        <ProjectResolutionView
          resolution={plan.project_resolution as TaskAgentProjectResolution}
        />
      ) : (
        <p className="min-w-0 break-words text-slate-500">
          対象: 未記録（v3より前のPlan）
        </p>
      )}
      {typeof plan.purpose === "string" && (
        <p className="min-w-0 whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
          <span className="font-medium">目的: </span>
          {plan.purpose}
        </p>
      )}
      {typeof plan.strategy === "string" && plan.strategy && (
        <p className="min-w-0 whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
          <span className="font-medium">方針: </span>
          {plan.strategy}
        </p>
      )}
      {Array.isArray(plan.capabilities) && (
        <ul className="space-y-0.5">
          {plan.capabilities.map((c, i) => (
            <li
              key={String(c.capability_key ?? i)}
              className="flex min-w-0 flex-wrap items-center gap-1"
            >
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium break-all text-slate-700">
                {String(c.capability_key ?? "")}
              </span>
              {typeof c.intent === "string" && c.intent && (
                <span className="min-w-0 break-words text-slate-600">
                  {c.intent}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      {typeof plan.constraints === "string" && plan.constraints && (
        <p className="min-w-0 whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
          <span className="font-medium">制約: </span>
          {plan.constraints}
        </p>
      )}
      {Array.isArray(plan.allowed_agent_ids) && plan.allowed_agent_ids.length > 0 && (
        <p className="min-w-0 break-words text-slate-500">
          委譲可能なAgent: {plan.allowed_agent_ids.map(String).join(", ")}
        </p>
      )}
      {Array.isArray(plan.allowed_project_ids) &&
        plan.allowed_project_ids.length > 0 && (
          <p className="min-w-0 break-words text-slate-500">
            実行可能なProject: {plan.allowed_project_ids.map(String).join(", ")}
          </p>
        )}
      {typeof plan.completion_criteria === "string" && (
        <p className="min-w-0 whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
          <span className="font-medium">完了条件: </span>
          {plan.completion_criteria}
        </p>
      )}
      {plan.max_actions !== null && plan.max_actions !== undefined && (
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
        <p className="min-w-0 whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
          <span className="font-medium">目的: </span>
          {p["purpose"]}
        </p>
      )}
      <p className="text-slate-500">Step数: {steps.length}</p>
    </div>
  );
}

/** payload 中の run 参照を識別可能なラベル付きリンクとして表示する。 */
function RelatedRunLinks({ payload }: { payload: Record<string, unknown> }) {
  const childRef = childRunRefFromPayload(payload);
  const hitlRunId = hitlRunIdFromPayload(payload);
  if (!childRef && !hitlRunId) return null;
  return (
    <p className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 text-xs">
      <span className="shrink-0 font-medium text-slate-500">関連run:</span>
      {childRef && <ChildRunLink {...childRef} />}
      {hitlRunId && <HitlRunLink runId={hitlRunId} />}
    </p>
  );
}

function defaultTargetValue(detail: TaskAgentTaskDetail | null): string {
  if (!detail) return "";
  const current = detail.plans.find(
    (p) => p.plan_id === detail.task.current_plan_id,
  );
  const resolution = (current?.plan as DirectionalPlanJson | undefined)
    ?.project_resolution;
  if (
    resolution &&
    resolution.kind === "project" &&
    resolution.project_id !== null &&
    resolution.project_id !== undefined
  ) {
    return `project:${resolution.project_id}`;
  }
  if (resolution && resolution.kind === "general") return "general";
  return "";
}

function sessionIdForRunId(
  events: TaskAgentEvent[],
  runId: string,
): string | null {
  for (const e of events) {
    const payload = e.payload as Record<string, unknown> | null | undefined;
    if (
      payload &&
      typeof payload === "object" &&
      payload["child_run_id"] === runId &&
      typeof payload["session_id"] === "string" &&
      payload["session_id"] !== ""
    ) {
      return payload["session_id"];
    }
  }
  return null;
}

export default function TaskAgentDetailPanel({
  taskId,
  onTaskChanged,
}: {
  taskId: string;
  /** approve/reject/cancel/replan 成功時に呼ばれる（一覧の再取得用）。 */
  onTaskChanged?: () => void;
}) {
  const [detail, setDetail] = useState<TaskAgentTaskDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [hitlRun, setHitlRun] = useState<HitlRunDetail | null>(null);
  const [hitlBusy, setHitlBusy] = useState(false);
  const [loadedTaskId, setLoadedTaskId] = useState<string | null>(null);
  const [targetOptions, setTargetOptions] = useState<TaskAgentTargetOption[]>(
    [],
  );
  const [targetOptionsError, setTargetOptionsError] = useState<string | null>(
    null,
  );
  const [selectedTarget, setSelectedTarget] = useState("");
  const [targetBusy, setTargetBusy] = useState(false);
  const inFlightRef = useRef(false);
  const requestGenRef = useRef(0);

  useEffect(() => {
    requestGenRef.current++;
    setRejectReason("");
    setActionError(null);
    setHitlRun(null);
    setTargetOptions([]);
    setTargetOptionsError(null);
    setSelectedTarget("");
  }, [taskId]);

  const loadDetail = useCallback(
    async (showLoading = true) => {
      if (!taskId) {
        setError("Taskが見つかりません");
        setLoading(false);
        return;
      }
      const currentGen = ++requestGenRef.current;
      if (showLoading) setLoading(true);
      setError(null);
      try {
        const res = await getTaskAgentTask(taskId);
        if (currentGen !== requestGenRef.current) return;
        setDetail(res);
        setLoadedTaskId(taskId);
        const asked = res.events
          .filter((e) => e.event_type === "hitl_question_asked")
          .sort((a, b) => (a.seq ?? 0) - (b.seq ?? 0))
          .at(-1);
        const hitlRunId = asked?.payload?.hitl_run_id;
        if (typeof hitlRunId === "string" && hitlRunId) {
          try {
            const hr = await getHitlRun(hitlRunId);
            if (currentGen !== requestGenRef.current) return;
            setHitlRun(hr);
          } catch (e) {
            if (currentGen !== requestGenRef.current) return;
            setHitlRun(null);
            setActionError(
              e instanceof ApiError
                ? `確認タスク読み込みエラー: ${e.message}`
                : "確認タスクの読み込みに失敗しました",
            );
          }
        } else {
          if (currentGen !== requestGenRef.current) return;
          setHitlRun(null);
        }
      } catch (e) {
        if (currentGen !== requestGenRef.current) return;
        setError(getApiErrorMessage(e, "読み込みに失敗しました"));
      } finally {
        if (currentGen === requestGenRef.current && showLoading) {
          setLoading(false);
        }
      }
    },
    [taskId],
  );

  useEffect(() => {
    void loadDetail();
  }, [loadDetail]);

  const currentDefaultTarget = detail ? defaultTargetValue(detail) : "";

  useEffect(() => {
    const status = detail?.task.status;
    if (!status || loadedTaskId !== taskId) return;
    if (!APPROVAL_STATUSES.includes(status)) return;
    const currentGen = requestGenRef.current;
    void listTaskAgentTargetOptions()
      .then((res) => {
        if (currentGen !== requestGenRef.current) return;
        const items = res.items ?? [];
        setTargetOptions(items);
        setTargetOptionsError(null);
        setSelectedTarget((prev) => prev || currentDefaultTarget);
      })
      .catch((e) => {
        if (currentGen !== requestGenRef.current) return;
        setTargetOptions([]);
        setTargetOptionsError(
          e instanceof ApiError
            ? `対象候補の読み込みエラー: ${e.message}`
            : "対象候補の読み込みに失敗しました",
        );
      });
    // Polling recreates `detail` every 3s; depend on the stable status and
    // resolution value instead of the object identity to avoid refetching.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail?.task.status, loadedTaskId, taskId, currentDefaultTarget]);

  useEffect(() => {
    const status = detail?.task.status;
    if (!status || loadedTaskId !== taskId || TERMINAL_SET.has(status)) return;
    const id = setInterval(() => {
      if (inFlightRef.current) return;
      inFlightRef.current = true;
      void loadDetail(false).finally(() => {
        inFlightRef.current = false;
      });
    }, 3000);
    return () => clearInterval(id);
  }, [loadDetail, detail?.task.status, loadedTaskId, taskId]);

  const runAction = useCallback(
    async (fn: (id: string) => Promise<unknown>) => {
      if (!taskId) return;
      setBusy(true);
      setActionError(null);
      try {
        await fn(taskId);
        await loadDetail(false);
        onTaskChanged?.();
      } catch (e) {
        setActionError(getApiErrorMessage(e, "操作に失敗しました"));
      } finally {
        setBusy(false);
      }
    },
    [taskId, loadDetail, onTaskChanged],
  );

  const changeTarget = useCallback(async () => {
    if (!taskId || !selectedTarget || targetBusy) return;
    const body =
      selectedTarget === "general"
        ? ({ kind: "general" } as const)
        : ({
            kind: "project",
            project_id: Number(selectedTarget.slice("project:".length)),
          } as const);
    if (
      body.kind === "project" &&
      (!Number.isInteger(body.project_id) || body.project_id <= 0)
    ) {
      setActionError("対象の選択が不正です");
      return;
    }
    setTargetBusy(true);
    setActionError(null);
    try {
      await setTaskAgentProjectResolution(taskId, body);
      await loadDetail(false);
      onTaskChanged?.();
    } catch (e) {
      setActionError(getApiErrorMessage(e, "対象の変更に失敗しました"));
    } finally {
      setTargetBusy(false);
    }
  }, [taskId, selectedTarget, targetBusy, loadDetail, onTaskChanged]);

  // 初回ロードかつ前回内容がない場合のみ全画面ローディングにする。
  // 行切替時は直前の内容を維持する（AGENTS.md: コンポーネントのマウント・更新）。
  if (loading && !detail)
    return <p className="p-4 text-sm text-slate-500">読み込み中…</p>;
  if (error && !detail)
    return (
      <div className="bg-slate-50 p-4">
        <p className="rounded border border-rose-300 bg-rose-50 p-2 text-sm text-rose-700">
          {error}
        </p>
        <Link
          to={ROUTES.TASK_AGENT}
          className="mt-2 inline-block text-sm text-blue-600"
        >
          ← 一覧
        </Link>
      </div>
    );
  if (!detail) return null;

  const task = detail.task;
  const isTerminal = TERMINAL_SET.has(task.status);
  const needsApproval = APPROVAL_STATUSES.includes(task.status);
  const canReplan = task.status === "interrupted";
  const showingStale = loadedTaskId !== null && loadedTaskId !== taskId;
  const childRefEvents = detail.events.filter(
    (e) => childRunRefFromPayload(e.payload) !== null,
  );
  const actionHistory = detail.events.filter(
    (e) => e.event_type === "capability_completed",
  );
  const pendingQuestions = hitlRun
    ? toQuestionItems(hitlRun.questions ?? [])
    : [];
  const showQuestionCard =
    hitlRun !== null &&
    ANSWERABLE_HITL_STATUSES.includes(hitlRun.status) &&
    pendingQuestions.length > 0;
  const actionBusy = busy || targetBusy;
  const rejectDisabled = actionBusy || !rejectReason.trim();
  const activeChildSession =
    task.active_child_run_id !== null && task.active_child_run_id !== undefined
      ? sessionIdForRunId(detail.events, task.active_child_run_id)
      : null;

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col bg-slate-50">
      <header className="border-b border-slate-200 bg-white px-4 py-3">
        <Link
          to={ROUTES.TASK_AGENT}
          aria-label="一覧に戻る"
          className="text-sm text-blue-600 lg:hidden"
        >
          ← 一覧
        </Link>
        <h1 className="mt-1 text-lg font-semibold">Task詳細</h1>
        <p className="mt-0.5 break-all font-mono text-[11px] text-slate-400">
          {task.task_id}
        </p>
      </header>
      <div className="min-h-0 min-w-0 flex-1 space-y-4 overflow-y-auto p-4">
        {(loading || showingStale) && (
          <p
            aria-live="polite"
            className="rounded border border-slate-200 bg-white p-2 text-xs text-slate-500"
          >
            読み込み中…
          </p>
        )}
        {error && detail && (
          <p className="rounded border border-rose-300 bg-rose-50 p-2 text-sm text-rose-700">
            {error}
          </p>
        )}
        {actionError && (
          <p className="rounded border border-rose-300 bg-rose-50 p-2 text-sm text-rose-700">
            {actionError}
          </p>
        )}

        <section
          aria-label="ユーザータスク"
          className="min-w-0 rounded border border-slate-200 bg-white p-4"
        >
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <span className={taskStatusBadgeClass(task.status)}>
              {taskStatusLabel(task.status)}
            </span>
            <span className="min-w-0 break-words text-xs text-slate-400">
              作成 {formatDateTime(task.created_at)}
              {task.started_at && ` / 開始 ${formatDateTime(task.started_at)}`}
              {task.finished_at && ` / 終了 ${formatDateTime(task.finished_at)}`}
            </span>
          </div>
          <h2 className="mt-3 text-sm font-semibold">ユーザータスク</h2>
          <div className="mt-1 min-w-0 text-sm">
            <SmartText text={task.prompt_text} />
          </div>
          <dl className="mt-3 space-y-1 border-t border-slate-100 pt-2 text-xs text-slate-600">
            <div className="flex min-w-0 flex-wrap gap-x-2">
              <dt className="shrink-0 font-medium text-slate-500">状態:</dt>
              <dd className="min-w-0 break-all">
                {taskStatusLabel(task.status)}（{task.status}）
              </dd>
            </div>
            <div className="flex min-w-0 flex-wrap gap-x-2">
              <dt className="shrink-0 font-medium text-slate-500">現行Plan:</dt>
              <dd className="min-w-0 break-all">
                {task.current_plan_id ?? "（未設定）"}
              </dd>
            </div>
            <div className="flex min-w-0 flex-wrap gap-x-2">
              <dt className="shrink-0 font-medium text-slate-500">Worker:</dt>
              <dd className="min-w-0 break-all">
                {task.worker_instance_id ?? "（未設定）"}
              </dd>
            </div>
            {task.active_child_run_id && (
              <div className="flex min-w-0 flex-wrap gap-x-2">
                <dt className="shrink-0 font-medium text-slate-500">
                  実行中の子run:
                </dt>
                <dd className="min-w-0 flex-1">
                  <ChildRunLink
                    childKind={task.active_child_kind ?? ""}
                    childRunId={task.active_child_run_id}
                    sessionId={activeChildSession}
                  />
                </dd>
              </div>
            )}
          </dl>
          <div className="mt-3 flex flex-wrap gap-2">
            {needsApproval && (
              <>
                <button
                  type="button"
                  data-testid="task-approve"
                  disabled={actionBusy}
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
                  disabled={actionBusy}
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
          {needsApproval && (
            <div className="mt-3 border-t border-slate-100 pt-2">
              <label
                htmlFor="task-target-select"
                className="text-xs font-medium text-slate-500"
              >
                対象Project /
                一般Taskの変更（変更すると現行Planは破棄され再計画されます）
              </label>
              <div className="mt-1 flex min-w-0 flex-wrap items-center gap-2">
                <select
                  id="task-target-select"
                  aria-label="対象の変更"
                  value={selectedTarget}
                  disabled={targetBusy || busy}
                  onChange={(e) => setSelectedTarget(e.target.value)}
                  className="min-w-0 flex-1 cursor-pointer rounded border border-slate-300 px-2 py-1.5 text-xs disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <option value="">選択してください</option>
                  {targetOptions.map((o) => (
                    <option
                      key={o.project_id}
                      value={`project:${o.project_id}`}
                    >
                      {o.name}（project:{o.project_id}）
                    </option>
                  ))}
                  {selectedTarget !== "" &&
                    selectedTarget !== "general" &&
                    !targetOptions.some(
                      (o) => `project:${o.project_id}` === selectedTarget,
                    ) && (
                      <option value={selectedTarget}>
                        現在の対象（{selectedTarget} / 候補に存在しません）
                      </option>
                    )}
                  <option value="general">
                    一般Task（Projectを特定しない）
                  </option>
                </select>
                <button
                  type="button"
                  data-testid="task-change-target"
                  disabled={
                    targetBusy ||
                    busy ||
                    !selectedTarget ||
                    selectedTarget === currentDefaultTarget
                  }
                  onClick={() => void changeTarget()}
                  className="cursor-pointer rounded bg-slate-900 px-3 py-1.5 text-xs text-white disabled:cursor-not-allowed disabled:opacity-50"
                >
                  対象を変更して再計画
                </button>
              </div>
              {targetOptionsError && (
                <p className="mt-1 text-xs text-rose-700">
                  {targetOptionsError}
                </p>
              )}
            </div>
          )}
        </section>

        <section
          aria-label="結果"
          className="min-w-0 rounded border border-slate-200 bg-white p-4"
        >
          <h2 className="text-sm font-semibold">結果</h2>
          {!task.result_summary && !task.error_summary && (
            <p className="mt-1 text-sm text-slate-500">結果はまだありません</p>
          )}
          {task.result_summary && (
            <div className="mt-1 min-w-0 text-sm text-slate-700">
              <SmartText text={task.result_summary} />
            </div>
          )}
          {task.error_summary && (
            <div className="mt-2 min-w-0 text-sm text-rose-700">
              <p className="text-xs font-medium">エラー:</p>
              <SmartText text={task.error_summary} />
            </div>
          )}
        </section>

        {showQuestionCard && hitlRun && (
          <WaitingRunQuestionCard
            hitlRunId={hitlRun.run_id}
            questions={pendingQuestions}
            disabled={hitlBusy}
            onSubmit={async (answers) => {
              setHitlBusy(true);
              setActionError(null);
              try {
                await Promise.all(
                  Object.entries(answers).map(([key, a]) =>
                    submitHitlAnswer(hitlRun.run_id, key, a.value, a.comment),
                  ),
                );
                await waitForHitlSettled(hitlRun.run_id).catch(() => undefined);
                await loadDetail(false);
              } catch (e) {
                setActionError(
                  e instanceof ApiError
                    ? e.message
                    : "回答の送信に失敗しました",
                );
                throw e;
              } finally {
                setHitlBusy(false);
              }
            }}
            onCancel={async () => {
              setHitlBusy(true);
              setActionError(null);
              try {
                await cancelHitlRun(hitlRun.run_id);
                await loadDetail(false);
              } catch (e) {
                setActionError(
                  e instanceof ApiError
                    ? e.message
                    : "確認タスクの取消に失敗しました",
                );
                throw e;
              } finally {
                setHitlBusy(false);
              }
            }}
          />
        )}

        <section
          aria-label="Plan履歴"
          className="min-w-0 rounded border border-slate-200 bg-white p-4"
        >
          <h2 className="text-sm font-semibold">Plan履歴</h2>
          {detail.plans.length === 0 && (
            <p className="mt-1 text-sm text-slate-500">Planはまだありません</p>
          )}
          <ul className="mt-2 space-y-3">
            {detail.plans.map((p) => (
              <li
                key={p.plan_id}
                className="min-w-0 rounded border border-slate-200 p-2"
              >
                <div className="flex min-w-0 flex-wrap items-center gap-2 text-xs">
                  <span className="font-medium">v{p.version}</span>
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-600">
                    {p.status}
                  </span>
                  {p.plan_id === task.current_plan_id && (
                    <span className="rounded-full bg-blue-100 px-2 py-0.5 text-[10px] font-medium text-blue-800">
                      現行
                    </span>
                  )}
                  <span className="min-w-0 break-words text-slate-400">
                    {formatDateTime(p.created_at)}
                  </span>
                </div>
                <p className="mt-1 min-w-0 break-all text-[11px] text-slate-400">
                  Plan ID: {p.plan_id}
                  {p.decided_at && ` / 決定 ${formatDateTime(p.decided_at)}`}
                </p>
                {p.rejection_reason && (
                  <p className="mt-1 min-w-0 whitespace-pre-wrap break-words text-xs text-rose-700 [overflow-wrap:anywhere]">
                    差戻し理由: {p.rejection_reason}
                  </p>
                )}
                {isDirectionalPlan(p.plan) ? (
                  <DirectionalPlanView plan={p.plan as DirectionalPlanJson} />
                ) : (
                  <LegacyPlanView plan={p.plan} />
                )}
                <div className="mt-2 min-w-0 border-t border-slate-100 pt-2 text-xs text-slate-700">
                  <p className="font-medium text-slate-500">Planデータ全体</p>
                  <div className="mt-1 min-w-0">
                    <StructuredValue value={p.plan} />
                  </div>
                </div>
                <div className="mt-2 min-w-0 text-xs text-slate-700">
                  <p className="font-medium text-slate-500">
                    承認ポリシースナップショット
                  </p>
                  <div className="mt-1 min-w-0">
                    <StructuredValue value={p.approval_policy_snapshot} />
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </section>

        {actionHistory.length > 0 && (
          <section
            aria-label="実行Action履歴"
            className="min-w-0 rounded border border-slate-200 bg-white p-4"
          >
            <h2 className="text-sm font-semibold">実行Action履歴</h2>
            <ul className="mt-1 space-y-2 text-xs text-slate-700">
              {actionHistory.map((e) => (
                <li
                  key={e.event_id}
                  className="min-w-0 rounded border border-slate-100 p-2"
                >
                  <div className="min-w-0 break-words font-medium">
                    Action{" "}
                    {String(e.payload?.action_index ?? e.payload?.step_index ?? "?")}
                    : {String(e.payload?.capability_key ?? "")}
                  </div>
                  <RelatedRunLinks payload={e.payload} />
                  <GeneratedMediaList value={e.payload} />
                  <div className="mt-1 min-w-0">
                    <StructuredValue value={e.payload} />
                  </div>
                </li>
              ))}
            </ul>
          </section>
        )}

        {childRefEvents.length > 0 && (
          <section
            aria-label="子run参照"
            className="min-w-0 rounded border border-slate-200 bg-white p-4"
          >
            <h2 className="text-sm font-semibold">子run参照</h2>
            <ul className="mt-1 space-y-1 text-xs text-slate-700">
              {childRefEvents.map((e) => {
                const ref = childRunRefFromPayload(e.payload);
                if (!ref) return null;
                const stepLabel =
                  e.payload?.step_index ?? e.payload?.action_index;
                return (
                  <li key={e.event_id} className="min-w-0">
                    <ChildRunLink {...ref} />
                    <span className="ml-2 break-words text-slate-400">
                      （{eventTypeLabel(e.event_type)}
                      {stepLabel !== null && stepLabel !== undefined
                        ? ` / Step ${String(stepLabel)}`
                        : ""}
                      {` / ${formatDateTime(e.created_at)}`}）
                    </span>
                  </li>
                );
              })}
            </ul>
          </section>
        )}

        <section
          aria-label="実行Event"
          className="min-w-0 rounded border border-slate-200 bg-white p-4"
        >
          <h2 className="text-sm font-semibold">実行Event</h2>
          {detail.events.length === 0 && (
            <p className="mt-1 text-sm text-slate-500">Eventはまだありません</p>
          )}
          <ul className="mt-1 divide-y divide-slate-100 text-xs">
            {detail.events.map((e) => (
              <li key={e.event_id} className="min-w-0 py-2">
                <span className="font-medium">{eventTypeLabel(e.event_type)}</span>
                <span className="ml-2 break-words text-slate-400">
                  {formatDateTime(e.created_at)}（seq {e.seq}）
                </span>
                <RelatedRunLinks payload={e.payload} />
                <GeneratedMediaList value={e.payload} />
                <div className="mt-1 min-w-0 text-slate-600">
                  <StructuredValue value={e.payload} />
                </div>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}
