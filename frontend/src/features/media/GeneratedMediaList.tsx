import { useMemo } from "react";
import { GeneratedMediaCard } from "./GeneratedMediaCard";
import { extractGeneratedMedia } from "./generatedMedia";

/**
 * Extracts media references from an arbitrary payload (string/object/array)
 * and renders one card each. Renders nothing when the payload has none, so it
 * can be dropped into any tool-result, event, or node-output view.
 */
export function GeneratedMediaList({
  value,
  className = "mt-2 flex flex-wrap gap-2",
}: {
  value: unknown;
  className?: string;
}) {
  const refs = useMemo(() => extractGeneratedMedia(value), [value]);
  if (refs.length === 0) return null;
  return (
    <div className={className} data-testid="generated-media-list">
      {refs.map((ref) => (
        <GeneratedMediaCard key={ref.media_id} media={ref} />
      ))}
    </div>
  );
}
