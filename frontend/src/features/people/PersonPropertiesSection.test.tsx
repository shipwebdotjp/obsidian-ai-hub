import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import PersonPropertiesSection from "./PersonPropertiesSection";
import { formatYmdWithDow } from "../../utils/date";
import { PersonPropertyDefinition, PersonPropertyValue } from "./types";

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

function renderSection(properties: PersonPropertyValue[], definitions: PersonPropertyDefinition[]) {
  return render(
    <PersonPropertiesSection
      personId="p1"
      properties={properties}
      definitions={definitions}
      loading={false}
      onCreateProperty={vi.fn()}
      onUpdateProperty={vi.fn()}
      onDeleteProperty={vi.fn()}
    />,
  );
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
