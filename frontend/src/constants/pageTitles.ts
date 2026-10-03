import { matchPath } from "react-router-dom";
import { ROUTES } from "./routes";

export const APP_TITLE = "Obsidian AI Hub";

interface PageTitleEntry {
  pattern: string;
  title: string;
}

// Listed from most specific to least specific; the first match wins.
// Dynamic routes resolve to their screen name (e.g. Workflow 詳細) rather
// than the parent menu title.
const PAGE_TITLE_ENTRIES: PageTitleEntry[] = [
  { pattern: ROUTES.TASK_AGENT_CAPABILITIES, title: "Task Capability設定" },
  { pattern: ROUTES.TASK_AGENT_DETAIL, title: "タスクエージェント詳細" },
  { pattern: ROUTES.TASK_AGENT, title: "タスクエージェント" },
  { pattern: ROUTES.COACH_GOAL_DETAIL, title: "長期目標コーチ詳細" },
  { pattern: ROUTES.COACH, title: "長期目標コーチ" },
  { pattern: ROUTES.WORKFLOW_EDIT, title: "Workflow エディタ" },
  { pattern: ROUTES.WORKFLOW_RUN, title: "Workflow Run" },
  { pattern: ROUTES.WORKFLOW_DETAIL, title: "Workflow 詳細" },
  { pattern: ROUTES.WORKFLOWS, title: "ワークフロー" },
  {
    pattern: ROUTES.EXECUTION_LOGS_JOB_STATES,
    title: "実行ログ（ジョブ状態）",
  },
  { pattern: ROUTES.EXECUTION_LOGS_LOGS, title: "実行ログ（ログ）" },
  { pattern: ROUTES.EXECUTION_LOGS, title: "実行ログ" },
  { pattern: ROUTES.MEMORIES, title: "メモリ" },
  { pattern: ROUTES.RESEARCH, title: "リサーチ" },
  { pattern: ROUTES.AGENTS, title: "AIエージェント" },
  { pattern: ROUTES.CODING, title: "コーディング" },
  { pattern: ROUTES.HITL, title: "確認待ち" },
  { pattern: ROUTES.VAULT_SEARCH, title: "Vault 検索" },
  { pattern: ROUTES.SUMMARY_DASHBOARD, title: "サマリダッシュボード" },
  { pattern: ROUTES.HEALTHCARE, title: "ヘルスケア" },
  { pattern: ROUTES.RECURRING_EVENTS, title: "定期記録" },
  { pattern: ROUTES.PEOPLE, title: "人物管理" },
  { pattern: ROUTES.PROJECTS, title: "プロジェクト管理" },
  { pattern: ROUTES.JOBS, title: "ジョブ管理" },
  { pattern: ROUTES.MEDIA, title: "メディア" },
  { pattern: ROUTES.PLANNER, title: "プランナー" },
  { pattern: ROUTES.SETTINGS, title: "設定" },
];

/**
 * Resolve the browser tab title for a pathname.
 * Unknown paths (including "/" which redirects to /memories) fall back to
 * the bare application title.
 */
export function resolvePageTitle(pathname: string): string {
  const entry = PAGE_TITLE_ENTRIES.find((candidate) =>
    matchPath({ path: candidate.pattern, end: true }, pathname),
  );
  return entry ? `${APP_TITLE} ${entry.title}` : APP_TITLE;
}
