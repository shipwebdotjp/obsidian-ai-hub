import { useEffect, useState } from "react";
import { getErrorMessage } from "../../utils/error";

export interface CheckinChoice {
  value: string;
  label: string;
  description?: string;
}

export interface CheckinQuestion {
  question_key: string;
  status?: string;
  prompt?: string | null;
  display_text?: string | null;
  choices?: CheckinChoice[] | null;
  answer?: { value?: unknown; comment?: unknown } | string | null;
}

export interface WeeklyCheckinCardProps {
  runId: string;
  questions: CheckinQuestion[];
  disabled?: boolean;
  onSubmitAnswer: (questionKey: string, value: string) => Promise<void>;
  onSubmitted: () => Promise<void>;
}

const NOTE_KEY = "checkin_note";
const NEXT_STEP_KEY = "checkin_next_step";
const DECISION_KEY = "checkin_decision";
const TARGET_KEY = "checkin_target_focus";

export const DECISION_OPTIONS: CheckinChoice[] = [
  { value: "continue", label: "続ける", description: "このまま同じ Focus で進める" },
  { value: "narrow", label: "小さくする", description: "範囲を狭めて続けやすくする" },
  { value: "change", label: "別の Focus へ", description: "切り替える Focus を選ぶ" },
  { value: "pause", label: "休む", description: "今週はこの Focus を休止する" },
];

function findQuestion(questions: CheckinQuestion[], key: string): CheckinQuestion | undefined {
  return questions.find((q) => q.question_key === key);
}

function isPending(q: CheckinQuestion | undefined): boolean {
  return !!q && (!q.status || q.status === "pending");
}

function answerLabel(q: CheckinQuestion | undefined): string {
  if (!q) return "";
  const ans = q.answer;
  if (ans && typeof ans === "object" && "value" in ans) return String(ans.value ?? "");
  return String(ans ?? "");
}

