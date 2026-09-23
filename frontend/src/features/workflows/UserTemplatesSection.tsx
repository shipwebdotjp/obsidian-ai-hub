import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  deleteWorkflowUserTemplate,
  exportWorkflowUserTemplate,
  importWorkflowDefinition,
  instantiateWorkflowUserTemplate,
  listWorkflowUserTemplates,
  updateWorkflowUserTemplate,
} from "../../api/client";
import type {
  WorkflowDefinitionFormat,
  WorkflowUserTemplate,
} from "../../api/types";
import { workflowEditPath } from "../../constants/routes";
import { formatDateTime } from "../../utils/date";
import { getApiErrorMessage } from "../../utils/error";
import { downloadDefinition, safeDefinitionFilename } from "./definitionDownload";

export default function UserTemplatesSection() {
  const navigate = useNavigate();
  const [templates, setTemplates] = useState<WorkflowUserTemplate[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [nameDraft, setNameDraft] = useState("");
  const [descriptionDraft, setDescriptionDraft] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const reload = useCallback(async () => {
    setError(null);
    try {
      const res = await listWorkflowUserTemplates();
      if (mountedRef.current) setTemplates(res.items);
    } catch (e) {
      if (mountedRef.current) {
        setError(
          getApiErrorMessage(e, "ユーザーテンプレートの読み込みに失敗しました"),
        );
      }
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const goToDraft = (revisionId: string, validationErrors: string[]) => {
    navigate(workflowEditPath(revisionId), {
      state: { serverIssues: validationErrors },
    });
  };

  const onInstantiate = async (template: WorkflowUserTemplate) => {
    setBusy(true);
    setError(null);
    try {
      const res = await instantiateWorkflowUserTemplate(template.template_id, {
        name: template.name,
      });
      goToDraft(res.revision.revision_id, res.validation_errors);
    } catch (e) {
      setError(getApiErrorMessage(e, "テンプレートからの作成に失敗しました"));
    } finally {
      setBusy(false);
    }
  };

  const startEdit = (template: WorkflowUserTemplate) => {
    setEditingId(template.template_id);
    setNameDraft(template.name);
    setDescriptionDraft(template.description ?? "");
  };

  const onSaveEdit = async () => {
    if (!editingId || !nameDraft.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await updateWorkflowUserTemplate(editingId, {
        name: nameDraft.trim(),
        description: descriptionDraft.trim(),
      });
      setEditingId(null);
      await reload();
    } catch (e) {
      setError(getApiErrorMessage(e, "テンプレートの更新に失敗しました"));
    } finally {
      setBusy(false);
    }
  };

  const onDelete = async (template: WorkflowUserTemplate) => {
    if (
      !window.confirm(
        `テンプレート「${template.name}」を削除しますか？` +
          "このテンプレートから作成済みのワークフローは変更されません。",
      )
    ) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await deleteWorkflowUserTemplate(template.template_id);
      await reload();
    } catch (e) {
      setError(getApiErrorMessage(e, "テンプレートの削除に失敗しました"));
    } finally {
      setBusy(false);
    }
  };

  const onDownload = async (
    template: WorkflowUserTemplate,
    format: WorkflowDefinitionFormat,
  ) => {
    setBusy(true);
    setError(null);
    try {
      const text = await exportWorkflowUserTemplate(template.template_id, format);
      downloadDefinition(
        `${safeDefinitionFilename(template.name)}.${format}`,
        text,
        format,
      );
    } catch (e) {
      setError(getApiErrorMessage(e, "ダウンロードに失敗しました"));
    } finally {
      setBusy(false);
    }
  };

  const onImport = async (file: File) => {
    setBusy(true);
    setError(null);
    try {
      const lower = file.name.toLowerCase();
      const format: WorkflowDefinitionFormat =
        lower.endsWith(".yaml") || lower.endsWith(".yml") ? "yaml" : "json";
      const res = await importWorkflowDefinition(await file.text(), format);
      goToDraft(res.revision.revision_id, res.validation_errors);
    } catch (e) {
      setError(getApiErrorMessage(e, "import に失敗しました"));
    } finally {
      setBusy(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  return (
    <section className="border-b border-slate-200 bg-white px-4 py-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h2 className="text-xs font-semibold text-slate-600">
          ユーザーテンプレート
        </h2>
        <label className="cursor-pointer rounded border border-slate-300 px-3 py-1 text-xs hover:bg-slate-50">
          JSON/YAML を import
          <input
            ref={fileInputRef}
            type="file"
            accept=".json,.yaml,.yml,application/json,application/x-yaml"
            className="hidden"
            disabled={busy}
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void onImport(file);
            }}
          />
        </label>
      </div>
      {error && <p className="mb-2 text-xs text-rose-700">{error}</p>}
      {templates.length === 0 ? (
        <p className="text-xs text-slate-500">
          保存済みのテンプレートはありません。公開済み Revision の行から保存できます。
        </p>
      ) : (
        <ul className="divide-y divide-slate-100 rounded border border-slate-200">
          {templates.map((template) => (
            <li
              key={template.template_id}
              className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm"
            >
              {editingId === template.template_id ? (
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
                    onClick={onSaveEdit}
                    disabled={busy || !nameDraft.trim()}
                    className="cursor-pointer rounded bg-blue-600 px-2 py-0.5 text-xs text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    保存
                  </button>
                  <button
                    type="button"
                    onClick={() => setEditingId(null)}
                    disabled={busy}
                    className="cursor-pointer rounded bg-slate-900 px-2 py-0.5 text-xs text-white disabled:opacity-50"
                  >
                    キャンセル
                  </button>
                </div>
              ) : (
                <div className="min-w-0">
                  <div className="text-sm font-medium">{template.name}</div>
                  <div className="text-xs text-slate-500">
                    {template.description || "説明なし"} ・ 更新{" "}
                    {formatDateTime(template.updated_at)}
                  </div>
                </div>
              )}
              {editingId !== template.template_id && (
                <span className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={() => onInstantiate(template)}
                    disabled={busy}
                    className="cursor-pointer rounded bg-blue-600 px-2 py-0.5 text-xs text-white hover:bg-blue-700 disabled:opacity-50"
                  >
                    使って作成
                  </button>
                  <button
                    type="button"
                    onClick={() => startEdit(template)}
                    disabled={busy}
                    className="cursor-pointer rounded bg-slate-900 px-2 py-0.5 text-xs text-white disabled:opacity-50"
                  >
                    編集
                  </button>
                  <button
                    type="button"
                    onClick={() => onDownload(template, "json")}
                    disabled={busy}
                    className="cursor-pointer rounded border border-slate-300 px-2 py-0.5 text-xs hover:bg-slate-50 disabled:opacity-50"
                  >
                    JSON
                  </button>
                  <button
                    type="button"
                    onClick={() => onDownload(template, "yaml")}
                    disabled={busy}
                    className="cursor-pointer rounded border border-slate-300 px-2 py-0.5 text-xs hover:bg-slate-50 disabled:opacity-50"
                  >
                    YAML
                  </button>
                  <button
                    type="button"
                    onClick={() => onDelete(template)}
                    disabled={busy}
                    className="cursor-pointer rounded bg-rose-800 px-2 py-0.5 text-xs text-white disabled:opacity-50"
                  >
                    削除
                  </button>
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
