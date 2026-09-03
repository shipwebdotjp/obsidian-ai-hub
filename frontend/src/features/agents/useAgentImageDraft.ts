import { useCallback, useEffect, useRef, type Dispatch, type SetStateAction } from "react";

/**
 * AgentsPage の添付画像下書き保存・復元。
 *
 * テキスト下書き（`useSessionPromptDraft`、sessionStorage）とは保存方式・キーを
 * 分離し、元実装と同一の localStorage キー・JSON形状・サイズ制限を復元する。
 * APIキー・認証情報・ツール出力は扱わず、画像のメタ情報とbase64本文のみ保存する。
 */
export interface ImageDraftItem {
  previewUrl: string;
  name: string;
  mime_type: string;
  data: string;
  size: number;
}

interface StoredImageAttachment {
  name: string;
  mime_type: string;
  data: string;
  size: number;
}

interface ImageDraftRecord {
  text?: string;
  attachments?: StoredImageAttachment[];
  savedAt?: string;
}

/** 元実装と同一のキー形式。Coding のキーとは衝突しない。 */
export function buildAgentImageDraftKey(sessionId: string): string {
  return `agent-draft:${sessionId}`;
}

/** 元実装と同一のサイズ上限（localStorage quota内に収めるための約4MB）。 */
export const AGENT_IMAGE_DRAFT_SIZE_LIMIT = 4_000_000;

/** テキスト下書きと合わせたデバウンス時間。 */
export const AGENT_IMAGE_DRAFT_DEBOUNCE_MS = 500;

function getLocalStorage(): Storage | null {
  try {
    if (typeof window === "undefined" || !window.localStorage) return null;
    return window.localStorage;
  } catch {
    return null;
  }
}

function isValidStoredAttachment(
  att: unknown,
): att is { name: string; mime_type: string; data: string; size: number } {
  return Boolean(
    att && (att as StoredImageAttachment).mime_type && (att as StoredImageAttachment).data,
  );
}

function toPreviewItem(att: StoredImageAttachment): ImageDraftItem {
  return {
    ...att,
    previewUrl: `data:${att.mime_type};base64,${att.data}`,
  };
}

function stripPreview(item: ImageDraftItem): StoredImageAttachment {
  return { name: item.name, mime_type: item.mime_type, data: item.data, size: item.size };
}

/** 指定セッションの画像下書きを読み、previewUrl を再構築して返す。破損時は空配列。 */
export function readAgentImageDraft(sessionId: string): ImageDraftItem[] {
  try {
    const storage = getLocalStorage();
    if (!storage) return [];
    const raw = storage.getItem(buildAgentImageDraftKey(sessionId));
    if (!raw) return [];
    const parsed = JSON.parse(raw) as ImageDraftRecord;
    const list = Array.isArray(parsed?.attachments) ? parsed.attachments : [];
    return list.filter(isValidStoredAttachment).map(toPreviewItem);
  } catch {
    // 破損・読み取り不可の下書きは破棄して空で開始する。
    return [];
  }
}

export type ImageDraftWriteResult = "ok" | "too-large" | "unavailable";

/**
 * 指定セッションの画像下書きを即時保存する。サイズ上限超過時はキーを削除して
 * "too-large" を返し、storage利用不可時は "unavailable" を返す（例外は投げない）。
 */
export function writeAgentImageDraft(
  sessionId: string,
  text: string,
  attachments: ImageDraftItem[],
): ImageDraftWriteResult {
  try {
    const storage = getLocalStorage();
    if (!storage) return "unavailable";
    const key = buildAgentImageDraftKey(sessionId);
    if (attachments.length === 0) {
      storage.removeItem(key);
      return "ok";
    }
    const serialized = JSON.stringify({
      text,
      attachments: attachments.map(stripPreview),
      savedAt: new Date().toISOString(),
    });
    if (serialized.length > AGENT_IMAGE_DRAFT_SIZE_LIMIT) {
      // quota超過で中途半端に残さず削除する。
      try {
        storage.removeItem(key);
      } catch {
        // ignore
      }
      return "too-large";
    }
    storage.setItem(key, serialized);
    return "ok";
  } catch (e) {
    // QuotaExceeded やプライベートモードでも入力をブロックしない。
    console.error("Failed to save image draft:", e);
    return "unavailable";
  }
}

/** 指定セッションの画像下書きを即時削除する（例外を投げない）。 */
export function removeAgentImageDraft(sessionId: string): void {
  try {
    getLocalStorage()?.removeItem(buildAgentImageDraftKey(sessionId));
  } catch {
    // ignore
  }
}

export interface AgentImageDraft {
  /** 指定セッションの画像下書きを即時保存する（送信失敗時の復元に使用）。 */
  saveImageDraftFor: (sessionId: string, text: string, attachments: ImageDraftItem[]) => ImageDraftWriteResult;
  /** 指定セッションの画像下書きを即時削除する（送信成功の確定処理に使用）。 */
  removeImageDraftFor: (sessionId: string) => void;
  /** 入力状態だけを更新し、storage へは触れない（送信開始時の一時クリア等に使用）。 */
  setLocalAttachments: (next: ImageDraftItem[]) => void;
}

