import { useMemo, useState } from "react";
import type { Project } from "../projects/types";
import { loadProjects, useWidgetOptions } from "./widgetData";

export interface ProjectFieldProps {
  value: unknown;
  onChange: (value: unknown) => void;
  testIdPrefix: string;
}

function projectLabel(project: Project): string {
  return `${project.display_name} (#${project.project_id})`;
}

function matches(project: Project, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return `${project.display_name} ${project.normalized_name} ${project.project_id}`
    .toLowerCase()
    .includes(needle);
}

function toNumericId(value: unknown): number | null {
  if (typeof value === "number") return value;
  if (value === "" || value === undefined || value === null) return null;
  const parsed = Number(value);
  return Number.isNaN(parsed) ? null : parsed;
}

/** Searchable single-select combobox over registered Projects. */
export default function ProjectField({
  value,
  onChange,
  testIdPrefix,
}: ProjectFieldProps) {
  const { options: projects, failed } = useWidgetOptions(loadProjects);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);

  const numericValue = toNumericId(value);
  const selected =
    projects.find((project) => project.project_id === numericValue) ?? null;
  const filtered = useMemo(
    () => projects.filter((project) => matches(project, open ? query : "")),
    [projects, query, open],
  );

  const commit = (projectId: number) => {
    onChange(projectId);
    setQuery("");
    setOpen(false);
  };

  return (
    <div className="relative space-y-1">
      <div className="flex w-full items-center rounded border border-slate-300 bg-white text-xs focus-within:border-slate-900">
        <input
          data-testid={`${testIdPrefix}-project-input`}
          role="combobox"
          aria-expanded={open}
          aria-autocomplete="list"
          className="w-full bg-transparent px-2 py-1 focus:outline-none"
          placeholder="-- Project を選択 --"
          value={open ? query : selected ? projectLabel(selected) : ""}
          onFocus={() => {
            setOpen(true);
            setQuery("");
          }}
          onChange={(event) => {
            setQuery(event.target.value);
            setOpen(true);
          }}
          onBlur={() => setOpen(false)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && open && filtered[0]) {
              event.preventDefault();
              commit(filtered[0].project_id);
            } else if (event.key === "Escape") {
              setOpen(false);
            }
          }}
        />
        {selected && (
          <button
            type="button"
            data-testid={`${testIdPrefix}-project-clear`}
            aria-label="選択をクリア"
            className="shrink-0 cursor-pointer px-1.5 text-slate-400 hover:text-slate-700"
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => {
              onChange(undefined);
              setQuery("");
              setOpen(false);
            }}
          >
            ×
          </button>
        )}
      </div>
      {failed && (
        <p className="text-[10px] text-rose-700">
          Project 一覧の取得に失敗しました
        </p>
      )}
      {open && (
        <ul
          data-testid={`${testIdPrefix}-project-list`}
          role="listbox"
          className="absolute z-10 mt-1 max-h-56 w-full overflow-y-auto rounded border border-slate-300 bg-white py-1 shadow-lg"
        >
          {filtered.length === 0 ? (
            <li className="px-2.5 py-2 text-xs text-slate-400">
              一致する Project がありません
            </li>
          ) : (
            filtered.map((project) => (
              <li
                key={project.project_id}
                role="option"
                aria-selected={project.project_id === numericValue}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => commit(project.project_id)}
                className={`cursor-pointer px-2.5 py-1.5 text-xs hover:bg-slate-100 ${
                  project.project_id === numericValue
                    ? "font-semibold text-slate-900"
                    : "text-slate-700"
                }`}
              >
                {projectLabel(project)}
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  );
}
