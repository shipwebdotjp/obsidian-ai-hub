import { useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import Sidebar from "./components/Sidebar";
import TokenPrompt from "./components/TokenPrompt";
import MemoryPage from "./features/memories/MemoryPage";
import ResearchPage from "./features/research/ResearchPage";
import VaultSearchPage from "./features/vault-search/VaultSearchPage";
import SummaryDashboardPage from "./features/summary-dashboard/SummaryDashboardPage";
import PeoplePage from "./features/people/PeoplePage";
import ProjectsPage from "./features/projects/ProjectsPage";
import TaskPage from "./features/tasks/TaskPage";
import { health, ApiError } from "./api/client";
import { ROUTES } from "./constants/routes";

export default function App() {
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [needsToken, setNeedsToken] = useState(false);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [navOpen, setNavOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    health()
      .then((res) => {
        if (cancelled) return;
        setNeedsToken(Boolean(res.auth_required));
        setAuthed(!res.auth_required);
      })
      .catch((e) => {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 401) {
          setNeedsToken(true);
          setAuthed(false);
        } else {
          setAuthed(false);
          setHealthError(e instanceof ApiError ? e.message : "サーバーとの接続に失敗しました");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!navOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setNavOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navOpen]);

  if (authed === null) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-slate-500">
        起動中…
      </div>
    );
  }

  if (healthError) {
    return (
      <div className="flex h-full items-center justify-center bg-slate-50 p-6">
        <div className="max-w-md space-y-3 rounded-2xl bg-white p-6 text-center shadow">
          <h1 className="text-lg font-semibold text-red-600">接続エラー</h1>
          <p className="text-sm text-slate-600">{healthError}</p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="rounded bg-slate-900 px-4 py-2 text-sm text-white"
          >
            再読み込み
          </button>
        </div>
      </div>
    );
  }

  if (needsToken && !authed) {
    return <TokenPrompt onAuthenticated={() => setAuthed(true)} />;
  }

  return (
    <div className="flex h-full flex-col lg:flex-row">
      <div className="flex shrink-0 items-center gap-2 border-b border-slate-200 bg-white p-3 lg:hidden">
        <button
          type="button"
          onClick={() => setNavOpen(true)}
          aria-label="メニューを開く"
          aria-expanded={navOpen}
          aria-controls="primary-nav"
          className="inline-flex h-9 w-9 items-center justify-center rounded hover:bg-slate-100"
        >
          <span className="sr-only">メニュー</span>
          <span aria-hidden="true" className="flex w-5 flex-col gap-1">
            <span className="block h-0.5 w-5 bg-slate-700" />
            <span className="block h-0.5 w-5 bg-slate-700" />
            <span className="block h-0.5 w-5 bg-slate-700" />
          </span>
        </button>
        <h1 className="text-sm font-semibold">obsidian-ai-hub</h1>
      </div>

      <Sidebar
        id="primary-nav"
        open={navOpen}
        onClose={() => setNavOpen(false)}
      />

      {navOpen && (
        <button
          type="button"
          aria-label="メニューを閉じる"
          onClick={() => setNavOpen(false)}
          className="fixed inset-0 z-40 bg-slate-900/40 lg:hidden"
        />
      )}

      <main className="min-h-0 min-w-0 flex-1 overflow-hidden">
        <Routes>
          <Route path="/" element={<Navigate to={ROUTES.MEMORIES} replace />} />
          <Route path={ROUTES.MEMORIES} element={<MemoryPage />} />
          <Route path={ROUTES.RESEARCH} element={<ResearchPage />} />
          <Route path={ROUTES.VAULT_SEARCH} element={<VaultSearchPage />} />
          <Route path={ROUTES.SUMMARY_DASHBOARD} element={<SummaryDashboardPage />} />
          <Route path={ROUTES.PEOPLE} element={<PeoplePage />} />
          <Route path={ROUTES.PROJECTS} element={<ProjectsPage />} />
          <Route path={ROUTES.TASKS} element={<TaskPage />} />
          <Route path="*" element={<Navigate to={ROUTES.MEMORIES} replace />} />
        </Routes>
      </main>
    </div>
  );
}
