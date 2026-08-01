import React, { useEffect, useState } from "react";
import { apiGet, apiPost, apiPatch, ApiError } from "../../api/client";
import type { ProjectCandidate } from "../../api/types";
import CandidateList from "./CandidateList";
import CandidateDetail from "./CandidateDetail";
import ProjectList from "./ProjectList";
import ProjectDetail from "./ProjectDetail";
import ArchiveList from "./ArchiveList";
import ProjectFormModal from "./ProjectFormModal";
import { parseKeywords } from "./utils";
import type {
  Project,
  ProjectDetail as ProjectDetailType,
  ProjectCandidateDetail,
  Tab,
  ProjectDomain,
  ProjectStatus,
  ResolveMode,
} from "./types";

export default function ProjectsPage() {
  const [activeTab, setActiveTab] = useState<Tab>("inbox");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMessage] = useState<string | null>(null);

  // Data states
  const [candidates, setCandidates] = useState<ProjectCandidate[]>([]);
  const [archivedCandidates, setArchivedCandidates] = useState<ProjectCandidate[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);

  // Selection states
  const [selectedProject, setSelectedProject] = useState<ProjectDetailType | null>(null);
  const [selectedCandidate, setSelectedCandidate] = useState<ProjectCandidateDetail | null>(null);
  const [mobileDetailOpen, setMobileDetailOpen] = useState(false);

  // Filters
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [domainFilter, setDomainFilter] = useState<string>("all");

  // Edit / Creation state
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [showResolveModal, setShowResolveModal] = useState(false);

  // Resolution Mode / Form states
  const [resolveMode, setResolveMode] = useState<ResolveMode>("approve_new");
  const [targetProjectId, setTargetProjectId] = useState<number | "">("");

  // Common Form Fields (used for Create, Edit, and Resolve/Approve)
  const [formDisplayName, setFormDisplayName] = useState("");
  const [formDomain, setFormDomain] = useState<ProjectDomain>("personal");
  const [formStatus, setFormStatus] = useState<ProjectStatus>("inquiry");
  const [formGoal, setFormGoal] = useState("");
  const [formDescription, setFormDescription] = useState("");
  const [formKeywordsText, setFormKeywordsText] = useState("");
  const [formStartDate, setFormStartDate] = useState("");
  const [formTargetDate, setFormTargetDate] = useState("");
  const [formCompletedDate, setFormCompletedDate] = useState("");
  const [formProjectPath, setFormProjectPath] = useState("");
  const [formReferenceUrl, setFormReferenceUrl] = useState("");

  const candidatesRequestCounterRef = React.useRef(0);
  const projectsRequestCounterRef = React.useRef(0);

  const clearMessages = () => {
    setError(null);
    setSuccessMessage(null);
  };

  const loadCandidatesOnly = async () => {
    const reqId = ++candidatesRequestCounterRef.current;
    setLoading(true);
    try {
      const unresolved = await apiGet<ProjectCandidate[]>("/api/v1/projects/candidates?status=unresolved");
      const resolved = await apiGet<ProjectCandidate[]>("/api/v1/projects/candidates?status=resolved");
      const rejected = await apiGet<ProjectCandidate[]>("/api/v1/projects/candidates?status=rejected");
      if (reqId === candidatesRequestCounterRef.current) {
        setCandidates(unresolved);
        setArchivedCandidates([...resolved, ...rejected]);
      }
    } catch (e: any) {
      if (reqId === candidatesRequestCounterRef.current) {
        setError(e.message || "候補の読み込みに失敗しました");
      }
    } finally {
      if (reqId === candidatesRequestCounterRef.current) {
        setLoading(false);
      }
    }
  };

  const loadProjectsOnly = async () => {
    const reqId = ++projectsRequestCounterRef.current;
    setLoading(true);
    try {
      let url = "/api/v1/projects";
      const qParts: string[] = [];
      if (domainFilter !== "all") {
        qParts.push(`domain=${domainFilter}`);
      }
      if (statusFilter !== "all") {
        qParts.push(`status=${statusFilter}`);
      }
      if (qParts.length > 0) {
        url += "?" + qParts.join("&");
      }
      const data = await apiGet<Project[]>(url);
      if (reqId === projectsRequestCounterRef.current) {
        setProjects(data);
      }
    } catch (e: any) {
      if (reqId === projectsRequestCounterRef.current) {
        setError(e.message || "プロジェクトの読み込みに失敗しました");
      }
    } finally {
      if (reqId === projectsRequestCounterRef.current) {
        setLoading(false);
      }
    }
  };

  const loadAllData = async (shouldClearSuccess = true) => {
    if (shouldClearSuccess) {
      clearMessages();
    }
    await Promise.all([loadCandidatesOnly(), loadProjectsOnly()]);
  };

  useEffect(() => {
    clearMessages();
    loadCandidatesOnly();
  }, []);

  useEffect(() => {
    loadProjectsOnly();
  }, [statusFilter, domainFilter]);

  useEffect(() => {
    setMobileDetailOpen(false);
  }, [activeTab]);

  useEffect(() => {
    if (!selectedProject && !selectedCandidate) setMobileDetailOpen(false);
  }, [selectedProject, selectedCandidate]);

  const handleSelectProject = async (p: Project) => {
    clearMessages();
    try {
      const data = await apiGet<ProjectDetailType>(`/api/v1/projects/${p.project_id}`);
      setSelectedProject(data);
      setMobileDetailOpen(true);
    } catch (e) {
      setError("プロジェクトの詳細の取得に失敗しました");
    }
  };

  const handleSelectCandidate = async (c: ProjectCandidate) => {
    clearMessages();
    try {
      const data = await apiGet<ProjectCandidateDetail>(`/api/v1/projects/candidates/${c.candidate_id}`);
      setSelectedCandidate(data);
      setMobileDetailOpen(true);
    } catch (e) {
      setError("候補の詳細の取得に失敗しました");
    }
  };

  const openCreateModal = () => {
    setFormDisplayName("");
    setFormDomain("personal");
    setFormStatus("inquiry");
    setFormGoal("");
    setFormDescription("");
    setFormKeywordsText("");
    setFormStartDate("");
    setFormTargetDate("");
    setFormCompletedDate("");
    setFormProjectPath("");
    setFormReferenceUrl("");
    setShowCreateModal(true);
  };

  const handleCreateProject = async () => {
    setLoading(true);
    clearMessages();
    try {
      const keywords = parseKeywords(formKeywordsText);

      const res = await apiPost<ProjectDetailType>("/api/v1/projects", {
        display_name: formDisplayName,
        domain: formDomain,
        status: formStatus,
        goal: formGoal || null,
        description: formDescription || null,
        keywords: keywords,
        start_date: formStartDate || null,
        target_date: formTargetDate || null,
        completed_date: formCompletedDate || null,
        project_path: formProjectPath || null,
        reference_url: formReferenceUrl || null,
      });

      setSuccessMessage(`プロジェクト「${res.display_name}」を登録しました。`);
      setShowCreateModal(false);
      await loadAllData(false);
      setSelectedProject(res);
      setMobileDetailOpen(true);
    } catch (e: any) {
      if (e instanceof ApiError && e.status === 409) {
        setError("競合エラー: 同一の名前を持つプロジェクトがすでに存在します。");
      } else {
        setError(e.message || "登録に失敗しました");
      }
    } finally {
      setLoading(false);
    }
  };

  const openEditModal = () => {
    if (!selectedProject) return;
    setFormDisplayName(selectedProject.display_name);
    setFormDomain(selectedProject.domain);
    setFormStatus(selectedProject.status);
    setFormGoal(selectedProject.goal || "");
    setFormDescription(selectedProject.description || "");
    setFormKeywordsText((selectedProject.keywords || []).join("\n"));
    setFormStartDate(selectedProject.start_date || "");
    setFormTargetDate(selectedProject.target_date || "");
    setFormCompletedDate(selectedProject.completed_date || "");
    setFormProjectPath(selectedProject.project_path || "");
    setFormReferenceUrl(selectedProject.reference_url || "");
    setShowEditModal(true);
  };

  const handleUpdateProject = async () => {
    if (!selectedProject) return;
    setLoading(true);
    clearMessages();
    try {
      const keywords = parseKeywords(formKeywordsText);

      const res = await apiPatch<ProjectDetailType>(`/api/v1/projects/${selectedProject.project_id}`, {
        display_name: formDisplayName,
        domain: formDomain,
        status: formStatus,
        goal: formGoal || null,
        description: formDescription || null,
        keywords: keywords,
        start_date: formStartDate || null,
        target_date: formTargetDate || null,
        completed_date: formCompletedDate || null,
        project_path: formProjectPath || null,
        reference_url: formReferenceUrl || null,
      });

      setSuccessMessage(`プロジェクト「${res.display_name}」を更新しました。`);
      setShowEditModal(false);
      await loadAllData(false);
      setSelectedProject(res);
    } catch (e: any) {
      if (e instanceof ApiError && e.status === 409) {
        setError("競合エラー: 同一の名前を持つプロジェクトがすでに存在します。");
      } else {
        setError(e.message || "更新に失敗しました");
      }
    } finally {
      setLoading(false);
    }
  };

  const openResolveModal = () => {
    if (!selectedCandidate) return;
    setResolveMode("approve_new");
    setTargetProjectId("");
    setFormDisplayName(selectedCandidate.display_name);
    setFormDomain(selectedCandidate.domain);
    setFormStatus("active");
    setFormGoal(selectedCandidate.goal || "");
    setFormDescription(selectedCandidate.description || "");
    setFormKeywordsText((selectedCandidate.keywords || []).join("\n"));
    setFormStartDate(selectedCandidate.start_date || "");
    setFormTargetDate(selectedCandidate.target_date || "");
    setFormCompletedDate(selectedCandidate.completed_date || "");
    setFormProjectPath("");
    setFormReferenceUrl("");
    setShowResolveModal(true);
  };

  const handleResolveCandidate = async () => {
    if (!selectedCandidate) return;
    setLoading(true);
    clearMessages();
    try {
      const keywords = parseKeywords(formKeywordsText);

      let payload: any = {
        action: resolveMode,
      };

      if (resolveMode === "approve_new") {
        payload = {
          ...payload,
          display_name: formDisplayName,
          domain: formDomain,
          status: formStatus,
          goal: formGoal || null,
          description: formDescription || null,
          keywords: keywords,
          start_date: formStartDate || null,
          target_date: formTargetDate || null,
          completed_date: formCompletedDate || null,
          project_path: formProjectPath || null,
          reference_url: formReferenceUrl || null,
        };
      } else if (resolveMode === "link_existing") {
        if (!targetProjectId) {
          throw new Error("紐付け先プロジェクトを選択してください。");
        }
        payload.target_project_id = Number(targetProjectId);
      }

      await apiPost(`/api/v1/projects/candidates/${selectedCandidate.candidate_id}/resolve`, payload);
      setSuccessMessage(`候補「${selectedCandidate.display_name}」の解決処理を完了しました。`);
      setShowResolveModal(false);
      setSelectedCandidate(null);
      await loadAllData(false);
    } catch (e: any) {
      if (e instanceof ApiError && e.status === 409) {
        setError("競合エラー: 同一の名前を持つプロジェクトがすでに存在します。");
      } else {
        setError(e.message || "解決処理に失敗しました");
      }
    } finally {
      setLoading(false);
    }
  };

  const handleQuickCandidateAction = async (c: ProjectCandidate, action: "reject" | "reopen_rejected") => {
    setLoading(true);
    clearMessages();
    try {
      await apiPost(`/api/v1/projects/candidates/${c.candidate_id}/resolve`, {
        action: action,
      });
      setSuccessMessage(action === "reject" ? `候補「${c.display_name}」を却下しました。` : `候補「${c.display_name}」を再開しました。`);
      if (selectedCandidate?.candidate_id === c.candidate_id) {
        setSelectedCandidate(null);
      }
      await loadAllData(false);
    } catch (e: any) {
      setError(e.message || "処理に失敗しました");
    } finally {
      setLoading(false);
    }
  };

  const closeModals = () => {
    setShowCreateModal(false);
    setShowEditModal(false);
    setShowResolveModal(false);
  };

  const handleModalSubmit = () => {
    if (showCreateModal) {
      handleCreateProject();
    } else if (showEditModal) {
      handleUpdateProject();
    } else if (showResolveModal) {
      handleResolveCandidate();
    }
  };

  return (
    <div className="flex h-full flex-col overflow-hidden bg-slate-50">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 p-4 sm:p-6 sm:pb-4">
        <div>
          <h1 className="text-xl font-bold text-slate-900">プロジェクト追跡</h1>
          <p className="mt-1 text-xs text-slate-500">
            ゴールや終了状態を持つ取り組みをプロジェクトとして管理し、サマリと紐付けます。
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={openCreateModal}
            className="rounded bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700"
          >
            新規登録
          </button>
          <button
            onClick={() => loadAllData()}
            disabled={loading}
            className="rounded border border-slate-300 bg-white px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            {loading ? "更新中..." : "再読み込み"}
          </button>
        </div>
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
          onClick={() => { setActiveTab("inbox"); clearMessages(); }}
          className={`px-4 py-2 text-xs font-medium border-b-2 transition-colors ${
            activeTab === "inbox"
              ? "border-slate-900 text-slate-900 font-semibold"
              : "border-transparent text-slate-500 hover:text-slate-700"
          }`}
        >
          候補受信箱 ({candidates.length})
        </button>
        <button
          onClick={() => { setActiveTab("projects"); clearMessages(); }}
          className={`px-4 py-2 text-xs font-medium border-b-2 transition-colors ${
            activeTab === "projects"
              ? "border-slate-900 text-slate-900 font-semibold"
              : "border-transparent text-slate-500 hover:text-slate-700"
          }`}
        >
          プロジェクト一覧 ({projects.length})
        </button>
        <button
          onClick={() => { setActiveTab("archive"); clearMessages(); }}
          className={`px-4 py-2 text-xs font-medium border-b-2 transition-colors ${
            activeTab === "archive"
              ? "border-slate-900 text-slate-900 font-semibold"
              : "border-transparent text-slate-500 hover:text-slate-700"
          }`}
        >
          履歴・却下済み候補 ({archivedCandidates.length})
        </button>
      </div>

      <div className="min-h-0 flex-1 flex flex-col gap-4 overflow-hidden lg:flex-row">
        {/* TAB 1: INBOX */}
        {activeTab === "inbox" && (
          <>
            <div
              className={`flex w-full flex-col overflow-y-auto rounded-lg border border-slate-200 bg-white p-4 lg:w-1/3 ${
                mobileDetailOpen ? "hidden" : "flex"
              } lg:flex`}
            >
              <CandidateList
                candidates={candidates}
                selectedCandidateId={selectedCandidate?.candidate_id ?? null}
                onSelect={handleSelectCandidate}
              />
            </div>

            <div
              className={`w-full overflow-y-auto rounded-lg border border-slate-200 bg-white p-4 lg:flex-1 ${
                mobileDetailOpen ? "flex flex-col" : "hidden"
              } lg:flex`}
            >
              <CandidateDetail
                candidate={selectedCandidate}
                mobileDetailOpen={mobileDetailOpen}
                onBack={() => setMobileDetailOpen(false)}
                onResolve={openResolveModal}
                onReject={(c) => handleQuickCandidateAction(c, "reject")}
              />
            </div>
          </>
        )}

        {/* TAB 2: PROJECTS */}
        {activeTab === "projects" && (
          <>
            <div
              className={`flex w-full flex-col overflow-y-auto rounded-lg border border-slate-200 bg-white p-4 lg:w-1/3 ${
                mobileDetailOpen ? "hidden" : "flex"
              } lg:flex`}
            >
              <ProjectList
                projects={projects}
                statusFilter={statusFilter}
                domainFilter={domainFilter}
                onStatusFilterChange={setStatusFilter}
                onDomainFilterChange={setDomainFilter}
                selectedProjectId={selectedProject?.project_id ?? null}
                onSelect={handleSelectProject}
              />
            </div>

            <div
              className={`w-full overflow-y-auto rounded-lg border border-slate-200 bg-white p-4 lg:flex-1 ${
                mobileDetailOpen ? "flex flex-col" : "hidden"
              } lg:flex`}
            >
              <ProjectDetail
                project={selectedProject}
                mobileDetailOpen={mobileDetailOpen}
                onBack={() => setMobileDetailOpen(false)}
                onEdit={openEditModal}
              />
            </div>
          </>
        )}

        {/* TAB 3: ARCHIVE */}
        {activeTab === "archive" && (
          <ArchiveList
            archivedCandidates={archivedCandidates}
            onReopen={(c) => handleQuickCandidateAction(c, "reopen_rejected")}
          />
        )}
      </div>

      {/* CREATE & EDIT & RESOLVE MODAL */}
      {(showCreateModal || showEditModal || showResolveModal) && (
        <ProjectFormModal
          showCreateModal={showCreateModal}
          showEditModal={showEditModal}
          showResolveModal={showResolveModal}
          selectedCandidateDisplayName={selectedCandidate?.display_name}
          resolveMode={resolveMode}
          onResolveModeChange={setResolveMode}
          targetProjectId={targetProjectId}
          onTargetProjectIdChange={setTargetProjectId}
          formDisplayName={formDisplayName}
          onFormDisplayNameChange={setFormDisplayName}
          formDomain={formDomain}
          onFormDomainChange={setFormDomain}
          formStatus={formStatus}
          onFormStatusChange={setFormStatus}
          formGoal={formGoal}
          onFormGoalChange={setFormGoal}
          formDescription={formDescription}
          onFormDescriptionChange={setFormDescription}
          formKeywordsText={formKeywordsText}
          onFormKeywordsTextChange={setFormKeywordsText}
          formStartDate={formStartDate}
          onFormStartDateChange={setFormStartDate}
          formTargetDate={formTargetDate}
          onFormTargetDateChange={setFormTargetDate}
          formCompletedDate={formCompletedDate}
          onFormCompletedDateChange={setFormCompletedDate}
          formProjectPath={formProjectPath}
          onFormProjectPathChange={setFormProjectPath}
          formReferenceUrl={formReferenceUrl}
          onFormReferenceUrlChange={setFormReferenceUrl}
          projects={projects}
          loading={loading}
          onCancel={closeModals}
          onSubmit={handleModalSubmit}
        />
      )}
      </div>
    </div>
  );
}
