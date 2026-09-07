import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import ExecutionLogPage from "./ExecutionLogPage";

vi.mock("../../api/client", () => ({
  apiGet: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

import { apiGet } from "../../api/client";

const mockApiGet = vi.mocked(apiGet);

const sampleCommandItem = {
  id: "cmd-1",
  kind: "command",
  status: "succeeded",
  name: "make_target",
  started_at: "2026-07-20T10:00:00Z",
  finished_at: "2026-07-20T10:01:00Z",
  summary: "Target generated successfully",
};

const sampleLLMItem = {
  id: "llm-1",
  kind: "llm",
  status: "succeeded",
  name: "gpt-4o-mini",
  started_at: "2026-07-20T10:00:30Z",
  finished_at: "2026-07-20T10:00:45Z",
  summary: "LLM call completed",
};

const sampleListResponse = {
  items: [sampleCommandItem, sampleLLMItem],
  total: 2,
};

const sampleCommandDetail = {
  run_id: "cmd-1",
  command: "make_target",
  started_at: "2026-07-20T10:00:00Z",
  finished_at: "2026-07-20T10:01:00Z",
  status: "succeeded",
  summary: "Target generated successfully",
  llm_calls: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  mockApiGet.mockImplementation((_path: string) => {
    return Promise.resolve(sampleListResponse);
  });
});

it("renders log items in the list and does not fetch task states", async () => {
  render(<ExecutionLogPage />);

  await waitFor(() => {
    expect(screen.getByText("make_target")).toBeInTheDocument();
  });
  expect(screen.getByText("gpt-4o-mini")).toBeInTheDocument();
  expect(screen.queryByText("タスク状態")).not.toBeInTheDocument();
  expect(mockApiGet).not.toHaveBeenCalledWith("/api/v1/task-states");
});

it("shows detail prompt on desktop when list says to select", async () => {
  render(<ExecutionLogPage />);

  await waitFor(() => {
    expect(screen.getByText("左側の一覧からログを選択すると詳細が表示されます。")).toBeInTheDocument();
  });
});

it("opens mobile detail panel when a list row is clicked", async () => {
  render(<ExecutionLogPage />);

  await waitFor(() => {
    expect(screen.getByText("make_target")).toBeInTheDocument();
  });

  mockApiGet.mockResolvedValueOnce(sampleCommandDetail);

  const row = screen.getAllByText("make_target")[0].closest("button")!;
  await userEvent.click(row);

  await waitFor(() => {
    expect(screen.getByText("← 一覧")).toBeInTheDocument();
  });
});

it("toggles mobile detail panel when multiple rows are clicked", async () => {
  render(<ExecutionLogPage />);

  await waitFor(() => {
    expect(screen.getByText("make_target")).toBeInTheDocument();
    expect(screen.getByText("gpt-4o-mini")).toBeInTheDocument();
  });

  mockApiGet.mockResolvedValueOnce(sampleCommandDetail);

  await userEvent.click(screen.getAllByText("make_target")[0].closest("button")!);

  await waitFor(() => {
    expect(screen.getByText("← 一覧")).toBeInTheDocument();
  });

  const backButton = screen.getByRole("button", { name: "一覧に戻る" });
  await userEvent.click(backButton);

  mockApiGet.mockResolvedValueOnce(sampleCommandDetail);

  await userEvent.click(screen.getAllByText("make_target")[0].closest("button")!);

  await waitFor(() => {
    expect(screen.getByText("← 一覧")).toBeInTheDocument();
  });
});

const listCalls = () =>
  mockApiGet.mock.calls
    .map((c) => c[0] as string)
    .filter((p) => p.startsWith("/api/v1/execution-logs?"));

it("shows a full-text search box", async () => {
  render(<ExecutionLogPage />);

  await waitFor(() => {
    expect(screen.getByText("make_target")).toBeInTheDocument();
  });
  expect(screen.getByText("全文検索")).toBeInTheDocument();
  expect(
    screen.getByPlaceholderText("e.g. プロンプト本文、引数、エラー文言")
  ).toBeInTheDocument();
});

it("sends q param and resets to the first page on input", async () => {
  mockApiGet.mockImplementation((_path: string) => {
    return Promise.resolve({ items: [sampleCommandItem], total: 120 });
  });
  render(<ExecutionLogPage />);

  const input = await screen.findByPlaceholderText(
    "e.g. プロンプト本文、引数、エラー文言"
  );

  await userEvent.click(screen.getByRole("button", { name: "次へ" }));
  await waitFor(() => {
    const calls = listCalls();
    expect(calls.length).toBeGreaterThan(0);
    expect(calls[calls.length - 1]).toContain("offset=50");
  });

  mockApiGet.mockClear();
  await userEvent.type(input, "hello");

  await waitFor(() => {
    const calls = listCalls();
    expect(calls.length).toBeGreaterThan(0);
    const last = calls[calls.length - 1];
    expect(last).toContain("q=hello");
    expect(last).toContain("offset=0");
  });
  expect(screen.getByText("1 / 3")).toBeInTheDocument();
});

it("clear button removes the q param", async () => {
  render(<ExecutionLogPage />);

  const input = await screen.findByPlaceholderText(
    "e.g. プロンプト本文、引数、エラー文言"
  );
  await userEvent.type(input, "hello");

  await waitFor(() => {
    const calls = listCalls();
    expect(calls.length).toBeGreaterThan(0);
    expect(calls[calls.length - 1]).toContain("q=hello");
  });

  mockApiGet.mockClear();
  await userEvent.click(screen.getByRole("button", { name: "クリア" }));

  await waitFor(() => {
    const calls = listCalls();
    expect(calls.length).toBeGreaterThan(0);
    expect(calls[calls.length - 1]).not.toContain("q=");
  });
});
