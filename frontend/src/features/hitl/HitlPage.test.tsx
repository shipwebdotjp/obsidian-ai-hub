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

// Spy on date formatters while keeping the real implementation as the default,
// so new tests can assert call args / render output deterministically without
// breaking unrelated tests that rely on the real formatting.
vi.mock("../../utils/date", async () => {
  const actual = await vi.importActual<typeof import("../../utils/date")>("../../utils/date");
  return {
    formatDateTime: vi.fn(actual.formatDateTime),
    formatYmdWithDow: vi.fn(actual.formatYmdWithDow),
  };
});

import { listHitlRuns, getHitlRun, submitHitlAnswer, cancelHitlRun, ApiError } from "../../api/client";
import { formatDateTime, formatYmdWithDow } from "../../utils/date";

const mockListHitlRuns = vi.mocked(listHitlRuns);
const mockGetHitlRun = vi.mocked(getHitlRun);
const mockSubmitHitlAnswer = vi.mocked(submitHitlAnswer);
const mockCancelHitlRun = vi.mocked(cancelHitlRun);
const mockFormatDateTime = vi.mocked(formatDateTime);
const mockFormatYmdWithDow = vi.mocked(formatYmdWithDow);

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
      context: {
        type: "research_suggestion",
        theme: "AIエージェントの未来",
        direction: "実務での活用方法を整理する",
        why_now: "最近の業務で検討が必要になったため",
      },
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
    expect(screen.getAllByText("AIエージェントの未来")).toHaveLength(3); // sidebar, detail heading, and suggestion context
    expect(screen.getByText("リサーチテーマを承認しますか？")).toBeInTheDocument();
    expect(screen.getByTestId("research-suggestion-context")).toHaveTextContent("テーマ: AIエージェントの未来");
    expect(screen.getByTestId("research-suggestion-context")).toHaveTextContent("調査の方向: 実務での活用方法を整理する");
    expect(screen.getByTestId("research-suggestion-context")).toHaveTextContent("今調べる理由: 最近の業務で検討が必要になったため");

    // Verify select type choices render (using structured labels)
    expect(screen.getByText("調査を実行する")).toBeInTheDocument();
    expect(screen.getByText("今回は見送る")).toBeInTheDocument();
  });

  it("omits an empty why_now from research suggestion context", async () => {
    mockGetHitlRun.mockResolvedValue({
      ...sampleDetail1,
      questions: [
        {
          ...sampleDetail1.questions[0],
          context: {
            type: "research_suggestion",
            theme: "AIエージェントの未来",
            direction: "実務での活用方法を整理する",
            why_now: null,
          },
        },
      ],
    } as any);
    renderPage(["/hitl?run_id=hrun-1"]);

    const context = await screen.findByTestId("research-suggestion-context");
    expect(context).toHaveTextContent("テーマ: AIエージェントの未来");
    expect(context).toHaveTextContent("調査の方向: 実務での活用方法を整理する");
    expect(context).not.toHaveTextContent("今調べる理由");
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
      expect(screen.getAllByText("AIエージェントの未来")).toHaveLength(3);
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
      expect(screen.getAllByText("AIエージェントの未来")).toHaveLength(3);
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
      expect(screen.getAllByText("AIエージェントの未来")).toHaveLength(3);
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
      expect(screen.getAllByText("AIエージェントの未来")).toHaveLength(3);
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
      expect(screen.getAllByText("AIエージェントの未来")).toHaveLength(3);
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

  it("returns to the list from the mobile detail view via the back button", async () => {
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
    expect(screen.getByText("一覧から確認待ちタスクを選択してください。")).toBeInTheDocument();

    fireEvent.click(screen.getByText("AIエージェントの未来"));

    await waitFor(() => {
      const sp = new URLSearchParams(screen.getByTestId("probe-full-search").textContent || "");
      expect(sp.get("run_id")).toBe("hrun-1");
      expect(sp.get("foo")).toBe("bar");
    });
    await waitFor(() => {
      expect(mockGetHitlRun).toHaveBeenCalledWith("hrun-1");
    });
    expect(screen.queryByText("一覧から確認待ちタスクを選択してください。")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "一覧に戻る" }));

    await waitFor(() => {
      const sp = new URLSearchParams(screen.getByTestId("probe-full-search").textContent || "");
      expect(sp.has("run_id")).toBe(false);
      expect(sp.get("foo")).toBe("bar");
    });
    await waitFor(() => {
      expect(screen.getByText("一覧から確認待ちタスクを選択してください。")).toBeInTheDocument();
    });
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

  it("preserves drafts of other pending questions when one answer is submitted", async () => {
    const sampleDetailFreeText = {
      run_id: "hrun-ft",
      handler: "dummy_handler",
      status: "pending_user",
      title: "Free Text",
      display_title: "Free Text",
      display_type: "進捗確認",
      created_at: "2026-07-20T12:00:00Z",
      questions: [
        {
          question_id: "q-f1",
          question_key: "q1",
          question_type: "text",
          display_text: "質問1",
          is_required: 0,
          status: "pending",
        },
        {
          question_id: "q-f2",
          question_key: "q2",
          question_type: "text",
          display_text: "質問2",
          is_required: 0,
          status: "pending",
        },
      ],
    };
    mockGetHitlRun.mockResolvedValue(sampleDetailFreeText as any);
    mockSubmitHitlAnswer.mockResolvedValue({ success: true });

    renderPage(["/hitl?run_id=hrun-ft"]);

    await waitFor(() => {
      expect(screen.getAllByPlaceholderText("回答を入力してください…")).toHaveLength(2);
    });

    const answerTextareas = screen.getAllByPlaceholderText("回答を入力してください…");
    fireEvent.change(answerTextareas[0], { target: { value: "first draft" } });
    fireEvent.change(answerTextareas[1], { target: { value: "second draft" } });

    const submitBtns = screen.getAllByRole("button", { name: "回答を送信" });
    fireEvent.click(submitBtns[0]);

    await waitFor(() => {
      expect(mockSubmitHitlAnswer).toHaveBeenCalledWith("hrun-ft", "q1", "first draft", null);
    });

    // The detail is reloaded after submit; the untouched draft must survive.
    await waitFor(() => {
      expect(mockGetHitlRun).toHaveBeenCalledTimes(2);
    });
    await waitFor(() => {
      const textareasAfterReload = screen.getAllByPlaceholderText("回答を入力してください…");
      expect(textareasAfterReload[1]).toHaveValue("second draft");
    });
  });

  describe("calendar/reminder context rendering", () => {
    const calendarContext = {
      type: "calendar_event",
      event: {
        title: "MTG",
        start_time: "2026-08-22T09:00:00Z",
        end_time: "2026-08-22T10:00:00Z",
        location: "Room A",
      },
      content: "Discuss plans",
    } as any;

    it("renders calendar event start/end times via formatDateTime", async () => {
      mockGetHitlRun.mockResolvedValue({
        ...sampleDetail1,
        questions: [
          {
            ...sampleDetail1.questions[0],
            context: calendarContext,
          },
        ],
      } as any);

      renderPage();
      await waitFor(() => {
        expect(screen.getByText("AIエージェントの未来")).toBeInTheDocument();
      });
      fireEvent.click(screen.getByText("AIエージェントの未来"));

      const ctx = await screen.findByTestId("calendar-event-context");
      expect(ctx).toHaveTextContent("タイトル: MTG");
      expect(mockFormatDateTime).toHaveBeenCalledWith("2026-08-22T09:00:00Z");
      expect(mockFormatDateTime).toHaveBeenCalledWith("2026-08-22T10:00:00Z");
      expect(ctx).toHaveTextContent(/開始: 2026\/08\/22\(土\) \d{2}:\d{2}/);
      expect(ctx).toHaveTextContent(/終了: 2026\/08\/22\(土\) \d{2}:\d{2}/);
      expect(ctx).toHaveTextContent("場所: Room A");
      expect(ctx).toHaveTextContent("元の内容: Discuss plans");
    });

    it("renders reminder due_date as YMD via formatYmdWithDow", async () => {
      mockGetHitlRun.mockResolvedValue({
        ...sampleDetail1,
        questions: [
          {
            ...sampleDetail1.questions[0],
            context: {
              type: "reminder",
              reminder: { title: "Pay bills", due_date: "2026-08-22" },
              content: "Don't forget",
            },
          },
        ],
      } as any);

      renderPage();
      await waitFor(() => {
        expect(screen.getByText("AIエージェントの未来")).toBeInTheDocument();
      });
      fireEvent.click(screen.getByText("AIエージェントの未来"));

      const ctx = await screen.findByTestId("reminder-context");
      expect(ctx).toHaveTextContent("タイトル: Pay bills");
      expect(mockFormatYmdWithDow).toHaveBeenCalledWith("2026-08-22");
      expect(mockFormatDateTime).not.toHaveBeenCalledWith("2026-08-22");
      expect(ctx).toHaveTextContent("期限: 2026/08/22(土)");
      expect(ctx).toHaveTextContent("元の内容: Don't forget");
    });

    it("renders reminder due_date via formatDateTime when value is not YMD-shaped", async () => {
      mockGetHitlRun.mockResolvedValue({
        ...sampleDetail1,
        questions: [
          {
            ...sampleDetail1.questions[0],
            context: {
              type: "reminder",
              reminder: { title: "Call", due_date: "2026-08-22T09:00:00Z" },
            },
          },
        ],
      } as any);

      renderPage();
      await waitFor(() => {
        expect(screen.getByText("AIエージェントの未来")).toBeInTheDocument();
      });
      fireEvent.click(screen.getByText("AIエージェントの未来"));

      const ctx = await screen.findByTestId("reminder-context");
      expect(mockFormatDateTime).toHaveBeenCalledWith("2026-08-22T09:00:00Z");
      expect(mockFormatYmdWithDow).not.toHaveBeenCalled();
      expect(ctx).toHaveTextContent(/期限: 2026\/08\/22\(土\) \d{2}:\d{2}/);
    });

    it("omits the date row when start_time/end_time/due_date are missing", async () => {
      mockGetHitlRun.mockResolvedValue({
        ...sampleDetail1,
        questions: [
          {
            ...sampleDetail1.questions[0],
            context: {
              type: "calendar_event",
              event: { title: "MTG", start_time: undefined, end_time: null, location: null },
            },
          },
        ],
      } as any);

      renderPage();
      await waitFor(() => {
        expect(screen.getByText("AIエージェントの未来")).toBeInTheDocument();
      });
      fireEvent.click(screen.getByText("AIエージェントの未来"));

      const ctx = await screen.findByTestId("calendar-event-context");
      expect(ctx).toHaveTextContent("タイトル: MTG");
      expect(ctx).not.toHaveTextContent("開始:");
      expect(ctx).not.toHaveTextContent("終了:");
      expect(mockFormatDateTime).not.toHaveBeenCalledWith(expect.stringMatching(/^2026-08-22/));
    });
  });

  describe("in_conversation_question (ASK) handling", () => {
    it("displays 'ASK' badge instead of 'in_conversation_question' in both list and detail header", async () => {
      mockListHitlRuns.mockResolvedValue({
        items: [
          {
            run_id: "hrun-ask-1",
            handler: "agents.ask_user",
            status: "completed",
            created_at: "2026-09-05T10:00:00Z",
            title: "会話内要件確認",
            display_title: "会話内要件確認",
            display_type: "in_conversation_question",
          },
        ],
        total: 1,
      } as any);
      mockGetHitlRun.mockResolvedValue({
        run_id: "hrun-ask-1",
        handler: "agents.ask_user",
        status: "completed",
        title: "会話内要件確認",
        display_title: "会話内要件確認",
        display_type: "in_conversation_question",
        questions: [
          {
            question_id: "q-1",
            question_key: "target",
            display_text: "対象範囲を選択してください",
            choices: [{ value: "backend", label: "バックエンド" }],
            answer: { value: "backend" },
            status: "answered",
          },
        ],
      } as any);

      renderPage(["/hitl?run_id=hrun-ask-1"]);

      await waitFor(() => {
        expect(screen.getAllByText("会話内要件確認").length).toBeGreaterThanOrEqual(1);
      });

      // Both list badge and detail badge should show "ASK"
      const askBadges = screen.getAllByText("ASK");
      expect(askBadges.length).toBeGreaterThanOrEqual(2);
      expect(screen.queryByText("in_conversation_question")).not.toBeInTheDocument();
    });

    it("renders answered in-conversation question as read-only card and omits empty question form", async () => {
      mockListHitlRuns.mockResolvedValue({ items: [], total: 0 } as any);
      mockGetHitlRun.mockResolvedValue({
        run_id: "hrun-ask-completed",
        handler: "agents.ask_user",
        status: "completed",
        title: "要件ヒアリング",
        display_title: "要件ヒアリング",
        display_type: "in_conversation_question",
        questions: [
          {
            question_id: "q-1",
            question_key: "scope",
            display_text: "対象範囲を選択してください",
            choices: [
              { value: "backend", label: "バックエンド" },
              { value: "other", label: "その他（自由入力）" },
            ],
            answer: { value: "other", comment: "クラウドインフラを含む" },
            status: "answered",
          },
        ],
      } as any);

      renderPage(["/hitl?run_id=hrun-ask-completed"]);

      await waitFor(() => {
        expect(screen.getByTestId("answered-in-conversation-card")).toBeInTheDocument();
      });

      expect(screen.getByText("✅ 回答済み要件確認")).toBeInTheDocument();
      expect(screen.getByText("対象範囲を選択してください")).toBeInTheDocument();
      expect(screen.getByText("その他（自由入力）")).toBeInTheDocument();
      expect(screen.getByText("クラウドインフラを含む")).toBeInTheDocument();

      // Ensure no unanswered form (WaitingRunQuestionCard) is rendered
      expect(screen.queryByText("回答を送信")).not.toBeInTheDocument();
      expect(screen.queryByText("要件確認・選択のお願い")).not.toBeInTheDocument();
    });

    it("renders answered history for ready_to_resume, failed, and cancelled runs", async () => {
      for (const st of ["ready_to_resume", "failed", "cancelled"]) {
        mockGetHitlRun.mockResolvedValue({
          run_id: `hrun-ask-${st}`,
          handler: "agents.ask_user",
          status: st,
          title: "テスト",
          display_title: "テスト",
          display_type: "in_conversation_question",
          questions: [
            {
              question_id: "q-1",
              question_key: "target",
              display_text: "テスト質問",
              choices: [{ value: "v1", label: "ラベル1" }],
              answer: { value: "v1" },
              status: "answered",
            },
          ],
        } as any);

        const { unmount } = renderPage([`/hitl?run_id=hrun-ask-${st}`]);

        await waitFor(() => {
          expect(screen.getByTestId("answered-in-conversation-card")).toBeInTheDocument();
        });
        expect(screen.getByText("ラベル1")).toBeInTheDocument();

        unmount();
      }
    });

    it("renders answered history first and pending form below when questions are mixed", async () => {
      mockGetHitlRun.mockResolvedValue({
        run_id: "hrun-ask-mixed",
        handler: "agents.ask_user",
        status: "pending_user",
        title: "複数質問",
        display_title: "複数質問",
        display_type: "in_conversation_question",
        questions: [
          {
            question_id: "q-1",
            question_key: "q1",
            display_text: "質問1（完了）",
            choices: [{ value: "opt1", label: "選択肢1" }],
            answer: { value: "opt1" },
            status: "answered",
          },
          {
            question_id: "q-2",
            question_key: "q2",
            display_text: "質問2（未回答）",
            choices: [{ value: "optA", label: "選択肢A" }],
            status: "pending",
          },
        ],
      } as any);

      renderPage(["/hitl?run_id=hrun-ask-mixed"]);

      await waitFor(() => {
        expect(screen.getByTestId("answered-in-conversation-card")).toBeInTheDocument();
      });

      // Answered card content
      expect(screen.getByText("質問1（完了）")).toBeInTheDocument();
      expect(screen.getByText("選択肢1")).toBeInTheDocument();

      // Pending question form content
      expect(screen.getByText(/要件確認・選択のお願い/)).toBeInTheDocument();
      expect(screen.getByText("質問2（未回答）")).toBeInTheDocument();
      expect(screen.getByText("選択肢A")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "回答を送信" })).toBeInTheDocument();
    });
  });
});
