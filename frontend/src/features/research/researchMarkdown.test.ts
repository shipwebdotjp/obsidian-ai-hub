import { describe, expect, it } from "vitest";
import { parseResearchFrontmatter } from "./researchMarkdown";
import { isResearchSucceeded, researchJobStatusLabel, researchModeLabel } from "./researchLabels";

describe("parseResearchFrontmatter", () => {
  it("splits metadata from the body", () => {
    const markdown = [
      "---",
      "title: generated",
      "status: researched",
      "generated_at: 2026-09-21T13:10:52+09:00",
      "source: tavily-search",
      "output_style: long",
      "---",
      "",
      "## 見出し",
      "本文",
      "",
    ].join("\n");

    const parsed = parseResearchFrontmatter(markdown);
    expect(parsed.title).toBe("generated");
    expect(parsed.source).toBe("tavily-search");
    expect(parsed.output_style).toBe("long");
    expect(parsed.body).toBe("## 見出し\n本文\n");
    expect(parsed.body).not.toContain("---");
  });

  it("returns the input as body when there is no frontmatter", () => {
    const markdown = "# 見出し\n本文\n";
    expect(parseResearchFrontmatter(markdown)).toEqual({ body: markdown });
  });

  it("returns the input as body when the closing fence is missing", () => {
    const markdown = "---\ntitle: generated\n本文\n";
    expect(parseResearchFrontmatter(markdown).body).toBe(markdown);
  });
});

describe("research status helpers", () => {
  it("treats only succeeded jobs as researched", () => {
    expect(isResearchSucceeded({ status: "succeeded" })).toBe(true);
    expect(isResearchSucceeded({ status: "running" })).toBe(false);
    expect(isResearchSucceeded(null)).toBe(false);
    expect(isResearchSucceeded(undefined)).toBe(false);
  });

  it("resolves known statuses and modes to a label different from the raw value", () => {
    for (const status of ["pending", "running", "succeeded", "failed"]) {
      expect(researchJobStatusLabel(status)).not.toBe(status);
    }
    for (const mode of ["internal", "web", "deep", "project"]) {
      expect(researchModeLabel(mode)).not.toBe(mode);
    }
  });

  it("falls back to the raw value for unknown statuses and modes", () => {
    expect(researchJobStatusLabel("unknown-state")).toBe("unknown-state");
    expect(researchModeLabel("unknown-mode")).toBe("unknown-mode");
  });
});
