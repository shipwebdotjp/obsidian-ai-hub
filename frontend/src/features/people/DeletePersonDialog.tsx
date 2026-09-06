import React, { useEffect, useRef } from "react";
import { PersonDetail } from "./types";

interface DeletePersonDialogProps {
  personToDelete: PersonDetail;
  loading: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

export default function DeletePersonDialog({
  personToDelete,
  loading,
  onCancel,
  onConfirm,
}: DeletePersonDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (dialog && !dialog.open) {
      dialog.showModal();
    }
  }, []);

  return (
    <dialog
      ref={dialogRef}
      onClose={onCancel}
      className="fixed inset-0 m-auto rounded-xl shadow-xl border border-slate-200 w-full max-w-md p-0 overflow-hidden backdrop:bg-slate-900/60 backdrop:backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="delete-person-dialog-title"
    >
      <div className="flex flex-col h-full bg-white">
        {/* Modal Header */}
        <div className="p-4 border-b border-slate-100 bg-red-50 flex items-center justify-between shrink-0">
          <h3 id="delete-person-dialog-title" className="text-sm font-bold text-red-900">⚠️ 人物の完全削除確認</h3>
          <button
            onClick={onCancel}
            className="text-red-400 hover:text-red-600 transition-colors text-xs cursor-pointer"
            aria-label="閉じる"
          >
            ✕
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-5 overflow-y-auto space-y-3 text-xs text-slate-700 leading-normal">
          <p className="font-semibold text-slate-950">
            本当に「{personToDelete.display_name}」を完全に削除してもよろしいですか？
          </p>

          {personToDelete.vault_id ? (
            <div className="rounded-lg bg-orange-50 border border-orange-200 p-3 text-orange-950 font-medium space-y-1">
              <div className="font-bold flex items-center gap-1">
                <span>⚠️</span> Vaultノート連携に対する警告
              </div>
              <p className="text-[11px] leading-normal text-orange-800">
                この人物は Vault ノート（ID: <code>{personToDelete.vault_id}</code>）と連携しています。DB から完全に削除されますが、Vault ノート自体は削除されません。
                そのため、<strong>次回の同期（Sync）を実行した際に、この人物が再びデータベース上に再作成される可能性</strong>がありますが、<strong>登録されていた関係（リレーション）および根拠は復元されません</strong>。
              </p>
            </div>
          ) : (
            <div className="rounded-lg bg-red-50 border border-red-200 p-3 text-red-950 font-medium space-y-1">
              <div className="font-bold flex items-center gap-1">
                <span>⚠️</span> 一部不備・取り消し不可の警告
              </div>
              <p className="text-[11px] leading-normal text-red-800">
                この人物は未連携の人物です。削除を実行すると、紐づいていたすべてのサマリ履歴メモ、登録別名、手動個別割当などの関連行がDBから永久に消去され、元に戻すことはできません。
              </p>
            </div>
          )}

          {personToDelete.relation_counts && (
            <div className="border border-slate-100 rounded-lg p-3 bg-slate-50 space-y-1 text-slate-600">
              <div className="font-bold text-slate-800 mb-1">影響を受ける関連レコード数:</div>
              <div>・紐づくサマリ: <strong className="text-slate-900">{personToDelete.relation_counts.summaries}</strong> 件</div>
              <div>・別名 (aliases): <strong className="text-slate-900">{personToDelete.relation_counts.aliases}</strong> 件</div>
              <div>・手動個別割当: <strong className="text-slate-900">{personToDelete.relation_counts.assignments}</strong> 件</div>
              <div>・発信リレーション: <strong className="text-slate-900">{personToDelete.relation_counts.subject_relations ?? 0}</strong> 件</div>
              <div>・受信リレーション: <strong className="text-slate-900">{personToDelete.relation_counts.object_relations ?? 0}</strong> 件</div>
              <div>・根拠 (evidence): <strong className="text-slate-900">{personToDelete.relation_counts.evidence ?? 0}</strong> 件</div>
            </div>
          )}
        </div>

        {/* Modal Footer */}
        <div className="p-4 border-t border-slate-100 bg-slate-50 flex items-center justify-end gap-2 shrink-0">
          <button
            onClick={onCancel}
            className="rounded border border-slate-300 bg-white px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 cursor-pointer"
          >
            キャンセル
          </button>
          <button
            onClick={onConfirm}
            disabled={loading}
            className={`rounded bg-rose-800 px-4 py-2 text-xs font-semibold text-white hover:bg-rose-900 disabled:opacity-50 ${
              loading ? "disabled:cursor-not-allowed" : "cursor-pointer"
            }`}
          >
            {loading ? "削除を実行中..." : "本当に完全に削除する"}
          </button>
        </div>
      </div>
    </dialog>
  );
}
