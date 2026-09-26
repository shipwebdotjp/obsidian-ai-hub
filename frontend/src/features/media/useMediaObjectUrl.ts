import { useEffect, useState } from "react";
import { getMediaBlob } from "../../api/client";

export interface MediaObjectUrlState {
  /** Revoked on unmount / media change. Null while loading or on failure. */
  objectUrl: string | null;
  error: string | null;
}

/**
 * Fetches an authenticated media artifact as a Blob and exposes it as an
 * object URL. The Bearer token cannot ride on an ``<img src>`` request, so
 * callers render this URL instead of the ``/api/v1/media/{id}`` path.
 */
export function useMediaObjectUrl(mediaId: string): MediaObjectUrlState {
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let createdUrl: string | null = null;
    setObjectUrl(null);
    setError(null);
    getMediaBlob(mediaId)
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
  }, [mediaId]);

  return { objectUrl, error };
}
