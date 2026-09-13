import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { GitMerge, Trash2 } from "lucide-react";
import { ApiError, listMemories } from "../../api/client";
import { Memory, Person, PersonAlias } from "../../api/types";
import {
  PersonDetail,
  PeopleError,
  PersonRelation,
  RelationStatus,
  PersonPropertyValue,
  PersonPropertyDefinition,
  PersonPropertyValueCreateRequest,
  PersonPropertyValueUpdateRequest,
  PersonPropertyBulkSaveRequest,
} from "./types";
import PersonRelationsSection from "./PersonRelationsSection";
import PersonPropertiesSection from "./PersonPropertiesSection";

interface PeopleListTabProps {
  people: Person[];
  selectedPerson: PersonDetail | null;
  principalPersonId?: string | null;
  onSetPrincipalPerson?: (personId: string) => Promise<void>;
  onUnsetPrincipalPerson?: () => Promise<void>;
  editDisplayName: string;
  editAliasesText: string;
  editError: PeopleError | null;
  editSuccess: string | null;
  mergeGuidance: { personId: string; personName: string } | null;
  mergeToPersonId?: string;
  loading: boolean;
  mobileDetailOpen: boolean;
  setMobileDetailOpen: (open: boolean) => void;
  onSelectPerson: (p: Person) => void;
  onChangeEditDisplayName: (name: string) => void;
  onChangeEditAliasesText: (text: string) => void;
  onUpdatePerson: () => void;
  onTriggerDeleteConfirm: (p: PersonDetail) => void;
  onTriggerMergeModal?: (p: PersonDetail) => void;
  onChangeMergeToPersonId?: (id: string) => void;
  onTriggerMergePreview?: (from: Person, to: Person) => void;
  onTriggerAliasDelete: (alias: PersonAlias) => void;
  personRelations?: PersonRelation[];
  relationStatusFilter?: RelationStatus | "all";
  onRelationStatusFilterChange?: (status: RelationStatus | "all") => void;
  onOpenCreateRelationModal?: () => void;
  onOpenEditRelationModal?: (relation: PersonRelation) => void;
  onDeleteRelation?: (relationId: string) => Promise<void>;
  personProperties?: PersonPropertyValue[];
  propertyDefinitions?: PersonPropertyDefinition[];
  onCreateProperty?: (req: PersonPropertyValueCreateRequest) => Promise<void>;
  onUpdateProperty?: (propertyValueId: string, req: PersonPropertyValueUpdateRequest) => Promise<void>;
  onDeleteProperty?: (propertyValueId: string) => Promise<void>;
  onBulkSaveProperty?: (propertyDefinitionId: string, req: PersonPropertyBulkSaveRequest) => Promise<void>;
}

