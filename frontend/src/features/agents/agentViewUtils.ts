import type {
  AgentLiveToolCall,
  AgentRun,
  AgentPromptTemplate,
  SlashCandidate,
} from "../../api/types";

// keep in sync with runtime.py _LIVE_RESULT_MAX_CHARS (DB is 20000)
export const LIVE_RESULT_MAX_CHARS = 2000;

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