/**
 * 添付画像のセッション別下書き hook。`attachments`（ページ側state）の変更を
 * デバウンス保存し、セッション切替時は切替元をflushして切替先を復元する。
 * テキストは `text` 引数で受けて保存形状に含めるが、読み取り時は画像のみ復元する
 * （テキストの正本は `useSessionPromptDraft` が持つ）。
 */
export function useAgentImageDraft(
  sessionId: string | null,
  attachments: ImageDraftItem[],
  setAttachments: Dispatch<SetStateAction<ImageDraftItem[]>>,
  text: string,
  onTooLarge: () => void,
  debounceMs: number = AGENT_IMAGE_DRAFT_DEBOUNCE_MS,
): AgentImageDraft {
  const sessionRef = useRef<string | null>(sessionId);
  const timerRef = useRef<number | null>(null);
  const pendingRef = useRef<{ sessionId: string; text: string; attachments: ImageDraftItem[] } | null>(null);
  const skipSaveRef = useRef(false);
  const latestAttachmentsRef = useRef(attachments);

  const textRef = useRef(text);
  const onTooLargeRef = useRef(onTooLarge);
  const setAttachmentsRef = useRef(setAttachments);
  useEffect(() => {
    textRef.current = text;
    onTooLargeRef.current = onTooLarge;
    setAttachmentsRef.current = setAttachments;
    latestAttachmentsRef.current = attachments;
  });

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const persistPending = useCallback((pending: { sessionId: string; text: string; attachments: ImageDraftItem[] }) => {
    const result = writeAgentImageDraft(pending.sessionId, pending.text, pending.attachments);
    if (result === "too-large") {
      onTooLargeRef.current();
    }
  }, []);

  const saveImageDraftFor = useCallback(
    (sid: string, draftText: string, atts: ImageDraftItem[]): ImageDraftWriteResult => {
      if (pendingRef.current?.sessionId === sid) {
        clearTimer();
        pendingRef.current = null;
      }
      const result = writeAgentImageDraft(sid, draftText, atts);
      if (result === "too-large") {
        onTooLargeRef.current();
      }
      return result;
    },
    [clearTimer],
  );

  const removeImageDraftFor = useCallback(
    (sid: string) => {
      if (pendingRef.current?.sessionId === sid) {
        clearTimer();
        pendingRef.current = null;
      }
      removeAgentImageDraft(sid);
    },
    [clearTimer],
  );

  const setLocalAttachments = useCallback(
    (next: ImageDraftItem[]) => {
      clearTimer();
      pendingRef.current = null;
      if (next !== latestAttachmentsRef.current) {
        latestAttachmentsRef.current = next;
        skipSaveRef.current = true;
        setAttachmentsRef.current(next);
      }
    },
    [clearTimer],
  );

  // セッション切替時: 切替元の保留保存を flush してから切替先の画像を復元する。
  // 下書きがなければ空にする（Aの画像がBに表示されない）。
  useEffect(() => {
    if (sessionRef.current && sessionRef.current !== sessionId) {
      const pending = pendingRef.current;
      if (pending) {
        clearTimer();
        pendingRef.current = null;
        persistPending(pending);
      }
    }
    sessionRef.current = sessionId;
    clearTimer();
    pendingRef.current = null;
    if (!sessionId) {
      skipSaveRef.current = true;
      setAttachmentsRef.current([]);
      return;
    }
    const restored = readAgentImageDraft(sessionId);
    latestAttachmentsRef.current = restored;
    skipSaveRef.current = true;
    setAttachmentsRef.current(restored);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, clearTimer, persistPending]);

  // 添付変更をデバウンス保存する。発火時にセッション一致を検証し、
  // 古いタイマーが新セッションのキーへ書き込むのを防ぐ。
  useEffect(() => {
    if (skipSaveRef.current) {
      skipSaveRef.current = false;
      return;
    }
    const sid = sessionRef.current;
    if (!sid) return;
    const snapshot = attachments.map((att) => ({ ...att }));
    pendingRef.current = { sessionId: sid, text: textRef.current, attachments: snapshot };
    clearTimer();
    timerRef.current = window.setTimeout(() => {
      const pending = pendingRef.current;
      timerRef.current = null;
      pendingRef.current = null;
      if (!pending) return;
      if (sessionRef.current !== pending.sessionId) return;
      persistPending(pending);
    }, debounceMs);
    return () => {
      clearTimer();
    };
  }, [attachments, debounceMs, clearTimer, persistPending]);

  // unmount 時は保留中の保存を flush する。
  useEffect(() => {
    return () => {
      const pending = pendingRef.current;
      if (pending) {
        pendingRef.current = null;
        writeAgentImageDraft(pending.sessionId, pending.text, pending.attachments);
      }
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { saveImageDraftFor, removeImageDraftFor, setLocalAttachments };
}
