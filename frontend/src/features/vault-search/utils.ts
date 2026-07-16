import type { VaultSearchHit } from "../../api/types";

export function formatScore(score: number): string {
  return score.toFixed(4);
}

export function formatMtime(mtime: number): string {
  try {
    const d = new Date(mtime * 1000);
    return d.toLocaleString("ja-JP");
  } catch {
    return String(mtime);
  }
}

export function buildObsidianUrl(hit: VaultSearchHit): string | null {
  const vaultName = hit.metadata.vault_name;
  const relativePath = hit.metadata.relative_path;
  if (!vaultName || !relativePath) return null;

  const encodedVault = encodeURIComponent(vaultName);
  const encodedFile = encodeURIComponent(relativePath.replace(/\.md$/, ""));
  return `obsidian://open?vault=${encodedVault}&file=${encodedFile}`;
}
