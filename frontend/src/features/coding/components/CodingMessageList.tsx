import { useMemo, type RefObject } from "react";
import type {
  CodingLiveToolCall,
  CodingMessage,
  CodingRun,
  CodingSessionDetail,
} from "../../../api/coding";
import MarkdownPreview from "../../../components/MarkdownPreview";
import { CopyMessageButton } from "../../../components/CopyMessageButton";
import {
  WaitingRunQuestionCard,
  WaitingRunStatusPanel,
  type ActiveWaitingRun,
} from "../../../components/InConversationQuestionCard";
import { AnsweredRequirementCard } from "../../../components/AnsweredRequirementCard";
import { formatDateTime } from "../../../utils/date";
import type { QueuedCodingMessage } from "../utils/codingSendQueue";
import {
  buildRunById,
  getRunIdForUserMessage,
  groupToolCallsByMessageId,
  groupUnassociatedToolCallsByRunId,
} from "../utils/codingSelectors";
import {
  formatCost,
  formatTokenBreakdown,
  hasCumulativeUsage,
  runUsageSummary,
} from "../utils/codingUsage";

interface CodingMessageListProps {
  messages: CodingMessage[];
  loadingMessages: boolean;
  isStreaming: boolean;
  sessionDetail: CodingSessionDetail | null;
  activeRun: CodingRun | null;
  latestRun: CodingRun | null;
  currentRun: CodingRun | null;
  activeWaitingRun: ActiveWaitingRun | null;
  streamingToolCalls: CodingLiveToolCall[];
  streamingText?: string;
  streamingThought?: string;
  acpToolCalls?: CodingLiveToolCall[];
  streamingPlan?: string[];
  activePhaseText: string | null;
  workerState: {
    status: "idle" | "running" | "done";
    attempt?: number;
    backend?: string;
    output?: string;
    error?: string | null;
  };
  copiedMessageId: string | null;
  onCopyMessage: (content: string, messageId: string) => void;
  onSubmitWaitingAnswers: (
    waiting: ActiveWaitingRun,
    answers: Record<string, { value: string; comment?: string }>,
  ) => Promise<void>;
  onCancelWaitingRun: (waiting: ActiveWaitingRun) => Promise<void>;
  queuedMessages?: QueuedCodingMessage[];
  onRemoveQueuedMessage?: (queueId: string) => void;
  onRetryQueuedMessage?: (queueId: string) => void;
  messageEndRef: RefObject<HTMLDivElement>;
  scrollContainerRef?: RefObject<HTMLDivElement>;
  onScrollMessages?: () => void;
  backend: string;
}

