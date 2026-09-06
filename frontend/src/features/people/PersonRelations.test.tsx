import { render, screen, fireEvent, waitFor } from "@testing-library/react";
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

    // Default endpoints are peo_taro -> peo_hanako. Switch subject to peo_jiro
    // so neither endpoint is the current person.
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
});
