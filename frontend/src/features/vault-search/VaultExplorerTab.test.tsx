import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import VaultExplorerTab, { type VaultExplorerTabProps } from "./VaultExplorerTab";
import type { VaultFileListItem } from "../../api/types";

function file(relative_path: string, mtime: number): VaultFileListItem {
  return { relative_path, size: 100, mtime };
}

const FILES = [
  file("root.md", 500),
  file("dir/a.md", 200),
  file("dir/sub/b.md", 300),
  file("other/c.md", 100),
];

function renderExplorer(overrides: Partial<VaultExplorerTabProps> = {}) {
  const props: VaultExplorerTabProps = {
    files: FILES,
    loading: false,
    error: null,
    onReload: vi.fn(),
    expandedDirs: [],
    onToggleDir: vi.fn(),
    selectedDir: "",
    onSelectDir: vi.fn(),
    notePath: null,
    onSelectNote: vi.fn(),
    sortKey: "mtime",
    sortDir: "desc",
    onSort: vi.fn(),
    notify: vi.fn(),
    ...overrides,
  };
  render(<VaultExplorerTab {...props} />);
  return props;
}

function rowPaths(): string[] {
  return screen.getAllByTestId("vault-explorer-row-name").map((el) => el.textContent ?? "");
}

describe("VaultExplorerTab", () => {
  it("shows only direct children for the root selection", () => {
    renderExplorer({ selectedDir: "" });
    expect(rowPaths()).toEqual(["root.md"]);
  });

  it("shows files recursively under a directory", () => {
    renderExplorer({ selectedDir: "dir" });
    expect(rowPaths().sort()).toEqual(["a.md", "b.md"]);
  });

  it("sorts by mtime descending by default", () => {
    renderExplorer({ selectedDir: "dir", sortKey: "mtime", sortDir: "desc" });
    expect(rowPaths()).toEqual(["b.md", "a.md"]);
  });

  it("filters by filename only, not directory", async () => {
    renderExplorer({ selectedDir: "dir" });
    await userEvent.type(screen.getByLabelText("ファイル名フィルター"), "b");
    expect(rowPaths()).toEqual(["b.md"]);

    await userEvent.clear(screen.getByLabelText("ファイル名フィルター"));
    await userEvent.type(screen.getByLabelText("ファイル名フィルター"), "sub");
    expect(screen.queryAllByTestId("vault-explorer-row")).toHaveLength(0);
  });

  it("requests sorting when a column header is clicked", async () => {
    const props = renderExplorer();
    await userEvent.click(screen.getByRole("button", { name: "ファイル名で並べ替え" }));
    expect(props.onSort).toHaveBeenCalledWith("name");
    await userEvent.click(screen.getByRole("button", { name: "更新日時で並べ替え" }));
    expect(props.onSort).toHaveBeenCalledWith("mtime");
  });

  it("selects a note when a row is clicked", async () => {
    const props = renderExplorer({ selectedDir: "" });
    await userEvent.click(screen.getByText("root.md"));
    expect(props.onSelectNote).toHaveBeenCalledWith("root.md");
  });

  it("selects a directory from the tree", async () => {
    const props = renderExplorer();
    await userEvent.click(screen.getByText("dir"));
    expect(props.onSelectDir).toHaveBeenCalledWith("dir");
  });

  it("reloads the file list on demand", async () => {
    const props = renderExplorer();
    await userEvent.click(screen.getByRole("button", { name: "再読込" }));
    expect(props.onReload).toHaveBeenCalledTimes(1);
  });

  it("shows an error state with a retry action when loading failed", async () => {
    const props = renderExplorer({ files: null, error: "取得に失敗しました" });
    expect(screen.getByText("取得に失敗しました")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "再読込" }));
    expect(props.onReload).toHaveBeenCalledTimes(1);
  });
});
