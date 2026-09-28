import { describe, expect, it } from "vitest";
import {
  coachGoalDetailPath,
  taskAgentDetailPath,
  workflowDetailPath,
  workflowEditPath,
  workflowRunPath,
} from "./routes";
import { APP_TITLE, resolvePageTitle } from "./pageTitles";

describe("resolvePageTitle", () => {
  it("returns the bare application title for unknown paths", () => {
    expect(resolvePageTitle("/")).toBe(APP_TITLE);
    expect(resolvePageTitle("/no-such-screen")).toBe(APP_TITLE);
  });

  it("resolves every static route to its own title", () => {
    const staticPaths = [
      "/memories",
      "/research",
      "/agents",
      "/coding",
      "/hitl",
      "/vault-search",
      "/summary-dashboard",
      "/healthcare",
      "/people",
      "/projects",
      "/coach",
      "/jobs",
      "/task-agent",
      "/workflows",
      "/media",
      "/execution-logs",
      "/execution-logs/logs",
      "/execution-logs/job-states",
      "/planner",
      "/settings",
    ];
    const titles = staticPaths.map(resolvePageTitle);
    for (const title of titles) {
      expect(title.startsWith(`${APP_TITLE} `)).toBe(true);
      expect(title.length).toBeGreaterThan(APP_TITLE.length + 1);
    }
    // Each static route maps to a distinct title entry.
    expect(new Set(titles).size).toBe(staticPaths.length);
  });

  it("resolves dynamic routes without falling back to the bare title", () => {
    const dynamicPaths = [
      coachGoalDetailPath("goal-1"),
      taskAgentDetailPath("task-1"),
      "/task-agent/capabilities",
      workflowDetailPath("wf-1"),
      workflowEditPath("rev-1"),
      workflowRunPath("run-1"),
    ];
    for (const path of dynamicPaths) {
      expect(resolvePageTitle(path)).not.toBe(APP_TITLE);
    }
    // /task-agent/capabilities must win over the /task-agent/:taskId pattern.
    expect(resolvePageTitle("/task-agent/capabilities")).not.toBe(
      resolvePageTitle(taskAgentDetailPath("some-task-id")),
    );
  });
});
