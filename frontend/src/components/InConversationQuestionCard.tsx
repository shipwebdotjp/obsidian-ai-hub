import React, { useState } from 'react';
import { getHitlRun } from '../api/client';

export interface ChoiceOption {
  value: string;
  label: string;
  description?: string;
}

export interface QuestionItem {
  question_id?: string;
  question_key?: string;
  question?: string;
  display_text?: string;
  choices: ChoiceOption[];
}

export interface InConversationQuestionCardProps {
  hitlRunId: string;
  questions: QuestionItem[];
  onSubmit: (answers: Record<string, { value: string; comment?: string }>) => Promise<void>;
  onCancel: () => Promise<void>;
  disabled?: boolean;
}

export interface PendingQuestionSource {
  question_key: string;
  question_id?: string;
  display_text?: string | null;
  prompt?: string | null;
  status?: string;
  choices?: Array<{ value: string; label: string; description?: string }> | null;
}

/** Active waiting-run state shared by Agents/Coding pages (status drives empty-state UI). */
export interface ActiveWaitingRun {
  hitlRunId: string;
  questions: QuestionItem[];
  /** HITL run status (e.g. pending_user, ready_to_resume, completed, failed, cancelled) or null when live. */
  hitlStatus: string | null;
  /** HITL run error_message for failed runs (recovery guidance). */
  hitlError?: string | null;
}

/** HITL terminal statuses: polling stops when one is reached. */
const HITL_SETTLED_STATUSES = new Set(["completed", "failed", "cancelled"]);

/**
 * Poll a HITL run until it settles (completed/failed/cancelled) or times out.
 * Used after answer submission so the UI reloads once dispatch finished
 * instead of flashing an empty question frame. Never throws: returns the
 * last seen detail (or null) on timeout/error.
 */
