import { afterEach, describe, expect, it } from "vitest";
import {
  getChatSendMode,
  setChatSendMode,
  CHANGED_EVENT_NAME,
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
});
