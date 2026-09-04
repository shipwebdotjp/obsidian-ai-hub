import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { AnsweredRequirementCard } from './AnsweredRequirementCard';
import type { AskUserAnswerRound } from '../api/types';

describe('AnsweredRequirementCard', () => {
  it('renders read-only answered requirement card with emerald styling and selected label', () => {
    const round: AskUserAnswerRound = {
      user_message_id: 'msg_1',
      hitl_run_id: 'hitl_123',
      tool_call_id: 'call_1',
      items: [
        {
          question_id: 'q_target',
          question: '対象範囲を選択してください',
          selected_value: 'backend',
          selected_label: 'バックエンド',
          text: null,
        },
      ],
    };

    render(<AnsweredRequirementCard round={round} />);

    expect(screen.getByText('✅ 回答済み要件確認')).toBeInTheDocument();
    expect(screen.getByText('ID: hitl_123')).toBeInTheDocument();
    expect(screen.getByText('対象範囲を選択してください')).toBeInTheDocument();
    expect(screen.getByText('選択:')).toBeInTheDocument();
    expect(screen.getByText('バックエンド')).toBeInTheDocument();
    expect(screen.queryByText('自由入力本文:')).not.toBeInTheDocument();
  });

  it('renders "other" selection along with free-text input', () => {
    const round: AskUserAnswerRound = {
      user_message_id: 'msg_2',
      hitl_run_id: 'hitl_456',
      tool_call_id: 'call_2',
      items: [
        {
          question_id: 'q_env',
          question: 'デプロイ環境を選択してください',
          selected_value: 'other',
          selected_label: 'その他（自由入力）',
          text: 'ステージング環境B',
        },
      ],
    };

    render(<AnsweredRequirementCard round={round} />);

    expect(screen.getByText('✅ 回答済み要件確認')).toBeInTheDocument();
    expect(screen.getByText('デプロイ環境を選択してください')).toBeInTheDocument();
    expect(screen.getByText('その他（自由入力）')).toBeInTheDocument();
    expect(screen.getByText('自由入力本文:')).toBeInTheDocument();
    expect(screen.getByText('ステージング環境B')).toBeInTheDocument();
  });
});
