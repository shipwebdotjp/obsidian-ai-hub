import type { CodingRun, SlashCandidate, SlashInvocation } from "../../../api/coding";
import {
  getChatInputPlaceholder,
  shouldSendOnEnter,
  useChatSendMode,
} from "../../settings/chatSendMode";

interface CodingChatInputProps {
  inputContent: string;
  onInputChange: (text: string) => void;
  isStreaming: boolean;
  currentRun: CodingRun | null;
  showSlashPalette: boolean;
  hasSkillsTool: boolean;
  filteredCandidates: SlashCandidate[];
  slashPaletteIndex: number;
  onSlashPaletteIndexChange: (index: number) => void;
  slashInvocation: SlashInvocation | null;
  onClearSlashInvocation: () => void;
  onSelectCandidate: (cand: SlashCandidate) => void;
  onSend: () => void | Promise<void>;
}

/** チャット入力欄とスラッシュ候補パレット・選択中スキルチップ。 */
export function CodingChatInput({
  inputContent,
  onInputChange,
  isStreaming,
  currentRun,
  showSlashPalette,
  hasSkillsTool,
  filteredCandidates,
  slashPaletteIndex,
  onSlashPaletteIndexChange,
  slashInvocation,
  onClearSlashInvocation,
  onSelectCandidate,
  onSend,
}: CodingChatInputProps) {
  const [chatSendMode] = useChatSendMode();

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    await onSend();
  };

  const handleInputKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (showSlashPalette) {
      if (e.key === "Escape") {
        e.preventDefault();
        onInputChange("");
        return;
      }
      if (hasSkillsTool && filteredCandidates.length > 0) {
        if (e.key === "ArrowDown") {
          e.preventDefault();
          onSlashPaletteIndexChange((slashPaletteIndex + 1) % filteredCandidates.length);
          return;
        }
        if (e.key === "ArrowUp") {
          e.preventDefault();
          onSlashPaletteIndexChange(
            (slashPaletteIndex - 1 + filteredCandidates.length) % filteredCandidates.length,
          );
          return;
        }
        if (e.key === "Enter") {
          e.preventDefault();
          const selected = filteredCandidates[slashPaletteIndex];
          if (selected) {
            onSelectCandidate(selected);
          }
          return;
        }
      }
    }

    if (shouldSendOnEnter(e, chatSendMode)) {
      e.preventDefault();
      void onSend();
    }
  };

  const codingPlaceholder = getChatInputPlaceholder(chatSendMode, "指示・質問を入力");

  return (
    <div className="border-t border-slate-200 bg-white p-3 relative">
      {/* Candidate Palette Popover */}
      {showSlashPalette && (
        <div className="absolute bottom-full left-3 mb-1 z-20 w-80 max-h-60 overflow-y-auto rounded-lg border border-slate-200 bg-white p-1 shadow-lg text-xs">
          {!hasSkillsTool ? (
            <div className="p-2 text-slate-500 text-center">
              skills ツールが無効なためスキルコマンドは利用できません
            </div>
          ) : filteredCandidates.length === 0 ? (
            <div className="p-2 text-slate-500 text-center">
              一致するスキルが見つかりません
            </div>
          ) : (
            filteredCandidates.map((cand, idx) => {
              const isSelected = idx === slashPaletteIndex;
              return (
                <button
                  key={cand.name}
                  type="button"
                  onClick={() => onSelectCandidate(cand)}
                  className={`w-full text-left px-2.5 py-1.5 rounded flex flex-col gap-0.5 cursor-pointer ${
                    isSelected ? "bg-slate-100 text-slate-900 font-medium" : "text-slate-700 hover:bg-slate-50"
                  }`}
                >
                  <div className="font-semibold text-slate-800">/{cand.name}</div>
                  {cand.description && (
                    <div className="text-[10px] text-slate-500 truncate">{cand.description}</div>
                  )}
                </button>
              );
            })
          )}
        </div>
      )}

      {/* Selected Skill Chip */}
      {slashInvocation && (
        <div className="mb-2 flex items-center gap-1.5">
          <span className="inline-flex items-center gap-1 rounded bg-blue-100 px-2.5 py-1 text-xs font-semibold text-blue-800 border border-blue-200">
            <span>/{slashInvocation.name}</span>
            <button
              type="button"
              onClick={onClearSlashInvocation}
              className="ml-1 rounded hover:bg-blue-200 p-0.5 text-blue-600 hover:text-blue-900 cursor-pointer"
              title="スキル選択を解除"
            >
              ✕
            </button>
          </span>
        </div>
      )}

      <form onSubmit={handleSendMessage} className="flex gap-2">
        <textarea
          rows={2}
          value={inputContent}
          onChange={(e) => onInputChange(e.target.value)}
          onKeyDown={handleInputKeyDown}
          placeholder={codingPlaceholder}
          disabled={isStreaming || currentRun?.status === "running"}
          className="flex-1 resize-none rounded-lg border border-slate-300 p-2 text-xs focus:border-slate-800 focus:outline-none disabled:bg-slate-100"
        />
        <button
          type="submit"
          disabled={
            !inputContent.trim() || isStreaming || currentRun?.status === "running"
          }
          className="rounded bg-slate-900 px-4 text-xs font-medium text-white hover:bg-slate-800 cursor-pointer disabled:cursor-not-allowed disabled:opacity-50 disabled:bg-slate-300"
        >
          送信
        </button>
      </form>
    </div>
  );
}
