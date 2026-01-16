/**
 * TypeScript types for Data Management entities.
 * These types mirror the Pydantic schemas from the backend API.
 */

// ============================================
// Enums
// ============================================

export type DatasetVisibility = 'private' | 'public';

export type DatasetStatus = 'pending' | 'scanning' | 'processing' | 'completed' | 'failed';

export type DatetimeParseStatus = 'pending' | 'success' | 'failed';

// ============================================
// Site Types
// ============================================

export interface Site {
  id: string;
  project_id: string;
  name: string;
  h3_index: string;
  created_at: string;
  updated_at: string;
}

export interface SiteDetail extends Site {
  dataset_count: number;
  recording_count: number;
  total_duration: number;
  latitude: number | null;
  longitude: number | null;
  coordinate_uncertainty: number | null;
  boundary: number[][] | null;
}

export interface SiteCreate {
  name: string;
  h3_index: string;
}

export interface SiteUpdate {
  name?: string;
  h3_index?: string;
}

export interface SiteListResponse {
  items: Site[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

// ============================================
// H3 Types
// ============================================

export interface H3ValidationRequest {
  h3_index: string;
}

export interface H3ValidationResponse {
  valid: boolean;
  resolution: number | null;
  latitude: number | null;
  longitude: number | null;
  error: string | null;
}

export interface H3FromCoordinatesRequest {
  latitude: number;
  longitude: number;
  resolution: number;
}

export interface H3FromCoordinatesResponse {
  h3_index: string;
  resolution: number;
  latitude: number;
  longitude: number;
  boundary: number[][];
}

// ============================================
// Dataset Types
// ============================================

export interface RecorderSummary {
  id: string;
  manufacturer: string;
  recorder_name: string;
}

export interface LicenseSummary {
  id: string;
  name: string;
  short_name: string;
}

export interface UserSummary {
  id: string;
  username: string;
  display_name: string | null;
}

export interface SiteSummary {
  id: string;
  name: string;
  h3_index: string;
}

export interface Dataset {
  id: string;
  site_id: string;
  project_id: string;
  recorder_id: string | null;
  license_id: string | null;
  created_by_id: string;
  name: string;
  description: string | null;
  audio_dir: string;
  visibility: DatasetVisibility;
  status: DatasetStatus;
  doi: string | null;
  gain: number | null;
  note: string | null;
  total_files: number;
  processed_files: number;
  processing_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface DatasetDetail extends Dataset {
  site: SiteSummary | null;
  recorder: RecorderSummary | null;
  license: LicenseSummary | null;
  created_by: UserSummary | null;
  recording_count: number;
  total_duration: number;
  start_date: string | null;
  end_date: string | null;
}

export interface DatasetCreate {
  site_id: string;
  name: string;
  description?: string | null;
  audio_dir: string;
  visibility?: DatasetVisibility;
  recorder_id?: string | null;
  license_id?: string | null;
  doi?: string | null;
  gain?: number | null;
  note?: string | null;
  datetime_pattern?: string | null;
  datetime_format?: string | null;
}

export interface DatasetUpdate {
  name?: string;
  description?: string | null;
  visibility?: DatasetVisibility;
  recorder_id?: string | null;
  license_id?: string | null;
  doi?: string | null;
  gain?: number | null;
  note?: string | null;
  datetime_pattern?: string | null;
  datetime_format?: string | null;
}

export interface DatasetListResponse {
  items: Dataset[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface ImportRequest {
  datetime_pattern?: string | null;
  datetime_format?: string | null;
}

export interface ImportStatusResponse {
  status: DatasetStatus;
  total_files: number;
  processed_files: number;
  progress_percent: number;
  error: string | null;
}

export interface DateRangeStats {
  start: string;
  end: string;
}

export interface RecordingsByDate {
  date: string;
  count: number;
  duration: number;
}

export interface RecordingsByHour {
  hour: number;
  count: number;
}

export interface DatasetStatistics {
  recording_count: number;
  total_duration: number;
  date_range: DateRangeStats | null;
  samplerate_distribution: Record<number, number>;
  format_distribution: Record<string, number>;
  recordings_by_date: RecordingsByDate[];
  recordings_by_hour: RecordingsByHour[];
}

export interface DirectoryInfo {
  name: string;
  path: string;
  audio_file_count: number;
  formats: string[];
}

export interface DirectoryListResponse {
  path: string;
  directories: DirectoryInfo[];
}

export interface ExportRequest {
  include_audio?: boolean;
}

// ============================================
// Recording Types
// ============================================

export interface DatasetSummary {
  id: string;
  name: string;
}

export interface Recording {
  id: string;
  dataset_id: string;
  filename: string;
  path: string;
  hash: string;
  duration: number;
  samplerate: number;
  channels: number;
  bit_depth: number | null;
  datetime: string | null;
  datetime_parse_status: DatetimeParseStatus;
  datetime_parse_error: string | null;
  time_expansion: number;
  note: string | null;
  created_at: string;
  updated_at: string;
}

export interface RecordingDetail extends Recording {
  dataset: DatasetSummary | null;
  site: SiteSummary | null;
  clip_count: number;
  effective_duration: number;
  is_ultrasonic: boolean;
}

export interface RecordingUpdate {
  time_expansion?: number;
  note?: string | null;
}

export interface RecordingListResponse {
  items: Recording[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface SpectrogramParams {
  start?: number;
  end?: number;
  n_fft?: number;
  hop_length?: number;
  freq_min?: number;
  freq_max?: number;
  colormap?: string;
  pcen?: boolean;
  channel?: number;
  width?: number;
  height?: number;
}

export interface PlaybackParams {
  speed?: number;
  start?: number;
  end?: number;
}

// ============================================
// Clip Types
// ============================================

export interface RecordingSummaryForClip {
  id: string;
  filename: string;
  duration: number;
  samplerate: number;
  time_expansion: number;
}

export interface Clip {
  id: string;
  recording_id: string;
  start_time: number;
  end_time: number;
  note: string | null;
  created_at: string;
  updated_at: string;
}

export interface ClipDetail extends Clip {
  duration: number;
  recording: RecordingSummaryForClip | null;
}

export interface ClipCreate {
  start_time: number;
  end_time: number;
  note?: string | null;
}

export interface ClipUpdate {
  start_time?: number;
  end_time?: number;
  note?: string | null;
}

export interface ClipListResponse {
  items: Clip[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface ClipGenerateRequest {
  clip_length: number;
  overlap?: number;
  start_time?: number;
  end_time?: number;
}

export interface ClipGenerateResponse {
  clips_created: number;
  clips: Clip[];
}

// ============================================
// Query Parameter Types
// ============================================

export interface SiteListParams {
  page?: number;
  page_size?: number;
}

export interface DatasetListParams {
  page?: number;
  page_size?: number;
  site_id?: string;
  status?: DatasetStatus;
  visibility?: DatasetVisibility;
  search?: string;
}

export interface RecordingListParams {
  page?: number;
  page_size?: number;
  search?: string;
  datetime_from?: string;
  datetime_to?: string;
  samplerate?: number;
  sort_by?: 'datetime' | 'filename' | 'duration' | 'created_at';
  sort_order?: 'asc' | 'desc';
}

export interface RecordingSearchParams extends RecordingListParams {
  site_id?: string;
  dataset_id?: string;
  tags?: string[];
}

export interface ClipListParams {
  page?: number;
  page_size?: number;
  sort_by?: 'start_time' | 'created_at';
  sort_order?: 'asc' | 'desc';
}
