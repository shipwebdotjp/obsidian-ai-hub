import { Link, useParams } from "react-router-dom";
import { ROUTES } from "../../constants/routes";
import TaskAgentDetailPanel from "./TaskAgentDetailPanel";

/**
 * 単体ルート（/task-agent/:taskId）用の薄いラッパー。
 * 一覧・詳細の同時表示は TaskAgentPage が担当する。
 */
export default function TaskAgentDetailPage() {
  const { taskId } = useParams<{ taskId: string }>();
  if (!taskId) {
    return (
      <div className="bg-slate-50 p-4">
        <p className="rounded border border-rose-300 bg-rose-50 p-2 text-sm text-rose-700">
          Taskが見つかりません
        </p>
        <Link
          to={ROUTES.TASK_AGENT}
          className="mt-2 inline-block text-sm text-blue-600"
        >
          ← 一覧
        </Link>
      </div>
    );
  }
  return <TaskAgentDetailPanel taskId={taskId} />;
}
