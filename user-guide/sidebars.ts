import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

// This runs in Node.js - Don't use client-side code here (browser APIs, JSX...)

/**
 * The user guide is a documentation-only site. The sidebar below defines the
 * single navigation tree, ordered from onboarding to daily use, the Workflow
 * graph feature, the remaining feature pages, settings, operations, and a
 * reference section.
 */
const sidebars: SidebarsConfig = {
  guideSidebar: [
    'index',
    {
      type: 'category',
      label: 'はじめに',
      collapsed: false,
      items: [
        'getting-started/overview',
        'getting-started/installation',
        'getting-started/web-ui',
      ],
    },
    {
      type: 'category',
      label: '日常のワークフロー',
      collapsed: false,
      items: [
        'daily/cli-basics',
        'daily/inbox-and-daily-note',
        'daily/summaries',
        'daily/schedule-target-backup',
      ],
    },
    {
      type: 'category',
      label: 'ワークフロー（グラフ実行）',
      collapsed: false,
      items: [
        'workflow/index',
        'workflow/concepts',
        'workflow/editor',
        'workflow/nodes',
        'workflow/data-flow',
        'workflow/runs',
        'workflow/templates',
        'workflow/limits',
      ],
    },
    {
      type: 'category',
      label: '主な機能',
      items: [
        'features/memory',
        'features/research',
        'features/agents',
        'features/coding',
        'features/task-agent',
        'features/planner',
        'features/jobs',
        'features/hitl',
        'features/vault-search',
        'features/summary-dashboard',
        'features/people',
        'features/projects',
        'features/healthcare',
        'features/system-maintenance',
      ],
    },
    {
      type: 'category',
      label: '設定',
      items: [
        'settings/configuration',
        'settings/llm',
        'settings/coding',
      ],
    },
    'operations',
    'troubleshooting',
    {
      type: 'category',
      label: 'リファレンス',
      items: [
        'reference/cli',
        'reference/job-schedules',
        'reference/web-ui-map',
      ],
    },
  ],
};

export default sidebars;
