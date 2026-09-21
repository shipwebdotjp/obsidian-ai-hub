import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

// This runs in Node.js - Don't use client-side code here (browser APIs, JSX...)

const config: Config = {
  title: 'obsidian-ai-hub ユーザーガイド',
  tagline: 'Obsidian のデイリーワークフローを自動化する',
  favicon: 'img/logo.svg',

  // Future flags, see https://docusaurus.io/docs/api/docusaurus-config#future
  future: {
    v4: true, // Improve compatibility with the upcoming Docusaurus v4
  },

  url: 'https://localhost',
  baseUrl: '/',

  onBrokenLinks: 'throw',

  markdown: {
    hooks: {
      onBrokenMarkdownLinks: 'throw',
    },
  },

  // The guide is written in Japanese.
  i18n: {
    defaultLocale: 'ja',
    locales: ['ja'],
  },

  presets: [
    [
      'classic',
      {
        // Documentation-only site: the docs section is the whole site, so the
        // docs root is served at "/" instead of "/docs".
        docs: {
          routeBasePath: '/',
          sidebarPath: './sidebars.ts',
          breadcrumbs: true,
          // No "edit this page" links: the guide lives inside the product repo.
          editUrl: undefined,
        },
        // Blog and the scaffold landing page are intentionally disabled.
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  themeConfig: {
    colorMode: {
      respectPrefersColorScheme: true,
    },
    navbar: {
      title: 'obsidian-ai-hub ユーザーガイド',
      logo: {
        alt: 'obsidian-ai-hub',
        src: 'img/logo.svg',
      },
      items: [
        {
          type: 'docSidebar',
          sidebarId: 'guideSidebar',
          position: 'left',
          label: 'ガイド',
        },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'ガイド',
          items: [
            {label: 'はじめに', to: '/getting-started/overview'},
            {label: 'ワークフロー', to: '/workflow/'},
            {label: '主な機能', to: '/features/memory'},
          ],
        },
        {
          title: 'リファレンス',
          items: [
            {label: 'CLI リファレンス', to: '/reference/cli'},
            {label: 'Web UI マップ', to: '/reference/web-ui-map'},
            {label: '設定', to: '/settings/configuration'},
          ],
        },
        {
          title: '困ったとき',
          items: [
            {label: 'トラブルシューティング', to: '/troubleshooting'},
            {label: '運用', to: '/operations'},
          ],
        },
      ],
      copyright: `Copyright © ${new Date().getFullYear()} obsidian-ai-hub. Built with Docusaurus.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
      additionalLanguages: ['bash', 'json', 'yaml'],
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
