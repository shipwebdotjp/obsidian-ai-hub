import type { GeneratedMediaRef } from "../../api/types";

/**
 * Tool/capability payloads reach the UI as JSON strings or nested objects
 * (Agent tool results, Task events, Workflow node outputs). This module finds
 * media references anywhere in such a value so every surface can render the
 * same card without knowing the producing capability.
 */

// Bounds the recursive JSON-string scan so a large embedded blob (e.g. a long
// base64 string that happens to start with "{") is never parsed.
const MAX_JSON_SCAN_CHARS = 20000;

function isMediaRef(value: unknown): value is Record<string, unknown> {
  if (value === null || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.media_id === "string" &&
    v.media_id.length > 0 &&
    typeof v.media_type === "string" &&
    v.media_type.length > 0 &&
    typeof v.mime_type === "string" &&
    v.mime_type.length > 0
  );
}

function normalize(value: Record<string, unknown>): GeneratedMediaRef {
  return {
    media_type: String(value.media_type),
    media_id: String(value.media_id),
    mime_type: String(value.mime_type),
    width: typeof value.width === "number" ? value.width : null,
    height: typeof value.height === "number" ? value.height : null,
    filename: typeof value.filename === "string" ? value.filename : undefined,
  };
}

export function extractGeneratedMedia(value: unknown): GeneratedMediaRef[] {
  const found = new Map<string, GeneratedMediaRef>();
  const seen = new Set<object>();

  const visit = (node: unknown): void => {
    if (typeof node === "string") {
      const text = node.trim();
      if (
        text.length > 0 &&
        text.length <= MAX_JSON_SCAN_CHARS &&
        (text.startsWith("{") || text.startsWith("["))
      ) {
        try {
          visit(JSON.parse(text));
        } catch {
          // Not JSON; nothing to extract.
        }
      }
      return;
    }
    if (node === null || typeof node !== "object") return;
    if (seen.has(node)) return;
    seen.add(node);
    if (Array.isArray(node)) {
      for (const item of node) visit(item);
      return;
    }
    if (isMediaRef(node)) {
      const ref = normalize(node);
      if (!found.has(ref.media_id)) found.set(ref.media_id, ref);
      return;
    }
    for (const child of Object.values(node as Record<string, unknown>)) {
      visit(child);
    }
  };

  visit(value);
  return Array.from(found.values());
}
