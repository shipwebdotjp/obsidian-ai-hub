import { describe, expect, it } from "vitest";
import {
  extractGeneratedMedia,
  extractMediaIdsFromMarkdown,
  mediaIdFromUrl,
} from "./generatedMedia";

const ref = {
  media_type: "image",
  media_id: "abc123",
  url: "/api/v1/media/abc123",
  download_url: "/api/v1/media/abc123/download",
  mime_type: "image/png",
  width: 1024,
  height: 1024,
  filename: "20260926-120000-abc123.png",
  prompt: "a cat",
  model: "gpt-image-2.5",
};

describe("extractGeneratedMedia", () => {
  it("extracts from a JSON string tool result", () => {
    const result = extractGeneratedMedia(
      JSON.stringify({ summary: "ok", images: [ref] }),
    );
    expect(result).toHaveLength(1);
    expect(result[0].media_id).toBe("abc123");
    expect(result[0].mime_type).toBe("image/png");
  });

  it("extracts from nested objects and arrays", () => {
    const payload = {
      action_index: 1,
      result: { nested: { images: [ref] } },
    };
    expect(extractGeneratedMedia(payload)).toHaveLength(1);
  });

  it("returns an empty list for unrelated payloads", () => {
    expect(extractGeneratedMedia("just text")).toEqual([]);
    expect(extractGeneratedMedia({ summary: "no media" })).toEqual([]);
    expect(extractGeneratedMedia(null)).toEqual([]);
  });

  it("deduplicates by media_id and keeps order", () => {
    const other = { ...ref, media_id: "def456" };
    const result = extractGeneratedMedia([ref, other, { ...ref }]);
    expect(result.map((r) => r.media_id)).toEqual(["abc123", "def456"]);
  });

  it("ignores malformed JSON strings instead of throwing", () => {
    expect(extractGeneratedMedia("{not json")).toEqual([]);
  });

  it("does not recurse infinitely on a self-referential array", () => {
    const cyclic: unknown[] = [];
    cyclic.push(cyclic);
    expect(extractGeneratedMedia(cyclic)).toEqual([]);
  });

  it("does not recurse infinitely on a self-referential object", () => {
    const cyclic: Record<string, unknown> = {};
    cyclic.self = cyclic;
    expect(extractGeneratedMedia(cyclic)).toEqual([]);
  });
});

describe("mediaIdFromUrl", () => {
  it("extracts the id from media delivery URLs", () => {
    expect(mediaIdFromUrl("/api/v1/media/abc123")).toBe("abc123");
    expect(mediaIdFromUrl("/api/v1/media/abc123/download")).toBe("abc123");
  });

  it("returns null for other sources", () => {
    expect(mediaIdFromUrl("https://example.com/a.png")).toBeNull();
    expect(mediaIdFromUrl("relative/image.png")).toBeNull();
    expect(mediaIdFromUrl("data:image/png;base64,AAA")).toBeNull();
    expect(mediaIdFromUrl("javascript:alert(1)")).toBeNull();
    expect(mediaIdFromUrl("/api/v1/media/")).toBeNull();
    expect(mediaIdFromUrl(undefined)).toBeNull();
    expect(mediaIdFromUrl(null)).toBeNull();
  });
});

describe("extractMediaIdsFromMarkdown", () => {
  it("collects ids from Markdown image syntax", () => {
    const ids = extractMediaIdsFromMarkdown(
      'one ![a](/api/v1/media/abc123) two ![b](/api/v1/media/def456/download) three ![c](/api/v1/media/ghi789 "title")',
    );
    expect(ids).toEqual(new Set(["abc123", "def456", "ghi789"]));
  });

  it("ignores non-image references so cards are not wrongly suppressed", () => {
    expect(
      extractMediaIdsFromMarkdown("[dl](/api/v1/media/abc123)"),
    ).toEqual(new Set());
    expect(
      extractMediaIdsFromMarkdown("![a](https://host/api/v1/media/abc123)"),
    ).toEqual(new Set());
    expect(
      extractMediaIdsFromMarkdown("![a](/api/v1/media/abc123?v=1)"),
    ).toEqual(new Set());
    expect(
      extractMediaIdsFromMarkdown("see /api/v1/media/abc123 in prose"),
    ).toEqual(new Set());
  });

  it("collects ids from angle-bracket destinations", () => {
    expect(
      extractMediaIdsFromMarkdown("![a](</api/v1/media/abc123>)"),
    ).toEqual(new Set(["abc123"]));
  });

  it("ignores image syntax inside code blocks and inline code", () => {
    expect(
      extractMediaIdsFromMarkdown("```\n![a](/api/v1/media/abc123)\n```"),
    ).toEqual(new Set());
    expect(
      extractMediaIdsFromMarkdown("~~~\n![a](/api/v1/media/abc123)\n~~~"),
    ).toEqual(new Set());
    expect(
      extractMediaIdsFromMarkdown("see `![a](/api/v1/media/abc123)` here"),
    ).toEqual(new Set());
  });

  it("ignores other URLs and non-string input", () => {
    expect(
      extractMediaIdsFromMarkdown("![x](https://example.com/a.png)"),
    ).toEqual(new Set());
    expect(extractMediaIdsFromMarkdown(null)).toEqual(new Set());
  });
});
