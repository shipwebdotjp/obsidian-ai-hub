import type { WorkflowDefinitionFormat } from "../../api/types";

/** Trigger a browser download of an exported definition package. */
export function downloadDefinition(
  filename: string,
  text: string,
  format: WorkflowDefinitionFormat,
): void {
  const mime = format === "json" ? "application/json" : "application/x-yaml";
  const blob = new Blob([text], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Keep a user-facing name usable as a download filename. */
export function safeDefinitionFilename(name: string): string {
  const cleaned = name
    .trim()
    .replace(/[^\p{L}\p{N}._-]+/gu, "_")
    .replace(/[._-]{2,}/g, "_")
    .replace(/^[._-]+|[._-]+$/g, "");
  return (cleaned || "workflow-definition").slice(0, 100);
}
