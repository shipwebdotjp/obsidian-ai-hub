import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import PeopleListTab from "./PeopleListTab";
import { Person } from "../../api/types";

const people: Person[] = [
  {
    person_id: "p1",
    display_name: "Alice Tanaka",
    normalized_name: "alice tanaka",
    vault_id: "vault-001",
    aliases: [],
    summary_count: 2,
  },
  {
    person_id: "p2",
    display_name: "佐藤花子",
    normalized_name: "佐藤花子",
    vault_id: null,
    aliases: [{ normalized_name: "さとう", display_name: "サトウ" }],
    summary_count: 1,
  },
  {
    person_id: "p3",
    display_name: "鈴木一郎",
    normalized_name: "鈴木一郎",
    vault_id: "vault-003",
    aliases: [],
    summary_count: 0,
  },
];

function renderTab(overrides: Partial<Parameters<typeof PeopleListTab>[0]> = {}) {
  return render(
    <PeopleListTab
      people={people}
      selectedPerson={null}
      editDisplayName=""
      editAliasesText=""
      editError={null}
      editSuccess={null}
      mergeGuidance={null}
      mergeToPersonId=""
      loading={false}
      mobileDetailOpen={false}
      setMobileDetailOpen={vi.fn()}
      onSelectPerson={vi.fn()}
      onChangeEditDisplayName={vi.fn()}
      onChangeEditAliasesText={vi.fn()}
      onUpdatePerson={vi.fn()}
      onTriggerDeleteConfirm={vi.fn()}
      onChangeMergeToPersonId={vi.fn()}
      onTriggerMergePreview={vi.fn()}
      onTriggerAliasDelete={vi.fn()}
      {...overrides}
    />,
  );
}

describe("PeopleListTab 検索ボックス", () => {
  it("初期表示で全人物が表示される", () => {
    renderTab();
    expect(screen.getByRole("searchbox", { name: "人物名で検索" })).toHaveValue("");
    expect(screen.getByRole("button", { name: /Alice Tanaka/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /佐藤花子/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /鈴木一郎/ })).toBeInTheDocument();
  });

  it("名前の部分一致で絞り込める", async () => {
    const user = userEvent.setup();
    renderTab();
    await user.type(screen.getByRole("searchbox", { name: "人物名で検索" }), "佐藤");
    expect(screen.getByRole("button", { name: /佐藤花子/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Alice Tanaka/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /鈴木一郎/ })).not.toBeInTheDocument();
  });

  it("大文字・小文字を区別しない", async () => {
    const user = userEvent.setup();
    renderTab();
    await user.type(screen.getByRole("searchbox", { name: "人物名で検索" }), "alice");
    expect(screen.getByRole("button", { name: /Alice Tanaka/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /佐藤花子/ })).not.toBeInTheDocument();
  });

  it("別名だけに一致する語句でも対象人物がヒットする", async () => {
    const user = userEvent.setup();
    renderTab();
    // p2 の別名「サトウ」は表示名「佐藤花子」・正規化名「佐藤花子」のいずれにも含まれない
    await user.type(screen.getByRole("searchbox", { name: "人物名で検索" }), "サトウ");
    expect(screen.getByRole("button", { name: /佐藤花子/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Alice Tanaka/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /鈴木一郎/ })).not.toBeInTheDocument();
  });

  it("0件時は登録なしメッセージと異なるメッセージを表示する", async () => {
    const user = userEvent.setup();
    renderTab();
    await user.type(screen.getByRole("searchbox", { name: "人物名で検索" }), "存在しない人物zzz");
    expect(screen.getByText("検索条件に一致する人物はいません。")).toBeInTheDocument();
    expect(screen.queryByText("現在、登録されている人物はいません。")).not.toBeInTheDocument();
  });

  it("入力クリアで全件に戻る", async () => {
    const user = userEvent.setup();
    renderTab();
    const searchbox = screen.getByRole("searchbox", { name: "人物名で検索" });
    await user.type(searchbox, "佐藤");
    expect(screen.queryByRole("button", { name: /鈴木一郎/ })).not.toBeInTheDocument();
    await user.clear(searchbox);
    expect(screen.getByRole("button", { name: /Alice Tanaka/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /佐藤花子/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /鈴木一郎/ })).toBeInTheDocument();
  });

  it("絞り込み後も人物選択ができる", async () => {
    const user = userEvent.setup();
    const onSelectPerson = vi.fn();
    renderTab({ onSelectPerson });
    await user.type(screen.getByRole("searchbox", { name: "人物名で検索" }), "鈴木");
    await user.click(screen.getByRole("button", { name: /鈴木一郎/ }));
    expect(onSelectPerson).toHaveBeenCalledWith(expect.objectContaining({ person_id: "p3" }));
  });

  it("人物が未登録の場合は従来の空状態メッセージを表示する", () => {
    renderTab({ people: [] });
    expect(screen.getByText("現在、登録されている人物はいません。")).toBeInTheDocument();
    // 未登録時は検索結果0件メッセージは出さない
    expect(screen.queryByText("検索条件に一致する人物はいません。")).not.toBeInTheDocument();
  });

  it("選択中の人物は絞り込み後も選択表示を維持する", () => {
    const selectedPerson = {
      ...people[0],
      summaries: [],
      relation_counts: { summaries: 0, aliases: 0, assignments: 0 },
    };
    renderTab({ selectedPerson });
    const button = screen.getByRole("button", { name: /Alice Tanaka/ });
    expect(button).toHaveAttribute("data-selected", "true");
    expect(within(button).getByText("Alice Tanaka")).toBeInTheDocument();
  });
});
