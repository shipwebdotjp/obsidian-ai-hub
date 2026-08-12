import { useEffect, useRef, useState, type FormEvent } from "react";
import { setToken, clearToken, listMemories, ApiError } from "../api/client";

export interface TokenPromptProps {
  onAuthenticated: () => void;
  validate?: () => Promise<unknown>;
  title?: string;
  description?: React.ReactNode;
}

export default function TokenPrompt({
  onAuthenticated,
  validate,
  title,
  description,
}: TokenPromptProps) {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const isMounted = useRef(true);

  useEffect(() => {
    return () => {
      isMounted.current = false;
    };
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    setToken(value.trim());
    try {
      // Validate by calling a protected endpoint
      if (validate) {
        await validate();
      } else {
        await listMemories({ status: "candidate" });
      }
      if (!isMounted.current) return;
      onAuthenticated();
    } catch (e) {
      if (!isMounted.current) return;
      const msg = e instanceof ApiError ? e.message : "トークン検証に失敗しました";
      setError(msg);
      clearToken();
    } finally {
      if (isMounted.current) setBusy(false);
    }
  }

  return (
    <div className="flex h-full items-center justify-center bg-slate-50 p-6">
      <form
        onSubmit={submit}
        className="w-full max-w-md space-y-4 rounded-2xl bg-white p-6 shadow"
      >
        <h1 className="text-lg font-semibold">{title ?? "トークン認証"}</h1>
        <p className="text-sm text-slate-600">
          {description ?? (
            <>
              このサーバはループバック以外で動作しています。
              <code className="rounded bg-slate-100 px-1">OBSIDIAN_AI_HUB_API_TOKEN</code>{" "}
              の値を入力してください。
            </>
          )}
        </p>
        <label htmlFor="review-token" className="sr-only">
          API token
        </label>
        <input
          id="review-token"
          type="password"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="API token"
          aria-describedby={error ? "token-error" : undefined}
          className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
        />
        {error && (
          <p id="token-error" className="text-sm text-red-600">
            {error}
          </p>
        )}
        <button
          type="submit"
          disabled={busy || !value}
          className="w-full rounded bg-slate-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {busy ? "確認中…" : "続行"}
        </button>
      </form>
    </div>
  );
}
