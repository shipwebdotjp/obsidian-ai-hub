import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, test, expect, vi, beforeEach } from "vitest";

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = vi.fn();
  HTMLDialogElement.prototype.close = vi.fn();
});
import RelationTypesTab from "./RelationTypesTab";
import PersonRelationsSection from "./PersonRelationsSection";
import DeletePersonDialog from "./DeletePersonDialog";
import RelationFormModal from "./RelationFormModal";
import RelationEvidenceSection from "./RelationEvidenceSection";
import MergePreviewDialog from "./MergePreviewDialog";
import { formatPeriodDate } from "./PersonRelationsSection";
import { PersonRelationType, PersonRelation, PersonDetail } from "./types";

describe("Person Relations UI Components", () => {
  const mockTypes: PersonRelationType[] = [
    {
      relation_type_id: "rlt_parent",
      slug: "parent-child",
      forward_label: "親である",
      reverse_label: "子である",
      directionality: "directed",
      description: "親子関係",
      is_builtin: true,
      is_active: true,
      created_at: "2026-01-01T00:00:00",
      updated_at: "2026-01-01T00:00:00",
    },
    {
      relation_type_id: "rlt_inactive",
      slug: "temp-slug",
      forward_label: "仮関係",
      reverse_label: "仮関係",
      directionality: "symmetric",
      description: null,
      is_builtin: false,
      is_active: false,
      created_at: "2026-01-01T00:00:00",
      updated_at: "2026-01-01T00:00:00",
    },
  ];

  test("RelationTypesTab renders type list and handles modal opening", () => {
    render(
      <RelationTypesTab
        types={mockTypes}
        loading={false}
        error={null}
        onCreateType={vi.fn()}
        onUpdateType={vi.fn()}
      />
    );

    expect(screen.getByText("関係タイプ管理")).toBeInTheDocument();
    expect(screen.getByText("parent-child")).toBeInTheDocument();
    expect(screen.getByText("親である")).toBeInTheDocument();
    expect(screen.getByText("子である")).toBeInTheDocument();
    expect(screen.getByText("非活性")).toBeInTheDocument();

    // Open Create Modal
    fireEvent.click(screen.getByText("＋ 新規関係タイプ"));
    expect(screen.getByText("新規関係タイプの追加")).toBeInTheDocument();
  });

  test("PersonRelationsSection renders forward/reverse labels and state filters correctly", () => {
    const currentPerson: PersonDetail = {
      person_id: "peo_taro",
      display_name: "山田 太郎",
      normalized_name: "山田太郎",
      vault_id: null,
      aliases: [],
      summary_count: 1,
      summaries: [],
      relation_counts: {
        summaries: 1,
        aliases: 0,
        assignments: 0,
        subject_relations: 1,
        object_relations: 0,
        evidence: 1,
      },
    };

    const mockRelations: PersonRelation[] = [
      {
        relation_id: "rel_1",
        subject_person_id: "peo_taro",
        object_person_id: "peo_hanako",
        relation_type_id: "rlt_parent",
        started_on: "2020-01-01",
        ended_on: null,
        note: "戸籍メモ",
        status: "active",
        created_at: "2026-01-01T00:00:00",
        updated_at: "2026-01-01T00:00:00",
        relation_type: mockTypes[0],
        evidence: [],
      },
    ];

    const mockPeopleList = [
      { person_id: "peo_taro", display_name: "山田 太郎", normalized_name: "山田太郎", vault_id: null, aliases: [], summary_count: 1 },
      { person_id: "peo_hanako", display_name: "鈴木 花子", normalized_name: "鈴木花子", vault_id: null, aliases: [], summary_count: 1 },
    ];

    render(
      <PersonRelationsSection
        currentPerson={currentPerson}
        relations={mockRelations}
        peopleList={mockPeopleList}
        statusFilter="all"
        onStatusFilterChange={vi.fn()}
        onOpenCreateModal={vi.fn()}
        onOpenEditModal={vi.fn()}
        onDeleteRelation={vi.fn()}
      />
    );

    expect(screen.getByText("親である")).toBeInTheDocument();
    expect(screen.getByText("鈴木 花子")).toBeInTheDocument();
    expect(screen.getByText("メモ: 戸籍メモ")).toBeInTheDocument();
  });

  test("DeletePersonDialog displays relation counts and Vault warning", () => {
    const personToDelete: PersonDetail = {
      person_id: "peo_vault",
      display_name: "連携人物",
      normalized_name: "連携人物",
      vault_id: "vault-123",
      aliases: [],
      summary_count: 2,
      summaries: [],
      relation_counts: {
        summaries: 2,
        aliases: 1,
        assignments: 0,
        subject_relations: 3,
        object_relations: 2,
        evidence: 4,
      },
    };

    render(
      <DeletePersonDialog
        personToDelete={personToDelete}
        loading={false}
        onCancel={vi.fn()}
        onConfirm={vi.fn()}
      />
    );

    expect(screen.getByText(/Vaultノート連携に対する警告/i)).toBeInTheDocument();
    expect(screen.getByText(/関係（リレーション）および根拠は復元されません/i)).toBeInTheDocument();
    expect(screen.getByText(/発信リレーション:/i)).toBeInTheDocument();
    expect(screen.getByText(/受信リレーション:/i)).toBeInTheDocument();
    expect(screen.getByText(/根拠 \(evidence\):/i)).toBeInTheDocument();
  });

  test("RelationFormModal rejects relations detached from the current person", async () => {
    const onCreate = vi.fn();
    const mockPeopleList = [
      { person_id: "peo_taro", display_name: "山田 太郎", normalized_name: "山田太郎", vault_id: null, aliases: [], summary_count: 1 },
      { person_id: "peo_hanako", display_name: "鈴木 花子", normalized_name: "鈴木花子", vault_id: null, aliases: [], summary_count: 1 },
      { person_id: "peo_jiro", display_name: "佐藤 次郎", normalized_name: "佐藤次郎", vault_id: null, aliases: [], summary_count: 1 },
    ];

    render(
      <RelationFormModal
        currentPersonId="peo_taro"
        relationToEdit={null}
        types={mockTypes}
        peopleList={mockPeopleList}
        onClose={vi.fn()}
        onCreate={onCreate}
        onUpdate={vi.fn()}
        onAddEvidence={vi.fn()}
        onUpdateEvidence={vi.fn()}
        onDeleteEvidence={vi.fn()}
      />
    );

    // 受信側は初期状態で未選択のため、先に peo_hanako を選択する。
    // その後 subject を peo_jiro に切り替え、両端点とも現在の人物でなくする。
    const objectInput = screen.getByPlaceholderText("相手人物を選択...");
    fireEvent.focus(objectInput);
    const hanakoLabel = await screen.findByText("鈴木 花子", { exact: false });
    const hanakoOption = hanakoLabel.closest("li");
    expect(hanakoOption).not.toBeNull();
    fireEvent.click(hanakoOption!);

    const subjectInput = screen.getByPlaceholderText("発信人物を選択...");
    fireEvent.focus(subjectInput);
    const optionLabel = await screen.findByText("佐藤 次郎", { exact: false });
    const option = optionLabel.closest("li");
    expect(option).not.toBeNull();
    fireEvent.click(option!);

    fireEvent.click(screen.getByText("関係を作成"));

    await waitFor(() => {
      expect(
        screen.getByText("いずれか一方の端点に現在表示中の人物を含めてください。")
      ).toBeInTheDocument();
    });
    expect(onCreate).not.toHaveBeenCalled();
  });

  test("RelationFormModal swaps directed endpoints via swap button", async () => {
    const mockPeopleList = [
      { person_id: "peo_taro", display_name: "山田 太郎", normalized_name: "山田太郎", vault_id: null, aliases: [], summary_count: 1 },
      { person_id: "peo_hanako", display_name: "鈴木 花子", normalized_name: "鈴木花子", vault_id: null, aliases: [], summary_count: 1 },
    ];

    render(
      <RelationFormModal
        currentPersonId="peo_taro"
        relationToEdit={null}
        types={mockTypes}
        peopleList={mockPeopleList}
        onClose={vi.fn()}
        onCreate={vi.fn()}
        onUpdate={vi.fn()}
        onAddEvidence={vi.fn()}
        onUpdateEvidence={vi.fn()}
        onDeleteEvidence={vi.fn()}
      />
    );

    const subjectInput = screen.getByPlaceholderText("発信人物を選択...") as HTMLInputElement;
    const objectInput = screen.getByPlaceholderText("相手人物を選択...") as HTMLInputElement;
    // 受信側は初期状態で未選択。
    expect(subjectInput.value).toContain("山田 太郎");
    expect(objectInput.value).toBe("");

    // 受信側に鈴木 花子を選択してから入れ替える。
    fireEvent.focus(objectInput);
    const hanakoLabel = await screen.findByText("鈴木 花子", { exact: false });
    const hanakoOption = hanakoLabel.closest("li");
    expect(hanakoOption).not.toBeNull();
    fireEvent.click(hanakoOption!);
    expect(objectInput.value).toContain("鈴木 花子");

    fireEvent.click(screen.getByRole("button", { name: "発信側と受信側を入れ替え", hidden: true }));

    expect(subjectInput.value).toContain("鈴木 花子");
    expect(objectInput.value).toContain("山田 太郎");
  });

  test("RelationFormModal starts with object endpoint unselected", () => {
    const mockPeopleList = [
      { person_id: "peo_taro", display_name: "山田 太郎", normalized_name: "山田太郎", vault_id: null, aliases: [], summary_count: 1 },
      { person_id: "peo_hanako", display_name: "鈴木 花子", normalized_name: "鈴木花子", vault_id: null, aliases: [], summary_count: 1 },
    ];

    render(
      <RelationFormModal
        currentPersonId="peo_taro"
        relationToEdit={null}
        types={mockTypes}
        peopleList={mockPeopleList}
        onClose={vi.fn()}
        onCreate={vi.fn()}
        onUpdate={vi.fn()}
        onAddEvidence={vi.fn()}
        onUpdateEvidence={vi.fn()}
        onDeleteEvidence={vi.fn()}
      />
    );

    // 有向: 発信側は現在の人物、受信側は未選択。
    expect((screen.getByPlaceholderText("発信人物を選択...") as HTMLInputElement).value).toContain("山田 太郎");
    expect((screen.getByPlaceholderText("相手人物を選択...") as HTMLInputElement).value).toBe("");
  });

  test("RelationFormModal hides swap button for symmetric types", () => {
    const symmetricTypes: PersonRelationType[] = [
      {
        relation_type_id: "rlt_sym",
        slug: "sym",
        forward_label: "同僚",
        reverse_label: "同僚",
        directionality: "symmetric",
        description: null,
        is_builtin: false,
        is_active: true,
        created_at: "2026-01-01T00:00:00",
        updated_at: "2026-01-01T00:00:00",
      },
    ];
    const mockPeopleList = [
      { person_id: "peo_taro", display_name: "山田 太郎", normalized_name: "山田太郎", vault_id: null, aliases: [], summary_count: 1 },
      { person_id: "peo_hanako", display_name: "鈴木 花子", normalized_name: "鈴木花子", vault_id: null, aliases: [], summary_count: 1 },
    ];

    render(
      <RelationFormModal
        currentPersonId="peo_taro"
        relationToEdit={null}
        types={symmetricTypes}
        peopleList={mockPeopleList}
        onClose={vi.fn()}
        onCreate={vi.fn()}
        onUpdate={vi.fn()}
        onAddEvidence={vi.fn()}
        onUpdateEvidence={vi.fn()}
        onDeleteEvidence={vi.fn()}
      />
    );

    expect(screen.queryByRole("button", { name: "発信側と受信側を入れ替え", hidden: true })).not.toBeInTheDocument();
    // 対称型でも人物Bは初期状態で未選択。
    expect((screen.getByPlaceholderText("人物Aを選択...") as HTMLInputElement).value).toContain("山田 太郎");
    expect((screen.getByPlaceholderText("人物Bを選択...") as HTMLInputElement).value).toBe("");
  });

  test("RelationEvidenceSection renders empty state for nullish evidence", () => {
    const { rerender } = render(
      <RelationEvidenceSection evidence={null as unknown as []} />
    );
    expect(
      screen.getByText("この関係に登録されている根拠 (Evidence) はありません。")
    ).toBeInTheDocument();

    rerender(<RelationEvidenceSection evidence={undefined as unknown as []} />);
    expect(
      screen.getByText("この関係に登録されている根拠 (Evidence) はありません。")
    ).toBeInTheDocument();
  });

  test("PersonRelationsSection collapses expanded relations on person change", () => {
    const personA: PersonDetail = {
      person_id: "peo_taro",
      display_name: "山田 太郎",
      normalized_name: "山田太郎",
      vault_id: null,
      aliases: [],
      summary_count: 0,
      summaries: [],
      relation_counts: {
        summaries: 0,
        aliases: 0,
        assignments: 0,
        subject_relations: 1,
        object_relations: 0,
        evidence: 1,
      },
    };
    const personB: PersonDetail = { ...personA, person_id: "peo_jiro", display_name: "佐藤 次郎" };
    const relations: PersonRelation[] = [
      {
        relation_id: "rel_1",
        subject_person_id: "peo_taro",
        object_person_id: "peo_hanako",
        relation_type_id: "rlt_parent",
        started_on: null,
        ended_on: null,
        note: null,
        status: "active",
        created_at: "2026-01-01T00:00:00",
        updated_at: "2026-01-01T00:00:00",
        relation_type: mockTypes[0],
        evidence: [
          {
            evidence_id: "rle_1",
            relation_id: "rel_1",
            source_type: "manual",
            source_ref: null,
            quote: "展開確認用の引用",
            note: null,
            observed_at: null,
            created_at: "2026-01-01T00:00:00",
            updated_at: "2026-01-01T00:00:00",
          },
        ],
      },
    ];
    const mockPeopleList = [
      { person_id: "peo_taro", display_name: "山田 太郎", normalized_name: "山田太郎", vault_id: null, aliases: [], summary_count: 1 },
      { person_id: "peo_hanako", display_name: "鈴木 花子", normalized_name: "鈴木花子", vault_id: null, aliases: [], summary_count: 1 },
    ];
    const sectionProps = {
      relations,
      peopleList: mockPeopleList,
      statusFilter: "all" as const,
      onStatusFilterChange: vi.fn(),
      onOpenCreateModal: vi.fn(),
      onOpenEditModal: vi.fn(),
      onDeleteRelation: vi.fn(),
    };

    const { rerender } = render(
      <PersonRelationsSection currentPerson={personA} {...sectionProps} />
    );
    fireEvent.click(screen.getByText("根拠 (1)", { exact: false }));
    expect(screen.getByText("展開確認用の引用", { exact: false })).toBeInTheDocument();

    rerender(<PersonRelationsSection currentPerson={personB} {...sectionProps} />);
    expect(screen.queryByText("展開確認用の引用", { exact: false })).not.toBeInTheDocument();
  });

  test("MergePreviewDialog shows relation impacts even when merge is blocked", () => {
    const fromPerson = { person_id: "peo_old", display_name: "旧 記録", normalized_name: "旧記録", vault_id: null, aliases: [], summary_count: 0 };
    const toPerson = { person_id: "peo_target", display_name: "対象 人物", normalized_name: "対象人物", vault_id: null, aliases: [], summary_count: 0 };

    render(
      <MergePreviewDialog
        mergeFromPerson={fromPerson}
        mergeToPerson={toPerson}
        previewLoading={false}
        previewData={{
          allowed: false,
          reason: "統合により自己関係が発生するため実行できません。",
          from_person: fromPerson,
          to_person: toPerson,
          transferred_summaries_count: 0,
          transferred_aliases_count: 0,
          transferred_relations_count: 0,
          merged_relations_count: 0,
          self_relation_conflicts_count: 1,
          alias_transfers: [],
          merged_summaries: [],
          relation_impacts: [
            {
              relation_id: "rel_1",
              other_person_id: "peo_target",
              other_person_name: "対象 人物",
              relation_type_id: "rlt_parent",
              relation_type_slug: "parent-child",
              relation_type_forward_label: "親である",
              relation_type_reverse_label: "子である",
              started_on: null,
              ended_on: null,
              result_type: "self_relation_conflict",
              surviving_relation_id: null,
            },
          ],
        }}
        mergeModalError={null}
        loading={false}
        onCloseModal={vi.fn()}
        onExecuteMerge={vi.fn()}
      />
    );

    expect(screen.getByText("統合阻害要因", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("自己関係違反")).toBeInTheDocument();
    expect(screen.getByText("(期間未設定)")).toBeInTheDocument();
  });

  test("MergePreviewDialog requires selecting mergeToPerson and confirming preview before execution", async () => {
    const user = userEvent.setup();
    const onRequestPreview = vi.fn();
    const onChangeMergeToPerson = vi.fn();
    const onExecuteMerge = vi.fn();

    const fromPerson = { person_id: "p1", display_name: "Alice Tanaka", normalized_name: "alice tanaka", vault_id: "vault-001", aliases: [], summary_count: 2 };
    const toPerson = { person_id: "p2", display_name: "佐藤花子", normalized_name: "佐藤花子", vault_id: null, aliases: [], summary_count: 1 };
    const peopleList = [fromPerson, toPerson];

    // Initial state: mergeToPerson is null, previewData is null
    const { rerender } = render(
      <MergePreviewDialog
        people={peopleList}
        mergeFromPerson={fromPerson}
        mergeToPerson={null}
        previewLoading={false}
        previewData={null}
        mergeModalError={null}
        loading={false}
        onCloseModal={vi.fn()}
        onExecuteMerge={onExecuteMerge}
        onChangeMergeToPerson={onChangeMergeToPerson}
        onRequestPreview={onRequestPreview}
      />
    );

    // "安全に統合を実行する" button should be disabled when previewData is null
    const executeBtn = screen.getByRole("button", { name: "安全に統合を実行する", hidden: true });
    expect(executeBtn).toBeDisabled();

    // "統合内容を確認" button is disabled when mergeToPerson is null
    const confirmBtn = screen.getByRole("button", { name: "統合内容を確認", hidden: true });
    expect(confirmBtn).toBeDisabled();

    // Select toPerson in PersonCombobox
    const comboboxInput = screen.getByRole("combobox", { name: "統合先（残す人物）", hidden: true });
    await user.click(comboboxInput);
    const option = await screen.findByText(/佐藤花子/);
    await user.click(option);

    expect(onChangeMergeToPerson).toHaveBeenCalledWith(toPerson);

    // Rerender with mergeToPerson set
    rerender(
      <MergePreviewDialog
        people={peopleList}
        mergeFromPerson={fromPerson}
        mergeToPerson={toPerson}
        previewLoading={false}
        previewData={null}
        mergeModalError={null}
        loading={false}
        onCloseModal={vi.fn()}
        onExecuteMerge={onExecuteMerge}
        onChangeMergeToPerson={onChangeMergeToPerson}
        onRequestPreview={onRequestPreview}
      />
    );

    // Now "統合内容を確認" is enabled
    const confirmBtnEnabled = screen.getByRole("button", { name: "統合内容を確認", hidden: true });
    expect(confirmBtnEnabled).not.toBeDisabled();
    await user.click(confirmBtnEnabled);

    expect(onRequestPreview).toHaveBeenCalled();

    // Rerender with allowed previewData
    rerender(
      <MergePreviewDialog
        people={peopleList}
        mergeFromPerson={fromPerson}
        mergeToPerson={toPerson}
        previewLoading={false}
        previewData={{
          allowed: true,
          reason: null,
          from_person: fromPerson,
          to_person: toPerson,
          transferred_summaries_count: 1,
          transferred_aliases_count: 0,
          transferred_relations_count: 0,
          merged_relations_count: 0,
          self_relation_conflicts_count: 0,
          alias_transfers: [],
          merged_summaries: [],
          relation_impacts: [],
        }}
        mergeModalError={null}
        loading={false}
        onCloseModal={vi.fn()}
        onExecuteMerge={onExecuteMerge}
        onChangeMergeToPerson={onChangeMergeToPerson}
        onRequestPreview={onRequestPreview}
      />
    );

    // "安全に統合を実行する" button is now enabled
    const executeBtnEnabled = screen.getByRole("button", { name: "安全に統合を実行する", hidden: true });
    expect(executeBtnEnabled).not.toBeDisabled();
  });

  test("PersonRelationsSection links target person name to detail via onSelectPerson", async () => {
    const user = userEvent.setup();
    const onSelectPerson = vi.fn();
    const currentPerson: PersonDetail = {
      person_id: "peo_taro",
      display_name: "山田 太郎",
      normalized_name: "山田太郎",
      vault_id: null,
      aliases: [],
      summary_count: 1,
      summaries: [],
      relation_counts: {
        summaries: 1,
        aliases: 0,
        assignments: 0,
        subject_relations: 1,
        object_relations: 0,
        evidence: 0,
      },
    };
    const relations: PersonRelation[] = [
      {
        relation_id: "rel_1",
        subject_person_id: "peo_taro",
        object_person_id: "peo_hanako",
        relation_type_id: "rlt_parent",
        started_on: null,
        ended_on: null,
        note: null,
        status: "active",
        created_at: "2026-01-01T00:00:00",
        updated_at: "2026-01-01T00:00:00",
        relation_type: mockTypes[0],
        evidence: [],
      },
    ];
    const hanako = { person_id: "peo_hanako", display_name: "鈴木 花子", normalized_name: "鈴木花子", vault_id: null, aliases: [], summary_count: 1 };
    const mockPeopleList = [
      { person_id: "peo_taro", display_name: "山田 太郎", normalized_name: "山田太郎", vault_id: null, aliases: [], summary_count: 1 },
      hanako,
    ];

    render(
      <PersonRelationsSection
        currentPerson={currentPerson}
        relations={relations}
        peopleList={mockPeopleList}
        statusFilter="all"
        onStatusFilterChange={vi.fn()}
        onOpenCreateModal={vi.fn()}
        onOpenEditModal={vi.fn()}
        onDeleteRelation={vi.fn()}
        onSelectPerson={onSelectPerson}
      />
    );

    const link = screen.getByRole("button", { name: "鈴木 花子の詳細を表示" });
    expect(link).toBeInTheDocument();
    await user.click(link);
    expect(onSelectPerson).toHaveBeenCalledWith(expect.objectContaining({ person_id: "peo_hanako" }));
  });

  test("PersonRelationsSection falls back to plain text for unknown person, self, or missing handler", () => {
    const basePerson: PersonDetail = {
      person_id: "peo_taro",
      display_name: "山田 太郎",
      normalized_name: "山田太郎",
      vault_id: null,
      aliases: [],
      summary_count: 1,
      summaries: [],
      relation_counts: {
        summaries: 1,
        aliases: 0,
        assignments: 0,
        subject_relations: 1,
        object_relations: 0,
        evidence: 0,
      },
    };
    const baseRelation = {
      relation_type_id: "rlt_parent",
      started_on: null,
      ended_on: null,
      note: null,
      created_at: "2026-01-01T00:00:00",
      updated_at: "2026-01-01T00:00:00",
      relation_type: mockTypes[0],
      evidence: [],
    };
    const peopleList = [
      { person_id: "peo_taro", display_name: "山田 太郎", normalized_name: "山田太郎", vault_id: null, aliases: [], summary_count: 1 },
      { person_id: "peo_hanako", display_name: "鈴木 花子", normalized_name: "鈴木花子", vault_id: null, aliases: [], summary_count: 1 },
    ];
    const sectionProps = {
      peopleList,
      statusFilter: "all" as const,
      onStatusFilterChange: vi.fn(),
      onOpenCreateModal: vi.fn(),
      onOpenEditModal: vi.fn(),
      onDeleteRelation: vi.fn(),
      onSelectPerson: vi.fn(),
    };

    // 不明人物: peopleList に存在しない相手IDはリンク化せず title にIDを保持する。
    const unknownRelation: PersonRelation = {
      ...baseRelation,
      relation_id: "rel_unknown",
      subject_person_id: "peo_taro",
      object_person_id: "peo_missing",
      status: "active",
    };
    const { unmount: unmountUnknown } = render(
      <PersonRelationsSection currentPerson={basePerson} relations={[unknownRelation]} {...sectionProps} />
    );
    expect(screen.getByText("不明な人物")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /の詳細を表示/ })).not.toBeInTheDocument();
    unmountUnknown();

    // 本人: 相手IDが本人と同一の場合はリンク化しない。
    const selfRelation: PersonRelation = {
      ...baseRelation,
      relation_id: "rel_self",
      subject_person_id: "peo_taro",
      object_person_id: "peo_taro",
      status: "active",
    };
    const { unmount: unmountSelf } = render(
      <PersonRelationsSection currentPerson={basePerson} relations={[selfRelation]} {...sectionProps} />
    );
    expect(screen.getByText("山田 太郎")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /の詳細を表示/ })).not.toBeInTheDocument();
    unmountSelf();

    // ハンドラ未指定: 従来通りプレーンテキスト表示となる。
    const normalRelation: PersonRelation = {
      ...baseRelation,
      relation_id: "rel_normal",
      subject_person_id: "peo_taro",
      object_person_id: "peo_hanako",
      status: "active",
    };
    const { onSelectPerson: _omitted, ...propsWithoutHandler } = sectionProps;
    render(
      <PersonRelationsSection currentPerson={basePerson} relations={[normalRelation]} {...propsWithoutHandler} />
    );
    expect(screen.getByText("鈴木 花子")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /の詳細を表示/ })).not.toBeInTheDocument();
  });

  test("formatPeriodDate hides null, empty, and invalid dates", () => {
    expect(formatPeriodDate("2020-01-01")).toBe("2020/01/01(水)");
    expect(formatPeriodDate("2020-12-31")).toBe("2020/12/31(木)");
    expect(formatPeriodDate(null)).toBe("");
    expect(formatPeriodDate(undefined)).toBe("");
    expect(formatPeriodDate("")).toBe("");
    expect(formatPeriodDate("2024-02-30")).toBe("");
    expect(formatPeriodDate("2020/01/01")).toBe("");
    expect(formatPeriodDate("not-a-date")).toBe("");
  });

  test("PersonRelationsSection renders start-only, end-only, and unset periods", () => {
    const currentPerson: PersonDetail = {
      person_id: "peo_taro",
      display_name: "山田 太郎",
      normalized_name: "山田太郎",
      vault_id: null,
      aliases: [],
      summary_count: 0,
      summaries: [],
      relation_counts: {
        summaries: 0,
        aliases: 0,
        assignments: 0,
        subject_relations: 3,
        object_relations: 0,
        evidence: 0,
      },
    };
    const baseRelation = {
      relation_type_id: "rlt_parent",
      note: null,
      created_at: "2026-01-01T00:00:00",
      updated_at: "2026-01-01T00:00:00",
      relation_type: mockTypes[0],
      evidence: [],
    };
    const relations: PersonRelation[] = [
      { ...baseRelation, relation_id: "rel_both", subject_person_id: "peo_taro", object_person_id: "peo_hanako", started_on: "2020-01-01", ended_on: "2020-12-31", status: "ended" },
      { ...baseRelation, relation_id: "rel_start", subject_person_id: "peo_taro", object_person_id: "peo_hanako", started_on: "2020-01-01", ended_on: null, status: "active" },
      { ...baseRelation, relation_id: "rel_end", subject_person_id: "peo_taro", object_person_id: "peo_hanako", started_on: null, ended_on: "2020-12-31", status: "ended" },
    ];
    const mockPeopleList = [
      { person_id: "peo_taro", display_name: "山田 太郎", normalized_name: "山田太郎", vault_id: null, aliases: [], summary_count: 1 },
      { person_id: "peo_hanako", display_name: "鈴木 花子", normalized_name: "鈴木花子", vault_id: null, aliases: [], summary_count: 1 },
    ];

    render(
      <PersonRelationsSection
        currentPerson={currentPerson}
        relations={relations}
        peopleList={mockPeopleList}
        statusFilter="all"
        onStatusFilterChange={vi.fn()}
        onOpenCreateModal={vi.fn()}
        onOpenEditModal={vi.fn()}
        onDeleteRelation={vi.fn()}
      />
    );

    expect(screen.getByText("期間: 2020/01/01(水) ～ 2020/12/31(木)")).toBeInTheDocument();
    expect(screen.getByText("期間: 2020/01/01(水) ～ 現在")).toBeInTheDocument();
    expect(screen.getByText("期間: 未指定 ～ 2020/12/31(木)")).toBeInTheDocument();
  });

  test("RelationFormModal rejects empty evidence in edit mode", async () => {
    const onAddEvidence = vi.fn();
    const onUpdateEvidence = vi.fn();
    const relationToEdit: PersonRelation = {
      relation_id: "rel_1",
      subject_person_id: "peo_taro",
      object_person_id: "peo_hanako",
      relation_type_id: "rlt_parent",
      started_on: null,
      ended_on: null,
      note: null,
      status: "active",
      created_at: "2026-01-01T00:00:00",
      updated_at: "2026-01-01T00:00:00",
      relation_type: mockTypes[0],
      evidence: [
        {
          evidence_id: "rle_1",
          relation_id: "rel_1",
          source_type: "manual",
          source_ref: null,
          quote: "既存の引用",
          note: "既存メモ",
          observed_at: null,
          created_at: "2026-01-01T00:00:00",
          updated_at: "2026-01-01T00:00:00",
        },
      ],
    };
    const mockPeopleList = [
      { person_id: "peo_taro", display_name: "山田 太郎", normalized_name: "山田太郎", vault_id: null, aliases: [], summary_count: 1 },
      { person_id: "peo_hanako", display_name: "鈴木 花子", normalized_name: "鈴木花子", vault_id: null, aliases: [], summary_count: 1 },
    ];

    const { container } = render(
      <RelationFormModal
        currentPersonId="peo_taro"
        relationToEdit={relationToEdit}
        types={mockTypes}
        peopleList={mockPeopleList}
        onClose={vi.fn()}
        onCreate={vi.fn()}
        onUpdate={vi.fn()}
        onAddEvidence={onAddEvidence}
        onUpdateEvidence={onUpdateEvidence}
        onDeleteEvidence={vi.fn()}
      />
    );

    // Empty add-form is rejected.
    fireEvent.click(screen.getByText("＋ 根拠を追加"));
    fireEvent.click(screen.getByText("追加保存"));
    await waitFor(() => {
      expect(
        screen.getByText("根拠を登録するにはいずれかの項目を入力してください。")
      ).toBeInTheDocument();
    });
    expect(onAddEvidence).not.toHaveBeenCalled();

    // Clearing every field of an existing evidence and saving is rejected too.
    fireEvent.click(screen.getByText("編集", { selector: "button" }));
    await waitFor(() => {
      expect(screen.getByText("根拠の編集")).toBeInTheDocument();
    });
    const textInputs = container.querySelectorAll(
      'div[class*="bg-amber-50"] input[type="text"]'
    );
    expect(textInputs.length).toBeGreaterThan(0);
    textInputs.forEach((input) => {
      fireEvent.change(input, { target: { value: "" } });
    });
    fireEvent.click(screen.getByText("更新保存"));
    await waitFor(() => {
      expect(
        screen.getAllByText("根拠を登録するにはいずれかの項目を入力してください。").length
      ).toBeGreaterThan(0);
    });
    expect(onUpdateEvidence).not.toHaveBeenCalled();
  });
});
