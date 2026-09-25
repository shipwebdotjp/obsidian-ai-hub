import { useEffect, useState } from "react";
import type { TextTemplatePreviewState } from "./useTextTemplatePreview";

export interface TextTemplatePreviewProps {
  preview: TextTemplatePreviewState;
  sampleValues: Record<string, unknown>;
  onChangeSampleValues: (values: Record<string, unknown>) => void;
  onGenerateScaffold: () => void;
  testIdPrefix?: string;
}

/**
 * Sample-value editor and rendered output for the ``text_template`` node.
 *
 * Sample values are editor-local (never persisted to the revision config); the
 * preview is produced by the backend renderer so it matches runtime semantics.
 */
export default function TextTemplatePreview({
  preview,
  sampleValues,
  onChangeSampleValues,
  onGenerateScaffold,
  testIdPrefix = "text-template",
}: TextTemplatePreviewProps) {
  const [text, setText] = useState(() => JSON.stringify(sampleValues, null, 2));
  const [parseError, setParseError] = useState<string | null>(null);

  useEffect(() => {
    setText((current) => {
      try {
        if (JSON.stringify(JSON.parse(current)) === JSON.stringify(sampleValues)) {
          return current;
        }
      } catch {
        // Keep resyncing when the current text is not comparable JSON.
      }
      return JSON.stringify(sampleValues, null, 2);
    });
    setParseError(null);
  }, [sampleValues]);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="block text-slate-700">サンプル値 (JSON)</span>
        <button
          type="button"
          data-testid={`${testIdPrefix}-sample-scaffold`}
          className="cursor-pointer rounded border border-slate-200 px-1 text-[10px] text-slate-600"
          onClick={onGenerateScaffold}
        >
          雛形を生成
        </button>
      </div>
      <textarea
        data-testid={`${testIdPrefix}-sample-values`}
        rows={5}
        className="w-full rounded border border-slate-300 px-2 py-1 font-mono text-[11px]"
        value={text}
        onChange={(event) => {
          const next = event.target.value;
          setText(next);
          try {
            const parsed = JSON.parse(next);
            if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
              setParseError("オブジェクトを指定してください");
              return;
            }
            setParseError(null);
            onChangeSampleValues(parsed as Record<string, unknown>);
          } catch {
            setParseError("JSON が不正です");
          }
        }}
      />
      {parseError && (
        <p className="text-[10px] text-rose-700">{parseError}</p>
      )}

      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <span className="text-slate-700">描画結果</span>
          {preview.pending && (
            <span className="text-[10px] text-slate-500">更新中…</span>
          )}
        </div>
        {preview.errors.length > 0 ? (
          <ul
            data-testid={`${testIdPrefix}-preview-errors`}
            className="space-y-0.5 text-[10px] leading-tight text-rose-700"
          >
            {preview.errors.map((error) => (
              <li key={error}>{error}</li>
            ))}
          </ul>
        ) : (
          <pre
            data-testid={`${testIdPrefix}-preview-output`}
            className="max-h-60 overflow-auto whitespace-pre-wrap rounded border border-slate-200 bg-slate-50 px-2 py-1 font-mono text-[11px] text-slate-800"
          >
            {preview.rendered ?? ""}
          </pre>
        )}
      </div>
    </div>
  );
}
