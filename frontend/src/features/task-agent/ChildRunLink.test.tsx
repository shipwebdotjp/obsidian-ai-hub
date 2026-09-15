import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import {
  ChildRunLink,
  HitlRunLink,
  childRunRefFromPayload,
  hitlRunIdFromPayload,
} from "./ChildRunLink";

function renderWithRouter(ui: React.ReactNode) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

describe("ChildRunLink", () => {
  it("links an agent child run to the existing agents session route", () => {
    renderWithRouter(
      <ChildRunLink
        childKind="agent"
        childRunId="arun_123"
        sessionId="asess_456"
        agentId="agent_1"
      />,
    );
    const link = screen.getByTestId("child-run-link");
    expect(link).toHaveAttribute("href", "/agents?session_id=asess_456");
    expect(link).toHaveTextContent("Agent run arun_123");
    expect(screen.getByText(/agent: agent_1/)).toBeInTheDocument();
  });

  it("links a coding child run to the existing coding session route", () => {
    renderWithRouter(
      <ChildRunLink
        childKind="coding"
        childRunId="crun_789"
        sessionId="cses_111"
        projectId={3}
        backend="opencode"
      />,
    );
    const link = screen.getByTestId("child-run-link");
    expect(link).toHaveAttribute("href", "/coding?session_id=cses_111");
    expect(link).toHaveTextContent("Coding run crun_789");
    expect(screen.getByText(/project: 3\/opencode/)).toBeInTheDocument();
  });

  it("renders plain text when the session is unknown (no guessed URL)", () => {
    renderWithRouter(
      <ChildRunLink childKind="agent" childRunId="arun_old" sessionId={null} />,
    );
    expect(screen.queryByTestId("child-run-link")).not.toBeInTheDocument();
    const text = screen.getByTestId("child-run-text");
    expect(text).toHaveTextContent("Agent run arun_old");
    expect(text).toHaveTextContent("セッション情報なし");
  });

  it("renders unknown kinds as plain text", () => {
    renderWithRouter(
      <ChildRunLink childKind="mystery" childRunId="xrun_1" sessionId="s1" />,
    );
    expect(screen.queryByTestId("child-run-link")).not.toBeInTheDocument();
    expect(screen.getByTestId("child-run-text")).toHaveTextContent(
      "mystery run xrun_1",
    );
  });

  it("HitlRunLink points at the existing hitl run route", () => {
    renderWithRouter(<HitlRunLink runId="hrun_1" />);
    const link = screen.getByTestId("hitl-run-link");
    expect(link).toHaveAttribute("href", "/hitl?run_id=hrun_1");
    expect(link).toHaveTextContent("hrun_1");
  });

  it("extracts refs from event payloads", () => {
    expect(
      childRunRefFromPayload({
        child_kind: "agent",
        child_run_id: "arun_1",
        session_id: "asess_1",
        agent_id: "agent_9",
      }),
    ).toMatchObject({
      childKind: "agent",
      childRunId: "arun_1",
      sessionId: "asess_1",
      agentId: "agent_9",
    });
    expect(childRunRefFromPayload({})).toBeNull();
    expect(childRunRefFromPayload(null)).toBeNull();
    expect(hitlRunIdFromPayload({ hitl_run_id: "hrun_9" })).toBe("hrun_9");
    expect(hitlRunIdFromPayload({})).toBeNull();
  });
});
