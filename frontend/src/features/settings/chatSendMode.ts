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
