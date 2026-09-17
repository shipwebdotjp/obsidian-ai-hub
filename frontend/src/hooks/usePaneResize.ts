import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";

type PaneSide = "left" | "right";

type UsePaneResizeOptions = {
  /** 初期幅。CSS の長さとして渡す（例: "50%", "20rem"）。 */
  defaultSize: string;
  /** どちら側のペインをリサイズするか。既定は "left"。 */
  side?: PaneSide;
  /** リサイズ対象ペインの最小幅(px)。 */
  minSize?: number;
  /** 反対側ペインの最小幅(px)。 */
  minOther?: number;
  /** 幅を保持する CSS 変数名。 */
  cssVar?: string;
  /** キーボード操作の 1 回あたりの変化量(px)。 */
  step?: number;
  /**
   * 幅を localStorage に永続化するためのキー。
   * 未指定ならセッション内のみ保持する。
   */
  storageKey?: string;
};

export type PaneResizeHandleProps = {
  onPointerDown: (event: ReactPointerEvent<HTMLElement>) => void;
  onKeyDown: (event: ReactKeyboardEvent<HTMLElement>) => void;
  role: "separator";
  "aria-orientation": "vertical";
  "aria-valuenow"?: number;
  "aria-valuemin"?: number;
  "aria-valuemax"?: number;
  tabIndex: number;
};

const HANDLE_WIDTH = 6;

/** 一覧:詳細の既定比率（一覧 約33% / 詳細 約67%）。 */
export const DEFAULT_LIST_RATIO = "33.3333%";

const PANE_RATIO_PREFIX = "oaih:pane-ratio:";

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function getStorage(): Storage | null {
  try {
    if (typeof window === "undefined" || !window.localStorage) return null;
    return window.localStorage;
  } catch {
    return null;
  }
}

/** 保存済み比率(0–1)を読み出す。不正値・未保存なら null。 */
function readStoredRatio(storageKey?: string): number | null {
  if (!storageKey) return null;
  try {
    const raw = getStorage()?.getItem(PANE_RATIO_PREFIX + storageKey);
    if (!raw) return null;
    const ratio = Number(raw);
    if (!Number.isFinite(ratio) || ratio <= 0 || ratio >= 1) return null;
    return ratio;
  } catch {
    return null;
  }
}

/** "%" 指定の初期値から比率を取り出す。px 等の絶対値なら null。 */
function parseRatio(size: string): number | null {
  const match = /^([\d.]+)%$/.exec(size.trim());
  if (!match) return null;
  const ratio = Number(match[1]) / 100;
  return Number.isFinite(ratio) && ratio > 0 && ratio < 1 ? ratio : null;
}

/**
 * 2 ペインの境界をドラッグでリサイズするための共通フック。
 *
 * - 幅は CSS 変数（既定 `--pane-size`）で管理し、対象ペイン側で
 *   `lg:w-[var(--pane-size)]` のように参照する。
 * - `storageKey` を渡すと比率(0–1)を localStorage に保存し、次回起動時に
 *   `%` として復元する（ウィンドウ幅に比例）。未指定ならセッション内のみ。
 * - ドラッグ中の値は px に変換される（初期値は "33.3333%" などの相対値で可）。
 * - ウィンドウ縮小で潰れないよう ResizeObserver で min/max にクランプする。
 *   縦積み・非表示（非分割レイアウト）のときはクランプしない。
 */
