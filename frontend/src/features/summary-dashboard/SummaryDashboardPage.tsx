import { useEffect, useState, useCallback, useRef } from "react";
import {
  ApiError,
  getDashboardHome,
  getDashboardBrowse,
  getDashboardSummary,
  getDashboardDayDetails,
  getDashboardStats,
  getEditOptions,
  updateSummary,
  deleteSummary,
  generateSummary,
  listPeople,
} from "../../api/client";
import type {
  DashboardHomeResponse,
  DashboardBrowseResponse,
  DashboardDayDetailsResponse,
  DashboardStatsResponse,
  SummaryDetail,
  EditOptionsResponse,
  SummaryUpdatePayload,
  Person,
  MissingSummaryTarget,
} from "../../api/types";
import { HomeTab } from "./HomeTab";
import { BrowseTab } from "./BrowseTab";
import { StatsTab } from "./StatsTab";

export default function SummaryDashboardPage() {
  const [activeTab, setActiveSubTab] = useState<"home" | "browse" | "stats">("home");

  // --- Home Tab State ---
  const [homeData, setHomeData] = useState<DashboardHomeResponse | null>(null);
  const [homeLoading, setHomeLoading] = useState(false);
  const [homeError, setHomeError] = useState<string | null>(null);

  // --- Browse Tab State ---
  const [browseYear, setBrowseYear] = useState<string>(() => String(new Date().getFullYear()));
  const [browseMonth, setBrowseMonth] = useState<string>(() => {
    const d = new Date();
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    return `${y}-${m}`;
  });
  const [browseData, setBrowseData] = useState<DashboardBrowseResponse | null>(null);
  const [browseLoading, setBrowseLoading] = useState(false);
  const [browseError, setBrowseError] = useState<string | null>(null);

  // Detail panel overlay/pane state
  const [selectedSummary, setSelectedSummary] = useState<SummaryDetail | null>(null);
  const [selectedDay, setSelectedDay] = useState<DashboardDayDetailsResponse | null>(null);
  const [selectedMissingTarget, setSelectedMissingTarget] = useState<MissingSummaryTarget | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [mobileDetailOpen, setMobileDetailOpen] = useState(false);

  // Edit/Delete state
  const [isEditing, setIsEditing] = useState(false);
  const [editForm, setEditForm] = useState<SummaryUpdatePayload>({});
  const [editSaving, setEditSaving] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [showRegenerateConfirm, setShowRegenerateConfirm] = useState(false);
  const [generationSaving, setGenerationSaving] = useState(false);
  const [generationError, setGenerationError] = useState<string | null>(null);
  const [allPeople, setAllPeople] = useState<Person[]>([]);
  const [editOptions, setEditOptions] = useState<EditOptionsResponse | null>(null);

  // --- Stats Tab State ---
  const [statsPreset, setStatsPreset] = useState<"year" | "30" | "90" | "custom">("30");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [statsData, setStatsData] = useState<DashboardStatsResponse | null>(null);
  const [statsLoading, setStatsLoading] = useState(false);
  const [statsError, setStatsError] = useState<string | null>(null);

  const [selectedTopics, setSelectedTopics] = useState<string[]>([]);
  const [selectedKeywords, setSelectedKeywords] = useState<string[]>([]);

  // Generation counter references to prevent race conditions on fast tab/selection switching
  const homeRequestRef = useRef(0);
  const browseRequestRef = useRef(0);
  const statsRequestRef = useRef(0);
  const detailRequestRef = useRef(0);
  const skipNextBrowseLoadRef = useRef(false);

  // --- Helper Date Calculations ---
  const getTodayISOString = () => {
    const d = new Date();
    const Y = d.getFullYear();
    const M = String(d.getMonth() + 1).padStart(2, "0");
    const D = String(d.getDate()).padStart(2, "0");
    return `${Y}-${M}-${D}`;
  };

  const getSubtractedDateISOString = (days: number) => {
    const d = new Date();
    d.setDate(d.getDate() - days);
    const Y = d.getFullYear();
    const M = String(d.getMonth() + 1).padStart(2, "0");
    const D = String(d.getDate()).padStart(2, "0");
    return `${Y}-${M}-${D}`;
  };

  // --- API Loaders ---
  const loadHome = useCallback(() => {
    const reqId = ++homeRequestRef.current;
    setHomeLoading(true);
    setHomeError(null);
    getDashboardHome()
      .then((data) => {
        if (reqId !== homeRequestRef.current) return;
        setHomeData(data);
      })
      .catch((e) => {
        if (reqId !== homeRequestRef.current) return;
        setHomeError(e instanceof ApiError ? e.message : "ホームデータの取得に失敗しました");
      })
      .finally(() => {
        if (reqId === homeRequestRef.current) setHomeLoading(false);
      });
  }, []);

  const loadBrowse = useCallback((y?: string, m?: string) => {
    const reqId = ++browseRequestRef.current;
    setBrowseLoading(true);
    setBrowseError(null);
    getDashboardBrowse({ year: y || undefined, month: m || undefined })
      .then((data) => {
        if (reqId !== browseRequestRef.current) return;
        setBrowseData(data);
        if (!y && !m) {
          setBrowseYear(data.selected_year);
          setBrowseMonth(data.selected_month || "");
        }
      })
      .catch((e) => {
        if (reqId !== browseRequestRef.current) return;
        setBrowseError(e instanceof ApiError ? e.message : "一覧データの取得に失敗しました");
      })
      .finally(() => {
        if (reqId === browseRequestRef.current) setBrowseLoading(false);
      });
  }, []);

  const loadStats = useCallback((start: string, end: string) => {
    const reqId = ++statsRequestRef.current;
    setStatsLoading(true);
    setStatsError(null);
    getDashboardStats({ start_date: start, end_date: end })
      .then((data) => {
        if (reqId !== statsRequestRef.current) return;
        setStatsData(data);
        setSelectedTopics(data.candidate_topics.slice(0, 5));
        setSelectedKeywords(data.candidate_keywords.slice(0, 5));
      })
      .catch((e) => {
        if (reqId !== statsRequestRef.current) return;
        setStatsError(e instanceof ApiError ? e.message : "統計データの取得に失敗しました");
      })
      .finally(() => {
        if (reqId === statsRequestRef.current) setStatsLoading(false);
      });
  }, []);

  // --- Detail Loader ---
  const showSummaryDetail = (summaryId: string) => {
    const reqId = ++detailRequestRef.current;
    setDetailLoading(true);
    setDetailError(null);
    setSelectedSummary(null);
    setSelectedDay(null); // Ensure BOTH are not populated at the same time
    setSelectedMissingTarget(null);
    getDashboardSummary(summaryId)
      .then((res) => {
        if (reqId !== detailRequestRef.current) return;
        setSelectedSummary(res);
        setSelectedDay(null);
      })
      .catch((e) => {
        if (reqId !== detailRequestRef.current) return;
        setDetailError(e instanceof ApiError ? e.message : "詳細の取得に失敗しました");
      })
      .finally(() => {
        if (reqId === detailRequestRef.current) setDetailLoading(false);
      });
  };

  const showDayDetail = (targetDate: string) => {
    const reqId = ++detailRequestRef.current;
    setDetailLoading(true);
    setDetailError(null);
    setSelectedSummary(null);
    setSelectedDay(null); // Ensure BOTH are not populated at the same time
    setSelectedMissingTarget(null);
    getDashboardDayDetails(targetDate)
      .then((res) => {
        if (reqId !== detailRequestRef.current) return;
        setSelectedDay(res);
        setSelectedSummary(null);
      })
      .catch((e) => {
        if (reqId !== detailRequestRef.current) return;
        setDetailError(e instanceof ApiError ? e.message : "日別詳細の取得に失敗しました");
      })
      .finally(() => {
        if (reqId === detailRequestRef.current) setDetailLoading(false);
      });
  };

  const openMissingTarget = (target: MissingSummaryTarget) => {
    setSelectedSummary(null);
    setSelectedDay(null);
    setSelectedMissingTarget(target);
    setDetailError(null);
    setGenerationError(null);
  };

  const generateSelectedSummary = useCallback(async () => {
    const target = selectedMissingTarget ?? (selectedSummary ? {
      period_type: selectedSummary.period_type,
      period_key: selectedSummary.period_key,
      period_start: selectedSummary.period_start ?? selectedSummary.period_key,
      period_end: selectedSummary.period_end ?? selectedSummary.period_key,
    } : null);
    if (!target) return;
    setGenerationSaving(true);
    setGenerationError(null);
    try {
      const result = await generateSummary(
        target.period_type === "month"
          ? { period_type: "month", target_month: target.period_key }
          : { period_type: target.period_type, target_date: target.period_start },
      );
      setSelectedSummary(result);
      setSelectedMissingTarget(null);
      setSelectedDay(null);
      setShowRegenerateConfirm(false);
      loadHome();
      loadBrowse(browseYear, browseMonth);
    } catch (e) {
      setGenerationError(e instanceof ApiError ? e.message : "サマリの生成に失敗しました。再試行してください。");
      setShowRegenerateConfirm(false);
    } finally {
      setGenerationSaving(false);
    }
  }, [selectedMissingTarget, selectedSummary, loadHome, loadBrowse, browseYear, browseMonth]);

  // --- Edit handlers ---
  const startEditing = useCallback(async () => {
    if (!selectedSummary) return;
    setIsEditing(true);
    setEditError(null);
    setEditForm({
      summary: selectedSummary.summary ?? "",
      keywords: [...selectedSummary.keywords],
      mood: selectedSummary.mood ?? null,
      sleep_raw: selectedSummary.sleep_raw ?? null,
      items: selectedSummary.items.map((it) => ({
        kind: it.kind,
        body: it.body,
        display_order: it.display_order,
      })),
      topics: [...selectedSummary.topics],
      people: selectedSummary.people
        .filter((p) => p.resolution_status === "resolved" && p.person_id)
        .map((p) => ({ person_id: p.person_id!, note: p.note })),
      project_notes: (selectedSummary.project_notes ?? []).map((pn) => ({
        project_id: pn.project_id,
        note: pn.note,
      })),
    });
    // Load edit options and people in parallel
    try {
      const [opts, people] = await Promise.all([getEditOptions(), listPeople()]);
      setEditOptions(opts);
      setAllPeople(people);
    } catch {
      setEditError("編集オプションの読み込みに失敗しました");
    }
  }, [selectedSummary]);

  const cancelEditing = useCallback(() => {
    setIsEditing(false);
    setEditForm({});
    setEditError(null);
  }, []);

  const saveEditing = useCallback(async () => {
    if (!selectedSummary) return;
    setEditSaving(true);
    setEditError(null);
    try {
      const updated = await updateSummary(selectedSummary.summary_id, editForm);
      setSelectedSummary(updated);
      setIsEditing(false);
      setEditForm({});
      // Refresh other data
      loadHome();
      loadBrowse(browseYear, browseMonth);
    } catch (e) {
      setEditError(e instanceof ApiError ? e.message : "保存に失敗しました");
    } finally {
      setEditSaving(false);
    }
  }, [selectedSummary, editForm, loadHome, loadBrowse, browseYear, browseMonth]);

  // --- Delete handlers ---
  const confirmDelete = useCallback(async () => {
    if (!selectedSummary) return;
    try {
      await deleteSummary(selectedSummary.summary_id);
      setSelectedSummary(null);
      setIsEditing(false);
      setShowDeleteConfirm(false);
      // Refresh data
      loadHome();
      loadBrowse(browseYear, browseMonth);
    } catch (e) {
      setEditError(e instanceof ApiError ? e.message : "削除に失敗しました");
      setShowDeleteConfirm(false);
    }
  }, [selectedSummary, loadHome, loadBrowse, browseYear, browseMonth]);

  const goToBrowseForSummary = (summary: SummaryDetail): void => {
    let year: string;
    let monthStr: string;
    if (summary.period_type === "month") {
      year = summary.period_key.split("-")[0] ?? String(new Date().getFullYear());
      monthStr = summary.period_key;
    } else {
      const start =
        summary.period_start ??
        (summary.period_key.match(/^\d{4}-\d{2}-\d{2}$/) ? summary.period_key : null);
      if (start) {
        year = start.slice(0, 4);
        monthStr = start.slice(0, 7);
      } else {
        const now = new Date();
        year = String(now.getFullYear());
        monthStr = `${year}-${String(now.getMonth() + 1).padStart(2, "0")}`;
      }
    }
    setBrowseYear(year);
    setBrowseMonth(monthStr);
    skipNextBrowseLoadRef.current = true;
    loadBrowse(year, monthStr);
    showSummaryDetail(summary.summary_id);
    setActiveSubTab("browse");
  };

  // --- Effects ---
  useEffect(() => {
    if (activeTab === "home") {
      loadHome();
    } else if (activeTab === "browse") {
      if (skipNextBrowseLoadRef.current) {
        skipNextBrowseLoadRef.current = false;
        return;
      }
      loadBrowse(browseYear, browseMonth);
    } else if (activeTab === "stats") {
      // Set default dates
      const end = getTodayISOString();
      const start = getSubtractedDateISOString(29); // 30 days including today
      setStartDate(start);
      setEndDate(end);
      setStatsPreset("30");
      loadStats(start, end);
    }
  }, [activeTab, browseYear, browseMonth, loadHome, loadBrowse, loadStats]);

  useEffect(() => {
    if (activeTab !== "browse") {
      setMobileDetailOpen(false);
      return;
    }
    if (selectedSummary || selectedDay || selectedMissingTarget) {
      setMobileDetailOpen(true);
    } else {
      setMobileDetailOpen(false);
    }
  }, [activeTab, selectedSummary, selectedDay]);

  // --- Presets handler ---
  const handlePresetChange = (preset: "year" | "30" | "90" | "custom") => {
    setStatsPreset(preset);
    const end = getTodayISOString();
    let start = "";
    if (preset === "30") {
      start = getSubtractedDateISOString(29);
      setStartDate(start);
      setEndDate(end);
      loadStats(start, end);
    } else if (preset === "90") {
      start = getSubtractedDateISOString(89);
      setStartDate(start);
      setEndDate(end);
      loadStats(start, end);
    } else if (preset === "year") {
      const year = new Date().getFullYear();
      start = `${year}-01-01`;
      setStartDate(start);
      setEndDate(end);
      loadStats(start, end);
    }
  };

  return (
    <div className="flex h-full flex-col bg-slate-50">
      {/* Top Navbar */}
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 bg-white px-4 py-3 sm:px-6">
        <div className="flex flex-wrap items-center gap-3 sm:gap-6">
          <h1 className="text-lg font-bold text-slate-900">サマリダッシュボード</h1>
          <nav className="flex shrink-0 gap-1 rounded-lg bg-slate-100 p-0.5 whitespace-nowrap">
            <button
              onClick={() => {
                setActiveSubTab("home");
                setSelectedSummary(null);
                setSelectedDay(null);
                setSelectedMissingTarget(null);
              }}
              className={`rounded-md px-3 py-1.5 text-xs font-semibold transition-all ${
                activeTab === "home"
                  ? "bg-white text-slate-900 shadow-sm"
                  : "text-slate-600 hover:text-slate-900"
              } cursor-pointer`}
            >
              ホーム
            </button>
            <button
              onClick={() => {
                setActiveSubTab("browse");
                setSelectedSummary(null);
                setSelectedDay(null);
                setSelectedMissingTarget(null);
              }}
              className={`rounded-md px-3 py-1.5 text-xs font-semibold transition-all ${
                activeTab === "browse"
                  ? "bg-white text-slate-900 shadow-sm"
                  : "text-slate-600 hover:text-slate-900"
              } cursor-pointer`}
            >
              一覧
            </button>
            <button
              onClick={() => {
                setActiveSubTab("stats");
                setSelectedSummary(null);
                setSelectedDay(null);
                setSelectedMissingTarget(null);
              }}
              className={`rounded-md px-3 py-1.5 text-xs font-semibold transition-all ${
                activeTab === "stats"
                  ? "bg-white text-slate-900 shadow-sm"
                  : "text-slate-600 hover:text-slate-900"
              } cursor-pointer`}
            >
              統計
            </button>
          </nav>
        </div>
      </header>

      {/* Main Content Area */}
      <div className="flex-1 overflow-hidden">
        {/* HOME TAB */}
        {activeTab === "home" && (
          <HomeTab data={homeData} loading={homeLoading} error={homeError} onGoToSummary={goToBrowseForSummary} />
        )}

        {/* BROWSE TAB */}
        {activeTab === "browse" && (
          <BrowseTab
            year={browseYear}
            month={browseMonth}
            setYear={setBrowseYear}
            setMonth={setBrowseMonth}
            data={browseData}
            loading={browseLoading}
            error={browseError}
            selectedSummary={selectedSummary}
            selectedDay={selectedDay}
            detailLoading={detailLoading}
            detailError={detailError}
            mobileDetailOpen={mobileDetailOpen}
            setMobileDetailOpen={setMobileDetailOpen}
            onOpenSummary={showSummaryDetail}
            isEditing={isEditing}
            editForm={editForm}
            setEditForm={setEditForm}
            editOptions={editOptions}
            allPeople={allPeople}
            editSaving={editSaving}
            editError={editError}
            onSave={saveEditing}
            onCancel={cancelEditing}
            onStartEdit={startEditing}
            onRequestDelete={() => setShowDeleteConfirm(true)}
            onShowDayDetail={showDayDetail}
            selectedMissingTarget={selectedMissingTarget}
            onOpenMissingTarget={openMissingTarget}
            generationSaving={generationSaving}
            generationError={generationError}
            onGenerate={generateSelectedSummary}
            onRequestRegenerate={() => setShowRegenerateConfirm(true)}
          />
        )}

        {/* STATS TAB */}
        {activeTab === "stats" && (
          <StatsTab
            preset={statsPreset}
            setPreset={setStatsPreset}
            startDate={startDate}
            endDate={endDate}
            setStartDate={setStartDate}
            setEndDate={setEndDate}
            data={statsData}
            loading={statsLoading}
            error={statsError}
            selectedTopics={selectedTopics}
            setSelectedTopics={setSelectedTopics}
            selectedKeywords={selectedKeywords}
            setSelectedKeywords={setSelectedKeywords}
            onPresetChange={handlePresetChange}
            onApplyCustom={loadStats}
          />
        )}
      </div>

      {/* Delete Confirmation Modal */}
      {showDeleteConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="rounded-xl bg-white p-6 shadow-xl max-w-sm w-full space-y-4">
            <h3 className="text-sm font-bold text-slate-900">サマリの削除</h3>
            <p className="text-xs text-slate-600">この操作は取り消せません。本当に削除しますか？</p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setShowDeleteConfirm(false)}
                className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-50 cursor-pointer"
              >
                やめる
              </button>
              <button
                onClick={confirmDelete}
                className="rounded-md bg-red-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-red-700 cursor-pointer"
              >
                削除する
              </button>
            </div>
          </div>
        </div>
      )}

      {showRegenerateConfirm && selectedSummary && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="rounded-xl bg-white p-6 shadow-xl max-w-sm w-full space-y-4">
            <h3 className="text-sm font-bold text-slate-900">サマリを再生成</h3>
            <p className="text-xs text-slate-600">手編集した内容も含め、現在のサマリを新しい生成結果で上書きします。続けますか？</p>
            <div className="flex justify-end gap-2">
              <button onClick={() => setShowRegenerateConfirm(false)} className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-50 cursor-pointer">やめる</button>
              <button onClick={generateSelectedSummary} disabled={generationSaving} className="rounded-md bg-amber-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-amber-700 disabled:opacity-50 cursor-pointer">{generationSaving ? "再生成中…" : "上書きして再生成"}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
