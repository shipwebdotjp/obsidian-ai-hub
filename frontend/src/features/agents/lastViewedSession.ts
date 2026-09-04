/**
 * AgentsPage の最終表示会話（last-viewed session）の保存・復元。
 *
 * `/agents` を `session_id` なしで開いたときに、同一ブラウザプロファイル内で
 * 最後に表示対象となった会話セッションを復元するために使う。
 * - 保存先は `localStorage` のみ（ブラウザ再起動後も維持する）。
 * - 値は JSON オブジェクト `{ session_id, savedAt }` とする。会話IDだけなら
 *   生文字列でも足りるが、`agent-draft:<sessionId>`（`useAgentImageDraft`）と
 *   同じく JSON 形状にしておくことで、将来の拡張（agent 解決補助など）を
 *   キー移行なしで吸収できる。`session_id` は snake_case で URL パラメータ名
 *   と一致させる。
 * - `sessionStorage`（タブ寿命）のプロンプト下書き・SSEカーソルとは寿命が
 *   異なるため、キーを分離する。
 * - プライベートモード・quota超過・破損値などストレージ例外時は例外を投げず、
 *   読み取りは `null`、書き込み・削除は無視する。呼び出し側は従来どおり
 *   先頭会話へフォールバックする。
 */

export const LAST_VIEWED_SESSION_STORAGE_KEY =
  "obsidian-ai-hub:agents-last-viewed-session:v1";

interface LastViewedSessionRecord {
  session_id?: unknown;
  savedAt?: unknown;
}

function getLocalStorage(): Storage | null {
  try {
    if (typeof window === "undefined" || !window.localStorage) return null;
    return window.localStorage;
  } catch {
    return null;
  }
}

/** 保存済みの最終表示会話の session_id を返す。なければ null。例外は投げない。 */
export function readLastViewedSessionId(): string | null {
  try {
    const storage = getLocalStorage();
    if (!storage) return null;
    const raw = storage.getItem(LAST_VIEWED_SESSION_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as LastViewedSessionRecord;
    const sessionId = parsed?.session_id;
    return typeof sessionId === "string" && sessionId.length > 0 ? sessionId : null;
  } catch {
    // 破損・読み取り不可の保存値は「保存なし」と同じ扱いにする。
    return null;
  }
}

/** 指定セッションを最終表示会話として保存する。例外は投げない。 */
export function writeLastViewedSessionId(sessionId: string): void {
  try {
    const storage = getLocalStorage();
    if (!storage) return;
    if (!sessionId) {
      storage.removeItem(LAST_VIEWED_SESSION_STORAGE_KEY);
      return;
    }
    storage.setItem(
      LAST_VIEWED_SESSION_STORAGE_KEY,
      JSON.stringify({ session_id: sessionId, savedAt: new Date().toISOString() }),
    );
  } catch {
    // QuotaExceeded やプライベートモードでも画面をブロックしない。
  }
}

/** 保存済みの最終表示会話を削除する。例外は投げない。 */
export function clearLastViewedSessionId(): void {
  try {
    getLocalStorage()?.removeItem(LAST_VIEWED_SESSION_STORAGE_KEY);
  } catch {
    // ignore
  }
}