export async function waitForHitlSettled(
  hitlRunId: string,
  opts: { intervalMs?: number; timeoutMs?: number } = {},
): Promise<{ status: string } | null> {
  const intervalMs = opts.intervalMs ?? 1000;
  const timeoutMs = opts.timeoutMs ?? 20000;
  const deadline = Date.now() + timeoutMs;
  let last: { status: string } | null = null;
  for (;;) {
    try {
      const detail = await getHitlRun(hitlRunId);
      last = detail;
      if (HITL_SETTLED_STATUSES.has(String(detail?.status ?? ""))) return last;
    } catch {
      // Transient read failure: retry until timeout.
    }
    if (Date.now() >= deadline) return last;
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}

export interface WaitingRunStatusPanelProps {
  hitlRunId: string;
  /** HITL run status; null/pending-ish means answers accepted, resume pending. */
  status: string | null;
  errorMessage?: string | null;
  onCancel: () => Promise<void>;
}

/**
 * Non-interactive status panel shown when a waiting run has no pending
 * questions (answers already submitted, or the HITL run failed). Replaces
 * the empty question-card frame so title/ID/buttons never linger alone.
 */
export const WaitingRunStatusPanel: React.FC<WaitingRunStatusPanelProps> = ({
  hitlRunId,
  status,
  errorMessage,
  onCancel,
}) => {
  const [isCancelling, setIsCancelling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const failed = status === "failed" || status === "cancelled";

  const handleCancel = async () => {
    if (isCancelling) return;
    setIsCancelling(true);
    setError(null);
    try {
      await onCancel();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '取消処理中にエラーが発生しました。');
      setIsCancelling(false);
    }
  };

  return (
    <div className={`my-4 p-4 border rounded-lg shadow-sm ${failed ? "border-rose-300 bg-rose-50/50" : "border-amber-300 bg-amber-50/50"}`}>
      <div className={`flex items-center justify-between mb-2 pb-2 border-b ${failed ? "border-rose-200" : "border-amber-200"}`}>
        <span className={`font-semibold text-sm flex items-center gap-2 ${failed ? "text-rose-900" : "text-amber-900"}`}>
          <span>{failed ? "⚠️ 確認処理に失敗しました" : "❓ 回答送信済み・再開待ち"}</span>
        </span>
        <span className="text-xs text-amber-700 font-mono">ID: {hitlRunId}</span>
      </div>
      {failed ? (
        <p className="text-xs text-rose-800">
          質問の処理が中断されました{errorMessage ? `（${errorMessage}）` : ""}。セッションの待機を解除するには「取消」を押し、内容を確認して再送してください。
        </p>
      ) : (
        <p className="text-xs text-amber-800">
          回答を受け付けました。実行の再開を待っています…（自動で再開しない場合はページを再読み込みしてください）
        </p>
      )}
      {error && (
        <p className="text-xs text-red-600 font-medium mt-2">{error}</p>
      )}
      <div className="flex items-center justify-end gap-3 pt-2">
        <button
          type="button"
          onClick={handleCancel}
          disabled={isCancelling}
          className="px-3 py-1.5 text-xs font-medium text-slate-600 bg-slate-100 hover:bg-slate-200 rounded disabled:opacity-50 cursor-pointer"
        >
          {isCancelling ? '取消中…' : '取消'}
        </button>
      </div>
    </div>
  );
};

/** Map HITL API questions to card items: keep pending only, tolerate null choices. */
export function toQuestionItems(questions: PendingQuestionSource[]): QuestionItem[] {
  return questions
    .filter((q) => !q.status || q.status === "pending")
    .map((q) => ({
      question_key: q.question_key,
      question_id: q.question_id,
      display_text: q.display_text ?? q.prompt ?? q.question_key,
      choices: Array.isArray(q.choices) ? q.choices : [],
    }));
}

export const WaitingRunQuestionCard: React.FC<InConversationQuestionCardProps> = ({
  hitlRunId,
  questions,
  onSubmit,
  onCancel,
  disabled = false,
}) => {
  const [selectedChoices, setSelectedChoices] = useState<Record<string, string>>({});
  const [otherTexts, setOtherTexts] = useState<Record<string, string>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const getQKey = (q: QuestionItem, idx: number) => q.question_key || q.question_id || `q_${idx}`;
  const getQText = (q: QuestionItem) => q.display_text || q.question || '';

  const handleRadioChange = (qKey: string, val: string) => {
    setSelectedChoices((prev) => ({ ...prev, [qKey]: val }));
    setErrorMessage(null);
  };

  const handleTextChange = (qKey: string, text: string) => {
    setOtherTexts((prev) => ({ ...prev, [qKey]: text }));
    setErrorMessage(null);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (disabled || isSubmitting || isCancelling) return;

    for (const [idx, q] of questions.entries()) {
      const k = getQKey(q, idx);
      const sel = selectedChoices[k];
      if (!sel) {
        setErrorMessage('すべての質問に回答してください。');
        return;
      }
      if (sel === 'other') {
        const txt = otherTexts[k]?.trim();
        if (!txt) {
          setErrorMessage('「その他」を選択した場合はテキストを入力してください。');
          return;
        }
      }
    }

    const payload: Record<string, { value: string; comment?: string }> = {};
    for (const [idx, q] of questions.entries()) {
      const k = getQKey(q, idx);
      const sel = selectedChoices[k];
      payload[k] = {
        value: sel,
        comment: sel === 'other' ? (otherTexts[k]?.trim() ?? '') : undefined,
      };
    }

    setIsSubmitting(true);
    setErrorMessage(null);
    try {
      await onSubmit(payload);
    } catch (err: unknown) {
      setErrorMessage(err instanceof Error ? err.message : '送信中にエラーが発生しました。');
      setIsSubmitting(false);
    }
  };

  const handleCancelClick = async () => {
    if (disabled || isSubmitting || isCancelling) return;
    setIsCancelling(true);
    setErrorMessage(null);
    try {
      await onCancel();
    } catch (err: unknown) {
      setErrorMessage(err instanceof Error ? err.message : '取消処理中にエラーが発生しました。');
      setIsCancelling(false);
    }
  };

  return (
    <div className="my-4 p-4 border border-amber-300 bg-amber-50/50 rounded-lg shadow-sm">
      <div className="flex items-center justify-between mb-3 border-b border-amber-200 pb-2">
        <span className="font-semibold text-amber-900 text-sm flex items-center gap-2">
          <span>❓ 要件確認・選択のお願い</span>
        </span>
        <span className="text-xs text-amber-700 font-mono">ID: {hitlRunId}</span>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        {questions.map((q, idx) => {
          const qKey = getQKey(q, idx);
          const qText = getQText(q);
          const currentChoice = selectedChoices[qKey] || '';

          return (
            <div key={qKey} className="bg-white p-3 rounded border border-amber-200">
              <p className="text-sm font-medium text-slate-800 mb-2">
                {questions.length > 1 ? `${idx + 1}. ` : ''}{qText}
              </p>
              <div className="space-y-2">
                {(q.choices ?? []).map((opt) => (
                  <label key={opt.value} className="flex items-start gap-2 text-sm text-slate-700 cursor-pointer">
                    <input
                      type="radio"
                      name={`question_${qKey}`}
                      value={opt.value}
                      checked={currentChoice === opt.value}
                      onChange={() => handleRadioChange(qKey, opt.value)}
                      disabled={disabled || isSubmitting || isCancelling}
                      className="mt-1 text-amber-600 focus:ring-amber-500"
                    />
                    <div>
                      <span className="font-medium">{opt.label}</span>
                      {opt.description && (
                        <p className="text-xs text-slate-500">{opt.description}</p>
                      )}
                    </div>
                  </label>
                ))}
              </div>

              {currentChoice === 'other' && (
                <div className="mt-3 pl-6">
                  <textarea
                    value={otherTexts[qKey] || ''}
                    onChange={(e) => handleTextChange(qKey, e.target.value)}
                    placeholder="具体的な内容を入力してください（必須）"
                    rows={2}
                    disabled={disabled || isSubmitting || isCancelling}
                    className="w-full text-sm p-2 border border-slate-300 rounded focus:ring-2 focus:ring-amber-500 focus:border-amber-500"
                  />
                </div>
              )}
            </div>
          );
        })}

        {errorMessage && (
          <p className="text-xs text-red-600 font-medium">{errorMessage}</p>
        )}

        <div className="flex items-center justify-end gap-3 pt-2">
          <button
            type="button"
            onClick={handleCancelClick}
            disabled={disabled || isSubmitting || isCancelling}
            className="px-3 py-1.5 text-xs font-medium text-slate-600 bg-slate-100 hover:bg-slate-200 rounded disabled:opacity-50"
          >
            {isCancelling ? '取消中…' : '取消'}
          </button>
          <button
            type="submit"
            disabled={disabled || isSubmitting || isCancelling}
            className="px-4 py-1.5 text-xs font-medium text-white bg-amber-600 hover:bg-amber-700 rounded shadow-sm disabled:opacity-50"
          >
            {isSubmitting ? '送信中…' : '回答を送信'}
          </button>
        </div>
      </form>
    </div>
  );
};
