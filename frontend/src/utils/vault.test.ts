import { describe, it, expect } from "vitest";
import {
  buildVaultTree,
  filterVaultFiles,
  filterVaultFilesByName,
  flattenVaultTree,
  formatVaultFileSize,
  listFilesInDirectory,
  parseNoteContent,
  sortVaultFiles,
  vaultFileDirectory,
  vaultFileName,
} from "./vault";
import type { VaultFileListItem } from "../api/types";

function file(relative_path: string, mtime: number = 1700000000): VaultFileListItem {
  return { relative_path, size: 100, mtime };
}

const FILES = [
  file("会議/2026-09-21 定例.md"),
  file("会議/2026-09-20 定例.md"),
  file("プロジェクトA/設計メモ.md"),
  file("プロジェクトA/議事録.md"),
  file("日記/2026-09-21.md"),
];

describe("filterVaultFiles", () => {
  it("returns the head of the list for an empty query", () => {
    expect(filterVaultFiles(FILES, "", 2)).toEqual(FILES.slice(0, 2));
  });

  it("matches filename substrings including Japanese", () => {
    const hits = filterVaultFiles(FILES, "定例");
    expect(hits.map((f) => f.relative_path)).toEqual([
      "会議/2026-09-21 定例.md",
      "会議/2026-09-20 定例.md",
    ]);
  });

  it("ranks filename starts-with above filename includes", () => {
    const hits = filterVaultFiles(FILES, "議事");
    expect(hits[0].relative_path).toBe("プロジェクトA/議事録.md");
  });

  it("falls back to directory matches when the filename does not match", () => {
    const hits = filterVaultFiles(FILES, "プロジェクトA");
    expect(hits.map((f) => f.relative_path)).toEqual([
      "プロジェクトA/設計メモ.md",
      "プロジェクトA/議事録.md",
    ]);
  });

  it("is case-insensitive and returns [] on no match", () => {
    expect(filterVaultFiles([file("Notes/Hello.md")], "hello")).toHaveLength(1);
    expect(filterVaultFiles(FILES, "存在しない")).toEqual([]);
  });
});

describe("filterVaultFilesByName", () => {
  it("matches only the filename, not the directory", () => {
    expect(filterVaultFilesByName(FILES, "プロジェクトA")).toEqual([]);
  });

  it("is case-insensitive and partial", () => {
    expect(filterVaultFilesByName([file("Notes/Hello.md")], "ello")).toHaveLength(1);
    expect(filterVaultFilesByName([file("Notes/Hello.md")], "HELLO")).toHaveLength(1);
  });

  it("returns all files (in input order) for an empty query", () => {
    expect(filterVaultFilesByName(FILES, "  ")).toEqual(FILES);
  });
});

describe("buildVaultTree / flattenVaultTree", () => {
  it("groups files by directory with directories first", () => {
    const tree = buildVaultTree(FILES);
    expect(tree.map((n) => n.name)).toEqual(["プロジェクトA", "会議", "日記"]);
    expect(tree.every((n) => n.isDirectory)).toBe(true);
    const meetings = tree.find((n) => n.name === "会議");
    expect(meetings?.children.map((c) => c.name)).toEqual([
      "2026-09-20 定例.md",
      "2026-09-21 定例.md",
    ]);
  });

  it("exposes visible rows honoring expanded directories", () => {
    const tree = buildVaultTree(FILES);
    const collapsed = flattenVaultTree(tree, new Set());
    expect(collapsed.every((r) => r.depth === 0)).toBe(true);
    const expanded = flattenVaultTree(tree, new Set(["会議"]));
    const meetingFiles = expanded.filter((r) => r.depth === 1);
    expect(meetingFiles).toHaveLength(2);
    expect(meetingFiles[0].node.file?.relative_path).toBe("会議/2026-09-20 定例.md");
  });
});

describe("listFilesInDirectory", () => {
  it("returns only direct children for the root", () => {
    const files = [file("root.md"), file("dir/a.md"), file("dir/sub/b.md")];
    expect(listFilesInDirectory(files, "").map((f) => f.relative_path)).toEqual(["root.md"]);
  });

  it("returns files recursively under a directory", () => {
    const files = [file("root.md"), file("dir/a.md"), file("dir/sub/b.md"), file("other/c.md")];
    expect(listFilesInDirectory(files, "dir").map((f) => f.relative_path)).toEqual([
      "dir/a.md",
      "dir/sub/b.md",
    ]);
  });
});

describe("sortVaultFiles", () => {
  const files = [
    file("b/aaa.md", 100),
    file("a/ccc.md", 300),
    file("a/bbb.md", 300),
  ];

  it("sorts by name ascending and descending", () => {
    expect(sortVaultFiles(files, "name", "asc").map((f) => f.relative_path)).toEqual([
      "b/aaa.md",
      "a/bbb.md",
      "a/ccc.md",
    ]);
    expect(sortVaultFiles(files, "name", "desc").map((f) => f.relative_path)).toEqual([
      "a/ccc.md",
      "a/bbb.md",
      "b/aaa.md",
    ]);
  });

  it("sorts by mtime with relative-path tie-break", () => {
    expect(sortVaultFiles(files, "mtime", "desc").map((f) => f.relative_path)).toEqual([
      "a/bbb.md",
      "a/ccc.md",
      "b/aaa.md",
    ]);
    expect(sortVaultFiles(files, "mtime", "asc").map((f) => f.relative_path)).toEqual([
      "b/aaa.md",
      "a/bbb.md",
      "a/ccc.md",
    ]);
  });
});

describe("vault path helpers", () => {
  it("splits filename and directory", () => {
    expect(vaultFileName("a/b/c.md")).toBe("c.md");
    expect(vaultFileDirectory("a/b/c.md")).toBe("a/b");
    expect(vaultFileName("root.md")).toBe("root.md");
    expect(vaultFileDirectory("root.md")).toBe("");
  });

  it("formats sizes in B/KB/MB", () => {
    expect(formatVaultFileSize(512)).toBe("512 B");
    expect(formatVaultFileSize(2048)).toBe("2.0 KB");
    expect(formatVaultFileSize(3 * 1024 * 1024)).toBe("3.0 MB");
    expect(formatVaultFileSize(NaN)).toBe("");
  });
});

describe("parseNoteContent", () => {
  it("separates frontmatter from body", () => {
    const parsed = parseNoteContent("---\ntitle: x\n---\n# Body");
    expect(parsed.frontmatter).toBe("---\ntitle: x\n---");
    expect(parsed.body).toBe("# Body");
  });

  it("returns the whole content as body without frontmatter", () => {
    const parsed = parseNoteContent("# Body");
    expect(parsed.frontmatter).toBeNull();
    expect(parsed.body).toBe("# Body");
  });
});