export default function PeopleListTab({
  people,
  selectedPerson,
  principalPersonId = null,
  onSetPrincipalPerson = async () => {},
  onUnsetPrincipalPerson = async () => {},
  editDisplayName,
  editAliasesText,
  editError,
  editSuccess,
  mergeGuidance,
  mergeToPersonId = "",
  loading,
  mobileDetailOpen,
  setMobileDetailOpen,
  onSelectPerson,
  onChangeEditDisplayName,
  onChangeEditAliasesText,
  onUpdatePerson,
  onTriggerDeleteConfirm,
  onTriggerMergeModal = () => {},
  onChangeMergeToPersonId = () => {},
  onTriggerMergePreview = () => {},
  onTriggerAliasDelete,
  personRelations = [],
  relationStatusFilter = "all",
  onRelationStatusFilterChange = () => {},
  onOpenCreateRelationModal = () => {},
  onOpenEditRelationModal = () => {},
  onDeleteRelation = async () => {},
  personProperties = [],
  propertyDefinitions = [],
  onCreateProperty = async () => {},
  onUpdateProperty = async () => {},
  onDeleteProperty = async () => {},
  onBulkSaveProperty = async () => {},
}: PeopleListTabProps) {
  const [nameQuery, setNameQuery] = useState("");
  const [personMemories, setPersonMemories] = useState<Memory[]>([]);
  const [loadingMemories, setLoadingMemories] = useState(false);
  const [memoriesError, setMemoriesError] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (!selectedPerson?.person_id) {
      setPersonMemories([]);
      setMemoriesError(null);
      return;
    }
    let cancelled = false;
    setLoadingMemories(true);
    setMemoriesError(null);
    (async () => {
      try {
        const res = await listMemories({ person_id: selectedPerson.person_id });
        if (!cancelled) setPersonMemories(res.items);
      } catch (e) {
        if (!cancelled) {
          const msg = e instanceof ApiError ? e.message : "人物メモリの取得に失敗しました";
          setMemoriesError(msg);
          setPersonMemories([]);
        }
      } finally {
        if (!cancelled) setLoadingMemories(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedPerson?.person_id]);

  const filteredPeople = useMemo(() => {
    const query = nameQuery.trim().toLowerCase();
    if (query.length === 0) return people;
    // 検索対象: 主たる名前（表示名・正規化名）＋別名（表示名・正規化名）。
    // vault_id は検索対象外。
    return people.filter((person) =>
      [
        person.display_name,
        person.normalized_name,
        ...(person.aliases ?? []).flatMap((alias) => [alias.display_name, alias.normalized_name]),
      ].some((text) => text.toLowerCase().includes(query)),
    );
  }, [people, nameQuery]);

  return (
    <>
      <div
        className={`flex w-full flex-col overflow-y-auto rounded-lg border border-slate-200 bg-white p-4 lg:w-1/3 ${
          mobileDetailOpen ? "hidden" : "flex"
        } lg:flex`}
      >
        <h2 className="mb-3 text-sm font-semibold">登録人物一覧</h2>
        <input
          type="search"
          value={nameQuery}
          onChange={(e) => setNameQuery(e.target.value)}
          aria-label="人物名で検索"
          placeholder="名前で検索"
          className="mb-3 w-full rounded border border-slate-300 px-2.5 py-1.5 text-xs focus:border-slate-900 focus:outline-none"
        />
        {people.length === 0 ? (
          <p className="text-xs text-slate-400">現在、登録されている人物はいません。</p>
        ) : filteredPeople.length === 0 ? (
          <p className="text-xs text-slate-400">検索条件に一致する人物はいません。</p>
        ) : (
          <div className="space-y-2">
            {filteredPeople.map((p) => {
              const isSelected = selectedPerson?.person_id === p.person_id;
              const isPrincipal = principalPersonId === p.person_id;
              return (
                <button
                  key={p.person_id}
                  onClick={() => onSelectPerson(p)}
                  data-selected={isSelected || undefined}
                  className={`w-full text-left p-2.5 rounded-lg border text-xs transition-all cursor-pointer ${
                    isSelected
                      ? "border-slate-800 bg-slate-200 border-l-4 font-medium"
                      : "border-slate-200 hover:bg-slate-50"
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5">
                      <span>{p.display_name}</span>
                      {isPrincipal && (
                        <span className="bg-indigo-100 text-indigo-800 text-[9px] px-1.5 py-0.5 rounded-full font-bold">
                          本人
                        </span>
                      )}
                    </div>
                    {p.vault_id ? (
                      <span className="bg-slate-100 text-slate-800 text-[9px] px-1.5 py-0.5 rounded-full font-mono">{p.vault_id}</span>
                    ) : (
                      <span className="bg-red-50 text-red-700 text-[9px] px-1.5 py-0.5 rounded-full">未連携</span>
                    )}
                  </div>
                  <div className="flex items-center justify-between mt-1 text-[10px] text-slate-400">
                    <span>サマリ: {p.summary_count ?? 0}件</span>
                  </div>
                  {p.aliases && p.aliases.length > 0 && (
                    <div className="text-[10px] text-slate-400 mt-1">
                      別名: {p.aliases.map((al) => al.display_name).join(", ")}
                    </div>
                  )}
                </button>
              );
            })}
          </div>
        )}
      </div>

      <div
        className={`w-full overflow-y-auto rounded-lg border border-slate-200 bg-white p-4 lg:flex-1 ${
          mobileDetailOpen ? "flex flex-col" : "hidden"
        } lg:flex`}
      >
        {mobileDetailOpen && (
          <div className="flex items-center gap-2 border-b border-slate-200 pb-2 lg:hidden">
            <button
              type="button"
              onClick={() => setMobileDetailOpen(false)}
              aria-label="一覧に戻る"
              className="rounded px-2 py-1 text-sm text-slate-600 hover:bg-slate-100 cursor-pointer"
            >
              ← 一覧
            </button>
            <span className="truncate text-sm font-semibold text-slate-700">
              人物詳細
            </span>
          </div>
        )}
        {selectedPerson ? (
          <div className="space-y-4">
            <div className="flex items-start justify-between gap-2">
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="text-base font-bold">{selectedPerson.display_name}</h2>
                  {principalPersonId === selectedPerson.person_id && (
                    <span className="bg-indigo-100 text-indigo-800 text-xs px-2 py-0.5 rounded-full font-bold">
                      本人
                    </span>
                  )}
                </div>
                <p className="text-xs text-slate-400">ID: {selectedPerson.person_id} | 正規化名: {selectedPerson.normalized_name}</p>
                {selectedPerson.vault_id && (
                  <p className="text-xs text-slate-500 mt-1">Vault 接続ID: <code className="bg-slate-100 px-1 rounded">{selectedPerson.vault_id}</code></p>
                )}
              </div>
              <div className="flex items-center gap-1.5 shrink-0">
                {principalPersonId === selectedPerson.person_id ? (
                  <button
                    type="button"
                    onClick={() => onUnsetPrincipalPerson()}
                    disabled={loading}
                    title="本人設定を解除"
                    aria-label="本人設定を解除"
                    className="flex items-center gap-1 rounded bg-slate-900 px-3 py-1 text-sm text-white hover:bg-slate-800 transition-colors disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
                  >
                    本人設定を解除
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => onSetPrincipalPerson(selectedPerson.person_id)}
                    disabled={loading}
                    title="本人に設定"
                    aria-label="本人に設定"
                    className="flex items-center gap-1 rounded bg-blue-600 px-3 py-1 text-sm text-white hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
                  >
                    本人に設定
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => onTriggerMergeModal(selectedPerson)}
                  disabled={loading}
                  title="この人物を別の人物へ統合"
                  aria-label="この人物を別の人物へ統合"
                  className="flex items-center gap-1 rounded bg-blue-600 px-3 py-1 text-sm text-white hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
                >
                  <GitMerge className="w-4 h-4" />
                </button>
                <button
                  type="button"
                  onClick={() => onTriggerDeleteConfirm(selectedPerson)}
                  disabled={loading}
                  title="この人物を完全に削除"
                  aria-label="この人物を完全に削除"
                  className="flex items-center gap-1 rounded bg-rose-800 px-3 py-1 text-sm text-white hover:bg-rose-900 transition-colors disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            </div>

            {selectedPerson.aliases && selectedPerson.aliases.length > 0 && (
              <div>
                <h3 className="text-xs font-bold text-slate-700 mb-1.5">確定済み別名 (person_aliases)</h3>
                <div className="flex flex-wrap gap-1.5">
                  {selectedPerson.aliases.map((al) => (
                    <span key={al.normalized_name} className="inline-flex items-center gap-1 bg-slate-100 text-slate-800 text-xs px-2 py-0.5 rounded border border-slate-200">
                      {al.display_name}
                      <button
                        onClick={() => onTriggerAliasDelete(al)}
                        disabled={loading}
                        className={`text-slate-400 hover:text-red-600 transition-colors leading-none disabled:opacity-50 ${
                          loading ? "disabled:cursor-not-allowed" : "cursor-pointer"
                        }`}
                        aria-label={`別名「${al.display_name}」を削除`}
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Edit Form (Unlinked Only) */}
            {selectedPerson.vault_id === null && (
              <div className="border border-slate-200 rounded-lg p-4 bg-slate-50 space-y-3">
                <h3 className="text-xs font-bold text-slate-800">未連携人物の編集</h3>
                {editError && (
                  <div className="rounded-lg bg-red-50 p-3 text-xs font-medium text-red-800 border border-red-200">
                    <div className="font-bold">
                      {editError.message}
                    </div>
                    {editError.conflict_type && (
                      <div className="mt-1 text-[11px] text-red-600">
                        競合の型: {editError.conflict_type}
                        {editError.existing_person_id && ` (競合人物ID: ${editError.existing_person_id}, 名前: ${editError.existing_person_name})`}
                      </div>
                    )}
                    {mergeGuidance && (
                      <div className="mt-2 text-[11px] text-amber-800 bg-amber-50 border border-amber-200 rounded p-2">
                        同一人物の可能性があるため、統合を検討してください。
                        統合先には競合人物（{mergeGuidance.personName}）を選択済みです。
                      </div>
                    )}
                  </div>
                )}
                {editSuccess && (
                  <div className="rounded-lg bg-green-50 p-3 text-xs font-medium text-green-800 border border-green-200">
                    {editSuccess}
                  </div>
                )}
                <div className="space-y-2">
                  <div>
                    <label className="block text-[11px] font-bold text-slate-700 mb-1" htmlFor="edit-name">表示名</label>
                    <input
                      id="edit-name"
                      type="text"
                      value={editDisplayName}
                      onChange={(e) => onChangeEditDisplayName(e.target.value)}
                      className="w-full rounded border border-slate-300 bg-white px-2.5 py-1.5 text-xs focus:border-slate-900 focus:outline-none"
                      placeholder="表示名を入力してください"
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] font-bold text-slate-700 mb-1" htmlFor="edit-aliases">別名 (1行に1別名を入力してください)</label>
                    <textarea
                      id="edit-aliases"
                      value={editAliasesText}
                      onChange={(e) => onChangeEditAliasesText(e.target.value)}
                      rows={3}
                      className="w-full rounded border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-mono focus:border-slate-900 focus:outline-none"
                      placeholder="別名を1行ずつ入力してください"
                    />
                  </div>
                </div>
                <div className="flex justify-end">
                  <button
                    onClick={onUpdatePerson}
                    disabled={loading || !editDisplayName.trim()}
                    className={`rounded bg-slate-900 px-4 py-1.5 text-xs text-white hover:bg-slate-800 disabled:opacity-50 ${
                      loading || !editDisplayName.trim() ? "disabled:cursor-not-allowed" : "cursor-pointer"
                    }`}
                  >
                    変更内容を保存
                  </button>
                </div>
              </div>
            )}

            {/* Person Properties Section */}
            <PersonPropertiesSection
              personId={selectedPerson.person_id}
              properties={personProperties}
              definitions={propertyDefinitions}
              loading={loading}
              onCreateProperty={onCreateProperty}
              onUpdateProperty={onUpdateProperty}
              onDeleteProperty={onDeleteProperty}
              onBulkSaveProperty={onBulkSaveProperty}
            />

            {/* Person Relations Section */}
            <PersonRelationsSection
              currentPerson={selectedPerson}
              relations={personRelations}
              peopleList={people}
              statusFilter={relationStatusFilter}
              onStatusFilterChange={onRelationStatusFilterChange}
              onOpenCreateModal={onOpenCreateRelationModal}
              onOpenEditModal={onOpenEditRelationModal}
              onDeleteRelation={onDeleteRelation}
              onSelectPerson={onSelectPerson}
            />

            {/* Person Memories Section */}
            <div className="border border-slate-200 rounded-lg p-3 bg-white">
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-xs font-bold text-slate-700">人物メモリ ({personMemories.length})</h3>
                <button
                  type="button"
                  onClick={() => navigate(`/memories?person_id=${selectedPerson.person_id}`)}
                  className="text-xs text-blue-600 hover:underline flex items-center gap-1 cursor-pointer font-medium"
                >
                  メモリ画面で見る →
                </button>
              </div>
              {memoriesError && <p className="text-xs text-red-600">{memoriesError}</p>}
              {loadingMemories ? (
                <p className="text-xs text-slate-400">読み込み中…</p>
              ) : personMemories.length === 0 ? (
                <p className="text-xs text-slate-400">人物メモリはありません。</p>
              ) : (
                <div className="border border-slate-100 rounded-lg overflow-hidden divide-y divide-slate-100">
                  {personMemories.map((m) => (
                    <div key={m.memory_id} className="p-2.5 text-xs bg-slate-50/50">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="rounded bg-indigo-100 text-indigo-800 text-[10px] font-medium px-1.5 py-0.5">
                          {m.status === "approved" ? "承認済み" : m.status === "candidate" ? "候補" : m.status}
                        </span>
                        <span className="rounded bg-slate-200 text-slate-700 text-[10px] px-1.5 py-0.5">
                          {m.kind || "fact"}
                        </span>
                      </div>
                      <div className="text-slate-800 font-medium whitespace-pre-wrap">{m.content}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div>
              <h3 className="text-xs font-bold text-slate-700 mb-2">紐づくサマリ ({selectedPerson.summaries.length})</h3>
              {selectedPerson.summaries.length === 0 ? (
                <p className="text-xs text-slate-400">紐づいているサマリはありません。</p>
              ) : (
                <div className="border border-slate-100 rounded-lg overflow-hidden divide-y divide-slate-100">
                  {selectedPerson.summaries.map((sum) => (
                    <div key={sum.summary_id} className="p-3 text-xs flex justify-between items-start">
                      <div>
                        <div className="font-semibold">{sum.period_key} ({sum.period_type})</div>
                        {sum.note && <div className="text-slate-600 mt-1 font-mono bg-slate-50 p-1.5 rounded">{sum.note}</div>}
                      </div>
                      <div className="text-[10px] text-slate-400">表示順: {sum.display_order}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="h-full flex items-center justify-center text-xs text-slate-400">
            人物を選択すると詳細が表示されます。
          </div>
        )}
      </div>
    </>
  );
}
