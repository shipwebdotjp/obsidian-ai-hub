import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  createWorkflowRevision,
  createWorkflowUserTemplate,
  deleteWorkflow,
  deleteWorkflowRevision,
  exportWorkflowRevision,
  getWorkflow,
  listWorkflowUserTemplates,
  updateWorkflow,
  updateWorkflowUserTemplate,
} from "../../api/client";
import type { WorkflowDefinitionFormat, WorkflowDetail, WorkflowUserTemplate } from "../../api/types";
import {
  ROUTES,
  workflowEditPath,
  workflowRunPath,
} from "../../constants/routes";
import { formatDateTime } from "../../utils/date";
import { getApiErrorMessage } from "../../utils/error";
import { downloadDefinition, safeDefinitionFilename } from "./definitionDownload";
import { REVISION_STATUS_LABEL } from "./revisionLabels";
import { runStatusLabel } from "./runStatusLabels";

export default function WorkflowDetailPage() {
  const { workflowId = "" } = useParams();
  const navigate = useNavigate();
  const [workflow, setWorkflow] = useState<WorkflowDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [nameDraft, setNameDraft] = useState("");
  const [descriptionDraft, setDescriptionDraft] = useState("");
  const [userTemplates, setUserTemplates] = useState<WorkflowUserTemplate[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState("");

  const reload = useCallback(async () => {
    setError(null);
    try {
      setWorkflow(await getWorkflow(workflowId));
    } catch (e) {
      setError(getApiErrorMessage(e, "読み込みに失敗しました"));
    }
  }, [workflowId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  useEffect(() => {
    let cancelled = false;
    listWorkflowUserTemplates()
      .then((res) => {
        if (!cancelled) setUserTemplates(res.items);
      })
      .catch(() => {
        // The template picker is optional; the page still works without it.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const startEditing = () => {
    setNameDraft(workflow?.name ?? "");
    setDescriptionDraft(workflow?.description ?? "");
    setEditing(true);
  };

  const onSave = async () => {
    if (!nameDraft.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await updateWorkflow(workflowId, {
        name: nameDraft.trim(),
        description: descriptionDraft.trim(),
      });
      setEditing(false);
      await reload();
    } catch (e) {
      setError(getApiErrorMessage(e, "更新に失敗しました"));
    } finally {
      setBusy(false);
    }
  };

  const onDeleteWorkflow = async () => {
    if (
      !window.confirm(
        "このワークフローと実行履歴をすべて削除しますか？この操作は取り消せません。",
      )
    ) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await deleteWorkflow(workflowId);
      navigate(ROUTES.WORKFLOWS);
    } catch (e) {
      setError(getApiErrorMessage(e, "削除に失敗しました"));
    } finally {
      setBusy(false);
    }
  };

  const onNewRevision = async () => {
    setBusy(true);
    try {
      await createWorkflowRevision(workflowId);
      await reload();
    } catch (e) {
      setError(getApiErrorMessage(e, "Revision 作成に失敗しました"));
    } finally {
      setBusy(false);
    }
  };

  const onDeleteRevision = async (revisionId: string, version: number, status: string) => {
    const statusLabel = REVISION_STATUS_LABEL[status] ?? status;
    if (
      !window.confirm(
        `v${version}（${statusLabel}）を完全に削除しますか？この操作は取り消せません。`,
      )
    ) {
      return;
    }
    setBusy(true);
    try {
      await deleteWorkflowRevision(revisionId);
      await reload();
    } catch (e) {
      setError(getApiErrorMessage(e, "Revision 削除に失敗しました"));
    } finally {
      setBusy(false);
    }
  };

  const onSaveAsTemplate = async (revisionId: string) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const created = await createWorkflowUserTemplate({
        source_revision_id: revisionId,
        name: workflow?.name,
        description: workflow?.description,
      });
      setUserTemplates((prev) => [created, ...prev]);
      setNotice("テンプレートとして保存しました");
    } catch (e) {
      setError(getApiErrorMessage(e, "テンプレートの保存に失敗しました"));
    } finally {
      setBusy(false);
    }
  };

  const onUpdateTemplate = async (revisionId: string) => {
    if (!selectedTemplateId) return;
    const target = userTemplates.find(
      (template) => template.template_id === selectedTemplateId,
    );
    if (
      !window.confirm(
        `テンプレート「${target?.name ?? selectedTemplateId}」の内容を` +
          "この公開 Revision の定義で置き換えますか？" +
          "過去にこのテンプレートから作成したワークフローは変更されません。",
      )
    ) {
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await updateWorkflowUserTemplate(selectedTemplateId, {
        source_revision_id: revisionId,
      });
      setNotice("テンプレートの内容を更新しました");
    } catch (e) {
      setError(getApiErrorMessage(e, "テンプレートの更新に失敗しました"));
    } finally {
      setBusy(false);
    }
  };

  const onDownloadRevision = async (
    revisionId: string,
    format: WorkflowDefinitionFormat,
  ) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const text = await exportWorkflowRevision(revisionId, format);
      downloadDefinition(
        `${safeDefinitionFilename(workflow?.name ?? "")}.${format}`,
        text,
        format,
      );
    } catch (e) {
      setError(getApiErrorMessage(e, "ダウンロードに失敗しました"));
    } finally {
      setBusy(false);
    }
  };

  if (!workflow) {
    return (
      <div className="p-4 text-sm text-slate-500">
        {error ?? "読み込み中…"}
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-auto bg-slate-50">
      <header className="border-b border-slate-200 bg-white px-4 py-3">
        <div className="flex items-center justify-between gap-4">
          {editing ? (
            <div className="flex flex-1 flex-wrap items-end gap-2">
              <label className="text-xs text-slate-600">
                名前
                <input
                  className="ml-1 rounded border border-slate-300 px-2 py-1 text-sm"
                  value={nameDraft}
                  onChange={(event) => setNameDraft(event.target.value)}
                />
              </label>
              <label className="text-xs text-slate-600">
                説明
                <input
                  className="ml-1 rounded border border-slate-300 px-2 py-1 text-sm"
                  value={descriptionDraft}
                  onChange={(event) => setDescriptionDraft(event.target.value)}
                />
              </label>
              <button
                type="button"
                onClick={onSave}
                disabled={busy || !nameDraft.trim()}
                className="cursor-pointer rounded bg-blue-600 px-3 py-1.5 text-xs text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                保存
              </button>
              <button
                type="button"
                onClick={() => setEditing(false)}
                disabled={busy}
                className="cursor-pointer rounded bg-slate-900 px-3 py-1.5 text-xs text-white disabled:opacity-50"
              >
                キャンセル
              </button>
            </div>
          ) : (
            <div>
              <h1 className="text-lg font-semibold">{workflow.name}</h1>
              <p className="text-xs text-slate-500">{workflow.description}</p>
            </div>
          )}
          {!editing && (
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={startEditing}
                disabled={busy}
                className="cursor-pointer rounded bg-slate-900 px-3 py-1.5 text-xs text-white disabled:opacity-50"
              >
                編集
              </button>
              <button
                type="button"
                onClick={onNewRevision}
                disabled={busy}
                className="cursor-pointer rounded bg-blue-600 px-3 py-1.5 text-xs text-white hover:bg-blue-700 disabled:opacity-50"
              >
                新しい下書き
              </button>
              <button
                type="button"
                onClick={onDeleteWorkflow}
                disabled={busy}
                className="cursor-pointer rounded bg-rose-800 px-3 py-1.5 text-xs text-white disabled:opacity-50"
              >
                Workflow を削除
              </button>
            </div>
          )}
        </div>
        {error && <p className="mt-2 text-xs text-rose-700">{error}</p>}
        {notice && <p className="mt-2 text-xs text-emerald-700">{notice}</p>}
      </header>

      <section className="px-4 py-3">
        <h2 className="mb-2 text-sm font-semibold">Revision</h2>
        <ul className="divide-y divide-slate-100 rounded border border-slate-200 bg-white">
          {(workflow.revisions ?? []).map((revision) => (
            <li
              key={revision.revision_id}
              className="flex items-center justify-between px-3 py-2 text-sm"
            >
              <span>
                v{revision.version} ・{" "}
                {REVISION_STATUS_LABEL[revision.status] ?? revision.status}
              </span>
              <span className="flex flex-wrap items-center gap-2">
                {revision.status === "draft" ? (
                  <Link
                    className="text-blue-700"
                    to={workflowEditPath(revision.revision_id)}
                  >
                    編集
                  </Link>
                ) : (
                  <span className="text-slate-400">編集不可</span>
                )}
                {revision.status === "published" && (
                  <>
                    <button
                      type="button"
                      onClick={() => onSaveAsTemplate(revision.revision_id)}
                      disabled={busy}
                      className="cursor-pointer rounded bg-emerald-600 px-2 py-0.5 text-xs text-white disabled:opacity-50"
                    >
                      Template 保存
                    </button>
                    <select
                      aria-label="更新するユーザーテンプレート"
                      className="rounded border border-slate-300 px-1 py-0.5 text-xs"
                      value={selectedTemplateId}
                      onChange={(event) => setSelectedTemplateId(event.target.value)}
                      disabled={busy || userTemplates.length === 0}
                    >
                      <option value="">テンプレート選択</option>
                      {userTemplates.map((template) => (
                        <option key={template.template_id} value={template.template_id}>
                          {template.name}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={() => onUpdateTemplate(revision.revision_id)}
                      disabled={busy || !selectedTemplateId}
                      className="cursor-pointer rounded bg-amber-600 px-2 py-0.5 text-xs text-white disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      内容を更新
                    </button>
                    <button
                      type="button"
                      onClick={() => onDownloadRevision(revision.revision_id, "json")}
                      disabled={busy}
                      className="cursor-pointer rounded border border-slate-300 px-2 py-0.5 text-xs hover:bg-slate-50 disabled:opacity-50"
                    >
                      JSON
                    </button>
                    <button
                      type="button"
                      onClick={() => onDownloadRevision(revision.revision_id, "yaml")}
                      disabled={busy}
                      className="cursor-pointer rounded border border-slate-300 px-2 py-0.5 text-xs hover:bg-slate-50 disabled:opacity-50"
                    >
                      YAML
                    </button>
                  </>
                )}
                {revision.status !== "published" && (
                  <button
                    type="button"
                    onClick={() =>
                      onDeleteRevision(
                        revision.revision_id,
                        revision.version,
                        revision.status,
                      )
                    }
                    disabled={busy}
                    className="cursor-pointer rounded bg-rose-800 px-2 py-0.5 text-xs text-white disabled:opacity-50"
                  >
                    削除
                  </button>
                )}
              </span>
            </li>
          ))}
        </ul>
      </section>

      <section className="px-4 py-3">
        <h2 className="mb-2 text-sm font-semibold">Run</h2>
        {(workflow.runs ?? []).length === 0 ? (
          <p className="text-xs text-slate-500">Run はありません。</p>
        ) : (
          <ul className="divide-y divide-slate-100 rounded border border-slate-200 bg-white">
            {(workflow.runs ?? []).map((run) => (
              <li
                key={run.run_id}
                className="flex items-center justify-between px-3 py-2 text-sm"
              >
                <span>
                  {runStatusLabel(run.status)} ・ {formatDateTime(run.created_at)}
                </span>
                <Link className="text-blue-700" to={workflowRunPath(run.run_id)}>
                  詳細
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
