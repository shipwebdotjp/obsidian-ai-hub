import React, { useEffect, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import { listMedia, getMediaInfo, deleteMediaItem } from "../../api/client";
import { GeneratedMediaCard } from "./GeneratedMediaCard";
import { taskAgentDetailPath, workflowRunPath, ROUTES } from "../../constants/routes";

interface MediaItem {
  media_id: string;
  media_type: string;
  source: string;
  relative_path: string;
  filename: string;
  mime_type: string;
  width?: number;
  height?: number;
  byte_size?: number;
  provider?: string;
  model?: string;
  prompt?: string;
  metadata_json?: string;
  metadata?: Record<string, unknown>;
  session_id?: string;
  run_id?: string;
  task_id?: string;
  workflow_run_id?: string;
  created_at: string;
  url: string;
  download_url: string;
}

export default function MediaGalleryPage() {
  const [items, setItems] = useState<MediaItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);

  // Filters
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [sourceFilter, setSourceFilter] = useState<string>("");
  const [typeFilter, setTypeFilter] = useState<string>("");

  // Selected item modal
  const [selectedMediaId, setSelectedMediaId] = useState<string | null>(null);
  const [selectedDetail, setSelectedDetail] = useState<MediaItem | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [copyFeedback, setCopyFeedback] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState(false);

  // Debounce search input
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(searchQuery);
    }, 300);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  const fetchMedia = useCallback(
    async (isLoadMore = false, cursorToUse?: string | null) => {
      if (isLoadMore) {
        setLoadingMore(true);
      } else {
        setLoading(true);
      }
      setError(null);

      try {
        const res = await listMedia({
          q: debouncedSearch || undefined,
          source: sourceFilter || undefined,
          media_type: typeFilter || undefined,
          limit: 24,
          cursor: isLoadMore ? cursorToUse ?? undefined : undefined,
        });

        if (isLoadMore) {
          setItems((prev) => [...prev, ...res.items]);
        } else {
          setItems(res.items);
        }
        setNextCursor(res.next_cursor);
        setHasMore(res.has_more);
      } catch (err: any) {
        setError(err?.message || "メディア一覧の取得に失敗しました");
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [debouncedSearch, sourceFilter, typeFilter]
  );

  useEffect(() => {
    fetchMedia(false);
  }, [fetchMedia]);

  // Fetch detail modal info
  useEffect(() => {
    if (!selectedMediaId) {
      setSelectedDetail(null);
      setDeleteConfirm(false);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    getMediaInfo(selectedMediaId)
      .then((detail) => {
        if (!cancelled) {
          setSelectedDetail(detail);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err?.message || "メディア詳細の取得に失敗しました");
        }
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedMediaId]);

  const handleDelete = async () => {
    if (!selectedMediaId) return;
    setDeleting(true);
    try {
      await deleteMediaItem(selectedMediaId);
      setItems((prev) => prev.filter((item) => item.media_id !== selectedMediaId));
      setSelectedMediaId(null);
    } catch (err: any) {
      alert(`削除に失敗しました: ${err?.message || err}`);
    } finally {
      setDeleting(false);
      setDeleteConfirm(false);
    }
  };

  const copyToClipboard = (text: string, label: string) => {
    navigator.clipboard.writeText(text);
    setCopyFeedback(`${label}をコピーしました`);
    setTimeout(() => setCopyFeedback(null), 2000);
  };

  const formatByteSize = (bytes?: number) => {
    if (!bytes) return "不明";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const formatSourceLabel = (src: string) => {
    switch (src) {
      case "generated":
        return "生成物";
      case "upload":
        return "添付ファイル";
      case "import":
        return "取り込み";
      default:
        return src;
    }
  };

  return (
    <div className="flex h-full flex-col bg-slate-50 p-4 lg:p-6 overflow-y-auto">
      {/* Header */}
      <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-900">メディアギャラリー</h1>
          <p className="text-xs text-slate-500 mt-1">
            生成画像および添付・取り込みメディアの一覧・閲覧・検索
          </p>
        </div>
      </div>

      {/* Filter Bar */}
      <div className="mb-6 flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
        <div className="flex-1 min-w-[200px]">
          <input
            type="text"
            placeholder="プロンプト・ファイル名・モデル検索…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full rounded-lg border border-slate-300 px-3 py-1.5 text-sm placeholder-slate-400 focus:border-slate-800 focus:outline-none"
          />
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs font-medium text-slate-600">ソース:</label>
          <select
            value={sourceFilter}
            onChange={(e) => setSourceFilter(e.target.value)}
            className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm text-slate-700 focus:border-slate-800 focus:outline-none"
          >
            <option value="">すべて</option>
            <option value="generated">生成物</option>
            <option value="upload">添付</option>
            <option value="import">取り込み</option>
          </select>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs font-medium text-slate-600">種別:</label>
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm text-slate-700 focus:border-slate-800 focus:outline-none"
          >
            <option value="">すべて</option>
            <option value="image">画像</option>
          </select>
        </div>
      </div>

      {/* Main Content */}
      {error && (
        <div className="mb-4 rounded-lg bg-rose-50 border border-rose-200 p-3 text-xs text-rose-700">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex h-48 items-center justify-center text-sm text-slate-500">
          メディアを読み込み中…
        </div>
      ) : items.length === 0 ? (
        <div className="flex h-48 flex-col items-center justify-center rounded-xl border border-dashed border-slate-300 bg-white p-6 text-center text-slate-500">
          <p className="text-sm font-medium">該当するメディアが見つかりませんでした</p>
          <p className="mt-1 text-xs text-slate-400">
            検索条件やフィルタを変更してみてください
          </p>
        </div>
      ) : (
        <div className="space-y-6">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
            {items.map((item) => (
              <div
                key={item.media_id}
                onClick={() => setSelectedMediaId(item.media_id)}
                className="group relative cursor-pointer overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm transition hover:border-slate-400 hover:shadow"
              >
                <div className="flex aspect-square w-full items-center justify-center overflow-hidden bg-slate-100">
                  <GeneratedMediaCard
                    media={{
                      media_type: item.media_type,
                      media_id: item.media_id,
                      url: item.url,
                      download_url: item.download_url,
                      mime_type: item.mime_type,
                      width: item.width,
                      height: item.height,
                      filename: item.filename,
                    }}
                    className="flex h-full w-full items-center justify-center"
                  />
                </div>
                <div className="p-2.5">
                  <div className="flex items-center justify-between gap-1">
                    <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-600">
                      {formatSourceLabel(item.source)}
                    </span>
                    <span className="text-[10px] text-slate-400">
                      {new Date(item.created_at).toLocaleDateString("ja-JP")}
                    </span>
                  </div>
                  {item.prompt ? (
                    <p className="mt-1.5 line-clamp-2 text-xs text-slate-700" title={item.prompt}>
                      {item.prompt}
                    </p>
                  ) : (
                    <p className="mt-1.5 truncate text-xs text-slate-400 italic">
                      {item.filename}
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>

          {/* Load More Button */}
          {hasMore && (
            <div className="flex justify-center pt-2 pb-6">
              <button
                type="button"
                onClick={() => fetchMedia(true, nextCursor)}
                disabled={loadingMore}
                className="rounded-lg border border-slate-300 bg-white px-5 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50 disabled:opacity-50"
              >
                {loadingMore ? "読み込み中…" : "さらに読み込む"}
              </button>
            </div>
          )}
        </div>
      )}

      {/* Detail Modal */}
      {selectedMediaId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
          <div className="relative max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-2xl bg-white p-6 shadow-xl flex flex-col">
            <div className="flex items-center justify-between border-b border-slate-200 pb-3">
              <h2 className="text-lg font-bold text-slate-900">メディア詳細</h2>
              <button
                type="button"
                onClick={() => setSelectedMediaId(null)}
                className="rounded text-slate-400 hover:bg-slate-100 hover:text-slate-600 p-1"
              >
                ✕
              </button>
            </div>

            {copyFeedback && (
              <div className="my-2 rounded bg-emerald-50 border border-emerald-200 p-2 text-xs text-emerald-800">
                {copyFeedback}
              </div>
            )}

            {detailLoading || !selectedDetail ? (
              <div className="flex h-64 items-center justify-center text-sm text-slate-500">
                読み込み中…
              </div>
            ) : (
              <div className="mt-4 flex flex-col gap-6 md:flex-row">
                {/* Media Preview Box */}
                <div className="flex flex-1 flex-col items-center justify-center rounded-xl border border-slate-200 bg-slate-900/5 p-4 min-h-[250px]">
                  <GeneratedMediaCard
                    media={{
                      media_type: selectedDetail.media_type,
                      media_id: selectedDetail.media_id,
                      url: selectedDetail.url,
                      download_url: selectedDetail.download_url,
                      mime_type: selectedDetail.mime_type,
                      width: selectedDetail.width,
                      height: selectedDetail.height,
                      filename: selectedDetail.filename,
                    }}
                  />
                </div>

                {/* Metadata List */}
                <div className="flex flex-1 flex-col space-y-3 text-xs text-slate-700">
                  <div>
                    <span className="font-semibold text-slate-500 block mb-0.5">Media ID</span>
                    <div className="flex items-center gap-2">
                      <code className="rounded bg-slate-100 px-1.5 py-0.5 text-slate-800 break-all font-mono">
                        {selectedDetail.media_id}
                      </code>
                      <button
                        type="button"
                        onClick={() => copyToClipboard(selectedDetail.media_id, "Media ID")}
                        className="text-blue-600 hover:underline shrink-0"
                      >
                        コピー
                      </button>
                    </div>
                  </div>

                  {selectedDetail.prompt && (
                    <div>
                      <span className="font-semibold text-slate-500 block mb-0.5">プロンプト</span>
                      <p className="rounded bg-slate-50 p-2 border border-slate-200 text-slate-800 whitespace-pre-wrap break-words">
                        {selectedDetail.prompt}
                      </p>
                    </div>
                  )}

                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <span className="font-semibold text-slate-500 block">ソース</span>
                      <span>{formatSourceLabel(selectedDetail.source)}</span>
                    </div>
                    <div>
                      <span className="font-semibold text-slate-500 block">ファイル名</span>
                      <span className="break-all">{selectedDetail.filename}</span>
                    </div>
                    <div>
                      <span className="font-semibold text-slate-500 block">プロバイダ / モデル</span>
                      <span>
                        {selectedDetail.provider || "openai"} / {selectedDetail.model || "-"}
                      </span>
                    </div>
                    <div>
                      <span className="font-semibold text-slate-500 block">サイズ / 容量</span>
                      <span>
                        {selectedDetail.width && selectedDetail.height
                          ? `${selectedDetail.width}×${selectedDetail.height}`
                          : "不明"}{" "}
                        ({formatByteSize(selectedDetail.byte_size)})
                      </span>
                    </div>
                    <div>
                      <span className="font-semibold text-slate-500 block">作成日時</span>
                      <span>{new Date(selectedDetail.created_at).toLocaleString("ja-JP")}</span>
                    </div>
                  </div>

                  {/* Origin Links */}
                  {(selectedDetail.session_id || selectedDetail.task_id || selectedDetail.workflow_run_id) && (
                    <div className="border-t border-slate-200 pt-3">
                      <span className="font-semibold text-slate-500 block mb-1">作成元</span>
                      <div className="space-y-1">
                        {selectedDetail.session_id && (
                          <div>
                            エージェント会話:{" "}
                            <Link
                              to={ROUTES.AGENTS}
                              className="text-blue-600 hover:underline font-mono"
                            >
                              {selectedDetail.session_id}
                            </Link>
                          </div>
                        )}
                        {selectedDetail.task_id && (
                          <div>
                            タスク:{" "}
                            <Link
                              to={taskAgentDetailPath(selectedDetail.task_id)}
                              className="text-blue-600 hover:underline font-mono"
                            >
                              {selectedDetail.task_id}
                            </Link>
                          </div>
                        )}
                        {selectedDetail.workflow_run_id && (
                          <div>
                            ワークフロー実行:{" "}
                            <Link
                              to={workflowRunPath(selectedDetail.workflow_run_id)}
                              className="text-blue-600 hover:underline font-mono"
                            >
                              {selectedDetail.workflow_run_id}
                            </Link>
                          </div>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Actions */}
                  <div className="mt-auto border-t border-slate-200 pt-4 flex items-center justify-between">
                    {deleteConfirm ? (
                      <div className="flex items-center gap-2">
                        <span className="text-rose-600 font-medium">本当に削除しますか？</span>
                        <button
                          type="button"
                          onClick={handleDelete}
                          disabled={deleting}
                          className="rounded bg-rose-600 px-3 py-1 text-white hover:bg-rose-700 disabled:opacity-50"
                        >
                          {deleting ? "削除中…" : "実行"}
                        </button>
                        <button
                          type="button"
                          onClick={() => setDeleteConfirm(false)}
                          className="rounded bg-slate-200 px-3 py-1 text-slate-700 hover:bg-slate-300"
                        >
                          キャンセル
                        </button>
                      </div>
                    ) : (
                      <button
                        type="button"
                        onClick={() => setDeleteConfirm(true)}
                        className="rounded border border-rose-200 bg-rose-50 px-3 py-1 text-rose-700 hover:bg-rose-100"
                      >
                        削除
                      </button>
                    )}

                    <button
                      type="button"
                      onClick={() =>
                        copyToClipboard(
                          `${window.location.origin}${selectedDetail.url}`,
                          "メディアURL"
                        )
                      }
                      className="rounded border border-slate-300 bg-white px-3 py-1 text-slate-700 hover:bg-slate-50"
                    >
                      URLコピー
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
