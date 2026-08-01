import type { ProjectCandidateDetail } from "./types";

export interface CandidateDetailProps {
  candidate: ProjectCandidateDetail | null;
  mobileDetailOpen: boolean;
  onBack: () => void;
  onResolve: () => void;
  onReject: (c: ProjectCandidateDetail) => void;
}

export default function CandidateDetail({ candidate, mobileDetailOpen, onBack, onResolve, onReject }: CandidateDetailProps) {
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
            候補詳細
          </span>
        </div>
      )}
      {candidate ? (
        <div className="space-y-4">
          <div className="flex items-start justify-between border-b pb-3">
            <div>
              <h2 className="text-base font-bold">{candidate.display_name}</h2>
              <p className="text-xs text-slate-400">正規化名: {candidate.normalized_name} | 領域: {candidate.domain === "work" ? "仕事" : "個人"}</p>
            </div>
            <div className="flex gap-2">
              <button
                onClick={onResolve}
                 className="rounded bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700"
               >
                 処理・解決
              </button>
              <button
                onClick={() => onReject(candidate)}
                className="rounded border border-red-200 bg-red-50 px-3 py-1.5 text-xs text-red-700 hover:bg-red-100"
              >
                却下
              </button>
            </div>
          </div>

          <div className="space-y-3 text-xs">
            {candidate.goal && (
              <div>
                <span className="font-bold block text-slate-600">目的:</span>
                <div className="bg-slate-50 p-2 rounded mt-1 whitespace-pre-wrap">{candidate.goal}</div>
              </div>
            )}
            {candidate.description && (
              <div>
                <span className="font-bold block text-slate-600">説明:</span>
                <div className="bg-slate-50 p-2 rounded mt-1 whitespace-pre-wrap">{candidate.description}</div>
              </div>
            )}
            {candidate.keywords && candidate.keywords.length > 0 && (
              <div>
                <span className="font-bold block text-slate-600">キーワード:</span>
                <div className="flex flex-wrap gap-1 mt-1">
                  {candidate.keywords.map((k, idx) => (
                    <span key={idx} className="bg-slate-100 text-slate-800 text-[10px] px-2 py-0.5 rounded border">
                      {k}
                    </span>
                  ))}
                </div>
              </div>
            )}
              {(candidate.start_date || candidate.target_date) && (
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {candidate.start_date && (
                  <div>
                    <span className="font-bold text-slate-600">開始日:</span>
                    <span className="ml-1 font-mono">{candidate.start_date}</span>
                  </div>
                )}
                {candidate.target_date && (
                  <div>
                    <span className="font-bold text-slate-600">目標日:</span>
                    <span className="ml-1 font-mono">{candidate.target_date}</span>
                  </div>
                )}
              </div>
            )}
            {candidate.evidence && (
              <div className="border-t pt-3">
                <span className="font-bold block text-slate-600 text-xs">検出根拠・ログ証拠:</span>
                <p className="mt-1 bg-amber-50/50 border border-amber-100 p-2.5 rounded text-slate-600 italic">
                  &ldquo;{candidate.evidence}&rdquo;
                </p>
              </div>
            )}
          </div>

          <div className="border-t pt-3">
            <h3 className="text-xs font-bold text-slate-700 mb-2">紐づくサマリ ({candidate.summaries.length})</h3>
            {candidate.summaries.length === 0 ? (
              <p className="text-xs text-slate-400">紐づいているサマリはありません。</p>
            ) : (
              <div className="border border-slate-100 rounded-lg overflow-hidden divide-y divide-slate-100 text-xs">
                {candidate.summaries.map((sum) => (
                  <div key={sum.summary_id} className="p-2.5 flex justify-between bg-slate-50/50">
                    <span className="font-semibold text-slate-800">{sum.period_key}</span>
                    <span className="text-slate-400 font-mono text-[10px]">{sum.period_type}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      ) : (
        <div className="h-full flex items-center justify-center text-xs text-slate-400">
          候補を選択すると詳細が表示されます。
        </div>
      )}
    </>
  );
}
