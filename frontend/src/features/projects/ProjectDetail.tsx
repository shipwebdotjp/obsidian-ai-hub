import type { ProjectDetail as ProjectDetailModel } from "./types";

export interface ProjectDetailProps {
  project: ProjectDetailModel | null;
  mobileDetailOpen: boolean;
  onBack: () => void;
  onEdit: () => void;
}

export default function ProjectDetail({ project, mobileDetailOpen, onBack, onEdit }: ProjectDetailProps) {
  return (
    <>
      {mobileDetailOpen && (
        <div className="flex items-center gap-2 border-b border-slate-200 pb-2 lg:hidden">
          <button
            type="button"
            onClick={onBack}
            aria-label="一覧に戻る"
            className="rounded px-2 py-1 text-sm text-slate-600 hover:bg-slate-100"
          >
            ← 一覧
          </button>
          <span className="truncate text-sm font-semibold text-slate-700">
            プロジェクト詳細
          </span>
        </div>
      )}
      {project ? (
        <div className="space-y-4">
          <div className="flex items-start justify-between border-b pb-3">
            <div>
              <h2 className="text-base font-bold">{project.display_name}</h2>
              <p className="text-xs text-slate-400">ID: {project.project_id} | 正規化名: {project.normalized_name} | 状態: <span className="font-semibold text-slate-700">{project.status}</span></p>
            </div>
            <button
              onClick={onEdit}
               className="rounded bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700"
             >
               詳細編集
            </button>
          </div>

          <div className="space-y-3 text-xs">
            {project.goal && (
              <div>
                <span className="font-bold block text-slate-600">目的:</span>
                <div className="bg-slate-50 p-2 rounded mt-1 whitespace-pre-wrap">{project.goal}</div>
              </div>
            )}
            {project.description && (
              <div>
                <span className="font-bold block text-slate-600">説明:</span>
                <div className="bg-slate-50 p-2 rounded mt-1 whitespace-pre-wrap">{project.description}</div>
              </div>
            )}
            {project.keywords && project.keywords.length > 0 && (
              <div>
                <span className="font-bold block text-slate-600">キーワード:</span>
                <div className="flex flex-wrap gap-1 mt-1">
                  {project.keywords.map((k, idx) => (
                    <span key={idx} className="bg-slate-100 text-slate-800 text-[10px] px-2 py-0.5 rounded border">
                      {k}
                    </span>
                  ))}
                </div>
              </div>
            )}
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
              <div>
                <span className="font-bold text-slate-600 block">開始日:</span>
                <span className="font-mono">{project.start_date || "-"}</span>
              </div>
              <div>
                <span className="font-bold text-slate-600 block">目標日:</span>
                <span className="font-mono">{project.target_date || "-"}</span>
              </div>
              <div>
                <span className="font-bold text-slate-600 block">完了日:</span>
                <span className="font-mono">{project.completed_date || "-"}</span>
              </div>
            </div>
            {project.project_path && (
              <div>
                <span className="font-bold text-slate-600 block">ディレクトリパス:</span>
                <code className="bg-slate-100 px-1.5 py-0.5 rounded font-mono text-[10px]">{project.project_path}</code>
              </div>
            )}
            {project.reference_url && (
              <div>
                <span className="font-bold text-slate-600 block">参照URL:</span>
                <a href={project.reference_url} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">
                  {project.reference_url}
                </a>
              </div>
            )}
          </div>

          <div className="border-t pt-3">
            <h3 className="text-xs font-bold text-slate-700 mb-2">紐づくサマリ ({project.summaries.length})</h3>
            {project.summaries.length === 0 ? (
              <p className="text-xs text-slate-400">紐づいているサマリはありません。</p>
            ) : (
              <div className="border border-slate-100 rounded-lg overflow-hidden divide-y divide-slate-100 text-xs">
                {project.summaries.map((sum) => (
                  <div key={sum.summary_id} className="p-2.5 flex flex-col bg-slate-50/50">
                    <div className="flex justify-between">
                      <span className="font-semibold text-slate-800">{sum.period_key}</span>
                      <span className="text-slate-400 font-mono text-[10px]">{sum.period_type}</span>
                    </div>
                    {sum.note && <span className="text-[10px] text-slate-500 mt-0.5">{sum.note}</span>}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      ) : (
        <div className="h-full flex items-center justify-center text-xs text-slate-400">
          プロジェクトを選択すると詳細が表示されます。
        </div>
      )}
    </>
  );
}
