import React, { useEffect, useState, useRef } from "react";
import { apiGet, apiPost, apiPatch, apiDelete, ApiError } from "../../api/client";

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
  summary_count: number;
}

interface AssociatedSummary {
  summary_id: string;
  period_type: string;
  period_key: string;
  note: string | null;
  display_order: number;
}

interface RelationCounts {
  summaries: number;
  aliases: number;
  assignments: number;
}

interface PersonDetail extends Person {
  summaries: AssociatedSummary[];
  relation_counts: RelationCounts;
}

interface PersonCandidate {
  candidate_id: string;
  display_name: string;
  normalized_name: string;
  status: string;
}

interface PersonCandidateDetail extends PersonCandidate {
  summaries: AssociatedSummary[];
  assigned_summaries_count: number;
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

interface MergedSummaryPreview {
  summary_id: string;
  period_key: string;
  period_type: string;
  from_note: string | null;
  to_note: string | null;
  merged_note: string | null;
  merged_display_order: number | null;
}

interface AliasTransferPreview {
  normalized_name: string;
  display_name: string;
}

interface PeopleMergePreviewResponse {
  allowed: boolean;
  reason: string | null;
  from_person: Person | null;
  to_person: Person | null;
  transferred_summaries_count: number;
  transferred_aliases_count: number;
  alias_transfers: AliasTransferPreview[];
  merged_summaries: MergedSummaryPreview[];
}

type Tab = "candidates" | "list" | "duplicates" | "report";

const PEOPLE_API = "/api/v1/people";

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
  const [mobileDetailOpen, setMobileDetailOpen] = useState(false);

  // Form states
  const [targetPersonId, setTargetPersonId] = useState("");
  const [resolveError, setResolveError] = useState<any | null>(null);
  const [summaryAssignments, setSummaryAssignments] = useState<Record<string, string>>({});

  // Edit & Delete states
  const [editDisplayName, setEditDisplayName] = useState("");
  const [editAliasesText, setEditAliasesText] = useState("");
  const [editError, setEditError] = useState<any | null>(null);
  const [editSuccess, setEditSuccess] = useState<string | null>(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [personToDelete, setPersonToDelete] = useState<PersonDetail | null>(null);

  // Alias deletion states
  const [aliasToDelete, setAliasToDelete] = useState<PersonAlias | null>(null);
  const [showAliasDeleteConfirm, setShowAliasDeleteConfirm] = useState(false);

  useEffect(() => {
    setSummaryAssignments({});
  }, [selectedCandidate]);

  useEffect(() => {
    setMobileDetailOpen(false);
  }, [activeTab]);

  useEffect(() => {
    if (!selectedCandidate && !selectedPerson) setMobileDetailOpen(false);
  }, [selectedCandidate, selectedPerson]);

  const handleAssignCandidateSummary = async (summaryId: string, assignedPersonId: string) => {
    if (!selectedCandidate || !assignedPersonId) return;
    clearMessages();
    setLoading(true);
    try {
      await apiPost(`${PEOPLE_API}/candidates/${selectedCandidate.candidate_id}/summaries/${summaryId}/assign`, {
        target_person_id: assignedPersonId,
      });
      setSuccessMessage(`サマリー「${summaryId}」への個別割当を保存しました。`);

      try {
        const data = await apiGet<PersonCandidateDetail>(`${PEOPLE_API}/candidates/${selectedCandidate.candidate_id}`);
        setSelectedCandidate(data);
      } catch (e: any) {
        setSelectedCandidate(null);
      }
      await loadAllData(false);
    } catch (e: any) {
      setError(e.message || "個別割当に失敗しました");
    } finally {
      setLoading(false);
    }
  };

  // Merge modal & preview states
  const [mergeToPersonId, setMergeToPersonId] = useState("");
  const [showMergeModal, setShowMergeModal] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewData, setPreviewData] = useState<PeopleMergePreviewResponse | null>(null);
  const [mergeFromPerson, setMergeFromPerson] = useState<Person | null>(null);
  const [mergeToPerson, setMergeToPerson] = useState<Person | null>(null);
  const [mergeModalError, setMergeModalError] = useState<string | null>(null);
  const [mergeGuidance, setMergeGuidance] = useState<{ personId: string; personName: string } | null>(null);

  // Refs
  const dialogRef = useRef<HTMLDialogElement>(null);
  const triggerRef = useRef<HTMLElement | null>(null);
  const requestCounterRef = useRef(0);

  useEffect(() => {
    if (showMergeModal && dialogRef.current) {
      if (!dialogRef.current.open) {
        dialogRef.current.showModal();
      }
    }
  }, [showMergeModal]);

  const clearMessages = () => {
    setError(null);
    setSuccessMessage(null);
    setResolveError(null);
    setEditError(null);
    setEditSuccess(null);
  };

