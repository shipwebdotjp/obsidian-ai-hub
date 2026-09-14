import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  listTaskAgentCapabilities,
  updateTaskAgentCapability,
} from "../../api/client";
import type {
  TaskAgentApprovalPolicy,
  TaskAgentCapability,
} from "../../api/types";
import { formatDateTime } from "../../utils/date";

const CAPABILITY_DESCRIPTIONS: Record<string, string> = {
  web_search: "Web検索",
  web_extract: "Web本文抽出",
  vault_search: "Vault検索",
  vault_read_file: "Vaultファイル読取",
  calendar_read: "カレンダー読取",
  reminders_read: "リマインダー読取",
  memory_search: "長期記憶検索",
  people_search: "人物検索",
  people_get: "人物詳細取得",
  project_search: "プロジェクト検索",
  project_get: "プロジェクト詳細取得",
  memory_propose: "長期記憶候補作成(Plan承認が必要)",
  specialist_agent: "登録済みAgentへの委譲(Plan承認が必要)",
  coding_cli: "Coding CLI実行(Plan承認が必要)",
};

interface RowState {
  enabled: boolean;
  approvalPolicy: TaskAgentApprovalPolicy;
  busy: boolean;
  saved: boolean;
  error: string | null;
}

function toRow(c: TaskAgentCapability): RowState {
  return {
    enabled: c.enabled,
    approvalPolicy:
      c.approval_policy === "plan_required" ? "plan_required" : "auto",
    busy: false,
    saved: false,
    error: null,
  };
}

export default function CapabilitySettingsPage() {
  const [items, setItems] = useState<TaskAgentCapability[]>([]);
  const [rows, setRows] = useState<Record<string, RowState>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listTaskAgentCapabilities();
      setItems(res);
      setRows(Object.fromEntries(res.map((c) => [c.capability_key, toRow(c)])));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "読み込みに失敗しました");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const patchRow = (key: string, patch: Partial<RowState>) =>
    setRows((prev) => {
      const cur = prev[key];
      if (!cur) return prev;
      return { ...prev, [key]: { ...cur, ...patch } };
    });

  const save = async (c: TaskAgentCapability) => {
    const row = rows[c.capability_key];
    if (!row || row.busy) return;
    patchRow(c.capability_key, { busy: true, saved: false, error: null });
    try {
      const updated = await updateTaskAgentCapability(c.capability_key, {
        enabled: row.enabled,
        approval_policy: row.approvalPolicy,
      });
      setItems((prev) =>
        prev.map((x) =>
          x.capability_key === c.capability_key ? updated : x,
        ),
      );
      patchRow(c.capability_key, { busy: false, saved: true, error: null });
    } catch (e) {
      patchRow(c.capability_key, {
        busy: false,
        error: e instanceof ApiError ? e.message : "保存に失敗しました",
      });
    }
  };

  if (loading) return <p className="p-4 text-sm text-slate-500">読み込み中…</p>;

  return (
    <div className="flex h-full flex-col bg-slate-50">
      <header className="border-b border-slate-200 bg-white px-4 py-3">
        <h1 className="text-lg font-semibold">Task Capability設定</h1>
        <p className="mt-1 text-xs text-slate-500">
          Adapter定義はコードで固定され、ここでは有効/無効と承認ポリシーのみ変更できます。
        </p>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {error && (
          <p className="mb-3 rounded border border-rose-300 bg-rose-50 p-2 text-sm text-rose-700">
            {error}
          </p>
        )}
        <div className="w-full max-w-3xl space-y-3">
          {items.map((c) => {
            const row = rows[c.capability_key];
            if (!row) return null;
            const dirty =
              row.enabled !== c.enabled ||
              row.approvalPolicy !== c.approval_policy;
            return (
              <section
                key={c.capability_key}
                data-testid="capability-row"
                className="w-full space-y-3 rounded border border-slate-200 bg-white p-4 shadow-sm"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <h2 className="text-sm font-semibold">{c.capability_key}</h2>
                    <p className="text-xs text-slate-500">
                      {CAPABILITY_DESCRIPTIONS[c.capability_key] ?? c.adapter_kind}
                    </p>
                  </div>
                  <span className="text-xs text-slate-400">
                    更新 {formatDateTime(c.updated_at)}
                  </span>
                </div>
                <div className="flex flex-wrap items-center gap-4">
                  <label className="flex cursor-pointer items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      aria-label={`${c.capability_key}の有効化`}
                      checked={row.enabled}
                      disabled={row.busy}
                      onChange={(e) =>
                        patchRow(c.capability_key, {
                          enabled: e.target.checked,
                          saved: false,
                          error: null,
                        })
                      }
                      className="cursor-pointer disabled:cursor-not-allowed"
                    />
                    有効
                  </label>
                  <label className="flex items-center gap-2 text-sm">
                    承認ポリシー
                    <select
                      aria-label={`${c.capability_key}の承認ポリシー`}
                      value={row.approvalPolicy}
                      disabled={row.busy}
                      onChange={(e) =>
                        patchRow(c.capability_key, {
                          approvalPolicy: e.target.value as
                            | "auto"
                            | "plan_required",
                          saved: false,
                          error: null,
                        })
                      }
                      className="cursor-pointer rounded border border-slate-300 px-2 py-1 text-sm disabled:cursor-not-allowed"
                    >
                      <option value="auto">auto(承認不要)</option>
                      <option value="plan_required">plan_required(Plan一括承認)</option>
                    </select>
                  </label>
                  <button
                    type="button"
                    disabled={!dirty || row.busy}
                    onClick={() => void save(c)}
                    className="cursor-pointer rounded bg-blue-600 px-3 py-1.5 text-xs text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    保存
                  </button>
                  {row.saved && (
                    <span className="text-xs text-emerald-700">保存しました</span>
                  )}
                  {row.error && (
                    <span className="text-xs text-rose-700">{row.error}</span>
                  )}
                </div>
              </section>
            );
          })}
        </div>
      </div>
    </div>
  );
}
