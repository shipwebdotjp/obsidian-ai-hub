import { useState } from "react";
import { ApiError, createTaskAgentTask } from "../../api/client";
import type { TaskAgentTask } from "../../api/types";

/**
 * Task Agent への新規タスク投入フォーム。
 *
 * - 空入力はクライアント側で弾き、サーバーへ送信しない。
 * - 成功時は作成された Task を `onCreated` へ渡す（呼び出し側で一覧再取得・詳細遷移を行う）。
 * - 通信/API 失敗時はサーバーまたは `ApiError` のメッセージを表示する。
 */
export default function TaskAgentCreateForm({
  onCreated,
  onCancel,
}: {
  onCreated: (task: TaskAgentTask) => void;
  onCancel: () => void;
}) {
  const [promptText, setPromptText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = promptText.trim().length > 0 && !submitting;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!promptText.trim()) {
      setError("依頼内容を入力してください");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const task = await createTaskAgentTask({ prompt_text: promptText });
      onCreated(task);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "タスクの作成に失敗しました",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form
      onSubmit={(e) => void handleSubmit(e)}
      className="border-b border-slate-200 bg-white px-4 py-3"
    >
      <label
        htmlFor="task-agent-create-prompt"
        className="mb-1 block text-sm font-medium text-slate-700"
      >
        新規タスクの依頼内容
      </label>
      <textarea
        id="task-agent-create-prompt"
        value={promptText}
        onChange={(e) => setPromptText(e.target.value)}
        rows={3}
        placeholder="Task Agentへの依頼を入力してください"
        disabled={submitting}
        className="w-full rounded border border-slate-300 px-2 py-1 text-sm disabled:opacity-50"
      />
      {error && (
        <p
          role="alert"
          className="mt-2 rounded border border-rose-300 bg-rose-50 p-2 text-sm text-rose-700"
        >
          {error}
        </p>
      )}
      <div className="mt-2 flex items-center gap-2">
        <button
          type="submit"
          disabled={!canSubmit}
          className="cursor-pointer rounded bg-blue-600 px-3 py-1 text-sm text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {submitting ? "投入中…" : "投入する"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={submitting}
          className="cursor-pointer rounded bg-slate-900 px-3 py-1 text-sm text-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          キャンセル
        </button>
      </div>
    </form>
  );
}
