import { Trash2, X } from "lucide-react";
import { ClipboardIcon } from "../../components/ClipboardIcon";
import { AGENT_DELEGATE_TOOL_ID } from "./agentViewUtils";
import type {
  Agent,
  AgentPromptTemplate,
  AgentTool,
} from "../../api/types";

interface AgentFormPanelProps {
  isCreatingAgent: boolean;
  isEditingAgent: boolean;
  activeAgent: Agent | undefined;
  selectedAgentId: string | null;
  onDeleteAgentTarget: (agent: Agent) => void;
  onCloseForm: () => void;
  formError: string | null;
  onSaveAgent: (e: React.FormEvent) => void;
  formName: string;
  onFormNameChange: (v: string) => void;
  formPrompt: string;
  onFormPromptChange: (v: string) => void;
  formProvider: string;
  onFormProviderChange: (v: string) => void;
  formModel: string;
  onFormModelChange: (v: string) => void;
  isAdvancedOpen: boolean;
  onAdvancedOpenChange: (open: boolean) => void;
  formMaxTokens: string;
  onFormMaxTokensChange: (v: string) => void;
  formReasoningEffort: string;
  onFormReasoningEffortChange: (v: string) => void;
  availableTools: AgentTool[];
  formToolIds: string[];
  onFormToolIdsChange: (ids: string[]) => void;
  agents: Agent[];
  formDelegateAgentIds: string[];
  onFormDelegateAgentIdsChange: (ids: string[]) => void;
  copiedAgentId: boolean;
  agentIdCopyError: string | null;
  onCopyAgentId: () => void;
  promptTemplates: AgentPromptTemplate[];
  templateLoading: boolean;
  templateError: string | null;
  editingTemplateId: string | null;
  onEditTemplate: (t: AgentPromptTemplate) => void;
  onDeleteTemplate: (templateId: string) => void;
  onCreateOrUpdateTemplate: (e: React.FormEvent) => void;
  templateFormName: string;
  onTemplateFormNameChange: (v: string) => void;
  templateFormContent: string;
  onTemplateFormContentChange: (v: string) => void;
  onCancelEditTemplate: () => void;
}

