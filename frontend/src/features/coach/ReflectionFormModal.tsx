import { useEffect, useState } from "react";
import {
  createCoachReflection,
  fetchCoachReflectionsByFocus,
  updateCoachReflection,
} from "./coachApi";
import {
  CoachDecisionType,
  CoachFocus,
  CoachGoalDetail,
  CoachWeeklyReflection,
} from "./types";
import { X, Calendar } from "lucide-react";

interface ReflectionFormModalProps {
  isOpen: boolean;
  onClose: () => void;
  goal: CoachGoalDetail;
  activeFocus: CoachFocus;
  onSubmitted: () => void;
}

function getPastISOWeekMondays(numWeeks = 12): string[] {
  const mondays: string[] = [];
  const now = new Date();
  const jstDate = new Date(
    now.toLocaleString("en-US", { timeZone: "Asia/Tokyo" })
  );
  const day = jstDate.getDay();
  const diffToMonday = (day + 6) % 7;
  const currentMonday = new Date(jstDate);
  currentMonday.setDate(jstDate.getDate() - diffToMonday);

  for (let i = 0; i < numWeeks; i++) {
    const d = new Date(currentMonday);
    d.setDate(currentMonday.getDate() - i * 7);
    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const dd = String(d.getDate()).padStart(2, "0");
    mondays.push(`${yyyy}-${mm}-${dd}`);
  }
  return mondays;
}

