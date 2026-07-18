import React, { useEffect, useState } from "react";
import { apiGet, apiPost, ApiError } from "../../api/client";

interface PersonAlias {
  normalized_name: string;
  display_name: string;
}

interface Person {
  person_id: string;
  display_name: string;
  normalized_name: string;
  vault_id: string | null;
  aliases: PersonAlias[];
}

interface AssociatedSummary {
  summary_id: string;
  period_type: string;
  period_key: string;
  note: string | null;
  display_order: number;
}

interface PersonDetail extends Person {
  summaries: AssociatedSummary[];
}

interface PersonCandidate {
  candidate_id: string;
  display_name: string;
  normalized_name: string;
  status: string;
}

interface PersonCandidateDetail extends PersonCandidate {
  summaries: AssociatedSummary[];
}

interface DuplicateVaultMatch {
  unlinked_person: Person;
  vault_person: {
    id: string;
    name: string;
    path: string;
  };
}

interface DuplicateSameVaultIdGroup {
  vault_id: string;
  people: Person[];
}

interface DuplicatesResponse {
  vault_matches: DuplicateVaultMatch[];
  same_vault_id_groups: DuplicateSameVaultIdGroup[];
}

interface SyncPeopleResponse {
  synced: boolean;
  loader_report: {
    file_deficiencies: Array<{ path: string; message: string }>;
    duplicate_ids: Array<{ id: string; paths: string[] }>;
    normalized_name_collisions: Array<{ normalized_name: string; notes: Array<{ id: string; name: string; path: string }> }>;
    alias_collisions: Array<{ alias: string; notes: Array<{ id: string; name: string; path: string; role: string }> }>;
  };
  db_conflicts: {
    mismatches: Array<{
      alias: string;
      db_person_id: string;
      db_person_name: string;
      db_person_vault_id: string | null;
      vault_note: { id: string; name: string; path: string };
    }>;
    compound_conflicts: Array<{
      alias: string;
      db_person_id: string;
      db_person_name: string;
      db_person_vault_id: string | null;
      vault_claimers: Array<{ id: string; name: string; path: string }>;
    }>;
  };
}

type Tab = "candidates" | "list" | "duplicates" | "report";

