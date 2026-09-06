import { useEffect, useRef, useState } from "react";
import type {
  Agent,
  AgentLiveToolCall,
  AgentMessage,
  AgentSession,
} from "../../api/types";
import type { ActiveWaitingRun } from "../../components/InConversationQuestionCard";
import { LG_BREAKPOINT } from "./agentViewUtils";

interface UseAgentsUiStateOptions {
  messages: AgentMessage[];
  streamingText: string;
  streamingToolCalls: AgentLiveToolCall[];
  streamingPhase: "thinking" | "tool_preparing" | "tool_running" | null;
  streamingIteration: number | null;
  activeWaitingRun: ActiveWaitingRun | null;
  activeSessionMenuId: string | null;
  setActiveSessionMenuId: React.Dispatch<React.SetStateAction<string | null>>;
  setAgentToDelete: React.Dispatch<React.SetStateAction<Agent | null>>;
  setSessionToDelete: React.Dispatch<React.SetStateAction<AgentSession | null>>;
  setSessionToEditTitle: React.Dispatch<React.SetStateAction<AgentSession | null>>;
}

/** ペイン開閉・ドロワー・スクロール・グローバルキー操作など表示状態を管理する。 */
export function useAgentsUiState({
  messages,
  streamingText,
  streamingToolCalls,
  streamingPhase,
  streamingIteration,
  activeWaitingRun,
  activeSessionMenuId,
  setActiveSessionMenuId,
  setAgentToDelete,
  setSessionToDelete,
  setSessionToEditTitle,
}: UseAgentsUiStateOptions) {
  // Mobile / desktop pane layout state.
  // `leftPaneOpen` controls the mobile-only overlay drawer; on desktop the
  // sidebar is rendered independently and these handlers are harmless no-ops.
  const [leftPaneOpen, setLeftPaneOpen] = useState(false);
  const [leftPaneCollapsed, setLeftPaneCollapsed] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const mobileDrawerCloseRef = useRef<HTMLButtonElement>(null);
  const mobileDrawerRef = useRef<HTMLDivElement>(null);
  const mobileDrawerTriggerRef = useRef<HTMLButtonElement>(null);

  // Move focus into the mobile drawer when it opens and restore it to the
  // trigger button when the drawer closes. Also trap Tab focus inside the drawer.
  useEffect(() => {
    if (leftPaneOpen) {
      mobileDrawerCloseRef.current?.focus();

      const drawer = mobileDrawerRef.current;
      if (!drawer) return;

      const focusableSelector =
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';
      const onKeyDown = (e: KeyboardEvent) => {
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
      drawer.addEventListener("keydown", onKeyDown);
      return () => {
        drawer.removeEventListener("keydown", onKeyDown);
        mobileDrawerTriggerRef.current?.focus();
      };
    }
  }, [leftPaneOpen]);

  // Lock body scroll only while the mobile sidebar drawer is actually visible.
  useEffect(() => {
    if (!leftPaneOpen) return;
    // Tailwind `lg` breakpoint is min-width: 1024px, so the drawer is only
    // shown below that width. Keep scroll-lock in sync with that breakpoint.
    if (typeof window.matchMedia !== "function") return;
    const mql = window.matchMedia(`(max-width: ${LG_BREAKPOINT - 1}px)`);
    if (!mql.matches) return;
    const original = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onChange = (e: MediaQueryListEvent) => {
      document.body.style.overflow = e.matches ? "hidden" : original;
    };
    if (typeof mql.addEventListener === "function") {
      mql.addEventListener("change", onChange);
      return () => {
        mql.removeEventListener("change", onChange);
        document.body.style.overflow = original;
      };
    }
    return () => {
      document.body.style.overflow = original;
    };
  }, [leftPaneOpen]);

  // Modal / drawer ESC listener
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setAgentToDelete(null);
        setSessionToDelete(null);
        setSessionToEditTitle(null);
        setActiveSessionMenuId(null);
        setLeftPaneOpen(false);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [setActiveSessionMenuId, setAgentToDelete, setSessionToDelete, setSessionToEditTitle]);

  // Close active session menu when clicking outside
  useEffect(() => {
    if (!activeSessionMenuId) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (e.target instanceof Node) {
        const menus = document.querySelectorAll("[data-session-menu]");
        let inside = false;
        menus.forEach((menu) => {
          if (menu.contains(e.target as Node)) inside = true;
        });
        if (!inside) setActiveSessionMenuId(null);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [activeSessionMenuId, setActiveSessionMenuId]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView?.({ behavior: "smooth" });
  }, [messages, streamingText, streamingToolCalls, streamingPhase, streamingIteration, activeWaitingRun]);

  return {
    leftPaneOpen,
    setLeftPaneOpen,
    leftPaneCollapsed,
    setLeftPaneCollapsed,
    messagesEndRef,
    mobileDrawerCloseRef,
    mobileDrawerRef,
    mobileDrawerTriggerRef,
  };
}
