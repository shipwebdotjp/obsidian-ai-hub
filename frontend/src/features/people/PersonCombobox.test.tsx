import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import PersonCombobox from "./PersonCombobox";
import { Person } from "../../api/types";

const people: Person[] = [
  {
    person_id: "p1",
    display_name: "山田太郎",
    normalized_name: "山田太郎",
    vault_id: "vault-001",
    aliases: [{ normalized_name: "やまだ", display_name: "ヤマダ" }],
    summary_count: 3,
  },
  {
    person_id: "p2",
    display_name: "佐藤花子",
    normalized_name: "佐藤花子",
    vault_id: null,
    aliases: [],
    summary_count: 1,
  },
  {
    person_id: "p3",
    display_name: "鈴木一郎",
    normalized_name: "鈴木一郎",
    vault_id: "vault-003",
    aliases: [{ normalized_name: "スズキ", display_name: "スズキ" }],
    summary_count: 0,
  },
];

describe("PersonCombobox", () => {
  it("未選択時はプレースホルダを表示し、選択済み人物の表示名と連携状態を示す", () => {
    const { rerender } = render(<PersonCombobox people={people} value="" onChange={vi.fn()} />);
    expect(screen.getByRole("combobox", { name: "一括解決先の人物" })).toHaveAttribute(
      "placeholder",
      "-- 解決先の人物を選択してください --",
    );

    rerender(<PersonCombobox people={people} value="p1" onChange={vi.fn()} />);
    expect(screen.getByRole("combobox", { name: "一括解決先の人物" })).toHaveValue("山田太郎 (vault-001)");
  });

  it("テキスト入力で候補を絞り込める", async () => {
    const user = userEvent.setup();
    render(<PersonCombobox people={people} value="" onChange={vi.fn()} />);
    const input = screen.getByRole("combobox", { name: "一括解決先の人物" });

    await user.click(input);
    expect(screen.getByRole("listbox")).toBeInTheDocument();

    await user.type(input, "佐藤");
    const listbox = screen.getByRole("listbox");
    expect(within(listbox).getByText("佐藤花子")).toBeInTheDocument();
    expect(within(listbox).queryByText("山田太郎")).not.toBeInTheDocument();
    expect(within(listbox).queryByText("鈴木一郎")).not.toBeInTheDocument();
  });

  it("別名やVault IDでも絞り込める", async () => {
    const user = userEvent.setup();
    render(<PersonCombobox people={people} value="" onChange={vi.fn()} />);
    const input = screen.getByRole("combobox", { name: "一括解決先の人物" });

    await user.click(input);
    await user.type(input, "ヤマダ");
    expect(screen.getByRole("listbox")).toHaveTextContent("山田太郎");
    expect(screen.getByRole("listbox")).not.toHaveTextContent("佐藤花子");

    await user.clear(input);
    await user.type(input, "vault-003");
    expect(screen.getByRole("listbox")).toHaveTextContent("鈴木一郎");
  });

  it("一致しない場合は空状態を表示する", async () => {
    const user = userEvent.setup();
    render(<PersonCombobox people={people} value="" onChange={vi.fn()} />);
    const input = screen.getByRole("combobox", { name: "一括解決先の人物" });

    await user.click(input);
    await user.type(input, "存在しない人物zzz");
    expect(screen.getByText("一致する人物がありません")).toBeInTheDocument();
  });

  it("候補のクリックで person_id を通知し、未連携の表示を損なわない", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<PersonCombobox people={people} value="" onChange={onChange} />);

    await user.click(screen.getByRole("combobox", { name: "一括解決先の人物" }));
    await user.click(screen.getByRole("option", { name: /佐藤花子/ }));
    expect(onChange).toHaveBeenCalledWith("p2");
    // 選択後は入力欄に選択済み人物が明確に表示され、未連携マーカーを損なわない
    expect(screen.getByRole("combobox", { name: "一括解決先の人物" })).toHaveValue("佐藤花子 (未連携)");
  });

  it("未連携マーカーと別名が選択肢に表示される", async () => {
    const user = userEvent.setup();
    render(<PersonCombobox people={people} value="" onChange={vi.fn()} />);
    await user.click(screen.getByRole("combobox", { name: "一括解決先の人物" }));
    const listbox = screen.getByRole("listbox");
    expect(within(listbox).getByText("(未連携)")).toBeInTheDocument();
    expect(within(listbox).getByText(/別名: ヤマダ/)).toBeInTheDocument();
  });

  it("クリアボタンで未選択に戻せる", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<PersonCombobox people={people} value="p1" onChange={onChange} />);

    await user.click(screen.getByRole("button", { name: "選択をクリア" }));
    expect(onChange).toHaveBeenCalledWith("");
  });

  it("キーボード操作（ArrowDown + Enter）で選択できる", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<PersonCombobox people={people} value="" onChange={onChange} />);
    const input = screen.getByRole("combobox", { name: "一括解決先の人物" });

    await user.click(input);
    await user.type(input, "鈴木");
    await user.keyboard("{ArrowDown}{Enter}");
    expect(onChange).toHaveBeenCalledWith("p3");
  });

  it("Escapeでドロップダウンを閉じる", async () => {
    const user = userEvent.setup();
    render(<PersonCombobox people={people} value="" onChange={vi.fn()} />);
    const input = screen.getByRole("combobox", { name: "一括解決先の人物" });

    await user.click(input);
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("disabled時は入力できない", () => {
    render(<PersonCombobox people={people} value="" onChange={vi.fn()} disabled />);
    expect(screen.getByRole("combobox", { name: "一括解決先の人物" })).toBeDisabled();
  });
});
