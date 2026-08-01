import React from "react";
import { Person } from "../../api/types";
import { PersonCandidate, PersonCandidateDetail, PeopleError } from "./types";

interface CandidateTabProps {
  candidates: PersonCandidate[];
  selectedCandidate: PersonCandidateDetail | null;
  people: Person[];
  targetPersonId: string;
  resolveError: PeopleError | null;
  promoteDisplayName: string;
  promoteError: PeopleError | null;
  summaryAssignments: Record<string, string>;
  loading: boolean;
  mobileDetailOpen: boolean;
  setMobileDetailOpen: (open: boolean) => void;
  onSelectCandidate: (cand: PersonCandidate) => void;
  onChangeTargetPersonId: (id: string) => void;
  onResolveCandidate: () => void;
  onChangePromoteDisplayName: (name: string) => void;
  onPromoteCandidate: () => void;
  onChangeSummaryAssignment: (summaryId: string, personId: string) => void;
  onAssignCandidateSummary: (summaryId: string, assignedPersonId: string) => void;
}

export default function CandidateTab({
  candidates,
  selectedCandidate,
  people,
  targetPersonId,
  resolveError,
  promoteDisplayName,
  promoteError,
  summaryAssignments,
  loading,
  mobileDetailOpen,
  setMobileDetailOpen,
  onSelectCandidate,
  onChangeTargetPersonId,
  onResolveCandidate,
  onChangePromoteDisplayName,
  onPromoteCandidate,
  onChangeSummaryAssignment,
  onAssignCandidateSummary,
}: CandidateTabProps) {
  return (
    <>
      <div
        className={`flex w-full flex-col overflow-y-auto rounded-lg border border-slate-200 bg-white p-4 lg:w-1/3 ${
          mobileDetailOpen ? "hidden" : "flex"
        } lg:flex`}
      >
        <h2 className="mb-3 text-sm font-semibold">未解決候補一覧</h2>
        {candidates.length === 0 ? (
          <p className="text-xs text-slate-400">現在、未解決候補はありません。</p>
        ) : (
          <div className="space-y-2">
            {candidates.map((cand) => {
              const isSelected = selectedCandidate?.candidate_id === cand.candidate_id;
              return (
                <button
                  key={cand.candidate_id}
                  onClick={() => onSelectCandidate(cand)}
                  data-selected={isSelected || undefined}
                  className={`w-full text-left p-2.5 rounded-lg border text-xs transition-all cursor-pointer ${
                    isSelected
                      ? "border-slate-800 bg-slate-200 border-l-4 font-medium"
                      : "border-slate-200 hover:bg-slate-50"
                  }`}
                >
                  <div>{cand.display_name}</div>
                  <div className="text-[10px] text-slate-400 mt-0.5">({cand.normalized_name})</div>
                </button>
              );
            })}
          </div>
        )}
      </div>

      <div
        className={`w-full overflow-y-auto rounded-lg border border-slate-200 bg-white p-4 lg:flex-1 ${
          mobileDetailOpen ? "flex flex-col" : "hidden"
        } lg:flex`}
      >
        {mobileDetailOpen && (
          <div className="flex items-center gap-2 border-b border-slate-200 pb-2 lg:hidden">
            <button
              type="button"
              onClick={() => setMobileDetailOpen(false)}
              aria-label="一覧に戻る"
              className="rounded px-2 py-1 text-sm text-slate-600 hover:bg-slate-100 cursor-pointer"
            >
              ← 一覧
            </button>
            <span className="truncate text-sm font-semibold text-slate-700">
              候補詳細
            </span>
          </div>
        )}
        {selectedCandidate ? (
          <div className="space-y-4">
            <div>
              <h2 className="text-base font-bold">{selectedCandidate.display_name}</h2>
              <p className="text-xs text-slate-400">ID: {selectedCandidate.candidate_id} | 正規化名: {selectedCandidate.normalized_name}</p>
            </div>

            {/* Resolve Panel */}
            <div className="border border-slate-200 rounded-lg p-4 bg-slate-50 space-y-3">
              <h3 className="text-xs font-bold text-slate-800">マスター人物と紐付け（一括解決）</h3>

              {selectedCandidate.assigned_summaries_count > 0 && (
                <div className="rounded-lg bg-amber-50 p-3 text-xs font-medium text-amber-800 border border-amber-200 space-y-1">
                  <div className="font-bold">⚠️ 一括解決不可</div>
                  <div>文脈別に割り当て済みのため一括解決不可（個別割当済み件数: {selectedCandidate.assigned_summaries_count}件）</div>
                </div>
              )}

              {resolveError && (
                <div className="rounded-lg bg-red-50 p-3 text-xs font-medium text-red-800 border border-red-200">
                  <div className="font-bold">
                    {resolveError.message}
                  </div>
                  {resolveError.conflict_type && (
                    <div className="mt-1 text-[11px] text-red-600">
                      確定済みの人物: ID: {resolveError.existing_person_id} (名前: {resolveError.existing_person_name})
                    </div>
                  )}
                </div>
              )}

              <div className="flex flex-col gap-2 sm:flex-row">
                <select
                  value={targetPersonId}
                  onChange={(e) => onChangeTargetPersonId(e.target.value)}
                  disabled={selectedCandidate.assigned_summaries_count > 0}
                  className="w-full rounded border border-slate-300 bg-white px-2.5 py-1.5 text-xs focus:border-slate-900 focus:outline-none disabled:bg-slate-100 disabled:text-slate-400 sm:flex-1"
                >
                  <option value="">-- 解決先のVault連携人物を選択してください --</option>
                  {people
                    .filter((p) => p.vault_id !== null)
                    .map((p) => (
                      <option key={p.person_id} value={p.person_id}>
                        {p.display_name} ({p.vault_id})
                      </option>
                    ))}
                </select>
                <button
                  onClick={onResolveCandidate}
                  disabled={loading || !targetPersonId || selectedCandidate.assigned_summaries_count > 0}
                  className={`shrink-0 rounded bg-slate-900 px-4 py-1.5 text-xs text-white hover:bg-slate-800 disabled:opacity-50 ${
                    loading || !targetPersonId || selectedCandidate.assigned_summaries_count > 0
                      ? "disabled:cursor-not-allowed"
                      : "cursor-pointer"
                  }`}
                >
                  解決
                </button>
              </div>
              <p className="text-[10px] text-slate-400">
                ※ 解決先はフロントマターに ID を持つ「Vault連携済み」の人物に制限されています。未解決候補を解決すると、確定別名として登録され、候補のサマリー履歴が自動で移管されます。すでに手動で個別割当を行っている候補は、グローバル解決（一括解決）が禁止されます。
              </p>
            </div>

            {/* Promote to Unlinked Person Panel */}
            <div className="border border-slate-200 rounded-lg p-4 bg-blue-50/50 space-y-3">
              <h3 className="text-xs font-bold text-slate-800">未連携人物として昇格</h3>

              {selectedCandidate.assigned_summaries_count > 0 && (
                <div className="rounded-lg bg-amber-50 p-3 text-xs font-medium text-amber-800 border border-amber-200 space-y-1">
                  <div className="font-bold">⚠️ 昇格不可</div>
                  <div>文脈別に割り当て済みのため昇格不可（個別割当済み件数: {selectedCandidate.assigned_summaries_count}件）</div>
                </div>
              )}

              {promoteError && (
                <div className="rounded-lg bg-red-50 p-3 text-xs font-medium text-red-800 border border-red-200">
                  <div className="font-bold">
                    {promoteError.message}
                  </div>
                  {promoteError.conflict_type && (
                    <div className="mt-1 text-[11px] text-red-600">
                      競合の型: {promoteError.conflict_type}
                      {promoteError.existing_person_id && ` (競合人物ID: ${promoteError.existing_person_id}, 名前: ${promoteError.existing_person_name})`}
                    </div>
                  )}
                </div>
              )}

              <div className="text-[10px] text-slate-500">
                移管対象サマリ: <strong>{selectedCandidate.summaries.length}</strong>件
              </div>
              {promoteDisplayName !== selectedCandidate.display_name && (
                <div className="text-[10px] text-blue-600">
                  ※ 候補表記「{selectedCandidate.display_name}」は新人物の別名として保存されます。
                </div>
              )}

              <div className="flex flex-col gap-2 sm:flex-row">
                <input
                  type="text"
                  value={promoteDisplayName}
                  onChange={(e) => onChangePromoteDisplayName(e.target.value)}
                  disabled={selectedCandidate.assigned_summaries_count > 0}
                  className="w-full rounded border border-slate-300 bg-white px-2.5 py-1.5 text-xs focus:border-slate-900 focus:outline-none disabled:bg-slate-100 disabled:text-slate-400 sm:flex-1"
                  placeholder="新人物の表示名を入力"
                />
                <button
                  onClick={onPromoteCandidate}
                  disabled={loading || !promoteDisplayName.trim() || selectedCandidate.assigned_summaries_count > 0}
                  className={`shrink-0 rounded bg-blue-600 px-4 py-1.5 text-xs text-white hover:bg-blue-700 disabled:opacity-50 ${
                    loading || !promoteDisplayName.trim() || selectedCandidate.assigned_summaries_count > 0
                      ? "disabled:cursor-not-allowed"
                      : "cursor-pointer"
                  }`}
                >
                  昇格
                </button>
              </div>
              <p className="text-[10px] text-slate-400">
                ※ 未連携人物として新規作成します。Vault連携は行われず、既存の未連携人物と同じ同期・統合ルールが適用されます。
              </p>
            </div>

            <div>
              <h3 className="text-xs font-bold text-slate-700 mb-2">影響を受けるサマリ ({selectedCandidate.summaries.length})</h3>
              {selectedCandidate.summaries.length === 0 ? (
                <p className="text-xs text-slate-400">紐づいているサマリはありません。</p>
              ) : (
                <div className="border border-slate-100 rounded-lg overflow-hidden divide-y divide-slate-100">
                  {selectedCandidate.summaries.map((sum) => {
                    const assignedPersonId = summaryAssignments[sum.summary_id] || "";
                    const isAssignDisabled = loading || !assignedPersonId;
                    return (
                      <div key={sum.summary_id} className="p-3 text-xs flex flex-col md:flex-row md:items-center justify-between gap-3">
                        <div className="flex-1">
                          <div className="font-semibold">{sum.period_key} ({sum.period_type})</div>
                          {sum.note && <div className="text-slate-600 mt-1 font-mono bg-slate-50 p-1.5 rounded whitespace-pre-wrap">{sum.note}</div>}
                        </div>
                        <div className="flex shrink-0 flex-wrap items-center gap-2 self-end md:self-center">
                          <select
                            value={assignedPersonId}
                            onChange={(e) => onChangeSummaryAssignment(sum.summary_id, e.target.value)}
                            aria-label={`割当先を選択 (${sum.period_key})`}
                            className="rounded border border-slate-300 bg-white px-2 py-1 text-xs focus:border-slate-900 focus:outline-none"
                          >
                            <option value="">-- 割当先を選択 --</option>
                            {people
                              .filter((p) => p.vault_id !== null)
                              .map((p) => (
                                <option key={p.person_id} value={p.person_id}>
                                  {p.display_name} ({p.vault_id})
                                </option>
                              ))}
                          </select>
                          <button
                            onClick={() => onAssignCandidateSummary(sum.summary_id, assignedPersonId)}
                            disabled={isAssignDisabled}
                            aria-label={`このサマリ (${sum.period_key}) に割当`}
                            className={`rounded bg-slate-900 px-3 py-1 text-xs text-white hover:bg-slate-800 disabled:opacity-50 ${
                              isAssignDisabled ? "disabled:cursor-not-allowed" : "cursor-pointer"
                            }`}
                          >
                            このサマリに割当
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="h-full flex items-center justify-center text-xs text-slate-400">
            候補を選択すると詳細が表示されます。
          </div>
        )}
      </div>
    </>
  );
}
