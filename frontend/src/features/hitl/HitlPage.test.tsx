import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import HitlPage from "./HitlPage";

// Mock the API client
vi.mock("../../api/client", () => ({
  listHitlRuns: vi.fn(),
  getHitlRun: vi.fn(),
  submitHitlAnswer: vi.fn(),
  cancelHitlRun: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

import { listHitlRuns, getHitlRun, submitHitlAnswer, cancelHitlRun, ApiError } from "../../api/client";

const mockListHitlRuns = vi.mocked(listHitlRuns);
const mockGetHitlRun = vi.mocked(getHitlRun);
const mockSubmitHitlAnswer = vi.mocked(submitHitlAnswer);
const mockCancelHitlRun = vi.mocked(cancelHitlRun);

const sampleRuns = {
  items: [
    {
      run_id: "hrun-1",
      handler: "research.run_approved_suggestion",
      status: "pending_user",
      created_at: "2026-07-20T10:00:00Z",
    },
    {
      run_id: "hrun-2",
      handler: "dummy_handler",
      status: "cancelled",
      created_at: "2026-07-20T11:00:00Z",
    },
  ],
  total: 2,
};

const sampleDetail1 = {
  run_id: "hrun-1",
  handler: "research.run_approved_suggestion",
  status: "pending_user",
  title: "AIエージェントの未来",
  description: "自動提案されたリサーチテーマの承認",
  created_at: "2026-07-20T10:00:00Z",
  questions: [
    {
      question_id: "q-1",
      question_key: "action",
      question_type: "select",
      display_text: "リサーチテーマを承認しますか？",
      choices: ["approve", "reject"],
      is_required: 1,
      status: "pending",
    },
    {
      question_id: "q-2",
      question_key: "notes",
      question_type: "text",
      display_text: "補足メモがあれば入力してください（任意）",
      is_required: 0,
      status: "pending",
    },
  ],
};

const sampleDetail2 = {
  run_id: "hrun-3",
  handler: "dummy_handler",
  status: "pending_user",
  title: "Boolean Test",
  description: "Boolean type rendering test",
  created_at: "2026-07-20T12:00:00Z",
  questions: [
    {
      question_id: "q-3",
      question_key: "boolean_q",
      question_type: "boolean",
      display_text: "進めますか？",
      choices: [true, false],
      is_required: 1,
      status: "pending",
    },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  mockListHitlRuns.mockResolvedValue(sampleRuns as any);
  mockGetHitlRun.mockResolvedValue(sampleDetail1 as any);
});

describe("HitlPage", () => {
  it("initial load fetches and lists hitl runs with default status pending_user", async () => {
    render(<HitlPage />);

    await waitFor(() => {
      expect(mockListHitlRuns).toHaveBeenCalledWith({
        status: "pending_user",
        limit: 100,
      });
    });

    // Verify runs render
    expect(screen.getByText("hrun-1")).toBeInTheDocument();
    expect(screen.getByText("Handler: research.run_approved_suggestion")).toBeInTheDocument();
  });

  it("filters runs by status when dropdown changes", async () => {
    render(<HitlPage />);

    await waitFor(() => {
      expect(screen.getByText("hrun-1")).toBeInTheDocument();
    });

    const filterSelect = screen.getByLabelText("ステータスフィルター");
    mockListHitlRuns.mockResolvedValue({ items: [], total: 0 } as any);

    fireEvent.change(filterSelect, { target: { value: "all" } });

    await waitFor(() => {
      expect(mockListHitlRuns).toHaveBeenLastCalledWith({
        status: undefined,
        limit: 100,
      });
    });
  });

  it("selects a run and initializes question answers", async () => {
    render(<HitlPage />);

    await waitFor(() => {
      expect(screen.getByText("hrun-1")).toBeInTheDocument();
    });

    // Click the first row to select it
    const row = screen.getByText("hrun-1");
    fireEvent.click(row);

    await waitFor(() => {
      expect(mockGetHitlRun).toHaveBeenCalledWith("hrun-1");
    });

    // Check title and description render
    expect(screen.getByText("AIエージェントの未来")).toBeInTheDocument();
    expect(screen.getByText("リサーチテーマを承認しますか？")).toBeInTheDocument();

    // Verify select type choices render
    expect(screen.getByRole("button", { name: "approve" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "reject" })).toBeInTheDocument();
  });

  it("initializes boolean questions to true by default", async () => {
    mockGetHitlRun.mockResolvedValue(sampleDetail2 as any);
    render(<HitlPage />);

    await waitFor(() => {
      expect(screen.getByText("hrun-1")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("hrun-1"));

    await waitFor(() => {
      expect(screen.getByText("Boolean Test")).toBeInTheDocument();
    });

    // Boolean radio for "はい (True)" should be checked initially
    const radioTrue = screen.getByLabelText("はい (True)") as HTMLInputElement;
    expect(radioTrue.checked).toBe(true);
  });

  it("validates required questions and prevents API call when empty", async () => {
    render(<HitlPage />);

    await waitFor(() => {
      expect(screen.getByText("hrun-1")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("hrun-1"));

    await waitFor(() => {
      expect(screen.getByText("AIエージェントの未来")).toBeInTheDocument();
    });

    // Submit answer without choosing 'approve' or 'reject'
    const submitBtn = screen.getAllByRole("button", { name: "回答を送信" })[0];
    fireEvent.click(submitBtn);

    // Validation message should appear
    await waitFor(() => {
      expect(screen.getByText("リサーチテーマを承認しますか？ の回答は必須です。")).toBeInTheDocument();
    });
    expect(mockSubmitHitlAnswer).not.toHaveBeenCalled();
  });

  it("submits answer successfully and reloads run details", async () => {
    mockSubmitHitlAnswer.mockResolvedValue({ success: true });

    render(<HitlPage />);

    await waitFor(() => {
      expect(screen.getByText("hrun-1")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("hrun-1"));

    await waitFor(() => {
      expect(screen.getByText("AIエージェントの未来")).toBeInTheDocument();
    });

    // Select choice 'approve'
    const approveBtn = screen.getByRole("button", { name: "approve" });
    fireEvent.click(approveBtn);

    // Submit
    const submitBtn = screen.getAllByRole("button", { name: "回答を送信" })[0];
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(mockSubmitHitlAnswer).toHaveBeenCalledWith(
        "hrun-1",
        "action",
        "approve",
        null
      );
    });
  });

  it("displays detail error if submitHitlAnswer fails with ApiError", async () => {
    mockSubmitHitlAnswer.mockRejectedValue(new ApiError(400, "Bad Request Answer"));

    render(<HitlPage />);

    await waitFor(() => {
      expect(screen.getByText("hrun-1")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("hrun-1"));

    await waitFor(() => {
      expect(screen.getByText("AIエージェントの未来")).toBeInTheDocument();
    });

    // Choose 'approve'
    fireEvent.click(screen.getByRole("button", { name: "approve" }));

    // Submit
    const submitBtn = screen.getAllByRole("button", { name: "回答を送信" })[0];
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByText("Bad Request Answer")).toBeInTheDocument();
    });
  });

  it("handles run cancellation confirmation (acceptance)", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    mockCancelHitlRun.mockResolvedValue({ success: true });

    render(<HitlPage />);

    await waitFor(() => {
      expect(screen.getByText("hrun-1")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("hrun-1"));

    await waitFor(() => {
      expect(screen.getByText("AIエージェントの未来")).toBeInTheDocument();
    });

    const cancelBtn = screen.getByRole("button", { name: "実行全体をキャンセル" });
    fireEvent.click(cancelBtn);

    expect(confirmSpy).toHaveBeenCalledWith("この確認タスクの実行全体をキャンセルしますか？");
    await waitFor(() => {
      expect(mockCancelHitlRun).toHaveBeenCalledWith("hrun-1");
    });
  });

  it("handles run cancellation confirmation (refusal)", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);

    render(<HitlPage />);

    await waitFor(() => {
      expect(screen.getByText("hrun-1")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("hrun-1"));

    await waitFor(() => {
      expect(screen.getByText("AIエージェントの未来")).toBeInTheDocument();
    });

    const cancelBtn = screen.getByRole("button", { name: "実行全体をキャンセル" });
    fireEvent.click(cancelBtn);

    expect(confirmSpy).toHaveBeenCalled();
    expect(mockCancelHitlRun).not.toHaveBeenCalled();
  });
});
