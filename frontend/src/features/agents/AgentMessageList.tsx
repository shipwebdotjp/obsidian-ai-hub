import React, { useMemo, type MutableRefObject, type RefObject } from "react";
import { Link } from "react-router-dom";
import type {
  AgentLiveToolCall,
  AgentMessage,
  AgentRun,
  AgentToolCall,
  AskUserAnswerRound,
} from "../../api/types";
import { ROUTES } from "../../constants/routes";
import MarkdownPreview from "../../components/MarkdownPreview";
import { CopyMessageButton } from "../../components/CopyMessageButton";
import {
  WaitingRunQuestionCard,
  WaitingRunStatusPanel,
  type ActiveWaitingRun,
} from "../../components/InConversationQuestionCard";
import { AnsweredRequirementCard } from "../../components/AnsweredRequirementCard";
import { formatDateTime } from "../../utils/date";
import {
  buildRunsByMessageId,
  buildRunsByUserMessageId,
  getLiveStatusClass,
  getLiveStatusLabel,
  truncateLiveResult,
} from "./agentViewUtils";

interface AgentMessageListProps {
  messages: AgentMessage[];
  isStreaming: boolean;
  runs: AgentRun[];
  answerHistory: AskUserAnswerRound[];
  activeWaitingRun: ActiveWaitingRun | null;
  streamingToolCalls: AgentLiveToolCall[];
  displayedStreamingPhase: "thinking" | "tool_preparing" | "tool_running" | null;
  streamingIteration: number | null;
  streamingText: string;
  hitlLinks: string[];
  chatError: string | null;
  copiedMessageId: string | null;
  onCopyMessage: (content: string, messageId: string) => void;
  onSubmitWaitingAnswers: (
    waiting: ActiveWaitingRun,
    answers: Record<string, { value: string; comment?: string }>,
  ) => Promise<void>;
  onCancelWaitingRun: (waiting: ActiveWaitingRun) => Promise<void>;
  messageRefs: MutableRefObject<Map<string, HTMLDivElement>>;
  messagesEndRef: RefObject<HTMLDivElement>;
}

