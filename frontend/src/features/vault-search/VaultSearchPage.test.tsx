import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import VaultSearchPage from "./VaultSearchPage";

vi.mock("../../api/client", () => ({
  searchVault: vi.fn(),
  listVaultFiles: vi.fn(),
  getVaultFile: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

import { searchVault, listVaultFiles, getVaultFile } from "../../api/client";
import { VAULT_SEARCH_UI_STORAGE_KEY } from "./vaultSearchUiState";

const mockSearchVault = vi.mocked(searchVault);
const mockListVaultFiles = vi.mocked(listVaultFiles);
const mockGetVaultFile = vi.mocked(getVaultFile);
const HISTORY_KEY = "obsidian-ai-hub:vault-search-history:v1";

beforeEach(() => {
  vi.clearAllMocks();
  mockListVaultFiles.mockResolvedValue({ items: [], total: 0 });
  mockGetVaultFile.mockResolvedValue({
    content: "",
    relative_path: "",
    vault_name: "vault",
  });
  localStorage.removeItem(HISTORY_KEY);
  localStorage.removeItem(VAULT_SEARCH_UI_STORAGE_KEY);
});

it("does not show 'no results' toast during loading", async () => {
  mockSearchVault.mockReturnValue(new Promise(() => {}));

  render(<VaultSearchPage />);

  const input = screen.getByPlaceholderText("検索クエリ");
  const button = screen.getByRole("button", { name: "検索" });

  await userEvent.type(input, "test query");
  await userEvent.click(button);

  expect(button).toBeDisabled();
  expect(screen.queryByText("検索結果が見つかりませんでした")).toBeNull();
});

it("shows 'no results' toast when search completes with empty results", async () => {
  mockSearchVault.mockResolvedValue({ items: [], total: 0 });

  render(<VaultSearchPage />);

  const input = screen.getByPlaceholderText("検索クエリ");
  const button = screen.getByRole("button", { name: "検索" });

  await userEvent.type(input, "test query");
  await userEvent.click(button);

  await waitFor(() => {
    expect(screen.getByText("検索結果が見つかりませんでした")).toBeInTheDocument();
  });
});

it("does not show 'no results' toast when search has results", async () => {
  mockSearchVault.mockResolvedValue({
    items: [{ content: "result", metadata: {}, score: 0.9 }],
    total: 1,
  });

  render(<VaultSearchPage />);

  const input = screen.getByPlaceholderText("検索クエリ");
  const button = screen.getByRole("button", { name: "検索" });

  await userEvent.type(input, "test query");
  await userEvent.click(button);

  await waitFor(() => {
    expect(screen.queryByText("検索結果が見つかりませんでした")).toBeNull();
  });
});

it("saves search to history and displays history section", async () => {
  mockSearchVault.mockResolvedValue({ items: [], total: 0 });
  render(<VaultSearchPage />);

  const input = screen.getByPlaceholderText("検索クエリ");
  await userEvent.type(input, "history test");
  await userEvent.click(screen.getByRole("button", { name: "検索" }));

  await waitFor(() => {
    expect(screen.getByText("history test")).toBeInTheDocument();
  });

  const raw = localStorage.getItem(HISTORY_KEY);
  expect(raw).not.toBeNull();
  const history = JSON.parse(raw!);
  expect(history.length).toBe(1);
  expect(history[0].query).toBe("history test");
  expect(history[0].mode).toBe("hybrid");
  expect(history[0].k).toBe(10);
  expect(history[0].searchedAt).toBeDefined();
});

it("history item re-runs search with saved params", async () => {
  mockSearchVault.mockResolvedValue({ items: [], total: 0 });
  render(<VaultSearchPage />);

  const input = screen.getByPlaceholderText("検索クエリ");
  await userEvent.type(input, "rerun test");
  await userEvent.click(screen.getByRole("button", { name: "検索" }));

  await waitFor(() => {
    expect(mockSearchVault).toHaveBeenCalledTimes(1);
  });

  mockSearchVault.mockClear();
  mockSearchVault.mockResolvedValue({ items: [], total: 0 });

  const historyBtn = screen.getByRole("button", { name: /rerun test/ });
  await userEvent.click(historyBtn);

  await waitFor(() => {
    expect(mockSearchVault).toHaveBeenCalledWith({
      q: "rerun test",
      k: 10,
      mode: "hybrid",
    });
  });
});

it("deduplicates identical searches in history", async () => {
  mockSearchVault.mockResolvedValue({ items: [], total: 0 });
  render(<VaultSearchPage />);

  const input = screen.getByPlaceholderText("検索クエリ");
  const button = screen.getByRole("button", { name: "検索" });

  await userEvent.type(input, "dedup query");
  await userEvent.click(button);
  await waitFor(() => {
    expect(screen.getByText("dedup query")).toBeInTheDocument();
  });

  mockSearchVault.mockClear();

  await userEvent.clear(input);
  await userEvent.type(input, "dedup query");
  await userEvent.click(button);

  await waitFor(() => {
    const raw = localStorage.getItem(HISTORY_KEY);
    const history = JSON.parse(raw!);
    expect(history.length).toBe(1);
  });
});

describe("vault explorer tab", () => {
  it("restores the saved explorer tab, loads files once, and keeps them across tab switches", async () => {
    localStorage.setItem(
      VAULT_SEARCH_UI_STORAGE_KEY,
      JSON.stringify({ activeTab: "explorer" }),
    );
    mockListVaultFiles.mockResolvedValue({
      items: [{ relative_path: "root.md", size: 10, mtime: 100 }],
      total: 1,
    });

    render(<VaultSearchPage />);

    expect(await screen.findByText("root.md")).toBeInTheDocument();
    expect(mockListVaultFiles).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole("tab", { name: "検索" }));
    await userEvent.click(screen.getByRole("tab", { name: "ファイルエクスプローラー" }));
    expect(mockListVaultFiles).toHaveBeenCalledTimes(1);
  });

  it("persists the last opened tab", async () => {
    render(<VaultSearchPage />);

    await userEvent.click(screen.getByRole("tab", { name: "ファイルエクスプローラー" }));

    await waitFor(() => {
      const saved = JSON.parse(localStorage.getItem(VAULT_SEARCH_UI_STORAGE_KEY)!);
      expect(saved.activeTab).toBe("explorer");
    });
  });

  it("keeps the filename filter across tab switches", async () => {
    localStorage.setItem(
      VAULT_SEARCH_UI_STORAGE_KEY,
      JSON.stringify({ activeTab: "explorer" }),
    );
    mockListVaultFiles.mockResolvedValue({
      items: [
        { relative_path: "alpha.md", size: 10, mtime: 100 },
        { relative_path: "beta.md", size: 10, mtime: 90 },
      ],
      total: 2,
    });

    render(<VaultSearchPage />);

    const filter = await screen.findByLabelText("ファイル名フィルター");
    await userEvent.type(filter, "alpha");
    await userEvent.click(screen.getByRole("tab", { name: "検索" }));
    await userEvent.click(screen.getByRole("tab", { name: "ファイルエクスプローラー" }));

    expect(screen.getByLabelText("ファイル名フィルター")).toHaveValue("alpha");
  });

  it("reloads the file list on demand", async () => {
    localStorage.setItem(
      VAULT_SEARCH_UI_STORAGE_KEY,
      JSON.stringify({ activeTab: "explorer" }),
    );
    mockListVaultFiles.mockResolvedValue({ items: [], total: 0 });

    render(<VaultSearchPage />);

    await waitFor(() => expect(mockListVaultFiles).toHaveBeenCalledTimes(1));
    await userEvent.click(screen.getByRole("button", { name: "再読込" }));
    await waitFor(() => expect(mockListVaultFiles).toHaveBeenCalledTimes(2));
  });

  it("clears a saved note that no longer exists in the file list", async () => {
    localStorage.setItem(
      VAULT_SEARCH_UI_STORAGE_KEY,
      JSON.stringify({ activeTab: "explorer", notePath: "gone.md" }),
    );
    mockListVaultFiles.mockResolvedValue({
      items: [{ relative_path: "root.md", size: 10, mtime: 100 }],
      total: 1,
    });

    render(<VaultSearchPage />);

    await waitFor(() => {
      const saved = JSON.parse(localStorage.getItem(VAULT_SEARCH_UI_STORAGE_KEY)!);
      expect(saved.notePath).toBeNull();
    });
  });
});
