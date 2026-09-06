import React, { useEffect, useState, useRef } from "react";
import { ApiError } from "../../api/client";
import { Person, PersonAlias } from "../../api/types";
import {
  PersonCandidate,
  PersonCandidateDetail,
  PersonDetail,
  DuplicatesResponse,
  SyncPeopleResponse,
  PeopleMergePreviewResponse,
  PeopleError
} from "./types";
import * as peopleApi from "./peopleApi";

import CandidateTab from "./CandidateTab";
import PeopleListTab from "./PeopleListTab";
import DuplicatesTab from "./DuplicatesTab";
import VaultReportTab from "./VaultReportTab";
import MergePreviewDialog from "./MergePreviewDialog";
import DeleteAliasDialog from "./DeleteAliasDialog";
import DeletePersonDialog from "./DeletePersonDialog";

import {
  PersonRelationType,
  PersonRelation,
  RelationStatus,
  PersonRelationTypeCreateRequest,
  PersonRelationTypeUpdateRequest,
  PersonRelationCreateRequest,
  PersonRelationUpdateRequest,
  PersonRelationEvidenceCreateRequest,
  PersonRelationEvidenceUpdateRequest
} from "./types";
import RelationTypesTab from "./RelationTypesTab";
import RelationFormModal from "./RelationFormModal";

type Tab = "candidates" | "rejected_candidates" | "list" | "relation_types" | "duplicates" | "report";

interface TabDefinition {
  value: Tab;
  label: string;
  getCount: (
    candidatesCount: number,
    rejectedCandidatesCount: number,
    peopleCount: number,
    duplicatesCount: number,
    typesCount: number
  ) => number | string;
}

const TABS_CONFIG: TabDefinition[] = [
  {
    value: "candidates",
    label: "未解決候補",
    getCount: (cands) => cands,
  },
  {
    value: "rejected_candidates",
    label: "却下済み候補",
    getCount: (_, rejected) => rejected,
  },
  {
    value: "list",
    label: "人物一覧",
    getCount: (_, __, people) => people,
  },
  {
    value: "relation_types",
    label: "関係タイプ",
    getCount: (_, __, ___, ____, types) => types,
  },
  {
    value: "duplicates",
    label: "重複候補",
    getCount: (_, __, ___, dups) => dups,
  },
  {
    value: "report",
    label: "Vault入力レポート",
    getCount: () => "",
  },
];

