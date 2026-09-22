import { useMemo, useState } from "react";
import { isReferencePath, type ReferenceGroup } from "./graphModel";

export interface ReferencePickerProps {
  groups: ReferenceGroup[];
  /** Current reference path (without the surrounding ``$ref`` wrapper). */
  value: string;
  onChange: (path: string) => void;
  /** Test id / datalist prefix; must be unique per editor instance. */
  idPrefix: string;
  placeholder?: string;
  allowEmpty?: boolean;
  /** Start with the candidate list expanded. */
  defaultOpen?: boolean;
}

/**
 * Type-aware selector for typed references.
 *
 * The free-text input keeps manual entry working; the grouped list below it
 * guides selection and shows each candidate's declared type.
 */
export default function ReferencePicker({
  groups,
  value,
  onChange,
  idPrefix,
  placeholder,
  allowEmpty = true,
  defaultOpen = false,
}: ReferencePickerProps) {
  const [filter, setFilter] = useState("");
  const [open, setOpen] = useState(defaultOpen);
  const invalid = value.trim() !== "" && !isReferencePath(value);

  const copyPath = () => {
    void navigator.clipboard?.writeText(value).catch(() => undefined);
  };

  const filtered = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    return groups
      .map((group) => ({
        label: group.label,
        fields: needle
          ? group.fields.filter((field) =>
              field.path.toLowerCase().includes(needle),
            )
          : group.fields,
      }))
      .filter((group) => group.fields.length > 0);
  }, [groups, filter]);

  return (
    <div className="space-y-1">
      <div className="flex gap-1">
        <input
          data-testid={`${idPrefix}-ref-value`}
          aria-invalid={invalid}
          className={`w-full rounded border px-1 py-0.5 font-mono text-[11px] ${
            invalid ? "border-amber-400" : "border-slate-300"
          }`}
          value={value}
          placeholder={placeholder ?? "nodes.<id>.output.<field>"}
          onChange={(event) => onChange(event.target.value)}
        />
        {value && (
          <button
            type="button"
            className="cursor-pointer whitespace-nowrap rounded border border-slate-300 px-1 text-[11px] text-slate-600"
            onClick={copyPath}
          >
            コピー
          </button>
        )}
        {allowEmpty && value && (
          <button
            type="button"
            className="cursor-pointer whitespace-nowrap rounded border border-slate-300 px-1 text-[11px] text-slate-600"
            onClick={() => onChange("")}
          >
            クリア
          </button>
        )}
      </div>
      {invalid && (
        <p
          data-testid={`${idPrefix}-ref-warning`}
          className="text-[10px] text-amber-700"
        >
          参照形式ではありません（例: nodes.&lt;id&gt;.output.field）
        </p>
      )}
      <button
        type="button"
        data-testid={`${idPrefix}-ref-toggle`}
        className="cursor-pointer rounded border border-slate-200 px-1 text-[10px] text-slate-600"
        onClick={() => setOpen((current) => !current)}
      >
        {open ? "候補を閉じる" : "候補から選ぶ"}
      </button>
      {open && (
        <>
          <input
            data-testid={`${idPrefix}-ref-filter`}
            className="w-full rounded border border-slate-200 px-1 py-0.5 text-[11px]"
            value={filter}
            placeholder="参照を検索…"
            onChange={(event) => setFilter(event.target.value)}
          />
          <div
            data-testid={`${idPrefix}-ref-list`}
            className="max-h-44 overflow-auto rounded border border-slate-200 bg-white"
          >
            {filtered.length === 0 ? (
              <p className="px-2 py-1 text-[11px] text-slate-500">
                参照候補がありません
              </p>
            ) : (
              filtered.map((group, index) => (
                <div key={`${group.label}-${index}`}>
                  <div className="sticky top-0 bg-slate-100 px-2 py-0.5 text-[10px] font-semibold text-slate-600">
                    {group.label}
                  </div>
                  {group.fields.map((field) => (
                    <button
                      key={field.path}
                      type="button"
                      title={field.description}
                      onClick={() => onChange(field.path)}
                      className={`flex w-full items-center justify-between gap-2 px-2 py-1 text-left font-mono text-[11px] hover:bg-slate-50 ${
                        field.path === value ? "bg-blue-50" : ""
                      }`}
                    >
                      <span className="truncate">{field.path}</span>
                      {field.type && (
                        <span className="shrink-0 rounded bg-slate-100 px-1 text-[10px] text-slate-500">
                          {field.type}
                        </span>
                      )}
                    </button>
                  ))}
                </div>
              ))
            )}
          </div>
        </>
      )}
    </div>
  );
}
