import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight, FileText, Folder, FolderOpen, RefreshCw } from "lucide-react";
import type { VaultFileListItem } from "../../api/types";
import { DEFAULT_LIST_RATIO } from "../../hooks/usePaneResize";
import {
  filterVaultFilesByName,
  listFilesInDirectory,
  sortVaultFiles,
  vaultFileDirectory,
  vaultFileName,
  type VaultSortDir,
  type VaultSortKey,
} from "../../utils/vault";
import MasterDetailLayout from "../../components/MasterDetailLayout";
import VaultNoteDetailPanel from "./VaultNoteDetailPanel";
import { collectVaultDirectories } from "./vaultSearchUiState";
import { formatMtime } from "./utils";

interface DirNode {
  name: string;
  path: string;
  children: DirNode[];
}

function buildDirectoryTree(files: VaultFileListItem[]): DirNode[] {
  const root: DirNode = { name: "", path: "", children: [] };
  const byPath = new Map<string, DirNode>([["", root]]);
  for (const dir of [...collectVaultDirectories(files)].sort((a, b) => a.localeCompare(b, "ja"))) {
    const parts = dir.split("/");
    const parent = byPath.get(parts.slice(0, -1).join("/")) ?? root;
    const node: DirNode = { name: parts[parts.length - 1], path: dir, children: [] };
    parent.children.push(node);
    byPath.set(dir, node);
  }
  return root.children;
}

export interface VaultExplorerTabProps {
  files: VaultFileListItem[] | null;
  loading: boolean;
  error: string | null;
  onReload: () => void;
  expandedDirs: string[];
  onToggleDir: (dir: string) => void;
  selectedDir: string;
  onSelectDir: (dir: string) => void;
  notePath: string | null;
  onSelectNote: (path: string) => void;
  sortKey: VaultSortKey;
  sortDir: VaultSortDir;
  onSort: (key: VaultSortKey) => void;
  notify: (msg: string, kind?: "info" | "error") => void;
}

/**
 * Vault ファイルエクスプローラー。広い画面では
 * 「ディレクトリツリー / ファイル一覧 / 共通ビューアー」の 3 ペイン、
 * 狭い画面ではツリー → 一覧 → 詳細の段階遷移にする。
 */
