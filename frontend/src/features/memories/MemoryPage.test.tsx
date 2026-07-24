import { render, screen, waitFor, act, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import MemoryPage from "./MemoryPage";

// Mock the API client
vi.mock("../../api/client", () => ({
  getMemoryOptions: vi.fn(),
  listMemories: vi.fn(),
  getMemory: vi.fn(),
  renderCopilotProfile: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

import { getMemoryOptions, listMemories, getMemory, renderCopilotProfile } from "../../api/client";

const mockGetMemoryOptions = vi.mocked(getMemoryOptions);
const mockListMemories = vi.mocked(listMemories);
const mockGetMemory = vi.mocked(getMemory);
const mockRenderCopilotProfile = vi.mocked(renderCopilotProfile);

const sampleOptions = {
  kinds: ["fact", "preference"],
  topics: ["AI・開発", "健康"],
};

const sampleCandidates = {
  items: [
    {
      memory_id: "mem-1",
      content: "朝のストレッチを毎日10分行う",
      kind: "fact",
      status: "candidate",
      created_at: "2026-07-20T10:00:00Z",
    },
    {
      memory_id: "mem-2",
      content: "React Testing Libraryを好む",
      kind: "preference",
      status: "candidate",
      created_at: "2026-07-20T11:00:00Z",
    },
  ],
  total: 2,
};

const sampleDetail = {
  memory_id: "mem-1",
  content: "朝のストレッチを毎日10分行う",
  kind: "fact",
  status: "candidate",
  created_at: "2026-07-20T10:00:00Z",
  evidence: [],
  events: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  mockGetMemoryOptions.mockResolvedValue(sampleOptions);
  mockListMemories.mockResolvedValue(sampleCandidates as any);
  mockGetMemory.mockResolvedValue(sampleDetail as any);
});

describe("MemoryPage", () => {
  it("initial load fetches options and lists candidate memories", async () => {
    render(<MemoryPage />);

    await waitFor(() => {
      expect(mockGetMemoryOptions).toHaveBeenCalledTimes(1);
      expect(mockListMemories).toHaveBeenCalledWith({
        status: "candidate",
        q: "",
        topic: "",
        kind: "",
      });
    });

    // Verify candidate memories are rendered
    expect(screen.getByText("朝のストレッチを毎日10分行う")).toBeInTheDocument();
    expect(screen.getByText("React Testing Libraryを好む")).toBeInTheDocument();
  });

  it("filters candidate memories when status, kind or topic select is changed", async () => {
    render(<MemoryPage />);

    await waitFor(() => {
      expect(screen.getByText("朝のストレッチを毎日10分行う")).toBeInTheDocument();
    });

    // Change status filter to "approved"
    const statusSelect = screen.getByLabelText("ステータスフィルター");
    mockListMemories.mockResolvedValue({ items: [], total: 0 } as any); // Empty response for approved

    await userEvent.selectOptions(statusSelect, "approved");

    await waitFor(() => {
      expect(mockListMemories).toHaveBeenLastCalledWith({
        status: "approved",
        q: "",
        topic: "",
        kind: "",
      });
    });

    // Change kind filter to "fact"
    const kindSelect = screen.getByLabelText("種別フィルター");
    await userEvent.selectOptions(kindSelect, "fact");

    await waitFor(() => {
      expect(mockListMemories).toHaveBeenLastCalledWith({
        status: "approved",
        q: "",
        topic: "",
        kind: "fact",
      });
    });

    // Change topic filter to "健康"
    const topicSelect = screen.getByLabelText("トピックフィルター");
    await userEvent.selectOptions(topicSelect, "健康");

    await waitFor(() => {
      expect(mockListMemories).toHaveBeenLastCalledWith({
        status: "approved",
        q: "",
        topic: "健康",
        kind: "fact",
      });
    });
  });

  it("resets selection when status, topic, kind, or search query changes", async () => {
    render(<MemoryPage />);

    await waitFor(() => {
      expect(screen.getByText("朝のストレッチを毎日10分行う")).toBeInTheDocument();
    });

    // Select a row first
    const rowButton = screen.getByRole("button", { name: /朝のストレッチを毎日10分行う/ });
    await userEvent.click(rowButton);

    // Verify detailed view loaded
    await waitFor(() => {
      expect(screen.getByText("本文")).toBeInTheDocument();
    });

    // Change filter (e.g. status)
    const statusSelect = screen.getByLabelText("ステータスフィルター");
    await userEvent.selectOptions(statusSelect, "approved");

    // Detailed panel should revert to default prompt
    await waitFor(() => {
      expect(screen.getByText("一覧から候補を選択してください。")).toBeInTheDocument();
    });
  });

  describe("Debounced free-text search", () => {
    beforeEach(() => {
      vi.useFakeTimers();
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it("does not trigger search immediately during typing but triggers after 500ms delay", async () => {
      render(<MemoryPage />);

      await act(async () => {
        vi.runAllTimers();
      });

      mockListMemories.mockClear();

      const searchInput = screen.getByLabelText("メモリ検索");
      fireEvent.change(searchInput, { target: { value: "Stretch" } });

      // While typing, mockListMemories should not have been called yet because of the 500ms debounce
      expect(mockListMemories).not.toHaveBeenCalled();

      // Fast-forward time by 500ms
      await act(async () => {
        vi.advanceTimersByTime(500);
      });

      // Now mockListMemories should be triggered with query "Stretch"
      expect(mockListMemories).toHaveBeenCalledTimes(1);
      expect(mockListMemories).toHaveBeenCalledWith({
        status: "candidate",
        q: "Stretch",
        topic: "",
        kind: "",
      });
    });
  });

  describe("Copilot Profile Generation", () => {
    it("asks for confirmation, calls renderCopilotProfile and shows success toast if approved", async () => {
      const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
      mockRenderCopilotProfile.mockResolvedValue({ updated_files: ["file1.md", "file2.md"] });

      render(<MemoryPage />);

      const renderButton = screen.getByRole("button", { name: "プロファイル生成" });
      await userEvent.click(renderButton);

      expect(confirmSpy).toHaveBeenCalledWith(
        expect.stringContaining("Copilotプロファイルを生成します。")
      );

      await waitFor(() => {
        expect(mockRenderCopilotProfile).toHaveBeenCalledTimes(1);
      });

      // Check success toast
      await waitFor(() => {
        expect(screen.getByText("2 個のファイルを更新しました")).toBeInTheDocument();
      });
    });

    it("does not call renderCopilotProfile if confirmation is rejected", async () => {
      const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);

      render(<MemoryPage />);

      const renderButton = screen.getByRole("button", { name: "プロファイル生成" });
      await userEvent.click(renderButton);

      expect(confirmSpy).toHaveBeenCalled();
      expect(mockRenderCopilotProfile).not.toHaveBeenCalled();
    });

    it("displays error toast if renderCopilotProfile fails", async () => {
      vi.spyOn(window, "confirm").mockReturnValue(true);
      mockRenderCopilotProfile.mockRejectedValue(new Error("Generation failed"));

      render(<MemoryPage />);

      const renderButton = screen.getByRole("button", { name: "プロファイル生成" });
      await userEvent.click(renderButton);

      await waitFor(() => {
        expect(screen.getByText("Generation failed")).toBeInTheDocument();
      });
    });
  });
});
