import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GeneratedMediaCard } from "./GeneratedMediaCard";
import type { GeneratedMediaRef } from "../../api/types";

const getMediaBlob = vi.fn();

vi.mock("../../api/client", () => ({
  getMediaBlob: (mediaId: string) => getMediaBlob(mediaId),
}));

const media: GeneratedMediaRef = {
  media_type: "image",
  media_id: "abc123",
  mime_type: "image/png",
  width: 512,
  height: 512,
  filename: "generated.png",
};

describe("GeneratedMediaCard", () => {
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

  it("fetches the blob and renders an image", async () => {
    getMediaBlob.mockResolvedValue(new Blob(["x"], { type: "image/png" }));
    render(<GeneratedMediaCard media={media} />);

    await waitFor(() => {
      expect(screen.getByTestId("generated-media-card")).toBeInTheDocument();
    });
    await waitFor(() => {
      const img = screen.getByRole("img");
      expect(img).toHaveAttribute("src", "blob:media-abc123");
    });
    expect(getMediaBlob).toHaveBeenCalledWith("abc123");
    expect(createObjectURL).toHaveBeenCalled();
  });

  it("revokes the object URL on unmount", async () => {
    getMediaBlob.mockResolvedValue(new Blob(["x"], { type: "image/png" }));
    const { unmount } = render(<GeneratedMediaCard media={media} />);
    await waitFor(() => expect(createObjectURL).toHaveBeenCalled());
    unmount();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:media-abc123");
  });

  it("shows an error instead of an image on fetch failure", async () => {
    getMediaBlob.mockRejectedValue(new Error("boom"));
    render(<GeneratedMediaCard media={media} />);

    await waitFor(() => {
      expect(screen.getByTestId("generated-media-card")).toBeInTheDocument();
    });
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(createObjectURL).not.toHaveBeenCalled();
  });
});
