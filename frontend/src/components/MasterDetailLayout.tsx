import type { ReactNode } from "react";
import SplitHandle from "./SplitHandle";
import { usePaneResize, type UsePaneResizeOptions } from "../hooks/usePaneResize";

export interface MasterDetailLayoutProps {
  list: ReactNode;
  detail: ReactNode;
  /** モバイルで詳細を表示するか。 */
  mobileOpen: boolean;
  /** モバイルの「一覧に戻る」ハンドラ。未指定なら戻るバーを出さない。 */
  onBack?: () => void;
  mobileTitle?: string;
  paneOptions: UsePaneResizeOptions;
  containerClassName?: string;
  listClassName?: string;
  detailClassName?: string;
  detailContentClassName?: string;
  /** SplitHandle の表示ブレークポイント。既定は lg。 */
  splitVisibilityClassName?: string;
  /** モバイル戻るバーの表示ブレークポイント。既定は lg:hidden。 */
  mobileBackVisibilityClassName?: string;
}

const DEFAULT_CONTAINER = "flex flex-1 flex-col overflow-hidden lg:flex-row";
// 幅は既定の CSS 変数 --pane-size を参照する。paneOptions.cssVar を変更する場合は
// listClassName で対応する lg:w-[var(...)] を上書きすること（Tailwind は動的な
// クラス名を生成できないため、ここで変数名を補間しない）。
const DEFAULT_LIST =
  "h-full w-full min-h-0 border-slate-200 lg:w-[var(--pane-size)]";
const DEFAULT_DETAIL =
  "h-full w-full min-w-0 min-h-0 overflow-hidden lg:flex-1";
const DEFAULT_DETAIL_CONTENT = "min-h-0 flex-1 overflow-hidden";

/**
 * 一覧ペインと詳細ペインの分割レイアウト。ペイン幅のリサイズ、モバイルでの
 * 表示切替（`mobileOpen`）と「一覧に戻る」バーを共通化する。
 *
 * `listClassName` / `detailClassName` に display ユーティリティ（`flex` / `hidden`
 * など）を含めないこと。表示切替は内部で付与する。
 */
export default function MasterDetailLayout({
  list,
  detail,
  mobileOpen,
  onBack,
  mobileTitle,
  paneOptions,
  containerClassName = DEFAULT_CONTAINER,
  listClassName = DEFAULT_LIST,
  detailClassName = DEFAULT_DETAIL,
  detailContentClassName = DEFAULT_DETAIL_CONTENT,
  splitVisibilityClassName = "hidden lg:flex",
  mobileBackVisibilityClassName = "lg:hidden",
}: MasterDetailLayoutProps) {
  const { containerRef, paneRef, containerStyle, isDragging, handleProps } =
    usePaneResize(paneOptions);

  const side = paneOptions.side ?? "left";

  const listPane = (
    <div
      ref={paneRef}
      className={`${listClassName} ${
        mobileOpen ? "hidden" : "flex flex-col"
      } lg:flex lg:flex-col`}
    >
      {list}
    </div>
  );

  const detailPane = (
    <div
      className={`${detailClassName} ${
        mobileOpen ? "flex flex-col" : "hidden"
      } lg:flex lg:flex-col`}
    >
      {onBack && (
        <div
          className={`flex items-center gap-2 border-b border-slate-200 p-3 ${mobileBackVisibilityClassName}`}
        >
          <button
            type="button"
            onClick={onBack}
            aria-label="一覧に戻る"
            className="cursor-pointer rounded px-2 py-1 text-sm text-slate-600 hover:bg-slate-100"
          >
            ← 一覧
          </button>
          {mobileTitle && (
            <span className="truncate text-sm font-semibold text-slate-700">
              {mobileTitle}
            </span>
          )}
        </div>
      )}
      <div className={detailContentClassName}>{detail}</div>
    </div>
  );

  return (
    <div ref={containerRef} style={containerStyle} className={containerClassName}>
      {side === "left" ? (
        <>
          {listPane}
          <SplitHandle
            handleProps={handleProps}
            isDragging={isDragging}
            visibilityClassName={splitVisibilityClassName}
          />
          {detailPane}
        </>
      ) : (
        <>
          {detailPane}
          <SplitHandle
            handleProps={handleProps}
            isDragging={isDragging}
            visibilityClassName={splitVisibilityClassName}
          />
          {listPane}
        </>
      )}
    </div>
  );
}
