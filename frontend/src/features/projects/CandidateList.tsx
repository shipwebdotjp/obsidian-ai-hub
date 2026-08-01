import type { ProjectCandidate } from "../../api/types";

export interface CandidateListProps {
  candidates: ProjectCandidate[];
  selectedCandidateId: number | null;
  onSelect: (c: ProjectCandidate) => void;
}

export default function CandidateList({ candidates, selectedCandidateId, onSelect }: CandidateListProps) {
  return (
    <>
      <h2 className="mb-3 text-sm font-semibold">新規候補</h2>
      {candidates.length === 0 ? (
        <p className="text-xs text-slate-400">現在、未解決の候補はありません。</p>
      ) : (
        <div className="space-y-2">
          {candidates.map((c) => (
            <button
              key={c.candidate_id}
              onClick={() => onSelect(c)}
              className={`w-full text-left p-2.5 rounded-lg border text-xs transition-all ${
                selectedCandidateId === c.candidate_id
                  ? "border-slate-900 bg-slate-50 font-medium"
                  : "border-slate-200 hover:bg-slate-50"
              }`}
            >
              <div className="font-semibold">{c.display_name}</div>
              <div className="text-[10px] text-slate-400 mt-1 flex justify-between">
                <span>領域: {c.domain === "work" ? "仕事" : "個人"}</span>
                <span>検出: {new Date(c.created_at).toLocaleDateString()}</span>
              </div>
            </button>
          ))}
        </div>
      )}
    </>
  );
}
