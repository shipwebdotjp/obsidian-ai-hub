import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState, type ComponentProps } from "react";
import { describe, it, expect, vi } from "vitest";
import { AgentChatInput } from "../AgentChatInput";

type ChatInputProps = ComponentProps<typeof AgentChatInput>;

function baseProps(overrides: Partial<ChatInputProps> = {}): ChatInputProps {
  return {
    inputText: "",
    onInputTextChange: () => {},
    isStreaming: false,
    queuedCount: 0,
    selectedSessionId: "asess_1",
    activeAgent: { agent_id: "a1", name: "A", model: "m" } as ChatInputProps["activeAgent"],
    isDragOver: false,
    pendingAttachments: [],
    onRemoveAttachment: () => {},
    pendingContextRefs: [],
    onRemoveContextRef: () => {},
    onToggleContextRef: () => {},
    vaultPickerOpen: false,
    onOpenVaultPicker: () => {},
    onCloseVaultPicker: () => {},
    selectedSkill: null,
    onClearSkill: () => {},
    isPaletteActive: false,
    filteredCandidates: [],
    skillCandidates: [],
    templateCandidates: [],
    paletteOrderedCandidates: [],
    paletteSelectedIndex: 0,
    onPaletteSelectedIndexChange: () => {},
    hasSkillsTool: false,
    onSelectCandidate: () => {},
    onSelectTemplate: () => {},
    plusMenuOpen: false,
    onTogglePlusMenu: () => {},
    onOpenTemplateSelector: () => {},
    templateSelectorOpen: false,
    promptTemplates: [],
    attachmentReadsPending: 0,
    imageInputRef: { current: null },
    onClosePlusMenu: () => {},
    onFilesSelected: () => {},
    onSend: () => {},
    onCancelRun: () => {},
    onDismissPalette: () => {},
    onPaste: () => {},
    onFormDragOver: () => {},
    onFormDragLeave: () => {},
    onFormDrop: () => {},
    ...overrides,
  };
}

function setup(overrides: Partial<ChatInputProps> = {}) {
  const props = baseProps(overrides);
  const spies = {
    onInputTextChange: vi.fn(),
    onOpenVaultPicker: vi.fn(),
    onRemoveContextRef: vi.fn(),
  };
  props.onInputTextChange = spies.onInputTextChange;
  props.onOpenVaultPicker = spies.onOpenVaultPicker;
  props.onRemoveContextRef = spies.onRemoveContextRef;
  render(<AgentChatInput {...props} />);
  return spies;
}

describe("AgentChatInput context refs", () => {
  it("opens the vault picker and strips @ typed at the start", async () => {
    const user = userEvent.setup();
    const props = setup();
    const textarea = screen.getByRole("textbox");
    await user.click(textarea);
    await user.keyboard("@");
    expect(props.onOpenVaultPicker).toHaveBeenCalledTimes(1);
    expect(props.onInputTextChange).toHaveBeenCalledWith("");
  });

  it("opens the picker for @ after whitespace but not inside a word", async () => {
    const user = userEvent.setup();
    const onOpenVaultPicker = vi.fn();
    function Wrapper() {
      const [text, setText] = useState("hello ");
      return (
        <AgentChatInput
          {...baseProps({ inputText: text, onInputTextChange: setText, onOpenVaultPicker })}
        />
      );
    }
    render(<Wrapper />);
    const textarea = screen.getByRole("textbox");
    await user.click(textarea);
    await user.keyboard("@");
    expect(onOpenVaultPicker).toHaveBeenCalledTimes(1);
    expect((textarea as HTMLTextAreaElement).value).toBe("hello ");
    // 語中の @（直前が空白でない）は発火しない
    await user.keyboard("user@");
    expect(onOpenVaultPicker).toHaveBeenCalledTimes(1);
    expect((textarea as HTMLTextAreaElement).value).toBe("hello user@");
  });

  it("renders selected refs as chips with a remove action", async () => {
    const user = userEvent.setup();
    const props = setup({
      pendingContextRefs: [{ kind: "vault_file", path: "a/b.md" }],
    });
    expect(screen.getByTestId("context-ref-chip")).toHaveTextContent("a/b.md");
    await user.click(screen.getByRole("button", { name: "a/b.md の参照を取り除く" }));
    expect(props.onRemoveContextRef).toHaveBeenCalledWith(0);
  });

  it("opens the picker from the plus menu", async () => {
    const user = userEvent.setup();
    const props = setup({ plusMenuOpen: true });
    await user.click(screen.getByRole("button", { name: /Vault ファイル/ }));
    expect(props.onOpenVaultPicker).toHaveBeenCalledTimes(1);
  });
});
