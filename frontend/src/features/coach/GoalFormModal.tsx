import { useState } from "react";
import { createCoachGoal } from "./coachApi";
import { CoachGoalDetail } from "./types";
import { Plus, Trash2, X } from "lucide-react";

interface GoalFormModalProps {
  isOpen: boolean;
  onClose: () => void;
  onCreated: (goal: CoachGoalDetail) => void;
}

export default function GoalFormModal({
  isOpen,
  onClose,
  onCreated,
}: GoalFormModalProps) {
  const [statement, setStatement] = useState("");
  const [reason, setReason] = useState("");
  const [focuses, setFocuses] = useState<string[]>([""]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleAddFocus = () => {
    setFocuses((prev) => [...prev, ""]);
  };

  const handleRemoveFocus = (index: number) => {
    if (focuses.length <= 1) return;
    setFocuses((prev) => prev.filter((_, i) => i !== index));
  };

  const handleFocusChange = (index: number, val: string) => {
    setFocuses((prev) => {
      const copy = [...prev];
      copy[index] = val;
      return copy;
    });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!statement.trim() || !reason.trim()) {
      setError("目標（到達像）と理由を入力してください。");
      return;
    }
    const validFocuses = focuses.map((f) => f.trim()).filter(Boolean);
    if (validFocuses.length === 0) {
      setError("Focus 候補を少なくとも1つ入力してください。");
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const created = await createCoachGoal({
        statement: statement.trim(),
        reason: reason.trim(),
        initial_focuses: validFocuses,
      });
      onCreated(created);
      onClose();
      // Reset form
      setStatement("");
      setReason("");
      setFocuses([""]);
    } catch (err: any) {
      setError(err?.message || "Goal の作成に失敗しました。");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
      <div className="w-full max-w-lg rounded-xl bg-white p-6 shadow-xl">
        <div className="mb-4 flex items-center justify-between border-b border-slate-200 pb-3">
          <h2 className="text-base font-semibold text-slate-800">
            新しい長期目標 (Goal) を作成
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {error && (
          <div className="mb-4 rounded bg-red-50 p-3 text-xs text-red-700">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-slate-700 mb-1">
              目標・目指す姿 (statement) <span className="text-red-500">*</span>
            </label>
            <textarea
              required
              rows={2}
              value={statement}
              onChange={(e) => setStatement(e.target.value)}
              placeholder="例: 数年かけて専門性を身につけ、信頼されるエンジニアになる"
              className="w-full rounded border border-slate-300 p-2 text-sm focus:border-slate-800 focus:outline-none"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-700 mb-1">
              理由・動機 (reason) <span className="text-red-500">*</span>
            </label>
            <textarea
              required
              rows={2}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="例: 自立して大きなプロジェクトを主導できるようになりたいため"
              className="w-full rounded border border-slate-300 p-2 text-sm focus:border-slate-800 focus:outline-none"
            />
          </div>

          <div>
            <div className="mb-1 flex items-center justify-between">
              <label className="text-xs font-medium text-slate-700">
                初期 Focus 候補 (最初の候補が active になります){" "}
                <span className="text-red-500">*</span>
              </label>
              <button
                type="button"
                onClick={handleAddFocus}
                className="inline-flex items-center gap-1 text-xs text-indigo-600 hover:text-indigo-800"
              >
                <Plus className="h-3.5 w-3.5" /> 候補を追加
              </button>
            </div>

            <div className="space-y-2">
              {focuses.map((f, idx) => (
                <div key={idx} className="flex items-center gap-2">
                  <input
                    type="text"
                    value={f}
                    onChange={(e) => handleFocusChange(idx, e.target.value)}
                    placeholder={
                      idx === 0
                        ? "例: 週に1回、学んだことを自分の言葉でまとめる (アクティブ)"
                        : "例: 毎日15分技術書を読む"
                    }
                    className="flex-1 rounded border border-slate-300 p-2 text-sm focus:border-slate-800 focus:outline-none"
                  />
                  {focuses.length > 1 && (
                    <button
                      type="button"
                      onClick={() => handleRemoveFocus(idx)}
                      className="text-slate-400 hover:text-red-600 p-1"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>

          <div className="mt-6 flex justify-end gap-2 border-t border-slate-200 pt-4">
            <button
              type="button"
              onClick={onClose}
              className="rounded px-4 py-2 text-xs font-medium text-slate-600 hover:bg-slate-100"
            >
              キャンセル
            </button>
            <button
              type="submit"
              disabled={loading}
              className="rounded bg-slate-900 px-4 py-2 text-xs font-medium text-white hover:bg-slate-800 disabled:opacity-50"
            >
              {loading ? "作成中…" : "目標を作成"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
