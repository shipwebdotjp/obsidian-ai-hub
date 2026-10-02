import { apiGet, apiPost, apiPut, apiDelete, getToken, withQuery } from "../../api/client";
import type {
  EventType,
  PropertyDefinition,
  RecurringEventSeries,
  MediaRef,
} from "./types";

// --- Event Types ---

export function listEventTypes(): Promise<EventType[]> {
  return apiGet<EventType[]>("/api/v1/recurring-event-types");
}

export function createEventType(data: {
  name: string;
  properties?: PropertyDefinition[];
}): Promise<EventType> {
  return apiPost<EventType>("/api/v1/recurring-event-types", data);
}

export function updateEventType(
  typeId: string,
  data: {
    name?: string;
    properties?: PropertyDefinition[];
  },
): Promise<EventType> {
  return apiPut<EventType>(`/api/v1/recurring-event-types/${encodeURIComponent(typeId)}`, data);
}

export function deleteEventType(typeId: string): Promise<void> {
  return apiDelete<void>(`/api/v1/recurring-event-types/${encodeURIComponent(typeId)}`);
}

// --- Series ---

export function listSeries(): Promise<RecurringEventSeries[]> {
  return apiGet<RecurringEventSeries[]>("/api/v1/recurring-event-series");
}

export function getSeries(seriesId: string): Promise<RecurringEventSeries> {
  return apiGet<RecurringEventSeries>(`/api/v1/recurring-event-series/${encodeURIComponent(seriesId)}`);
}

export function createSeries(data: {
  type_id: string;
  interval_value: number;
  interval_unit: string;
  property_values: Record<string, unknown>;
  executed_on: string;
  note?: string | null;
  media_id?: string | null;
  count_contribution?: number | null;
}): Promise<RecurringEventSeries> {
  return apiPost<RecurringEventSeries>("/api/v1/recurring-event-series", data);
}

export function updateSeriesInterval(
  seriesId: string,
  data: {
    interval_value: number;
    interval_unit: string;
  },
): Promise<RecurringEventSeries> {
  return apiPut<RecurringEventSeries>(
    `/api/v1/recurring-event-series/${encodeURIComponent(seriesId)}/interval`,
    data,
  );
}

// --- Execution Records ---

export function addExecutionRecord(
  seriesId: string,
  data: {
    executed_on: string;
    note?: string | null;
    media_id?: string | null;
  },
): Promise<RecurringEventSeries> {
  return apiPost<RecurringEventSeries>(
    `/api/v1/recurring-event-series/${encodeURIComponent(seriesId)}/records`,
    data,
  );
}

export function updateExecutionRecord(
  recordId: string,
  data: {
    executed_on?: string;
    note?: string | null;
    media_id?: string | null;
    clear_media?: boolean;
    count_contribution?: number | null;
  },
): Promise<RecurringEventSeries> {
  return apiPut<RecurringEventSeries>(
    `/api/v1/recurring-event-records/${encodeURIComponent(recordId)}`,
    data,
  );
}

export function deleteExecutionRecord(
  recordId: string,
): Promise<{ success: boolean; series_id: string | null; series_deleted: boolean }> {
  return apiDelete<{ success: boolean; series_id: string | null; series_deleted: boolean }>(
    `/api/v1/recurring-event-records/${encodeURIComponent(recordId)}`,
  );
}

// --- Image Upload ---

export async function uploadMedia(file: File): Promise<MediaRef> {
  const formData = new FormData();
  formData.append("file", file);
  const token = getToken();
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch("/api/v1/media/upload", {
    method: "POST",
    headers,
    body: formData,
  });

  if (!res.ok) {
    let errDetail = res.statusText;
    try {
      const b = await res.json();
      if (b && b.detail) errDetail = b.detail;
    } catch (_) {}
    throw new Error(errDetail);
  }

  return (await res.json()) as MediaRef;
}
