import React from "react";
import { SyncPeopleResponse } from "./types";

interface VaultReportTabProps {
  vaultReport: SyncPeopleResponse | null;
  loading: boolean;
  onSyncPeople: () => void;
}

export default function VaultReportTab({
  vaultReport,
  loading,
  onSyncPeople,
}: VaultReportTabProps) {
  return (
    <div className="flex-1 border border-slate-200 bg-white rounded-lg p-5 overflow-y-auto space-y-6">
      <div className="flex items-center justify-between border-b pb-3">
        <div>
          <h2 className="text-sm font-bold text-slate-900">Vault同期 & 安全性レポート</h2>
          <p className="text-xs text-slate-500 mt-0.5">現在のVaultファイルを安全にスキャンし、不備や衝突、DBとの差分状況を検証します。</p>
        </div>
        <button
          onClick={onSyncPeople}
          disabled={loading}
          className="rounded bg-slate-950 px-4 py-2 text-xs font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
        >
          {loading ? "同期中..." : "Vaultと人物同期を実行"}
        </button>
      </div>

      {vaultReport && (
        <div className="space-y-6 divide-y divide-slate-100">
          {/* 1. File Deficiencies */}
          <div className="space-y-2.5">
            <h3 className="text-xs font-bold text-red-800 flex items-center gap-1">
              <span>⚠️</span> ファイル不備・解析エラー ({vaultReport.loader_report.file_deficiencies.length})
            </h3>
            {vaultReport.loader_report.file_deficiencies.length === 0 ? (
              <p className="text-xs text-slate-400">ファイル不備・エラーはありません。</p>
            ) : (
              <div className="space-y-1.5">
                {vaultReport.loader_report.file_deficiencies.map((fd, i) => (
                  <div key={i} className="bg-red-50 border border-red-100 text-red-900 text-xs p-2.5 rounded font-mono">
                    <div><strong>Path:</strong> {fd.path}</div>
                    <div className="mt-0.5"><strong>Error:</strong> {fd.message}</div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* 2. Duplicate IDs */}
          <div className="pt-4 space-y-2.5">
            <h3 className="text-xs font-bold text-red-800 flex items-center gap-1">
              <span>⚠️</span> 重複した人物ID (Vault内) ({vaultReport.loader_report.duplicate_ids.length})
            </h3>
            {vaultReport.loader_report.duplicate_ids.length === 0 ? (
              <p className="text-xs text-slate-400">IDの重複はありません。</p>
            ) : (
              <div className="space-y-1.5">
                {vaultReport.loader_report.duplicate_ids.map((dup, i) => (
                  <div key={i} className="bg-red-50 border border-red-100 text-red-900 text-xs p-2.5 rounded">
                    <div><strong>ID:</strong> <code className="bg-red-100 px-1 rounded font-mono">{dup.id}</code></div>
                    <div className="mt-1 font-mono text-[11px] text-red-700">対象ファイル: {dup.paths.join(", ")}</div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* 3. Normalized Name Collisions */}
          <div className="pt-4 space-y-2.5">
            <h3 className="text-xs font-bold text-red-800 flex items-center gap-1">
              <span>⚠️</span> 同名衝突 (正規化名衝突) ({vaultReport.loader_report.normalized_name_collisions.length})
            </h3>
            {vaultReport.loader_report.normalized_name_collisions.length === 0 ? (
              <p className="text-xs text-slate-400">正規名衝突はありません。</p>
            ) : (
              <div className="space-y-2">
                {vaultReport.loader_report.normalized_name_collisions.map((col, i) => (
                  <div key={i} className="bg-red-50 border border-red-100 text-red-900 text-xs p-2.5 rounded space-y-1">
                    <div className="font-semibold">衝突した名前: {col.normalized_name}</div>
                    <div className="divide-y divide-red-100 font-mono text-[11px]">
                      {col.notes.map((n) => (
                        <div key={n.id} className="py-1">ID: {n.id} | 名前: {n.name} | パス: {n.path}</div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* 4. Alias Collisions */}
          <div className="pt-4 space-y-2.5">
            <h3 className="text-xs font-bold text-orange-800 flex items-center gap-1">
              <span>⚠️</span> 別名衝突 (alias衝突) ({vaultReport.loader_report.alias_collisions.length})
            </h3>
            <p className="text-[10px] text-slate-500">※ 異なる人物が同じaliasを主張しているため、この別名だけをスキャン照合マップから安全に除外しました。</p>
            {vaultReport.loader_report.alias_collisions.length === 0 ? (
              <p className="text-xs text-slate-400">別名衝突はありません。</p>
            ) : (
              <div className="space-y-2">
                {vaultReport.loader_report.alias_collisions.map((col, i) => (
                  <div key={i} className="bg-orange-50 border border-orange-100 text-orange-900 text-xs p-2.5 rounded space-y-1">
                    <div className="font-semibold">衝突した別名 (alias): {col.alias}</div>
                    <div className="divide-y divide-orange-100 font-mono text-[11px]">
                      {col.notes.map((n, j) => (
                        <div key={j} className="py-1">ID: {n.id} | 表記: {n.name} | 役割: {n.role} | パス: {n.path}</div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* 5. DB vs Vault Mismatches */}
          <div className="pt-4 space-y-2.5">
            <h3 className="text-xs font-bold text-red-800 flex items-center gap-1">
              <span>⚠️</span> DB確定別名とVault入力の不一致 ({vaultReport.db_conflicts.mismatches.length})
            </h3>
            <p className="text-[10px] text-slate-500">※ DBの確定別名とVault内の別名が矛盾しています。DBが優先され、Vault側の情報は候補吸収などに使用されません。</p>
            {vaultReport.db_conflicts.mismatches.length === 0 ? (
              <p className="text-xs text-slate-400">確定別名とVault入力の不一致はありません。</p>
            ) : (
              <div className="space-y-2">
                {vaultReport.db_conflicts.mismatches.map((m, i) => (
                  <div key={i} className="bg-red-50 border border-red-100 text-red-900 text-xs p-2.5 rounded space-y-1">
                    <div className="font-semibold">不一致の別名: {m.alias}</div>
                    <div className="font-mono text-[11px] space-y-0.5">
                      <div><strong>DBの確定人物:</strong> ID: {m.db_person_id} | 名前: {m.db_person_name} | Vault ID: {m.db_person_vault_id || "なし"}</div>
                      <div><strong>Vault側の主張者:</strong> ID: {m.vault_note.id} | 名前: {m.vault_note.name} | パス: {m.vault_note.path}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* 6. Compound Conflicts */}
          <div className="pt-4 space-y-2.5">
            <h3 className="text-xs font-bold text-red-800 flex items-center gap-1">
              <span>⚠️</span> DB確定人物と複数Vault主張者の複合衝突 ({vaultReport.db_conflicts.compound_conflicts.length})
            </h3>
            <p className="text-[10px] text-slate-500">※ 複数のVault主張者がDB確定人物のaliasと衝突しています。DB確定が維持され、自動吸収は行われません。</p>
            {vaultReport.db_conflicts.compound_conflicts.length === 0 ? (
              <p className="text-xs text-slate-400">複合衝突はありません。</p>
            ) : (
              <div className="space-y-2">
                {vaultReport.db_conflicts.compound_conflicts.map((cc, i) => (
                  <div key={i} className="bg-red-50 border border-red-100 text-red-900 text-xs p-2.5 rounded space-y-1">
                    <div className="font-semibold">衝突した別名: {cc.alias}</div>
                    <div className="font-mono text-[11px] space-y-1">
                      <div><strong>DBの確定人物:</strong> ID: {cc.db_person_id} | 名前: {cc.db_person_name} | Vault ID: {cc.db_person_vault_id || "なし"}</div>
                      <div className="text-red-700"><strong>Vault側の全主張者:</strong></div>
                      {cc.vault_claimers.map((vc) => (
                        <div key={vc.id} className="pl-4">• ID: {vc.id} | 名前: {vc.name} | パス: {vc.path}</div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