  const fetchCandidates = async () => {
    try {
      const data = await apiGet<PersonCandidate[]>(`${PEOPLE_API}/candidates`);
      setCandidates(data);
    } catch (e) {
      console.error(e);
      throw e;
    }
  };

  const fetchPeople = async () => {
    try {
      const data = await apiGet<Person[]>(PEOPLE_API);
      setPeople(data);
    } catch (e) {
      console.error(e);
      throw e;
    }
  };

  const fetchDuplicates = async () => {
    try {
      const data = await apiGet<DuplicatesResponse>(`${PEOPLE_API}/duplicates`);
      setDuplicates(data);
    } catch (e) {
      console.error(e);
      throw e;
    }
  };

  const fetchVaultReport = async () => {
    try {
      const data = await apiGet<SyncPeopleResponse>(`${PEOPLE_API}/vault-report`);
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
      const data = await apiGet<PersonCandidateDetail>(`${PEOPLE_API}/candidates/${cand.candidate_id}`);
      setSelectedCandidate(data);
      setMobileDetailOpen(true);
    } catch (e) {
      setError("候補の詳細の取得に失敗しました");
    }
  };

  const handleSelectPerson = async (p: Person) => {
    clearMessages();
    setMergeToPersonId("");
    setMergeGuidance(null);
    setEditError(null);
    setEditSuccess(null);
    try {
      const data = await apiGet<PersonDetail>(`${PEOPLE_API}/${p.person_id}`);
      setSelectedPerson(data);
      setMobileDetailOpen(true);
      setEditDisplayName(data.display_name);
      setEditAliasesText((data.aliases || []).map((al) => al.display_name).join("\n"));
    } catch (e) {
      setError("人物の詳細の取得に失敗しました");
    }
  };

  const handleUpdatePerson = async () => {
    if (!selectedPerson) return;
    setLoading(true);
    setEditError(null);
    setEditSuccess(null);
    try {
      const aliasList = editAliasesText
        .split("\n")
        .map((line) => line.trim())
        .filter((line) => line.length > 0);

      const res = await apiPatch<PersonDetail>(`${PEOPLE_API}/${selectedPerson.person_id}`, {
        display_name: editDisplayName,
        aliases: aliasList
      });

      setSuccessMessage(`人物「${res.display_name}」を更新しました。`);
      setSelectedPerson(res);
      setEditDisplayName(res.display_name);
      setEditAliasesText((res.aliases || []).map((al) => al.display_name).join("\n"));
      await loadAllData(false);
    } catch (e: any) {
      if (e instanceof ApiError && e.status === 409) {
        const detail = e.body?.detail;
        setEditError(detail || e.message);
        if (detail && (detail.conflict_type === "main_name_conflict" || detail.conflict_type === "alias_conflict")) {
          if (detail.existing_person_id && people.some(p => p.person_id === detail.existing_person_id)) {
            setMergeToPersonId(detail.existing_person_id);
            setMergeGuidance({ personId: detail.existing_person_id, personName: detail.existing_person_name || "" });
          }
        }
      } else {
        setEditError(e.message || "更新に失敗しました");
      }
    } finally {
      setLoading(false);
    }
  };

  const handleExecuteDelete = async () => {
    if (!personToDelete) return;
    setLoading(true);
    try {
      const res = await apiDelete<any>(`${PEOPLE_API}/${personToDelete.person_id}`);
      if (res.success) {
        setSuccessMessage(
          `人物「${personToDelete.display_name}」を完全に削除しました。` +
          `（削除された関連サマリ数: ${res.deleted_summary_people}件、別名数: ${res.deleted_aliases}件、手動割当数: ${res.deleted_assignments}件）`
        );
      } else {
        setSuccessMessage(`人物「${personToDelete.display_name}」を削除しました。`);
      }
      setSelectedPerson(null);
      setPersonToDelete(null);
      setShowDeleteConfirm(false);
      await loadAllData(false);
    } catch (e: any) {
      setError(e.message || "削除に失敗しました");
    } finally {
      setLoading(false);
    }
  };

