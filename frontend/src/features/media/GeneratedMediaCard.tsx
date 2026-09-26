import { useEffect, useState } from "react";
import { getMediaBlob } from "../../api/client";
import type { GeneratedMediaRef } from "../../api/types";

interface GeneratedMediaCardProps {
  media: GeneratedMediaRef;
  alt?: string;
  className?: string;
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
}: GeneratedMediaCardProps) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let createdUrl: string | null = null;
    setObjectUrl(null);
    setError(null);
    getMediaBlob(media.media_id)
      .then((blob) => {
        if (cancelled) return;
        createdUrl = URL.createObjectURL(blob);
        setObjectUrl(createdUrl);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(
          err instanceof Error && err.message
            ? err.message
            : "メディアの読み込みに失敗しました",
        );
      });
    return () => {
      cancelled = true;
      if (createdUrl) URL.revokeObjectURL(createdUrl);
    };
  }, [media.media_id]);

  const handleDownload = () => {
    if (!objectUrl) return;
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = media.filename || `${media.media_id}`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  };

  const isImage =
    media.media_type === "image" || media.mime_type.startsWith("image/");

  function renderBody() {
    if (!isImage) {
      return (
        <div className="text-[11px] text-slate-500">{media.media_id}</div>
      );
    }
    if (!objectUrl) {
      return (
        <div className="flex h-24 w-40 items-center justify-center rounded border border-slate-200 bg-slate-50 text-[11px] text-slate-400">
          読み込み中…
        </div>
      );
    }
    return (
      <img
        src={objectUrl}
        onError={() => setError("メディアの読み込みに失敗しました")}
        alt={alt || media.filename || "生成画像"}
        className="max-h-80 max-w-full rounded border border-slate-200 object-contain"
      />
    );
  }

  return (
    <figure
      data-testid="generated-media-card"
      data-media-id={media.media_id}
      className={className}
    >
      {error ? (
        <div className="rounded border border-rose-200 bg-rose-50 px-2 py-1 text-[11px] text-rose-700">
          {error}
        </div>
      ) : (
        <>
          {renderBody()}
          <figcaption className="mt-1 flex flex-wrap items-center gap-2 text-[11px]">
            <button
              type="button"
              onClick={handleDownload}
              disabled={!objectUrl}
              className="cursor-pointer rounded bg-blue-600 px-2 py-0.5 text-xs text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              ダウンロード
            </button>
            {media.filename && (
              <span className="break-all text-slate-500">{media.filename}</span>
            )}
          </figcaption>
        </>
      )}
    </figure>
  );
}
