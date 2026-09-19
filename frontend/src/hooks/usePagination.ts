import { useCallback, useState } from "react";

export interface Pagination {
  page: number;
  limit: number;
  offset: number;
  total: number;
  totalPages: number;
  setTotal: (total: number) => void;
  setPage: (page: number) => void;
}

interface State {
  key: string | number;
  page: number;
  total: number;
}

/**
 * 一覧ページングの共通状態。`resetKey` が変わるとページと総件数を初期化する。
 * 総件数が減って現在ページが範囲外になった場合は最終ページへクランプする。
 */
export function usePagination(
  resetKey: string | number,
  initialLimit = 50,
): Pagination {
  const limit = initialLimit;
  const [state, setState] = useState<State>({
    key: resetKey,
    page: 1,
    total: 0,
  });

  if (!Object.is(state.key, resetKey)) {
    setState({ key: resetKey, page: 1, total: 0 });
  }

  const synced = Object.is(state.key, resetKey);
  const page = synced ? state.page : 1;
  const total = synced ? state.total : 0;
  const totalPages = Math.max(1, Math.ceil(total / limit));
  const safePage = Math.min(page, totalPages);

  if (safePage !== page) {
    setState({ key: resetKey, page: safePage, total });
  }

  const setTotal = useCallback(
    (next: number) => {
      setState((s) => {
        if (!Object.is(s.key, resetKey) || s.total === next) return s;
        return { ...s, total: next };
      });
    },
    [resetKey],
  );

  const setPage = useCallback((next: number) => {
    const target = Number.isFinite(next) ? Math.max(1, Math.floor(next)) : 1;
    setState((s) => (s.page === target ? s : { ...s, page: target }));
  }, []);

  return {
    page: safePage,
    limit,
    offset: (safePage - 1) * limit,
    total,
    totalPages,
    setTotal,
    setPage,
  };
}
