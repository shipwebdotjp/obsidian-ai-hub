import type {
  AgentContextRef,
  AgentLiveToolCall,
  AgentRun,
  AgentPromptTemplate,
  SlashCandidate,
  VaultFileListItem,
} from "../../api/types";

// keep in sync with backend agents/vault_context.py MAX_AGENT_CONTEXT_REFS
export const MAX_AGENT_CONTEXT_REFS = 5;

export const MAX_AGENT_IMAGES = 5;
export const MAX_AGENT_IMAGE_BYTES = 8 * 1024 * 1024;

export const AGENT_DELEGATE_TOOL_ID = "agent_delegate";

// Tailwind v4 default `lg` breakpoint is 1024px. Used to keep JS behavior
// (e.g. body scroll lock) in sync with the responsive drawer visibility.
export const LG_BREAKPOINT = 1024;

export interface PendingAttachment {
  previewUrl: string;
  name: string;
  mime_type: string;
  data: string;
  size: number;
}

export interface PendingContextRef {
  kind: "vault_file";
  path: string;
}

/** Vault ファイル参照の形状検証（下書き・キューの正規化で共用）。 */
export function isValidContextRef(value: unknown): value is PendingContextRef {
  if (!value || typeof value !== "object") return false;
  const ref = value as PendingContextRef;
  return ref.kind === "vault_file" && typeof ref.path === "string" && ref.path.length > 0;
}

export function toAgentContextRef(ref: PendingContextRef): AgentContextRef {
  return { kind: ref.kind, path: ref.path };
}

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

// keep in sync with runtime.py _LIVE_RESULT_MAX_CHARS (DB is 20000)
export const LIVE_RESULT_MAX_CHARS = 2000;

export function filterSlashCandidates(
  candidates: SlashCandidate[],
  inputText: string,
): SlashCandidate[] {
  if (!inputText.startsWith("/")) return [];
  const rawQuery = inputText.slice(1);
  const explicitTemplateMatch = rawQuery.match(/^template\s+(.*)/i);

  if (explicitTemplateMatch) {
    const query = (explicitTemplateMatch[1] || "").trim().toLowerCase();
    const templatesOnly = candidates.filter((c) => c.kind === "template");
    if (!query) return templatesOnly.slice(0, 8);

    const startsWith: SlashCandidate[] = [];
    const includes: SlashCandidate[] = [];
    for (const c of templatesOnly) {
      const lower = c.name.toLowerCase();
      if (lower.startsWith(query)) startsWith.push(c);
      else if (lower.includes(query)) includes.push(c);
    }
    return [...startsWith, ...includes].slice(0, 8);
  }

  const query = rawQuery.trim().toLowerCase();
  if (!query) return candidates.slice(0, 16);

  const startsWith: SlashCandidate[] = [];
  const includes: SlashCandidate[] = [];
  for (const c of candidates) {
    const lower = c.name.toLowerCase();
    if (lower.startsWith(query)) startsWith.push(c);
    else if (lower.includes(query)) includes.push(c);
  }
  return [...startsWith, ...includes].slice(0, 16);
}

export const LIVE_STATUS_CONFIG: Record<AgentLiveToolCall["status"], { label: string; cls: string }> = {
  succeeded: { label: "成功", cls: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  failed: { label: "失敗", cls: "bg-rose-50 text-rose-700 border-rose-200" },
  running: { label: "実行中…", cls: "bg-amber-50 text-amber-700 border-amber-200" },
  preparing: { label: "準備中…", cls: "bg-blue-50 text-blue-700 border-blue-200" },
};

export function getLiveStatusLabel(s: AgentLiveToolCall["status"]): string {
  return LIVE_STATUS_CONFIG[s].label;
}

export function getLiveStatusClass(s: AgentLiveToolCall["status"]): string {
  return LIVE_STATUS_CONFIG[s].cls;
}

export function matchesLiveToolCall(
  toolCall: AgentLiveToolCall,
  callKey?: string,
  callId?: string,
): boolean {
  return (
    (Boolean(callKey) && (toolCall.call_key === callKey || toolCall.id === callKey)) ||
    (Boolean(callId) && (toolCall.call_id === callId || toolCall.id === callId))
  );
}

/** assistant_message_id -> run の対応表を作る。 */
export function buildRunsByMessageId(runs: AgentRun[]): Map<string, AgentRun> {
  const map = new Map<string, AgentRun>();
  for (const r of runs) {
    if (r.assistant_message_id) map.set(r.assistant_message_id, r);
  }
  return map;
}

/** user_message_id -> run の対応表を作る。 */
export function buildRunsByUserMessageId(runs: AgentRun[]): Map<string, AgentRun> {
  const map = new Map<string, AgentRun>();
  for (const r of runs) {
    if (r.user_message_id) map.set(r.user_message_id, r);
  }
  return map;
}

/** ライブ表示用に長いツール結果を切り詰める。 */
export function truncateLiveResult(result: string): string {
  if (result && result.length > LIVE_RESULT_MAX_CHARS) {
    return result.slice(0, LIVE_RESULT_MAX_CHARS) + "\n…(truncated for live view)";
  }
  return result;
}

/** プロンプトテンプレートをスラッシュ候補形式へ変換する。 */
export function toClientTemplateCandidates(
  promptTemplates: AgentPromptTemplate[],
): SlashCandidate[] {
  return promptTemplates.map((t) => ({
    kind: "template",
    name: t.name,
    description: t.content,
    template_id: t.template_id,
    content: t.content,
  }));
}
