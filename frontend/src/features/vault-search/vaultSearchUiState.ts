import type { VaultFileListItem } from "../../api/types";
import type { VaultSortDir, VaultSortKey } from "../../utils/vault";

export const VAULT_SEARCH_UI_STORAGE_KEY = "obsidian-ai-hub:vault-search-ui:v1";

export type VaultSearchTab = "search" | "explorer";

export interface VaultSearchUiState {
  activeTab: VaultSearchTab;
  expandedDirs: string[];
  selectedDir: string;
  notePath: string | null;
  sortKey: VaultSortKey;
  sortDir: VaultSortDir;
}

export const DEFAULT_VAULT_SEARCH_UI_STATE: VaultSearchUiState = {
  activeTab: "search",
  expandedDirs: [],
  selectedDir: "",
  notePath: null,
  sortKey: "mtime",
  sortDir: "desc",
};

function getLocalStorage(): Storage | null {
  try {
    if (typeof window === "undefined" || !window.localStorage) return null;
    return window.localStorage;
  } catch {
    return null;
  }
}

function defaultState(): VaultSearchUiState {
  return { ...DEFAULT_VAULT_SEARCH_UI_STATE, expandedDirs: [] };
}

/**
 * 保存済みの Vault 検索 UI 状態を返す。localStorage 非利用・破損 JSON・
 * 型不正のいずれでも既定状態を返し、例外は投げない。
 */
export function readVaultSearchUiState(): VaultSearchUiState {
  try {
    const storage = getLocalStorage();
    if (!storage) return defaultState();
    const raw = storage.getItem(VAULT_SEARCH_UI_STORAGE_KEY);
    if (!raw) return defaultState();
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object") return defaultState();
    const record = parsed as Record<string, unknown>;
    return {
      activeTab: record.activeTab === "explorer" ? "explorer" : "search",
      expandedDirs: Array.isArray(record.expandedDirs)
        ? record.expandedDirs.filter((d): d is string => typeof d === "string")
        : [],
      selectedDir: typeof record.selectedDir === "string" ? record.selectedDir : "",
      notePath:
        typeof record.notePath === "string" && record.notePath.length > 0
          ? record.notePath
          : null,
      sortKey: record.sortKey === "name" ? "name" : "mtime",
      sortDir: record.sortDir === "asc" ? "asc" : "desc",
    };
  } catch {
    return defaultState();
  }
}

/** UI 状態を保存する。保存不可（プライベートモード・quota超過）でも例外は投げない。 */
export function writeVaultSearchUiState(state: VaultSearchUiState): void {
  try {
    const storage = getLocalStorage();
    if (!storage) return;
    storage.setItem(VAULT_SEARCH_UI_STORAGE_KEY, JSON.stringify(state));
  } catch {
    // ignore
  }
}

/** 保存値から存在するディレクトリ集合（すべての祖先ディレクトリ）を作る。 */
export function collectVaultDirectories(items: VaultFileListItem[]): Set<string> {
  const dirs = new Set<string>();
  for (const item of items) {
    const parts = item.relative_path.replace(/\\/g, "/").split("/").filter(Boolean);
    for (let i = 1; i < parts.length; i++) {
      dirs.add(parts.slice(0, i).join("/"));
    }
  }
  return dirs;
}

/**
 * 最新のファイル一覧と保存状態を照合する。削除・移動済みの項目は、その状態
 * だけを初期値へ戻し、一覧・ビューアーは壊さない。
 */
export function reconcileExplorerState(
  state: VaultSearchUiState,
  items: VaultFileListItem[],
): VaultSearchUiState {
  const directories = collectVaultDirectories(items);
  const expandedDirs = state.expandedDirs.filter((d) => directories.has(d));
  const selectedDir =
    state.selectedDir === "" || directories.has(state.selectedDir)
      ? state.selectedDir
      : "";
  const notePath =
    state.notePath && items.some((f) => f.relative_path === state.notePath)
      ? state.notePath
      : null;
  return { ...state, expandedDirs, selectedDir, notePath };
}