/** エージェント新規作成・設定編集フォームとテンプレート管理。 */
export function AgentFormPanel({
  isCreatingAgent,
  isEditingAgent,
  activeAgent,
  selectedAgentId,
  onDeleteAgentTarget,
  onCloseForm,
  formError,
  onSaveAgent,
  formName,
  onFormNameChange,
  formPrompt,
  onFormPromptChange,
  formProvider,
  onFormProviderChange,
  formModel,
  onFormModelChange,
  isAdvancedOpen,
  onAdvancedOpenChange,
  formMaxTokens,
  onFormMaxTokensChange,
  formReasoningEffort,
  onFormReasoningEffortChange,
  availableTools,
  formToolIds,
  onFormToolIdsChange,
  agents,
  formDelegateAgentIds,
  onFormDelegateAgentIdsChange,
  copiedAgentId,
  agentIdCopyError,
  onCopyAgentId,
  promptTemplates,
  templateLoading,
  templateError,
  editingTemplateId,
  onEditTemplate,
  onDeleteTemplate,
  onCreateOrUpdateTemplate,
  templateFormName,
  onTemplateFormNameChange,
  templateFormContent,
  onTemplateFormContentChange,
  onCancelEditTemplate,
}: AgentFormPanelProps) {
  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="mx-auto max-w-2xl rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="mb-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            {isEditingAgent && activeAgent && (
              <button
                type="button"
                onClick={() => onDeleteAgentTarget(activeAgent)}
                className="inline-flex h-7 w-7 items-center justify-center rounded text-rose-600 hover:bg-rose-50 cursor-pointer"
                aria-label="エージェントを削除"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            )}
            <h3 className="text-base font-semibold text-slate-900">
              {isCreatingAgent
                ? "新規エージェント作成"
                : "エージェント設定編集"}
            </h3>
          </div>
          <button
            type="button"
            onClick={onCloseForm}
            className="inline-flex h-7 w-7 items-center justify-center rounded text-slate-400 hover:bg-slate-100 hover:text-slate-700 cursor-pointer"
            aria-label="閉じる"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {formError && (
          <div className="mb-4 rounded-lg bg-red-50 p-3 text-xs text-red-600">
            {formError}
          </div>
        )}

        <form onSubmit={onSaveAgent} className="space-y-4 text-xs">
          {isEditingAgent && (
            <div>
              <span className="block font-medium text-slate-700 mb-1">
                エージェントID（CLI用）
              </span>
              {selectedAgentId ? (
                <>
                  <div className="flex items-center gap-2">
                    <code
                      data-testid="agent-id-value"
                      className="min-w-0 flex-1 truncate rounded-md border border-slate-200 bg-slate-50 px-2 py-1.5 font-mono text-[11px] text-slate-800"
                    >
                      {selectedAgentId}
                    </code>
                    <button
                      type="button"
                      onClick={onCopyAgentId}
                      className="inline-flex shrink-0 items-center gap-1 cursor-pointer rounded border border-slate-300 bg-white px-2 py-1 text-[11px] text-slate-700 hover:bg-slate-50"
                      aria-label="エージェントIDをコピー"
                      title="エージェントIDをコピー"
                      data-testid="copy-agent-id"
                    >
                      {copiedAgentId ? (
                        <>
                          <svg
                            className="h-3.5 w-3.5 text-emerald-600"
                            fill="none"
                            viewBox="0 0 24 24"
                            stroke="currentColor"
                            aria-hidden="true"
                          >
                            <path
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              strokeWidth={2}
                              d="M5 13l4 4L19 7"
                            />
                          </svg>
                          <span className="text-emerald-700">コピーしました</span>
                        </>
                      ) : (
                        <>
                          <ClipboardIcon />
                          <span>コピー</span>
                        </>
                      )}
                    </button>
                  </div>
                  <p className="mt-1 text-[10px] text-slate-500">
                    CLI の --agent-chat で指定するIDです（例: --agent-id {selectedAgentId}）。
                  </p>
                  {agentIdCopyError && (
                    <p role="alert" className="mt-1 text-[11px] text-red-600">
                      {agentIdCopyError}
                    </p>
                  )}
                </>
              ) : (
                <p className="text-[11px] text-slate-500">
                  IDを取得できませんでした。
                </p>
              )}
            </div>
          )}
          <div>
            <label className="block font-medium text-slate-700 mb-1">
              エージェント名 <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              required
              value={formName}
              onChange={(e) => onFormNameChange(e.target.value)}
              placeholder="例: 予定アシスタント"
              className="w-full rounded-md border border-slate-300 p-2 text-xs focus:border-slate-500 focus:outline-none"
            />
          </div>

          <div>
            <label className="block font-medium text-slate-700 mb-1">
              システムプロンプト <span className="text-red-500">*</span>
            </label>
            <textarea
              required
              rows={4}
              value={formPrompt}
              onChange={(e) => onFormPromptChange(e.target.value)}
              placeholder="エージェントの役割や振る舞いを指示します"
              className="w-full rounded-md border border-slate-300 p-2 text-xs focus:border-slate-500 focus:outline-none"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block font-medium text-slate-700 mb-1">
                LLM Provider (任意)
              </label>
              <input
                type="text"
                value={formProvider}
                onChange={(e) => onFormProviderChange(e.target.value)}
                placeholder="空欄でアプリ既定値"
                className="w-full rounded-md border border-slate-300 p-2 text-xs focus:border-slate-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block font-medium text-slate-700 mb-1">
                LLM Model (任意)
              </label>
              <input
                type="text"
                value={formModel}
                onChange={(e) => onFormModelChange(e.target.value)}
                placeholder="空欄でアプリ既定値"
                className="w-full rounded-md border border-slate-300 p-2 text-xs focus:border-slate-500 focus:outline-none"
              />
            </div>
          </div>
          <p className="text-[11px] text-slate-500">
            ※ Provider / Model が空欄の場合はアプリ全体の既定LLM設定が自動適用されます。
          </p>

          <details
            open={isAdvancedOpen}
            onToggle={(e) => onAdvancedOpenChange(e.currentTarget.open)}
            className="rounded-md border border-slate-200 bg-slate-50/50"
          >
            <summary className="cursor-pointer list-none flex items-center justify-between px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50">
              <span>高度なパラメーター</span>
              <span className="text-[10px] text-slate-400">{isAdvancedOpen ? "▲" : "▼"}</span>
            </summary>
            <div className="border-t border-slate-200 bg-white p-3 space-y-3">
              <div>
                <label className="block font-medium text-slate-700 mb-1">
                  最大トークン数 (max_tokens / max_output_tokens)
                </label>
                <input
                  type="number"
                  value={formMaxTokens}
                  onChange={(e) => onFormMaxTokensChange(e.target.value)}
                  placeholder="例: 4096 (空欄で既定値)"
                  className="w-full rounded-md border border-slate-300 p-2 text-xs focus:border-slate-500 focus:outline-none"
                />
                <p className="mt-1 text-[10px] text-slate-500">
                  OpenAI は Responses API では max_output_tokens、Chat Completions では max_completion_tokens へ、Ollama では num_predict へ自動マッピングされます。
                </p>
              </div>
              <div>
                <label className="block font-medium text-slate-700 mb-1">
                  reasoning.effort
                </label>
                <input
                  type="text"
                  value={formReasoningEffort}
                  onChange={(e) => onFormReasoningEffortChange(e.target.value)}
                  placeholder="例: low / medium / high (空欄で既定値)"
                  className="w-full rounded-md border border-slate-300 p-2 text-xs focus:border-slate-500 focus:outline-none"
                />
                <p className="mt-1 text-[10px] text-slate-500">
                  OpenAI/opencode_go では reasoning_effort、Ollama では reasoning へマッピングされます。
                </p>
              </div>
            </div>
          </details>

          <div>
            <label className="block font-medium text-slate-700 mb-2">
              利用可能ツール選択
            </label>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 border border-slate-200 rounded-md p-3 max-h-48 overflow-y-auto">
              {availableTools.length === 0 ? (
                <p className="text-[11px] text-slate-400 italic">利用可能なツールがありません。</p>
              ) : (
              availableTools.map((t) => {
                const checked = formToolIds.includes(t.tool_id);
                return (
                  <label
                    key={t.tool_id}
                    className="flex items-start gap-2 text-xs cursor-pointer hover:bg-slate-50 p-1 rounded"
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={(e) => {
                        if (e.target.checked) {
                          onFormToolIdsChange([...formToolIds, t.tool_id]);
                        } else {
                          onFormToolIdsChange(
                            formToolIds.filter((id) => id !== t.tool_id)
                          );
                        }
                      }}
                      className="mt-0.5 cursor-pointer"
                    />
                    <div>
                      <span className="font-semibold text-slate-800">
                        {t.name}
                      </span>
                      <p className="text-[10px] text-slate-500">
                        {t.description}
                      </p>
                    </div>
                  </label>
                );
              })
              )}
            </div>
          </div>

          {formToolIds.includes(AGENT_DELEGATE_TOOL_ID) && (
            <div className="rounded-md border border-slate-200 bg-white p-3">
              <label className="block font-medium text-slate-700 mb-1">
                許可する委譲先エージェント
              </label>
              <p className="text-[10px] text-slate-500 mb-2">
                このエージェントが agent_delegate ツールで委譲できる別エージェントを選択してください（自身を除く）。
              </p>
              {(() => {
                const otherAgents = agents.filter(
                  (a) => !isEditingAgent || a.agent_id !== selectedAgentId
                );
                if (otherAgents.length === 0) {
                  return (
                    <p className="text-[11px] text-slate-400 italic">
                      委譲可能な他のエージェントが登録されていません。
                    </p>
                  );
                }
                return (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 border border-slate-200 bg-white rounded-md p-2 max-h-36 overflow-y-auto">
                    {otherAgents.map((target) => {
                      const isChecked = formDelegateAgentIds.includes(
                        target.agent_id
                      );
                      return (
                        <label
                          key={target.agent_id}
                          className={`flex items-center gap-2 text-xs cursor-pointer p-1 rounded ${
                            isChecked ? "bg-slate-100" : "hover:bg-slate-50"
                          }`}
                        >
                          <input
                            type="checkbox"
                            checked={isChecked}
                            onChange={(e) => {
                              if (e.target.checked) {
                                onFormDelegateAgentIdsChange([
                                  ...formDelegateAgentIds,
                                  target.agent_id,
                                ]);
                              } else {
                                onFormDelegateAgentIdsChange(
                                  formDelegateAgentIds.filter(
                                    (id) => id !== target.agent_id
                                  )
                                );
                              }
                            }}
                            className="cursor-pointer"
                          />
                          <span className="font-semibold text-slate-800">
                            {target.name}
                          </span>
                        </label>
                      );
                    })}
                  </div>
                );
              })()}
            </div>
          )}



          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onCloseForm}
              className="rounded cursor-pointer border border-slate-300 bg-white px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50"
            >
              キャンセル
            </button>
            <button
              type="submit"
              className="rounded cursor-pointer bg-slate-900 px-4 py-1.5 text-xs text-white hover:bg-slate-800 font-medium"
            >
              保存する
            </button>
          </div>
        </form>
        {isEditingAgent && selectedAgentId && (
          <div className="mt-4 rounded-md border border-slate-200 bg-white p-3 space-y-3">
            <div className="flex items-center justify-between">
              <label className="block font-medium text-slate-700">
                プロンプトテンプレート
              </label>
              <span className="text-[10px] text-slate-500">
                {templateLoading ? "読込中…" : `${promptTemplates.length}件`}
              </span>
            </div>
            <p className="text-[10px] text-slate-500">
              エージェントごとに登録した定型プロンプト。チャット入力欄で呼び出して置き換えます。
            </p>
            {templateError && (
              <div className="rounded bg-red-50 p-2 text-[11px] text-red-600">{templateError}</div>
            )}
            {promptTemplates.length > 0 && (
              <div className="space-y-1 max-h-48 overflow-y-auto border border-slate-100 rounded p-2">
                {promptTemplates.map((t) => (
                  <div
                    key={t.template_id}
                    className={`flex items-start justify-between gap-2 rounded p-2 text-xs ${editingTemplateId === t.template_id ? "bg-indigo-50 border border-indigo-200" : "bg-slate-50 border border-slate-200"}`}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="font-semibold truncate text-slate-800">{t.name}</div>
                      <div className="text-[11px] text-slate-600 whitespace-pre-wrap break-words line-clamp-2">{t.content}</div>
                    </div>
                    <div className="flex shrink-0 gap-1">
                      <button
                        type="button"
                        onClick={() => onEditTemplate(t)}
                        className="rounded cursor-pointer bg-white border border-slate-300 px-2 py-1 text-[10px] hover:bg-slate-50"
                      >
                        編集
                      </button>
                      <button
                        type="button"
                        onClick={() => onDeleteTemplate(t.template_id)}
                        className="rounded cursor-pointer bg-white border border-red-200 px-2 py-1 text-[10px] text-red-600 hover:bg-red-50"
                      >
                        削除
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
            <form onSubmit={onCreateOrUpdateTemplate} className="space-y-2 border-t border-slate-100 pt-3">
              <div className="text-[11px] font-medium text-slate-700">
                {editingTemplateId ? "テンプレートを編集" : "テンプレートを追加"}
              </div>
              <input
                type="text"
                value={templateFormName}
                onChange={(e) => onTemplateFormNameChange(e.target.value)}
                placeholder="テンプレート名"
                className="w-full rounded-md border border-slate-300 p-2 text-xs focus:border-slate-500 focus:outline-none"
                required
              />
              <textarea
                rows={3}
                value={templateFormContent}
                onChange={(e) => onTemplateFormContentChange(e.target.value)}
                placeholder="テンプレート本文"
                className="w-full rounded-md border border-slate-300 p-2 text-xs focus:border-slate-500 focus:outline-none"
                required
              />
              <div className="flex gap-2">
                <button
                  type="submit"
                  className="rounded cursor-pointer bg-slate-900 px-3 py-1.5 text-xs text-white hover:bg-slate-800"
                >
                  {editingTemplateId ? "更新" : "追加"}
                </button>
                {editingTemplateId && (
                  <button
                    type="button"
                    onClick={onCancelEditTemplate}
                    className="rounded cursor-pointer border border-slate-300 bg-white px-3 py-1.5 text-xs hover:bg-slate-50"
                  >
                    キャンセル
                  </button>
                )}
              </div>
            </form>
          </div>
        )}
      </div>
    </div>
  );
}
