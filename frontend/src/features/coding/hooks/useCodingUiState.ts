import { useEffect, useRef, useState } from "react";
import type { CodingLiveToolCall, CodingMessage } from "../../../api/coding";
import type { ActiveWaitingRun } from "../../../components/InConversationQuestionCard";

interface UseCodingUiStateOptions {
  messages: CodingMessage[];
  activePhaseText: string | null;
  streamingToolCalls: CodingLiveToolCall[];
  workerState: { status: "idle" | "running" | "done" };
  activeWaitingRun: ActiveWaitingRun | null;
}

/** ペイン開閉・ドロワー・コピー・自動スクロールなど表示状態を管理する。 */
export function useCodingUiState({
  messages,
  activePhaseText,
  streamingToolCalls,
  workerState,
  activeWaitingRun,
}: UseCodingUiStateOptions) {
  // Desktop left pane collapse & mobile drawer state
  const [leftPaneCollapsed, setLeftPaneCollapsed] = useState(false);
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false);
  const drawerCloseBtnRef = useRef<HTMLButtonElement>(null);
  const drawerTriggerBtnRef = useRef<HTMLButtonElement>(null);
  const mobileDrawerRef = useRef<HTMLDivElement>(null);

  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const copyResetRef = useRef<number | null>(null);

  const messageEndRef = useRef<HTMLDivElement>(null);

  const handleCopyMessage = async (content: string, messageId: string) => {
    try {
      await navigator.clipboard.writeText(content);
      setCopiedMessageId(messageId);
      if (copyResetRef.current !== null) {
        window.clearTimeout(copyResetRef.current);
      }
      copyResetRef.current = window.setTimeout(() => {
        setCopiedMessageId((current) => (current === messageId ? null : current));
        copyResetRef.current = null;
      }, 2000);
    } catch (err) {
      console.error("Failed to copy message:", err);
    }
  };

  useEffect(() => {
    return () => {
      if (copyResetRef.current !== null) {
        window.clearTimeout(copyResetRef.current);
        copyResetRef.current = null;
      }
    };
  }, []);

  // Auto-scroll on new messages / phase change / waiting-run change
  // Only when already near the bottom so reading history isn't yanked.
  useEffect(() => {
    const el = messageEndRef.current;
    if (!el || typeof el.scrollIntoView !== "function") return;
    const container = el.parentElement;
    if (container) {
      const distanceFromBottom =
        container.scrollHeight - container.scrollTop - container.clientHeight;
      if (distanceFromBottom > 200) return;
    }
    el.scrollIntoView({ behavior: "auto", block: "end" });
  }, [messages, activePhaseText, streamingToolCalls, workerState, activeWaitingRun]);

  // Mobile drawer focus management & trap
  useEffect(() => {
    if (mobileDrawerOpen) {
      drawerCloseBtnRef.current?.focus();

      const drawer = mobileDrawerRef.current;
      if (!drawer) return;

      const focusableSelector =
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';
      const onKeyDown = (e: KeyboardEvent) => {
        if (e.key === "Escape") {
          setMobileDrawerOpen(false);
          return;
        }
        if (e.key !== "Tab") return;
        const focusable = Array.from(
          drawer.querySelectorAll<HTMLElement>(focusableSelector)
        ).filter((el) => !el.hasAttribute("disabled") && el.offsetParent !== null);
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      };
      window.addEventListener("keydown", onKeyDown);
      return () => {
        window.removeEventListener("keydown", onKeyDown);
        drawerTriggerBtnRef.current?.focus();
      };
    }
  }, [mobileDrawerOpen]);

  return {
    leftPaneCollapsed,
    setLeftPaneCollapsed,
    mobileDrawerOpen,
    setMobileDrawerOpen,
    drawerCloseBtnRef,
    drawerTriggerBtnRef,
    mobileDrawerRef,
    copiedMessageId,
    handleCopyMessage,
    messageEndRef,
  };
}
