import { afterEach, describe, expect, it, vi } from "vitest";
import {
  getChatSendMode,
  setChatSendMode,
  CHANGED_EVENT_NAME,
  getChatInputPlaceholder,
  isMobileSendButtonOnly,
  shouldSendOnEnter,
} from "./chatSendMode";

const DESKTOP_UA =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36";
const IPHONE_UA =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1";

function mockMatchMedia(matches: boolean): void {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: vi.fn(
      (query: string) => ({ matches: query === "(pointer: coarse)" && matches }) as MediaQueryList,
    ),
  });
}

function mockUserAgent(ua: string): void {
  Object.defineProperty(navigator, "userAgent", {
    configurable: true,
    value: ua,
  });
}

describe("chatSendMode", () => {
  afterEach(() => {
    localStorage.clear();
    window.dispatchEvent(new Event(CHANGED_EVENT_NAME));
    vi.unstubAllGlobals();
    mockMatchMedia(false);
    mockUserAgent(DESKTOP_UA);
  });

  it("defaults to 'enter'", () => {
    expect(getChatSendMode()).toBe("enter");
  });

  it("persists 'newline' and reads it back", () => {
    setChatSendMode("newline");
    expect(getChatSendMode()).toBe("newline");
  });

  it("treats any non-'newline' value as 'enter'", () => {
    localStorage.setItem("obsidian-ai-hub:chat-send-mode", "bogus");
    expect(getChatSendMode()).toBe("enter");
  });

  it("dispatches the changed event on update", () => {
    let fired = false;
    const listener = () => {
      fired = true;
    };
    window.addEventListener(CHANGED_EVENT_NAME, listener);
    setChatSendMode("newline");
    window.removeEventListener(CHANGED_EVENT_NAME, listener);
    expect(fired).toBe(true);
  });

  it("returns correct placeholders", () => {
    expect(getChatInputPlaceholder("enter")).toBe(
      "メッセージを入力…（Enterで送信 / Shift+Enterで改行）",
    );
    expect(getChatInputPlaceholder("newline")).toBe(
      "メッセージを入力…（Enterで改行 / Ctrl+Enterで送信）",
    );
    expect(getChatInputPlaceholder("enter", "指示・質問を入力")).toBe(
      "指示・質問を入力…（Enterで送信 / Shift+Enterで改行）",
    );
    expect(getChatInputPlaceholder("newline", "指示・質問を入力")).toBe(
      "指示・質問を入力…（Enterで改行 / Ctrl+Enterで送信）",
    );
  });

  it("decides send shortcut correctly per mode and prevents IME", () => {
    const mk = (overrides: Partial<React.KeyboardEvent<HTMLTextAreaElement>> & { keyCode?: number }) =>
      ({
        key: "Enter",
        shiftKey: false,
        ctrlKey: false,
        metaKey: false,
        keyCode: 0,
        nativeEvent: { isComposing: false } as any,
        ...overrides,
      }) as unknown as React.KeyboardEvent<HTMLTextAreaElement>;

    // enter mode
    expect(shouldSendOnEnter(mk({}), "enter")).toBe(true);
    expect(shouldSendOnEnter(mk({ shiftKey: true }), "enter")).toBe(false);
    expect(shouldSendOnEnter(mk({ ctrlKey: true }), "enter")).toBe(true);
    expect(shouldSendOnEnter(mk({ metaKey: true }), "enter")).toBe(true);
    expect(shouldSendOnEnter(mk({ key: "a" }), "enter")).toBe(false);

    // newline mode
    expect(shouldSendOnEnter(mk({}), "newline")).toBe(false);
    expect(shouldSendOnEnter(mk({ shiftKey: true }), "newline")).toBe(false);
    expect(shouldSendOnEnter(mk({ ctrlKey: true }), "newline")).toBe(true);
    expect(shouldSendOnEnter(mk({ metaKey: true }), "newline")).toBe(true);
    expect(shouldSendOnEnter(mk({ ctrlKey: true, shiftKey: true }), "newline")).toBe(true);
    expect(shouldSendOnEnter(mk({ key: "a", ctrlKey: true }), "newline")).toBe(false);

    // IME composing
    expect(shouldSendOnEnter(mk({ nativeEvent: { isComposing: true } as any }), "enter")).toBe(false);
    expect(shouldSendOnEnter(mk({ keyCode: 229 }), "enter")).toBe(false);
  });

  it("disables Enter-send on coarse-pointer devices regardless of mode", () => {
    mockMatchMedia(true);
    mockUserAgent(DESKTOP_UA);
    expect(isMobileSendButtonOnly()).toBe(true);

    const mk = (overrides: Partial<React.KeyboardEvent<HTMLTextAreaElement>> & { keyCode?: number }) =>
      ({
        key: "Enter",
        shiftKey: false,
        ctrlKey: false,
        metaKey: false,
        keyCode: 0,
        nativeEvent: { isComposing: false } as any,
        ...overrides,
      }) as unknown as React.KeyboardEvent<HTMLTextAreaElement>;

    expect(shouldSendOnEnter(mk({}), "enter")).toBe(false);
    expect(shouldSendOnEnter(mk({ ctrlKey: true }), "enter")).toBe(false);
    expect(shouldSendOnEnter(mk({ metaKey: true }), "enter")).toBe(false);
    expect(shouldSendOnEnter(mk({}), "newline")).toBe(false);
    expect(shouldSendOnEnter(mk({ ctrlKey: true }), "newline")).toBe(false);
    expect(shouldSendOnEnter(mk({ metaKey: true }), "newline")).toBe(false);
    // Button-only hint is mode-independent on mobile.
    expect(getChatInputPlaceholder("enter")).toBe(getChatInputPlaceholder("newline"));
  });

  it("detects smartphones via user agent when pointer query is unavailable", () => {
    mockMatchMedia(false);
    mockUserAgent(IPHONE_UA);
    expect(isMobileSendButtonOnly()).toBe(true);

    const enterKey = {
      key: "Enter",
      shiftKey: false,
      ctrlKey: false,
      metaKey: false,
      keyCode: 0,
      nativeEvent: { isComposing: false },
    } as unknown as React.KeyboardEvent<HTMLTextAreaElement>;
    expect(shouldSendOnEnter(enterKey, "enter")).toBe(false);
  });

  it("keeps Enter-send on desktop pointers", () => {
    mockMatchMedia(false);
    mockUserAgent(DESKTOP_UA);
    expect(isMobileSendButtonOnly()).toBe(false);

    const enterKey = {
      key: "Enter",
      shiftKey: false,
      ctrlKey: false,
      metaKey: false,
      keyCode: 0,
      nativeEvent: { isComposing: false },
    } as unknown as React.KeyboardEvent<HTMLTextAreaElement>;
    expect(shouldSendOnEnter(enterKey, "enter")).toBe(true);
  });
});
