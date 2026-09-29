import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import CoachOverviewPage from "../CoachOverviewPage";
import GoalDetailPage from "../GoalDetailPage";
import * as coachApi from "../coachApi";
import { CoachGoalDetail } from "../types";

vi.mock("../coachApi", () => ({
  fetchCoachGoals: vi.fn(),
  createCoachGoal: vi.fn(),
  fetchCoachGoalDetail: vi.fn(),
  updateCoachGoal: vi.fn(),
  pauseCoachGoal: vi.fn(),
  resumeCoachGoal: vi.fn(),
  endCoachGoal: vi.fn(),
  createCoachFocus: vi.fn(),
  updateCoachFocus: vi.fn(),
  activateCoachFocus: vi.fn(),
  pauseCoachFocus: vi.fn(),
  createCoachReflection: vi.fn(),
  fetchCoachReflectionsByFocus: vi.fn(),
  fetchCoachReflectionDetail: vi.fn(),
  updateCoachReflection: vi.fn(),
  fetchCoachThreadEvents: vi.fn(),
}));

const mockGoals: CoachGoalDetail[] = [
  {
    goal_id: "cgoal_1",
    statement: "専門性を身につける",
    reason: "キャリア成長のため",
    status: "active",
    created_at: "2026-09-20T10:00:00Z",
    updated_at: "2026-09-20T10:00:00Z",
    active_focus: {
      focus_id: "cfoc_1",
      goal_id: "cgoal_1",
      name: "週1アウトプット",
      status: "active",
      created_at: "2026-09-20T10:00:00Z",
      updated_at: "2026-09-20T10:00:00Z",
    },
    focuses: [
      {
        focus_id: "cfoc_1",
        goal_id: "cgoal_1",
        name: "週1アウトプット",
        status: "active",
        created_at: "2026-09-20T10:00:00Z",
        updated_at: "2026-09-20T10:00:00Z",
      },
      {
        focus_id: "cfoc_2",
        goal_id: "cgoal_1",
        name: "毎日15分読書",
        status: "candidate",
        created_at: "2026-09-20T10:00:00Z",
        updated_at: "2026-09-20T10:00:00Z",
      },
    ],
  },
];

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(coachApi.fetchCoachGoals).mockResolvedValue({
    items: mockGoals,
    total: 1,
  });
  vi.mocked(coachApi.fetchCoachGoalDetail).mockResolvedValue(mockGoals[0]);
  vi.mocked(coachApi.fetchCoachReflectionsByFocus).mockResolvedValue([]);
  vi.mocked(coachApi.fetchCoachThreadEvents).mockResolvedValue({
    items: [
      {
        event_id: "cevt_1",
        goal_id: "cgoal_1",
        event_type: "goal_created",
        payload: {
          goal_statement: "専門性を身につける",
          goal_reason: "キャリア成長のため",
        },
        created_at: "2026-09-20T10:00:00Z",
      },
    ],
    total: 1,
  });
});

describe("CoachOverviewPage", () => {
  it("renders goals list and opens goal create modal", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/coach"]}>
        <Routes>
          <Route path="/coach" element={<CoachOverviewPage />} />
        </Routes>
      </MemoryRouter>
    );

    expect(
      await screen.findByText("長期目標コーチ (Long-term Coach)")
    ).toBeInTheDocument();
    expect(screen.getByText("専門性を身につける")).toBeInTheDocument();
    expect(screen.getByText("週1アウトプット")).toBeInTheDocument();

    // Open Modal
    await user.click(screen.getByRole("button", { name: "新しい Goal を作成" }));
    expect(
      screen.getByText("新しい長期目標 (Goal) を作成")
    ).toBeInTheDocument();
  });
});

describe("GoalDetailPage", () => {
  it("renders goal details, focus section, and thread timeline", async () => {
    render(
      <MemoryRouter initialEntries={["/coach/goals/cgoal_1"]}>
        <Routes>
          <Route path="/coach/goals/:goalId" element={<GoalDetailPage />} />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByRole("heading", { name: "専門性を身につける" })).toBeInTheDocument();
    expect(screen.getAllByText(/キャリア成長のため/).length).toBeGreaterThan(0);
    expect(screen.getByText("Focus 候補・選択")).toBeInTheDocument();
    expect(screen.getByText("Coach Thread（経過タイムライン）")).toBeInTheDocument();
    expect(screen.getByText("Goal を作成しました")).toBeInTheDocument();
  });

  it("opens the reflection modal with a subject focus selector", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/coach/goals/cgoal_1"]}>
        <Routes>
          <Route path="/coach/goals/:goalId" element={<GoalDetailPage />} />
        </Routes>
      </MemoryRouter>
    );

    await screen.findByText("Focus 候補・選択");
    await user.click(
      screen.getByRole("button", { name: "週次 Reflection を記録" })
    );

    const select = await screen.findByLabelText("対象 Focus:");
    expect(select).toBeInTheDocument();
    // Active and candidate focuses are both selectable as the subject.
    expect(
      screen.getByRole("option", { name: /週1アウトプット/ })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: /毎日15分読書/ })
    ).toBeInTheDocument();
    expect(coachApi.fetchCoachReflectionsByFocus).toHaveBeenCalledWith(
      "cfoc_1"
    );
  });

  it("shows the record button even without an active focus", async () => {
    const user = userEvent.setup();
    vi.mocked(coachApi.fetchCoachGoalDetail).mockResolvedValue({
      ...mockGoals[0],
      active_focus: null,
    });

    render(
      <MemoryRouter initialEntries={["/coach/goals/cgoal_1"]}>
        <Routes>
          <Route path="/coach/goals/:goalId" element={<GoalDetailPage />} />
        </Routes>
      </MemoryRouter>
    );

    await screen.findByText("Focus 候補・選択");
    await user.click(
      screen.getByRole("button", { name: "週次 Reflection を記録" })
    );

    // The modal falls back to the first focus as the subject.
    expect(await screen.findByLabelText("対象 Focus:")).toBeInTheDocument();
    expect(coachApi.fetchCoachReflectionsByFocus).toHaveBeenCalledWith(
      "cfoc_1"
    );
  });

  it("handles manual focus activation", async () => {
    const user = userEvent.setup();
    vi.mocked(coachApi.activateCoachFocus).mockResolvedValue({
      focus_id: "cfoc_2",
      goal_id: "cgoal_1",
      name: "毎日15分読書",
      status: "active",
      created_at: "2026-09-20T10:00:00Z",
      updated_at: "2026-09-20T10:00:00Z",
    });

    render(
      <MemoryRouter initialEntries={["/coach/goals/cgoal_1"]}>
        <Routes>
          <Route path="/coach/goals/:goalId" element={<GoalDetailPage />} />
        </Routes>
      </MemoryRouter>
    );

    await screen.findByText("Focus 候補・選択");
    const activateBtn = screen.getByRole("button", { name: "選択 (Active)" });
    await user.click(activateBtn);

    expect(coachApi.activateCoachFocus).toHaveBeenCalledWith("cfoc_2");
  });
});
