import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, getMemory, reviewMemory, resolveMemory, deleteMemory } from "../../api/client";
import type { MemoryDetail } from "../../api/types";
import type { Memory } from "../../api/types";
import MemoryEditForm from "./MemoryEditForm";

export interface MemoryDetailPanelProps {
  memoryId: string;
  status: string;
  onChanged: (memory: MemoryDetail | null) => void;
  notify: (msg: string, kind?: "info" | "error") => void;
}

export default function MemoryDetailPanel({
  memoryId,
  status,
  onChanged,
  notify,
}: MemoryDetailPanelProps) {
  const [detail, setDetail] = useState<MemoryDetail | null>(null);
  const [targetDetails, setTargetDetails] = useState<Record<string, Memory>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [integratedContent, setIntegratedContent] = useState("");
  const [switchDate, setSwitchDate] = useState("");
  const fetchIdRef = useRef(0);

  useEffect(() => {
    const currentFetchId = ++fetchIdRef.current;
    setLoading(true);
    setError(null);
    setEditing(false);
    setTargetDetails({});
    getMemory(memoryId)
      .then((d) => {
        if (currentFetchId !== fetchIdRef.current) return;
        setDetail(d);
        onChanged(d);

        if (d.dedup_assessment?.integrated_content) {
          setIntegratedContent(d.dedup_assessment.integrated_content);
        } else {
          setIntegratedContent("");
        }
        setSwitchDate(d.valid_from || "");

        // Fetch target details for suggestions and assessments
        const targetIds = new Set<string>();
        (d.dedup_suggestions || []).forEach((s) => {
          if (s.target_memory_id) targetIds.add(s.target_memory_id);
        });
        if (d.dedup_assessment?.target_memory_id) {
          targetIds.add(d.dedup_assessment.target_memory_id);
        }

        Array.from(targetIds).forEach((tid) => {
          getMemory(tid)
            .then((td) => {
              if (currentFetchId !== fetchIdRef.current) return;
              setTargetDetails((prev) => ({ ...prev, [tid]: td }));
            })
            .catch((e) => {
              console.error(`Failed to fetch target memory ${tid}:`, e);
            });
        });
      })
      .catch((e) => {
        if (currentFetchId !== fetchIdRef.current) return;
        const msg = e instanceof ApiError ? e.message : "詳細取得に失敗しました";
        setError(msg);
        setDetail(null);
      })
      .finally(() => {
        if (currentFetchId === fetchIdRef.current) setLoading(false);
      });
  }, [memoryId, onChanged]);

  const handleUpdated = useCallback(
    (m: Memory) => {
      setDetail((prev) => (prev ? { ...prev, ...m } : prev));
      setEditing(false);
      onChanged({ ...(detail || (m as MemoryDetail)), ...m } as MemoryDetail);
    },
    [detail, onChanged],
  );

  async function handleDelete() {
    if (!window.confirm(`記憶 ${memoryId} を完全に削除しますか？この操作は取り消せません。`)) return;
    setIsSubmitting(true);
    try {
      await deleteMemory(memoryId);
      notify(`${memoryId} を削除しました`);
      onChanged(null);
      setDetail(null);
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "削除に失敗しました";
      notify(msg, "error");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function act(action: "approve" | "reject") {
    setIsSubmitting(true);
    try {
      await reviewMemory(memoryId, action);
      const updated = await getMemory(memoryId);
      setDetail(updated);
      notify(`${memoryId} を${action === "approve" ? "承認" : "却下"}しました`);
      onChanged(updated);
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "操作に失敗しました";
      notify(msg, "error");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleResolve(action: "keep_both" | "replace_existing", targetMemoryId: string) {
    await handleResolveWithParams(action, targetMemoryId);
  }

  async function handleResolveWithParams(
    action: "keep_both" | "replace_existing" | "merge_existing" | "supersede_existing",
    targetMemoryId: string,
    intContent?: string,
    swDate?: string
  ) {
    setIsSubmitting(true);
    try {
      await resolveMemory(memoryId, action, targetMemoryId, intContent, swDate);
      const updated = await getMemory(memoryId);
      setDetail(updated);
      let actionLabel = "";
      if (action === "keep_both") actionLabel = "両方保持";
      else if (action === "replace_existing") actionLabel = "既存を候補で更新";
      else if (action === "merge_existing") actionLabel = "マージ";
      else if (action === "supersede_existing") actionLabel = "後継として保存";

      notify(`${memoryId} を「${actionLabel}」で解決しました`);
      onChanged(updated);
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "操作に失敗しました";
      notify(msg, "error");
    } finally {
      setIsSubmitting(false);
    }
  }

  if (loading) {
    return <p className="p-6 text-sm text-slate-500">読み込み中…</p>;
  }
  if (error) {
    return <p className="p-6 text-sm text-red-600">{error}</p>;
  }
  if (!detail) {
    return null;
  }

  const hasSuggestions = (detail.dedup_suggestions || []).length > 0;

  return (
    <div className="flex h-full flex-col overflow-y-auto p-4">
      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
        <span className="rounded bg-slate-200 px-1">{detail.kind || "?"}</span>
        <span>status: {detail.status}</span>
        {detail.memory_key && <span>key: {detail.memory_key}</span>}
        {detail.stability && <span>stability: {detail.stability}</span>}
        {typeof detail.extraction_confidence === "number" && (
          <span>conf: {detail.extraction_confidence.toFixed(2)}</span>
        )}
      </div>
      <h2 className="text-sm font-semibold text-slate-700">本文</h2>
      <p className="mt-1 whitespace-pre-wrap text-sm">{detail.content}</p>

      {(detail.evidence || []).length > 0 && (
        <>
          <h2 className="mt-4 text-sm font-semibold text-slate-700">根拠</h2>
          <ul className="mt-1 space-y-1 text-sm">
            {detail.evidence.map((ev, i) => (
              <li key={i} className="rounded border border-slate-200 p-2">
                <div className="text-xs text-slate-500">{ev.path}</div>
                {ev.quote && <div className="mt-1">「{ev.quote}」</div>}
                {ev.observed_at && <div className="mt-1 text-xs text-slate-500">{ev.observed_at}</div>}
              </li>
            ))}
          </ul>
        </>
      )}

      {detail.status === "candidate" && detail.dedup_assessment && (
        <>
          <h2 className="mt-4 text-sm font-semibold text-slate-700">LLM重複・置換判定</h2>
          <div className="mt-1 space-y-2">
            {detail.dedup_assessment.decision === "merge" && (
              <div className="rounded border border-blue-200 bg-blue-50 p-3">
                <div className="font-semibold text-blue-900">
                  マージ提案 (Merge)
                  {typeof detail.dedup_assessment.similarity_score === "number" && ` (類似度: ${detail.dedup_assessment.similarity_score})`}
                </div>
                {detail.dedup_assessment.reason && (
                  <div className="text-xs text-blue-800 mt-1">理由: {detail.dedup_assessment.reason}</div>
                )}

                {detail.dedup_assessment.target_memory_id && targetDetails[detail.dedup_assessment.target_memory_id] ? (
                  <div className="mt-3 border-t border-blue-200 pt-3 text-xs">
                    <div className="font-semibold text-slate-700">既存記憶 ({detail.dedup_assessment.target_memory_id}):</div>
                    <div className="mt-1 whitespace-pre-wrap text-slate-800 bg-white p-2 rounded border border-blue-100">
                      {targetDetails[detail.dedup_assessment.target_memory_id].content}
                    </div>
                  </div>
                ) : (
                  detail.dedup_assessment.target_memory_id && <div className="text-xs text-slate-500 mt-2">既存記憶を読み込み中…</div>
                )}

                <div className="mt-3 text-xs">
                  <label className="font-semibold text-slate-700 block mb-1 font-semibold text-blue-900">統合本文の編集:</label>
                  <textarea
                    value={integratedContent}
                    onChange={(e) => setIntegratedContent(e.target.value)}
                    className="w-full rounded border border-blue-300 p-2 text-sm bg-white"
                    rows={3}
                  />
                </div>

                <div className="mt-3 flex gap-2 border-t border-blue-200 pt-3">
                  <button
                    type="button"
                    onClick={() => {
                      if (detail.dedup_assessment?.target_memory_id) {
                        handleResolveWithParams("merge_existing", detail.dedup_assessment.target_memory_id, integratedContent);
                      }
                    }}
                    disabled={isSubmitting || !integratedContent.trim() || !detail.dedup_assessment?.target_memory_id}
                    className="rounded bg-blue-600 px-3 py-1 text-xs text-white disabled:opacity-50"
                  >
                    マージ
                  </button>
                  <button
                    type="button"
                    onClick={() => act("approve")}
                    disabled={isSubmitting}
                    className="rounded bg-slate-600 px-3 py-1 text-xs text-white disabled:opacity-50"
                  >
                    新規として保存
                  </button>
                </div>
              </div>
            )}

            {detail.dedup_assessment.decision === "supersede" && (
              <div className="rounded border border-purple-200 bg-purple-50 p-3">
                <div className="font-semibold text-purple-900">
                  置換提案 (Supersede)
                </div>
                {detail.dedup_assessment.reason && (
                  <div className="text-xs text-purple-800 mt-1">理由: {detail.dedup_assessment.reason}</div>
                )}

                {detail.dedup_assessment.target_memory_id && targetDetails[detail.dedup_assessment.target_memory_id] ? (
                  <div className="mt-3 border-t border-purple-200 pt-3 text-xs">
                    <div className="font-semibold text-slate-700">置換される既存記憶 ({detail.dedup_assessment.target_memory_id}):</div>
                    <div className="mt-1 whitespace-pre-wrap text-slate-800 bg-white p-2 rounded border border-purple-100">
                      {targetDetails[detail.dedup_assessment.target_memory_id].content}
                    </div>
                  </div>
                ) : (
                  detail.dedup_assessment.target_memory_id && <div className="text-xs text-slate-500 mt-2">既存記憶を読み込み中…</div>
                )}

                <div className="mt-3 text-xs">
                  <label className="font-semibold text-slate-700 block mb-1 font-semibold text-purple-900">切替日 (YYYY-MM-DD):</label>
                  <input
                    type="text"
                    value={switchDate}
                    onChange={(e) => setSwitchDate(e.target.value)}
                    placeholder="YYYY-MM-DD"
                    className="rounded border border-purple-300 px-2 py-1 text-sm bg-white"
                  />
                </div>

                <div className="mt-3 flex gap-2 border-t border-purple-200 pt-3">
                  <button
                    type="button"
                    onClick={() => {
                      if (detail.dedup_assessment?.target_memory_id) {
                        handleResolveWithParams("supersede_existing", detail.dedup_assessment.target_memory_id, undefined, switchDate);
                      }
                    }}
                    disabled={isSubmitting || !/^\d{4}-\d{2}-\d{2}$/.test(switchDate) || !detail.dedup_assessment?.target_memory_id}
                    className="rounded bg-purple-600 px-3 py-1 text-xs text-white disabled:opacity-50"
                  >
                    後継として保存
                  </button>
                  <button
                    type="button"
                    onClick={() => act("approve")}
                    disabled={isSubmitting}
                    className="rounded bg-slate-600 px-3 py-1 text-xs text-white disabled:opacity-50"
                  >
                    新規として保存
                  </button>
                </div>
              </div>
            )}

            {detail.dedup_assessment.decision === "new" && (
              <div className="rounded border border-emerald-200 bg-emerald-50 p-3">
                <div className="font-semibold text-emerald-900">
                  新規判定 (New)
                </div>
                {detail.dedup_assessment.reason && (
                  <div className="text-xs text-emerald-800 mt-1">理由: {detail.dedup_assessment.reason}</div>
                )}
                <div className="text-xs text-emerald-700 mt-2 font-medium">
                  既存の記憶に重複・類似するものはなく、新しい情報であると判定されました。通常の承認フローで処理してください。
                </div>
              </div>
            )}

            {detail.dedup_assessment.decision === "failed" && (
              <div className="rounded border border-rose-200 bg-rose-50 p-3">
                <div className="font-semibold text-rose-900">
                  LLM判定に失敗。通常レビュー可能
                </div>
                <div className="text-xs text-rose-700 mt-2">
                  類似候補のLLM分類に失敗しました。通常の承認・却下フローで処理してください。
                </div>
              </div>
            )}
          </div>
        </>
      )}

      {!detail.dedup_assessment && hasSuggestions && (
        <>
          <h2 className="mt-4 text-sm font-semibold text-slate-700">重複・置換提案</h2>
          <ul className="mt-1 space-y-2 text-sm">
            {detail.dedup_suggestions.map((s, i) => (
              <li key={i} className="rounded border border-amber-200 bg-amber-50 p-3">
                <div className="font-semibold text-amber-900">
                  {s.relation === "supersedes" ? "置換候補" : "重複候補"}: {s.target_memory_id}
                  {typeof s.score === "number" && ` (類似度: ${s.score})`}
                </div>
                {s.reason && <div className="text-xs text-amber-800 mt-1">{s.reason}</div>}

                {/* Compare target memory */}
                {targetDetails[s.target_memory_id] ? (
                  <div className="mt-3 border-t border-amber-200 pt-3 text-xs">
                    <div className="font-semibold text-slate-700">比較対象の既存記憶:</div>
                    <div className="mt-1 whitespace-pre-wrap text-slate-800 bg-white p-2 rounded border border-amber-100">
                      {targetDetails[s.target_memory_id].content}
                    </div>
                    {targetDetails[s.target_memory_id].evidence && targetDetails[s.target_memory_id].evidence.length > 0 && (
                      <div className="mt-2 text-slate-600">
                        根拠: {targetDetails[s.target_memory_id].evidence.map(e => e.path).join(", ")}
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="text-xs text-slate-500 mt-2">比較用の既存記憶を取得中…</div>
                )}

                {/* Resolving action buttons inside card */}
                {detail.status === "candidate" && (
                  <div className="mt-3 flex gap-2 border-t border-amber-200 pt-3">
                    <button
                      type="button"
                      onClick={() => handleResolve("keep_both", s.target_memory_id)}
                      disabled={isSubmitting}
                      className="rounded bg-emerald-600 px-3 py-1 text-xs text-white disabled:opacity-50"
                    >
                      両方保持
                    </button>
                    <button
                      type="button"
                      onClick={() => handleResolve("replace_existing", s.target_memory_id)}
                      disabled={isSubmitting}
                      className="rounded bg-amber-600 px-3 py-1 text-xs text-white disabled:opacity-50"
                    >
                      既存を候補で更新
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </>
      )}

      {(detail.events || []).length > 0 && (
        <>
          <h2 className="mt-4 text-sm font-semibold text-slate-700">来歴</h2>
          <ul className="mt-1 space-y-1 text-xs text-slate-600">
            {detail.events.map((e) => (
              <li key={e.event_id} className="rounded border border-slate-200 p-2">
                <div>
                  {e.occurred_at} / {e.event_type} ({e.previous_status || "-"} → {e.new_status || "-"})
                </div>
                {e.reason && <div>reason: {e.reason}</div>}
                {e.changes && Object.keys(e.changes).length > 0 && (
                  <pre className="mt-1 whitespace-pre-wrap rounded bg-slate-50 p-1 text-[11px]">
                    {JSON.stringify(e.changes, null, 2)}
                  </pre>
                )}
              </li>
            ))}
          </ul>
        </>
      )}

      <div className="mt-6 space-y-3">
        {!editing ? (
          <div className="flex gap-2">
            {detail.status === "candidate" && (
              detail.dedup_assessment
                ? (detail.dedup_assessment.decision === "new" || detail.dedup_assessment.decision === "failed")
                : !hasSuggestions
            ) && (
              <>
                <button
                  type="button"
                  onClick={() => act("approve")}
                  disabled={isSubmitting}
                  className="rounded bg-emerald-600 px-3 py-1 text-sm text-white disabled:opacity-50"
                >
                  {isSubmitting ? "処理中…" : "承認"}
                </button>
                <button
                  type="button"
                  onClick={() => act("reject")}
                  disabled={isSubmitting}
                  className="rounded bg-rose-600 px-3 py-1 text-sm text-white disabled:opacity-50"
                >
                  {isSubmitting ? "処理中…" : "却下"}
                </button>
              </>
            )}
            <button
              type="button"
              onClick={() => setEditing(true)}
              disabled={isSubmitting}
              className="rounded bg-slate-900 px-3 py-1 text-sm text-white disabled:opacity-50"
            >
              編集して承認
            </button>
            <button
              type="button"
              onClick={handleDelete}
              disabled={isSubmitting}
              className="rounded bg-rose-800 px-3 py-1 text-sm text-white disabled:opacity-50"
            >
              削除
            </button>
          </div>
        ) : (
          <MemoryEditForm
            memory={detail}
            onUpdated={handleUpdated}
            notify={notify}
            onCancel={() => setEditing(false)}
          />
        )}
      </div>
    </div>
  );
}
