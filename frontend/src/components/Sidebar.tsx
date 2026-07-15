import { NavLink } from "react-router-dom";
import { ROUTES } from "../constants/routes";

export default function Sidebar() {
  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `block rounded px-3 py-2 text-sm ${
      isActive ? "bg-slate-900 text-white" : "text-slate-700 hover:bg-slate-200"
    }`;
  return (
    <aside className="flex w-56 shrink-0 flex-col border-r border-slate-200 bg-white p-4">
      <h2 className="mb-4 text-base font-semibold">obsidian-ai-hub</h2>
      <nav className="space-y-1">
        <NavLink to={ROUTES.MEMORIES} className={linkClass}>
          メモリ
        </NavLink>
        <NavLink to={ROUTES.RESEARCH} className={linkClass}>
          リサーチ
        </NavLink>
      </nav>
    </aside>
  );
}
