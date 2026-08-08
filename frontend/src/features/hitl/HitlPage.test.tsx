import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useSearchParams } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
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
      title: "AIエージェントの未来",
      display_title: "AIエージェントの未来",
      display_type: "リサーチ提案",
      description: "自動提案されたリサーチテーマの承認",
    },
    {
      run_id: "hrun-2",
      handler: "dummy_handler",
      status: "cancelled",
      created_at: "2026-07-20T11:00:00Z",
      title: "Boolean Test",
      display_title: "Boolean Test",
      display_type: "進捗確認",
      description: "Boolean type rendering test",
    },
  ],
  total: 2,
};

const sampleDetail1 = {
  run_id: "hrun-1",
  handler: "research.run_approved_suggestion",
  status: "pending_user",
  title: "AIエージェントの未来",
  display_title: "AIエージェントの未来",
  display_type: "リサーチ提案",
  description: "自動提案されたリサーチテーマの承認",
  created_at: "2026-07-20T10:00:00Z",
  questions: [
    {
      question_id: "q-1",
      question_key: "action",
      question_type: "select",
      display_text: "リサーチテーマを承認しますか？",
      choices: [
        { value: "approve", label: "調査を実行する", description: "承認してリサーチを実行します" },
        { value: "reject", label: "今回は見送る", description: "却下して見送ります" }
      ],
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
  display_title: "Boolean Test",
  display_type: "進捗確認",
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

function renderPage(initialEntries: string[] = ["/hitl"]) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <HitlPage />
    </MemoryRouter>
  );
}

function RouterProbe({ children }: { children: React.ReactNode }) {
  const [sp] = useSearchParams();
  return (
    <>
      <div data-testid="probe-full-search">{sp.toString()}</div>
      {children}
    </>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockListHitlRuns.mockResolvedValue(sampleRuns as any);
  mockGetHitlRun.mockResolvedValue(sampleDetail1 as any);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("HitlPage", () => {
  it("initial load fetches and lists hitl runs with default status pending_user", async () => {
    renderPage();

    await waitFor(() => {
      expect(mockListHitlRuns).toHaveBeenCalledWith({
        status: "pending_user",
        limit: 100,
      });
    });

    // Verify runs render
    expect(screen.getByText("AIエージェントの未来")).toBeInTheDocument();
    expect(screen.getByText("リサーチ提案")).toBeInTheDocument();
  });

  it("filters runs by status when dropdown changes", async () => {
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("AIエージェントの未来")).toBeInTheDocument();
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
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("AIエージェントの未来")).toBeInTheDocument();
    });

    // Click the first row to select it
    const row = screen.getByText("AIエージェントの未来");
    fireEvent.click(row);

    await waitFor(() => {
      expect(mockGetHitlRun).toHaveBeenCalledWith("hrun-1");
    });

    // Check title and description render
    expect(screen.getAllByText("AIエージェントの未来")).toHaveLength(2); // one in sidebar, one in detail top
    expect(screen.getByText("リサーチテーマを承認しますか？")).toBeInTheDocument();

    // Verify select type choices render (using structured labels)
    expect(screen.getByText("調査を実行する")).toBeInTheDocument();
    expect(screen.getByText("今回は見送る")).toBeInTheDocument();
  });

  it("initializes boolean questions to true by default", async () => {
    mockGetHitlRun.mockResolvedValue(sampleDetail2 as any);
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("AIエージェントの未来")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("AIエージェントの未来"));

    await waitFor(() => {
      expect(screen.getByText("Boolean Test")).toBeInTheDocument();
    });

    // Boolean radio for "はい (True)" should be checked initially
    const radioTrue = screen.getByLabelText("はい (True)") as HTMLInputElement;
    expect(radioTrue.checked).toBe(true);
  });

  it("validates required questions and prevents API call when empty", async () => {
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("AIエージェントの未来")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("AIエージェントの未来"));

    await waitFor(() => {
      expect(screen.getAllByText("AIエージェントの未来")).toHaveLength(2);
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

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("AIエージェントの未来")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("AIエージェントの未来"));

    await waitFor(() => {
      expect(screen.getAllByText("AIエージェントの未来")).toHaveLength(2);
    });

    // Initial getHitlRun from row selection
    expect(mockGetHitlRun).toHaveBeenCalledTimes(1);

    // Select choice 'approve'
    const approveBtn = screen.getByText("調査を実行する");
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

    // After successful submit the page should refetch the run detail
    await waitFor(() => {
      expect(mockGetHitlRun).toHaveBeenCalledTimes(2);
    });
    expect(mockGetHitlRun).toHaveBeenLastCalledWith("hrun-1");
  });

  it("displays detail error if submitHitlAnswer fails with ApiError", async () => {
    mockSubmitHitlAnswer.mockRejectedValue(new ApiError(400, "Bad Request Answer"));

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("AIエージェントの未来")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("AIエージェントの未来"));

    await waitFor(() => {
      expect(screen.getAllByText("AIエージェントの未来")).toHaveLength(2);
    });

    // Choose 'approve'
    fireEvent.click(screen.getByText("調査を実行する"));

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

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("AIエージェントの未来")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("AIエージェントの未来"));

    await waitFor(() => {
      expect(screen.getAllByText("AIエージェントの未来")).toHaveLength(2);
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

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("AIエージェントの未来")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("AIエージェントの未来"));

    await waitFor(() => {
      expect(screen.getAllByText("AIエージェントの未来")).toHaveLength(2);
    });

    const cancelBtn = screen.getByRole("button", { name: "実行全体をキャンセル" });
    fireEvent.click(cancelBtn);

    expect(confirmSpy).toHaveBeenCalled();
    expect(mockCancelHitlRun).not.toHaveBeenCalled();
  });

  it("loads the detail pane for the run given by ?run_id= deep link", async () => {
    mockGetHitlRun.mockResolvedValue(sampleDetail2 as any);
    renderPage(["/hitl?run_id=hrun-2"]);

    await waitFor(() => {
      expect(mockGetHitlRun).toHaveBeenCalledWith("hrun-2");
    });

    expect(await screen.findByText("進めますか？")).toBeInTheDocument();
  });

  it("shows an error when the deep-linked run cannot be fetched", async () => {
    mockGetHitlRun.mockRejectedValue(new ApiError(404, "Not Found"));

    renderPage(["/hitl?run_id=missing"]);

    await waitFor(() => {
      expect(screen.getByText("Not Found")).toBeInTheDocument();
    });
  });

  it("does not fetch detail on mount without a ?run_id= parameter", async () => {
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("AIエージェントの未来")).toBeInTheDocument();
    });

    expect(mockGetHitlRun).not.toHaveBeenCalled();
  });

  it("syncs the ?run_id= parameter to the URL when a row is selected", async () => {
    render(
      <MemoryRouter initialEntries={["/hitl?foo=bar"]}>
        <RouterProbe>
          <HitlPage />
        </RouterProbe>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("AIエージェントの未来")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("AIエージェントの未来"));

    await waitFor(() => {
      const sp = new URLSearchParams(screen.getByTestId("probe-full-search").textContent || "");
      expect(sp.get("run_id")).toBe("hrun-1");
      expect(sp.get("foo")).toBe("bar");
    });

    await waitFor(() => {
      expect(mockGetHitlRun).toHaveBeenCalledWith("hrun-1");
    });
  });

  it("refetches the detail when the same selected row is clicked again", async () => {
    renderPage();

    const firstRow = () => screen.getAllByTestId("hitl-run-row")[0] as HTMLElement;
    await waitFor(() => {
      expect(screen.getByText("AIエージェントの未来")).toBeInTheDocument();
    });

    fireEvent.click(firstRow());
    await waitFor(() => {
      expect(mockGetHitlRun).toHaveBeenCalledTimes(1);
    });

    fireEvent.click(firstRow());
    await waitFor(() => {
      expect(mockGetHitlRun).toHaveBeenCalledTimes(2);
    });
    expect(mockGetHitlRun).toHaveBeenLastCalledWith("hrun-1");
  });
});
