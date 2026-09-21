export interface ResearchMarkdownMeta {
  title?: string;
  status?: string;
  generated_at?: string;
  source?: string;
  output_style?: string;
  body: string;
}

const FRONTMATTER_KEYS = new Set([
  "title",
  "status",
  "generated_at",
  "source",
  "output_style",
]);

/**
 * `build_markdown()` が先頭に付与する YAML frontmatter を
 * メタ情報と本文に分離する。frontmatter が無い・壊れている場合は
 * 元の文字列を本文としてそのまま返す。
 */
export function parseResearchFrontmatter(markdown: string): ResearchMarkdownMeta {
  if (!markdown.startsWith("---\n") && !markdown.startsWith("---\r\n")) {
    return { body: markdown };
  }
  const normalized = markdown.replace(/\r\n/g, "\n");
  const lines = normalized.split("\n");
  let closingIndex = -1;
  for (let i = 1; i < lines.length; i++) {
    if (lines[i] === "---") {
      closingIndex = i;
      break;
    }
  }
  if (closingIndex === -1) {
    return { body: markdown };
  }

  const meta: ResearchMarkdownMeta = {
    body: lines.slice(closingIndex + 1).join("\n").replace(/^\n/, ""),
  };
  for (const line of lines.slice(1, closingIndex)) {
    const match = line.match(/^([A-Za-z_]+):\s*(.*)$/);
    if (!match) continue;
    const key = match[1]!;
    if (!FRONTMATTER_KEYS.has(key)) continue;
    const value = (match[2] ?? "").trim();
    if (!value) continue;
    if (key === "title") meta.title = value;
    else if (key === "status") meta.status = value;
    else if (key === "generated_at") meta.generated_at = value;
    else if (key === "source") meta.source = value;
    else if (key === "output_style") meta.output_style = value;
  }
  return meta;
}
