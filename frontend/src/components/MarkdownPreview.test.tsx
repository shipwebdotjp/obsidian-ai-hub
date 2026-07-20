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
});
