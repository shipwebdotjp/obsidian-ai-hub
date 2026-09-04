import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { WaitingRunQuestionCard } from './InConversationQuestionCard';

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
