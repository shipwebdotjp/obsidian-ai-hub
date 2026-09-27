import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  createWorkflowRevision,
  createWorkflowRun,
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
import Modal from "../../components/Modal";
import { ActionMenu } from "../../components/ActionMenu";
import { downloadDefinition, safeDefinitionFilename } from "./definitionDownload";
import { REVISION_STATUS_LABEL } from "./revisionLabels";
import { confirmAndDeleteRun } from "./runActions";
import { runStatusLabel, TERMINAL_RUN_STATUSES } from "./runStatusLabels";
import InputsSchemaForm from "./InputsSchemaForm";
import { WorkflowBreadcrumb } from "./WorkflowBreadcrumb";

const NEUTRAL_BADGE =
  "rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold text-slate-500";

const REVISION_STATUS_BADGE: Record<string, string> = {
  draft: "rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-800",
  published: "rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-800",
  superseded: NEUTRAL_BADGE,
};

function RevisionBadge({ status }: { status: string }) {
  return (
    <span className={REVISION_STATUS_BADGE[status] ?? NEUTRAL_BADGE}>
      {REVISION_STATUS_LABEL[status] ?? status}
    </span>
  );
}

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
  const [skipApprovalDraft, setSkipApprovalDraft] = useState(false);
  const [userTemplates, setUserTemplates] = useState<WorkflowUserTemplate[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState("");
  const [runRevisionId, setRunRevisionId] = useState<string | null>(null);
  const [runInputs, setRunInputs] = useState<Record<string, unknown>>({});
  const [runErrors, setRunErrors] = useState<string[]>([]);
  const [templateDialogFor, setTemplateDialogFor] = useState<string | null>(null);
  const [templateDialogError, setTemplateDialogError] = useState<string | null>(null);
  const [showOldRevisions, setShowOldRevisions] = useState(false);

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
    setSkipApprovalDraft(workflow?.skip_approval ?? false);
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
        skip_approval: skipApprovalDraft,
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
      const created = await createWorkflowRevision(workflowId);
      navigate(workflowEditPath(created.revision_id));
    } catch (e) {
      setError(getApiErrorMessage(e, "Revision 作成に失敗しました"));
    } finally {
      setBusy(false);
    }
  };

  const onStartRun = async (revisionId: string) => {
    setBusy(true);
    setError(null);
    setRunErrors([]);
    try {
      const run = await createWorkflowRun(revisionId, runInputs);
      navigate(workflowRunPath(run.run_id));
    } catch (e) {
      const detail = (e as { body?: { detail?: { errors?: string[] } } })?.body
        ?.detail;
      setRunErrors(Array.isArray(detail?.errors) ? detail.errors : []);
      setError(getApiErrorMessage(e, "実行に失敗しました"));
    } finally {
      setBusy(false);
    }
  };

  const onDeleteRun = async (runId: string) => {
    setBusy(true);
    setError(null);
    try {
      if (await confirmAndDeleteRun(runId)) {
        await reload();
      }
    } catch (e) {
      setError(getApiErrorMessage(e, "Run 削除に失敗しました"));
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

  const closeTemplateDialog = () => {
    setTemplateDialogFor(null);
    setTemplateDialogError(null);
    setSelectedTemplateId("");
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
    setTemplateDialogError(null);
    try {
      await updateWorkflowUserTemplate(selectedTemplateId, {
        source_revision_id: revisionId,
      });
      closeTemplateDialog();
      setNotice("テンプレートの内容を更新しました");
    } catch (e) {
      const message = getApiErrorMessage(e, "テンプレートの更新に失敗しました");
      setTemplateDialogError(message);
      setError(message);
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

  const revisions = workflow.revisions ?? [];
  const publishedRevision =
    revisions.find((revision) => revision.status === "published") ?? null;
  const draftRevisions = revisions.filter(
    (revision) => revision.status === "draft",
  );
  const oldRevisions = revisions.filter(
    (revision) =>
      revision.status !== "published" && revision.status !== "draft",
  );

  return (
    <div className="flex h-full flex-col overflow-auto bg-slate-50">
      <WorkflowBreadcrumb items={[{ label: workflow.name }]} />
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
              <label className="flex cursor-pointer items-center gap-1 text-xs text-slate-600">
                <input
                  type="checkbox"
                  className="cursor-pointer"
                  checked={skipApprovalDraft}
                  onChange={(event) =>
                    setSkipApprovalDraft(event.target.checked)
                  }
                />
                承認なしで実行する
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
        <h2 className="mb-2 text-sm font-semibold">公開中の Revision</h2>
        {publishedRevision ? (
          <div className="rounded border border-emerald-200 bg-white px-3 py-2">
            <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <span className="flex items-center gap-2">
                v{publishedRevision.version} <RevisionBadge status={publishedRevision.status} />
              </span>
              <span className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => {
                    setRunRevisionId(
                      runRevisionId === publishedRevision.revision_id
                        ? null
                        : publishedRevision.revision_id,
                    );
                    setRunInputs({});
                    setRunErrors([]);
                  }}
                  disabled={busy}
                  data-testid="run-form-toggle"
                  className="cursor-pointer rounded bg-blue-600 px-3 py-1 text-xs text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  実行
                </button>
                <ActionMenu
                  testId="revision-menu"
                  disabled={busy}
                  items={[
                    {
                      label: "テンプレートとして保存",
                      testId: "menu-save-template",
                      onSelect: () => void onSaveAsTemplate(publishedRevision.revision_id),
                    },
                    {
                      label: "テンプレートを更新…",
                      testId: "menu-update-template",
                      disabled: userTemplates.length === 0,
                      onSelect: () => {
                        setTemplateDialogError(null);
                        setTemplateDialogFor(publishedRevision.revision_id);
                      },
                    },
                    {
                      label: "JSON をダウンロード",
                      testId: "menu-download-json",
                      onSelect: () =>
                        void onDownloadRevision(publishedRevision.revision_id, "json"),
                    },
                    {
                      label: "YAML をダウンロード",
                      testId: "menu-download-yaml",
                      onSelect: () =>
                        void onDownloadRevision(publishedRevision.revision_id, "yaml"),
                    },
                  ]}
                />
              </span>
            </div>
            {runRevisionId === publishedRevision.revision_id && (
              <div className="mt-2 border-t border-emerald-100 pt-2">
                <InputsSchemaForm
                  schema={publishedRevision.inputs_schema ?? { type: "object" }}
                  values={runInputs}
                  onChange={setRunInputs}
                  errors={runErrors}
                />
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={() => void onStartRun(publishedRevision.revision_id)}
                    disabled={busy}
                    data-testid="run-start"
                    className="cursor-pointer rounded bg-blue-600 px-3 py-1 text-xs text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    この入力で実行
                  </button>
                  <span className="text-[11px] text-slate-500">
                    承認が必要な場合は承認待ちで作成されます
                  </span>
                </div>
              </div>
            )}
          </div>
        ) : (
          <p className="text-xs text-slate-500">公開中の Revision はありません。</p>
        )}
      </section>

      <section className="px-4 py-3">
        <h2 className="mb-2 text-sm font-semibold">下書き</h2>
        {draftRevisions.length === 0 ? (
          <p className="text-xs text-slate-500">下書きはありません。</p>
        ) : (
          <ul className="divide-y divide-slate-100 rounded border border-slate-200 bg-white">
            {draftRevisions.map((revision) => (
              <li
                key={revision.revision_id}
                className="flex items-center justify-between px-3 py-2 text-sm"
              >
                <span className="flex items-center gap-2">
                  v{revision.version} <RevisionBadge status={revision.status} />
                </span>
                <span className="flex flex-wrap items-center gap-2">
                  <Link
                    className="text-blue-700"
                    to={workflowEditPath(revision.revision_id)}
                  >
                    編集
                  </Link>
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
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {oldRevisions.length > 0 && (
        <section className="px-4 py-3">
          <button
            type="button"
            onClick={() => setShowOldRevisions((value) => !value)}
            aria-expanded={showOldRevisions}
            data-testid="old-revisions-toggle"
            className="cursor-pointer text-sm font-semibold text-slate-600 hover:text-slate-900"
          >
            {showOldRevisions ? "旧版を隠す" : `旧版を表示 (${oldRevisions.length})`}
          </button>
          {showOldRevisions && (
            <ul className="mt-2 divide-y divide-slate-100 rounded border border-slate-200 bg-white">
              {oldRevisions.map((revision) => (
                <li
                  key={revision.revision_id}
                  className="flex items-center justify-between px-3 py-2 text-sm"
                >
                  <span className="flex items-center gap-2">
                    v{revision.version} <RevisionBadge status={revision.status} />
                  </span>
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="text-slate-400">編集不可</span>
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
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {templateDialogFor && (
        <Modal onClose={closeTemplateDialog} labelledBy="template-dialog-title">
          <h2 id="template-dialog-title" className="text-sm font-semibold">
            テンプレートを更新
          </h2>
          <p className="text-xs text-slate-600">
            公開 Revision の定義でテンプレートを置き換えます。過去にこのテンプレート
            から作成したワークフローは変更されません。
          </p>
          {templateDialogError && (
            <p className="text-xs text-rose-700">{templateDialogError}</p>
          )}
          <select
            aria-label="更新するユーザーテンプレート"
            className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
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
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={closeTemplateDialog}
              disabled={busy}
              className="cursor-pointer rounded bg-slate-900 px-3 py-1.5 text-xs text-white disabled:opacity-50"
            >
              キャンセル
            </button>
            <button
              type="button"
              onClick={() => void onUpdateTemplate(templateDialogFor)}
              disabled={busy || !selectedTemplateId}
              data-testid="template-update-confirm"
              className="cursor-pointer rounded bg-amber-600 px-3 py-1.5 text-xs text-white hover:bg-amber-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              内容を更新
            </button>
          </div>
        </Modal>
      )}

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
                <span className="flex items-center gap-2">
                  <Link className="text-blue-700" to={workflowRunPath(run.run_id)}>
                    詳細
                  </Link>
                  {TERMINAL_RUN_STATUSES.has(run.status) && (
                    <button
                      type="button"
                      className="cursor-pointer rounded bg-rose-800 px-2 py-0.5 text-xs text-white disabled:opacity-50"
                      disabled={busy}
                      data-testid={`run-delete-${run.run_id}`}
                      onClick={() => void onDeleteRun(run.run_id)}
                    >
                      削除
                    </button>
                  )}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
