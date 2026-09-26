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

// Matches the authenticated media delivery paths served by the backend:
// `/api/v1/media/{media_id}` and `/api/v1/media/{media_id}/download`.
const MEDIA_URL_RE = /^\/api\/v1\/media\/([A-Za-z0-9_-]+)(?:\/download)?$/;
// Finds Markdown image sources so the dedup scan only collects ids that
// `MarkdownPreview` actually renders as media cards (absolute URLs, query
// strings, plain links, and prose mentions are intentionally excluded).
const MARKDOWN_IMAGE_SRC_RE = /!\[[^\]]*\]\(\s*([^)\s]+)/g;

/**
 * Extracts the media id when `src` is an in-app media delivery URL, or
 * returns null for any other source (external, relative, unsafe scheme).
 */
export function mediaIdFromUrl(src: unknown): string | null {
  if (typeof src !== "string") return null;
  const match = MEDIA_URL_RE.exec(src.trim());
  return match ? match[1] : null;
}

/**
 * Collects the media ids referenced as in-app delivery URLs inside Markdown
 * image syntax. Used to prefer the inline body rendering over duplicate
 * tool-result cards for the same artifact.
 */
export function extractMediaIdsFromMarkdown(text: unknown): Set<string> {
  const ids = new Set<string>();
  if (typeof text !== "string") return ids;
  // Image syntax inside code renders as literal text (no media card), so code
  // is stripped first to avoid suppressing a card that has no inline twin.
  // Tilde fences and indented/reference-style constructs are not covered;
  // a missed id degrades to a duplicate card, never a vanished artifact.
  const prose = text
    .replace(/```[\s\S]*?(?:```|$)/g, "")
    .replace(/~~~[\s\S]*?(?:~~~|$)/g, "")
    .replace(/`[^`\n]+`/g, "");
  for (const match of prose.matchAll(MARKDOWN_IMAGE_SRC_RE)) {
    // Allow CommonMark angle-bracket destinations: ![a](</api/v1/media/x>).
    const mediaId = mediaIdFromUrl(match[1].replace(/^<|>$/g, ""));
    if (mediaId) ids.add(mediaId);
  }
  return ids;
}

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
