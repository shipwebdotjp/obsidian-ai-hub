import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { WaitingRunQuestionCard, WaitingRunStatusPanel, waitForHitlSettled } from './InConversationQuestionCard';
import * as clientApi from '../api/client';

vi.mock('../api/client', () => ({
  getHitlRun: vi.fn(),
}));

describe('WaitingRunQuestionCard', () => {
  const sampleQuestions = [
    {
      question_id: 'q1',
      question: 'Which environment should we target?',
      choices: [
        { value: 'dev', label: 'Development' },
        { value: 'prod', label: 'Production' },
        { value: 'other', label: 'その他（自由入力）' },
      ],
    },
  ];

  it('renders questions and choices', () => {
    render(
      <WaitingRunQuestionCard
        hitlRunId="hitl_123"
        questions={sampleQuestions}
        onSubmit={async () => {}}
        onCancel={async () => {}}
      />
    );

    expect(screen.getByText('Which environment should we target?')).toBeInTheDocument();
    expect(screen.getByText('Development')).toBeInTheDocument();
    expect(screen.getByText('Production')).toBeInTheDocument();
    expect(screen.getByText('その他（自由入力）')).toBeInTheDocument();
  });

  it('validates selection before submission', async () => {
    const handleSubmit = vi.fn();
    render(
      <WaitingRunQuestionCard
        hitlRunId="hitl_123"
        questions={sampleQuestions}
        onSubmit={handleSubmit}
        onCancel={async () => {}}
      />
    );

    fireEvent.click(screen.getByText('回答を送信'));
    expect(await screen.findByText('すべての質問に回答してください。')).toBeInTheDocument();
    expect(handleSubmit).not.toHaveBeenCalled();
  });

  it('requires text input when "other" is selected', async () => {
    const handleSubmit = vi.fn();
    render(
      <WaitingRunQuestionCard
        hitlRunId="hitl_123"
        questions={sampleQuestions}
        onSubmit={handleSubmit}
        onCancel={async () => {}}
      />
    );

    fireEvent.click(screen.getByLabelText('その他（自由入力）'));
    fireEvent.click(screen.getByText('回答を送信'));

    expect(
      await screen.findByText('「その他」を選択した場合はテキストを入力してください。')
    ).toBeInTheDocument();
    expect(handleSubmit).not.toHaveBeenCalled();
  });

  it('submits correctly when valid choice selected', async () => {
    const handleSubmit = vi.fn().mockResolvedValue(undefined);
    render(
      <WaitingRunQuestionCard
        hitlRunId="hitl_123"
        questions={sampleQuestions}
        onSubmit={handleSubmit}
        onCancel={async () => {}}
      />
    );

    fireEvent.click(screen.getByLabelText('Development'));
    fireEvent.click(screen.getByText('回答を送信'));

    await waitFor(() => {
      expect(handleSubmit).toHaveBeenCalledWith({
        q1: { value: 'dev', comment: undefined },
      });
    });
  });
});

describe('WaitingRunStatusPanel', () => {
  it('shows resume-pending notice without answer controls', () => {
    render(
      <WaitingRunStatusPanel
        hitlRunId="hitl_1"
        status="ready_to_resume"
        onCancel={async () => {}}
      />
    );

    expect(screen.getByText(/回答送信済み・再開待ち/)).toBeInTheDocument();
    expect(screen.queryByText('回答を送信')).not.toBeInTheDocument();
  });

  it('shows failure notice with error and cancel', async () => {
    const handleCancel = vi.fn().mockResolvedValue(undefined);
    render(
      <WaitingRunStatusPanel
        hitlRunId="hitl_2"
        status="failed"
        errorMessage="Handler 'coding.ask_user' is not registered."
        onCancel={handleCancel}
      />
    );

    expect(screen.getByText(/確認処理に失敗しました/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '取消' }));
    await waitFor(() => {
      expect(handleCancel).toHaveBeenCalledTimes(1);
    });
  });
});

describe('waitForHitlSettled', () => {
  it('resolves once the run settles', async () => {
    vi.mocked(clientApi.getHitlRun)
      .mockResolvedValueOnce({ status: 'ready_to_resume' } as any)
      .mockResolvedValueOnce({ status: 'running' } as any)
      .mockResolvedValue({ status: 'completed' } as any);

    const result = await waitForHitlSettled('hitl_1', { intervalMs: 1, timeoutMs: 5000 });
    expect(result?.status).toBe('completed');
    expect(clientApi.getHitlRun).toHaveBeenCalledWith('hitl_1');
  });

  it('returns last state on timeout instead of throwing', async () => {
    vi.mocked(clientApi.getHitlRun).mockResolvedValue({ status: 'ready_to_resume' } as any);

    const result = await waitForHitlSettled('hitl_1', { intervalMs: 1, timeoutMs: 10 });
    expect(result?.status).toBe('ready_to_resume');
  });
});
