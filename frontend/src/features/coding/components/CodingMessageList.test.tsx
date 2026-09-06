import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CodingMessageList } from "./CodingMessageList";
import type { CodingMessage } from "../../../api/coding";
import { formatDateTime } from "../../../utils/date";

const CLIPBOARD_PATH_D =
  "M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h12a2 2 0 002-2V7a2 2 0 00-2-2h-2M8 5a2 2 0 002 2h4a2 2 0 002-2M8 5a2 2 0 012-2h4a2 2 0 012 2";

function message(overrides: Partial<CodingMessage>): CodingMessage {
  return {
    message_id: "cmsg_1",
    session_id: "cses_1",
    sequence: 1,
    role: "user",
    content: "ユーザー発話の本文",
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

const baseProps = {
  loadingMessages: false,
  isStreaming: false,
  sessionDetail: {
    session: { session_id: "cses_1" },
    messages: [],
    runs: [],
    orchestrator_tool_calls: [],
    ask_user_answer_history: [],
  } as never,
  activeRun: null,
  latestRun: null,
  currentRun: null,
  activeWaitingRun: null,
  streamingToolCalls: [],
  activePhaseText: null,
  workerState: { status: "idle" as const },
  copiedMessageId: null,
  onSubmitWaitingAnswers: vi.fn(),
  onCancelWaitingRun: vi.fn(),
  messageEndRef: { current: null },
  backend: "opencode",
};

function clipboardPathOf(testId: string): string | null {
  const btn = screen.getByTestId(testId);
  return btn.querySelector("svg path")?.getAttribute("d") ?? null;
}

describe("CodingMessageList bubbles", () => {
  it("ユーザー発話にコピーボタンと日時が表示される", () => {
    const onCopy = vi.fn();
    render(
      <CodingMessageList
        {...baseProps}
        messages={[message({ message_id: "u1" })]}
        onCopyMessage={onCopy}
      />,
    );

    const btn = screen.getByTestId("copy-message-u1");
    expect(btn).toHaveAttribute("aria-label", "メッセージをコピー");
    expect(screen.getByText(formatDateTime("2026-01-01T00:00:00Z"))).toBeInTheDocument();
  });

  it("ユーザー発話のコピー対象が本文である", () => {
    const onCopy = vi.fn();
    render(
      <CodingMessageList
        {...baseProps}
        messages={[message({ message_id: "u1", content: "コピーされる本文" })]}
        onCopyMessage={onCopy}
      />,
    );

    fireEvent.click(screen.getByTestId("copy-message-u1"));
    expect(onCopy).toHaveBeenCalledWith("コピーされる本文", "u1");
  });

  it("コピー完了時は全バブルで同じ完了表現になる", () => {
    render(
      <CodingMessageList
        {...baseProps}
        messages={[message({ message_id: "u1" })]}
        copiedMessageId="u1"
        onCopyMessage={vi.fn()}
      />,
    );

    expect(screen.getByText("コピーしました")).toBeInTheDocument();
  });

  it("全バブルがAI ORCHESTRATORと同じクリップボードアイコンを使う", () => {
    render(
      <CodingMessageList
        {...baseProps}
        messages={[
          message({ message_id: "u1", role: "user", content: "user" }),
          message({ message_id: "o1", role: "orchestrator", content: "orch" }),
          message({ message_id: "c1", role: "cli_request", content: "cli" }),
          message({ message_id: "w1", role: "worker", content: "work" }),
        ]}
        onCopyMessage={vi.fn()}
      />,
    );

    for (const id of ["u1", "o1", "c1", "w1"]) {
      expect(clipboardPathOf(`copy-message-${id}`)).toBe(CLIPBOARD_PATH_D);
    }
  });

  it("CLI Workerへの指示の先頭に絵文字がなくトグルが矢印表示になる", () => {
    render(
      <CodingMessageList
        {...baseProps}
        messages={[message({ message_id: "c1", role: "cli_request", content: "git status" })]}
        onCopyMessage={vi.fn()}
      />,
    );

    const card = screen.getByTestId("cli-request-card");
    expect(card).toBeInTheDocument();
    expect(card).not.toHaveAttribute("open");
    expect(screen.queryByText(/🤖/)).not.toBeInTheDocument();
    expect(screen.getByText("CLI Workerへの指示")).toBeInTheDocument();
    expect(screen.getByText("▼")).toBeInTheDocument();
    expect(screen.getByText("▲")).toBeInTheDocument();
    // アクセシブルな説明は sr-only で保持される
    expect(screen.getByText("クリックで展開/折りたたみ")).toBeInTheDocument();
  });

  it("CLI Worker最終返答のトグルが矢印表示になる", () => {
    render(
      <CodingMessageList
        {...baseProps}
        messages={[message({ message_id: "w1", role: "worker", content: "done" })]}
        onCopyMessage={vi.fn()}
      />,
    );

    expect(screen.getByText(/CLI Worker 最終返答/)).toBeInTheDocument();
    expect(screen.getByText("▼")).toBeInTheDocument();
    expect(screen.getByText("▲")).toBeInTheDocument();
  });
  it("展開・折りたたみ操作が壊れていない", () => {
    render(
      <CodingMessageList
        {...baseProps}
        messages={[message({ message_id: "c1", role: "cli_request", content: "git status" })]}
        onCopyMessage={vi.fn()}
      />,
    );

    const card = screen.getByTestId("cli-request-card");
    const summary = card.querySelector("summary");
    expect(summary).not.toBeNull();
    if (summary) {
      fireEvent.click(summary);
      expect(card).toHaveAttribute("open");
      fireEvent.click(summary);
      expect(card).not.toHaveAttribute("open");
    }
  });

  it("再読み込み中も既存メッセージを維持し高さを潰さない", () => {
    render(
      <CodingMessageList
        {...baseProps}
        messages={[message({ message_id: "u1", content: "維持される本文" })]}
        loadingMessages
        onCopyMessage={vi.fn()}
      />,
    );

    // 一覧を空プレースホルダに置き換えず、既存メッセージを残す
    expect(screen.getByText("維持される本文")).toBeInTheDocument();
    expect(screen.queryByText("会話履歴読み込み中...")).not.toBeInTheDocument();
    expect(screen.getByText("会話履歴を更新中...")).toBeInTheDocument();
  });

  it("初回読み込み（メッセージなし）のみ全面プレースホルダを出す", () => {
    render(
      <CodingMessageList
        {...baseProps}
        messages={[]}
        loadingMessages
        onCopyMessage={vi.fn()}
      />,
    );

    expect(screen.getByText("会話履歴読み込み中...")).toBeInTheDocument();
  });

  it("スクロールコンテナのrefとonScrollを受け付ける", () => {
    const scrollContainerRef = { current: null };
    const onScrollMessages = vi.fn();
    const { container } = render(
      <CodingMessageList
        {...baseProps}
        messages={[message({ message_id: "u1" })]}
        onCopyMessage={vi.fn()}
        scrollContainerRef={scrollContainerRef}
        onScrollMessages={onScrollMessages}
      />,
    );

    const scroller = container.querySelector("div.flex-1.overflow-y-auto");
    expect(scroller).not.toBeNull();
    if (scroller) {
      fireEvent.scroll(scroller);
      expect(onScrollMessages).toHaveBeenCalledTimes(1);
    }
  });

  it("メッセージ一覧がrelativeな独立スクロール領域である", () => {
    const { container } = render(
      <CodingMessageList
        {...baseProps}
        messages={[message({ message_id: "c1", role: "cli_request", content: "git status" })]}
        onCopyMessage={vi.fn()}
      />,
    );

    // 独立スクロール領域: flex-1 + overflow-y-auto を維持する
    const scroller = container.querySelector("div.flex-1.overflow-y-auto");
    expect(scroller).not.toBeNull();
    // absolute配置の子孫(sr-onlyトグル等)を文書高さへ漏らさないための包含
    expect(scroller).toHaveClass("relative");
    // トグル補助文言はスクロール領域内に収まる
    expect(scroller?.textContent).toContain("クリックで展開/折りたたみ");
  });
});
