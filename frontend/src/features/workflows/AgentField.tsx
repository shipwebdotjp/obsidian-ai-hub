import { loadAgents, useWidgetOptions } from "./widgetData";

export interface AgentFieldProps {
  value: string;
  onChange: (agentId: string) => void;
  testIdPrefix: string;
}

/** Single Agent select for target-based capabilities. */
export default function AgentField({
  value,
  onChange,
  testIdPrefix,
}: AgentFieldProps) {
  const { options: agents, failed } = useWidgetOptions(loadAgents);

  return (
    <div className="space-y-1">
      <select
        data-testid={`${testIdPrefix}-agent`}
        className="w-full rounded border border-slate-300 px-2 py-1 text-xs"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">-- Agent を選択 --</option>
        {agents.map((agent) => (
          <option key={agent.agent_id} value={agent.agent_id}>
            {agent.name}
          </option>
        ))}
      </select>
      {failed && (
        <p className="text-[10px] text-rose-700">
          Agent 一覧の取得に失敗しました
        </p>
      )}
    </div>
  );
}
