export interface PaginationBarProps {
  page: number;
  totalPages: number;
  total: number;
  limit: number;
  onPageChange: (page: number) => void;
  disabled?: boolean;
}

export default function PaginationBar({
  page,
  totalPages,
  total,
  limit,
  onPageChange,
  disabled = false,
}: PaginationBarProps) {
  if (total <= 0) return null;
  const start = (page - 1) * limit + 1;
  const end = Math.min(page * limit, total);
  return (
    <div className="flex shrink-0 items-center justify-between border-t border-slate-200 bg-white px-4 py-3">
      <span className="text-xs font-semibold text-slate-600">
        全 {total} 件中 {start}-{end} 件
      </span>
      <div className="flex gap-2">
        <button
          type="button"
          disabled={disabled || page <= 1}
          onClick={() => onPageChange(page - 1)}
          className="cursor-pointer rounded border border-slate-300 bg-white px-3 py-1 text-xs text-slate-700 transition disabled:cursor-not-allowed disabled:opacity-50 enabled:hover:bg-slate-50"
        >
          前へ
        </button>
        <span className="self-center px-1 text-xs font-bold text-slate-700">
          {page} / {totalPages}
        </span>
        <button
          type="button"
          disabled={disabled || page >= totalPages}
          onClick={() => onPageChange(page + 1)}
          className="cursor-pointer rounded border border-slate-300 bg-white px-3 py-1 text-xs text-slate-700 transition disabled:cursor-not-allowed disabled:opacity-50 enabled:hover:bg-slate-50"
        >
          次へ
        </button>
      </div>
    </div>
  );
}
