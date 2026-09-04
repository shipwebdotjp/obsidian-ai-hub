import React from 'react';
import type { AskUserAnswerRound } from '../api/types';

export interface AnsweredRequirementCardProps {
  round: AskUserAnswerRound;
}

export const AnsweredRequirementCard: React.FC<AnsweredRequirementCardProps> = ({ round }) => {
  return (
    <div
      data-testid="answered-requirement-card"
      className="my-3 p-4 border border-emerald-300 bg-emerald-50/50 rounded-lg shadow-sm"
    >
      <div className="flex items-center justify-between mb-3 border-b border-emerald-200 pb-2">
        <span className="font-semibold text-emerald-900 text-sm flex items-center gap-2">
          <span>✅ 回答済み要件確認</span>
        </span>
        <span className="text-xs text-emerald-700 font-mono">ID: {round.hitl_run_id}</span>
      </div>

      <div className="space-y-3">
        {round.items.map((item, idx) => (
          <div key={item.question_id || idx} className="bg-white p-3 rounded border border-emerald-200">
            <p className="text-sm font-medium text-slate-800 mb-1.5">
              {round.items.length > 1 ? `${idx + 1}. ` : ''}{item.question}
            </p>
            <div className="text-sm text-slate-700 flex items-start gap-1.5 pl-1">
              <span className="font-semibold text-emerald-700 shrink-0">選択:</span>
              <span className="font-medium text-slate-900">{item.selected_label}</span>
            </div>
            {item.selected_value === 'other' && item.text && (
              <div className="mt-2 pl-3 border-l-2 border-emerald-400 bg-emerald-50/30 py-1 pr-2 rounded-r">
                <p className="text-xs text-emerald-800 font-semibold mb-0.5">自由入力本文:</p>
                <p className="text-sm text-slate-800 whitespace-pre-wrap">{item.text}</p>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
};
