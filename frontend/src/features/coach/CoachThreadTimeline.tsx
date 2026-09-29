import { useEffect, useState } from "react";
import { fetchCoachThreadEvents } from "./coachApi";
import { CoachThreadEvent } from "./types";
import {
  Calendar,
  CheckCircle2,
  Clock,
  Edit2,
  Flag,
  PauseCircle,
  PlayCircle,
  RotateCcw,
  Target,
} from "lucide-react";

interface CoachThreadTimelineProps {
  goalId: string;
  refreshKey?: number;
}

export default function CoachThreadTimeline({
  goalId,
  refreshKey,
}: CoachThreadTimelineProps) {
  const [events, setEvents] = useState<CoachThreadEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const limit = 20;
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadEvents = async (off = 0) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchCoachThreadEvents(goalId, limit, off);
      setEvents(res.items);
      setTotal(res.total);
      setOffset(off);
    } catch (err: any) {
      setError(err?.message || "タイムラインの読み込みに失敗しました。");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadEvents(0);
  }, [goalId, refreshKey]);

  const renderEventIcon = (eventType: string) => {
    switch (eventType) {
      case "goal_created":
        return <Target className="h-4 w-4 text-indigo-600" />;
      case "goal_paused":
        return <PauseCircle className="h-4 w-4 text-amber-600" />;
      case "goal_resumed":
        return <PlayCircle className="h-4 w-4 text-emerald-600" />;
      case "goal_ended":
        return <Flag className="h-4 w-4 text-slate-500" />;
      case "focus_created":
        return <Clock className="h-4 w-4 text-blue-500" />;
      case "focus_activated":
        return <CheckCircle2 className="h-4 w-4 text-emerald-600" />;
      case "focus_paused":
        return <PauseCircle className="h-4 w-4 text-slate-400" />;
      case "focus_demoted":
        return <Clock className="h-4 w-4 text-amber-600" />;
      case "focus_renamed":
        return <Edit2 className="h-4 w-4 text-slate-500" />;
      case "reflection_created":
        return <RotateCcw className="h-4 w-4 text-purple-600" />;
      default:
        return <Clock className="h-4 w-4 text-slate-400" />;
    }
  };

  const renderEventTitle = (evt: CoachThreadEvent) => {
    const p = evt.payload || {};
    switch (evt.event_type) {
      case "goal_created":
        return "Goal を作成しました";
      case "goal_paused":
        return "Goal を休止しました";
      case "goal_resumed":
        return "Goal を再開しました";
      case "goal_ended":
        return "Goal を終了（アーカイブ）しました";
      case "focus_created":
        return `Focus 候補「${p.focus_name || ""}」を追加しました`;
      case "focus_activated":
        return `Focus「${p.focus_name || ""}」をアクティブに選択しました`;
      case "focus_paused":
        return `Focus「${p.focus_name || ""}」を休止しました`;
      case "focus_demoted":
        return `Focus「${p.focus_name || ""}」を候補に戻しました`;
      case "focus_renamed":
        return `Focus を「${p.old_name || ""}」から「${p.new_name || ""}」に変更しました`;
      case "reflection_created": {
        const decLabels: Record<string, string> = {
          continue: "継続",
          narrow: "小さくする",
          change: "切替",
          pause: "休止",
        };
        const decLabel = decLabels[p.decision_type] || p.decision_type;
        return `${p.iso_week_monday || ""} 週の Reflection 記録（決定: ${decLabel}）`;
      }
      default:
        return evt.event_type;
    }
  };

  const renderEventBody = (evt: CoachThreadEvent) => {
    const p = evt.payload || {};
    if (evt.event_type === "goal_created") {
      return (
        <div className="mt-1 text-xs text-slate-600 space-y-1">
          <p>
            <span className="font-medium text-slate-700">到達像:</span>{" "}
            {p.goal_statement}
          </p>
          {p.goal_reason && (
            <p>
              <span className="font-medium text-slate-700">理由:</span>{" "}
              {p.goal_reason}
            </p>
          )}
        </div>
      );
    }

    if (evt.event_type === "reflection_created") {
      return (
        <div className="mt-2 rounded-lg bg-slate-50 p-3 text-xs text-slate-700 space-y-1.5 border border-slate-200">
          {p.worked_well && (
            <p>
              <span className="font-medium text-slate-900">できたこと:</span>{" "}
              {p.worked_well}
            </p>
          )}
          {p.difficult_reason && (
            <p>
              <span className="font-medium text-slate-900">難しかったこと:</span>{" "}
              {p.difficult_reason}
            </p>
          )}
          {p.learnings && (
            <p>
              <span className="font-medium text-slate-900">気づき:</span>{" "}
              {p.learnings}
            </p>
          )}
          {p.next_week_scope && (
            <p>
              <span className="font-medium text-slate-900">次週の試行範囲:</span>{" "}
              {p.next_week_scope}
            </p>
          )}
          {p.decision_type === "change" && p.target_focus_name && (
            <p className="text-indigo-700 font-medium pt-1">
              切替先 Focus: 「{p.target_focus_name}」
            </p>
          )}
        </div>
      );
    }

    return null;
  };

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-800">
            Coach Thread（経過タイムライン）
          </h3>
          <p className="text-xs text-slate-500">
            Goal・Focus の選択・振り返りの時系列記録です（全 {total} 件）。
          </p>
        </div>
      </div>

      {error && (
        <div className="mb-3 rounded bg-red-50 p-2 text-xs text-red-700">
          {error}
        </div>
      )}

      {loading && events.length === 0 ? (
        <div className="py-6 text-center text-xs text-slate-400">
          タイムラインを読み込み中…
        </div>
      ) : events.length === 0 ? (
        <div className="py-6 text-center text-xs text-slate-400">
          記録されたイベントがありません。
        </div>
      ) : (
        <div className="relative pl-6 space-y-6 border-l-2 border-slate-200 ml-3 my-2">
          {events.map((evt) => (
            <div key={evt.event_id} className="relative">
              <div className="absolute -left-[31px] top-0 flex h-6 w-6 items-center justify-center rounded-full bg-white border border-slate-300 shadow-sm">
                {renderEventIcon(evt.event_type)}
              </div>

              <div>
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold text-slate-800">
                    {renderEventTitle(evt)}
                  </span>
                  <span className="text-[10px] text-slate-400">
                    {new Date(evt.created_at).toLocaleString("ja-JP")}
                  </span>
                </div>
                {renderEventBody(evt)}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Pagination */}
      {total > limit && (
        <div className="mt-4 flex items-center justify-between border-t border-slate-200 pt-3">
          <button
            type="button"
            disabled={offset === 0 || loading}
            onClick={() => loadEvents(Math.max(0, offset - limit))}
            className="rounded px-3 py-1 text-xs text-slate-600 hover:bg-slate-100 disabled:opacity-40"
          >
            前へ
          </button>
          <span className="text-xs text-slate-500">
            {offset + 1} - {Math.min(total, offset + limit)} / {total} 件
          </span>
          <button
            type="button"
            disabled={offset + limit >= total || loading}
            onClick={() => loadEvents(offset + limit)}
            className="rounded px-3 py-1 text-xs text-slate-600 hover:bg-slate-100 disabled:opacity-40"
          >
            次へ
          </button>
        </div>
      )}
    </div>
  );
}
