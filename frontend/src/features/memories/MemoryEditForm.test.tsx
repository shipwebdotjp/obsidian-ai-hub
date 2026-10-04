import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import MemoryEditForm from "./MemoryEditForm";

vi.mock("../../api/client", () => ({
  editMemory: vi.fn(),
}));

import { editMemory } from "../../api/client";

const mockEditMemory = vi.mocked(editMemory);

const baseMemory = {
  memory_id: "mem-1",
  content: "Body text",
  kind: "fact",
  topics: [],
  tags: [],
  evidence: [],
  people: [],
};

const notifyMock = vi.fn();
const onUpdatedMock = vi.fn();
const onCancelMock = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  mockEditMemory.mockResolvedValue({ memory: { ...baseMemory } } as any);
});

function renderForm(memory: Record<string, unknown>) {
  return render(
    <MemoryEditForm
      memory={memory as any}
      peopleOptions={[]}
      onUpdated={onUpdatedMock}
      notify={notifyMock}
      onCancel={onCancelMock}
    />
  );
}

describe("MemoryEditForm injection_mode", () => {
  it("submits injection_mode for approved user-scope memories", async () => {
    const user = userEvent.setup();
    renderForm({ ...baseMemory, status: "approved", scope: "user" });

    const select = screen.getByLabelText("エージェントへの注入");
    await user.selectOptions(select, "always");
    await user.click(screen.getByRole("button", { name: "編集して承認" }));

    await waitFor(() => expect(mockEditMemory).toHaveBeenCalledTimes(1));
    expect(mockEditMemory.mock.calls[0][1]).toMatchObject({
      injection_mode: "always",
    });
  });

  it("hides the injection control for person-scope memories", async () => {
    renderForm({ ...baseMemory, status: "approved", scope: "person" });

    expect(screen.queryByLabelText("エージェントへの注入")).toBeNull();
  });

  it("hides the injection control for candidates", async () => {
    renderForm({ ...baseMemory, status: "candidate", scope: "user" });

    expect(screen.queryByLabelText("エージェントへの注入")).toBeNull();
  });
});
