import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, beforeEach, vi } from "vitest";
import { AgentVaultFilePicker } from "../AgentVaultFilePicker";

vi.mock("../../../api/client", () => ({
  listVaultFiles: vi.fn(),
  searchVault: vi.fn(),
}));

import { listVaultFiles, searchVault } from "../../../api/client";

const mockListVaultFiles = vi.mocked(listVaultFiles);
const mockSearchVault = vi.mocked(searchVault);

const FILES = {
  items: [
    { relative_path: "会議/2026-09-21 定例.md", size: 120, mtime: 1700000000 },
    { relative_path: "設計メモ.md", size: 340, mtime: 1700000001 },
  ],
  total: 2,
};

function setup(selected: { kind: "vault_file"; path: string }[] = []) {
  const onToggle = vi.fn();
  const onClose = vi.fn();
  render(
    <AgentVaultFilePicker selected={selected} onToggle={onToggle} onClose={onClose} />,
  );
  return { onToggle, onClose };
}

describe("AgentVaultFilePicker", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockListVaultFiles.mockResolvedValue(FILES);
    mockSearchVault.mockResolvedValue({ items: [], total: 0 });
  });

  it("loads the file list and shows the tree when the query is empty", async () => {
    setup();
    expect(mockListVaultFiles).toHaveBeenCalledTimes(1);
    await waitFor(() => {
      expect(screen.getByText("会議")).toBeInTheDocument();
    });
    expect(screen.getByText("設計メモ.md")).toBeInTheDocument();
  });

  it("expands a directory and toggles a file on click", async () => {
    const user = userEvent.setup();
    const { onToggle } = setup();
    await waitFor(() => {
      expect(screen.getByText("会議")).toBeInTheDocument();
    });
    // 初回はトップレベル展開済みのはず
    await user.click(screen.getByText("2026-09-21 定例.md"));
    expect(onToggle).toHaveBeenCalledWith("会議/2026-09-21 定例.md");
  });

  it("filters by filename as the query is typed", async () => {
    const user = userEvent.setup();
    setup();
    await waitFor(() => {
      expect(screen.getByText("会議")).toBeInTheDocument();
    });
    const search = screen.getByLabelText("Vault ファイル検索");
    await user.type(search, "設計");
    await waitFor(() => {
      expect(screen.getByText("ファイル名")).toBeInTheDocument();
    });
    expect(screen.getByText("設計メモ.md")).toBeInTheDocument();
    expect(screen.queryByText("会議")).not.toBeInTheDocument();
  });

  it("marks already-selected files and disables over-limit rows", async () => {
    setup([
      { kind: "vault_file", path: "設計メモ.md" },
      { kind: "vault_file", path: "a.md" },
      { kind: "vault_file", path: "b.md" },
      { kind: "vault_file", path: "c.md" },
      { kind: "vault_file", path: "d.md" },
    ]);
    await waitFor(() => {
      expect(screen.getByText("設計メモ.md")).toBeInTheDocument();
    });
    const picker = screen.getByTestId("agent-vault-file-picker");
    expect(within(picker).getByText("選択中 5/5")).toBeInTheDocument();
    // 未選択の行は上限で無効化される
    const treeRow = screen.getByText("2026-09-21 定例.md").closest("button");
    expect(treeRow).toBeDisabled();
  });

  it("closes on Escape", async () => {
    const user = userEvent.setup();
    const { onClose } = setup();
    await waitFor(() => {
      expect(screen.getByText("会議")).toBeInTheDocument();
    });
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });
});
