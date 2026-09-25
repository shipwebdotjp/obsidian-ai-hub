import { useEffect, useMemo, useRef, useState } from "react";
import { previewTextTemplate } from "../../api/client";
import { getApiErrorMessage } from "../../utils/error";

export interface TextTemplatePreviewState {
  rendered: string | null;
  errors: string[];
  pending: boolean;
}

const EMPTY: TextTemplatePreviewState = {
  rendered: null,
  errors: [],
  pending: false,
};

/**
 * Debounced ``text_template`` preview backed by the backend renderer.
 *
 * A sequence guard drops stale responses so a slow request cannot overwrite a
 * newer render.
 */
export function useTextTemplatePreview(
  template: string,
  values: Record<string, unknown>,
  options: { debounceMs?: number; enabled?: boolean } = {},
): TextTemplatePreviewState {
  const { debounceMs = 500, enabled = true } = options;
  const [state, setState] = useState<TextTemplatePreviewState>(EMPTY);
  const sequence = useRef(0);
  // Key on the serialized values so callers may pass inline objects without
  // re-triggering the effect on every render.
  const valuesKey = useMemo(() => JSON.stringify(values), [values]);

  useEffect(() => {
    if (!enabled) {
      // Invalidate any in-flight request so it cannot overwrite the reset.
      sequence.current += 1;
      setState(EMPTY);
      return;
    }
    const current = ++sequence.current;
    setState((prev) => ({ ...prev, pending: true }));
    const handle = window.setTimeout(() => {
      void (async () => {
        try {
          const res = await previewTextTemplate({ template, values });
          if (sequence.current !== current) return;
          setState({
            rendered: res.rendered,
            errors: res.errors,
            pending: false,
          });
        } catch (error: unknown) {
          if (sequence.current !== current) return;
          setState({
            rendered: null,
            errors: [getApiErrorMessage(error, "プレビューに失敗しました")],
            pending: false,
          });
        }
      })();
    }, debounceMs);
    return () => window.clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [template, valuesKey, debounceMs, enabled]);

  return state;
}
