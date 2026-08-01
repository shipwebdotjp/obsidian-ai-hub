import type { Project } from "./types";

export interface ProjectListProps {
  projects: Project[];
  statusFilter: string;
  domainFilter: string;
  onStatusFilterChange: (value: string) => void;
  onDomainFilterChange: (value: string) => void;
  selectedProjectId: number | null;
  onSelect: (p: Project) => void;
}

export default function ProjectList({ projects, statusFilter, domainFilter, onStatusFilterChange, onDomainFilterChange, selectedProjectId, onSelect }: ProjectListProps) {
  return (
    <>
      <h2 className="mb-3 text-sm font-semibold">正式プロジェクト一覧</h2>

      {/* Filters */}
        <div className="grid grid-cols-1 gap-2 mb-3 sm:grid-cols-2">
          <div>
            <label className="block text-[10px] font-bold text-slate-500 mb-1">状態</label>
            <select
              value={statusFilter}
              onChange={(e) => onStatusFilterChange(e.target.value)}
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
            onChange={(e) => onDomainFilterChange(e.target.value)}
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
              onClick={() => onSelect(p)}
              className={`w-full text-left p-2.5 rounded-lg border text-xs transition-all ${
                selectedProjectId === p.project_id
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
    </>
  );
}
