import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ProjectField from "./ProjectField";
import { resetWidgetCaches } from "./widgetData";

vi.mock("../../api/client", () => ({
  apiGet: vi.fn(),
  listAgents: vi.fn(),
  listPeople: vi.fn(),
}));

import { apiGet } from "../../api/client";

describe("ProjectField", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetWidgetCaches();
    vi.mocked(apiGet).mockResolvedValue([
      { project_id: 7, display_name: "Alpha", normalized_name: "alpha" },
      { project_id: 9, display_name: "Beta", normalized_name: "beta" },
    ]);
  });

  it("selects a numeric project id", async () => {
    const onChange = vi.fn();
    render(
      <ProjectField value={undefined} onChange={onChange} testIdPrefix="p" />,
    );
    await userEvent.click(screen.getByTestId("p-project-input"));
    await waitFor(() =>
      expect(screen.getByText("Alpha (#7)")).toBeInTheDocument(),
    );
    await userEvent.click(screen.getByText("Beta (#9)"));
    expect(onChange).toHaveBeenCalledWith(9);
  });

  it("filters the project list", async () => {
    render(
      <ProjectField value={undefined} onChange={vi.fn()} testIdPrefix="p2" />,
    );
    await userEvent.click(screen.getByTestId("p2-project-input"));
    await waitFor(() =>
      expect(screen.getByText("Alpha (#7)")).toBeInTheDocument(),
    );
    await userEvent.type(screen.getByTestId("p2-project-input"), "beta");
    expect(screen.queryByText("Alpha (#7)")).not.toBeInTheDocument();
    expect(screen.getByText("Beta (#9)")).toBeInTheDocument();
  });
});
