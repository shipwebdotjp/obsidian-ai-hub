import "@testing-library/jest-dom/vitest";

// Newer Node releases expose an empty built-in localStorage object when their
// storage file is unavailable.  It shadows jsdom's Storage implementation,
// so provide the browser-shaped fallback only for that test-environment case.
if (typeof globalThis.localStorage?.getItem !== "function") {
  const values = new Map<string, string>();
  const fallbackStorage: Storage = {
    get length() {
      return values.size;
    },
    clear() {
      values.clear();
    },
    getItem(key) {
      return values.get(String(key)) ?? null;
    },
    key(index) {
      return [...values.keys()][index] ?? null;
    },
    removeItem(key) {
      values.delete(String(key));
    },
    setItem(key, value) {
      values.set(String(key), String(value));
    },
  };
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    value: fallbackStorage,
  });
}
