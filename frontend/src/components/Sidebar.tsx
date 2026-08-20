import { useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { listHitlRuns } from "../api/client";
import { ROUTES } from "../constants/routes";

interface SidebarProps {
  open: boolean;
  onClose: () => void;
  id?: string;
}

export default function Sidebar({ open, onClose, id }: SidebarProps) {
  const location = useLocation();
  const [pendingCount, setPendingCount] = useState<number | null>(null);
  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `block rounded px-3 py-2 text-sm ${
      isActive ? "bg-slate-900 text-white" : "text-slate-700 hover:bg-slate-200"
    }`;

  useEffect(() => {
    let cancelled = false;
    listHitlRuns({ status: "pending_user", limit: 1 })
      .then((res) => {
        if (!cancelled) setPendingCount(res.total);
      })
      .catch(() => {
        // Keep the current badge value; auth gating happens in App.
      });
    return () => {
      cancelled = true;
    };
  }, [location.pathname]);
  return (
    <aside
      id={id}
      className={`fixed inset-y-0 left-0 z-50 flex w-64 flex-col border-r border-slate-200 bg-white p-4 transition-transform duration-200 ease-in-out lg:static lg:w-56 lg:translate-x-0 ${
        open ? "translate-x-0" : "-translate-x-full"
      }`}
    >
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-base font-semibold">obsidian-ai-hub</h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="メニューを閉じる"
          className="inline-flex h-8 w-8 items-center justify-center rounded text-slate-500 hover:bg-slate-200 lg:hidden"
        >
          ✕
        </button>
      </div>
      <nav className="space-y-1">
        <NavLink to={ROUTES.MEMORIES} className={linkClass} onClick={onClose}>
          メモリ
        </NavLink>
        <NavLink to={ROUTES.RESEARCH} className={linkClass} onClick={onClose}>
          リサーチ
        </NavLink>
        <NavLink to={ROUTES.AGENTS} className={linkClass} onClick={onClose}>
          AIエージェント
        </NavLink>
        <NavLink to={ROUTES.HITL} className={linkClass} onClick={onClose}>
          <span className="flex items-center justify-between">
            <span>確認待ち</span>
            {pendingCount !== null && pendingCount > 0 && (
              <span
                data-testid="hitl-pending-badge"
                className="rounded-full bg-yellow-100 px-2 py-0.5 text-[10px] font-medium text-yellow-800"
              >
                {pendingCount}
              </span>
            )}
          </span>
        </NavLink>
        <NavLink to={ROUTES.VAULT_SEARCH} className={linkClass} onClick={onClose}>
          Vault 検索
        </NavLink>
        <NavLink to={ROUTES.SUMMARY_DASHBOARD} className={linkClass} onClick={onClose}>
          サマリダッシュボード
        </NavLink>
        <NavLink to={ROUTES.PEOPLE} className={linkClass} onClick={onClose}>
          人物管理
        </NavLink>
        <NavLink to={ROUTES.PROJECTS} className={linkClass} onClick={onClose}>
          プロジェクト管理
        </NavLink>
        <NavLink to={ROUTES.TASKS} className={linkClass} onClick={onClose}>
          タスク管理
        </NavLink>
        <NavLink to={ROUTES.EXECUTION_LOGS} className={linkClass} onClick={onClose}>
          実行ログ
        </NavLink>
        <NavLink to={ROUTES.PLANNER} className={linkClass} onClick={onClose}>
          プランナー
        </NavLink>
      </nav>
      <div className="mt-auto border-t border-slate-200 pt-2">
        <NavLink to={ROUTES.SETTINGS} className={linkClass} onClick={onClose}>
          設定
        </NavLink>
      </div>
    </aside>
  );
}
