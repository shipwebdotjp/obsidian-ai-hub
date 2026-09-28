import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { fetchCoachGoals } from "./coachApi";
import { CoachGoalDetail } from "./types";
import GoalFormModal from "./GoalFormModal";
import { coachGoalDetailPath } from "../../constants/routes";
import {
  ChevronRight,
  Flag,
  PauseCircle,
  Plus,
  Target,
  Archive,
} from "lucide-react";

export default function CoachOverviewPage() {
  const navigate = useNavigate();
  const [goals, setGoals] = useState<CoachGoalDetail[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [showArchive, setShowArchive] = useState(false);

  const loadGoals = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchCoachGoals();
      setGoals(res.items);
    } catch (err: any) {
      setError(err?.message || "目標一覧の取得に失敗しました。");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadGoals();
  }, []);

  const activeGoals = goals.filter((g) => g.status === "active");
  const pausedGoals = goals.filter((g) => g.status === "paused");
  const endedGoals = goals.filter((g) => g.status === "ended");

  return (
    <div className="h-full overflow-y-auto bg-slate-50 p-6 space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-200 pb-4">
        <div>
          <h1 className="text-xl font-bold text-slate-900 flex items-center gap-2">
            <Target className="h-6 w-6 text-slate-800" />
            長期目標コーチ (Long-term Coach)
          </h1>
          <p className="text-xs text-slate-500 mt-1">
            大きな目標（Goal）を見失わず、今の焦点（Focus）と週次 Reflection で前進を継続します。
          </p>
        </div>

        <button
          type="button"
          onClick={() => setIsCreateModalOpen(true)}
          className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-4 py-2 text-xs font-medium text-white shadow-sm hover:bg-slate-800 shrink-0"
        >
          <Plus className="h-4 w-4" /> 新しい Goal を作成
        </button>
      </div>

      {error && (
        <div className="rounded-lg bg-red-50 p-3 text-xs text-red-700">
          {error}
        </div>
      )}

      {loading ? (
        <div className="py-12 text-center text-xs text-slate-400">
          目標一覧を読み込み中…
        </div>
      ) : (
        <div className="space-y-6">
          {/* Active Goals Section */}
          <div>
            <h2 className="text-sm font-semibold text-slate-800 mb-3 flex items-center gap-2">
              <span className="h-2 w-2 rounded-full bg-emerald-500" />
              アクティブな長期目標 ({activeGoals.length})
            </h2>

            {activeGoals.length === 0 ? (
              <div className="rounded-xl border border-dashed border-slate-300 bg-white p-8 text-center">
                <Target className="mx-auto h-8 w-8 text-slate-300 mb-2" />
                <p className="text-xs text-slate-500 mb-3">
                  現在アクティブな Goal がありません。
                </p>
                <button
                  type="button"
                  onClick={() => setIsCreateModalOpen(true)}
                  className="inline-flex items-center gap-1 rounded bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800"
                >
                  <Plus className="h-3.5 w-3.5" /> Goal を作成する
                </button>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {activeGoals.map((g) => (
                  <div
                    key={g.goal_id}
                    onClick={() => navigate(coachGoalDetailPath(g.goal_id))}
                    className="group flex flex-col justify-between rounded-xl border border-slate-200 bg-white p-5 shadow-sm hover:border-slate-400 hover:shadow transition-all cursor-pointer"
                  >
                    <div>
                      <div className="flex items-start justify-between gap-2 mb-2">
                        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold text-emerald-800">
                          アクティブ
                        </span>
                        <ChevronRight className="h-4 w-4 text-slate-400 group-hover:text-slate-700 transition-colors" />
                      </div>

                      <h3 className="text-base font-bold text-slate-900 group-hover:text-indigo-900 line-clamp-2">
                        {g.statement}
                      </h3>

                      <p className="mt-1.5 text-xs text-slate-600 line-clamp-2">
                        <span className="font-medium text-slate-700">理由:</span>{" "}
                        {g.reason}
                      </p>
                    </div>

                    <div className="mt-4 pt-3 border-t border-slate-100 flex items-center justify-between">
                      <div className="flex items-center gap-1.5 overflow-hidden">
                        <span className="text-[11px] font-medium text-slate-500 shrink-0">
                          現在の Focus:
                        </span>
                        {g.active_focus ? (
                          <span className="text-xs font-medium text-slate-800 truncate bg-slate-100 px-2 py-0.5 rounded">
                            {g.active_focus.name}
                          </span>
                        ) : (
                          <span className="text-xs text-amber-600 italic">
                            未選択
                          </span>
                        )}
                      </div>

                      <span className="text-[10px] text-slate-400 shrink-0 ml-2">
                        {new Date(g.created_at).toLocaleDateString("ja-JP")}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* History / Archive Toggle Section */}
          {(pausedGoals.length > 0 || endedGoals.length > 0) && (
            <div className="pt-4 border-t border-slate-200">
              <button
                type="button"
                onClick={() => setShowArchive((prev) => !prev)}
                className="inline-flex items-center gap-2 text-xs font-semibold text-slate-700 hover:text-slate-900"
              >
                <Archive className="h-4 w-4 text-slate-500" />
                休止・アーカイブ履歴 ({pausedGoals.length + endedGoals.length})
                <span className="text-slate-400">{showArchive ? "▲" : "▼"}</span>
              </button>

              {showArchive && (
                <div className="mt-4 space-y-4">
                  {pausedGoals.length > 0 && (
                    <div>
                      <h3 className="text-xs font-semibold text-amber-800 mb-2 flex items-center gap-1.5">
                        <PauseCircle className="h-3.5 w-3.5" />
                        休止中の Goal ({pausedGoals.length})
                      </h3>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        {pausedGoals.map((g) => (
                          <Link
                            key={g.goal_id}
                            to={coachGoalDetailPath(g.goal_id)}
                            className="block rounded-lg border border-amber-200 bg-amber-50/40 p-4 hover:border-amber-400 transition-colors"
                          >
                            <h4 className="text-sm font-semibold text-slate-800">
                              {g.statement}
                            </h4>
                            <p className="mt-1 text-xs text-slate-600 line-clamp-1">
                              {g.reason}
                            </p>
                          </Link>
                        ))}
                      </div>
                    </div>
                  )}

                  {endedGoals.length > 0 && (
                    <div>
                      <h3 className="text-xs font-semibold text-slate-600 mb-2 flex items-center gap-1.5">
                        <Flag className="h-3.5 w-3.5" />
                        終了（アーカイブ）された Goal ({endedGoals.length})
                      </h3>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        {endedGoals.map((g) => (
                          <Link
                            key={g.goal_id}
                            to={coachGoalDetailPath(g.goal_id)}
                            className="block rounded-lg border border-slate-200 bg-slate-100/60 p-4 hover:border-slate-300 transition-colors"
                          >
                            <h4 className="text-sm font-semibold text-slate-700">
                              {g.statement}
                            </h4>
                            <p className="mt-1 text-xs text-slate-500 line-clamp-1">
                              {g.reason}
                            </p>
                          </Link>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Goal Create Modal */}
      <GoalFormModal
        isOpen={isCreateModalOpen}
        onClose={() => setIsCreateModalOpen(false)}
        onCreated={(newGoal) => {
          navigate(coachGoalDetailPath(newGoal.goal_id));
        }}
      />
    </div>
  );
}
