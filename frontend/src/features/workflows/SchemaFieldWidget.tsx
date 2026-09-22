import type { ReactNode } from "react";
import AgentField from "./AgentField";
import PersonField from "./PersonField";
import ProjectField from "./ProjectField";
import VaultPathField from "./VaultPathField";

function toDateTimeLocal(value: unknown): string {
  const text = value === undefined || value === null ? "" : String(value);
  if (!text) return "";
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) return text;
  const pad = (part: number) => String(part).padStart(2, "0");
  // Offset-aware values are converted to the browser's local wall clock so the
  // input does not silently shift the instant by the timezone offset.
  return `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(
    parsed.getDate(),
  )}T${pad(parsed.getHours())}:${pad(parsed.getMinutes())}`;
}

/**
 * Render the literal control for a backend ``x-ui`` widget hint.
 *
 * Returns ``null`` for an unknown widget so the caller falls back to the
 * default type-based control.
 */
export function renderFieldWidget(
  widget: string,
  value: unknown,
  onChange: (value: unknown) => void,
  testId: string,
): ReactNode | null {
  switch (widget) {
    case "vault_path":
      return (
        <VaultPathField
          value={value === undefined || value === null ? "" : String(value)}
          onChange={onChange}
          testIdPrefix={testId}
        />
      );
    case "project":
      return (
        <ProjectField value={value} onChange={onChange} testIdPrefix={testId} />
      );
    case "person":
      return (
        <PersonField
          value={value === undefined || value === null ? "" : String(value)}
          onChange={onChange}
          testIdPrefix={testId}
        />
      );
    case "agent":
      return (
        <AgentField
          value={value === undefined || value === null ? "" : String(value)}
          onChange={onChange}
          testIdPrefix={testId}
        />
      );
    case "date":
      return (
        <input
          type="date"
          data-testid={testId}
          className="w-full rounded border border-slate-300 px-2 py-1"
          value={value === undefined || value === null ? "" : String(value)}
          onChange={(event) => onChange(event.target.value)}
        />
      );
    case "datetime":
      return (
        <input
          type="datetime-local"
          data-testid={testId}
          className="w-full rounded border border-slate-300 px-2 py-1"
          value={toDateTimeLocal(value)}
          onChange={(event) => onChange(event.target.value)}
        />
      );
    default:
      return null;
  }
}
