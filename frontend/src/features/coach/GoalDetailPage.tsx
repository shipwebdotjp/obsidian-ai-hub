import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  endCoachGoal,
  fetchCoachGoalDetail,
  pauseCoachGoal,
  resumeCoachGoal,
  updateCoachGoal,
} from "./coachApi";
import { CoachGoalDetail } from "./types";
import FocusSection from "./FocusSection";
import ReflectionFormModal from "./ReflectionFormModal";
import CoachThreadTimeline from "./CoachThreadTimeline";
import { ROUTES } from "../../constants/routes";
import {
  ArrowLeft,
  ChevronRight,
  Edit2,
  Flag,
  PauseCircle,
  PlayCircle,
  RotateCcw,
  Target,
  Check,
  X,
} from "lucide-react";

export default function GoalDetailPage() {
  const { goalId } = useParams<{ goalId: string }>();
  const [goal, setGoal] = useState<CoachGoalDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [timelineKey, setTimelineKey] = useState(0);

  // Edit Goal modal/inline state
  const [isEditingGoal, setIsEditingGoal] = useState(false);
  const [editStatement, setEditStatement] = useState("");
  const [editReason, setEditReason] = useState("");

  // Reflection modal
  const [isReflectionOpen, setIsReflectionOpen] = useState(false);

  const loadGoal = async () => {
    if (!goalId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await fetchCoachGoalDetail(goalId);
      setGoal(data);
      setTimelineKey((k) => k + 1);
    } catch (err: any) {
      setError(err?.message || "Goal の読み込みに失敗しました。");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadGoal();
  }, [goalId]);

  if (loading && !goal) {
    return (
      <div className="flex h-full items-center justify-center text-xs text-slate-500">
        長期目標を読み込み中…
      </div>
    );
  }

  if (error || !goal) {
    return (
      <div className="p-6">
        <Link
          to={ROUTES.COACH}
          className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-800 mb-4"
        >
          <ArrowLeft className="h-3.5 w-3.5" /> コーチ一覧へ戻る
        </Link>
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-xs text-red-700">
          {error || "指定された長期目標が見つかりませんでした。"}
        </div>
      </div>
    );
  }

  const isEnded = goal.status === "ended";
  const isPaused = goal.status === "paused";
  const isActive = goal.status === "active";
  const activeFocus = goal.active_focus;

  const handleStartEditGoal = () => {
    if (isEnded) return;
    setEditStatement(goal.statement);
    setEditReason(goal.reason);
    setIsEditingGoal(true);
  };

  const handleSaveGoal = async () => {
    if (!editStatement.trim() || !editReason.trim() || isEnded) return;
    try {
      setError(null);
      await updateCoachGoal(goal.goal_id, {
        statement: editStatement.trim(),
        reason: editReason.trim(),
      });
      setIsEditingGoal(false);
      loadGoal();
    } catch (err: any) {
      setError(err?.message || "Goal の更新に失敗しました。");
    }
  };

  const handlePauseGoal = async () => {
    try {
      setError(null);
      await pauseCoachGoal(goal.goal_id);
      loadGoal();
    } catch (err: any) {
      setError(err?.message || "Goal の休止に失敗しました。");
    }
  };

  const handleResumeGoal = async () => {
    try {
      setError(null);
      await resumeCoachGoal(goal.goal_id);
      loadGoal();
    } catch (err: any) {
      setError(err?.message || "Goal の再開に失敗しました。");
    }
  };

  const handleEndGoal = async () => {
    if (!window.confirm("この Goal を終了（アーカイブ）しますか？ Phase 1 では終了後の再開・編集はできません。")) {
      return;
    }
    try {
      setError(null);
      await endCoachGoal(goal.goal_id);
      loadGoal();
    } catch (err: any) {
      setError(err?.message || "Goal の終了に失敗しました。");
    }
  };

  return (
    <div className="h-full overflow-y-auto bg-slate-50 p-6 space-y-6">
      {/* Breadcrumb */}
      <div className="flex items-center gap-1.5 text-xs text-slate-500">
        <Link to={ROUTES.COACH} className="hover:text-slate-800">
          長期目標コーチ
        </Link>
        <ChevronRight className="h-3.5 w-3.5 text-slate-400" />
        <span className="font-medium text-slate-800 truncate max-w-xs">
          {goal.statement}
        </span>
      </div>

      {error && (
        <div className="rounded-lg bg-red-50 p-3 text-xs text-red-700">
          {error}
        </div>
      )}

      {/* Main Goal Header Card */}
      <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-col lg:flex-row lg:items-start justify-between gap-4 border-b border-slate-200 pb-5">
          <div className="space-y-3 flex-1">
            <div className="flex items-center gap-2">
              {isActive ? (
                <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-semibold text-emerald-800">
                  <Target className="h-3.5 w-3.5" /> アクティブ
                </span>
              ) : isPaused ? (
                <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-semibold text-amber-800">
                  <PauseCircle className="h-3.5 w-3.5" /> 休止中
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 rounded-full bg-slate-200 px-2.5 py-0.5 text-xs font-semibold text-slate-700">
                  <Flag className="h-3.5 w-3.5" /> 終了（アーカイブ）
                </span>
              )}

              {!isEnded && !isEditingGoal && (
                <button
                  type="button"
                  onClick={handleStartEditGoal}
                  className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
                  title="Goalの編集"
                >
                  <Edit2 className="h-3.5 w-3.5" />
                </button>
              )}
            </div>

            {isEditingGoal ? (
              <div className="space-y-3 pt-1">
                <div>
                  <label className="block text-[11px] font-medium text-slate-500 mb-0.5">
                    到達像 (statement)
                  </label>
                  <textarea
                    rows={2}
                    value={editStatement}
                    onChange={(e) => setEditStatement(e.target.value)}
                    className="w-full rounded border border-slate-300 p-2 text-sm focus:border-slate-800 focus:outline-none"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-medium text-slate-500 mb-0.5">
                    理由 (reason)
                  </label>
                  <textarea
                    rows={2}
                    value={editReason}
                    onChange={(e) => setEditReason(e.target.value)}
                    className="w-full rounded border border-slate-300 p-2 text-sm focus:border-slate-800 focus:outline-none"
                  />
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={handleSaveGoal}
                    className="inline-flex items-center gap-1 rounded bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800"
                  >
                    <Check className="h-3.5 w-3.5" /> 保存
                  </button>
                  <button
                    type="button"
                    onClick={() => setIsEditingGoal(false)}
                    className="inline-flex items-center gap-1 rounded px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-100"
                  >
                    <X className="h-3.5 w-3.5" /> キャンセル
                  </button>
                </div>
              </div>
            ) : (
              <div>
                <h1 className="text-lg font-bold text-slate-900">
                  {goal.statement}
                </h1>
                <p className="mt-1 text-xs text-slate-600">
                  <span className="font-medium text-slate-700">理由:</span>{" "}
                  {goal.reason}
                </p>
              </div>
            )}
          </div>

          {/* Goal Action controls */}
          <div className="flex flex-wrap items-center gap-2 shrink-0">
            {isActive && (
              <button
                type="button"
                onClick={handlePauseGoal}
                className="inline-flex items-center gap-1 rounded border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-100"
              >
                <PauseCircle className="h-3.5 w-3.5" /> Goal を休止
              </button>
            )}

            {isPaused && (
              <button
                type="button"
                onClick={handleResumeGoal}
                className="inline-flex items-center gap-1 rounded bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700"
              >
                <PlayCircle className="h-3.5 w-3.5" /> Goal を再開
              </button>
            )}

            {!isEnded && (
              <button
                type="button"
                onClick={handleEndGoal}
                className="inline-flex items-center gap-1 rounded border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-red-50 hover:text-red-700 hover:border-red-200"
              >
                <Flag className="h-3.5 w-3.5" /> Goal を終了
              </button>
            )}
          </div>
        </div>

        {/* Reflection Action CTA */}
        <div className="mt-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-lg bg-indigo-50/70 p-4 border border-indigo-100">
          <div>
            <span className="text-xs font-semibold text-indigo-950 block">
              週次 Reflection（振り返り）
            </span>
            <span className="text-[11px] text-indigo-700">
              {isActive && activeFocus
                ? `現在の Focus 「${activeFocus.name}」について週次振り返りを記録します。`
                : isPaused
                ? "Goal が休止中のため、Reflection は登録できません。"
                : isEnded
                ? "Goal が終了したため、閲覧専用となります。"
                : "Active な Focus が選択されていません。下記 Focus セクションから選択してください。"}
            </span>
          </div>

          {isActive && activeFocus && (
            <button
              type="button"
              onClick={() => setIsReflectionOpen(true)}
              className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-medium text-white shadow-sm hover:bg-indigo-700 shrink-0"
            >
              <RotateCcw className="h-4 w-4" /> 週次 Reflection を記録
            </button>
          )}
        </div>
      </div>

      {/* Focuses Management Section */}
      <FocusSection
        goal={goal}
        onGoalUpdated={(updated) => {
          setGoal(updated);
          setTimelineKey((k) => k + 1);
        }}
      />

      {/* Coach Thread Events Timeline Section */}
      <CoachThreadTimeline goalId={goal.goal_id} refreshKey={timelineKey} />

      {/* Reflection Form Modal */}
      {activeFocus && (
        <ReflectionFormModal
          isOpen={isReflectionOpen}
          onClose={() => setIsReflectionOpen(false)}
          goal={goal}
          activeFocus={activeFocus}
          onSubmitted={() => {
            loadGoal();
          }}
        />
      )}
    </div>
  );
}
