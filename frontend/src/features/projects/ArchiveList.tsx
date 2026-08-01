import type { ProjectCandidate } from "../../api/types";

export interface ArchiveListProps {
  archivedCandidates: ProjectCandidate[];
  onReopen: (c: ProjectCandidate) => void;
}

export default function ArchiveList({ archivedCandidates, onReopen }: ArchiveListProps) {
  return (
    <div className="flex-1 border border-slate-200 bg-white rounded-lg p-5 overflow-y-auto space-y-4">
      <div>
        <h2 className="text-sm font-bold text-slate-900">処理・却下済み候補アーカイブ</h2>
        <p className="text-xs text-slate-500 mt-0.5">処理が完了した（resolved）、または却下された（rejected）プロジェクト候補の履歴です。</p>
      </div>

      {archivedCandidates.length === 0 ? (
        <p className="text-xs text-slate-400">該当する候補はありません。</p>
      ) : (
        <div className="border border-slate-200 rounded-lg overflow-hidden divide-y divide-slate-200 text-xs">
          {archivedCandidates.map((c) => (
            <div key={c.candidate_id} className="p-3 bg-slate-50/50 flex items-center justify-between gap-4">
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-slate-800">{c.display_name}</span>
                  <span className={`text-[9px] px-1.5 py-0.5 rounded-full font-mono ${
                    c.status === "resolved" ? "bg-green-100 text-green-800" : "bg-red-100 text-red-800"
                  }`}>{c.status}</span>
                </div>
                <div className="text-[10px] text-slate-400 mt-1 font-mono">
                  正規名: {c.normalized_name} | 作成: {new Date(c.created_at).toLocaleString()}
                </div>
                {c.evidence && <div className="text-[10px] text-slate-500 mt-1 italic">根拠: &ldquo;{c.evidence}&rdquo;</div>}
              </div>
              {c.status === "rejected" && (
                <button
                  onClick={() => onReopen(c)}
                  className="rounded border border-slate-300 bg-white px-2.5 py-1 text-xs text-slate-700 hover:bg-slate-50"
                >
                  再開
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
