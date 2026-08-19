import { useEffect, useState } from "react";
import type { PlannerProposal, PlannerProposalUpdatePayload } from "../../api/types";

interface Props {
  proposal: PlannerProposal;
  busy: boolean;
  onSave: (payload: PlannerProposalUpdatePayload) => Promise<void>;
  onPromote: () => Promise<void>;
  onReject: () => Promise<void>;
  onClose: () => void;
}

export default function ProposalDetailPanel({
  proposal,
  busy,
  onSave,
  onPromote,
  onReject,
  onClose,
}: Props) {
  const [title, setTitle] = useState(proposal.title);
  const [rationale, setRationale] = useState(proposal.rationale);
  const [kind, setKind] = useState(proposal.kind);
  const [startTime, setStartTime] = useState(proposal.start_time ?? "");
  const [endTime, setEndTime] = useState(proposal.end_time ?? "");
  const [location, setLocation] = useState(proposal.location ?? "");
  const [dueDate, setDueDate] = useState(proposal.due_date ?? "");

  useEffect(() => {
    setTitle(proposal.title);
    setRationale(proposal.rationale);
    setKind(proposal.kind);
    setStartTime(proposal.start_time ?? "");
    setEndTime(proposal.end_time ?? "");
    setLocation(proposal.location ?? "");
    setDueDate(proposal.due_date ?? "");
  }, [proposal.proposal_id, proposal.title, proposal.rationale, proposal.kind, proposal.start_time, proposal.end_time, proposal.location, proposal.due_date]);

  const handleSave = async () => {
    const payload: PlannerProposalUpdatePayload = { title, rationale, kind };
    if (kind === "calendar") {
      payload.start_time = startTime || null;
      payload.end_time = endTime || null;
      payload.location = location || null;
    } else {
      payload.due_date = dueDate || null;
    }
    await onSave(payload);
  };

  return (
    <div className="flex h-full flex-col border-l border-slate-200 bg-white">
      <div className="flex items-center justify-between border-b border-slate-200 p-3">
        <h2 className="text-sm font-semibold">AI提案の編集</h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="詳細を閉じる"
          className="cursor-pointer rounded px-2 py-1 text-sm text-slate-500 hover:bg-slate-100"
        >
          ✕
        </button>
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
        <div className="space-y-1">
          <label htmlFor="pp-title" className="block text-xs font-medium text-slate-600">
            タイトル
          </label>
          <input
            id="pp-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
          />
        </div>
        <div className="space-y-1">
          <label htmlFor="pp-kind" className="block text-xs font-medium text-slate-600">
            種類
          </label>
          <select
            id="pp-kind"
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            className="cursor-pointer rounded border border-slate-300 px-2 py-1 text-sm"
          >
            <option value="calendar">予定</option>
            <option value="reminder">リマインダー</option>
          </select>
        </div>
        {kind === "calendar" ? (
          <>
            <div className="space-y-1">
              <label htmlFor="pp-start" className="block text-xs font-medium text-slate-600">
                開始 (ISO)
              </label>
              <input
                id="pp-start"
                value={startTime}
                onChange={(e) => setStartTime(e.target.value)}
                placeholder="YYYY-MM-DDTHH:MM:SS"
                className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
              />
            </div>
            <div className="space-y-1">
              <label htmlFor="pp-end" className="block text-xs font-medium text-slate-600">
                終了 (ISO, 任意)
              </label>
              <input
                id="pp-end"
                value={endTime}
                onChange={(e) => setEndTime(e.target.value)}
                placeholder="YYYY-MM-DDTHH:MM:SS"
                className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
              />
            </div>
            <div className="space-y-1">
              <label htmlFor="pp-location" className="block text-xs font-medium text-slate-600">
                場所 (任意)
              </label>
              <input
                id="pp-location"
                value={location}
                onChange={(e) => setLocation(e.target.value)}
                className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
              />
            </div>
          </>
        ) : (
          <div className="space-y-1">
            <label htmlFor="pp-due" className="block text-xs font-medium text-slate-600">
              期限 (ISO, 任意)
            </label>
            <input
              id="pp-due"
              value={dueDate}
              onChange={(e) => setDueDate(e.target.value)}
              placeholder="YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS"
              className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
            />
          </div>
        )}
        <div className="space-y-1">
          <label htmlFor="pp-rationale" className="block text-xs font-medium text-slate-600">
            根拠
          </label>
          <textarea
            id="pp-rationale"
            value={rationale}
            onChange={(e) => setRationale(e.target.value)}
            rows={4}
            className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
          />
        </div>
        <p className="text-xs text-slate-500">
          昇格するとAppleカレンダー/リマインダーに登録されます。却下すると再利用のためfingerprintが解放されます。
        </p>
      </div>
      <div className="space-y-2 border-t border-slate-200 p-4">
        <button
          type="button"
          disabled={busy || !title.trim()}
          onClick={handleSave}
          className="cursor-pointer rounded bg-slate-900 px-3 py-1.5 text-xs text-white disabled:opacity-50"
        >
          保存
        </button>
        <div className="flex gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={onPromote}
            className="cursor-pointer rounded bg-emerald-600 px-3 py-1.5 text-xs text-white disabled:opacity-50"
          >
            Appleに登録
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={onReject}
            className="cursor-pointer rounded bg-rose-600 px-3 py-1.5 text-xs text-white disabled:opacity-50"
          >
            却下
          </button>
        </div>
      </div>
    </div>
  );
}