export default function PeoplePage() {
  const [activeTab, setActiveTab] = useState<Tab>("candidates");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMessage] = useState<string | null>(null);

  // Data states
  const [candidates, setCandidates] = useState<PersonCandidate[]>([]);
  const [people, setPeople] = useState<Person[]>([]);
  const [duplicates, setDuplicates] = useState<DuplicatesResponse | null>(null);
  const [vaultReport, setVaultReport] = useState<SyncPeopleResponse | null>(null);

  // Selected details
  const [selectedCandidate, setSelectedCandidate] = useState<PersonCandidateDetail | null>(null);
  const [selectedPerson, setSelectedPerson] = useState<PersonDetail | null>(null);

  // Form states
  const [targetPersonId, setTargetPersonId] = useState("");
  const [resolveError, setResolveError] = useState<any | null>(null);

  const clearMessages = () => {
    setError(null);
    setSuccessMessage(null);
    setResolveError(null);
  };

  const fetchCandidates = async () => {
    try {
      const data = await apiGet<PersonCandidate[]>("/people/candidates");
      setCandidates(data);
    } catch (e) {
      console.error(e);
      throw e;
    }
  };

  const fetchPeople = async () => {
    try {
      const data = await apiGet<Person[]>("/people");
      setPeople(data);
    } catch (e) {
      console.error(e);
      throw e;
    }
  };

  const fetchDuplicates = async () => {
    try {
      const data = await apiGet<DuplicatesResponse>("/people/duplicates");
      setDuplicates(data);
    } catch (e) {
      console.error(e);
      throw e;
    }
  };

  const fetchVaultReport = async () => {
    try {
      const data = await apiGet<SyncPeopleResponse>("/people/vault-report");
      setVaultReport(data);
    } catch (e) {
      console.error(e);
      throw e;
    }
  };

  const loadAllData = async (shouldClearSuccess?: any) => {
    setLoading(true);
    setError(null);
    setResolveError(null);
    if (shouldClearSuccess !== false) {
      setSuccessMessage(null);
    }
    try {
      await Promise.all([
        fetchCandidates(),
        fetchPeople(),
        fetchDuplicates(),
        fetchVaultReport(),
      ]);
    } catch (e) {
      setError("データの読み込みに失敗しました");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAllData(true);
  }, []);

  const handleSelectCandidate = async (cand: PersonCandidate) => {
    clearMessages();
    setTargetPersonId("");
    try {
      const data = await apiGet<PersonCandidateDetail>(`/people/candidates/${cand.candidate_id}`);
      setSelectedCandidate(data);
    } catch (e) {
      setError("候補の詳細の取得に失敗しました");
    }
  };

  const handleSelectPerson = async (p: Person) => {
    clearMessages();
    try {
      const data = await apiGet<PersonDetail>(`/people/${p.person_id}`);
      setSelectedPerson(data);
    } catch (e) {
      setError("人物の詳細の取得に失敗しました");
    }
  };

  const handleResolveCandidate = async () => {
    if (!selectedCandidate || !targetPersonId) return;
    clearMessages();
    setLoading(true);
    try {
      await apiPost(`/people/candidates/${selectedCandidate.candidate_id}/resolve`, {
        target_person_id: targetPersonId,
      });
      setSuccessMessage(`候補「${selectedCandidate.display_name}」を解決しました。`);
      setSelectedCandidate(null);
      await loadAllData(false);
    } catch (e: any) {
      if (e instanceof ApiError && e.status === 409) {
        setResolveError(e.body?.detail || e.message);
      } else {
        setError(e.message || "解決に失敗しました");
      }
    } finally {
      setLoading(false);
    }
  };

  const handleMergePeople = async (fromId: string, toId: string) => {
    clearMessages();
    setLoading(true);
    try {
      await apiPost("/people/merge", {
        from_person_id: fromId,
        to_person_id: toId,
      });
      setSuccessMessage("人物統合が完了しました。");
      await loadAllData(false);
    } catch (e: any) {
      setError(e.message || "人物統合に失敗しました");
    } finally {
      setLoading(false);
    }
  };

  const handleSyncPeople = async () => {
    clearMessages();
    setLoading(true);
    try {
      const data = await apiPost<SyncPeopleResponse>("/people/sync", {});
      setVaultReport(data);
      setSuccessMessage("Vaultの同期が完了しました。");
      await loadAllData(false);
    } catch (e: any) {
      setError(e.message || "同期に失敗しました");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex h-full flex-col bg-slate-50 p-6 overflow-y-auto">
      <div className="flex items-center justify-between border-b border-slate-200 pb-4 mb-4">
        <div>
          <h1 className="text-xl font-bold text-slate-900">人物同定・管理</h1>
          <p className="text-xs text-slate-500 mt-1">
            サマリから抽出された人物の解決、重複統合、およびVaultファイルとの同期を安全に管理します。
          </p>
        </div>
        <button
          onClick={loadAllData}
          disabled={loading}
          className="rounded bg-slate-900 px-3 py-1.5 text-xs text-white hover:bg-slate-800 disabled:opacity-50"
        >
          {loading ? "更新中..." : "データを再読み込み"}
        </button>
      </div>

      {successMsg && (
        <div className="mb-4 rounded-lg bg-green-50 p-3 text-xs font-medium text-green-800 border border-green-200">
          {successMsg}
        </div>
      )}

      {error && (
        <div className="mb-4 rounded-lg bg-red-50 p-3 text-xs font-medium text-red-800 border border-red-200">
          {error}
        </div>
      )}

      {/* Tabs */}
      <div className="flex space-x-1 border-b border-slate-200 mb-4 shrink-0">
        <button
          onClick={() => { setActiveTab("candidates"); clearMessages(); }}
          className={`px-4 py-2 text-xs font-medium border-b-2 transition-colors ${
            activeTab === "candidates"
              ? "border-slate-900 text-slate-900 font-semibold"
              : "border-transparent text-slate-500 hover:text-slate-700"
          }`}
        >
          未解決候補 ({candidates.length})
        </button>
        <button
          onClick={() => { setActiveTab("list"); clearMessages(); }}
          className={`px-4 py-2 text-xs font-medium border-b-2 transition-colors ${
            activeTab === "list"
              ? "border-slate-900 text-slate-900 font-semibold"
              : "border-transparent text-slate-500 hover:text-slate-700"
          }`}
        >
          人物一覧 ({people.length})
        </button>
        <button
          onClick={() => { setActiveTab("duplicates"); clearMessages(); }}
          className={`px-4 py-2 text-xs font-medium border-b-2 transition-colors ${
            activeTab === "duplicates"
              ? "border-slate-900 text-slate-900 font-semibold"
              : "border-transparent text-slate-500 hover:text-slate-700"
          }`}
        >
          重複候補 ({(duplicates?.vault_matches.length || 0) + (duplicates?.same_vault_id_groups.length || 0)})
        </button>
        <button
          onClick={() => { setActiveTab("report"); clearMessages(); }}
          className={`px-4 py-2 text-xs font-medium border-b-2 transition-colors ${
            activeTab === "report"
              ? "border-slate-900 text-slate-900 font-semibold"
              : "border-transparent text-slate-500 hover:text-slate-700"
          }`}
        >
          Vault入力レポート
        </button>
      </div>

      <div className="flex-1 min-h-0 flex gap-4 overflow-hidden">
        {/* TAB 1: CANDIDATES */}
        {activeTab === "candidates" && (
          <>
            <div className="w-1/3 border border-slate-200 bg-white rounded-lg p-4 flex flex-col overflow-y-auto">
              <h2 className="text-sm font-semibold mb-3">未解決候補一覧</h2>
              {candidates.length === 0 ? (
                <p className="text-xs text-slate-400">現在、未解決候補はありません。</p>
              ) : (
                <div className="space-y-2">
                  {candidates.map((cand) => (
                    <button
                      key={cand.candidate_id}
                      onClick={() => handleSelectCandidate(cand)}
                      className={`w-full text-left p-2.5 rounded-lg border text-xs transition-all ${
                        selectedCandidate?.candidate_id === cand.candidate_id
                          ? "border-slate-900 bg-slate-50 font-medium"
                          : "border-slate-200 hover:bg-slate-50"
                      }`}
                    >
                      <div>{cand.display_name}</div>
                      <div className="text-[10px] text-slate-400 mt-0.5">({cand.normalized_name})</div>
                    </button>
                  ))}
                </div>
              )}
            </div>

            <div className="flex-1 border border-slate-200 bg-white rounded-lg p-4 overflow-y-auto">
              {selectedCandidate ? (
                <div className="space-y-4">
                  <div>
                    <h2 className="text-base font-bold">{selectedCandidate.display_name}</h2>
                    <p className="text-xs text-slate-400">ID: {selectedCandidate.candidate_id} | 正規化名: {selectedCandidate.normalized_name}</p>
                  </div>

                  {/* Resolve Panel */}
                  <div className="border border-slate-200 rounded-lg p-4 bg-slate-50 space-y-3">
                    <h3 className="text-xs font-bold text-slate-800">マスター人物と紐付け（解決）</h3>

                    {resolveError && (
                      <div className="rounded-lg bg-red-50 p-3 text-xs font-medium text-red-800 border border-red-200">
                        <div className="font-bold">
                          {typeof resolveError === "object" ? resolveError.message : resolveError}
                        </div>
                        {typeof resolveError === "object" && resolveError.conflict_type && (
                          <div className="mt-1 text-[11px] text-red-600">
                            確定済みの人物: ID: {resolveError.existing_person_id} (名前: {resolveError.existing_person_name})
                          </div>
                        )}
                      </div>
                    )}

                    <div className="flex gap-2">
                      <select
                        value={targetPersonId}
                        onChange={(e) => setTargetPersonId(e.target.value)}
                        className="flex-1 rounded border border-slate-300 bg-white px-2.5 py-1.5 text-xs focus:border-slate-900 focus:outline-none"
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
                        onClick={handleResolveCandidate}
                        disabled={loading || !targetPersonId}
                        className="rounded bg-slate-900 px-4 py-1.5 text-xs text-white hover:bg-slate-800 disabled:opacity-50"
                      >
                        解決
                      </button>
                    </div>
                    <p className="text-[10px] text-slate-400">
                      ※ 解決先は、フロントマターに ID を持つ「Vault連携済み」の人物に制限されています。未解決候補を解決すると、確定別名として登録され、候補のサマリー履歴が自動で移管されます。
                    </p>
                  </div>

                  <div>
                    <h3 className="text-xs font-bold text-slate-700 mb-2">影響を受けるサマリ ({selectedCandidate.summaries.length})</h3>
                    {selectedCandidate.summaries.length === 0 ? (
                      <p className="text-xs text-slate-400">紐づいているサマリはありません。</p>
                    ) : (
                      <div className="border border-slate-100 rounded-lg overflow-hidden divide-y divide-slate-100">
                        {selectedCandidate.summaries.map((sum) => (
                          <div key={sum.summary_id} className="p-3 text-xs flex justify-between items-start">
                            <div>
                              <div className="font-semibold">{sum.period_key} ({sum.period_type})</div>
                              {sum.note && <div className="text-slate-600 mt-1 font-mono bg-slate-50 p-1.5 rounded">{sum.note}</div>}
                            </div>
                            <div className="text-[10px] text-slate-400">表示順: {sum.display_order}</div>
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
            </div>
          </>
        )}

        {/* TAB 2: PEOPLE LIST */}
        {activeTab === "list" && (
          <>
            <div className="w-1/3 border border-slate-200 bg-white rounded-lg p-4 flex flex-col overflow-y-auto">
              <h2 className="text-sm font-semibold mb-3">登録人物一覧</h2>
              {people.length === 0 ? (
                <p className="text-xs text-slate-400">現在、登録されている人物はいません。</p>
              ) : (
                <div className="space-y-2">
                  {people.map((p) => (
                    <button
                      key={p.person_id}
                      onClick={() => handleSelectPerson(p)}
                      className={`w-full text-left p-2.5 rounded-lg border text-xs transition-all ${
                        selectedPerson?.person_id === p.person_id
                          ? "border-slate-900 bg-slate-50 font-medium"
                          : "border-slate-200 hover:bg-slate-50"
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <span>{p.display_name}</span>
                        {p.vault_id ? (
                          <span className="bg-slate-100 text-slate-800 text-[9px] px-1.5 py-0.5 rounded-full font-mono">{p.vault_id}</span>
                        ) : (
                          <span className="bg-red-50 text-red-700 text-[9px] px-1.5 py-0.5 rounded-full">未連携</span>
                        )}
                      </div>
                      {p.aliases && p.aliases.length > 0 && (
                        <div className="text-[10px] text-slate-400 mt-1">
                          別名: {p.aliases.map((al) => al.display_name).join(", ")}
                        </div>
                      )}
                    </button>
                  ))}
                </div>
              )}
            </div>

            <div className="flex-1 border border-slate-200 bg-white rounded-lg p-4 overflow-y-auto">
              {selectedPerson ? (
                <div className="space-y-4">
                  <div>
                    <h2 className="text-base font-bold">{selectedPerson.display_name}</h2>
                    <p className="text-xs text-slate-400">ID: {selectedPerson.person_id} | 正規化名: {selectedPerson.normalized_name}</p>
                    {selectedPerson.vault_id && (
                      <p className="text-xs text-slate-500 mt-1">Vault 接続ID: <code className="bg-slate-100 px-1 rounded">{selectedPerson.vault_id}</code></p>
                    )}
                  </div>

                  {selectedPerson.aliases && selectedPerson.aliases.length > 0 && (
                    <div>
                      <h3 className="text-xs font-bold text-slate-700 mb-1.5">確定済み別名 (person_aliases)</h3>
                      <div className="flex flex-wrap gap-1.5">
                        {selectedPerson.aliases.map((al) => (
                          <span key={al.normalized_name} className="bg-slate-100 text-slate-800 text-xs px-2 py-0.5 rounded border border-slate-200">
                            {al.display_name}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  <div>
                    <h3 className="text-xs font-bold text-slate-700 mb-2">紐づくサマリ ({selectedPerson.summaries.length})</h3>
                    {selectedPerson.summaries.length === 0 ? (
                      <p className="text-xs text-slate-400">紐づいているサマリはありません。</p>
                    ) : (
                      <div className="border border-slate-100 rounded-lg overflow-hidden divide-y divide-slate-100">
                        {selectedPerson.summaries.map((sum) => (
                          <div key={sum.summary_id} className="p-3 text-xs flex justify-between items-start">
                            <div>
                              <div className="font-semibold">{sum.period_key} ({sum.period_type})</div>
                              {sum.note && <div className="text-slate-600 mt-1 font-mono bg-slate-50 p-1.5 rounded">{sum.note}</div>}
                            </div>
                            <div className="text-[10px] text-slate-400">表示順: {sum.display_order}</div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <div className="h-full flex items-center justify-center text-xs text-slate-400">
                  人物を選択すると詳細が表示されます。
                </div>
              )}
            </div>
          </>
        )}

        {/* TAB 3: DUPLICATE CANDIDATES */}
        {activeTab === "duplicates" && (
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
                  {duplicates.vault_matches.map((m) => (
                    <div key={m.unlinked_person.person_id} className="border border-slate-200 rounded-lg p-4 bg-slate-50 flex items-center justify-between">
                      <div className="space-y-1">
                        <div className="text-xs font-semibold text-red-700">未連携人物: {m.unlinked_person.display_name} (ID: {m.unlinked_person.person_id})</div>
                        <div className="text-xs text-green-700 font-medium">Vault側の該当ノート: {m.vault_person.name} (Vault ID: {m.vault_person.id})</div>
                        <div className="text-[10px] text-slate-400 font-mono">ファイルパス: {m.vault_person.path}</div>
                      </div>

                      <div className="flex gap-2">
                        {/* Find corresponding master person_id in DB */}
                        {(() => {
                          const target = people.find((p) => p.vault_id === m.vault_person.id);
                          if (target) {
                            return (
                              <button
                                onClick={() => {
                                  if (window.confirm(`「${m.unlinked_person.display_name}」を「${target.display_name}」へ統合しますか？`)) {
                                    handleMergePeople(m.unlinked_person.person_id, target.person_id);
                                  }
                                }}
                                disabled={loading}
                                className="rounded bg-slate-950 px-3 py-1.5 text-xs text-white hover:bg-slate-800 disabled:opacity-50"
                              >
                                {target.display_name}へ統合
                              </button>
                            );
                          }
                          return (
                            <span className="text-xs text-slate-400">統合先人物を準備中...</span>
                          );
                        })()}
                      </div>
                    </div>
                  ))}
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
                          <div key={p.person_id} className="py-2.5 flex items-center justify-between text-xs">
                            <div>
                              <span className="font-semibold">{p.display_name}</span>
                              <span className="text-[10px] text-slate-400 ml-1.5">(ID: {p.person_id})</span>
                            </div>

                            {/* Allow merging other rows into this row */}
                            <div className="flex gap-1.5">
                              {grp.people
                                .filter((other) => other.person_id !== p.person_id)
                                .map((other) => (
                                  <button
                                    key={other.person_id}
                                    onClick={() => {
                                      if (window.confirm(`「${other.display_name}」を「${p.display_name}」へ統合しますか？`)) {
                                        handleMergePeople(other.person_id, p.person_id);
                                      }
                                    }}
                                    disabled={loading}
                                    className="rounded border border-slate-300 bg-white px-2 py-1 text-[11px] text-slate-700 hover:bg-slate-50"
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
        )}

        {/* TAB 4: VAULT REPORT / SYNCHRONIZE */}
        {activeTab === "report" && (
          <div className="flex-1 border border-slate-200 bg-white rounded-lg p-5 overflow-y-auto space-y-6">
            <div className="flex items-center justify-between border-b pb-3">
              <div>
                <h2 className="text-sm font-bold text-slate-900">Vault同期 & 安全性レポート</h2>
                <p className="text-xs text-slate-500 mt-0.5">現在のVaultファイルを安全にスキャンし、不備や衝突、DBとの差分状況を検証します。</p>
              </div>
              <button
                onClick={handleSyncPeople}
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
        )}
      </div>
    </div>
  );
}
