import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  listTaskAgentCapabilities,
  updateTaskAgentCapability,
} from "../../api/client";
import CapabilitySettingsPage from "./CapabilitySettingsPage";

vi.mock("../../api/client", () => ({
  listTaskAgentCapabilities: vi.fn(),
  updateTaskAgentCapability: vi.fn(),
  ApiError: class ApiError extends Error {},
}));

const mockList = vi.mocked(listTaskAgentCapabilities);
const mockUpdate = vi.mocked(updateTaskAgentCapability);

const sampleCapabilities = [
  {
    capability_key: "web_search",
    adapter_kind: "registry_tool",
    enabled: true,
    approval_policy: "auto",
    updated_at: "2026-09-14T10:00:00+09:00",
  },
  {
    capability_key: "coding_cli",
    adapter_kind: "coding",
    enabled: true,
    approval_policy: "plan_required",
    updated_at: "2026-09-14T10:00:00+09:00",
  },
];

function renderPage() {
  return render(
    <MemoryRouter>
      <CapabilitySettingsPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockList.mockResolvedValue(sampleCapabilities as any);
  mockUpdate.mockImplementation(async (_key, update) => ({
    capability_key: "coding_cli",
    adapter_kind: "coding",
    enabled: update.enabled ?? true,
    approval_policy: update.approval_policy ?? "plan_required",
    updated_at: "2026-09-14T11:00:00+09:00",
  }) as any);
});

describe("CapabilitySettingsPage", () => {
  it("lists capabilities with descriptions", async () => {
    renderPage();
    await waitFor(() => expect(mockList).toHaveBeenCalled());
    expect(await screen.findByText("Web検索")).toBeInTheDocument();
    expect(screen.getByText(/Coding CLI実行/)).toBeInTheDocument();
  });

  it("toggles enabled and saves with PUT args", async () => {
    const user = userEvent.setup();
    renderPage();
    const rows = await screen.findAllByTestId("capability-row");
    expect(rows).toHaveLength(2);
    const codingRow = rows[1];
    const checkbox = within(codingRow as HTMLElement).getByLabelText("coding_cliの有効化");
    await user.click(checkbox);
    const saveButtons = within(codingRow as HTMLElement).getAllByRole("button", { name: "保存" });
    const save = saveButtons[0];
    expect(save).not.toBeDisabled();
    await user.click(save);
    await waitFor(() =>
      expect(mockUpdate).toHaveBeenCalledWith("coding_cli", {
        enabled: false,
        approval_policy: "plan_required",
      }),
    );
    expect(await screen.findByText("保存しました")).toBeInTheDocument();
  });

  it("shows an error when save fails", async () => {
    const user = userEvent.setup();
    mockUpdate.mockRejectedValue(new Error("denied"));
    renderPage();
    const rows = await screen.findAllByTestId("capability-row");
    const checkbox = within(rows[0] as HTMLElement).getByLabelText("web_searchの有効化");
    await user.click(checkbox);
    const save = within(rows[0] as HTMLElement).getAllByRole("button", { name: "保存" })[0];
    await user.click(save);
    await waitFor(() =>
      expect(screen.getByText("保存に失敗しました")).toBeInTheDocument(),
    );
  });
});
