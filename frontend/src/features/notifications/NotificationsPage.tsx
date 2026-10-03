import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  NotificationInboxItem,
  listNotifications,
  markNotificationAsRead,
} from "../../api/client";

export function NotificationsPage() {
  const [items, setItems] = useState<NotificationInboxItem[]>([]);
  const [total, setTotal] = useState<number>(0);
  const [page, setPage] = useState<number>(1);
  const [limit] = useState<number>(20);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const [statusFilter, setStatusFilter] = useState<"all" | "unread">("all");
  const [categoryFilter, setCategoryFilter] = useState<
    "all" | "action_required" | "failure"
  >("all");

  const [selectedItem, setSelectedItem] = useState<NotificationInboxItem | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const loadData = async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await listNotifications(
          { status: statusFilter, category: categoryFilter, page, limit },
          controller.signal,
        );
        if (controller.signal.aborted) return;
        setItems(res.items);
        setTotal(res.total);
      } catch (err: unknown) {
        if (!controller.signal.aborted) {
          setError(err instanceof Error ? err.message : "通知の取得に失敗しました");
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    };
    void loadData();
    return () => controller.abort();
  }, [statusFilter, categoryFilter, page, limit]);

  const handleOpenDetail = async (item: NotificationInboxItem) => {
    setSelectedItem(item);
    if (!item.read_at) {
      try {
        const updated = await markNotificationAsRead(item.notification_id);
        setSelectedItem(updated);
        setItems((prev) =>
          prev.map((i) =>
            i.notification_id === item.notification_id ? updated : i,
          ),
        );
      } catch {
        setError("既読への更新に失敗しました");
      }
    }
  };

  const totalPages = Math.ceil(total / limit) || 1;

  const renderCategoryBadge = (category: string) => {
    if (category === "action_required") {
      return (
        <span className="inline-flex items-center rounded bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800">
          要対応
        </span>
      );
    }
    return (
      <span className="inline-flex items-center rounded bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-800">
        失敗
      </span>
    );
  };

  const renderLineStatusLabel = (status: string) => {
    switch (status) {
      case "accepted":
        return <span className="text-emerald-700">LINE: API受理</span>;
      case "failed":
        return <span className="text-red-600">LINE: 送信失敗</span>;
      case "unknown":
        return <span className="text-amber-700">LINE: 結果不明</span>;
      case "in_progress":
        return <span className="text-blue-700">LINE: 処理中</span>;
      case "pending":
        return <span className="text-slate-500">LINE: 未試行</span>;
      default:
        return <span className="text-slate-500">LINE: 意図的スキップ</span>;
    }
  };

  const renderWebPushStatusLabel = (item: NotificationInboxItem) => {
    switch (item.web_push_status) {
      case "accepted":
        return <span className="text-emerald-700">Web Push: API受理 ({item.web_push_success_count}/{item.web_push_target_count})</span>;
      case "partial_accepted":
        return <span className="text-amber-700">Web Push: 一部受理 ({item.web_push_success_count}/{item.web_push_target_count})</span>;
      case "failed":
        return <span className="text-red-600">Web Push: 送信失敗 ({item.web_push_failure_count}/{item.web_push_target_count})</span>;
      case "unknown":
        return <span className="text-amber-700">Web Push: 結果不明</span>;
      case "in_progress":
        return <span className="text-blue-700">Web Push: 処理中</span>;
      case "pending":
        return <span className="text-slate-500">Web Push: 未試行</span>;
      default:
        return <span className="text-slate-500">Web Push: 意図的スキップ</span>;
    }
  };

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <h1 className="text-2xl font-bold text-slate-900">通知受信箱</h1>

        {/* Filters */}
        <div className="flex flex-wrap gap-2">
          {/* Status Filter */}
          <div className="inline-flex rounded-md shadow-sm" role="group">
            <button
              type="button"
              onClick={() => {
                setStatusFilter("all");
                setPage(1);
              }}
              className={`rounded-l-lg border border-slate-300 px-3 py-1.5 text-xs font-medium ${
                statusFilter === "all"
                  ? "bg-slate-900 text-white border-slate-900"
                  : "bg-white text-slate-700 hover:bg-slate-50"
              }`}
            >
              すべて
            </button>
            <button
              type="button"
              onClick={() => {
                setStatusFilter("unread");
                setPage(1);
              }}
              className={`rounded-r-lg border border-l-0 border-slate-300 px-3 py-1.5 text-xs font-medium ${
                statusFilter === "unread"
                  ? "bg-slate-900 text-white border-slate-900"
                  : "bg-white text-slate-700 hover:bg-slate-50"
              }`}
            >
              未読のみ
            </button>
          </div>

          {/* Category Filter */}
          <div className="inline-flex rounded-md shadow-sm" role="group">
            <button
              type="button"
              onClick={() => {
                setCategoryFilter("all");
                setPage(1);
              }}
              className={`rounded-l-lg border border-slate-300 px-3 py-1.5 text-xs font-medium ${
                categoryFilter === "all"
                  ? "bg-slate-900 text-white border-slate-900"
                  : "bg-white text-slate-700 hover:bg-slate-50"
              }`}
            >
              全種別
            </button>
            <button
              type="button"
              onClick={() => {
                setCategoryFilter("action_required");
                setPage(1);
              }}
              className={`border-y border-r border-slate-300 px-3 py-1.5 text-xs font-medium ${
                categoryFilter === "action_required"
                  ? "bg-slate-900 text-white border-slate-900"
                  : "bg-white text-slate-700 hover:bg-slate-50"
              }`}
            >
              要対応
            </button>
            <button
              type="button"
              onClick={() => {
                setCategoryFilter("failure");
                setPage(1);
              }}
              className={`rounded-r-lg border border-l-0 border-slate-300 px-3 py-1.5 text-xs font-medium ${
                categoryFilter === "failure"
                  ? "bg-slate-900 text-white border-slate-900"
                  : "bg-white text-slate-700 hover:bg-slate-50"
              }`}
            >
              失敗
            </button>
          </div>
        </div>
      </div>

      {error && (
        <div className="rounded-md bg-red-50 p-4 text-sm text-red-700">{error}</div>
      )}

      {/* Notification List */}
      <div className="rounded-lg border border-slate-200 bg-white shadow-sm">
        {loading ? (
          <div className="p-8 text-center text-slate-500">読み込み中...</div>
        ) : items.length === 0 ? (
          <div className="p-8 text-center text-slate-500">通知はありません</div>
        ) : (
          <ul className="divide-y divide-slate-100">
            {items.map((item) => (
              <li
                key={item.notification_id}
                role="button"
                tabIndex={0}
                onClick={() => handleOpenDetail(item)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    void handleOpenDetail(item);
                  }
                }}
                className={`cursor-pointer p-4 transition-colors hover:bg-slate-50 ${
                  !item.read_at ? "bg-blue-50/40" : ""
                }`}
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 space-y-1">
                    <div className="flex items-center gap-2">
                      {!item.read_at && (
                        <span className="h-2 w-2 rounded-full bg-blue-600" title="未読" />
                      )}
                      {renderCategoryBadge(item.category)}
                      <h3 className="font-medium text-slate-900">{item.title}</h3>
                    </div>
                    <p className="text-sm text-slate-600 line-clamp-2">{item.body}</p>
                    <div className="flex flex-wrap items-center gap-4 text-xs text-slate-500 pt-1">
                      <span>{new Date(item.created_at).toLocaleString("ja-JP")}</span>
                      <span>|</span>
                      {renderLineStatusLabel(item.line_status)}
                      <span>|</span>
                      {renderWebPushStatusLabel(item)}
                    </div>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between border-t border-slate-200 pt-4 text-xs text-slate-600">
          <div>
            全 {total} 件 ({page} / {totalPages} ページ)
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              className="rounded border border-slate-300 px-3 py-1 disabled:opacity-50"
            >
              前へ
            </button>
            <button
              type="button"
              disabled={page >= totalPages}
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              className="rounded border border-slate-300 px-3 py-1 disabled:opacity-50"
            >
              次へ
            </button>
          </div>
        </div>
      )}

      {/* Detail Modal */}
      {selectedItem && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          onClick={() => setSelectedItem(null)}
        >
          <div
            className="w-full max-w-lg space-y-4 rounded-lg bg-white p-6 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-2">
                {renderCategoryBadge(selectedItem.category)}
                <h2 className="text-lg font-bold text-slate-900">
                  {selectedItem.title}
                </h2>
              </div>
              <button
                type="button"
                onClick={() => setSelectedItem(null)}
                className="text-slate-400 hover:text-slate-600"
              >
                ✕
              </button>
            </div>

            <div className="space-y-2 border-y border-slate-100 py-3 text-sm text-slate-700">
              <div className="font-semibold text-slate-800">本文要約</div>
              <p className="whitespace-pre-wrap rounded bg-slate-50 p-3 text-slate-800">
                {selectedItem.body}
              </p>
            </div>

            {/* Delivery Details */}
            <div className="space-y-2 text-xs text-slate-600">
              <div className="font-semibold text-slate-800 text-sm">外部チャネル配信結果</div>
              <div className="grid grid-cols-2 gap-2 rounded border border-slate-200 p-3 bg-slate-50">
                <div className="space-y-1">
                  <div><span className="font-medium">LINE配信:</span> {renderLineStatusLabel(selectedItem.line_status)}</div>
                  {selectedItem.line_failure_reason && <div>理由: {selectedItem.line_failure_reason}</div>}
                  {selectedItem.line_status_at && <div>確定: {new Date(selectedItem.line_status_at).toLocaleString("ja-JP")}</div>}
                </div>
                <div className="space-y-1">
                  <div><span className="font-medium">Web Push:</span> {renderWebPushStatusLabel(selectedItem)}</div>
                  {selectedItem.web_push_failure_reason && <div>理由: {selectedItem.web_push_failure_reason}</div>}
                  {selectedItem.web_push_status_at && <div>確定: {new Date(selectedItem.web_push_status_at).toLocaleString("ja-JP")}</div>}
                </div>
              </div>
              <p className="text-[11px] text-slate-400">
                ※「成功＝外部チャネルへの受理であり、ユーザーの閲覧保証ではありません」
              </p>
            </div>

            <div className="text-xs text-slate-500 space-y-1">
              <div>発生日時: {new Date(selectedItem.created_at).toLocaleString("ja-JP")}</div>
              {selectedItem.read_at && (
                <div>既読日時: {new Date(selectedItem.read_at).toLocaleString("ja-JP")}</div>
              )}
            </div>

            <div className="flex items-center justify-between border-t border-slate-100 pt-4">
              <Link
                to={
                  selectedItem.relative_link.startsWith("/") && !selectedItem.relative_link.startsWith("//")
                    ? selectedItem.relative_link
                    : "/"
                }
                onClick={() => setSelectedItem(null)}
                className="inline-flex items-center rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
              >
                対象画面を開く
              </Link>
              <button
                type="button"
                onClick={() => setSelectedItem(null)}
                className="rounded-md border border-slate-300 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50"
              >
                閉じる
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
