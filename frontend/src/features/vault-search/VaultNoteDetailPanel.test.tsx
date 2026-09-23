import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import VaultNoteDetailPanel from "./VaultNoteDetailPanel";

vi.mock("../../api/client", () => ({
  getVaultFile: vi.fn(),
}));

import { getVaultFile } from "../../api/client";

const mockGetVaultFile = vi.mocked(getVaultFile);

beforeEach(() => {
  vi.clearAllMocks();
});

describe("VaultNoteDetailPanel", () => {
  it("renders frontmatter and body fetched from the vault-file API", async () => {
    mockGetVaultFile.mockResolvedValue({
      content: "---\ntitle: Hello\n---\n# World",
      relative_path: "notes/a.md",
      vault_name: "MyVault",
    });

    render(
      <VaultNoteDetailPanel relativePath="notes/a.md" notify={vi.fn()} />,
    );

    expect(await screen.findByText("World")).toBeInTheDocument();
    expect(screen.getByText(/title: Hello/)).toBeInTheDocument();
    expect(screen.getByText("MyVault")).toBeInTheDocument();
  });

  it("opens Obsidian with the vault_name from the API response", async () => {
    mockGetVaultFile.mockResolvedValue({
      content: "body",
      relative_path: "notes/a.md",
      vault_name: "MyVault",
    });
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);

    render(
      <VaultNoteDetailPanel relativePath="notes/a.md" notify={vi.fn()} />,
    );

    await screen.findByText("body");
    await userEvent.click(screen.getByRole("button", { name: "Obsidian で開く" }));

    expect(openSpy).toHaveBeenCalledTimes(1);
    const url = openSpy.mock.calls[0][0] as string;
    expect(url).toContain("obsidian://open");
    expect(url).toContain("vault=MyVault");
    expect(url).toContain(`file=${encodeURIComponent("notes/a")}`);
    openSpy.mockRestore();
  });

  it("shows an error when the note cannot be fetched", async () => {
    mockGetVaultFile.mockRejectedValue(new Error("boom"));

    render(
      <VaultNoteDetailPanel relativePath="notes/a.md" notify={vi.fn()} />,
    );

    await waitFor(() => {
      expect(screen.getByText("boom")).toBeInTheDocument();
    });
  });
});
