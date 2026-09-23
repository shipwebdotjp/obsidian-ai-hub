import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  createWorkflow,
  createWorkflowFromTemplate,
  listWorkflowTemplates,
  listWorkflows,
} from "../../api/client";
import type { WorkflowSummary, WorkflowTemplate } from "../../api/types";
import PaginationBar from "../../components/PaginationBar";
import { usePagination } from "../../hooks/usePagination";
import {
  ROUTES,
  workflowDetailPath,
  workflowEditPath,
} from "../../constants/routes";
import { formatDateTime } from "../../utils/date";
import { getApiErrorMessage } from "../../utils/error";
import UserTemplatesSection from "./UserTemplatesSection";

export default function WorkflowsPage() {
  const navigate = useNavigate();
  const [items, setItems] = useState<WorkflowSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [creating, setCreating] = useState(false);
  const [templates, setTemplates] = useState<WorkflowTemplate[]>([]);
  const { page, limit, offset, total, totalPages, setTotal, setPage } =
    usePagination("workflows", 20);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listWorkflows({ limit, offset });
      setItems(res.items);
      setTotal(res.total);
    } catch (e) {
      setError(getApiErrorMessage(e, "読み込みに失敗しました"));
    } finally {
      setLoading(false);
    }
  }, [limit, offset, setTotal]);

  useEffect(() => {
    void reload();
  }, [reload]);

  useEffect(() => {
    let cancelled = false;
    listWorkflowTemplates()
      .then((res) => {
        if (!cancelled) setTemplates(res.items);
      })
      .catch(() => {
        // Template list is optional; the page still works without it.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const onCreate = async () => {
    if (!name.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const workflow = await createWorkflow({
        name: name.trim(),
        description: description.trim(),
      });
      const revisionId = workflow.revision?.revision_id;
      navigate(
        revisionId
          ? workflowEditPath(revisionId)
          : workflowDetailPath(workflow.workflow_id),
      );
    } catch (e) {
      setError(getApiErrorMessage(e, "作成に失敗しました"));
    } finally {
      setCreating(false);
    }
  };

  const onCreateFromTemplate = async (template: WorkflowTemplate) => {
    setCreating(true);
    setError(null);
    try {
      const workflow = await createWorkflowFromTemplate({
        template_key: template.template_key,
      });
      const revisionId = workflow.revision?.revision_id;
      navigate(
        revisionId
          ? workflowEditPath(revisionId)
          : workflowDetailPath(workflow.workflow_id),
      );
    } catch (e) {
      setError(getApiErrorMessage(e, "テンプレートからの作成に失敗しました"));
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="flex h-full flex-col bg-slate-50">
      <header className="border-b border-slate-200 bg-white px-4 py-3">
        <h1 className="text-lg font-semibold">ワークフロー</h1>
        <p className="text-xs text-slate-500">
          ノードグラフを設計し、承認付きで実行します。
        </p>
      </header>
      <section className="border-b border-slate-200 bg-white px-4 py-3">
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-xs text-slate-600">
            名前
            <input
              className="ml-1 rounded border border-slate-300 px-2 py-1 text-sm"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <label className="text-xs text-slate-600">
            説明
            <input
              className="ml-1 rounded border border-slate-300 px-2 py-1 text-sm"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </label>
          <button
            type="button"
            onClick={onCreate}
            disabled={creating || !name.trim()}
            className="cursor-pointer rounded bg-blue-600 px-3 py-1.5 text-xs text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            新規作成
          </button>
        </div>
        {error && <p className="mt-2 text-xs text-rose-700">{error}</p>}
      </section>
      {templates.length > 0 && (
        <section className="border-b border-slate-200 bg-white px-4 py-3">
          <h2 className="mb-2 text-xs font-semibold text-slate-600">
            テンプレートから作成
          </h2>
          <div className="flex flex-wrap gap-2">
            {templates.map((template) => (
              <button
                key={template.template_key}
                type="button"
                disabled={creating}
                onClick={() => onCreateFromTemplate(template)}
                className="cursor-pointer rounded border border-slate-300 px-3 py-1.5 text-xs hover:bg-slate-50 disabled:opacity-50"
                title={template.description}
              >
                {template.name}
              </button>
            ))}
          </div>
        </section>
      )}
      <UserTemplatesSection />
      <div className="flex-1 overflow-auto">
        {loading ? (
          <p className="p-4 text-sm text-slate-500">読み込み中…</p>
        ) : items.length === 0 ? (
          <p className="p-4 text-sm text-slate-500">ワークフローはありません。</p>
        ) : (
          <ul className="divide-y divide-slate-100 bg-white">
            {items.map((workflow) => (
              <li key={workflow.workflow_id}>
                <Link
                  to={workflowDetailPath(workflow.workflow_id)}
                  className="block px-4 py-3 hover:bg-slate-50"
                >
                  <div className="text-sm font-medium">{workflow.name}</div>
                  <div className="text-xs text-slate-500">
                    {workflow.description || "説明なし"} ・ 更新{" "}
                    {formatDateTime(workflow.updated_at)}
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
      <PaginationBar
        page={page}
        totalPages={totalPages}
        total={total}
        limit={limit}
        onPageChange={setPage}
        disabled={loading}
      />
      <div className="border-t border-slate-200 bg-white px-4 py-2 text-xs">
        <Link className="text-blue-700" to={ROUTES.TASK_AGENT}>
          Task Agent へ
        </Link>
      </div>
    </div>
  );
}
