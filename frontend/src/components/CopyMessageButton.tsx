import { ClipboardIcon } from "./ClipboardIcon";

interface CopyMessageButtonProps {
  content: string;
  messageId: string;
  copiedMessageId: string | null;
  onCopy: (content: string, messageId: string) => void;
  ariaLabel?: string;
}

/**
 * メッセージバブル共通のコピーボタン。
 * クリップボード型アイコンとコピー完了表示（チェック＋文言）を提供する。
 * コピー対象・完了状態の管理は呼び出し側が行う。
 */
export function CopyMessageButton({
  content,
  messageId,
  copiedMessageId,
  onCopy,
  ariaLabel = "メッセージをコピー",
}: CopyMessageButtonProps) {
  return (
    <button
      type="button"
      onClick={() => onCopy(content, messageId)}
      className="inline-flex items-center gap-1 cursor-pointer rounded px-1.5 py-0.5 hover:bg-slate-100 hover:text-slate-600 transition"
      aria-label={ariaLabel}
      data-testid={`copy-message-${messageId}`}
    >
      {copiedMessageId === messageId ? (
        <>
          <svg
            className="h-3.5 w-3.5 text-emerald-600"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M5 13l4 4L19 7"
            />
          </svg>
          <span className="text-emerald-700">コピーしました</span>
        </>
      ) : (
        <ClipboardIcon />
      )}
    </button>
  );
}
