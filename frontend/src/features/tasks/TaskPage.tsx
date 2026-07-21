import { useEffect, useState, useRef } from "react";
import {
  getTaskConfig,
  updateTaskConfig,
  previewCommand,
} from "../../api/client";
import type { TaskItem, CommandSegment } from "../../api/types";
import { ApiError } from "../../api/client";

const PRESET_OPTIONS = [
  { name: "Inbox merge", flag: "--merge-inbox" },
  { name: "日サマリ", flag: "--summerize-day" },
  { name: "週サマリ", flag: "--summerize-week" },
  { name: "月サマリ", flag: "--summerize-month" },
  { name: "目標作成", flag: "--make-target" },
  { name: "カレンダー通知", flag: "--notify-calendar-event" },
  { name: "今日の予定通知", flag: "--notify-today-schedule" },
  { name: "Backup", flag: "--backup" },
  { name: "Vault sync", flag: "--sync-vault" },
  { name: "People sync", flag: "--sync-people" },
  { name: "Knowledge sync", flag: "--sync-knowledge" },
  { name: "Review draft", flag: "--review-draft" },
  { name: "Memory extract", flag: "--memory-extract" },
  { name: "Research suggestion", flag: "--suggest-research-theme" },
  { name: "Activity log", flag: "--log-activity" },
];

