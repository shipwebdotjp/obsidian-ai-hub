import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SmartText, StructuredValue } from "./StructuredValue";

describe("StructuredValue", () => {
  it("renders null and undefined without dropping them", () => {
    const { rerender } = render(<StructuredValue value={null} />);
    expect(screen.getByText("null")).toBeInTheDocument();
    rerender(<StructuredValue value={undefined} />);
    expect(screen.getByText("（未設定）")).toBeInTheDocument();
  });

  it("renders primitives and long text", () => {
    render(
      <div>
        <StructuredValue value={42} />
        <StructuredValue value={true} />
        <StructuredValue value={"a".repeat(500)} />
      </div>,
    );
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText("true")).toBeInTheDocument();
    expect(screen.getByText("a".repeat(500))).toBeInTheDocument();
  });

  it("marks empty string, array, and object explicitly", () => {
    render(
      <div>
        <StructuredValue value={""} />
        <StructuredValue value={[]} />
        <StructuredValue value={{}} />
      </div>,
    );
    expect(screen.getByText("（空文字）")).toBeInTheDocument();
    expect(screen.getByText("（空の配列）")).toBeInTheDocument();
    expect(screen.getByText("（空のオブジェクト）")).toBeInTheDocument();
  });

  it("renders nested objects, arrays, and unknown fields without omission", () => {
    render(
      <StructuredValue
        value={{
          purpose: "まとめる",
          count: 3,
          enabled: false,
          nothing: null,
          tags: ["a", "b"],
          nested: { deep: { leaf: "到達" } },
          unknown_future_field: { surprise: [1, { two: 2 }] },
        }}
      />,
    );
    for (const key of [
      "purpose",
      "count",
      "enabled",
      "nothing",
      "tags",
      "nested",
      "unknown_future_field",
      "deep",
      "leaf",
      "surprise",
      "two",
    ]) {
      expect(screen.getByText(key)).toBeInTheDocument();
    }
    expect(screen.getByText("まとめる")).toBeInTheDocument();
    expect(screen.getByText("到達")).toBeInTheDocument();
    expect(screen.getByText("null")).toBeInTheDocument();
  });

  it("SmartText renders plain text as-is", () => {
    render(<SmartText text={"今日の予定をまとめて\n2行目"} />);
    expect(screen.getByText(/今日の予定をまとめて/)).toBeInTheDocument();
  });

  it("SmartText structures a JSON object string instead of raw JSON", () => {
    const { container } = render(
      <SmartText text={'{"summary": "完了", "items": [1, 2]}'} />,
    );
    expect(screen.getByText("summary")).toBeInTheDocument();
    expect(screen.getByText("完了")).toBeInTheDocument();
    expect(screen.getByText("items")).toBeInTheDocument();
    // 生 JSON の波括弧・引用符の羅列ではなく構造化表示になる。
    expect(container.querySelector("pre")).toBeNull();
  });

  it("SmartText leaves non-JSON strings untouched", () => {
    render(<SmartText text={"ただの文字列 { ではない"} />);
    expect(screen.getByText("ただの文字列 { ではない")).toBeInTheDocument();
  });
});
