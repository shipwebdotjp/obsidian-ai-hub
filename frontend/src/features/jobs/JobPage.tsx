import { useEffect, useState, useRef } from "react";
import {
  getRecurringJobs,
  updateRecurringJobs,
  previewCommand,
  listOneShotJobs,
  getOneShotJobDetail,
  cancelOneShotJob,
} from "../../api/client";
import type { RecurringJob, RecurringJobSchedule, RecurringJobScheduleType, RecurringJobUpdate, CommandSegment, OneShotJobSummary, OneShotJobDetail } from "../../api/types";
import { ApiError } from "../../api/client";
import TokenPrompt from "../../components/TokenPrompt";

// Keep in sync with backend PRESET_FLAGS (scheduler_jobs/recurring.py).
// Every flag here must exist as an argparse flag in main.py; otherwise the
// generated command fails at runtime.
const PRESET_OPTIONS = [
  { name: "Inbox merge", flag: "--merge-inbox" },
  { name: "日サマリ", flag: "--summerize-day" },
  { name: "週サマリ", flag: "--summerize-week" },
  { name: "月サマリ", flag: "--summerize-month" },
  { name: "目標作成", flag: "--make-target" },
  { name: "今日の予定・タスクを書き込み", flag: "--write-today-schedule" },
  { name: "今日の予定通知", flag: "--notify-today-schedule" },
  { name: "Backup", flag: "--backup" },
  { name: "Vault sync", flag: "--sync-vault" },
  { name: "People sync", flag: "--sync-people" },
  { name: "Knowledge sync", flag: "--sync-knowledge" },
  { name: "Review draft", flag: "--review-draft" },
  { name: "Memory extract", flag: "--memory-extract" },
  { name: "Research suggestion", flag: "--suggest-research-theme" },
  { name: "AIプランナー提案生成", flag: "--generate-planner-proposals" },
  { name: "Activity log", flag: "--log-activity" },
  { name: "HITL dispatch", flag: "--hitl-dispatch" },
  { name: "LINE Webhook cleanup", flag: "--cleanup-line-webhooks" },
];