export default function TaskPage() {
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [filepath, setFilepath] = useState("");
  const [revision, setRevision] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [localhostBlock, setLocalhostBlock] = useState(false);

  // Form State
  const [editingTask, setEditingTask] = useState<TaskItem | null>(null);
  const [isNew, setIsNew] = useState(false);
  const [formId, setFormId] = useState("");
  const [formEnabled, setFormEnabled] = useState(true);
  const [formType, setFormType] = useState<"minutely" | "hourly" | "daily" | "weekly" | "monthly">("daily");

  // Cron fields state
  const [formSecond, setFormSecond] = useState("0");
  const [formMinute, setFormMinute] = useState("0");
  const [formHour, setFormHour] = useState("0");
  const [formWeekday, setFormWeekday] = useState("*");
  const [formDay, setFormDay] = useState("1");

  // Command state
  const [commandMode, setCommandMode] = useState<"preset" | "detailed">("preset");
  const [formPresetFlag, setFormPresetFlag] = useState("--merge-inbox");
  const [formDetailedCommand, setFormDetailedCommand] = useState("");
  const [previewSegments, setPreviewSegments] = useState<CommandSegment[]>([]);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const primaryInputRef = useRef<HTMLInputElement>(null);

  // Esc-key modal closing handler
  useEffect(() => {
    if (!editingTask) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" || e.key === "Esc") {
        setEditingTask(null);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [editingTask]);

  // Set focus on modal open
  useEffect(() => {
    if (editingTask) {
      setTimeout(() => {
        primaryInputRef.current?.focus();
      }, 50);
    }
  }, [editingTask]);

  const fetchConfig = async () => {
    setLoading(true);
    setError(null);
    setLocalhostBlock(false);
    try {
      const data = await getTaskConfig();
      setTasks(data.tasks);
      setFilepath(data.filepath);
      setRevision(data.revision);
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 403) {
          setLocalhostBlock(true);
        } else {
          setError(e.message || "タスク設定の取得に失敗しました");
        }
      } else {
        setError("サーバーとの通信に失敗しました");
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchConfig();
  }, []);

  // Update command preview for detailed mode
  useEffect(() => {
    if (commandMode !== "detailed" || !formDetailedCommand.trim()) {
      setPreviewSegments([]);
      setPreviewError(null);
      return;
    }

    const timer = setTimeout(async () => {
      try {
        const preview = await previewCommand(formDetailedCommand);
        setPreviewSegments(preview.segments);
        setPreviewError(null);
      } catch (e) {
        if (e instanceof ApiError) {
          setPreviewError(e.message);
        } else {
          setPreviewError("コマンド解析中にエラーが発生しました");
        }
        setPreviewSegments([]);
      }
    }, 400);

    return () => clearTimeout(timer);
  }, [formDetailedCommand, commandMode]);

  const handleEdit = (task: TaskItem) => {
    setEditingTask(task);
    setIsNew(false);
    setFormId(task.id);
    setFormEnabled(task.enabled);
    setFormType((task.schedule.type || "daily") as any);
    setFormSecond(String(task.schedule.second ?? "0"));
    setFormMinute(String(task.schedule.minute ?? "0"));
    setFormHour(String(task.schedule.hour ?? "0"));
    setFormWeekday(String(task.schedule.weekday ?? "*"));
    setFormDay(String(task.schedule.day ?? "1"));

    setSaveError(null);

    if (task.is_preset && task.preset_flag) {
      setCommandMode("preset");
      setFormPresetFlag(task.preset_flag);
      setFormDetailedCommand("");
    } else {
      setCommandMode("detailed");
      setFormPresetFlag("--merge-inbox");
      setFormDetailedCommand(task.command);
    }
  };

  const handleAdd = () => {
    setEditingTask({} as any);
    setIsNew(true);
    setFormId("");
    setFormEnabled(true);
    setFormType("daily");
    setFormSecond("0");
    setFormMinute("0");
    setFormHour("0");
    setFormWeekday("*");
    setFormDay("1");

    setCommandMode("preset");
    setFormPresetFlag("--merge-inbox");
    setFormDetailedCommand("");
    setPreviewSegments([]);
    setPreviewError(null);
    setSaveError(null);
  };

  const handleDelete = async (taskId: string) => {
    if (!window.confirm(`タスク "${taskId}" を削除しますか？`)) return;

    setSaving(true);
    const updatedTasks = tasks.filter((t) => t.id !== taskId);
    // Map tasks back to raw yml structure
    const rawTasks = updatedTasks.map((t) => ({
      id: t.id,
      enabled: t.enabled,
      schedule: t.schedule,
      command: t.command,
    }));

    try {
      const res = await updateTaskConfig(revision, rawTasks);
      setRevision(res.revision);
      // reload
      await fetchConfig();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        alert("版競合が発生しました。他のセッションで設定が更新されています。最新の状態をロードして再試行してください。");
        fetchConfig();
      } else {
        alert(e instanceof ApiError ? e.message : "タスクの削除に失敗しました");
      }
    } finally {
      setSaving(false);
    }
  };

  const handleToggleEnabled = async (task: TaskItem) => {
    setSaving(true);
    const updatedTasks = tasks.map((t) => {
      if (t.id === task.id) {
        return { ...t, enabled: !t.enabled };
      }
      return t;
    });

    const rawTasks = updatedTasks.map((t) => ({
      id: t.id,
      enabled: t.enabled,
      schedule: t.schedule,
      command: t.command,
    }));

    try {
      const res = await updateTaskConfig(revision, rawTasks);
      setRevision(res.revision);
      await fetchConfig();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        alert("版競合が発生しました。他のセッションで設定が更新されています。最新の状態をロードして再試行してください。");
        fetchConfig();
      } else {
        alert(e instanceof ApiError ? e.message : "有効状態の切り替えに失敗しました");
      }
    } finally {
      setSaving(false);
    }
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formId.trim()) {
      setSaveError("タスク ID は必須です");
      return;
    }

    setSaving(true);
    setSaveError(null);

    // Build schedule
    const schedule: Record<string, any> = { type: formType };
    if (formType === "minutely") {
      schedule.second = isNaN(Number(formSecond)) ? formSecond : Number(formSecond);
    } else if (formType === "hourly") {
      schedule.second = isNaN(Number(formSecond)) ? formSecond : Number(formSecond);
      schedule.minute = isNaN(Number(formMinute)) ? formMinute : Number(formMinute);
    } else if (formType === "daily") {
      schedule.second = isNaN(Number(formSecond)) ? formSecond : Number(formSecond);
      schedule.minute = isNaN(Number(formMinute)) ? formMinute : Number(formMinute);
      schedule.hour = isNaN(Number(formHour)) ? formHour : Number(formHour);
    } else if (formType === "weekly") {
      schedule.second = isNaN(Number(formSecond)) ? formSecond : Number(formSecond);
      schedule.minute = isNaN(Number(formMinute)) ? formMinute : Number(formMinute);
      schedule.hour = isNaN(Number(formHour)) ? formHour : Number(formHour);
      schedule.weekday = isNaN(Number(formWeekday)) ? formWeekday : Number(formWeekday);
    } else if (formType === "monthly") {
      schedule.second = isNaN(Number(formSecond)) ? formSecond : Number(formSecond);
      schedule.minute = isNaN(Number(formMinute)) ? formMinute : Number(formMinute);
      schedule.hour = isNaN(Number(formHour)) ? formHour : Number(formHour);
      schedule.day = isNaN(Number(formDay)) ? formDay : Number(formDay);
    }

    // Command
    let command = "";
    if (commandMode === "preset") {
      // Base directory is derived from filepath on the backend.
      // E.g. /app/tasks/tasks.local.yml -> /app
      const baseDir = filepath.replace(/\/tasks\/tasks\.(local\.)?yml$/, "");
      command = `uv --directory ${baseDir} run -m obsidian_ai_hub ${formPresetFlag}`;
    } else {
      command = formDetailedCommand;
    }

    // Build the new task object
    const newTask: any = {
      id: formId,
      enabled: formEnabled,
      schedule,
      command,
    };

    // Construct the complete updated tasks list
    let updatedTasks: any[] = [];
    if (isNew) {
      if (tasks.some((t) => t.id === formId)) {
        setSaveError("同じ ID のタスクが既に存在します");
        setSaving(false);
        return;
      }
      updatedTasks = [...tasks, newTask];
    } else {
      updatedTasks = tasks.map((t) => (t.id === editingTask?.id ? newTask : t));
    }

    const rawTasks = updatedTasks.map((t) => ({
      id: t.id,
      enabled: t.enabled,
      schedule: t.schedule,
      command: t.command,
    }));

    try {
      const res = await updateTaskConfig(revision, rawTasks);
      setRevision(res.revision);
      setEditingTask(null);
      await fetchConfig();
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 409) {
          setSaveError("版競合が発生しました。他のセッションで設定が更新されています。最新の状態をロードして再試行してください。");
        } else {
          setSaveError(e.message || "タスクの保存に失敗しました");
        }
      } else {
        setSaveError("タスクの保存に失敗しました");
      }
    } finally {
      setSaving(false);
    }
  };

  const formatSchedule = (task: TaskItem) => {
    const s = task.schedule;
    const t = s.type;
    if (t === "minutely") {
      return `毎分 (秒: ${s.second ?? 0})`;
    }
    if (t === "hourly") {
      return `毎時 (分: ${s.minute ?? 0}, 秒: ${s.second ?? 0})`;
    }
    if (t === "daily") {
      return `毎日 ${String(s.hour ?? 0).padStart(2, "0")}:${String(s.minute ?? 0).padStart(2, "0")}:${String(s.second ?? 0).padStart(2, "0")}`;
    }
    if (t === "weekly") {
      return `毎週 (曜日: ${s.weekday ?? "*"}) ${String(s.hour ?? 0).padStart(2, "0")}:${String(s.minute ?? 0).padStart(2, "0")}`;
    }
    if (t === "monthly") {
      return `毎月 ${s.day ?? 1}日 ${String(s.hour ?? 0).padStart(2, "0")}:${String(s.minute ?? 0).padStart(2, "0")}`;
    }
    return t;
  };

  const formatNextRun = (isoStr?: string | null) => {
    if (!isoStr) return "-";
    try {
      const d = new Date(isoStr);
      return d.toLocaleString("ja-JP", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    } catch {
      return isoStr;
    }
  };

  if (localhostBlock) {
    return (
      <div className="flex h-full items-center justify-center bg-slate-50 p-6">
        <div className="max-w-lg space-y-4 rounded-2xl bg-white p-8 text-center shadow-lg border border-slate-200">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-red-100 text-red-600">
            <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m0-6v2m0-5h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <h1 className="text-xl font-bold text-slate-900">アクセス制限</h1>
          <p className="text-sm text-slate-600 leading-relaxed">
            セキュリティ保護のため、タスク管理機能は localhost 経由でのみ利用可能です。
            LAN や外部ネットワークからの編集・閲覧はブロックされています。
          </p>
          <div className="rounded-xl bg-slate-100 p-4 text-xs font-mono text-slate-500">
            タスク管理はこの Mac 上で localhost 経由で開いてください。
          </div>
          <button
            type="button"
            onClick={fetchConfig}
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm text-white hover:bg-slate-800 transition"
          >
            再試行
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col bg-slate-50">
      {/* Header */}
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-white px-4 py-3 sm:px-6 sm:py-4">
        <div className="min-w-0">
          <h1 className="text-lg font-bold text-slate-900">タスク管理</h1>
          <p className="mt-0.5 truncate text-xs font-mono text-slate-500">
            設定ファイル: {filepath || "読み込み中…"}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={fetchConfig}
            disabled={loading}
            className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            更新
          </button>
          <button
            type="button"
            onClick={handleAdd}
            disabled={loading}
            className="rounded-lg bg-slate-900 px-3 py-1.5 text-xs text-white hover:bg-slate-800 disabled:opacity-50"
          >
            タスク新規追加
          </button>
        </div>
      </header>

      {/* Main Content Area */}
      <div className="flex-1 overflow-auto p-4 sm:p-6">
        {error && (
          <div className="mb-6 rounded-lg bg-red-50 p-4 text-sm text-red-600">
            {error}
          </div>
        )}

        {loading && tasks.length === 0 ? (
          <div className="flex h-64 items-center justify-center text-sm text-slate-400">
            読み込み中…
          </div>
        ) : tasks.length === 0 ? (
          <div className="flex h-64 flex-col items-center justify-center gap-3 text-sm text-slate-400">
            登録されているタスクがありません
            <button
              onClick={handleAdd}
              className="text-xs text-blue-600 underline font-semibold"
            >
              最初のタスクを追加する
            </button>
          </div>
        ) : (
          <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[800px] border-collapse text-left text-sm text-slate-500">
              <thead className="bg-slate-50 text-xs font-semibold text-slate-700 uppercase">
                <tr>
                  <th className="px-6 py-3 w-16">有効</th>
                  <th className="px-6 py-3">タスク ID</th>
                  <th className="px-6 py-3">スケジュール</th>
                  <th className="px-6 py-3">コマンド</th>
                  <th className="px-6 py-3">次回予定枠</th>
                  <th className="px-6 py-3 text-right">アクション</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {tasks.map((task) => (
                  <tr key={task.id} className="hover:bg-slate-50/50">
                    <td className="px-6 py-4">
                      <input
                        type="checkbox"
                        checked={task.enabled}
                        onChange={() => handleToggleEnabled(task)}
                        disabled={saving}
                        className="h-4 w-4 rounded border-slate-300 text-slate-900 focus:ring-slate-500 cursor-pointer"
                      />
                    </td>
                    <td className="px-6 py-4 font-semibold text-slate-900 font-mono">
                      {task.id}
                    </td>
                    <td className="px-6 py-4 text-slate-600">
                      {formatSchedule(task)}
                    </td>
                    <td className="px-6 py-4 max-w-xs truncate">
                      {task.is_preset ? (
                        <span className="inline-flex items-center gap-1 rounded bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-800">
                          {task.preset_name}
                        </span>
                      ) : (
                        <code className="text-xs font-mono text-slate-500 bg-slate-100 px-1 py-0.5 rounded">
                          {task.command}
                        </code>
                      )}
                    </td>
                    <td className="px-6 py-4 text-xs font-mono text-slate-600">
                      {formatNextRun(task.next_run)}
                    </td>
                    <td className="px-6 py-4 text-right">
                      <div className="flex justify-end gap-2">
                        <button
                          type="button"
                          onClick={() => handleEdit(task)}
                          className="rounded px-2.5 py-1 text-xs font-medium text-slate-600 hover:bg-slate-100"
                        >
                          編集
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDelete(task.id)}
                          className="rounded px-2.5 py-1 text-xs font-medium text-red-600 hover:bg-red-50"
                        >
                          削除
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          </div>
        )}
      </div>

      {/* Add / Edit Task Modal */}
      {editingTask && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
          <div className="flex h-full max-h-[85vh] w-full max-w-2xl flex-col rounded-xl bg-white shadow-xl border border-slate-200 overflow-hidden">
            {/* Modal Header */}
            <div className="border-b border-slate-100 px-6 py-4">
              <h2 className="text-base font-bold text-slate-900">
                {isNew ? "新規タスク追加" : "タスク編集"}
              </h2>
            </div>

            {/* Modal Form Content */}
            <form onSubmit={handleSave} className="flex-1 overflow-y-auto p-6 space-y-6">
              {saveError && (
                <div className="rounded-lg bg-red-50 p-4 text-xs text-red-600">
                  {saveError}
                </div>
              )}

              {/* Task ID */}
              <div>
                <label className="block text-xs font-semibold text-slate-700 uppercase mb-1">
                  タスク ID
                </label>
                <input
                  ref={isNew ? primaryInputRef : null}
                  type="text"
                  required
                  value={formId}
                  onChange={(e) => setFormId(e.target.value)}
                  disabled={!isNew || saving}
                  placeholder="e.g. daily_backup"
                  className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none disabled:bg-slate-50 font-mono"
                />
              </div>

              {/* Enabled */}
              <div className="flex items-center gap-2">
                <input
                  ref={!isNew ? primaryInputRef : null}
                  type="checkbox"
                  id="formEnabled"
                  checked={formEnabled}
                  onChange={(e) => setFormEnabled(e.target.checked)}
                  disabled={saving}
                  className="h-4 w-4 rounded border-slate-300 text-slate-900 focus:ring-slate-500"
                />
                <label htmlFor="formEnabled" className="text-sm font-medium text-slate-700 cursor-pointer">
                  タスクを有効にする
                </label>
              </div>

              {/* Schedule Definition */}
              <div className="rounded-xl bg-slate-50 p-4 border border-slate-200 space-y-4">
                <h3 className="text-xs font-bold text-slate-800 uppercase tracking-wide">
                  スケジュール設定
                </h3>

                <div>
                  <label className="block text-xs font-medium text-slate-600 mb-1">
                    タイプ
                  </label>
                  <select
                    value={formType}
                    onChange={(e) => setFormType(e.target.value as any)}
                    disabled={saving}
                    className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-slate-500 focus:outline-none"
                  >
                    <option value="minutely">毎分 (minutely)</option>
                    <option value="hourly">毎時 (hourly)</option>
                    <option value="daily">毎日 (daily)</option>
                    <option value="weekly">毎週 (weekly)</option>
                    <option value="monthly">毎月 (monthly)</option>
                  </select>
                </div>

                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  {/* Seconds */}
                  <div>
                    <label className="block text-xs font-medium text-slate-600 mb-1">
                      秒 (second)
                    </label>
                    <input
                      type="text"
                      value={formSecond}
                      onChange={(e) => setFormSecond(e.target.value)}
                      disabled={saving}
                      placeholder="0-59 or * or */15"
                      className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs focus:border-slate-500 focus:outline-none font-mono"
                    />
                  </div>

                  {/* Minutes */}
                  {formType !== "minutely" && (
                    <div>
                      <label className="block text-xs font-medium text-slate-600 mb-1">
                        分 (minute)
                      </label>
                      <input
                        type="text"
                        value={formMinute}
                        onChange={(e) => setFormMinute(e.target.value)}
                        disabled={saving}
                        placeholder="0-59 or * or */5"
                        className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs focus:border-slate-500 focus:outline-none font-mono"
                      />
                    </div>
                  )}

                  {/* Hour */}
                  {formType !== "minutely" && formType !== "hourly" && (
                    <div>
                      <label className="block text-xs font-medium text-slate-600 mb-1">
                        時 (hour)
                      </label>
                      <input
                        type="text"
                        value={formHour}
                        onChange={(e) => setFormHour(e.target.value)}
                        disabled={saving}
                        placeholder="0-23 or *"
                        className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs focus:border-slate-500 focus:outline-none font-mono"
                      />
                    </div>
                  )}

                  {/* Weekday */}
                  {formType === "weekly" && (
                    <div>
                      <label className="block text-xs font-medium text-slate-600 mb-1">
                        曜日 (weekday)
                      </label>
                      <input
                        type="text"
                        value={formWeekday}
                        onChange={(e) => setFormWeekday(e.target.value)}
                        disabled={saving}
                        placeholder="0-6 (0=Mon) or * or [1,3]"
                        className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs focus:border-slate-500 focus:outline-none font-mono"
                      />
                    </div>
                  )}

                  {/* Day */}
                  {formType === "monthly" && (
                    <div>
                      <label className="block text-xs font-medium text-slate-600 mb-1">
                        日 (day)
                      </label>
                      <input
                        type="text"
                        value={formDay}
                        onChange={(e) => setFormDay(e.target.value)}
                        disabled={saving}
                        placeholder="1-31 or *"
                        className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs focus:border-slate-500 focus:outline-none font-mono"
                      />
                    </div>
                  )}
                </div>
              </div>

              {/* Command Definition */}
              <div className="space-y-3">
                <label className="block text-xs font-semibold text-slate-700 uppercase">
                  実行コマンド設定
                </label>

                <div className="flex gap-2 rounded-lg bg-slate-100 p-1 border border-slate-200">
                  <button
                    type="button"
                    onClick={() => setCommandMode("preset")}
                    className={`flex-1 whitespace-nowrap rounded-md py-1.5 text-xs font-medium transition ${
                      commandMode === "preset"
                        ? "bg-white text-slate-900 shadow-sm"
                        : "text-slate-500 hover:text-slate-900"
                    }`}
                  >
                    標準モード (プリセット)
                  </button>
                  <button
                    type="button"
                    onClick={() => setCommandMode("detailed")}
                    className={`flex-1 whitespace-nowrap rounded-md py-1.5 text-xs font-medium transition ${
                      commandMode === "detailed"
                        ? "bg-white text-slate-900 shadow-sm"
                        : "text-slate-500 hover:text-slate-900"
                    }`}
                  >
                    詳細モード (任意コマンド)
                  </button>
                </div>

                {commandMode === "preset" ? (
                  <div>
                    <label className="block text-xs font-medium text-slate-600 mb-1">
                      プリセット一覧
                    </label>
                    <select
                      value={formPresetFlag}
                      onChange={(e) => setFormPresetFlag(e.target.value)}
                      disabled={saving}
                      className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-slate-500 focus:outline-none"
                    >
                      {PRESET_OPTIONS.map((p) => (
                        <option key={p.flag} value={p.flag}>
                          {p.name} ({p.flag})
                        </option>
                      ))}
                    </select>
                  </div>
                ) : (
                  <div className="space-y-3">
                    <div>
                      <label className="block text-xs font-medium text-slate-600 mb-1">
                        任意コマンド入力 (&& による接続もサポート)
                      </label>
                      <textarea
                        required
                        rows={3}
                        value={formDetailedCommand}
                        onChange={(e) => setFormDetailedCommand(e.target.value)}
                        disabled={saving}
                        placeholder="e.g. cd /app && python -m task_module"
                        className="w-full rounded-lg border border-slate-200 px-3 py-2 text-xs font-mono focus:border-slate-500 focus:outline-none"
                      />
                    </div>

                    {/* Shlex parse live preview */}
                    {formDetailedCommand.trim() && (
                      <div className="rounded-xl bg-slate-900 text-slate-100 p-4 border border-slate-800 space-y-2">
                        <h4 className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">
                          バックエンド構文解析プレビュー
                        </h4>
                        {previewError ? (
                          <div className="text-xs text-red-400 font-semibold">
                            ⚠️ {previewError}
                          </div>
                        ) : previewSegments.length > 0 ? (
                          <div className="space-y-2 max-h-48 overflow-y-auto font-mono text-xs">
                            {previewSegments.map((seg, idx) => (
                              <div key={idx} className="border-b border-slate-800 pb-2 last:border-0 last:pb-0">
                                {seg.cwd && (
                                  <div className="text-slate-400 mb-1">
                                    <span className="text-blue-400 font-semibold">📂 cd:</span> {seg.cwd}
                                  </div>
                                )}
                                <div className="text-emerald-400">
                                  <span className="text-slate-400 font-semibold">🚀 args:</span>{" "}
                                  {JSON.stringify(seg.args)}
                                </div>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <div className="text-xs text-slate-500 font-mono">
                            解析中…
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </form>

            {/* Modal Footer Actions */}
            <div className="flex items-center justify-end gap-3 border-t border-slate-100 bg-slate-50 px-6 py-4 shrink-0">
              <button
                type="button"
                onClick={() => setEditingTask(null)}
                disabled={saving}
                className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              >
                キャンセル
              </button>
              <button
                type="button"
                onClick={handleSave}
                disabled={saving || (commandMode === "detailed" && !!previewError)}
                className="rounded-lg bg-slate-900 px-4 py-2 text-xs font-medium text-white hover:bg-slate-800 disabled:opacity-50"
              >
                {saving ? "保存中..." : "保存"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
