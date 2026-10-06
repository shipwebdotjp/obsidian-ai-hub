import { useCallback, useEffect, useRef, useState } from "react";
import VaultSearchTab from "./VaultSearchTab";
import VaultExplorerTab from "./VaultExplorerTab";
import { ToastStack, useToasts } from "../../components/Toast";
import { listVaultFiles } from "../../api/client";
import { getApiErrorMessage } from "../../utils/error";
import { useVaults, vaultLabel } from "../../hooks/useVaults";
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
  const [explorerVault, setExplorerVault] = useState<string | null>(null);
  const filesRequestedRef = useRef(false);
  const { vaults, primary, error: vaultsError } = useVaults();
  const effectiveVault = explorerVault ?? primary?.vault_id ?? vaults?.[0]?.vault_id ?? "main";

  useEffect(() => {
    writeVaultSearchUiState(ui);
  }, [ui]);

  const loadFiles = useCallback(async (vault: string) => {
    setFilesLoading(true);
    setFilesError(null);
    try {
      const res = await listVaultFiles(vault);
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
    if (ui.activeTab === "explorer" && !filesRequestedRef.current && vaults) {
      filesRequestedRef.current = true;
      void loadFiles(effectiveVault);
    }
  }, [ui.activeTab, effectiveVault, vaults, loadFiles]);

  const handleVaultChange = useCallback((vault: string) => {
    setExplorerVault(vault);
    filesRequestedRef.current = true;
    setUi((prev) => ({ ...prev, selectedDir: "", notePath: null, expandedDirs: [] }));
    void loadFiles(vault);
  }, [loadFiles]);

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
        {ui.activeTab === "explorer" && (
          <>
            <label className="flex items-center gap-1 text-sm text-slate-600">
              Vault
              <select
                value={effectiveVault}
                onChange={(e) => handleVaultChange(e.target.value)}
                aria-label="エクスプローラーのVault選択"
                title={vaultsError ?? undefined}
                className="cursor-pointer rounded border border-slate-300 px-2 py-1 text-sm"
              >
                {(vaults ?? [{ vault_id: "main", display_name: "main", is_primary: true }]).map((v) => (
                  <option key={v.vault_id} value={v.vault_id}>
                    {vaultLabel(v)}
                  </option>
                ))}
              </select>
            </label>
            {vaultsError && (
              <span className="text-xs text-red-600" title={vaultsError}>
                Vault一覧の取得に失敗しました
              </span>
            )}
          </>
        )}
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
          vaultId={effectiveVault}
          onReload={() => void loadFiles(effectiveVault)}
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
