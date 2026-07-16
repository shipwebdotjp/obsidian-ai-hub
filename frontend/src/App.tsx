import { useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import Sidebar from "./components/Sidebar";
import TokenPrompt from "./components/TokenPrompt";
import MemoryPage from "./features/memories/MemoryPage";
import ResearchPage from "./features/research/ResearchPage";
import VaultSearchPage from "./features/vault-search/VaultSearchPage";
import { health, ApiError } from "./api/client";
import { ROUTES } from "./constants/routes";

export default function App() {
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [needsToken, setNeedsToken] = useState(false);
  const [healthError, setHealthError] = useState<string | null>(null);

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
    <div className="flex h-full">
      <Sidebar />
      <main className="flex-1 overflow-hidden">
        <Routes>
          <Route path="/" element={<Navigate to={ROUTES.MEMORIES} replace />} />
          <Route path={ROUTES.MEMORIES} element={<MemoryPage />} />
          <Route path={ROUTES.RESEARCH} element={<ResearchPage />} />
          <Route path={ROUTES.VAULT_SEARCH} element={<VaultSearchPage />} />
          <Route path="*" element={<Navigate to={ROUTES.MEMORIES} replace />} />
        </Routes>
      </main>
    </div>
  );
}
