import { useEffect, useState } from "react";
import { listVaults } from "../api/client";
import type { VaultInfo } from "../api/types";

/** Registry Vault 一覧を取得する共有 hook（初期選択は primary）。 */
export function useVaults() {
  const [vaults, setVaults] = useState<VaultInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    listVaults()
      .then((res) => {
        if (!cancelled) {
          setVaults(res.items);
          setError(null);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Vault 一覧の取得に失敗しました");
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const primary = vaults?.find((v) => v.is_primary) ?? null;
  return { vaults, primary, error, loading };
}

/** Vault 選択ドロップダウンの表示ラベル。 */
export function vaultLabel(v: VaultInfo): string {
  return `${v.display_name} (${v.vault_id})`;
}