/** 会話メッセージ一覧とストリーミング・待機中質問・リンク・エラー表示。 */
export function AgentMessageList({
  messages,
  isStreaming,
  runs,
  answerHistory,
  activeWaitingRun,
  streamingToolCalls,
  displayedStreamingPhase,
  streamingIteration,
  streamingText,
  hitlLinks,
  chatError,
  copiedMessageId,
  onCopyMessage,
  onSubmitWaitingAnswers,
  onCancelWaitingRun,
  messageRefs,
  messagesEndRef,
}: AgentMessageListProps) {
  // Memoize assistant_message_id -> run & user_message_id -> run
  const runsByMessageId = useMemo(() => buildRunsByMessageId(runs), [runs]);
  const runsByUserMessageId = useMemo(() => buildRunsByUserMessageId(runs), [runs]);

  return (
    <div className="flex-1 overflow-y-auto p-4 space-y-4">
      {messages.length === 0 && !isStreaming ? (
        <div className="flex h-full items-center justify-center text-xs text-slate-400">
          メッセージを入力して会話を開始してください。
        </div>
      ) : (
        messages.map((m) => {
          const relatedRun =
            m.role === "assistant"
              ? runsByMessageId.get(m.message_id) ?? null
              : null;
          const toolCalls: AgentToolCall[] = relatedRun?.tool_calls || [];
          const isAssistant = m.role === "assistant";
          const userRounds = m.role === "user"
            ? answerHistory.filter((h) => h.user_message_id === m.message_id)
            : [];
          return (
            <React.Fragment key={m.message_id}>
              <div
                ref={(element) => {
                  if (element) {
                    messageRefs.current.set(m.message_id, element);
                  } else {
                    messageRefs.current.delete(m.message_id);
                  }
                }}
                data-message-id={m.message_id}
                className="space-y-1"
              >
              {/* Tool calls (chronological: before the assistant's final response) */}
              {toolCalls.length > 0 && (
                <div className="flex justify-start">
                  <div className="max-w-xl w-full space-y-1.5 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2">
                    <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
                      ツール呼び出し {toolCalls.length}件
                    </div>
                    {toolCalls.map((tc) => (
                      <details
                        key={tc.id}
                        className="rounded border border-slate-200 bg-white text-xs overflow-hidden group"
                      >
                        <summary className="cursor-pointer list-none flex items-center justify-between gap-2 px-3 py-1.5 bg-slate-50 hover:bg-slate-100">
                          <span className="flex items-center gap-1.5 min-w-0">
                            <span className="font-semibold truncate text-slate-800">{tc.tool_name}</span>
                            <span
                              className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold border ${
                                tc.status === "succeeded"
                                  ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                                  : "bg-rose-50 text-rose-700 border-rose-200"
                              }`}
                            >
                              {tc.status === "succeeded" ? "成功" : "失敗"}
                            </span>
                            {tc.hitl_run_id && (
                              <span className="text-[10px] text-amber-700 bg-amber-50 border border-amber-200 rounded px-1 truncate">
                                HITL: {tc.hitl_run_id}
                              </span>
                            )}
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
              )}
              {/* Message bubble (user: plain text, assistant: Markdown) */}
              <div
                className={`flex ${
                  m.role === "user" ? "justify-end" : "justify-start"
                }`}
              >
                <div
                  className={`max-w-xl rounded-2xl px-4 py-2.5 text-xs shadow-sm ${
                    isAssistant
                      ? "bg-white border border-slate-200 text-slate-800"
                      : "bg-slate-900 text-white whitespace-pre-wrap"
                  }`}
                >
                  {isAssistant ? (
                    <MarkdownPreview content={m.content} />
                  ) : (
                    <div className="space-y-2">
                      {(() => {
                        const userRun = runsByUserMessageId.get(m.message_id);
                        if (userRun?.slash_invocation?.name) {
                          return (
                            <div className="mb-1">
                              <span
                                className="inline-flex items-center gap-1 rounded bg-slate-800 px-2 py-0.5 font-mono text-[10px] font-semibold text-slate-200"
                                data-testid={`skill-badge-${m.message_id}`}
                              >
                                /{userRun.slash_invocation.name}
                              </span>
                            </div>
                          );
                        }
                        return null;
                      })()}
                      {m.attachments && m.attachments.length > 0 && (
                        <div className="flex flex-wrap gap-1.5">
                          {m.attachments.map((att, attIndex) => (
                            <img
                              key={`${att.name}-${attIndex}`}
                              src={`data:${att.mime_type};base64,${att.data}`}
                              alt={att.name}
                              className="max-h-40 max-w-[12rem] rounded border border-slate-700 object-cover"
                            />
                          ))}
                        </div>
                      )}
                      {m.content && <div>{m.content}</div>}
                    </div>
                  )}
                </div>
              </div>
              {/* Footer: copy button + timestamp */}
              <div
                className={`flex items-center gap-2 text-[10px] text-slate-400 ${
                  m.role === "user" ? "justify-end" : "justify-start"
                }`}
              >
                <CopyMessageButton
                  content={m.content}
                  messageId={m.message_id}
                  copiedMessageId={copiedMessageId}
                  onCopy={onCopyMessage}
                />
                <span aria-label="送信時刻">{formatDateTime(m.created_at)}</span>
              </div>
              </div>
              {userRounds.map((round) => (
                <AnsweredRequirementCard key={`${round.hitl_run_id}-${round.tool_call_id}`} round={round} />
              ))}
            </React.Fragment>
          );
        })
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

      {/* Live Streaming Response Chunk */}
      {isStreaming && (
        <div className="space-y-3">
          {(displayedStreamingPhase || streamingToolCalls.length > 0) && (
            <div className="flex justify-start">
              <div className="max-w-xl w-full space-y-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2">
                {displayedStreamingPhase === "thinking" && streamingToolCalls.length === 0 && (
                  <div className="flex items-center gap-2 text-xs text-slate-600">
                    <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-blue-500" />
                    LLMが考え中…{streamingIteration ? ` (iter ${streamingIteration})` : ""}
                  </div>
                )}
                {displayedStreamingPhase === "thinking" && streamingToolCalls.length > 0 && (
                  <div className="flex items-center gap-2 text-[11px] text-slate-500">
                    <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-blue-500" />
                    ツール結果を踏まえて次の応答を生成中…
                  </div>
                )}
                {displayedStreamingPhase === "tool_preparing" && (
                  <div className="flex items-center gap-2 text-xs text-blue-700">
                    <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-blue-500" />
                    ツール呼び出しを準備中…
                  </div>
                )}
                {displayedStreamingPhase === "tool_running" && (
                  <div className="flex items-center gap-2 text-xs text-amber-700">
                    <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-amber-500" />
                    ツールを実行中…
                  </div>
                )}
                {streamingToolCalls.length > 0 && (
                  <>
                    <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
                      ツール呼び出し {streamingToolCalls.length}件
                    </div>
                    {streamingToolCalls.map((tc) => (
                      <details
                        key={tc.id}
                        className="rounded border border-slate-200 bg-white text-xs overflow-hidden group"
                      >
                        <summary className="cursor-pointer list-none flex items-center justify-between gap-2 px-3 py-1.5 bg-slate-50 hover:bg-slate-100">
                          <span className="flex items-center gap-1.5 min-w-0">
                            <span className="font-semibold truncate text-slate-800">{tc.tool_name}</span>
                            <span
                              className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold border ${getLiveStatusClass(tc.status)}`}
                            >
                              {getLiveStatusLabel(tc.status)}
                            </span>
                            {tc.hitl_run_id && (
                              <span className="text-[10px] text-amber-700 bg-amber-50 border border-amber-200 rounded px-1 truncate">
                                HITL: {tc.hitl_run_id}
                              </span>
                            )}
                          </span>
                          <span className="text-[10px] text-slate-400 group-open:rotate-180 transition-transform shrink-0">▼</span>
                        </summary>
                        <div className="border-t border-slate-200 p-3 space-y-2 bg-white">
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
                                    {truncateLiveResult(tc.result) || "-"}
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
                    ))}
                  </>
                )}
                {streamingToolCalls.length === 0 && displayedStreamingPhase === "tool_preparing" && (
                  <div className="text-[11px] text-slate-400">ツール呼び出しを準備中…</div>
                )}
              </div>
            </div>
          )}
          <div className="flex justify-start">
            <div className="max-w-xl rounded-2xl border border-slate-200 bg-white px-4 py-2.5 text-xs text-slate-800 shadow-sm">
              {streamingText ? (
                <MarkdownPreview content={streamingText} />
              ) : displayedStreamingPhase === "thinking" ? (
                <span className="flex items-center gap-2 text-slate-500">
                  <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-slate-300 border-t-slate-600" />
                  考え中…
                </span>
              ) : displayedStreamingPhase === "tool_preparing" ? (
                <span className="text-slate-500">ツール呼び出しを準備しています…</span>
              ) : displayedStreamingPhase === "tool_running" ? (
                <span className="text-slate-500">ツールの実行結果を待っています…</span>
              ) : (
                "考え中…"
              )}
            </div>
          </div>
        </div>
      )}

      {/* HITL Run Links Alert */}
      {hitlLinks.length > 0 && (
        <div className="rounded-lg border border-yellow-200 bg-yellow-50 p-3 text-xs text-yellow-800">
          <div className="font-semibold mb-1">
            承認待ちの登録申請が作成されました
          </div>
          <p className="mb-2 text-[11px]">
            エージェントがカレンダー／リマインダー作成提案を登録しました。確認待ち画面で確認・承認を行ってください。
          </p>
          <Link
            to={ROUTES.HITL}
            className="inline-flex items-center gap-1 font-semibold text-yellow-900 underline hover:text-yellow-700 cursor-pointer"
          >
            → 確認待ち画面へ移動する
          </Link>
        </div>
      )}

      {/* Chat Error */}
      {chatError && (
        <div className="rounded-lg bg-red-50 p-3 text-xs text-red-600">
          {chatError}
        </div>
      )}

      <div ref={messagesEndRef} />
    </div>
  );
}
