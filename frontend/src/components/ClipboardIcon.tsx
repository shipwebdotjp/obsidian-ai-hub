interface ClipboardIconProps {
  className?: string;
}

/** クリップボード型アイコン（メッセージ／IDコピーボタン共通）。 */
export function ClipboardIcon({ className = "h-3.5 w-3.5" }: ClipboardIconProps) {
  return (
    <svg
      className={className}
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      aria-hidden="true"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h12a2 2 0 002-2V7a2 2 0 00-2-2h-2M8 5a2 2 0 002 2h4a2 2 0 002-2M8 5a2 2 0 012-2h4a2 2 0 012 2"
      />
    </svg>
  );
}
