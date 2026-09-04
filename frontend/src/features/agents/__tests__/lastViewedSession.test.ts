import { describe, it, expect, beforeEach } from "vitest";
import {
  LAST_VIEWED_SESSION_STORAGE_KEY,
  clearLastViewedSessionId,
  readLastViewedSessionId,
  writeLastViewedSessionId,
} from "../lastViewedSession";

describe("last viewed session storage", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
  });

  it("uses a versioned obsidian-ai-hub localStorage key", () => {
    expect(LAST_VIEWED_SESSION_STORAGE_KEY).toBe(
      "obsidian-ai-hub:agents-last-viewed-session:v1",
    );
  });

  it("round-trips the session id as JSON", () => {
    writeLastViewedSessionId("asess_456");
    const raw = JSON.parse(window.localStorage.getItem(LAST_VIEWED_SESSION_STORAGE_KEY) || "{}");
    expect(raw.session_id).toBe("asess_456");
    expect(raw.savedAt).toBeTruthy();
    expect(readLastViewedSessionId()).toBe("asess_456");
  });

  it("overwrites with the most recently written session (shared across tabs)", () => {
    writeLastViewedSessionId("asess_111");
    writeLastViewedSessionId("asess_222");
    expect(readLastViewedSessionId()).toBe("asess_222");
  });

  it("clears the stored session", () => {
    writeLastViewedSessionId("asess_456");
    clearLastViewedSessionId();
    expect(window.localStorage.getItem(LAST_VIEWED_SESSION_STORAGE_KEY)).toBeNull();
    expect(readLastViewedSessionId()).toBeNull();
  });

  it("returns null for missing, corrupt, or invalid values", () => {
    expect(readLastViewedSessionId()).toBeNull();
    window.localStorage.setItem(LAST_VIEWED_SESSION_STORAGE_KEY, "{not-json");
    expect(readLastViewedSessionId()).toBeNull();
    window.localStorage.setItem(LAST_VIEWED_SESSION_STORAGE_KEY, JSON.stringify({ session_id: "" }));
    expect(readLastViewedSessionId()).toBeNull();
    window.localStorage.setItem(LAST_VIEWED_SESSION_STORAGE_KEY, JSON.stringify({ savedAt: "t" }));
    expect(readLastViewedSessionId()).toBeNull();
    window.localStorage.setItem(LAST_VIEWED_SESSION_STORAGE_KEY, JSON.stringify(["asess_456"]));
    expect(readLastViewedSessionId()).toBeNull();
  });

  it("does not throw when localStorage access fails", () => {
    const throwing = {
      getItem: () => {
        throw new Error("denied");
      },
      setItem: () => {
        throw new Error("denied");
      },
      removeItem: () => {
        throw new Error("denied");
      },
    };
    const original = window.localStorage;
    Object.defineProperty(window, "localStorage", { configurable: true, value: throwing });
    try {
      expect(readLastViewedSessionId()).toBeNull();
      expect(() => writeLastViewedSessionId("asess_456")).not.toThrow();
      expect(() => clearLastViewedSessionId()).not.toThrow();
    } finally {
      Object.defineProperty(window, "localStorage", { configurable: true, value: original });
    }
  });

  it("does not break when localStorage is unavailable", () => {
    const original = window.localStorage;
    Object.defineProperty(window, "localStorage", { configurable: true, value: undefined });
    try {
      expect(readLastViewedSessionId()).toBeNull();
      expect(() => writeLastViewedSessionId("asess_456")).not.toThrow();
      expect(() => clearLastViewedSessionId()).not.toThrow();
    } finally {
      Object.defineProperty(window, "localStorage", { configurable: true, value: original });
    }
  });
});