/** Live tool-call card shared by Coordinator and ACP worker streams. */
function StreamingToolCallCard({
  tc,
  tone,
  testId,
}: {
  tc: CodingLiveToolCall;
  tone: "slate" | "teal";
  testId?: string;
}) {
  const border = tone === "teal" ? "border-teal-200" : "border-slate-200";
  const headerBg =
    tone === "teal" ? "bg-teal-50 hover:bg-teal-100" : "bg-slate-50 hover:bg-slate-100";
  return (
    <details
      className={`rounded border ${border} bg-white text-xs overflow-hidden group`}
      data-testid={testId}
    >
      <summary
        className={`cursor-pointer list-none flex items-center justify-between gap-2 px-3 py-1.5 ${headerBg}`}
      >
        <span className="flex items-center gap-1.5 min-w-0">
          <span className="font-semibold truncate text-slate-800">{tc.tool_name}</span>
          <span
            className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold border ${
              tc.status === "succeeded"
                ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                : tc.status === "failed"
                ? "bg-rose-50 text-rose-700 border-rose-200"
                : tc.status === "running"
                ? "bg-amber-50 text-amber-700 border-amber-200"
                : "bg-blue-50 text-blue-700 border-blue-200"
            }`}
          >
            {tc.status === "succeeded"
              ? "成功"
              : tc.status === "failed"
              ? "失敗"
              : tc.status === "running"
              ? "実行中…"
              : "準備中…"}
          </span>
        </span>
        <span className="text-[10px] text-slate-400 group-open:rotate-180 transition-transform shrink-0">▼</span>
      </summary>
      <div className={`border-t ${border} p-3 space-y-2 bg-white`}>
        {tc.status === "preparing" ? (
          <div className="flex items-center gap-2 text-[11px] text-blue-700">
            <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-blue-200 border-t-blue-600" />
            ツール呼び出しを準備中…
          </div>
        ) : (
          <>
            <div>
              <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1">引数</div>
              <pre className="max-h-40 overflow-auto rounded bg-slate-50 border border-slate-200 p-2 text-[11px] font-mono whitespace-pre-wrap break-all">
                {(() => {
                  try {
                    return JSON.stringify(tc.args, null, 2);
                  } catch {
                    return String(tc.args);
                  }
                })()}
              </pre>
            </div>
            {tc.status !== "running" && (
              <div>
                <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1">結果</div>
                <pre className="max-h-64 overflow-auto rounded bg-slate-50 border border-slate-200 p-2 text-[11px] font-mono whitespace-pre-wrap break-all">
                  {tc.result || "-"}
                </pre>
              </div>
            )}
          </>
        )}
        {tc.status === "running" && (
          <div className="flex items-center gap-2 text-[11px] text-amber-700">
            <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-amber-300 border-t-amber-600" />
            実行中…
          </div>
        )}
        {tc.error && (
          <div className="text-[11px] text-rose-700 bg-rose-50 border border-rose-200 rounded px-2 py-1 break-all">
            {tc.error}
          </div>
        )}
      </div>
    </details>
  );
}

/** 会話メッセージ一覧とストリーミング・待機中質問の表示。 */
export function CodingMessageList({
  messages,
  loadingMessages,
  isStreaming,
  sessionDetail,
  activeRun,
  latestRun,
  currentRun,
  activeWaitingRun,
  streamingToolCalls,
  streamingText = "",
  streamingThought = "",
  acpToolCalls = [],
  streamingPlan = [],
  activePhaseText,
  workerState,
  copiedMessageId,
  onCopyMessage,
  onSubmitWaitingAnswers,
  onCancelWaitingRun,
  queuedMessages = [],
  onRemoveQueuedMessage,
  onRetryQueuedMessage,
  messageEndRef,
  scrollContainerRef,
  onScrollMessages,
  backend,
}: CodingMessageListProps) {
  const toolCallsByMessageId = useMemo(
    () => groupToolCallsByMessageId(sessionDetail?.orchestrator_tool_calls),
    [sessionDetail?.orchestrator_tool_calls],
  );

  const unassociatedToolCallsByRunId = useMemo(
    () => groupUnassociatedToolCallsByRunId(sessionDetail?.orchestrator_tool_calls),
    [sessionDetail?.orchestrator_tool_calls],
  );

  const runById = useMemo(
    () => buildRunById(sessionDetail?.runs, activeRun, latestRun),
    [sessionDetail?.runs, activeRun, latestRun],
  );

  return (
    // relative: contains absolutely-positioned descendants (e.g. sr-only
    // toggle labels) inside this scroll container so they never extend the
    // document's scrollable overflow (outer page scrollbar).
    <div
      ref={scrollContainerRef}
      onScroll={onScrollMessages}
      className="flex-1 overflow-y-auto p-4 space-y-4 min-w-0 relative"
    >
      {loadingMessages && messages.length > 0 && (
        <div className="text-center text-[11px] text-slate-400" aria-live="polite">
          会話履歴を更新中...
        </div>
      )}
      {loadingMessages && messages.length === 0 && !isStreaming ? (
        <div className="text-center text-xs text-slate-500 py-8">
          会話履歴読み込み中...
        </div>
      ) : messages.length === 0 && !isStreaming ? (
        <div className="text-center text-xs text-slate-400 py-8">
          ユーザーメッセージを入力してコーディングセッションを開始してください
        </div>
      ) : (
        messages.map((msg) => (
          <div key={msg.message_id} className="space-y-1 min-w-0">
            {msg.role === "user" && (
              <>
                <div className="flex flex-col items-end min-w-0">
                  {(() => {
                    const uRunId = getRunIdForUserMessage(msg, activeRun, latestRun);
                    const uRun = uRunId ? runById.get(uRunId) ?? null : null;
                    if (uRun?.slash_invocation) {
                      return (
                        <div className="mb-1 inline-flex items-center gap-1 rounded bg-blue-100 px-2 py-0.5 text-[10px] font-semibold text-blue-800">
                          <span>/{uRun.slash_invocation.name}</span>
                        </div>
                      );
                    }
                    return null;
                  })()}
                  <div className="max-w-2xl min-w-0 overflow-hidden rounded-2xl bg-slate-900 px-4 py-2.5 text-xs text-white [overflow-wrap:anywhere]">
                    <p className="whitespace-pre-wrap wrap-anywhere break-words [overflow-wrap:anywhere] [word-break:break-word]">
                      {msg.content}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2 text-[10px] text-slate-400 justify-end">
                  <CopyMessageButton
                    content={msg.content}
                    messageId={msg.message_id}
                    copiedMessageId={copiedMessageId}
                    onCopy={onCopyMessage}
                  />
                  <span aria-label="送信時刻">{formatDateTime(msg.created_at)}</span>
                </div>
                {sessionDetail?.ask_user_answer_history
                  ?.filter((round) => round.user_message_id === msg.message_id)
                  .map((round) => (
                    <AnsweredRequirementCard
                      key={`${round.hitl_run_id}-${round.tool_call_id}`}
                      round={round}
                    />
                  ))}
                {(() => {
                  const userRunId = getRunIdForUserMessage(msg, activeRun, latestRun);
                  const unassociatedToolCalls = userRunId
                    ? unassociatedToolCallsByRunId.get(userRunId) || []
                    : [];
                  if (unassociatedToolCalls.length === 0) return null;
                  return (
                    <div className="flex justify-start my-1.5 min-w-0">
                      <div className="max-w-2xl w-full min-w-0 space-y-1.5 rounded-xl border border-amber-200 bg-amber-50/50 px-3 py-2">
                        <div className="text-[10px] font-bold uppercase tracking-wider text-amber-800">
                          中断したオーケストレーター処理 ({unassociatedToolCalls.length}件)
                        </div>
                        {unassociatedToolCalls.map((tc) => (
                          <details
                            key={tc.call_id}
                            className="rounded border border-amber-200 bg-white text-xs overflow-hidden group"
                          >
                            <summary className="cursor-pointer list-none flex items-center justify-between gap-2 px-3 py-1.5 bg-amber-50/80 hover:bg-amber-100/80">
                              <span className="flex items-center gap-1.5 min-w-0">
                                <span className="font-semibold truncate text-slate-800">{tc.tool_name}</span>
                                <span
                                  className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold border ${
                                    tc.status === "succeeded"
                                      ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                                      : tc.status === "failed"
                                      ? "bg-rose-50 text-rose-700 border-rose-200"
                                      : "bg-amber-100 text-amber-800 border-amber-300"
                                  }`}
                                >
                                  {tc.status === "succeeded"
                                    ? "成功"
                                    : tc.status === "failed"
                                    ? "失敗"
                                    : "中断"}
                                </span>
                              </span>
                              <span className="text-[10px] text-slate-400 group-open:rotate-180 transition-transform shrink-0">▼</span>
                            </summary>
                            <div className="border-t border-amber-200 p-3 space-y-2 bg-white">
                              <div>
                                <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1">引数</div>
                                <pre className="max-h-40 overflow-auto rounded bg-slate-50 border border-slate-200 p-2 text-[11px] font-mono whitespace-pre-wrap break-all">
                                  {(() => {
                                    try {
                                      return JSON.stringify(tc.args, null, 2);
                                    } catch {
                                      return String(tc.args);
                                    }
                                  })()}
                                </pre>
                              </div>
                              <div>
                                <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1">結果</div>
                                <pre className="max-h-64 overflow-auto rounded bg-slate-50 border border-slate-200 p-2 text-[11px] font-mono whitespace-pre-wrap break-all">
                                  {tc.result || "-"}
                                </pre>
                              </div>
                              {tc.error && (
                                <div className="text-[11px] text-rose-700 bg-rose-50 border border-rose-200 rounded px-2 py-1 break-all">
                                  {tc.error}
                                </div>
                              )}
                            </div>
                          </details>
                        ))}
                      </div>
                    </div>
                  );
                })()}
              </>
            )}

            {msg.role === "orchestrator" && (
              <>
                {(() => {
                  const toolCalls = toolCallsByMessageId.get(msg.message_id) || [];
                  if (toolCalls.length === 0) return null;
                  return (
                    <div className="flex justify-start my-1.5 min-w-0">
                      <div className="max-w-2xl w-full min-w-0 space-y-1.5 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2">
                        <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
                          ツール呼び出し {toolCalls.length}件
                        </div>
                        {toolCalls.map((tc) => (
                          <details
                            key={tc.call_id}
                            className="rounded border border-slate-200 bg-white text-xs overflow-hidden group"
                          >
                            <summary className="cursor-pointer list-none flex items-center justify-between gap-2 px-3 py-1.5 bg-slate-50 hover:bg-slate-100">
                              <span className="flex items-center gap-1.5 min-w-0">
                                <span className="font-semibold truncate text-slate-800">{tc.tool_name}</span>
                                <span
                                  className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold border ${
                                    tc.status === "succeeded"
                                      ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                                      : tc.status === "failed"
                                      ? "bg-rose-50 text-rose-700 border-rose-200"
                                      : "bg-amber-50 text-amber-700 border-amber-200"
                                  }`}
                                >
                                  {tc.status === "succeeded"
                                    ? "成功"
                                    : tc.status === "failed"
                                    ? "失敗"
                                    : "中断"}
                                </span>
                              </span>
                              <span className="text-[10px] text-slate-400 group-open:rotate-180 transition-transform shrink-0">▼</span>
                            </summary>
                            <div className="border-t border-slate-200 p-3 space-y-2 bg-white">
                              <div>
                                <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1">引数</div>
                                <pre className="max-h-40 overflow-auto rounded bg-slate-50 border border-slate-200 p-2 text-[11px] font-mono whitespace-pre-wrap break-all">
                                  {(() => {
                                    try {
                                      return JSON.stringify(tc.args, null, 2);
                                    } catch {
                                      return String(tc.args);
                                    }
                                  })()}
                                </pre>
                              </div>
                              <div>
                                <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1">結果</div>
                                <pre className="max-h-64 overflow-auto rounded bg-slate-50 border border-slate-200 p-2 text-[11px] font-mono whitespace-pre-wrap break-all">
                                  {tc.result || "-"}
                                </pre>
                              </div>
                              {tc.error && (
                                <div className="text-[11px] text-rose-700 bg-rose-50 border border-rose-200 rounded px-2 py-1 break-all">
                                  {tc.error}
                                </div>
                              )}
                            </div>
                          </details>
                        ))}
                      </div>
                    </div>
                  );
                })()}
                {/* Worker指示のみでユーザー向け本文が空の場合はバブルを表示しない */}
                {msg.content?.trim() ? (
                  <>
                    <div className="flex min-w-0 justify-start">
                      <div className="max-w-2xl min-w-0 overflow-hidden rounded-2xl bg-white border border-slate-200 p-4 text-xs text-slate-800 shadow-sm [overflow-wrap:anywhere]">
                        <div className="mb-1 text-[10px] font-semibold text-slate-400 uppercase">
                          AI Orchestrator
                        </div>
                        <MarkdownPreview content={msg.content} />
                      </div>
                    </div>
                    <div className="flex items-center gap-2 text-[10px] text-slate-400 justify-start">
                      <CopyMessageButton
                        content={msg.content}
                        messageId={msg.message_id}
                        copiedMessageId={copiedMessageId}
                        onCopy={onCopyMessage}
                      />
                      <span aria-label="送信時刻">{formatDateTime(msg.created_at)}</span>
                    </div>
                  </>
                ) : (toolCallsByMessageId.get(msg.message_id)?.length ? (
                  <div className="flex items-center gap-2 text-[10px] text-slate-400 justify-start">
                    <span aria-label="送信時刻">{formatDateTime(msg.created_at)}</span>
                  </div>
                ) : null)}
              </>
            )}

            {msg.role === "cli_request" && (
              <>
                <div className="flex min-w-0 justify-start">
                  <div className="w-full max-w-2xl min-w-0">
                    {/* `open` is the initial-open state: React has no
                        `defaultOpen` for <details>, and a constant `open` prop
                        never resets a user collapse on re-render. */}
                    <details
                      className="rounded-xl border border-blue-200 bg-blue-50 text-xs text-blue-950 shadow-sm overflow-hidden group min-w-0"
                      data-testid="cli-request-card"
                      open
                    >
                      <summary className="flex cursor-pointer items-center justify-between px-4 py-2.5 bg-blue-100/80 font-mono text-[11px] text-blue-950 font-semibold hover:bg-blue-100">
                        <span className="flex items-center gap-1.5">
                          <span>Workerへの指示</span>
                        </span>
                        <span className="text-blue-700 text-[10px] font-normal" aria-hidden="true">
                          <span className="group-open:hidden">▼</span>
                          <span className="hidden group-open:inline">▲</span>
                        </span>
                        <span className="sr-only">クリックで展開/折りたたみ</span>
                      </summary>
                      <div className="p-4 overflow-x-auto max-h-80 border-t border-blue-200/60 min-w-0 [overflow-wrap:anywhere]">
                        <pre className="whitespace-pre-wrap font-mono text-xs leading-relaxed text-blue-900 bg-blue-100/50 p-3 rounded-lg border border-blue-200/60 min-w-0 max-w-full [overflow-wrap:anywhere] wrap-anywhere break-words">
                          {msg.content}
                        </pre>
                      </div>
                    </details>
                  </div>
                </div>
                <div className="flex items-center gap-2 text-[10px] text-slate-400 justify-start">
                  <CopyMessageButton
                    content={msg.content}
                    messageId={msg.message_id}
                    copiedMessageId={copiedMessageId}
                    onCopy={onCopyMessage}
                    ariaLabel="指示内容をコピー"
                  />
                  <span aria-label="送信時刻">{formatDateTime(msg.created_at)}</span>
                </div>
              </>
            )}

            {msg.role === "worker" && (
              <>
                <div className="flex min-w-0 justify-start">
                  <div className="w-full max-w-2xl min-w-0">
                    {/* Initial-open; see the cli_request card note above. */}
                    <details
                      className="rounded-xl border border-slate-200 bg-slate-900 text-slate-100 text-xs shadow-sm overflow-hidden group min-w-0"
                      data-testid="worker-response-card"
                      open
                    >
                      <summary className="flex cursor-pointer items-center justify-between px-4 py-2.5 bg-slate-800 font-mono text-[11px] hover:bg-slate-700">
                        <span>Worker 最終返答 ({backend})</span>
                        <span className="text-slate-400 text-[10px]" aria-hidden="true">
                          <span className="group-open:hidden">▼</span>
                          <span className="hidden group-open:inline">▲</span>
                        </span>
                        <span className="sr-only">クリックで展開/折りたたみ</span>
                      </summary>
                      <div className="p-4 overflow-x-auto max-h-96 border-b border-slate-800 min-w-0 [overflow-wrap:anywhere]">
                        <MarkdownPreview content={msg.content} variant="dark" />
                      </div>

                      {/* Worker execution info (Coordinator tool calls are shown separately) */}
                      {(() => {
                        const msgRun = (msg.run_id ? runById.get(msg.run_id) : undefined) ?? currentRun;
                        const diag = msgRun?.diagnostics;
                        if (!diag) return null;
                        const sessionId =
                          diag.acp_session_id ||
                          diag.returned_session_id ||
                          diag.requested_session_id ||
                          null;
                        // Worker tool counts: new ACP diagnostics first, legacy
                        // direct_cli worker counts as fallback. Coordinator
                        // counts (orchestrator_tool_calls) are never used here.
                        const workerCount =
                          diag.worker_tool_call_count ?? diag.tool_call_count ?? null;
                        const workerFailures =
                          diag.worker_tool_failure_count ?? diag.tool_failure_count ?? null;
                        const hasWorkerCount =
                          typeof workerCount === "number" && Number.isFinite(workerCount);
                        const hasWorkerFailures =
                          typeof workerFailures === "number" && Number.isFinite(workerFailures);
                        const model = diag.acp_model || diag.model || null;
                        const profile = diag.acp_profile_id || null;
                        const agentName = diag.acp_agent?.name || null;
                        const agentVersion = diag.acp_agent?.version || null;
                        const hasAgent = !!(agentName || agentVersion);
                        const usage = diag.usage || null;
                        const hasUsage = !!(
                          usage &&
                          (typeof usage.input === "number" ||
                            typeof usage.output === "number" ||
                            typeof usage.total === "number" ||
                            typeof usage.cached === "number" ||
                            typeof usage.used === "number" ||
                            typeof usage.size === "number" ||
                            typeof usage.cost?.amount === "number")
                        );
                        // Run-wide accumulation over every worker attempt. Falls
                        // back to the last attempt for runs persisted before the
                        // backend began accumulating.
                        const runUsage = runUsageSummary(msgRun);
                        const cumulativeUsage = hasCumulativeUsage(msgRun);
                        const attemptCount =
                          typeof diag.worker_attempt_count === "number" &&
                          Number.isFinite(diag.worker_attempt_count)
                            ? diag.worker_attempt_count
                            : null;
                        const resultText =
                          msgRun?.status && msgRun.status !== "completed"
                            ? `${msgRun.status}${msgRun.error_message ? `: ${msgRun.error_message}` : ""}`
                            : diag.stop_reason ||
                              (typeof diag.exit_code === "number"
                                ? `exit ${diag.exit_code}`
                                : null) ||
                              diag.error ||
                              null;
                        const structError = diag.structured_error || diag.error || null;
                        const hasAny =
                          !!(
                            sessionId ||
                            resultText ||
                            hasWorkerCount ||
                            model ||
                            profile ||
                            hasAgent ||
                            hasUsage ||
                            runUsage ||
                            structError ||
                            (msgRun?.status && msgRun.status !== "completed")
                          );
                        if (!hasAny) return null;
                        return (
                        <div
                          className="p-3 bg-slate-950 font-mono text-[11px] space-y-1.5 border-t border-slate-800 text-slate-300"
                          data-testid="worker-diagnostics"
                        >
                          <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">
                            実行情報
                          </div>
                          <div className="grid grid-cols-1 gap-1 pl-1">
                            {sessionId && (
                              <div className="flex items-center gap-1.5">
                                <span className="text-slate-500">セッションID: </span>
                                <span className="text-slate-200 select-all break-all">{sessionId}</span>
                                <CopyMessageButton
                                  content={sessionId}
                                  messageId={`session-${msg.message_id}`}
                                  copiedMessageId={copiedMessageId}
                                  onCopy={onCopyMessage}
                                  ariaLabel="セッションIDをコピー"
                                />
                              </div>
                            )}
                            {resultText && (
                              <div>
                                <span className="text-slate-500">実行結果: </span>
                                <span className="text-slate-200 break-all">{resultText}</span>
                              </div>
                            )}
                            {hasWorkerCount && (
                              <div>
                                <span className="text-slate-500">Worker ツール実行: </span>
                                <span className="text-slate-200">
                                  {workerCount}回
                                  {hasWorkerFailures ? ` (失敗: ${workerFailures}回)` : ""}
                                </span>
                              </div>
                            )}
                            {model && (
                              <div>
                                <span className="text-slate-500">モデル: </span>
                                <span className="text-slate-200 break-all">
                                  {model}
                                  {diag.variant ? ` (${diag.variant})` : ""}
                                </span>
                              </div>
                            )}
                            {profile && (
                              <div>
                                <span className="text-slate-500">プロファイル: </span>
                                <span className="text-slate-200 break-all">{profile}</span>
                              </div>
                            )}
                            {hasAgent && (
                              <div>
                                <span className="text-slate-500">エージェント: </span>
                                <span className="text-slate-200 break-all">
                                  {[agentName, agentVersion].filter(Boolean).join(" ")}
                                  {diag.acp_version != null ? ` (ACP ${String(diag.acp_version)})` : ""}
                                </span>
                              </div>
                            )}
                            {runUsage && (
                              <div>
                                <span className="text-slate-500">
                                  {cumulativeUsage
                                    ? `トークン使用量（この実行の累積${attemptCount && attemptCount > 1 ? `・${attemptCount}回試行` : ""}）: `
                                    : "トークン使用量: "}
                                </span>
                                <span className="text-slate-200">
                                  {formatTokenBreakdown(runUsage)}
                                  {runUsage.costAmount !== undefined
                                    ? `（費用 ${formatCost(runUsage.costAmount, runUsage.costCurrency)}）`
                                    : ""}
                                </span>
                              </div>
                            )}
                            {structError && (
                              <div className="text-rose-400">
                                <span className="text-rose-500">構造化エラー: </span>
                                {structError}
                              </div>
                            )}
                          </div>
                        </div>
                        );
                      })()}
                    </details>
                  </div>
                </div>
                <div className="flex items-center gap-2 text-[10px] text-slate-400 justify-start">
                  <CopyMessageButton
                    content={msg.content}
                    messageId={msg.message_id}
                    copiedMessageId={copiedMessageId}
                    onCopy={onCopyMessage}
                  />
                  <span aria-label="送信時刻">{formatDateTime(msg.created_at)}</span>
                </div>
              </>
            )}
          </div>
        ))
      )}

      {/* Streaming state UI */}
      {isStreaming && (
        <div className="space-y-3">
          {streamingPlan.length > 0 && (
            <div className="flex justify-start min-w-0">
              <div className="max-w-2xl w-full min-w-0 rounded-xl border border-indigo-200 bg-indigo-50/60 px-3 py-2">
                <div className="text-[10px] font-bold uppercase tracking-wider text-indigo-800">
                  タスク計画 {streamingPlan.length}件
                </div>
                <ol className="mt-1 list-decimal space-y-0.5 pl-4 text-[11px] text-indigo-950">
                  {streamingPlan.map((entry, i) => (
                    <li key={`acp-plan-${i}`} className="[overflow-wrap:anywhere]">
                      {entry}
                    </li>
                  ))}
                </ol>
              </div>
            </div>
          )}

          {acpToolCalls.length > 0 && (
            <div className="flex justify-start min-w-0">
              <div className="max-w-2xl w-full min-w-0 space-y-1.5 rounded-xl border border-teal-200 bg-teal-50/50 px-3 py-2">
                <div className="text-[10px] font-bold uppercase tracking-wider text-teal-800">
                  ACP ツール実行 {acpToolCalls.length}件
                </div>
                {acpToolCalls.map((tc) => (
                  <StreamingToolCallCard key={tc.id} tc={tc} tone="teal" testId="acp-tool-call" />
                ))}
              </div>
            </div>
          )}

          {streamingThought && (
            <div className="flex justify-start min-w-0">
              <details className="max-w-2xl w-full min-w-0 rounded-xl border border-slate-300 bg-slate-100 px-3 py-2 text-xs text-slate-600">
                <summary className="cursor-pointer list-none text-[10px] font-bold uppercase tracking-wider text-slate-500">
                  思考プロセス
                </summary>
                <div className="mt-1 whitespace-pre-wrap [overflow-wrap:anywhere]">
                  {streamingThought}
                </div>
              </details>
            </div>
          )}

          {streamingText && (
            <div className="flex min-w-0 justify-start">
              <div className="max-w-2xl w-full min-w-0 overflow-hidden rounded-xl border border-teal-300 bg-slate-900 p-4 text-xs text-slate-100 shadow-sm">
                <div className="mb-1 text-[10px] font-semibold uppercase text-teal-300">
                  ACP Worker 応答（ストリーミング）
                </div>
                <MarkdownPreview content={streamingText} variant="dark" />
              </div>
            </div>
          )}

          {streamingToolCalls.length > 0 && (
            <div className="flex justify-start min-w-0">
              <div className="max-w-2xl w-full min-w-0 space-y-1.5 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2">
                <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
                  ツール呼び出し {streamingToolCalls.length}件
                </div>
                {streamingToolCalls.map((tc) => (
                  <StreamingToolCallCard key={tc.id} tc={tc} tone="slate" />
                ))}
              </div>
            </div>
          )}

          {activePhaseText && (
            <div className="flex justify-start">
              <div className="rounded-xl bg-white border border-slate-200 p-3 text-xs text-slate-700 shadow-sm flex items-center gap-2">
                <span className="inline-block h-2 w-2 animate-ping rounded-full bg-slate-600" />
                <span>AI Orchestrator: {activePhaseText}</span>
              </div>
            </div>
          )}

          {workerState.status === "running" && (
            <div className="flex justify-start">
              <div className="rounded-xl bg-slate-800 p-3 text-xs text-slate-200 font-mono flex items-center gap-2">
                <span className="inline-block h-2 w-2 animate-ping rounded-full bg-emerald-400" />
                Worker {workerState.attempt ? `(${workerState.attempt}回目)` : ""} ({workerState.backend}) 実行中...
              </div>
            </div>
          )}
        </div>
      )}

      {/* Queued messages waiting for the current turn to finish */}
      {queuedMessages.length > 0 && (
        <div className="space-y-2" data-testid="coding-queued-messages">
          {queuedMessages.map((item) => (
            <div key={item.queue_id} className="flex justify-end">
              <div className="max-w-xl rounded-2xl border border-dashed border-slate-300 bg-white px-4 py-2.5 text-xs text-slate-700 shadow-sm">
                <div className="mb-1 flex items-center gap-2">
                  <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold text-slate-500">
                    送信待ち
                  </span>
                  {item.slash_invocation?.name && (
                    <span className="rounded bg-slate-800 px-2 py-0.5 font-mono text-[10px] font-semibold text-slate-200">
                      /{item.slash_invocation.name}
                    </span>
                  )}
                  <button
                    type="button"
                    onClick={() => onRemoveQueuedMessage?.(item.queue_id)}
                    className="ml-auto inline-flex h-4 w-4 items-center justify-center rounded-full text-slate-400 hover:bg-slate-100 hover:text-slate-700 cursor-pointer"
                    aria-label="送信待ちメッセージを削除"
                  >
                    ×
                  </button>
                </div>
                {item.content && <div className="whitespace-pre-wrap">{item.content}</div>}
                {item.status === "error" && (
                  <div className="mt-1 flex items-center gap-2 text-[11px] text-rose-600">
                    <span data-testid="coding-queued-error">
                      {item.error_message ?? "送信に失敗しました。"}
                    </span>
                    <button
                      type="button"
                      onClick={() => onRetryQueuedMessage?.(item.queue_id)}
                      className="rounded border border-rose-300 px-1.5 py-0.5 font-semibold text-rose-700 hover:bg-rose-50 cursor-pointer"
                    >
                      再送
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Run status badge when run finishes with error or cancellation */}
      {currentRun && currentRun.status !== "running" && currentRun.status !== "completed" && (
        <div className="p-2 text-center text-xs">
          <span
            className={`inline-block rounded px-2 py-1 font-medium ${
              currentRun.status === "failed"
                ? "bg-red-100 text-red-800"
                : currentRun.status === "cancelled"
                ? "bg-slate-200 text-slate-700"
                : "bg-amber-100 text-amber-800"
            }`}
          >
            ステータス: {currentRun.status}
            {currentRun.error_message && ` (${currentRun.error_message})`}
          </span>
        </div>
      )}

      {/* In-Conversation Active Question Card (message flow bottom) */}
      {activeWaitingRun && activeWaitingRun.questions.length > 0 && (
        <WaitingRunQuestionCard
          key={activeWaitingRun.hitlRunId}
          hitlRunId={activeWaitingRun.hitlRunId}
          questions={activeWaitingRun.questions}
          onSubmit={(answers) => onSubmitWaitingAnswers(activeWaitingRun, answers)}
          onCancel={() => onCancelWaitingRun(activeWaitingRun)}
        />
      )}
      {activeWaitingRun && activeWaitingRun.questions.length === 0 && (
        <WaitingRunStatusPanel
          key={`${activeWaitingRun.hitlRunId}-status`}
          hitlRunId={activeWaitingRun.hitlRunId}
          status={activeWaitingRun.hitlStatus}
          errorMessage={activeWaitingRun.hitlError}
          onCancel={() => onCancelWaitingRun(activeWaitingRun)}
        />
      )}

      <div ref={messageEndRef} />
    </div>
  );
}
