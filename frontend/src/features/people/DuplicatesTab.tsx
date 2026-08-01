import React from "react";
import { Person } from "../../api/types";
import { DuplicatesResponse } from "./types";

interface DuplicatesTabProps {
  duplicates: DuplicatesResponse | null;
  people: Person[];
  loading: boolean;
  onTriggerMergePreview: (from: Person, to: Person) => void;
}

export default function DuplicatesTab({
  duplicates,
  people,
  loading,
  onTriggerMergePreview,
}: DuplicatesTabProps) {
  return (
    <div className="flex-1 border border-slate-200 bg-white rounded-lg p-4 overflow-y-auto space-y-6">
      <div>
        <h2 className="text-sm font-bold text-slate-900">重複人物候補</h2>
        <p className="text-xs text-slate-500 mt-0.5">データベース内で重複している、または同一Vault IDを持つ行の候補を表示し、安全に統合します。</p>
      </div>

      {/* Section 1: Vault Matches */}
      <div className="space-y-3">
        <h3 className="text-xs font-bold text-slate-800 border-b pb-1">未連携人物と現在のVaultファイルの一致</h3>
        {!duplicates?.vault_matches || duplicates.vault_matches.length === 0 ? (
          <p className="text-xs text-slate-400">一致する重複候補はありません。</p>
        ) : (
          <div className="space-y-3">
            {duplicates.vault_matches.map((m) => {
              const target = people.find((p) => p.vault_id === m.vault_person.id);
              return (
                <div key={m.unlinked_person.person_id} className="flex flex-col gap-3 rounded-lg border border-slate-200 bg-slate-50 p-4 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0 space-y-1">
                    <div className="text-xs font-semibold text-red-700">未連携人物: {m.unlinked_person.display_name} (ID: {m.unlinked_person.person_id})</div>
                    <div className="text-xs text-green-700 font-medium">Vault側の該当ノート: {m.vault_person.name} (Vault ID: {m.vault_person.id})</div>
                    <div className="text-[10px] text-slate-400 font-mono break-all">ファイルパス: {m.vault_person.path}</div>
                  </div>

                  <div className="flex shrink-0 gap-2">
                    {target ? (
                      <button
                        onClick={() => onTriggerMergePreview(m.unlinked_person, target)}
                        disabled={loading}
                        className={`rounded bg-blue-600 px-2 py-0.5 text-xs text-white hover:bg-blue-700 disabled:opacity-50 ${
                          loading ? "disabled:cursor-not-allowed" : "cursor-pointer"
                        }`}
                      >
                        {target.display_name}へ統合
                      </button>
                    ) : (
                      <span className="text-xs text-slate-400 font-medium">統合先人物を準備中...</span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Section 2: Same Vault ID Groups */}
      <div className="space-y-3">
        <h3 className="text-xs font-bold text-slate-800 border-b pb-1">同一の Vault 接続ID を持つ複数行</h3>
        {!duplicates?.same_vault_id_groups || duplicates.same_vault_id_groups.length === 0 ? (
          <p className="text-xs text-slate-400">同一Vault IDの重複行はありません。</p>
        ) : (
          <div className="space-y-4">
            {duplicates.same_vault_id_groups.map((grp) => (
              <div key={grp.vault_id} className="border border-slate-200 rounded-lg p-4 bg-slate-50 space-y-3">
                <div className="text-xs font-bold text-slate-800">Vault ID: <code className="bg-slate-200 px-1 rounded">{grp.vault_id}</code> の重複</div>

                <div className="divide-y divide-slate-100">
                  {grp.people.map((p) => (
                    <div key={p.person_id} className="flex flex-col gap-2 py-2.5 text-xs sm:flex-row sm:items-center sm:justify-between">
                      <div className="min-w-0">
                        <span className="font-semibold">{p.display_name}</span>
                        <span className="ml-1.5 text-[10px] text-slate-400">(ID: {p.person_id})</span>
                      </div>

                      {/* Allow merging other rows into this row */}
                      <div className="flex shrink-0 flex-wrap gap-1.5">
                        {grp.people
                          .filter((other) => other.person_id !== p.person_id)
                          .map((other) => (
                            <button
                              key={other.person_id}
                              onClick={() => onTriggerMergePreview(other, p)}
                              disabled={loading}
                              className={`rounded border border-blue-600 bg-blue-600 px-2 py-0.5 text-xs text-white hover:bg-blue-700 disabled:opacity-50 ${
                                loading ? "disabled:cursor-not-allowed" : "cursor-pointer"
                              }`}
                            >
                              {other.display_name}をここに統合
                            </button>
                          ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
