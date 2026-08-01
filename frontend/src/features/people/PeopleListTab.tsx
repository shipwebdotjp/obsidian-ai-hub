import React from "react";
import { Person, PersonAlias } from "../../api/types";
import { PersonDetail } from "./types";

interface PeopleListTabProps {
  people: Person[];
  selectedPerson: PersonDetail | null;
  editDisplayName: string;
  editAliasesText: string;
  editError: any | null;
  editSuccess: string | null;
  mergeGuidance: { personId: string; personName: string } | null;
  mergeToPersonId: string;
  loading: boolean;
  mobileDetailOpen: boolean;
  setMobileDetailOpen: (open: boolean) => void;
  onSelectPerson: (p: Person) => void;
  onChangeEditDisplayName: (name: string) => void;
  onChangeEditAliasesText: (text: string) => void;
  onUpdatePerson: () => void;
  onTriggerDeleteConfirm: (p: PersonDetail) => void;
  onChangeMergeToPersonId: (id: string) => void;
  onTriggerMergePreview: (from: Person, to: Person) => void;
  onTriggerAliasDelete: (alias: PersonAlias) => void;
}

export default function PeopleListTab({
  people,
  selectedPerson,
  editDisplayName,
  editAliasesText,
  editError,
  editSuccess,
  mergeGuidance,
  mergeToPersonId,
  loading,
  mobileDetailOpen,
  setMobileDetailOpen,
  onSelectPerson,
  onChangeEditDisplayName,
  onChangeEditAliasesText,
  onUpdatePerson,
  onTriggerDeleteConfirm,
  onChangeMergeToPersonId,
  onTriggerMergePreview,
  onTriggerAliasDelete,
}: PeopleListTabProps) {
  return (
    <>
      <div
        className={`flex w-full flex-col overflow-y-auto rounded-lg border border-slate-200 bg-white p-4 lg:w-1/3 ${
          mobileDetailOpen ? "hidden" : "flex"
        } lg:flex`}
      >
        <h2 className="mb-3 text-sm font-semibold">登録人物一覧</h2>
        {people.length === 0 ? (
          <p className="text-xs text-slate-400">現在、登録されている人物はいません。</p>
        ) : (
          <div className="space-y-2">
            {people.map((p) => (
              <button
                key={p.person_id}
                onClick={() => onSelectPerson(p)}
                className={`w-full text-left p-2.5 rounded-lg border text-xs transition-all ${
                  selectedPerson?.person_id === p.person_id
                    ? "border-slate-900 bg-slate-50 font-medium"
                    : "border-slate-200 hover:bg-slate-50"
                }`}
              >
                <div className="flex items-center justify-between">
                  <span>{p.display_name}</span>
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
            ))}
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
              className="rounded px-2 py-1 text-sm text-slate-600 hover:bg-slate-100"
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
            <div>
              <h2 className="text-base font-bold">{selectedPerson.display_name}</h2>
              <p className="text-xs text-slate-400">ID: {selectedPerson.person_id} | 正規化名: {selectedPerson.normalized_name}</p>
              {selectedPerson.vault_id && (
                <p className="text-xs text-slate-500 mt-1">Vault 接続ID: <code className="bg-slate-100 px-1 rounded">{selectedPerson.vault_id}</code></p>
              )}
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
                        className="text-slate-400 hover:text-red-600 transition-colors leading-none"
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
                      {typeof editError === "object" ? editError.message : editError}
                    </div>
                    {typeof editError === "object" && editError.conflict_type && (
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
                    className="rounded bg-slate-900 px-4 py-1.5 text-xs text-white hover:bg-slate-800 disabled:opacity-50"
                  >
                    変更内容を保存
                  </button>
                </div>
              </div>
            )}

            {/* Complete Deletion Section */}
            <div className="border border-red-200 rounded-lg p-4 bg-red-50/50 space-y-3">
              <h3 className="text-xs font-bold text-red-800">人物の完全削除 (危険操作)</h3>
              <p className="text-[10px] text-red-600 leading-normal">
                この操作を実行すると、人物データ本体に加えて、3つの関連テーブル（サマリ紐づき、確定別名、文脈別手動割当）からも関連行が完全に削除されます。サマリ本体や、Vault内のMarkdownファイル自体は削除されません。
              </p>
              <div className="flex justify-end">
                <button
                  onClick={() => onTriggerDeleteConfirm(selectedPerson)}
                  disabled={loading}
                  className="rounded bg-red-600 px-4 py-1.5 text-xs text-white hover:bg-red-700 disabled:opacity-50"
                >
                  完全に削除する
                </button>
              </div>
            </div>

            {/* Merge with another person section */}
            <div className="border border-slate-200 rounded-lg p-4 bg-slate-50 space-y-3">
              <h3 className="text-xs font-bold text-slate-800">この人物を別の人物へ統合</h3>
              <div className="flex flex-col gap-2 sm:flex-row">
                <select
                  value={mergeToPersonId}
                  onChange={(e) => onChangeMergeToPersonId(e.target.value)}
                  className="w-full rounded border border-slate-300 bg-white px-2.5 py-1.5 text-xs focus:border-slate-900 focus:outline-none sm:flex-1"
                >
                  <option value="">-- 統合先（残す）の人物を選択してください --</option>
                  {people
                    .filter((p) => p.person_id !== selectedPerson.person_id)
                    .map((p) => (
                      <option key={p.person_id} value={p.person_id}>
                        {p.display_name} {p.vault_id ? `(${p.vault_id})` : "(未連携)"}
                      </option>
                    ))}
                </select>
                <button
                  onClick={() => {
                    const target = people.find((p) => p.person_id === mergeToPersonId);
                    if (target) {
                      onTriggerMergePreview(selectedPerson, target);
                    }
                  }}
                  disabled={loading || !mergeToPersonId}
                  className="shrink-0 rounded bg-slate-900 px-4 py-1.5 text-xs text-white hover:bg-slate-800 disabled:opacity-50"
                >
                  統合プレビュー
                </button>
              </div>
              <p className="text-[10px] text-slate-400">
                ※ 統合元（この人物）のサマリー履歴や別名はすべて統合先にマージされ、統合元は削除されます。異なる Vault ID を持つ人物同士の統合や、連携済みから未連携への統合は拒否されます。
              </p>
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
