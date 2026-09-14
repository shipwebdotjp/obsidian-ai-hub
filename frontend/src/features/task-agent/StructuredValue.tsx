/**
 * 未知の形状の値（オブジェクト・配列・プリミティブ・空値）を欠落なく
 * 表示するための構造化レンダラー。
 *
 * 方針:
 * - すべてのキー・要素・値を省略せずに描画する（未知フィールド対応）。
 * - 空値（null / undefined / 空文字 / 空配列 / 空オブジェクト）は
 *   「空であること」が分かる表示にする。
 * - 長文・深いネスト・狭幅でも崩れないよう折返しと min-w-0 を徹底する。
 * - 生 JSON 文字列（JSON.stringify の直接表示）はここでは扱わない。
 *   JSON 文字列の解釈は SmartText が担当する。
 */
export function tryParseJsonObjectOrArray(text: string): unknown | undefined {
  const trimmed = text.trim();
  if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) {
    return undefined;
  }
  try {
    const parsed: unknown = JSON.parse(trimmed);
    if (parsed !== null && typeof parsed === "object") {
      return parsed;
    }
    return undefined;
  } catch {
    return undefined;
  }
}

/**
 * 通常のテキストを表示する。内容全体が JSON オブジェクト／配列として
 * 解釈できる場合は構造化表示に切り替える（情報の欠落なし）。
 */
export function SmartText({
  text,
  className,
}: {
  text: string;
  className?: string;
}) {
  const parsed = tryParseJsonObjectOrArray(text);
  if (parsed !== undefined) {
    return (
      <span className={className}>
        <StructuredValue value={parsed} />
      </span>
    );
  }
  return (
    <span
      className={`min-w-0 whitespace-pre-wrap break-words [overflow-wrap:anywhere]${className ? ` ${className}` : ""}`}
    >
      {text}
    </span>
  );
}

export function StructuredValue({
  value,
  depth = 0,
}: {
  value: unknown;
  depth?: number;
}) {
  if (value === undefined) {
    return <span className="text-slate-400">（未設定）</span>;
  }
  if (value === null) {
    return (
      <code className="rounded bg-slate-100 px-1 font-mono text-slate-500">
        null
      </code>
    );
  }
  if (typeof value === "string") {
    if (value === "") {
      return <span className="text-slate-400">（空文字）</span>;
    }
    return (
      <span className="min-w-0 whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
        {value}
      </span>
    );
  }
  if (
    typeof value === "number" ||
    typeof value === "boolean" ||
    typeof value === "bigint"
  ) {
    return (
      <code className="rounded bg-slate-100 px-1 font-mono text-slate-700">
        {String(value)}
      </code>
    );
  }
  if (Array.isArray(value)) {
    if (value.length === 0) {
      return <span className="text-slate-400">（空の配列）</span>;
    }
    return (
      <ol className="min-w-0 space-y-1">
        {value.map((item, index) => (
          // eslint-disable-next-line react/no-array-index-key
          <li key={`${depth}-${index}`} className="flex min-w-0 gap-2">
            <span
              aria-hidden="true"
              className="h-fit shrink-0 rounded bg-slate-100 px-1.5 font-mono text-slate-500"
            >
              {index}
            </span>
            <span className="min-w-0 flex-1">
              <StructuredValue value={item} depth={depth + 1} />
            </span>
          </li>
        ))}
      </ol>
    );
  }
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) {
      return <span className="text-slate-400">（空のオブジェクト）</span>;
    }
    return (
      <dl className="min-w-0 space-y-1.5">
        {entries.map(([fieldKey, fieldValue]) => (
          <div key={`${depth}-${fieldKey}`} className="min-w-0">
            <dt className="min-w-0">
              <code className="break-all rounded bg-slate-100 px-1 font-mono text-slate-600">
                {fieldKey}
              </code>
            </dt>
            <dd className="mt-0.5 min-w-0 pl-3">
              <StructuredValue value={fieldValue} depth={depth + 1} />
            </dd>
          </div>
        ))}
      </dl>
    );
  }
  return (
    <code className="rounded bg-slate-100 px-1 font-mono text-slate-700">
      {String(value)}
    </code>
  );
}
