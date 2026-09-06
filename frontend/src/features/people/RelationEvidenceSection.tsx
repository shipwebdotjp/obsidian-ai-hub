import React from "react";
import { PersonRelationEvidence } from "./types";

interface RelationEvidenceSectionProps {
  evidence: PersonRelationEvidence[];
}

export default function RelationEvidenceSection({ evidence }: RelationEvidenceSectionProps) {
  if (evidence.length === 0) {
    return (
      <div className="p-2.5 bg-slate-50 border border-slate-200 rounded-lg text-slate-400 italic text-[11px]">
        この関係に登録されている根拠 (Evidence) はありません。
      </div>
    );
  }

  return (
    <div className="p-3 bg-slate-50 border border-slate-200 rounded-lg space-y-2">
      <div className="text-[11px] font-bold text-slate-700">登録根拠 (Evidence)</div>
      <div className="space-y-1.5">
        {evidence.map((ev) => (
          <div
            key={ev.evidence_id}
            className="p-2 bg-white border border-slate-200 rounded text-xs text-slate-700 space-y-0.5"
          >
            {ev.quote && <div className="italic font-medium text-slate-900">“{ev.quote}”</div>}
            <div className="flex flex-wrap gap-2 text-[11px] text-slate-500">
              {ev.source_ref && <span>参照: {ev.source_ref}</span>}
              {ev.observed_at && <span>観測日: {ev.observed_at}</span>}
            </div>
            {ev.note && <div className="text-[11px] text-slate-600">メモ: {ev.note}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}
