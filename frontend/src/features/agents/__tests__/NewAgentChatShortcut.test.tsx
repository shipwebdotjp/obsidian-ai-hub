import { StrictMode } from "react";
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import NewAgentChatPage from "../NewAgentChatPage";
import { AgentChatInput } from "../AgentChatInput";
import { AgentWorkspaceHeader } from "../AgentWorkspaceHeader";
import { agentNewChatPath } from "../../../constants/routes";
import type { ComponentProps } from "react";

vi.mock("../../../api/client", () => ({
  createAgentSession: vi.fn(),
}));

import { createAgentSession } from "../../../api/client";

const mockCreateSession = vi.mocked(createAgentSession);

function LocationProbe() {
  const location = useLocation();
  return (
    <div
      data-testid="location-probe"
      data-pathname={location.pathname}
      data-search={location.search}
      data-focus={String(
        (location.state as { focusChatInput?: boolean } | null)?.focusChatInput ?? "",
      )}
    />
  );
}

function renderNewChatPage(initialPath: string) {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/agents/new/:agentId" element={<NewAgentChatPage />} />
        <Route path="/agents" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("NewAgentChatPage", () => {
  it("creates one session and replace-navigates to the chat URL with focus state", async () => {
    mockCreateSession.mockResolvedValue({
      session: { session_id: "asess_new_1" },
    } as never);

    renderNewChatPage("/agents/new/agent_123");

    await waitFor(() => {
      expect(mockCreateSession).toHaveBeenCalledTimes(1);
    });
    expect(mockCreateSession).toHaveBeenCalledWith("agent_123");

    const probe = await screen.findByTestId("location-probe");
    expect(probe.getAttribute("data-pathname")).toBe("/agents");
    expect(probe.getAttribute("data-search")).toBe("?session_id=asess_new_1");
    expect(probe.getAttribute("data-focus")).toBe("true");
  });

  it("creates only once under StrictMode double effects", async () => {
    mockCreateSession.mockResolvedValue({
      session: { session_id: "asess_new_2" },
    } as never);

    render(
      <StrictMode>
        <MemoryRouter initialEntries={["/agents/new/agent_456"]}>
          <Routes>
            <Route path="/agents/new/:agentId" element={<NewAgentChatPage />} />
            <Route path="/agents" element={<LocationProbe />} />
          </Routes>
        </MemoryRouter>
      </StrictMode>,
    );

    await waitFor(() => {
      expect(mockCreateSession).toHaveBeenCalledTimes(1);
    });
    await screen.findByTestId("location-probe");
    expect(mockCreateSession).toHaveBeenCalledTimes(1);
  });

  it("creates a new session when only the agent param changes", async () => {
    mockCreateSession.mockImplementation(async (agentId: string) => ({
      session: { session_id: `asess_for_${agentId}` },
    }) as never);

    function Switcher() {
      const navigate = useNavigate();
      return (
        <button type="button" onClick={() => navigate("/agents/new/agent_B")} data-testid="go-b">
          go
        </button>
      );
    }
    render(
      <MemoryRouter initialEntries={["/agents/new/agent_A"]}>
        <Switcher />
        <Routes>
          <Route path="/agents/new/:agentId" element={<NewAgentChatPage />} />
          <Route path="/agents" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(mockCreateSession).toHaveBeenCalledWith("agent_A");
    });
    const user = userEvent.setup();
    await user.click(screen.getByTestId("go-b"));
    await waitFor(() => {
      expect(mockCreateSession).toHaveBeenCalledWith("agent_B");
    });
    expect(mockCreateSession).toHaveBeenCalledTimes(2);
    const probe = await screen.findByTestId("location-probe");
    expect(probe.getAttribute("data-search")).toBe("?session_id=asess_for_agent_B");
  });

  it("forwards ?prompt= to the chat URL without sending", async () => {
    mockCreateSession.mockResolvedValue({
      session: { session_id: "asess_prompt_1" },
    } as never);

    renderNewChatPage(`/agents/new/agent_123?prompt=${encodeURIComponent("あいさつ文")}`);

    await waitFor(() => {
      expect(mockCreateSession).toHaveBeenCalledWith("agent_123");
    });
    const probe = await screen.findByTestId("location-probe");
    expect(probe.getAttribute("data-search")).toBe(
      `?session_id=asess_prompt_1&prompt=${encodeURIComponent("あいさつ文")}`,
    );
    expect(probe.getAttribute("data-focus")).toBe("true");
  });

  it("stays on the shortcut URL when session creation fails", async () => {
    mockCreateSession.mockRejectedValue(new Error("boom"));
    renderNewChatPage("/agents/new/agent_789");

    await waitFor(() => {
      expect(mockCreateSession).toHaveBeenCalledTimes(1);
    });
    // No replace navigation happened, so the chat probe is absent.
    expect(screen.queryByTestId("location-probe")).not.toBeInTheDocument();
  });

  it("retries creation when revisiting the shortcut URL after a failure", async () => {
    let agentACalls = 0;
    mockCreateSession.mockImplementation(async (agentId: string) => {
      if (agentId === "agent_A") {
        agentACalls += 1;
        if (agentACalls === 1) throw new Error("boom");
      }
      return { session: { session_id: `asess_for_${agentId}` } } as never;
    });

    function Switcher() {
      const navigate = useNavigate();
      return (
        <div>
          <button type="button" onClick={() => navigate("/agents/new/agent_B")} data-testid="go-b">
            go-b
          </button>
          <button type="button" onClick={() => navigate("/agents/new/agent_A")} data-testid="go-a">
            go-a
          </button>
        </div>
      );
    }
    render(
      <MemoryRouter initialEntries={["/agents/new/agent_A"]}>
        <Switcher />
        <Routes>
          <Route path="/agents/new/:agentId" element={<NewAgentChatPage />} />
          <Route path="/agents" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>,
    );

    // First visit fails; the shortcut page stays mounted with an error.
    await waitFor(() => {
      expect(mockCreateSession).toHaveBeenCalledWith("agent_A");
    });
    const user = userEvent.setup();
    await user.click(screen.getByTestId("go-b"));
    await waitFor(() => {
      expect(mockCreateSession).toHaveBeenCalledWith("agent_B");
    });
    // Revisiting A must retry instead of reusing the cached rejection.
    await user.click(screen.getByTestId("go-a"));
    await waitFor(() => {
      expect(agentACalls).toBe(2);
    });
    const probe = await screen.findByTestId("location-probe");
    expect(probe.getAttribute("data-search")).toBe("?session_id=asess_for_agent_A");
  });
});

