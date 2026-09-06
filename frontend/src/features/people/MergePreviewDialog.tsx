import React, { forwardRef } from "react";
import { Person } from "../../api/types";
import { PeopleMergePreviewResponse } from "./types";

interface MergePreviewDialogProps {
  mergeFromPerson: Person | null;
  mergeToPerson: Person | null;
  previewLoading: boolean;
  previewData: PeopleMergePreviewResponse | null;
  mergeModalError: string | null;
  loading: boolean;
  onCloseModal: () => void;
  onExecuteMerge: () => void;
}

const MergePreviewDialog = forwardRef<HTMLDialogElement, MergePreviewDialogProps>(
  (
    {
      mergeFromPerson,
      mergeToPerson,
      previewLoading,
      previewData,
      mergeModalError,
      loading,
      onCloseModal,
      onExecuteMerge,
    },
    ref
  ) => {
    return (
      <dialog
        ref={ref}
        onClose={onCloseModal}
        className="fixed inset-0 m-auto rounded-xl shadow-xl border border-slate-200 w-full max-w-2xl max-h-[85vh] p-0 overflow-hidden backdrop:bg-slate-900/60 backdrop:backdrop-blur-sm"
        role="dialog"
        aria-labelledby="merge-dialog-title"
        aria-modal="true"
      >
        <div className="flex flex-col h-full bg-white">
          {/* Modal Header */}
          <div className="p-4 border-b border-slate-100 flex items-center justify-between shrink-0 bg-slate-50">
            <h2 id="merge-dialog-title" className="text-sm font-bold text-slate-900">人物統合プレビューと確認</h2>
            <button
              onClick={onCloseModal}
              className="text-slate-400 hover:text-slate-600 transition-colors text-xs cursor-pointer"
              aria-label="閉じる"
            >
              ✕
            </button>
          </div>

          {/* Modal Body */}
          <div className="p-5 overflow-y-auto space-y-4 text-xs text-slate-700">
            {/* Target info comparison */}
            <div className="grid grid-cols-1 gap-4 border border-slate-100 rounded-lg p-3 bg-slate-50 sm:grid-cols-2">
              <div className="space-y-1">
                <div className="text-[10px] uppercase font-bold text-slate-400">統合元（削除される人物）</div>
                <div className="font-semibold text-slate-800 text-sm">{mergeFromPerson?.display_name}</div>
                <div className="text-slate-500 text-[10px]">ID: {mergeFromPerson?.person_id}</div>
                <div className="text-slate-500 text-[10px]">
                  Vault ID: {mergeFromPerson?.vault_id ? <code className="bg-slate-200 px-1 rounded">{mergeFromPerson.vault_id}</code> : "未連携"}
                </div>
              </div>
              <div className="space-y-1 border-t border-slate-200 pt-4 sm:border-l sm:border-t-0 sm:pl-4 sm:pt-0">
                <div className="text-[10px] uppercase font-bold text-slate-400">統合先（残す人物）</div>
                <div className="font-semibold text-slate-800 text-sm">{mergeToPerson?.display_name}</div>
                <div className="text-slate-500 text-[10px]">ID: {mergeToPerson?.person_id}</div>
                <div className="text-slate-500 text-[10px]">
                  Vault ID: {mergeToPerson?.vault_id ? <code className="bg-slate-200 px-1 rounded">{mergeToPerson.vault_id}</code> : "未連携"}
                </div>
              </div>
            </div>

            {previewLoading && (
              <div className="text-center py-6 text-slate-500 font-medium">
                統合可能性と影響データを検証中...
              </div>
            )}

            {mergeModalError && (
              <div className="rounded-lg bg-red-50 p-3 font-medium text-red-800 border border-red-200">
                {mergeModalError}
              </div>
            )}

            {previewData && (
              <div className="space-y-4">
                {/* Status Banner */}
                {previewData.allowed ? (
                  <div className="rounded-lg bg-green-50 p-3 text-green-800 border border-green-200 font-semibold flex items-center gap-1.5">
                    <span>✅</span> 統合可能です。安全上の問題は検出されませんでした。
                  </div>
                ) : (
                  <div className="rounded-lg bg-red-50 p-3 text-red-800 border border-red-200 font-semibold flex flex-col gap-1">
                    <span className="flex items-center gap-1.5">❌ 統合できません。</span>
                    <div className="font-normal mt-1">{previewData.reason}</div>
                  </div>
                )}

                {previewData.allowed && (
                  <>
                    {/* Aliases, Summaries & Relations Migration Counts */}
                    <div className="grid grid-cols-3 gap-3">
                      <div className="border border-slate-100 p-3 rounded-lg bg-white">
                        <div className="font-bold text-slate-800">移管されるサマリー</div>
                        <div className="text-lg font-extrabold text-slate-900 mt-1">{previewData.transferred_summaries_count} <span className="text-xs font-normal text-slate-500">件</span></div>
                        <div className="text-[10px] text-slate-400 mt-1">サマリー参照の自動マージ</div>
                      </div>
                      <div className="border border-slate-100 p-3 rounded-lg bg-white">
                        <div className="font-bold text-slate-800">移管される別名</div>
                        <div className="text-lg font-extrabold text-slate-900 mt-1">{previewData.transferred_aliases_count} <span className="text-xs font-normal text-slate-500">件</span></div>
                        {previewData.alias_transfers.length > 0 && (
                          <div className="flex flex-wrap gap-1 mt-1">
                            {previewData.alias_transfers.map((al) => (
                              <span key={al.normalized_name} className="bg-slate-100 text-slate-800 text-[9px] px-1 py-0.5 rounded border">
                                {al.display_name}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                      <div className="border border-slate-100 p-3 rounded-lg bg-white">
                        <div className="font-bold text-slate-800">影響を受ける関係辺</div>
                        <div className="text-lg font-extrabold text-slate-900 mt-1">
                          {(previewData.transferred_relations_count ?? 0) + (previewData.merged_relations_count ?? 0)} <span className="text-xs font-normal text-slate-500">件</span>
                        </div>
                        <div className="text-[10px] text-slate-400 mt-1">
                          移管: {previewData.transferred_relations_count ?? 0}件 / 重複統合: {previewData.merged_relations_count ?? 0}件
                        </div>
                      </div>
                    </div>

                    {/* Relation impacts details */}
                    {previewData.relation_impacts && previewData.relation_impacts.length > 0 && (
                      <div className="space-y-2">
                        <div className="font-bold text-slate-800 flex items-center gap-1">
                          <span>🔁</span> 人物間関係 (Relations) の移管・統合影響一覧 ({previewData.relation_impacts.length} 件)
                        </div>
                        <div className="border border-slate-200 rounded-lg overflow-hidden divide-y divide-slate-100 font-mono text-[11px] max-h-40 overflow-y-auto bg-white">
                          {previewData.relation_impacts.map((imp) => (
                            <div key={imp.relation_id} className="p-2.5 flex items-center justify-between gap-2">
                              <div>
                                <span className="font-bold text-slate-900">{imp.other_person_name}</span> との「{imp.relation_type_forward_label}」
                                <span className="text-slate-400 text-[10px] ml-2">({imp.started_on || "未指定"} ～ {imp.ended_on || "現在"})</span>
                              </div>
                              <div>
                                {imp.result_type === "transferred" && (
                                  <span className="px-2 py-0.5 bg-blue-50 text-blue-700 font-semibold border border-blue-200 rounded text-[10px]">端点移管</span>
                                )}
                                {imp.result_type === "merged_into_existing" && (
                                  <span className="px-2 py-0.5 bg-purple-50 text-purple-700 font-semibold border border-purple-200 rounded text-[10px]">重複統合</span>
                                )}
                                {imp.result_type === "self_relation_conflict" && (
                                  <span className="px-2 py-0.5 bg-red-50 text-red-700 font-semibold border border-red-200 rounded text-[10px]">自己関係違反</span>
                                )}
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Same summary note consolidation details */}
                    {previewData.merged_summaries.length > 0 && (
                      <div className="space-y-2">
                        <div className="font-bold text-slate-800 flex items-center gap-1">
                          <span>🔗</span> 同一サマリーでのメモ連結対象 ({previewData.merged_summaries.length} 件)
                        </div>
                        <p className="text-[10px] text-slate-400">同一サマリーに両者の参照が存在するため、メモ内容を改行連結し、表示順の先頭側を維持して統合します。</p>
                        <div className="border border-slate-200 rounded-lg overflow-hidden max-h-48 overflow-y-auto divide-y divide-slate-100 font-mono text-[11px]">
                          {previewData.merged_summaries.map((sum) => (
                            <div key={sum.summary_id} className="p-3 bg-slate-50 space-y-2">
                              <div className="font-bold text-slate-700 flex justify-between">
                                <span>{sum.period_key} ({sum.period_type})</span>
                                <span className="text-slate-400">表示順優先: {sum.merged_display_order}</span>
                              </div>
                              <div className="grid grid-cols-2 gap-2 text-[10px]">
                                <div className="bg-red-50 p-1.5 rounded border border-red-100">
                                  <div className="font-semibold text-red-700 mb-0.5">元メモ (統合元):</div>
                                  <div className="whitespace-pre-wrap">{sum.from_note || "(なし)"}</div>
                                </div>
                                <div className="bg-green-50 p-1.5 rounded border border-green-100">
                                  <div className="font-semibold text-green-700 mb-0.5">元メモ (統合先):</div>
                                  <div className="whitespace-pre-wrap">{sum.to_note || "(なし)"}</div>
                                </div>
                              </div>
                              <div className="bg-blue-50 p-2 rounded border border-blue-100 text-[11px]">
                                <div className="font-semibold text-blue-700 mb-0.5">連結後のメモ:</div>
                                <div className="whitespace-pre-wrap">{sum.merged_note || "(なし)"}</div>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </>
                )}
              </div>
            )}

            {/* Warnings and Unalterable Statement */}
            {previewData?.allowed && (
              <div className="rounded-lg bg-orange-50 border border-orange-200 p-3 text-orange-900 space-y-1.5">
                <div className="font-bold flex items-center gap-1">
                  <span>⚠️</span> 取り消し不可の警告
                </div>
                <p className="text-[10px] text-orange-800 leading-normal">
                  この操作はデータベースを直接書き換えるため取り消しできません。統合を完了すると、統合元の人物データは永久に削除されます。内容に間違いがないか、事前によく確認してください。
                </p>
              </div>
            )}
          </div>

          {/* Modal Footer */}
          <div className="p-4 border-t border-slate-100 bg-slate-50 flex items-center justify-end gap-2 shrink-0">
            <button
              onClick={onCloseModal}
              className="rounded border border-slate-300 bg-white px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 cursor-pointer"
              autoFocus
            >
              キャンセル
            </button>
            <button
              onClick={onExecuteMerge}
              disabled={loading || previewLoading || !previewData?.allowed}
              className={`rounded bg-blue-600 px-4 py-2 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-50 ${
                loading || previewLoading || !previewData?.allowed ? "disabled:cursor-not-allowed" : "cursor-pointer"
              }`}
            >
              {loading ? "統合を実行中..." : "安全に統合を実行する"}
            </button>
          </div>
        </div>
      </dialog>
    );
  }
);

MergePreviewDialog.displayName = "MergePreviewDialog";

export default MergePreviewDialog;
