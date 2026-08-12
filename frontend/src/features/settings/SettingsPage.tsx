import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  getToken,
  setToken,
  clearToken,
  listMemories,
  ApiError,
  AUTH_EXPIRED_EVENT,
} from "../../api/client";

export default function SettingsPage() {
  const [value, setValue] = useState(getToken());
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isMounted = useRef(true);

  useEffect(() => {
    isMounted.current = true;
    return () => {
      isMounted.current = false;
    };
  }, []);

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaved(false);
    setBusy(true);
    setToken(value.trim());
    try {
      await listMemories({ status: "candidate" });
      if (!isMounted.current) return;
      setSaved(true);
    } catch (e) {
      if (!isMounted.current) return;
      const msg = e instanceof ApiError ? e.message : "トークン検証に失敗しました";
      clearToken();
      setError(msg);
    } finally {
      if (isMounted.current) setBusy(false);
    }
  }

  function handleClear() {
    if (!window.confirm("API トークンを削除しますか？")) return;
    clearToken();
    setValue("");
    setSaved(false);
    setError(null);
    window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
  }

  return (
    <div className="flex h-full flex-col bg-slate-50">
      <header className="flex shrink-0 items-center justify-between gap-3 border-b border-slate-200 bg-white px-4 py-3 sm:px-6 sm:py-4">
        <h1 className="text-lg font-bold text-slate-900">設定</h1>
      </header>
      <div className="flex-1 overflow-auto p-4 sm:p-6">
        <form
          onSubmit={handleSave}
          className="w-full max-w-xl space-y-4 rounded-xl border border-slate-200 bg-white p-6 shadow-sm"
        >
          <div>
            <h2 className="text-base font-semibold text-slate-900">API トークン</h2>
            <p className="mt-1 text-sm text-slate-600">
              API リクエストの
              <code className="mx-1 rounded bg-slate-100 px-1">Authorization</code>{" "}
              ヘッダーに付与されます。ブラウザのローカルストレージに保存されます。
            </p>
          </div>
          <div>
            <label htmlFor="api-token" className="sr-only">
              API token
            </label>
            <input
              id="api-token"
              type="password"
              value={value}
              onChange={(e) => {
                setValue(e.target.value);
                setSaved(false);
              }}
              placeholder="API token"
              aria-describedby={error ? "settings-token-error" : undefined}
              className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
            />
            {error && (
              <p id="settings-token-error" className="mt-2 text-sm text-red-600">
                {error}
              </p>
            )}
            {saved && !error && (
              <p className="mt-2 text-sm text-emerald-600">トークンを保存しました</p>
            )}
          </div>
          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={busy || !value.trim()}
              className="cursor-pointer rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {busy ? "確認中…" : "保存"}
            </button>
            <button
              type="button"
              onClick={handleClear}
              disabled={busy}
              className="cursor-pointer rounded bg-rose-800 px-4 py-2 text-sm font-medium text-white hover:bg-rose-900 disabled:cursor-not-allowed disabled:opacity-50"
            >
              トークンを削除
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
