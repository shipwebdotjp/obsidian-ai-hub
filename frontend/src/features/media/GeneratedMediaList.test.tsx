import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GeneratedMediaList } from "./GeneratedMediaList";

const getMediaBlob = vi.fn();

vi.mock("../../api/client", () => ({
  getMediaBlob: (mediaId: string) => getMediaBlob(mediaId),
}));

function ref(mediaId: string) {
  return {
    media_type: "image",
    media_id: mediaId,
    mime_type: "image/png",
    width: 1024,
    height: 1024,
  };
}

describe("GeneratedMediaList", () => {
  const createObjectURL = vi.fn(() => "blob:media");
  const revokeObjectURL = vi.fn();

  beforeEach(() => {
    getMediaBlob.mockReset();
    getMediaBlob.mockResolvedValue(new Blob(["x"], { type: "image/png" }));
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

  it("renders one card per media reference", async () => {
    render(<GeneratedMediaList value={{ images: [ref("abc123"), ref("def456")] }} />);

    await waitFor(() => {
      const cards = screen.getAllByTestId("generated-media-card");
      expect(cards).toHaveLength(2);
    });
  });

  it("drops references listed in excludeMediaIds", async () => {
    render(
      <GeneratedMediaList
        value={{ images: [ref("abc123"), ref("def456")] }}
        excludeMediaIds={new Set(["abc123"])}
      />,
    );

    await waitFor(() => {
      const cards = screen.getAllByTestId("generated-media-card");
      expect(cards).toHaveLength(1);
      expect(cards[0]).toHaveAttribute("data-media-id", "def456");
    });
  });

  it("renders nothing when every reference is excluded", () => {
    render(
      <GeneratedMediaList
        value={{ images: [ref("abc123")] }}
        excludeMediaIds={new Set(["abc123"])}
      />,
    );
    expect(screen.queryByTestId("generated-media-list")).not.toBeInTheDocument();
  });
});
