import { useCallback, useEffect, useRef, useState } from "react";
import VaultSearchTab from "./VaultSearchTab";
import VaultExplorerTab from "./VaultExplorerTab";
import { ToastStack, useToasts } from "../../components/Toast";
import { listVaultFiles } from "../../api/client";
import { getApiErrorMessage } from "../../utils/error";
import type { VaultFileListItem } from "../../api/types";
import type { VaultSortKey } from "../../utils/vault";
import {
  readVaultSearchUiState,
  reconcileExplorerState,
  writeVaultSearchUiState,
  type VaultSearchTab as VaultSearchTabId,
  type VaultSearchUiState,
} from "./vaultSearchUiState";

export default function VaultSearchPage() {
  const { toasts, notify } = useToasts();
  const [ui, setUi] = useState<VaultSearchUiState>(readVaultSearchUiState);
  const [files, setFiles] = useState<VaultFileListItem[] | null>(null);
  const [filesLoading, setFilesLoading] = useState(false);
  const [filesError, setFilesError] = useState<string | null>(null);
  const filesRequestedRef = useRef(false);

  useEffect(() => {
    writeVaultSearchUiState(ui);
  }, [ui]);

  const loadFiles = useCallback(async () => {
    setFilesLoading(true);
    setFilesError(null);
    try {
      const res = await listVaultFiles();
      setFiles(res.items);
      setUi((prev) => reconcileExplorerState(prev, res.items));
    } catch (err) {
      // 初回取得に失敗したらガードを解除し、タブ再訪で再試行できるようにする。
      filesRequestedRef.current = false;
      setFilesError(getApiErrorMessage(err, "ファイル一覧の取得に失敗しました"));
    } finally {
      setFilesLoading(false);
    }
  }, []);

  useEffect(() => {
    if (ui.activeTab === "explorer" && !filesRequestedRef.current) {
      filesRequestedRef.current = true;
      void loadFiles();
    }
  }, [ui.activeTab, loadFiles]);

  const setActiveTab = useCallback((tab: VaultSearchTabId) => {
    setUi((prev) => ({ ...prev, activeTab: tab }));
  }, []);

  const toggleDir = useCallback((dir: string) => {
    setUi((prev) => {
      const next = new Set(prev.expandedDirs);
      if (next.has(dir)) next.delete(dir);
      else next.add(dir);
      return { ...prev, expandedDirs: [...next] };
    });
  }, []);

  const handleSort = useCallback((key: VaultSortKey) => {
    setUi((prev) =>
      prev.sortKey === key
        ? { ...prev, sortDir: prev.sortDir === "asc" ? "desc" : "asc" }
        : { ...prev, sortKey: key, sortDir: key === "name" ? "asc" : "desc" },
    );
  }, []);

  const tabClass = (active: boolean) =>
    `cursor-pointer rounded px-3 py-1 text-sm font-medium ${
      active ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"
    }`;

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-2 border-b border-slate-200 bg-white p-3 sm:gap-3 sm:p-4">
        <h1 className="text-base font-semibold">Vault 検索</h1>
        <div role="tablist" aria-label="Vault 検索の表示切替" className="flex items-center gap-1">
          <button
            type="button"
            role="tab"
            aria-selected={ui.activeTab === "search"}
            onClick={() => setActiveTab("search")}
            className={tabClass(ui.activeTab === "search")}
          >
            検索
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={ui.activeTab === "explorer"}
            onClick={() => setActiveTab("explorer")}
            className={tabClass(ui.activeTab === "explorer")}
          >
            ファイルエクスプローラー
          </button>
        </div>
      </header>
      <div
        role="tabpanel"
        aria-hidden={ui.activeTab !== "search"}
        className={`${
          ui.activeTab === "search" ? "flex" : "hidden"
        } min-h-0 flex-1 flex-col`}
      >
        <VaultSearchTab notify={notify} />
      </div>
      <div
        role="tabpanel"
        aria-hidden={ui.activeTab !== "explorer"}
        className={`${
          ui.activeTab === "explorer" ? "flex" : "hidden"
        } min-h-0 flex-1 flex-col`}
      >
        <VaultExplorerTab
          files={files}
          loading={filesLoading}
          error={filesError}
          onReload={() => void loadFiles()}
          expandedDirs={ui.expandedDirs}
          onToggleDir={toggleDir}
          selectedDir={ui.selectedDir}
          onSelectDir={(dir) => setUi((prev) => ({ ...prev, selectedDir: dir }))}
          notePath={ui.notePath}
          onSelectNote={(path) => setUi((prev) => ({ ...prev, notePath: path }))}
          sortKey={ui.sortKey}
          sortDir={ui.sortDir}
          onSort={handleSort}
          notify={notify}
        />
      </div>
      <ToastStack toasts={toasts} />
    </div>
  );
}
