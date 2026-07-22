import { useEffect, useState } from "react";
import { apiGet } from "../../api/client";

interface ExecutionLogItem {
  id: string;
  kind: "command" | "llm";
  status: "running" | "succeeded" | "failed";
  name: string;
  started_at: string;
  finished_at?: string;
  summary?: string;
}

interface ExecutionChildLLMCall {
  call_id: string;
  provider?: string;
  model?: string;
  temperature?: number;
  max_tokens?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  finish_reason?: string;
  started_at: string;
  finished_at?: string;
  status: string;
  exception_type?: string;
  exception_message?: string;
}

interface CommandRunDetail {
  run_id: string;
  command: string;
  args_json?: string;
  started_at: string;
  finished_at?: string;
  status: string;
  summary?: string;
  exception_type?: string;
  exception_message?: string;
  traceback?: string;
  llm_calls: ExecutionChildLLMCall[];
}

interface LLMCallDetail {
  call_id: string;
  run_id?: string;
  provider?: string;
  model?: string;
  temperature?: number;
  max_tokens?: number;
  prompt?: string;
  response?: string;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  finish_reason?: string;
  started_at: string;
  finished_at?: string;
  status: string;
  exception_type?: string;
  exception_message?: string;
  traceback?: string;
}

export default function ExecutionLogPage() {
  const [logs, setLogs] = useState<ExecutionLogItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters state
  const [kind, setKind] = useState<string>("");
  const [status, setStatus] = useState<string>("");
  const [command, setCommand] = useState<string>("");
  const [fromDate, setFromDate] = useState<string>("");
  const [toDate, setToDate] = useState<string>("");

  // Pagination state
  const [page, setPage] = useState(1);
  const limit = 50;

  // Selection state
  const [selectedItem, setSelectedItem] = useState<{ id: string; kind: "command" | "llm" } | null>(null);
  const [cmdDetail, setCmdDetail] = useState<CommandRunDetail | null>(null);
  const [llmDetail, setLlmDetail] = useState<LLMCallDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [mobileDetailOpen, setMobileDetailOpen] = useState(false);

  // Fetch logs list
  const fetchLogs = async () => {
    setLoading(true);
    setError(null);
    try {
      const sp = new URLSearchParams();
      if (kind) sp.set("kind", kind);
      if (status) sp.set("status", status);
      if (command) sp.set("command", command);
      if (fromDate) sp.set("from", new Date(fromDate).toISOString());
      if (toDate) sp.set("to", new Date(toDate).toISOString());
      sp.set("limit", String(limit));
      sp.set("offset", String((page - 1) * limit));

      const res = await apiGet<{ items: ExecutionLogItem[]; total: number }>(
        `/api/v1/execution-logs?${sp.toString()}`
      );
      setLogs(res.items);
      setTotal(res.total);
    } catch (e: any) {
      setError(e.message || "ログ一覧の取得に失敗しました");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchLogs();
  }, [kind, status, command, fromDate, toDate, page]);

  // Fetch detail when selection changes
  useEffect(() => {
    if (!selectedItem) {
      setCmdDetail(null);
      setLlmDetail(null);
      return;
    }

    const fetchDetail = async () => {
      setDetailLoading(true);
      setDetailError(null);
      setCmdDetail(null);
      setLlmDetail(null);

      try {
        if (selectedItem.kind === "command") {
          const detail = await apiGet<CommandRunDetail>(
            `/api/v1/execution-logs/commands/${selectedItem.id}`
          );
          setCmdDetail(detail);
        } else {
          const detail = await apiGet<LLMCallDetail>(
            `/api/v1/execution-logs/llm/${selectedItem.id}`
          );
          setLlmDetail(detail);
        }
      } catch (e: any) {
        setDetailError(e.message || "詳細データの取得に失敗しました");
      } finally {
        setDetailLoading(false);
      }
    };

    fetchDetail();
  }, [selectedItem]);

  const handleRowClick = (item: ExecutionLogItem) => {
    setSelectedItem({ id: item.id, kind: item.kind });
    setMobileDetailOpen(true);
  };

  const handleChildLLMClick = (callId: string) => {
    setSelectedItem({ id: callId, kind: "llm" });
    setMobileDetailOpen(true);
  };

  const formatLocalTime = (isoString: string | undefined) => {
    if (!isoString) return "-";
    try {
      const date = new Date(isoString);
      return date.toLocaleString();
    } catch (_) {
      return isoString;
    }
  };

  const getStatusBadgeClass = (stat: string) => {
    switch (stat) {
      case "succeeded":
        return "bg-emerald-50 text-emerald-700 border-emerald-200";
      case "failed":
        return "bg-rose-50 text-red-700 border-rose-200";
      case "running":
        return "bg-amber-50 text-amber-700 border-amber-200";
      default:
        return "bg-slate-50 text-slate-700 border-slate-200";
    }
  };

  const getKindBadgeClass = (k: string) => {
    if (k === "command") {
      return "bg-indigo-50 text-indigo-700 border-indigo-200";
    }
    return "bg-sky-50 text-sky-700 border-sky-200";
  };

  const totalPages = Math.ceil(total / limit) || 1;

  return (
    <div className="flex h-full flex-col overflow-hidden bg-slate-50">
      {/* Header */}
      <div className="shrink-0 border-b border-slate-200 bg-white px-6 py-4 shadow-sm">
        <h1 className="text-xl font-bold text-slate-900">実行ログ & LLMコール履歴</h1>
        <p className="text-xs text-slate-500 mt-1">過去30日間の CLI 実行ログおよび LLM コールの詳細履歴を閲覧できます（閲覧専用）</p>
      </div>

      {/* Filter and Filters Bar */}
      <div className="shrink-0 bg-white border-b border-slate-200 px-6 py-3 flex flex-wrap gap-4 items-center">
        {/* Search */}
        <div className="flex flex-col min-w-[200px]">
          <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1">コマンド・モデル検索</label>
          <input
            type="text"
            placeholder="e.g. make_target, gpt-4"
            value={command}
            onChange={(e) => {
              setCommand(e.target.value);
              setPage(1);
            }}
            className="rounded border border-slate-300 px-3 py-1 text-sm focus:border-slate-500 focus:outline-none"
          />
        </div>

        {/* Kind */}
        <div className="flex flex-col">
          <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1">種別</label>
          <select
            value={kind}
            onChange={(e) => {
              setKind(e.target.value);
              setPage(1);
            }}
            className="rounded border border-slate-300 px-2 py-1 text-sm bg-white focus:border-slate-500 focus:outline-none"
          >
            <option value="">すべて</option>
            <option value="command">コマンド実行</option>
            <option value="llm">LLM呼び出し</option>
          </select>
        </div>

        {/* Status */}
        <div className="flex flex-col">
          <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1">ステータス</label>
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setPage(1);
            }}
            className="rounded border border-slate-300 px-2 py-1 text-sm bg-white focus:border-slate-500 focus:outline-none"
          >
            <option value="">すべて</option>
            <option value="running">実行中</option>
            <option value="succeeded">成功</option>
            <option value="failed">失敗</option>
          </select>
        </div>

        {/* Date From */}
        <div className="flex flex-col">
          <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1">開始日時 (From)</label>
          <input
            type="date"
            value={fromDate}
            onChange={(e) => {
              setFromDate(e.target.value);
              setPage(1);
            }}
            className="rounded border border-slate-300 px-2 py-1 text-sm bg-white focus:border-slate-500 focus:outline-none"
          />
        </div>

        {/* Date To */}
        <div className="flex flex-col">
          <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1">終了日時 (To)</label>
          <input
            type="date"
            value={toDate}
            onChange={(e) => {
              setToDate(e.target.value);
              setPage(1);
            }}
            className="rounded border border-slate-300 px-2 py-1 text-sm bg-white focus:border-slate-500 focus:outline-none"
          />
        </div>

        {/* Clear Filters */}
        {(kind || status || command || fromDate || toDate) && (
          <button
            type="button"
            onClick={() => {
              setKind("");
              setStatus("");
              setCommand("");
              setFromDate("");
              setToDate("");
              setPage(1);
            }}
            className="text-sm text-slate-600 hover:text-slate-900 border border-slate-300 px-3 py-1 rounded hover:bg-slate-50 mt-5 transition"
          >
            クリア
          </button>
        )}
      </div>

      {/* Main Workspace */}
      <div className="flex-1 flex overflow-hidden min-h-0">
        {/* Left Side: Logs List */}
        <div className={`flex-col border-r border-slate-200 overflow-y-auto min-w-[320px] ${
          mobileDetailOpen ? 'hidden' : 'flex-1 flex'
        } md:flex-1 md:flex md:flex-col`}>
          {loading ? (
            <div className="p-8 text-center text-slate-500 text-sm">読み込み中…</div>
          ) : error ? (
            <div className="p-8 text-center text-red-500 text-sm font-semibold">{error}</div>
          ) : logs.length === 0 ? (
            <div className="p-8 text-center text-slate-500 text-sm">該当するログがありません。</div>
          ) : (
            <div className="flex-1 flex flex-col justify-between">
              {/* Table/List */}
              <div className="divide-y divide-slate-200">
                {logs.map((item) => {
                  const isSelected = selectedItem?.id === item.id;
                  return (
                    <button
                      key={item.id}
                      onClick={() => handleRowClick(item)}
                      className={`w-full p-4 text-left transition flex flex-col gap-2 hover:bg-slate-100 ${
                        isSelected ? "bg-slate-200 border-l-4 border-slate-800" : "bg-white"
                      }`}
                    >
                      <div className="flex justify-between items-start">
                        <span className="text-xs font-semibold text-slate-500">
                          {formatLocalTime(item.started_at)}
                        </span>
                        <div className="flex gap-2">
                          <span className={`text-[10px] uppercase font-bold border px-1.5 py-0.5 rounded ${getKindBadgeClass(item.kind)}`}>
                            {item.kind === "command" ? "Command" : "LLM"}
                          </span>
                          <span className={`text-[10px] uppercase font-bold border px-1.5 py-0.5 rounded ${getStatusBadgeClass(item.status)}`}>
                            {item.status}
                          </span>
                        </div>
                      </div>
                      <div className="font-semibold text-slate-800 break-all text-sm">
                        {item.name}
                      </div>
                      {item.summary && (
                        <div className="text-xs text-slate-500 truncate max-w-lg break-all">
                          {item.summary}
                        </div>
                      )}
                    </button>
                  );
                })}
              </div>

              {/* Pagination bar */}
              <div className="shrink-0 border-t border-slate-200 bg-white px-4 py-3 flex items-center justify-between">
                <span className="text-xs text-slate-600 font-semibold">
                  全 {total} 件中 {(page - 1) * limit + 1}-{Math.min(page * limit, total)} 件
                </span>
                <div className="flex gap-2">
                  <button
                    type="button"
                    disabled={page === 1}
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    className="px-3 py-1 border border-slate-300 rounded text-xs bg-white text-slate-700 disabled:opacity-50 enabled:hover:bg-slate-50 transition"
                  >
                    前へ
                  </button>
                  <span className="text-xs self-center px-1 text-slate-700 font-bold">
                    {page} / {totalPages}
                  </span>
                  <button
                    type="button"
                    disabled={page >= totalPages}
                    onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                    className="px-3 py-1 border border-slate-300 rounded text-xs bg-white text-slate-700 disabled:opacity-50 enabled:hover:bg-slate-50 transition"
                  >
                    次へ
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Right Side: Selected Detail Panel */}
        <div className={`flex-col bg-white ${
          mobileDetailOpen ? 'flex flex-1' : 'hidden'
        } md:w-1/2 md:flex md:flex-col`}>
          {/* Mobile back button */}
          <div className="flex items-center gap-2 border-b border-slate-200 p-3 md:hidden">
            <button
              type="button"
              onClick={() => setMobileDetailOpen(false)}
              aria-label="一覧に戻る"
              className="rounded px-2 py-1 text-sm text-slate-600 hover:bg-slate-100"
            >
              ← 一覧
            </button>
            <span className="truncate text-sm font-semibold text-slate-700">
              実行ログ詳細
            </span>
          </div>
          <div className="flex-1 overflow-y-auto min-w-[400px]">
          {!selectedItem ? (
            <div className="flex items-center justify-center text-slate-400 text-sm italic p-6 h-full">
              左側の一覧からログを選択すると詳細が表示されます。
            </div>
          ) : detailLoading ? (
            <div className="flex items-center justify-center text-slate-500 text-sm p-6 h-full">
              詳細データを読み込み中…
            </div>
          ) : detailError ? (
            <div className="flex items-center justify-center text-red-500 text-sm font-semibold p-6 h-full">
              {detailError}
            </div>
          ) : cmdDetail ? (
            /* COMMAND RUN DETAIL VIEW */
            <div className="p-6 space-y-6">
              {/* Head */}
              <div className="border-b border-slate-200 pb-4">
                <div className="flex justify-between items-center mb-2">
                  <span className="text-xs font-bold uppercase tracking-wider text-indigo-600 bg-indigo-50 border border-indigo-200 px-2 py-0.5 rounded">
                    Command Run
                  </span>
                  <span className={`text-xs font-bold uppercase tracking-wider border px-2 py-0.5 rounded ${getStatusBadgeClass(cmdDetail.status)}`}>
                    {cmdDetail.status}
                  </span>
                </div>
                <h2 className="text-lg font-extrabold text-slate-800 break-all">{cmdDetail.command}</h2>
                <div className="text-xs text-slate-500 mt-2 flex flex-col gap-1">
                  <div>開始日時: {formatLocalTime(cmdDetail.started_at)}</div>
                  {cmdDetail.finished_at && <div>終了日時: {formatLocalTime(cmdDetail.finished_at)}</div>}
                  <div>ID: {cmdDetail.run_id}</div>
                </div>
              </div>

              {/* Arguments JSON */}
              {cmdDetail.args_json && (
                <div>
                  <h3 className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-2">実行引数 (Args)</h3>
                  <pre className="bg-slate-50 border border-slate-200 text-xs p-3 rounded font-mono overflow-x-auto max-h-48 whitespace-pre">
                    {(() => {
                      try {
                        return JSON.stringify(JSON.parse(cmdDetail.args_json), null, 2);
                      } catch (_) {
                        return cmdDetail.args_json;
                      }
                    })()}
                  </pre>
                </div>
              )}

              {/* Summary */}
              {cmdDetail.summary && (
                <div>
                  <h3 className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-2">結果要約</h3>
                  <div className="bg-slate-50 border border-slate-200 text-slate-800 text-sm p-4 rounded break-all whitespace-pre-wrap">
                    {cmdDetail.summary}
                  </div>
                </div>
              )}

              {/* Exceptions (If Failed) */}
              {cmdDetail.status === "failed" && (
                <div className="border border-red-200 rounded overflow-hidden">
                  <div className="bg-red-50 text-red-800 px-4 py-2 border-b border-red-200 font-bold text-sm">
                    例外情報 ({cmdDetail.exception_type})
                  </div>
                  <div className="p-4 space-y-4">
                    <div className="text-xs font-semibold text-slate-700 bg-rose-50/50 p-2 rounded break-all">
                      {cmdDetail.exception_message}
                    </div>
                    {cmdDetail.traceback && (
                      <div>
                        <div className="text-xs font-bold text-slate-500 mb-1">トレースバック:</div>
                        <pre className="bg-slate-900 text-rose-300 text-[10px] p-3 rounded font-mono overflow-x-auto max-h-96 whitespace-pre leading-relaxed">
                          {cmdDetail.traceback}
                        </pre>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Associated Child LLM Calls */}
              <div>
                <h3 className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-3">
                  紐づく LLM 呼び出し ({cmdDetail.llm_calls.length})
                </h3>
                {cmdDetail.llm_calls.length === 0 ? (
                  <p className="text-sm text-slate-400 italic">このコマンドでは LLM 呼び出しは行われませんでした。</p>
                ) : (
                  <div className="border border-slate-200 rounded divide-y divide-slate-200 overflow-hidden">
                    {cmdDetail.llm_calls.map((call) => (
                      <div
                        key={call.call_id}
                        onClick={() => handleChildLLMClick(call.call_id)}
                        className="p-3 hover:bg-slate-50 cursor-pointer flex justify-between items-center transition"
                      >
                        <div className="min-w-0 flex-1 pr-4">
                          <div className="font-semibold text-slate-700 truncate text-xs">
                            {call.provider} / {call.model}
                          </div>
                          <div className="text-[10px] text-slate-500 mt-1 flex gap-2">
                            <span>{formatLocalTime(call.started_at)}</span>
                            {call.total_tokens !== undefined && (
                              <span className="font-medium text-slate-600">
                                {call.total_tokens} tokens
                              </span>
                            )}
                          </div>
                        </div>
                        <span className={`text-[9px] uppercase font-bold border px-1.5 py-0.5 rounded shrink-0 ${getStatusBadgeClass(call.status)}`}>
                          {call.status}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ) : llmDetail ? (
            /* LLM CALL DETAIL VIEW */
            <div className="p-6 space-y-6">
              {/* Head */}
              <div className="border-b border-slate-200 pb-4">
                <div className="flex justify-between items-center mb-2">
                  <div className="flex gap-2">
                    {llmDetail.run_id && (
                      <button
                        type="button"
                        onClick={() => setSelectedItem({ id: llmDetail.run_id!, kind: "command" })}
                        className="text-xs font-bold text-slate-500 bg-slate-100 hover:bg-slate-200 border border-slate-300 px-2 py-0.5 rounded transition"
                      >
                        ← 親コマンドへ
                      </button>
                    )}
                    <span className="text-xs font-bold uppercase tracking-wider text-sky-600 bg-sky-50 border border-sky-200 px-2 py-0.5 rounded">
                      LLM Call Log
                    </span>
                  </div>
                  <span className={`text-xs font-bold uppercase tracking-wider border px-2 py-0.5 rounded ${getStatusBadgeClass(llmDetail.status)}`}>
                    {llmDetail.status}
                  </span>
                </div>
                <h2 className="text-lg font-extrabold text-slate-800 break-all">{llmDetail.provider} / {llmDetail.model}</h2>
                <div className="text-xs text-slate-500 mt-2 flex flex-col gap-1">
                  <div>開始日時: {formatLocalTime(llmDetail.started_at)}</div>
                  {llmDetail.finished_at && <div>終了日時: {formatLocalTime(llmDetail.finished_at)}</div>}
                  <div>ID: {llmDetail.call_id}</div>
                </div>
              </div>

              {/* Call Settings */}
              <div className="grid grid-cols-3 gap-4 bg-slate-50 border border-slate-200 p-3 rounded text-center">
                <div>
                  <div className="text-[10px] font-bold text-slate-400 uppercase">Temperature</div>
                  <div className="text-sm font-semibold text-slate-700">{llmDetail.temperature !== undefined ? llmDetail.temperature : "-"}</div>
                </div>
                <div>
                  <div className="text-[10px] font-bold text-slate-400 uppercase">Max Tokens</div>
                  <div className="text-sm font-semibold text-slate-700">{llmDetail.max_tokens !== undefined ? llmDetail.max_tokens : "-"}</div>
                </div>
                <div>
                  <div className="text-[10px] font-bold text-slate-400 uppercase">Finish Reason</div>
                  <div className={`text-sm font-bold ${llmDetail.finish_reason === "length" ? "text-amber-600" : "text-slate-600"}`}>
                    {llmDetail.finish_reason || "-"}
                  </div>
                </div>
              </div>

              {/* Token Usage */}
              {llmDetail.status === "succeeded" && (
                <div>
                  <h3 className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-2">消費トークン量</h3>
                  <div className="grid grid-cols-3 gap-2 text-center">
                    <div className="bg-slate-50/50 p-2 border border-slate-100 rounded">
                      <div className="text-[9px] text-slate-400 uppercase">Input (Prompt)</div>
                      <div className="text-sm font-semibold text-slate-700">{llmDetail.prompt_tokens !== null && llmDetail.prompt_tokens !== undefined ? llmDetail.prompt_tokens : "-"}</div>
                    </div>
                    <div className="bg-slate-50/50 p-2 border border-slate-100 rounded">
                      <div className="text-[9px] text-slate-400 uppercase">Output (Completion)</div>
                      <div className="text-sm font-semibold text-slate-700">{llmDetail.completion_tokens !== null && llmDetail.completion_tokens !== undefined ? llmDetail.completion_tokens : "-"}</div>
                    </div>
                    <div className="bg-slate-50/50 p-2 border border-slate-100 rounded">
                      <div className="text-[9px] text-slate-400 uppercase">Total</div>
                      <div className="text-sm font-bold text-slate-800">{llmDetail.total_tokens !== null && llmDetail.total_tokens !== undefined ? llmDetail.total_tokens : "-"}</div>
                    </div>
                  </div>
                </div>
              )}

              {/* Error section */}
              {llmDetail.status === "failed" && (
                <div className="border border-red-200 rounded overflow-hidden">
                  <div className="bg-red-50 text-red-800 px-4 py-2 border-b border-red-200 font-bold text-sm">
                    エラー情報 ({llmDetail.exception_type})
                  </div>
                  <div className="p-4 space-y-3">
                    <div className="text-xs font-semibold text-slate-700 bg-rose-50/50 p-2 rounded break-all">
                      {llmDetail.exception_message}
                    </div>
                    {llmDetail.traceback && (
                      <pre className="bg-slate-950 text-rose-300 text-[10px] p-3 rounded font-mono overflow-x-auto max-h-64 whitespace-pre">
                        {llmDetail.traceback}
                      </pre>
                    )}
                  </div>
                </div>
              )}

              {/* Prompt Accordion */}
              {llmDetail.prompt && (
                <details className="border border-slate-200 rounded bg-slate-50 overflow-hidden group" open>
                  <summary className="font-bold text-xs text-slate-600 uppercase tracking-wider px-4 py-3 cursor-pointer select-none bg-slate-100 hover:bg-slate-200 transition list-none flex justify-between items-center">
                    <span>プロンプト全文 (Prompt)</span>
                    <span className="text-[10px] text-slate-400 group-open:rotate-180 transition-transform">▼</span>
                  </summary>
                  <div className="p-4 bg-white border-t border-slate-200">
                    <pre className="text-xs text-slate-800 font-mono whitespace-pre-wrap break-all leading-relaxed leading-5">
                      {llmDetail.prompt}
                    </pre>
                  </div>
                </details>
              )}

              {/* Response Accordion */}
              {llmDetail.response && (
                <details className="border border-slate-200 rounded bg-slate-50 overflow-hidden group" open>
                  <summary className="font-bold text-xs text-slate-600 uppercase tracking-wider px-4 py-3 cursor-pointer select-none bg-slate-100 hover:bg-slate-200 transition list-none flex justify-between items-center">
                    <span>応答全文 (Response)</span>
                    <span className="text-[10px] text-slate-400 group-open:rotate-180 transition-transform">▼</span>
                  </summary>
                  <div className="p-4 bg-white border-t border-slate-200">
                    <pre className="text-xs text-slate-800 font-mono whitespace-pre-wrap break-all leading-relaxed leading-5">
                      {llmDetail.response}
                    </pre>
                  </div>
                </details>
              )}
            </div>
          ) : null}
        </div>
        </div>
      </div>
    </div>
  );
}
