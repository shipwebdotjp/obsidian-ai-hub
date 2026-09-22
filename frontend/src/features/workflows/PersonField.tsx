import PersonCombobox from "../people/PersonCombobox";
import { loadPeople, useWidgetOptions } from "./widgetData";

export interface PersonFieldProps {
  value: string;
  onChange: (personId: string) => void;
  testIdPrefix: string;
}

/** Single person select reusing the shared PersonCombobox. */
export default function PersonField({
  value,
  onChange,
  testIdPrefix,
}: PersonFieldProps) {
  const { options: people, failed } = useWidgetOptions(loadPeople);

  return (
    <div data-testid={`${testIdPrefix}-person`} className="space-y-1">
      <PersonCombobox
        people={people}
        value={value}
        onChange={onChange}
        ariaLabel="対象人物"
        placeholder="-- 人物を選択 --"
      />
      {failed && (
        <p className="text-[10px] text-rose-700">
          人物一覧の取得に失敗しました
        </p>
      )}
    </div>
  );
}
