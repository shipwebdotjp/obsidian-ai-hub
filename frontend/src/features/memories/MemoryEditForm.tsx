import { useState } from "react";
import { ApiError, editMemory } from "../../api/client";
import type { EditPayload, Memory, MemoryDetail, Person, Stability } from "../../api/types";

const STABILITIES: Stability[] = ["stable", "tentative", "explicitly_settled"];

export interface MemoryEditFormProps {
  memory: Memory | MemoryDetail;
  peopleOptions?: Person[];
  onUpdated: (memory: Memory) => void;
  notify: (msg: string, kind?: "info" | "error") => void;
  onCancel: () => void;
}

export default function MemoryEditForm({ memory, peopleOptions = [], onUpdated, notify, onCancel }: MemoryEditFormProps) {
  const [content, setContent] = useState(memory.content);
  const [topicsText, setTopicsText] = useState((memory.topics || []).join(", "));
  const [tagsText, setTagsText] = useState((memory.tags || []).join(", "));
  const [validFrom, setValidFrom] = useState(memory.valid_from || "");
  const [validUntil, setValidUntil] = useState(memory.valid_until || "");
  const [reviewDueAt, setReviewDueAt] = useState(memory.review_due_at || "");
  const [stability, setStability] = useState<Stability>(memory.stability || "stable");
  const [selectedPersonIds, setSelectedPersonIds] = useState<string[]>(
    (memory.people || []).map((p) => p.person_id)
  );
  const [busy, setBusy] = useState(false);

  function splitList(value: string): string[] {
    return value
      .split(/[,\n]/)
      .map((s) => s.trim())
      .filter(Boolean);
  }

  function togglePerson(personId: string) {
    if (selectedPersonIds.includes(personId)) {
      setSelectedPersonIds(selectedPersonIds.filter((id) => id !== personId));
    } else {
      setSelectedPersonIds([...selectedPersonIds, personId]);
    }
  }

  async function save() {
    if (memory.scope === "person" && selectedPersonIds.length === 0) {
      notify("人物メモリには最低1人の関連人物が必要です", "error");
      return;
    }
    setBusy(true);
    const payload: EditPayload = {
      content: content.trim(),
      topics: splitList(topicsText),
      tags: splitList(tagsText),
      stability,
      valid_from: validFrom || null,
      valid_until: validUntil || null,
      review_due_at: reviewDueAt || null,
      person_ids: selectedPersonIds,
    };

    try {
      const res = await editMemory(memory.memory_id, payload);
      onUpdated(res.memory);
      notify("編集を保存して承認しました");
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "編集に失敗しました";
      notify(msg, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold">編集して承認</h3>
      <label className="block text-xs text-slate-500">本文</label>
      <textarea
        className="w-full rounded border border-slate-300 p-2 text-sm"
        rows={4}
        value={content}
        onChange={(e) => setContent(e.target.value)}
      />
      {(memory.scope === "person" || peopleOptions.length > 0) && (
        <div>
          <label className="block text-xs text-slate-500 mb-1">関連人物 {memory.scope === "person" && "(必須: 1人以上)"}</label>
          {peopleOptions.length === 0 ? (
            <p className="text-xs text-red-600">人物一覧の取得に失敗しました。人物メモリは保存できません。</p>
          ) : (
          <div className="flex flex-wrap gap-2 max-h-32 overflow-y-auto border border-slate-200 rounded p-2 bg-slate-50">
            {peopleOptions.map((p) => {
              const checked = selectedPersonIds.includes(p.person_id);
              return (
                <label key={p.person_id} className={`inline-flex items-center gap-1 text-xs px-2 py-1 rounded cursor-pointer border ${checked ? "bg-indigo-100 border-indigo-300 text-indigo-900 font-medium" : "bg-white border-slate-200 text-slate-700"}`}>
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => togglePerson(p.person_id)}
                    className="cursor-pointer"
                  />
                  <span>{p.display_name}</span>
                </label>
              );
            })}
          </div>
          )}
        </div>
      )}
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <div>
          <label className="block text-xs text-slate-500">Topics (カンマ区切り)</label>
          <input
            className="w-full rounded border border-slate-300 p-2 text-sm"
            value={topicsText}
            onChange={(e) => setTopicsText(e.target.value)}
          />
        </div>
        <div>
          <label className="block text-xs text-slate-500">Tags (カンマ区切り)</label>
          <input
            className="w-full rounded border border-slate-300 p-2 text-sm"
            value={tagsText}
            onChange={(e) => setTagsText(e.target.value)}
          />
        </div>
        <div>
          <label className="block text-xs text-slate-500">valid_from</label>
          <input
            type="date"
            className="w-full rounded border border-slate-300 p-2 text-sm"
            value={validFrom}
            onChange={(e) => setValidFrom(e.target.value)}
          />
        </div>
        <div>
          <label className="block text-xs text-slate-500">valid_until</label>
          <input
            type="date"
            className="w-full rounded border border-slate-300 p-2 text-sm"
            value={validUntil}
            onChange={(e) => setValidUntil(e.target.value)}
          />
        </div>
        <div>
          <label className="block text-xs text-slate-500">review_due_at</label>
          <input
            type="date"
            className="w-full rounded border border-slate-300 p-2 text-sm"
            value={reviewDueAt}
            onChange={(e) => setReviewDueAt(e.target.value)}
          />
        </div>
        <div>
          <label className="block text-xs text-slate-500">stability</label>
          <select
            className="w-full cursor-pointer rounded border border-slate-300 p-2 text-sm"
            value={stability}
            onChange={(e) => setStability(e.target.value as Stability)}
          >
            {STABILITIES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          disabled={busy}
          className="cursor-pointer rounded border border-slate-300 px-3 py-1 text-sm disabled:cursor-not-allowed disabled:opacity-50"
        >
          キャンセル
        </button>
        <button
          type="button"
          onClick={save}
          disabled={busy || !content.trim() || (memory.scope === "person" && peopleOptions.length === 0)}
          className="cursor-pointer rounded bg-slate-900 px-3 py-1 text-sm text-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? "保存中…" : "編集して承認"}
        </button>
      </div>
    </div>
  );
}
