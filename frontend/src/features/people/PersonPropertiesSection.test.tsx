import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import PersonPropertiesSection from "./PersonPropertiesSection";
import { formatYmdWithDow } from "../../utils/date";
import {
  PersonPropertyBulkSaveRequest,
  PersonPropertyDefinition,
  PersonPropertyValue,
  PersonPropertyValueCreateRequest,
  PersonPropertyValueUpdateRequest,
} from "./types";

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = vi.fn(function (this: HTMLDialogElement) {
    this.open = true;
  });
  HTMLDialogElement.prototype.close = vi.fn(function (this: HTMLDialogElement) {
    this.open = false;
  });
});

function makeDefinition(overrides: Partial<PersonPropertyDefinition> = {}): PersonPropertyDefinition {
  return {
    property_definition_id: "def-date",
    key: "birth_date",
    display_name: "生年月日",
    data_type: "date",
    cardinality: "single",
    source_type: "vault",
    aliases: [],
    options: [],
    created_at: "2026-01-01T00:00:00",
    updated_at: "2026-01-01T00:00:00",
    ...overrides,
  };
}

function makeValue(overrides: Partial<PersonPropertyValue> = {}): PersonPropertyValue {
  return {
    property_value_id: "pv-1",
    person_id: "p1",
    property_definition_id: "def-date",
    property_key: "birth_date",
    property_display_name: "生年月日",
    data_type: "date",
    cardinality: "single",
    source_type: "vault",
    value: "2026-09-07",
    value_text: null,
    value_date: "2026-09-07",
    value_number: null,
    value_boolean: null,
    option_id: null,
    option_key: null,
    option_display_name: null,
    valid_from: null,
    valid_until: null,
    note: null,
    created_at: "2026-01-01T00:00:00",
    updated_at: "2026-01-01T00:00:00",
    ...overrides,
  };
}

function makeMultiDefinition(overrides: Partial<PersonPropertyDefinition> = {}): PersonPropertyDefinition {
  return makeDefinition({
    property_definition_id: "def-skills",
    key: "skills",
    display_name: "スキル",
    data_type: "text",
    cardinality: "multiple",
    source_type: "database",
    ...overrides,
  });
}

function makeMultiValue(text: string, overrides: Partial<PersonPropertyValue> = {}): PersonPropertyValue {
  return makeValue({
    property_value_id: `pv-${text}`,
    person_id: "p1",
    property_definition_id: "def-skills",
    property_key: "skills",
    property_display_name: "スキル",
    data_type: "text",
    cardinality: "multiple",
    source_type: "database",
    value: text,
    value_text: text,
    value_date: null,
    ...overrides,
  });
}

function renderSection(
  properties: PersonPropertyValue[],
  definitions: PersonPropertyDefinition[],
  handlers: {
    onCreateProperty?: Mock<(req: PersonPropertyValueCreateRequest) => Promise<void>>;
    onUpdateProperty?: Mock<(propertyValueId: string, req: PersonPropertyValueUpdateRequest) => Promise<void>>;
    onDeleteProperty?: Mock<(propertyValueId: string) => Promise<void>>;
    onBulkSaveProperty?: Mock<(propertyDefinitionId: string, req: PersonPropertyBulkSaveRequest) => Promise<void>>;
  } = {},
) {
  const bound = {
    onCreateProperty: handlers.onCreateProperty ?? vi.fn(async () => {}),
    onUpdateProperty: handlers.onUpdateProperty ?? vi.fn(async () => {}),
    onDeleteProperty: handlers.onDeleteProperty ?? vi.fn(async () => {}),
    onBulkSaveProperty: handlers.onBulkSaveProperty ?? vi.fn(async () => {}),
  };
  const result = render(
    <PersonPropertiesSection
      personId="p1"
      properties={properties}
      definitions={definitions}
      loading={false}
      {...bound}
    />,
  );
  return { ...result, ...bound };
}