  const handleResolveCandidate = async () => {
    if (!selectedCandidate || !targetPersonId) return;
    clearMessages();
    setLoading(true);
    try {
      await apiPost(`${PEOPLE_API}/candidates/${selectedCandidate.candidate_id}/resolve`, {
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

  const handleTriggerMergePreview = async (fromPerson: Person, toPerson: Person) => {
    triggerRef.current = document.activeElement as HTMLElement;
    const reqId = ++requestCounterRef.current;
    setMergeFromPerson(fromPerson);
    setMergeToPerson(toPerson);
    setPreviewData(null);
    setMergeModalError(null);
    setPreviewLoading(true);
    setShowMergeModal(true);
    try {
      const data = await apiPost<PeopleMergePreviewResponse>(`${PEOPLE_API}/merge/preview`, {
        from_person_id: fromPerson.person_id,
        to_person_id: toPerson.person_id,
      });
      if (reqId === requestCounterRef.current) {
        setPreviewData(data);
      }
    } catch (e: any) {
      if (reqId === requestCounterRef.current) {
        setMergeModalError(e.message || "マージプレビューの取得に失敗しました。");
      }
    } finally {
      if (reqId === requestCounterRef.current) {
        setPreviewLoading(false);
      }
    }
  };

  const handleCloseModal = () => {
    requestCounterRef.current++;
    if (dialogRef.current) {
      dialogRef.current.close();
    }
    setShowMergeModal(false);
    setPreviewData(null);
    setMergeFromPerson(null);
    setMergeToPerson(null);
    if (triggerRef.current) {
      triggerRef.current.focus();
      triggerRef.current = null;
    }
  };

  const handleExecuteMerge = async () => {
    if (!mergeFromPerson || !mergeToPerson) return;
    const toPersonId = mergeToPerson.person_id;
    const toPersonName = mergeToPerson.display_name;
    setLoading(true);
    try {
      await apiPost(`${PEOPLE_API}/merge`, {
        from_person_id: mergeFromPerson.person_id,
        to_person_id: toPersonId,
      });
      setSuccessMessage(`「${mergeFromPerson.display_name}」を「${toPersonName}」へ統合しました。`);
      handleCloseModal();
      await loadAllData(false);
      setActiveTab("list");
      const detail = await apiGet<PersonDetail>(`${PEOPLE_API}/${toPersonId}`);
      setSelectedPerson(detail);
      setEditDisplayName(detail.display_name);
      setEditAliasesText((detail.aliases || []).map((al) => al.display_name).join("\n"));
    } catch (e: any) {
      setMergeModalError(e.message || "人物統合に失敗しました");
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteAlias = async () => {
    if (!selectedPerson || !aliasToDelete) return;
    setLoading(true);
    try {
      const detail = await apiDelete<PersonDetail>(
        `${PEOPLE_API}/${selectedPerson.person_id}/aliases?normalized_name=${encodeURIComponent(aliasToDelete.normalized_name)}`
      );
      setSuccessMessage(`別名「${aliasToDelete.display_name}」を削除しました。`);
      setSelectedPerson(detail);
      setEditDisplayName(detail.display_name);
      setEditAliasesText((detail.aliases || []).map((al) => al.display_name).join("\n"));
      setShowAliasDeleteConfirm(false);
      setAliasToDelete(null);
      await loadAllData(false);
    } catch (e: any) {
      setError(e.message || "別名の削除に失敗しました");
    } finally {
      setLoading(false);
    }
  };

  const handleMergePeople = async (fromId: string, toId: string) => {
    clearMessages();
    setLoading(true);
    try {
      await apiPost(`${PEOPLE_API}/merge`, {
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
      const data = await apiPost<SyncPeopleResponse>(`${PEOPLE_API}/sync`, {});
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
    <div className="flex h-full flex-col overflow-hidden bg-slate-50">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 p-4 sm:p-6 sm:pb-4">
        <div>
          <h1 className="text-xl font-bold text-slate-900">人物同定・管理</h1>
          <p className="mt-1 text-xs text-slate-500">
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

      <div className="flex-1 min-h-0 flex flex-col gap-4 overflow-hidden p-4 pt-4 sm:p-6 sm:pt-4">
        {successMsg && (
          <div className="shrink-0 rounded-lg bg-green-50 p-3 text-xs font-medium text-green-800 border border-green-200">
            {successMsg}
          </div>
        )}

        {error && (
          <div className="shrink-0 rounded-lg bg-red-50 p-3 text-xs font-medium text-red-800 border border-red-200">
            {error}
          </div>
        )}

        {/* Tabs */}
        <div className="flex shrink-0 space-x-1 overflow-x-auto whitespace-nowrap border-b border-slate-200">
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

      <div className="min-h-0 flex-1 flex flex-col gap-4 overflow-hidden lg:flex-row">
        {/* TAB 1: CANDIDATES */}
        {activeTab === "candidates" && (
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
                    className="rounded px-2 py-1 text-sm text-slate-600 hover:bg-slate-100"
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
                          {typeof resolveError === "object" ? resolveError.message : resolveError}
                        </div>
                        {typeof resolveError === "object" && resolveError.conflict_type && (
                          <div className="mt-1 text-[11px] text-red-600">
                            確定済みの人物: ID: {resolveError.existing_person_id} (名前: {resolveError.existing_person_name})
                          </div>
                        )}
                      </div>
                    )}

                    <div className="flex flex-col gap-2 sm:flex-row">
                      <select
                        value={targetPersonId}
                        onChange={(e) => setTargetPersonId(e.target.value)}
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
                        onClick={handleResolveCandidate}
                        disabled={loading || !targetPersonId || selectedCandidate.assigned_summaries_count > 0}
                        className="shrink-0 rounded bg-slate-900 px-4 py-1.5 text-xs text-white hover:bg-slate-800 disabled:opacity-50"
                      >
                        解決
                      </button>
                    </div>
                    <p className="text-[10px] text-slate-400">
                      ※ 解決先は、フロントマターに ID を持つ「Vault連携済み」の人物に制限されています。未解決候補を解決すると、確定別名として登録され、候補のサマリー履歴が自動で移管されます。すでに手動で個別割当を行っている候補は、グローバル解決（一括解決）が禁止されます。
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
                          return (
                            <div key={sum.summary_id} className="p-3 text-xs flex flex-col md:flex-row md:items-center justify-between gap-3">
                              <div className="flex-1">
                                <div className="font-semibold">{sum.period_key} ({sum.period_type})</div>
                                {sum.note && <div className="text-slate-600 mt-1 font-mono bg-slate-50 p-1.5 rounded whitespace-pre-wrap">{sum.note}</div>}
                              </div>
                              <div className="flex shrink-0 flex-wrap items-center gap-2 self-end md:self-center">
                                <select
                                  value={assignedPersonId}
                                  onChange={(e) => setSummaryAssignments(prev => ({ ...prev, [sum.summary_id]: e.target.value }))}
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
                                  onClick={() => handleAssignCandidateSummary(sum.summary_id, assignedPersonId)}
                                  disabled={loading || !assignedPersonId}
                                  aria-label={`このサマリ (${sum.period_key}) に割当`}
                                  className="rounded bg-slate-900 px-3 py-1 text-xs text-white hover:bg-slate-800 disabled:opacity-50"
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
        )}

        {/* TAB 2: PEOPLE LIST */}
        {activeTab === "list" && (
          <>
            <div
              className={`flex w-full flex-col overflow-y-auto rounded-lg border border-slate-200 bg-white p-4 lg:w-1/3 ${
                mobileDetailOpen ? "hidden" : "flex"
              } lg:flex`}
            >
              <h2 className="mb-3 text-sm font-semibold">登録人物一覧</h2>
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
                      <div className="flex items-center justify-between mt-1 text-[10px] text-slate-400">
                        <span>サマリ: {p.summary_count ?? 0}件</span>
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
                    className="rounded px-2 py-1 text-sm text-slate-600 hover:bg-slate-100"
                  >
                    ← 一覧
                  </button>
                  <span className="truncate text-sm font-semibold text-slate-700">
                    人物詳細
                  </span>
                </div>
              )}
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
                          <span key={al.normalized_name} className="inline-flex items-center gap-1 bg-slate-100 text-slate-800 text-xs px-2 py-0.5 rounded border border-slate-200">
                            {al.display_name}
                            <button
                              onClick={() => {
                                setAliasToDelete(al);
                                setShowAliasDeleteConfirm(true);
                              }}
                              className="text-slate-400 hover:text-red-600 transition-colors leading-none"
                              aria-label={`別名「${al.display_name}」を削除`}
                            >
                              ×
                            </button>
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Edit Form (Unlinked Only) */}
                  {selectedPerson.vault_id === null && (
                    <div className="border border-slate-200 rounded-lg p-4 bg-slate-50 space-y-3">
                      <h3 className="text-xs font-bold text-slate-800">未連携人物の編集</h3>
                      {editError && (
                        <div className="rounded-lg bg-red-50 p-3 text-xs font-medium text-red-800 border border-red-200">
                          <div className="font-bold">
                            {typeof editError === "object" ? editError.message : editError}
                          </div>
                          {typeof editError === "object" && editError.conflict_type && (
                            <div className="mt-1 text-[11px] text-red-600">
                              競合の型: {editError.conflict_type}
                              {editError.existing_person_id && ` (競合人物ID: ${editError.existing_person_id}, 名前: ${editError.existing_person_name})`}
                            </div>
                          )}
                          {mergeGuidance && (
                            <div className="mt-2 text-[11px] text-amber-800 bg-amber-50 border border-amber-200 rounded p-2">
                              同一人物の可能性があるため、統合を検討してください。
                              統合先には競合人物（{mergeGuidance.personName}）を選択済みです。
                            </div>
                          )}
                        </div>
                      )}
                      {editSuccess && (
                        <div className="rounded-lg bg-green-50 p-3 text-xs font-medium text-green-800 border border-green-200">
                          {editSuccess}
                        </div>
                      )}
                      <div className="space-y-2">
                        <div>
                          <label className="block text-[11px] font-bold text-slate-700 mb-1" htmlFor="edit-name">表示名</label>
                          <input
                            id="edit-name"
                            type="text"
                            value={editDisplayName}
                            onChange={(e) => setEditDisplayName(e.target.value)}
                            className="w-full rounded border border-slate-300 bg-white px-2.5 py-1.5 text-xs focus:border-slate-900 focus:outline-none"
                            placeholder="表示名を入力してください"
                          />
                        </div>
                        <div>
                          <label className="block text-[11px] font-bold text-slate-700 mb-1" htmlFor="edit-aliases">別名 (1行に1別名を入力してください)</label>
                          <textarea
                            id="edit-aliases"
                            value={editAliasesText}
                            onChange={(e) => setEditAliasesText(e.target.value)}
                            rows={3}
                            className="w-full rounded border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-mono focus:border-slate-900 focus:outline-none"
                            placeholder="別名を1行ずつ入力してください"
                          />
                        </div>
                      </div>
                      <div className="flex justify-end">
                        <button
                          onClick={handleUpdatePerson}
                          disabled={loading || !editDisplayName.trim()}
                          className="rounded bg-slate-900 px-4 py-1.5 text-xs text-white hover:bg-slate-800 disabled:opacity-50"
                        >
                          変更内容を保存
                        </button>
                      </div>
                    </div>
                  )}

                  {/* Complete Deletion Section */}
                  <div className="border border-red-200 rounded-lg p-4 bg-red-50/50 space-y-3">
                    <h3 className="text-xs font-bold text-red-800">人物の完全削除 (危険操作)</h3>
                    <p className="text-[10px] text-red-600 leading-normal">
                      この操作を実行すると、人物データ本体に加えて、3つの関連テーブル（サマリ紐づき、確定別名、文脈別手動割当）からも関連行が完全に削除されます。サマリ本体や、Vault内のMarkdownファイル自体は削除されません。
                    </p>
                    <div className="flex justify-end">
                      <button
                        onClick={() => {
                          setPersonToDelete(selectedPerson);
                          setShowDeleteConfirm(true);
                        }}
                        disabled={loading}
                        className="rounded bg-red-600 px-4 py-1.5 text-xs text-white hover:bg-red-700 disabled:opacity-50"
                      >
                        完全に削除する
                      </button>
                    </div>
                  </div>

                  {/* Merge with another person section */}
                  <div className="border border-slate-200 rounded-lg p-4 bg-slate-50 space-y-3">
                    <h3 className="text-xs font-bold text-slate-800">この人物を別の人物へ統合</h3>
                    <div className="flex flex-col gap-2 sm:flex-row">
                      <select
                        value={mergeToPersonId}
                        onChange={(e) => setMergeToPersonId(e.target.value)}
                        className="w-full rounded border border-slate-300 bg-white px-2.5 py-1.5 text-xs focus:border-slate-900 focus:outline-none sm:flex-1"
                      >
                        <option value="">-- 統合先（残す）の人物を選択してください --</option>
                        {people
                          .filter((p) => p.person_id !== selectedPerson.person_id)
                          .map((p) => (
                            <option key={p.person_id} value={p.person_id}>
                              {p.display_name} {p.vault_id ? `(${p.vault_id})` : "(未連携)"}
                            </option>
                          ))}
                      </select>
                      <button
                        onClick={() => {
                          const target = people.find((p) => p.person_id === mergeToPersonId);
                          if (target) {
                            handleTriggerMergePreview(selectedPerson, target);
                          }
                        }}
                        disabled={loading || !mergeToPersonId}
                        className="shrink-0 rounded bg-slate-900 px-4 py-1.5 text-xs text-white hover:bg-slate-800 disabled:opacity-50"
                      >
                        統合プレビュー
                      </button>
                    </div>
                    <p className="text-[10px] text-slate-400">
                      ※ 統合元（この人物）のサマリー履歴や別名はすべて統合先にマージされ、統合元は削除されます。異なる Vault ID を持つ人物同士の統合や、連携済みから未連携への統合は拒否されます。
                    </p>
                  </div>

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
                    <div key={m.unlinked_person.person_id} className="flex flex-col gap-3 rounded-lg border border-slate-200 bg-slate-50 p-4 sm:flex-row sm:items-center sm:justify-between">
                      <div className="min-w-0 space-y-1">
                        <div className="text-xs font-semibold text-red-700">未連携人物: {m.unlinked_person.display_name} (ID: {m.unlinked_person.person_id})</div>
                        <div className="text-xs text-green-700 font-medium">Vault側の該当ノート: {m.vault_person.name} (Vault ID: {m.vault_person.id})</div>
                        <div className="text-[10px] text-slate-400 font-mono break-all">ファイルパス: {m.vault_person.path}</div>
                      </div>

                      <div className="flex shrink-0 gap-2">
                        {/* Find corresponding master person_id in DB */}
                        {(() => {
                          const target = people.find((p) => p.vault_id === m.vault_person.id);
                          if (target) {
                            return (
                              <button
                                onClick={() => handleTriggerMergePreview(m.unlinked_person, target)}
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
                                    onClick={() => handleTriggerMergePreview(other, p)}
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

      {/* People Merge Preview Modal */}
      {showMergeModal && (
        <dialog
          ref={dialogRef}
          onCancel={handleCloseModal}
          onClose={handleCloseModal}
          className="fixed inset-0 m-auto rounded-xl shadow-xl border border-slate-200 w-full max-w-2xl max-h-[85vh] p-0 overflow-hidden backdrop:bg-slate-900/60 backdrop:backdrop-blur-sm"
          role="dialog"
          aria-labelledby="merge-dialog-title"
          aria-modal="true"
        >
          <div className="flex flex-col h-full bg-white">
            {/* Modal Header */}
            <div className="p-4 border-b border-slate-100 flex items-center justify-between shrink-0 bg-slate-50">
              <h2 id="merge-dialog-title" className="text-sm font-bold text-slate-900">人物統合プレビューと確認</h2>
              <button
                onClick={handleCloseModal}
                className="text-slate-400 hover:text-slate-600 transition-colors text-xs"
                aria-label="閉じる"
              >
                ✕
              </button>
            </div>

            {/* Modal Body */}
            <div className="p-5 overflow-y-auto space-y-4 text-xs text-slate-700">
              {/* Target info comparison */}
              <div className="grid grid-cols-1 gap-4 border border-slate-100 rounded-lg p-3 bg-slate-50 sm:grid-cols-2">
                <div className="space-y-1">
                  <div className="text-[10px] uppercase font-bold text-slate-400">統合元（削除される人物）</div>
                  <div className="font-semibold text-slate-800 text-sm">{mergeFromPerson?.display_name}</div>
                  <div className="text-slate-500 text-[10px]">ID: {mergeFromPerson?.person_id}</div>
                  <div className="text-slate-500 text-[10px]">
                    Vault ID: {mergeFromPerson?.vault_id ? <code className="bg-slate-200 px-1 rounded">{mergeFromPerson.vault_id}</code> : "未連携"}
                  </div>
                </div>
                <div className="space-y-1 border-t border-slate-200 pt-4 sm:border-l sm:border-t-0 sm:pl-4 sm:pt-0">
                  <div className="text-[10px] uppercase font-bold text-slate-400">統合先（残す人物）</div>
                  <div className="font-semibold text-slate-800 text-sm">{mergeToPerson?.display_name}</div>
                  <div className="text-slate-500 text-[10px]">ID: {mergeToPerson?.person_id}</div>
                  <div className="text-slate-500 text-[10px]">
                    Vault ID: {mergeToPerson?.vault_id ? <code className="bg-slate-200 px-1 rounded">{mergeToPerson.vault_id}</code> : "未連携"}
                  </div>
                </div>
              </div>

              {previewLoading && (
                <div className="text-center py-6 text-slate-500 font-medium">
                  統合可能性と影響データを検証中...
                </div>
              )}

              {mergeModalError && (
                <div className="rounded-lg bg-red-50 p-3 font-medium text-red-800 border border-red-200">
                  {mergeModalError}
                </div>
              )}

              {previewData && (
                <div className="space-y-4">
                  {/* Status Banner */}
                  {previewData.allowed ? (
                    <div className="rounded-lg bg-green-50 p-3 text-green-800 border border-green-200 font-semibold flex items-center gap-1.5">
                      <span>✅</span> 統合可能です。安全上の問題は検出されませんでした。
                    </div>
                  ) : (
                    <div className="rounded-lg bg-red-50 p-3 text-red-800 border border-red-200 font-semibold flex items-center gap-1.5">
                      <span>❌</span> 統合できません。
                      <div className="font-normal mt-1">{previewData.reason}</div>
                    </div>
                  )}

                  {previewData.allowed && (
                    <>
                      {/* Aliases & Summaries Migration Counts */}
                      <div className="grid grid-cols-2 gap-4">
                        <div className="border border-slate-100 p-3 rounded-lg">
                          <div className="font-bold text-slate-800">移管されるサマリー</div>
                          <div className="text-lg font-extrabold text-slate-900 mt-1">{previewData.transferred_summaries_count} <span className="text-xs font-normal text-slate-500">件</span></div>
                          <div className="text-[10px] text-slate-400 mt-1">※ 統合元に紐付いていたすべてのサマリー履歴が統合先へ移管されます。</div>
                        </div>
                        <div className="border border-slate-100 p-3 rounded-lg">
                          <div className="font-bold text-slate-800">移管・一本化される別名</div>
                          <div className="text-lg font-extrabold text-slate-900 mt-1">{previewData.transferred_aliases_count} <span className="text-xs font-normal text-slate-500">件</span></div>
                          {previewData.alias_transfers.length > 0 && (
                            <div className="flex flex-wrap gap-1.5 mt-1.5">
                              {previewData.alias_transfers.map((al) => (
                                <span key={al.normalized_name} className="bg-slate-100 text-slate-800 text-[10px] px-1.5 py-0.5 rounded border">
                                  {al.display_name}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>

                      {/* Same summary note consolidation details */}
                      {previewData.merged_summaries.length > 0 && (
                        <div className="space-y-2">
                          <div className="font-bold text-slate-800 flex items-center gap-1">
                            <span>🔗</span> 同一サマリーでのメモ連結対象 ({previewData.merged_summaries.length} 件)
                          </div>
                          <p className="text-[10px] text-slate-400">同一サマリーに両者の参照が存在するため、メモ内容を改行連結し、表示順の先頭側を維持して統合します。</p>
                          <div className="border border-slate-200 rounded-lg overflow-hidden max-h-48 overflow-y-auto divide-y divide-slate-100 font-mono text-[11px]">
                            {previewData.merged_summaries.map((sum) => (
                              <div key={sum.summary_id} className="p-3 bg-slate-50 space-y-2">
                                <div className="font-bold text-slate-700 flex justify-between">
                                  <span>{sum.period_key} ({sum.period_type})</span>
                                  <span className="text-slate-400">表示順優先: {sum.merged_display_order}</span>
                                </div>
                                <div className="grid grid-cols-2 gap-2 text-[10px]">
                                  <div className="bg-red-50 p-1.5 rounded border border-red-100">
                                    <div className="font-semibold text-red-700 mb-0.5">元メモ (統合元):</div>
                                    <div className="whitespace-pre-wrap">{sum.from_note || "(なし)"}</div>
                                  </div>
                                  <div className="bg-green-50 p-1.5 rounded border border-green-100">
                                    <div className="font-semibold text-green-700 mb-0.5">元メモ (統合先):</div>
                                    <div className="whitespace-pre-wrap">{sum.to_note || "(なし)"}</div>
                                  </div>
                                </div>
                                <div className="bg-blue-50 p-2 rounded border border-blue-100 text-[11px]">
                                  <div className="font-semibold text-blue-700 mb-0.5">連結後のメモ:</div>
                                  <div className="whitespace-pre-wrap">{sum.merged_note || "(なし)"}</div>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}

              {/* Warnings and Unalterable Statement */}
              {previewData?.allowed && (
                <div className="rounded-lg bg-orange-50 border border-orange-200 p-3 text-orange-900 space-y-1.5">
                  <div className="font-bold flex items-center gap-1">
                    <span>⚠️</span> 取り消し不可の警告
                  </div>
                  <p className="text-[10px] text-orange-800 leading-normal">
                    この操作はデータベースを直接書き換えるため取り消しできません。統合を完了すると、統合元の人物データは永久に削除されます。内容に間違いがないか、事前によく確認してください。
                  </p>
                </div>
              )}
            </div>

            {/* Modal Footer */}
            <div className="p-4 border-t border-slate-100 bg-slate-50 flex items-center justify-end gap-2 shrink-0">
              <button
                onClick={handleCloseModal}
                className="rounded border border-slate-300 bg-white px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
                autoFocus
              >
                キャンセル
              </button>
              <button
                onClick={handleExecuteMerge}
                disabled={loading || previewLoading || !previewData?.allowed}
                className="rounded bg-slate-950 px-4 py-2 text-xs font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
              >
                {loading ? "統合を実行中..." : "安全に統合を実行する"}
              </button>
            </div>
          </div>
        </dialog>
      )}

      {/* Alias Delete Confirmation Modal */}
      {showAliasDeleteConfirm && aliasToDelete && selectedPerson && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-sm p-4">
          <div className="bg-white rounded-xl shadow-xl border border-slate-200 w-full max-w-sm overflow-hidden flex flex-col">
            <div className="p-4 border-b border-slate-100 bg-slate-50 flex items-center justify-between shrink-0">
              <h3 className="text-sm font-bold text-slate-900">別名の削除確認</h3>
              <button
                onClick={() => {
                  setAliasToDelete(null);
                  setShowAliasDeleteConfirm(false);
                }}
                className="text-slate-400 hover:text-slate-600 transition-colors text-xs"
                aria-label="閉じる"
              >
                ✕
              </button>
            </div>
            <div className="p-5 space-y-3 text-xs text-slate-700">
              <p>
                本当に別名「<strong className="text-slate-900">{aliasToDelete.display_name}</strong>」を
                「<strong className="text-slate-900">{selectedPerson.display_name}</strong>」から削除してもよろしいですか？
              </p>
              <p className="text-[10px] text-slate-500">
                この操作はデータベースから直接削除し、元に戻すことはできません。次回のVault同期でも復活しません。
              </p>
            </div>
            <div className="p-4 border-t border-slate-100 bg-slate-50 flex items-center justify-end gap-2 shrink-0">
              <button
                onClick={() => {
                  setAliasToDelete(null);
                  setShowAliasDeleteConfirm(false);
                }}
                className="rounded border border-slate-300 bg-white px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
              >
                キャンセル
              </button>
              <button
                onClick={handleDeleteAlias}
                disabled={loading}
                className="rounded bg-red-600 px-4 py-2 text-xs font-semibold text-white hover:bg-red-700 disabled:opacity-50"
              >
                {loading ? "削除中..." : "削除する"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Hard Delete Confirmation Modal */}
      {showDeleteConfirm && personToDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-sm p-4">
          <div className="bg-white rounded-xl shadow-xl border border-slate-200 w-full max-w-md overflow-hidden flex flex-col">
            {/* Modal Header */}
            <div className="p-4 border-b border-slate-100 bg-red-50 flex items-center justify-between shrink-0">
              <h3 className="text-sm font-bold text-red-900">⚠️ 人物の完全削除確認</h3>
              <button
                onClick={() => {
                  setPersonToDelete(null);
                  setShowDeleteConfirm(false);
                }}
                className="text-red-400 hover:text-red-600 transition-colors text-xs"
                aria-label="閉じる"
              >
                ✕
              </button>
            </div>

            {/* Modal Body */}
            <div className="p-5 overflow-y-auto space-y-3 text-xs text-slate-700 leading-normal">
              <p className="font-semibold text-slate-950">
                本当に「{personToDelete.display_name}」を完全に削除してもよろしいですか？
              </p>

              {personToDelete.vault_id ? (
                <div className="rounded-lg bg-orange-50 border border-orange-200 p-3 text-orange-950 font-medium space-y-1">
                  <div className="font-bold flex items-center gap-1">
                    <span>⚠️</span> Vaultノート連携に対する警告
                  </div>
                  <p className="text-[11px] leading-normal text-orange-800">
                    この人物は Vault ノート（ID: <code>{personToDelete.vault_id}</code>）と連携しています。DB から完全に削除されますが、Vault ノート自体は削除されません。
                    そのため、<strong>次回の同期（Sync）を実行した際に、この人物が再びデータベース上に再作成される可能性</strong>があります。
                  </p>
                </div>
              ) : (
                <div className="rounded-lg bg-red-50 border border-red-200 p-3 text-red-950 font-medium space-y-1">
                  <div className="font-bold flex items-center gap-1">
                    <span>⚠️</span> 取り消し不可の警告
                  </div>
                  <p className="text-[11px] leading-normal text-red-800">
                    この人物は未連携の人物です。削除を実行すると、紐づいていたすべてのサマリ履歴メモ、登録別名、手動個別割当などの関連行がDBから永久に消去され、元に戻すことはできません。
                  </p>
                </div>
              )}

              {personToDelete.relation_counts && (
                <div className="border border-slate-100 rounded-lg p-3 bg-slate-50 space-y-1 text-slate-600">
                  <div className="font-bold text-slate-800 mb-1">影響を受ける関連レコード数:</div>
                  <div>・紐づくサマリ: <strong className="text-slate-900">{personToDelete.relation_counts.summaries}</strong> 件</div>
                  <div>・別名 (aliases): <strong className="text-slate-900">{personToDelete.relation_counts.aliases}</strong> 件</div>
                  <div>・手動個別割当: <strong className="text-slate-900">{personToDelete.relation_counts.assignments}</strong> 件</div>
                </div>
              )}
            </div>

            {/* Modal Footer */}
            <div className="p-4 border-t border-slate-100 bg-slate-50 flex items-center justify-end gap-2 shrink-0">
              <button
                onClick={() => {
                  setPersonToDelete(null);
                  setShowDeleteConfirm(false);
                }}
                className="rounded border border-slate-300 bg-white px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
              >
                キャンセル
              </button>
              <button
                onClick={handleExecuteDelete}
                disabled={loading}
                className="rounded bg-red-600 px-4 py-2 text-xs font-semibold text-white hover:bg-red-700 disabled:opacity-50"
              >
                {loading ? "削除を実行中..." : "本当に完全に削除する"}
              </button>
            </div>
          </div>
        </div>
      )}
      </div>
    </div>
  );
}
