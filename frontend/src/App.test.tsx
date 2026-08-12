import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import App from "./App";
import { health, ApiError, listHitlRuns } from "./api/client";

// Mock the API client
vi.mock("./api/client", () => ({
  health: vi.fn(),
  listHitlRuns: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

// Mock the individual feature pages to keep App routing tests fast and isolated
vi.mock("./features/memories/MemoryPage", () => ({ default: () => <div data-testid="page-memories">MemoryPage</div> }));
vi.mock("./features/research/ResearchPage", () => ({ default: () => <div data-testid="page-research">ResearchPage</div> }));
vi.mock("./features/hitl/HitlPage", () => ({ default: () => <div data-testid="page-hitl">HitlPage</div> }));
vi.mock("./features/vault-search/VaultSearchPage", () => ({ default: () => <div data-testid="page-vault-search">VaultSearchPage</div> }));
vi.mock("./features/summary-dashboard/SummaryDashboardPage", () => ({ default: () => <div data-testid="page-summary-dashboard">SummaryDashboardPage</div> }));
vi.mock("./features/people/PeoplePage", () => ({ default: () => <div data-testid="page-people">PeoplePage</div> }));
vi.mock("./features/projects/ProjectsPage", () => ({ default: () => <div data-testid="page-projects">ProjectsPage</div> }));
vi.mock("./features/tasks/TaskPage", () => ({ default: () => <div data-testid="page-tasks">TaskPage</div> }));
vi.mock("./features/execution-logs/ExecutionLogPage", () => ({ default: () => <div data-testid="page-execution-logs">ExecutionLogPage</div> }));

// Mock TokenPrompt to avoid token input rendering complexities
vi.mock("./components/TokenPrompt", () => ({
  default: ({ onAuthenticated }: { onAuthenticated: () => void }) => (
    <div data-testid="token-prompt">
      TokenPrompt
      <button onClick={onAuthenticated}>Authenticate</button>
    </div>
  ),
}));

const mockHealth = vi.mocked(health);
const mockListHitlRuns = vi.mocked(listHitlRuns);

beforeEach(() => {
  vi.clearAllMocks();
  mockListHitlRuns.mockResolvedValue({ items: [], total: 0 });
});

describe("App", () => {
  it("renders 起動中… initially", () => {
    // Return a promise that does not resolve immediately
    mockHealth.mockReturnValue(new Promise(() => {}));
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>
    );
    expect(screen.getByText("起動中…")).toBeInTheDocument();
  });

  it("renders sidebar and page content when health check succeeds and auth is not required", async () => {
    mockHealth.mockResolvedValue({ status: "ok", auth_required: false });
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByTestId("page-memories")).toBeInTheDocument();
    });
    expect(screen.queryByTestId("token-prompt")).not.toBeInTheDocument();
  });

  it("renders TokenPrompt when health check succeeds but auth is required", async () => {
    mockHealth.mockResolvedValue({ status: "ok", auth_required: true });
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByTestId("token-prompt")).toBeInTheDocument();
    });

    // Authenticate should switch view to main app
    const authButton = screen.getByRole("button", { name: "Authenticate" });
    await userEvent.click(authButton);

    expect(screen.getByTestId("page-memories")).toBeInTheDocument();
  });

  it("renders TokenPrompt when health check fails with 401", async () => {
    mockHealth.mockRejectedValue(new ApiError(401, "Unauthorized"));
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByTestId("token-prompt")).toBeInTheDocument();
    });
  });

  it("renders Connection Error screen when health check fails with non-401 error", async () => {
    mockHealth.mockRejectedValue(new ApiError(500, "Internal Server Error"));
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("接続エラー")).toBeInTheDocument();
    });
    expect(screen.getByText("Internal Server Error")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "再読み込み" })).toBeInTheDocument();
  });

  it("redirects root path / to /memories", async () => {
    mockHealth.mockResolvedValue({ status: "ok", auth_required: false });
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByTestId("page-memories")).toBeInTheDocument();
    });
  });

  it("manages mobile navigation menu (open/close and Esc key)", async () => {
    mockHealth.mockResolvedValue({ status: "ok", auth_required: false });
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByTestId("page-memories")).toBeInTheDocument();
    });

    // Initially menu is closed: only the sidebar close button is in DOM
    expect(screen.getAllByRole("button", { name: "メニューを閉じる" })).toHaveLength(1);

    const openMenuBtn = screen.getByRole("button", { name: "メニューを開く" });
    expect(openMenuBtn).toBeInTheDocument();

    // Click to open menu
    await userEvent.click(openMenuBtn);

    // Verify it's open: both overlay and sidebar buttons are in DOM
    expect(screen.getAllByRole("button", { name: "メニューを閉じる" })).toHaveLength(2);

    // Press Esc key to close
    fireEvent.keyDown(window, { key: "Escape", code: "Escape" });
    await waitFor(() => {
      expect(screen.getAllByRole("button", { name: "メニューを閉じる" })).toHaveLength(1);
    });

    // Open again to test click to close
    await userEvent.click(openMenuBtn);
    expect(screen.getAllByRole("button", { name: "メニューを閉じる" })).toHaveLength(2);

    const closeMenuBtnAgain = screen.getAllByRole("button", { name: "メニューを閉じる" })[0];
    await userEvent.click(closeMenuBtnAgain);
    expect(screen.getAllByRole("button", { name: "メニューを閉じる" })).toHaveLength(1);
  });

  it("navigates to different sidebar routes correctly", async () => {
    mockHealth.mockResolvedValue({ status: "ok", auth_required: false });
    render(
      <MemoryRouter initialEntries={["/memories"]}>
        <App />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByTestId("page-memories")).toBeInTheDocument();
    });

    // Sidebar should be loaded. Let's find all sidebar nav links and click them.
    const links = [
      { name: "メモリ", testId: "page-memories" },
      { name: "リサーチ", testId: "page-research" },
      { name: "確認待ち", testId: "page-hitl" },
      { name: "Vault 検索", testId: "page-vault-search" },
      { name: "サマリダッシュボード", testId: "page-summary-dashboard" },
      { name: "人物管理", testId: "page-people" },
      { name: "プロジェクト管理", testId: "page-projects" },
      { name: "タスク管理", testId: "page-tasks" },
      { name: "実行ログ", testId: "page-execution-logs" },
    ];

    for (const link of links) {
      const element = screen.getByRole("link", { name: link.name });
      await userEvent.click(element);
      await waitFor(() => {
        expect(screen.getByTestId(link.testId)).toBeInTheDocument();
      });
    }
  });

  it("shows a pending count badge on the 確認待ち link when pending runs exist", async () => {
    mockHealth.mockResolvedValue({ status: "ok", auth_required: false });
    mockListHitlRuns.mockResolvedValue({ items: [], total: 3 });
    render(
      <MemoryRouter initialEntries={["/memories"]}>
        <App />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByTestId("page-memories")).toBeInTheDocument();
    });
    const badge = await screen.findByTestId("hitl-pending-badge");
    expect(badge).toHaveTextContent("3");
  });

  it("hides the pending count badge when there are no pending runs", async () => {
    mockHealth.mockResolvedValue({ status: "ok", auth_required: false });
    mockListHitlRuns.mockResolvedValue({ items: [], total: 0 });
    render(
      <MemoryRouter initialEntries={["/memories"]}>
        <App />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByTestId("page-memories")).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(mockListHitlRuns).toHaveBeenCalled();
    });
    expect(screen.queryByTestId("hitl-pending-badge")).not.toBeInTheDocument();
  });
});
