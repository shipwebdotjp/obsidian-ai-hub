import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AgentFormPanel } from "./AgentFormPanel";
import type { Agent } from "../../api/types";

const CLIPBOARD_PATH_D =
  "M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h12a2 2 0 002-2V7a2 2 0 00-2-2h-2M8 5a2 2 0 002 2h4a2 2 0 002-2M8 5a2 2 0 012-2h4a2 2 0 012 2";

const agent: Agent = {
  agent_id: "agent_123",
  name: "テストエージェント",
  system_prompt: "prompt",
  provider: null,
  model: null,
  tool_ids: [],
  delegate_agent_ids: [],
  advanced_params: null,
  pinned_at: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
} as unknown as Agent;

const baseProps: React.ComponentProps<typeof AgentFormPanel> = {
  isCreatingAgent: false,
  isEditingAgent: true,
  activeAgent: agent,
  selectedAgentId: "agent_123",
  onDeleteAgentTarget: vi.fn(),
  onCloseForm: vi.fn(),
  formError: null,
  onSaveAgent: vi.fn(),
  formName: "テストエージェント",
  onFormNameChange: vi.fn(),
  formPrompt: "prompt",
  onFormPromptChange: vi.fn(),
  formProvider: "",
  onFormProviderChange: vi.fn(),
  formModel: "",
  onFormModelChange: vi.fn(),
  isAdvancedOpen: false,
  onAdvancedOpenChange: vi.fn(),
  formMaxTokens: "",
  onFormMaxTokensChange: vi.fn(),
  formReasoningEffort: "",
  onFormReasoningEffortChange: vi.fn(),
  availableTools: [],
  formToolIds: [],
  onFormToolIdsChange: vi.fn(),
  agents: [agent],
  formDelegateAgentIds: [],
  onFormDelegateAgentIdsChange: vi.fn(),
  copiedAgentId: false,
  agentIdCopyError: null,
  onCopyAgentId: vi.fn(),
  promptTemplates: [],
  templateLoading: false,
  templateError: null,
  editingTemplateId: null,
  onEditTemplate: vi.fn(),
  onDeleteTemplate: vi.fn(),
  onCreateOrUpdateTemplate: vi.fn(),
  templateFormName: "",
  onTemplateFormNameChange: vi.fn(),
  templateFormContent: "",
  onTemplateFormContentChange: vi.fn(),
  onCancelEditTemplate: vi.fn(),
};

describe("AgentFormPanel agent ID copy button", () => {
  it("共通クリップボードアイコンを使い既存属性を維持する", () => {
    render(<AgentFormPanel {...baseProps} />);

    const btn = screen.getByTestId("copy-agent-id");
    expect(btn).toHaveAttribute("aria-label", "エージェントIDをコピー");
    expect(btn).toHaveAttribute("title", "エージェントIDをコピー");
    expect(btn.querySelector("svg path")?.getAttribute("d")).toBe(CLIPBOARD_PATH_D);
    expect(btn.querySelector(".lucide-copy")).toBeNull();
    expect(btn).toHaveTextContent("コピー");
  });

  it("クリックでIDコピーハンドラが呼ばれる", () => {
    const onCopyAgentId = vi.fn();
    render(<AgentFormPanel {...baseProps} onCopyAgentId={onCopyAgentId} />);

    fireEvent.click(screen.getByTestId("copy-agent-id"));
    expect(onCopyAgentId).toHaveBeenCalledTimes(1);
  });
});
