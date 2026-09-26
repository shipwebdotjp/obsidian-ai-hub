import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, it, expect, vi } from "vitest";
import MarkdownPreview from "./MarkdownPreview";

const getMediaBlob = vi.fn();

vi.mock("../api/client", () => ({
  getMediaBlob: (mediaId: string) => getMediaBlob(mediaId),
}));

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

describe("MarkdownPreview images", () => {
  const createObjectURL = vi.fn(() => "blob:media-abc123");
  const revokeObjectURL = vi.fn();

  beforeEach(() => {
    getMediaBlob.mockReset();
    createObjectURL.mockClear();
    revokeObjectURL.mockClear();
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL,
      revokeObjectURL,
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders in-app media URLs as an authenticated media card", async () => {
    getMediaBlob.mockResolvedValue(new Blob(["x"], { type: "image/png" }));
    render(<MarkdownPreview content="![generated](/api/v1/media/abc123)" />);

    await waitFor(() => {
      expect(screen.getByTestId("generated-media-card")).toBeInTheDocument();
    });
    expect(getMediaBlob).toHaveBeenCalledWith("abc123");
    await waitFor(() => {
      const img = screen.getByRole("img");
      expect(img).toHaveAttribute("src", "blob:media-abc123");
    });
  });

  it("renders media download URLs the same way", async () => {
    getMediaBlob.mockResolvedValue(new Blob(["x"], { type: "image/png" }));
    render(
      <MarkdownPreview content="![generated](/api/v1/media/abc123/download)" />
    );

    await waitFor(() => {
      expect(screen.getByTestId("generated-media-card")).toBeInTheDocument();
    });
    expect(getMediaBlob).toHaveBeenCalledWith("abc123");
  });

  it("renders in-app media URLs in the dark variant", async () => {
    getMediaBlob.mockResolvedValue(new Blob(["x"], { type: "image/png" }));
    render(
      <MarkdownPreview
        content="![generated](/api/v1/media/abc123)"
        variant="dark"
      />
    );

    await waitFor(() => {
      expect(screen.getByTestId("generated-media-card")).toBeInTheDocument();
    });
    expect(getMediaBlob).toHaveBeenCalledWith("abc123");
  });

  it("blocks unsafe image schemes and degrades to alt text", () => {
    const { container } = render(
      <MarkdownPreview
        content="![evil](javascript:alert(1)) ![evil2](data:image/png;base64,AAA)"
      />
    );
    const imgs = container.querySelectorAll("img");
    expect(imgs.length).toBe(0);
    for (const img of Array.from(imgs)) {
      const src = img.getAttribute("src") ?? "";
      expect(/^(javascript|data|vbscript|file):/i.test(src)).toBe(false);
    }
  });

  it("passes external image URLs through to a plain img", () => {
    render(<MarkdownPreview content="![ext](https://example.com/a.png)" />);
    const img = screen.getByRole("img");
    expect(img).toHaveAttribute("src", "https://example.com/a.png");
    expect(screen.queryByTestId("generated-media-card")).not.toBeInTheDocument();
  });

  it("forwards the image title to a plain img", () => {
    render(
      <MarkdownPreview content='![ext](https://example.com/a.png "caption")' />
    );
    expect(screen.getByRole("img")).toHaveAttribute("title", "caption");
  });

  it("does not fetch media for non-media sources", () => {
    render(<MarkdownPreview content="![ext](https://example.com/a.png)" />);
    expect(getMediaBlob).not.toHaveBeenCalled();
  });
});
