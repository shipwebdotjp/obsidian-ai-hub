import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CodingConversationHeader } from "./CodingConversationHeader";
import type { CodingSession } from "../../../api/coding";

const session: CodingSession = {
  session_id: "cses_1",
  project_id: 1,
  backend: "opencode",
  repo_path: "/repo",
  external_session_id: null,
  title: "テスト会話",
  transport: "acp",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function renderHeader(sessionUsage: Parameters<typeof CodingConversationHeader>[0]["sessionUsage"]) {
  return render(
    <CodingConversationHeader
      selectedSession={session}
      sessionDetail={null}
      gitStatus={null}
      currentRun={null}
      sessionUsage={sessionUsage}
      leftPaneCollapsed={false}
      onExpandLeftPane={vi.fn()}
      drawerTriggerBtnRef={{ current: null }}
      onOpenMobileDrawer={vi.fn()}
      onOpenSessionSettings={vi.fn()}
      onCancelRun={vi.fn()}
    />,
  );
}

describe("CodingConversationHeader session token usage", () => {
  it("セッション累積のトークン使用量と費用を表示する", () => {
    renderHeader({
      input: 1200,
      cached: 300,
      output: 40,
      total: 1500,
      costAmount: 0.03,
      costCurrency: "USD",
    });

    const badge = screen.getByTestId("session-token-usage");
    expect(badge.textContent).toContain("入力 1.2k");
    expect(badge.textContent).toContain("キャッシュ読取 300");
    expect(badge.textContent).toContain("出力 40");
    expect(badge.textContent).toContain("合計 1.5k");
    expect(badge.textContent).toContain("0.03 USD");
  });

  it("使用量が無ければバッジを表示しない", () => {
    renderHeader(null);
    expect(screen.queryByTestId("session-token-usage")).not.toBeInTheDocument();
  });
});