export default function PeoplePage() {
  // 1. All useState declarations grouped at the top
  const [activeTab, setActiveTab] = useState<Tab>("candidates");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMessage] = useState<string | null>(null);

  // Data states
  const [candidates, setCandidates] = useState<PersonCandidate[]>([]);
  const [rejectedCandidates, setRejectedCandidates] = useState<PersonCandidate[]>([]);
  const [people, setPeople] = useState<Person[]>([]);
  const [duplicates, setDuplicates] = useState<DuplicatesResponse | null>(null);
  const [vaultReport, setVaultReport] = useState<SyncPeopleResponse | null>(null);
  const [relationTypes, setRelationTypes] = useState<PersonRelationType[]>([]);

  // Person relations state
  const [personRelations, setPersonRelations] = useState<PersonRelation[]>([]);
  const [relationStatusFilter, setRelationStatusFilter] = useState<RelationStatus | "all">("all");
  const [showRelationModal, setShowRelationModal] = useState(false);
  const [editingRelation, setEditingRelation] = useState<PersonRelation | null>(null);

  // Selected details
  const [selectedCandidate, setSelectedCandidate] = useState<PersonCandidateDetail | null>(null);
  const [selectedPerson, setSelectedPerson] = useState<PersonDetail | null>(null);
  const [mobileDetailOpen, setMobileDetailOpen] = useState(false);

  // Form states
  const [targetPersonId, setTargetPersonId] = useState("");
  const [resolveError, setResolveError] = useState<PeopleError | null>(null);
  const [summaryAssignments, setSummaryAssignments] = useState<Record<string, string>>({});

  // Edit & Delete states
  const [editDisplayName, setEditDisplayName] = useState("");
  const [editAliasesText, setEditAliasesText] = useState("");
  const [editError, setEditError] = useState<PeopleError | null>(null);
  const [editSuccess, setEditSuccess] = useState<string | null>(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [personToDelete, setPersonToDelete] = useState<PersonDetail | null>(null);

  // Alias deletion states
  const [aliasToDelete, setAliasToDelete] = useState<PersonAlias | null>(null);
  const [showAliasDeleteConfirm, setShowAliasDeleteConfirm] = useState(false);

  // Promote states
  const [promoteDisplayName, setPromoteDisplayName] = useState("");
  const [promoteError, setPromoteError] = useState<PeopleError | null>(null);

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

  // 2. All useEffect hooks and handler definitions defined after declarations
  useEffect(() => {
    setSummaryAssignments({});
    setPromoteDisplayName(selectedCandidate?.display_name || "");
    setPromoteError(null);
  }, [selectedCandidate]);

  useEffect(() => {
    setMobileDetailOpen(false);
  }, [activeTab]);

  useEffect(() => {
    if (!selectedCandidate && !selectedPerson) setMobileDetailOpen(false);
  }, [selectedCandidate, selectedPerson]);

  useEffect(() => {
    if (showMergeModal && dialogRef.current) {
      if (!dialogRef.current.open) {
        dialogRef.current.showModal();
      }
    }
  }, [showMergeModal]);

  useEffect(() => {
    loadAllData(true);
  }, []);

  const clearMessages = () => {
    setError(null);
    setSuccessMessage(null);
    setResolveError(null);
    setEditError(null);
    setEditSuccess(null);
  };

  const loadAllData = async (shouldClearSuccess?: boolean): Promise<boolean> => {
    setLoading(true);
    setError(null);
    setResolveError(null);
    if (shouldClearSuccess !== false) {
      setSuccessMessage(null);
    }
    try {
      const [candsData, rejectedCandsData, peopleData, dupsData, reportData, typesData] = await Promise.all([
        peopleApi.fetchCandidates("unresolved"),
        peopleApi.fetchCandidates("rejected"),
        peopleApi.fetchPeople(),
        peopleApi.fetchDuplicates(),
        peopleApi.fetchVaultReport(),
        peopleApi.fetchPersonRelationTypes(),
      ]);
      setCandidates(candsData);
      setRejectedCandidates(rejectedCandsData);
      setPeople(peopleData);
      setDuplicates(dupsData);
      setVaultReport(reportData);
      setRelationTypes(typesData);
      return true;
    } catch (e) {
      setError("データの読み込みに失敗しました");
      return false;
    } finally {
      setLoading(false);
    }
  };

  // Always fetch the full relation list; status filtering is done client-side
  // in PersonRelationsSection so counts stay consistent.
  // The request id guards against rapid person switching: a stale fetch
  // resolving after a newer one must not overwrite the current list.
  // Returns null on failure AND when superseded (both already surfaced or
  // moot), so callers can skip their success messages in those cases.
  // A legitimately empty list is `[]`, never null.
  const relationsRequestRef = useRef(0);
  const loadPersonRelations = async (personId: string): Promise<PersonRelation[] | null> => {
    const reqId = ++relationsRequestRef.current;
    try {
      const data = await peopleApi.fetchPersonRelations(personId);
      if (reqId !== relationsRequestRef.current) return null;
      setPersonRelations(data);
      return data;
    } catch {
      if (reqId !== relationsRequestRef.current) return null;
      setError("関係の読み込みに失敗しました");
      return null;
    }
  };

  // Mirrors the currently selected person for staleness guards: detail
  // fetches resolving after a person switch must not overwrite the new
  // selection (same race as the relation list above).
  const selectedPersonIdRef = useRef<string | null>(null);

  const handleRejectCandidate = async (candId: string) => {
    clearMessages();
    setLoading(true);
    try {
      await peopleApi.rejectCandidate(candId);
      setSuccessMessage("候補を却下しました。");
      setSelectedCandidate(null);
      await loadAllData(false);
    } catch (e: any) {
      setError(e.message || "却下に失敗しました");
    } finally {
      setLoading(false);
    }
  };

  const handleReopenCandidate = async (candId: string) => {
    clearMessages();
    setLoading(true);
    try {
      await peopleApi.reopenCandidate(candId);
      setSuccessMessage("候補を再開しました。");
      setSelectedCandidate(null);
      await loadAllData(false);
    } catch (e: any) {
      setError(e.message || "再開に失敗しました");
    } finally {
      setLoading(false);
    }
  };

  const handleAssignCandidateSummary = async (summaryId: string, assignedPersonId: string) => {
    if (!selectedCandidate || !assignedPersonId) return;
    clearMessages();
    setLoading(true);
    try {
      await peopleApi.assignCandidateSummary(
        selectedCandidate.candidate_id,
        summaryId,
        assignedPersonId
      );
      setSuccessMessage(`サマリー「${summaryId}」への個別割当を保存しました。`);

      try {
        const data = await peopleApi.fetchCandidateDetail(selectedCandidate.candidate_id);
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

  const handleSelectCandidate = async (cand: PersonCandidate) => {
    clearMessages();
    setTargetPersonId("");
    try {
      const data = await peopleApi.fetchCandidateDetail(cand.candidate_id);
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
    // Clear the previous person's relations immediately so stale data
    // is never shown while the new person's data loads.
    setPersonRelations([]);
    selectedPersonIdRef.current = p.person_id;
    try {
      const data = await peopleApi.fetchPersonDetail(p.person_id);
      if (selectedPersonIdRef.current !== p.person_id) return;
      setSelectedPerson(data);
      setMobileDetailOpen(true);
      setEditDisplayName(data.display_name);
      setEditAliasesText((data.aliases || []).map((al) => al.display_name).join("\n"));
      await loadPersonRelations(p.person_id);
    } catch (e) {
      if (selectedPersonIdRef.current !== p.person_id) return;
      setError("人物の詳細の取得に失敗しました");
    }
  };

  const handleRelationStatusFilterChange = (status: RelationStatus | "all") => {
    setRelationStatusFilter(status);
  };

  const handleCreateRelationType = async (req: PersonRelationTypeCreateRequest) => {
    await peopleApi.createPersonRelationType(req);
    const reloaded = await loadAllData(false);
    if (!reloaded) return;
    setSuccessMessage(`関係タイプ「${req.slug}」を作成しました。`);
  };

  const handleUpdateRelationType = async (relationTypeId: string, req: PersonRelationTypeUpdateRequest) => {
    const updated = await peopleApi.updatePersonRelationType(relationTypeId, req);
    const reloaded = await loadAllData(false);
    if (!reloaded) return;
    setSuccessMessage(`関係タイプ「${updated.slug}」を更新しました。`);
  };

  const handleCreateRelation = async (req: PersonRelationCreateRequest) => {
    if (!selectedPerson) return;
    const personId = selectedPerson.person_id;
    const res = await peopleApi.createPersonRelation(personId, req);
    // Set the success message only after the reload succeeds so a reload
    // failure never leaves contradictory success + error banners.
    const successMsg =
      res.action === "merged_into_existing"
        ? "既存の同一人物間関係が存在するため、内容および根拠を重複統合しました。"
        : "新しい人物間関係を作成しました。";
    try {
      const reloaded = await loadAllData(false);
      const updatedDetail = await peopleApi.fetchPersonDetail(personId);
      if (selectedPersonIdRef.current !== personId) return;
      setSelectedPerson(updatedDetail);
      const relations = await loadPersonRelations(personId);
      if (selectedPersonIdRef.current !== personId) return;
      if (!reloaded || relations === null) return;
      setSuccessMessage(successMsg);
    } catch (e) {
      if (selectedPersonIdRef.current !== personId) return;
      setError(e instanceof Error ? e.message : "詳細の再読み込みに失敗しました");
    }
  };

  const handleUpdateRelation = async (relationId: string, req: PersonRelationUpdateRequest) => {
    if (!selectedPerson) return;
    const personId = selectedPerson.person_id;
    const res = await peopleApi.updatePersonRelation(relationId, req);
    const successMsg =
      res.action === "merged_into_existing"
        ? "期間の変更により既存関係と一致したため、関係を統合しました。"
        : "人物間関係を更新しました。";
    try {
      const reloaded = await loadAllData(false);
      const updatedDetail = await peopleApi.fetchPersonDetail(personId);
      if (selectedPersonIdRef.current !== personId) return;
      setSelectedPerson(updatedDetail);
      const relations = await loadPersonRelations(personId);
      if (selectedPersonIdRef.current !== personId) return;
      if (!reloaded || relations === null) return;
      setSuccessMessage(successMsg);
    } catch (e) {
      if (selectedPersonIdRef.current !== personId) return;
      setError(e instanceof Error ? e.message : "詳細の再読み込みに失敗しました");
    }
  };

  const handleDeleteRelation = async (relationId: string) => {
    if (!selectedPerson) return;
    const personId = selectedPerson.person_id;
    try {
      await peopleApi.deletePersonRelation(relationId);
      const reloaded = await loadAllData(false);
      const updatedDetail = await peopleApi.fetchPersonDetail(personId);
      if (selectedPersonIdRef.current !== personId) return;
      setSelectedPerson(updatedDetail);
      const relations = await loadPersonRelations(personId);
      if (selectedPersonIdRef.current !== personId) return;
      if (!reloaded || relations === null) return;
      setSuccessMessage("人物間関係を削除しました。");
    } catch (e) {
      if (selectedPersonIdRef.current !== personId) return;
      setError(e instanceof Error ? e.message : "人物間関係の削除に失敗しました");
    }
  };

  const handleAddRelationEvidence = async (relationId: string, req: PersonRelationEvidenceCreateRequest) => {
    if (!selectedPerson) return;
    const personId = selectedPerson.person_id;
    await peopleApi.addRelationEvidence(relationId, req);
    const data = await loadPersonRelations(personId);
    if (selectedPersonIdRef.current !== personId) return;
    if (data === null) return;
    if (editingRelation && editingRelation.relation_id === relationId) {
      const updatedRel = data.find(
        (r) => r.relation_id === relationId
      );
      if (updatedRel) setEditingRelation(updatedRel);
    }
    setSuccessMessage("根拠 (Evidence) を追加しました。");
  };

  const handleUpdateRelationEvidence = async (evidenceId: string, req: PersonRelationEvidenceUpdateRequest) => {
    if (!selectedPerson) return;
    const personId = selectedPerson.person_id;
    await peopleApi.updateRelationEvidence(evidenceId, req);
    const data = await loadPersonRelations(personId);
    if (selectedPersonIdRef.current !== personId) return;
    if (data === null) return;
    if (editingRelation) {
      const updatedRel = data.find(
        (r) => r.relation_id === editingRelation.relation_id
      );
      if (updatedRel) setEditingRelation(updatedRel);
    }
    setSuccessMessage("根拠 (Evidence) を更新しました。");
  };

  const handleDeleteRelationEvidence = async (evidenceId: string) => {
    if (!selectedPerson) return;
    const personId = selectedPerson.person_id;
    await peopleApi.deleteRelationEvidence(evidenceId);
    const data = await loadPersonRelations(personId);
    if (selectedPersonIdRef.current !== personId) return;
    if (data === null) return;
    if (editingRelation) {
      const updatedRel = data.find(
        (r) => r.relation_id === editingRelation.relation_id
      );
      if (updatedRel) setEditingRelation(updatedRel);
    }
    setSuccessMessage("根拠 (Evidence) を削除しました。");
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

      const res = await peopleApi.updatePerson(
        selectedPerson.person_id,
        editDisplayName,
        aliasList
      );

      setSuccessMessage(`人物「${res.display_name}」を更新しました。`);
      setSelectedPerson(res);
      setEditDisplayName(res.display_name);
      setEditAliasesText((res.aliases || []).map((al) => al.display_name).join("\n"));
      await loadAllData(false);
    } catch (e: any) {
      if (e instanceof ApiError && e.status === 409) {
        const detail = e.body?.detail as PeopleError;
        setEditError(detail || { message: e.message });
        if (detail && (detail.conflict_type === "main_name_conflict" || detail.conflict_type === "alias_conflict")) {
          if (detail.existing_person_id && people.some(p => p.person_id === detail.existing_person_id)) {
            setMergeToPersonId(detail.existing_person_id);
            setMergeGuidance({ personId: detail.existing_person_id, personName: detail.existing_person_name || "" });
          }
        }
      } else {
        setEditError({ message: e.message || "更新に失敗しました" });
      }
    } finally {
      setLoading(false);
    }
  };

  const handleExecuteDelete = async () => {
    if (!personToDelete) return;
    setLoading(true);
    try {
      const res = await peopleApi.deletePerson(personToDelete.person_id);
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
      await peopleApi.resolveCandidate(selectedCandidate.candidate_id, targetPersonId);
      setSuccessMessage(`候補「${selectedCandidate.display_name}」を解決しました。`);
      setSelectedCandidate(null);
      await loadAllData(false);
    } catch (e: any) {
      if (e instanceof ApiError && e.status === 409) {
        setResolveError((e.body?.detail as PeopleError) || { message: e.message });
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
      const data = await peopleApi.getMergePreview(fromPerson.person_id, toPerson.person_id);
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
      await peopleApi.executeMerge(mergeFromPerson.person_id, toPersonId);
      setSuccessMessage(`「${mergeFromPerson.display_name}」を「${toPersonName}」へ統合しました。`);
      handleCloseModal();
      await loadAllData(false);
      setActiveTab("list");
      const detail = await peopleApi.fetchPersonDetail(toPersonId);
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
      const detail = await peopleApi.deleteAlias(selectedPerson.person_id, aliasToDelete.normalized_name);
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

  const handlePromoteCandidate = async () => {
    if (!selectedCandidate) return;
    clearMessages();
    setPromoteError(null);
    setLoading(true);
    try {
      const result = await peopleApi.promoteCandidate(
        selectedCandidate.candidate_id,
        promoteDisplayName
      );
      setSuccessMessage(`人物「${result.display_name}」を未連携人物として作成しました。`);
      setSelectedCandidate(null);
      setActiveTab("list");
      await loadAllData(false);
      setSelectedPerson(result);
      setEditDisplayName(result.display_name);
      setEditAliasesText((result.aliases || []).map((al) => al.display_name).join("\n"));
    } catch (e: any) {
      if (e instanceof ApiError && e.status === 409) {
        setPromoteError((e.body?.detail as PeopleError) || { message: e.message });
      } else {
        setError(e.message || "昇格に失敗しました");
      }
    } finally {
      setLoading(false);
    }
  };

  const handleSyncPeople = async () => {
    clearMessages();
    setLoading(true);
    try {
      const data = await peopleApi.syncPeople();
      setVaultReport(data);
      setSuccessMessage("Vaultの同期が完了しました。");
      await loadAllData(false);
    } catch (e: any) {
      setError(e.message || "同期に失敗しました");
    } finally {
      setLoading(false);
    }
  };

  const duplicatesTotalCount = (duplicates?.vault_matches.length || 0) + (duplicates?.same_vault_id_groups.length || 0);

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
          onClick={() => loadAllData()}
          disabled={loading}
          className="rounded bg-slate-900 px-3 py-1.5 text-xs text-white hover:bg-slate-800 disabled:opacity-50 cursor-pointer"
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

        {/* Dynamic Tab Buttons Render */}
        <div className="flex shrink-0 space-x-1 overflow-x-auto whitespace-nowrap border-b border-slate-200">
          {TABS_CONFIG.map((tab) => {
            const count = tab.getCount(candidates.length, rejectedCandidates.length, people.length, duplicatesTotalCount, relationTypes.length);
            const countSuffix = count !== "" ? ` (${count})` : "";
            const isTabActive = activeTab === tab.value;
            return (
              <button
                key={tab.value}
                onClick={() => { setActiveTab(tab.value); setSelectedCandidate(null); clearMessages(); }}
                className={`px-4 py-2 text-xs font-medium border-b-2 transition-colors cursor-pointer ${
                  isTabActive
                    ? "border-slate-900 text-slate-900 font-semibold"
                    : "border-transparent text-slate-500 hover:text-slate-700"
                }`}
              >
                {tab.label}{countSuffix}
              </button>
            );
          })}
        </div>

        <div className="min-h-0 flex-1 flex flex-col gap-4 overflow-hidden lg:flex-row">
          {activeTab === "relation_types" && (
            <div className="w-full overflow-y-auto rounded-lg border border-slate-200 bg-white p-6">
              <RelationTypesTab
                types={relationTypes}
                loading={loading}
                error={error}
                onCreateType={handleCreateRelationType}
                onUpdateType={handleUpdateRelationType}
              />
            </div>
          )}

          {activeTab === "candidates" && (
            <CandidateTab
              candidates={candidates}
              selectedCandidate={selectedCandidate}
              people={people}
              targetPersonId={targetPersonId}
              resolveError={resolveError}
              promoteDisplayName={promoteDisplayName}
              promoteError={promoteError}
              summaryAssignments={summaryAssignments}
              loading={loading}
              mobileDetailOpen={mobileDetailOpen}
              setMobileDetailOpen={setMobileDetailOpen}
              onSelectCandidate={handleSelectCandidate}
              onChangeTargetPersonId={setTargetPersonId}
              onResolveCandidate={handleResolveCandidate}
              onChangePromoteDisplayName={setPromoteDisplayName}
              onPromoteCandidate={handlePromoteCandidate}
              onChangeSummaryAssignment={(summaryId, personId) =>
                setSummaryAssignments((prev) => ({ ...prev, [summaryId]: personId }))
              }
              onAssignCandidateSummary={handleAssignCandidateSummary}
              onRejectCandidate={handleRejectCandidate}
            />
          )}

          {activeTab === "rejected_candidates" && (
            <CandidateTab
              candidates={rejectedCandidates}
              selectedCandidate={selectedCandidate}
              people={people}
              targetPersonId={targetPersonId}
              resolveError={resolveError}
              promoteDisplayName={promoteDisplayName}
              promoteError={promoteError}
              summaryAssignments={summaryAssignments}
              loading={loading}
              mobileDetailOpen={mobileDetailOpen}
              setMobileDetailOpen={setMobileDetailOpen}
              onSelectCandidate={handleSelectCandidate}
              onChangeTargetPersonId={setTargetPersonId}
              onResolveCandidate={handleResolveCandidate}
              onChangePromoteDisplayName={setPromoteDisplayName}
              onPromoteCandidate={handlePromoteCandidate}
              onChangeSummaryAssignment={(summaryId, personId) =>
                setSummaryAssignments((prev) => ({ ...prev, [summaryId]: personId }))
              }
              onAssignCandidateSummary={handleAssignCandidateSummary}
              onReopenCandidate={handleReopenCandidate}
              isRejectedTab={true}
            />
          )}

          {activeTab === "list" && (
            <PeopleListTab
              people={people}
              selectedPerson={selectedPerson}
              editDisplayName={editDisplayName}
              editAliasesText={editAliasesText}
              editError={editError}
              editSuccess={editSuccess}
              mergeGuidance={mergeGuidance}
              mergeToPersonId={mergeToPersonId}
              loading={loading}
              mobileDetailOpen={mobileDetailOpen}
              setMobileDetailOpen={setMobileDetailOpen}
              onSelectPerson={handleSelectPerson}
              onChangeEditDisplayName={setEditDisplayName}
              onChangeEditAliasesText={setEditAliasesText}
              onUpdatePerson={handleUpdatePerson}
              onTriggerDeleteConfirm={(p) => {
                setPersonToDelete(p);
                setShowDeleteConfirm(true);
              }}
              onChangeMergeToPersonId={setMergeToPersonId}
              onTriggerMergePreview={handleTriggerMergePreview}
              onTriggerAliasDelete={(al) => {
                setAliasToDelete(al);
                setShowAliasDeleteConfirm(true);
              }}
              personRelations={personRelations}
              relationStatusFilter={relationStatusFilter}
              onRelationStatusFilterChange={handleRelationStatusFilterChange}
              onOpenCreateRelationModal={() => {
                setEditingRelation(null);
                setShowRelationModal(true);
              }}
              onOpenEditRelationModal={(rel) => {
                setEditingRelation(rel);
                setShowRelationModal(true);
              }}
              onDeleteRelation={handleDeleteRelation}
            />
          )}

          {activeTab === "duplicates" && (
            <DuplicatesTab
              duplicates={duplicates}
              people={people}
              loading={loading}
              onTriggerMergePreview={handleTriggerMergePreview}
            />
          )}

          {activeTab === "report" && (
            <VaultReportTab
              vaultReport={vaultReport}
              loading={loading}
              onSyncPeople={handleSyncPeople}
            />
          )}
        </div>

        {/* Dialogs / Modals */}
        <MergePreviewDialog
          ref={dialogRef}
          mergeFromPerson={mergeFromPerson}
          mergeToPerson={mergeToPerson}
          previewLoading={previewLoading}
          previewData={previewData}
          mergeModalError={mergeModalError}
          loading={loading}
          onCloseModal={handleCloseModal}
          onExecuteMerge={handleExecuteMerge}
        />

        {showAliasDeleteConfirm && aliasToDelete && selectedPerson && (
          <DeleteAliasDialog
            aliasToDelete={aliasToDelete}
            selectedPerson={selectedPerson}
            loading={loading}
            onCancel={() => {
              setAliasToDelete(null);
              setShowAliasDeleteConfirm(false);
            }}
            onConfirm={handleDeleteAlias}
          />
        )}

        {showDeleteConfirm && personToDelete && (
          <DeletePersonDialog
            personToDelete={personToDelete}
            loading={loading}
            onCancel={() => {
              setPersonToDelete(null);
              setShowDeleteConfirm(false);
            }}
            onConfirm={handleExecuteDelete}
          />
        )}

        {showRelationModal && selectedPerson && (
          <RelationFormModal
            currentPersonId={selectedPerson.person_id}
            relationToEdit={editingRelation}
            types={relationTypes}
            peopleList={people}
            onClose={() => {
              setShowRelationModal(false);
              setEditingRelation(null);
            }}
            onCreate={handleCreateRelation}
            onUpdate={handleUpdateRelation}
            onAddEvidence={handleAddRelationEvidence}
            onUpdateEvidence={handleUpdateRelationEvidence}
            onDeleteEvidence={handleDeleteRelationEvidence}
          />
        )}
      </div>
    </div>
  );
}
