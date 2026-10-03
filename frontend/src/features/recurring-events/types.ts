export type PropertyDataType = "text" | "number" | "select";
export type IntervalUnit = "day" | "week" | "month";

export interface PropertyOption {
  option_id?: string;
  option_key: string;
  display_name: string;
  display_order?: number;
}

export interface PropertyDefinition {
  property_id?: string;
  key: string;
  display_name: string;
  data_type: PropertyDataType;
  options?: PropertyOption[];
}

export interface EventType {
  type_id: string;
  name: string;
  properties: PropertyDefinition[];
  series_count: number;
  created_at: string;
  updated_at: string;
}

export interface MediaRef {
  media_type: string;
  media_id: string;
  url: string;
  download_url: string;
  mime_type: string;
  filename: string;
}

export interface SeriesPropertyItem {
  property_id: string;
  key: string;
  display_name: string;
  data_type: PropertyDataType;
  value: unknown;
  value_display: string;
}

export interface ExecutionRecord {
  record_id: string;
  series_id: string;
  executed_on: string;
  note: string | null;
  media_id: string | null;
  media: MediaRef | null;
  count_contribution: number;
  is_start_record: boolean;
  created_at: string;
  updated_at: string;
}

export interface RecurringEventSeries {
  series_id: string;
  type_id: string;
  type_name: string;
  interval_value: number;
  interval_unit: IntervalUnit;
  properties: SeriesPropertyItem[];
  properties_dict: Record<string, unknown>;
  latest_executed_on: string | null;
  next_due_date: string | null;
  elapsed_days: number | null;
  total_count: number;
  latest_photo_thumbnail: MediaRef | null;
  latest_note: string | null;
  records: ExecutionRecord[];
  created_at: string;
  updated_at: string;
}
