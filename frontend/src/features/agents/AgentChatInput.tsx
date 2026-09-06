import { useEffect, useRef, type MutableRefObject } from "react";
import { FileText, Image as ImageIcon, Plus, SendHorizontal, X } from "lucide-react";
import type {
  Agent,
  AgentPromptTemplate,
  SlashCandidate,
  SlashInvocation,
} from "../../api/types";
import {
  getChatInputPlaceholder,
  shouldSendOnEnter,
  useChatSendMode,
} from "../settings/chatSendMode";
import { MAX_AGENT_IMAGES, type PendingAttachment } from "./agentViewUtils";

interface AgentChatInputProps {
  inputText: string;
  onInputTextChange: (text: string) => void;
  isStreaming: boolean;
  selectedSessionId: string | null;
  activeAgent: Agent | undefined;
  isDragOver: boolean;
  pendingAttachments: PendingAttachment[];
  onRemoveAttachment: (index: number) => void;
  selectedSkill: SlashInvocation | null;
  onClearSkill: () => void;
  isPaletteActive: boolean;
  filteredCandidates: SlashCandidate[];
  skillCandidates: SlashCandidate[];
  templateCandidates: SlashCandidate[];
  paletteOrderedCandidates: SlashCandidate[];
  paletteSelectedIndex: number;
  onPaletteSelectedIndexChange: React.Dispatch<React.SetStateAction<number>>;
  hasSkillsTool: boolean;
  onSelectCandidate: (candidate: SlashCandidate) => void;
  onSelectTemplate: (content: string) => void;
  plusMenuOpen: boolean;
  onTogglePlusMenu: () => void;
  onOpenTemplateSelector: () => void;
  templateSelectorOpen: boolean;
  promptTemplates: AgentPromptTemplate[];
  attachmentReadsPending: number;
  imageInputRef: MutableRefObject<HTMLInputElement | null>;
  onClosePlusMenu: () => void;
  onFilesSelected: (files: FileList | File[] | null) => void;
  onSend: () => void;
  onCancelRun: () => void;
  onDismissPalette: () => void;
  onPaste: (e: React.ClipboardEvent<HTMLTextAreaElement>) => void;
  onFormDragOver: (e: React.DragEvent<HTMLFormElement>) => void;
  onFormDragLeave: (e: React.DragEvent<HTMLFormElement>) => void;
  onFormDrop: (e: React.DragEvent<HTMLFormElement>) => void;
}

