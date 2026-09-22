import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import VaultPathField from "./VaultPathField";

vi.mock("../../api/client", () => ({
  listVaultFiles: vi.fn(),
}));

import { listVaultFiles } from "../../api/client";

describe("VaultPathField", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listVaultFiles).mockResolvedValue({
      items: [
        { relative_path: "notes/a.md", size: 10, mtime: 0 },
        { relative_path: "notes/b.md", size: 20, mtime: 0 },
      ],
      total: 2,
    });
  });

  it("selects a vault path from the picker", async () => {
    const onChange = vi.fn();
    render(
      <VaultPathField value="" onChange={onChange} testIdPrefix="v" />,
    );
    await userEvent.click(screen.getByTestId("v-vault-open"));
    await waitFor(() =>
      expect(screen.getByText("notes/a.md")).toBeInTheDocument(),
    );
    await userEvent.click(screen.getByText("notes/b.md"));
    expect(onChange).toHaveBeenCalledWith("notes/b.md");
  });

  it("filters the file list by the search text", async () => {
    render(<VaultPathField value="" onChange={vi.fn()} testIdPrefix="v2" />);
    await userEvent.click(screen.getByTestId("v2-vault-open"));
    await waitFor(() =>
      expect(screen.getByText("notes/a.md")).toBeInTheDocument(),
    );
    await userEvent.type(screen.getByTestId("v2-vault-search"), "b.md");
    expect(screen.queryByText("notes/a.md")).not.toBeInTheDocument();
    expect(screen.getByText("notes/b.md")).toBeInTheDocument();
  });
});
