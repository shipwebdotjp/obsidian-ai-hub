import type { Project, ProjectDomain, ProjectStatus, ResolveMode } from "./types";

export interface ProjectFormModalProps {
  showCreateModal: boolean;
  showEditModal: boolean;
  showResolveModal: boolean;
  selectedCandidateDisplayName?: string;
  resolveMode: ResolveMode;
  onResolveModeChange: (mode: ResolveMode) => void;
  targetProjectId: number | "";
  onTargetProjectIdChange: (value: number | "") => void;
  formDisplayName: string;
  onFormDisplayNameChange: (value: string) => void;
  formDomain: ProjectDomain;
  onFormDomainChange: (value: ProjectDomain) => void;
  formStatus: ProjectStatus;
  onFormStatusChange: (value: ProjectStatus) => void;
  formGoal: string;
  onFormGoalChange: (value: string) => void;
  formDescription: string;
  onFormDescriptionChange: (value: string) => void;
  formKeywordsText: string;
  onFormKeywordsTextChange: (value: string) => void;
  formStartDate: string;
  onFormStartDateChange: (value: string) => void;
  formTargetDate: string;
  onFormTargetDateChange: (value: string) => void;
  formCompletedDate: string;
  onFormCompletedDateChange: (value: string) => void;
  formProjectPath: string;
  onFormProjectPathChange: (value: string) => void;
  formReferenceUrl: string;
  onFormReferenceUrlChange: (value: string) => void;
  projects: Project[];
  loading: boolean;
  onCancel: () => void;
  onSubmit: () => void;
}

