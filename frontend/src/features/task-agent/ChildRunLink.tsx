import { Link } from "react-router-dom";
import { ROUTES } from "../../constants/routes";

/**
 * 子 run 参照を既存ルーティングに合わせたリンクにするための部品。
 *
 * 実在する遷移先（推測のハードコードなし）:
 * - agent 子 run: /agents?session_id=<session_id>（AgentsPage の深リンク）
 * - coding 子 run: /coding?session_id=<session_id>（CodingPage の深リンク）
 * - HITL run: /hitl?run_id=<hitl_run_id>（HitlPage の深リンク）
 *
 * child_run_started payload には session_id が同梱される（新形式）。
 * session_id のない旧形式イベントや未知の child_kind はリンク化せず、
 * run ID をテキストとして表示する（推測 URL を作らない）。
 */

export function agentSessionPath(sessionId: string): string {
  return `${ROUTES.AGENTS}?session_id=${encodeURIComponent(sessionId)}`;
}

export function codingSessionPath(sessionId: string): string {
  return `${ROUTES.CODING}?session_id=${encodeURIComponent(sessionId)}`;
}

export function hitlRunPath(runId: string): string {
  return `${ROUTES.HITL}?run_id=${encodeURIComponent(runId)}`;
}

export function childKindLabel(childKind: string): string {
  if (childKind === "agent") return "Agent";
  if (childKind === "coding") return "Coding";
  return childKind || "子";
}

function asText(value: unknown): string | null {
  if (typeof value === "string" && value !== "") return value;
  if (typeof value === "number") return String(value);
  return null;
}

export interface ChildRunRef {
  childKind: string;
  childRunId: string;
  sessionId?: string | null;
  agentId?: string | null;
  projectId?: string | number | null;
  backend?: string | null;
}

export function ChildRunLink({
  childKind,
  childRunId,
  sessionId,
  agentId,
  projectId,
  backend,
}: ChildRunRef) {
  const label = `${childKindLabel(childKind)} run ${childRunId}`;
  const meta: string[] = [];
  if (agentId) meta.push(`agent: ${agentId}`);
  if (projectId != null && String(projectId) !== "") {
    meta.push(`project: ${String(projectId)}${backend ? `/${backend}` : ""}`);
  } else if (backend) {
    meta.push(`backend: ${backend}`);
  }
  if (sessionId) meta.push(`session: ${sessionId}`);
  const metaText = meta.length > 0 ? `（${meta.join(" / ")}）` : "";

  if (childKind === "agent" && sessionId) {
    return (
      <span className="min-w-0 break-words [overflow-wrap:anywhere]">
        <Link
          to={agentSessionPath(sessionId)}
          data-testid="child-run-link"
          className="break-all text-blue-600 underline"
        >
          {label}
        </Link>
        {metaText && <span className="text-slate-500"> {metaText}</span>}
      </span>
    );
  }
  if (childKind === "coding" && sessionId) {
    return (
      <span className="min-w-0 break-words [overflow-wrap:anywhere]">
        <Link
          to={codingSessionPath(sessionId)}
          data-testid="child-run-link"
          className="break-all text-blue-600 underline"
        >
          {label}
        </Link>
        {metaText && <span className="text-slate-500"> {metaText}</span>}
      </span>
    );
  }
  return (
    <span
      data-testid="child-run-text"
      className="min-w-0 break-all text-slate-700"
    >
      {label}
      {metaText && <span className="text-slate-500"> {metaText}</span>}
      {(childKind === "agent" || childKind === "coding") && !sessionId && (
        <span className="text-slate-400">（セッション情報なし）</span>
      )}
    </span>
  );
}

/** payload から子 run 参照を取り出す。なければ null。 */
export function childRunRefFromPayload(
  payload: Record<string, unknown> | null | undefined,
): ChildRunRef | null {
  if (!payload || typeof payload !== "object") return null;
  const childRunId = asText(payload["child_run_id"]);
  if (!childRunId) return null;
  const childKind = asText(payload["child_kind"]) ?? "";
  return {
    childKind,
    childRunId,
    sessionId: asText(payload["session_id"]),
    agentId: asText(payload["agent_id"]),
    projectId:
      typeof payload["project_id"] === "string" ||
      typeof payload["project_id"] === "number"
        ? payload["project_id"]
        : null,
    backend: asText(payload["backend"]),
  };
}

/** payload 中の HITL run 参照を取り出す。なければ null。 */
export function hitlRunIdFromPayload(
  payload: Record<string, unknown> | null | undefined,
): string | null {
  if (!payload || typeof payload !== "object") return null;
  return asText(payload["hitl_run_id"]);
}

export function HitlRunLink({ runId }: { runId: string }) {
  return (
    <Link
      to={hitlRunPath(runId)}
      data-testid="hitl-run-link"
      className="break-all text-blue-600 underline"
    >
      確認タスク {runId}
    </Link>
  );
}
