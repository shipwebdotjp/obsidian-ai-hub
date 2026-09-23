import { isReferenceValue, REFERENCE_TIME_REF, type ReferenceGroup } from "./graphModel";
import ReferencePicker from "./ReferencePicker";
import {
  DEFAULT_TIMEZONE,
  WEEKDAYS,
  type ExpressionResult,
  type ExpressionValue,
  type Weekday,
  type WorkflowExpression,
  validateExpressionValue,
} from "./expressionModel";

export interface ExpressionEditorProps {
  value: ExpressionValue;
  onChange: (value: ExpressionValue) => void;
  idPrefix: string;
  referenceGroups?: ReferenceGroup[];
  /** When false, anchors are limited to the Run context (Run input form). */
  allowNodeAnchors?: boolean;
  /** Target field ``format`` (``date`` / ``date-time``) for result checking. */
  expectedFormat?: string;
}

export default function ExpressionEditor({
  value,
  onChange,
  idPrefix,
  referenceGroups = [],
  allowNodeAnchors = true,
  expectedFormat,
}: ExpressionEditorProps) {
  const expr = value.$expr;
  const update = (patch: Partial<WorkflowExpression>) =>
    onChange({ $expr: { ...expr, ...patch } });
  const issues = validateExpressionValue(value, {
    allowNodeAnchors,
    expectedFormat,
  });
  const anchor = expr.anchor ?? "now";
  const anchored = anchor !== "now";
  const anchorRef = isReferenceValue(anchor) ? anchor.$ref : "";

  return (
    <div className="space-y-1 rounded border border-indigo-200 bg-indigo-50/40 p-2 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[10px] text-slate-500">基準</span>
        <select
          data-testid={`${idPrefix}-anchor-kind`}
          className="rounded border border-slate-300 px-1 py-0.5"
          value={anchored ? "ref" : "now"}
          onChange={(event) =>
            update({
              anchor:
                event.target.value === "now"
                  ? "now"
                  : { $ref: REFERENCE_TIME_REF },
            })
          }
        >
          <option value="now">now</option>
          <option value="ref">参照</option>
        </select>
        <span className="text-[10px] text-slate-500">結果</span>
        <select
          data-testid={`${idPrefix}-result`}
          className="rounded border border-slate-300 px-1 py-0.5"
          value={expr.result ?? "date"}
          onChange={(event) =>
            update({ result: event.target.value as ExpressionResult })
          }
        >
          <option value="date">date</option>
          <option value="datetime">datetime</option>
        </select>
      </div>

      {anchored && (
        <ReferencePicker
          idPrefix={`${idPrefix}-anchor`}
          groups={referenceGroups}
          value={anchorRef}
          onChange={(path) => update({ anchor: { $ref: path } })}
        />
      )}

      <div className="flex items-center gap-2">
        <span className="text-[10px] text-slate-500">演算</span>
        <input
          type="text"
          data-testid={`${idPrefix}-math`}
          className="w-full rounded border border-slate-300 px-2 py-0.5 font-mono"
          placeholder="例: /w+6d"
          value={expr.math ?? ""}
          onChange={(event) => update({ math: event.target.value })}
        />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[10px] text-slate-500">TZ</span>
        <input
          type="text"
          data-testid={`${idPrefix}-timezone`}
          className="w-40 rounded border border-slate-300 px-2 py-0.5"
          placeholder={DEFAULT_TIMEZONE}
          value={expr.timezone ?? ""}
          onChange={(event) => update({ timezone: event.target.value })}
        />
        <span className="text-[10px] text-slate-500">週開始</span>
        <select
          data-testid={`${idPrefix}-week-start`}
          className="rounded border border-slate-300 px-1 py-0.5"
          value={expr.week_starts_on ?? "monday"}
          onChange={(event) =>
            update({ week_starts_on: event.target.value as Weekday })
          }
        >
          {WEEKDAYS.map((day) => (
            <option key={day} value={day}>
              {day}
            </option>
          ))}
        </select>
      </div>

      {issues.length > 0 && (
        <ul
          data-testid={`${idPrefix}-issues`}
          className="text-[10px] text-rose-700"
        >
          {issues.map((issue, index) => (
            <li key={`${issue.code}-${index}`}>{issue.message}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
