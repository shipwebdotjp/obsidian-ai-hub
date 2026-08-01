import React, { useEffect, useRef } from "react";
import { PersonAlias } from "../../api/types";
import { PersonDetail } from "./types";

interface DeleteAliasDialogProps {
  aliasToDelete: PersonAlias;
  selectedPerson: PersonDetail;
  loading: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

export default function DeleteAliasDialog({
  aliasToDelete,
  selectedPerson,
  loading,
  onCancel,
  onConfirm,
}: DeleteAliasDialogProps) {
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
      className="fixed inset-0 m-auto rounded-xl shadow-xl border border-slate-200 w-full max-w-sm p-0 overflow-hidden backdrop:bg-slate-900/60 backdrop:backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="delete-alias-dialog-title"
    >
      <div className="flex flex-col h-full bg-white">
        <div className="p-4 border-b border-slate-100 bg-slate-50 flex items-center justify-between shrink-0">
          <h3 id="delete-alias-dialog-title" className="text-sm font-bold text-slate-900">別名の削除確認</h3>
          <button
            onClick={onCancel}
            className="text-slate-400 hover:text-slate-600 transition-colors text-xs cursor-pointer"
            aria-label="閉じる"
          >
            ✕
          </button>
        </div>
        <div className="p-5 space-y-3 text-xs text-slate-700">
          <p>
            本当に別名「<strong className="text-slate-900">{aliasToDelete.display_name}</strong>」を
            「<strong className="text-slate-900">{selectedPerson.display_name}</strong>」から削除してもよろしいですか？
          </p>
          <p className="text-[10px] text-slate-500">
            この操作はデータベースから直接削除し、元に戻すことはできません。次回のVault同期でも復活しません。
          </p>
        </div>
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
            {loading ? "削除中..." : "削除する"}
          </button>
        </div>
      </div>
    </dialog>
  );
}
