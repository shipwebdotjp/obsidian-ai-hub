import type { MutableRefObject } from "react";
import type {
  CodingDefaults,
  CodingProjectItem,
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
  isNewSessionModalOpen: boolean;
  onCloseNewSession: () => void;
  newSessionTitle: string;
  setNewSessionTitle: React.Dispatch<React.SetStateAction<string>>;
  newSessionBackend: "codex" | "opencode";
  setNewSessionBackend: React.Dispatch<React.SetStateAction<"codex" | "opencode">>;
  backendManuallySelected: MutableRefObject<boolean>;
  creatingSession: boolean;
  selectedProjectItem: CodingProjectItem | undefined;
  onCreateSession: () => void;
}

/** 会話設定・ユーザー既定・新規セッションの3モーダル。 */
export function CodingModals({
  isSessionSettingsOpen,
  onCloseSessionSettings,
  sessionDetail,
  sessionSelectedTools,
  setSessionSelectedTools,
  sessionTitleDraft,
  setSessionTitleDraft,
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
  isNewSessionModalOpen,
  onCloseNewSession,
  newSessionTitle,
  setNewSessionTitle,
  newSessionBackend,
  setNewSessionBackend,
  backendManuallySelected,
  creatingSession,
  selectedProjectItem,
  onCreateSession,
}: CodingModalsProps) {
  return (
    <>
      {/* Conversation Settings Modal */}
      {isSessionSettingsOpen && sessionDetail && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
          <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-xl max-h-[90vh] flex flex-col">
            <h3 className="text-base font-semibold text-slate-900">会話の利用可能ツール設定</h3>
            <p className="mt-1 text-xs text-slate-500">
              オーケストレーターがこの会話で呼び出せるツールを選択してください。
              未選択のツールは呼び出せなくなります。
            </p>

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

      {/* New Session Modal */}
      {isNewSessionModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
          <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl">
            <h3 className="text-base font-semibold text-slate-900">新規コーディングセッション作成</h3>
            <p className="mt-1 text-xs text-slate-500">
              プロジェクト: {selectedProjectItem?.project.display_name}
            </p>

            <div className="mt-4 space-y-4">
              <div>
                <label className="block text-xs font-medium text-slate-700">
                  セッションタイトル
                </label>
                <input
                  type="text"
                  value={newSessionTitle}
                  onChange={(e) => setNewSessionTitle(e.target.value)}
                  placeholder="自動生成 (空欄可) / 例: リファクタリング作業"
                  className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-xs focus:border-slate-800 focus:outline-none"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-700">
                  CLI バックエンド選択
                </label>
                <div className="mt-2 grid grid-cols-2 gap-3">
                  <button
                    type="button"
                    onClick={() => {
                      backendManuallySelected.current = true;
                      setNewSessionBackend("codex");
                    }}
                    className={`rounded-lg border p-3 text-left text-xs transition-colors ${
                      newSessionBackend === "codex"
                        ? "border-slate-900 bg-slate-900 text-white"
                        : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
                    }`}
                  >
                    <div className="font-semibold">Codex CLI</div>
                    <div className="mt-0.5 text-[10px] opacity-80">OpenAI Codex アダプタ</div>
                  </button>

                  <button
                    type="button"
                    onClick={() => {
                      backendManuallySelected.current = true;
                      setNewSessionBackend("opencode");
                    }}
                    className={`rounded-lg border p-3 text-left text-xs transition-colors ${
                      newSessionBackend === "opencode"
                        ? "border-slate-900 bg-slate-900 text-white"
                        : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
                    }`}
                  >
                    <div className="font-semibold">OpenCode CLI</div>
                    <div className="mt-0.5 text-[10px] opacity-80">OpenCode CLI アダプタ</div>
                  </button>
                </div>
              </div>
            </div>

            <div className="mt-6 flex justify-end gap-2">
              <button
                type="button"
                onClick={onCloseNewSession}
                className="rounded px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-100 cursor-pointer"
              >
                キャンセル
              </button>
              <button
                type="button"
                disabled={creatingSession}
                onClick={onCreateSession}
                className="rounded bg-blue-600 px-4 py-1.5 text-xs font-medium text-white hover:bg-blue-700 cursor-pointer disabled:cursor-not-allowed disabled:opacity-50"
              >
                {creatingSession ? "作成中..." : "作成"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
