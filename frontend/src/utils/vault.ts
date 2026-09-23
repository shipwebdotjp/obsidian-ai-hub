import type { VaultFileListItem } from "../api/types";

export function vaultFileName(path: string): string {
  const normalized = path.replace(/\\/g, "/");
  const idx = normalized.lastIndexOf("/");
  return idx >= 0 ? normalized.slice(idx + 1) : normalized;
}

export function vaultFileDirectory(path: string): string {
  const normalized = path.replace(/\\/g, "/");
  const idx = normalized.lastIndexOf("/");
  return idx > 0 ? normalized.slice(0, idx) : "";
}

export function formatVaultFileSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Vault ファイル一覧のファイル名/パス部分一致フィルタ（大文字小文字無視）。 */
export function filterVaultFiles(
  files: VaultFileListItem[],
  query: string,
  limit: number = 50,
): VaultFileListItem[] {
  const q = query.trim().toLowerCase();
  if (!q) return files.slice(0, limit);
  const nameStarts: VaultFileListItem[] = [];
  const nameIncludes: VaultFileListItem[] = [];
  const pathIncludes: VaultFileListItem[] = [];
  for (const f of files) {
    const pathLower = f.relative_path.toLowerCase();
    const nameLower = vaultFileName(f.relative_path).toLowerCase();
    if (nameLower.startsWith(q)) nameStarts.push(f);
    else if (nameLower.includes(q)) nameIncludes.push(f);
    else if (pathLower.includes(q)) pathIncludes.push(f);
  }
  return [...nameStarts, ...nameIncludes, ...pathIncludes].slice(0, limit);
}

/**
 * ファイル名のみを対象にした部分一致フィルタ（大文字小文字無視）。
 * ディレクトリ名やパスは対象にせず、並び順は入力順を維持する。
 */
export function filterVaultFilesByName(
  files: VaultFileListItem[],
  query: string,
): VaultFileListItem[] {
  const q = query.trim().toLowerCase();
  if (!q) return files.slice();
  return files.filter((f) => vaultFileName(f.relative_path).toLowerCase().includes(q));
}

export interface VaultTreeNode {
  name: string;
  path: string;
  isDirectory: boolean;
  children: VaultTreeNode[];
  file?: VaultFileListItem;
}

/** Vault ファイル一覧をディレクトリツリー構造に変換する。 */
export function buildVaultTree(files: VaultFileListItem[]): VaultTreeNode[] {
  const root: VaultTreeNode = { name: "", path: "", isDirectory: true, children: [] };
  for (const f of files) {
    const parts = f.relative_path.replace(/\\/g, "/").split("/").filter(Boolean);
    let node = root;
    for (let i = 0; i < parts.length; i++) {
      const isLast = i === parts.length - 1;
      const partPath = parts.slice(0, i + 1).join("/");
      let child = node.children.find((c) => c.name === parts[i] && (c.isDirectory || isLast));
      if (!child) {
        child = {
          name: parts[i],
          path: partPath,
          isDirectory: !isLast,
          children: [],
          file: isLast ? f : undefined,
        };
        node.children.push(child);
        node.children.sort((a, b) => {
          if (a.isDirectory !== b.isDirectory) return a.isDirectory ? -1 : 1;
          return a.name.localeCompare(b.name, "ja");
        });
      }
      node = child;
    }
  }
  return root.children;
}

/** ツリー走査用に可視ノードをフラット化する（キーボード移動用）。 */
export interface FlatVaultRow {
  key: string;
  depth: number;
  node: VaultTreeNode;
}

export function flattenVaultTree(
  nodes: VaultTreeNode[],
  expanded: Set<string>,
  depth: number = 0,
): FlatVaultRow[] {
  const rows: FlatVaultRow[] = [];
  for (const node of nodes) {
    rows.push({ key: node.path || node.name, depth, node });
    if (node.isDirectory && expanded.has(node.path)) {
      rows.push(...flattenVaultTree(node.children, expanded, depth + 1));
    }
  }
  return rows;
}

/**
 * 選択ディレクトリ直下のファイルを返す。`dir` が空（ルート）のときは
 * 直下の Markdown のみ、それ以外は `dir/` 配下を再帰的に返す。
 */
export function listFilesInDirectory(
  files: VaultFileListItem[],
  dir: string,
): VaultFileListItem[] {
  const normalized = dir.replace(/\\/g, "/");
  if (!normalized) {
    return files.filter((f) => !f.relative_path.replace(/\\/g, "/").includes("/"));
  }
  const prefix = normalized.endsWith("/") ? normalized : `${normalized}/`;
  return files.filter((f) => f.relative_path.replace(/\\/g, "/").startsWith(prefix));
}

export type VaultSortKey = "name" | "mtime";
export type VaultSortDir = "asc" | "desc";

/**
 * ファイル一覧を並べ替える。`name` はファイル名、`mtime` は更新日時。
 * 同値のときは相対パス昇順で安定化する（方向に依存しない）。
 */
export function sortVaultFiles(
  files: VaultFileListItem[],
  key: VaultSortKey,
  dir: VaultSortDir,
): VaultFileListItem[] {
  const sign = dir === "asc" ? 1 : -1;
  return [...files].sort((a, b) => {
    const cmp =
      key === "name"
        ? vaultFileName(a.relative_path).localeCompare(vaultFileName(b.relative_path), "ja")
        : a.mtime - b.mtime;
    if (cmp !== 0) return cmp * sign;
    return a.relative_path.localeCompare(b.relative_path, "ja");
  });
}

/** frontmatter（先頭の `---` ブロック）と本文を分離する。 */
export function parseNoteContent(rawContent: string): {
  frontmatter: string | null;
  body: string;
} {
  const lines = rawContent.split(/\r?\n/);
  if (lines.length > 0 && lines[0] === "---") {
    let endIdx = -1;
    for (let i = 1; i < lines.length; i++) {
      if (lines[i] === "---" || lines[i] === "...") {
        endIdx = i;
        break;
      }
    }
    if (endIdx !== -1) {
      return {
        frontmatter: lines.slice(0, endIdx + 1).join("\n"),
        body: lines.slice(endIdx + 1).join("\n"),
      };
    }
  }
  return { frontmatter: null, body: rawContent };
}

/** Obsidian の URI スキームでノートを開く URL を組み立てる。 */
export function buildObsidianUrl(
  vaultName: string | null | undefined,
  relativePath: string | null | undefined,
): string | null {
  if (!vaultName || !relativePath) return null;
  const encodedVault = encodeURIComponent(vaultName);
  const encodedFile = encodeURIComponent(relativePath.replace(/\.md$/, ""));
  return `obsidian://open?vault=${encodedVault}&file=${encodedFile}`;
}