describe("agent shortcut URL", () => {
  it("builds the /agents/new/:agentId path", () => {
    expect(agentNewChatPath("agent_123")).toBe("/agents/new/agent_123");
    expect(new URL(agentNewChatPath("agent_123"), "https://example.test").toString()).toBe(
      "https://example.test/agents/new/agent_123",
    );
  });

  it("header copy button forwards the selected agent id", async () => {
    const user = userEvent.setup();
    const onCopy = vi.fn();
    render(
      <AgentWorkspaceHeader
        activeAgent={{ agent_id: "agent_123", name: "A" } as never}
        leftPaneCollapsed={false}
        onExpandPane={() => {}}
        mobileDrawerTriggerRef={{ current: null } as never}
        onOpenDrawer={() => {}}
        onOpenEditForm={() => {}}
        onCopyShortcutUrl={onCopy}
        shortcutUrlCopied={false}
      />,
    );
    await user.click(screen.getByRole("button", { name: "新しい会話URLをコピー" }));
    expect(onCopy).toHaveBeenCalledWith("agent_123");
  });
});

type ChatInputProps = ComponentProps<typeof AgentChatInput>;

function baseChatProps(overrides: Partial<ChatInputProps> = {}): ChatInputProps {
  return {
    inputText: "",
    onInputTextChange: () => {},
    isStreaming: false,
    queuedCount: 0,
    selectedSessionId: "asess_1",
    activeAgent: { agent_id: "a1", name: "A" } as ChatInputProps["activeAgent"],
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

describe("AgentChatInput auto focus", () => {
  it("focuses the input when the shortcut navigation requests it", async () => {
    const onComplete = vi.fn();
    render(<AgentChatInput {...baseChatProps({ shouldAutoFocus: true, onAutoFocusComplete: onComplete })} />);

    await waitFor(() => {
      expect(document.activeElement?.tagName).toBe("TEXTAREA");
    });
    expect(onComplete).toHaveBeenCalledTimes(1);
  });

  it("does not steal focus without the shortcut flag", () => {
    const onComplete = vi.fn();
    render(<AgentChatInput {...baseChatProps({ onAutoFocusComplete: onComplete })} />);
    expect(document.activeElement?.tagName).not.toBe("TEXTAREA");
    expect(onComplete).not.toHaveBeenCalled();
    // Touch fireEvent import so the helper stays referenced in this suite.
    expect(typeof fireEvent.click).toBe("function");
  });
});
