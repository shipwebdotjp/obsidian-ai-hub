import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Check,
  ChevronDown,
  ChevronRight,
  FileText,
  Folder,
  FolderOpen,
  Loader2,
  RefreshCw,
  Search,
  X,
} from "lucide-react";
import { listVaultFiles, searchVault } from "../../api/client";
import type { VaultFileListItem } from "../../api/types";
import {
  MAX_AGENT_CONTEXT_REFS,
  buildVaultTree,
  filterVaultFiles,
  flattenVaultTree,
  formatVaultFileSize,
  vaultFileDirectory,
  vaultFileName,
  type FlatVaultRow,
  type PendingContextRef,
  type VaultTreeNode,
} from "./agentViewUtils";

interface ContentHit {
  path: string;
  snippet: string;
}

/**
 * Vault ファイル参照ピッカー（`@` と `+` メニューの共通UI）。
 *
 * - 検索欄: ファイル名/パスをクライアント側で即時部分一致
 * - 本文一致: クエリ2文字以上で既存 vault-search（hybrid）を debounce 検索
 * - クエリ空: ディレクトリツリーを辿って選択
 * - 選択は複数可（チップ側で保持）。ピッカー自体は開いたまま追加できる
 */
interface AgentVaultFilePickerProps {
  selected: PendingContextRef[];
  onToggle: (path: string) => void;
  onClose: () => void;
}

