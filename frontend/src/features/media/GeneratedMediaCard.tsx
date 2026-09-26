import { useEffect, useState, type MouseEvent } from "react";
import { useMediaObjectUrl } from "./useMediaObjectUrl";
import type { GeneratedMediaRef } from "../../api/types";

interface GeneratedMediaCardProps {
  media: GeneratedMediaRef;
  alt?: string;
  className?: string;
  /**
   * Render with a `<span>` root instead of `<figure>` so the card can live
   * inside a Markdown `<p>` without invalid block-in-paragraph nesting.
   */
  inline?: boolean;
  variant?: "light" | "dark";
}

/**
 * Renders a generated media artifact. The Bearer token cannot ride on an
 * ``<img src>`` request, so the blob is fetched with the shared client and
 * displayed via an object URL that is revoked on unmount.
 */
export function GeneratedMediaCard({
  media,
  alt,
  className,
  inline = false,
  variant = "light",
}: GeneratedMediaCardProps) {
  const { objectUrl, error: fetchError } = useMediaObjectUrl(media.media_id);
  const [decodeError, setDecodeError] = useState<string | null>(null);
  const dark = variant === "dark";

  useEffect(() => {
    setDecodeError(null);
  }, [media.media_id]);

  const error = fetchError ?? decodeError;

  const handleDownload = () => {
    if (!objectUrl) return;
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = media.filename || `${media.media_id}`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  };

  // Stop propagation so a card nested in a link (e.g. a Markdown image link
  // `[![alt](...)](/...)`) does not trigger navigation on download.
  const onDownloadClick = (e: MouseEvent<HTMLButtonElement>) => {
    e.stopPropagation();
    e.preventDefault();
    handleDownload();
  };

  const isImage =
    media.media_type === "image" || media.mime_type.startsWith("image/");

  // Inline mode lives inside a Markdown `<p>`, so body elements must be
  // phrasing content (`<span>`); the standalone card uses block elements.
  function renderBody(asInline: boolean) {
    const BodyTag = asInline ? "span" : "div";
    if (!isImage) {
      return (
        <BodyTag className={`text-[11px] ${dark ? "text-slate-400" : "text-slate-500"}`}>{media.media_id}</BodyTag>
      );
    }
    if (!objectUrl) {
      return (
        <BodyTag
          className={`${asInline ? "inline-flex" : "flex"} h-24 w-40 items-center justify-center rounded border text-[11px] ${
            dark
              ? "border-slate-600 bg-slate-800 text-slate-400"
              : "border-slate-200 bg-slate-50 text-slate-400"
          }`}
        >
          読み込み中…
        </BodyTag>
      );
    }
    return (
      <img
        src={objectUrl}
        onError={() => setDecodeError("メディアの読み込みに失敗しました")}
        alt={alt || media.filename || "生成画像"}
        className={`max-h-80 max-w-full rounded border object-contain ${
          dark ? "border-slate-600" : "border-slate-200"
        }`}
      />
    );
  }

  const errorClass = dark
    ? "rounded border border-rose-800 bg-rose-950 px-2 py-1 text-[11px] text-rose-300"
    : "rounded border border-rose-200 bg-rose-50 px-2 py-1 text-[11px] text-rose-700";
  const filenameClass = `break-all ${dark ? "text-slate-400" : "text-slate-500"}`;

  const RootTag = inline ? "span" : "figure";
  const CaptionTag = inline ? "span" : "figcaption";
  const StatusTag = inline ? "span" : "div";

  return (
    <RootTag
      data-testid="generated-media-card"
      data-media-id={media.media_id}
      className={className}
    >
      {error ? (
        <StatusTag className={errorClass}>{error}</StatusTag>
      ) : (
        <>
          {renderBody(inline)}
          <CaptionTag className="mt-1 flex flex-wrap items-center gap-2 text-[11px]">
            <button
              type="button"
              onClick={onDownloadClick}
              disabled={!objectUrl}
              className="cursor-pointer rounded bg-blue-600 px-2 py-0.5 text-xs text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              ダウンロード
            </button>
            {media.filename && (
              <span className={filenameClass}>{media.filename}</span>
            )}
          </CaptionTag>
        </>
      )}
    </RootTag>
  );
}
