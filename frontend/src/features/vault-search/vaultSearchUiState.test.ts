import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import type { VaultFileListItem } from "../../api/types";
import {
  DEFAULT_VAULT_SEARCH_UI_STATE,
  VAULT_SEARCH_UI_STORAGE_KEY,
  collectVaultDirectories,
  readVaultSearchUiState,
  reconcileExplorerState,
  writeVaultSearchUiState,
  type VaultSearchUiState,
} from "./vaultSearchUiState";

function file(relative_path: string): VaultFileListItem {
  return { relative_path, size: 100, mtime: 1700000000 };
}

beforeEach(() => {
  localStorage.removeItem(VAULT_SEARCH_UI_STORAGE_KEY);
});

describe("readVaultSearchUiState", () => {
  it("returns defaults when nothing is saved", () => {
    expect(readVaultSearchUiState()).toEqual(DEFAULT_VAULT_SEARCH_UI_STATE);
  });

  it("round-trips a saved state", () => {
    const state: VaultSearchUiState = {
      activeTab: "explorer",
      expandedDirs: ["会議"],
      selectedDir: "会議",
      notePath: "会議/a.md",
      sortKey: "name",
      sortDir: "asc",
    };
    writeVaultSearchUiState(state);
    expect(readVaultSearchUiState()).toEqual(state);
  });

  it("falls back per-field for invalid values", () => {
    localStorage.setItem(
      VAULT_SEARCH_UI_STORAGE_KEY,
      JSON.stringify({
        activeTab: "bogus",
        expandedDirs: [1, "ok", null],
        selectedDir: 42,
        notePath: "",
        sortKey: "size",
        sortDir: "sideways",
      }),
    );
    expect(readVaultSearchUiState()).toEqual({
      activeTab: "search",
      expandedDirs: ["ok"],
      selectedDir: "",
      notePath: null,
      sortKey: "mtime",
      sortDir: "desc",
    });
  });

  it("returns defaults for broken JSON", () => {
    localStorage.setItem(VAULT_SEARCH_UI_STORAGE_KEY, "{not json");
    expect(readVaultSearchUiState()).toEqual(DEFAULT_VAULT_SEARCH_UI_STATE);
  });

  it("returns defaults when localStorage is unavailable", () => {
    const original = Object.getOwnPropertyDescriptor(window, "localStorage");
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      get() {
        throw new Error("denied");
      },
    });
    try {
      expect(readVaultSearchUiState()).toEqual(DEFAULT_VAULT_SEARCH_UI_STATE);
      expect(() =>
        writeVaultSearchUiState({ ...DEFAULT_VAULT_SEARCH_UI_STATE, activeTab: "explorer" }),
      ).not.toThrow();
    } finally {
      if (original) Object.defineProperty(window, "localStorage", original);
    }
  });
});

describe("writeVaultSearchUiState", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("never throws when setItem fails", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    expect(() => writeVaultSearchUiState(DEFAULT_VAULT_SEARCH_UI_STATE)).not.toThrow();
  });
});

describe("collectVaultDirectories", () => {
  it("collects every ancestor directory", () => {
    const dirs = collectVaultDirectories([file("a/b/c.md"), file("root.md")]);
    expect([...dirs].sort()).toEqual(["a", "a/b"]);
  });
});

describe("reconcileExplorerState", () => {
  const base: VaultSearchUiState = {
    activeTab: "explorer",
    expandedDirs: ["会議", "消えた"],
    selectedDir: "消えた",
    notePath: "消えた/old.md",
    sortKey: "mtime",
    sortDir: "desc",
  };

  it("drops missing directories and resets missing selected dir / note independently", () => {
    const items = [file("会議/a.md"), file("会議/sub/b.md")];
    expect(reconcileExplorerState(base, items)).toEqual({
      activeTab: "explorer",
      expandedDirs: ["会議"],
      selectedDir: "",
      notePath: null,
      sortKey: "mtime",
      sortDir: "desc",
    });
  });

  it("keeps still-valid state", () => {
    const items = [file("会議/a.md"), file("会議/sub/b.md")];
    const state: VaultSearchUiState = {
      activeTab: "explorer",
      expandedDirs: ["会議", "会議/sub"],
      selectedDir: "会議",
      notePath: "会議/sub/b.md",
      sortKey: "name",
      sortDir: "asc",
    };
    expect(reconcileExplorerState(state, items)).toEqual(state);
  });

  it("keeps root selection (empty string) as valid", () => {
    const items = [file("root.md")];
    const state: VaultSearchUiState = {
      ...base,
      expandedDirs: [],
      selectedDir: "",
      notePath: null,
    };
    expect(reconcileExplorerState(state, items)).toEqual(state);
  });
});
