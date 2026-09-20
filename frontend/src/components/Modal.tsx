import { useEffect, type ReactNode } from "react";

export interface ModalProps {
  /** 見出し要素の id。 */
  labelledBy?: string;
  onClose: () => void;
  /** カードのクラス。既定は確認ダイアログ向けの小さいカード。 */
  cardClassName?: string;
  children: ReactNode;
}

const DEFAULT_CARD = "w-full max-w-sm rounded-xl bg-white p-5 shadow-lg space-y-3";

/**
 * オーバーレイ付きモーダルの共通シェル。背景クリックと Escape で閉じ、
 * カード内クリックは伝播を止める。中身は呼び出し側が渡す。
 */
export default function Modal({
  labelledBy,
  onClose,
  cardClassName = DEFAULT_CARD,
  children,
}: ModalProps) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !event.isComposing) onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby={labelledBy}
      onClick={onClose}
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
    >
      <div onClick={(e) => e.stopPropagation()} className={cardClassName}>
        {children}
      </div>
    </div>
  );
}
