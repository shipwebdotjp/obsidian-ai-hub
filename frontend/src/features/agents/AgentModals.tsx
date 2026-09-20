import type { Agent, AgentSession } from "../../api/types";
import Modal from "../../components/Modal";

interface AgentModalsProps {
  agentToDelete: Agent | null;
  onCloseDeleteAgent: () => void;
  onConfirmDeleteAgent: () => void;
  sessionToEditTitle: AgentSession | null;
  onCloseEditTitle: () => void;
  editTitleError: string | null;
  editTitleText: string;
  onEditTitleTextChange: (text: string) => void;
  onSaveSessionTitle: (e: React.FormEvent) => void;
  sessionToDelete: AgentSession | null;
  onCloseDeleteSession: () => void;
  onConfirmDeleteSession: () => void;
}

/** 削除確認2種と会話タイトル変更のモーダル。 */
export function AgentModals({
  agentToDelete,
  onCloseDeleteAgent,
  onConfirmDeleteAgent,
  sessionToEditTitle,
  onCloseEditTitle,
  editTitleError,
  editTitleText,
  onEditTitleTextChange,
  onSaveSessionTitle,
  sessionToDelete,
  onCloseDeleteSession,
  onConfirmDeleteSession,
}: AgentModalsProps) {
  return (
    <>
      {/* Delete Agent Modal */}
      {agentToDelete && (
        <Modal
          labelledBy="delete-agent-dialog-heading"
          onClose={onCloseDeleteAgent}
        >
          <h4 id="delete-agent-dialog-heading" className="text-sm font-semibold text-slate-900">
            エージェントの削除確認
          </h4>
          <p className="text-xs text-slate-600">
            「{agentToDelete.name}」を削除してもよろしいですか？関連するすべての会話セッション、メッセージ履歴、および実行記録も削除されます。
          </p>
          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onCloseDeleteAgent}
              className="rounded cursor-pointer border border-slate-300 bg-white px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50"
            >
              キャンセル
            </button>
            <button
              type="button"
              onClick={onConfirmDeleteAgent}
              className="rounded cursor-pointer bg-red-600 px-3 py-1.5 text-xs text-white hover:bg-red-700 font-medium"
            >
              削除する
            </button>
          </div>
        </Modal>
      )}

      {/* Edit Session Title Modal */}
      {sessionToEditTitle && (
        <Modal
          labelledBy="edit-session-title-dialog-heading"
          onClose={onCloseEditTitle}
        >
          <h4 id="edit-session-title-dialog-heading" className="text-sm font-semibold text-slate-900">
            会話タイトルの変更
          </h4>
          {editTitleError && (
            <div className="rounded-lg bg-red-50 p-2.5 text-xs text-red-600">
              {editTitleError}
            </div>
          )}
          <form onSubmit={onSaveSessionTitle} className="space-y-3">
            <input
              type="text"
              required
              value={editTitleText}
              onChange={(e) => onEditTitleTextChange(e.target.value)}
              placeholder="会話タイトルを入力"
              className="w-full rounded-md border border-slate-300 p-2 text-xs focus:border-slate-500 focus:outline-none"
              autoFocus
            />
            <div className="flex justify-end gap-2 pt-1">
              <button
                type="button"
                onClick={onCloseEditTitle}
                className="rounded cursor-pointer border border-slate-300 bg-white px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50"
              >
                キャンセル
              </button>
              <button
                type="submit"
                className="rounded cursor-pointer bg-slate-900 px-3 py-1.5 text-xs text-white hover:bg-slate-800 font-medium"
              >
                保存する
              </button>
            </div>
          </form>
        </Modal>
      )}

      {/* Delete Session Modal */}
      {sessionToDelete && (
        <Modal
          labelledBy="delete-session-dialog-heading"
          onClose={onCloseDeleteSession}
        >
          <h4 id="delete-session-dialog-heading" className="text-sm font-semibold text-slate-900">
            会話履歴の削除確認
          </h4>
          <p className="text-xs text-slate-600">
            「{sessionToDelete.title}」を削除してもよろしいですか？含まれる全メッセージおよび実行記録が削除されます。
          </p>
          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onCloseDeleteSession}
              className="rounded cursor-pointer border border-slate-300 bg-white px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50"
            >
              キャンセル
            </button>
            <button
              type="button"
              onClick={onConfirmDeleteSession}
              className="rounded cursor-pointer bg-red-600 px-3 py-1.5 text-xs text-white hover:bg-red-700 font-medium"
            >
              削除する
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}
