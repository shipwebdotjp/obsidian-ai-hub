import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import VaultSearchPage from "./VaultSearchPage";

vi.mock("../../api/client", () => ({
  searchVault: vi.fn(),
  ApiError: class ApiError extends Error {
    constructor(message: string) {
      super(message);
      this.name = "ApiError";
    }
  },
}));

import { searchVault } from "../../api/client";

const mockSearchVault = vi.mocked(searchVault);

beforeEach(() => {
  vi.clearAllMocks();
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
