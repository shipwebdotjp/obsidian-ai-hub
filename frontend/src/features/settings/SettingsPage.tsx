import { useEffect, useRef, useState, type FormEvent } from "react";
import { getApiErrorMessage } from "../../utils/error";
import {
  getToken,
  setToken,
  clearToken,
  listMemories,
  getNotificationSettings,
  updateNotificationSettings,
  getVapidPublicKey,
  registerWebPushSubscription,
  unregisterWebPushSubscription,
  listWebPushSubscriptions,
  AUTH_EXPIRED_EVENT,
} from "../../api/client";
import type {
  NotificationSettings,
  WebPushSubscriptionMetadata,
} from "../../api/types";
import { useChatSendMode } from "./chatSendMode";

function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = window.atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}

export default function SettingsPage() {
  const [value, setValue] = useState(getToken());
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sendMode, setSendMode] = useChatSendMode();
  const isMounted = useRef(true);

  // Notification settings state
  const [notifSettings, setNotifSettings] = useState<NotificationSettings | null>(null);
  const [subscriptions, setSubscriptions] = useState<WebPushSubscriptionMetadata[]>([]);
  const [notifLoading, setNotifLoading] = useState(false);
  const [notifError, setNotifError] = useState<string | null>(null);
  const [notifSuccess, setNotifSuccess] = useState<string | null>(null);
  const [permissionState, setPermissionState] = useState<NotificationPermission>(
    typeof Notification !== "undefined" ? Notification.permission : "default"
  );
  const [isSupported, setIsSupported] = useState(false);

  useEffect(() => {
    isMounted.current = true;
    const supported =
      typeof window !== "undefined" &&
      "serviceWorker" in navigator &&
      "PushManager" in window &&
      "Notification" in window;
    setIsSupported(supported);

    if (getToken()) {
      fetchNotifSettings();
    }

    return () => {
      isMounted.current = false;
    };
  }, []);

  async function fetchNotifSettings() {
    setNotifLoading(true);
    setNotifError(null);
    try {
      const [settings, subs] = await Promise.all([
        getNotificationSettings(),
        listWebPushSubscriptions(),
      ]);
      if (!isMounted.current) return;
      setNotifSettings(settings);
      setSubscriptions(subs);
    } catch (err) {
      if (!isMounted.current) return;
      setNotifError(getApiErrorMessage(err, "通知設定の取得に失敗しました"));
    } finally {
      if (isMounted.current) setNotifLoading(false);
    }
  }

  async function handleToggleSetting(
    key: keyof Omit<NotificationSettings, "updated_at">,
    value: boolean
  ) {
    if (!notifSettings) return;
    setNotifError(null);
    setNotifSuccess(null);
    try {
      const updated = await updateNotificationSettings({ [key]: value });
      if (!isMounted.current) return;
      setNotifSettings(updated);
    } catch (err) {
      if (!isMounted.current) return;
      setNotifError(getApiErrorMessage(err, "設定の更新に失敗しました"));
    }
  }

  async function handleEnableWebPush() {
    setNotifError(null);
    setNotifSuccess(null);
    setNotifLoading(true);

    try {
      if (!isSupported) {
        throw new Error("このブラウザは Web Push に対応していません。");
      }

      // 1. Request Notification permission
      const perm = await Notification.requestPermission();
      setPermissionState(perm);
      if (perm !== "granted") {
        throw new Error("通知の許可が拒否されています。ブラウザの設定から通知を許可してください。");
      }

      // 2. Fetch VAPID public key
      const { vapid_public_key } = await getVapidPublicKey();
      if (!vapid_public_key) {
        throw new Error("VAPID公開鍵が設定されていません。WEB_PUSH_VAPID_PUBLIC_KEY を確認してください。");
      }

      // 3. Register Service Worker
      const reg = await navigator.serviceWorker.register("/service-worker.js");
      await navigator.serviceWorker.ready;

      // 4. Subscribe to PushManager
      const sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(vapid_public_key) as BufferSource,
      });

      const subJson = sub.toJSON();
      if (!subJson.endpoint || !subJson.keys?.p256dh || !subJson.keys?.auth) {
        throw new Error("Push購読データの取得に失敗しました。");
      }

      // 5. Send subscription to server
      await registerWebPushSubscription({
        endpoint: subJson.endpoint,
        p256dh: subJson.keys.p256dh,
        auth: subJson.keys.auth,
        user_agent: navigator.userAgent,
      });

      // 6. Update notification settings
      const updated = await updateNotificationSettings({
        web_push_enabled: true,
        web_push_action_required: true,
        web_push_failure: true,
      });

      if (!isMounted.current) return;
      setNotifSettings(updated);
      setNotifSuccess("Web Push を有効化し、端末を登録しました。");
      fetchNotifSettings();
    } catch (err) {
      if (!isMounted.current) return;
      setNotifError(getApiErrorMessage(err, "Web Push の有効化に失敗しました"));
    } finally {
      if (isMounted.current) setNotifLoading(false);
    }
  }

  async function handleUnsubscribeWebPush(subId?: string) {
    setNotifError(null);
    setNotifSuccess(null);
    setNotifLoading(true);

    try {
      let isCurrentBrowserSub = false;
      let browserSub: PushSubscription | null = null;

      if (isSupported && "serviceWorker" in navigator) {
        const reg = await navigator.serviceWorker.getRegistration("/service-worker.js");
        if (reg) {
          browserSub = await reg.pushManager.getSubscription();
        }
      }

      if (subId) {
        const target = subscriptions.find((s) => s.subscription_id === subId);
        if (browserSub && target && browserSub.endpoint.includes(target.endpoint_domain)) {
          isCurrentBrowserSub = true;
        }
        await unregisterWebPushSubscription(subId);
      } else if (subscriptions.length > 0) {
        for (const sub of subscriptions) {
          await unregisterWebPushSubscription(sub.subscription_id);
        }
        isCurrentBrowserSub = true;
      }

      if (isCurrentBrowserSub && browserSub) {
        await browserSub.unsubscribe().catch(() => {});
      }

      const shouldDisableWebPush = isCurrentBrowserSub || (!subId && subscriptions.length > 0);
      const updated = await updateNotificationSettings({
        web_push_enabled: shouldDisableWebPush ? false : notifSettings?.web_push_enabled,
      });

      if (!isMounted.current) return;
      setNotifSettings(updated);
      setNotifSuccess("Web Push 購読を解除しました。");
      fetchNotifSettings();
    } catch (err) {
      if (!isMounted.current) return;
      setNotifError(getApiErrorMessage(err, "購読解除に失敗しました"));
    } finally {
      if (isMounted.current) setNotifLoading(false);
    }
  }

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
      fetchNotifSettings();
    } catch (e) {
      if (!isMounted.current) return;
      const msg = getApiErrorMessage(e, "トークン検証に失敗しました");
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
    setNotifSettings(null);
    window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
  }

  return (
    <div className="flex h-full flex-col bg-slate-50">
      <header className="flex shrink-0 items-center justify-between gap-3 border-b border-slate-200 bg-white px-4 py-3 sm:px-6 sm:py-4">
        <h1 className="text-lg font-bold text-slate-900">設定</h1>
      </header>
      <div className="flex-1 overflow-auto p-4 space-y-6 sm:p-6">
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

        {/* --- Web Push / Notifications Section --- */}
        <section className="w-full max-w-xl space-y-4 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <div>
            <h2 className="text-base font-semibold text-slate-900">Web Push 通知</h2>
            <p className="mt-1 text-sm text-slate-600">
              要対応イベント（HITL、承認待ち、Agent質問等）および処理失敗時にブラウザへリアルタイム通知を送ります。
            </p>
          </div>

          {!isSupported && (
            <div className="rounded-lg bg-amber-50 p-3 text-sm text-amber-800 border border-amber-200">
              このブラウザは Web Push 通知に対応していません。
            </div>
          )}

          {permissionState === "denied" && (
            <div className="rounded-lg bg-rose-50 p-3 text-sm text-rose-800 border border-rose-200">
              通知の許可が拒否されています。ブラウザの設定からこのサイトの通知を許可してください。
            </div>
          )}

          {notifError && (
            <div className="rounded-lg bg-rose-50 p-3 text-sm text-rose-800 border border-rose-200">
              {notifError}
            </div>
          )}

          {notifSuccess && (
            <div className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800 border border-emerald-200">
              {notifSuccess}
            </div>
          )}

          {notifSettings && (
            <div className="space-y-4 pt-2">
              <div className="flex items-center justify-between border-b border-slate-100 pb-3">
                <div>
                  <span className="font-medium text-sm text-slate-900">Web Push 有効化</span>
                  <p className="text-xs text-slate-500">全体配信スイッチ</p>
                </div>
                <input
                  type="checkbox"
                  checked={notifSettings.web_push_enabled}
                  onChange={(e) => handleToggleSetting("web_push_enabled", e.target.checked)}
                  disabled={notifLoading}
                  className="h-5 w-5 cursor-pointer accent-blue-600"
                />
              </div>

              {notifSettings.web_push_enabled && (
                <div className="space-y-3 pl-4 border-l-2 border-slate-200">
                  <label className="flex items-center justify-between text-sm text-slate-700 cursor-pointer">
                    <span>要対応通知（HITL, Task/Workflow承認, Agent/Coding質問, Planner提案）</span>
                    <input
                      type="checkbox"
                      checked={notifSettings.web_push_action_required}
                      onChange={(e) => handleToggleSetting("web_push_action_required", e.target.checked)}
                      disabled={notifLoading}
                      className="h-4 w-4 cursor-pointer accent-blue-600"
                    />
                  </label>
                  <label className="flex items-center justify-between text-sm text-slate-700 cursor-pointer">
                    <span>失敗系通知（failed, interrupted, incomplete）</span>
                    <input
                      type="checkbox"
                      checked={notifSettings.web_push_failure}
                      onChange={(e) => handleToggleSetting("web_push_failure", e.target.checked)}
                      disabled={notifLoading}
                      className="h-4 w-4 cursor-pointer accent-blue-600"
                    />
                  </label>
                </div>
              )}

              <div className="flex flex-wrap items-center gap-3 pt-2">
                <button
                  type="button"
                  onClick={handleEnableWebPush}
                  disabled={notifLoading || !isSupported}
                  className="cursor-pointer rounded bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {notifLoading ? "処理中…" : "この端末でWeb Pushを購読"}
                </button>

                {subscriptions.length > 0 && (
                  <button
                    type="button"
                    onClick={() => handleUnsubscribeWebPush()}
                    disabled={notifLoading}
                    className="cursor-pointer rounded border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    すべての登録を解除
                  </button>
                )}
              </div>

              {subscriptions.length > 0 && (
                <div className="mt-4 pt-3 border-t border-slate-100">
                  <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">
                    登録済み端末・ブラウザ一覧 ({subscriptions.length})
                  </h3>
                  <ul className="space-y-2 text-xs text-slate-600">
                    {subscriptions.map((sub) => (
                      <li
                        key={sub.subscription_id}
                        className="flex items-center justify-between rounded bg-slate-50 p-2 border border-slate-200"
                      >
                        <div>
                          <span className="font-mono font-medium text-slate-800">{sub.endpoint_domain}</span>
                          <span className="ml-2 text-slate-400">({new Date(sub.created_at).toLocaleDateString()})</span>
                        </div>
                        <button
                          type="button"
                          onClick={() => handleUnsubscribeWebPush(sub.subscription_id)}
                          className="text-rose-600 hover:underline text-xs"
                        >
                          削除
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </section>

        {/* --- LINE Notifications Section --- */}
        <section className="w-full max-w-xl space-y-4 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <div>
            <h2 className="text-base font-semibold text-slate-900">LINE 通知</h2>
            <p className="mt-1 text-sm text-slate-600">
              LINE Messaging API 経由で要対応・失敗系通知を受信します（LINE_MESSAGING_TOKEN と LINE_TARGET_ID が必要）。
            </p>
          </div>

          {notifSettings && (
            <div className="space-y-4 pt-2">
              <div className="flex items-center justify-between border-b border-slate-100 pb-3">
                <div>
                  <span className="font-medium text-sm text-slate-900">LINE通知 有効化</span>
                  <p className="text-xs text-slate-500">全体配信スイッチ</p>
                </div>
                <input
                  type="checkbox"
                  checked={notifSettings.line_enabled}
                  onChange={(e) => handleToggleSetting("line_enabled", e.target.checked)}
                  disabled={notifLoading}
                  className="h-5 w-5 cursor-pointer accent-blue-600"
                />
              </div>

              {notifSettings.line_enabled && (
                <div className="space-y-3 pl-4 border-l-2 border-slate-200">
                  <label className="flex items-center justify-between text-sm text-slate-700 cursor-pointer">
                    <span>要対応通知（HITL, Task/Workflow承認, Agent/Coding質問, Planner提案）</span>
                    <input
                      type="checkbox"
                      checked={notifSettings.line_action_required}
                      onChange={(e) => handleToggleSetting("line_action_required", e.target.checked)}
                      disabled={notifLoading}
                      className="h-4 w-4 cursor-pointer accent-blue-600"
                    />
                  </label>
                  <label className="flex items-center justify-between text-sm text-slate-700 cursor-pointer">
                    <span>失敗系通知（failed, interrupted, incomplete）</span>
                    <input
                      type="checkbox"
                      checked={notifSettings.line_failure}
                      onChange={(e) => handleToggleSetting("line_failure", e.target.checked)}
                      disabled={notifLoading}
                      className="h-4 w-4 cursor-pointer accent-blue-600"
                    />
                  </label>
                </div>
              )}
            </div>
          )}
        </section>

        <section className="w-full max-w-xl space-y-3 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <div>
            <h2 className="text-base font-semibold text-slate-900">チャット入力の送信方法</h2>
            <p className="mt-1 text-sm text-slate-600">
              メッセージ入力欄での Enter キーの動作を選択します。
            </p>
          </div>
          <div className="space-y-2">
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input
                type="radio"
                checked={sendMode === "enter"}
                onChange={() => setSendMode("enter")}
                className="cursor-pointer"
              />
              Enter で送信（Shift+Enter で改行）
            </label>
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input
                type="radio"
                checked={sendMode === "newline"}
                onChange={() => setSendMode("newline")}
                className="cursor-pointer"
              />
              Enter で改行（Ctrl/Cmd+Enter で送信）
            </label>
          </div>
        </section>
      </div>
    </div>
  );
}
