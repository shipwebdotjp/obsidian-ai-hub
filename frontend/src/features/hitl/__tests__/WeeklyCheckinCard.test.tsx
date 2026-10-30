import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import WeeklyCheckinCard, { type CheckinQuestion } from "../WeeklyCheckinCard";

function makeQuestions(overrides: Partial<CheckinQuestion>[] = []): CheckinQuestion[] {
  const base: CheckinQuestion[] = [
    { question_key: "checkin_note", status: "pending", prompt: "今週はどうでしたか？" },
    { question_key: "checkin_next_step", status: "pending", prompt: "来週試したいこと" },
    {
      question_key: "checkin_decision",
      status: "pending",
      prompt: "来週はどうしますか？",
      choices: [
        { value: "continue", label: "続ける" },
        { value: "narrow", label: "小さくする" },
        { value: "change", label: "別の Focus へ" },
        { value: "pause", label: "休む" },
      ],
    },
    {
      question_key: "checkin_target_focus",
      status: "pending",
      prompt: "切替先",
      choices: [
        { value: "cfoc_aaa", label: "Focus A" },
        { value: "cfoc_bbb", label: "Focus B" },
      ],
    },
  ];
  return base.map((q, i) => ({ ...q, ...(overrides[i] ?? {}) }));
}

describe("WeeklyCheckinCard", () => {
  it("renders the note prompt, optional next step, and four decision options", () => {
    render(
      <WeeklyCheckinCard
        runId="coach_checkin_2026-W44"
        questions={makeQuestions()}
        onSubmitAnswer={vi.fn()}
        onSubmitted={vi.fn()}
      />
    );
    expect(screen.getByText("今週はどうでしたか？")).toBeTruthy();
    expect(screen.getByLabelText("来週試したいこと")).toBeTruthy();
    for (const label of ["続ける", "小さくする", "別の Focus へ", "休む"]) {
      expect(screen.getByRole("button", { name: new RegExp(label) })).toBeTruthy();
    }
  });

  it("requires the note before submitting", async () => {
    const user = userEvent.setup();
    render(
      <WeeklyCheckinCard
        runId="r1"
        questions={makeQuestions()}
        onSubmitAnswer={vi.fn()}
        onSubmitted={vi.fn()}
      />
    );
    await user.click(screen.getByRole("button", { name: "回答を送信" }));
    expect(await screen.findByText("今週の振り返りを入力してください。")).toBeTruthy();
  });

  it("requires a decision after the note is filled", async () => {
    const user = userEvent.setup();
    const onSubmitAnswer = vi.fn().mockResolvedValue(undefined);
    render(
      <WeeklyCheckinCard
        runId="r1"
        questions={makeQuestions()}
        onSubmitAnswer={onSubmitAnswer}
        onSubmitted={vi.fn()}
      />
    );
    await user.type(screen.getByLabelText("今週の振り返り"), "声をかけられた");
    await user.click(screen.getByRole("button", { name: "回答を送信" }));
    expect(await screen.findByText("来週の扱いを選んでください。")).toBeTruthy();
    expect(onSubmitAnswer).not.toHaveBeenCalled();
  });

  it("submits optional first and required decision last, in order", async () => {
    const user = userEvent.setup();
    const onSubmitAnswer = vi.fn().mockResolvedValue(undefined);
    const onSubmitted = vi.fn().mockResolvedValue(undefined);
    render(
      <WeeklyCheckinCard
        runId="r1"
        questions={makeQuestions()}
        onSubmitAnswer={onSubmitAnswer}
        onSubmitted={onSubmitted}
      />
    );
    await user.type(screen.getByLabelText("今週の振り返り"), "声をかけられた");
    await user.type(screen.getByLabelText("来週試したいこと"), "来週も続ける");
    await user.click(screen.getByRole("button", { name: /続ける/ }));
    await user.click(screen.getByRole("button", { name: "回答を送信" }));

    await waitFor(() => expect(onSubmitted).toHaveBeenCalled());
    expect(onSubmitAnswer.mock.calls.map((c) => c[0])).toEqual([
      "checkin_next_step",
      "checkin_note",
      "checkin_decision",
    ]);
    expect(onSubmitAnswer.mock.calls[2][1]).toBe("continue");
  });

  it("requires next step text when narrowing", async () => {
    const user = userEvent.setup();
    render(
      <WeeklyCheckinCard
        runId="r1"
        questions={makeQuestions()}
        onSubmitAnswer={vi.fn()}
        onSubmitted={vi.fn()}
      />
    );
    await user.type(screen.getByLabelText("今週の振り返り"), "忙しかった");
    await user.click(screen.getByRole("button", { name: /小さくする/ }));
    await user.click(screen.getByRole("button", { name: "回答を送信" }));
    expect(await screen.findByText(/「小さくする」を選んだ場合は/)).toBeTruthy();
  });

  it("shows the focus selector for change and submits the target between optionals and note", async () => {
    const user = userEvent.setup();
    const onSubmitAnswer = vi.fn().mockResolvedValue(undefined);
    const onSubmitted = vi.fn().mockResolvedValue(undefined);
    render(
      <WeeklyCheckinCard
        runId="r1"
        questions={makeQuestions()}
        onSubmitAnswer={onSubmitAnswer}
        onSubmitted={onSubmitted}
      />
    );
    await user.type(screen.getByLabelText("今週の振り返り"), "方向転換したい");
    await user.click(screen.getByRole("button", { name: /別の Focus へ/ }));
    const select = await screen.findByLabelText("切り替える Focus");
    await user.selectOptions(select, "cfoc_bbb");
    await user.click(screen.getByRole("button", { name: "回答を送信" }));

    await waitFor(() => expect(onSubmitted).toHaveBeenCalled());
    expect(onSubmitAnswer.mock.calls.map((c) => c[0])).toEqual([
      "checkin_target_focus",
      "checkin_note",
      "checkin_decision",
    ]);
    expect(onSubmitAnswer.mock.calls[0][1]).toBe("cfoc_bbb");
  });

  it("blocks change when there is no switchable focus", async () => {
    const user = userEvent.setup();
    const questions = makeQuestions();
    questions[3] = { ...questions[3], choices: [] };
    render(
      <WeeklyCheckinCard
        runId="r1"
        questions={questions}
        onSubmitAnswer={vi.fn()}
        onSubmitted={vi.fn()}
      />
    );
    await user.type(screen.getByLabelText("今週の振り返り"), "方向転換したい");
    await user.click(screen.getByRole("button", { name: /別の Focus へ/ }));
    await user.click(screen.getByRole("button", { name: "回答を送信" }));
    expect(await screen.findByText("切り替え先の Focus がありません。先に Focus を追加してください。")).toBeTruthy();
  });
});
