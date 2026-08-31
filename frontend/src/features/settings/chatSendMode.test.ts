import { afterEach, describe, expect, it } from "vitest";
import {
  getChatSendMode,
  setChatSendMode,
  CHANGED_EVENT_NAME,
  getChatInputPlaceholder,
  shouldSendOnEnter,
} from "./chatSendMode";

describe("chatSendMode", () => {
  afterEach(() => {
    localStorage.clear();
    window.dispatchEvent(new Event(CHANGED_EVENT_NAME));
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
});