export function usePaneResize({
  defaultSize,
  side = "left",
  minSize = 240,
  minOther = 320,
  cssVar = "--pane-size",
  step = 16,
  storageKey,
}: UsePaneResizeOptions) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const paneRef = useRef<HTMLDivElement | null>(null);
  const dragState = useRef<{
    startX: number;
    startWidth: number;
  } | null>(null);
  const pendingRatioRef = useRef<number | null>(null);
  const prevBodyStylesRef = useRef<{ cursor: string; userSelect: string } | null>(null);
  const [size, setSize] = useState<string>(() => {
    const stored = readStoredRatio(storageKey);
    return stored === null ? defaultSize : `${stored * 100}%`;
  });
  const [ratio, setRatio] = useState<number | null>(
    () => readStoredRatio(storageKey) ?? parseRatio(defaultSize),
  );
  const [isDragging, setIsDragging] = useState(false);

  const measureBounds = useCallback(() => {
    const pane = paneRef.current;
    const container = containerRef.current;
    if (!pane || !container) return null;
    const paneWidth = pane.getBoundingClientRect().width;
    const containerWidth = container.getBoundingClientRect().width;
    const maxWidth = Math.max(minSize, containerWidth - minOther - HANDLE_WIDTH);
    return { paneWidth, containerWidth, maxWidth };
  }, [minSize, minOther]);

  const persistRatio = useCallback(
    (value: number) => {
      if (!storageKey) return;
      try {
        getStorage()?.setItem(PANE_RATIO_PREFIX + storageKey, String(value));
      } catch {
        // SecurityError / quota 等でも操作をブロックしない。
      }
    },
    [storageKey],
  );

  const applySize = useCallback(
    (widthPx: number, containerWidth: number) => {
      const next = Math.round(widthPx);
      setSize(`${next}px`);
      if (containerWidth > 0) {
        const nextRatio = next / containerWidth;
        pendingRatioRef.current = nextRatio;
        setRatio(nextRatio);
      }
    },
    [],
  );

  const handleWindowMove = useCallback(
    (event: PointerEvent) => {
      const state = dragState.current;
      if (!state) return;
      // ドラッグ中にコンテナ幅が変わっても正しくクランプ/記録するため毎回計測する。
      const bounds = measureBounds();
      if (!bounds) return;
      const delta = event.clientX - state.startX;
      const raw = side === "left" ? state.startWidth + delta : state.startWidth - delta;
      applySize(clamp(raw, minSize, bounds.maxWidth), bounds.containerWidth);
    },
    [applySize, measureBounds, minSize, side],
  );

  const restoreBodyStyles = useCallback(() => {
    const prev = prevBodyStylesRef.current;
    if (prev) {
      document.body.style.cursor = prev.cursor;
      document.body.style.userSelect = prev.userSelect;
      prevBodyStylesRef.current = null;
    }
  }, []);

  const handleWindowUp = useCallback(() => {
    dragState.current = null;
    setIsDragging(false);
    if (pendingRatioRef.current !== null) {
      persistRatio(pendingRatioRef.current);
      pendingRatioRef.current = null;
    }
    window.removeEventListener("pointermove", handleWindowMove);
    window.removeEventListener("pointerup", handleWindowUp);
    window.removeEventListener("pointercancel", handleWindowUp);
    restoreBodyStyles();
  }, [handleWindowMove, persistRatio, restoreBodyStyles]);

  useEffect(() => {
    return () => {
      if (pendingRatioRef.current !== null) {
        persistRatio(pendingRatioRef.current);
        pendingRatioRef.current = null;
      }
      window.removeEventListener("pointermove", handleWindowMove);
      window.removeEventListener("pointerup", handleWindowUp);
      window.removeEventListener("pointercancel", handleWindowUp);
      restoreBodyStyles();
    };
  }, [handleWindowMove, handleWindowUp, persistRatio, restoreBodyStyles]);

  // ウィンドウ/コンテナ縮小時に最小・最大へクランプする。
  // 縦積み（モバイル）や非表示ペインでは幅の意味が変わるため何もしない。
  useEffect(() => {
    const container = containerRef.current;
    if (!container || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      const bounds = measureBounds();
      if (!bounds) return;
      if (bounds.paneWidth <= 0) return;
      if (bounds.paneWidth >= bounds.containerWidth - HANDLE_WIDTH) return;
      if (bounds.paneWidth < minSize - 0.5) {
        applySize(minSize, bounds.containerWidth);
        if (bounds.containerWidth > 0) persistRatio(minSize / bounds.containerWidth);
      } else if (bounds.paneWidth > bounds.maxWidth + 0.5) {
        applySize(bounds.maxWidth, bounds.containerWidth);
        if (bounds.containerWidth > 0) persistRatio(bounds.maxWidth / bounds.containerWidth);
      }
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, [applySize, measureBounds, minSize, persistRatio]);

  const onPointerDown = useCallback(
    (event: ReactPointerEvent<HTMLElement>) => {
      if (!event.isPrimary) return;
      if (event.pointerType === "mouse" && event.button !== 0) return;
      const bounds = measureBounds();
      if (!bounds) return;
      // フォーカスを奪わないよう preventDefault しない。ドラッグ中の選択は
      // body の userSelect で抑止する。
      event.currentTarget.focus?.({ preventScroll: true });
      dragState.current = {
        startX: event.clientX,
        startWidth: bounds.paneWidth,
      };
      setIsDragging(true);
      prevBodyStylesRef.current = {
        cursor: document.body.style.cursor,
        userSelect: document.body.style.userSelect,
      };
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
      window.addEventListener("pointermove", handleWindowMove);
      window.addEventListener("pointerup", handleWindowUp);
      window.addEventListener("pointercancel", handleWindowUp);
    },
    [handleWindowMove, handleWindowUp, measureBounds],
  );

  const onKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLElement>) => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      const bounds = measureBounds();
      if (!bounds) return;
      event.preventDefault();
      const direction = event.key === "ArrowRight" ? 1 : -1;
      const raw =
        side === "left"
          ? bounds.paneWidth + direction * step
          : bounds.paneWidth - direction * step;
      const next = clamp(raw, minSize, bounds.maxWidth);
      applySize(next, bounds.containerWidth);
      if (bounds.containerWidth > 0) {
        persistRatio(next / bounds.containerWidth);
      }
    },
    [applySize, measureBounds, minSize, persistRatio, side, step],
  );

  const containerStyle = { [cssVar]: size } as CSSProperties;
  const handleProps: PaneResizeHandleProps = {
    onPointerDown,
    onKeyDown,
    role: "separator",
    "aria-orientation": "vertical",
    "aria-valuenow": ratio === null ? undefined : Math.round(ratio * 100),
    "aria-valuemin": 0,
    "aria-valuemax": 100,
    tabIndex: 0,
  };

  return { containerRef, paneRef, containerStyle, isDragging, handleProps };
}
