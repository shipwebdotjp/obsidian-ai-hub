import { useCallback, useEffect, useRef, useState } from "react";
import { getApiErrorMessage } from "../utils/error";

interface ListResult<T> {
  items: T[];
  total?: number;
}

interface UseListResourceOptions<T> {
  fetcher: () => Promise<ListResult<T>>;
  /**
   * この値が変わると再取得する（フィルタ条件など）。
   * 再取得の判定に使うため、プリミティブ値のみを渡すこと。
   */
  deps: unknown[];
  /** 外部から再取得を促すキー。 */
  refreshKey?: number;
  /** 取得成功時の追加処理（総件数更新・選択解除など）。 */
  onSuccess?: (result: ListResult<T>) => void;
  /** 取得失敗時のメッセージ。 */
  fallbackError: string;
}

/**
 * 一覧取得の共通ロジック。応答の競合を AbortController で防ぎ（古い応答を
 * 無視する。下位 API が signal 非対応のため通信自体の中断はしない）、
 * loading / error 状態と `reload` を提供する。
 */
export function useListResource<T>({
  fetcher,
  deps,
  refreshKey = 0,
  onSuccess,
  fallbackError,
}: UseListResourceOptions<T>) {
  const [items, setItems] = useState<T[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const onSuccessRef = useRef(onSuccess);
  onSuccessRef.current = onSuccess;

  const reload = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    setError(null);
    try {
      const result = await fetcherRef.current();
      if (controller.signal.aborted) return;
      setItems(result.items);
      onSuccessRef.current?.(result);
    } catch (e) {
      if (controller.signal.aborted) return;
      setError(getApiErrorMessage(e, fallbackError));
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fallbackError, ...deps]);

  useEffect(() => {
    void reload();
    return () => {
      abortRef.current?.abort();
    };
  }, [reload, refreshKey]);

  return { items, loading, error, reload };
}