export default function ReflectionFormModal({
  isOpen,
  onClose,
  goal,
  activeFocus,
  onSubmitted,
}: ReflectionFormModalProps) {
  const weekOptions = getPastISOWeekMondays(12);
  const [selectedWeek, setSelectedWeek] = useState<string>(weekOptions[0]);

  const [existingReflections, setExistingReflections] = useState<
    CoachWeeklyReflection[]
  >([]);
  const [existingReflection, setExistingReflection] =
    useState<CoachWeeklyReflection | null>(null);

  const [workedWell, setWorkedWell] = useState("");
  const [difficultReason, setDifficultReason] = useState("");
  const [learnings, setLearnings] = useState("");
  const [nextWeekScope, setNextWeekScope] = useState("");
  const [decisionType, setDecisionType] =
    useState<CoachDecisionType>("continue");
  const [targetFocusId, setTargetFocusId] = useState<string>("");

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Candidate Focuses for "change" decision
  const candidateFocuses = goal.focuses.filter(
    (f) => f.focus_id !== activeFocus.focus_id && f.status === "candidate"
  );

  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    fetchCoachReflectionsByFocus(activeFocus.focus_id)
      .then((items) => {
        if (!cancelled) {
          setExistingReflections(items);
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [isOpen, activeFocus.focus_id]);

  useEffect(() => {
    const found = existingReflections.find(
      (r) => r.iso_week_monday === selectedWeek
    );
    if (found) {
      setExistingReflection(found);
      setWorkedWell(found.worked_well || "");
      setDifficultReason(found.difficult_reason || "");
      setLearnings(found.learnings || "");
      setNextWeekScope(found.next_week_scope || "");
      setDecisionType(found.decision_type);
      setTargetFocusId(found.target_focus_id || "");
    } else {
      setExistingReflection(null);
      setWorkedWell("");
      setDifficultReason("");
      setLearnings("");
      setNextWeekScope("");
      setDecisionType("continue");
      setTargetFocusId(candidateFocuses[0]?.focus_id || "");
    }
  }, [selectedWeek, existingReflections]);

  if (!isOpen) return null;

  const isEditMode = !!existingReflection;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (decisionType === "narrow" && !nextWeekScope.trim()) {
      setError("decision_typeが 'narrow' の場合は「次週の範囲」の入力が必須です。");
      return;
    }

    if (decisionType === "change" && !targetFocusId) {
      setError("別の Focus への切り替え先を選択してください。");
      return;
    }

    setLoading(true);
    try {
      if (isEditMode) {
        // Body update mode
        await updateCoachReflection(existingReflection.reflection_id, {
          worked_well: workedWell.trim() || undefined,
          difficult_reason: difficultReason.trim() || undefined,
          learnings: learnings.trim() || undefined,
          next_week_scope: nextWeekScope.trim() || undefined,
        });
      } else {
        // Create mode
        await createCoachReflection(activeFocus.focus_id, {
          focus_id: activeFocus.focus_id,
          iso_week_monday: selectedWeek,
          worked_well: workedWell.trim() || undefined,
          difficult_reason: difficultReason.trim() || undefined,
          learnings: learnings.trim() || undefined,
          next_week_scope: nextWeekScope.trim() || undefined,
          decision_type: decisionType,
          target_focus_id:
            decisionType === "change" ? targetFocusId : undefined,
        });
      }
      onSubmitted();
      onClose();
    } catch (err: any) {
      setError(err?.message || "Reflection の保存に失敗しました。");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
      <div className="w-full max-w-xl max-h-[90vh] flex flex-col rounded-xl bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-slate-200 p-4 shrink-0">
          <div>
            <h2 className="text-base font-semibold text-slate-800">
              週次 Reflection（振り返り）
            </h2>
            <p className="text-xs text-slate-500">
              Focus: <span className="font-medium text-slate-800">{activeFocus.name}</span>
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="p-5 overflow-y-auto flex-1 space-y-4">
          {error && (
            <div className="rounded bg-red-50 p-3 text-xs text-red-700">
              {error}
            </div>
          )}

          <div className="flex items-center gap-2 rounded-lg bg-slate-50 p-3 border border-slate-200">
            <Calendar className="h-4 w-4 text-slate-500 shrink-0" />
            <label className="text-xs font-medium text-slate-700 shrink-0">
              対象週 (ISO週月曜日):
            </label>
            <select
              value={selectedWeek}
              onChange={(e) => setSelectedWeek(e.target.value)}
              className="flex-1 rounded border border-slate-300 p-1.5 text-xs bg-white focus:border-slate-800 focus:outline-none"
            >
              {weekOptions.map((w, idx) => (
                <option key={w} value={w}>
                  {w} 週 {idx === 0 ? "（今週）" : ""}
                </option>
              ))}
            </select>
          </div>

          {isEditMode && (
            <div className="rounded bg-amber-50 p-2.5 text-xs text-amber-800 border border-amber-200">
              この週の Reflection は登録済みです。本文と次週の範囲のみ編集できます（決定種別は変更不可）。
            </div>
          )}

          <form id="reflection-form" onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-slate-700 mb-1">
                うまくいったこと・近づけたと感じた場面 (worked_well)
              </label>
              <textarea
                rows={2}
                value={workedWell}
                onChange={(e) => setWorkedWell(e.target.value)}
                placeholder="例: 火曜日に自分から声をかけて質問できた"
                className="w-full rounded border border-slate-300 p-2 text-xs focus:border-slate-800 focus:outline-none"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-700 mb-1">
                難しかったこと・できなかった理由 (difficult_reason)
              </label>
              <textarea
                rows={2}
                value={difficultReason}
                onChange={(e) => setDifficultReason(e.target.value)}
                placeholder="例: 木曜日は忙しくて集中して話を聞く時間が取れなかった"
                className="w-full rounded border border-slate-300 p-2 text-xs focus:border-slate-800 focus:outline-none"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-700 mb-1">
                気づき・学び (learnings)
              </label>
              <textarea
                rows={2}
                value={learnings}
                onChange={(e) => setLearnings(e.target.value)}
                placeholder="例: 朝一番にひと声をかけておくとその後の対話がスムーズになる"
                className="w-full rounded border border-slate-300 p-2 text-xs focus:border-slate-800 focus:outline-none"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-700 mb-1">
                次週の決定種別 (decision_type) {isEditMode && "（変更不可）"}
              </label>
              <div className="grid grid-cols-2 gap-2">
                {[
                  {
                    type: "continue",
                    label: "継続 (continue)",
                    desc: "この Focus を維持して続ける",
                  },
                  {
                    type: "narrow",
                    label: "小さくする (narrow)",
                    desc: "Focus を維持し、次週の範囲を小さく絞る",
                  },
                  {
                    type: "change",
                    label: "切替 (change)",
                    desc: "同じ Goal の別 Focus 候補へ切り替える",
                  },
                  {
                    type: "pause",
                    label: "休止 (pause)",
                    desc: "現在の Focus を休止状態にする",
                  },
                ].map((opt) => (
                  <label
                    key={opt.type}
                    className={`flex flex-col p-2.5 rounded-lg border cursor-pointer transition-colors ${
                      decisionType === opt.type
                        ? "border-slate-800 bg-slate-50"
                        : "border-slate-200 bg-white hover:bg-slate-50"
                    } ${isEditMode ? "opacity-60 cursor-not-allowed" : ""}`}
                  >
                    <div className="flex items-center gap-1.5 font-medium text-xs text-slate-800">
                      <input
                        type="radio"
                        name="decision_type"
                        disabled={isEditMode}
                        value={opt.type}
                        checked={decisionType === opt.type}
                        onChange={() => setDecisionType(opt.type as CoachDecisionType)}
                        className="text-slate-900 focus:ring-slate-800"
                      />
                      {opt.label}
                    </div>
                    <span className="text-[10px] text-slate-500 mt-1 pl-5">
                      {opt.desc}
                    </span>
                  </label>
                ))}
              </div>
            </div>

            {decisionType === "change" && !isEditMode && (
              <div className="rounded-lg bg-indigo-50/60 p-3 border border-indigo-100">
                <label className="block text-xs font-medium text-indigo-900 mb-1">
                  切替先の Focus 候補を選択 <span className="text-red-500">*</span>
                </label>
                {candidateFocuses.length === 0 ? (
                  <p className="text-xs text-red-600">
                    切替可能な Focus 候補がありません。先に Goal 詳細画面で Focus 候補を追加してください。
                  </p>
                ) : (
                  <select
                    value={targetFocusId}
                    onChange={(e) => setTargetFocusId(e.target.value)}
                    className="w-full rounded border border-slate-300 p-2 text-xs bg-white focus:border-slate-800 focus:outline-none"
                  >
                    {candidateFocuses.map((cf) => (
                      <option key={cf.focus_id} value={cf.focus_id}>
                        {cf.name}
                      </option>
                    ))}
                  </select>
                )}
              </div>
            )}

            <div>
              <label className="block text-xs font-medium text-slate-700 mb-1">
                次週の範囲・小さくする具体策 (next_week_scope)
                {decisionType === "narrow" && (
                  <span className="text-red-500"> * (narrow 選択時は必須)</span>
                )}
              </label>
              <textarea
                rows={2}
                value={nextWeekScope}
                onChange={(e) => setNextWeekScope(e.target.value)}
                placeholder="例: まず火曜日の朝の1回だけに絞って試す"
                className="w-full rounded border border-slate-300 p-2 text-xs focus:border-slate-800 focus:outline-none"
              />
            </div>
          </form>
        </div>

        <div className="flex justify-end gap-2 border-t border-slate-200 p-4 shrink-0 bg-slate-50 rounded-b-xl">
          <button
            type="button"
            onClick={onClose}
            className="rounded px-4 py-2 text-xs font-medium text-slate-600 hover:bg-slate-200"
          >
            キャンセル
          </button>
          <button
            type="submit"
            form="reflection-form"
            disabled={loading}
            className="rounded bg-slate-900 px-4 py-2 text-xs font-medium text-white hover:bg-slate-800 disabled:opacity-50"
          >
            {loading
              ? "保存中…"
              : isEditMode
              ? "Reflection を更新"
              : "Reflection を保存"}
          </button>
        </div>
      </div>
    </div>
  );
}
