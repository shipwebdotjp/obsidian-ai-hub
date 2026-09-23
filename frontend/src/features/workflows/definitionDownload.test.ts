import { describe, expect, it } from "vitest";
import { safeDefinitionFilename } from "./definitionDownload";

describe("safeDefinitionFilename", () => {
  it("keeps readable names", () => {
    expect(safeDefinitionFilename("my-workflow")).toBe("my-workflow");
    expect(safeDefinitionFilename("日本語のワークフロー")).toBe(
      "日本語のワークフロー",
    );
  });

  it("collapses separators and trims edge punctuation", () => {
    expect(safeDefinitionFilename("a  b/c")).toBe("a_b_c");
    expect(safeDefinitionFilename("..")).toBe("workflow-definition");
    expect(safeDefinitionFilename("--name--")).toBe("name");
  });

  it("falls back and caps the length", () => {
    expect(safeDefinitionFilename("   ")).toBe("workflow-definition");
    expect(safeDefinitionFilename("x".repeat(200)).length).toBe(100);
  });
});
