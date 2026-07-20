import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import VaultSearchPage from "./VaultSearchPage";

vi.mock("../../api/client", () => ({
  searchVault: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

import { searchVault } from "../../api/client";

const mockSearchVault = vi.mocked(searchVault);
const HISTORY_KEY = "obsidian-ai-hub:vault-search-history:v1";

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.removeItem(HISTORY_KEY);
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
