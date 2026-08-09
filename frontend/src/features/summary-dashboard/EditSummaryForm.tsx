import type {
  SummaryDetail,
  SummaryUpdatePayload,
  EditOptionsResponse,
  Person,
} from "../../api/types";

export function EditSummaryForm({
  summary,
  form,
  setForm,
  editOptions,
  allPeople,
  saving,
  onSave,
  onCancel,
}: {
  summary: SummaryDetail;
  form: SummaryUpdatePayload;
  setForm: (f: SummaryUpdatePayload) => void;
  editOptions: EditOptionsResponse | null;
  allPeople: Person[];
  saving: boolean;
  onSave: () => void;
  onCancel: () => void;
}) {
  const allowedKinds = editOptions?.item_kinds[summary.period_type] ?? [];

  // Group edit items by kind, including empty kinds
  const itemsByKind = allowedKinds.map((kind) => ({
    kind,
    items: (form.items ?? []).filter((it) => it.kind === kind),
  }));

  const updateItemBody = (kind: string, index: number, body: string) => {
    const items = [...(form.items ?? [])];
    const kindItems = items.filter((it) => it.kind === kind);
    const otherItems = items.filter((it) => it.kind !== kind);
    if (kindItems[index]) {
      kindItems[index] = { ...kindItems[index], body };
    }
    setForm({ ...form, items: [...otherItems, ...kindItems] });
  };

  const addItem = (kind: string) => {
    const items = [...(form.items ?? [])];
    items.push({ kind, body: "", display_order: items.length });
    setForm({ ...form, items });
  };

  const removeItem = (kind: string, index: number) => {
    const items = [...(form.items ?? [])];
    const kindItems = items.filter((it) => it.kind === kind);
    const otherItems = items.filter((it) => it.kind !== kind);
    kindItems.splice(index, 1);
    setForm({ ...form, items: [...otherItems, ...kindItems] });
  };

  const moveItem = (kind: string, index: number, direction: -1 | 1) => {
    const items = [...(form.items ?? [])];
    const kindItems = items.filter((it) => it.kind === kind);
    const otherItems = items.filter((it) => it.kind !== kind);
    const newIndex = index + direction;
    if (newIndex < 0 || newIndex >= kindItems.length) return;
    const [moved] = kindItems.splice(index, 1);
    kindItems.splice(newIndex, 0, moved);
    setForm({ ...form, items: [...otherItems, ...kindItems] });
  };

  const toggleTopic = (topic: string) => {
    const topics = [...(form.topics ?? [])];
    const idx = topics.indexOf(topic);
    if (idx >= 0) {
      topics.splice(idx, 1);
    } else if (topics.length < 5) {
      topics.push(topic);
    }
    setForm({ ...form, topics });
  };

  const addKeyword = (value: string) => {
    const trimmed = value.trim();
    if (!trimmed) return;
    const keywords = [...(form.keywords ?? [])];
    if (!keywords.includes(trimmed)) {
      keywords.push(trimmed);
    }
    setForm({ ...form, keywords });
  };

  const removeKeyword = (index: number) => {
    const keywords = [...(form.keywords ?? [])];
    keywords.splice(index, 1);
    setForm({ ...form, keywords });
  };

  const togglePerson = (personId: string) => {
    const people = [...(form.people ?? [])];
    const idx = people.findIndex((p) => p.person_id === personId);
    if (idx >= 0) {
      people.splice(idx, 1);
    } else {
      people.push({ person_id: personId, note: "" });
    }
    setForm({ ...form, people });
  };

  const updatePersonNote = (personId: string, note: string) => {
    const people = [...(form.people ?? [])];
    const idx = people.findIndex((p) => p.person_id === personId);
    if (idx >= 0) {
      people[idx] = { ...people[idx], note };
    }
    setForm({ ...form, people });
  };

  // Unresolved candidates from original summary (read-only, preserved on save)
  const unresolvedCandidates = summary.people.filter(
    (p) => p.resolution_status === "unresolved"
  );

  // Rejected candidates from original summary (read-only, preserved on save)
  const rejectedCandidates = summary.people.filter(
    (p) => p.resolution_status === "rejected"
  );

  // Resolved people IDs currently selected
  const selectedPersonIds = new Set((form.people ?? []).map((p) => p.person_id));

  return (
    <div className="space-y-5">
      {/* Summary body */}
      <div>
        <label className="text-xs font-bold uppercase tracking-wider text-slate-400">本文</label>
        <textarea
          value={form.summary ?? ""}
          onChange={(e) => setForm({ ...form, summary: e.target.value })}
          rows={4}
          className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-xs focus:border-blue-500 focus:outline-none resize-y"
        />
      </div>

      {/* Topics */}
      {editOptions && (
        <div>
          <label className="text-xs font-bold uppercase tracking-wider text-slate-400">トピック (最大5)</label>
          <div className="mt-1 flex flex-wrap gap-1">
            {editOptions.topics.map((t) => (
              <button
                key={t}
                onClick={() => toggleTopic(t)}
                className={`rounded px-2 py-0.5 text-xs font-medium cursor-pointer ${
                  (form.topics ?? []).includes(t)
                    ? "bg-emerald-500 text-white"
                    : "bg-emerald-50 text-emerald-700 hover:bg-emerald-100"
                }`}
              >
                {t}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Keywords */}
      <div>
          <label className="text-xs font-bold uppercase tracking-wider text-slate-400">キーワード</label>
        <div className="mt-1 flex flex-wrap gap-1">
          {(form.keywords ?? []).map((k, i) => (
            <span key={`${k}-${i}`} className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-600 font-medium flex items-center gap-1">
              {k}
              <button onClick={() => removeKeyword(i)} className="text-slate-400 hover:text-slate-600 cursor-pointer">&times;</button>
            </span>
          ))}
          <input
            type="text"
            placeholder="追加してEnter"
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                addKeyword((e.target as HTMLInputElement).value);
                (e.target as HTMLInputElement).value = "";
              }
            }}
            className="rounded border border-slate-300 px-2 py-0.5 text-xs focus:border-blue-500 focus:outline-none w-24"
          />
        </div>
      </div>

      {/* Mood / Sleep (day only) */}
      {summary.period_type === "day" && (
        <div className="flex flex-col gap-4 sm:flex-row">
          <div className="flex-1">
            <label className="text-xs font-bold uppercase tracking-wider text-slate-400">気分</label>
            <input
              type="text"
              value={form.mood ?? ""}
              onChange={(e) => setForm({ ...form, mood: e.target.value || null })}
              placeholder="空でクリア"
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-xs focus:border-blue-500 focus:outline-none"
            />
          </div>
          <div className="flex-1">
            <label className="text-xs font-bold uppercase tracking-wider text-slate-400">睡眠</label>
            <input
              type="text"
              value={form.sleep_raw ?? ""}
              onChange={(e) => setForm({ ...form, sleep_raw: e.target.value || null })}
              placeholder="空でクリア"
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-xs focus:border-blue-500 focus:outline-none"
            />
          </div>
        </div>
      )}

      {/* Items by kind */}
      <div className="space-y-3">
        <label className="text-xs font-bold uppercase tracking-wider text-slate-400">セクション</label>
        {itemsByKind.map(({ kind, items }) => (
          <div key={kind} className="rounded-md border border-slate-200 p-3 space-y-2">
            <h4 className="text-xs font-bold text-slate-500">{kind}</h4>
            {items.map((item, idx) => (
              <div key={`${kind}-${idx}`} className="flex gap-1 items-start">
                  <textarea
                    value={item.body}
                    onChange={(e) => updateItemBody(kind, idx, e.target.value)}
                    rows={2}
                    className="flex-1 rounded border border-slate-300 px-2 py-1 text-xs focus:border-blue-500 focus:outline-none resize-y"
                  />
                  <div className="flex flex-col gap-0.5">
                    <button onClick={() => moveItem(kind, idx, -1)} disabled={idx === 0} className="text-[10px] text-slate-400 hover:text-slate-600 disabled:opacity-30 cursor-pointer">↑</button>
                    <button onClick={() => moveItem(kind, idx, 1)} disabled={idx === items.length - 1} className="text-[10px] text-slate-400 hover:text-slate-600 disabled:opacity-30 cursor-pointer">↓</button>
                    <button onClick={() => removeItem(kind, idx)} className="text-[10px] text-red-400 hover:text-red-600 cursor-pointer">&times;</button>
                  </div>
                </div>
            ))}
            <button
              onClick={() => addItem(kind)}
              className="text-[10px] text-blue-500 hover:text-blue-700 cursor-pointer"
            >
              + フレーズを追加
            </button>
          </div>
        ))}
      </div>

      {/* People */}
      <div>
        <label className="text-xs font-bold uppercase tracking-wider text-slate-400">人物</label>
        <div className="mt-1 space-y-1">
          {allPeople.map((p) => {
            const selected = selectedPersonIds.has(p.person_id);
            const noteVal = (form.people ?? []).find((pp) => pp.person_id === p.person_id)?.note ?? "";
            return (
              <div key={p.person_id} className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={selected}
                  onChange={() => togglePerson(p.person_id)}
                  className="h-3 w-3"
                />
                <span className="text-xs text-slate-700 min-w-[80px]">{p.display_name}</span>
                {selected && (
                  <input
                    type="text"
                    value={noteVal}
                    onChange={(e) => updatePersonNote(p.person_id, e.target.value)}
                    placeholder="メモ"
                    className="flex-1 rounded border border-slate-300 px-2 py-0.5 text-[10px] focus:border-blue-500 focus:outline-none"
                  />
                )}
              </div>
            );
          })}
          {unresolvedCandidates.length > 0 && (
            <>
              <div className="text-[10px] text-slate-400 mt-2">--- 未解決候補 ---</div>
              {unresolvedCandidates.map((c) => (
                <div key={c.candidate_id ?? c.name} className="flex items-center gap-2 opacity-60">
                  <input type="checkbox" disabled className="h-3 w-3" />
                  <span className="inline-flex items-center justify-center w-4 h-4 rounded-full bg-amber-200 text-amber-800 text-[9px] font-bold flex-shrink-0" title="未解決候補" aria-label="未解決候補">?</span>
                  <span className="text-xs text-slate-500">{c.name}</span>
                  {c.note && <span className="text-xs text-slate-400">{c.note}</span>}
                </div>
              ))}
            </>
          )}
          {rejectedCandidates.length > 0 && (
            <>
              <div className="text-[10px] text-rose-400 mt-2">--- 却下済み候補 ---</div>
              {rejectedCandidates.map((c) => (
                <div key={c.candidate_id ?? c.name} className="flex items-center gap-2 opacity-80">
                  <input type="checkbox" disabled className="h-3 w-3" />
                  <span className="inline-flex items-center justify-center px-1.5 h-4 rounded bg-rose-100 text-rose-800 text-[9px] font-bold flex-shrink-0" title="却下済み" aria-label="却下済み">却下済み</span>
                  <span className="text-xs text-rose-700 font-medium">{c.name}</span>
                  {c.note && <span className="text-xs text-rose-500">{c.note}</span>}
                </div>
              ))}
            </>
          )}
        </div>
      </div>

      {/* Project Notes */}
      {(summary.project_notes ?? []).length > 0 && (
        <div>
          <label className="text-xs font-bold uppercase tracking-wider text-slate-400">プロジェクト</label>
          <div className="mt-1 space-y-1">
            {(summary.project_notes ?? []).map((pn) => {
              const noteVal = (form.project_notes ?? []).find((fp) => fp.project_id === pn.project_id)?.note ?? "";
              return (
                <div key={pn.project_id} className="flex items-center gap-2">
                  <span className="text-xs text-slate-700 min-w-[80px]">{pn.display_name}</span>
                  <input
                    type="text"
                    value={noteVal}
                    onChange={(e) => {
                      const notes = [...(form.project_notes ?? [])];
                      const idx = notes.findIndex((fp) => fp.project_id === pn.project_id);
                      if (idx >= 0) {
                        notes[idx] = { ...notes[idx], note: e.target.value };
                      } else {
                        notes.push({ project_id: pn.project_id, note: e.target.value });
                      }
                      setForm({ ...form, project_notes: notes });
                    }}
                    placeholder="活動メモ"
                    className="flex-1 rounded border border-slate-300 px-2 py-0.5 text-[10px] focus:border-blue-500 focus:outline-none"
                  />
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Save/Cancel */}
      <div className="flex gap-2 pt-2">
        <button
          onClick={onSave}
          disabled={saving}
          className="rounded-md bg-blue-600 px-4 py-1.5 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-50 cursor-pointer"
        >
          {saving ? "保存中…" : "保存"}
        </button>
        <button
          onClick={onCancel}
          disabled={saving}
          className="rounded-md border border-slate-200 bg-white px-4 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-50 cursor-pointer"
        >
          キャンセル
        </button>
      </div>
    </div>
  );
}