describe("PersonPropertiesSection", () => {
  it("日付型の値を共通フォーマッターで表示する", () => {
    renderSection([makeValue()], [makeDefinition()]);
    expect(screen.getByText(formatYmdWithDow("2026-09-07"))).toBeDefined();
    expect(screen.queryByText("2026-09-07")).toBeNull();
  });

  it("表示名と整形済み値を表示しslugを表示しない", () => {
    renderSection([makeValue()], [makeDefinition()]);
    expect(screen.getByText("生年月日")).toBeDefined();
    expect(screen.queryByText("(birth_date)")).toBeNull();
    expect(screen.queryByText("birth_date")).toBeNull();
  });

  it("multiple 属性は値行ごとに表示し単一の編集導線だけを持つ", () => {
    renderSection(
      [makeMultiValue("php"), makeMultiValue("python")],
      [makeMultiDefinition()],
    );
    expect(screen.getByText("php")).toBeInTheDocument();
    expect(screen.getByText("python")).toBeInTheDocument();
    // Group-level single edit affordance; no per-row edit/delete buttons.
    expect(screen.getByRole("button", { name: "スキルを一括編集" })).toBeInTheDocument();
    expect(screen.queryByText("削除")).toBeNull();
  });

  it("single 属性は従来どおり行ごとの編集・削除を持つ", () => {
    renderSection(
      [
        makeValue({ property_value_id: "pv-a", value: "a", value_text: "a", source_type: "database", cardinality: "single" }),
        makeValue({ property_value_id: "pv-b", value: "b", value_text: "b", source_type: "database", cardinality: "single" }),
      ],
      [makeDefinition({ source_type: "database", cardinality: "single" })],
    );
    expect(screen.getAllByRole("button", { name: "編集" })).toHaveLength(2);
    expect(screen.getAllByRole("button", { name: "削除" })).toHaveLength(2);
  });

  it("新規追加で multiple を選ぶと複数行フォームから一括保存する", async () => {
    const onBulkSaveProperty = vi.fn(async () => {});
    const onCreateProperty = vi.fn(async () => {});
    renderSection([], [makeMultiDefinition()], { onBulkSaveProperty, onCreateProperty });

    fireEvent.click(screen.getByRole("button", { name: "＋ 属性を追加" }));
    expect(screen.getByLabelText("値 1 値")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "＋ 値行を追加" }));
    expect(screen.getByLabelText("値 2 値")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("値 1 値"), { target: { value: "php" } });
    fireEvent.change(screen.getByLabelText("値 2 値"), { target: { value: "python" } });
    fireEvent.change(screen.getByLabelText("値 2 メモ"), { target: { value: "得意" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => expect(onBulkSaveProperty).toHaveBeenCalledTimes(1));
    expect(onBulkSaveProperty).toHaveBeenCalledWith(
      "def-skills",
      {
        values: [
          { value: "php", valid_from: null, valid_until: null, note: null },
          { value: "python", valid_from: null, valid_until: null, note: "得意" },
        ],
      },
    );
    expect(onCreateProperty).not.toHaveBeenCalled();
  });

  it("既存 multiple 値の編集導線から全値を読み込み追加・削除して一括保存する", async () => {
    const onBulkSaveProperty = vi.fn(async () => {});
    renderSection(
      [
        makeMultiValue("php", { property_value_id: "pv-php", note: "古い" }),
        makeMultiValue("python", { property_value_id: "pv-python" }),
      ],
      [makeMultiDefinition()],
      { onBulkSaveProperty },
    );

    fireEvent.click(screen.getByRole("button", { name: "スキルを一括編集" }));
    expect(screen.getByRole("heading", { name: "スキルの一括編集" })).toBeInTheDocument();
    expect(screen.getByLabelText("値 1 値")).toHaveValue("php");
    expect(screen.getByLabelText("値 2 値")).toHaveValue("python");

    // Drop the first row, keep the second, add a third.
    fireEvent.click(screen.getByRole("button", { name: "値 1の行を削除" }));
    expect(screen.queryByDisplayValue("php")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "＋ 値行を追加" }));
    fireEvent.change(screen.getByLabelText("値 2 値"), { target: { value: "rust" } });
    fireEvent.click(screen.getByRole("button", { name: "一括保存" }));

    await waitFor(() => expect(onBulkSaveProperty).toHaveBeenCalledTimes(1));
    expect(onBulkSaveProperty).toHaveBeenCalledWith(
      "def-skills",
      {
        values: [
          {
            property_value_id: "pv-python",
            value: "python",
            valid_from: null,
            valid_until: null,
            note: null,
          },
          { value: "rust", valid_from: null, valid_until: null, note: null },
        ],
      },
    );
  });

  it("全ての値行を削除して一括保存すると空配列で全削除する", async () => {
    const onBulkSaveProperty = vi.fn(async () => {});
    renderSection(
      [makeMultiValue("php", { property_value_id: "pv-php" })],
      [makeMultiDefinition()],
      { onBulkSaveProperty },
    );

    fireEvent.click(screen.getByRole("button", { name: "スキルを一括編集" }));
    fireEvent.click(screen.getByRole("button", { name: "値 1の行を削除" }));
    expect(screen.getByText("すべての値行を削除しました。保存するとこの属性の値がすべて削除されます。")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "一括保存" }));

    await waitFor(() => expect(onBulkSaveProperty).toHaveBeenCalledTimes(1));
    expect(onBulkSaveProperty).toHaveBeenCalledWith("def-skills", { values: [] });
  });

  it("boolean の新規行は未選択のまま保存できず選択を促す", async () => {
    const onBulkSaveProperty = vi.fn(async () => {});
    renderSection(
      [],
      [makeMultiDefinition({ data_type: "boolean" })],
      { onBulkSaveProperty },
    );

    fireEvent.click(screen.getByRole("button", { name: "＋ 属性を追加" }));
    expect(screen.getByLabelText("値 1 値")).toHaveValue("");
    // fireEvent.submit bypasses native required-validation to exercise the JS guard.
    fireEvent.submit(screen.getByRole("dialog").querySelector("form")!);

    await waitFor(() => expect(screen.getByText("値を選択してください。")).toBeInTheDocument());
    expect(onBulkSaveProperty).not.toHaveBeenCalled();
  });

  it("一括保存エラー時は入力を保持してエラーを表示する", async () => {
    const onBulkSaveProperty = vi.fn(async () => {
      throw new Error("保存失敗");
    });
    renderSection([makeMultiValue("php", { property_value_id: "pv-php" })], [makeMultiDefinition()], {
      onBulkSaveProperty,
    });

    fireEvent.click(screen.getByRole("button", { name: "スキルを一括編集" }));
    fireEvent.change(screen.getByLabelText("値 1 値"), { target: { value: "changed" } });
    fireEvent.click(screen.getByRole("button", { name: "一括保存" }));

    await waitFor(() => expect(screen.getByText("保存失敗")).toBeInTheDocument());
    // Dialog stays open and user input is preserved.
    expect(screen.getByRole("heading", { name: "スキルの一括編集" })).toBeInTheDocument();
    expect(screen.getByLabelText("値 1 値")).toHaveValue("changed");
  });

  it("日付・有効期間・メモを持つ属性の補足表示を維持する", () => {
    const { container } = renderSection(
      [
        makeValue({
          valid_from: "2026-01-01",
          valid_until: "2026-12-31",
          note: "備考メモ",
        }),
      ],
      [makeDefinition()],
    );
    const text = container.textContent ?? "";
    expect(text).toContain(formatYmdWithDow("2026-09-07"));
    expect(text).toContain(formatYmdWithDow("2026-01-01"));
    expect(text).toContain(formatYmdWithDow("2026-12-31"));
    expect(screen.getByText("備考メモ")).toBeDefined();
  });
});
