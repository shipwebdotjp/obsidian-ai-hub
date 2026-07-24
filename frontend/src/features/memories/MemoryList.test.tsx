import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import MemoryList from "./MemoryList";

vi.mock("../../api/client", () => ({
  listMemories: vi.fn(),
  batchReview: vi.fn(),
  reviewMemory: vi.fn(),
  batchDeleteMemories: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

import { listMemories, batchReview, reviewMemory, batchDeleteMemories } from "../../api/client";

const mockListMemories = vi.mocked(listMemories);
const mockBatchReview = vi.mocked(batchReview);
const mockReviewMemory = vi.mocked(reviewMemory);
const mockBatchDeleteMemories = vi.mocked(batchDeleteMemories);

const sampleItems = {
  items: [
    {
      memory_id: "mem-1",
      content: "Memory 1 content",
      kind: "fact",
      status: "candidate",
      created_at: "2026-07-20T10:00:00Z",
    },
    {
      memory_id: "mem-2",
      content: "Memory 2 content",
      kind: "preference",
      status: "candidate",
      created_at: "2026-07-20T11:00:00Z",
    },
  ],
  total: 2,
};

const notifyMock = vi.fn();
const onSelectionChangeMock = vi.fn();
const onSelectMock = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  mockListMemories.mockResolvedValue(sampleItems as any);
});

describe("MemoryList", () => {
  it("renders elements and supports toggling selection checkboxes", async () => {
    const selectedIds = new Set<string>();
    render(
      <MemoryList
        status="candidate"
        query=""
        topic=""
        selectedIds={selectedIds}
        selectedMemoryId={null}
        onSelectionChange={onSelectionChangeMock}
        onSelect={onSelectMock}
        refreshKey={0}
        notify={notifyMock}
      />
    );

    await waitFor(() => {
      expect(screen.getByText("Memory 1 content")).toBeInTheDocument();
    });

    const checkboxes = screen.getAllByRole("checkbox");
    // checkboxes[0] is "全選択", checkboxes[1] is mem-1, checkboxes[2] is mem-2
    expect(checkboxes).toHaveLength(3);

    // Toggle individual checkbox
    await userEvent.click(checkboxes[1]);
    expect(onSelectionChangeMock).toHaveBeenCalledWith(new Set(["mem-1"]));

    // Toggle all selection checkbox
    await userEvent.click(checkboxes[0]);
    expect(onSelectionChangeMock).toHaveBeenCalledWith(new Set(["mem-1", "mem-2"]));
  });

  it("handles batch review approval successfully", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    mockBatchReview.mockResolvedValue({ updated: ["mem-1", "mem-2"], not_found: [], events: [] } as any);

    const selectedIds = new Set(["mem-1", "mem-2"]);
    render(
      <MemoryList
        status="candidate"
        query=""
        topic=""
        selectedIds={selectedIds}
        selectedMemoryId={null}
        onSelectionChange={onSelectionChangeMock}
        onSelect={onSelectMock}
        refreshKey={0}
        notify={notifyMock}
      />
    );

    const batchApproveBtn = screen.getByRole("button", { name: "一括承認" });
    await userEvent.click(batchApproveBtn);

    expect(window.confirm).toHaveBeenCalledWith("2 件を一括承認します。よろしいですか？");
    await waitFor(() => {
      expect(mockBatchReview).toHaveBeenCalledWith({
        memory_ids: ["mem-1", "mem-2"],
        action: "approve",
      });
      expect(notifyMock).toHaveBeenCalledWith("2 件を承認しました");
    });
  });

  it("handles batch deletion successfully", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    mockBatchDeleteMemories.mockResolvedValue({ deleted: ["mem-1"], not_found: [], events_deleted: [] } as any);

    const selectedIds = new Set(["mem-1"]);
    render(
      <MemoryList
        status="candidate"
        query=""
        topic=""
        selectedIds={selectedIds}
        selectedMemoryId={null}
        onSelectionChange={onSelectionChangeMock}
        onSelect={onSelectMock}
        refreshKey={0}
        notify={notifyMock}
      />
    );

    const batchDeleteBtn = screen.getByRole("button", { name: "一括削除" });
    await userEvent.click(batchDeleteBtn);

    expect(window.confirm).toHaveBeenCalledWith("1 件を完全に削除しますか？この操作は取り消せません。");
    await waitFor(() => {
      expect(mockBatchDeleteMemories).toHaveBeenCalledWith({
        memory_ids: ["mem-1"],
      });
      expect(notifyMock).toHaveBeenCalledWith("1 件を削除しました");
    });
  });

  it("sets data-selected correctly based on selectedMemoryId prop", async () => {
    render(
      <MemoryList
        status="candidate"
        query=""
        topic=""
        selectedIds={new Set()}
        selectedMemoryId="mem-1"
        onSelectionChange={onSelectionChangeMock}
        onSelect={onSelectMock}
        refreshKey={0}
        notify={notifyMock}
      />
    );

    await waitFor(() => {
      expect(screen.getByText("Memory 1 content")).toBeInTheDocument();
    });

    const rows = screen.getAllByTestId("memory-row");
    expect(rows[0]).toHaveAttribute("data-selected", "true");
    expect(rows[1]).toHaveAttribute("data-selected", "false");
  });
});
