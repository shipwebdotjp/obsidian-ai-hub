import { useState } from "react";
import {
  activateCoachFocus,
  createCoachFocus,
  fetchCoachGoalDetail,
  pauseCoachFocus,
  updateCoachFocus,
} from "./coachApi";
import { CoachFocus, CoachGoalDetail } from "./types";
import { CheckCircle2, PauseCircle, Plus, Edit2, Check, X } from "lucide-react";

interface FocusSectionProps {
  goal: CoachGoalDetail;
  onGoalUpdated: (updated: CoachGoalDetail) => void;
}

export default function FocusSection({
  goal,
  onGoalUpdated,
}: FocusSectionProps) {
  const [newFocusName, setNewFocusName] = useState("");
  const [adding, setAdding] = useState(false);
  const [editingFocusId, setEditingFocusId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const isEnded = goal.status === "ended";

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newFocusName.trim() || isEnded) return;

    try {
      setError(null);
      await createCoachFocus(goal.goal_id, { name: newFocusName.trim() });
      setNewFocusName("");
      setAdding(false);
      // Refresh goal details
      const updated = await fetchCoachGoalDetail(goal.goal_id);
      onGoalUpdated(updated);
    } catch (err: any) {
      setError(err?.message || "Focus の作成に失敗しました。");
    }
  };

  const handleStartEdit = (focus: CoachFocus) => {
    if (isEnded) return;
    setEditingFocusId(focus.focus_id);
    setEditingName(focus.name);
  };

  const handleSaveEdit = async (focusId: string) => {
    if (!editingName.trim() || isEnded) return;

    try {
      setError(null);
      await updateCoachFocus(focusId, { name: editingName.trim() });
      setEditingFocusId(null);
      const updated = await fetchCoachGoalDetail(goal.goal_id);
      onGoalUpdated(updated);
    } catch (err: any) {
      setError(err?.message || "Focus 名の変更に失敗しました。");
    }
  };

  const handleActivate = async (focusId: string) => {
    if (isEnded) return;
    try {
      setError(null);
      await activateCoachFocus(focusId);
      const updated = await fetchCoachGoalDetail(goal.goal_id);
      onGoalUpdated(updated);
    } catch (err: any) {
      setError(err?.message || "Focus のアクティブ化に失敗しました。");
    }
  };

  const handlePause = async (focusId: string) => {
    if (isEnded) return;
    try {
      setError(null);
      await pauseCoachFocus(focusId);
      const updated = await fetchCoachGoalDetail(goal.goal_id);
      onGoalUpdated(updated);
    } catch (err: any) {
      setError(err?.message || "Focus の休止に失敗しました。");
    }
  };

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-800">
            Focus 候補・選択
          </h3>
          <p className="text-xs text-slate-500">
            Goal に向けた今週・最近の重点取り組みです（アクティブは最大1つ）。
          </p>
        </div>

        {!isEnded && !adding && (
          <button
            type="button"
            onClick={() => setAdding(true)}
            className="inline-flex items-center gap-1 rounded bg-slate-100 px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-200"
          >
            <Plus className="h-3.5 w-3.5" /> 候補を追加
          </button>
        )}
      </div>

      {error && (
        <div className="mb-3 rounded bg-red-50 p-2 text-xs text-red-700">
          {error}
        </div>
      )}

      {adding && (
        <form onSubmit={handleCreate} className="mb-4 flex gap-2">
          <input
            type="text"
            required
            value={newFocusName}
            onChange={(e) => setNewFocusName(e.target.value)}
            placeholder="新しい Focus 候補を入力"
            className="flex-1 rounded border border-slate-300 p-2 text-xs focus:border-slate-800 focus:outline-none"
          />
          <button
            type="submit"
            className="rounded bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800"
          >
            追加
          </button>
          <button
            type="button"
            onClick={() => setAdding(false)}
            className="rounded px-2 py-1.5 text-xs text-slate-500 hover:bg-slate-100"
          >
            キャンセル
          </button>
        </form>
      )}

      <div className="space-y-2">
        {goal.focuses.length === 0 ? (
          <p className="py-2 text-xs text-slate-400">Focus 候補がありません。</p>
        ) : (
          goal.focuses.map((f) => {
            const isActive = f.status === "active";
            const isPaused = f.status === "paused";
            const isEditing = editingFocusId === f.focus_id;

            return (
              <div
                key={f.focus_id}
                className={`flex items-center justify-between rounded-lg border p-3 transition-colors ${
                  isActive
                    ? "border-emerald-300 bg-emerald-50/50"
                    : isPaused
                    ? "border-slate-200 bg-slate-50 opacity-75"
                    : "border-slate-200 bg-white hover:border-slate-300"
                }`}
              >
                <div className="flex flex-1 items-center gap-2.5 mr-2">
                  {isActive ? (
                    <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold text-emerald-800 shrink-0">
                      <CheckCircle2 className="h-3 w-3" /> アクティブ
                    </span>
                  ) : isPaused ? (
                    <span className="inline-flex items-center gap-1 rounded-full bg-slate-200 px-2 py-0.5 text-[10px] font-medium text-slate-600 shrink-0">
                      <PauseCircle className="h-3 w-3" /> 休止中
                    </span>
                  ) : (
                    <span className="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-500 shrink-0">
                      候補
                    </span>
                  )}

                  {isEditing ? (
                    <div className="flex flex-1 items-center gap-1">
                      <input
                        type="text"
                        value={editingName}
                        onChange={(e) => setEditingName(e.target.value)}
                        className="flex-1 rounded border border-slate-300 p-1 text-xs focus:border-slate-800 focus:outline-none"
                      />
                      <button
                        type="button"
                        onClick={() => handleSaveEdit(f.focus_id)}
                        className="rounded p-1 text-emerald-600 hover:bg-emerald-100"
                      >
                        <Check className="h-4 w-4" />
                      </button>
                      <button
                        type="button"
                        onClick={() => setEditingFocusId(null)}
                        className="rounded p-1 text-slate-400 hover:bg-slate-100"
                      >
                        <X className="h-4 w-4" />
                      </button>
                    </div>
                  ) : (
                    <span className="text-xs font-medium text-slate-800">
                      {f.name}
                    </span>
                  )}
                </div>

                {!isEnded && !isEditing && (
                  <div className="flex items-center gap-1 shrink-0">
                    <button
                      type="button"
                      onClick={() => handleStartEdit(f)}
                      title="名称変更"
                      className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
                    >
                      <Edit2 className="h-3.5 w-3.5" />
                    </button>

                    {!isActive && (
                      <button
                        type="button"
                        onClick={() => handleActivate(f.focus_id)}
                        className="rounded bg-emerald-600 px-2 py-1 text-[11px] font-medium text-white hover:bg-emerald-700"
                      >
                        選択 (Active)
                      </button>
                    )}

                    {isActive && (
                      <button
                        type="button"
                        onClick={() => handlePause(f.focus_id)}
                        className="rounded border border-slate-300 bg-white px-2 py-1 text-[11px] font-medium text-slate-600 hover:bg-slate-100"
                      >
                        休止
                      </button>
                    )}
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
