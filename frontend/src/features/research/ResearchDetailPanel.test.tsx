import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import ResearchDetailPanel from "./ResearchDetailPanel";

vi.mock("../../api/client", () => ({
  getResearchTheme: vi.fn(),
  reviewResearchTheme: vi.fn(),
  rerunResearchTheme: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

import { getResearchTheme } from "../../api/client";
const mockGetResearchTheme = vi.mocked(getResearchTheme);

const longMarkdown = `# Title

This is a paragraph with **bold** and *italic*.

| Col1 | Col2 |
|------|------|
| A    | B    |

\`\`\`python
print("hello")
\`\`\`

> A quote block

[A link](https://example.com)
`
  + "x".repeat(15000);

describe("ResearchDetailPanel", () => {
  it("renders succeeded job markdown with full content (no truncation)", async () => {
    mockGetResearchTheme.mockResolvedValue({
      theme_id: "test-1",
      status: "approved",
      theme: "AI safety",
      normalized_key: "ai-safety",
      related_theme_ids: [],
      created_at: "2026-01-01",
      latest_job: {
        job_id: "job-1",
        status: "succeeded",
        markdown: longMarkdown,
      },
    });

    render(
      <ResearchDetailPanel
        themeId="test-1"
        onChanged={vi.fn()}
        onOpenTheme={vi.fn()}
        notify={vi.fn()}
      />
    );

    await waitFor(() => {
      expect(screen.getByText("Title")).toBeInTheDocument();
    });

    expect(screen.getByRole("heading", { name: "Title", level: 1 })).toBeInTheDocument();
    expect(screen.getByText("bold")).toBeInTheDocument();
    expect(screen.getByText("italic")).toBeInTheDocument();
    expect(screen.getByText("Col1")).toBeInTheDocument();
    expect(screen.getByText("A")).toBeInTheDocument();
    expect(screen.getByText('print("hello")')).toBeInTheDocument();
    expect(screen.getByText("A quote block")).toBeInTheDocument();

    const link = screen.getByRole("link", { name: "A link" });
    expect(link).toHaveAttribute("href", "https://example.com");
    expect(link).toHaveAttribute("target", "_blank");

    expect(screen.queryByText("...(truncated)")).toBeNull();
  });

  it("does not render markdown when job is not succeeded", async () => {
    mockGetResearchTheme.mockResolvedValue({
      theme_id: "test-2",
      status: "candidate",
      theme: "test",
      normalized_key: "test",
      related_theme_ids: [],
      latest_job: {
        job_id: "job-2",
        status: "failed",
        markdown: "# Should not show",
      },
    });

    render(
      <ResearchDetailPanel
        themeId="test-2"
        onChanged={vi.fn()}
        onOpenTheme={vi.fn()}
        notify={vi.fn()}
      />
    );

    await waitFor(() => {
      expect(screen.getByText("test")).toBeInTheDocument();
    });

    expect(screen.queryByText("Should not show")).toBeNull();
  });

  it("links to the HITL page with the run_id query param for pending auto-suggestions", async () => {
    mockGetResearchTheme.mockResolvedValue({
      theme_id: "test-3",
      status: "candidate",
      origin: "auto_suggestion",
      hitl_run_id: "hrun-abc",
      theme: "test",
      normalized_key: "test",
      related_theme_ids: [],
      latest_job: {
        job_id: "job-3",
        status: "pending",
      },
    });

    render(
      <MemoryRouter>
        <ResearchDetailPanel
          themeId="test-3"
          onChanged={vi.fn()}
          onOpenTheme={vi.fn()}
          notify={vi.fn()}
        />
      </MemoryRouter>
    );

    const link = await screen.findByRole("link", { name: "HITLで回答" });
    expect(link).toHaveAttribute("href", "/hitl?run_id=hrun-abc");
  });

  it("shows the duplicate target theme and opens it", async () => {
    mockGetResearchTheme.mockResolvedValue({
      theme_id: "test-duplicate",
      status: "duplicate",
      theme: "重複したテーマ",
      normalized_key: "duplicate",
      duplicate_of_theme_id: "test-target",
      duplicate_of_theme: {
        theme_id: "test-target",
        theme: "重複先のテーマ",
      },
      related_theme_ids: [],
    });
    const onOpenTheme = vi.fn();

    render(
      <ResearchDetailPanel
        themeId="test-duplicate"
        onChanged={vi.fn()}
        onOpenTheme={onOpenTheme}
        notify={vi.fn()}
      />
    );

    const target = await screen.findByRole("button", {
      name: "重複先テーマ「重複先のテーマ」を開く",
    });
    await userEvent.click(target);

    expect(onOpenTheme).toHaveBeenCalledWith("test-target");
  });
});
