import { ApiError } from "../api/client";

/**
 * API エラーならそのメッセージ、そうでなければ fallback を返す。
 * 呼び出し側で個別の文言を表示したい箇所で使う。
 */
export function getApiErrorMessage(e: unknown, fallback: string): string {
  if (e instanceof ApiError && e.message) return e.message;
  return fallback;
}

/**
 * Error（ApiError を含む）ならそのメッセージ、そうでなければ fallback を返す。
 */
export function getErrorMessage(e: unknown, fallback: string): string {
  if (e instanceof Error && e.message) return e.message;
  return fallback;
}