export default function JobPage() {
  const [jobs, setJobs] = useState<RecurringJob[]>([]);
  const [filepath, setFilepath] = useState("");
  const [revision, setRevision] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [authRequired, setAuthRequired] = useState(false);
  const [blocked, setBlocked] = useState(false);

  // Form State
  const [editingJob, setEditingJob] = useState<RecurringJob | null>(null);
  const [isNew, setIsNew] = useState(false);
  const [formId, setFormId] = useState("");
  const [formEnabled, setFormEnabled] = useState(true);
  const [formType, setFormType] = useState<RecurringJobScheduleType>("daily");

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

  // One-shot Jobs State
  const [oneShotJobs, setOneShotJobs] = useState<OneShotJobSummary[]>([]);
  const [oneShotTotal, setOneShotTotal] = useState(0);
  const [oneShotLoading, setOneShotLoading] = useState(true);
  const [oneShotError, setOneShotError] = useState<string | null>(null);
  const [selectedOneShot, setSelectedOneShot] = useState<OneShotJobDetail | null>(null);
  const [selectedOneShotJobId, setSelectedOneShotJobId] = useState<string | null>(null);
  const [oneShotDetailLoading, setOneShotDetailLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const primaryInputRef = useRef<HTMLInputElement>(null);

  // Esc-key modal closing handler
  useEffect(() => {
    if (!editingJob && !isNew) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" || e.key === "Esc") {
        closeEditor();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [editingJob, isNew]);

  // Set focus on modal open
  useEffect(() => {
    if (editingJob || isNew) {
      setTimeout(() => {
        primaryInputRef.current?.focus();
      }, 50);
    }
  }, [editingJob, isNew]);

  const closeEditor = () => {
    setEditingJob(null);
    setIsNew(false);
  };

  const fetchConfig = async () => {
    setLoading(true);
    setError(null);
    setAuthRequired(false);
    setBlocked(false);
    try {
      const data = await getRecurringJobs();
      setJobs(data.jobs);
      setFilepath(data.filepath);
      setRevision(data.revision);
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 401) {
          setAuthRequired(true);
        } else if (e.status === 403) {
          setBlocked(true);
        } else {
          setError(e.message || "ジョブ設定の取得に失敗しました");
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
    fetchOneShotJobs();
  }, []);

  const fetchOneShotJobs = async () => {
    setOneShotLoading(true);
    setOneShotError(null);
    try {
      const data = await listOneShotJobs(100, 0);
      setOneShotJobs(data.items);
      setOneShotTotal(data.total);
    } catch (e) {
      if (e instanceof ApiError) {
        setOneShotError(e.message || "ワンショット実行ジョブの取得に失敗しました");
      } else {
        setOneShotError("サーバーとの通信に失敗しました");
      }
    } finally {
      setOneShotLoading(false);
    }
  };

  const handleSelectOneShot = async (jobId: string) => {
    setSelectedOneShotJobId(jobId);
    setSelectedOneShot(null);
    setOneShotDetailLoading(true);
    try {
      const detail = await getOneShotJobDetail(jobId);
      setSelectedOneShot(detail);
    } catch (e) {
      if (e instanceof ApiError) {
        setOneShotError(e.message || "ワンショット実行ジョブの詳細取得に失敗しました");
      } else {
        setOneShotError("サーバーとの通信に失敗しました");
      }
    } finally {
      setOneShotDetailLoading(false);
    }
  };

  const closeOneShotDetail = () => {
    setSelectedOneShotJobId(null);
    setSelectedOneShot(null);
  };

  const handleCancelOneShot = async (jobId: string) => {
    if (!window.confirm(`ワンショット実行ジョブ "${jobId}" を取り消しますか？（未開始のみ取消可能）`)) return;
    try {
      await cancelOneShotJob(jobId);
      closeOneShotDetail();
      await fetchOneShotJobs();
    } catch (e) {
      alert(e instanceof ApiError ? e.message : "ワンショット実行ジョブの取消に失敗しました");
    }
  };

  const toRawJob = (t: RecurringJob): RecurringJobUpdate => ({
    id: t.id,
    enabled: t.enabled,
    schedule: t.schedule,
    command: t.command,
  });

  const toRawJobs = (items: RecurringJob[]): RecurringJobUpdate[] =>
    items.map(toRawJob);

  // Update command preview for detailed mode (stale responses are ignored).
  const previewSeq = useRef(0);
  useEffect(() => {
    if (commandMode !== "detailed" || !formDetailedCommand.trim()) {
      setPreviewSegments([]);
      setPreviewError(null);
      return;
    }

    const seq = ++previewSeq.current;
    const snapshot = formDetailedCommand;
    const timer = setTimeout(async () => {
      try {
        const preview = await previewCommand(snapshot);
        if (seq !== previewSeq.current) return;
        setPreviewSegments(preview.segments);
        setPreviewError(null);
      } catch (e) {
        if (seq !== previewSeq.current) return;
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

  const handleEdit = (job: RecurringJob) => {
    setEditingJob(job);
    setIsNew(false);
    setFormId(job.id);
    setFormEnabled(job.enabled);
    setFormType(job.schedule?.type ?? "daily");
    setFormSecond(String(job.schedule?.second ?? "0"));
    setFormMinute(String(job.schedule?.minute ?? "0"));
    setFormHour(String(job.schedule?.hour ?? "0"));
    setFormWeekday(String(job.schedule?.weekday ?? "*"));
    setFormDay(String(job.schedule?.day ?? "1"));

    setSaveError(null);

    if (job.is_preset && job.preset_flag) {
      setCommandMode("preset");
      setFormPresetFlag(job.preset_flag);
      setFormDetailedCommand("");
    } else {
      setCommandMode("detailed");
      setFormPresetFlag("--merge-inbox");
      setFormDetailedCommand(job.command);
    }
  };

  const handleAdd = () => {
    setEditingJob(null);
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

  const handleDelete = async (jobId: string) => {
    if (!window.confirm(`ジョブ "${jobId}" を削除しますか？`)) return;

    setSaving(true);
    const updatedJobs = jobs.filter((t) => t.id !== jobId);
    // Map jobs back to raw yml structure
    const rawJobs = toRawJobs(updatedJobs);

    try {
      const res = await updateRecurringJobs(revision, rawJobs);
      setRevision(res.revision);
      // reload
      await fetchConfig();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        alert("版競合が発生しました。他のセッションで設定が更新されています。最新の状態をロードして再試行してください。");
        fetchConfig();
      } else {
        alert(e instanceof ApiError ? e.message : "ジョブの削除に失敗しました");
      }
    } finally {
      setSaving(false);
    }
  };

  const handleToggleEnabled = async (job: RecurringJob) => {
    setSaving(true);
    const updatedJobs = jobs.map((t) => {
      if (t.id === job.id) {
        return { ...t, enabled: !t.enabled };
      }
      return t;
    });

    const rawJobs = toRawJobs(updatedJobs);

    try {
      const res = await updateRecurringJobs(revision, rawJobs);
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
      setSaveError("ジョブ ID は必須です");
      return;
    }

    setSaving(true);
    setSaveError(null);

    // Build schedule
    const schedule: RecurringJobSchedule = { type: formType };
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
      // E.g. /app/jobs/jobs.local.yml -> /app
      const m = filepath.match(/^(.*)\/jobs\/jobs\.(local\.)?yml$/);
      if (!m?.[1]) {
        setSaveError("設定ファイルパスが不正なためプリセットを生成できません");
        setSaving(false);
        return;
      }
      const baseDir = m[1];
      command = `uv --directory "${baseDir.replace(/"/g, '\\"')}" run -m obsidian_ai_hub ${formPresetFlag}`;
    } else {
      command = formDetailedCommand;
    }

    // Build the new job object
    const newJob: RecurringJobUpdate = {
      id: formId,
      enabled: formEnabled,
      schedule,
      command,
    };

    // Construct the complete updated jobs list
    let updatedJobs: RecurringJobUpdate[] = [];
    if (isNew) {
      if (jobs.some((t) => t.id === formId)) {
        setSaveError("同じ ID のジョブが既に存在します");
        setSaving(false);
        return;
      }
      updatedJobs = [...jobs.map(toRawJob), newJob];
    } else {
      updatedJobs = jobs.map((t) => (t.id === editingJob?.id ? newJob : toRawJob(t)));
    }

    const rawJobs = updatedJobs;

    try {
      const res = await updateRecurringJobs(revision, rawJobs);
      setRevision(res.revision);
      closeEditor();
      await fetchConfig();
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 409) {
          setSaveError("版競合が発生しました。他のセッションで設定が更新されています。最新の状態をロードして再試行してください。");
        } else {
          setSaveError(e.message || "ジョブの保存に失敗しました");
        }
      } else {
        setSaveError("ジョブの保存に失敗しました");
      }
    } finally {
      setSaving(false);
    }
  };

  const formatSchedule = (job: RecurringJob) => {
    // Backend returns schedule verbatim from hand-editable YAML; a missing or
    // malformed schedule must not break the whole table render.
    const s = job.schedule as Partial<RecurringJobSchedule> | null | undefined;
    const t = s?.type;
    if (t === "minutely") {
      return `毎分 (秒: ${s?.second ?? 0})`;
    }
    if (t === "hourly") {
      return `毎時 (分: ${s?.minute ?? 0}, 秒: ${s?.second ?? 0})`;
    }
    if (t === "daily") {
      return `毎日 ${String(s?.hour ?? 0).padStart(2, "0")}:${String(s?.minute ?? 0).padStart(2, "0")}:${String(s?.second ?? 0).padStart(2, "0")}`;
    }
    if (t === "weekly") {
      return `毎週 (曜日: ${s?.weekday ?? "*"}) ${String(s?.hour ?? 0).padStart(2, "0")}:${String(s?.minute ?? 0).padStart(2, "0")}`;
    }
    if (t === "monthly") {
      return `毎月 ${s?.day ?? 1}日 ${String(s?.hour ?? 0).padStart(2, "0")}:${String(s?.minute ?? 0).padStart(2, "0")}`;
    }
    return typeof t === "string" ? t : "-";
  };

  const formatNextRun = (isoStr?: string | null) => {
    if (!isoStr) return "-";
    const d = new Date(isoStr);
    if (isNaN(d.getTime())) return isoStr;
    return d.toLocaleString("ja-JP", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  };

  if (authRequired) {
    return (
      <TokenPrompt
        title="トークン認証（ジョブ管理）"
        description={
          <>
            Tailscale tailnet 経由でジョブ管理機能を利用するには
            <code className="rounded bg-slate-100 px-1">OBSIDIAN_AI_HUB_API_TOKEN</code>{" "}
            の値が必要です。
          </>
        }
        validate={getRecurringJobs}
        onAuthenticated={() => { fetchConfig(); fetchOneShotJobs(); }}
      />
    );
  }

  if (blocked) {
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
            セキュリティ保護のため、ジョブ管理機能は localhost 経由、または
            Tailscale tailnet 内（トークン認証付き）でのみ利用可能です。
            LAN や外部ネットワークからの編集・閲覧はブロックされています。
          </p>
          <div className="rounded-xl bg-slate-100 p-4 text-xs font-mono text-slate-500">
            ジョブ管理はこの Mac 上で localhost 経由で開くか、
            <br />
            Tailscale 内のホストで <code>OBSIDIAN_AI_HUB_API_TOKEN</code> を設定して開いてください。
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
          <h1 className="text-lg font-bold text-slate-900">ジョブ管理</h1>
          <p className="mt-0.5 truncate text-xs font-mono text-slate-500">
            設定ファイル: {filepath || "読み込み中…"}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => { fetchConfig(); fetchOneShotJobs(); }}
            disabled={loading}
            className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            更新
          </button>
          <button
            type="button"
            onClick={handleAdd}
            disabled={loading}
            className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            ジョブ新規追加
          </button>
        </div>
      </header>

      {/* Main Content Area */}
      <div className="flex-1 overflow-auto p-4 sm:p-6">
        <h2 className="mb-3 text-sm font-bold text-slate-800">定期実行ジョブ</h2>
        {error && (
          <div className="mb-6 rounded-lg bg-red-50 p-4 text-sm text-red-600">
            {error}
          </div>
        )}

        {loading && jobs.length === 0 ? (
          <div className="flex h-64 items-center justify-center text-sm text-slate-400">
            読み込み中…
          </div>
        ) : jobs.length === 0 ? (
          <div className="flex h-64 flex-col items-center justify-center gap-3 text-sm text-slate-400">
            登録されているジョブがありません
            <button
              onClick={handleAdd}
              className="text-xs text-blue-600 underline font-semibold"
            >
              最初のジョブを追加する
            </button>
          </div>
        ) : (
          <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[800px] border-collapse text-left text-sm text-slate-500">
              <thead className="bg-slate-50 text-xs font-semibold text-slate-700 uppercase">
                <tr>
                  <th className="px-6 py-3 w-16">有効</th>
                  <th className="px-6 py-3">ジョブ ID</th>
                  <th className="px-6 py-3">スケジュール</th>
                  <th className="px-6 py-3">コマンド</th>
                  <th className="px-6 py-3">次回予定枠</th>
                  <th className="px-6 py-3 text-right">アクション</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {jobs.map((job) => (
                  <tr key={job.id} className="hover:bg-slate-50/50">
                    <td className="px-6 py-4">
                      <input
                        type="checkbox"
                        checked={job.enabled}
                        onChange={() => handleToggleEnabled(job)}
                        disabled={saving}
                        className="h-4 w-4 rounded border-slate-300 text-slate-900 focus:ring-slate-500 cursor-pointer"
                      />
                    </td>
                    <td className="px-6 py-4 font-semibold text-slate-900 font-mono">
                      {job.id}
                    </td>
                    <td className="px-6 py-4 text-slate-600">
                      {formatSchedule(job)}
                    </td>
                    <td className="px-6 py-4 max-w-xs truncate">
                      {job.is_preset ? (
                        <span className="inline-flex items-center gap-1 rounded bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-800">
                          {job.preset_name}
                        </span>
                      ) : (
                        <code className="text-xs font-mono text-slate-500 bg-slate-100 px-1 py-0.5 rounded">
                          {job.command}
                        </code>
                      )}
                    </td>
                    <td className="px-6 py-4 text-xs font-mono text-slate-600">
                      {formatNextRun(job.next_run)}
                    </td>
                    <td className="px-6 py-4 text-right">
                      <div className="flex justify-end gap-2">
                        <button
                          type="button"
                          onClick={() => handleEdit(job)}
                          className="rounded px-2.5 py-1 text-xs font-medium text-slate-600 hover:bg-slate-100"
                        >
                          編集
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDelete(job.id)}
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

        {/* One-shot Jobs Section */}
        <h2 className="mb-3 mt-8 text-sm font-bold text-slate-800">ワンショット実行ジョブ</h2>
        <p className="mb-3 text-xs text-slate-500">
          Agent が register_one_shot_job で登録した一度だけ実行するジョブ。未完了を優先して表示し、終端履歴は30日間保持。UI からの手動登録はなし。
        </p>
        {oneShotError && (
          <div className="mb-6 rounded-lg bg-red-50 p-4 text-sm text-red-600">
            {oneShotError}
          </div>
        )}
        {oneShotLoading ? (
          <div className="flex h-32 items-center justify-center text-sm text-slate-400">
            読み込み中…
          </div>
        ) : oneShotJobs.length === 0 ? (
          <div className="flex h-32 flex-col items-center justify-center gap-3 text-sm text-slate-400">
            登録されているワンショット実行ジョブがありません
          </div>
        ) : (
          <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[800px] border-collapse text-left text-sm text-slate-500">
                <thead className="bg-slate-50 text-xs font-semibold text-slate-700 uppercase">
                  <tr>
                    <th className="px-6 py-3">予定時刻</th>
                    <th className="px-6 py-3">状態</th>
                    <th className="px-6 py-3">登録元</th>
                    <th className="px-6 py-3">コマンド</th>
                    <th className="px-6 py-3">終了コード</th>
                    <th className="px-6 py-3 text-right">アクション</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200">
                  {oneShotJobs.map((job) => (
                    <tr key={job.job_id} className="hover:bg-slate-50/50">
                      <td className="px-6 py-4 text-xs font-mono text-slate-600">
                        {formatNextRun(job.run_at_utc)}
                      </td>
                      <td className="px-6 py-4">
                        <span className="inline-flex items-center gap-1 rounded bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-800">
                          {job.status}
                        </span>
                      </td>
                      <td className="px-6 py-4 text-xs font-mono text-slate-500">
                        {[job.agent_id, job.session_id, job.run_id].filter(Boolean).join(" / ") || "-"}
                      </td>
                      <td className="px-6 py-4 max-w-xs truncate">
                        <code className="text-xs font-mono text-slate-500 bg-slate-100 px-1 py-0.5 rounded">
                          {job.command}
                        </code>
                      </td>
                      <td className="px-6 py-4 text-xs font-mono text-slate-600">
                        {job.exit_code ?? "-"}
                      </td>
                      <td className="px-6 py-4 text-right">
                        <div className="flex justify-end gap-2">
                          <button
                            type="button"
                            onClick={() => handleSelectOneShot(job.job_id)}
                            className="rounded px-2.5 py-1 text-xs font-medium text-slate-600 hover:bg-slate-100"
                          >
                            詳細
                          </button>
                          {job.status === "queued" && (
                            <button
                              type="button"
                              onClick={() => handleCancelOneShot(job.job_id)}
                              className="rounded px-2.5 py-1 text-xs font-medium text-red-600 hover:bg-red-50"
                            >
                              取消
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
        {oneShotTotal > oneShotJobs.length && (
          <p className="mt-2 text-xs text-slate-400">
            {oneShotTotal} 件中 {oneShotJobs.length} 件を表示
          </p>
        )}

        {/* One-shot Detail Modal */}
        {selectedOneShotJobId && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
            <div className="flex h-full max-h-[85vh] w-full max-w-2xl flex-col rounded-xl bg-white shadow-xl border border-slate-200 overflow-hidden">
              <div className="border-b border-slate-100 px-6 py-4">
                <h2 className="text-base font-bold text-slate-900 font-mono">
                  {selectedOneShotJobId}
                </h2>
                {selectedOneShot && (
                  <>
                    <p className="mt-1 text-xs text-slate-500">
                      状態: {selectedOneShot.status}
                      {selectedOneShot.exit_code !== null && selectedOneShot.exit_code !== undefined && ` / 終了コード: ${selectedOneShot.exit_code}`}
                    </p>
                    {selectedOneShot.error_summary && (
                      <p className="mt-1 text-xs text-red-600">{selectedOneShot.error_summary}</p>
                    )}
                  </>
                )}
              </div>
              <div className="flex-1 overflow-y-auto p-6 space-y-4">
                {oneShotDetailLoading ? (
                  <div className="text-sm text-slate-400">読み込み中…</div>
                ) : (
                  (selectedOneShot?.segments ?? []).map((seg, idx) => (
                    <div key={idx} className="rounded-xl bg-slate-900 text-slate-100 p-4 border border-slate-800 space-y-2">
                      <h4 className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">
                        セグメント {idx + 1}（終了コード: {seg.exit_code ?? "-"}）
                      </h4>
                      {seg.cwd && (
                        <div className="text-slate-400 mb-1 font-mono text-xs">
                          <span className="text-blue-400 font-semibold">📂 cd:</span> {seg.cwd}
                        </div>
                      )}
                      <div className="text-emerald-400 font-mono text-xs">
                        <span className="text-slate-400 font-semibold">🚀 args:</span> {JSON.stringify(seg.args)}
                      </div>
                      {seg.stdout && (
                        <pre className="whitespace-pre-wrap break-all font-mono text-xs text-slate-200">{seg.stdout}{seg.truncated_stdout && "\n...[切詰めあり]"}</pre>
                      )}
                      {seg.stderr && (
                        <pre className="whitespace-pre-wrap break-all font-mono text-xs text-red-300">{seg.stderr}{seg.truncated_stderr && "\n...[切詰めあり]"}</pre>
                      )}
                    </div>
                  ))
                )}
                {(selectedOneShot?.segments ?? []).length === 0 && !oneShotDetailLoading && (
                  <div className="text-xs text-slate-500">実行結果はまだありません。</div>
                )}
              </div>
              <div className="flex items-center justify-end gap-3 border-t border-slate-100 bg-slate-50 px-6 py-4 shrink-0">
                {selectedOneShot?.status === "queued" && selectedOneShot && (
                  <button
                    type="button"
                    onClick={() => handleCancelOneShot(selectedOneShot.job_id)}
                    className="rounded-lg bg-rose-800 px-4 py-2 text-xs font-medium text-white hover:bg-rose-700"
                  >
                    取消
                  </button>
                )}
                <button
                  type="button"
                  onClick={closeOneShotDetail}
                  className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50"
                >
                  閉じる
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Add / Edit Job Modal */}
      {(editingJob || isNew) && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
          <div className="flex h-full max-h-[85vh] w-full max-w-2xl flex-col rounded-xl bg-white shadow-xl border border-slate-200 overflow-hidden">
            {/* Modal Header */}
            <div className="border-b border-slate-100 px-6 py-4">
              <h2 className="text-base font-bold text-slate-900">
                {isNew ? "新規ジョブ追加" : "ジョブ編集"}
              </h2>
            </div>

            {/* Modal Form Content */}
            <form onSubmit={handleSave} className="flex-1 overflow-y-auto p-6 space-y-6">
              {saveError && (
                <div className="rounded-lg bg-red-50 p-4 text-xs text-red-600">
                  {saveError}
                </div>
              )}

              {/* Job ID */}
              <div>
                <label className="block text-xs font-semibold text-slate-700 uppercase mb-1">
                  ジョブ ID
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
                  ジョブを有効にする
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
                    onChange={(e) => setFormType(e.target.value as RecurringJobScheduleType)}
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
                        placeholder="e.g. cd /app && python -m job_module"
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
                onClick={closeEditor}
                disabled={saving}
                className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              >
                キャンセル
              </button>
              <button
                type="button"
                onClick={handleSave}
                disabled={saving || (commandMode === "detailed" && !!previewError)}
                className="rounded-lg bg-blue-600 px-4 py-2 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
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
