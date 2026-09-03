import { useCallback, useEffect, useRef, useState } from "react";

/**
 * セッションごとのプロンプト下書き保存・復元フック。
 *
 * - 保存先は `sessionStorage` のみ。入力中プロンプトのテキストだけを保存し、
 *   APIキー・認証情報・ツール出力などは扱わない。
 * - キーはページ種別とセッションIDを含む
 *   (`oaih:prompt-draft:<page>:<sessionId>`) ため、Coding と Agents の間でも混ざらない。
 * - デバウンス保存し、セッション切替・unmount 時は保留中の保存を flush する。
 * - `sessionStorage` が利用不可（SSR・SecurityError・quota等）でも例外を投げない。
 */
export type PromptDraftPage = "coding" | "agents";

/** MemoryPage の 500ms 規約に合わせたデバウンス時間。 */
export const PROMPT_DRAFT_DEBOUNCE_MS = 500;

export function buildPromptDraftKey(page: PromptDraftPage, sessionId: string): string {
  return `oaih:prompt-draft:${page}:${sessionId}`;
}

function getSessionStorage(): Storage | null {
  try {
    if (typeof window === "undefined" || !window.sessionStorage) return null;
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export function readPromptDraft(page: PromptDraftPage, sessionId: string): string {
  try {
    const storage = getSessionStorage();
    if (!storage) return "";
    return storage.getItem(buildPromptDraftKey(page, sessionId)) ?? "";
  } catch {
    return "";
  }
}

function writePromptDraft(page: PromptDraftPage, sessionId: string, value: string): void {
  try {
    const storage = getSessionStorage();
    if (!storage) return;
    const key = buildPromptDraftKey(page, sessionId);
    if (value === "") {
      storage.removeItem(key);
    } else {
      storage.setItem(key, value);
    }
  } catch {
    // SecurityError / quota 等でも入力をブロックしない。
  }
}

function removePromptDraft(page: PromptDraftPage, sessionId: string): void {
  try {
    getSessionStorage()?.removeItem(buildPromptDraftKey(page, sessionId));
  } catch {
    // ignore
  }
}

/**
 * 指定したページ種別・セッションIDの下書きを即時保存する。
 * 現在セッションに依存しないため、送信成否の確定処理から使う。
 */
export function savePromptDraftFor(page: PromptDraftPage, sessionId: string, value: string): void {
  writePromptDraft(page, sessionId, value);
}

/**
 * 指定したページ種別・セッションIDの下書きを即時削除する。
 * 現在セッションに依存しないため、送信成功の確定処理から使う。
 */
export function removePromptDraftFor(page: PromptDraftPage, sessionId: string): void {
  removePromptDraft(page, sessionId);
}

export interface SessionPromptDraft {
  draft: string;
  setDraft: (value: string | ((prev: string) => string)) => void;
  /**
   * 入力状態だけを更新し、storage へは触れない（保存のスケジュールもしない）。
   * 送信開始時の一時クリアや、確定処理での入力復元・クリアに使う。
   */
  setLocalDraft: (value: string | ((prev: string) => string)) => void;
  /** 該当セッションの下書きを削除する（送信成功時に使用）。 */
  clearDraft: () => void;
  /** 保留中のデバウンス保存を直ちに書き込む。 */
  flush: () => void;
  /** 指定セッションの下書きを即時保存する（送信失敗時の復元に使用）。 */
  saveDraftFor: (sessionId: string, value: string) => void;
  /** 指定セッションの下書きを即時削除する（送信成功の確定処理に使用）。 */
  removeDraftFor: (sessionId: string) => void;
}

export function useSessionPromptDraft(
  page: PromptDraftPage,
  sessionId: string | null,
  debounceMs: number = PROMPT_DRAFT_DEBOUNCE_MS,
): SessionPromptDraft {
  const [draft, setDraftState] = useState("");
  const sessionRef = useRef<string | null>(sessionId);
  const draftRef = useRef("");
  const timerRef = useRef<number | null>(null);
  const pendingRef = useRef<{ sessionId: string; value: string } | null>(null);
  // 次の保存スケジュールを1回だけ抑止するフラグ。送信開始時の一時クリアや
  // 確定処理での入力付け替えが storage へ波及しないようにする。
  const skipSaveRef = useRef(false);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const persist = useCallback(
    (sid: string, value: string) => {
      writePromptDraft(page, sid, value);
    },
    [page],
  );

  const flush = useCallback(() => {
    const pending = pendingRef.current;
    if (!pending) return;
    clearTimer();
    pendingRef.current = null;
    persist(pending.sessionId, pending.value);
  }, [clearTimer, persist]);

  const clearDraft = useCallback(() => {
    const sid = sessionRef.current;
    clearTimer();
    pendingRef.current = null;
    if (sid) {
      removePromptDraft(page, sid);
    }
  }, [clearTimer, page]);

  // セッション切替時: 切替元の保留保存を flush してから切替先を復元する。
  // 下書きがなければ入力欄を空にする。復元による state 更新は保存対象にしない。
  useEffect(() => {
    if (sessionRef.current && sessionRef.current !== sessionId) {
      flush();
    }
    sessionRef.current = sessionId;
    clearTimer();
    pendingRef.current = null;
    if (!sessionId) {
      if (draftRef.current !== "") {
        draftRef.current = "";
        skipSaveRef.current = true;
        setDraftState("");
      }
      return;
    }
    const restored = readPromptDraft(page, sessionId);
    if (draftRef.current !== restored) {
      draftRef.current = restored;
      skipSaveRef.current = true;
      setDraftState(restored);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, page]);

  // テキスト変更をデバウンス保存する。スケジュール時点のセッションIDを
  // 保持し、発火時に current と一致しなければ書き込まないことで、
  // 古いタイマーが新セッションのキーへ書き込むのを防ぐ。
  useEffect(() => {
    if (skipSaveRef.current) {
      skipSaveRef.current = false;
      return;
    }
    const sid = sessionRef.current;
    if (!sid) return;
    pendingRef.current = { sessionId: sid, value: draft };
    clearTimer();
    timerRef.current = window.setTimeout(() => {
      const pending = pendingRef.current;
      timerRef.current = null;
      pendingRef.current = null;
      if (!pending) return;
      if (sessionRef.current !== pending.sessionId) return;
      persist(pending.sessionId, pending.value);
    }, debounceMs);
    return () => {
      clearTimer();
    };
  }, [draft, debounceMs, clearTimer, persist]);

  // unmount 時は保留中の保存を flush する。
  useEffect(() => {
    return () => {
      const pending = pendingRef.current;
      if (pending) {
        writePromptDraft(page, pending.sessionId, pending.value);
        pendingRef.current = null;
      }
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page]);

  const setLocalDraft = useCallback(
    (value: string | ((prev: string) => string)) => {
      const next = typeof value === "function" ? value(draftRef.current) : value;
      clearTimer();
      pendingRef.current = null;
      if (next !== draftRef.current) {
        draftRef.current = next;
        skipSaveRef.current = true;
        setDraftState(next);
      }
    },
    [clearTimer],
  );

  const saveDraftFor = useCallback(
    (sid: string, value: string) => {
      if (pendingRef.current?.sessionId === sid) {
        clearTimer();
        pendingRef.current = null;
      }
      writePromptDraft(page, sid, value);
    },
    [clearTimer, page],
  );

  const removeDraftFor = useCallback(
    (sid: string) => {
      if (pendingRef.current?.sessionId === sid) {
        clearTimer();
        pendingRef.current = null;
      }
      removePromptDraft(page, sid);
    },
    [clearTimer, page],
  );

  const setDraft = useCallback((value: string | ((prev: string) => string)) => {
    const next = typeof value === "function" ? value(draftRef.current) : value;
    draftRef.current = next;
    setDraftState(next);
  }, []);

  return { draft, setDraft, setLocalDraft, clearDraft, flush, saveDraftFor, removeDraftFor };
}
