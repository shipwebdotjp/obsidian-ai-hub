import React, { useEffect, useState } from "react";

export type DatePrecision = "day" | "month" | "year";

/** Detect date precision of a normalized partial date string (YYYY / YYYY-MM / YYYY-MM-DD). */
export function detectDatePrecision(val: string): DatePrecision {
  if (/^\d{4}$/.test(val.trim())) return "year";
  if (/^\d{4}-\d{2}$/.test(val.trim())) return "month";
  return "day";
}

/** Format a normalized partial date (YYYY / YYYY-MM / YYYY-MM-DD) in Japanese. Returns "" for invalid values. */
export function formatJapaneseDate(value: string | null | undefined): string {
  if (!value) return "";
  const v = value.trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(v)) {
    const [y, m, d] = v.split("-").map(Number);
    const date = new Date(y, m - 1, d);
    if (date.getFullYear() === y && date.getMonth() === m - 1 && date.getDate() === d) {
      return `${y}年${m}月${d}日`;
    }
    return "";
  }
  if (/^\d{4}-\d{2}$/.test(v)) {
    const [y, m] = v.split("-").map(Number);
    if (m >= 1 && m <= 12) {
      return `${y}年${m}月`;
    }
    return "";
  }
  if (/^\d{4}$/.test(v)) {
    const y = Number(v);
    if (y >= 1000 && y <= 9999) {
      return `${v}年`;
    }
    return "";
  }
  return "";
}

export interface PartialDateBounds {
  min: string | null;
  max: string | null;
}

/** Return YYYY-MM-DD bounds for a normalized partial date string. Returns nulls for empty/invalid values. */
export function getPartialDateBounds(value: string | null | undefined): PartialDateBounds {
  if (!value) return { min: null, max: null };
  const v = value.trim();
  let m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(v);
  if (m) {
    const y = Number(m[1]);
    const mo = Number(m[2]);
    const d = Number(m[3]);
    const date = new Date(y, mo - 1, d);
    if (date.getFullYear() === y && date.getMonth() === mo - 1 && date.getDate() === d) {
      return { min: v, max: v };
    }
    return { min: null, max: null };
  }
  m = /^(\d{4})-(\d{2})$/.exec(v);
  if (m) {
    const y = Number(m[1]);
    const mo = Number(m[2]);
    if (mo < 1 || mo > 12) return { min: null, max: null };
    const lastDay = new Date(y, mo, 0).getDate();
    const mm = String(mo).padStart(2, "0");
    return { min: `${y}-${mm}-01`, max: `${y}-${mm}-${String(lastDay).padStart(2, "0")}` };
  }
  m = /^(\d{4})$/.exec(v);
  if (m) {
    const y = Number(m[1]);
    if (y < 1000 || y > 9999) return { min: null, max: null };
    return { min: `${m[1]}-01-01`, max: `${m[1]}-12-31` };
  }
  return { min: null, max: null };
}

interface DatePrecisionInputProps {
  value: string;
  onChange: (val: string) => void;
  labelPrefix: string;
  required?: boolean;
}

export default function DatePrecisionInput({ value, onChange, labelPrefix, required = false }: DatePrecisionInputProps) {
  const [precision, setPrecision] = useState<DatePrecision>(() => detectDatePrecision(value));

  // Sync the picker when the parent replaces the value (e.g. editing a
  // different relation). Empty values keep the current picker so clearing
  // a month/year input doesn't yank it back to day mode.
  useEffect(() => {
    if (value) {
      setPrecision(detectDatePrecision(value));
    }
  }, [value]);

  const handlePrecisionChange = (newPrec: DatePrecision) => {
    setPrecision(newPrec);
    if (!value) return;
    if (newPrec === "year") {
      if (value.length >= 4 && /^\d{4}/.test(value)) {
        onChange(value.slice(0, 4));
      } else {
        onChange("");
      }
    } else if (newPrec === "month") {
      if (value.length >= 7 && /^\d{4}-\d{2}/.test(value)) {
        onChange(value.slice(0, 7));
      } else {
        onChange("");
      }
    } else if (newPrec === "day") {
      if (/^\d{4}-\d{2}-\d{2}$/.test(value.trim())) {
        onChange(value.trim());
      } else {
        onChange("");
      }
    }
  };

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2 mb-1">
        <span className="text-[11px] font-semibold text-slate-600">精度:</span>
        {(["day", "month", "year"] as const).map((p) => (
          <label key={p} className="inline-flex items-center gap-1 text-[11px] text-slate-700 cursor-pointer">
            <input
              type="radio"
              name={`prec-${labelPrefix}`}
              checked={precision === p}
              onChange={() => handlePrecisionChange(p)}
              className="text-slate-800 focus:ring-slate-800 cursor-pointer"
            />
            {({ day: "日", month: "月", year: "年" } as const)[p]}
          </label>
        ))}
      </div>
      {precision === "day" && (
        <input
          aria-label={`${labelPrefix} 日`}
          type="date"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full rounded border border-slate-300 p-2 text-xs font-mono focus:ring-2 focus:ring-slate-800 focus:outline-none"
          required={required}
        />
      )}
      {precision === "month" && (
        <input
          aria-label={`${labelPrefix} 月`}
          type="month"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full rounded border border-slate-300 p-2 text-xs font-mono focus:ring-2 focus:ring-slate-800 focus:outline-none"
          required={required}
        />
      )}
      {precision === "year" && (
        <input
          aria-label={`${labelPrefix} 年`}
          type="number"
          min="1000"
          max="9999"
          placeholder="YYYY"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full rounded border border-slate-300 p-2 text-xs font-mono focus:ring-2 focus:ring-slate-800 focus:outline-none"
          required={required}
        />
      )}
    </div>
  );
}
