import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useCodingUiState } from "./useCodingUiState";
import type { CodingMessage } from "../../../api/coding";

function message(id: string): CodingMessage {
  return {
    message_id: id,
    session_id: "cses_1",
    sequence: 1,
    role: "user",
    content: id,
    created_at: "2026-01-01T00:00:00Z",
  };
}

function fakeContainer(overrides: Record<string, unknown> = {}) {
  return {
    scrollHeight: 1000,
    scrollTop: 800,
    clientHeight: 200,
    scrollTo: vi.fn(),
    ...overrides,
  } as unknown as HTMLDivElement & { scrollTo: ReturnType<typeof vi.fn> };
}

const baseProps = {
  messages: [message("u1")],
  activePhaseText: null as string | null,
  streamingToolCalls: [],
  workerState: { status: "idle" as const },
  activeWaitingRun: null,
};

describe("useCodingUiState auto-scroll", () => {
  it("下端付近では新着時にコンテナ末尾へスクロールする", () => {
    const { result, rerender } = renderHook((p: typeof baseProps) => useCodingUiState(p), {
      initialProps: baseProps,
    });
    const container = fakeContainer();
    act(() => {
      (result.current.scrollContainerRef as { current: unknown }).current = container;
    });
    (container.scrollTo as ReturnType<typeof vi.fn>).mockClear();

    rerender({ ...baseProps, messages: [message("u1"), message("u2")] });

    expect(container.scrollTo).toHaveBeenCalledWith({
      top: container.scrollHeight,
      behavior: "auto",
    });
  });

  it("履歴を遡っている時は新着でもスクロールしない", () => {
    const { result, rerender } = renderHook((p: typeof baseProps) => useCodingUiState(p), {
      initialProps: baseProps,
    });
    // 下端から500px離れている状態でスクロールイベントを発火
    const container = fakeContainer({ scrollTop: 300 });
    act(() => {
      (result.current.scrollContainerRef as { current: unknown }).current = container;
      result.current.handleMessageScroll();
    });
    (container.scrollTo as ReturnType<typeof vi.fn>).mockClear();

    rerender({ ...baseProps, messages: [message("u1"), message("u2")] });

    expect(container.scrollTo).not.toHaveBeenCalled();
  });

  it("scrollIntoViewを使わずコンテナ内スクロールに留める", () => {
    const scrollIntoView = vi.fn();
    const { result, rerender } = renderHook((p: typeof baseProps) => useCodingUiState(p), {
      initialProps: baseProps,
    });
    const container = fakeContainer();
    const end = { scrollIntoView } as unknown as HTMLDivElement;
    act(() => {
      (result.current.scrollContainerRef as { current: unknown }).current = container;
      (result.current.messageEndRef as { current: unknown }).current = end;
    });

    rerender({ ...baseProps, activePhaseText: "依頼を検討中..." });

    expect(scrollIntoView).not.toHaveBeenCalled();
    expect(container.scrollTo).toHaveBeenCalled();
  });
});
