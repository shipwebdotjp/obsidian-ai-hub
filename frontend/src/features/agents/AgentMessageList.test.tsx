import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { AgentMessageList } from "./AgentMessageList";
import type { AgentMessage } from "../../api/types";

const CLIPBOARD_PATH_D =
  "M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h12a2 2 0 002-2V7a2 2 0 00-2-2h-2M8 5a2 2 0 002 2h4a2 2 0 002-2M8 5a2 2 0 012-2h4a2 2 0 012 2";

function renderList(props: Partial<React.ComponentProps<typeof AgentMessageList>> = {}) {
  const onCopy = vi.fn();
  const view = render(
    <MemoryRouter>
      <AgentMessageList
        messages={[
          {
            message_id: "m1",
            session_id: "s1",
            sequence: 1,
            role: "user",
            content: "エージェントへの依頼文",
            created_at: "2026-01-01T00:00:00Z",
          } satisfies AgentMessage,
        ]}
        isStreaming={false}
        runs={[]}
        answerHistory={[]}
        activeWaitingRun={null}
        streamingToolCalls={[]}
        displayedStreamingPhase={null}
        streamingIteration={null}
        streamingText=""
        hitlLinks={[]}
        chatError={null}
        copiedMessageId={null}
        onCopyMessage={onCopy}
        onSubmitWaitingAnswers={vi.fn()}
        onCancelWaitingRun={vi.fn()}
        messageRefs={{ current: new Map() }}
        messagesEndRef={{ current: null }}
        {...props}
      />
    </MemoryRouter>,
  );
  return { onCopy, ...view };
}

describe("AgentMessageList copy button", () => {
  it("クリップボード型アイコンを使いlucideのCopyアイコンを使わない", () => {
    const { container } = renderList();

    const btn = screen.getByTestId("copy-message-m1");
    expect(btn).toHaveAttribute("aria-label", "メッセージをコピー");
    expect(btn.querySelector("svg path")?.getAttribute("d")).toBe(CLIPBOARD_PATH_D);
    expect(container.querySelector(".lucide-copy")).toBeNull();
  });

  it("コピー対象がメッセージ本文である", () => {
    const { onCopy } = renderList();

    fireEvent.click(screen.getByTestId("copy-message-m1"));
    expect(onCopy).toHaveBeenCalledWith("エージェントへの依頼文", "m1");
  });

  it("コピー完了時はチェックと完了文言になる", () => {
    renderList({ copiedMessageId: "m1" });

    expect(screen.getByText("コピーしました")).toBeInTheDocument();
  });
});
