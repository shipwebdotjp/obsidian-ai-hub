import { ApiError, AUTH_EXPIRED_EVENT, clearToken, getToken } from "./client";

export interface RunSseEnvelope {
  eventId: number;
  data: Record<string, unknown>;
}

export function storageKey(domain: "agent" | "coding", runId: string): string {
  return `run-sse:${domain}:${runId}:last-event-id`;
}

export function loadLastAppliedId(domain: "agent" | "coding", runId: string): number {
  try {
    const raw = sessionStorage.getItem(storageKey(domain, runId));
    if (!raw) return 0;
    const parsed = parseInt(raw, 10);
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
  } catch {
    return 0;
  }
}

export function saveLastAppliedId(
  domain: "agent" | "coding",
  runId: string,
  eventId: number,
): void {
  try {
    sessionStorage.setItem(storageKey(domain, runId), String(eventId));
  } catch {
    // sessionStorage full/blocked: server log remains source of truth.
  }
}

/** Parse one SSE block with optional `id:` line (at-least-once replay). */
export function parseRunSseBlock(
  block: string,
  onEvent: (envelope: RunSseEnvelope) => void,
): void {
  let eventId: number | null = null;
  const dataLines: string[] = [];
  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith(":")) continue; // heartbeat comment
    if (line.startsWith("id:")) {
      const parsed = parseInt(line.slice(3).trim(), 10);
      if (Number.isFinite(parsed)) eventId = parsed;
      continue;
    }
    if (line.startsWith("data:")) {
      let data = line.slice(5);
      if (data.startsWith(" ")) data = data.slice(1);
      dataLines.push(data);
    }
  }
  if (dataLines.length === 0 || eventId === null) return;
  try {
    const data = JSON.parse(dataLines.join("\n")) as Record<string, unknown>;
    onEvent({ eventId, data });
  } catch (e) {
    console.error("Failed to parse run SSE event:", block, e);
  }
}

function drainRunSseBlocks(
  buffer: string,
  onEvent: (envelope: RunSseEnvelope) => void,
): string {
  let remainder = buffer;
  while (true) {
    const sep = /\r?\n\r?\n/.exec(remainder);
    if (!sep || sep.index === undefined) return remainder;
    parseRunSseBlock(remainder.slice(0, sep.index), onEvent);
    remainder = remainder.slice(sep.index + sep[0].length);
  }
}

export interface SubscribeRunEventsOptions {
  url: string;
  lastEventId: number;
  signal?: AbortSignal;
  /** Return true when the envelope is terminal and the stream should close. */
  isTerminal?: (envelope: RunSseEnvelope) => boolean;
  onEnvelope?: (envelope: RunSseEnvelope) => void;
}

/**
 * Fetch-based SSE subscriber that sends Authorization + Last-Event-ID.
 * Never uses EventSource (it cannot send Authorization headers).
 * Reconnects with exponential backoff; caller aborts via AbortController
 * for unmount/session-switch (which must NOT cancel the run).
 */
export async function subscribeRunEvents(
  options: SubscribeRunEventsOptions,
): Promise<void> {
  const { url, signal, isTerminal, onEnvelope } = options;
  let cursor = options.lastEventId;
  let backoffMs = 500;
  const maxBackoffMs = 8000;

  // At-least-once delivery: ignore re-sent IDs.
  let lastApplied = cursor;
  const handleEnvelope = (envelope: RunSseEnvelope) => {
    if (envelope.eventId <= lastApplied) return;
    lastApplied = envelope.eventId;
    cursor = envelope.eventId;
    onEnvelope?.(envelope);
  };

  while (true) {
    if (signal?.aborted) return;
    const headers = new Headers();
    headers.set("Accept", "text/event-stream");
    headers.set("Last-Event-ID", String(cursor));
    const token = getToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);

    let response: Response;
    try {
      response = await fetch(url, { headers, signal });
    } catch (e: unknown) {
      if (signal?.aborted) return;
      // Network failure: exponential backoff and retry same cursor.
      await sleepWithAbort(backoffMs, signal);
      backoffMs = Math.min(backoffMs * 2, maxBackoffMs);
      continue;
    }

    if (response.status === 401) {
      clearToken();
      window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
      throw new ApiError(401, "Authentication failed.");
    }
    // Terminal/auth/cancel: do not reconnect.
    if (response.status === 404 || response.status === 410) {
      throw new ApiError(response.status, response.statusText);
    }
    if (!response.ok || !response.body) {
      await sleepWithAbort(backoffMs, signal);
      backoffMs = Math.min(backoffMs * 2, maxBackoffMs);
      continue;
    }

    backoffMs = 500;
    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    let terminalReached = false;

    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        buffer = drainRunSseBlocks(buffer, (envelope) => {
          handleEnvelope(envelope);
          if (isTerminal?.(envelope)) terminalReached = true;
        });
        if (terminalReached) break;
        if (signal?.aborted) break;
      }
      buffer += decoder.decode();
      buffer = drainRunSseBlocks(buffer, (envelope) => {
        handleEnvelope(envelope);
        if (isTerminal?.(envelope)) terminalReached = true;
      });
      if (buffer.trim()) parseRunSseBlock(buffer, handleEnvelope);
    } catch (e: unknown) {
      if (signal?.aborted) return;
      await sleepWithAbort(backoffMs, signal);
      backoffMs = Math.min(backoffMs * 2, maxBackoffMs);
      continue;
    } finally {
      try {
        reader.releaseLock();
      } catch {
        // ignore
      }
    }

    if (terminalReached) return;
    if (signal?.aborted) return;
    // Server closed without terminal (e.g. waiting_user pause or heartbeat
    // timeout): return so the caller can fold and resubscribe on demand.
    // For live runs the caller re-invokes subscribe; transient network drops
    // are retried above via read errors.
    return;
  }
}

function sleepWithAbort(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal?.aborted) {
      resolve();
      return;
    }
    const timer = window.setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      window.clearTimeout(timer);
      resolve();
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

/** Fold text_append deltas in id order (append-only, no duplication). */
export function foldTextDeltas(
  envelopes: RunSseEnvelope[],
  lastAppliedId: number,
): { text: string; lastId: number } {
  const sorted = [...envelopes]
    .filter((e) => e.eventId > lastAppliedId)
    .sort((a, b) => a.eventId - b.eventId);
  let text = "";
  let lastId = lastAppliedId;
  for (const env of sorted) {
    const type = String(env.data["type"] ?? env.data["event"] ?? "");
    if (type === "text_append") {
      text += String(env.data["delta"] ?? "");
    }
    lastId = Math.max(lastId, env.eventId);
  }
  return { text, lastId };
}
