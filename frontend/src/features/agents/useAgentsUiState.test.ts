import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useAgentsUiState } from "./useAgentsUiState";

function setup(overrides: Partial<Parameters<typeof useAgentsUiState>[0]> = {}) {
  const onCloseForm = vi.fn();
  const setAgentToDelete = vi.fn();
  const setSessionToDelete = vi.fn();
  const setSessionToEditTitle = vi.fn();
  const setActiveSessionMenuId = vi.fn();
  const props: Parameters<typeof useAgentsUiState>[0] = {
    messages: [],
    streamingText: "",
    streamingToolCalls: [],
    streamingPhase: null,
    streamingIteration: null,
    activeWaitingRun: null,
    activeSessionMenuId: null,
    setActiveSessionMenuId,
    setAgentToDelete,
    setSessionToDelete,
    setSessionToEditTitle,
    agentToDelete: null,
    sessionToDelete: null,
    sessionToEditTitle: null,
    isFormOpen: true,
    onCloseForm,
    ...overrides,
  };
  const result = renderHook(
    (p: Parameters<typeof useAgentsUiState>[0]) => useAgentsUiState(p),
    { initialProps: props },
  );
  // leftPaneOpen はフック内部所有。Escape経路の検証にはフォーム開閉と
  // モーダル状態で十分である。
  const rerenderSame = () => result.rerender(props);
  return { ...result, rerenderSame, onCloseForm, setAgentToDelete, setSessionToDelete, setActiveSessionMenuId };
}

function keydown(key: string, isComposing = false) {
  const ev = new Event("keydown", { bubbles: true, cancelable: true });
  Object.defineProperty(ev, "key", { value: key });
  Object.defineProperty(ev, "isComposing", { value: isComposing });
  window.dispatchEvent(ev);
}

describe("useAgentsUiState Escape handling", () => {
  it("フォーム表示中のEscapeで閉じる", () => {
    const { onCloseForm } = setup();
    act(() => {
      keydown("Escape");
    });
    expect(onCloseForm).toHaveBeenCalledTimes(1);
  });

  it("Escape以外のキーでは閉じない", () => {
    const { onCloseForm } = setup();
    act(() => {
      keydown("Enter");
      keydown("a");
    });
    expect(onCloseForm).not.toHaveBeenCalled();
  });

  it("IME変換中のEscapeでは閉じない", () => {
    const { onCloseForm } = setup();
    act(() => {
      keydown("Escape", true);
    });
    expect(onCloseForm).not.toHaveBeenCalled();
  });

  it("フォームが閉じていればEscapeで何もしない", () => {
    const { onCloseForm } = setup({ isFormOpen: false });
    act(() => {
      keydown("Escape");
    });
    expect(onCloseForm).not.toHaveBeenCalled();
  });

  it("モーダル表示中はモーダルだけ閉じてフォームは閉じない", () => {
    const { onCloseForm, setSessionToDelete } = setup({
      sessionToDelete: { session_id: "s1" } as never,
    });
    act(() => {
      keydown("Escape");
    });
    expect(setSessionToDelete).toHaveBeenCalledWith(null);
    expect(onCloseForm).not.toHaveBeenCalled();
  });

  it("アンマウント後はリスナーが残留しない", () => {
    const { onCloseForm, unmount } = setup();
    unmount();
    act(() => {
      keydown("Escape");
    });
    expect(onCloseForm).not.toHaveBeenCalled();
  });

  it("再表示・再描画で多重発火しない", () => {
    const { onCloseForm, rerenderSame } = setup();
    rerenderSame();
    rerenderSame();
    act(() => {
      keydown("Escape");
    });
    expect(onCloseForm).toHaveBeenCalledTimes(1);
  });
});
