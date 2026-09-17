import type { PaneResizeHandleProps } from "../hooks/usePaneResize";

type SplitHandleProps = {
  handleProps: PaneResizeHandleProps;
  isDragging: boolean;
  /** 表示するブレークポイント。既定は lg 以上。 */
  visibilityClassName?: string;
  ariaLabel?: string;
  className?: string;
};

export default function SplitHandle({
  handleProps,
  isDragging,
  visibilityClassName = "hidden lg:flex",
  ariaLabel = "ペインの境界をドラッグして幅を変更",
  className = "",
}: SplitHandleProps) {
  return (
    <div
      {...handleProps}
      aria-label={ariaLabel}
      className={`${visibilityClassName} w-1.5 shrink-0 cursor-col-resize touch-none items-center justify-center bg-slate-200 transition-colors hover:bg-blue-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-600 ${
        isDragging ? "bg-blue-500" : ""
      } ${className}`}
    >
      <div aria-hidden="true" className="h-8 w-0.5 rounded-full bg-slate-400" />
    </div>
  );
}
