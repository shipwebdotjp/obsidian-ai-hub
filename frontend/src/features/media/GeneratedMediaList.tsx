import { useMemo } from "react";
import { GeneratedMediaCard } from "./GeneratedMediaCard";
import { extractGeneratedMedia } from "./generatedMedia";

/**
 * Extracts media references from an arbitrary payload (string/object/array)
 * and renders one card each. Renders nothing when the payload has none, so it
 * can be dropped into any tool-result, event, or node-output view.
 *
 * `excludeMediaIds` drops references already shown elsewhere (e.g. embedded
 * in the assistant's Markdown body) so the same artifact is not displayed
 * twice.
 */
export function GeneratedMediaList({
  value,
  className = "mt-2 flex flex-wrap gap-2",
  excludeMediaIds,
}: {
  value: unknown;
  className?: string;
  excludeMediaIds?: ReadonlySet<string>;
}) {
  const refs = useMemo(() => {
    const all = extractGeneratedMedia(value);
    if (!excludeMediaIds || excludeMediaIds.size === 0) return all;
    return all.filter((ref) => !excludeMediaIds.has(ref.media_id));
  }, [value, excludeMediaIds]);
  if (refs.length === 0) return null;
  return (
    <div className={className} data-testid="generated-media-list">
      {refs.map((ref) => (
        <GeneratedMediaCard key={ref.media_id} media={ref} />
      ))}
    </div>
  );
}
