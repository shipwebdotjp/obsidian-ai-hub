import React, { useEffect, useState } from "react";
import { apiGet, apiPost, apiPatch, ApiError } from "../../api/client";
import { ProjectCandidate } from "../../api/types";

interface Project {
  project_id: number;
  normalized_name: string;
  display_name: string;
  domain: "work" | "personal";
  status: "inquiry" | "active" | "paused" | "completed" | "cancelled";
  goal: string | null;
  description: string | null;
  keywords: string[];
  start_date: string | null;
  target_date: string | null;
  completed_date: string | null;
  project_path: string | null;
  reference_url: string | null;
  created_at: string;
  updated_at: string;
  summary_count: number;
}

interface AssociatedSummary {
  summary_id: string;
  period_type: string;
  period_key: string;
  note?: string | null;
  display_order?: number | null;
}

interface ProjectDetail extends Project {
  summaries: AssociatedSummary[];
}


interface ProjectCandidateDetail extends ProjectCandidate {
  summaries: AssociatedSummary[];
  assigned_summaries_count: number;
}

type Tab = "inbox" | "projects" | "archive";

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
  const [selectedProject, setSelectedProject] = useState<ProjectDetail | null>(null);
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
  const [resolveMode, setResolveMode] = useState<"approve_new" | "link_existing" | "reject">("approve_new");
  const [targetProjectId, setTargetProjectId] = useState<number | "">("");

  // Common Form Fields (used for Create, Edit, and Resolve/Approve)
  const [formDisplayName, setFormDisplayName] = useState("");
  const [formDomain, setFormDomain] = useState<"work" | "personal">("personal");
  const [formStatus, setFormStatus] = useState<"inquiry" | "active" | "paused" | "completed" | "cancelled">("inquiry");
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
      const data = await apiGet<ProjectDetail>(`/api/v1/projects/${p.project_id}`);
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
      const keywords = formKeywordsText
        .split("\n")
        .map((k) => k.trim())
        .filter((k) => k.length > 0);

      const res = await apiPost<ProjectDetail>("/api/v1/projects", {
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
      const keywords = formKeywordsText
        .split("\n")
        .map((k) => k.trim())
        .filter((k) => k.length > 0);

      const res = await apiPatch<ProjectDetail>(`/api/v1/projects/${selectedProject.project_id}`, {
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
      const keywords = formKeywordsText
        .split("\n")
        .map((k) => k.trim())
        .filter((k) => k.length > 0);

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
              <h2 className="mb-3 text-sm font-semibold">新規候補</h2>
              {candidates.length === 0 ? (
                <p className="text-xs text-slate-400">現在、未解決の候補はありません。</p>
              ) : (
                <div className="space-y-2">
                  {candidates.map((c) => (
                    <button
                      key={c.candidate_id}
                      onClick={() => handleSelectCandidate(c)}
                      className={`w-full text-left p-2.5 rounded-lg border text-xs transition-all ${
                        selectedCandidate?.candidate_id === c.candidate_id
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
                  <div className="flex items-start justify-between border-b pb-3">
                    <div>
                      <h2 className="text-base font-bold">{selectedCandidate.display_name}</h2>
                      <p className="text-xs text-slate-400">正規化名: {selectedCandidate.normalized_name} | 領域: {selectedCandidate.domain === "work" ? "仕事" : "個人"}</p>
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={openResolveModal}
                         className="rounded bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700"
                       >
                         処理・解決
                      </button>
                      <button
                        onClick={() => handleQuickCandidateAction(selectedCandidate, "reject")}
                        className="rounded border border-red-200 bg-red-50 px-3 py-1.5 text-xs text-red-700 hover:bg-red-100"
                      >
                        却下
                      </button>
                    </div>
                  </div>

                  <div className="space-y-3 text-xs">
                    {selectedCandidate.goal && (
                      <div>
                        <span className="font-bold block text-slate-600">目的:</span>
                        <div className="bg-slate-50 p-2 rounded mt-1 whitespace-pre-wrap">{selectedCandidate.goal}</div>
                      </div>
                    )}
                    {selectedCandidate.description && (
                      <div>
                        <span className="font-bold block text-slate-600">説明:</span>
                        <div className="bg-slate-50 p-2 rounded mt-1 whitespace-pre-wrap">{selectedCandidate.description}</div>
                      </div>
                    )}
                    {selectedCandidate.keywords && selectedCandidate.keywords.length > 0 && (
                      <div>
                        <span className="font-bold block text-slate-600">キーワード:</span>
                        <div className="flex flex-wrap gap-1 mt-1">
                          {selectedCandidate.keywords.map((k, idx) => (
                            <span key={idx} className="bg-slate-100 text-slate-800 text-[10px] px-2 py-0.5 rounded border">
                              {k}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                      {(selectedCandidate.start_date || selectedCandidate.target_date) && (
                        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                        {selectedCandidate.start_date && (
                          <div>
                            <span className="font-bold text-slate-600">開始日:</span>
                            <span className="ml-1 font-mono">{selectedCandidate.start_date}</span>
                          </div>
                        )}
                        {selectedCandidate.target_date && (
                          <div>
                            <span className="font-bold text-slate-600">目標日:</span>
                            <span className="ml-1 font-mono">{selectedCandidate.target_date}</span>
                          </div>
                        )}
                      </div>
                    )}
                    {selectedCandidate.evidence && (
                      <div className="border-t pt-3">
                        <span className="font-bold block text-slate-600 text-xs">検出根拠・ログ証拠:</span>
                        <p className="mt-1 bg-amber-50/50 border border-amber-100 p-2.5 rounded text-slate-600 italic">
                          &ldquo;{selectedCandidate.evidence}&rdquo;
                        </p>
                      </div>
                    )}
                  </div>

                  <div className="border-t pt-3">
                    <h3 className="text-xs font-bold text-slate-700 mb-2">紐づくサマリ ({selectedCandidate.summaries.length})</h3>
                    {selectedCandidate.summaries.length === 0 ? (
                      <p className="text-xs text-slate-400">紐づいているサマリはありません。</p>
                    ) : (
                      <div className="border border-slate-100 rounded-lg overflow-hidden divide-y divide-slate-100 text-xs">
                        {selectedCandidate.summaries.map((sum) => (
                          <div key={sum.summary_id} className="p-2.5 flex justify-between bg-slate-50/50">
                            <span className="font-semibold text-slate-800">{sum.period_key}</span>
                            <span className="text-slate-400 font-mono text-[10px]">{sum.period_type}</span>
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

        {/* TAB 2: PROJECTS */}
        {activeTab === "projects" && (
          <>
            <div
              className={`flex w-full flex-col overflow-y-auto rounded-lg border border-slate-200 bg-white p-4 lg:w-1/3 ${
                mobileDetailOpen ? "hidden" : "flex"
              } lg:flex`}
            >
              <h2 className="mb-3 text-sm font-semibold">正式プロジェクト一覧</h2>

              {/* Filters */}
                <div className="grid grid-cols-1 gap-2 mb-3 sm:grid-cols-2">
                  <div>
                    <label className="block text-[10px] font-bold text-slate-500 mb-1">状態</label>
                    <select
                      value={statusFilter}
                      onChange={(e) => setStatusFilter(e.target.value)}
                      className="w-full rounded border border-slate-300 bg-white px-2 py-1 text-[11px] focus:outline-none"
                    >
                      <option value="all">すべて</option>
                      <option value="inquiry">inquiry</option>
                      <option value="active">active</option>
                      <option value="paused">paused</option>
                      <option value="completed">completed</option>
                      <option value="cancelled">cancelled</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-[10px] font-bold text-slate-500 mb-1">領域</label>
                  <select
                    value={domainFilter}
                    onChange={(e) => setDomainFilter(e.target.value)}
                    className="w-full rounded border border-slate-300 bg-white px-2 py-1 text-[11px] focus:outline-none"
                  >
                    <option value="all">すべて</option>
                    <option value="work">仕事</option>
                    <option value="personal">個人</option>
                  </select>
                </div>
              </div>

              {projects.length === 0 ? (
                <p className="text-xs text-slate-400">条件に合致するプロジェクトはありません。</p>
              ) : (
                <div className="space-y-2">
                  {projects.map((p) => (
                    <button
                      key={p.project_id}
                      onClick={() => handleSelectProject(p)}
                      className={`w-full text-left p-2.5 rounded-lg border text-xs transition-all ${
                        selectedProject?.project_id === p.project_id
                          ? "border-slate-900 bg-slate-50 font-medium"
                          : "border-slate-200 hover:bg-slate-50"
                      }`}
                    >
                      <div className="flex items-center justify-between font-semibold">
                        <span>{p.display_name}</span>
                        <span className={`text-[9px] px-1.5 py-0.5 rounded-full font-mono ${
                          p.status === "active" ? "bg-green-50 text-green-700" : "bg-slate-100 text-slate-700"
                        }`}>{p.status}</span>
                      </div>
                      <div className="text-[10px] text-slate-400 mt-1.5 flex justify-between">
                        <span>領域: {p.domain === "work" ? "仕事" : "個人"}</span>
                        <span>サマリ: {p.summary_count}件</span>
                      </div>
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
                    プロジェクト詳細
                  </span>
                </div>
              )}
              {selectedProject ? (
                <div className="space-y-4">
                  <div className="flex items-start justify-between border-b pb-3">
                    <div>
                      <h2 className="text-base font-bold">{selectedProject.display_name}</h2>
                      <p className="text-xs text-slate-400">ID: {selectedProject.project_id} | 正規化名: {selectedProject.normalized_name} | 状態: <span className="font-semibold text-slate-700">{selectedProject.status}</span></p>
                    </div>
                    <button
                      onClick={openEditModal}
                       className="rounded bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700"
                     >
                       詳細編集
                    </button>
                  </div>

                  <div className="space-y-3 text-xs">
                    {selectedProject.goal && (
                      <div>
                        <span className="font-bold block text-slate-600">目的:</span>
                        <div className="bg-slate-50 p-2 rounded mt-1 whitespace-pre-wrap">{selectedProject.goal}</div>
                      </div>
                    )}
                    {selectedProject.description && (
                      <div>
                        <span className="font-bold block text-slate-600">説明:</span>
                        <div className="bg-slate-50 p-2 rounded mt-1 whitespace-pre-wrap">{selectedProject.description}</div>
                      </div>
                    )}
                    {selectedProject.keywords && selectedProject.keywords.length > 0 && (
                      <div>
                        <span className="font-bold block text-slate-600">キーワード:</span>
                        <div className="flex flex-wrap gap-1 mt-1">
                          {selectedProject.keywords.map((k, idx) => (
                            <span key={idx} className="bg-slate-100 text-slate-800 text-[10px] px-2 py-0.5 rounded border">
                              {k}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                      <div>
                        <span className="font-bold text-slate-600 block">開始日:</span>
                        <span className="font-mono">{selectedProject.start_date || "-"}</span>
                      </div>
                      <div>
                        <span className="font-bold text-slate-600 block">目標日:</span>
                        <span className="font-mono">{selectedProject.target_date || "-"}</span>
                      </div>
                      <div>
                        <span className="font-bold text-slate-600 block">完了日:</span>
                        <span className="font-mono">{selectedProject.completed_date || "-"}</span>
                      </div>
                    </div>
                    {selectedProject.project_path && (
                      <div>
                        <span className="font-bold text-slate-600 block">ディレクトリパス:</span>
                        <code className="bg-slate-100 px-1.5 py-0.5 rounded font-mono text-[10px]">{selectedProject.project_path}</code>
                      </div>
                    )}
                    {selectedProject.reference_url && (
                      <div>
                        <span className="font-bold text-slate-600 block">参照URL:</span>
                        <a href={selectedProject.reference_url} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">
                          {selectedProject.reference_url}
                        </a>
                      </div>
                    )}
                  </div>

                  <div className="border-t pt-3">
                    <h3 className="text-xs font-bold text-slate-700 mb-2">紐づくサマリ ({selectedProject.summaries.length})</h3>
                    {selectedProject.summaries.length === 0 ? (
                      <p className="text-xs text-slate-400">紐づいているサマリはありません。</p>
                    ) : (
                      <div className="border border-slate-100 rounded-lg overflow-hidden divide-y divide-slate-100 text-xs">
                        {selectedProject.summaries.map((sum) => (
                          <div key={sum.summary_id} className="p-2.5 flex flex-col bg-slate-50/50">
                            <div className="flex justify-between">
                              <span className="font-semibold text-slate-800">{sum.period_key}</span>
                              <span className="text-slate-400 font-mono text-[10px]">{sum.period_type}</span>
                            </div>
                            {sum.note && <span className="text-[10px] text-slate-500 mt-0.5">{sum.note}</span>}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <div className="h-full flex items-center justify-center text-xs text-slate-400">
                  プロジェクトを選択すると詳細が表示されます。
                </div>
              )}
            </div>
          </>
        )}

        {/* TAB 3: ARCHIVE */}
        {activeTab === "archive" && (
          <div className="flex-1 border border-slate-200 bg-white rounded-lg p-5 overflow-y-auto space-y-4">
            <div>
              <h2 className="text-sm font-bold text-slate-900">処理・却下済み候補アーカイブ</h2>
              <p className="text-xs text-slate-500 mt-0.5">処理が完了した（resolved）、または却下された（rejected）プロジェクト候補の履歴です。</p>
            </div>

            {archivedCandidates.length === 0 ? (
              <p className="text-xs text-slate-400">該当する候補はありません。</p>
            ) : (
              <div className="border border-slate-200 rounded-lg overflow-hidden divide-y divide-slate-200 text-xs">
                {archivedCandidates.map((c) => (
                  <div key={c.candidate_id} className="p-3 bg-slate-50/50 flex items-center justify-between gap-4">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-slate-800">{c.display_name}</span>
                        <span className={`text-[9px] px-1.5 py-0.5 rounded-full font-mono ${
                          c.status === "resolved" ? "bg-green-100 text-green-800" : "bg-red-100 text-red-800"
                        }`}>{c.status}</span>
                      </div>
                      <div className="text-[10px] text-slate-400 mt-1 font-mono">
                        正規名: {c.normalized_name} | 作成: {new Date(c.created_at).toLocaleString()}
                      </div>
                      {c.evidence && <div className="text-[10px] text-slate-500 mt-1 italic">根拠: &ldquo;{c.evidence}&rdquo;</div>}
                    </div>
                    {c.status === "rejected" && (
                      <button
                        onClick={() => handleQuickCandidateAction(c, "reopen_rejected")}
                        className="rounded border border-slate-300 bg-white px-2.5 py-1 text-xs text-slate-700 hover:bg-slate-50"
                      >
                        再開
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* CREATE & EDIT & RESOLVE MODAL */}
      {(showCreateModal || showEditModal || showResolveModal) && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-sm p-4">
          <div className="bg-white rounded-xl shadow-xl border border-slate-200 w-full max-w-lg overflow-hidden flex flex-col max-h-[90vh]">
            <div className="p-4 border-b border-slate-100 bg-slate-50 flex items-center justify-between shrink-0">
              <h3 className="text-sm font-bold text-slate-900">
                {showCreateModal && "プロジェクト新規作成"}
                {showEditModal && "プロジェクト詳細編集"}
                {showResolveModal && `候補の処理解決: ${selectedCandidate?.display_name}`}
              </h3>
              <button
                onClick={() => {
                  setShowCreateModal(false);
                  setShowEditModal(false);
                  setShowResolveModal(false);
                }}
                className="text-slate-400 hover:text-slate-600 transition-colors text-xs"
              >
                ✕
              </button>
            </div>

            <div className="p-5 space-y-4 text-xs text-slate-700 overflow-y-auto">
              {showResolveModal && (
                <div className="border-b pb-3 mb-3">
                  <label className="block text-[11px] font-bold text-slate-700 mb-1">解決アクション</label>
                  <div className="flex gap-4">
                    <label className="flex items-center gap-1.5 cursor-pointer">
                      <input
                        type="radio"
                        name="resolveMode"
                        checked={resolveMode === "approve_new"}
                        onChange={() => setResolveMode("approve_new")}
                      />
                      <span>新規正式プロジェクトとして承認</span>
                    </label>
                    <label className="flex items-center gap-1.5 cursor-pointer">
                      <input
                        type="radio"
                        name="resolveMode"
                        checked={resolveMode === "link_existing"}
                        onChange={() => setResolveMode("link_existing")}
                      />
                      <span>既存プロジェクトへ紐付け</span>
                    </label>
                  </div>
                </div>
              )}

              {/* Resolution link_existing selector */}
              {showResolveModal && resolveMode === "link_existing" ? (
                <div>
                  <label className="block text-[11px] font-bold text-slate-700 mb-1">紐付け先プロジェクト</label>
                  <select
                    value={targetProjectId}
                    onChange={(e) => setTargetProjectId(e.target.value ? Number(e.target.value) : "")}
                    className="w-full rounded border border-slate-300 bg-white px-2.5 py-1.5 text-xs focus:border-slate-900 focus:outline-none"
                  >
                    <option value="">-- プロジェクトを選択してください --</option>
                    {projects.map((p) => (
                      <option key={p.project_id} value={p.project_id}>
                        {p.display_name} ({p.status})
                      </option>
                    ))}
                  </select>
                </div>
              ) : (
                /* Attribute input fields (for Create, Edit, or approve_new resolution) */
                <div className="space-y-3">
                  <div>
                    <label className="block text-[11px] font-bold text-slate-700 mb-1">プロジェクト名称 *</label>
                    <input
                      type="text"
                      value={formDisplayName}
                      onChange={(e) => setFormDisplayName(e.target.value)}
                      className="w-full rounded border border-slate-300 bg-white px-2.5 py-1.5 text-xs focus:border-slate-900 focus:outline-none"
                      placeholder="表示名を入力"
                    />
                  </div>

                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <div>
                      <label className="block text-[11px] font-bold text-slate-700 mb-1">領域 (Domain)</label>
                      <select
                        value={formDomain}
                        onChange={(e) => setFormDomain(e.target.value as "work" | "personal")}
                        className="w-full rounded border border-slate-300 bg-white px-2.5 py-1.5 text-xs focus:outline-none"
                      >
                        <option value="personal">個人 (personal)</option>
                        <option value="work">仕事 (work)</option>
                      </select>
                    </div>
                    <div>
                      <label className="block text-[11px] font-bold text-slate-700 mb-1">状態 (Status)</label>
                      <select
                        value={formStatus}
                        onChange={(e) => setFormStatus(e.target.value as any)}
                        className="w-full rounded border border-slate-300 bg-white px-2.5 py-1.5 text-xs focus:outline-none"
                      >
                        <option value="inquiry">検討中 (inquiry)</option>
                        <option value="active">進行中 (active)</option>
                        <option value="paused">保留中 (paused)</option>
                        <option value="completed">完了 (completed)</option>
                        <option value="cancelled">中止 (cancelled)</option>
                      </select>
                    </div>
                  </div>

                  <div>
                    <label className="block text-[11px] font-bold text-slate-700 mb-1">目的 (Goal)</label>
                    <textarea
                      value={formGoal}
                      onChange={(e) => setFormGoal(e.target.value)}
                      rows={2}
                      className="w-full rounded border border-slate-300 bg-white px-2.5 py-1.5 text-xs focus:border-slate-900 focus:outline-none"
                      placeholder="目的を入力"
                    />
                  </div>

                  <div>
                    <label className="block text-[11px] font-bold text-slate-700 mb-1">説明 (Description)</label>
                    <textarea
                      value={formDescription}
                      onChange={(e) => setFormDescription(e.target.value)}
                      rows={2}
                      className="w-full rounded border border-slate-300 bg-white px-2.5 py-1.5 text-xs focus:border-slate-900 focus:outline-none"
                      placeholder="説明を入力"
                    />
                  </div>

                  <div>
                    <label className="block text-[11px] font-bold text-slate-700 mb-1">キーワード (1行に1キーワード)</label>
                    <textarea
                      value={formKeywordsText}
                      onChange={(e) => setFormKeywordsText(e.target.value)}
                      rows={2}
                      className="w-full rounded border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-mono focus:border-slate-900 focus:outline-none"
                      placeholder="キーワードを入力"
                    />
                  </div>

                  <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                    <div>
                      <label className="block text-[11px] font-bold text-slate-700 mb-1">開始日</label>
                      <input
                        type="text"
                        value={formStartDate}
                        onChange={(e) => setFormStartDate(e.target.value)}
                        className="w-full rounded border border-slate-300 bg-white px-2 py-1 text-xs font-mono focus:outline-none"
                        placeholder="YYYY-MM-DD"
                      />
                    </div>
                    <div>
                      <label className="block text-[11px] font-bold text-slate-700 mb-1">目標日</label>
                      <input
                        type="text"
                        value={formTargetDate}
                        onChange={(e) => setFormTargetDate(e.target.value)}
                        className="w-full rounded border border-slate-300 bg-white px-2 py-1 text-xs font-mono focus:outline-none"
                        placeholder="YYYY-MM-DD"
                      />
                    </div>
                    <div>
                      <label className="block text-[11px] font-bold text-slate-700 mb-1">完了日</label>
                      <input
                        type="text"
                        value={formCompletedDate}
                        onChange={(e) => setFormCompletedDate(e.target.value)}
                        className="w-full rounded border border-slate-300 bg-white px-2 py-1 text-xs font-mono focus:outline-none"
                        placeholder="YYYY-MM-DD"
                      />
                    </div>
                  </div>

                  <div>
                    <label className="block text-[11px] font-bold text-slate-700 mb-1">ディレクトリパス</label>
                    <input
                      type="text"
                      value={formProjectPath}
                      onChange={(e) => setFormProjectPath(e.target.value)}
                      className="w-full rounded border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-mono focus:border-slate-900 focus:outline-none"
                      placeholder="/Users/name/projects/my-project"
                    />
                  </div>

                  <div>
                    <label className="block text-[11px] font-bold text-slate-700 mb-1">参照URL</label>
                    <input
                      type="text"
                      value={formReferenceUrl}
                      onChange={(e) => setFormReferenceUrl(e.target.value)}
                      className="w-full rounded border border-slate-300 bg-white px-2.5 py-1.5 text-xs focus:border-slate-900 focus:outline-none"
                      placeholder="https://github.com/..."
                    />
                  </div>
                </div>
              )}
            </div>

            <div className="p-4 border-t border-slate-100 bg-slate-50 flex items-center justify-end gap-2 shrink-0">
              <button
                onClick={() => {
                  setShowCreateModal(false);
                  setShowEditModal(false);
                  setShowResolveModal(false);
                }}
                className="rounded border border-slate-300 bg-white px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
              >
                キャンセル
              </button>
              <button
                onClick={() => {
                  if (showCreateModal) {
                    handleCreateProject();
                  } else if (showEditModal) {
                    handleUpdateProject();
                  } else if (showResolveModal) {
                    handleResolveCandidate();
                  }
                }}
                disabled={
                  loading ||
                  (showCreateModal && !formDisplayName.trim()) ||
                  (showEditModal && !formDisplayName.trim()) ||
                  (showResolveModal && resolveMode === "approve_new" && !formDisplayName.trim()) ||
                  (showResolveModal && resolveMode === "link_existing" && !targetProjectId)
                }
                 className="rounded bg-blue-600 px-4 py-2 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {loading ? "処理中..." : "保存する"}
              </button>
            </div>
          </div>
        </div>
      )}
      </div>
    </div>
  );
}
