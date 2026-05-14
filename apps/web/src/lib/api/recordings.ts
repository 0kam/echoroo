/**
 * Recordings API client for TanStack Query.
 */

import type {
  RecordingDetail,
  RecordingUpdate,
  SpectrogramParams,
  PlaybackParams,
} from '$lib/types/data';
import { apiClient } from './client';

const API_BASE = '/api/v1';
const WEB_API_BASE = '/web-api/v1';

export interface ProjectRecordingItem {
  id: string;
  project_id: string;
  dataset_id: string;
  name: string;
  duration_seconds: number | null;
  samplerate: number;
  channels: number;
  datetime: string | null;
  datetime_parse_status: 'pending' | 'success' | 'failed';
  site_h3_index: string | null;
}

export interface ProjectRecordingListResponse {
  items: ProjectRecordingItem[];
  total: number;
  page: number;
  limit: number;
  pages: number;
}

export interface ListRecordingsParams {
  projectId: string;
  datasetId?: string;
  siteId?: string;
  page?: number;
  pageSize?: number;
  search?: string;
  datetimeFrom?: string;
  datetimeTo?: string;
  samplerate?: number;
  sortBy?: string;
  sortOrder?: string;
}

/**
 * Fetch recordings for a project.
 */
export async function listRecordings(
  params: ListRecordingsParams
): Promise<ProjectRecordingListResponse> {
  const searchParams = new URLSearchParams();
  if (params.datasetId) searchParams.append('dataset_id', params.datasetId);
  if (params.siteId) searchParams.append('site_id', params.siteId);
  if (params.page) searchParams.append('page', params.page.toString());
  if (params.pageSize) searchParams.append('limit', params.pageSize.toString());
  if (params.search) searchParams.append('search', params.search);
  if (params.datetimeFrom) searchParams.append('datetime_from', params.datetimeFrom);
  if (params.datetimeTo) searchParams.append('datetime_to', params.datetimeTo);
  if (params.samplerate) searchParams.append('samplerate', params.samplerate.toString());
  if (params.sortBy) searchParams.append('sort_by', params.sortBy);
  if (params.sortOrder) searchParams.append('sort_order', params.sortOrder);

  const query = searchParams.toString();
  const url = `${WEB_API_BASE}/projects/${params.projectId}/recordings${query ? `?${query}` : ''}`;
  const response = await apiClient.get<Omit<ProjectRecordingListResponse, 'pages'>>(url);
  const pageSize = response.limit;
  return {
    ...response,
    pages: pageSize > 0 ? Math.max(1, Math.ceil(response.total / pageSize)) : 1,
  };
}

/**
 * Fetch a single recording by ID.
 */
export async function getRecording(
  projectId: string,
  recordingId: string
): Promise<RecordingDetail> {
  return apiClient.get<RecordingDetail>(
    `${WEB_API_BASE}/projects/${projectId}/recordings/${recordingId}`
  );
}

/**
 * Update a recording.
 */
export async function updateRecording(
  projectId: string,
  recordingId: string,
  data: RecordingUpdate
): Promise<RecordingDetail> {
  return apiClient.patch<RecordingDetail>(
    `${API_BASE}/projects/${projectId}/recordings/${recordingId}`,
    data
  );
}

/**
 * Delete a recording.
 */
export async function deleteRecording(projectId: string, recordingId: string): Promise<void> {
  return apiClient.delete<void>(`${API_BASE}/projects/${projectId}/recordings/${recordingId}`);
}

/**
 * Get URL for playback with optional speed adjustment.
 */
export function getPlaybackUrl(
  projectId: string,
  recordingId: string,
  params?: PlaybackParams
): string {
  const url = new URL(
    `${WEB_API_BASE}/projects/${projectId}/recordings/${recordingId}/playback`,
    window.location.origin
  );
  if (params?.speed) url.searchParams.append('speed', params.speed.toString());
  if (params?.start !== undefined) url.searchParams.append('start', params.start.toString());
  if (params?.end !== undefined) url.searchParams.append('end', params.end.toString());
  return url.toString();
}

/**
 * Get URL for spectrogram image.
 */
export function getSpectrogramUrl(
  projectId: string,
  recordingId: string,
  params?: SpectrogramParams
): string {
  const url = new URL(
    `${WEB_API_BASE}/projects/${projectId}/recordings/${recordingId}/spectrogram`,
    window.location.origin
  );
  if (params?.start !== undefined) url.searchParams.append('start', params.start.toString());
  if (params?.end !== undefined) url.searchParams.append('end', params.end.toString());
  if (params?.n_fft) url.searchParams.append('n_fft', params.n_fft.toString());
  if (params?.hop_length) url.searchParams.append('hop_length', params.hop_length.toString());
  if (params?.freq_min !== undefined)
    url.searchParams.append('freq_min', params.freq_min.toString());
  if (params?.freq_max !== undefined)
    url.searchParams.append('freq_max', params.freq_max.toString());
  if (params?.colormap) url.searchParams.append('colormap', params.colormap);
  if (params?.pcen !== undefined) url.searchParams.append('pcen', params.pcen.toString());
  if (params?.channel !== undefined) url.searchParams.append('channel', params.channel.toString());
  if (params?.width) url.searchParams.append('width', params.width.toString());
  if (params?.height) url.searchParams.append('height', params.height.toString());
  return url.toString();
}

/**
 * Get URL for downloading the original audio file.
 */
export function getDownloadUrl(projectId: string, recordingId: string): string {
  return `${API_BASE}/projects/${projectId}/recordings/${recordingId}/download`;
}