export default function ProjectFormModal({
  showCreateModal,
  showEditModal,
  showResolveModal,
  selectedCandidateDisplayName,
  resolveMode,
  onResolveModeChange,
  targetProjectId,
  onTargetProjectIdChange,
  formDisplayName,
  onFormDisplayNameChange,
  formDomain,
  onFormDomainChange,
  formStatus,
  onFormStatusChange,
  formGoal,
  onFormGoalChange,
  formDescription,
  onFormDescriptionChange,
  formKeywordsText,
  onFormKeywordsTextChange,
  formStartDate,
  onFormStartDateChange,
  formTargetDate,
  onFormTargetDateChange,
  formCompletedDate,
  onFormCompletedDateChange,
  formProjectPath,
  onFormProjectPathChange,
  formReferenceUrl,
  onFormReferenceUrlChange,
  projects,
  loading,
  onCancel,
  onSubmit,
}: ProjectFormModalProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-sm p-4">
      <div className="bg-white rounded-xl shadow-xl border border-slate-200 w-full max-w-lg overflow-hidden flex flex-col max-h-[90vh]">
        <div className="p-4 border-b border-slate-100 bg-slate-50 flex items-center justify-between shrink-0">
          <h3 className="text-sm font-bold text-slate-900">
            {showCreateModal && "プロジェクト新規作成"}
            {showEditModal && "プロジェクト詳細編集"}
            {showResolveModal && `候補の処理解決: ${selectedCandidateDisplayName}`}
          </h3>
          <button
            onClick={onCancel}
            className="text-slate-400 hover:text-slate-600 transition-colors text-xs"
          >
            ✕
          </button>
        </div>

        <div className="p-5 space-y-4 text-xs text-slate-700 overflow-y-auto">
          {showResolveModal && (
            <div className="border-b pb-3 mb-3">
              <label className="block text-[11px] font-bold text-slate-700 mb-1">解決アクション</label>
              <div className="flex gap-4">
                <label className="flex items-center gap-1.5 cursor-pointer">
                  <input
                    type="radio"
                    name="resolveMode"
                    checked={resolveMode === "approve_new"}
                    onChange={() => onResolveModeChange("approve_new")}
                  />
                  <span>新規正式プロジェクトとして承認</span>
                </label>
                <label className="flex items-center gap-1.5 cursor-pointer">
                  <input
                    type="radio"
                    name="resolveMode"
                    checked={resolveMode === "link_existing"}
                    onChange={() => onResolveModeChange("link_existing")}
                  />
                  <span>既存プロジェクトへ紐付け</span>
                </label>
              </div>
            </div>
          )}

          {/* Resolution link_existing selector */}
          {showResolveModal && resolveMode === "link_existing" ? (
            <div>
              <label className="block text-[11px] font-bold text-slate-700 mb-1">紐付け先プロジェクト</label>
              <select
                value={targetProjectId}
                onChange={(e) => onTargetProjectIdChange(e.target.value ? Number(e.target.value) : "")}
                className="w-full rounded border border-slate-300 bg-white px-2.5 py-1.5 text-xs focus:border-slate-900 focus:outline-none"
              >
                <option value="">-- プロジェクトを選択してください --</option>
                {projects.map((p) => (
                  <option key={p.project_id} value={p.project_id}>
                    {p.display_name} ({p.status})
                  </option>
                ))}
              </select>
            </div>
          ) : (
            /* Attribute input fields (for Create, Edit, or approve_new resolution) */
            <div className="space-y-3">
              <div>
                <label className="block text-[11px] font-bold text-slate-700 mb-1">プロジェクト名称 *</label>
                <input
                  type="text"
                  value={formDisplayName}
                  onChange={(e) => onFormDisplayNameChange(e.target.value)}
                  className="w-full rounded border border-slate-300 bg-white px-2.5 py-1.5 text-xs focus:border-slate-900 focus:outline-none"
                  placeholder="表示名を入力"
                />
              </div>

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <label className="block text-[11px] font-bold text-slate-700 mb-1">領域 (Domain)</label>
                  <select
                    value={formDomain}
                    onChange={(e) => onFormDomainChange(e.target.value as "work" | "personal")}
                    className="w-full rounded border border-slate-300 bg-white px-2.5 py-1.5 text-xs focus:outline-none"
                  >
                    <option value="personal">個人 (personal)</option>
                    <option value="work">仕事 (work)</option>
                  </select>
                </div>
                <div>
                  <label className="block text-[11px] font-bold text-slate-700 mb-1">状態 (Status)</label>
                  <select
                    value={formStatus}
                    onChange={(e) => onFormStatusChange(e.target.value as any)}
                    className="w-full rounded border border-slate-300 bg-white px-2.5 py-1.5 text-xs focus:outline-none"
                  >
                    <option value="inquiry">検討中 (inquiry)</option>
                    <option value="active">進行中 (active)</option>
                    <option value="paused">保留中 (paused)</option>
                    <option value="completed">完了 (completed)</option>
                    <option value="cancelled">中止 (cancelled)</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-[11px] font-bold text-slate-700 mb-1">目的 (Goal)</label>
                <textarea
                  value={formGoal}
                  onChange={(e) => onFormGoalChange(e.target.value)}
                  rows={2}
                  className="w-full rounded border border-slate-300 bg-white px-2.5 py-1.5 text-xs focus:border-slate-900 focus:outline-none"
                  placeholder="目的を入力"
                />
              </div>

              <div>
                <label className="block text-[11px] font-bold text-slate-700 mb-1">説明 (Description)</label>
                <textarea
                  value={formDescription}
                  onChange={(e) => onFormDescriptionChange(e.target.value)}
                  rows={2}
                  className="w-full rounded border border-slate-300 bg-white px-2.5 py-1.5 text-xs focus:border-slate-900 focus:outline-none"
                  placeholder="説明を入力"
                />
              </div>

              <div>
                <label className="block text-[11px] font-bold text-slate-700 mb-1">キーワード (1行に1キーワード)</label>
                <textarea
                  value={formKeywordsText}
                  onChange={(e) => onFormKeywordsTextChange(e.target.value)}
                  rows={2}
                  className="w-full rounded border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-mono focus:border-slate-900 focus:outline-none"
                  placeholder="キーワードを入力"
                />
              </div>

              <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                <div>
                  <label className="block text-[11px] font-bold text-slate-700 mb-1">開始日</label>
                  <input
                    type="text"
                    value={formStartDate}
                    onChange={(e) => onFormStartDateChange(e.target.value)}
                    className="w-full rounded border border-slate-300 bg-white px-2 py-1 text-xs font-mono focus:outline-none"
                    placeholder="YYYY-MM-DD"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-bold text-slate-700 mb-1">目標日</label>
                  <input
                    type="text"
                    value={formTargetDate}
                    onChange={(e) => onFormTargetDateChange(e.target.value)}
                    className="w-full rounded border border-slate-300 bg-white px-2 py-1 text-xs font-mono focus:outline-none"
                    placeholder="YYYY-MM-DD"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-bold text-slate-700 mb-1">完了日</label>
                  <input
                    type="text"
                    value={formCompletedDate}
                    onChange={(e) => onFormCompletedDateChange(e.target.value)}
                    className="w-full rounded border border-slate-300 bg-white px-2 py-1 text-xs font-mono focus:outline-none"
                    placeholder="YYYY-MM-DD"
                  />
                </div>
              </div>

              <div>
                <label className="block text-[11px] font-bold text-slate-700 mb-1">ディレクトリパス</label>
                <input
                  type="text"
                  value={formProjectPath}
                  onChange={(e) => onFormProjectPathChange(e.target.value)}
                  className="w-full rounded border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-mono focus:border-slate-900 focus:outline-none"
                  placeholder="/Users/name/projects/my-project"
                />
              </div>

              <div>
                <label className="block text-[11px] font-bold text-slate-700 mb-1">参照URL</label>
                <input
                  type="text"
                  value={formReferenceUrl}
                  onChange={(e) => onFormReferenceUrlChange(e.target.value)}
                  className="w-full rounded border border-slate-300 bg-white px-2.5 py-1.5 text-xs focus:border-slate-900 focus:outline-none"
                  placeholder="https://github.com/..."
                />
              </div>
            </div>
          )}
        </div>

        <div className="p-4 border-t border-slate-100 bg-slate-50 flex items-center justify-end gap-2 shrink-0">
          <button
            onClick={onCancel}
            className="rounded border border-slate-300 bg-white px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
          >
            キャンセル
          </button>
          <button
            onClick={onSubmit}
            disabled={
              loading ||
              (showCreateModal && !formDisplayName.trim()) ||
              (showEditModal && !formDisplayName.trim()) ||
              (showResolveModal && resolveMode === "approve_new" && !formDisplayName.trim()) ||
              (showResolveModal && resolveMode === "link_existing" && !targetProjectId)
            }
             className="rounded bg-blue-600 px-4 py-2 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {loading ? "処理中..." : "保存する"}
          </button>
        </div>
      </div>
    </div>
  );
}
