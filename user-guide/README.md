# obsidian-ai-hub ユーザーガイド

このディレクトリは、obsidian-ai-hub のエンドユーザー向けガイドを提供する
[Docusaurus](https://docusaurus.io/) サイトです。トップページ機能と blog は使わず、
Document 機能だけで構成しています。ガイド本体は `docs/` にあります。

## 開発サーバー

```bash
npm install
npm run start
```

ローカルで表示を確認できます。

## ビルド

```bash
npm run build
```

静的ファイルを `build/` に生成します。壊れたリンクはビルド時に検出されます。

## 型チェック

```bash
npm run typecheck
```

## 構成

- `docs/` — ガイド本文（日本語）。`index.md` がサイトの入口です。
- `sidebars.ts` — サイドバー定義（このガイドの情報設計）。
- `docusaurus.config.ts` — サイト設定（Document 専用、`routeBasePath: '/'`）。

## 執筆方針

- 実装・設定・既存文書で裏付けられる操作だけを書きます。
- 推測で機能や手順を記載しません。
- プロンプト・メッセージ・UI 文言そのものをテストするのではなく、振る舞いと契約を確認します。
