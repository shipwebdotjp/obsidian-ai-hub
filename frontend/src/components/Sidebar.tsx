import { NavLink } from "react-router-dom";
import { ROUTES } from "../constants/routes";

interface SidebarProps {
  open: boolean;
  onClose: () => void;
  id?: string;
}

export default function Sidebar({ open, onClose, id }: SidebarProps) {
  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `block rounded px-3 py-2 text-sm ${
      isActive ? "bg-slate-900 text-white" : "text-slate-700 hover:bg-slate-200"
    }`;
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
      </nav>
    </aside>
  );
}