export default function VaultExplorerTab({
  files,
  loading,
  error,
  onReload,
  expandedDirs,
  onToggleDir,
  selectedDir,
  onSelectDir,
  notePath,
  onSelectNote,
  sortKey,
  sortDir,
  onSort,
  notify,
}: VaultExplorerTabProps) {
  const [filter, setFilter] = useState("");
  const [stage, setStage] = useState<"tree" | "list" | "detail">("list");

  const tree = useMemo(() => buildDirectoryTree(files ?? []), [files]);
  const expanded = useMemo(() => new Set(expandedDirs), [expandedDirs]);

  const visibleFiles = useMemo(() => {
    const inDir = listFilesInDirectory(files ?? [], selectedDir);
    const filtered = filterVaultFilesByName(inDir, filter);
    return sortVaultFiles(filtered, sortKey, sortDir);
  }, [files, selectedDir, filter, sortKey, sortDir]);

  const selectedFile = useMemo(
    () => (notePath ? (files ?? []).find((f) => f.relative_path === notePath) ?? null : null),
    [files, notePath],
  );

  const renderDirNode = (node: DirNode, depth: number) => {
    const isOpen = expanded.has(node.path);
    const hasChildren = node.children.length > 0;
    const isSelected = selectedDir === node.path;
    return (
      <li key={node.path}>
        <div
          className={`flex items-center gap-1 ${
            isSelected ? "bg-slate-200 border-l-4 border-slate-800" : "hover:bg-slate-50"
          }`}
          data-selected={isSelected ? "true" : "false"}
        >
          {hasChildren ? (
            <button
              type="button"
              onClick={() => onToggleDir(node.path)}
              aria-label={`${node.name} を${isOpen ? "折りたたむ" : "展開"}`}
              className="inline-flex h-5 w-5 shrink-0 cursor-pointer items-center justify-center text-slate-400 hover:text-slate-600"
            >
              {isOpen ? (
                <ChevronDown className="h-3 w-3" />
              ) : (
                <ChevronRight className="h-3 w-3" />
              )}
            </button>
          ) : (
            <span className="inline-block h-5 w-5 shrink-0" />
          )}
          <button
            type="button"
            onClick={() => {
              onSelectDir(node.path);
              setStage("list");
            }}
            className="flex min-w-0 flex-1 cursor-pointer items-center gap-1.5 py-1 pr-2 text-left text-xs"
            style={{ paddingLeft: `${depth * 12}px` }}
          >
            {isOpen ? (
              <FolderOpen className="h-3.5 w-3.5 shrink-0 text-slate-400" />
            ) : (
              <Folder className="h-3.5 w-3.5 shrink-0 text-slate-400" />
            )}
            <span className="truncate font-medium text-slate-700">{node.name}</span>
          </button>
        </div>
        {hasChildren && isOpen && (
          <ul>{node.children.map((child) => renderDirNode(child, depth + 1))}</ul>
        )}
      </li>
    );
  };

  const treePane = (
    <div
      className={`${
        stage === "tree" ? "flex" : "hidden"
      } min-h-0 w-full shrink-0 flex-col overflow-hidden border-slate-200 lg:flex lg:w-56 lg:border-r`}
    >
      <div className="flex items-center justify-between border-b border-slate-200 bg-white p-3 text-sm font-semibold text-slate-700">
        ディレクトリ
      </div>
      <ul className="flex-1 overflow-y-auto py-1">
        <li>
          <div
            className={`flex items-center gap-1 ${
              selectedDir === "" ? "bg-slate-200 border-l-4 border-slate-800" : "hover:bg-slate-50"
            }`}
            data-selected={selectedDir === "" ? "true" : "false"}
          >
            <span className="inline-block h-5 w-5 shrink-0" />
            <button
              type="button"
              onClick={() => {
                onSelectDir("");
                setStage("list");
              }}
              className="flex min-w-0 flex-1 cursor-pointer items-center gap-1.5 py-1 pr-2 text-left text-xs"
            >
              <Folder className="h-3.5 w-3.5 shrink-0 text-slate-400" />
              <span className="truncate font-medium text-slate-700">ルート（直下）</span>
            </button>
          </div>
        </li>
        {tree.map((node) => renderDirNode(node, 1))}
      </ul>
    </div>
  );

  const fileListPane = (
    <>
      <div className="border-b border-slate-200 bg-white p-2">
        <button
          type="button"
          onClick={() => setStage("tree")}
          className="mb-2 cursor-pointer rounded px-2 py-1 text-xs text-slate-600 hover:bg-slate-100 lg:hidden"
        >
          ← ツリー
        </button>
        <div className="flex items-center gap-2">
          <input
            type="search"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="ファイル名で絞り込み"
            aria-label="ファイル名フィルター"
            className="w-full min-w-0 rounded border border-slate-300 px-2 py-1 text-sm"
          />
          <button
            type="button"
            onClick={onReload}
            aria-label="再読込"
            className="inline-flex h-7 w-7 shrink-0 cursor-pointer items-center justify-center rounded text-slate-500 hover:bg-slate-100"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>
      <div className="flex border-b border-slate-200 bg-slate-50 text-xs font-medium text-slate-500">
        <button
          type="button"
          onClick={() => onSort("name")}
          aria-label="ファイル名で並べ替え"
          className="flex flex-1 cursor-pointer items-center gap-1 px-3 py-1.5 text-left hover:bg-slate-100"
        >
          <span>ファイル名</span>
          {sortKey === "name" && <span aria-hidden="true">{sortDir === "asc" ? "↑" : "↓"}</span>}
        </button>
        <button
          type="button"
          onClick={() => onSort("mtime")}
          aria-label="更新日時で並べ替え"
          className="flex shrink-0 cursor-pointer items-center gap-1 px-3 py-1.5 text-right hover:bg-slate-100"
        >
          <span>更新日時</span>
          {sortKey === "mtime" && <span aria-hidden="true">{sortDir === "asc" ? "↑" : "↓"}</span>}
        </button>
      </div>
      <ul className="flex-1 overflow-y-auto divide-y divide-slate-100">
        {visibleFiles.map((f) => {
          const isSelected = notePath === f.relative_path;
          return (
            <li key={f.relative_path}>
              <button
                type="button"
                onClick={() => {
                  onSelectNote(f.relative_path);
                  setStage("detail");
                }}
                data-testid="vault-explorer-row"
                data-selected={isSelected ? "true" : "false"}
                className={`flex w-full cursor-pointer items-start gap-2 px-3 py-2 text-left text-sm ${
                  isSelected ? "bg-slate-200 border-l-4 border-slate-800" : "hover:bg-slate-50"
                }`}
              >
                <FileText className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
                <span className="min-w-0 flex-1">
                  <span
                    data-testid="vault-explorer-row-name"
                    className="block truncate font-medium text-slate-800"
                  >
                    {vaultFileName(f.relative_path)}
                  </span>
                  <span className="mt-0.5 flex min-w-0 items-center gap-2 text-[11px] text-slate-400">
                    {vaultFileDirectory(f.relative_path) && (
                      <span className="truncate">{vaultFileDirectory(f.relative_path)}</span>
                    )}
                    <span className="shrink-0">{formatMtime(f.mtime)}</span>
                  </span>
                </span>
              </button>
            </li>
          );
        })}
        {!loading && visibleFiles.length === 0 && (
          <li className="p-6 text-sm text-slate-500">該当するファイルはありません。</li>
        )}
      </ul>
    </>
  );

  const detailPane = notePath ? (
    <VaultNoteDetailPanel
      relativePath={notePath}
      mtime={selectedFile?.mtime}
      notify={notify}
    />
  ) : (
    <p className="p-6 text-sm text-slate-500">一覧からファイルを選択してください。</p>
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
      {treePane}
      <div
        className={`${
          stage === "tree" ? "hidden" : "flex"
        } min-h-0 min-w-0 flex-1 flex-col lg:flex`}
      >
        {error ? (
          <div className="flex flex-col items-start gap-2 p-6 text-sm text-red-600">
            <p>{error}</p>
            <button
              type="button"
              onClick={onReload}
              disabled={loading}
              className="cursor-pointer rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-100 disabled:opacity-50"
            >
              再読込
            </button>
          </div>
        ) : loading && !files ? (
          <div className="p-6 text-sm text-slate-500">ファイル一覧を読み込み中…</div>
        ) : (
          <MasterDetailLayout
            mobileOpen={stage === "detail"}
            onBack={() => setStage("list")}
            mobileTitle="ノートプレビュー"
            listClassName="w-full overflow-hidden border-slate-200 lg:w-[var(--pane-size)]"
            detailClassName="w-full min-w-0 overflow-hidden lg:flex-1"
            detailContentClassName="flex-1 overflow-hidden"
            paneOptions={{
              defaultSize: DEFAULT_LIST_RATIO,
              minSize: 300,
              minOther: 320,
              storageKey: "vault-explorer",
            }}
            list={fileListPane}
            detail={detailPane}
          />
        )}
      </div>
    </div>
  );
}