/** チャット入力フッター（添付・スキルチップ・パレット・送信操作）。 */
export function AgentChatInput({
  inputText,
  onInputTextChange,
  isStreaming,
  selectedSessionId,
  activeAgent,
  isDragOver,
  pendingAttachments,
  onRemoveAttachment,
  selectedSkill,
  onClearSkill,
  isPaletteActive,
  filteredCandidates,
  skillCandidates,
  templateCandidates,
  paletteOrderedCandidates,
  paletteSelectedIndex,
  onPaletteSelectedIndexChange,
  hasSkillsTool,
  onSelectCandidate,
  onSelectTemplate,
  plusMenuOpen,
  onTogglePlusMenu,
  onOpenTemplateSelector,
  templateSelectorOpen,
  promptTemplates,
  attachmentReadsPending,
  imageInputRef,
  onClosePlusMenu,
  onFilesSelected,
  onSend,
  onCancelRun,
  onDismissPalette,
  onPaste,
  onFormDragOver,
  onFormDragLeave,
  onFormDrop,
}: AgentChatInputProps) {
  const [chatSendMode] = useChatSendMode();
  const chatInputRef = useRef<HTMLTextAreaElement>(null);
  const plusMenuRef = useRef<HTMLDivElement | null>(null);

  const focusInputSoon = () => {
    setTimeout(() => {
      chatInputRef.current?.focus();
    }, 0);
  };

  const handleSelectCandidateAndFocus = (candidate: SlashCandidate) => {
    onSelectCandidate(candidate);
    focusInputSoon();
  };

  const handleSelectTemplateAndFocus = (content: string) => {
    onSelectTemplate(content);
    focusInputSoon();
  };

  const handleSendMessage = (e: React.FormEvent) => {
    e.preventDefault();
    void onSend();
  };

  const handleInputKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.nativeEvent.isComposing || e.keyCode === 229) return;

    if (isPaletteActive) {
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        void onSend();
        return;
      }
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        if (
          paletteOrderedCandidates.length > 0 &&
          paletteSelectedIndex >= 0 &&
          paletteSelectedIndex < paletteOrderedCandidates.length
        ) {
          handleSelectCandidateAndFocus(paletteOrderedCandidates[paletteSelectedIndex]);
        }
        return;
      }
      if (e.key === "ArrowDown") {
        e.preventDefault();
        if (paletteOrderedCandidates.length > 0) {
          onPaletteSelectedIndexChange((prev) => (prev + 1) % paletteOrderedCandidates.length);
        }
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        if (paletteOrderedCandidates.length > 0) {
          onPaletteSelectedIndexChange(
            (prev) => (prev - 1 + paletteOrderedCandidates.length) % paletteOrderedCandidates.length,
          );
        }
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        onDismissPalette();
        return;
      }    }

    if (shouldSendOnEnter(e, chatSendMode)) {
      e.preventDefault();
      void onSend();
    }
  };

  useEffect(() => {
    const el = chatInputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [inputText]);

  // Close the plus menu and template selector when clicking outside of them.
  // onClosePlusMenu is an inline prop; keep it in a ref so the listener is
  // not re-subscribed on every parent render while the menu is open.
  const onClosePlusMenuRef = useRef(onClosePlusMenu);
  onClosePlusMenuRef.current = onClosePlusMenu;
  useEffect(() => {
    if (!plusMenuOpen && !templateSelectorOpen) return;
    const onClick = (e: MouseEvent) => {
      if (!(e.target instanceof Node)) return;
      if (plusMenuRef.current && !plusMenuRef.current.contains(e.target)) {
        onClosePlusMenuRef.current();
      }
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [plusMenuOpen, templateSelectorOpen]);

  const inputPlaceholder = !selectedSessionId
    ? "左側の「＋ 新しい会話」をクリックして会話を開始してください"
    : getChatInputPlaceholder(chatSendMode);

  return (
    <form
      onSubmit={handleSendMessage}
      onDragEnter={onFormDragOver}
      onDragOver={onFormDragOver}
      onDragLeave={onFormDragLeave}
      onDrop={onFormDrop}
      className="border-t border-slate-200 bg-white p-3 flex flex-col gap-2 relative"
    >
      {isDragOver && (
        <div
          className="absolute inset-1 z-20 flex items-center justify-center rounded-lg border-2 border-dashed border-blue-600 bg-blue-600/10 pointer-events-none"
          data-testid="agent-drop-overlay"
        >
          <span className="rounded bg-blue-600 px-3 py-1 text-xs font-medium text-white">
            ここに画像をドロップ
          </span>
        </div>
      )}
      {pendingAttachments.length > 0 && (
        <div className="flex flex-wrap gap-2 border border-slate-200 rounded-lg p-2 bg-slate-50/50" aria-label="送信前の添付画像">
          {pendingAttachments.map((att, index) => (
            <div
              key={`${att.name}-${index}`}
              className="relative h-16 w-16 rounded border border-slate-300 overflow-hidden bg-white"
            >
              <img
                src={att.previewUrl}
                alt={att.name}
                className="h-full w-full object-cover"
              />
              <button
                type="button"
                onClick={() => onRemoveAttachment(index)}
                className="absolute top-0 right-0 inline-flex h-4 w-4 items-center justify-center rounded-bl bg-slate-900/80 text-[10px] text-white hover:bg-slate-900 cursor-pointer"
                aria-label={`${att.name} を取り除く`}
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          ))}
        </div>
      )}
      {/* Skill Chip directly above textarea */}
      {selectedSkill && (
        <div
          className="flex items-center gap-1.5 self-start rounded-full bg-slate-800 px-3 py-1 text-xs text-white shadow-sm"
          data-testid="skill-chip"
        >
          <span className="font-mono font-semibold">/{selectedSkill.name}</span>
          <button
            type="button"
            onClick={onClearSkill}
            className="ml-1 inline-flex h-4 w-4 items-center justify-center rounded-full hover:bg-slate-700 text-slate-300 hover:text-white cursor-pointer"
            aria-label="スキル選択を解除"
          >
            <X className="h-3 w-3" />
          </button>
        </div>
      )}

      {/* Command Palette directly above textarea */}
      {isPaletteActive && (
        <div
          data-testid="agent-command-palette"
          className="absolute bottom-full left-3 right-3 mb-2 max-h-64 overflow-y-auto rounded-lg border border-slate-200 bg-white shadow-lg z-20"
        >
          {filteredCandidates.length === 0 ? (
            <div className="p-3 text-center text-xs text-slate-400">
              該当する候補がありません
            </div>
          ) : (
            <div>
              {hasSkillsTool && skillCandidates.length > 0 && (
                <div>
                  <div className="bg-slate-50 px-3 py-1 text-[10px] font-semibold text-slate-500 uppercase tracking-wider border-b border-slate-100">
                    スキル
                  </div>
                  {skillCandidates.map((c) => {
                    const flatIndex = paletteOrderedCandidates.indexOf(c);
                    return (
                      <button
                        key={`skill-${c.name}`}
                        type="button"
                        onClick={() => handleSelectCandidateAndFocus(c)}
                        onMouseEnter={() => onPaletteSelectedIndexChange(flatIndex)}
                        className={`w-full text-left px-3 py-2 text-xs border-b border-slate-50 last:border-0 cursor-pointer ${
                          flatIndex === paletteSelectedIndex ? "bg-slate-100 font-medium" : "hover:bg-slate-50"
                        }`}
                      >
                        <div className="flex items-center gap-1.5 font-medium text-slate-800 truncate">
                          <span className="rounded bg-indigo-50 px-1 py-0.5 text-[10px] text-indigo-600 font-mono">/{c.name}</span>
                        </div>
                        <div className="text-[11px] text-slate-500 line-clamp-1 truncate">
                          {c.description}
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}
              {templateCandidates.length > 0 && (
                <div>
                  <div className="bg-slate-50 px-3 py-1 text-[10px] font-semibold text-slate-500 uppercase tracking-wider border-b border-slate-100">
                    テンプレート
                  </div>
                  {templateCandidates.map((c) => {
                    const flatIndex = paletteOrderedCandidates.indexOf(c);
                    return (
                      <button
                        key={`template-${c.template_id || c.name}`}
                        type="button"
                        onClick={() => handleSelectCandidateAndFocus(c)}
                        onMouseEnter={() => onPaletteSelectedIndexChange(flatIndex)}
                        className={`w-full text-left px-3 py-2 text-xs border-b border-slate-50 last:border-0 cursor-pointer ${
                          flatIndex === paletteSelectedIndex ? "bg-slate-100 font-medium" : "hover:bg-slate-50"
                        }`}
                      >
                        <div className="font-medium text-slate-800 truncate">{c.name}</div>
                        <div className="text-[11px] text-slate-500 line-clamp-2 whitespace-pre-wrap break-words">
                          {c.description.length > 80 ? c.description.slice(0, 80) + "…" : c.description}
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </div>
      )}
      {/* Row 1: textarea */}
      <textarea
        ref={chatInputRef}
        rows={1}
        value={inputText}
        onChange={(e) => onInputTextChange(e.target.value)}
        onKeyDown={handleInputKeyDown}
        onPaste={onPaste}
        disabled={isStreaming || !selectedSessionId}
        placeholder={inputPlaceholder}
        className="w-full resize-none rounded-lg border border-slate-300 p-2 text-xs leading-relaxed focus:border-slate-500 focus:outline-none disabled:bg-slate-100 disabled:opacity-50 disabled:cursor-not-allowed"
      />
      {/* Row 2: tools + model + send */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <div ref={plusMenuRef} className="relative">
            <button
              type="button"
              disabled={!activeAgent || !selectedSessionId || isStreaming}
              onClick={onTogglePlusMenu}
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-slate-300 bg-white text-slate-700 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
              aria-label="追加メニュー"
            >
              <Plus className="h-4 w-4" />
            </button>
            {plusMenuOpen && (
              <div className="absolute bottom-full left-0 mb-2 w-48 rounded-lg border border-slate-200 bg-white shadow-lg z-10 overflow-hidden">
                <button
                  type="button"
                  disabled={promptTemplates.length === 0}
                  onClick={onOpenTemplateSelector}
                  className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  <FileText className="h-3.5 w-3.5 text-slate-500" />
                  テンプレート
                </button>
                <button
                  type="button"
                  disabled={
                    !activeAgent ||
                    !selectedSessionId ||
                    isStreaming ||
                    attachmentReadsPending > 0 ||
                    pendingAttachments.length >= MAX_AGENT_IMAGES
                  }
                  onClick={() => {
                    imageInputRef.current?.click();
                    onClosePlusMenu();
                  }}
                  className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  <ImageIcon className="h-3.5 w-3.5 text-slate-500" />
                  {attachmentReadsPending > 0 ? "読込中…" : "画像アップロード"}
                </button>
              </div>
            )}
            {templateSelectorOpen && promptTemplates.length > 0 && (
              <div
                data-testid="agent-template-selector"
                className="absolute bottom-full left-0 mb-2 w-72 max-h-64 overflow-y-auto rounded-lg border border-slate-200 bg-white shadow-lg z-10"
              >
                <div className="p-2 border-b border-slate-100 text-[11px] font-medium text-slate-500">
                  登録済みテンプレート（選択で入力を置き換え）
                </div>
                {promptTemplates.map((t) => (
                  <button
                    key={t.template_id}
                    type="button"
                    onClick={() => handleSelectTemplateAndFocus(t.content)}
                    className="w-full text-left px-3 py-2 text-xs hover:bg-slate-50 border-b border-slate-50 last:border-0"
                  >
                    <div className="font-medium text-slate-800 truncate">{t.name}</div>
                    <div className="text-[11px] text-slate-500 line-clamp-2 whitespace-pre-wrap break-words">
                      {t.content.length > 80 ? t.content.slice(0, 80) + "…" : t.content}
                    </div>
                  </button>
                ))}
              </div>
            )}
            <input
              ref={imageInputRef}
              type="file"
              accept="image/*"
              multiple
              data-testid="agent-image-input"
              className="hidden"
              onChange={(e) => {
                void onFilesSelected(e.target.files);
                e.target.value = "";
              }}
            />
          </div>
          {activeAgent && (
            <span className="text-[11px] text-slate-400 truncate max-w-[12rem]">
              {activeAgent.model || activeAgent.provider || "既定"}
            </span>
          )}
        </div>
        {isStreaming && (
          <button
            type="button"
            onClick={onCancelRun}
            className="inline-flex h-8 items-center rounded-lg bg-rose-600 px-3 text-xs font-medium text-white hover:bg-rose-700 cursor-pointer"
            aria-label="実行をキャンセル"
          >
            キャンセル
          </button>
        )}
        <button
          type="submit"
          disabled={
            isStreaming ||
            attachmentReadsPending > 0 ||
            (!inputText.trim() && pendingAttachments.length === 0 && !selectedSkill) ||
            !selectedSessionId
          }
          className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-slate-900 text-white hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
          aria-label="送信"
        >
          <SendHorizontal className="h-4 w-4" />
        </button>
      </div>
    </form>
  );
}
