import type {
  CodingDefaults,
  CodingSessionDetail,
} from "../../../api/coding";

interface CodingModalsProps {
  isSessionSettingsOpen: boolean;
  onCloseSessionSettings: () => void;
  sessionDetail: CodingSessionDetail | null;
  sessionSelectedTools: string[];
  setSessionSelectedTools: React.Dispatch<React.SetStateAction<string[]>>;
  sessionTitleDraft: string;
  setSessionTitleDraft: React.Dispatch<React.SetStateAction<string>>;
  orchestratorProviderDraft: string;
  onOrchestratorProviderChange: (provider: string) => void;
  orchestratorModelDraft: string;
  setOrchestratorModelDraft: React.Dispatch<React.SetStateAction<string>>;
  savingSessionTools: boolean;
  onSaveSessionTools: () => void;
  onResetSessionTools: () => void;
  isUserDefaultsOpen: boolean;
  onCloseUserDefaults: () => void;
  loadingUserDefaults: boolean;
  userDefaults: CodingDefaults | null;
  userDefaultsSelectedTools: string[];
  setUserDefaultsSelectedTools: React.Dispatch<React.SetStateAction<string[]>>;
  savingUserDefaults: boolean;
  onSaveUserDefaults: () => void;
}

/** 会話設定・ユーザー既定の2モーダル。 */
export function CodingModals({
  isSessionSettingsOpen,
  onCloseSessionSettings,
  sessionDetail,
  sessionSelectedTools,
  setSessionSelectedTools,
  sessionTitleDraft,
  setSessionTitleDraft,
  orchestratorProviderDraft,
  onOrchestratorProviderChange,
  orchestratorModelDraft,
  setOrchestratorModelDraft,
  savingSessionTools,
  onSaveSessionTools,
  onResetSessionTools,
  isUserDefaultsOpen,
  onCloseUserDefaults,
  loadingUserDefaults,
  userDefaults,
  userDefaultsSelectedTools,
  setUserDefaultsSelectedTools,
  savingUserDefaults,
  onSaveUserDefaults,
}: CodingModalsProps) {
  return (
    <>
      {/* Conversation Settings Modal */}
      {isSessionSettingsOpen && sessionDetail && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
          <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-xl max-h-[90vh] flex flex-col">
            <h3 className="text-base font-semibold text-slate-900">会話設定</h3>

            <div className="mt-4">
              <label
                htmlFor="coding-session-title"
                className="block text-xs font-medium text-slate-700"
              >
                セッションタイトル
              </label>
              <input
                id="coding-session-title"
                type="text"
                value={sessionTitleDraft}
                onChange={(e) => setSessionTitleDraft(e.target.value)}
                placeholder="セッションタイトルを入力"
                disabled={savingSessionTools}
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-xs focus:border-slate-800 focus:outline-none disabled:bg-slate-100"
              />
            </div>

            <div className="mt-4 border-t border-slate-200 pt-4">
              <label
                htmlFor="coding-orchestrator-provider"
                className="block text-xs font-medium text-slate-700"
              >
                オーケストレーター（進行役）
              </label>
              <p className="mt-1 text-[11px] text-slate-500">
                この会話の進行役 LLM のプロバイダーとモデルを指定します。
                「既定を使用」の場合は config の既定値を使用します。
              </p>
              <div className="mt-2 flex gap-2">
                <select
                  id="coding-orchestrator-provider"
                  value={orchestratorProviderDraft}
                  onChange={(e) => onOrchestratorProviderChange(e.target.value)}
                  disabled={savingSessionTools}
                  className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs text-slate-700 focus:border-slate-800 focus:outline-none disabled:bg-slate-100 cursor-pointer disabled:cursor-not-allowed"
                  title="オーケストレーターのプロバイダー"
                >
                  <option value="">
                    既定を使用（{sessionDetail.default_orchestrator_provider ?? "-"}）
                  </option>
                  {(sessionDetail.available_orchestrator_providers ?? []).map((p) => (
                    <option key={p} value={p}>
                      {p}
                    </option>
                  ))}
                </select>
                <input
                  id="coding-orchestrator-model"
                  type="text"
                  aria-label="オーケストレーターのモデル"
                  value={orchestratorModelDraft}
                  onChange={(e) => setOrchestratorModelDraft(e.target.value)}
                  disabled={savingSessionTools || !orchestratorProviderDraft}
                  placeholder={
                    orchestratorProviderDraft
                      ? "モデル名"
                      : `既定: ${sessionDetail.default_orchestrator_model ?? "-"}`
                  }
                  className="flex-1 rounded-md border border-slate-300 px-3 py-1.5 text-xs focus:border-slate-800 focus:outline-none disabled:bg-slate-100"
                />
              </div>
            </div>

            <div className="mt-4 border-t border-slate-200 pt-4">
              <h4 className="text-xs font-medium text-slate-700">利用可能ツール</h4>
              <p className="mt-1 text-[11px] text-slate-500">
                オーケストレーターがこの会話で呼び出せるツールを選択してください。
                未選択のツールは呼び出せなくなります。
              </p>
            </div>

            <div className="mt-3 flex items-center justify-between border-b border-slate-200 pb-2 text-xs">
              <span className="text-slate-600 font-medium">
                選択中: {sessionSelectedTools.length} / {sessionDetail.available_tools.length} 個
              </span>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() =>
                    setSessionSelectedTools(sessionDetail.available_tools.map((t) => t.tool_id))
                  }
                  className="text-slate-600 hover:text-slate-900 text-[11px] underline"
                >
                  全選択
                </button>
                <button
                  type="button"
                  onClick={() => setSessionSelectedTools([])}
                  className="text-slate-600 hover:text-slate-900 text-[11px] underline"
                >
                  全解除
                </button>
              </div>
            </div>

            <div className="mt-3 flex-1 overflow-y-auto space-y-1.5 pr-1">
              {sessionDetail.available_tools.map((tool) => {
                const isChecked = sessionSelectedTools.includes(tool.tool_id);
                return (
                  <label
                    key={tool.tool_id}
                    className={`flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs cursor-pointer transition-colors ${
                      isChecked
                        ? "border-slate-800 bg-slate-50 text-slate-900"
                        : "border-slate-200 bg-white text-slate-500 hover:bg-slate-50"
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={isChecked}
                      onChange={(e) => {
                        if (e.target.checked) {
                          setSessionSelectedTools((prev) => [...prev, tool.tool_id]);
                        } else {
                          setSessionSelectedTools((prev) =>
                            prev.filter((tid) => tid !== tool.tool_id)
                          );
                        }
                      }}
                      className="rounded border-slate-300 text-slate-900 focus:ring-slate-800 cursor-pointer"
                    />
                    <span className="font-semibold text-slate-800">
                      {tool.name} <span className="text-[10px] text-slate-400 font-mono">({tool.tool_id})</span>
                    </span>
                  </label>
                );
              })}
            </div>

            <div className="mt-6 flex items-center justify-between border-t border-slate-200 pt-4">
              <button
                type="button"
                disabled={savingSessionTools || !sessionDetail.has_custom_tools}
                onClick={onResetSessionTools}
                className="rounded px-3 py-1.5 text-xs font-medium text-rose-700 hover:bg-rose-50 cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
                title="既定ツール設定へリセット"
              >
                既定値に戻す
              </button>

              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={onCloseSessionSettings}
                  className="rounded px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-100 cursor-pointer"
                >
                  キャンセル
                </button>
                <button
                  type="button"
                  disabled={savingSessionTools}
                  onClick={onSaveSessionTools}
                  className="rounded bg-blue-600 px-4 py-1.5 text-xs font-medium text-white hover:bg-blue-700 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {savingSessionTools ? "保存中..." : "保存"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* User Default Tools Modal */}
      {isUserDefaultsOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
          <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-xl max-h-[90vh] flex flex-col">
            <h3 className="text-base font-semibold text-slate-900">ユーザー既定の利用可能ツール設定</h3>
            <p className="mt-1 text-xs text-slate-500">
              新規会話作成時にデフォルトで許可されるツールセットを設定します。
            </p>

            {loadingUserDefaults ? (
              <div className="py-8 text-center text-xs text-slate-500">読み込み中...</div>
            ) : userDefaults ? (
              <>
                <div className="mt-3 flex items-center justify-between border-b border-slate-200 pb-2 text-xs">
                  <span className="text-slate-600 font-medium">
                    選択中: {userDefaultsSelectedTools.length} / {userDefaults.available_tools.length} 個
                  </span>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() =>
                        setUserDefaultsSelectedTools(userDefaults.available_tools.map((t) => t.tool_id))
                      }
                      className="text-slate-600 hover:text-slate-900 text-[11px] underline"
                    >
                      全選択
                    </button>
                    <button
                      type="button"
                      onClick={() => setUserDefaultsSelectedTools([])}
                      className="text-slate-600 hover:text-slate-900 text-[11px] underline"
                    >
                      全解除
                    </button>
                  </div>
                </div>

                <div className="mt-3 flex-1 overflow-y-auto space-y-1.5 pr-1">
                  {userDefaults.available_tools.map((tool) => {
                    const isChecked = userDefaultsSelectedTools.includes(tool.tool_id);
                    return (
                      <label
                        key={tool.tool_id}
                        className={`flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs cursor-pointer transition-colors ${
                          isChecked
                            ? "border-slate-800 bg-slate-50 text-slate-900"
                            : "border-slate-200 bg-white text-slate-500 hover:bg-slate-50"
                        }`}
                      >
                        <input
                          type="checkbox"
                          checked={isChecked}
                          onChange={(e) => {
                            if (e.target.checked) {
                              setUserDefaultsSelectedTools((prev) => [...prev, tool.tool_id]);
                            } else {
                              setUserDefaultsSelectedTools((prev) =>
                                prev.filter((tid) => tid !== tool.tool_id)
                              );
                            }
                          }}
                          className="rounded border-slate-300 text-slate-900 focus:ring-slate-800 cursor-pointer"
                        />
                        <span className="font-semibold text-slate-800">
                          {tool.name} <span className="text-[10px] text-slate-400 font-mono">({tool.tool_id})</span>
                        </span>
                      </label>
                    );
                  })}
                </div>

                <div className="mt-6 flex justify-end gap-2 border-t border-slate-200 pt-4">
                  <button
                    type="button"
                    onClick={onCloseUserDefaults}
                    className="rounded px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-100 cursor-pointer"
                  >
                    キャンセル
                  </button>
                  <button
                    type="button"
                    disabled={savingUserDefaults}
                    onClick={onSaveUserDefaults}
                    className="rounded bg-blue-600 px-4 py-1.5 text-xs font-medium text-white hover:bg-blue-700 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {savingUserDefaults ? "保存中..." : "既定値として保存"}
                  </button>
                </div>
              </>
            ) : null}
          </div>
        </div>
      )}

    </>
  );
}
