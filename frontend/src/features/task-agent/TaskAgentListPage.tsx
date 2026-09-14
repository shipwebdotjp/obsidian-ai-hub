import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, listTaskAgentTasks } from "../../api/client";
import type { TaskAgentTask } from "../../api/types";
import { taskAgentDetailPath } from "../../constants/routes";
import { formatDateTime } from "../../utils/date";
import {
  NON_TERMINAL_FILTER,
  TERMINAL_STATUSES,
  taskStatusBadgeClass,
  taskStatusLabel,
} from "./taskAgentLabels";

const TERMINAL_SET = new Set<string>(TERMINAL_STATUSES);
const STATUS_FILTERS = [
  { value: "", label: "すべて" },
  { value: NON_TERMINAL_FILTER, label: "未終端" },
  ...[
    "queued",
    "planning",
    "waiting_user",
    "waiting_approval",
    "ready",
    "running",
    "waiting_reapproval",
    "cancelling",
    "interrupted",
    ...TERMINAL_STATUSES,
  ].map((status) => ({ value: status, label: taskStatusLabel(status) })),
];

export default function TaskAgentListPage() {
  const [filter, setFilter] = useState("");
  const [items, setItems] = useState<TaskAgentTask[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const singleStatus =
        filter && filter !== NON_TERMINAL_FILTER ? filter : undefined;
      const res = await listTaskAgentTasks({
        status: singleStatus,
        limit: 100,
      });
      let visible = res.items;
      if (filter === NON_TERMINAL_FILTER) {
        visible = res.items.filter((t) => !TERMINAL_SET.has(t.status));
      }
      setItems(visible);
      setTotal(filter === NON_TERMINAL_FILTER ? visible.length : res.total);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "読み込みに失敗しました");
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const head = (t: TaskAgentTask) =>
    t.prompt_text.length > 60 ? `${t.prompt_text.slice(0, 60)}…` : t.prompt_text;

  return (
    <div className="flex h-full flex-col bg-slate-50">
      <header className="border-b border-slate-200 bg-white px-4 py-3">
        <h1 className="text-lg font-semibold">Task Agent</h1>
        <div className="mt-2 flex items-center gap-2">
          <select
            aria-label="ステータスフィルター"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="cursor-pointer rounded border border-slate-300 px-2 py-1 text-sm"
          >
            {STATUS_FILTERS.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => void reload()}
            className="cursor-pointer rounded bg-slate-900 px-3 py-1 text-sm text-white"
          >
            再読込
          </button>
          <span className="text-sm text-slate-500">{total} 件</span>
        </div>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {loading && <p className="p-4 text-sm text-slate-500">読み込み中…</p>}
        {error && (
          <p className="m-4 rounded border border-rose-300 bg-rose-50 p-2 text-sm text-rose-700">
            {error}
          </p>
        )}
        {!loading && !error && items.length === 0 && (
          <p className="p-4 text-sm text-slate-500">Taskがありません</p>
        )}
        <ul className="divide-y divide-slate-100">
          {items.map((t) => (
            <li key={t.task_id}>
              <Link
                to={taskAgentDetailPath(t.task_id)}
                data-testid="task-agent-row"
                className="block cursor-pointer px-4 py-2 hover:bg-slate-50"
              >
                <span className={taskStatusBadgeClass(t.status)}>
                  {taskStatusLabel(t.status)}
                </span>
                <span className="ml-2 text-sm">{head(t)}</span>
                <span className="ml-2 text-xs text-slate-400">
                  {formatDateTime(t.created_at)}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