export function AgentVaultFilePicker({ selected, onToggle, onClose }: AgentVaultFilePickerProps) {
  const [files, setFiles] = useState<VaultFileListItem[] | null>(null);
  const [filesLoading, setFilesLoading] = useState(false);
  const [filesError, setFilesError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [highlight, setHighlight] = useState(0);
  const [contentHits, setContentHits] = useState<ContentHit[]>([]);
  const [contentSearching, setContentSearching] = useState(false);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const selectedPaths = useMemo(() => new Set(selected.map((r) => r.path)), [selected]);
  const limitReached = selected.length >= MAX_AGENT_CONTEXT_REFS;

  const loadFiles = useCallback(async () => {
    setFilesLoading(true);
    setFilesError(null);
    try {
      const res = await listVaultFiles();
      setFiles(res.items);
      // 初回はトップレベルディレクトリだけ展開しておく
      setExpanded((prev) => {
        if (prev.size > 0) return prev;
        const top = new Set<string>();
        for (const f of res.items) {
          const first = f.relative_path.split("/")[0];
          if (f.relative_path.includes("/")) top.add(first);
        }
        return top;
      });
    } catch (err) {
      setFilesError(err instanceof Error ? err.message : "ファイル一覧の取得に失敗しました。");
    } finally {
      setFilesLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadFiles();
  }, [loadFiles]);

  useEffect(() => {
    searchInputRef.current?.focus();
  }, []);

  const tree = useMemo(() => (files ? buildVaultTree(files) : []), [files]);
  const trimmedQuery = query.trim();
  const filenameMatches = useMemo(
    () => (files ? filterVaultFiles(files, trimmedQuery) : []),
    [files, trimmedQuery],
  );

  // 本文検索（debounce、クエリ2文字以上）
  useEffect(() => {
    if (trimmedQuery.length < 2) {
      setContentHits([]);
      setContentSearching(false);
      return;
    }
    setContentSearching(true);
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void searchVault({ q: trimmedQuery, k: 10, mode: "hybrid" }, controller.signal)
        .then((res) => {
          if (controller.signal.aborted) return;
          const seen = new Set<string>();
          const hits: ContentHit[] = [];
          for (const hit of res.items) {
            const path = hit.metadata?.relative_path;
            if (!path || seen.has(path)) continue;
            seen.add(path);
            const snippet = (hit.content || "").replace(/\s+/g, " ").slice(0, 120);
            hits.push({ path, snippet });
            if (hits.length >= 5) break;
          }
          setContentHits(hits);
        })
        .catch(() => {
          if (!controller.signal.aborted) setContentHits([]);
        })
        .finally(() => {
          if (!controller.signal.aborted) setContentSearching(false);
        });
    }, 400);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [trimmedQuery]);

  const filenamePaths = useMemo(
    () => new Set(filenameMatches.map((f) => f.relative_path)),
    [filenameMatches],
  );
  const contentOnlyHits = useMemo(
    () => contentHits.filter((h) => !filenamePaths.has(h.path)),
    [contentHits, filenamePaths],
  );

  const treeRows: FlatVaultRow[] = useMemo(
    () => (trimmedQuery ? [] : flattenVaultTree(tree, expanded)),
    [trimmedQuery, tree, expanded],
  );

  useEffect(() => {
    setHighlight(0);
  }, [query, expanded, files]);

  const toggleDirectory = useCallback((dirPath: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(dirPath)) next.delete(dirPath);
      else next.add(dirPath);
      return next;
    });
  }, []);

  const activateRow = useCallback(
    (row: { path: string | null; node: VaultTreeNode | null }) => {
      if (row.node?.isDirectory) {
        toggleDirectory(row.node.path);
        return;
      }
      if (row.path) onToggle(row.path);
    },
    [onToggle, toggleDirectory],
  );

  const handleSearchKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.nativeEvent.isComposing || e.keyCode === 229) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (navRows.length > 0) setHighlight((h) => (h + 1) % navRows.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (navRows.length > 0) setHighlight((h) => (h - 1 + navRows.length) % navRows.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      const row = navRows[highlight];
      if (row) activateRow(row);
    } else if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    }
  };

  const renderFileRow = (
    path: string,
    size: number | undefined,
    key: string,
    navIndex: number,
    snippet?: string,
  ) => {
    const isSelected = selectedPaths.has(path);
    const isHighlight = navIndex === highlight;
    const disabled = !isSelected && limitReached;
    return (
      <button
        key={key}
        type="button"
        disabled={disabled}
        onClick={() => onToggle(path)}
        onMouseEnter={() => setHighlight(navIndex)}
        className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs disabled:cursor-not-allowed disabled:opacity-40 ${
          isHighlight ? "bg-slate-100" : "hover:bg-slate-50"
        }`}
      >
        <FileText className="h-3.5 w-3.5 shrink-0 text-slate-400" />
        <span className="min-w-0 flex-1">
          <span className="block truncate font-medium text-slate-800">
            {vaultFileName(path)}
          </span>
          {vaultFileDirectory(path) && (
            <span className="block truncate text-[11px] text-slate-400">
              {vaultFileDirectory(path)}
            </span>
          )}
          {snippet && (
            <span className="block truncate text-[11px] text-slate-500">{snippet}</span>
          )}
        </span>
        <span className="shrink-0 text-[10px] text-slate-400">
          {size !== undefined ? formatVaultFileSize(size) : ""}
        </span>
        {isSelected && <Check className="h-3.5 w-3.5 shrink-0 text-slate-700" />}
      </button>
    );
  };

  const fileByPath = useMemo(() => {
    const map = new Map<string, VaultFileListItem>();
    for (const f of files ?? []) map.set(f.relative_path, f);
    return map;
  }, [files]);

  // ファイル一覧に無いパス（削除済み等）は候補から除外する
  const renderedContentHits = useMemo(
    () => contentOnlyHits.filter((h) => fileByPath.has(h.path)),
    [contentOnlyHits, fileByPath],
  );

  // キーボード移動対象の可視行（描画順と一致させる）
  const navRows: { key: string; path: string | null; node: VaultTreeNode | null }[] = useMemo(() => {
    if (trimmedQuery) {
      const rows = filenameMatches.map((f) => ({
        key: `file:${f.relative_path}`,
        path: f.relative_path,
        node: null as VaultTreeNode | null,
      }));
      for (const h of renderedContentHits) {
        rows.push({ key: `content:${h.path}`, path: h.path, node: null });
      }
      return rows;
    }
    return treeRows.map((r) => ({
      key: `tree:${r.key}`,
      path: r.node.isDirectory ? null : (r.node.file?.relative_path ?? null),
      node: r.node,
    }));
  }, [trimmedQuery, filenameMatches, renderedContentHits, treeRows]);

  let navCounter = -1;
  const nextNavIndex = () => {
    navCounter += 1;
    return navCounter;
  };

  return (
    <div
      data-testid="agent-vault-file-picker"
      className="absolute bottom-full left-3 right-3 z-20 mb-2 flex max-h-96 flex-col overflow-hidden rounded-lg border border-slate-200 bg-white shadow-lg"
    >
      <div className="flex items-center gap-2 border-b border-slate-100 px-3 py-2">
        <Search className="h-3.5 w-3.5 shrink-0 text-slate-400" />
        <input
          ref={searchInputRef}
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleSearchKeyDown}
          placeholder="ファイル名・本文で検索（空でツリー表示）"
          className="w-full bg-transparent text-xs text-slate-800 focus:outline-none"
          aria-label="Vault ファイル検索"
        />
        {query && (
          <button
            type="button"
            onClick={() => setQuery("")}
            className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded text-slate-400 hover:bg-slate-100 hover:text-slate-600 cursor-pointer"
            aria-label="検索をクリア"
          >
            <X className="h-3 w-3" />
          </button>
        )}
        <button
          type="button"
          onClick={() => void loadFiles()}
          className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded text-slate-400 hover:bg-slate-100 hover:text-slate-600 cursor-pointer"
          aria-label="ファイル一覧を再読込"
        >
          <RefreshCw className={`h-3 w-3 ${filesLoading ? "animate-spin" : ""}`} />
        </button>
        <button
          type="button"
          onClick={onClose}
          className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded text-slate-400 hover:bg-slate-100 hover:text-slate-600 cursor-pointer"
          aria-label="ピッカーを閉じる"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto py-1">
        {filesLoading && !files && (
          <div className="flex items-center justify-center gap-2 p-4 text-xs text-slate-400">
            <Loader2 className="h-4 w-4 animate-spin" />
            ファイル一覧を読込中…
          </div>
        )}
        {filesError && (
          <div className="p-3 text-center text-xs text-slate-500">{filesError}</div>
        )}
        {files && files.length === 0 && !filesError && (
          <div className="p-3 text-center text-xs text-slate-400">
            Vault に Markdown ファイルがありません
          </div>
        )}
        {files && files.length > 0 && trimmedQuery === "" && (
          <div>
            {treeRows.length === 0 && (
              <div className="p-3 text-center text-xs text-slate-400">
                該当する候補がありません
              </div>
            )}
            {treeRows.map((row) => {
              const navIndex = nextNavIndex();
              const isHighlight = navIndex === highlight;
              if (row.node.isDirectory) {
                const isOpen = expanded.has(row.node.path);
                return (
                  <button
                    key={`tree:${row.key}`}
                    type="button"
                    onClick={() => toggleDirectory(row.node.path)}
                    onMouseEnter={() => setHighlight(navIndex)}
                    className={`flex w-full items-center gap-1.5 px-3 py-1.5 text-left text-xs ${
                      isHighlight ? "bg-slate-100" : "hover:bg-slate-50"
                    }`}
                    style={{ paddingLeft: `${12 + row.depth * 14}px` }}
                  >
                    {isOpen ? (
                      <ChevronDown className="h-3 w-3 shrink-0 text-slate-400" />
                    ) : (
                      <ChevronRight className="h-3 w-3 shrink-0 text-slate-400" />
                    )}
                    {isOpen ? (
                      <FolderOpen className="h-3.5 w-3.5 shrink-0 text-slate-400" />
                    ) : (
                      <Folder className="h-3.5 w-3.5 shrink-0 text-slate-400" />
                    )}
                    <span className="truncate font-medium text-slate-700">{row.node.name}</span>
                  </button>
                );
              }
              const item = row.node.file;
              if (!item) return null;
              const isSelected = selectedPaths.has(item.relative_path);
              const disabled = !isSelected && limitReached;
              return (
                <button
                  key={`tree:${row.key}`}
                  type="button"
                  disabled={disabled}
                  onClick={() => onToggle(item.relative_path)}
                  onMouseEnter={() => setHighlight(navIndex)}
                  className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs disabled:cursor-not-allowed disabled:opacity-40 ${
                    isHighlight ? "bg-slate-100" : "hover:bg-slate-50"
                  }`}
                  style={{ paddingLeft: `${24 + row.depth * 14}px` }}
                >
                  <FileText className="h-3.5 w-3.5 shrink-0 text-slate-400" />
                  <span className="min-w-0 flex-1 truncate font-medium text-slate-800">
                    {item ? vaultFileName(item.relative_path) : row.node.name}
                  </span>
                  <span className="shrink-0 text-[10px] text-slate-400">
                    {formatVaultFileSize(item.size)}
                  </span>
                  {isSelected && <Check className="h-3.5 w-3.5 shrink-0 text-slate-700" />}
                </button>
              );
            })}
          </div>
        )}
        {files && trimmedQuery !== "" && (
          <div>
            {filenameMatches.length === 0 && !contentSearching && renderedContentHits.length === 0 && (
              <div className="p-3 text-center text-xs text-slate-400">
                該当する候補がありません
              </div>
            )}
            {filenameMatches.length > 0 && (
              <div>
                <div className="border-b border-slate-100 bg-slate-50 px-3 py-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                  ファイル名
                </div>
                {filenameMatches.map((f) =>
                  renderFileRow(f.relative_path, f.size, `file:${f.relative_path}`, nextNavIndex()),
                )}
              </div>
            )}
            {(contentSearching || renderedContentHits.length > 0) && (
              <div>
                <div className="border-b border-slate-100 bg-slate-50 px-3 py-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                  本文
                  {contentSearching && (
                    <Loader2 className="ml-1 inline h-3 w-3 animate-spin" />
                  )}
                </div>
                {renderedContentHits.map((h) => {
                  const item = fileByPath.get(h.path);
                  if (!item) return null;
                  return renderFileRow(h.path, item.size, `content:${h.path}`, nextNavIndex(), h.snippet);
                })}
              </div>
            )}
          </div>
        )}
      </div>

      <div className="flex items-center justify-between border-t border-slate-100 px-3 py-1.5">
        <span className="text-[11px] text-slate-400">
          選択中 {selected.length}/{MAX_AGENT_CONTEXT_REFS}
        </span>
        <button
          type="button"
          onClick={onClose}
          className="rounded bg-slate-900 px-3 py-1 text-xs text-white hover:bg-slate-800 cursor-pointer"
        >
          完了
        </button>
      </div>
    </div>
  );
}
