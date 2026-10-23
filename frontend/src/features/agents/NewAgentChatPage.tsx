import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { createAgentSession } from "../../api/client";
import { getErrorMessage } from "../../utils/error";
import { ROUTES } from "../../constants/routes";

/** Creates one empty conversation for a shortcut URL, then opens it normally. */
export default function NewAgentChatPage() {
  const { agentId } = useParams<{ agentId: string }>();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  // ?prompt=... があれば新規セッション遷移時に引き継ぐ（自動送信はしない）。
  const promptParam = searchParams.get("prompt") ?? "";
  // One in-flight/finished creation per agent id so StrictMode's remount and
  // same-mount revisits (A -> B -> A) reuse the promise instead of creating
  // a duplicate empty session. Same type as createAgentSession's return.
  const pendingByAgentRef = useRef(
    new Map<string, ReturnType<typeof createAgentSession>>(),
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!agentId) {
      setError("エージェントが指定されていません。");
      return;
    }
    // React Router reuses this component when only the param changes
    // (/agents/new/A -> /agents/new/B); the map keys the guard per agent.
    let pending = pendingByAgentRef.current.get(agentId) ?? null;
    if (!pending) {
      pending = createAgentSession(agentId);
      pendingByAgentRef.current.set(agentId, pending);
    }

    let cancelled = false;
    const carriedPrompt = promptParam;
    void pending
      .then(({ session }) => {
        // Drop the resolved entry so revisiting this shortcut URL starts a
        // fresh conversation; StrictMode remounts re-enter while the request
        // is still in flight and keep reusing the pending promise.
        pendingByAgentRef.current.delete(agentId);
        if (cancelled) return;
        const target =
          `${ROUTES.AGENTS}?session_id=${encodeURIComponent(session.session_id)}` +
          (carriedPrompt ? `&prompt=${encodeURIComponent(carriedPrompt)}` : "");
        navigate(target, { replace: true, state: { focusChatInput: true } });
      })
      .catch((cause: unknown) => {
        // Drop the cached failure so revisiting this URL retries creation.
        pendingByAgentRef.current.delete(agentId);
        if (cancelled) return;
        setError(getErrorMessage(cause, "新しい会話を作成できませんでした。"));
      });
    return () => {
      cancelled = true;
    };
  }, [agentId, navigate, promptParam]);

  if (error) {
    return (
      <div className="flex h-full items-center justify-center bg-slate-50 p-6">
        <div className="max-w-md space-y-3 rounded-2xl bg-white p-6 text-center shadow">
          <p className="text-sm text-rose-600">{error}</p>
          <button
            type="button"
            onClick={() => navigate(ROUTES.AGENTS, { replace: true })}
            className="rounded bg-slate-900 px-4 py-2 text-sm text-white"
          >
            エージェント画面へ戻る
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full items-center justify-center text-sm text-slate-500">
      新しい会話を準備中…
    </div>
  );
}
