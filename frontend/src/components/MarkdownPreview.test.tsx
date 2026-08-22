import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import MarkdownPreview from "./MarkdownPreview";

describe("MarkdownPreview", () => {
  it("renders headings", () => {
    render(<MarkdownPreview content={"# Heading 1\n\n## Heading 2"} />);
    expect(screen.getByRole("heading", { name: "Heading 1", level: 1 })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Heading 2", level: 2 })).toBeInTheDocument();
  });

  it("renders GFM table", () => {
    render(<MarkdownPreview content={"| A | B |\n|---|---|\n| 1 | 2 |"} />);
    expect(screen.getByText("A")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("renders code blocks", () => {
    render(<MarkdownPreview content={"```ts\nconst x = 1;\n```"} />);
    const codeEl = screen.getByText("const x = 1;");
    expect(codeEl).toBeInTheDocument();
  });

  it("renders external links with target=_blank", () => {
    render(<MarkdownPreview content="[example](https://example.com)" />);
    const link = screen.getByRole("link", { name: "example" });
    expect(link).toHaveAttribute("href", "https://example.com");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("renders inline code", () => {
    render(<MarkdownPreview content={"use `code` here"} />);
    expect(screen.getByText("code")).toBeInTheDocument();
  });

  it("renders blockquotes", () => {
    render(<MarkdownPreview content={"> quoted text"} />);
    expect(screen.getByText("quoted text")).toBeInTheDocument();
  });

  it("strips javascript: and data: hrefs to prevent XSS", () => {
    const { container } = render(
      <MarkdownPreview
        content={
          "[click](javascript:alert(1)) and [data](data:text/html,<script>alert(1)</script>) and [vbs](vbscript:msgbox(1))"
        }
      />
    );
    // No anchor with a javascript:/data:/vbscript: href should be rendered.
    const anchors = container.querySelectorAll("a");
    for (const a of Array.from(anchors)) {
      const href = a.getAttribute("href") ?? "";
      expect(/^(javascript|data|vbscript|file):/i.test(href)).toBe(false);
    }
  });
});
