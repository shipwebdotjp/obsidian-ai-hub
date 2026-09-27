import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ActionMenu } from "./ActionMenu";

describe("ActionMenu", () => {
  it("opens on trigger click and selects an item", () => {
    const onSelect = vi.fn();
    render(
      <ActionMenu
        testId="menu"
        items={[{ label: "first", testId: "item-first", onSelect }]}
      />,
    );
    fireEvent.click(screen.getByTestId("menu"));
    fireEvent.click(screen.getByTestId("item-first"));
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("item-first")).not.toBeInTheDocument();
  });

  it("closes on Escape", () => {
    render(
      <ActionMenu
        testId="menu"
        items={[{ label: "first", testId: "item-first", onSelect: () => {} }]}
      />,
    );
    fireEvent.click(screen.getByTestId("menu"));
    expect(screen.getByTestId("item-first")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByTestId("item-first")).not.toBeInTheDocument();
  });

  it("does not fire disabled items", () => {
    const onSelect = vi.fn();
    render(
      <ActionMenu
        testId="menu"
        items={[
          { label: "first", testId: "item-first", onSelect, disabled: true },
        ]}
      />,
    );
    fireEvent.click(screen.getByTestId("menu"));
    fireEvent.click(screen.getByTestId("item-first"));
    expect(onSelect).not.toHaveBeenCalled();
  });
});
