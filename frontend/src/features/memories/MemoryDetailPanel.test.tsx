import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import MemoryDetailPanel from "./MemoryDetailPanel";

vi.mock("../../api/client", () => ({
  getMemory: vi.fn(),
  reviewMemory: vi.fn(),
  resolveMemory: vi.fn(),
  deleteMemory: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

import { getMemory, reviewMemory, deleteMemory, ApiError } from "../../api/client";

const mockGetMemory = vi.mocked(getMemory);
const mockReviewMemory = vi.mocked(reviewMemory);
const mockDeleteMemory = vi.mocked(deleteMemory);

const sampleDetail1 = {
  memory_id: "mem-1",
  content: "Stretch for 10 mins",
  kind: "fact",
  status: "candidate",
  created_at: "2026-07-20T10:00:00Z",
  evidence: [],
  events: [],
};

const sampleDetail2 = {
  memory_id: "mem-2",
  content: "Drink water regularly",
  kind: "fact",
  status: "candidate",
  created_at: "2026-07-20T11:00:00Z",
  evidence: [],
  events: [],
};

const notifyMock = vi.fn();
const onChangedMock = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
});

describe("MemoryDetailPanel", () => {
  it("renders detail successfully", async () => {
    mockGetMemory.mockResolvedValue(sampleDetail1 as any);

    render(
      <MemoryDetailPanel
        memoryId="mem-1"
        status="candidate"
        onChanged={onChangedMock}
        notify={notifyMock}
      />
    );

    await waitFor(() => {
      expect(screen.getByText("Stretch for 10 mins")).toBeInTheDocument();
    });
    expect(screen.getByText("status: candidate")).toBeInTheDocument();
  });

  it("handles getMemory failure gracefully and displays the error", async () => {
    mockGetMemory.mockRejectedValue(new ApiError(500, "API Server Error"));

    render(
      <MemoryDetailPanel
        memoryId="mem-1"
        status="candidate"
        onChanged={onChangedMock}
        notify={notifyMock}
      />
    );

    await waitFor(() => {
      expect(screen.getByText("API Server Error")).toBeInTheDocument();
    });
  });

  it("ignores/suppresses out-of-order detailed API responses when memoryId changes", async () => {
    let resolve1: any;
    let resolve2: any;

    const promise1 = new Promise<any>((resolve) => {
      resolve1 = resolve;
    });
    const promise2 = new Promise<any>((resolve) => {
      resolve2 = resolve;
    });

    // Setup mock to return promise1 on first call, promise2 on second call
    mockGetMemory
      .mockReturnValueOnce(promise1)
      .mockReturnValueOnce(promise2);

    const { rerender } = render(
      <MemoryDetailPanel
        memoryId="mem-1"
        status="candidate"
        onChanged={onChangedMock}
        notify={notifyMock}
      />
    );

    // Promptly change memoryId to mem-2
    rerender(
      <MemoryDetailPanel
        memoryId="mem-2"
        status="candidate"
        onChanged={onChangedMock}
        notify={notifyMock}
      />
    );

    // Resolve promise2 (mem-2) first
    resolve2(sampleDetail2);
    await waitFor(() => {
      expect(screen.getByText("Drink water regularly")).toBeInTheDocument();
    });

    // Now resolve promise1 (mem-1) afterwards
    resolve1(sampleDetail1);

    // The detail panel should STILL display mem-2 (not overwritten by the stale promise1)
    // Flush pending microtasks before asserting the absence of the stale text
    await waitFor(() => {
      expect(screen.queryByText("Stretch for 10 mins")).not.toBeInTheDocument();
    });
    expect(screen.getByText("Drink water regularly")).toBeInTheDocument();
  });

  it("renders consolidated candidate badge and source details", async () => {
    const consolidatedDetail = {
      memory_id: "mem-consolidated",
      content: "Consolidated memory content",
      kind: "preference",
      status: "candidate",
      created_at: "2026-08-01T10:00:00Z",
      provenance: {
        consolidation: {
          source_candidate_ids: ["mem-src-1", "mem-src-2"],
          target_memory_id: "mem-target-1",
        },
      },
      dedup_assessment: {
        decision: "merge",
        target_memory_id: "mem-target-1",
        target_fingerprint: "fp-mock-123",
        reason: "Merged two preference candidates",
      },
      evidence: [{ path: "test://path", quote: "Sample quote" }],
      events: [],
    };

    mockGetMemory.mockResolvedValue(consolidatedDetail as any);

    render(
      <MemoryDetailPanel
        memoryId="mem-consolidated"
        status="candidate"
        onChanged={onChangedMock}
        notify={notifyMock}
      />
    );

    await waitFor(() => {
      expect(screen.getByText(/統合候補 \(元候補 2件\)/)).toBeInTheDocument();
    });
    expect(screen.getByText("mem-src-1, mem-src-2")).toBeInTheDocument();
    expect(screen.getByText("Merged two preference candidates")).toBeInTheDocument();
  });
});
