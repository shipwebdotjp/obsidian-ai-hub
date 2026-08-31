import { useCallback, useEffect, useState } from "react";

export type ChatSendMode = "enter" | "newline";

const STORAGE_KEY = "obsidian-ai-hub:chat-send-mode";
export const CHANGED_EVENT_NAME = "chat-send-mode-changed";

export function getChatSendMode(): ChatSendMode {
  return localStorage.getItem(STORAGE_KEY) === "newline" ? "newline" : "enter";
}

export function setChatSendMode(mode: ChatSendMode): void {
  localStorage.setItem(STORAGE_KEY, mode);
  window.dispatchEvent(new Event(CHANGED_EVENT_NAME));
}

export function shouldSendOnEnter(
  e: React.KeyboardEvent<HTMLTextAreaElement>,
  mode: ChatSendMode,
): boolean {
  if (e.nativeEvent.isComposing || e.keyCode === 229) return false;
  if (e.key !== "Enter") return false;
  if (mode === "enter") {
    return !e.shiftKey;
  }
  return Boolean(e.metaKey || e.ctrlKey);
}

export function getChatInputPlaceholder(
  mode: ChatSendMode,
  prefix = "メッセージを入力",
): string {
  return mode === "enter"
    ? `${prefix}…（Enterで送信 / Shift+Enterで改行）`
    : `${prefix}…（Enterで改行 / Ctrl+Enterで送信）`;
}

export function useChatSendMode(): [ChatSendMode, (mode: ChatSendMode) => void] {
  const [mode, setMode] = useState<ChatSendMode>(getChatSendMode);

  useEffect(() => {
    const sync = () => setMode(getChatSendMode());
    window.addEventListener(CHANGED_EVENT_NAME, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(CHANGED_EVENT_NAME, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  const update = useCallback((next: ChatSendMode) => setChatSendMode(next), []);
  return [mode, update];
}
