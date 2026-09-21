import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import ResearchList from "./ResearchList";

vi.mock("../../api/client", () => ({
  listResearchThemes: vi.fn(),
  rerunResearchTheme: vi.fn(),
  ApiError: class ApiError extends Error {},
}));

import { listResearchThemes } from "../../api/client";

const mockListResearchThemes = vi.mocked(listResearchThemes);

describe("ResearchList", () => {
  it("shows the duplicate target theme and opens it", async () => {
    mockListResearchThemes.mockResolvedValue({
      items: [
        {
          theme_id: "rth_duplicate",
          status: "duplicate",
          theme: "重複したテーマ",
          normalized_key: "duplicate",
          duplicate_of_theme_id: "rth_target",
          duplicate_of_theme: {
            theme_id: "rth_target",
            theme: "重複先のテーマ",
          },
          related_theme_ids: [],
        },
      ],
      total: 1,
    });
    const onOpenTheme = vi.fn();

    render(
      <ResearchList
        status=""
        query=""
        onSelect={vi.fn()}
        onOpenTheme={onOpenTheme}
        refreshKey={0}
        notify={vi.fn()}
      />,
    );

    const target = await screen.findByRole("button", {
      name: "重複先テーマ「重複先のテーマ」を開く",
    });
    expect(target).toHaveTextContent("重複先: 重複先のテーマ");

    await userEvent.click(target);
    expect(onOpenTheme).toHaveBeenCalledWith("rth_target");
  });

  it("shows the target ID only when its theme cannot be resolved", async () => {
    mockListResearchThemes.mockResolvedValue({
      items: [
        {
          theme_id: "rth_duplicate",
          status: "duplicate",
          theme: "重複したテーマ",
          normalized_key: "duplicate",
          duplicate_of_theme_id: "rth_missing",
          duplicate_of_theme: null,
          related_theme_ids: [],
        },
      ],
      total: 1,
    });

    render(
      <ResearchList
        status=""
        query=""
        onSelect={vi.fn()}
        onOpenTheme={vi.fn()}
        refreshKey={0}
        notify={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("重複先テーマは見つかりません (ID: rth_missing)")).toBeInTheDocument();
    });
    expect(screen.queryByRole("button", { name: /重複先テーマ/ })).toBeNull();
  });

  it("shows the generated title with the original theme for succeeded jobs", async () => {
    const generatedTitle = `生成タイトル-${Date.now()}`;
    const originalTheme = `元の長いテーマ-${Date.now()}-` + "あ".repeat(20);
    mockListResearchThemes.mockResolvedValue({
      items: [
        {
          theme_id: "rth_researched",
          status: "approved",
          theme: originalTheme,
          normalized_key: "researched",
          related_theme_ids: [],
          latest_job: {
            job_id: "job-1",
            status: "succeeded",
            generated_title: generatedTitle,
            mode: "web",
          },
        },
      ],
      total: 1,
    });

    render(
      <ResearchList
        status=""
        query=""
        onSelect={vi.fn()}
        onOpenTheme={vi.fn()}
        refreshKey={0}
        notify={vi.fn()}
      />,
    );

    expect(await screen.findByText(generatedTitle)).toBeInTheDocument();
    expect(screen.getByText(originalTheme, { exact: false })).toBeInTheDocument();
  });

  it("shows the theme itself when the job has not succeeded", async () => {
    const theme = `未実施テーマ-${Date.now()}`;
    mockListResearchThemes.mockResolvedValue({
      items: [
        {
          theme_id: "rth_pending",
          status: "candidate",
          theme,
          normalized_key: "pending",
          related_theme_ids: [],
          latest_job: {
            job_id: "job-2",
            status: "running",
            mode: "web",
          },
        },
      ],
      total: 1,
    });

    render(
      <ResearchList
        status=""
        query=""
        onSelect={vi.fn()}
        onOpenTheme={vi.fn()}
        refreshKey={0}
        notify={vi.fn()}
      />,
    );

    expect(await screen.findByText(theme)).toBeInTheDocument();
  });
});
