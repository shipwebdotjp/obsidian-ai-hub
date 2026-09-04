import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Person } from "../../api/types";

export function formatPersonOptionLabel(person: Person): string {
  return `${person.display_name} ${person.vault_id ? `(${person.vault_id})` : "(未連携)"}`;
}

function personMatchesQuery(person: Person, query: string): boolean {
  const normalized = query.trim().toLowerCase();
  if (normalized.length === 0) return true;
  const haystacks: string[] = [
    person.display_name,
    person.normalized_name,
    person.vault_id ?? "",
    ...(person.aliases ?? []).flatMap((alias) => [alias.display_name, alias.normalized_name]),
  ];
  return haystacks.some((text) => text.toLowerCase().includes(normalized));
}

interface PersonComboboxProps {
  people: Person[];
  value: string;
  onChange: (personId: string) => void;
  disabled?: boolean;
  ariaLabel?: string;
  placeholder?: string;
}

/**
 * 一括解決先の人物を選択するための検索可能コンボボックス。
 * 依存追加なしで input フィルタ + listbox による絞り込み選択を提供する。
 * value/onChange は person_id 文字列（"" = 未選択）のまま維持し、
 * 送信データ・バリデーション側の変更を不要にしている。
 */
export default function PersonCombobox({
  people,
  value,
  onChange,
  disabled = false,
  ariaLabel = "一括解決先の人物",
  placeholder = "-- 解決先の人物を選択してください --",
}: PersonComboboxProps) {
  const selected = people.find((person) => person.person_id === value) ?? null;
  const selectedLabel = selected ? formatPersonOptionLabel(selected) : "";

  const [inputValue, setInputValue] = useState(selectedLabel);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listboxId = useId();

  // 親主導の value 変更（候補切替時のリセット等）を表示に反映する。
  // 入力操作中（フォーカス中）はクエリや確定直後のローカル表示を優先し、上書きしない。
  // 確定・クリア・blur・Escape 時の表示戻しは各ハンドラが明示的に行う。
  useEffect(() => {
    if (document.activeElement !== inputRef.current) {
      setInputValue(selectedLabel);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, people]);

  // 確定済みテキストと一致している間はフィルタを掛けず全件表示する。
  // （選択済みラベルが残っている状態でフォーカスしても他候補が消えないようにする）
  const isCommittedText = inputValue === selectedLabel;
  const filtered = useMemo(() => {
    if (!open || isCommittedText) return people;
    return people.filter((person) => personMatchesQuery(person, inputValue));
  }, [open, isCommittedText, people, inputValue]);

  useEffect(() => {
    setActiveIndex(0);
  }, [inputValue, open]);

  const clampedActiveIndex = filtered.length === 0 ? -1 : Math.min(Math.max(activeIndex, 0), filtered.length - 1);
  const activeId = clampedActiveIndex >= 0 ? `${listboxId}-option-${clampedActiveIndex}` : undefined;

  const commitSelection = (personId: string) => {
    const next = people.find((person) => person.person_id === personId) ?? null;
    onChange(personId);
    setInputValue(next ? formatPersonOptionLabel(next) : "");
    setOpen(false);
  };

  const handleClear = () => {
    onChange("");
    setInputValue("");
    setOpen(false);
    inputRef.current?.focus();
  };

  const handleBlur = (event: React.FocusEvent) => {
    if (containerRef.current?.contains(event.relatedTarget as Node | null)) return;
    setOpen(false);
    // 未確定の入力は破棄し、選択中ラベル（または空）に戻す
    setInputValue(selectedLabel);
  };

  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (disabled) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (!open) {
        setOpen(true);
      } else if (filtered.length > 0) {
        setActiveIndex((prev) => (prev + 1) % filtered.length);
      }
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) {
        setOpen(true);
      } else if (filtered.length > 0) {
        setActiveIndex((prev) => (prev - 1 + filtered.length) % filtered.length);
      }
    } else if (event.key === "Enter") {
      if (open && clampedActiveIndex >= 0 && filtered[clampedActiveIndex]) {
        event.preventDefault();
        commitSelection(filtered[clampedActiveIndex].person_id);
      }
    } else if (event.key === "Escape") {
      if (open) {
        event.preventDefault();
        setOpen(false);
        setInputValue(selectedLabel);
      }
    }
  };

  return (
    <div ref={containerRef} onBlur={handleBlur} className="relative w-full sm:flex-1">
      <div
        className={`flex w-full items-center rounded border border-slate-300 bg-white text-xs focus-within:border-slate-900 ${
          disabled ? "bg-slate-100 text-slate-400" : ""
        }`}
      >
        <input
          ref={inputRef}
          type="text"
          role="combobox"
          aria-label={ariaLabel}
          aria-expanded={open}
          aria-controls={listboxId}
          aria-activedescendant={open ? activeId : undefined}
          aria-autocomplete="list"
          value={inputValue}
          placeholder={placeholder}
          disabled={disabled}
          onFocus={() => {
            if (!disabled) setOpen(true);
          }}
          onChange={(event) => {
            setInputValue(event.target.value);
            if (!disabled) setOpen(true);
          }}
          onKeyDown={handleKeyDown}
          onClick={() => {
            if (!disabled) setOpen(true);
          }}
          className="w-full bg-transparent px-2.5 py-1.5 text-xs focus:outline-none disabled:text-slate-400 placeholder:text-slate-400"
        />
        {value !== "" && !disabled && (
          <button
            type="button"
            onClick={handleClear}
            aria-label="選択をクリア"
            className="shrink-0 cursor-pointer rounded px-1.5 py-1 text-sm leading-none text-slate-400 hover:text-slate-700"
          >
            ×
          </button>
        )}
        <button
          type="button"
          tabIndex={-1}
          aria-hidden="true"
          disabled={disabled}
          onClick={() => {
            if (disabled) return;
            setOpen((prev) => !prev);
            inputRef.current?.focus();
          }}
          className="shrink-0 cursor-pointer px-2 py-1 text-slate-400 hover:text-slate-700 disabled:cursor-not-allowed"
        >
          ▾
        </button>
      </div>
      {open && !disabled && (
        <ul
          id={listboxId}
          role="listbox"
          aria-label={ariaLabel}
          className="absolute z-10 mt-1 max-h-56 w-full overflow-y-auto rounded border border-slate-300 bg-white py-1 shadow-lg"
        >
          {filtered.length === 0 ? (
            <li aria-disabled="true" className="px-2.5 py-2 text-xs text-slate-400">
              一致する人物がありません
            </li>
          ) : (
            filtered.map((person, index) => {
              const isSelected = person.person_id === value;
              const isActive = index === clampedActiveIndex;
              return (
                <li
                  key={person.person_id}
                  id={`${listboxId}-option-${index}`}
                  role="option"
                  aria-selected={isSelected}
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => commitSelection(person.person_id)}
                  onMouseEnter={() => setActiveIndex(index)}
                  className={`cursor-pointer px-2.5 py-1.5 text-xs ${
                    isActive ? "bg-slate-100" : "bg-white"
                  } ${isSelected ? "font-semibold text-slate-900" : "text-slate-700"}`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span>
                      {person.display_name}{" "}
                      <span className="text-slate-400">{person.vault_id ? `(${person.vault_id})` : "(未連携)"}</span>
                    </span>
                    {isSelected && <span aria-hidden="true">✓</span>}
                  </div>
                  {person.aliases && person.aliases.length > 0 && (
                    <div className="mt-0.5 text-[10px] text-slate-400">
                      別名: {person.aliases.map((alias) => alias.display_name).join(", ")}
                    </div>
                  )}
                </li>
              );
            })
          )}
        </ul>
      )}
    </div>
  );
}
