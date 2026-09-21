import { useCallback, useEffect, useRef, type Dispatch, type SetStateAction } from "react";
import type { AgentContextRef } from "../../api/types";
import { MAX_AGENT_CONTEXT_REFS, isValidContextRef } from "./agentViewUtils";
import type { PendingContextRef } from "./agentViewUtils";

/**
 * AgentsPage の参照コンテキスト（Vault ファイル）下書き保存・復元。
 *
 * 画像下書き（`useAgentImageDraft`、本文 base64 あり）とは別キーで、パスのみを
 * 軽量に保持する。テキストの正本は `useSessionPromptDraft` が持つ。
 */
export function buildAgentContextRefDraftKey(sessionId: string): string {
  return `agent-context-refs:${sessionId}`;
}

function getLocalStorage(): Storage | null {
  try {
    if (typeof window === "undefined" || !window.localStorage) return null;
    return window.localStorage;
  } catch {
    return null;
  }
}

function toPendingRef(ref: AgentContextRef): PendingContextRef {
  return { kind: "vault_file", path: ref.path };
}

/** 指定セッションの参照下書きを読む。破損時は空配列。上限で切り詰める。 */
export function readAgentContextRefDraft(sessionId: string): PendingContextRef[] {
  try {
    const storage = getLocalStorage();
    if (!storage) return [];
    const raw = storage.getItem(buildAgentContextRefDraftKey(sessionId));
    if (!raw) return [];
    const parsed = JSON.parse(raw) as { refs?: unknown };
    const list = Array.isArray(parsed?.refs) ? parsed.refs : [];
    return list
      .filter(isValidContextRef)
      .slice(0, MAX_AGENT_CONTEXT_REFS)
      .map(toPendingRef);
  } catch {
    return [];
  }
}

/** 指定セッションの参照下書きを即時保存する（例外を投げない）。 */
export function writeAgentContextRefDraft(sessionId: string, refs: PendingContextRef[]): void {
  try {
    const storage = getLocalStorage();
    if (!storage) return;
    const key = buildAgentContextRefDraftKey(sessionId);
    if (refs.length === 0) {
      storage.removeItem(key);
      return;
    }
    storage.setItem(
      key,
      JSON.stringify({
        refs: refs.map((r) => ({ kind: r.kind, path: r.path })),
        savedAt: new Date().toISOString(),
      }),
    );
  } catch (e) {
    console.error("Failed to save context ref draft:", e);
  }
}

/** 指定セッションの参照下書きを即時削除する（例外を投げない）。 */
export function removeAgentContextRefDraft(sessionId: string): void {
  try {
    getLocalStorage()?.removeItem(buildAgentContextRefDraftKey(sessionId));
  } catch {
    // ignore
  }
}

export interface AgentContextRefDraft {
  saveContextRefDraftFor: (sessionId: string, refs: PendingContextRef[]) => void;
  removeContextRefDraftFor: (sessionId: string) => void;
  setLocalContextRefs: (next: PendingContextRef[]) => void;
}

/**
 * 参照コンテキストのセッション別下書き hook。画像下書きと同様に、
 * セッション切替時は切替元を flush して切替先を復元する。
 */
export function useAgentContextRefDraft(
  sessionId: string | null,
  refs: PendingContextRef[],
  setRefs: Dispatch<SetStateAction<PendingContextRef[]>>,
): AgentContextRefDraft {
  const sessionRef = useRef<string | null>(sessionId);
  const timerRef = useRef<number | null>(null);
  const pendingRef = useRef<{ sessionId: string; refs: PendingContextRef[] } | null>(null);
  const skipSaveRef = useRef(false);
  const latestRefsRef = useRef(refs);
  const setRefsRef = useRef(setRefs);

  useEffect(() => {
    setRefsRef.current = setRefs;
    latestRefsRef.current = refs;
  });

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const saveContextRefDraftFor = useCallback(
    (sid: string, next: PendingContextRef[]) => {
      if (pendingRef.current?.sessionId === sid) {
        clearTimer();
        pendingRef.current = null;
      }
      writeAgentContextRefDraft(sid, next);
    },
    [clearTimer],
  );

  const removeContextRefDraftFor = useCallback(
    (sid: string) => {
      if (pendingRef.current?.sessionId === sid) {
        clearTimer();
        pendingRef.current = null;
      }
      removeAgentContextRefDraft(sid);
    },
    [clearTimer],
  );

  const setLocalContextRefs = useCallback(
    (next: PendingContextRef[]) => {
      clearTimer();
      pendingRef.current = null;
      if (next !== latestRefsRef.current) {
        latestRefsRef.current = next;
        skipSaveRef.current = true;
        setRefsRef.current(next);
      }
    },
    [clearTimer],
  );

  // セッション切替時: 切替元の保留保存を flush してから切替先を復元する。
  useEffect(() => {
    if (sessionRef.current && sessionRef.current !== sessionId) {
      const pending = pendingRef.current;
      if (pending) {
        clearTimer();
        pendingRef.current = null;
        writeAgentContextRefDraft(pending.sessionId, pending.refs);
      }
    }
    sessionRef.current = sessionId;
    clearTimer();
    pendingRef.current = null;
    if (!sessionId) {
      skipSaveRef.current = true;
      setRefsRef.current([]);
      return;
    }
    const restored = readAgentContextRefDraft(sessionId);
    latestRefsRef.current = restored;
    skipSaveRef.current = true;
    setRefsRef.current(restored);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, clearTimer]);

  // 参照変更をデバウンス保存する（500ms、画像下書きと同一）。
  useEffect(() => {
    if (skipSaveRef.current) {
      skipSaveRef.current = false;
      return;
    }
    const sid = sessionRef.current;
    if (!sid) return;
    const snapshot = refs.map((r) => ({ ...r }));
    pendingRef.current = { sessionId: sid, refs: snapshot };
    clearTimer();
    timerRef.current = window.setTimeout(() => {
      const pending = pendingRef.current;
      timerRef.current = null;
      pendingRef.current = null;
      if (!pending) return;
      if (sessionRef.current !== pending.sessionId) return;
      writeAgentContextRefDraft(pending.sessionId, pending.refs);
    }, 500);
    return () => {
      clearTimer();
    };
  }, [refs, clearTimer]);

  useEffect(() => {
    return () => {
      const pending = pendingRef.current;
      if (pending) {
        pendingRef.current = null;
        writeAgentContextRefDraft(pending.sessionId, pending.refs);
      }
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { saveContextRefDraftFor, removeContextRefDraftFor, setLocalContextRefs };
}
