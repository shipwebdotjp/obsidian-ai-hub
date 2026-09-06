import type {
  CodingMessage,
  CodingOrchestratorToolCall,
  CodingProjectItem,
  CodingRun,
} from "../../../api/coding";

/** git リポジトリとして有効なプロジェクトのみを返す。 */
export function selectValidProjects(projects: CodingProjectItem[]): CodingProjectItem[] {
  return projects.filter((p) => p.is_valid_git_repo === true);
}

/** 永続化済みツール呼び出しを紐付き orchestrator メッセージごとに束ねる。 */
export function groupToolCallsByMessageId(
  toolCalls: CodingOrchestratorToolCall[] | undefined,
): Map<string, CodingOrchestratorToolCall[]> {
  const map = new Map<string, CodingOrchestratorToolCall[]>();
  if (!toolCalls) return map;
  for (const tc of toolCalls) {
    if (tc.orchestrator_message_id) {
      const list = map.get(tc.orchestrator_message_id) || [];
      list.push(tc);
      map.set(tc.orchestrator_message_id, list);
    }
  }
  return map;
}

/** どの orchestrator メッセージにも紐付かない中断ツール呼び出しを run ごとに束ねる。 */
export function groupUnassociatedToolCallsByRunId(
  toolCalls: CodingOrchestratorToolCall[] | undefined,
): Map<string, CodingOrchestratorToolCall[]> {
  const map = new Map<string, CodingOrchestratorToolCall[]>();
  if (!toolCalls) return map;
  for (const tc of toolCalls) {
    if (!tc.orchestrator_message_id && tc.run_id) {
      const list = map.get(tc.run_id) || [];
      list.push(tc);
      map.set(tc.run_id, list);
    }
  }
  return map;
}

/** セッション内 runs と実行中・最新 run を run_id で引けるようにする。 */
export function buildRunById(
  runs: CodingRun[] | undefined,
  activeRun: CodingRun | null,
  latestRun: CodingRun | null,
): Map<string, CodingRun> {
  const m = new Map<string, CodingRun>();
  for (const r of runs ?? []) m.set(r.run_id, r);
  if (latestRun) m.set(latestRun.run_id, latestRun);
  if (activeRun) m.set(activeRun.run_id, activeRun);
  return m;
}

/** user メッセージを起点にした run を特定する。 */
export function getRunIdForUserMessage(
  msg: CodingMessage,
  activeRun: CodingRun | null,
  latestRun: CodingRun | null,
): string | null {
  if (msg.run_id) return msg.run_id;
  if (activeRun && activeRun.user_message_id === msg.message_id) return activeRun.run_id;
  if (latestRun && latestRun.user_message_id === msg.message_id) return latestRun.run_id;
  return null;
}
