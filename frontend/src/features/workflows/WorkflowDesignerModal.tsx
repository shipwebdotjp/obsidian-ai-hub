import { useState, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { composeDesignerWorkflow, importWorkflowDefinition, ApiError } from "../../api/client";
import type { DesignerComposeResponse } from "../../api/types";
import { workflowEditPath } from "../../constants/routes";
import { getApiErrorMessage } from "../../utils/error";

interface WorkflowDesignerModalProps {
  isOpen: boolean;
  onClose: () => void;
}

type Stage = "input" | "generating" | "preview";

export default function WorkflowDesignerModal({ isOpen, onClose }: WorkflowDesignerModalProps) {
  const navigate = useNavigate();
  const [stage, setStage] = useState<Stage>("input");
  const [requirement, setRequirement] = useState("");
  const [composeResult, setComposeResult] = useState<DesignerComposeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notConfigured, setNotConfigured] = useState(false);
  const [importing, setImporting] = useState(false);

  const abortControllerRef = useRef<AbortController | null>(null);

  if (!isOpen) return null;

  const handleStartCompose = async () => {
    if (!requirement.trim()) return;
    setStage("generating");
    setError(null);
    setNotConfigured(false);
    setComposeResult(null);

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const res = await composeDesignerWorkflow(requirement.trim(), controller.signal);
      setComposeResult(res);
      setStage("preview");
    } catch (err: unknown) {
      if (err instanceof Error && err.name === "AbortError") {
        setStage("input");
        return;
      }
      if (err instanceof ApiError && err.status === 503) {
        setNotConfigured(true);
        setError("llm.workflow_designer の provider または model が未設定です。config.yml の llm.workflow_designer 設定を確認してください。");
      } else {
        setError(getApiErrorMessage(err, "下書きの生成に失敗しました"));
      }
      setStage("input");
    } finally {
      abortControllerRef.current = null;
    }
  };

  const handleAbort = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setStage("input");
  };

  const handleReset = () => {
    setStage("input");
    setComposeResult(null);
    setError(null);
  };

  const handleCloseModal = () => {
    handleAbort();
    handleReset();
    onClose();
  };

  const handleCreateDraft = async () => {
    if (!composeResult || !composeResult.package) return;
    setImporting(true);
    setError(null);
    try {
      const packageJson = JSON.stringify(composeResult.package);
      const imported = await importWorkflowDefinition(packageJson, "json");
      const revisionId = imported.revision?.revision_id;
      if (revisionId) {
        handleCloseModal();
        navigate(workflowEditPath(revisionId));
      } else {
        setError("下書きリビジョンの作成結果が見つかりませんでした");
      }
    } catch (err: unknown) {
      setError(getApiErrorMessage(err, "下書きの作成に失敗しました"));
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
      <div className="flex max-h-[85vh] w-full max-w-3xl flex-col rounded-lg bg-white shadow-xl">
        <header className="flex items-center justify-between border-b border-slate-200 px-5 py-3">
          <h2 className="text-base font-semibold text-slate-800">AIで下書きを作成 (Workflow Designer)</h2>
          <button
            type="button"
            onClick={handleCloseModal}
            className="text-slate-400 hover:text-slate-600"
          >
            ✕
          </button>
        </header>

        <div className="flex-1 overflow-y-auto p-5">
          {error && (
            <div className="mb-4 rounded border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700">
              <p className="font-semibold">{notConfigured ? "設定不足エラー" : "エラー"}</p>
              <p className="mt-0.5">{error}</p>
            </div>
          )}

          {stage === "input" && (
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-700">
                  作成したいワークフローの要望
                </label>
                <textarea
                  value={requirement}
                  onChange={(e) => setRequirement(e.target.value)}
                  placeholder="例: Vault 内の daily ノートを検索して読み込み、要約を Agent で生成して指定されたプロジェクトへ結果を登録するワークフロー"
                  className="mt-1.5 h-32 w-full rounded border border-slate-300 p-2.5 text-xs text-slate-800 focus:border-blue-500 focus:outline-none"
                />
              </div>

              <div className="rounded border border-amber-200 bg-amber-50/60 p-3 text-[11px] text-amber-900 space-y-1">
                <p className="font-semibold text-amber-950">外部送信・ログ保存に関する注意事項</p>
                <ul className="list-disc pl-4 space-y-0.5">
                  <li>要望文、選択された名前・ID・相対パス、およびツール実行結果は外部 LLM プロバイダへ送信されます（Vault 本文・プロンプト全文は送信されません）。</li>
                  <li>すべてのやり取りは <code className="bg-amber-100 px-1 py-0.5 rounded">llm_call_logs</code> に記録されます（ログ削除ジョブ未導入時は長期間保持されます）。</li>
                  <li>生成中に「表示中止」を押してもサーバー側の LLM 処理停止は保証されません。ただし「下書きを作成」を押すまでワークフローは DB に保存されません。</li>
                </ul>
              </div>
            </div>
          )}

          {stage === "generating" && (
            <div className="flex flex-col items-center justify-center py-12 space-y-4">
              <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent"></div>
              <p className="text-sm font-medium text-slate-700">AI が要件を解析し、グラフ構造を下書きしています…</p>
              <p className="text-xs text-slate-500">（通常 10秒〜30秒程度かかります）</p>
            </div>
          )}

          {stage === "preview" && composeResult && (
            <div className="space-y-5 text-xs text-slate-800">
              <div className="rounded border border-slate-200 bg-slate-50 p-3">
                <h3 className="font-semibold text-slate-700 text-xs mb-1">グラフ概要</h3>
                <p className="text-slate-600">{composeResult.summary || "概要なし"}</p>
              </div>

              {composeResult.assumptions && composeResult.assumptions.length > 0 && (
                <div>
                  <h3 className="font-semibold text-slate-700 mb-1">前提事項</h3>
                  <ul className="list-disc pl-4 space-y-0.5 text-slate-600">
                    {composeResult.assumptions.map((item, i) => (
                      <li key={i}>{item}</li>
                    ))}
                  </ul>
                </div>
              )}

              {composeResult.node_analysis && composeResult.node_analysis.length > 0 && (
                <div>
                  <h3 className="font-semibold text-slate-700 mb-2">構成ノードの副作用と承認要否</h3>
                  <div className="divide-y divide-slate-200 border border-slate-200 rounded bg-white">
                    {composeResult.node_analysis.map((na) => (
                      <div key={na.node_id} className="p-2.5 space-y-1">
                        <div className="flex items-center justify-between">
                          <span className="font-medium text-slate-900">{na.label} ({na.node_type})</span>
                          {na.requires_approval ? (
                            <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-800">
                              承認が必要
                            </span>
                          ) : (
                            <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-600">
                              承認不要
                            </span>
                          )}
                        </div>
                        <p className="text-slate-600">副作用: {na.effects}</p>
                        <p className="text-slate-500 text-[10px]">{na.requires_approval_reason}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {composeResult.structural_errors && composeResult.structural_errors.length > 0 && (
                <div className="rounded border border-rose-200 bg-rose-50 p-3 text-rose-800">
                  <p className="font-semibold mb-1">構造エラー（下書き作成不可）</p>
                  <ul className="list-disc pl-4 space-y-0.5">
                    {composeResult.structural_errors.map((err, i) => (
                      <li key={i}>{err.message}</li>
                    ))}
                  </ul>
                </div>
              )}

              {composeResult.validation_issues && composeResult.validation_issues.length > 0 && (
                <div className="rounded border border-amber-200 bg-amber-50 p-3 text-amber-800">
                  <p className="font-semibold mb-1">静的検証警告（エディタで修正可能な下書きとして作成できます）</p>
                  <ul className="list-disc pl-4 space-y-0.5">
                    {composeResult.validation_issues.map((issue, i) => (
                      <li key={i}>{issue.message}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>

        <footer className="flex items-center justify-between border-t border-slate-200 px-5 py-3">
          {stage === "input" && (
            <>
              <button
                type="button"
                onClick={handleCloseModal}
                className="rounded border border-slate-300 px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50"
              >
                キャンセル
              </button>
              <button
                type="button"
                onClick={handleStartCompose}
                disabled={!requirement.trim()}
                className="rounded bg-blue-600 px-4 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                AI で生成開始
              </button>
            </>
          )}

          {stage === "generating" && (
            <button
              type="button"
              onClick={handleAbort}
              className="ml-auto rounded border border-rose-300 bg-rose-50 px-3 py-1.5 text-xs font-medium text-rose-700 hover:bg-rose-100"
            >
              表示中止
            </button>
          )}

          {stage === "preview" && (
            <>
              <button
                type="button"
                onClick={handleReset}
                className="rounded border border-slate-300 px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50"
              >
                要件を再入力
              </button>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={handleCloseModal}
                  className="rounded border border-slate-300 px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50"
                >
                  閉じる
                </button>
                <button
                  type="button"
                  onClick={handleCreateDraft}
                  disabled={importing || !composeResult?.package || (composeResult.structural_errors && composeResult.structural_errors.length > 0)}
                  className="cursor-pointer rounded bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {importing ? "下書き作成中…" : "下書きを作成"}
                </button>
              </div>
            </>
          )}
        </footer>
      </div>
    </div>
  );
}
