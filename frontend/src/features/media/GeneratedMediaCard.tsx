import { useEffect, useState, type KeyboardEvent, type MouseEvent } from "react";
import { createPortal } from "react-dom";
import Modal from "../../components/Modal";
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
  /**
   * Clicking the image opens an enlarged lightbox. Disable where the parent
   * already handles clicks (e.g. the gallery grid opens its detail modal).
   */
  enlargeable?: boolean;
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
  enlargeable = true,
}: GeneratedMediaCardProps) {
  const { objectUrl, error: fetchError } = useMediaObjectUrl(media.media_id);
  const [decodeError, setDecodeError] = useState<string | null>(null);
  const [enlarged, setEnlarged] = useState(false);
  const dark = variant === "dark";

  useEffect(() => {
    setDecodeError(null);
    setEnlarged(false);
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

  // Opening the lightbox also wins over surrounding links/handlers so the
  // click never navigates away or opens a second overlay behind the modal.
  const openEnlarged = () => setEnlarged(true);
  const onImageClick = (e: MouseEvent<HTMLSpanElement>) => {
    e.stopPropagation();
    e.preventDefault();
    openEnlarged();
  };
  const onImageKeyDown = (e: KeyboardEvent<HTMLSpanElement>) => {
    if (e.key === "Enter" || e.key === " ") {
      e.stopPropagation();
      e.preventDefault();
      openEnlarged();
    }
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
    const image = (
      <img
        src={objectUrl}
        onError={() => setDecodeError("メディアの読み込みに失敗しました")}
        alt={alt || media.filename || "生成画像"}
        className={`max-h-80 max-w-full rounded border object-contain ${
          dark ? "border-slate-600" : "border-slate-200"
        }`}
      />
    );
    if (!enlargeable) return image;
    // A span (not a button) so the card stays valid inside a Markdown link.
    return (
      <span
        role="button"
        tabIndex={0}
        aria-label={`${alt || media.filename || "画像"}を拡大表示`}
        aria-haspopup="dialog"
        aria-expanded={enlarged}
        data-testid="generated-media-enlarge"
        onClick={onImageClick}
        onKeyDown={onImageKeyDown}
        className="inline-block cursor-zoom-in"
      >
        {image}
      </span>
    );
  }

  const errorClass = dark
    ? "rounded border border-rose-800 bg-rose-950 px-2 py-1 text-[11px] text-rose-300"
    : "rounded border border-rose-200 bg-rose-50 px-2 py-1 text-[11px] text-rose-700";
  const filenameClass = `break-all ${dark ? "text-slate-400" : "text-slate-500"}`;

  const RootTag = inline ? "span" : "figure";
  const CaptionTag = inline ? "span" : "figcaption";
  const StatusTag = inline ? "span" : "div";

  // Shared by the card caption and the lightbox caption so the download
  // action and caption text stay in sync.
  function renderCaptionActions(
    captionClassName: string,
    captionText?: string,
  ) {
    return (
      <>
        <button
          type="button"
          onClick={onDownloadClick}
          disabled={!objectUrl}
          className="cursor-pointer rounded bg-blue-600 px-2 py-0.5 text-xs text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          ダウンロード
        </button>
        {captionText && (
          <span className={captionClassName}>{captionText}</span>
        )}
      </>
    );
  }

  // Portaled to document.body so the dialog never nests inside the card's
  // inline `<span>` (or a Markdown link). The wrapper stops propagation so
  // overlay clicks cannot bubble through the React tree to card ancestors.
  const lightboxTitleId = `generated-media-lightbox-title-${media.media_id}`;
  const lightbox =
    enlarged && objectUrl
      ? createPortal(
          <div onClick={(e) => e.stopPropagation()}>
            <Modal
              onClose={() => setEnlarged(false)}
              labelledBy={lightboxTitleId}
              cardClassName="max-h-[90vh] max-w-[90vw] overflow-auto rounded-xl bg-slate-900 p-4 shadow-xl"
            >
              <h2 id={lightboxTitleId} className="sr-only">
                {media.filename || alt || "生成画像"}
              </h2>
              <img
                src={objectUrl}
                alt={alt || media.filename || "生成画像"}
                data-testid="generated-media-lightbox-image"
                className="mx-auto max-h-[75vh] w-auto max-w-full cursor-zoom-out rounded object-contain"
                onClick={() => setEnlarged(false)}
              />
              <div className="mt-2 flex flex-wrap items-center justify-center gap-2 text-[11px]">
                {renderCaptionActions(
                  "break-all text-slate-300",
                  media.filename || alt,
                )}
              </div>
            </Modal>
          </div>,
          document.body,
        )
      : null;

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
            {renderCaptionActions(filenameClass, media.filename)}
          </CaptionTag>
        </>
      )}
      {lightbox}
    </RootTag>
  );
}
