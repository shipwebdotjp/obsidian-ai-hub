import { describe, expect, it } from "vitest";
import { extractGeneratedMedia } from "./generatedMedia";

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
