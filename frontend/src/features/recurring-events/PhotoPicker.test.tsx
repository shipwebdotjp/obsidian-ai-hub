import { render, screen, fireEvent } from "@testing-library/react";
import { vi, describe, it, expect } from "vitest";
import { PhotoPicker } from "./PhotoPicker";

function dropFile(el: Element, files: File[]) {
  fireEvent.drop(el, {
    dataTransfer: { files, types: ["Files"] },
  });
}

describe("PhotoPicker", () => {
  it("selects a file from the file dialog", () => {
    const onSelect = vi.fn();
    render(<PhotoPicker selectedFile={null} onSelect={onSelect} />);

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    expect(input.getAttribute("accept")).toContain(".heic");
    const file = new File(["img"], "photo.jpg", { type: "image/jpeg" });
    fireEvent.change(input, { target: { files: [file] } });

    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith(file);
  });

  it("selects a single dropped file", () => {
    const onSelect = vi.fn();
    const { container } = render(<PhotoPicker selectedFile={null} onSelect={onSelect} />);
    const zone = container.firstElementChild as Element;

    const file = new File(["img"], "photo.heic", { type: "image/heic" });
    fireEvent.dragEnter(zone, { dataTransfer: { types: ["Files"] } });
    expect(zone.getAttribute("data-dragging")).toBe("true");
    dropFile(zone, [file]);

    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith(file);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("rejects a multi-file drop without changing the selection", () => {
    const onSelect = vi.fn();
    const current = new File(["img"], "current.jpg", { type: "image/jpeg" });
    const { container } = render(<PhotoPicker selectedFile={current} onSelect={onSelect} />);
    const zone = container.firstElementChild as Element;

    dropFile(zone, [
      new File(["a"], "a.jpg", { type: "image/jpeg" }),
      new File(["b"], "b.jpg", { type: "image/jpeg" }),
    ]);

    expect(onSelect).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("shows an error for an empty drop without changing the selection", () => {
    const onSelect = vi.fn();
    const { container } = render(<PhotoPicker selectedFile={null} onSelect={onSelect} />);
    const zone = container.firstElementChild as Element;

    dropFile(zone, []);

    expect(onSelect).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });
});