export default function WeeklyCheckinCard({
  runId,
  questions,
  disabled = false,
  onSubmitAnswer,
  onSubmitted,
}: WeeklyCheckinCardProps) {
  const noteQ = findQuestion(questions, NOTE_KEY);
  const nextStepQ = findQuestion(questions, NEXT_STEP_KEY);
  const decisionQ = findQuestion(questions, DECISION_KEY);
  const targetQ = findQuestion(questions, TARGET_KEY);

  const notePending = isPending(noteQ);
  const nextStepPending = isPending(nextStepQ);
  const decisionPending = isPending(decisionQ);
  const targetPending = isPending(targetQ);

  const [note, setNote] = useState("");
  const [nextStep, setNextStep] = useState("");
  const [decision, setDecision] = useState("");
  const [target, setTarget] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset per-run form state when the user switches to another run.
  useEffect(() => {
    setNote("");
    setNextStep("");
    setDecision("");
    setTarget("");
    setError(null);
  }, [runId]);

  const notePrompt = noteQ?.prompt || noteQ?.display_text || "今週は Focus に向けてどんな1週間でしたか？";
  const targetChoices = Array.isArray(targetQ?.choices) ? targetQ!.choices! : [];

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (disabled || submitting) return;
    setError(null);

    if (notePending && !note.trim()) {
      setError("今週の振り返りを入力してください。");
      return;
    }
    if (decisionPending && !decision) {
      setError("来週の扱いを選んでください。");
      return;
    }
    if (decision === "narrow" && nextStepPending && !nextStep.trim()) {
      setError("「小さくする」を選んだ場合は、来週試すことを入力してください。");
      return;
    }
    if (decision === "change") {
      if (targetChoices.length === 0) {
        setError("切り替え先の Focus がありません。先に Focus を追加してください。");
        return;
      }
      if (targetPending && !target) {
        setError("切り替える Focus を選んでください。");
        return;
      }
    }

    setSubmitting(true);
    try {
      // Optional answers first, required answers last: the run becomes
      // ready_to_resume only after the final required answer lands, so the
      // worker never sees a partially answered set.
      if (nextStepPending && nextStep.trim()) {
        await onSubmitAnswer(NEXT_STEP_KEY, nextStep.trim());
      }
      if (decision === "change" && targetPending && target) {
        await onSubmitAnswer(TARGET_KEY, target);
      }
      if (notePending) {
        await onSubmitAnswer(NOTE_KEY, note.trim());
      }
      if (decisionPending) {
        await onSubmitAnswer(DECISION_KEY, decision);
      }
      await onSubmitted();
    } catch (err: unknown) {
      setError(getErrorMessage(err, "回答の送信に失敗しました。"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mt-6 rounded-lg border border-slate-200 bg-white p-5">
      <div className="flex items-center justify-between border-b border-slate-200 pb-2">
        <span className="text-sm font-bold text-slate-800">週次チェックイン</span>
        <span className="font-mono text-xs text-slate-400">ID: {runId}</span>
      </div>

      <form onSubmit={handleSubmit} className="mt-4 space-y-5">
        <div>
          <p className="text-sm font-semibold text-slate-800">{notePrompt}</p>
          {notePending ? (
            <textarea
              aria-label="今週の振り返り"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="一言でかまいません。「特になし」でも大丈夫です"
              rows={3}
              disabled={disabled || submitting}
              className="mt-2 w-full rounded border border-slate-200 bg-white p-3 text-sm text-slate-800 outline-none focus:border-slate-400"
            />
          ) : (
            <p className="mt-2 rounded border border-slate-100 bg-slate-50 p-3 text-sm text-slate-800 whitespace-pre-wrap">
              {answerLabel(noteQ)}
            </p>
          )}
        </div>

        {nextStepPending && (
          <div>
            <p className="text-xs font-semibold text-slate-600">来週試したいこと（任意）</p>
            <textarea
              aria-label="来週試したいこと"
              value={nextStep}
              onChange={(e) => setNextStep(e.target.value)}
              placeholder="来週の一歩として残したいことがあれば"
              rows={2}
              disabled={disabled || submitting}
              className="mt-2 w-full rounded border border-slate-200 bg-white p-2 text-sm text-slate-800 outline-none focus:border-slate-400"
            />
          </div>
        )}

        <div>
          <p className="text-xs font-semibold text-slate-600">来週はどうしますか？</p>
          {decisionPending ? (
            <div className="mt-2 grid gap-2 sm:grid-cols-2">
              {DECISION_OPTIONS.map((opt) => {
                const selected = decision === opt.value;
                return (
                  <button
                    key={opt.value}
                    type="button"
                    aria-pressed={selected}
                    onClick={() => setDecision(opt.value)}
                    disabled={disabled || submitting}
                    className={`rounded-lg border p-3 text-left transition-colors cursor-pointer disabled:cursor-not-allowed ${
                      selected
                        ? "border-blue-600 bg-blue-50 text-blue-900 ring-1 ring-blue-600"
                        : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
                    }`}
                  >
                    <span className="block text-xs font-bold">{opt.label}</span>
                    {opt.description && (
                      <span className="mt-1 block text-[10px] text-slate-500 leading-normal">
                        {opt.description}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          ) : (
            <p className="mt-2 text-sm text-slate-800">
              {DECISION_OPTIONS.find((o) => o.value === answerLabel(decisionQ))?.label ??
                answerLabel(decisionQ)}
            </p>
          )}
        </div>

        {decision === "change" && targetPending && (
          <div>
            <p className="text-xs font-semibold text-slate-600">切り替える Focus</p>
            {targetChoices.length === 0 ? (
              <p className="mt-2 text-xs text-amber-700">
                切り替え先の Focus がありません。Coach 画面で Focus を追加してください。
              </p>
            ) : (
              <select
                aria-label="切り替える Focus"
                value={target}
                onChange={(e) => setTarget(e.target.value)}
                disabled={disabled || submitting}
                className="mt-2 w-full max-w-md cursor-pointer rounded border border-slate-200 bg-white p-2 text-sm text-slate-800 outline-none focus:border-slate-400 disabled:cursor-not-allowed"
              >
                <option value="">選択してください</option>
                {targetChoices.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </select>
            )}
          </div>
        )}

        {error && <p className="text-xs font-medium text-red-600">{error}</p>}

        {(notePending || decisionPending) && (
          <div className="flex justify-end">
            <button
              type="submit"
              disabled={disabled || submitting}
              className="rounded bg-blue-600 px-4 py-2 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-50 cursor-pointer disabled:cursor-not-allowed"
            >
              {submitting ? "送信中…" : "回答を送信"}
            </button>
          </div>
        )}
      </form>
    </div>
  );
}
