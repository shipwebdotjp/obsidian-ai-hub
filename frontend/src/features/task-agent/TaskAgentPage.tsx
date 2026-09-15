import { useState } from "react";
import { useParams } from "react-router-dom";
import TaskAgentDetailPanel from "./TaskAgentDetailPanel";
import TaskAgentListPage from "./TaskAgentListPage";

/**
 * Task Agent のマスター・詳細ページ。
 *
 * - PC 幅（lg 以上）: 左ペインに Task 一覧、右ペインに選択中 Task の詳細を
 *   同時表示する（HitlPage / MemoryPage と同じブレークポイント・配色）。
 * - モバイル幅: 一覧→詳細の 1 ペイン表示。詳細表示中は一覧を hidden にし、
 *   詳細側の「← 一覧」（lg:hidden）で戻る。
 * - 詳細の通常ロード（ポーリング含む）では一覧を再取得しない。
 *   approve/reject/cancel/replan などのデータ変更操作時のみ再取得する。
 */
export default function TaskAgentPage() {
  const { taskId } = useParams<{ taskId: string }>();
  const [refreshKey, setRefreshKey] = useState(0);

  return (
    <div className="flex h-full flex-col bg-slate-50 lg:flex-row">
      <div
        className={`h-full w-full min-h-0 shrink-0 border-slate-200 bg-white lg:w-96 lg:border-r ${
          taskId ? "hidden" : "flex flex-col"
        } lg:flex lg:flex-col`}
      >
        <TaskAgentListPage
          selectedTaskId={taskId ?? null}
          refreshKey={refreshKey}
        />
      </div>
      <div
        className={`min-h-0 min-w-0 flex-1 overflow-hidden bg-slate-50 ${
          taskId ? "flex flex-col" : "hidden"
        } lg:flex lg:flex-col`}
      >
        {taskId ? (
          <TaskAgentDetailPanel
            taskId={taskId}
            onTaskChanged={() => setRefreshKey((v) => v + 1)}
          />
        ) : (
          <p className="p-6 text-sm text-slate-500">
            一覧からTaskを選択してください。
          </p>
        )}
      </div>
    </div>
  );
}
