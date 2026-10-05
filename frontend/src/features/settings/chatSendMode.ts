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

/**
 * スマートフォン等のタッチ端末では Enter 系キーでの誤送信を防ぐため、
 * 設定に関わらず Enter 送信を無効化し送信ボタン操作に限定する。
 */
export function isMobileSendButtonOnly(): boolean {
  if (typeof window === "undefined" || typeof navigator === "undefined")
    return false;
  if (
    typeof window.matchMedia === "function" &&
    window.matchMedia("(pointer: coarse)").matches
  )
    return true;
  return /Mobi|Android|iPhone|iPad|iPod/i.test(navigator.userAgent ?? "");
}

export function shouldSendOnEnter(
  e: React.KeyboardEvent<HTMLTextAreaElement>,
  mode: ChatSendMode,
): boolean {
  if (isMobileSendButtonOnly()) return false;
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
  if (isMobileSendButtonOnly()) return `${prefix}…（送信ボタンで送信）`;
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
